"""
AI Foundry Image Generator Agent implementation for creative image synthesis workflows.
Adapted from the ADK agent pattern to work with Azure AI Foundry for prompt orchestration, style guidance, and tool-driven image creation.

IMPORTANT: QUOTA REQUIREMENTS FOR AZURE AI FOUNDRY AGENTS
========================================================

Based on Microsoft support documentation and user reports, Azure AI Foundry agents
require a MINIMUM of 20,000 TPM (Tokens Per Minute) to function properly without
rate limiting issues.

If you're experiencing "Rate limit exceeded" errors with normal usage:

1. Check your current TPM quota in Azure AI Foundry portal:
   - Go to Management > Quota
   - Look for your model deployment TPM allocation

2. If your TPM is below 20,000, request a quota increase:
   - In Azure portal, create a support request
   - Select "Service and subscription limits (quotas)" as Issue type
   - Select "Cognitive Services" as Quota type
   - Request at least 20,000 TPM for your model
   - Specify you need it for Azure AI Foundry agents with Bing Search

3. Consider using different regions:
   - Some regions have higher default quotas
   - US West 3 with Global Standard deployment type often works
   - Try gpt-4o instead of gpt-4 if available

4. Alternative deployment types:
   - Global Standard deployments often have higher limits
   - Data Zone deployments may have different quota availability

Common symptoms when TPM is too low:
- Rate limit errors on the first or second request
- "Try again in X seconds" even with minimal usage
- Agents failing during file search setup or Bing search operations

Reference: https://learn.microsoft.com/en-us/answers/questions/2237624/getting-rate-limit-exceeded-when-testing-ai-agent
"""
import os
import time
import asyncio
import logging
import json
import base64
import tempfile
import uuid
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime, timedelta

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import Agent, ThreadMessage, ThreadRun, AgentThread, ToolOutput, BingGroundingTool, ListSortOrder, FilePurpose, FileSearchTool, RequiredMcpToolCall, ToolApproval
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
import glob
from openai import OpenAI
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.core.credentials import AzureNamedKeyCredential, AzureSasCredential
from a2a.types import Part, DataPart
from a2a.utils.message import new_agent_parts_message
from io import BytesIO
import httpx
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)


class FoundryImageGeneratorAgent:
    """
    AI Foundry Image Generator Agent for orchestrating creative briefs and image synthesis.
    This class adapts the ADK agent pattern for Azure AI Foundry with focus on prompt parsing,
    style grounding, and delegating image creation to an external tool (dummy placeholder for now).
    """
    
    # Class-level shared resources for brand/style document search (created once)
    _shared_vector_store = None
    _shared_uploaded_files = []
    _shared_file_search_tool = None
    _file_search_setup_lock = asyncio.Lock()
    _ACTIVE_RUN_STATUSES = {"queued", "in_progress", "requires_action", "cancelling"}
    
    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self.agent: Optional[Agent] = None
        self.threads: Dict[str, str] = {}  # thread_id -> thread_id mapping
        self._file_search_tool = None  # Cache the file search tool
        self._agents_client = None  # Cache the agents client
        self._project_client = None  # Cache the project client
        self._openai_client: Optional[OpenAI] = None
        self._blob_service_client: Optional[BlobServiceClient] = None
        self._latest_artifacts: List[Dict[str, Any]] = []
        self._pending_file_refs_by_thread: Dict[str, List[Dict[str, Any]]] = {}
        self.last_token_usage: Optional[Dict[str, int]] = None  # Store token usage from last run

    def _get_blob_service_client(self) -> Optional[BlobServiceClient]:
        """Return a BlobServiceClient if Azure storage is configured and forced."""
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
                connection_string,
                api_version="2023-11-03",
            )
            return self._blob_service_client
        except Exception as e:
            logger.error(f"Failed to create BlobServiceClient: {e}")
            raise
        
    def _get_client(self) -> AgentsClient:
        """Get a cached AgentsClient instance to reduce API calls."""
        if self._agents_client is None:
            self._agents_client = AgentsClient(
                endpoint=self.endpoint,
                credential=self.credential,
            )
        return self._agents_client
        
    def _get_project_client(self) -> AIProjectClient:
        """Get a cached AIProjectClient instance to reduce API calls."""
        if self._project_client is None:
            self._project_client = AIProjectClient(
                endpoint=self.endpoint,
                credential=self.credential,
            )
        return self._project_client
    
    async def _setup_file_search(self, files_directory: str = "documents") -> Optional[FileSearchTool]:
        """Upload files from local directory and create vector store for style guidance search - ONCE per class."""
        async with FoundryImageGeneratorAgent._file_search_setup_lock:
            if FoundryImageGeneratorAgent._shared_file_search_tool is not None:
                logger.info("Reusing existing shared file search tool")
                return FoundryImageGeneratorAgent._shared_file_search_tool
            
            try:
                # Check if files directory exists
                if not os.path.exists(files_directory):
                    logger.info(f"No {files_directory} directory found, skipping file search setup")
                    return None
                
                # Find all supported files in the directory
                supported_extensions = ['*.txt', '*.md', '*.pdf', '*.docx', '*.json', '*.csv']
                file_paths = set()  # Use set to avoid duplicates
                for ext in supported_extensions:
                    file_paths.update(glob.glob(os.path.join(files_directory, ext)))
                    file_paths.update(glob.glob(os.path.join(files_directory, "**", ext), recursive=True))
                
                file_paths = list(file_paths)  # Convert back to list
                
                if not file_paths:
                    logger.info(f"No supported files found in {files_directory}, skipping file search setup")
                    return None
                
                logger.info(f"Found {len(file_paths)} files to upload: {[os.path.basename(f) for f in file_paths]}")
                
                # Upload files ONCE
                file_ids = []
                project_client = self._get_project_client()
                for file_path in file_paths:
                    try:
                        logger.info(f"Uploading file: {os.path.basename(file_path)}")
                        file = project_client.agents.files.upload_and_poll(
                            file_path=file_path, 
                            purpose=FilePurpose.AGENTS
                        )
                        file_ids.append(file.id)
                        FoundryImageGeneratorAgent._shared_uploaded_files.append(file.id)
                        logger.info(f"Uploaded file: {os.path.basename(file_path)} (ID: {file.id})")
                    except Exception as e:
                        logger.warning(f"Failed to upload {file_path}: {e}")
                
                if not file_ids:
                    logger.warning("No files were successfully uploaded")
                    return None
                
                # Create vector store ONCE using project client
                logger.info("Creating shared vector store with uploaded files...")
                FoundryImageGeneratorAgent._shared_vector_store = project_client.agents.vector_stores.create_and_poll(
                    file_ids=file_ids, 
                    name="image-generator-vectorstore"
                )
                logger.info(f"Created shared vector store: {FoundryImageGeneratorAgent._shared_vector_store.id}")
                
                # Create file search tool ONCE
                file_search = FileSearchTool(vector_store_ids=[FoundryImageGeneratorAgent._shared_vector_store.id])
                logger.info(f"File search capability prepared, type: {type(file_search)}")
                logger.debug(f"FileSearchTool object: {file_search}")
                
                # Verify the object has the expected attributes
                if not hasattr(file_search, 'definitions'):
                    logger.error(f"FileSearchTool missing 'definitions' attribute. Object: {file_search}")
                    return None
                if not hasattr(file_search, 'resources'):
                    logger.error(f"FileSearchTool missing 'resources' attribute. Object: {file_search}")
                    return None
                
                # Cache the shared file search tool
                FoundryImageGeneratorAgent._shared_file_search_tool = file_search
                logger.info("Cached shared file search tool for future use")
                    
                return file_search
                    
            except Exception as e:
                logger.error(f"Error setting up file search: {e}")
                return None
        
    async def create_agent(self) -> Agent:
        """Create the AI Foundry agent with optional web search and style document search capabilities."""
        if self.agent:
            logger.info("Image generator agent already exists, returning existing instance")
            return self.agent
        
        tools = []
        tool_resources = None
        
        project_client = self._get_project_client()
        
        # Add image generation function tool definition
        generate_image_tool = {
            "type": "function",
            "function": {
                "name": "generate_image",
                "description": """Create or edit an image from the supplied prompt and style parameters.
                
IMPORTANT - File Attachments:
- When the user message includes file attachments (base images, masks, overlays), they are AUTOMATICALLY available to this tool
- You do NOT need to specify image URLs or file paths in the parameters
- The tool will automatically detect and use attachments based on their roles:
  * 'base' role: The source image for editing
  * 'mask' role: Transparency mask defining editable regions
  * 'overlay' role: Image to composite onto the base
- Simply call this tool with your creative prompt - the system handles file access

For image editing with masks:
- Just describe what changes to make in the prompt
- The tool automatically applies changes only within the mask region
- No need to ask for file URLs - they're already available

For new image generation:
- Call with just a creative prompt when no attachments are present""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string", 
                            "description": "Primary creative prompt describing the desired image or edits to make."
                        },
                        "style": {
                            "type": "string", 
                            "description": "Optional style or art direction (e.g. 'photorealistic', 'oil painting')."
                        },
                        "size": {
                            "type": "string", 
                            "description": "Desired output resolution (e.g. '1024x1024', '1792x1024')."
                        },
                        "n": {
                            "type": "integer", 
                            "minimum": 1, 
                            "maximum": 1, 
                            "description": "Number of images to generate. Always use 1 unless explicitly requested otherwise."
                        },
                        "model": {
                            "type": "string", 
                            "description": "OpenAI model name (typically 'gpt-image-1')."
                        },
                        "input_fidelity": {
                            "type": "string", 
                            "description": "Optional edit fidelity override (e.g. 'high', 'medium', 'low')."
                        },
                    },
                    "required": ["prompt"],
                    "additionalProperties": False
                }
            }
        }
        tools.append(generate_image_tool)

        try:
            bing_connection = project_client.connections.get(name="agentbing")
            bing = BingGroundingTool(connection_id=bing_connection.id)
            tools.extend(bing.definitions)
            logger.info("Added Bing search capability for reference gathering")
        except Exception as e:
            logger.warning(f"Could not add Bing search: {e}")
            logger.info("Agent will work without web search capabilities")
        
        if self._file_search_tool is None:
            self._file_search_tool = await self._setup_file_search()
        
        if self._file_search_tool:
            logger.info(f"Using file search tool, type: {type(self._file_search_tool)}")
            if hasattr(self._file_search_tool, 'definitions'):
                tools.extend(self._file_search_tool.definitions)
                logger.info("Extended tools with file search definitions for style references")
            if hasattr(self._file_search_tool, 'resources'):
                tool_resources = self._file_search_tool.resources
                logger.info("Added file search tool resources for style documents")
                
        with project_client:
            agent_kwargs = dict(
                    model="gpt-4o",
                name="foundry-image-generator",
                    instructions=self._get_agent_instructions(),
                    tools=tools
                )
            if tool_resources:
                agent_kwargs["tool_resources"] = tool_resources
            self.agent = project_client.agents.create_agent(**agent_kwargs)
        
        logger.info(f"Created AI Foundry agent: {self.agent.id}")
        return self.agent
    
    def _get_agent_instructions(self) -> str:
        """Get the agent instructions for image generation and creative guidance."""
        return f"""
You are an Azure AI Foundry image generator agent.

Your mission is to generate images based on the prompts you receive. You work as part of a multi-agent system where other specialized agents (like branding agents) provide you with complete creative briefs.

## Core Responsibilities

1. **JUST GENERATE**: Use the prompt exactly as provided. DO NOT ask for clarifications about branding, style, colors, or creative direction - these should come from upstream agents.
2. **Trust the Input**: If you receive a prompt, assume it's complete and ready for image generation. The orchestrator has already coordinated with other agents to gather necessary information.
3. Reference documents in `documents/` for brand, palette, or art direction when helpful, but prioritize information in the prompt.
4. Keep prompts safe, avoiding disallowed or copyrighted content.
5. **CRITICAL**: Call `generate_image` EXACTLY ONCE per user request. DO NOT generate an image and then immediately refine it unless explicitly asked to do so.
6. **CRITICAL**: ALWAYS set `n=1` to generate exactly ONE image per request. NEVER generate multiple images (n > 1) unless explicitly asked.

### File Attachments (CRITICAL - READ CAREFULLY)
7. **AUTOMATIC FILE ACCESS**: When file attachments (base images, masks, overlays) are included in the request, they are AUTOMATICALLY available to the `generate_image` tool. You do NOT need to:
   - Ask for file URLs or paths
   - Specify file parameters in the tool call
   - Request access to the files
   - Wait for the user to provide anything else
   
8. **JUST CALL THE TOOL**: Simply call `generate_image` with your creative prompt. The system automatically:
   - Detects which files are attached (base, mask, overlay)
   - Downloads them from their URIs
   - Passes them to the appropriate image generation API
   - Handles all file I/O behind the scenes

9. **IMAGE EDITING WITH MASK**: If the request mentions editing/refining an image with a mask:
   - Call `generate_image` with a prompt describing the desired changes
   - The tool automatically uses the base image and mask that were attached
   - No need to ask for anything - just describe what to change

10. Return a summary of the generated image concept and tool output.

### Multi-turn Refinement
- If the user says "refine the previous image", call `generate_image` with refinement instructions
- If file attachments are present, they're automatically used
- NEVER ask "Please provide the URLs" - files are already available to your tool

## Response Template
```
🖼️ IMAGE GENERATION SUMMARY

**Concept**: <short description>
**Prompt Sent**: <final prompt>
**Style Notes**: <style / palette / inspiration>
**Tool Result**: <tool output>
**Next Steps**: <optional suggestions>
```

Current date and time: {datetime.now().isoformat()}

Always validate the prompt for safety before invoking the tool.
"""
    

    


    async def create_thread(self, thread_id: Optional[str] = None) -> AgentThread:
        """Create or retrieve a conversation thread."""
        if thread_id and thread_id in self.threads:
            # Return thread info - we'll need to get it fresh each time
            pass
            
        client = self._get_client()
        thread = client.threads.create()
        self.threads[thread.id] = thread.id
        logger.info(f"Created thread: {thread.id}")
        return thread

    async def ensure_thread_ready(
        self,
        thread_id: str,
        *,
        timeout: float = 10.0,
        poll_interval: float = 2.0,
    ) -> None:
        """Ensure there are no active runs on a thread before queuing a new message.

        Azure AI Foundry rejects new messages while a run remains active. To avoid long
        blocking periods that trigger upstream HTTP timeouts, we perform a quick
        cancellation sweep and hand control back to the caller if the run cannot be
        cleared promptly.
        """
        client = self._get_client()

        try:
            runs_listing = client.runs.list(
                thread_id=thread_id,
                order=ListSortOrder.DESCENDING,
            )
        except Exception as list_error:  # pragma: no cover - defensive logging
            logger.debug(
                "Unable to list runs for thread %s before enqueueing message: %s",
                thread_id,
                list_error,
            )
            return

        def _collect_active_runs(listing) -> List[ThreadRun]:
            data_seq = getattr(listing, "data", None)
            if data_seq is None:
                data_seq = listing
            if not data_seq:
                return []
            active: List[ThreadRun] = []
            for run in data_seq:
                status = getattr(run, "status", None)
                if status in self._ACTIVE_RUN_STATUSES:
                    active.append(run)
            return active

        active_runs = _collect_active_runs(runs_listing)
        if not active_runs:
            return

        logger.warning(
            "Thread %s has %d active run(s); attempting to cancel before queuing new message",
            thread_id,
            len(active_runs),
        )
        for run in active_runs:
            run_id = getattr(run, "id", None)
            if not run_id:
                continue
            try:
                client.runs.cancel(thread_id=thread_id, run_id=run_id)
                logger.info(
                    "Issued cancel for run %s on thread %s",
                    run_id,
                    thread_id,
                )
            except Exception as cancel_error:  # pragma: no cover
                logger.error(
                    "Failed to cancel run %s on thread %s: %s",
                    run_id,
                    thread_id,
                    cancel_error,
                )

        deadline = time.time() + timeout
        while time.time() < deadline:
            await asyncio.sleep(poll_interval)
            remaining_runs: List[ThreadRun] = []
            for run in active_runs:
                run_id = getattr(run, "id", None)
                if not run_id:
                    continue
                try:
                    refreshed = client.runs.get(thread_id=thread_id, run_id=run_id)
                except Exception:  # pragma: no cover
                    continue
                status = getattr(refreshed, "status", None)
                if status in self._ACTIVE_RUN_STATUSES:
                    remaining_runs.append(refreshed)
                else:
                    logger.info(
                        "Run %s on thread %s finished with status %s",
                        run_id,
                        thread_id,
                        status,
                    )
            if not remaining_runs:
                return
            active_runs = remaining_runs

        raise RuntimeError(
            f"Thread {thread_id} still has active Azure AI Foundry run(s) after cancellation attempts"
        )
    
    async def send_message(self, thread_id: str, content: str, role: str = "user") -> ThreadMessage:
        """Send a message to the conversation thread."""
        client = self._get_client()
        message = client.messages.create(
            thread_id=thread_id,
            role=role,
            content=content
        )
        logger.info(f"Created message in thread {thread_id}: {message.id}")
        return message
    
    async def run_conversation_stream(
        self,
        thread_id: str,
        user_message: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ):
        """Async generator: yields progress/tool call messages and final assistant response(s) in real time."""
        if not self.agent:
            await self.create_agent()

        if attachments:
            self._pending_file_refs_by_thread[thread_id] = attachments
            logger.info(f"Stored {len(attachments)} attachment(s) for thread {thread_id} - will be automatically available to generate_image tool")
            for idx, att in enumerate(attachments):
                file_info = att.get("file", {})
                logger.info(f"  Attachment[{idx}]: name={file_info.get('name')} role={file_info.get('role')} uri={file_info.get('uri', 'no-uri')[:80]}...")

        await self.ensure_thread_ready(thread_id)
        await self.send_message(thread_id, user_message)
        client = self._get_client()
        run = client.runs.create(thread_id=thread_id, agent_id=self.agent.id)

        max_iterations = 25
        iterations = 0
        retry_count = 0
        max_retries = 3
        tool_calls_yielded = set()
        stuck_run_count = 0
        max_stuck_runs = 3

        while run.status in ["queued", "in_progress", "requires_action"] and iterations < max_iterations:
            iterations += 1
            await asyncio.sleep(2)
            
            # Check for new tool calls in real-time (only show what we can actually detect)
            try:
                run_steps = client.run_steps.list(thread_id, run.id)
                for run_step in run_steps:
                    if (hasattr(run_step, "step_details") and
                        hasattr(run_step.step_details, "type") and
                        run_step.step_details.type == "tool_calls" and
                        hasattr(run_step.step_details, "tool_calls")):
                        for tool_call in run_step.step_details.tool_calls:
                            if tool_call and hasattr(tool_call, "type"):
                                tool_type = tool_call.type
                                if tool_type not in tool_calls_yielded:
                                    # Show actual tool calls that we can detect
                                    tool_description = self._get_tool_description(tool_type, tool_call)
                                    yield f"🛠️ Remote agent executing: {tool_description}"
                                    tool_calls_yielded.add(tool_type)
            except Exception as e:
                # Continue if we can't get run steps yet
                pass

            try:
                run = client.runs.get(thread_id=thread_id, run_id=run.id)
            except Exception as e:
                if "rate limit" in str(e).lower() or "429" in str(e):
                    retry_count += 1
                    if retry_count <= max_retries:
                        backoff_time = min(15 * (2 ** retry_count), 45)
                        await asyncio.sleep(backoff_time)
                        continue
                    else:
                        yield "Error: Rate limit exceeded, please try again later"
                        return
                else:
                    yield f"Error: {str(e)}"
                    return

            if run.status == "failed":
                logger.debug(f"Full run object on failure: {run}")
                logger.debug(f"run.last_error: {run.last_error}")
                yield f"Error: {run.last_error}"
                return

            if run.status == "requires_action":
                logger.info(f"Run {run.id} requires action - checking for tool calls")
                try:
                    # Check if there are actually tool calls to handle
                    if hasattr(run, 'required_action') and run.required_action:
                        logger.info(f"Found required action: {run.required_action}")
                        await self._handle_tool_calls(run, thread_id)
                    else:
                        logger.warning(f"Run status is 'requires_action' but no required_action found - this may indicate a stuck run")
                        stuck_run_count += 1
                        if stuck_run_count >= max_stuck_runs:
                            logger.error(f"Run {run.id} is stuck in requires_action state without tool calls after {stuck_run_count} attempts")
                            yield f"Error: Run is stuck in requires_action state - please try again"
                            return
                        # Try to get the run again to see if it has progressed
                        run = client.runs.get(thread_id=thread_id, run_id=run.id)
                except Exception as e:
                    yield f"Error handling tool calls: {str(e)}"
                    return

        if run.status == "failed":
            yield f"Error: {run.last_error}"
            return

        if iterations >= max_iterations:
            yield "Error: Request timed out"
            return

        # Extract token usage from completed run
        if hasattr(run, 'usage') and run.usage:
            self.last_token_usage = {
                'prompt_tokens': getattr(run.usage, 'prompt_tokens', 0),
                'completion_tokens': getattr(run.usage, 'completion_tokens', 0),
                'total_tokens': getattr(run.usage, 'total_tokens', 0)
            }
            logger.debug(f"💰 Token usage: {self.last_token_usage}")
        else:
            self.last_token_usage = None

        # After run is complete, yield the assistant's response(s) with citation formatting
        messages = list(client.messages.list(thread_id=thread_id, order=ListSortOrder.ASCENDING))
        logger.debug(f"Found {len(messages)} messages in thread")
        for msg in reversed(messages):
            logger.debug(f"Processing message: role={msg.role}, content_count={len(msg.content) if msg.content else 0}")
            if msg.role == "assistant" and msg.content:
                for content_item in msg.content:
                    logger.debug(f"Processing content item: type={type(content_item)}")
                    if hasattr(content_item, 'text'):
                        text_content = content_item.text.value
                        logger.debug(f"Original text content: {text_content[:200]}...")
                        citations = []
                        # Extract citations as before
                        if hasattr(content_item.text, 'annotations') and content_item.text.annotations:
                            logger.debug(f"Found {len(content_item.text.annotations)} annotations")
                            main_text = content_item.text.value if hasattr(content_item.text, 'value') else str(content_item.text)
                            for i, annotation in enumerate(content_item.text.annotations):
                                logger.debug(f"Processing annotation {i}: {type(annotation)}")
                                # File citations
                                if hasattr(annotation, 'file_citation') and annotation.file_citation:
                                    file_citation = annotation.file_citation
                                    quote = getattr(file_citation, 'quote', '') or ''
                                    file_id = getattr(file_citation, 'file_id', '') or ''
                                    annotation_text = getattr(annotation, 'text', '') or ''
                                    citation_context = self._extract_citation_context(main_text, annotation, quote)
                                    citation_text = self._create_meaningful_citation_text(quote, citation_context, file_id)
                                    citations.append({
                                        'type': 'file',
                                        'text': citation_text,
                                        'file_id': file_id,
                                        'quote': quote,
                                        'context': citation_context,
                                        'annotation_text': annotation_text
                                    })
                                    logger.debug(f"Added file citation: {citation_text}")
                                # File path citations
                                elif hasattr(annotation, 'file_path') and annotation.file_path:
                                    file_path = annotation.file_path
                                    file_id = getattr(file_path, 'file_id', '') or ''
                                    try:
                                        project_client = self._get_project_client()
                                        file_info = project_client.agents.files.get(file_id)
                                        if hasattr(file_info, 'filename') and file_info.filename:
                                            citation_text = file_info.filename
                                        else:
                                            citation_text = f"File Reference (ID: {file_id[-8:]})"
                                    except Exception as e:
                                        citation_text = f"File Reference (ID: {file_id[-8:]})"
                                    citations.append({
                                        'type': 'file_path',
                                        'text': citation_text,
                                        'file_id': file_id
                                    })
                                    logger.debug(f"Added file_path citation: {citation_text}")
                                # URL citations
                                elif hasattr(annotation, 'url_citation') and annotation.url_citation:
                                    url_citation = annotation.url_citation
                                    url = getattr(url_citation, 'url', '') or '#'
                                    title = getattr(url_citation, 'title', '') or 'Web Source'
                                    citations.append({
                                        'type': 'web',
                                        'text': title,
                                        'url': url
                                    })
                                    logger.debug(f"Added URL citation: {title} -> {url}")
                        else:
                            logger.debug(f"No annotations found in content item")
                        
                        logger.debug(f"Total citations found: {len(citations)}")
                        if citations:
                            logger.debug(f"Citations: {citations}")
                        else:
                            logger.debug(f"No citations found - this is why sources are missing!")
                        formatted_response = self._format_response_with_citations(text_content, citations)
                        logger.debug(f"Formatted response: {formatted_response[:200]}...")
                        logger.debug(f"Full formatted response length: {len(formatted_response)}")
                        logger.debug(f"Sources section in response: {'📚 Sources:' in formatted_response}")
                        if '📚 Sources:' in formatted_response:
                            sources_start = formatted_response.find('📚 Sources:')
                            logger.debug(f"Sources section: {formatted_response[sources_start:sources_start+200]}...")
                        yield formatted_response
                break
    
    def _format_response_with_citations(self, text_content: str, citations: List[Dict]) -> str:
        """Format the response text with clickable citations for Gradio UI."""
        if not citations:
            return text_content
        
        logger.debug(f"Processing {len(citations)} citations before deduplication")
        
        # Smart deduplication that preserves meaningful content
        unique_citations = []
        seen_citations = set()
        
        for citation in citations:
            # Create a unique key based on meaningful content
            if citation['type'] == 'web':
                key = f"web_{citation.get('url', '')}"
            elif citation['type'] in ['file', 'file_path']:
                file_id = citation.get('file_id', '')
                quote = citation.get('quote', '').strip()
                context = citation.get('context', '').strip()
                
                # Use content-based uniqueness for better deduplication
                if quote and len(quote) > 20:
                    # Use first 50 chars of quote for uniqueness
                    content_key = quote[:50].lower().replace(' ', '').replace('\n', '')
                    key = f"file_content_{content_key}"
                elif context and len(context) > 20:
                    # Use first 50 chars of context for uniqueness
                    content_key = context[:50].lower().replace(' ', '').replace('\n', '')
                    key = f"file_context_{content_key}"
                else:
                    # Fallback to file_id
                    key = f"file_{file_id}"
            else:
                # For other types, use text content
                text_key = citation.get('text', '')[:50].lower().replace(' ', '')
                key = f"{citation['type']}_{text_key}"
            
            # Only add if we haven't seen this content before
            if key not in seen_citations:
                seen_citations.add(key)
                unique_citations.append(citation)
        
        logger.debug(f"After deduplication: {len(unique_citations)} unique citations")
        
        # Start with the main text and clean up citation markers
        formatted_text = text_content
        
        # Remove Azure AI Foundry citation markers like 【4:0†source】
        import re
        formatted_text = re.sub(r'【\d+:\d+†source】', '', formatted_text)
        
        # Add a sources section if we have citations
        if unique_citations:
            formatted_text += "\n\n**📚 Sources:**\n"
            
            citation_num = 1
            for citation in unique_citations:
                if citation['type'] == 'web':
                    formatted_text += f"{citation_num}. 🌐 [{citation.get('text', 'Web Source')}]({citation.get('url', '#')})\n"
                elif citation['type'] in ['file', 'file_path']:
                    # Use our improved method to get meaningful citation text
                    meaningful_text = self._get_readable_file_name(citation)
                    formatted_text += f"{citation_num}. 📄 **{meaningful_text}** *(from uploaded documents)*\n"
                citation_num += 1
            
            logger.info(f"Generated sources section with {len(unique_citations)} citations")
        
        return formatted_text
    

    
    async def _handle_tool_calls(self, run: ThreadRun, thread_id: str):
        """Handle tool calls during agent execution."""
        logger.info(f"Handling tool calls for run {run.id}")
        
        if not hasattr(run, 'required_action') or not run.required_action:
            logger.warning(f"No required action found in run {run.id}")
            return
            
        required_action = run.required_action
        logger.info(f"Required action type: {type(required_action)}")
        logger.info(f"Required action attributes: {dir(required_action)}")
        
        if not hasattr(required_action, 'submit_tool_outputs') or not required_action.submit_tool_outputs:
            logger.warning(f"No tool outputs required in run {run.id}")
            return
            
        try:
            action_type = getattr(required_action, 'type', 'submit_tool_outputs')
            tool_calls = required_action.submit_tool_outputs.tool_calls
            if not tool_calls:
                logger.warning("No tool calls found in required action")
                return
            
            tool_outputs = []

            async def handle_single_tool_call(tool_call):
                function_name = tool_call.function.name
                arguments = tool_call.function.arguments
                logger.info(f"Processing tool call: {function_name} with args: {arguments}")
                logger.debug(f"Tool call ID: {tool_call.id}")
                
                if function_name == "generate_image":
                    try:
                        payload = json.loads(arguments)
                    except json.JSONDecodeError:
                        payload = {"raw": arguments}

                    self._current_tool_payload = payload
                    try:
                        logger.info(
                            "Initial tool payload snapshot | keys=%s | mask_fields=%s | fidelity=%s",
                            sorted(payload.keys()),
                            {
                                "mask_url": payload.get("mask_url"),
                                "mask_image_url": payload.get("mask_image_url"),
                            },
                            payload.get("input_fidelity") or payload.get("edit_input_fidelity"),
                        )
                    except Exception:  # pragma: no cover - defensive logging
                        logger.info("Initial tool payload snapshot unavailable due to non-standard payload type")

                    pending_attachments = self._pending_file_refs_by_thread.get(thread_id) or []
                    if pending_attachments:
                        logger.info(
                            "🎯 Thread %s: Automatically mapping %d attachment(s) to tool parameters",
                            thread_id,
                            len(pending_attachments),
                        )
                        for idx, attachment in enumerate(pending_attachments):
                            file_info = attachment.get("file") or {}
                            logger.info(
                                "  📎 Attachment[%d]: name=%s role=%s uri=%s bytes=%s",
                                idx,
                                file_info.get("name"),
                                (file_info.get("role")
                                 or (file_info.get("metadata") or {}).get("role")),
                                file_info.get("uri", "no-uri")[:80] + "...",
                                "yes" if file_info.get("bytes") or file_info.get("bytes_base64") else "no",
                            )
                        logger.debug(
                            "Injecting %d attachment(s) into payload for thread %s",
                            len(pending_attachments),
                            thread_id,
                        )
                        payload.setdefault("attachments", pending_attachments)

                        base_uri = self._extract_attachment_uri_by_role(pending_attachments, role="base")
                        if base_uri:
                            payload["image_url"] = base_uri
                            logger.info(
                                "✅ Mapped 'base' role attachment → image_url: %s",
                                base_uri[:80] + "...",
                            )
                        else:
                            requested_image_url = payload.get("image_url") or payload.get("input_image_url")
                            if requested_image_url and not str(requested_image_url).lower().startswith(("http://", "https://")):
                                logger.info(
                                    "Discarding non-URL base image reference for thread %s: %s",
                                    thread_id,
                                    requested_image_url,
                                )
                                payload.pop("image_url", None)
                                payload.pop("input_image_url", None)
                                requested_image_url = None
                            if not requested_image_url:
                                fallback_uri = self._extract_first_attachment_uri(pending_attachments)
                                if fallback_uri:
                                    payload["image_url"] = fallback_uri
                                    logger.debug(
                                        "Normalized image_url using first attachment URI for thread %s",
                                        thread_id,
                                    )

                        mask_uri = self._extract_attachment_uri_by_role(pending_attachments, role="mask")
                        if mask_uri:
                            payload["mask_url"] = mask_uri
                            logger.info(
                                "✅ Mapped 'mask' role attachment → mask_url: %s",
                                mask_uri[:80] + "...",
                            )
                        else:
                            existing_mask = payload.get("mask_url")
                            if existing_mask:
                                if not str(existing_mask).lower().startswith(("http://", "https://")):
                                    logger.info(
                                        "Discarding non-URL mask reference for thread %s: %s",
                                        thread_id,
                                        existing_mask,
                                    )
                                    payload.pop("mask_url", None)
                        try:
                            attachment_roles = [
                                (
                                    (att.get("file") or {}).get("name"),
                                    (att.get("file") or {}).get("role")
                                    or ((att.get("file") or {}).get("metadata") or {}).get("role"),
                                )
                                for att in payload.get("attachments", [])
                            ]
                            logger.info(
                                "Post-normalization payload | image_url=%s | mask_url=%s | attachment_roles=%s",
                                payload.get("image_url") or payload.get("input_image_url"),
                                payload.get("mask_url") or payload.get("mask_image_url"),
                                attachment_roles,
                            )
                        except Exception:  # pragma: no cover
                            logger.info("Unable to log post-normalization payload details")
                    else:
                        logger.debug(
                            "No attachments found for thread %s; payload keys=%s",
                            thread_id,
                            list(payload.keys()),
                        )
                        if not payload.get("image_url") and not payload.get("input_image_url"):
                            logger.warning(
                                "Thread %s lacks attachments providing a base image; edit may fail",
                                thread_id,
                            )

                    if not payload.get("image_url") and not payload.get("input_image_url"):
                        if pending_attachments:
                            error_msg = (
                                "Image edit request is missing a base image attachment or image_url; "
                                f"thread={thread_id}, payload_keys={list(payload.keys())}"
                            )
                            logger.error(error_msg)
                            return {
                                "tool_call_id": tool_call.id,
                                "output": json.dumps({"status": "error", "message": error_msg}),
                            }
                        else:
                            logger.debug("No base attachment provided; treating as fresh generation")

                    try:
                        openai_result = self._generate_image_via_openai(payload)
                        if openai_result is not None:
                            openai_result["tool_call_id"] = getattr(tool_call, "id", None)
                            output_payload = json.dumps(openai_result)
                        else:
                            output_payload = json.dumps({"status": "error", "message": "Image generation returned no result"})
                    except Exception as exc:
                        logger.error(f"Image generation failed: {exc}")
                        output_payload = json.dumps({"status": "error", "message": str(exc)})
                    finally:
                        if thread_id in self._pending_file_refs_by_thread:
                            cached_count = len(self._pending_file_refs_by_thread.get(thread_id, []))
                            logger.debug(
                                "Clearing %d cached attachment(s) for thread %s after tool call",
                                cached_count,
                                thread_id,
                            )
                            self._pending_file_refs_by_thread.pop(thread_id, None)
                    return {
                        "tool_call_id": tool_call.id,
                        "output": output_payload
                    }

                logger.info(f"Skipping system tool call: {function_name} (handled automatically)")
                return {
                    "tool_call_id": tool_call.id,
                    "output": "{}"
                }

            # Run all tool calls in parallel
            results = await asyncio.gather(
                *(handle_single_tool_call(tc) for tc in tool_calls)
            )
            # Filter out any None results (e.g., skipped system tool calls)
            tool_outputs = [r for r in results if r is not None]

            if not tool_outputs:
                logger.info("No valid tool outputs generated - submitting empty outputs to move run forward")
                # Submit empty tool outputs to move the run forward
                tool_outputs = [{"tool_call_id": tc.id, "output": "{}"} for tc in tool_calls if hasattr(tc, 'id') and tc.id]
                
            logger.debug(f"Tool outputs to submit: {tool_outputs}")
            
        except Exception as e:
            logger.error(f"Error processing tool calls: {e}")
            logger.error(f"Required action structure: {required_action}")
            raise
        
        # Submit the tool outputs or approvals
        client = self._get_client()
        try:
            if action_type == "submit_tool_outputs":
                # Create tool outputs in the expected format
                formatted_outputs = []
                for output in tool_outputs:
                    formatted_outputs.append(ToolOutput(
                        tool_call_id=output["tool_call_id"],
                        output=output["output"]
                    ))
                
                logger.debug(f"Submitting formatted tool outputs: {formatted_outputs}")
                
                client.runs.submit_tool_outputs(
                    thread_id=thread_id,
                    run_id=run.id,
                    tool_outputs=formatted_outputs
                )
                logger.info(f"Submitted {len(formatted_outputs)} tool outputs")
            elif action_type == "submit_tool_approval":
                # For tool approvals, we need to approve the MCP tool calls
                logger.info(f"Handling tool approval for {len(tool_calls)} tool calls")
                
                tool_approvals = []
                for tool_call in tool_calls:
                    if isinstance(tool_call, RequiredMcpToolCall):
                        try:
                            logger.info(f"Approving MCP tool call: {tool_call}")
                            tool_approvals.append(
                                ToolApproval(
                                    tool_call_id=tool_call.id,
                                    approve=True,
                                    headers={}  # Add any required headers here
                                )
                            )
                        except Exception as e:
                            logger.error(f"Error approving tool_call {tool_call.id}: {e}")
                
                if tool_approvals:
                    client.runs.submit_tool_outputs(
                        thread_id=thread_id,
                        run_id=run.id,
                        tool_approvals=tool_approvals
                    )
                    logger.info(f"Approved {len(tool_approvals)} MCP tool calls")
                else:
                    logger.warning("No valid tool approvals to submit")
        except Exception as e:
            logger.error(f"Failed to submit tool outputs: {e}")
            logger.error(f"Raw tool outputs structure: {tool_outputs}")
            # Try submitting without ToolOutput wrapper as fallback
            try:
                logger.info("Trying fallback submission with raw dict format")
                client.runs.submit_tool_outputs(
                    thread_id=thread_id,
                    run_id=run.id,
                    tool_outputs=tool_outputs
                )
                logger.info(f"Fallback submission successful")
            except Exception as e2:
                logger.error(f"Fallback submission also failed: {e2}")
                raise e
        
    def _get_readable_file_name(self, citation: Dict) -> str:
        """Get meaningful citation text based on content, not just file names."""
        
        # Priority 1: Use actual quote/content if available and meaningful
        quote = citation.get('quote', '').strip()
        if quote and len(quote) > 20:  # Ensure substantial content
            # Clean and truncate the quote for readability
            clean_quote = quote.replace('\n', ' ').replace('\r', ' ')
            if len(clean_quote) > 100:
                clean_quote = clean_quote[:97] + "..."
            return f'"{clean_quote}"'
        
        # Priority 2: Extract meaningful content from the citation text itself
        citation_text = citation.get('text', '').strip()
        if citation_text and 'Document excerpt:' in citation_text:
            # Already formatted as an excerpt
            return citation_text
        
        # Priority 3: Try to create meaningful content from available text
        if citation_text and len(citation_text) > 20:
            clean_text = citation_text.replace('\n', ' ').replace('\r', ' ')
            if len(clean_text) > 100:
                clean_text = clean_text[:97] + "..."
            return f'Document excerpt: "{clean_text}"'
        
        # Priority 4: Use file information if available
        file_id = citation.get('file_id', '')
        if file_id:
            return f"Document (ID: {file_id[-8:]})"  # Use last 8 chars for brevity
        
        # Fallback: Generic but still informative
        source_type = citation.get('type', 'document')
        return f"Referenced {source_type}"

    def _extract_citation_context(self, main_text: str, annotation, quote: str) -> str:
        """Extract meaningful context around a citation from the main response text."""
        try:
            # If we have a quote, try to find it in the main text and get surrounding context
            if quote and len(quote.strip()) > 10:
                import re
                # Look for the quote or similar content in the main text
                quote_words = quote.strip().split()[:5]  # First 5 words
                if len(quote_words) >= 2:
                    pattern = r'.{0,50}' + re.escape(' '.join(quote_words[:2])) + r'.{0,50}'
                    match = re.search(pattern, main_text, re.IGNORECASE)
                    if match:
                        context = match.group(0).strip()
                        return context
            
            # Fallback: Try to get context around citation markers
            if hasattr(annotation, 'text') and annotation.text:
                marker = annotation.text
                # Look for the citation marker in the main text
                marker_pos = main_text.find(marker)
                if marker_pos != -1:
                    # Extract 100 characters before and after the marker
                    start = max(0, marker_pos - 100)
                    end = min(len(main_text), marker_pos + len(marker) + 100)
                    context = main_text[start:end].strip()
                    # Clean up the context
                    context = context.replace(marker, '').strip()
                    if context:
                        return context
            
            return ""
        except Exception as e:
            logger.debug(f"Error extracting citation context: {e}")
            return ""

    def _create_meaningful_citation_text(self, quote: str, context: str, file_id: str) -> str:
        """Create meaningful citation text using available information."""
        
        # Priority 1: Use substantial quote content
        if quote and len(quote.strip()) > 20:
            clean_quote = quote.replace('\n', ' ').replace('\r', ' ').strip()
            if len(clean_quote) > 100:
                clean_quote = clean_quote[:97] + "..."
            return f'Document excerpt: "{clean_quote}"'
        
        # Priority 2: Use extracted context
        if context and len(context.strip()) > 20:
            clean_context = context.replace('\n', ' ').replace('\r', ' ').strip()
            if len(clean_context) > 100:
                clean_context = clean_context[:97] + "..."
            return f'Document content: "{clean_context}"'
        
        # Priority 3: Try to get meaningful filename
        if file_id:
            try:
                project_client = self._get_project_client()
                file_info = project_client.agents.files.get(file_id)
                if hasattr(file_info, 'filename') and file_info.filename:
                    # Clean up the filename for display
                    filename = file_info.filename
                    if filename.endswith('.pdf'):
                        filename = filename[:-4]  # Remove .pdf extension
                    return f'Document: "{filename}"'
            except Exception as e:
                logger.debug(f"Could not retrieve filename for {file_id}: {e}")
        
        # Priority 4: Use shortened file ID
        if file_id and len(file_id) > 8:
            return f"Document (ID: {file_id[-8:]})"
        elif file_id:
            return f"Document (ID: {file_id})"
        
        # Fallback
        return "Referenced document"

    def _get_tool_description(self, tool_type: str, tool_call) -> str:
        """Helper to get a more meaningful tool description from the tool call."""
        try:
            # Try to get the actual function name from the tool call
            if hasattr(tool_call, 'function') and hasattr(tool_call.function, 'name'):
                function_name = tool_call.function.name
                # Try to get arguments if available
                if hasattr(tool_call.function, 'arguments'):
                    try:
                        import json
                        args = json.loads(tool_call.function.arguments)
                        # Create a more descriptive message based on function name and args
                        if function_name == "bing_grounding" or function_name == "web_search":
                            query = args.get('query', '')
                            if query:
                                return f"Searching the web for: '{query[:50]}{'...' if len(query) > 50 else ''}'"
                            else:
                                return "Performing web search"
                        elif function_name == "file_search":
                            query = args.get('query', '')
                            if query:
                                return f"Searching documents for: '{query[:50]}{'...' if len(query) > 50 else ''}'"
                            else:
                                return "Searching through uploaded documents"
                        elif function_name.startswith("search_"):
                            search_term = args.get('search_term', args.get('query', ''))
                            if search_term:
                                return f"Searching ServiceNow for: '{search_term[:50]}{'...' if len(search_term) > 50 else ''}'"
                            else:
                                return f"Executing {function_name} in ServiceNow"
                        elif function_name.startswith("get_"):
                            return f"Retrieving {function_name.replace('get_', '').replace('_', ' ')} from ServiceNow"
                        elif function_name.startswith("create_"):
                            return f"Creating new {function_name.replace('create_', '').replace('_', ' ')} in ServiceNow"
                        elif function_name.startswith("list_"):
                            return f"Listing {function_name.replace('list_', '').replace('_', ' ')} from ServiceNow"
                        else:
                            return f"Executing {function_name}"
                    except (json.JSONDecodeError, AttributeError):
                        return f"Executing {function_name}"
                else:
                    return f"Executing {function_name}"
            else:
                # Fallback to tool type if function name not available
                return f"Executing {tool_type}"
        except Exception as e:
            # Final fallback
            return f"Executing tool: {tool_type}"

    def _get_openai_client(self) -> OpenAI:
        """Lazy-create an OpenAI client using the project environment variables."""
        if self._openai_client is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY environment variable is required for image generation")
            self._openai_client = OpenAI(api_key=api_key)
        return self._openai_client

    def _generate_image_via_openai(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Call the OpenAI Responses API and return metadata about the generated image."""
        client = self._get_openai_client()
        prompt = payload.get("prompt")
        style = payload.get("style")
        size = payload.get("size", "1024x1024")
        n_images = int(payload.get("n", 1))
        
        # SAFETY: Force n=1 for agent-to-agent mode to prevent multiple image generation
        # This prevents the agent from creating variations when a single image is requested
        if n_images > 1:
            logger.warning(f"Agent requested n={n_images} images, forcing n=1 for agent-to-agent mode")
            n_images = 1

        requested_model_raw = payload.get("model")
        if isinstance(requested_model_raw, str) and requested_model_raw.strip() and requested_model_raw.strip() != "gpt-image-1":
            logger.info(
                "Ignoring requested image model '%s'; using 'gpt-image-1' for all generations",
                requested_model_raw.strip(),
            )
        model_to_use = "gpt-image-1"

        if not prompt:
            raise ValueError("Image generation payload must include a 'prompt'")

        if style:
            prompt = f"{prompt}\n\nStyle guidance: {style}"

        input_image_url = payload.get("image_url") or payload.get("input_image_url")
        mask_image_url = payload.get("mask_url") or payload.get("mask_image_url")
        attachments = payload.get("attachments") or payload.get("files") or []

        has_mask = self._payload_has_mask(payload)
        has_overlay = self._payload_has_overlay(payload)

        try:
            logger.info(
                "OpenAI payload diagnostics | has_mask=%s | mask_url=%s | attachments=%d | fidelity=%s",
                has_mask,
                mask_image_url,
                len(attachments),
                payload.get("input_fidelity") or payload.get("edit_input_fidelity"),
            )
        except Exception:  # pragma: no cover
            logger.info("Unable to capture OpenAI payload diagnostics")

        if mask_image_url:
            prompt = f"{prompt}\n\nApply the requested changes ONLY within the provided mask region."
        elif not has_mask:
            prompt = (
                f"{prompt}\n\nPreserve the original photographic realism, lighting, surface textures, and any existing text. "
                "Do not convert the scene into a flat graphic or illustration; make only subtle color grading and accent adjustments."
            )
        if has_overlay:
            prompt = (
                f"{prompt}\n\nUse the provided overlay image exactly as supplied, matching its shapes and colors pixel-for-pixel. "
                "Do not redraw, restyle, or reinterpret the overlay; integrate it into the base image verbatim."
            )

        if input_image_url or attachments:
            if model_to_use.lower() not in {"gpt-image-1", "gpt-image-1-mini"}:
                logger.debug(
                    "Overriding requested model '%s' with 'gpt-image-1' for image edit",
                    model_to_use,
                )
                model_to_use = "gpt-image-1"
            return self._generate_image_edit(
                client=client,
                model=model_to_use,
                prompt=prompt,
                image_url=input_image_url,
                mask_url=mask_image_url,
                attachments=attachments,
                size=size,
                n_images=n_images,
                output_dir=payload.get("output_dir"),
            )

        images: List[Dict[str, Any]] = []
        generated_artifacts: List[Dict[str, Any]] = []
        download_errors: List[str] = []

        default_outputs_dir = Path(__file__).parent / "static" / "outputs"
        output_dir = Path(payload.get("output_dir") or default_outputs_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        image_response = client.images.generate(
            model=model_to_use,
            prompt=prompt,
            size=size,
            n=n_images,
        )

        response_id = getattr(image_response, "id", None) or getattr(image_response, "created", None)

        for output_index, data in enumerate(image_response.data[:n_images]):
            result_payload = data

            filename = payload.get("output_filename") or f"generated_{uuid.uuid4().hex[:8]}_{output_index}.png"
            output_path = output_dir / filename

            entry = {
                "index": output_index,
                "response_id": response_id,
                "image_call_id": getattr(data, "id", None),
                "model": model_to_use,
            }

            saved_path: Optional[Path] = None
            b64_payload = None
            if isinstance(result_payload, str):
                b64_payload = result_payload
            elif isinstance(result_payload, dict):
                b64_payload = result_payload.get("image_base64") or result_payload.get("b64_json")
                if not b64_payload:
                    entry["source_url"] = result_payload.get("url")
            elif hasattr(result_payload, "b64_json"):
                b64_payload = result_payload.b64_json
            elif hasattr(result_payload, "image_base64"):
                b64_payload = result_payload.image_base64

            if b64_payload:
                image_bytes = base64.b64decode(b64_payload)
                output_path.write_bytes(image_bytes)
                saved_path = output_path
                entry["file_size_bytes"] = len(image_bytes)
            elif entry.get("source_url"):
                try:
                    with httpx.Client(timeout=30.0, follow_redirects=True) as client_http:
                        resp = client_http.get(entry["source_url"])
                        resp.raise_for_status()
                        output_path.write_bytes(resp.content)
                        saved_path = output_path
                        entry["file_size_bytes"] = len(resp.content)
                except Exception as download_err:
                    logger.error(f"Failed to download image from URL: {download_err}")
                    entry["error"] = f"download_failed: {download_err}"
                    download_errors.append(str(download_err))
            else:
                entry["error"] = "no_image_content"

            if saved_path:
                entry["saved_path"] = str(saved_path)
                blob_url = self._upload_to_blob(saved_path)
                if blob_url:
                    entry["blob_url"] = blob_url
                    logger.info("Uploaded edited image to blob: %s", blob_url)
                    artifact_record: Dict[str, Any] = {
                        "artifact-uri": blob_url,
                        "file-name": saved_path.name,
                        "storage-type": "azure_blob",
                        "status": "stored",
                        "provider-response-id": response_id,
                        "provider-image-call-id": entry.get("image_call_id"),
                        "provider": "openai",
                        "model": model_to_use,
                        # Don't assign role - generated images are distinct artifacts, not editing inputs
                        # They should all be displayed, not deduplicated
                    }
                    artifact_record["local-path"] = str(saved_path)
                    if entry.get("file_size_bytes") is not None:
                        artifact_record["file-size"] = entry["file_size_bytes"]
                    if entry.get("source_url"):
                        artifact_record["source-url"] = entry["source_url"]
                    logger.info(f"🖼️ [EDIT] Created artifact_record: file={artifact_record.get('file-name')}, has_role={'role' in artifact_record}, keys={list(artifact_record.keys())}")
                    generated_artifacts.append(artifact_record)

            images.append(entry)

        if generated_artifacts:
            self._latest_artifacts.extend(generated_artifacts)

        response_id = images[0].get("response_id") if images else (download_errors[0] if download_errors else None)

        result: Dict[str, Any] = {
            "status": "success" if images else "error",
            "images": images,
            "created": datetime.utcnow().isoformat(),
            "model": model_to_use,
            "response_id": response_id,
            "image_call_id": images[0].get("image_call_id") if images else None,
            "provider": "openai",
        }

        if download_errors:
            result["warnings"] = download_errors

        return result

    @staticmethod
    def _extract_file_infos(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        file_infos: List[Dict[str, Any]] = []
        seen_uris: set[str] = set()

        for part in parts:
            file_info = part.get("file") if isinstance(part, dict) else None
            if not file_info:
                continue

            uri = file_info.get("uri")
            key = uri or file_info.get("name")
            if key and key in seen_uris:
                continue

            seen_uris.add(key)
            file_infos.append(file_info)

        return file_infos

    def _generate_image_edit(
        self,
        client: OpenAI,
        model: str,
        prompt: str,
        image_url: Optional[str],
        mask_url: Optional[str],
        attachments: List[Dict[str, Any]],
        size: str,
        n_images: int,
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Perform image refinement via the OpenAI Images API."""
        logger.info("Performing image edit using OpenAI Images API")
        logger.info(
            "Edit payload summary | image_url=%s | mask_url=%s | attachment_count=%d",
            image_url,
            mask_url,
            len(attachments or []),
        )

        if attachments:
            for idx, part in enumerate(attachments):
                file_info = part.get("file") if isinstance(part, dict) else None
                if not file_info:
                    continue
                logger.info(
                    "Attachment[%d]: name=%s uri=%s role=%s mime=%s",
                    idx,
                    file_info.get("name"),
                    file_info.get("uri"),
                    file_info.get("role") or (file_info.get("metadata") or {}).get("role"),
                    file_info.get("mimeType") or file_info.get("mime_type"),
                )

        default_outputs_dir = Path(__file__).parent / "static" / "outputs"
        output_dir_path = Path(output_dir or default_outputs_dir)
        output_dir_path.mkdir(parents=True, exist_ok=True)

        image_bytes: Optional[bytes] = None
        mask_bytes: Optional[bytes] = None
        overlay_bytes: Optional[bytes] = None

        download_errors: List[str] = []

        def _looks_like_image(file_info: Dict[str, Any]) -> bool:
            name_candidate = str(file_info.get("name", "")).strip().lower()
            uri_candidate = str(file_info.get("uri", "")).strip().lower()
            if uri_candidate:
                uri_candidate = uri_candidate.split("?")[0]
            image_extensions = [
                "png",
                "jpg",
                "jpeg",
                "gif",
                "webp",
                "bmp",
                "tiff",
                "tif",
                "apng",
                "jfif",
            ]
            if any(name_candidate.endswith(f".{ext}") for ext in image_extensions):
                return True
            if any(uri_candidate.endswith(f".{ext}") for ext in image_extensions):
                return True
            return False

        def _is_image_mime(mime: Optional[str], file_info: Dict[str, Any]) -> bool:
            if mime:
                normalized = mime.lower()
                if normalized.startswith("image/"):
                    return True
                # Some uploads come through as octet-stream even though they are images
                if normalized in {"application/octet-stream", "binary/octet-stream"}:
                    return _looks_like_image(file_info)
                return False
            return _looks_like_image(file_info)

        def _attachment_to_bytes(part: Dict[str, Any]) -> Optional[bytes]:
            file_info = part.get("file") or {}
            uri = file_info.get("uri")
            mime = file_info.get("mimeType") or file_info.get("mime_type")

            if not _is_image_mime(mime, file_info):
                return None

            if uri:
                try:
                    with httpx.Client(timeout=60.0, follow_redirects=True) as http_client:
                        resp = http_client.get(uri)
                        resp.raise_for_status()
                        return resp.content
                except Exception as uri_err:
                    error_msg = f"Failed to download attachment from {uri}: {uri_err}"
                    logger.error(error_msg)
                    download_errors.append(error_msg)
                    # Intentionally continue to fall back to inline bytes/base64 if available

            raw_bytes = file_info.get("bytes")
            if raw_bytes is not None and isinstance(raw_bytes, (bytes, bytearray)):
                return bytes(raw_bytes)

            raw_bytes_b64 = file_info.get("bytes_base64")
            if raw_bytes_b64:
                try:
                    return base64.b64decode(raw_bytes_b64)
                except Exception as decode_err:
                    error_msg = f"Failed to decode base64 attachment: {decode_err}"
                    logger.error(error_msg)
                    download_errors.append(error_msg)
                    return None

            return None
# ... ensure_png definition added

        unique_files = self._extract_file_infos(attachments)

        def _resolve_role(info: Dict[str, Any]) -> Optional[str]:
            raw_role = info.get("role")
            if not raw_role:
                metadata = info.get("metadata") or {}
                raw_role = metadata.get("role")
            if isinstance(raw_role, str):
                return raw_role.lower()
            return None

        role_assignments: List[Tuple[Dict[str, Any], Optional[str], str]] = []
        for info in unique_files:
            role = _resolve_role(info)
            name_lower = str(info.get("name") or "").lower()
            if not role and "mask" in name_lower:
                role = "mask"
            role_assignments.append((info, role, name_lower))

        base_info = next((info for info, role, _ in role_assignments if role == "base"), None)
        mask_info = next((info for info, role, _ in role_assignments if role == "mask"), None)
        overlay_infos = [info for info, role, _ in role_assignments if role == "overlay"]

        for info, role, name_lower in role_assignments:
            looks_like_base_name = (
                "_base" in name_lower or name_lower.endswith("-base.png") or name_lower.endswith("_base.png")
            )

            if role == "base" or looks_like_base_name:
                base_info = info
                continue
            if role == "mask":
                mask_info = info
                continue
            if role == "overlay":
                if info not in overlay_infos:
                    overlay_infos.append(info)
                continue

            if base_info is None:
                base_info = info
            elif mask_info is None and ("mask" in name_lower or name_lower.endswith("_mask.png")):
                mask_info = info
            else:
                if info not in overlay_infos:
                    overlay_infos.append(info)

        if base_info and image_bytes is None:
            image_bytes = _attachment_to_bytes({"file": base_info})
            try:
                logger.info(
                    "Selected base attachment | name=%s uri=%s",
                    base_info.get("name"),
                    base_info.get("uri"),
                )
            except Exception:
                pass

        if overlay_bytes is None and overlay_infos:
            overlay_bytes = _attachment_to_bytes({"file": overlay_infos[0]})
            if overlay_bytes:
                logger.info(
                    "Loaded overlay image %s (%d bytes)",
                    overlay_infos[0].get("name"),
                    len(overlay_bytes),
                )
            else:
                logger.warning(
                    "Failed to load overlay image %s", overlay_infos[0].get("name")
                )

        if mask_bytes is None and mask_info:
            mask_bytes = _attachment_to_bytes({"file": mask_info})
            try:
                logger.info(
                    "Selected mask attachment | name=%s uri=%s",
                    mask_info.get("name"),
                    mask_info.get("uri"),
                )
            except Exception:
                pass

        if image_bytes is None:
            for part in attachments:
                maybe_bytes = _attachment_to_bytes(part)
                if maybe_bytes:
                    image_bytes = maybe_bytes
                    break

        if mask_bytes is None and mask_url and mask_url.lower().startswith(("http://", "https://")):
            mask_bytes = _attachment_to_bytes({"file": {"uri": mask_url}})

        if image_bytes is None and image_url:
            try:
                with httpx.Client(timeout=60.0, follow_redirects=True) as http_client:
                    base_image_resp = http_client.get(image_url)
                    base_image_resp.raise_for_status()
                    image_bytes = base_image_resp.content
                logger.info("Downloaded base image from %s (%d bytes)", image_url, len(image_bytes))
            except Exception as download_err:
                error_msg = f"Failed to download base image from {image_url}: {download_err}"
                logger.error(error_msg)
                download_errors.append(error_msg)

        if mask_bytes is None and mask_url:
            try:
                with httpx.Client(timeout=60.0, follow_redirects=True) as http_client:
                    mask_resp = http_client.get(mask_url)
                    mask_resp.raise_for_status()
                    mask_bytes = mask_resp.content
                logger.info("Downloaded mask from %s (%d bytes)", mask_url, len(mask_bytes))
            except Exception as mask_err:
                error_msg = f"Failed to download mask image from {mask_url}: {mask_err}"
                logger.error(error_msg)
                download_errors.append(error_msg)

        if mask_bytes is not None and image_bytes is not None:
            try:
                with Image.open(BytesIO(image_bytes)) as base_image, Image.open(BytesIO(mask_bytes)) as mask_image:
                    if mask_image.size != base_image.size:
                        raise ValueError(
                            f"Mask dimensions {mask_image.size} do not match base image dimensions {base_image.size}."
                        )
            except UnidentifiedImageError as dimension_err:
                raise ValueError(f"Mask image is not a valid image: {dimension_err}")

        if image_bytes is None:
            if download_errors:
                raise ValueError("Could not obtain base image for refinement: " + "; ".join(download_errors))
            raise ValueError("No base image available for refinement")

        if image_bytes is not None:
            image_bytes = self._ensure_png(image_bytes)
            source_file_path = self._write_temp_png(image_bytes)
            temp_paths: List[str] = [source_file_path]
        else:
            raise ValueError("No base image available for refinement")

        mask_file_handle = None
        image_file_handles: List[Any] = []
        overlay_file_path: Optional[str] = None
        mask_file_path: Optional[str] = None

        try:
            edit_kwargs: Dict[str, Any] = {
                "model": "gpt-image-1",
                "prompt": prompt,
                "n": n_images,
            }

            current_payload = getattr(self, "_current_tool_payload", {})
            fidelity = current_payload.get("input_fidelity") or current_payload.get("edit_input_fidelity")
            payload_has_mask = self._payload_has_mask(current_payload)

            try:
                logger.info(
                    "Mask workflow diagnostics | payload_has_mask=%s | mask_bytes_present=%s | overlay_bytes_present=%s | fidelity=%s",
                    payload_has_mask,
                    mask_bytes is not None,
                    overlay_bytes is not None,
                    fidelity,
                )
            except Exception:  # pragma: no cover
                logger.info("Unable to log mask workflow diagnostics")

            if fidelity and not payload_has_mask:
                edit_kwargs["input_fidelity"] = fidelity
            elif not payload_has_mask:
                edit_kwargs["input_fidelity"] = "high"
            elif fidelity:
                logger.debug(
                    "Omitting input_fidelity=%s for mask-based edit", fidelity
                )

            if payload_has_mask and mask_bytes is None:
                logger.warning(
                    "Payload reported mask but no mask bytes were resolved | mask_url=%s | attachments=%d",
                    mask_url,
                    len(attachments or []),
                )

            base_handle = open(source_file_path, "rb")
            image_file_handles.append(base_handle)

            if overlay_bytes:
                overlay_png = self._ensure_png(overlay_bytes)
                overlay_file_path = self._write_temp_png(overlay_png)
                temp_paths.append(overlay_file_path)
                overlay_handle = open(overlay_file_path, "rb")
                image_file_handles.append(overlay_handle)

            if mask_bytes:
                mask_bytes = self._ensure_png(mask_bytes)
                mask_file_path = self._write_temp_png(mask_bytes)
                temp_paths.append(mask_file_path)
                mask_file_handle = open(mask_file_path, "rb")
                edit_kwargs["mask"] = mask_file_handle
                logger.info(
                    "Prepared mask file for OpenAI edit | path=%s | size=%d",
                    mask_file_path,
                    len(mask_bytes),
                )
            if size:
                edit_kwargs["size"] = size

            edit_kwargs["image"] = image_file_handles
            logger.info(
                "Invoking OpenAI images.edit | has_mask=%s | image_handles=%d | kwargs_keys=%s",
                "mask" in edit_kwargs,
                len(image_file_handles),
                [key for key in edit_kwargs.keys() if key != "prompt"],
            )
            edit_response = client.images.edit(**edit_kwargs)
            logger.info("Image edit completed successfully")
        except Exception as edit_error:
            logger.error(f"Image edit failed: {edit_error}")
            raise
        finally:
            setattr(self, "_current_tool_payload", None)
            for handle in image_file_handles:
                try:
                    handle.close()
                except Exception:
                    pass
            if mask_file_handle:
                mask_file_handle.close()
            for path in temp_paths:
                try:
                    os.unlink(path)
                except Exception:
                    pass

        images: List[Dict[str, Any]] = []
        generated_artifacts: List[Dict[str, Any]] = []

        for output_index, data in enumerate(edit_response.data[:n_images]):
            filename = f"edit_{uuid.uuid4().hex[:8]}_{output_index}.png"
            output_path = output_dir_path / filename

            entry: Dict[str, Any] = {
                "index": output_index,
                "response_id": getattr(edit_response, "id", None) or f"edit_{uuid.uuid4().hex}",
                "image_call_id": getattr(data, "id", None),
                "model": model,
            }

            saved_path: Optional[Path] = None
            b64_json = getattr(data, "b64_json", None) or (data.get("b64_json") if isinstance(data, dict) else None)
            if b64_json:
                image_bytes = base64.b64decode(b64_json)
                output_path.write_bytes(image_bytes)
                saved_path = output_path
                entry["file_size_bytes"] = len(image_bytes)
            elif isinstance(data, dict) and data.get("url"):
                entry["source_url"] = data["url"]
                try:
                    with httpx.Client(timeout=30.0, follow_redirects=True) as http_client:
                        resp = http_client.get(data["url"])
                        resp.raise_for_status()
                        output_path.write_bytes(resp.content)
                        saved_path = output_path
                        entry["file_size_bytes"] = len(resp.content)
                except Exception as download_err:
                    logger.error(f"Failed to download edited image: {download_err}")
                    entry["error"] = f"download_failed: {download_err}"
            else:
                entry["error"] = "no_image_content"

            if saved_path:
                entry["saved_path"] = str(saved_path)
                blob_url = self._upload_to_blob(saved_path)
                if blob_url:
                    entry["blob_url"] = blob_url
                    artifact_record: Dict[str, Any] = {
                        "artifact-uri": blob_url,
                        "file-name": saved_path.name,
                        "storage-type": "azure_blob",
                        "status": "stored",
                        "provider-response-id": entry["response_id"],
                        "provider-image-call-id": entry.get("image_call_id"),
                        "provider": "openai",
                        "model": model,
                        # Don't assign role - edited images are distinct artifacts, not editing inputs
                        # They should all be displayed, not deduplicated
                    }
                    artifact_record["local-path"] = str(saved_path)
                    if entry.get("file_size_bytes") is not None:
                        artifact_record["file-size"] = entry["file_size_bytes"]
                    if entry.get("source_url"):
                        artifact_record["source-url"] = entry["source_url"]
                    logger.info(f"🖼️ [GEN] Created artifact_record: file={artifact_record.get('file-name')}, has_role={'role' in artifact_record}, keys={list(artifact_record.keys())}")
                    generated_artifacts.append(artifact_record)

            images.append(entry)

        if generated_artifacts:
            self._latest_artifacts.extend(generated_artifacts)

        response_id = images[0].get("response_id") if images else (download_errors[0] if download_errors else None)

        result: Dict[str, Any] = {
            "status": "success" if images else "error",
            "images": images,
            "created": datetime.utcnow().isoformat(),
            "model": model,
            "response_id": response_id,
            "image_call_id": images[0].get("image_call_id") if images else None,
            "provider": "openai",
        }

        if download_errors:
            result["warnings"] = download_errors

        return result

    def _ensure_png(self, raw_bytes: bytes) -> bytes:
        if not raw_bytes:
            raise ValueError("Empty image payload cannot be processed")

        try:
            with Image.open(BytesIO(raw_bytes)) as img:
                # Pillow lazily decodes; ensure load succeeds
                img.load()

                if img.mode not in ("RGB", "RGBA", "L"):
                    img = img.convert("RGBA" if "A" in img.mode else "RGB")

                output = BytesIO()
                img.save(output, format="PNG")
                return output.getvalue()
        except UnidentifiedImageError as exc:
            raise ValueError(f"Attachment is not a recognizable image: {exc}")
        except Exception as exc:
            raise ValueError(f"Failed to normalize image bytes: {exc}")

    def _write_temp_png(self, png_bytes: bytes) -> str:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.write(png_bytes)
        tmp.flush()
        tmp.close()
        logger.debug("Wrote temp PNG for edit: %s", tmp.name)
        return tmp.name

    def _extract_first_attachment_uri(self, attachments: List[Dict[str, Any]]) -> Optional[str]:
        for part in attachments:
            file_info = part.get("file") or {}
            uri = file_info.get("uri")
            if uri and str(uri).lower().startswith(("http://", "https://")):
                return uri
        return None

    @staticmethod
    def _payload_has_mask(payload: Dict[str, Any]) -> bool:
        if not payload:
            return False
        if payload.get("mask_url") or payload.get("mask_image_url"):
            return True
        attachments = payload.get("attachments") or payload.get("files") or []
        for part in attachments:
            file_info = part.get("file") if isinstance(part, dict) else None
            if not file_info:
                continue
            role_val = (file_info.get("role") or (file_info.get("metadata") or {}).get("role") or "").lower()
            name_val = str(file_info.get("name", "")).lower()
            if role_val == "mask" or "_mask" in name_val or name_val.endswith("-mask.png"):
                return True
        return False

    @staticmethod
    def _payload_has_overlay(payload: Dict[str, Any]) -> bool:
        if not payload:
            return False
        attachments = payload.get("attachments") or payload.get("files") or []
        for part in attachments:
            file_info = part.get("file") if isinstance(part, dict) else None
            if not file_info:
                continue
            role_val = (file_info.get("role") or (file_info.get("metadata") or {}).get("role") or "").lower()
            name_val = str(file_info.get("name", "")).lower()
            if role_val == "overlay" or "logo" in name_val or name_val.endswith(".png"):
                # treat any non-base, non-mask image as overlay when explicitly tagged
                if role_val == "overlay" or ("_base" not in name_val and "-base" not in name_val and "mask" not in name_val):
                    return True
        return False

    @staticmethod
    def _extract_attachment_uri_by_role(
        attachments: List[Dict[str, Any]],
        role: str,
    ) -> Optional[str]:
        role_lower = role.lower()
        base_fallback: List[Tuple[str, str]] = []  # (uri, name)
        for part in attachments:
            file_info = part.get("file") or {}
            uri = file_info.get("uri")
            name = str(file_info.get("name", "")).lower()
            file_role = (
                str(file_info.get("role", ""))
                or str(file_info.get("mimeRole", ""))
                or str(file_info.get("role" if "role" in file_info else ""))
            ).lower()

            metadata = file_info.get("metadata") or {}
            meta_role = str(metadata.get("role", "")).lower()

            is_match = False
            if file_role == role_lower or meta_role == role_lower:
                is_match = True
            elif role_lower == "mask" and "mask" in name:
                is_match = True
            elif role_lower == "base" and "mask" not in name and file_role != "mask" and meta_role != "mask":
                # Remember non-mask candidates for fallback once explicit base patterns are checked
                if uri and str(uri).lower().startswith(("http://", "https://")):
                    base_fallback.append((uri, name))
                # Prefer files that look like base assets
                if "_base" in name or name.endswith("-base.png") or name.endswith("_base.png"):
                    is_match = True

            if is_match and uri and str(uri).lower().startswith(("http://", "https://")):
                return uri

        if role_lower == "base":
            for uri, name in base_fallback:
                if "mask" in name:
                    continue
                return uri

        return None

    def pop_latest_artifacts(self) -> List[Dict[str, Any]]:
        artifacts = self._latest_artifacts
        self._latest_artifacts = []
        return artifacts

    def _upload_to_blob(self, file_path: Path) -> Optional[str]:
        """Upload the given file to Azure Blob Storage and return the blob URL."""
        blob_client = self._get_blob_service_client()
        if not blob_client:
            return None

        container_name = os.getenv("AZURE_BLOB_CONTAINER", "a2a-files")
        blob_size_threshold = int(os.getenv("AZURE_BLOB_SIZE_THRESHOLD", "8048576"))
        force_blob = os.getenv("FORCE_AZURE_BLOB", "false").lower() == "true"

        try:
            file_size = file_path.stat().st_size
            if not force_blob and file_size < blob_size_threshold:
                logger.info(
                    "File %s below blob size threshold (%s); skipping upload",
                    file_path,
                    blob_size_threshold,
                )
                return None
        except FileNotFoundError:
            logger.error(f"File not found for blob upload: {file_path}")
            return None

        blob_name = f"image-generator/{uuid.uuid4().hex}/{file_path.name}"
        try:
            container_client = blob_client.get_container_client(container_name)
            if not container_client.exists():
                container_client.create_container()
            with open(file_path, "rb") as data:
                container_client.upload_blob(name=blob_name, data=data, overwrite=True)

            sas_duration_minutes = int(
                os.getenv("AZURE_BLOB_SAS_DURATION_MINUTES", str(24 * 60))
            )

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
                            expiry=datetime.utcnow() + timedelta(minutes=sas_duration_minutes),
                            protocol="https",
                            version="2023-11-03",
                        )
                    except Exception as sas_error:
                        logger.error(f"Failed to generate SAS URL with shared key: {sas_error}")

            if sas_token is None and self._blob_service_client is not None:
                try:
                    delegation_key = self._blob_service_client.get_user_delegation_key(
                        key_start_time=datetime.utcnow() - timedelta(minutes=5),
                        key_expiry_time=datetime.utcnow() + timedelta(minutes=sas_duration_minutes),
                    )
                    sas_token = generate_blob_sas(
                        account_name=self._blob_service_client.account_name,
                        container_name=container_name,
                        blob_name=blob_name,
                        user_delegation_key=delegation_key,
                        permission=BlobSasPermissions(read=True),
                        expiry=datetime.utcnow() + timedelta(minutes=sas_duration_minutes),
                        version="2023-11-03",
                    )
                except Exception as ude_err:
                    logger.warning(f"Failed to generate user delegation SAS: {ude_err}")

            if sas_token:
                base_url = blob_client.get_blob_client(container=container_name, blob=blob_name).url
                token = sas_token.lstrip("?")
                separator = '&' if '?' in base_url else '?'
                return f"{base_url}{separator}{token}"

            raise RuntimeError("Unable to generate SAS token for blob upload; verify storage credentials")
        except Exception as e:
            logger.error(f"Failed to upload {file_path} to blob storage: {e}")
            return None




async def create_foundry_image_generator_agent() -> FoundryImageGeneratorAgent:
    """Factory function to create and initialize a Foundry Image Generator agent."""
    agent = FoundryImageGeneratorAgent()
    await agent.create_agent()
    return agent


# Example usage for testing
async def demo_agent_interaction():
    """Demo function showing how to use the Foundry Image Generator agent for creative prompts."""
    agent = await create_foundry_image_generator_agent()
    
    try:
        thread = await agent.create_thread()
        message = "Generate a surreal landscape with floating islands and waterfalls."
        print(f"\nUser: {message}")
        async for response in agent.run_conversation_stream(thread.id, message):
            print(f"Assistant: {response}")
    finally:
        logger.info("Demo completed - agent preserved for reuse")


if __name__ == "__main__":
    asyncio.run(demo_agent_interaction())