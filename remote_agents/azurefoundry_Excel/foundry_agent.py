"""
AI Foundry Excel Agent with spreadsheet creation capabilities.
Uses the Responses API with native MCP tool support to interact with a
remote Excel MCP server.  After the LLM finishes building the spreadsheet
this agent fetches the resulting .xlsx from the MCP server's download
endpoint, uploads it to Azure Blob Storage, and exposes it as an A2A artifact.
"""
import os
import time
import datetime
import asyncio
import logging
import json
import uuid
import tempfile
import re
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import timedelta

import httpx
from openai import AsyncAzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.core.credentials import AzureNamedKeyCredential, AzureSasCredential

logger = logging.getLogger(__name__)

EXCEL_MCP_URL = os.getenv(
    "EXCEL_MCP_URL",
    "https://mcp-excel.ambitioussky-6c709152.westus2.azurecontainerapps.io/mcp",
)

# Base URL of the MCP server (for downloading generated files)
_MCP_BASE_URL = EXCEL_MCP_URL.rsplit("/mcp", 1)[0]


class FoundryExcelAgent:
    """AI Foundry Agent with Excel capabilities via Responses API."""

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
            "server_label": "Excel",
            "server_url": EXCEL_MCP_URL,
            "require_approval": "never",
            "allowed_tools": [
                "excel_open_from_url",
                "excel_describe_sheets",
                "excel_read_sheet",
                "excel_write_to_sheet",
                "excel_create_table",
                "excel_copy_sheet",
                "excel_format_range",
                "build_spreadsheet",
            ],
            "headers": {
                "Content-Type": "application/json",
                "User-Agent": "Azure-AI-Foundry-Agent",
                "Accept": "application/json, text/event-stream",
            },
        }

    # ------------------------------------------------------------------
    # Azure Blob Storage helpers (same pattern as image generator)
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
    # Excel file download helper
    # ------------------------------------------------------------------

    async def _download_excel_file(self, filename: str) -> Optional[Path]:
        """Download a .xlsx from the MCP server's /download/ endpoint."""
        url = f"{_MCP_BASE_URL}/download/{filename}"
        logger.info(f"Downloading Excel file from {url}")
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                tmp_dir = Path(tempfile.gettempdir()) / "xlsx_agent"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                local_path = tmp_dir / filename
                local_path.write_bytes(resp.content)
                logger.info(f"Saved Excel file to {local_path} ({len(resp.content)} bytes)")
                return local_path
        except Exception as e:
            logger.error(f"Failed to download Excel file: {e}")
            return None

    @staticmethod
    def _extract_filename_from_outputs(output_items) -> Optional[str]:
        """Scan response output items for filenames in MCP tool arguments or build_spreadsheet output."""
        last_filename = None
        for item in output_items:
            item_type = getattr(item, "type", None)
            if item_type not in ("mcp_call", "mcp_tool_call"):
                continue

            tool_name = getattr(item, "name", None)

            # Check build_spreadsheet output for download_url/filename
            if tool_name == "build_spreadsheet":
                raw = getattr(item, "output", None)
                if raw:
                    try:
                        data = json.loads(raw) if isinstance(raw, str) else raw
                        if isinstance(data, dict) and data.get("filename"):
                            last_filename = data["filename"]
                            continue
                    except (json.JSONDecodeError, TypeError):
                        pass

            # Check arguments for fileAbsolutePath
            args_raw = getattr(item, "arguments", None) or getattr(item, "server_params", None)
            if args_raw:
                try:
                    args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                    if isinstance(args, dict):
                        fpath = args.get("fileAbsolutePath", "")
                        if "/tmp/xlsx_downloads/" in fpath:
                            last_filename = fpath.split("/tmp/xlsx_downloads/")[-1]
                except (json.JSONDecodeError, TypeError):
                    pass
        return last_filename

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
        logger.info("Initializing Excel agent (Responses API)...")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{_MCP_BASE_URL}/health")
                logger.info(f"MCP Server status: {response.status_code}")
        except Exception as e:
            logger.warning(f"MCP Server health check failed: {e} (continuing anyway)")
        self._get_client()
        self._initialized = True

    def _get_agent_instructions(self) -> str:
        return f"""You are a professional Excel spreadsheet creator and data analyst.
You have access to Excel MCP tools that let you create, populate, format,
and export Excel workbooks.

## Creating New Spreadsheets — ALWAYS use build_spreadsheet

When creating a new workbook, you MUST use `build_spreadsheet` which creates the
entire workbook in a single tool call.  Do NOT call `excel_write_to_sheet` +
`excel_create_table` + `excel_format_range` etc. individually — this will fail
due to platform tool-call limits.

Example — create a sales report with two sheets:
```json
build_spreadsheet(
  filename="Sales_Report_Q1.xlsx",
  sheets=[
    {{
      "name": "Revenue",
      "data": [
        ["Month", "Revenue", "Growth"],
        ["January", "$120,000", "5%"],
        ["February", "$135,000", "12%"],
        ["March", "$150,000", "11%"]
      ],
      "table_name": "RevenueTable",
      "header_style": {{"font": {{"bold": true, "color": "#FFFFFF"}}, "fill": {{"type": "pattern", "pattern": "solid", "color": ["#4472C4"]}}}},
      "data_style": {{"font": {{"size": 11}}}}
    }},
    {{
      "name": "Summary",
      "data": [
        ["Metric", "Value"],
        ["Total Revenue", "$405,000"],
        ["Avg Growth", "9.3%"]
      ],
      "table_name": "SummaryTable"
    }}
  ]
)
```

`build_spreadsheet` automatically saves to `/tmp/xlsx_downloads/` and returns
a `download_url` — you do NOT need any additional steps after it.

## Editing / Reading Existing Spreadsheets

For reading or editing existing files, use the individual tools:

- `excel_describe_sheets` — List sheets and metadata
- `excel_read_sheet` — Read cell values from a sheet
- `excel_write_to_sheet` — Write values/formulas to cells
- `excel_create_table` — Create structured Excel table with headers
- `excel_format_range` — Apply styling (fonts, borders, fills, number formats)
- `excel_copy_sheet` — Duplicate a sheet

## Reading Existing Spreadsheets

When the user asks you to read, summarize, or extract data from an existing spreadsheet,
use the read tools — do NOT create a new workbook. The read tools accept URLs directly
(e.g. Azure Blob Storage URLs with SAS tokens).

- `excel_describe_sheets(fileAbsolutePath="https://...blob.core.windows.net/...xlsx?sv=...")` — list sheets and metadata
- `excel_read_sheet(fileAbsolutePath="https://...", sheetName="Sheet1")` — read cell values

Pass the full URL (including any query parameters like SAS tokens) as the `fileAbsolutePath` argument.
Do NOT call `excel_write_to_sheet` when only reading.

## Editing Existing Spreadsheets from URLs

When the user asks you to edit/modify an existing spreadsheet from a URL:

1. Call `excel_open_from_url(url="https://...blob.core.windows.net/...xlsx?sv=...")` — this downloads it to a local path
2. Use the returned local path with edit tools: `excel_write_to_sheet`, `excel_format_range`, `excel_create_table`, etc.
3. The modified file will be available for download at the path returned by `excel_open_from_url`

Do NOT pass URLs directly to edit tools — always use `excel_open_from_url` first.

## Formatting Tips

- Bold header row: use font style `{{"bold": true}}`
- Currency: use numFmt `"$#,##0.00"`
- Percentage: use numFmt `"0.0%"`
- Date: use numFmt `"yyyy-mm-dd"`
- Header background: use fill `{{"type": "pattern", "pattern": "solid", "color": ["#4472C4"]}}`
  with white font `{{"color": "#FFFFFF"}}`

Current date: {datetime.datetime.now().isoformat()}

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
                excel_filename: Optional[str] = None

                logger.info("Stream started — iterating events...")
                async for event in response:
                    event_type = getattr(event, "type", None)
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
                        pass  # filename extracted from response.completed output items

                    elif event_type == "response.mcp_call.failed":
                        tool_name = getattr(event, "name", None) or getattr(event, "item_id", "mcp_tool")
                        mcp_failures.append(tool_name)
                        logger.warning(f"MCP call failed: {tool_name}")

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

                            # Scan output items for the Excel file path
                            output_items = getattr(resp, "output", None) or []
                            excel_filename = self._extract_filename_from_outputs(output_items)
                            if excel_filename:
                                logger.info(f"Extracted Excel filename from MCP calls: {excel_filename}")

                # ---- Post-stream: handle file download + blob upload ----
                # Fallback: parse filename from LLM text if not found in tool args
                if not excel_filename and text_chunks:
                    full_text = "".join(text_chunks)
                    match = re.search(r'/tmp/xlsx_downloads/([^\s\])"\']+\.xlsx)', full_text)
                    if match:
                        excel_filename = match.group(1)
                        logger.info(f"Extracted Excel filename from text: {excel_filename}")

                logger.info(f"Stream finished. text_chunks={len(text_chunks)}, tools_seen={tool_calls_seen}, filename={excel_filename}, mcp_failures={mcp_failures}")

                if excel_filename:
                    local_path = await self._download_excel_file(excel_filename)
                    if local_path and local_path.exists():
                        blob_url = self._upload_to_blob(local_path)
                        if blob_url:
                            artifact: Dict[str, Any] = {
                                "artifact-uri": blob_url,
                                "file-name": excel_filename,
                                "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                "storage-type": "azure_blob",
                                "status": "stored",
                                "file-size": local_path.stat().st_size,
                            }
                            self._latest_artifacts.append(artifact)
                            logger.info(f"Created Excel artifact: {excel_filename} -> {blob_url[:80]}...")
                        else:
                            logger.warning("Blob upload failed; artifact not created")
                    else:
                        logger.warning("Excel file download failed; artifact not created")

                if text_chunks:
                    full_text = "".join(text_chunks)
                    if mcp_failures and not self._latest_artifacts:
                        # Only report as error if no artifact was produced
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
                    yield f"Rate limit exceeded after {max_retries} retries"
                else:
                    yield f"Error: {e}"
                return

    def _get_tool_description(self, tool_name: str) -> str:
        descriptions = {
            "excel_write_to_sheet": "Write To Sheet",
            "excel_create_table": "Create Table",
            "excel_format_range": "Format Range",
            "excel_describe_sheets": "Describe Sheets",
            "excel_read_sheet": "Read Sheet",
            "excel_copy_sheet": "Copy Sheet",
            "excel_screen_capture": "Screen Capture",
            "build_spreadsheet": "Build Complete Spreadsheet",
        }
        return descriptions.get(tool_name, tool_name.replace("_", " ").title())

    async def run_conversation(self, session_id: str, user_message: str) -> str:
        return "\n".join([r async for r in self.run_conversation_stream(session_id, user_message)])

    async def chat(self, session_id: str, user_message: str) -> str:
        return await self.run_conversation(session_id, user_message)
