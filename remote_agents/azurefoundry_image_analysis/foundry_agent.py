"""
AI Foundry Image Analysis Agent implementation for comprehensive image analysis workflows.
Adapted from the ADK agent pattern to work with Azure AI Foundry and Azure OpenAI GPT-4o vision for image understanding, damage assessment, object detection, and scene analysis.

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
# Vision analysis is handled by Azure AI Foundry Agent with GPT-4o
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.core.credentials import AzureNamedKeyCredential, AzureSasCredential
from a2a.types import Part, DataPart
from a2a.utils.message import new_agent_parts_message
from io import BytesIO
import httpx
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)


class FoundryImageAnalysisAgent:
    """
    AI Foundry Image Analysis Agent for comprehensive image understanding and analysis.
    This class adapts the ADK agent pattern for Azure AI Foundry with focus on analyzing images
    using Azure OpenAI GPT-4o vision for damage assessment, object detection, scene understanding, and text extraction.
    """
    
    # Class-level shared resources for reference document search (created once)
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
        self._blob_service_client: Optional[BlobServiceClient] = None
        self._latest_artifacts: List[Dict[str, Any]] = []
        self._pending_file_refs_by_thread: Dict[str, List[Dict[str, Any]]] = {}

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
        async with FoundryImageAnalysisAgent._file_search_setup_lock:
            if FoundryImageAnalysisAgent._shared_file_search_tool is not None:
                logger.info("Reusing existing shared file search tool")
                return FoundryImageAnalysisAgent._shared_file_search_tool
            
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
                        FoundryImageAnalysisAgent._shared_uploaded_files.append(file.id)
                        logger.info(f"Uploaded file: {os.path.basename(file_path)} (ID: {file.id})")
                    except Exception as e:
                        logger.warning(f"Failed to upload {file_path}: {e}")
                
                if not file_ids:
                    logger.warning("No files were successfully uploaded")
                    return None
                
                # Create vector store ONCE using project client
                logger.info("Creating shared vector store with uploaded files...")
                FoundryImageAnalysisAgent._shared_vector_store = project_client.agents.vector_stores.create_and_poll(
                    file_ids=file_ids, 
                    name="image-generator-vectorstore"
                )
                logger.info(f"Created shared vector store: {FoundryImageAnalysisAgent._shared_vector_store.id}")
                
                # Create file search tool ONCE
                file_search = FileSearchTool(vector_store_ids=[FoundryImageAnalysisAgent._shared_vector_store.id])
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
                FoundryImageAnalysisAgent._shared_file_search_tool = file_search
                logger.info("Cached shared file search tool for future use")
                    
                return file_search
                    
            except Exception as e:
                logger.error(f"Error setting up file search: {e}")
                return None
        
    async def create_agent(self) -> Agent:
        """Create the AI Foundry agent with optional web search and style document search capabilities."""
        if self.agent:
            logger.info("Image analysis agent already exists, returning existing instance")
            return self.agent
        
        tools = []
        tool_resources = None
        
        project_client = self._get_project_client()
        
        # Image analysis is handled natively by GPT-4o vision
        # No custom tools needed - the model analyzes images attached to thread messages automatically

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
                name="foundry-image-analyzer",
                instructions=self._get_agent_instructions(),
                tools=tools if tools else []
            )
            if tool_resources:
                agent_kwargs["tool_resources"] = tool_resources
            self.agent = project_client.agents.create_agent(**agent_kwargs)
        
        logger.info(f"Created AI Foundry agent: {self.agent.id}")
        return self.agent
    
    def _get_agent_instructions(self) -> str:
        """Get the agent instructions for image analysis and visual understanding."""
        return f"""
You are an Azure AI Foundry image analysis agent powered by Azure OpenAI GPT-4o vision.

Your mission is to analyze images provided by users and deliver comprehensive insights including damage assessment, object detection, scene understanding, quality inspection, and text extraction using advanced computer vision capabilities.

## Core Responsibilities

1. **Damage Assessment**: Identify and describe visible damage in vehicles, properties, or objects. Assess severity, location, and potential causes.
2. **Object Detection**: Recognize and catalog all significant objects, vehicles, structures, or items visible in the image.
3. **Scene Understanding**: Provide detailed descriptions of the overall scene, environment, context, lighting, and atmospheric conditions.
4. **Quality Inspection**: Evaluate the condition, quality, maintenance state, and wear/tear of items or structures shown.
5. **Text Extraction**: Read and extract any visible text, labels, signs, license plates, VINs, or documents in the image.
6. **Contextual Analysis**: Understand spatial relationships, identify safety hazards, and provide relevant observations.

## How to Handle Requests

- When images are attached to messages, automatically analyze them using your vision capabilities
- Carefully consider the user's question or request about the image
- Reference documents in `documents/` for reference guidelines, standards, or assessment criteria when helpful
- Provide detailed, structured analysis based on what you observe in the image
- Be factual and specific - avoid speculation, but note when additional information would be beneficial
- For damage assessment, describe location, extent, type, and severity
- For object detection, list all significant items with their positions and characteristics
- If the user asks about an image but none is attached, politely ask them to provide the image

## Response Template
```
🔍 IMAGE ANALYSIS RESULTS

**Analysis Type**: <damage assessment / object detection / scene understanding / quality inspection / text extraction>
**Key Findings**: <bulleted list of main observations>
**Detailed Analysis**: <comprehensive description>
**Recommendations**: <if applicable: next steps, additional views needed, concerns>
```

Current date and time: {datetime.now().isoformat()}

Always provide thorough, accurate analysis based on visible evidence in the image.
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
    
    async def send_message(self, thread_id: str, content: str, role: str = "user", attachments: Optional[List[Dict[str, Any]]] = None) -> ThreadMessage:
        """Send a message to the conversation thread, optionally with image attachments for vision analysis."""
        client = self._get_client()
        
        # Check if there are pending attachments for this thread (images to analyze)
        if attachments is None and thread_id in self._pending_file_refs_by_thread:
            attachments = self._pending_file_refs_by_thread.get(thread_id, [])
        
        # If we have attachments (images), format the message content for GPT-4o vision
        if attachments:
            logger.info(f"Attaching {len(attachments)} file(s) to message in thread {thread_id}")
            
            # Build content array with text and image URLs for vision
            content_parts = [{"type": "text", "text": content}]
            
            for attachment in attachments:
                file_info = attachment.get("file", {}) if isinstance(attachment, dict) else {}
                uri = file_info.get("uri")
                
                if uri:
                    logger.info(f"Adding image to message: {uri[:100]}...")
                    # Add image_url part for GPT-4o vision
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": uri}
                    })
            
            message = client.messages.create(
                thread_id=thread_id,
                role=role,
                content=content_parts  # Array format for vision
            )
        else:
            # No attachments, send text only
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
            logger.info(f"📎 Received {len(attachments)} attachment(s) for vision analysis in thread {thread_id}")

        await self.ensure_thread_ready(thread_id)
        # Send message with attachments if available (for GPT-4o vision)
        await self.send_message(thread_id, user_message, attachments=attachments)
        client = self._get_client()
        logger.info(f"🚀 Creating run for thread {thread_id} with agent {self.agent.id}")
        run = client.runs.create(thread_id=thread_id, agent_id=self.agent.id)
        logger.info(f"📊 Run created: id={run.id}, initial_status={run.status}")

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

        # After run is complete, yield the assistant's response(s) with citation formatting
        logger.info(f"🏁 Run completed with status={run.status} after {iterations} iterations")
        messages = list(client.messages.list(thread_id=thread_id, order=ListSortOrder.ASCENDING))
        logger.info(f"📨 Retrieved {len(messages)} messages from thread")
        assistant_response_found = False
        for msg in reversed(messages):
            logger.info(f"📝 Checking message: role={msg.role}, has_content={bool(msg.content)}")
            if msg.role == "assistant" and msg.content:
                assistant_response_found = True
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
                        logger.info(f"✅ Yielding assistant response ({len(formatted_response)} chars)")
                        yield formatted_response
                break
        
        # If no assistant response was found, log a warning
        if not assistant_response_found:
            logger.warning(f"⚠️ No assistant response found in {len(messages)} messages!")
            for msg in messages:
                logger.warning(f"  - Message role={msg.role}, content={bool(msg.content)}")
            yield "Error: No response received from the image analysis agent"
    
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
                
                # Image analysis is handled natively by Azure AI Foundry + GPT-4o vision
                # No custom tool calls needed - images in thread messages are automatically analyzed
                if function_name == "analyze_image_deprecated":
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
                            "Thread %s received %d attachment(s) for tool call",
                            thread_id,
                            len(pending_attachments),
                        )
                        for idx, attachment in enumerate(pending_attachments):
                            file_info = attachment.get("file") or {}
                            logger.info(
                                "  Attachment[%d]: name=%s role=%s uri=%s bytes=%s",
                                idx,
                                file_info.get("name"),
                                (file_info.get("role")
                                 or (file_info.get("metadata") or {}).get("role")),
                                file_info.get("uri"),
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
                                "Normalized image_url from base attachment for thread %s -> %s",
                                thread_id,
                                base_uri,
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
                                "Normalized mask_url from mask attachment for thread %s -> %s",
                                thread_id,
                                mask_uri,
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
                        openai_result = self._analyze_image_via_azure_openai(payload)
                        if openai_result is not None:
                            openai_result["tool_call_id"] = getattr(tool_call, "id", None)
                            output_payload = json.dumps(openai_result)
                        else:
                            output_payload = json.dumps({"status": "error", "message": "Image analysis returned no result"})
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

    def _supports_vision(self) -> bool:
        """Check if the current model supports vision (GPT-4o, GPT-4 Turbo with vision)."""
        model = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "")
        vision_models = ["gpt-4o", "gpt-4-turbo", "gpt-4-vision"]
        return any(vision_model in model.lower() for vision_model in vision_models)

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

    def _extract_first_attachment_uri(self, attachments: List[Dict[str, Any]]) -> Optional[str]:
        """Extract the first URI from attachments - useful for getting image URLs from A2A messages."""
        for part in attachments:
            file_info = part.get("file") or {}
            uri = file_info.get("uri")
            if uri and str(uri).lower().startswith(("http://", "https://")):
                return uri
        return None

    def pop_latest_artifacts(self) -> List[Dict[str, Any]]:
        """Return and clear any artifacts. For analysis agent, this typically returns empty."""
        # Image analysis doesn't generate artifacts like image generation does
        # This method is kept for compatibility with the executor
        return []


# ===== Factory Functions ===== #

async def create_foundry_image_analysis_agent() -> FoundryImageAnalysisAgent:
    """Factory function to create and initialize a Foundry Image Analysis agent."""
    agent = FoundryImageAnalysisAgent()
    await agent.create_agent()
    return agent


# Example usage for testing
async def demo_agent_interaction():
    """Demo function showing how to use the Foundry Image Analysis agent for analyzing images."""
    agent = await create_foundry_image_analysis_agent()
    
    try:
        thread = await agent.create_thread()
        message = "Analyze this image and identify any visible damage or issues."
        print(f"\nUser: {message}")
        async for response in agent.run_conversation_stream(thread.id, message):
            print(f"Assistant: {response}")
    finally:
        logger.info("Demo completed - agent preserved for reuse")


if __name__ == "__main__":
    asyncio.run(demo_agent_interaction())

