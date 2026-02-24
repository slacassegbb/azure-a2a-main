"""
AI Foundry PowerPoint Agent with presentation creation capabilities.
Uses the Responses API with native MCP tool support to interact with a
remote PowerPoint MCP server.  After the LLM finishes building slides it
calls download_presentation, and this agent fetches the resulting .pptx,
uploads it to Azure Blob Storage, and exposes it as an A2A artifact.
"""
import os
import time
import datetime
import asyncio
import logging
import json
import uuid
import tempfile
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import timedelta

import httpx
from openai import AsyncAzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.core.credentials import AzureNamedKeyCredential, AzureSasCredential

logger = logging.getLogger(__name__)

POWERPOINT_MCP_URL = os.getenv(
    "POWERPOINT_MCP_URL",
    "https://mcp-powerpoint.ambitioussky-6c709152.westus2.azurecontainerapps.io/mcp",
)

# Base URL of the MCP server (for downloading generated files)
_MCP_BASE_URL = POWERPOINT_MCP_URL.rsplit("/mcp", 1)[0]


class FoundryPowerPointAgent:
    """AI Foundry Agent with PowerPoint capabilities via Responses API."""

    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self._client: Optional[AsyncAzureOpenAI] = None
        self._initialized = False
        self._response_ids: Dict[str, str] = {}
        self.last_token_usage: Optional[Dict[str, int]] = None
        self._latest_artifacts: List[Dict[str, Any]] = []
        self._blob_service_client: Optional[BlobServiceClient] = None
        self._current_context_id: Optional[str] = None
        self._mcp_tool_config = {
            "type": "mcp",
            "server_label": "PowerPoint",
            "server_url": POWERPOINT_MCP_URL,
            "require_approval": "never",
            "allowed_tools": [
                "create_presentation",
                "create_presentation_from_template",
                "open_presentation",
                "save_presentation",
                "download_presentation",
                "get_presentation_info",
                "get_template_file_info",
                "set_core_properties",
                "add_slide",
                "get_slide_info",
                "extract_slide_text",
                "extract_presentation_text",
                "populate_placeholder",
                "add_bullet_points",
                "manage_text",
                "manage_image",
                "list_slide_templates",
                "apply_slide_template",
                "create_slide_from_template",
                "create_presentation_from_templates",
                "get_template_info",
                "auto_generate_presentation",
                "optimize_slide_text",
                "add_table",
                "format_table_cell",
                "add_shape",
                "add_chart",
                "apply_professional_design",
                "apply_picture_effects",
                "manage_fonts",
                "manage_hyperlinks",
                "manage_slide_masters",
                "add_connector",
                "update_chart_data",
                "manage_slide_transitions",
                "list_presentations",
                "switch_presentation",
                "get_server_info",
                "build_presentation",
            ],
            "headers": {
                "Content-Type": "application/json",
                "User-Agent": "Azure-AI-Foundry-Agent",
                "Accept": "application/json, text/event-stream",
            },
        }

    # ------------------------------------------------------------------
    # Azure Blob Storage helpers (adapted from image generator agent)
    # ------------------------------------------------------------------

    def _get_blob_service_client(self) -> Optional[BlobServiceClient]:
        force_blob = os.getenv("FORCE_AZURE_BLOB", "false").lower() == "true"
        if not force_blob:
            return None
        if self._blob_service_client is not None:
            return self._blob_service_client
        connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            logger.error("AZURE_STORAGE_CONNECTION_STRING must be set when FORCE_AZURE_BLOB=true")
            raise RuntimeError("Missing AZURE_STORAGE_CONNECTION_STRING for blob uploads")
        try:
            self._blob_service_client = BlobServiceClient.from_connection_string(
                connection_string, api_version="2023-11-03",
            )
            return self._blob_service_client
        except Exception as e:
            logger.error(f"Failed to create BlobServiceClient: {e}")
            raise

    def _upload_to_blob(self, file_path: Path) -> Optional[str]:
        """Upload *file_path* to Azure Blob Storage and return a SAS URL."""
        blob_client = self._get_blob_service_client()
        if not blob_client:
            return None

        container_name = os.getenv("AZURE_BLOB_CONTAINER", "a2a-files")

        file_id = uuid.uuid4().hex
        context_id = self._current_context_id
        if context_id and "::" in context_id:
            session_id = context_id.split("::")[0]
        elif context_id:
            session_id = context_id
        else:
            session_id = "unknown"

        blob_name = f"uploads/{session_id}/{file_id}/{file_path.name}"

        try:
            container_client = blob_client.get_container_client(container_name)
            if not container_client.exists():
                container_client.create_container()
            with open(file_path, "rb") as data:
                container_client.upload_blob(name=blob_name, data=data, overwrite=True)

            sas_duration_minutes = int(os.getenv("AZURE_BLOB_SAS_DURATION_MINUTES", str(24 * 60)))
            sas_token: Optional[str] = None
            service_client = self._blob_service_client

            if service_client is not None:
                credential = getattr(service_client, "credential", None)
                account_key_value: Optional[str] = None

                if isinstance(credential, AzureNamedKeyCredential):
                    account_key_value = credential.key
                elif isinstance(credential, AzureSasCredential):
                    sas_token = credential.signature.lstrip("?")
                elif hasattr(credential, "account_key"):
                    account_key_value = getattr(credential, "account_key")
                elif hasattr(credential, "key"):
                    account_key_value = getattr(credential, "key")

                if callable(account_key_value):
                    account_key_value = account_key_value()
                if isinstance(account_key_value, bytes):
                    account_key_value = account_key_value.decode()

                if account_key_value:
                    try:
                        sas_token = generate_blob_sas(
                            account_name=service_client.account_name,
                            container_name=container_name,
                            blob_name=blob_name,
                            account_key=account_key_value,
                            permission=BlobSasPermissions(read=True),
                            expiry=datetime.datetime.utcnow() + timedelta(minutes=sas_duration_minutes),
                            protocol="https",
                            version="2023-11-03",
                        )
                    except Exception as sas_error:
                        logger.error(f"Failed to generate SAS URL with shared key: {sas_error}")

            if sas_token is None and self._blob_service_client is not None:
                try:
                    delegation_key = self._blob_service_client.get_user_delegation_key(
                        key_start_time=datetime.datetime.utcnow() - timedelta(minutes=5),
                        key_expiry_time=datetime.datetime.utcnow() + timedelta(minutes=sas_duration_minutes),
                    )
                    sas_token = generate_blob_sas(
                        account_name=self._blob_service_client.account_name,
                        container_name=container_name,
                        blob_name=blob_name,
                        user_delegation_key=delegation_key,
                        permission=BlobSasPermissions(read=True),
                        expiry=datetime.datetime.utcnow() + timedelta(minutes=sas_duration_minutes),
                        version="2023-11-03",
                    )
                except Exception as ude_err:
                    logger.warning(f"Failed to generate user delegation SAS: {ude_err}")

            if sas_token:
                base_url = blob_client.get_blob_client(container=container_name, blob=blob_name).url
                token = sas_token.lstrip("?")
                separator = "&" if "?" in base_url else "?"
                return f"{base_url}{separator}{token}"

            raise RuntimeError("Unable to generate SAS token; verify storage credentials")
        except Exception as e:
            logger.error(f"Failed to upload {file_path} to blob storage: {e}")
            return None

    def pop_latest_artifacts(self) -> List[Dict[str, Any]]:
        artifacts = self._latest_artifacts
        self._latest_artifacts = []
        return artifacts

    # ------------------------------------------------------------------
    # Presentation download helper
    # ------------------------------------------------------------------

    async def _download_presentation_file(self, download_path: str, filename: str) -> Optional[Path]:
        """Download a .pptx from the MCP server and return the local Path."""
        url = f"{_MCP_BASE_URL}{download_path}"
        logger.info(f"Downloading presentation from {url}")
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                tmp_dir = Path(tempfile.gettempdir()) / "pptx_agent"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                local_path = tmp_dir / filename
                local_path.write_bytes(resp.content)
                logger.info(f"Saved presentation to {local_path} ({len(resp.content)} bytes)")
                return local_path
        except Exception as e:
            logger.error(f"Failed to download presentation: {e}")
            return None

    # ------------------------------------------------------------------
    # OpenAI / Azure client
    # ------------------------------------------------------------------

    def _get_client(self) -> AsyncAzureOpenAI:
        if self._client is None:
            if "services.ai.azure.com" in self.endpoint:
                resource_name = self.endpoint.split("//")[1].split(".")[0]
                openai_endpoint = f"https://{resource_name}.openai.azure.com/openai/v1/"
            else:
                openai_endpoint = (
                    self.endpoint
                    if self.endpoint.endswith("/openai/v1/")
                    else f"{self.endpoint.rstrip('/')}/openai/v1/"
                )
            token_provider = get_bearer_token_provider(
                self.credential, "https://cognitiveservices.azure.com/.default",
            )
            self._client = AsyncAzureOpenAI(
                base_url=openai_endpoint,
                azure_ad_token_provider=token_provider,
                api_version="preview",
            )
        return self._client

    async def create_agent(self) -> None:
        if self._initialized:
            return
        logger.info("Initializing PowerPoint agent (Responses API)...")
        try:
            base_url = _MCP_BASE_URL
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{base_url}/health")
                logger.info(f"MCP Server status: {response.status_code}")
        except Exception as e:
            logger.warning(f"MCP Server health check failed: {e} (continuing anyway)")
        self._get_client()
        self._initialized = True

    def _get_agent_instructions(self) -> str:
        return f"""You are a professional PowerPoint presentation creator.
You have access to a comprehensive set of PowerPoint MCP tools that let you create,
design, and export professional presentations.

## Creating New Presentations — ALWAYS use build_presentation

When creating a new presentation, you MUST use `build_presentation` which creates
the entire presentation in a single tool call.  Do NOT call `create_presentation` +
`add_slide` + `manage_text` etc. individually — this will fail due to platform
tool-call limits.

Example — create a business presentation:
```json
build_presentation(
  filename="Q4_Results.pptx",
  title="Q4 Results",
  author="Business Team",
  color_scheme="modern_blue",
  slides=[
    {{"type": "title", "title": "Q4 Business Results", "subtitle": "Annual Review 2025"}},
    {{"type": "content", "title": "Key Highlights", "bullets": ["Revenue up 15%", "New market expansion", "Customer satisfaction at 92%"]}},
    {{"type": "table", "title": "Financial Summary", "headers": ["Metric", "Q3", "Q4", "Change"], "rows": [["Revenue", "$2.1M", "$2.4M", "+15%"], ["Profit", "$400K", "$520K", "+30%"]]}},
    {{"type": "two_column", "title": "Strengths & Opportunities", "left": ["Strong brand", "Loyal customers", "Efficient ops"], "right": ["New markets", "Product expansion", "Partnerships"]}},
    {{"type": "chart", "title": "Revenue Trend", "chart_type": "column", "categories": ["Q1", "Q2", "Q3", "Q4"], "series": [{{"name": "Revenue", "values": [1800000, 1950000, 2100000, 2400000]}}]}}
  ]
)
```

IMPORTANT: Call `build_presentation` as a tool call directly. Do NOT output the
JSON as text in your response — that does not execute the tool. You must invoke
the tool so the file is actually created.

`build_presentation` automatically saves the file and returns a `download_url` —
you do NOT need to call `download_presentation` after it.

Supported slide types:
- `title` — title slide with title and subtitle
- `content` — title + bullet points
- `two_column` — title + left/right bullet columns
- `table` — title + data table (headers + rows)
- `chart` — title + chart (column, bar, line, pie, doughnut, area)
- `image` — title + image (from url or file path)
- `blank` — empty slide

## Editing / Reading Existing Presentations

For reading or editing existing presentations, use the individual tools.

## Important Rules

- Keep text concise and use bullet points for readability.
- If the user provides specific content, use it verbatim; otherwise generate
  appropriate content for the topic.
- Prefer action over asking. If the request is clear enough to produce a
  reasonable presentation, make assumptions and produce it immediately rather
  than asking for details. Only use NEEDS_INPUT when genuinely critical
  information is missing and cannot be reasonably assumed.

## Adding Images from URLs

When a previous workflow step provides an image URL (e.g. from Azure Blob Storage),
use `manage_image` with `source_type: "url"` and pass the full URL as `image_source`.
Example: manage_image(slide_index=0, operation="add", image_source="https://...blob.core.windows.net/...", source_type="url")

## Reading Existing Presentations

When the user asks you to read, summarize, or extract content from an existing presentation,
use `open_presentation` with the URL — do NOT create a new presentation.

- `open_presentation(file_path="https://...blob.core.windows.net/...pptx?sv=...")` — open and read slides

Pass the full URL (including any query parameters like SAS tokens) as the `file_path` argument.
After opening, use `get_slide_content` or similar tools to extract slide text.
Do NOT call `create_presentation` or `save_presentation` when only reading.

## Editing Existing Presentations from URLs

When the user asks you to edit/modify an existing presentation from a URL:

1. Call `open_presentation(file_path="https://...blob.core.windows.net/...pptx?sv=...")` — this downloads and opens it
2. Use edit tools: `manage_text`, `add_slide`, `manage_image`, `add_bullet_points`, etc.
3. Call `save_presentation` or `download_presentation` to return the modified file

`open_presentation` supports URLs directly — no extra download step needed.

## Available Design Themes
- **modern_blue** - Clean Microsoft-inspired blue theme
- **corporate_gray** - Professional grayscale with blue accents
- **elegant_green** - Forest green with cream accents
- **warm_red** - Deep red with orange/yellow accents

Current date: {datetime.datetime.now().isoformat()}

## Error Reporting (CRITICAL)

If you CANNOT complete the requested task — due to rate limits, API errors, missing data,
authentication failures, or any other reason — you MUST start your response with "Error:".

Examples:
- "Error: Rate limit exceeded. Please try again later."
- "Error: Authentication failed — invalid credentials."
- "Error: Could not complete the request due to a service outage."

Do NOT write a polite explanation without the "Error:" prefix. The system uses this prefix
to detect failures. Without it, the task is marked as successful even though it failed.

## NEEDS_INPUT - Human-in-the-Loop

Use NEEDS_INPUT to pause and ask the user a question:

```NEEDS_INPUT
Your question here
```END_NEEDS_INPUT
"""

    async def create_session(self) -> str:
        return f"session_{int(time.time())}_{os.urandom(4).hex()}"

    async def run_conversation_stream(self, session_id: str, user_message: str, context_id: Optional[str] = None):
        if not self._initialized:
            await self.create_agent()

        if context_id:
            self._current_context_id = context_id

        client = self._get_client()
        model = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")

        kwargs = {
            "model": model,
            "instructions": self._get_agent_instructions(),
            "input": [{"role": "user", "content": user_message}],
            "tools": [self._mcp_tool_config],
            "stream": True,
            "max_output_tokens": 16000,
        }
        if session_id in self._response_ids:
            kwargs["previous_response_id"] = self._response_ids[session_id]

        retry_count = 0
        max_retries = 3
        while retry_count <= max_retries:
            try:
                response = await client.responses.create(**kwargs)
                text_chunks: List[str] = []
                tool_calls_seen: set = set()
                mcp_failures: List[str] = []
                download_info: Optional[Dict[str, Any]] = None

                logger.info("Stream started — iterating events...")
                async for event in response:
                    event_type = getattr(event, "type", None)
                    # Log every event type for debugging
                    if event_type != "response.output_text.delta":
                        logger.info(f"[STREAM] event_type={event_type}")

                    if event_type == "response.output_text.delta":
                        text_chunks.append(event.delta)

                    elif event_type == "response.mcp_call.in_progress":
                        tool_name = getattr(event, "name", "mcp_tool")
                        if tool_name not in tool_calls_seen:
                            tool_calls_seen.add(tool_name)
                            yield f"\U0001f6e0\ufe0f Remote agent executing: {self._get_tool_description(tool_name)}"

                    elif event_type == "response.mcp_call.completed":
                        # Try to capture download_presentation or build_presentation result
                        item = getattr(event, "item", None) or event
                        tool_name = getattr(item, "name", None) or getattr(event, "name", None)
                        if tool_name in ("download_presentation", "build_presentation"):
                            output = getattr(item, "output", None) or getattr(event, "output", None)
                            if output:
                                try:
                                    data = json.loads(output) if isinstance(output, str) else output
                                    if isinstance(data, dict) and data.get("download_url"):
                                        download_info = data
                                        logger.info(f"Captured {tool_name} result: {data}")
                                except (json.JSONDecodeError, TypeError):
                                    pass

                    elif event_type == "response.mcp_call.failed":
                        tool_name = getattr(event, "name", None) or getattr(event, "item_id", "mcp_tool")
                        mcp_failures.append(tool_name)

                    elif event_type == "response.failed":
                        resp = getattr(event, "response", None)
                        error_obj = getattr(resp, "error", None) if resp else None
                        yield f"Error: {getattr(error_obj, 'message', 'Unknown error') if error_obj else 'Unknown error'}"
                        return

                    elif event_type == "response.output_item.added":
                        item = getattr(event, "item", None)
                        if item and getattr(item, "type", None) in ("mcp_call", "mcp_tool_call"):
                            tool_name = getattr(item, "name", None) or getattr(item, "tool_name", "mcp_tool")
                            if tool_name not in tool_calls_seen:
                                tool_calls_seen.add(tool_name)
                                yield f"\U0001f6e0\ufe0f Remote agent executing: {self._get_tool_description(tool_name)}"

                    elif event_type in ("response.completed", "response.done"):
                        resp = getattr(event, "response", None)
                        if resp:
                            usage = getattr(resp, "usage", None)
                            if usage:
                                self.last_token_usage = {
                                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) or getattr(usage, "input_tokens", 0),
                                    "completion_tokens": getattr(usage, "completion_tokens", 0) or getattr(usage, "output_tokens", 0),
                                    "total_tokens": getattr(usage, "total_tokens", 0),
                                }
                            resp_id = getattr(resp, "id", None)
                            if resp_id:
                                self._response_ids[session_id] = resp_id

                            # Fallback: scan response output items for download_presentation/build_presentation result
                            if download_info is None:
                                output_items = getattr(resp, "output", None) or []
                                for out_item in output_items:
                                    item_type = getattr(out_item, "type", None)
                                    if item_type in ("mcp_call", "mcp_tool_call"):
                                        name = getattr(out_item, "name", None)
                                        if name in ("download_presentation", "build_presentation"):
                                            raw = getattr(out_item, "output", None)
                                            if raw:
                                                try:
                                                    data = json.loads(raw) if isinstance(raw, str) else raw
                                                    if isinstance(data, dict) and data.get("download_url"):
                                                        download_info = data
                                                        logger.info(f"Captured download info from response output: {data}")
                                                except (json.JSONDecodeError, TypeError):
                                                    pass

                # ---- Post-stream: handle file download + blob upload ----
                logger.info(f"Stream finished. text_chunks={len(text_chunks)}, tools_seen={tool_calls_seen}, download_info={download_info}, mcp_failures={mcp_failures}")
                if download_info and download_info.get("download_url"):
                    filename = download_info.get("filename", "presentation.pptx")
                    local_path = await self._download_presentation_file(
                        download_info["download_url"], filename
                    )
                    if local_path and local_path.exists():
                        blob_url = self._upload_to_blob(local_path)
                        if blob_url:
                            artifact: Dict[str, Any] = {
                                "artifact-uri": blob_url,
                                "file-name": filename,
                                "mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                                "storage-type": "azure_blob",
                                "status": "stored",
                                "file-size": local_path.stat().st_size,
                            }
                            self._latest_artifacts.append(artifact)
                            logger.info(f"Created PowerPoint artifact: {filename} -> {blob_url[:80]}...")
                        else:
                            logger.warning("Blob upload failed; artifact not created")
                    else:
                        logger.warning("Presentation download failed; artifact not created")

                if text_chunks:
                    full_text = "".join(text_chunks)
                    if mcp_failures:
                        yield f"Error: MCP tool(s) failed ({', '.join(mcp_failures)}). {full_text}"
                    else:
                        yield full_text
                else:
                    yield "Error: Agent completed but no response text was generated"
                return

            except Exception as e:
                error_str = str(e).lower()
                if "rate_limit" in error_str or "429" in error_str or "too many requests" in error_str:
                    retry_count += 1
                    if retry_count <= max_retries:
                        backoff = min(15 * (2 ** retry_count), 60)
                        yield f"Rate limit hit - retrying in {backoff}s..."
                        await asyncio.sleep(backoff)
                        continue
                    yield f"Error: Rate limit exceeded after {max_retries} retries"
                else:
                    yield f"Error: {e}"
                return

    def _get_tool_description(self, tool_name: str) -> str:
        descriptions = {
            "create_presentation": "Create Presentation",
            "create_presentation_from_template": "Create From Template",
            "add_slide": "Add Slide",
            "manage_text": "Manage Text",
            "add_bullet_points": "Add Bullet Points",
            "add_table": "Add Table",
            "add_chart": "Add Chart",
            "add_shape": "Add Shape",
            "apply_professional_design": "Apply Professional Design",
            "download_presentation": "Download Presentation",
            "save_presentation": "Save Presentation",
            "manage_image": "Manage Image",
            "apply_picture_effects": "Apply Picture Effects",
            "manage_fonts": "Manage Fonts",
            "manage_hyperlinks": "Manage Hyperlinks",
            "add_connector": "Add Connector",
            "manage_slide_transitions": "Manage Transitions",
            "optimize_slide_text": "Optimize Text",
            "apply_slide_template": "Apply Slide Template",
            "create_slide_from_template": "Create Slide From Template",
            "create_presentation_from_templates": "Create From Templates",
            "auto_generate_presentation": "Auto Generate Presentation",
            "format_table_cell": "Format Table Cell",
            "update_chart_data": "Update Chart Data",
            "build_presentation": "Build Complete Presentation",
        }
        return descriptions.get(tool_name, tool_name.replace("_", " ").title())

    async def run_conversation(self, session_id: str, user_message: str) -> str:
        return "\n".join([r async for r in self.run_conversation_stream(session_id, user_message)])

    async def chat(self, session_id: str, user_message: str) -> str:
        return await self.run_conversation(session_id, user_message)
