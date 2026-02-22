"""
Foundry Host Agent - Multi-Agent Orchestration with Azure AI Foundry

This module implements the core host agent that coordinates multiple specialized remote agents
using the Agent-to-Agent (A2A) protocol. It provides:
- Multi-agent workflow orchestration with dynamic task decomposition
- Integration with Azure AI Foundry for LLM-powered coordination
- Real-time WebSocket streaming for UI updates
- Memory service for cross-conversation context
- File handling with Azure Blob Storage support
- Comprehensive error handling and retry logic

The host agent acts as an intelligent orchestrator that:
1. Receives user requests
2. Analyzes which specialized agents can help
3. Coordinates parallel or sequential agent execution
4. Synthesizes responses from multiple agents
5. Maintains conversation context across interactions
"""

import asyncio
import ast
import base64
import re
import json
import uuid
import os
import sys
import logging
import time
import contextvars
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Iterable, Literal

# Context variable for async-safe context_id tracking
# This replaces the race-condition-prone self._current_host_context_id
_current_context_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('current_context_id', default=None)
# Tracks a unique ID for each parallel send_message call so the frontend can show separate step cards
_current_parallel_call_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('parallel_call_id', default=None)
import httpx
from dotenv import load_dotenv

# OpenTelemetry for distributed tracing and monitoring
from opentelemetry import trace
from azure.monitor.opentelemetry import configure_azure_monitor

# Azure authentication - supports multiple credential types for flexibility
from azure.identity import DefaultAzureCredential, ChainedTokenCredential, AzureCliCredential, ManagedIdentityCredential, EnvironmentCredential, ClientSecretCredential

# Azure AI Projects Client - for connecting to Azure AI Foundry
from azure.ai.projects.aio import AIProjectClient

# Note: We use the OpenAI SDK's Responses API directly (openai_client.responses.create)
# Tools are defined as dicts in OpenAI format, not azure-ai-projects models

# A2A Protocol SDK for agent-to-agent communication
from a2a.client import A2ACardResolver
from a2a.types import (
    AgentCard,
    Artifact,
    DataPart,
    FilePart,
    FileWithBytes,
    FileWithUri,
    Message,
    MessageSendConfiguration,
    MessageSendParams,
    Part,
    Task,
    TaskState,
    TextPart,
)

# Internal modules for agent coordination and data processing
from .remote_agent_connection import RemoteAgentConnections, TaskUpdateCallback, TaskCallbackArg
from .a2a_memory_service import a2a_memory_service
from .a2a_document_processor import a2a_document_processor

# Extracted models and parsers (refactored from this file)
from .models import (
    SessionContext,
    AgentModeTask,
    AgentModePlan,
    NextStep,
)
from .tool_context import DummyToolContext
from .utils import (
    get_context_id,
    get_message_id,
    get_task_id,
    normalize_env_bool,
    normalize_env_int,
)
from .instructions import (
    build_agent_mode_instruction,
    build_orchestrator_instruction,
    apply_custom_instruction,
)
from .core import (
    EventEmitters,
    AgentRegistry,
    StreamingHandlers,
    MemoryOperations,
    AzureClients,
    WorkflowOrchestration,
)
from pydantic import BaseModel, Field

# Tenant utilities for multi-tenancy support
from utils.tenant import get_tenant_from_context
# File parts utilities for standardized artifact handling
from utils.file_parts import (
    extract_uri,
    extract_filename,
    extract_mime_type,
    create_file_part,
    is_file_part,
    is_image_part,
    extract_all_images,
    convert_artifact_dict_to_file_part,
)
# Chat history persistence
from service.chat_history_service import add_message as persist_message, create_conversation
import time

# Load environment configuration from project root
ROOT_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(dotenv_path=ROOT_ENV_PATH, override=False)

# Ensure logging utilities are accessible
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from log_config import log_debug, log_info, log_success, log_warning, log_error, log_foundry_debug

logger = logging.getLogger(__name__)

# Configure distributed tracing with Azure Application Insights
application_insights_connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
if application_insights_connection_string:
    configure_azure_monitor(connection_string=application_insights_connection_string)
tracer = trace.get_tracer(__name__)


def _build_persist_parts(final_responses) -> list:
    """Build parts array for chat history persistence, including both text and file parts.

    Extracts text from string responses and FilePart metadata from Message objects
    so that images/videos are preserved in chat history across page refreshes.
    """
    parts = []

    # Collect text from string responses
    text_responses = [r for r in final_responses if isinstance(r, str)]
    response_text = "\n\n".join(text_responses) if text_responses else ""
    if response_text:
        parts.append({"kind": "text", "text": response_text})

    # Collect FileParts from Message objects in final_responses
    for resp in final_responses:
        if hasattr(resp, 'parts') and hasattr(resp, 'role'):  # It's a Message object
            for part in resp.parts:
                fp = getattr(part, 'root', part) if hasattr(part, 'root') else part
                file_obj = getattr(fp, 'file', None)
                if file_obj:
                    uri = str(getattr(file_obj, 'uri', ''))
                    if uri.startswith(('http://', 'https://')):
                        file_entry = {
                            "kind": "file",
                            "file": {
                                "uri": uri,
                                "name": getattr(file_obj, 'name', 'artifact'),
                                "mimeType": getattr(file_obj, 'mime_type', None) or getattr(file_obj, 'mimeType', 'application/octet-stream')
                            }
                        }
                        # Preserve metadata (e.g. role='mask') for proper rendering after refresh
                        fp_meta = getattr(fp, 'metadata', None)
                        if fp_meta:
                            file_entry["metadata"] = fp_meta if isinstance(fp_meta, dict) else dict(fp_meta)
                        parts.append(file_entry)
                # Also persist DataParts (e.g. video_metadata for remix functionality)
                elif hasattr(fp, 'data') and isinstance(getattr(fp, 'data', None), dict):
                    parts.append({"kind": "data", "data": fp.data})

    return parts


# Note: SessionContext, AgentModeTask, AgentModePlan, NextStep
# have been extracted to models.py
# 
# Utility functions (get_context_id, get_message_id, get_task_id, normalize_env_bool,
# normalize_env_int) have been extracted to utils.py
#
# Event emitter methods (_emit_*) have been extracted to event_emitters.py
#
# Agent registry methods have been extracted to agent_registry.py
#
# Azure client methods (_ensure_project_client, _init_azure_blob_client, _get_auth_headers,
# _get_openai_endpoint, etc.) have been extracted to azure_clients.py


class FoundryHostAgent2(EventEmitters, AgentRegistry, StreamingHandlers, MemoryOperations, AzureClients, WorkflowOrchestration):
    def __init__(
        self,
        remote_agent_addresses: List[str],
        http_client: httpx.AsyncClient,
        task_callback: Optional[TaskUpdateCallback] = None,
        enable_task_evaluation: bool = False,
        create_agent_at_startup: bool = True,  # Changed back: Using Foundry Agent Service
    ):
        """
        Initialize the Foundry Host Agent with Azure AI Foundry Agent Service backend.
        
        Args:
            remote_agent_addresses: List of remote agent URLs to connect to
            http_client: Shared HTTP client for agent communication
            task_callback: Optional callback for task status updates
            enable_task_evaluation: Whether to evaluate task completion quality
            create_agent_at_startup: Create agent in Azure AI Foundry at startup (enables portal visibility)
        """
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        
        try:
            log_foundry_debug("Initializing Azure AI Foundry Agent Service...")
            log_debug("[INIT] TIP: If you see authentication errors, run 'python test_azure_auth.py' to diagnose")
            
            from azure.identity.aio import AzureCliCredential, DefaultAzureCredential, ManagedIdentityCredential
            
            # Detect if we're running in Azure Container Apps (managed identity)
            is_azure_container = os.environ.get('CONTAINER_APP_NAME') or os.environ.get('WEBSITE_INSTANCE_ID')
            
            if is_azure_container:
                # Use DefaultAzureCredential in Azure (will use managed identity)
                log_foundry_debug("Running in Azure Container Apps - using DefaultAzureCredential (Managed Identity)")
                self.credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
                log_foundry_debug("Using DefaultAzureCredential for managed identity")
            else:
                # Use AzureCliCredential locally
                cli_credential = AzureCliCredential(process_timeout=5)
                self.credential = cli_credential
                log_foundry_debug("Using AzureCliCredential for local development")
                    
        except Exception as e:
            log_foundry_debug(f"Credential initialization failed: {e}")
            log_debug("Falling back to DefaultAzureCredential only")
            from azure.identity.aio import DefaultAzureCredential
            self.credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
            log_foundry_debug("Using DefaultAzureCredential as fallback")
        
        # Initialize Azure AI Project Client (async)
        self.project_client: Optional[AIProjectClient] = None
        self.agents_client = None  # Will be set from project_client.agents
        
        self.agent: Optional[Any] = None  # Agent object from Foundry Agent Service
        self.agent_id: Optional[str] = None
        self.task_callback = task_callback or self._default_task_callback
        self.httpx_client = http_client
        self.remote_agent_connections: Dict[str, RemoteAgentConnections] = {}
        self.cards: Dict[str, AgentCard] = {}
        self.agents: str = ''
        self.session_contexts: Dict[str, SessionContext] = {}
        
        # RESPONSES API: Store response IDs for multi-turn context chaining
        self._response_ids: Dict[str, str] = {}  # context_id -> last_response_id
        
        # Model configuration (set in create_agent)
        self.model_name: Optional[str] = None
        self.agent_instructions: Optional[str] = None
        self.agent_tools: Optional[List[Dict[str, Any]]] = None

        # Multi-endpoint model support: models can live on different Azure resources
        self._alt_endpoint = os.environ.get("AZURE_AI_ALT_ENDPOINT", "")
        self._model_endpoints = {
            "gpt-4o": "default",       # Uses primary project endpoint (simonfoundry)
            "gpt-5.2": self._alt_endpoint,  # Uses alternate endpoint
        }
        self._original_openai_client = None  # Saved ref to project client's OpenAI client
        self._alt_openai_clients = {}  # endpoint -> AsyncAzureOpenAI client cache
        
        # REMOVED: self.default_contextId = str(uuid.uuid4())
        # We NEVER want to use a UUID fallback - context_id must come from the request
        self.default_contextId = None
        self._agent_tasks: Dict[str, Optional[Task]] = {}
        self.agent_token_usage: Dict[str, dict] = {}  # Store token usage per agent
        self.host_token_usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}  # Host agent tokens
        
        self.enable_task_evaluation = enable_task_evaluation
        self._active_conversations: Dict[str, str] = {}
        self.max_retries = 2
        
        # Cancellation support: tracks which contexts have been cancelled
        # Key: context_id, Value: True if cancelled
        self._cancellation_tokens: Dict[str, bool] = {}
        # Track active A2A tasks for cancellation (context_id -> {agent_name: task_id})
        self._active_agent_tasks: Dict[str, Dict[str, str]] = {}
        # Snapshot of plan at cancel time (before current_plan is cleared)
        self._cancelled_plan_snapshots: Dict[str, dict] = {}
        # Interrupt support: queued user instructions to redirect a running workflow
        # Key: context_id, Value: new user instruction string
        self._interrupt_instructions: Dict[str, str] = {}
        
        # Configure context-sharing between agents for improved continuity
        # When enabled, agents receive information about previous agent responses
        include_flag = os.environ.get("A2A_INCLUDE_LAST_HOST_TURN", "true").strip().lower()
        self.include_last_host_turn = include_flag not in {"false", "0", "no"}
        
        # Limit context size to prevent token overflow while maintaining useful history
        self.last_host_turn_max_chars = normalize_env_int(
            os.environ.get("A2A_LAST_HOST_TURN_MAX_CHARS"),
            1500,  # Default: ~500 tokens of context
        )
        
        # Number of recent agent interactions to include in context (1-5 turns)
        self.last_host_turns = max(
            1,
            min(
                5,
                normalize_env_int(os.environ.get("A2A_LAST_HOST_TURNS"), 1),
            ),
        )
        
        # Maximum characters for memory search summaries (PER RESULT)
        # Default 5000 chars per result - enough for full invoices, documents, and complex data
        # With top_k=2, max context injection is ~10000 chars (~2500 tokens)
        self.memory_summary_max_chars = max(
            200,
            normalize_env_int(os.environ.get("A2A_MEMORY_SUMMARY_MAX_CHARS"), 5000),
        )

        self._azure_blob_client = None
        self._init_azure_blob_client()
        # Note: Memory is no longer auto-cleared on startup to preserve file analysis status
        # Use the "Clear memory" button in the UI to manually clear when needed
        self._messages = []
        self._host_responses_sent = set()
        self._host_manager = None
        self.custom_root_instruction = None
        self._cached_token = None
        self._token_expiry = None
        self._create_agent_at_startup = create_agent_at_startup
        self._agent_registry_path = self._find_agent_registry_path()

        loop = asyncio.get_running_loop()
        loop.create_task(self.init_remote_agent_addresses(remote_agent_addresses))
        
        if self._create_agent_at_startup:
            loop.create_task(self._create_agent_at_startup_task())

    # Note: set_session_agents, _find_agent_registry_path, _load_agent_registry,
    # _save_agent_registry, _agent_card_to_dict, _update_agent_registry have been
    # extracted to agent_registry.py

    async def _create_agent_at_startup_task(self):
        """Background task to create the agent at startup with proper error handling."""
        try:
            log_debug("[INIT] Creating Azure AI Foundry agent at startup...")
            await self.create_agent()
            log_info("Azure AI Foundry agent created successfully at startup!")
        except Exception as e:
            log_error(f"Failed to create agent at startup: {e}")
            log_info("Agent will be created lazily when first conversation occurs")
            # Don't raise - allow the application to continue and create agent lazily

    def _clear_memory_on_startup(self):
        """Clear memory index automatically on startup for clean testing"""
        log_info("Auto-clearing memory index on startup...")
        try:
            success = a2a_memory_service.clear_all_interactions()
            if success:
                log_info("Memory index auto-cleared successfully")
            else:
                log_warning(f"Memory index auto-clear had no effect (may be empty)")
        except Exception as e:
            log_warning(f"Error auto-clearing memory index: {e}")
            log_debug(f"Continuing with startup...")

    def _format_tools_for_responses_api(self) -> List[Dict[str, Any]]:
        """
        Format agent tools for Responses API.
        
        Returns tools in the Responses API format for function calling.
        Uses self.agent_tools if available (which includes web_search),
        otherwise falls back to _get_tools().
        
        Returns:
            List of tool definitions in Responses API format
        """
        # Use self.agent_tools which includes web_search added in create_agent()
        if hasattr(self, 'agent_tools') and self.agent_tools:
            tools = self.agent_tools
        else:
            # Fallback to _get_tools() if agent_tools not set yet
            tools = self._get_tools()
            
        log_debug(f"[TOOLS] _format_tools_for_responses_api returning {len(tools)} tools:")
        for tool in tools:
            tool_name = tool.get('name', tool.get('type', 'unknown'))
            log_debug(f"  Tool: {tool_name}")
        return tools

    async def _create_response_with_streaming(
        self,
        user_message: str,
        context_id: str,
        session_context: SessionContext,
        tools: List[Dict[str, Any]],
        instructions: str,
        event_logger=None,
        image_urls: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Create a response using Azure AI Foundry Responses API with streaming.
        
        This is the core method for the Responses API pattern:
        - Uses openai_client.responses.create() with model, tools, instructions
        - Supports streaming for real-time UI updates
        - Handles tool calls (function calls) in a loop
        - Uses previous_response_id for multi-turn context
        - Implements retry logic for transient Azure OpenAI errors
        
        Returns:
            Dict with keys: id, text, tool_calls, status, usage
        """
        try:
            await self._ensure_project_client()
            if not self.agent:
                await self.create_agent()
            
            # Track previous response for multi-turn context
            previous_response_id = self._response_ids.get(context_id)
            
            # Stream the response
            full_text = ""
            response_id = None
            status = "completed"
            tool_calls_to_execute = []
            
            # Retry logic for transient Azure OpenAI errors
            max_retries = self.max_retries if hasattr(self, 'max_retries') else 2
            last_error = None
            
            for attempt in range(max_retries + 1):
                try:
                    # Create the streaming response using Responses API
                    # Pass instructions directly - this is supported by the OpenAI SDK!
                    # Instructions parameter overrides any agent_reference instructions
                    log_foundry_debug(f"[AZURE] Creating stream (attempt {attempt + 1}/{max_retries + 1})...")
                    log_foundry_debug(f"[AZURE] Agent: {self.agent.name if self.agent else 'None'}, Input length: {len(user_message)}")
                    log_foundry_debug(f"[AZURE] Instructions length: {len(instructions)} chars")
                    log_foundry_debug(f"[AZURE] Checking if Email Agent is in instructions: {'Email Agent'in instructions}")
                    log_foundry_debug(f"[AZURE] Tools count: {len(tools)}")

                    # Build multimodal input when images are present
                    if image_urls:
                        content_items = [{"type": "input_text", "text": user_message}]
                        for img_url in image_urls:
                            content_items.append({"type": "input_image", "image_url": img_url})
                        api_input = [{"role": "user", "content": content_items}]
                        log_foundry_debug(f"[AZURE] Using multimodal input with {len(image_urls)} image(s)")
                    else:
                        api_input = user_message

                    client_base = getattr(self.openai_client, '_base_url', getattr(self.openai_client, 'base_url', 'unknown'))
                    log_foundry_debug(f"[AZURE] responses.create() -> model={self.model_name}, client_base_url={client_base}")
                    stream = await self.openai_client.responses.create(
                        input=api_input,
                        previous_response_id=previous_response_id,
                        instructions=instructions,
                        model=self.model_name,
                        tools=tools,
                        stream=True,
                    )
                    log_foundry_debug("[AZURE] Stream created successfully")
                    break  # Success, exit retry loop
                except Exception as stream_error:
                    last_error = stream_error
                    error_str = str(stream_error).lower()
                    
                    # Check if this is a retryable error
                    is_retryable = any(keyword in error_str for keyword in [
                        'rate limit', 'throttl', 'overload', 'capacity', 'timeout',
                        'connection', 'temporarily', 'retry', '429', '503', '504', '500',
                        'an error occurred while processing'  # Generic Azure error
                    ])
                    
                    if is_retryable and attempt < max_retries:
                        wait_time = (2 ** attempt) + 1  # Exponential backoff: 2s, 3s, 5s
                        log_error(f"Azure OpenAI error (attempt {attempt + 1}/{max_retries + 1}), retrying in {wait_time}s: {stream_error}")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        log_error(f"Error creating stream (attempt {attempt + 1}/{max_retries + 1}): {stream_error}")
                        return {
                            "id": None,
                            "text": f"I apologize, but I encountered an error processing your request: {str(stream_error)}",
                            "tool_calls": [],
                            "status": "failed",
                            "usage": None
                        }
            else:
                # All retries exhausted
                log_error(f"All {max_retries + 1} attempts failed for Azure OpenAI request")
                return {
                    "id": None,
                    "text": f"I apologize, but I encountered a persistent error after {max_retries + 1} attempts: {str(last_error)}",
                    "tool_calls": [],
                    "status": "failed",
                    "usage": None
                }
            
            # Process the streaming response with retry for mid-stream failures
            stream_retry_count = 0
            max_stream_retries = 2
            event_count = 0
            
            log_foundry_debug(f"[AZURE] Starting stream processing...")
            while stream_retry_count <= max_stream_retries:
                try:
                    async for event in stream:
                        event_count += 1
                        event_type = event.type
                        
                        if event_count <= 3 or event_count % 10 == 0:
                            log_foundry_debug(f"[AZURE] Event {event_count}: {event_type}")
                        
                        if event_type == "response.created":
                            response_id = event.response.id
                            self._response_ids[context_id] = response_id  # Track for multi-turn
                            log_debug(f"Response created: {response_id}")
                            log_foundry_debug(f"[AZURE] Response created: {response_id}")
                        
                        elif event_type == "response.output_text.delta":
                            chunk = event.delta
                            if chunk:
                                full_text += chunk
                                await self._emit_text_chunk(chunk, context_id)
                        
                        elif event_type == "response.output_item.done":
                            # Check for function call outputs
                            if hasattr(event, 'item') and event.item.type == "function_call":
                                tool_call = event.item
                                tool_calls_to_execute.append(tool_call)
                                log_debug(f"[FUNCTION CALL] name={tool_call.name}, arguments={tool_call.arguments}")
                        
                        elif event_type == "response.completed":
                            log_debug(f"Response completed")
                            break
                        
                        elif event_type == "error":
                            log_error(f"Stream error: {event}")
                            status = "failed"
                            break
                    
                    # Successfully processed stream, exit retry loop
                    break
                            
                except Exception as stream_proc_error:
                    stream_retry_count += 1
                    error_str = str(stream_proc_error).lower()
                    
                    # DEBUG: Print full exception details
                    log_foundry_debug(f"[AZURE] Stream exception type: {type(stream_proc_error).__name__}")
                    log_foundry_debug(f"[AZURE] Stream exception: {stream_proc_error}")
                    if hasattr(stream_proc_error, 'response'):
                        log_foundry_debug(f"[AZURE] Response status: {stream_proc_error.response.status_code if hasattr(stream_proc_error.response, 'status_code') else 'N/A'}")
                    if hasattr(stream_proc_error, 'body'):
                        log_foundry_debug(f"[AZURE] Response body: {stream_proc_error.body}")
                    
                    # Check if this is a retryable error
                    is_retryable = any(keyword in error_str for keyword in [
                        'rate limit', 'throttl', 'overload', 'capacity', 'timeout',
                        'connection', 'temporarily', 'retry', '429', '503', '504', '500',
                        'an error occurred while processing'  # Generic Azure error
                    ])
                    
                    if is_retryable and stream_retry_count <= max_stream_retries:
                        wait_time = (2 ** stream_retry_count) + 1
                        log_error(f"Stream processing error (attempt {stream_retry_count}/{max_stream_retries + 1}), retrying in {wait_time}s: {stream_proc_error}")
                        await asyncio.sleep(wait_time)
                        
                        # Need to recreate the stream for retry
                        try:
                            stream = await self.openai_client.responses.create(
                                input=user_message,
                                previous_response_id=previous_response_id,
                                extra_body={"agent": {"name": self.agent.name, "type": "agent_reference"}},
                                stream=True,
                            )
                            # Reset state for new stream
                            full_text = ""
                            tool_calls_to_execute = []
                            continue
                        except Exception as retry_error:
                            log_error(f"Failed to create retry stream: {retry_error}")
                            # Fall through to handle as non-retryable
                    
                    log_error(f"Error processing stream: {stream_proc_error}")
                    if full_text:
                        return {
                            "id": response_id,
                            "text": full_text,
                            "tool_calls": [],
                            "status": "completed",
                            "usage": None
                        }
                    # Return a user-friendly error instead of raising
                    return {
                        "id": None,
                        "text": f"I apologize, but I encountered a temporary error communicating with Azure. Please try again in a moment.",
                        "tool_calls": [],
                        "status": "failed",
                        "usage": None
                    }

            # MULTI-TURN TOOL EXECUTION LOOP
            max_tool_iterations = 30
            tool_iteration = 0
            
            while tool_calls_to_execute and tool_iteration < max_tool_iterations:
                tool_iteration += 1
                log_debug(f"Tool iteration {tool_iteration}: {len(tool_calls_to_execute)} calls")
                
                # Execute tool calls — send_message calls run in parallel, others sequential
                tool_outputs = []
                send_message_calls = []
                other_calls = []
                for tc in tool_calls_to_execute:
                    if tc.name in ("send_message", "send_message_sync"):
                        send_message_calls.append(tc)
                    else:
                        other_calls.append(tc)

                # Parallel execution for send_message calls
                if len(send_message_calls) > 1:
                    log_debug(f"Executing {len(send_message_calls)} send_message calls in parallel")
                    for tc in send_message_calls:
                        asyncio.create_task(self._emit_granular_agent_event(
                            "foundry-host-agent", f"🛠️ Calling: {tc.name}", context_id,
                            event_type="tool_call", metadata={"tool_name": tc.name}
                        ))

                    async def _run_parallel_call(call_id, tool_call):
                        """Wrapper that sets parallel_call_id contextvar for this coroutine's context."""
                        _current_parallel_call_id.set(call_id)
                        return await self._execute_single_tool_call(
                            tool_call.name, tool_call.arguments, context_id, session_context
                        )

                    parallel_tasks = []
                    for tc in send_message_calls:
                        parallel_tasks.append((tc, _run_parallel_call(tc.call_id, tc)))

                    results = await asyncio.gather(
                        *[task for _, task in parallel_tasks],
                        return_exceptions=True
                    )

                    for (tc, _), result in zip(parallel_tasks, results):
                        if isinstance(result, Exception):
                            log_error(f"Parallel tool execution error: {result}")
                            tool_outputs.append({
                                "tool_call_id": tc.call_id,
                                "output": f"Error: {str(result)}"
                            })
                        else:
                            tool_outputs.append({
                                "tool_call_id": tc.call_id,
                                "output": str(result)
                            })
                else:
                    # Single send_message or none — add to other_calls for sequential execution
                    other_calls = send_message_calls + other_calls

                # Sequential execution for non-send_message calls (and single send_message)
                for tool_call in other_calls:
                    asyncio.create_task(self._emit_granular_agent_event(
                        "foundry-host-agent", f"🛠️ Calling: {tool_call.name}", context_id,
                        event_type="tool_call", metadata={"tool_name": tool_call.name}
                    ))

                    try:
                        result = await self._execute_single_tool_call(
                            tool_call.name,
                            tool_call.arguments,
                            context_id,
                            session_context
                        )
                        tool_outputs.append({
                            "tool_call_id": tool_call.call_id,
                            "output": str(result)
                        })
                    except Exception as tool_error:
                        log_error(f"Tool execution error: {tool_error}")
                        tool_outputs.append({
                            "tool_call_id": tool_call.call_id,
                            "output": f"Error: {str(tool_error)}"
                        })
                
                # Continue the conversation with tool outputs
                tool_calls_to_execute = []
                
                # Retry logic for continuing conversation after tool calls
                continue_retry_count = 0
                max_continue_retries = 2
                
                while continue_retry_count <= max_continue_retries:
                    try:
                        # Use previous_response_id to chain responses 
                        # Tool outputs are submitted by setting input to function call outputs
                        function_call_outputs = []
                        for output in tool_outputs:
                            function_call_outputs.append({
                                "type": "function_call_output",
                                "call_id": output["tool_call_id"],
                                "output": output["output"]
                            })
                        
                        # Continue conversation with agent reference
                        continue_stream = await self.openai_client.responses.create(
                            input=function_call_outputs,  # Pass tool outputs as input
                            previous_response_id=response_id,  # Chain to previous response
                            extra_body={"agent": {"name": self.agent.name, "type": "agent_reference"}},
                            stream=True,
                        )
                        
                        async for event in continue_stream:
                            event_type = event.type
                            
                            if event_type == "response.created":
                                response_id = event.response.id
                                self._response_ids[context_id] = response_id
                            
                            elif event_type == "response.output_text.delta":
                                chunk = event.delta
                                if chunk:
                                    full_text += chunk
                                    await self._emit_text_chunk(chunk, context_id)
                            
                            elif event_type == "response.output_item.done":
                                if hasattr(event, 'item') and event.item.type == "function_call":
                                    tool_calls_to_execute.append(event.item)
                            
                            elif event_type == "response.completed":
                                break
                        
                        # Successfully processed, exit retry loop
                        break
                                
                    except Exception as continue_error:
                        continue_retry_count += 1
                        error_str = str(continue_error).lower()
                        
                        # Check if this is a retryable error
                        is_retryable = any(keyword in error_str for keyword in [
                            'rate limit', 'throttl', 'overload', 'capacity', 'timeout',
                            'connection', 'temporarily', 'retry', '429', '503', '504', '500',
                            'an error occurred while processing'  # Generic Azure error
                        ])
                        
                        if is_retryable and continue_retry_count <= max_continue_retries:
                            wait_time = (2 ** continue_retry_count) + 1
                            log_error(f"Tool continuation error (attempt {continue_retry_count}/{max_continue_retries + 1}), retrying in {wait_time}s: {continue_error}")
                            await asyncio.sleep(wait_time)
                            continue
                        
                        log_error(f"Error continuing conversation: {continue_error}")
                        break
            
            return {
                "id": response_id,
                "text": full_text,
                "tool_calls": [],
                "status": "completed",
                "usage": None
            }
            
        except Exception as e:
            log_error(f"Error in _create_response_with_streaming: {e}")
            raise

    async def _execute_single_tool_call(
        self,
        function_name: str,
        arguments_json: str,
        context_id: str,
        session_context: SessionContext
    ) -> str:
        """
        Execute a single tool call and return the result as a string.
        
        This is called from _create_response_with_streaming to handle
        function calls from the Responses API.
        
        Args:
            function_name: Name of the function to call
            arguments_json: JSON string of arguments
            context_id: Conversation context ID
            session_context: Session state
            
        Returns:
            Result as a string (JSON or plain text)
        """
        try:
            # Parse arguments
            arguments = json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
            
            if function_name in ("send_message", "send_message_sync"):
                # Call remote agent
                agent_name = arguments.get("agent_name")
                message = arguments.get("message")
                file_uris = arguments.get("file_uris")
                video_metadata = arguments.get("video_metadata")
                
                result = await self.send_message_sync(
                    agent_name=agent_name,
                    message=message,
                    file_uris=file_uris,
                    video_metadata=video_metadata
                )
                return self._format_agent_response_for_model(result, agent_name)
            
            elif function_name in ("list_remote_agents", "list_remote_agents_sync"):
                result = self.list_remote_agents_sync()
                return json.dumps(result) if not isinstance(result, str) else result
            
            elif function_name in ("search_memory", "search_memory_sync"):
                query = arguments.get("query", "")
                top_k = arguments.get("top_k", 5)
                result = await self.search_memory_sync(query=query, top_k=top_k)
                return result if isinstance(result, str) else json.dumps(result)
            
            else:
                # Unknown function - web_search is handled natively by the model
                return json.dumps({"error": f"Unknown function: {function_name}"})
                
        except Exception as e:
            log_error(f"Error executing tool {function_name}: {e}")
            return json.dumps({"error": str(e)})

    async def _execute_tool_calls_from_response(
        self,
        tool_calls: List[Dict[str, Any]],
        context_id: str,
        session_context: SessionContext,
        event_logger=None
    ) -> List[Dict[str, Any]]:
        """
        Execute tool calls from Responses API.
        
        This is a simpler version adapted for Responses API that reuses
        the tool execution logic from _handle_tool_calls.
        
        Args:
            tool_calls: List of tool calls from Responses API
            context_id: Conversation context ID
            session_context: Session state
            event_logger: Optional event logger
            
        Returns:
            List of tool outputs in format needed for next response
        """
        log_foundry_debug(f"_execute_tool_calls_from_response: Processing {len(tool_calls)} tool calls")
        
        tool_outputs = []
        
        # Separate send_message calls from other tools
        send_message_calls = []
        other_calls = []
        
        for tool_call in tool_calls:
            function_name = tool_call["function"]["name"]
            # Check for both send_message and send_message_sync (the actual function name)
            if function_name in ("send_message", "send_message_sync"):
                send_message_calls.append(tool_call)
            else:
                other_calls.append(tool_call)
        
        # Execute send_message calls in parallel (if not in agent mode)
        if send_message_calls and not session_context.agent_mode:
            log_foundry_debug(f"Executing {len(send_message_calls)} send_message calls in parallel")
            
            tasks = []
            for tool_call in send_message_calls:
                arguments = json.loads(tool_call["function"]["arguments"]) if isinstance(tool_call["function"]["arguments"], str) else tool_call["function"]["arguments"]
                
                # Create dummy tool context
                tool_context = type('obj', (object,), {'state': session_context})()
                
                # EXPLICIT FILE ROUTING: Extract file_uris and video_metadata from arguments
                file_uris = arguments.get("file_uris", None)
                video_metadata = arguments.get("video_metadata", None)
                
                task = self.send_message(
                    agent_name=arguments["agent_name"],
                    message=arguments["message"],
                    tool_context=tool_context,
                    suppress_streaming=True,
                    file_uris=file_uris,
                    video_metadata=video_metadata
                )
                tasks.append((tool_call, task))
            
            # Execute in parallel
            results = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)
            
            for i, ((tool_call, _), result) in enumerate(zip(tasks, results)):
                arguments = json.loads(tool_call["function"]["arguments"]) if isinstance(tool_call["function"]["arguments"], str) else tool_call["function"]["arguments"]
                agent_name = arguments.get("agent_name", "unknown")
                
                if isinstance(result, Exception):
                    output_str = json.dumps({"error": str(result), "agent": agent_name})
                else:
                    # Format output so GPT-4 sees file URIs for explicit routing
                    output_str = self._format_agent_response_for_model(result, agent_name)
                
                tool_outputs.append({
                    "type": "function_call_output",
                    "call_id": tool_call["id"],
                    "output": output_str
                })
        else:
            # Sequential execution for agent mode
            for tool_call in send_message_calls:
                arguments = json.loads(tool_call["function"]["arguments"]) if isinstance(tool_call["function"]["arguments"], str) else tool_call["function"]["arguments"]
                agent_name = arguments.get("agent_name", "unknown")
                
                tool_context = type('obj', (object,), {'state': session_context})()
                
                # EXPLICIT FILE ROUTING: Extract file_uris and video_metadata from arguments
                file_uris = arguments.get("file_uris", None)
                video_metadata = arguments.get("video_metadata", None)
                
                try:
                    result = await self.send_message(
                        agent_name=arguments["agent_name"],
                        message=arguments["message"],
                        tool_context=tool_context,
                        suppress_streaming=True,
                        file_uris=file_uris,
                        video_metadata=video_metadata
                    )
                    # Format output so GPT-4 sees file URIs for explicit routing
                    output_str = self._format_agent_response_for_model(result, agent_name)
                except Exception as e:
                    output_str = json.dumps({"error": str(e), "agent": agent_name})
                
                tool_outputs.append({
                    "type": "function_call_output",
                    "call_id": tool_call["id"],
                    "output": output_str
                })
        
        # Execute other tool calls sequentially
        for tool_call in other_calls:
            function_name = tool_call["function"]["name"]
            arguments = json.loads(tool_call["function"]["arguments"]) if isinstance(tool_call["function"]["arguments"], str) else tool_call["function"]["arguments"]
            
            await self._emit_tool_call_event("foundry-host-agent", function_name, arguments, context_id)
            
            if function_name == "list_remote_agents":
                output = self.list_remote_agents()
            elif function_name in ("search_memory", "search_memory_sync"):
                # Execute memory search
                try:
                    query = arguments.get("query", "")
                    top_k = arguments.get("top_k", 5)
                    output = await self.search_memory_sync(query=query, top_k=top_k)
                except Exception as e:
                    output = json.dumps({"error": str(e), "results": []})
            # Note: web_search is now handled by native BingGroundingTool
            else:
                output = {"error": f"Unknown function: {function_name}"}
            
            tool_outputs.append({
                "type": "function_call_output",
                "call_id": tool_call["id"],
                "output": json.dumps(output) if isinstance(output, dict) else output
            })
        
        log_foundry_debug(f"Tool execution complete - {len(tool_outputs)} outputs")
        return tool_outputs

    # Note: init_remote_agent_addresses, retrieve_card, register_agent_card
    # have been extracted to agent_registry.py

    async def create_agent(self) -> bool:
        """
        Create an Azure Agent Service agent with Bing Grounding support.
        
        This creates a persistent agent in Azure AI Foundry that can be used
        with the Responses API. The agent is configured with:
        - Function tools (list_remote_agents, send_message, search_memory)
        - BingGroundingAgentTool for web search
        
        The agent is then referenced in Responses API calls using:
        extra_body={"agent": {"name": agent.name, "type": "agent_reference"}}
        
        Returns:
            True if agent created successfully
        """
        if self.agent:
            log_foundry_debug(f"Agent already initialized: {self.agent.name}")
            return True
        
        log_foundry_debug(f"Creating Azure Agent Service agent...")
        log_foundry_debug(f"AZURE_AI_FOUNDRY_PROJECT_ENDPOINT = {os.environ.get('AZURE_AI_FOUNDRY_PROJECT_ENDPOINT', 'NOT SET')}")
        log_foundry_debug(f"AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME = {os.environ.get('AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME', 'NOT SET')}")
        
        # Validate required environment variables
        if not os.environ.get("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"):
            raise ValueError("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT environment variable is required")
        if not os.environ.get("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME"):
            raise ValueError("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME environment variable is required")
        
        try:
            # Ensure project client is initialized
            await self._ensure_project_client()
            
            # Import Azure AI Projects models for agent creation
            from azure.ai.projects.models import (
                BingGroundingAgentTool,
                BingGroundingSearchToolParameters,
                BingGroundingSearchConfiguration,
                PromptAgentDefinition,
                FunctionTool,
            )
            
            # Configuration — use live model if already set, else env var
            model_name = self.model_name or os.environ["AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME"]
            instructions = self.root_instruction('foundry-host-agent')
            
            log_foundry_debug(f"Agent parameters:")
            log_debug(f"- model: {model_name}")
            log_debug(f"- name: foundry-host-agent")
            log_debug(f"- instructions length: {len(instructions)}")
            
            # Get Bing connection ID
            self.bing_connection_id = os.environ.get("BING_CONNECTION_ID")
            if self.bing_connection_id:
                log_debug(f"Bing connection ID loaded: {self.bing_connection_id[:50]}...")
            else:
                log_warning(f"BING_CONNECTION_ID not set - web search disabled")
            
            # Create tools list - convert to NEW SDK FunctionTool format
            tools_list = []
            
            log_debug(f"Converting function tools to NEW SDK format...")
            # Get function definitions from _get_tools()
            # These are in Responses API format: {"type": "function", "name": "...", "description": "...", "parameters": {...}}
            old_tools = self._get_tools()
            
            # Convert each tool to FunctionTool
            for tool_def in old_tools:
                if tool_def.get('type') == 'function':
                    # Responses API format - name, description, parameters are at top level
                    function_tool = FunctionTool(
                        name=tool_def['name'],
                        description=tool_def['description'],
                        parameters=tool_def['parameters']
                    )
                    tools_list.append(function_tool)
            
            log_debug(f"Added {len(tools_list)} function tools")
            
            # Add Bing Grounding Tool if connection ID is available
            if self.bing_connection_id:
                bing_tool = BingGroundingAgentTool(
                    bing_grounding=BingGroundingSearchToolParameters(
                        search_configurations=[
                            BingGroundingSearchConfiguration(
                                project_connection_id=self.bing_connection_id,
                                count=5
                            )
                        ]
                    )
                )
                tools_list.append(bing_tool)
                log_debug(f"Added BingGroundingAgentTool to tools list")
                log_debug(f"Connection ID: {self.bing_connection_id[:50]}...")
                log_foundry_debug(f"Added BingGroundingAgentTool to tools list")
            else:
                log_warning(f"NO Bing connection ID found!")
            
            log_foundry_debug(f"Creating agent with {len(tools_list)} total tools (Azure Agent Service)")
            
            # Create agent using Azure AI Projects SDK
            agent_definition = PromptAgentDefinition(
                model=model_name,
                instructions=instructions,
                tools=tools_list
            )
            
            self.agent = await self.project_client.agents.create_version(
                agent_name="foundry-host-agent",
                definition=agent_definition,
                description="Multi-agent orchestrator with Bing web search grounding"
            )
            
            # Store model name for responses API calls
            self.model_name = model_name

            # Allowlist of valid model deployment names for live switching
            self.allowed_models = ["gpt-4o", "gpt-5.2"]

            log_foundry_debug(f"Azure Agent created successfully!")
            log_foundry_debug(f"Agent created successfully! ID: {self.agent.id}")
            log_foundry_debug(f"Agent object attributes: {dir(self.agent)}")
            log_foundry_debug(f"Agent visible in Azure AI Foundry portal: {self.agent.id}")
            
            return True
            
        except Exception as e:
            log_foundry_debug(f"Exception in create_agent(): {type(e).__name__}: {e}")
            raise
    
    def get_model_name(self) -> str:
        """Return the current model deployment name."""
        return getattr(self, 'model_name', os.environ.get("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o"))

    def set_model_name(self, model: str) -> None:
        """Switch the model deployment used for all subsequent requests."""
        if hasattr(self, 'allowed_models') and model not in self.allowed_models:
            raise ValueError(f"Model '{model}' not in allowed list: {self.allowed_models}")
        old = self.model_name
        self.model_name = model
        log_debug(f"Host agent model switched: {old} -> {model}")
        self._swap_openai_client_for_model(model)

    def _swap_openai_client_for_model(self, model: str) -> None:
        """Swap the OpenAI client to match the model's Azure endpoint."""
        endpoint_key = getattr(self, '_model_endpoints', {}).get(model, "default")
        if endpoint_key == "default":
            # Restore original project client's OpenAI client
            if self._original_openai_client:
                self.openai_client = self._original_openai_client
                log_debug(f"Restored original OpenAI client (primary endpoint) for {model}")
        elif endpoint_key:
            # Save original client on first swap
            if not self._original_openai_client and hasattr(self, 'openai_client') and self.openai_client:
                self._original_openai_client = self.openai_client
            # Create or reuse cached alt client
            if endpoint_key not in self._alt_openai_clients:
                self._alt_openai_clients[endpoint_key] = self._create_alt_responses_client(endpoint_key)
            self.openai_client = self._alt_openai_clients[endpoint_key]
            log_debug(f"Switched OpenAI client to alt endpoint for {model}: {endpoint_key}")

    def _create_alt_responses_client(self, endpoint: str):
        """Create an AsyncAzureOpenAI client for an alternate Azure endpoint (Responses API).

        Uses AsyncAzureOpenAI with azure_ad_token_provider for automatic token management.
        The /responses endpoint is NOT in AsyncAzureOpenAI's _deployments_endpoints set,
        so no deployment-based URL rewriting is applied — requests go directly to
        {azure_endpoint}/openai/v1/responses as expected.
        """
        from openai import AsyncAzureOpenAI
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")
        resource_name = endpoint.split("//")[1].split(".")[0]
        azure_endpoint = f"https://{resource_name}.openai.azure.com"
        log_foundry_debug(f"Creating alt Responses API client (AsyncAzureOpenAI): {azure_endpoint}")
        client = AsyncAzureOpenAI(
            azure_endpoint=azure_endpoint,
            azure_ad_token_provider=token_provider,
            api_version="2025-03-01-preview",
        )
        return client

    def _get_base_endpoint(self) -> str:
        """Return the correct Azure base endpoint for the current model."""
        endpoint_key = getattr(self, '_model_endpoints', {}).get(self.model_name, "default")
        if endpoint_key and endpoint_key != "default":
            return endpoint_key
        endpoint = os.environ.get("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "")
        return endpoint.split('/api/projects')[0] if '/api/projects' in endpoint else endpoint

    # Note: list_remote_agents_sync has been extracted to agent_registry.py

    async def send_message_sync(
        self,
        agent_name: str,
        message: str,
        file_uris: Optional[List[str]] = None,
        video_metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Async wrapper for send_message - for use with AsyncFunctionTool.
        
        Azure AI Agents SDK's AsyncFunctionTool.execute() checks if the function
        is async (using inspect.iscoroutinefunction) and awaits it if needed.
        Since send_message is async, this wrapper must also be async.
        
        EXPLICIT FILE ROUTING (Option 3):
        - file_uris: List of file URIs from previous agent responses to pass along
        - video_metadata: Dict with video_id for remix operations
        
        HITL (Human-in-the-Loop) Support:
        - When an agent returns input_required, this function returns a special
          STOP message that tells GPT-4 to halt and wait for human input
        - The original user goal is saved for automatic resumption when the human responds
        """
        log_foundry_debug("[SEND_MESSAGE_SYNC] CALLED by Azure SDK!")
        log_debug(f"agent_name: {agent_name}")
        log_debug(f"message: {message[:100]}...")
        log_debug(f"file_uris: {file_uris}")
        log_debug(f"video_metadata: {video_metadata}")
        
        # Use contextvars for async-safe context_id (prevents race conditions between concurrent workflows)
        # Fall back to instance variable for backwards compatibility
        context_id_to_use = _current_context_id.get() or getattr(self, '_current_host_context_id', None)
        
        log_debug(f"[send_message_sync] context_id from contextvar: {_current_context_id.get()}")
        log_debug(f"[send_message_sync] context_id from instance: {getattr(self, '_current_host_context_id', None)}")
        log_debug(f"[send_message_sync] using context_id: {context_id_to_use}")
        log_debug(f"[send_message_sync] session_contexts keys: {list(self.session_contexts.keys())}")
        
        # CRITICAL: If we don't have the current context_id, this is a bug
        if not context_id_to_use:
            raise ValueError(f"send_message_sync called but context_id not set! This should be set by run_conversation_with_parts. Available keys: {list(self.session_contexts.keys())}")
        
        # Get existing session context or create new one with proper contextId
        session_ctx = self.session_contexts.get(context_id_to_use)
        if not session_ctx:
            log_debug(f"[send_message_sync] SessionContext NOT FOUND, creating new one with contextId={context_id_to_use}")
            session_ctx = SessionContext(
                agent_mode=False,
                host_task=None,
                plan=None,
                contextId=context_id_to_use  # CRITICAL: Pass contextId to prevent UUID generation
            )
            # CRITICAL: Store the new session context so it persists for HITL resumption
            self.session_contexts[context_id_to_use] = session_ctx
            log_debug(f"[send_message_sync] Stored new SessionContext in self.session_contexts")
        else:
            log_debug(f"[send_message_sync] SessionContext FOUND with contextId={session_ctx.contextId}")
        
        # Create a task context mock
        tool_context = type('obj', (object,), {
            'state': session_ctx
        })()
        
        # Call the async send_message - SDK will await it
        # NOTE: suppress_streaming=False allows status updates to flow to sidebar
        # EXPLICIT FILE ROUTING: Pass file_uris and video_metadata
        result = await self.send_message(
            agent_name=agent_name,
            message=message,
            tool_context=tool_context,
            suppress_streaming=False,  # Enable streaming for sidebar status updates!
            file_uris=file_uris,
            video_metadata=video_metadata
        )
        
        return result

    async def search_memory_sync(
        self,
        query: str,
        top_k: int = 5
    ):
        """
        Async function for searching uploaded documents and past conversations.
        
        This tool allows the host orchestrator to access memory (uploaded documents,
        past interactions) and include relevant context in its responses.
        
        Benefits over auto-injection:
        - Host decides WHEN to search (not every message)
        - Can search multiple times with different queries
        - More control over what context is used
        - Only uses tokens when actually needed
        
        Args:
            query: The search query string
            top_k: Number of results to return (default 5)
            
        Returns:
            JSON string with search results containing relevant excerpts
        """
        log_foundry_debug(f"[SEARCH_MEMORY_SYNC] CALLED by Azure SDK!")
        log_debug(f"query: {query}")
        log_debug(f"top_k: {top_k}")
        
        # Ensure top_k is an integer
        try:
            top_k = int(top_k) if top_k else 5
        except (ValueError, TypeError):
            top_k = 5
        
        # Use contextvars for async-safe context_id (prevents race conditions)
        context_id = _current_context_id.get() or getattr(self, '_current_host_context_id', None)
        log_debug(f"context_id (contextvar): {_current_context_id.get()}")
        log_debug(f"context_id (instance): {getattr(self, '_current_host_context_id', None)}")
        log_debug(f"context_id (using): {context_id}")
        
        if not context_id:
            log_warning(f"ERROR: No active context!")
            return json.dumps({
                "error": "No active context",
                "results": []
            })
        
        try:
            # Search memory using the same service remote agents use
            log_memory_debug(f"Calling _search_relevant_memory...")
            memory_results = await self._search_relevant_memory(
                query=query,
                context_id=context_id,
                agent_name=None,  # Search all sources
                top_k=top_k
            )
            log_memory_debug(f"_search_relevant_memory returned: {len(memory_results) if memory_results else 0} results")
            
            if not memory_results:
                log_debug(f"[SEARCH_MEMORY] No results found for query: {query}")
                return json.dumps({
                    "status": "success",
                    "query": query,
                    "results_count": 0,
                    "message": "No relevant information found in memory for this query.",
                    "results": []
                })
            
            log_debug(f"[SEARCH_MEMORY] Found {len(memory_results)} results")
            
            # Format results for the model
            formatted_results = []
            for i, result in enumerate(memory_results, 1):
                try:
                    source = result.get('agent_name', 'Unknown')
                    timestamp = result.get('timestamp', 'Unknown')
                    chunk_info = None  # Will store chunk metadata if available
                    
                    # Extract content
                    content = ""
                    if 'inbound_payload' in result and result['inbound_payload']:
                        inbound = result['inbound_payload']
                        if isinstance(inbound, str):
                            try:
                                inbound = json.loads(inbound)
                            except json.JSONDecodeError:
                                inbound = {}
                        
                        # Document content (from uploads)
                        if isinstance(inbound, dict) and 'content' in inbound:
                            content = str(inbound['content'])
                            # Check if there's a filename for better source attribution
                            if 'filename' in inbound:
                                source = f"{inbound['filename']}"
                            # Check for chunk metadata
                            if 'chunk_index' in inbound and 'total_chunks' in inbound:
                                chunk_info = f"(Section {inbound['chunk_index'] + 1} of {inbound['total_chunks']})"
                        # A2A message content
                        elif isinstance(inbound, dict) and 'parts' in inbound:
                            parts_content = []
                            for part in inbound['parts']:
                                if isinstance(part, dict):
                                    if 'text' in part:
                                        parts_content.append(str(part['text']))
                                    elif 'root' in part and isinstance(part['root'], dict) and 'text' in part['root']:
                                        parts_content.append(str(part['root']['text']))
                            if parts_content:
                                content = " ".join(parts_content)
                    
                    if content:
                        # Truncate very long content but keep enough for context
                        if len(content) > 3000:
                            content = content[:3000] + "... [truncated]"
                        
                        result_entry = {
                            "rank": i,
                            "source": source,
                            "content": content,
                            "relevance": "high" if i <= 3 else "medium"
                        }
                        # Add chunk info if available
                        if chunk_info:
                            result_entry["section"] = chunk_info
                        
                        formatted_results.append(result_entry)
                
                except Exception as e:
                    log_warning(f"Error processing memory result {i}: {e}")
                    continue
            
            # Build source citations for the response with section info
            source_citations = []
            for r in formatted_results:
                if r["source"] != "Unknown":
                    citation = r["source"]
                    if "section" in r:
                        citation += f" {r['section']}"
                    source_citations.append(citation)
            
            unique_sources = list(set(r["source"] for r in formatted_results if r["source"] != "Unknown"))
            sources_text = ""
            if source_citations:
                # Deduplicate but preserve section info
                seen = set()
                unique_citations = []
                for c in source_citations:
                    if c not in seen:
                        seen.add(c)
                        unique_citations.append(c)
                sources_text = "\n\n📄 **Sources:** " + " | ".join(unique_citations[:5])  # Limit to 5 citations
            
            log_debug(f"Returning {len(formatted_results)} formatted results from sources: {unique_sources}")
            return json.dumps({
                "status": "success",
                "query": query,
                "results_count": len(formatted_results),
                "message": f"Found {len(formatted_results)} relevant excerpts from uploaded documents and past conversations.",
                "sources": unique_sources,
                "sources_citation": sources_text,
                "instruction": "IMPORTANT: Include the sources at the end of your response to cite where the information came from.",
                "results": formatted_results
            }, indent=2)
        
        except Exception as e:
            log_error(f"[SEARCH_MEMORY] Exception: {e}")
            return json.dumps({
                "error": str(e),
                "results": []
            })

    # Note: web_search_sync was removed - Bing search is now handled by native BingGroundingTool
    # which is added to the toolset in _initialize_function_tools()

    def _format_agent_response_for_model(self, response_parts: list, agent_name: str) -> str:
        """
        Format the response parts from send_message into clean text for the model.
        
        This extracts text content and FILE URIs from response_parts so GPT-4 can
        explicitly pass them to subsequent agent calls via the file_uris parameter.
        
        CRITICAL: Include full file URIs so GPT-4 can route files between agents.
        
        Args:
            response_parts: List of Part objects from send_message
            agent_name: Name of the agent that responded
            
        Returns:
            JSON string with response text, file URIs, and video metadata
        """
        if not response_parts:
            return json.dumps({
                "agent": agent_name,
                "status": "completed",
                "response": "Agent completed the task but returned no text content."
            })
        
        text_parts = []
        files = []  # Full file info with URIs for explicit passing
        video_metadata = None  # For video_id tracking
        
        for part in response_parts:
            try:
                # Handle various part formats
                part_root = getattr(part, 'root', part)
                
                # Check for text content
                if hasattr(part_root, 'text') and part_root.text:
                    text_parts.append(part_root.text)
                elif hasattr(part, 'text') and part.text:
                    text_parts.append(part.text)
                elif isinstance(part, str):
                    text_parts.append(part)
                elif isinstance(part, dict):
                    if 'text' in part:
                        text_parts.append(part['text'])
                    elif 'content' in part:
                        text_parts.append(str(part['content']))
                
                # Check for file content - extract FULL URI for explicit passing
                if hasattr(part_root, 'file') or hasattr(part, 'file'):
                    file_obj = getattr(part_root, 'file', None) or getattr(part, 'file', None)
                    if file_obj:
                        file_name = getattr(file_obj, 'name', 'unknown_file')
                        file_uri = getattr(file_obj, 'uri', None)
                        file_mime = getattr(file_obj, 'mimeType', None)
                        if file_uri:
                            files.append({
                                "name": file_name,
                                "uri": str(file_uri),
                                "mimeType": file_mime or "application/octet-stream"
                            })
                
                # Check for DataPart with artifact-uri (alternate file format)
                if isinstance(part_root, DataPart) and isinstance(getattr(part_root, 'data', None), dict):
                    data = part_root.data
                    if data.get('artifact-uri'):
                        files.append({
                            "name": data.get('file-name', 'unknown'),
                            "uri": data.get('artifact-uri'),
                            "mimeType": data.get('mime', 'application/octet-stream')
                        })
                    # Check for video metadata
                    if data.get('type') == 'video_metadata' and data.get('video_id'):
                        video_metadata = {"video_id": data.get('video_id')}
                        
            except Exception as e:
                log_foundry_debug(f"Error processing part: {e}")
                try:
                    if hasattr(part, 'model_dump'):
                        text_parts.append(str(part.model_dump(mode='json')))
                    else:
                        text_parts.append(str(part))
                except:
                    pass
        
        # Build response with explicit file URIs for GPT-4 to pass along
        response_text = "\n\n".join(text_parts) if text_parts else ""
        
        result = {
            "agent": agent_name,
            "status": "completed",
            "response": response_text if response_text else "Task completed successfully."
        }
        
        # CRITICAL: Include files with URIs so GPT-4 can explicitly route them
        if files:
            result["files"] = files
            # Also provide a simple list for easy reference
            result["file_uris"] = [f["uri"] for f in files]
        
        # Include video metadata for remix operations
        if video_metadata:
            result["video_metadata"] = video_metadata
        
        return json.dumps(result, ensure_ascii=False)

    async def _update_agent_instructions(self, agent_mode: bool = False):
        """
        Update the agent's instructions with the current agent list.
        
        With the Responses API using agent_reference, we need to update
        the agent definition in Azure AI Foundry so the instructions
        reflect the current session agents.
        
        Args:
            agent_mode: Whether to use agent mode instructions (default: False for orchestrator mode)
        """
        if not self.agent:
            log_warning(f"No agent initialized to update")
            return
            
        try:
            log_debug(f"Updating agent instructions with {len(self.cards)} registered agents (agent_mode={agent_mode})...")
            
            # CRITICAL: Update self.agents FIRST with current agent list
            self.agents = json.dumps(self.list_remote_agents(), indent=2)
            
            # Update the cached instructions with current agent list
            self.agent_instructions = self.root_instruction('foundry-host-agent', agent_mode=agent_mode)
            
            # Also update the tools list in case agents changed
            self.agent_tools = self._get_tools()
            
            log_info(f"Agent instructions updated successfully!")
            log_debug(f"Agent now knows about: {', '.join(self.cards.keys())}")
                    
        except Exception as e:
            log_error(f"Error updating agent instructions: {e}")
            # Don't fail the registration if instruction update fails
            pass

    def _get_tools(self) -> List[Dict[str, Any]]:
        """
        Define Azure AI Foundry function tools for agent coordination.
        
        NOTE: Responses API format is different from Chat Completions API!
        - Responses API: {"type": "function", "name": "...", "description": "...", "parameters": {...}}
        - Chat Completions: {"type": "function", "function": {"name": "...", ...}}
        """
        return [
            {
                "type": "function",
                "name": "list_remote_agents",
                "description": "List the available remote agents you can use to delegate the task.",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "type": "function",
                "name": "send_message",
                "description": "Send a message to a remote agent. When an agent returns files, include their URIs from the response in file_uris to pass them to the next agent. For video remix operations, include video_metadata with the video_id.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_name": {"type": "string", "description": "The name of the agent to send the task to."},
                        "message": {"type": "string", "description": "The message to send to the agent."},
                        "file_uris": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional: URIs of files to send with the message. Use this to pass files between agents by including URIs from previous agent responses."
                        },
                        "video_metadata": {
                            "type": "object",
                            "properties": {
                                "video_id": {"type": "string", "description": "The video_id from a previous video generation, required for remix operations."}
                            },
                            "description": "Optional: Video metadata for remix operations. Include video_id from previous video generation responses."
                        }
                    },
                    "required": ["agent_name", "message"],
                },
            },
            {
                "type": "function",
                "name": "search_memory",
                "description": "Search uploaded documents and past conversations for relevant information. Use this when the user asks about previously uploaded documents (PDFs, Word docs, etc.) or past interactions. Returns relevant excerpts from memory that can help answer the user's question.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query. Be specific - e.g., 'patent claims', 'financial data from Q3 report', 'user's previous question about X'."
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of results to return. Default is 5. Use higher values (8-10) for comprehensive searches.",
                            "default": 5
                        }
                    },
                    "required": ["query"],
                },
            },
            # Note: Bing web search is now handled by native BingGroundingTool (added in _initialize_function_tools)
        ]

    def root_instruction(self, current_agent: str, agent_mode: bool = False) -> str:
        """
        Generate system prompt for the host agent based on operational mode.
        Supports custom instruction overrides and agent-mode vs standard orchestration prompts.
        """
        if self.custom_root_instruction:
            return apply_custom_instruction(
                self.custom_root_instruction, 
                self.agents, 
                current_agent
            )

        if agent_mode:
            return build_agent_mode_instruction(self.agents, current_agent)

        return build_orchestrator_instruction(self.agents, current_agent)

    # Note: list_remote_agents has been extracted to agent_registry.py

    async def _call_azure_openai_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        context_id: str
    ) -> BaseModel:
        """
        Make a structured output request to Azure OpenAI for agent-mode planning.
        Uses Pydantic models to enforce response schema validation.
        """
        try:
            log_foundry_debug(f"[Agent Mode] Calling Azure OpenAI for structured output...")
            await self._emit_granular_agent_event(
                "foundry-host-agent", "Planning next task with AI...", context_id,
                event_type="phase", metadata={"phase": "planning_ai"}
            )
            
            # Use live model name and endpoint (supports model switching)
            model_name = self.model_name or os.environ.get("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")
            base_endpoint = self._get_base_endpoint()
            log_foundry_debug(f"[Agent Mode] Azure endpoint: {base_endpoint}")
            log_debug(f"[Agent Mode] Model deployment: {model_name}")

            # Get Azure credential token
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            from openai import AsyncAzureOpenAI
            credential = DefaultAzureCredential()
            token_provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")

            # Create Azure OpenAI client with token auth
            client = AsyncAzureOpenAI(
                azure_endpoint=base_endpoint,
                azure_ad_token_provider=token_provider,
                api_version="2024-08-01-preview"  # Version that supports structured outputs
            )

            log_debug(f"[Agent Mode] Making structured output request with OpenAI SDK...")

            # Use OpenAI SDK's parse method for structured outputs
            completion = await client.beta.chat.completions.parse(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format=response_model,
                temperature=0.0,  # Use 0.0 for deterministic workflow execution
                **{"max_completion_tokens" if model_name.startswith("gpt-5") else "max_tokens": 2000}
            )
            
            parsed = completion.choices[0].message.parsed
            log_debug(f"[Agent Mode] Got structured response: {parsed.model_dump_json()[:200]}...")
            
            # Extract token usage from orchestration call
            if hasattr(completion, 'usage') and completion.usage:
                self.host_token_usage["prompt_tokens"] += completion.usage.prompt_tokens or 0
                self.host_token_usage["completion_tokens"] += completion.usage.completion_tokens or 0
                self.host_token_usage["total_tokens"] += completion.usage.total_tokens or 0
                log_debug(f"[Host Agent] Orchestration tokens: +{completion.usage.total_tokens} (total: {self.host_token_usage['total_tokens']})")
            
            return parsed
                    
        except Exception as e:
            log_error(f"[Agent Mode] Error calling Azure OpenAI: {e}")
            raise

    async def _call_azure_openai_raw(
        self,
        system_prompt: str,
        user_prompt: str,
        context_id: str
    ) -> str:
        """
        Make a simple text completion request to Azure OpenAI.
        Used for lightweight tasks like agent selection.
        """
        try:
            # Use live model name and endpoint (supports model switching)
            model_name = self.model_name or os.environ.get("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")
            base_endpoint = self._get_base_endpoint()

            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            from openai import AsyncAzureOpenAI
            credential = DefaultAzureCredential()
            token_provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")

            client = AsyncAzureOpenAI(
                azure_endpoint=base_endpoint,
                azure_ad_token_provider=token_provider,
                api_version="2024-08-01-preview"
            )

            completion = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                **{"max_completion_tokens" if model_name.startswith("gpt-5") else "max_tokens": 100}
            )
            
            return completion.choices[0].message.content or ""
            
        except Exception as e:
            log_error(f"[Azure OpenAI Raw] Error: {e}")
            raise

    async def _select_agent_for_task(
        self,
        task_description: str,
        available_agents: List[Dict[str, str]],
        context_id: str
    ) -> Optional[str]:
        """
        Use LLM to select the best agent for a task description.
        
        This is a lightweight call just for agent selection when the workflow
        doesn't explicitly specify which agent to use.
        """
        try:
            system_prompt = """You are an agent selector. Given a task description and available agents, 
select the most appropriate agent. Return ONLY the agent name, nothing else."""
            
            user_prompt = f"""Task: {task_description}

Available Agents:
{json.dumps(available_agents, indent=2)}

Return the name of the best agent for this task (exact match from the list above):"""
            
            response = await self._call_azure_openai_raw(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                context_id=context_id
            )
            
            agent_name = response.strip().strip('"').strip("'")
            
            # Verify it's a valid agent
            for agent in available_agents:
                if agent["name"].lower() == agent_name.lower():
                    return agent["name"]
            
            # Try partial match
            for agent in available_agents:
                if agent_name.lower() in agent["name"].lower() or agent["name"].lower() in agent_name.lower():
                    return agent["name"]
            
            return None
            
        except Exception as e:
            log_error(f"[Agent Selection] Error: {e}")
            return None

    async def get_current_root_instruction(self) -> str:
        """Get the current root instruction (custom or default)"""
        return self.root_instruction('foundry-host-agent')

    async def update_root_instruction(self, new_instruction: str) -> bool:
        """Update the root instruction and apply it to the Azure AI Foundry agent"""
        try:
            log_debug(f"Updating root instruction...")
            log_debug(f"New instruction length: {len(new_instruction)} characters")
            
            # Store the custom instruction
            self.custom_root_instruction = new_instruction
            
            # Update the Azure AI Foundry agent with the new instruction
            await self._update_agent_instructions()
            
            log_info(f"Root instruction updated successfully!")
            return True
            
        except Exception as e:
            log_error(f"Error updating root instruction: {e}")
            return False

    async def reset_root_instruction(self) -> bool:
        """Reset to default root instruction"""
        try:
            log_debug(f"Resetting to default root instruction...")
            
            # Clear the custom instruction
            self.custom_root_instruction = None
            
            # Update the Azure AI Foundry agent with the default instruction
            await self._update_agent_instructions()
            
            log_info(f"Root instruction reset to default!")
            return True
            
        except Exception as e:
            log_error(f"Error resetting root instruction: {e}")
            return False

    # Note: _stream_remote_agent_activity, _default_task_callback, _display_task_status_update,
    # _get_status_display_text, _extract_message_content, _extract_text_from_response
    # have been extracted to streaming_handlers.py
    def get_session_context(self, context_id: str) -> SessionContext:
        log_debug(f"[get_session_context] Called with context_id: {context_id}")
        log_debug(f"[get_session_context] Existing session_contexts keys: {list(self.session_contexts.keys())}")
        
        if context_id not in self.session_contexts:
            # Clear host response tracking for new conversations
            if context_id in self._host_responses_sent:
                self._host_responses_sent.remove(context_id)
            log_debug(f"[get_session_context] Creating NEW SessionContext with contextId={context_id}")
            self.session_contexts[context_id] = SessionContext(contextId=context_id)
        else:
            log_debug(f"[get_session_context] FOUND existing SessionContext for key={context_id}")
            
        return self.session_contexts[context_id]

    # Note: _search_relevant_memory, clear_memory_index, _create_memory_artifact
    # have been extracted to memory_service.py
    async def _evaluate_task_completion(self, original_request: str, task_response: Task, agent_name: str) -> Dict[str, Any]:
        """Use direct Azure OpenAI call to evaluate if a task was truly completed successfully"""
        
        try:
            # Extract response content from LATEST task artifact only (avoid evaluating retry history)
            response_content = ""
            if task_response.artifacts:
                # Get only the most recent artifact (last one in the list)
                latest_artifact = task_response.artifacts[-1]
                for part in latest_artifact.parts:
                    if hasattr(part, 'root') and part.root.kind == 'text':
                        response_content = part.root.text  # Only the latest response
                        break  # Stop after first text part of latest artifact
            
            # If no artifacts, check status message
            if not response_content and task_response.status.message:
                if hasattr(task_response.status.message, 'parts'):
                    for part in task_response.status.message.parts:
                        if hasattr(part, 'root') and part.root.kind == 'text':
                            response_content += part.root.text + "\n"
            
            evaluation_prompt = f"""Evaluate ONLY this specific agent response:

Request: "{original_request}"
Agent: {agent_name}  
Response: "{response_content.strip()}"

SUCCESS criteria (mark as true):
- Agent completed the requested task successfully
- Agent provided a confirmation, result, or request ID
- Agent asked for truly missing required information
- Response directly addresses the user's request

FAILURE criteria (mark as false):
- Agent completely ignored the request
- Agent gave totally irrelevant information
- Agent had major errors or contradictions

IMPORTANT: If the agent provided ANY form of completion, confirmation, or request ID, it's SUCCESS.

Answer with just JSON:

{{"is_successful": true/false, "reason": "brief reason"}}"""

            log_foundry_debug(f"Making direct Azure OpenAI call for evaluation...")
            
            # Use the same Azure AI Foundry approach as the rest of the system
            from openai import AsyncAzureOpenAI
            from azure.identity import get_bearer_token_provider
            
            # Use live model name and endpoint (supports model switching)
            model_name = self.model_name or os.environ.get("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")
            base_endpoint = self._get_base_endpoint()

            # Use DefaultAzureCredential like the rest of the system
            token_provider = get_bearer_token_provider(
                self.credential,
                "https://cognitiveservices.azure.com/.default"
            )

            # Create Azure OpenAI client with same auth as main system
            client = AsyncAzureOpenAI(
                azure_endpoint=base_endpoint,
                azure_ad_token_provider=token_provider,
                api_version="2024-02-15-preview"
            )

            # Make direct chat completion call
            response = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "You are a task completion evaluator. Analyze agent responses and return JSON evaluations."},
                    {"role": "user", "content": evaluation_prompt}
                ],
                **{"max_completion_tokens" if model_name.startswith("gpt-5") else "max_tokens": 200},
                temperature=0.1
            )
            
            evaluation_response = response.choices[0].message.content
            log_debug(f"Direct OpenAI evaluation response: {evaluation_response}")
            
            # Parse JSON response
            try:
                # Extract JSON from response (in case there's extra text)
                start_idx = evaluation_response.find('{')
                end_idx = evaluation_response.rfind('}') + 1
                if start_idx >= 0 and end_idx > start_idx:
                    json_str = evaluation_response[start_idx:end_idx]
                    evaluation_result = json.loads(json_str)
                    log_debug(f"Parsed evaluation result: {evaluation_result}")
                    
                    # Add default fields if missing from simplified response
                    if "retry_suggestion" not in evaluation_result:
                        evaluation_result["retry_suggestion"] = "Try rephrasing your request or provide more details"
                    if "alternative_agent" not in evaluation_result:
                        evaluation_result["alternative_agent"] = None
                    if "needs_clarification" not in evaluation_result:
                        evaluation_result["needs_clarification"] = None
                        
                    return evaluation_result
                else:
                    log_error(f"No valid JSON found in evaluation response")
                    return {"is_successful": True, "reason": "Could not parse evaluation"}
                    
            except json.JSONDecodeError as e:
                log_error(f"JSON parsing error: {e}")
                return {"is_successful": True, "reason": "Could not parse evaluation"}
                
        except Exception as e:
            log_error(f"Error during task evaluation: {e}")
            # Default to successful if evaluation fails to avoid blocking user
            return {"is_successful": True, "reason": f"Evaluation error: {str(e)}"}

    async def _log_evaluation_result(self, original_request: str, task_response: Task, agent_name: str):
        """Background evaluation for monitoring - doesn't affect user experience"""
        try:
            log_debug(f"[BACKGROUND] Running evaluation for monitoring...")
            evaluation = await self._evaluate_task_completion(original_request, task_response, agent_name)
            
            # Just log the results for monitoring/analytics
            if evaluation.get("is_successful", True):
                log_debug(f"[BACKGROUND] Task evaluation: SUCCESS - {evaluation.get('reason', '')}")
            else:
                log_error(f"[BACKGROUND] Task evaluation: FAILED - {evaluation.get('reason', '')}")
                log_debug(f"[BACKGROUND] Suggestion: {evaluation.get('retry_suggestion', 'None')}")
                
            # Could store results for analytics dashboard
            # await self._store_evaluation_analytics(original_request, task_response, agent_name, evaluation)
            
        except Exception as e:
            log_error(f"[BACKGROUND] Evaluation error (non-blocking): {e}")
            # Background evaluation errors don't affect user experience



    def _extract_failure_reason(self, failed_task: Task) -> str:
        """Extract meaningful failure reason from failed task"""
        if failed_task.status.message:
            if hasattr(failed_task.status.message, 'parts'):
                for part in failed_task.status.message.parts:
                    if hasattr(part, 'root') and part.root.kind == 'text':
                        return part.root.text
            elif hasattr(failed_task.status.message, 'text'):
                return failed_task.status.message.text
        
        return "Task failed with unknown error"

    def _generate_failure_recovery_options(self, failed_task: Task, agent_name: str, original_request: str) -> List[str]:
        """Generate helpful recovery options for the user"""
        failure_reason = self._extract_failure_reason(failed_task)
        
        options = []
        
        # Always offer to try a different approach
        options.append("Try a different approach to your request")
        
        # Suggest alternative agents if available
        available_agents = [name for name in self.remote_agent_connections.keys() if name != agent_name]
        if available_agents:
            options.append(f"Use a different specialist agent ({', '.join(available_agents[:2])})")
        
        # Suggest breaking down the request
        if len(original_request.split()) > 5:
            options.append("Break your request into smaller, simpler steps")
        
        # Suggest rephrasing
        options.append("Rephrase your request with more details")
        
        # Offer to try again later if it seems like a temporary issue
        if any(term in failure_reason.lower() for term in ['timeout', 'rate limit', 'unavailable', 'busy']):
            options.append("Try again in a few minutes")
        
        return options

    @staticmethod
    def _parse_retry_after_from_task(task) -> int:
        """
        Parse retry-after delay from a failed task's error message.
        
        Looks for rate limit messages and extracts the suggested wait time.
        Returns 0 if no rate limit is detected, otherwise the wait time in seconds.
        """
        try:
            if hasattr(task, 'status') and task.status and getattr(task.status, 'message', None):
                parts = getattr(task.status.message, 'parts', []) or []
                import re
                for p in parts:
                    txt = None
                    if hasattr(p, 'root') and hasattr(p.root, 'text') and p.root.text:
                        txt = p.root.text
                    elif hasattr(p, 'text') and p.text:
                        txt = p.text
                    if not txt:
                        continue
                    lower = txt.lower()
                    if 'rate limit' in lower or 'rate_limit_exceeded' in lower:
                        m = re.search(r"try again in\s+(\d+)\s*seconds", lower)
                        return int(m.group(1)) if m else 15
        except Exception:
            pass
        return 0

    @staticmethod
    def _infer_file_role(explicit_role: Optional[str], name_hint: Optional[str]) -> Optional[str]:
        """
        Infer file role (base, mask, overlay) from filename for image editing workflows.
        
        Role assignment rules:
        1. If explicit_role is provided, use it
        2. Generated/edited files (generated_*, edit_*) get no role (kept separate)
        3. Files with "mask" in name → mask role
        4. Files with "_base" in name → base role  
        5. Image files and logos → overlay role
        6. Everything else → no role
        
        Args:
            explicit_role: Role explicitly set on the file
            name_hint: Filename to infer role from
            
        Returns:
            Role string (base, mask, overlay) or None
        """
        if explicit_role:
            return str(explicit_role).lower()

        if not name_hint:
            return None

        name_lower = str(name_hint).lower()

        # Generated/edited outputs get no role - kept as separate artifacts
        if "generated_" in name_lower or "edit_" in name_lower:
            return None

        # Mask files
        if "mask" in name_lower or name_lower.endswith("-mask.png") or name_lower.endswith("_mask.png"):
            return "mask"

        # Base files
        if name_lower.endswith("-base.png") or name_lower.endswith("_base.png") or "_base" in name_lower:
            return "base"

        # Image files default to overlay
        image_exts = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".heic", ".heif", ".jfif", ".apng")
        if name_lower.endswith(image_exts) or "logo" in name_lower:
            return "overlay"

        return None

    @staticmethod
    def _normalize_uri(value: Optional[str]) -> Optional[str]:
        """
        Normalize a URI for comparison/deduplication.
        
        Strips whitespace, removes query parameters, and lowercases.
        """
        if not value:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        base, _, _ = normalized.partition("?")
        return base.lower()

    @staticmethod
    def _apply_role_to_part(part: Any, role: Optional[str]) -> None:
        """
        Apply a role to a part's metadata for image editing workflows.
        
        Handles both DataPart and FilePart structures.
        """
        if not role:
            return
        normalized_role = str(role).lower()
        target = part.root if isinstance(part, Part) else part
        if isinstance(target, DataPart) and isinstance(target.data, dict):
            target.data["role"] = normalized_role
            meta = target.data.get("metadata") or {}
            meta["role"] = normalized_role
            target.data["metadata"] = meta
        elif isinstance(target, FilePart):
            meta = target.metadata or {}
            meta["role"] = normalized_role
            target.metadata = meta

    @staticmethod
    def _build_mask_parts(
        file_id: str,
        mime_type: str,
        artifact_uri: Optional[str],
        artifact_info: dict,
        file_bytes: Optional[bytes],
        artifact_response: Optional[DataPart],
    ) -> tuple[DataPart, FilePart]:
        """
        Build DataPart + FilePart for a mask file artifact.
        
        Consolidates mask-specific metadata and file part construction
        that was previously duplicated in convert_part.
        
        Args:
            file_id: Filename/identifier
            mime_type: MIME type of the file
            artifact_uri: URI where artifact is stored (if available)
            artifact_info: Artifact metadata dict from save_artifact
            file_bytes: Raw file bytes (fallback if no URI)
            artifact_response: Existing DataPart from save_artifact (if any)
            
        Returns:
            Tuple of (DataPart with metadata, FilePart with URI or bytes)
        """
        # Build or update the metadata DataPart
        if isinstance(artifact_response, DataPart) and hasattr(artifact_response, 'data'):
            artifact_response.data['description'] = artifact_response.data.get('description', 'image mask attachment')
            artifact_response.data['skip-document-processing'] = True
            artifact_response.data['role'] = 'mask'
            metadata = artifact_response.data.get('metadata') or {}
            metadata['role'] = 'mask'
            artifact_response.data['metadata'] = metadata
            mask_metadata_part = artifact_response
            artifact_uri = artifact_uri or artifact_response.data.get('artifact-uri')
        else:
            # Create new DataPart with mask metadata
            mask_metadata_part = DataPart(data={
                'artifact-id': artifact_info.get('artifact_id') or str(uuid.uuid4()),
                'artifact-uri': artifact_uri or artifact_info.get('artifact_uri'),
                'storage-type': artifact_info.get('storage_type', 'unknown'),
                'file-name': artifact_info.get('file_name') or file_id,
                'description': 'image mask attachment',
                'skip-document-processing': True,
                'role': 'mask',
                'metadata': {'role': 'mask'},
            })

        # Build the FilePart - prefer URI, fallback to embedded bytes
        if artifact_uri:
            mask_file_part = FilePart(
                kind="file",
                file=FileWithUri(
                    name=file_id,
                    mimeType=mime_type,
                    uri=artifact_uri,
                    role="mask",
                ),
            )
        else:
            mask_file_part = FilePart(
                kind="file",
                file=FileWithBytes(
                    name=file_id,
                    mimeType=mime_type,
                    bytes=file_bytes or b'',
                    role="mask",
                )
            )

        return mask_metadata_part, mask_file_part

    @staticmethod
    def _store_parts_in_session(tool_context: Any, *parts: Any) -> None:
        """
        DEPRECATED: No longer used with explicit file routing.
        
        Previously stored parts in session context for implicit file sharing.
        Now GPT-4 routes files explicitly via file_uris parameter.
        
        This method is kept for backward compatibility but is a no-op.
        """
        # No-op: Explicit file routing via file_uris replaces implicit memory
        pass

    @staticmethod
    def _wrap_item_for_agent(item: Any) -> List[Part]:
        """
        Wrap any item as A2A Parts for agent communication.
        
        Handles Part, DataPart, FilePart, TextPart, str, dict, and other types.
        For DataParts with artifact data, also creates FilePart for consistency.
        """
        wrapped: List[Part] = []

        if isinstance(item, Part):
            wrapped.append(item)
        elif isinstance(item, DataPart):
            wrapped.append(Part(root=item))
            # Also convert to FilePart for consistent handling
            if isinstance(item.data, dict):
                uri = extract_uri(item)
                if uri:
                    file_part = convert_artifact_dict_to_file_part(item)
                    if file_part:
                        wrapped.append(Part(root=file_part))
                if item.data.get("extracted_content"):
                    wrapped.append(Part(root=TextPart(text=str(item.data["extracted_content"]))))
        elif isinstance(item, FilePart):
            wrapped.append(Part(root=item))
        elif isinstance(item, TextPart):
            wrapped.append(Part(root=item))
        elif isinstance(item, str):
            wrapped.append(Part(root=TextPart(text=item)))
        elif isinstance(item, dict):
            uri = extract_uri(item)
            if uri:
                file_part = convert_artifact_dict_to_file_part(item)
                if file_part:
                    wrapped.append(Part(root=file_part))
            else:
                wrapped.append(Part(root=DataPart(data=item)))
        elif item is not None:
            wrapped.append(Part(root=TextPart(text=str(item))))

        return wrapped

    @staticmethod
    def _flatten_nested(items: Iterable[Any]) -> Iterable[Any]:
        """Flatten nested lists/tuples/sets into a single iterable."""
        def _do_flatten(items):
            for item in items:
                if isinstance(item, (list, tuple, set)):
                    yield from _do_flatten(item)
                else:
                    yield item
        return _do_flatten(items)

    def _build_image_edit_guidance(self, processed_parts: List[Any]) -> Optional[str]:
        """
        Scan processed parts for base/mask image attachments and build
        guidance text for image editing workflows.
        
        Returns guidance string if base attachment found, None otherwise.
        """
        has_base = False
        has_mask = False
        base_filenames: List[str] = []
        mask_filenames: List[str] = []

        for result in self._flatten_nested(processed_parts):
            candidate_part = None
            candidate_data: Optional[Dict[str, Any]] = None

            if isinstance(result, DataPart) and isinstance(result.data, dict):
                candidate_data = result.data
            elif isinstance(result, FilePart):
                candidate_part = result
            elif isinstance(result, Part):
                inner = getattr(result, "root", None)
                if isinstance(inner, DataPart) and isinstance(inner.data, dict):
                    candidate_data = inner.data
                elif isinstance(inner, FilePart):
                    candidate_part = inner

            if candidate_data:
                role_val = (candidate_data.get("role") or (candidate_data.get("metadata") or {}).get("role") or "").lower()
                if role_val == "base":
                    has_base = True
                    name_hint = candidate_data.get("file-name") or candidate_data.get("name")
                    if name_hint:
                        base_filenames.append(str(name_hint))
                if role_val == "mask":
                    has_mask = True
                    name_hint = candidate_data.get("file-name") or candidate_data.get("name")
                    if name_hint:
                        mask_filenames.append(str(name_hint))

            if candidate_part:
                role_attr = (candidate_part.metadata or {}).get("role") if getattr(candidate_part, "metadata", None) else None
                part_name = getattr(candidate_part.file, "name", "")
                name_attr = part_name.lower()
                role_lower = str(role_attr).lower() if role_attr else ""
                if role_lower == "base" or name_attr.endswith("_base.png"):
                    has_base = True
                    if part_name:
                        base_filenames.append(part_name)
                if role_lower == "mask" or "_mask" in name_attr or "-mask" in name_attr:
                    has_mask = True
                    if part_name:
                        mask_filenames.append(part_name)

        if not has_base:
            return None

        lines = [
            "IMPORTANT: Treat this request as an image edit using the provided attachments.",
            "Reuse the supplied base image exactly; do not regenerate a new scene or subject.",
        ]
        if base_filenames:
            lines.append(f"Base image attachment(s): {', '.join(sorted(set(base_filenames)))}.")
        if has_mask:
            lines.append("Apply the requested changes strictly within the transparent region of the provided mask and leave all other pixels unchanged.")
            if mask_filenames:
                lines.append(f"Mask attachment(s): {', '.join(sorted(set(mask_filenames)))} (must include transparency).")
        else:
            lines.append("Apply the requested changes directly to the supplied base image only.")

        return "\n".join(lines)

    @staticmethod
    def _load_file_bytes(file_part: Any, context_id: Optional[str] = None) -> tuple[Optional[bytes], Optional[str]]:
        """
        Load file bytes from various sources: uploads directory, inline bytes, or HTTP URI.
        
        Args:
            file_part: The file object from FilePart.root.file
            context_id: Context ID for session-scoped directory lookup
            
        Returns:
            Tuple of (file_bytes, error_message). One will be None.
        """
        import os
        
        file_id = getattr(file_part, 'name', 'unknown')
        
        # Strategy 1: Load from /uploads/ URI
        uri = getattr(file_part, 'uri', None)
        if uri and str(uri).startswith('/uploads/'):
            file_uuid = uri.split('/')[-1]
            upload_dir = "uploads"
            
            # Extract session_id for tenant isolation
            session_id = None
            if context_id and '::' in context_id:
                session_id = context_id.split('::')[0]
            
            try:
                # Try session-scoped directory first
                if session_id:
                    session_upload_dir = os.path.join(upload_dir, session_id)
                    if os.path.exists(session_upload_dir):
                        for filename in os.listdir(session_upload_dir):
                            if filename.startswith(file_uuid):
                                file_path = os.path.join(session_upload_dir, filename)
                                with open(file_path, 'rb') as f:
                                    return f.read(), None
                
                # Fall back to flat directory (legacy)
                if os.path.exists(upload_dir):
                    for filename in os.listdir(upload_dir):
                        if os.path.isdir(os.path.join(upload_dir, filename)):
                            continue
                        if filename.startswith(file_uuid):
                            file_path = os.path.join(upload_dir, filename)
                            with open(file_path, 'rb') as f:
                                return f.read(), None
                
                return None, f"Could not find uploaded file {file_id}"
            except Exception as e:
                return None, f"Could not read uploaded file {file_id}: {e}"
        
        # Strategy 2: Inline base64 or raw bytes
        if hasattr(file_part, 'bytes') and file_part.bytes:
            try:
                if isinstance(file_part.bytes, str):
                    return base64.b64decode(file_part.bytes), None
                return file_part.bytes, None
            except Exception as e:
                return None, f"Failed to decode file {file_id}: {e}"
        
        # Strategy 3: HTTP/HTTPS URI download
        if uri and str(uri).lower().startswith(("http://", "https://")):
            try:
                import httpx
                with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                    resp = client.get(uri)
                    resp.raise_for_status()
                    return resp.content, None
            except Exception as e:
                return None, f"Could not download file {file_id}: {e}"
        
        return None, f"No file data found for {file_id}"

    def _get_retry_count(self, session_context: SessionContext) -> int:
        """Get current retry count for this session"""
        return session_context.retry_count

    def _increment_retry_count(self, session_context: SessionContext):
        """Increment retry count for this session"""
        session_context.retry_count += 1

    def _reset_retry_count(self, session_context: SessionContext):
        """Reset retry count after successful completion"""
        session_context.retry_count = 0

    def _update_last_host_turn(
        self,
        session_context: SessionContext,
        agent_name: str,
        responses: List[Any],
    ) -> None:
        """Cache the most recent host-side turn so we can hand it to the next agent."""
        if not self.include_last_host_turn or not responses:
            return

        text_chunks: List[str] = []
        for item in responses:
            # Extract text from various response types
            if isinstance(item, str):
                text = item.strip()
                if text:
                    text_chunks.append(text)
            elif isinstance(item, TextPart):
                text = (item.text or "").strip()
                if text:
                    text_chunks.append(text)
            elif hasattr(item, 'root') and hasattr(item.root, 'text'):
                # Part wrapper with TextPart inside
                text = (item.root.text or "").strip()
                if text:
                    text_chunks.append(text)
            elif isinstance(item, DataPart) and isinstance(item.data, dict):
                # Try to extract meaningful text from DataPart
                if 'text' in item.data:
                    text = str(item.data['text']).strip()
                    if text:
                        text_chunks.append(text)
            elif hasattr(item, 'root') and hasattr(item.root, 'data') and isinstance(item.root.data, dict):
                # Part wrapper with DataPart inside
                if 'text' in item.root.data:
                    text = str(item.root.data['text']).strip()
                if text:
                    text_chunks.append(text)

        if not text_chunks:
            return

        combined = "\n\n".join(text_chunks)
        if len(combined) > self.last_host_turn_max_chars:
            combined = combined[: self.last_host_turn_max_chars] + "..."

        session_context.last_host_turn_text = combined
        session_context.last_host_turn_agent = agent_name
        history = list(getattr(session_context, "host_turn_history", []))
        history.append({"agent": agent_name, "text": combined})
        if len(history) > self.last_host_turns:
            history = history[-self.last_host_turns :]
        session_context.host_turn_history = history
        
        log_debug(f"[Context] Updated host_turn_history with response from {agent_name} ({len(combined)} chars)")
        logger.debug(
            "[A2A] Cached host turn for agent %s (len=%d, history=%d)",
            agent_name,
            len(combined),
            len(getattr(session_context, "host_turn_history", [])),
        )

    async def _load_agent_from_catalog(self, agent_name: str) -> bool:
        """
        Load an agent from the global catalog and register it for this session.
        
        This enables workflows and scheduled workflows to call agents that aren't
        explicitly registered to the session. The agent just needs to exist in
        the catalog (database).
        
        Args:
            agent_name: Name of the agent to load (can be partial/fuzzy match)
            
        Returns:
            True if agent was loaded successfully, False if not found
        """
        try:
            from service.agent_registry import get_registry
            from a2a.types import AgentCard, AgentSkill, AgentCapabilities, AgentProvider
            
            registry = get_registry()
            
            # First try exact match
            agent_config = registry.get_agent(agent_name)
            
            # If not found, try fuzzy matching
            if not agent_config:
                all_agents = registry.get_all_agents()
                search_lower = agent_name.lower()
                
                # Try to find agent by partial name match
                for agent in all_agents:
                    agent_name_lower = agent.get('name', '').lower()
                    # Check if search term is contained in agent name or vice versa
                    if search_lower in agent_name_lower or agent_name_lower in search_lower:
                        agent_config = agent
                        log_debug(f"[CATALOG_FALLBACK] Fuzzy match: '{agent_name}' -> '{agent.get('name')}'")
                        break
                    # Also check for word overlap (e.g., "QuickBooks" matches "AI Foundry QuickBooks Agent")
                    search_words = set(search_lower.split())
                    agent_words = set(agent_name_lower.split())
                    if search_words & agent_words:  # If there's any word overlap
                        agent_config = agent
                        log_debug(f"[CATALOG_FALLBACK] Word match: '{agent_name}' -> '{agent.get('name')}'")
                        break

            if not agent_config:
                log_warning(f"[CATALOG_FALLBACK] Agent '{agent_name}' not found in catalog (tried fuzzy match)")
                return False

            log_debug(f"[CATALOG_FALLBACK] Found agent '{agent_config.get('name')}' in catalog: {agent_config.get('url')}")
            
            # Build AgentCard from catalog data
            skills = []
            if agent_config.get('skills'):
                for skill in agent_config['skills']:
                    if isinstance(skill, dict):
                        skills.append(AgentSkill(
                            id=skill.get('id', skill.get('name', '')),
                            name=skill.get('name', ''),
                            description=skill.get('description', '')
                        ))
            
            caps_data = agent_config.get('capabilities', {})
            if isinstance(caps_data, dict):
                capabilities = AgentCapabilities(
                    streaming=caps_data.get('streaming', False),
                    pushNotifications=caps_data.get('pushNotifications', False)
                )
            else:
                capabilities = AgentCapabilities(streaming=False, pushNotifications=False)
            
            provider = None
            if agent_config.get('provider'):
                prov_data = agent_config['provider']
                if isinstance(prov_data, dict):
                    provider = AgentProvider(organization=prov_data.get('organization', ''))
            
            card = AgentCard(
                name=agent_config['name'],
                url=agent_config['url'],
                description=agent_config.get('description', ''),
                version=agent_config.get('version', '1.0.0'),
                skills=skills if skills else None,
                capabilities=capabilities,
                provider=provider
            )
            
            # Register the agent card (this adds to self.cards and self.remote_agent_connections)
            self.register_agent_card(card)
            
            log_debug(f"[CATALOG_FALLBACK] Registered agent '{agent_name}' from catalog")
            return True
            
        except Exception as e:
            log_warning(f"[CATALOG_FALLBACK] Error loading agent '{agent_name}': {e}")
            return False

    async def send_message(
        self,
        agent_name: str,
        message: str,
        tool_context: Any,
        suppress_streaming: bool = True,
        file_uris: Optional[List[str]] = None,
        video_metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Send a message to a remote agent and handle the A2A protocol response.
        
        This is the core method for agent-to-agent communication. It:
        - Adds conversation context from previous agent interactions
        - Searches semantic memory for relevant past conversations
        - Handles A2A Task protocol responses (completed, failed, input_required, etc.)
        - Implements retry logic for rate limits and transient failures
        - Converts agent responses into formats usable by other agents
        - Stores all interactions in memory for future retrieval
        
        EXPLICIT FILE ROUTING (Option 3):
        - Files are passed explicitly via file_uris parameter
        - GPT-4 sees file URIs in agent responses and decides which to pass
        - This enables proper parallel execution without shared state issues
        
        Args:
            agent_name: Name of the target remote agent
            message: The message/task to send to the agent
            tool_context: Context object with session state and artifact storage
            suppress_streaming: If True, don't stream to main chat (used for sub-agent calls)
                               If False, stream to UI (used for direct user-facing responses)
            file_uris: Optional list of file URIs to include with the message
            video_metadata: Optional dict with video_id for remix operations
        
        Returns:
            List of response parts (text, files, data) from the remote agent
        """
        """Sends a task using the A2A protocol with parallel execution support.
        
        This version is optimized for parallel agent execution by:
        1. Preserving shared context IDs across parallel calls
        2. Reducing synchronous pre-await work
        3. Simplifying event processing
        """
        log_debug(f"[SEND_MESSAGE] ENTERING send_message for agent: {agent_name}")
        with tracer.start_as_current_span("send_message") as span:
            span.set_attribute("agent_name", agent_name)
            span.set_attribute("suppress_streaming", suppress_streaming)
            session_context = tool_context.state  # Should be SessionContext
            if not isinstance(session_context, SessionContext):
                raise TypeError(
                    "tool_context.state must be a SessionContext instance for A2A-compliant send_message"
                )

            # CHECK FOR CANCELLATION - bail early if workflow was cancelled
            if self.is_cancelled(session_context.contextId):
                log_info(f"[SEND_MESSAGE] Workflow cancelled, skipping call to {agent_name}")
                return ["[Workflow cancelled by user]"]

            # CRITICAL: DO NOT generate new contextId - it comes from the session_context
            # The session_context already has the correct contextId from the HTTP request
            import uuid
            if not session_context.task_id:
                session_context.task_id = str(uuid.uuid4())
            if not session_context.message_id:
                session_context.message_id = str(uuid.uuid4())

            # Simplified telemetry - reduced synchronous work for parallel execution
            span.set_attribute("operation.type", "agent_delegation")
            span.set_attribute("agent_name", agent_name)
            span.set_attribute("context_id", session_context.contextId)
            
            # Check if agent exists - if not, try to load from global catalog
            # This enables workflows/scheduled workflows to call agents without session registration
            if agent_name not in self.remote_agent_connections:
                log_debug(f"[SEND_MESSAGE] Agent '{agent_name}' not in session, checking global catalog...")
                agent_loaded = await self._load_agent_from_catalog(agent_name)
                if not agent_loaded:
                    available_agents = list(self.remote_agent_connections.keys())
                    log_warning(f"[SEND_MESSAGE] Agent '{agent_name}' not found in session or catalog! Available: {available_agents}")
                    raise ValueError(f"Agent '{agent_name}' not found. Available agents: {available_agents}")
                log_debug(f"[SEND_MESSAGE] Agent '{agent_name}' loaded from catalog")
            
            client = self.remote_agent_connections[agent_name]
            if not client:
                log_warning(f"[SEND_MESSAGE] Client not available for {agent_name}")
                raise ValueError(f"Client not available for {agent_name}")

            # Ensure message is clean text, not a JSON structure
            clean_message = message
            if isinstance(message, str) and message.strip().startswith('{') and 'contextId' in message:
                # This looks like a stringified A2A message - extract just the text
                try:
                    msg_obj = json.loads(message)
                    if isinstance(msg_obj, dict) and 'parts' in msg_obj:
                        for part in msg_obj['parts']:
                            if isinstance(part, dict) and part.get('kind') == 'text' and 'text' in part:
                                clean_message = part['text']
                                log_warning(f"Cleaned JSON message structure to text: {clean_message[:100]}...")
                                break
                except:
                    pass  # Keep original if parsing fails

            # Add conversation context to message (this can be optimized further)
            contextualized_message = await self._add_context_to_message(
                clean_message,
                session_context,
                thread_id=None,
                target_agent_name=agent_name,
            )
            
            # Log the size of the contextualized message for debugging token usage
            log_debug(f"[send_message] Message to {agent_name}: {len(contextualized_message)} chars (~{len(contextualized_message)//4} tokens)")
            if len(contextualized_message) > 500:
                log_debug(f"Preview: {contextualized_message[:200]}...")

            # Respect any active cooldown for this agent due to throttling
            try:
                cool_until = session_context.agent_cooldowns.get(agent_name, 0)
                now_ts = time.time()
                if cool_until and cool_until > now_ts:
                    wait_s = min(60, max(0, int(cool_until - now_ts)))
                    if wait_s > 0:
                        # Use contextvar for async-safe context isolation
                        throttle_context_id = _current_context_id.get() or session_context.contextId
                        asyncio.create_task(self._emit_granular_agent_event(agent_name, f"throttled; waiting {wait_s}s", throttle_context_id, event_type="info"))
                        await asyncio.sleep(wait_s)
            except Exception:
                pass
            
            # Use per-agent taskId only if the previous task for this agent is actively in-progress
            # NOTE: Do NOT reuse task_id for "input-required" state - when the remote agent returns
            # input_required, it means the task is paused waiting for human input. If the human
            # responds OR if a new message comes in, we should create a NEW task, not reuse the old one.
            # The A2A SDK will reject reusing a task that has already completed or been processed.
            taskId = None
            last_task_id = session_context.agent_task_ids.get(agent_name)
            last_task_state = session_context.agent_task_states.get(agent_name)
            # Only reuse task if it's actively working (not paused, not terminal)
            if last_task_id and last_task_state in {"working", "submitted"}:
                taskId = last_task_id
            else:
                # Clear stale task state to ensure clean slate for new task
                if agent_name in session_context.agent_task_ids:
                    del session_context.agent_task_ids[agent_name]
                if agent_name in session_context.agent_task_states:
                    del session_context.agent_task_states[agent_name]
            # CRITICAL FIX: Use contextvar for async-safe context isolation
            # The contextvar is set correctly in run_conversation_with_parts, but session_context
            # may have a stale contextId from a previous workflow when passed through function params
            contextId = _current_context_id.get() or session_context.contextId
            log_debug(f"[send_message] Using contextId: {contextId} (contextvar: {_current_context_id.get()}, session: {session_context.contextId})")
            messageId = str(uuid.uuid4())  # Generate fresh message ID for this specific call

            prepared_parts: List[Any] = [Part(root=TextPart(text=contextualized_message))]
            
            # EXPLICIT FILE ROUTING (Option 3): Construct parts from arguments
            # GPT-4 passes file_uris and video_metadata explicitly - no shared state needed
            log_foundry_debug(f"Before sending to {agent_name}:")
            log_debug(f"  file_uris: {file_uris}")
            log_debug(f"  video_metadata: {video_metadata}")
            log_debug(f"  agent_mode: {getattr(session_context, 'agent_mode', False)}")

            # Add FileParts from explicit file_uris (passed by GPT-4 from previous agent responses)
            # Look up stored metadata (name, role) to preserve info lost in URI-only routing
            uri_metadata = getattr(session_context, '_file_uri_metadata', {})
            if file_uris:
                log_debug(f"Adding {len(file_uris)} explicit file URIs for remote agent {agent_name}")
                for uri in file_uris:
                    if uri and isinstance(uri, str) and uri.startswith(('http://', 'https://')):
                        # Look up stored metadata by stripping SAS params
                        lookup_key = uri.split('?')[0]
                        stored_meta = uri_metadata.get(lookup_key, {})

                        # Use stored name if available, otherwise extract from URI path
                        file_name = stored_meta.get('name') or (uri.split('/')[-1].split('?')[0] if '/' in uri else 'file')
                        stored_role = stored_meta.get('role')

                        # Guess mime type from extension
                        ext = file_name.split('.')[-1].lower() if '.' in file_name else ''
                        mime_map = {
                            'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                            'gif': 'image/gif', 'webp': 'image/webp', 'mp4': 'video/mp4',
                            'pdf': 'application/pdf', 'mp3': 'audio/mpeg', 'wav': 'audio/wav'
                        }
                        mime_type = mime_map.get(ext, 'application/octet-stream')

                        file_part_kwargs = {'file': FileWithUri(
                            uri=uri,
                            name=file_name,
                            mimeType=mime_type
                        )}
                        if stored_role:
                            file_part_kwargs['metadata'] = {'role': stored_role}

                        file_part = FilePart(**file_part_kwargs)
                        prepared_parts.append(Part(root=file_part))
                        log_debug(f"  Added FilePart: {file_name} ({mime_type}, role={stored_role})")
            
            # Add video metadata for remix operations (passed by GPT-4)
            if video_metadata and video_metadata.get('video_id'):
                video_id = video_metadata['video_id']
                log_debug(f"Adding video_remix_request with video_id: {video_id}")
                remix_data_part = DataPart(data={
                    "type": "video_remix_request",
                    "video_id": video_id
                })
                prepared_parts.append(Part(root=remix_data_part))

            request = MessageSendParams(
                message=Message(
                    role='user',
                    parts=prepared_parts,
                    message_id=messageId,
                    context_id=contextId,
                    task_id=taskId,
                ),
                configuration=MessageSendConfiguration(
                    acceptedOutputModes=['text', 'text/plain', 'image/png'],
                ),
            )
            
            log_debug(f"Calling agent: {agent_name} with context: {contextId}, task_id: {taskId}")
            log_debug(f"[SEND_MESSAGE] taskId={taskId}, last_task_id={last_task_id}, last_task_state={last_task_state}")
            
            # Track start time for processing duration
            start_time = time.time()
            
            # Create a user-friendly query preview for status messages
            query_preview = message[:200] + "..." if len(message) > 200 else message
            query_preview = " ".join(query_preview.split())
            
            # ========================================================================
            # EMIT WORKFLOW MESSAGE: Clear "Calling agent" message for workflow panel
            # ========================================================================
            asyncio.create_task(self._emit_granular_agent_event(
                agent_name, f"Contacting {agent_name}...", contextId,
                event_type="agent_progress"
            ))
            
            # ========================================================================
            # EMIT INITIAL STATUS: "submitted" - task has been sent to remote agent
            # This is for the SIDEBAR to show the agent is starting work
            # ========================================================================
            asyncio.create_task(self._emit_simple_task_status(agent_name, "submitted", contextId, taskId))
            
            try:
                # CRITICAL: Store HOST's contextId for use in callbacks
                # Callbacks receive events with remote agent's contextId, but we need
                # to route WebSocket events using the host's session contextId
                # Use BOTH contextvars (async-safe) and instance variable (backwards compat)
                _current_context_id.set(contextId)
                self._current_host_context_id = contextId
                host_context_id = contextId
                
                # SIMPLIFIED: Callback for streaming execution that handles file artifacts
                # Status events are handled ONLY in _default_task_callback -> _emit_task_event
                # Track if we've emitted "working" status for this callback session
                _working_emitted = {"emitted": False}
                
                def streaming_task_callback(event, agent_card):
                    """Enhanced callback for streaming execution that captures detailed agent activities"""
                    agent_name = agent_card.name
                    log_debug(f"[streaming_task_callback] CALLED for {agent_name}: {type(event).__name__}")
                    log_debug(f"[STREAMING] Detailed callback from {agent_name}: {type(event).__name__}")
                    
                    # ========================================================================
                    # EMIT "working" status on FIRST callback - shows agent is processing
                    # ========================================================================
                    if not _working_emitted["emitted"]:
                        _working_emitted["emitted"] = True
                        log_debug(f"[WORKING] First callback - emitting working status for {agent_name}")
                        asyncio.create_task(self._emit_simple_task_status(agent_name, "working", contextId, taskId))
                    
                    # Emit granular events based on the type of update
                    if hasattr(event, 'kind'):
                        event_kind = getattr(event, 'kind', 'unknown')
                        
                        if event_kind == 'status-update':
                            # Extract task state to decide if we should emit a UI event
                            task_state = None
                            if hasattr(event, 'status') and event.status and hasattr(event.status, 'state'):
                                state_obj = event.status.state
                                task_state = state_obj.value if hasattr(state_obj, 'value') else str(state_obj)
                            
                            # SKIP emitting UI events for final states (completed, input_required)
                            # These are handled separately after the streaming completes
                            # Only emit for intermediate states (working, submitted)
                            if task_state in ('completed', 'input_required', 'input-required', 'failed'):
                                log_debug(f"[STREAMING] Skipping UI emit for final state {task_state} from {agent_name}")
                            else:
                                # Extract detailed status information for intermediate states
                                status_text = "processing"
                                if hasattr(event, 'status') and event.status:
                                    if hasattr(event.status, 'message') and event.status.message:
                                        if hasattr(event.status.message, 'parts') and event.status.message.parts:
                                            # Process ALL parts - don't break early so we catch all image artifacts
                                            for part in event.status.message.parts:
                                                # Check for text parts
                                                if hasattr(part, 'root') and hasattr(part.root, 'text'):
                                                    status_text = part.root.text
                                                    # Continue processing to find image artifacts - don't break!
                                                # Check for image artifacts in DataPart
                                                elif hasattr(part, 'root') and hasattr(part.root, 'data') and isinstance(part.root.data, dict):
                                                    artifact_uri = part.root.data.get('artifact-uri')
                                                    if artifact_uri:
                                                        log_debug(f"Found image artifact in streaming event: {artifact_uri}")
                                                        # Files are already in blob storage at uploads/{session_id}/
                                                        
                                                        # Determine if file will be auto-indexed via Content Understanding
                                                        stream_file_name = part.root.data.get("file-name", "agent-artifact.png")
                                                        from .a2a_document_processor import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, IMAGE_EXTENSIONS, DOCUMENT_EXTENSIONS, TEXT_EXTENSIONS, CU_TEXT_FORMATS
                                                        indexable_exts = DOCUMENT_EXTENSIONS + IMAGE_EXTENSIONS + VIDEO_EXTENSIONS + AUDIO_EXTENSIONS + TEXT_EXTENSIONS + CU_TEXT_FORMATS
                                                        stream_file_ext = '.' + stream_file_name.split('.')[-1].lower() if '.' in stream_file_name else ''
                                                        stream_status = 'processing' if stream_file_ext in indexable_exts else 'uploaded'
                                                        
                                                        # Emit file_uploaded event - USE HOST'S contextId for routing!
                                                        asyncio.create_task(self._emit_file_artifact_event(
                                                            filename=stream_file_name,
                                                            uri=artifact_uri,
                                                            context_id=host_context_id,
                                                            agent_name=agent_name,
                                                            content_type="image/png",
                                                            size=part.root.data.get("file-size", 0),
                                                            status=stream_status
                                                        ))
                                                # Check for image artifacts in FilePart
                                                elif hasattr(part, 'root') and hasattr(part.root, 'file'):
                                                    file_obj = part.root.file
                                                    if isinstance(file_obj, FileWithUri):
                                                        file_uri = file_obj.uri
                                                        if file_uri and str(file_uri).startswith(("http://", "https://")):
                                                            log_debug(f"Found image artifact in streaming event (FilePart): {file_uri}")
                                                            # Capture values to avoid closure issues
                                                            file_name = file_obj.name
                                                            mime_type = file_obj.mimeType if hasattr(file_obj, 'mimeType') else 'image/png'
                                                            
                                                            # Determine if file will be auto-indexed via Content Understanding
                                                            from .a2a_document_processor import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, IMAGE_EXTENSIONS, DOCUMENT_EXTENSIONS, TEXT_EXTENSIONS, CU_TEXT_FORMATS
                                                            indexable_exts = DOCUMENT_EXTENSIONS + IMAGE_EXTENSIONS + VIDEO_EXTENSIONS + AUDIO_EXTENSIONS + TEXT_EXTENSIONS + CU_TEXT_FORMATS
                                                            stream_file_ext = '.' + file_name.split('.')[-1].lower() if '.' in file_name else ''
                                                            stream_status = 'processing' if stream_file_ext in indexable_exts else 'uploaded'
                                                            
                                                            # UNIFIED STORAGE: No need to register - files are already in uploads/{session_id}/
                                                            # The /api/files endpoint queries blob storage directly
                                                            
                                                            # Emit file_uploaded event - USE HOST'S contextId for routing!
                                                            asyncio.create_task(self._emit_file_artifact_event(
                                                                filename=file_name,
                                                                uri=str(file_uri),
                                                                context_id=host_context_id,
                                                                agent_name=agent_name,
                                                                content_type=mime_type,
                                                                size=0,
                                                                status=stream_status
                                                            ))
                                    elif hasattr(event.status, 'state'):
                                        state = event.status.state
                                        if hasattr(state, 'value'):
                                            state_value = state.value
                                        else:
                                            state_value = str(state)
                                        
                                        # Calculate elapsed time for context
                                        elapsed_seconds = int(time.time() - start_time)
                                        elapsed_str = f" ({elapsed_seconds}s)" if elapsed_seconds >= 5 else ""
                                        
                                        # Make status messages friendly and personalized with user's query context
                                        if state_value == "working":
                                            status_text = f"{agent_name} is working on: \"{query_preview}\"{elapsed_str}"
                                        elif state_value == "submitted":
                                            status_text = f"Request sent to {agent_name}: \"{query_preview}\""
                                        else:
                                            status_text = f"{agent_name}: {state_value}{elapsed_str}"
                                
                                # Filter out noisy/internal status messages before sending to UI
                                status_lower = status_text.lower().strip()
                                skip_patterns = [
                                    "processing",          # generic fallback, adds no value
                                    "mcp_tool",            # raw internal tool name
                                    "mcp_call",            # raw internal event type
                                ]
                                should_skip = (
                                    status_lower in skip_patterns
                                    or len(status_text.strip()) < 3
                                    or status_lower.startswith("rate limited")  # internal retry noise
                                    or status_lower.startswith("throttled")     # internal retry noise
                                )
                                
                                if not should_skip:
                                    # Classify the event type based on content
                                    stream_event_type = "agent_progress"
                                    stream_metadata = None
                                    sl = status_text.lower()
                                    if any(kw in sl for kw in ["creating ", "searching ", "looking up", "listing ", "retrieving ", "using "]):
                                        stream_event_type = "tool_call"
                                        # Extract tool action name
                                        stream_metadata = {"tool_action": status_text.strip()}
                                    elif "is working on" in sl or "request sent to" in sl:
                                        stream_event_type = "agent_progress"
                                    
                                    # Stream detailed status to UI - USE HOST'S contextId for routing!
                                    asyncio.create_task(self._emit_granular_agent_event(
                                        agent_name, status_text, host_context_id,
                                        event_type=stream_event_type, metadata=stream_metadata
                                    ))
                            
                        elif event_kind == 'artifact-update':
                            # Agent is generating artifacts - USE HOST'S contextId for routing!
                            elapsed_seconds = int(time.time() - start_time)
                            elapsed_str = f" ({elapsed_seconds}s)" if elapsed_seconds >= 5 else ""
                            asyncio.create_task(self._emit_granular_agent_event(
                                agent_name, f"{agent_name} is preparing results{elapsed_str}", host_context_id,
                                event_type="agent_progress"
                            ))
                        
                        elif event_kind == 'task':
                            # Initial task creation - USE HOST'S contextId for routing!
                            asyncio.create_task(self._emit_granular_agent_event(
                                agent_name, f"{agent_name} has started working on: \"{query_preview}\"", host_context_id,
                                event_type="agent_progress"
                            ))
                    
                    # Call the original callback for task management
                    return self._default_task_callback(event, agent_card)                # Emit outgoing message event for DAG display (use original message, not contextualized)
                clean_message = message
                if isinstance(message, dict):
                    clean_message = message.get('text', message.get('message', str(message)))
                elif not isinstance(message, str):
                    clean_message = str(message)
                
                # Truncate very long messages for DAG display
                if len(clean_message) > 500:
                    clean_message = clean_message[:497] + "..."
                
                asyncio.create_task(self._emit_outgoing_message_event(agent_name, clean_message, contextId))
                
                response = await client.send_message(request, streaming_task_callback)
                log_debug(f"Agent {agent_name} responded successfully")
                
            except Exception as e:
                log_debug(f"Agent {agent_name} failed: {e}")
                import traceback
                log_debug(f"Traceback: {traceback.format_exc()}")
                raise
            
            # Process response based on type
            if isinstance(response, Task):
                task = response
                log_debug(f"[TASK RESPONSE] Agent {agent_name} returned Task with state={task.status.state}")
                log_debug(f"Task response from {agent_name}: state={task.status.state if hasattr(task, 'status') else 'N/A'}")
                
                # Update session context
                context_id = get_context_id(task)
                if context_id:
                    session_context.contextId = context_id
                t_id = get_task_id(task)
                session_context.agent_task_ids[agent_name] = t_id
                
                # Track active task for cancellation support
                if contextId not in self._active_agent_tasks:
                    self._active_agent_tasks[contextId] = {}
                self._active_agent_tasks[contextId][agent_name] = t_id
                
                try:
                    state_val = task.status.state.value if hasattr(task.status.state, 'value') else str(task.status.state)
                except Exception:
                    state_val = "working"
                session_context.agent_task_states[agent_name] = state_val
                
                # Handle task states
                if task.status.state == TaskState.completed:
                    # IMPORTANT: Clear the task_id so future requests create new tasks
                    # The A2A protocol treats completed tasks as terminal - we can't reuse them
                    log_debug(f"[TASK COMPLETED] Clearing task_id and state for '{agent_name}'")
                    log_debug(f"Before: agent_task_ids={dict(session_context.agent_task_ids)}")
                    log_debug(f"Before: agent_task_states={dict(session_context.agent_task_states)}")
                    if agent_name in session_context.agent_task_ids:
                        del session_context.agent_task_ids[agent_name]
                    if agent_name in session_context.agent_task_states:
                        del session_context.agent_task_states[agent_name]
                    # Clear from active tasks (cancellation tracking)
                    if contextId in self._active_agent_tasks:
                        self._active_agent_tasks[contextId].pop(agent_name, None)
                    log_debug(f"After: agent_task_ids={dict(session_context.agent_task_ids)}")
                    log_debug(f"After: agent_task_states={dict(session_context.agent_task_states)}")
                    log_debug(f"Cleared completed task state for {agent_name} to allow new tasks")
                    
                    # Emit completed status for remote agent - the streaming callback doesn't always
                    # receive a final status-update event with state=completed from remote agents
                    asyncio.create_task(self._emit_simple_task_status(agent_name, "completed", contextId, taskId))
                    asyncio.create_task(self._emit_granular_agent_event(
                        agent_name, f"{agent_name} has completed the task successfully", contextId,
                        event_type="agent_complete"
                    ))
                    
                    response_parts = []
                    
                    # Extract token usage from message parts before converting
                    if task.status.message and task.status.message.parts:
                        for part in task.status.message.parts:
                            if hasattr(part, 'root') and hasattr(part.root, 'kind') and part.root.kind == 'data':
                                data = getattr(part.root, 'data', {})
                                if isinstance(data, dict) and data.get('type') == 'token_usage':
                                    self.agent_token_usage[agent_name] = {
                                        'prompt_tokens': data.get('prompt_tokens', 0),
                                        'completion_tokens': data.get('completion_tokens', 0),
                                        'total_tokens': data.get('total_tokens', 0)
                                    }
                                    log_debug(f"[send_message] Token usage from {agent_name}: prompt={data.get('prompt_tokens', 0)}, completion={data.get('completion_tokens', 0)}, total={data.get('total_tokens', 0)}")
                                    break
                    
                    if task.status.message:
                        response_parts.extend(
                            await self.convert_parts(task.status.message.parts, tool_context)
                        )
                    if task.artifacts:
                        for artifact in task.artifacts:
                            response_parts.extend(
                                await self.convert_parts(artifact.parts, tool_context)
                            )

                    # Add file artifacts from this response to _agent_generated_artifacts for UI display
                    # AND emit WebSocket events so the frontend/test can receive them
                    for item in response_parts:
                        is_file = isinstance(item, FilePart) or (hasattr(item, 'root') and isinstance(item.root, FilePart))
                        is_data = isinstance(item, DataPart) or (hasattr(item, 'root') and isinstance(item.root, DataPart))
                        if is_file or is_data:
                            if not hasattr(session_context, '_agent_generated_artifacts'):
                                session_context._agent_generated_artifacts = []
                            session_context._agent_generated_artifacts.append(item)
                            
                            # EMIT FILE ARTIFACT EVENT for WebSocket subscribers
                            # This ensures frontend/tests receive file parts from completed tasks
                            if is_file:
                                try:
                                    file_part = item.root if hasattr(item, 'root') else item
                                    file_obj = getattr(file_part, 'file', None)
                                    if file_obj:
                                        file_uri = str(getattr(file_obj, 'uri', ''))
                                        file_name = getattr(file_obj, 'name', 'agent-artifact')
                                        mime_type = getattr(file_obj, 'mimeType', 'application/octet-stream')
                                        if file_uri.startswith(('http://', 'https://')):
                                            log_debug(f"Emitting file artifact event for completed task: {file_name}")
                                            # Files are already in blob storage at uploads/{session_id}/
                                            
                                            # Determine if file will be auto-indexed via Content Understanding
                                            # Includes: documents, images, audio, video - all processed by Azure CU
                                            from .a2a_document_processor import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, IMAGE_EXTENSIONS, DOCUMENT_EXTENSIONS, TEXT_EXTENSIONS, CU_TEXT_FORMATS
                                            indexable_extensions = DOCUMENT_EXTENSIONS + IMAGE_EXTENSIONS + VIDEO_EXTENSIONS + AUDIO_EXTENSIONS + TEXT_EXTENSIONS + CU_TEXT_FORMATS
                                            file_ext = '.' + file_name.split('.')[-1].lower() if '.' in file_name else ''
                                            is_indexable = file_ext in indexable_extensions
                                            file_status = 'processing' if is_indexable else 'uploaded'
                                            
                                            asyncio.create_task(self._emit_file_artifact_event(
                                                filename=file_name,
                                                uri=file_uri,
                                                context_id=contextId,
                                                agent_name=agent_name,
                                                content_type=mime_type,
                                                size=0,
                                                status=file_status
                                            ))
                                except Exception as e:
                                    log_debug(f"Error emitting file artifact event: {e}")

                    # ========================================================================
                    # AUTO-INDEX FILE ARTIFACTS: Process documents for memory search
                    # This enables future agents to search/reference files from previous agents
                    # ========================================================================
                    file_artifacts_to_index = []
                    for item in response_parts:
                        is_file = isinstance(item, FilePart) or (hasattr(item, 'root') and isinstance(item.root, FilePart))
                        if is_file:
                            try:
                                file_part = item.root if hasattr(item, 'root') else item
                                file_obj = getattr(file_part, 'file', None)
                                if file_obj:
                                    file_uri = str(getattr(file_obj, 'uri', ''))
                                    file_name = getattr(file_obj, 'name', 'agent-artifact')
                                    mime_type = getattr(file_obj, 'mimeType', 'application/octet-stream')
                                    if file_uri.startswith(('http://', 'https://')):
                                        file_artifacts_to_index.append({
                                            'uri': file_uri,
                                            'name': file_name,
                                            'mime_type': mime_type,
                                            'source_agent': agent_name
                                        })
                            except Exception as e:
                                log_debug(f"Error extracting file artifact for indexing: {e}")
                    
                    # Index documents if we have any file artifacts
                    if file_artifacts_to_index:
                        session_id = contextId.split('::')[0] if '::' in contextId else contextId
                        extracted_contents = await self._index_agent_file_artifacts(
                            file_artifacts=file_artifacts_to_index,
                            session_id=session_id,
                            context_id=contextId,
                            agent_name=agent_name
                        )
                        # Store extracted content on session_context for immediate use
                        # by subsequent steps (e.g., EVALUATE). Azure Search has indexing
                        # latency, so newly stored documents may not be queryable yet.
                        if extracted_contents:
                            if not hasattr(session_context, '_extracted_documents'):
                                session_context._extracted_documents = []
                            session_context._extracted_documents.extend(extracted_contents)

                    self._update_last_host_turn(session_context, agent_name, response_parts)
                    
                    # Store interaction in background (only if inter-agent memory is enabled)
                    enable_memory = getattr(session_context, 'enable_inter_agent_memory', False)
                    if enable_memory:
                        asyncio.create_task(self._store_a2a_interaction_background(
                            outbound_request=request,
                            inbound_response=response,
                            agent_name=agent_name,
                            processing_time=time.time() - start_time,
                            span=span,
                            context_id=contextId
                        ))
                        log_debug(f"[Memory] Storing A2A interaction for {agent_name} (memory enabled)")
                    else:
                        log_debug(f"[Memory] Skipping A2A interaction storage for {agent_name} (memory disabled)")
                    
                    return response_parts
                    
                elif task.status.state == TaskState.failed:
                    log_debug(f"Task failed for {agent_name}")
                    # Emit failed status for remote agent
                    asyncio.create_task(self._emit_simple_task_status(agent_name, "failed", contextId, taskId))
                    retry_after = self._parse_retry_after_from_task(task)
                    max_rate_limit_retries = 3
                    retry_attempt = 0
                    # Use contextvar for async-safe context isolation in retry path
                    retry_context_id = _current_context_id.get() or session_context.contextId

                    while retry_after and retry_after > 0 and retry_attempt < max_rate_limit_retries:
                        retry_attempt += 1
                        session_context.agent_task_states[agent_name] = 'failed'
                        session_context.agent_cooldowns[agent_name] = time.time() + retry_after
                        try:
                            asyncio.create_task(self._emit_granular_agent_event(agent_name, f"rate limited; retrying in {retry_after}s (attempt {retry_attempt}/{max_rate_limit_retries})", retry_context_id, event_type="info"))
                        except Exception:
                            pass

                        await asyncio.sleep(min(60, retry_after))

                        retry_request = MessageSendParams(
                            id=str(uuid.uuid4()),
                            message=Message(
                                role='user',
                                parts=[Part(root=TextPart(text=contextualized_message))],
                                messageId=str(uuid.uuid4()),
                                contextId=retry_context_id,
                                taskId=None,
                            ),
                            configuration=MessageSendConfiguration(
                                acceptedOutputModes=['text', 'text/plain', 'image/png'],
                            ),
                        )
                        try:
                            retry_response = await client.send_message(retry_request, self.task_callback)
                        except Exception as e:
                            log_debug(f"[STREAMING] Retry after rate limit failed for {agent_name}: {e}")
                            break

                        if isinstance(retry_response, Task):
                            task2 = retry_response
                            context_id2 = get_context_id(task2)
                            if context_id2:
                                session_context.contextId = context_id2
                            session_context.agent_task_ids[agent_name] = task2.id
                            try:
                                state_val2 = task2.status.state.value if hasattr(task2.status.state, 'value') else str(task2.status.state)
                            except Exception:
                                state_val2 = 'working'
                            session_context.agent_task_states[agent_name] = state_val2

                            if task2.status.state == TaskState.completed:
                                retry_parts = []
                                if task2.status.message:
                                    retry_parts.extend(await self.convert_parts(task2.status.message.parts, tool_context))
                                if task2.artifacts:
                                    for artifact in task2.artifacts:
                                        retry_parts.extend(await self.convert_parts(artifact.parts, tool_context))
                                self._update_last_host_turn(session_context, agent_name, retry_parts)
                                return retry_parts

                            if task2.status.state == TaskState.input_required:
                                # Set pending_input_agent for HITL routing
                                current_task_id = session_context.agent_task_ids.get(agent_name)
                                session_context.pending_input_agent = agent_name
                                session_context.pending_input_task_id = current_task_id
                                log_info(f"[HITL] Retry task input_required from '{agent_name}', setting pending_input_agent (task_id: {current_task_id})")
                                
                                if task2.status.message:
                                    retry_input = await self.convert_parts(task2.status.message.parts, tool_context)
                                    self._update_last_host_turn(session_context, agent_name, retry_input)
                                    return retry_input
                                return [f"Agent {agent_name} requires additional input"]

                            if task2.status.state == TaskState.failed:
                                retry_after = self._parse_retry_after_from_task(task2)
                                if retry_after:
                                    continue

                            return [f"Agent {agent_name} is processing your request"]

                        if isinstance(retry_response, Message):
                            retry_result = await self.convert_parts(retry_response.parts, tool_context)
                            self._update_last_host_turn(session_context, agent_name, retry_result)
                            return retry_result

                        return [str(retry_response)]

                    # IMPORTANT: Clear the task_id so future requests to this agent create a NEW task
                    # Without this, the A2A SDK rejects new messages with "Task is in terminal state: failed"
                    if agent_name in session_context.agent_task_ids:
                        del session_context.agent_task_ids[agent_name]
                        log_debug(f"Cleared task_id for {agent_name} after failed task")
                    # Clear from active tasks (cancellation tracking)
                    if contextId in self._active_agent_tasks:
                        self._active_agent_tasks[contextId].pop(agent_name, None)
                    return [f"Agent {agent_name} failed to complete the task"]

                elif task.status.state == TaskState.input_required:
                    log_warning(f"[HITL] Agent {agent_name} requires input - SETTING pending_input_agent!")
                    log_debug(f"[STREAMING] Agent {agent_name} requires input")
                    
                    # CRITICAL: Set pending_input_agent so the human response gets routed correctly
                    # The streaming callback also sets this, but we need it here as a fallback
                    # in case the response comes directly without a streaming status-update event
                    current_task_id = session_context.agent_task_ids.get(agent_name)
                    session_context.pending_input_agent = agent_name
                    session_context.pending_input_task_id = current_task_id
                    log_debug(f"[HITL] Task response input_required from '{agent_name}', setting pending_input_agent='{agent_name}'(task_id: {current_task_id})")
                    log_info(f"[HITL] Task response input_required from '{agent_name}', setting pending_input_agent (task_id: {current_task_id})")
                    
                    if task.status.message:
                        response_parts = await self.convert_parts(task.status.message.parts, tool_context)
                        self._update_last_host_turn(session_context, agent_name, response_parts)
                        return response_parts
                    return [f"Agent {agent_name} requires additional input"]
                    
                else:
                    # Handle working/pending states
                    return [f"Agent {agent_name} is processing your request"]
                    
            elif isinstance(response, Message):
                # Direct message response
                result = await self.convert_parts(response.parts, tool_context)
                self._update_last_host_turn(session_context, agent_name, result)
                
                # Store interaction in background (only if inter-agent memory is enabled)
                enable_memory = getattr(session_context, 'enable_inter_agent_memory', False)
                if enable_memory:
                    asyncio.create_task(self._store_a2a_interaction_background(
                        outbound_request=request,
                        inbound_response=response,
                        agent_name=agent_name,
                        processing_time=time.time() - start_time,
                        span=span,
                        context_id=contextId
                    ))
                    log_debug(f"[Memory] Storing A2A interaction for {agent_name} (memory enabled)")
                else:
                    log_debug(f"[Memory] Skipping A2A interaction storage for {agent_name} (memory disabled)")
                
                return result
                
            elif isinstance(response, str):
                self._update_last_host_turn(session_context, agent_name, [response])
                return [response]
                
            else:
                return [str(response)]
            
    async def _add_context_to_message(
        self,
        message: str,
        session_context: SessionContext,
        thread_id: str = None,
        target_agent_name: Optional[str] = None,
    ) -> str:
        """
        Enhance agent messages with relevant context for better continuity and accuracy.
        
        Context enrichment strategies:
        1. **Last Turn Context**: Include recent responses from other agents so the current
           agent knows what has already been discussed/done (configurable via env vars)
        
        2. **Memory Search**: Query semantic memory service to find similar past conversations
           that might provide useful precedents or patterns (only if enabled for this session)
        
        3. **Cross-Agent Handoff**: When agent B is called after agent A, include agent A's
           response so agent B can build on it rather than starting from scratch
        
        The context is carefully sized to stay within token limits while maximizing
        the useful information provided to the agent.
        
        Args:
            message: The original message to send to the agent
            session_context: Current session state with conversation history
            thread_id: Optional thread ID for Azure AI Foundry conversation
            target_agent_name: Name of the agent receiving this message
            
        Returns:
            Enhanced message with relevant context prepended
        """
        """Add relevant conversation context and memory insights to the message for better agent responses.
        
        Following Google A2A best practices: host manages context and includes it in agent messages.
        
        Context injection behavior based on mode and inter-agent memory toggle:
        
        AGENT MODE + MEMORY OFF (minimal context for focused workflows):
          - Recent agent outputs: Only immediate previous agent (1 response)
          - Vector search: Disabled
          - Use case: Sequential workflows where agents only need the last step
          
        AGENT MODE + MEMORY ON (full context):
          - Recent agent outputs: Last N agents (default: 1, configurable)
          - Vector search: Enabled (searches all past interactions)
          - Use case: Complex reasoning requiring broader context
          
        STANDARD MODE (always full context):
          - Recent agent outputs: Last N agents (default: 1, configurable)
          - Vector search: Enabled when memory ON, disabled when OFF
          - Use case: User conversations with multi-turn context
        """
        is_agent_mode = hasattr(session_context, 'agent_mode') and session_context.agent_mode
        mode_label = "Agent Mode" if is_agent_mode else "Standard Mode"
        
        context_parts = []
        
        # Always search memory for relevant context (retrieval is always enabled)
        # The memory toggle only controls STORAGE of new interactions, not retrieval
        try:
            # Retrieve top 10 memory results to ensure we get all chunks of large documents
            # This allows chunk reassembly to work correctly for multi-chunk documents
            # and ensures agents have sufficient context from past interactions
            top_k_results = 10
            # Use contextvar for async-safe context isolation (fixes stale session_context issue)
            effective_context_id = _current_context_id.get() or session_context.contextId
            log_debug(f"[_add_context_to_message] Using context_id: {effective_context_id} (contextvar: {_current_context_id.get()}, session: {session_context.contextId})")
            memory_results = await self._search_relevant_memory(
                query=message,
                context_id=effective_context_id,
                agent_name=None,
                top_k=top_k_results
            )
            
            if memory_results:
                context_parts.append("Relevant context from previous interactions:")
                
                # Process memory results to extract key information
                for i, result in enumerate(memory_results, 1):
                        try:
                            agent_name = result.get('agent_name', 'Unknown')
                            timestamp = result.get('timestamp', 'Unknown')
                                
                            # Get the actual content - try multiple possible locations
                            content_summary = ""
                            
                            # Method 1: Look for content in inbound payload
                            if 'inbound_payload' in result and result['inbound_payload']:
                                inbound = result['inbound_payload']

                                log_memory_debug(f"[MEMORY] Result {i} from {agent_name}:")
                                log_memory_debug(f"[MEMORY] Inbound type: {type(inbound)}")
                                log_memory_debug(f"[MEMORY] Inbound keys: {inbound.keys() if isinstance(inbound, dict) else 'N/A'}")

                                # Parse JSON string if needed
                                if isinstance(inbound, str):
                                    log_memory_debug(f"[MEMORY] Inbound is string, length: {len(inbound)} chars, parsing JSON...")
                                    try:
                                        inbound = json.loads(inbound)
                                        log_memory_debug(f"[MEMORY] Parsed JSON keys: {inbound.keys() if isinstance(inbound, dict) else 'N/A'}")
                                    except json.JSONDecodeError as e:
                                        log_memory_debug(f"[MEMORY] JSON parse failed: {e}")
                                        inbound = {}

                                # Try direct content field (DocumentProcessor format)
                                if isinstance(inbound, dict) and 'content' in inbound:
                                    content_length = len(str(inbound['content']))
                                    log_memory_debug(f"[MEMORY] Found 'content' field: {content_length} chars")
                                    content_summary = str(inbound['content'])
                                    log_memory_debug(f"[MEMORY] Content summary length: {len(content_summary)} chars")
                                    log_memory_debug(f"[MEMORY] Content preview: {content_summary[:200]}...")

                                # Try Task structure: status.message.parts (A2A Task format)
                                if not content_summary and isinstance(inbound, dict) and 'status' in inbound:
                                    status = inbound['status']
                                    if isinstance(status, dict) and 'message' in status:
                                        status_message = status['message']
                                        if isinstance(status_message, dict) and 'parts' in status_message:
                                            parts_content = []
                                            for part in status_message['parts']:
                                                if isinstance(part, dict):
                                                    if 'text' in part:
                                                        parts_content.append(str(part['text']))
                                                    elif 'kind' in part and part['kind'] == 'text' and 'text' in part:
                                                        parts_content.append(str(part['text']))
                                            if parts_content:
                                                content_summary = " ".join(parts_content)

                                # Try parts array at root (A2A Message structure)
                                if not content_summary and isinstance(inbound, dict) and 'parts' in inbound:
                                    parts_content = []
                                    for part in inbound['parts']:
                                        if isinstance(part, dict):
                                            if 'text' in part:
                                                parts_content.append(str(part['text']))
                                            elif 'root' in part and isinstance(part['root'], dict) and 'text' in part['root']:
                                                parts_content.append(str(part['root']['text']))
                                    if parts_content:
                                        content_summary = " ".join(parts_content)
                            
                            # Method 2: Look in outbound payload if inbound didn't work
                            if not content_summary and 'outbound_payload' in result:
                                outbound = result['outbound_payload']
                                
                                if isinstance(outbound, str):
                                    try:
                                        outbound = json.loads(outbound)
                                    except json.JSONDecodeError:
                                        outbound = {}
                                
                                # Try message.parts structure (A2A response format)
                                if isinstance(outbound, dict) and 'message' in outbound and 'parts' in outbound['message']:
                                    parts_content = []
                                    for part in outbound['message']['parts']:
                                        if isinstance(part, dict):
                                            # Try direct text field
                                            if 'text' in part:
                                                parts_content.append(str(part['text']))
                                            # Try root.text structure
                                            elif 'root' in part and isinstance(part['root'], dict) and 'text' in part['root']:
                                                parts_content.append(str(part['root']['text']))
                                            # Try kind=text structure
                                            elif part.get('kind') == 'text' and 'text' in part:
                                                parts_content.append(str(part['text']))
                                    if parts_content:
                                        content_summary = " ".join(parts_content)
                            
                            # Method 3: Skip - don't dump raw JSON, just skip if we can't extract text
                            if not content_summary:
                                # Skip this memory result - we couldn't extract meaningful text
                                log_warning(f"Skipping memory result {i} from {agent_name} - no clean text extracted")
                                continue
                            
                            # CLEANUP: Handle legacy malformed format {'result': '...'} stored in text field
                            # This was caused by str(task.output) being stored instead of task.output.get("result")
                            if content_summary.startswith("{'result':") or content_summary.startswith('{"result":'):
                                try:
                                    import ast
                                    parsed = ast.literal_eval(content_summary) if content_summary.startswith("{'") else json.loads(content_summary)
                                    if isinstance(parsed, dict) and 'result' in parsed:
                                        content_summary = str(parsed['result'])
                                        log_memory_debug(f"Cleaned malformed result format from memory entry {i}")
                                except:
                                    pass  # Keep original if parsing fails
                            
                            # Add to context if we found content
                            if content_summary:
                                # Truncate long content for context efficiency
                                # Use configured max_chars - applies to all agents uniformly
                                max_chars = self.memory_summary_max_chars
                                    
                                if len(content_summary) > max_chars:
                                    content_summary = content_summary[:max_chars] + "..."
                                context_parts.append(f"  {i}. From {agent_name}: {content_summary}")
                            else:
                                log_warning(f"No content found in memory result {i} from {agent_name}")
                        
                        except Exception as e:
                            log_warning(f"Error processing memory result {i}: {e}")
                            continue
                
            else:
                log_debug(f"No relevant memory context found")
        
        except Exception as e:
            log_error(f"Error searching memory: {e}")
            context_parts.append("Note: Unable to retrieve relevant context from memory")
        
        # NOTE: host_turn_history injection has been removed.
        # GPT-4 is now instructed to include all relevant context from previous agents
        # in its message parameter when calling send_message. This eliminates redundant
        # context injection and prevents payload bloat in multi-step workflows.
        # See instructions.py "CONTEXT PASSING (CRITICAL)" section.

        # Fallback: Add minimal recent thread context only if memory search failed
        if not context_parts and thread_id:
            try:
                log_debug("Fallback: Using recent thread context (memory search failed)")
                messages = await self._http_list_messages(thread_id, limit=5)
                
                if messages and len(messages) > 0:
                    context_parts.append("Recent conversation context:")
                    # Only include last 5 exchanges to avoid context bloat
                    for msg in messages[:5]:  # Already in reverse order from _http_list_messages
                        if msg.get('content'):
                            for content in msg['content']:
                                if content.get('type') == 'text' and content.get('text', {}).get('value'):
                                    role = msg.get('role', 'unknown')
                                    text = content['text']['value']
                                    context_parts.append(f"{role}: {text}")
                log_debug(f"Added {len(context_parts)-1} recent messages to context")
            except Exception as e:
                log_error(f"Error accessing thread context: {e}")
        
        # Combine context with original message
        # IMPORTANT: Ensure message is clean text, not JSON structure
        clean_message = message
        if isinstance(message, str):
            # Check if message looks like a JSON/dict structure that was stringified
            if message.strip().startswith('{') and 'contextId' in message:
                # This is a raw message structure, try to extract just the text
                try:
                    msg_obj = json.loads(message)
                    if isinstance(msg_obj, dict) and 'parts' in msg_obj:
                        for part in msg_obj['parts']:
                            if isinstance(part, dict) and part.get('kind') == 'text' and 'text' in part:
                                clean_message = part['text']
                                break
                except:
                    pass  # Keep original if parsing fails
        
        if context_parts:
            full_context = "\n".join(context_parts)
            return f"{full_context}\n\nCurrent request: {clean_message}"
        else:
            return clean_message

    async def _store_a2a_interaction_background(
        self, 
        outbound_request: MessageSendParams,
        inbound_response: Any,
        agent_name: str,
        processing_time: float,
        span: Any,
        context_id: str = None
    ):
        """Background task for storing A2A interactions without blocking parallel execution"""
        try:
            await self._store_a2a_interaction(
                outbound_request=outbound_request,
                inbound_response=inbound_response,
                agent_name=agent_name,
                processing_time=processing_time,
                span=span,
                context_id=context_id
            )
        except Exception as e:
            log_error(f"Background A2A interaction storage failed for {agent_name}: {e}")
            # Don't let storage errors affect parallel execution

    async def _index_agent_file_artifacts(
        self,
        file_artifacts: List[Dict[str, Any]],
        session_id: str,
        context_id: str,
        agent_name: str
    ) -> List[str]:
        """
        Process and index file artifacts returned by remote agents for memory search.

        This enables powerful cross-agent workflows:
        - Email Agent downloads invoice PDF → indexed → search_memory can find it
        - Document Agent analyzes contract → indexed → future queries can reference it
        - Image Agent generates image → indexed via Content Understanding → searchable
        - Any agent that produces files → automatically processed and searchable

        Args:
            file_artifacts: List of dicts with uri, name, mime_type, source_agent
            session_id: Session ID for tenant isolation
            context_id: Context ID for status updates
            agent_name: Agent that produced these files

        Returns:
            List of extracted content strings (for immediate use by subsequent steps,
            since Azure Search indexing may have latency before documents are queryable).
        """
        from .a2a_document_processor import process_file_part, determine_file_type, AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, IMAGE_EXTENSIONS, DOCUMENT_EXTENSIONS, TEXT_EXTENSIONS, CU_TEXT_FORMATS
        
        # All Content Understanding supported formats are indexable
        indexable_extensions = DOCUMENT_EXTENSIONS + IMAGE_EXTENSIONS + VIDEO_EXTENSIONS + AUDIO_EXTENSIONS + TEXT_EXTENSIONS + CU_TEXT_FORMATS
        files_to_index = []
        
        for artifact in file_artifacts:
            file_name = artifact.get('name', '')
            file_ext = '.' + file_name.split('.')[-1].lower() if '.' in file_name else ''
            
            if file_ext in indexable_extensions:
                files_to_index.append(artifact)
                log_debug(f"Queuing for indexing: {file_name} ({artifact.get('mime_type', 'unknown')})")
            else:
                log_warning(f"Skipping non-document: {file_name} (not indexable)")
        
        if not files_to_index:
            log_warning(f"No indexable documents from {agent_name}")
            return []
        
        # Emit orchestrator status - file received from agent
        asyncio.create_task(self._emit_granular_agent_event(
            "foundry-host-agent", 
            f"📥 Received {len(files_to_index)} file(s) from {agent_name} - processing for memory indexing", 
            context_id,
            event_type="info",
            metadata={"phase": "document_indexing", "file_count": len(files_to_index), "source_agent": agent_name}
        ))
        
        indexed_count = 0
        extracted_contents = []  # Collect extracted content for immediate use by subsequent steps
        for artifact in files_to_index:
            try:
                file_uri = artifact.get('uri', '')
                file_name = artifact.get('name', 'unknown')
                
                log_debug(f"Downloading {file_name} from {file_uri[:50]}...")
                
                # Emit per-file extraction status
                asyncio.create_task(self._emit_granular_agent_event(
                    "foundry-host-agent",
                    f"📄 Extracting content from: {file_name}",
                    context_id,
                    event_type="info",
                    metadata={"phase": "document_extraction", "file_name": file_name, "source_agent": agent_name}
                ))
                
                # Download file bytes from Azure Blob
                import httpx
                async with httpx.AsyncClient() as client:
                    response = await client.get(file_uri, timeout=60.0)
                    response.raise_for_status()
                    file_bytes = response.content
                
                log_debug(f"Processing {file_name} ({len(file_bytes)} bytes)...")
                
                # Process and index the file
                result = await process_file_part(
                    file_part=None,  # We'll pass artifact_info instead
                    artifact_info={
                        'file_name': file_name,
                        'file_bytes': file_bytes,
                        'artifact_uri': file_uri,
                        'source_agent': agent_name
                    },
                    session_id=session_id
                )
                
                if result and result.get('success'):
                    chunks_stored = result.get('chunks_stored', 0)
                    indexed_count += 1
                    log_memory_debug(f"Indexed {file_name}: {chunks_stored} chunks stored in memory")

                    # Get the extracted content for display and for subsequent steps
                    extracted_content = result.get('content', '')
                    if extracted_content:
                        extracted_contents.append(extracted_content)
                    
                    # Format content preview for orchestrator display
                    if extracted_content:
                        # Truncate for display but keep meaningful context
                        content_preview = extracted_content[:1500] if len(extracted_content) > 1500 else extracted_content
                        if len(extracted_content) > 1500:
                            content_preview += "... [truncated]"
                        
                        # Emit detailed extraction result to orchestrator
                        extraction_message = f"📄 **Extracted from {file_name} (from {agent_name}):**\n\n{content_preview}\n\n---\n📊 Stored {chunks_stored} searchable chunks in memory"
                        log_debug(f"[DOC_EXTRACTION] Emitting orchestrator extraction event: {len(content_preview)} chars")
                        asyncio.create_task(self._emit_granular_agent_event(
                            "foundry-host-agent",
                            extraction_message,
                            context_id,
                            event_type="info",
                            metadata={"phase": "document_extraction_complete", "file_name": file_name, "chunks": chunks_stored, "source_agent": agent_name}
                        ))
                    else:
                        log_warning(f"[DOC_EXTRACTION] No extracted content from {file_name}")
                    
                    # Emit file_processing_completed event so frontend updates status to 'analyzed'
                    # This uses the same event type that the /api/files/process endpoint uses
                    asyncio.create_task(self._emit_file_analyzed_event(
                        filename=file_name,
                        uri=file_uri,
                        context_id=context_id,
                        session_id=session_id
                    ))
                else:
                    error = result.get('error', 'Unknown error') if result else 'No result'
                    log_error(f"Failed to index {file_name}: {error}")
                    # Emit file_processing_completed with 'error' status so UI updates
                    asyncio.create_task(self._emit_file_analyzed_event(
                        filename=file_name,
                        uri=file_uri,
                        context_id=context_id,
                        session_id=session_id,
                        status='error'
                    ))
                    
            except Exception as e:
                log_error(f"Error indexing {artifact.get('name', 'unknown')}: {e}")
                # Emit file_processing_completed with 'error' status so UI updates
                asyncio.create_task(self._emit_file_analyzed_event(
                    filename=artifact.get('name', 'unknown'),
                    uri=artifact.get('uri', ''),
                    context_id=context_id,
                    session_id=session_id,
                    status='error'
                ))
        
        # Final status — attribute to source agent
        if indexed_count > 0:
            asyncio.create_task(self._emit_granular_agent_event(
                agent_name, 
                f"✅ Indexed {indexed_count} document(s) — now searchable via memory", 
                context_id,
                event_type="info",
                metadata={"phase": "document_indexing_complete", "indexed_count": indexed_count, "source_agent": agent_name}
            ))
            log_debug(f"Successfully indexed {indexed_count}/{len(files_to_index)} documents from {agent_name}")
        else:
            log_warning(f"No documents were successfully indexed from {agent_name}")

        return extracted_contents

    async def _store_a2a_interaction(
        self, 
        outbound_request: MessageSendParams,
        inbound_response: Any,
        agent_name: str,
        processing_time: float,
        span: Any,
        context_id: str = None
    ):
        """
        Persist agent-to-agent interactions to memory service for future semantic search.
        
        NOTE: This is only called when inter-agent memory is ENABLED in the UI toggle.
        When disabled, only uploaded document content is stored (not A2A conversations).
        
        Why we store interactions (when enabled):
        - Enable "has this been asked before?" queries across conversations
        - Learn from past agent responses and patterns
        - Provide cross-conversation context
        - Track agent performance and reliability
        - Support debugging and troubleshooting
        
        The memory service uses Azure Cognitive Search with vector embeddings to enable
        semantic similarity search. This means agents can find relevant past conversations
        even when the wording is different.
        
        Example: If a user asks "What's our refund policy?" and later asks "Can I get my
        money back?", the agent can retrieve the previous policy explanation.
        
        Args:
            outbound_request: The original A2A message sent to the remote agent
            inbound_response: The response received from the remote agent
            agent_name: Name of the agent that processed the request
            processing_time: How long the agent took to respond (for performance tracking)
            span: OpenTelemetry span for distributed tracing
            context_id: Context ID for tenant isolation (required for multi-tenancy)
        """
        """Store complete A2A protocol payloads"""
        try:
            # Extract session_id for tenant isolation
            session_id = get_tenant_from_context(context_id) if context_id else None
            
            if not session_id:
                log_debug(f"[A2A Memory] Warning: No session_id available, skipping interaction storage for tenant isolation")
                return
            
            # Prepare interaction data with complete A2A payloads
            interaction_data = {
                "interaction_id": str(uuid.uuid4()),
                "agent_name": agent_name,
                "processing_time_seconds": processing_time,
                "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                
                # Complete outbound A2A payload
                "outbound_payload": outbound_request.model_dump() if hasattr(outbound_request, 'model_dump') else str(outbound_request),
                
                # Complete inbound A2A payload  
                "inbound_payload": inbound_response.model_dump() if hasattr(inbound_response, 'model_dump') else str(inbound_response)
            }
            
            # Store in memory service with session_id for tenant isolation
            success = await a2a_memory_service.store_interaction(interaction_data, session_id=session_id)
            
            if success:
                log_debug(f"[A2A Memory] Stored A2A payloads for {agent_name} (session: {session_id})")
                span.add_event("memory_stored", {"agent_name": agent_name, "session_id": session_id})
            else:
                log_debug(f"[A2A Memory] Failed to store A2A payloads for {agent_name}")
                span.add_event("memory_store_failed", {"agent_name": agent_name})
            
            # ✅ EMIT A2A PAYLOAD TO WEBSOCKET FOR FRONTEND VISIBILITY
            # This enables the "Show Agent Workflow" view and sidebar status tracking
            try:
                from service.websocket_streamer import get_websocket_streamer
                streamer = await get_websocket_streamer()
                if streamer:
                    # Emit a2a_payload event with complete request/response data
                    a2a_payload_event = {
                        "interactionId": interaction_data["interaction_id"],
                        "agentName": agent_name,
                        "timestamp": interaction_data["timestamp"],
                        "processingTime": processing_time,
                        "outboundPayload": interaction_data["outbound_payload"],
                        "inboundPayload": interaction_data["inbound_payload"],
                        "contextId": context_id
                    }
                    
                    await streamer._send_event("a2a_payload", a2a_payload_event, context_id)
                    log_debug(f"[A2A PAYLOAD] Emitted A2A payload to WebSocket for {agent_name}")
                else:
                    log_debug("WebSocket streamer not available for A2A payload emission")
            except Exception as ws_error:
                log_debug(f"Failed to emit A2A payload to WebSocket: {ws_error}")
                # Don't fail the entire storage operation if WebSocket emission fails
                
        except Exception as e:
            log_debug(f"[A2A Memory] Error storing A2A payloads: {str(e)}")
            span.add_event("memory_store_error", {
                "agent_name": agent_name,
                "error": str(e)
            })

    async def _store_user_host_interaction_safe(
        self,
        user_message_parts: List[Part],
        user_message_text: str,
        host_response: List[str],
        context_id: str,
        span: Any,
        artifact_info: Dict[int, Dict[str, str]] = None,
        session_context: Any = None
    ):
        """Safe wrapper for User->Host memory storage that won't block conversation.
        
        NOTE: Respects the inter-agent memory toggle. If memory is disabled,
        this function returns early without storing anything.
        """
        # Check memory toggle - if disabled, skip storage entirely
        if session_context is not None:
            enable_memory = getattr(session_context, 'enable_inter_agent_memory', False)
            if not enable_memory:
                log_debug(f"[Memory] Skipping User->Host interaction storage (memory disabled)")
                return
        
        try:
            await self._store_user_host_interaction(
                user_message_parts=user_message_parts,
                user_message_text=user_message_text,
                host_response=host_response,
                context_id=context_id,
                span=span,
                artifact_info=artifact_info
            )
        except Exception as e:
            log_error(f"User->Host interaction storage failed: {e}")
            log_error(f"Exception type: {type(e).__name__}")
            import traceback
            log_debug(f"Traceback: {traceback.format_exc()}")

    async def _store_user_host_interaction(
        self,
        user_message_parts: List[Part],
        user_message_text: str,
        host_response: List[str],
        context_id: str,
        span: Any,
        artifact_info: Dict[int, Dict[str, str]] = None
    ):
        """
        Store User->Host A2A protocol exchange for memory/search.
        
        KEY FIX: Skip Message objects in response list - they contain FileParts
        which are handled separately and can't be JSON serialized directly.
        """
        try:
            # Clean file bytes from parts before storing
            cleaned_parts = self._clean_file_bytes_from_parts(user_message_parts, artifact_info)
            
            # Create outbound message (user request)
            outbound_message = Message(
                messageId=str(uuid.uuid4()),
                contextId=context_id,
                taskId=None,
                role="user",
                parts=cleaned_parts
            )
            
            outbound_request = MessageSendParams(
                id=str(uuid.uuid4()),
                message=outbound_message,
                configuration=MessageSendConfiguration(acceptedOutputModes=["text", "text/plain", "image/png"])
            )
            
            # Create inbound message (host response)
            response_parts = []
            for response in host_response:
                # Skip artifact dicts - for UI display only
                if isinstance(response, dict) and ('artifact-uri' in response or 'artifact-id' in response):
                    continue
                
                # Skip Message objects - FileParts handled separately, can't JSON serialize
                if hasattr(response, 'parts') and hasattr(response, 'kind') and response.kind == 'message':
                    continue
                
                # Convert response to text
                if isinstance(response, str):
                    text = response
                elif hasattr(response, 'model_dump'):
                    text = json.dumps(response.model_dump(mode='json'), ensure_ascii=False)
                else:
                    text = json.dumps(response, ensure_ascii=False)
                response_parts.append(Part(root=TextPart(text=text)))
            
            inbound_message = Message(
                messageId=str(uuid.uuid4()),
                contextId=context_id,
                taskId=None,
                role="agent",
                parts=response_parts
            )
            
            # Store interaction
            session_id = get_tenant_from_context(context_id) if context_id else None
            if not session_id:
                return
            
            interaction_data = {
                "interaction_id": str(uuid.uuid4()),
                "agent_name": "host_agent",
                "processing_time_seconds": 1.0,
                "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                "outbound_payload": outbound_request.model_dump(),
                "inbound_payload": inbound_message.model_dump()
            }
            
            await a2a_memory_service.store_interaction(interaction_data, session_id=session_id)
                
        except Exception as e:
            log_error(f"_store_user_host_interaction failed: {e}")

    def _clean_file_bytes_from_parts(self, parts: List[Part], artifact_info: Dict[int, Dict[str, str]] = None) -> List[Part]:
        """Remove file bytes from A2A Parts to prevent large payloads in memory storage"""
        import copy
        cleaned_parts = []
        
        for i, part in enumerate(parts):
            if hasattr(part, 'root') and part.root.kind == 'file':
                # Create a copy of the part without the large file bytes
                cleaned_part = copy.deepcopy(part)
                if hasattr(cleaned_part.root.file, 'bytes'):
                    # Get original size before replacement
                    original_size = len(str(cleaned_part.root.file.bytes)) if cleaned_part.root.file.bytes else 0
                    
                    # If we have artifact info for this part, include the URI reference
                    if artifact_info and i in artifact_info:
                        artifact = artifact_info[i]
                        cleaned_part.root.file.bytes = f"<file_bytes_excluded_for_memory_storage_original_size_{original_size}_artifact_uri_{artifact.get('artifact_uri', 'unknown')}_artifact_id_{artifact.get('artifact_id', 'unknown')}>"
                    else:
                        # Fallback to simple metadata reference
                        cleaned_part.root.file.bytes = f"<file_bytes_excluded_for_memory_storage_original_size_{original_size}>"
                
                cleaned_parts.append(cleaned_part)
            else:
                # Non-file parts can be used as-is
                cleaned_parts.append(part)
                
        return cleaned_parts

    async def run_conversation_with_parts(self, message_parts: List[Part], context_id: Optional[str] = None, event_logger=None, agent_mode: bool = False, enable_inter_agent_memory: bool = False, workflow: Optional[str] = None, workflow_goal: Optional[str] = None, available_workflows: Optional[List[Dict[str, Any]]] = None) -> Any:
        """
        Process a user message that may include files, images, or multimodal content.
        
        This is the main entry point for complex user interactions involving:
        - File uploads (PDFs, images, documents)
        - Image editing requests (with base/mask images)
        - Multi-step workflows with file handoffs between agents
        
        Processing pipeline:
        1. **File Processing**: Extract text from documents, analyze images, handle masks
        2. **Artifact Storage**: Save files to Azure Blob or local storage with unique IDs
        3. **Context Preparation**: Package files for agent consumption (URIs + metadata)
        4. **Route Selection**: If multiple workflows available, LLM selects best approach
        5. **Mode Selection**: Route to agent-mode orchestration or standard conversation
        6. **Response Synthesis**: Combine results from multiple agents if needed
        
        Agent Mode vs Standard Mode:
        - **Agent Mode**: AI orchestrator breaks down request into specialized tasks
        - **Standard Mode**: Single LLM call with tool use for agent delegation
        
        Multi-Workflow Routing:
        - When available_workflows is provided, LLM intelligently selects the best approach
        - Can choose a specific workflow, free-form agent orchestration, or direct response
        
        Args:
            message_parts: List of A2A Part objects (text, files, data)
            context_id: Conversation identifier for state management
            event_logger: Optional callback for logging conversation events
            agent_mode: If True, use multi-agent orchestration loop
            enable_inter_agent_memory: If True, agents can access conversation context
            workflow: Optional predefined workflow steps to execute (single workflow mode)
            workflow_goal: Optional goal for workflow completion evaluation
            available_workflows: Optional list of workflow metadata dicts for intelligent routing
                Each dict should have: name, description, goal, workflow (steps text)
            
        Returns:
            List of response strings from the host agent
        """
        """Run conversation with A2A message parts (including files)."""
        log_debug(f"[ENTRY DEBUG] run_conversation_with_parts: workflow={workflow}, available_workflows={available_workflows}")
        log_debug(f"ENTRY: run_conversation_with_parts called with {len(message_parts) if message_parts else 0} parts")
        try:
            log_debug(f"Step: About to create tracer span...")
            scenario = "run_conversation_with_parts"
            with tracer.start_as_current_span(scenario) as span:
                log_debug(f"Step: Created tracer span successfully")
                
                log_debug(f"Step: About to call span.set_attribute...")
                span.set_attribute("context_id", context_id or self.default_context_id)
                log_debug(f"Step: span.set_attribute completed")
                log_debug(f"Step: Set span attribute")
            log_debug(f"run_conversation_with_parts: {len(message_parts)} parts")
            
            log_debug(f"[run_conversation_with_parts] ENTRY - context_id param: {context_id}")
            
            # CRITICAL: context_id must be provided by caller (foundry_host_manager.process_message)
            # It should NEVER be None - if it is, that's a bug in the caller
            if not context_id:
                raise ValueError(f"context_id is required but was None or empty. This is a bug - foundry_host_manager should always provide context_id")
            
            log_debug(f"[run_conversation_with_parts] Using context_id: {context_id}")
            
            # Clear any previous cancellation flag - new message starts fresh
            self.clear_cancellation(context_id)
            
            # CRITICAL: Store the context_id using contextvars for async-safe isolation
            # This ensures each async task sees its own context_id, preventing race conditions
            # between concurrent workflows. Also keep instance variable for backwards compat.
            _current_context_id.set(context_id)
            self._current_host_context_id = context_id
            log_debug(f"[run_conversation_with_parts] SET context_id (contextvar + instance) to: {context_id}")
            
            # Extract text message for thread
            log_debug(f"Step: About to extract text message...")
            user_message = ""
            for part in message_parts:
                if hasattr(part, 'root') and part.root.kind == 'text':
                    user_message = part.root.text
                    break
            log_debug(f"Step: Extracted text message")
            
            # Store the original user message for HITL resumption
            # This allows send_message_sync to save the goal when an agent returns input_required
            self._current_user_message = user_message
            log_debug(f"[HITL] Stored _current_user_message for potential HITL resumption")
            
            log_debug(f"Extracted user message: {user_message}")
            log_debug(f"Processing {len(message_parts)} parts including files")
            
            # Persist user message to chat history database
            try:
                session_id = context_id.split("::")[0] if "::" in context_id else "default"
                message_id = str(uuid.uuid4())
                parts_data = []
                for p in message_parts:
                    if hasattr(p, 'model_dump'):
                        parts_data.append(p.model_dump())
                    elif hasattr(p, 'dict'):
                        parts_data.append(p.dict())
                    else:
                        parts_data.append({"text": str(p)})
                persist_message(context_id, {
                    "messageId": message_id,
                    "role": "user",
                    "parts": parts_data,
                    "contextId": context_id,
                    "metadata": {"type": "user_message"}
                })
            except Exception as e:
                log_debug(f"[ChatHistory] Error persisting user message: {e}")
            
            # Ensure agent is created (may be lazy creation if startup creation failed)
            log_debug(f"Step: About to ensure agent exists...")
            log_foundry_debug(f"Current agent state: {self.agent is not None}")
            if self.agent:
                log_foundry_debug(f"Agent ready with model: {self.model_name}")
            else:
                log_warning("Agent not created at startup, creating now (lazy creation)...")
                log_foundry_debug(f"Calling create_agent()...")
                await self.create_agent()
                log_foundry_debug(f"create_agent() completed")
            log_debug(f"Step: Agent ready with model: {self.model_name if self.agent else 'STILL_NULL'}")
            
            session_context = self.get_session_context(context_id)
            # Set agent mode in session context
            session_context.agent_mode = agent_mode
            session_context.enable_inter_agent_memory = enable_inter_agent_memory
            log_foundry_debug(f"Agent mode set to: {agent_mode}, Inter-agent memory: {enable_inter_agent_memory}")
                
            # NOTE: EXPLICIT FILE ROUTING - no longer using _latest_processed_parts for file sharing
            # GPT-4 now receives file URIs in agent responses and passes them explicitly via file_uris parameter
            # This enables proper parallel execution without shared state issues
            session_context._agent_generated_artifacts = []
            log_foundry_debug(f"Using explicit file routing (no _latest_processed_parts)")
            
            log_foundry_debug(f"=================== STARTING MESSAGE PROCESSING ===================")
            log_foundry_debug(f"About to process {len(message_parts)} message parts")
            
            # Process all message parts (including files) BEFORE sending to thread
            # Use the SAME session_context so prepared parts are visible to send_message
            tool_context = DummyToolContext(session_context, self._azure_blob_client)
            processed_parts: List[Any] = []
            log_foundry_debug(f"processed_parts list initialized")
            
            # Count files to show appropriate status
            log_foundry_debug(f"Counting files in message parts...")
            file_count = 0
            for part in message_parts:
                if hasattr(part, 'root') and hasattr(part.root, 'kind') and part.root.kind == 'file':
                    file_count += 1
            log_foundry_debug(f"Found {file_count} files in {len(message_parts)} parts")
            
            if file_count > 0:
                log_foundry_debug(f"Emitting file processing status...")
                try:
                    if file_count == 1:
                        await self._emit_granular_agent_event(
                            "foundry-host-agent", "processing uploaded file", context_id,
                            event_type="info", metadata={"files": 1}
                        )
                    else:
                        await self._emit_granular_agent_event(
                            "foundry-host-agent", f"processing {file_count} uploaded files", context_id,
                            event_type="info", metadata={"files": file_count}
                        )
                    log_foundry_debug(f"File processing status emitted successfully")
                except Exception as e:
                    log_foundry_debug(f"Exception emitting file processing status: {e}")
                    # Don't let status emission failures stop the main flow
            
            log_foundry_debug(f"PART: About to process {len(message_parts)} parts:")
            for i, part in enumerate(message_parts):
                log_foundry_debug(f"PART: Part {i}: {type(part)} - hasattr root: {hasattr(part, 'root')}")
                if hasattr(part, 'root'):
                    log_foundry_debug(f"PART: Part {i} root kind: {getattr(part.root, 'kind', 'no kind attr')}")
                    if hasattr(part.root, 'kind') and part.root.kind == 'file':
                        log_foundry_debug(f"PART: Part {i} is FILE - name: {getattr(part.root.file, 'name', 'no name')}, uri: {getattr(part.root.file, 'uri', 'no uri')}")
                
                log_foundry_debug(f"PART: About to call convert_part for part {i}")
                try:
                    processed_result = await self.convert_part(part, tool_context, context_id)
                    if isinstance(processed_result, list):
                        log_foundry_debug(f"PART: convert_part result for part {i}: list of {len(processed_result)} items")
                        processed_parts.extend(processed_result)
                    else:
                        if isinstance(processed_result, DataPart) and hasattr(processed_result, "data"):
                            log_foundry_debug(f"PART: convert_part result for part {i}: DataPart -> {processed_result.data}")
                        else:
                            log_foundry_debug(f"PART: convert_part result for part {i}: {type(processed_result)} - {str(processed_result)[:120]}...")
                        processed_parts.append(processed_result)
                except Exception as e:
                    log_error(f"CRITICAL ERROR in convert_part for part {i}: {e}")
                    import traceback
                    log_error(f"CONVERT_PART TRACEBACK: {traceback.format_exc()}")
                    raise
            
            log_debug(f"Processed {len(processed_parts)} parts")

            # Convert processed results into A2A Part wrappers for delegation
            prepared_parts_for_agents: List[Part] = []
            for processed in processed_parts:
                prepared_parts_for_agents.extend(self._wrap_item_for_agent(processed))

            # NOTE: No longer storing parts in _latest_processed_parts (EXPLICIT FILE ROUTING)
            # GPT-4 now routes files explicitly via file_uris parameter in send_message calls
            session_context._agent_generated_artifacts = []
            log_debug(f"Prepared {len(prepared_parts_for_agents)} parts (explicit routing via file_uris)")
            
            # If files were processed, include information about them in the message
            # EXPLICIT FILE ROUTING: Include URIs so GPT-4 can pass them to agents
            file_info = []
            file_uris_for_gpt4 = []  # URIs for explicit routing
            file_contents = []
            for result in processed_parts:
                if isinstance(result, DataPart) and hasattr(result, 'data'):
                    if 'artifact-id' in result.data:
                        file_name = result.data.get('file-name', 'unknown')
                        file_uri = result.data.get('artifact-uri', '')
                        file_info.append(f"File uploaded: {file_name}")
                        if file_uri:
                            entry = {"name": file_name, "uri": file_uri}
                            role_val = result.data.get('role') or (result.data.get('metadata') or {}).get('role')
                            if role_val:
                                entry["role"] = str(role_val).lower()
                            file_uris_for_gpt4.append(entry)

                        # CRITICAL FIX: Include extracted content in enhanced_message
                        # This was missing - file content was never being added to the message!
                        if 'extracted_content' in result.data and result.data['extracted_content']:
                            extracted = result.data['extracted_content']
                            formatted_content = f"\n\n--- Extracted from {file_name} ---\n{extracted}\n--- End of {file_name} ---\n"
                            file_contents.append(formatted_content)
                            log_debug(f"Added extracted content to message: {len(extracted)} characters from {file_name}")

                elif isinstance(result, FilePart) or (isinstance(result, Part) and isinstance(getattr(result, 'root', None), FilePart)):
                    # FileParts that passed through convert_part (already had HTTP URIs)
                    # Must also be captured so GPT-4 can route them via file_uris
                    fp = result if isinstance(result, FilePart) else result.root
                    fp_uri = str(getattr(fp.file, 'uri', '') or '')
                    fp_name = getattr(fp.file, 'name', 'unknown')
                    fp_role = (fp.metadata or {}).get('role') if getattr(fp, 'metadata', None) else None
                    if fp_uri.startswith(('http://', 'https://')):
                        entry = {"name": fp_name, "uri": fp_uri}
                        if fp_role:
                            entry["role"] = str(fp_role).lower()
                        file_uris_for_gpt4.append(entry)
                        file_info.append(f"File uploaded: {fp_name}")
                        log_debug(f"Captured passthrough FilePart URI for GPT-4: {fp_name} (role={fp_role})")

                elif isinstance(result, str) and result.startswith("File:") and "Content:" in result:
                    # Legacy format - this is processed file content from uploaded files
                    log_debug(f"Found processed file content (legacy format): {len(result)} characters")
                    file_contents.append(result)
            
            # Store URI→metadata mapping so send_message can restore roles and filenames
            # when constructing FileParts from bare URI strings
            if not hasattr(session_context, '_file_uri_metadata'):
                session_context._file_uri_metadata = {}
            for entry in file_uris_for_gpt4:
                uri = entry.get("uri", "")
                if uri:
                    # Strip SAS query params for stable lookup key
                    lookup_key = uri.split('?')[0]
                    session_context._file_uri_metadata[lookup_key] = {
                        "name": entry.get("name"),
                        "role": entry.get("role"),
                    }
            if session_context._file_uri_metadata:
                log_debug(f"Stored URI metadata for {len(session_context._file_uri_metadata)} files: {list(session_context._file_uri_metadata.values())}")

            # Emit completion status if files were processed
            if file_count > 0 and (file_info or file_contents):
                if file_count == 1:
                    await self._emit_granular_agent_event(
                        "foundry-host-agent", "file processing completed", context_id,
                        event_type="info", metadata={"files": 1, "action": "complete"}
                    )
                else:
                    await self._emit_granular_agent_event(
                        "foundry-host-agent", f"all {file_count} files processed successfully", context_id,
                        event_type="info", metadata={"files": file_count, "action": "complete"}
                    )
            
            # Enhance user message with file information and content
            # EXPLICIT FILE ROUTING: Include URIs so GPT-4 can pass them to agents via file_uris
            enhanced_message = user_message
            if file_uris_for_gpt4:
                # Format file URIs in a way GPT-4 can easily extract and use
                files_json = json.dumps(file_uris_for_gpt4)
                enhanced_message = f"{user_message}\n\n[USER UPLOADED FILES - use file_uris parameter to pass these to agents: {files_json}]"
            elif file_info:
                enhanced_message = f"{user_message}\n\n[Files uploaded: {'; '.join(file_info)}]"
            if file_contents:
                enhanced_message = f"{enhanced_message}\n\n{''.join(file_contents)}"

            # Add image edit guidance if base/mask attachments detected
            image_guidance = self._build_image_edit_guidance(processed_parts)
            if image_guidance:
                enhanced_message = f"{image_guidance}\n\n{enhanced_message}" if enhanced_message else image_guidance
            
            # Collect image URIs for GPT-4o vision (multimodal input)
            # Also process images through content understanding for memory storage
            image_uris_for_vision = []
            for part in message_parts:
                if is_image_part(part):
                    uri = extract_uri(part)
                    if uri:
                        image_uris_for_vision.append(uri)
            if image_uris_for_vision:
                log_debug(f"Collected {len(image_uris_for_vision)} image(s) for GPT-4o vision input")
                # Process images through content understanding and store in memory
                # This makes image content available to remote agents via search_memory
                session_id = get_tenant_from_context(context_id) if context_id else None
                image_descriptions = []
                for part in message_parts:
                    if is_image_part(part):
                        img_uri = extract_uri(part)
                        img_name = extract_filename(part) or 'pasted_image.png'
                        if img_uri:
                            try:
                                processing_result = await a2a_document_processor.process_file_part(
                                    part.root.file if hasattr(part, 'root') else part,
                                    {'file_name': img_name, 'artifact_uri': img_uri},
                                    session_id=session_id
                                )
                                if processing_result and processing_result.get("success"):
                                    content = processing_result.get("content", "")
                                    if content:
                                        image_descriptions.append(f"\n\n--- Image description: {img_name} ---\n{content}\n--- End of {img_name} ---\n")
                                        log_debug(f"Processed image for memory: {img_name} ({len(content)} chars)")
                            except Exception as e:
                                log_debug(f"Image content understanding failed for {img_name}: {e}")
                if image_descriptions:
                    enhanced_message = f"{enhanced_message}\n\n{''.join(image_descriptions)}"

            log_debug(f"Enhanced message prepared")

            # =====================================================================
            # HITL RESUME CHECK: Skip routing if an agent is waiting for user input
            # =====================================================================
            # If there's a pending_input_agent, this message is a HITL response
            # Route directly to that agent instead of doing intelligent routing
            hitl_direct_return = False  # Flag to skip orchestration for non-workflow HITL
            if session_context.pending_input_agent:
                pending_agent = session_context.pending_input_agent
                pending_task_id = session_context.pending_input_task_id
                log_warning(f"[HITL RESUME] Detected pending_input_agent='{pending_agent}', skipping routing")
                log_info(f"[HITL RESUME] Detected pending_input_agent='{pending_agent}', routing directly to agent")
                await self._emit_granular_agent_event(
                    "foundry-host-agent", f"Resuming with your input...", context_id,
                    event_type="phase", metadata={"phase": "hitl_resume", "agent": pending_agent}
                )
                
                # IMPORTANT: Emit a "completed" status for the pending agent to clear "Waiting" in sidebar
                # This ensures the UI updates when the human provides their response
                try:
                    asyncio.create_task(self._emit_simple_task_status(
                        pending_agent, 
                        "completed", 
                        context_id, 
                        pending_task_id or str(uuid.uuid4())
                    ))
                    log_info(f"[HITL RESUME] Emitted 'completed'status for {pending_agent} to clear Waiting state")
                except Exception as e:
                    log_debug(f"[HITL RESUME] Failed to emit completed status: {e}")
                
                # CRITICAL FIX: Do NOT create a synthetic one-step workflow here!
                # The workflow was already restored from the saved plan by foundry_host_manager.py
                # Creating a synthetic workflow here would overwrite the full multi-step workflow
                # and cause the orchestrator to mark the goal as "completed" after just the HITL step.
                # If no workflow was passed in (edge case), use the saved plan's workflow
                if not workflow and session_context.current_plan and session_context.current_plan.workflow:
                    workflow = session_context.current_plan.workflow
                    log_info(f"[HITL RESUME] Restored workflow from saved plan ({len(workflow)} chars)")
                if not workflow_goal and session_context.current_plan and session_context.current_plan.workflow_goal:
                    workflow_goal = session_context.current_plan.workflow_goal
                    log_info(f"[HITL RESUME] Restored workflow_goal from saved plan")
                
                # CRITICAL: Mark the input_required task as completed now that user has responded
                # This ensures the orchestrator knows to skip this step when resuming
                if session_context.current_plan and session_context.current_plan.tasks:
                    for task in session_context.current_plan.tasks:
                        if task.state == "input_required":
                            task.state = "completed"
                            task.output = {"result": f"HITL Response: {enhanced_message[:200]}"}
                            from datetime import datetime, timezone
                            task.updated_at = datetime.now(timezone.utc)
                            log_info(f"[HITL RESUME] Marked task '{task.task_description[:50]}...'as completed")
                            break  # Only mark the first input_required task
                
                # SYNTHETIC WORKFLOW DETECTION: Workflows auto-generated for single-agent routing
                # (e.g., "1. [Agent Name] Complete the user's request") should be treated as non-workflow HITL
                # because the single task is now complete with the human's response
                is_synthetic_single_step = False
                if workflow and workflow.strip():
                    workflow_stripped = workflow.strip()
                    # Check if it's a single-step synthetic workflow
                    if "Complete the user's request" in workflow_stripped:
                        lines = [l for l in workflow_stripped.split('\n') if l.strip()]
                        if len(lines) == 1:
                            is_synthetic_single_step = True
                            log_info(f"[HITL RESUME] Detected synthetic single-step workflow - treating as non-workflow HITL")
                            workflow = None  # Clear workflow so it uses non-workflow path
                
                # Check if we have a workflow - if not, just acknowledge the HITL response
                if not workflow:
                    log_warning(f"[HITL RESUME] No workflow - HITL completed, acknowledging response")
                    log_info(f"[HITL RESUME] No workflow context - just acknowledging HITL response")
                    
                    # Clear the pending_input_agent
                    session_context.pending_input_agent = None
                    session_context.pending_input_task_id = None
                    
                    # For non-workflow HITL, just acknowledge the response was received
                    # The Teams agent has already processed the response in its webhook
                    # We don't need to call it again - just tell the user we got it
                    ack_message = f"✅ Response received: \"{enhanced_message}\"\n\nThe {pending_agent} has processed your input."
                    await self._emit_granular_agent_event(
                        "foundry-host-agent", ack_message, context_id,
                        event_type="info", metadata={"hitl_ack": True, "agent": pending_agent}
                    )
                    
                    log_info(f"[HITL RESUME] Non-workflow HITL completed, acknowledged response")
                    return [ack_message]
                else:
                    # We have a workflow - enable agent mode for orchestration
                    agent_mode = True
                    log_info(f"[HITL RESUME] Using workflow with {len(workflow)} chars (continuing orchestration)")
                
                # Clear the pending_input_agent so subsequent requests don't loop
                # (The agent will set it again if it needs more input)
                session_context.pending_input_agent = None
                session_context.pending_input_task_id = None
                log_info(f"[HITL RESUME] Cleared pending_input_agent after routing")
            
            # =====================================================================
            # MULTI-WORKFLOW ROUTING: LLM selects best approach when multiple workflows available
            # =====================================================================
            # Track selected workflow metadata for run history (initialized here, may be set during routing)
            selected_workflow_metadata = None
            
            log_debug(f"[DEBUG] available_workflows = {available_workflows}, workflow = {workflow}")
            if available_workflows and len(available_workflows) > 0 and not workflow:
                log_debug(f"[Multi-Workflow] {len(available_workflows)} workflows available, invoking intelligent routing")
                log_debug(f"[Multi-Workflow] {len(available_workflows)} workflows available, invoking intelligent routing")
                await self._emit_granular_agent_event(
                    "foundry-host-agent", f"Analyzing request against {len(available_workflows)} available workflows...", context_id,
                    event_type="phase", metadata={"phase": "routing", "workflow_count": len(available_workflows)}
                )
                
                try:
                    route_selection = await self._intelligent_route_selection(
                        user_message=enhanced_message,
                        available_workflows=available_workflows,
                        context_id=context_id
                    )
                    
                    log_debug(f"[Route] Decision: approach={route_selection.approach}, workflow={route_selection.selected_workflow}, workflows={route_selection.selected_workflows}, agent={getattr(route_selection, 'selected_agent', None)}, confidence={route_selection.confidence:.2f}")
                    log_debug(f"[Route] Reasoning: {route_selection.reasoning}")
                    log_debug(f"[Route] Decision: {route_selection.approach} (confidence: {route_selection.confidence})")
                    
                    if route_selection.approach == "workflow" and route_selection.selected_workflow:
                        # Find the selected workflow from available_workflows (case-insensitive match)
                        selected_wf = None
                        selected_workflow_lower = route_selection.selected_workflow.lower().strip()
                        for wf in available_workflows:
                            wf_name = wf.get('name', '').lower().strip()
                            if wf_name == selected_workflow_lower:
                                selected_wf = wf
                                break
                        
                        if selected_wf:
                            workflow = selected_wf.get('workflow', selected_wf.get('steps', ''))
                            workflow_goal = selected_wf.get('goal', workflow_goal)
                            agent_mode = True  # Enable orchestration for workflow execution
                            # Store metadata for run history
                            selected_workflow_metadata = {
                                'id': selected_wf.get('id', ''),
                                'name': selected_wf.get('name', ''),
                                'goal': selected_wf.get('goal', '')
                            }
                            log_debug(f"[Multi-Workflow] Selected workflow: {route_selection.selected_workflow}")
                            await self._emit_granular_agent_event(
                                "foundry-host-agent", f"🔄 Route Decision: Using WORKFLOW '{route_selection.selected_workflow}'", context_id,
                                event_type="info", metadata={"route": "workflow", "workflow_name": route_selection.selected_workflow}
                            )
                        else:
                            log_error(f"[Multi-Workflow] Workflow '{route_selection.selected_workflow}' not found in available workflows")
                            agent_mode = True  # Fallback to agent orchestration
                    
                    elif route_selection.approach == "workflows_parallel" and route_selection.selected_workflows:
                        # Execute multiple workflows in parallel
                        # Note: asyncio is already imported at module level
                        
                        parallel_workflow_names = route_selection.selected_workflows
                        log_debug(f"[Multi-Workflow] Parallel execution of {len(parallel_workflow_names)} workflows: {parallel_workflow_names}")
                        await self._emit_granular_agent_event(
                            "foundry-host-agent", f"Executing {len(parallel_workflow_names)} workflows in parallel...", context_id,
                            event_type="phase", metadata={"phase": "parallel_workflows", "workflow_count": len(parallel_workflow_names)}
                        )
                        
                        # Find matching workflows
                        parallel_workflows = []
                        for wf_name in parallel_workflow_names:
                            wf_name_lower = wf_name.lower().strip()
                            for wf in available_workflows:
                                if wf.get('name', '').lower().strip() == wf_name_lower:
                                    parallel_workflows.append(wf)
                                    break
                        
                        if len(parallel_workflows) >= 2:
                            # Execute workflows in parallel using asyncio.gather
                            async def execute_single_workflow(wf_data: dict) -> List[str]:
                                wf_steps = wf_data.get('workflow', wf_data.get('steps', ''))
                                wf_goal_text = wf_data.get('goal', '')
                                wf_name_str = wf_data.get('name', 'Workflow')
                                
                                await self._emit_granular_agent_event(
                                    "foundry-host-agent", f"Starting: {wf_name_str}", context_id,
                                    event_type="info", metadata={"workflow": wf_name_str, "action": "start"}
                                )
                                
                                try:
                                    outputs = await self._agent_mode_orchestration_loop(
                                        user_message=enhanced_message,
                                        context_id=f"{context_id}_{wf_name_str}",  # Unique context per workflow
                                        session_context=session_context,
                                        event_logger=event_logger,
                                        workflow=wf_steps,
                                        workflow_goal=wf_goal_text
                                    )
                                    await self._emit_granular_agent_event(
                                        "foundry-host-agent", f"Completed: {wf_name_str}", context_id,
                                        event_type="info", metadata={"workflow": wf_name_str, "action": "complete"}
                                    )
                                    return outputs if outputs else []
                                except Exception as wf_err:
                                    log_error(f"[Parallel Workflow] Error in {wf_name_str}: {wf_err}")
                                    return [f"Error in {wf_name_str}: {str(wf_err)}"]
                            
                            # Run all workflows in parallel
                            log_debug(f"[Multi-Workflow] Launching {len(parallel_workflows)} workflows in parallel")
                            parallel_results = await asyncio.gather(
                                *[execute_single_workflow(wf) for wf in parallel_workflows],
                                return_exceptions=True
                            )
                            
                            # Combine all outputs
                            all_parallel_outputs = []
                            for i, (wf, result) in enumerate(zip(parallel_workflows, parallel_results)):
                                wf_name_str = wf.get('name', f'Workflow {i+1}')
                                if isinstance(result, Exception):
                                    all_parallel_outputs.append(f"## {wf_name_str}\n\nError: {str(result)}")
                                elif isinstance(result, list):
                                    combined = "\n\n".join(result) if result else "No output"
                                    all_parallel_outputs.append(f"## {wf_name_str}\n\n{combined}")
                                else:
                                    all_parallel_outputs.append(f"## {wf_name_str}\n\n{str(result)}")
                            
                            # Return combined response directly
                            combined_response = "\n\n---\n\n".join(all_parallel_outputs)
                            log_debug(f"[Multi-Workflow] Parallel execution complete - {len(parallel_workflows)} workflows")
                            await self._emit_granular_agent_event(
                                "foundry-host-agent", "All parallel workflows completed", context_id,
                                event_type="phase", metadata={"phase": "complete", "parallel_workflows": True}
                            )
                            
                            # Store interaction and return combined response
                            await self._store_user_host_interaction_safe(
                                user_message_parts=message_parts,
                                user_message_text=enhanced_message,
                                host_response=[combined_response],
                                context_id=context_id,
                                span=span,
                                session_context=session_context
                            )
                            return [combined_response]
                        else:
                            # Not enough workflows found, fallback to agents
                            log_error(f"[Multi-Workflow] Could not find all workflows for parallel execution, falling back to agents")
                            agent_mode = True
                            workflow = None
                            
                    elif route_selection.approach == "single_agent" and route_selection.selected_agent:
                        # Direct call to a single agent - use orchestration but targeted
                        single_agent_name = route_selection.selected_agent
                        log_debug(f"[Route Selection] Using single agent: {single_agent_name}")
                        await self._emit_granular_agent_event(
                            "foundry-host-agent", f"🔄 Route Decision: Direct call to AGENT '{single_agent_name}'", context_id,
                            event_type="info", metadata={"route": "single_agent", "agent_name": single_agent_name}
                        )
                        
                        # Verify the agent exists in session cards
                        agent_exists = False
                        for card in self.cards.values():
                            if card.name.lower().strip() == single_agent_name.lower().strip():
                                agent_exists = True
                                single_agent_name = card.name  # Use exact name
                                break
                        
                        # If not in session, try to load from catalog
                        if not agent_exists:
                            log_debug(f"[Single Agent] Agent '{single_agent_name}'not in session, checking catalog...")
                            agent_loaded = await self._load_agent_from_catalog(single_agent_name)
                            if agent_loaded:
                                agent_exists = True
                                # Get the exact name from the newly loaded card
                                for card in self.cards.values():
                                    if card.name.lower().strip() == single_agent_name.lower().strip():
                                        single_agent_name = card.name
                                        break
                                log_debug(f"[Single Agent] Loaded agent '{single_agent_name}'from catalog")
                        
                        if agent_exists:
                            # Use agent mode orchestration WITHOUT a synthetic workflow
                            # This allows the orchestrator to route to the agent naturally
                            # and properly handles HITL (input_required) without workflow complications
                            agent_mode = True
                            workflow = None  # Don't create synthetic workflow - causes HITL issues
                            workflow_goal = None
                            log_debug(f"[Single Agent] Using agent mode for {single_agent_name} (no synthetic workflow)")
                        else:
                            # Agent not found even in catalog - give clear error
                            log_error(f"[Single Agent] Agent '{single_agent_name}'not found in session or catalog")
                            await self._emit_granular_agent_event(
                                "foundry-host-agent", f"⚠️ Agent '{single_agent_name}' not available", context_id,
                                event_type="agent_error", metadata={"agent_name": single_agent_name}
                            )
                            # Return error response instead of falling back to broken multi-agent
                            await self._store_user_host_interaction_safe(
                                user_message_parts=message_parts,
                                user_message_text=enhanced_message,
                                host_response=[f"I couldn't find an agent named '{single_agent_name}'. Please make sure the agent is registered and available."],
                                context_id=context_id,
                                span=span,
                                session_context=session_context
                            )
                            return [f"I couldn't find an agent named '{single_agent_name}'. Please make sure the agent is registered and available."]
                    
                    elif route_selection.approach == "multi_agent":
                        # Use free-form multi-agent orchestration (no specific workflow)
                        agent_mode = True
                        workflow = None
                        workflow_goal = None  # Clear workflow_goal so orchestrator uses user's message
                        log_debug(f"[Route Selection] Using multi-agent orchestration")
                        await self._emit_granular_agent_event(
                            "foundry-host-agent", "🔄 Route Decision: Using MULTI-AGENT orchestration", context_id,
                            event_type="info", metadata={"route": "multi_agent"}
                        )
                        
                    elif route_selection.approach == "direct":
                        # Skip orchestration, use standard Foundry response
                        agent_mode = False
                        workflow = None
                        workflow_goal = None  # Clear workflow_goal
                        log_debug(f"[Multi-Workflow] Using direct response (no orchestration)")
                        await self._emit_granular_agent_event(
                            "foundry-host-agent", "🔄 Route Decision: Direct response (no agents needed)", context_id,
                            event_type="info", metadata={"route": "direct"}
                        )
                        
                except Exception as e:
                    log_error(f"[Multi-Workflow] Routing error: {e}, falling back to agent mode")
                    agent_mode = True
                    workflow = None
            
            # =====================================================================
            # MODE DETECTION: Use orchestration when workflow OR agent_mode is set
            # =====================================================================
            # Agent mode enables the LLM planner which can detect and execute
            # parallel tasks (e.g., "generate 3 images" becomes 3 parallel tasks)
            use_orchestration = (workflow and workflow.strip()) or agent_mode
            
            if use_orchestration:
                mode_type = "Workflow" if (workflow and workflow.strip()) else "Agent"
                log_debug(f"[{mode_type} Mode] Using orchestration loop (workflow={bool(workflow)}, agent_mode={agent_mode}, workflow_goal={workflow_goal[:50] if workflow_goal else None})")
                await self._emit_granular_agent_event(
                    "foundry-host-agent", "Starting orchestration...", context_id,
                    event_type="phase", metadata={"phase": "orchestration_start"}
                )
                
                # Debug: Log agent count before orchestration
                cards_count = len(self.cards) if hasattr(self, 'cards') and self.cards else 0
                log_debug(f"[DEBUG] Cards available before orchestration: {cards_count}")
                if cards_count > 0:
                    log_debug(f"[DEBUG] Card names: {list(self.cards.keys())[:5]}...")
                
                # Use agent mode orchestration loop
                try:
                    orchestration_outputs = await self._agent_mode_orchestration_loop(
                        user_message=enhanced_message,
                        context_id=context_id,
                        session_context=session_context,
                        event_logger=event_logger,
                        workflow=workflow,
                        workflow_goal=workflow_goal
                    )
                    
                    # =========================================================
                    # HITL CHECK: If plan was saved, we're waiting for human input
                    # =========================================================
                    # When the orchestration loop pauses for HITL, it saves the plan
                    # to session_context.current_plan. In that case, we should NOT
                    # combine all outputs and return "Workflow completed" - we should
                    # return only the HITL agent's message (the last output).
                    # =========================================================
                    if session_context.current_plan is not None:
                        log_debug(f"[HITL PAUSE] Detected saved plan - workflow paused for human input")
                        log_info(f"[HITL PAUSE] Plan saved for resume, returning HITL response only")
                        
                        # Show the message that was sent (so user knows what they're approving)
                        # Plus a clear status indicator that we're waiting
                        pending_agent = session_context.pending_input_agent or "an agent"
                        agent_output = orchestration_outputs[-1] if orchestration_outputs else ""
                        
                        # Build response: show what was sent + status
                        hitl_message = f"{agent_output}\n\n⏸️ **Workflow paused** - waiting for your response in {pending_agent.replace(' Agent', '')}."
                        log_info(f"[HITL PAUSE] Returning HITL message with agent output")
                        final_responses = [hitl_message]
                        
                        # Persist the HITL waiting message to chat history
                        try:
                            # Include plan in HITL message so workflow state is preserved
                            message_metadata = {"type": "hitl_waiting", "pending_agent": session_context.pending_input_agent}
                            if session_context and session_context.current_plan:
                                try:
                                    plan_data = session_context.current_plan.model_dump(mode='json', exclude_none=True)
                                    message_metadata["workflow_plan"] = plan_data
                                except Exception as plan_err:
                                    log_warning(f"[ChatHistory] Warning - could not serialize plan: {plan_err}")
                            
                            persist_message(context_id, {
                                "messageId": str(uuid.uuid4()),
                                "role": "agent",
                                "parts": [{"root": {"kind": "text", "text": final_responses[0]}}],
                                "contextId": context_id,
                                "metadata": message_metadata
                            })
                        except Exception as e:
                            log_debug(f"[ChatHistory] Error persisting HITL response: {e}")
                        
                        log_debug(f"[HITL PAUSE] Returning early, workflow will resume on next message")
                        return final_responses
                    
                    # =========================================================
                    # CANCELLATION CHECK: If workflow was cancelled, skip synthesis
                    # =========================================================
                    if self.is_cancelled(context_id):
                        log_info(f"[CANCEL] Workflow cancelled - skipping LLM synthesis, returning silent cancel")
                        log_warning(f"[CANCEL] Workflow cancelled - skipping synthesis")

                        # Emit a cancelled event so frontend knows
                        await self._emit_granular_agent_event(
                            "foundry-host-agent", "Workflow cancelled", context_id,
                            event_type="phase", metadata={"phase": "cancelled"}
                        )

                        # Return a minimal cancelled message (not a full LLM summary)
                        final_responses = ["Workflow cancelled."]

                        # Persist cancellation to chat history (include plan so UI can reconstruct workflow steps)
                        try:
                            cancel_metadata: dict = {"type": "workflow_cancelled"}
                            # Try current_plan first, fall back to snapshot saved by cancel_workflow()
                            plan_data = None
                            if session_context and session_context.current_plan:
                                try:
                                    plan_data = session_context.current_plan.model_dump(mode='json', exclude_none=True)
                                except Exception as plan_err:
                                    log_warning(f"[ChatHistory] Warning - could not serialize plan for cancel: {plan_err}")
                            if plan_data is None:
                                plan_data = self._cancelled_plan_snapshots.pop(context_id, None)
                            if plan_data:
                                plan_data["goal_status"] = "cancelled"
                                cancel_metadata["workflow_plan"] = plan_data

                            persist_message(context_id, {
                                "messageId": str(uuid.uuid4()),
                                "role": "agent",
                                "parts": [{"root": {"kind": "text", "text": "Workflow cancelled."}}],
                                "contextId": context_id,
                                "metadata": cancel_metadata
                            })
                        except Exception as e:
                            log_debug(f"[ChatHistory] Error persisting cancel message: {e}")

                        # Clear the cancellation token so next message works fresh
                        self.clear_cancellation(context_id)

                        return final_responses

                    # WORKFLOW MODE: Synthesize outputs into a clean executive summary
                    # The orchestration loop has executed all workflow steps in order
                    log_debug(f"[Workflow Mode] Workflow completed - {len(orchestration_outputs)} task outputs")
                    log_debug(f"[Workflow Mode] All workflow steps completed, synthesizing summary")

                    # Use LLM to synthesize a clean, professional summary from raw agent outputs
                    if orchestration_outputs:
                        try:
                            await self._emit_granular_agent_event(
                                "foundry-host-agent", "Generating workflow summary...", context_id,
                                event_type="phase", metadata={"phase": "synthesis"}
                            )
                            await self._ensure_project_client()
                            
                            # Build numbered step outputs for the synthesis prompt
                            # Try to extract agent names from workflow definition for attribution
                            workflow_agents = []
                            if workflow:
                                import re
                                # Parse workflow steps like "1. Email Agent: ..." or "2a. QuickBooks Agent: ..."
                                step_pattern = re.findall(r'\d+[a-z]?\.\s*(?:\*\*)?([^:*\n]+?)(?:\*\*)?:', workflow)
                                workflow_agents = [a.strip() for a in step_pattern]

                            import re as _re
                            step_outputs = []
                            for i, output in enumerate(orchestration_outputs, 1):
                                # Strip markdown image references — images are already displayed
                                # separately as FilePart artifacts, so including them in the
                                # synthesis text causes duplicate rendering in the frontend.
                                output = _re.sub(r'!\[[^\]]*\]\([^)]+\)', '', output)
                                output = _re.sub(r'\n{3,}', '\n\n', output).strip()
                                # Truncate very long outputs to avoid token limits
                                truncated = output[:3000] if len(output) > 3000 else output
                                # Tag with agent name if available from workflow definition
                                agent_label = workflow_agents[i-1] if i-1 < len(workflow_agents) else f"Step {i}"
                                step_outputs.append(f"--- {agent_label} (Step {i}) ---\n{truncated}")
                            
                            raw_outputs = "\n\n".join(step_outputs)
                            
                            synthesis_prompt = f"""Synthesize the following workflow step outputs into a clear, professional summary for the user.

RULES:
- Write a cohesive narrative, NOT a raw dump of step outputs
- Lead with the most important outcome/result
- Include key details: amounts, IDs, names, dates, links
- Use markdown formatting: **bold** for labels, bullet points for details
- NEVER use triple-backtick code blocks (```) for IDs, invoice numbers, or amounts — use **bold** or inline `code` instead
- Keep it concise — aim for 10-15 lines max
- Do NOT include internal processing details, rate limit messages, or raw API responses
- Do NOT include phrases like "Step 1 output:" or "The email agent said..."
- In the "Actions Completed" section, mention WHICH AGENT performed each action (e.g., "**Email Agent** retrieved the invoice PDF", "**QuickBooks Agent** recorded the bill", "**Stripe Agent** created and finalized the invoice")
- Write as if YOU coordinated the work across the agents
- Do NOT include image URLs, markdown image references (![...](url)), or raw blob storage links — images are displayed separately in the UI

WORKFLOW STEPS AND OUTPUTS:
{raw_outputs}"""
                            
                            synthesis_response = await self.openai_client.responses.create(
                                input=synthesis_prompt,
                                instructions="You are a professional executive assistant summarizing completed multi-agent workflow results. Be clear, concise, and action-oriented. Always credit which agent performed each action. Never use triple-backtick code blocks — use **bold** or inline `code` for IDs and numbers.",
                                model=self.model_name,
                            )
                            
                            # Extract text from the synthesis response
                            combined_response = ""
                            if hasattr(synthesis_response, 'output'):
                                for item in synthesis_response.output:
                                    if hasattr(item, 'content'):
                                        for content in item.content:
                                            if hasattr(content, 'text'):
                                                combined_response += content.text
                            
                            if not combined_response.strip():
                                # Fallback if synthesis returned empty
                                combined_response = "\n\n".join(orchestration_outputs)
                                log_debug(f"[Workflow Mode] Synthesis returned empty, using raw outputs")
                            else:
                                log_debug(f"[Workflow Mode] LLM synthesis: {len(combined_response)} chars from {len(orchestration_outputs)} outputs")
                        
                        except Exception as synth_err:
                            log_error(f"[Workflow Mode] Synthesis failed ({synth_err}), using raw outputs")
                            combined_response = "\n\n".join(orchestration_outputs)
                    else:
                        combined_response = "Workflow completed successfully."
                    
                    # Return as single response (not a list)
                    final_responses = [combined_response]

                    # Include agent-generated artifacts (images, videos) so they persist in chat history
                    if hasattr(session_context, '_agent_generated_artifacts') and session_context._agent_generated_artifacts:
                        artifact_file_parts = []
                        video_metadata_parts = []
                        for part in session_context._agent_generated_artifacts:
                            target = getattr(part, 'root', part)
                            if isinstance(target, DataPart) and isinstance(target.data, dict):
                                if target.data.get('type') == 'video_metadata':
                                    video_metadata_parts.append(part)
                                    continue
                            uri = extract_uri(part)
                            if uri and uri.startswith('http'):
                                if is_file_part(part):
                                    actual_part = part.root if hasattr(part, 'root') and is_file_part(part.root) else part
                                    artifact_file_parts.append(actual_part)
                                else:
                                    file_part = convert_artifact_dict_to_file_part(part)
                                    if file_part:
                                        artifact_file_parts.append(file_part)

                        if artifact_file_parts:
                            combined_parts = []
                            for fp in artifact_file_parts:
                                if hasattr(fp, 'root'):
                                    combined_parts.append(fp)
                                else:
                                    combined_parts.append(Part(root=fp))
                            for vmp in video_metadata_parts:
                                if hasattr(vmp, 'root'):
                                    combined_parts.append(vmp)
                                else:
                                    combined_parts.append(Part(root=vmp))
                            if combined_parts:
                                combined_message = Message(
                                    role='agent',
                                    parts=combined_parts,
                                    messageId=str(uuid.uuid4()),
                                )
                                final_responses.append(combined_message)
                                log_debug(f"[Workflow Mode] Including {len(artifact_file_parts)} artifact(s) in persisted response")
                    
                    # Record workflow run in history (for on-demand runs via routing)
                    if selected_workflow_metadata:
                        try:
                            from service.scheduler_service import get_workflow_scheduler
                            from datetime import datetime
                            scheduler = get_workflow_scheduler()
                            session_id = context_id.split("::")[0] if "::" in context_id else "unknown"
                            scheduler._add_run_history(
                                schedule_id="on-demand",  # Indicates this was not a scheduled run
                                workflow_id=selected_workflow_metadata.get('id', ''),
                                workflow_name=selected_workflow_metadata.get('name', ''),
                                session_id=session_id,
                                status="success",
                                result=combined_response[:2000] if combined_response else None,
                                error=None,
                                started_at=None,  # Will use current time
                                completed_at=None,
                                execution_time=None
                            )
                            log_debug(f"[Run History] Recorded on-demand workflow run: {selected_workflow_metadata.get('name')}")
                        except Exception as history_err:
                            log_error(f"[Run History] Failed to record workflow run: {history_err}")
                    
                    # Store the interaction and return
                    log_debug("About to store User->Host interaction for context_id: {context_id}")
                    await self._store_user_host_interaction_safe(
                        user_message_parts=message_parts,
                        user_message_text=enhanced_message,
                        host_response=final_responses,
                        context_id=context_id,
                        span=span,
                        session_context=session_context
                    )
                    
                    # Persist agent response to chat history database
                    try:
                        persist_parts = _build_persist_parts(final_responses)
                        if persist_parts:
                            # Build metadata with workflow plan if available
                            message_metadata = {"type": "agent_response", "agentName": "foundry-host-agent"}
                            if session_context and session_context.current_plan:
                                try:
                                    plan_data = session_context.current_plan.model_dump(mode='json', exclude_none=True)
                                    message_metadata["workflow_plan"] = plan_data
                                except Exception as plan_err:
                                    log_warning(f"[ChatHistory] Warning - could not serialize plan: {plan_err}")

                            persist_message(context_id, {
                                "messageId": str(uuid.uuid4()),
                                "role": "agent",
                                "parts": persist_parts,
                                "contextId": context_id,
                                "metadata": message_metadata
                            })
                    except Exception as e:
                        log_debug(f"[ChatHistory] Error persisting agent response: {e}")

                    # =========================================================
                    # CONVERSATION HISTORY: Record workflow in Responses API
                    # =========================================================
                    # After workflow completes, make a Responses API call to record
                    # the user message and workflow result in the conversation history.
                    # This ensures follow-up messages have proper context via
                    # previous_response_id chaining.
                    # =========================================================
                    try:
                        tools = self._format_tools_for_responses_api()
                        # Create a context-recording response - include user's original request
                        # and the workflow result so LLM has full context for follow-ups
                        workflow_context_message = f"""User request: {enhanced_message}

Workflow completed with result:
{combined_response[:3000] if len(combined_response) > 3000 else combined_response}"""
                        
                        # Use non-streaming call just to record context
                        await self._ensure_project_client()
                        previous_response_id = self._response_ids.get(context_id)
                        
                        context_response = await self.openai_client.responses.create(
                            input=workflow_context_message,
                            previous_response_id=previous_response_id,
                            instructions="You are a helpful assistant. The user just completed a workflow. Acknowledge the completion briefly.",
                            model=self.model_name,
                            tools=tools,
                        )
                        
                        # Store the response ID for conversation continuity
                        if hasattr(context_response, 'id') and context_response.id:
                            self._response_ids[context_id] = context_response.id
                            log_info(f"[Workflow] Recorded workflow context in conversation history: {context_response.id}")
                        
                    except Exception as ctx_err:
                        log_debug(f"[Workflow] Failed to record workflow context: {ctx_err}")
                        # Non-critical - workflow still completed successfully
                    
                    log_debug(f"[Workflow Mode] Orchestration complete, returning 1 combined response")
                    return final_responses
                    
                except Exception as e:
                    log_error(f"[Agent Mode] Orchestration error: {e}")

                    # Get error type and message
                    error_type = type(e).__name__
                    error_msg = str(e) if str(e) else error_type
                    
                    # If synthesis failed but we have agent outputs, return them directly
                    if orchestration_outputs:
                        log_error(f"[Agent Mode] Synthesis failed ({error_msg}), but returning {len(orchestration_outputs)} agent outputs directly")
                        # Strip markdown image references — images displayed separately as FileParts
                        import re as _re
                        final_responses = [
                            _re.sub(r'\n{3,}', '\n\n', _re.sub(r'!\[[^\]]*\]\([^)]+\)', '', o)).strip()
                            for o in orchestration_outputs
                        ]
                        
                        # Add ONLY agent-generated artifacts if available
                        if hasattr(session_context, '_agent_generated_artifacts'):
                            artifact_dicts = []
                            for part in session_context._agent_generated_artifacts:
                                # Use utility to extract URI from any part type
                                uri = extract_uri(part)
                                if uri:
                                    # Convert to FilePart format for consistency
                                    file_part = convert_artifact_dict_to_file_part(part)
                                    if file_part:
                                        artifact_dicts.append(file_part)
                            
                            if artifact_dicts:
                                log_debug(f"[Agent Mode] Including {len(artifact_dicts)} agent-generated artifact(s) in fallback response")
                                final_responses.extend(artifact_dicts)
                        
                        # Persist agent response to chat history database
                        try:
                            persist_parts = _build_persist_parts(final_responses)
                            if persist_parts:
                                message_metadata = {"type": "agent_response", "agentName": "foundry-host-agent"}
                                if session_context and session_context.current_plan:
                                    try:
                                        plan_data = session_context.current_plan.model_dump(mode='json', exclude_none=True)
                                        message_metadata["workflow_plan"] = plan_data
                                    except Exception as plan_err:
                                        log_warning(f"[ChatHistory] Warning - could not serialize plan: {plan_err}")

                                persist_message(context_id, {
                                    "messageId": str(uuid.uuid4()),
                                    "role": "agent",
                                    "parts": persist_parts,
                                    "contextId": context_id,
                                    "metadata": message_metadata
                                })
                        except Exception as e:
                            log_debug(f"[ChatHistory] Error persisting agent response: {e}")

                        return final_responses
                    else:
                        # No outputs to return, show error
                        final_responses = [f"Agent Mode orchestration encountered an error: {error_msg}"]
                        # Persist error response - include plan for error context
                        try:
                            message_metadata = {"type": "agent_response", "error": True, "agentName": "foundry-host-agent"}
                            if session_context and session_context.current_plan:
                                try:
                                    plan_data = session_context.current_plan.model_dump(mode='json', exclude_none=True)
                                    message_metadata["workflow_plan"] = plan_data
                                except Exception as plan_err:
                                    log_warning(f"[ChatHistory] Warning - could not serialize plan: {plan_err}")
                            
                            persist_message(context_id, {
                                "messageId": str(uuid.uuid4()),
                                "role": "agent",
                                "parts": [{"root": {"kind": "text", "text": final_responses[0]}}],
                                "contextId": context_id,
                                "metadata": message_metadata
                            })
                        except Exception as e:
                            log_debug(f"[ChatHistory] Error persisting error response: {e}")
                        return final_responses
            
            # Continue with standard conversation flow using Responses API (streaming)
            log_foundry_debug(f"=================== STARTING RESPONSE CREATION ===================")
            log_foundry_debug(f"Creating response with Responses API (streaming)")
            await self._emit_granular_agent_event(
                "foundry-host-agent", "creating AI response with streaming", context_id,
                event_type="info", metadata={"action": "response_creation"}
            )
            
            # Get tools for this agent
            tools = self._format_tools_for_responses_api()
            
            # Create streaming response
            log_debug(f"[DEBUG] About to create response with instructions containing {len(self.cards)} agents")
            log_debug(f"[DEBUG] Agent names in self.cards: {list(self.cards.keys())}")
            log_debug(f"[DEBUG] self.agents JSON value:\n{self.agents}")
            log_foundry_debug(f"[DEBUG] FULL INSTRUCTIONS being sent to Azure:\n{self.agent_instructions if self.agent_instructions else 'NONE'}")
            log_debug(f"[DEBUG] ===== END INSTRUCTIONS =====")
            response = await self._create_response_with_streaming(
                user_message=enhanced_message,
                context_id=context_id,
                session_context=session_context,
                tools=tools,
                instructions=self.agent_instructions or '',
                event_logger=event_logger,
                image_urls=image_uris_for_vision if image_uris_for_vision else None
            )

            log_foundry_debug(f"Response created successfully with ID: {response['id']}, status: {response['status']}")
            log_foundry_debug(f"=================== RESPONSE CREATED SUCCESSFULLY ===================")
            await self._emit_granular_agent_event(
                "foundry-host-agent", f"AI response created - status: {response['status']}", context_id,
                event_type="info", metadata={"response_id": response['id'], "status": str(response['status'])}
            )
            
            # Handle tool calls if needed (iterative loop for multi-turn tool execution)
            # NOTE: _create_response_with_streaming now handles tool calls internally, 
            # so this loop should rarely execute (only if internal loop hit max iterations)
            max_tool_iterations = 30
            tool_iteration = 0
            last_tool_output = None
            
            # Helper to check if response status requires action (handles enum and string)
            def response_requires_action(response_status):
                if response_status is None:
                    return False
                status_str = str(response_status).lower()
                return "requires_action" in status_str
            
            log_foundry_debug(f"Starting tool handling loop for response {response['id']}")
            while response_requires_action(response["status"]) and tool_iteration < max_tool_iterations:
                tool_iteration += 1
                log_foundry_debug(f"Tool iteration {tool_iteration}, response requires action")
                await self._emit_granular_agent_event(
                    "foundry-host-agent", f"executing tools (attempt {tool_iteration})", context_id,
                    event_type="tool_call", metadata={"attempt": tool_iteration}
                )
                
                # Execute all tool calls from this response
                tool_outputs = await self._execute_tool_calls_from_response(
                    tool_calls=response.get('tool_calls', []),
                    context_id=context_id,
                    session_context=session_context,
                    event_logger=event_logger
                )
                
                if tool_outputs:
                    last_tool_output = tool_outputs
                    await self._emit_granular_agent_event(
                        "foundry-host-agent", "tool execution completed, continuing conversation", context_id,
                        event_type="info", metadata={"action": "tool_complete"}
                    )
                    
                    # Create a new response with tool outputs to continue the conversation
                    # The tool outputs become part of the conversation history via previous_response_id chaining
                    response = await self._create_response_with_streaming(
                        user_message="",  # Empty message, tool outputs are in conversation history
                        context_id=context_id,
                        session_context=session_context,
                        tools=tools,
                        instructions=self.agent_instructions or '',
                        event_logger=event_logger
                    )
                    log_foundry_debug(f"Created follow-up response after tool execution: {response['id']}, status: {response['status']}")
                else:
                    log_debug(f"No tool outputs generated, breaking tool loop")
                    break
            
            log_foundry_debug(f"Tool handling loop completed. Final status: {response['status']}, iterations: {tool_iteration}")
            await self._emit_granular_agent_event(
                "foundry-host-agent", "AI processing completed, finalizing response", context_id,
                event_type="phase", metadata={"phase": "complete"}
            )
            
            # Get response text
            responses = []
            if response.get('text'):
                responses.append(response['text'])
                log_foundry_debug(f"Found response text: {response['text'][:100]}...")
            
            # If no valid response text found, surface tool output as fallback
            if not responses and last_tool_output:
                log_foundry_debug(f"No response text found, using tool output as fallback")
                # Extract response from tool outputs
                for tool_output in last_tool_output:
                    if isinstance(tool_output, dict) and 'output' in tool_output:
                        responses.append(tool_output['output'])
            
            log_foundry_debug(f"After response processing - responses count: {len(responses) if responses else 0}")
            if responses:
                log_foundry_debug(f"First response: {responses[0][:100]}...")
                
                # Check if files were processed and have extracted content
                has_extracted_content = False
                extracted_contents = []
                
                if processed_parts and any(isinstance(p, DataPart) for p in processed_parts):
                    artifact_info = []
                    
                    for p in processed_parts:
                        if isinstance(p, DataPart) and hasattr(p, 'data') and 'artifact-id' in p.data:
                            artifact_info.append(p.data)
                            
                            # Check if we have extracted content to display
                            if 'extracted_content' in p.data and p.data['extracted_content']:
                                file_name = p.data.get('file-name', 'uploaded file')
                                content = p.data['extracted_content']
                                extracted_contents.append(f"**{file_name}:**\n{content}")
                                has_extracted_content = True
                
                final_responses: List[str] = []

                # Include the assessment agent responses first if available
                if responses:
                    if isinstance(responses, list):
                        final_responses.extend(str(r) for r in responses if r)
                    else:
                        final_responses.append(str(responses))

                # Include ONLY agent-generated artifacts (not user uploads) in Standard Mode
                # This ensures NEW images show up with "Refine" buttons, but user uploads don't echo
                # Use centralized utility for clean artifact handling
                if hasattr(session_context, '_agent_generated_artifacts') and session_context._agent_generated_artifacts:
                    # Strip markdown image references from text responses — images are
                    # displayed separately as FilePart artifacts with Refine buttons
                    import re as _re
                    final_responses = [
                        _re.sub(r'\n{3,}', '\n\n', _re.sub(r'!\[[^\]]*\]\([^)]+\)', '', r)).strip()
                        if isinstance(r, str) else r
                        for r in final_responses
                    ]

                if hasattr(session_context, '_agent_generated_artifacts'):
                    artifact_file_parts = []  # FilePart objects (standard format)
                    video_metadata_parts = []  # DataParts with video_metadata (for video_id tracking)
                    
                    for part in session_context._agent_generated_artifacts:
                        # Check if this is a video_metadata DataPart - keep it for later
                        target = getattr(part, 'root', part)
                        if isinstance(target, DataPart) and isinstance(target.data, dict):
                            if target.data.get('type') == 'video_metadata':
                                video_metadata_parts.append(part)
                                log_debug(f"[VideoRemix] Collected video_metadata with video_id: {target.data.get('video_id')}")
                                continue  # Don't convert to FilePart
                        
                        # Use utility to extract URI from any format
                        uri = extract_uri(part)
                        if uri and uri.startswith('http'):
                            # Convert to FilePart if not already
                            if is_file_part(part):
                                # Already a FilePart, use directly
                                actual_part = part.root if hasattr(part, 'root') and is_file_part(part.root) else part
                                artifact_file_parts.append(actual_part)
                                log_debug(f"Found FilePart artifact: {uri[:80]}...")
                            else:
                                # Convert legacy DataPart to FilePart
                                file_part = convert_artifact_dict_to_file_part(part)
                                if file_part:
                                    artifact_file_parts.append(file_part)
                                    log_debug(f"Converted DataPart to FilePart: {uri[:80]}...")
                    
                    # Group video FileParts with their metadata to preserve video_id for remix
                    if artifact_file_parts:
                        log_debug(f"[Standard Mode] Including {len(artifact_file_parts)} FilePart artifact(s) in response")
                        
                        # Create a Message containing all artifact parts (FileParts + video_metadata)
                        # This ensures video_id flows through to frontend
                        combined_parts = []
                        for fp in artifact_file_parts:
                            if hasattr(fp, 'root'):
                                combined_parts.append(fp)  # Already a Part
                            else:
                                combined_parts.append(Part(root=fp))
                        
                        # Add video_metadata DataParts so they're in the same Message
                        for vmp in video_metadata_parts:
                            if hasattr(vmp, 'root'):
                                combined_parts.append(vmp)
                            else:
                                combined_parts.append(Part(root=vmp))
                        
                        # Create a single Message with all parts (FileParts + video_metadata)
                        if combined_parts:
                            combined_message = Message(
                                role='agent',
                                parts=combined_parts,
                                messageId=str(uuid.uuid4()),
                            )
                            final_responses.append(combined_message)
                            log_debug(f"[VideoRemix] Created combined message with {len(artifact_file_parts)} FileParts and {len(video_metadata_parts)} video_metadata")
                        
                        for idx, fp in enumerate(artifact_file_parts):
                            file_obj = getattr(fp, 'file', None)
                            uri = getattr(file_obj, 'uri', '') if file_obj else ''
                            filename = getattr(file_obj, 'name', 'unknown') if file_obj else 'unknown'
                            log_debug(f"  FilePart Artifact {idx+1}: {filename} (URI: {uri[:80]}...)")

                # If we have extracted content, prepend it to the response
                if has_extracted_content:
                    extracted_content_message = (
                        "The file has been processed. Here is the extracted content:\n\n" + 
                        "\n\n---\n\n".join(extracted_contents)
                    )
                    log_debug(f"Prepending extracted content to response...")
                    final_responses.insert(0, extracted_content_message)

                # Fallback if nothing collected yet
                if not final_responses:
                    final_responses = ["No response received"]

                # Add acknowledgement when files processed but no extracted content
                if (processed_parts and any(isinstance(p, DataPart) for p in processed_parts) and not has_extracted_content):
                    final_responses.append(
                        f"File processing completed. {len([p for p in processed_parts if isinstance(p, DataPart)])} file(s) uploaded and stored as artifacts."
                    )
                
                log_foundry_debug(f"final_responses set to: {final_responses} (FIRST PATH)")
                log_foundry_debug(f"final_responses count: {len(final_responses)} (FIRST PATH)")
                
                # Note: Conversation history is now managed by OpenAI threads - no need to store separately
                
                # Store User->Host A2A interaction (fire-and-forget)
                log_debug(f"About to store User->Host interaction for context_id: {context_id}")
                
                # Extract artifact info from processed parts for memory storage
                artifact_info = {}
                for i, result in enumerate(processed_parts):
                    if isinstance(result, DataPart) and hasattr(result, 'data') and 'artifact-id' in result.data:
                        artifact_info[i] = {
                            'artifact_id': result.data.get('artifact-id'),
                            'artifact_uri': result.data.get('artifact-uri'),
                            'file-name': result.data.get('file-name'),
                            'storage-type': result.data.get('storage-type')
                        }
                
                asyncio.create_task(self._store_user_host_interaction_safe(
                    user_message_parts=message_parts,  # Original parts - will be cleaned in memory storage
                    user_message_text=user_message,
                    host_response=final_responses,
                    context_id=context_id,
                    span=span,
                    artifact_info=artifact_info,  # Pass artifact info for URI replacement
                    session_context=session_context
                ))
                
                # Persist agent response to chat history database
                try:
                    persist_parts = _build_persist_parts(final_responses)
                    if persist_parts:
                        # Build metadata with workflow plan if available
                        message_metadata = {"type": "agent_response", "agentName": "foundry-host-agent"}
                        if session_context and session_context.current_plan:
                            try:
                                plan_data = session_context.current_plan.model_dump(mode='json', exclude_none=True)
                                message_metadata["workflow_plan"] = plan_data
                            except Exception as plan_err:
                                log_warning(f"[ChatHistory] Warning - could not serialize plan: {plan_err}")

                        persist_message(context_id, {
                            "messageId": str(uuid.uuid4()),
                            "role": "agent",
                            "parts": persist_parts,
                            "contextId": context_id,
                            "metadata": message_metadata
                        })
                except Exception as e:
                    log_debug(f"[ChatHistory] Error persisting agent response: {e}")
                
                log_foundry_debug(f"About to return final_responses: {final_responses} (FIRST PATH)")
                
                return final_responses
        
        except Exception as e:
            log_error(f"CRITICAL ERROR in run_conversation_with_parts: {e}")
            import traceback
            log_error(f"FULL TRACEBACK: {traceback.format_exc()}")
            raise

    async def _handle_tool_calls(self, run: Dict[str, Any], thread_id: str, context_id: str, session_context: SessionContext, event_logger=None):
        """
        Execute function tools requested by the host agent during conversation processing.
        
        The host agent can call two main tools:
        1. **list_remote_agents**: Get list of available specialized agents
        2. **send_message**: Delegate tasks to specific remote agents
        
        Key optimization: PARALLEL EXECUTION
        - When multiple agents are needed, we call them simultaneously rather than sequentially
        - This dramatically reduces latency for multi-agent workflows
        - Example: Analyzing an image AND searching a knowledge base can happen at once
        
        The function handles:
        - Parsing tool call arguments from Azure AI Foundry JSON format
        - Executing send_message calls in parallel using asyncio.gather
        - Processing list_remote_agents calls sequentially (fast operation)
        - Converting responses back to Azure AI Foundry expected format
        - Error handling for individual tool failures (doesn't fail entire batch)
        
        Args:
            run: Azure AI Foundry run object with required_action containing tool_calls
            thread_id: Azure AI Foundry thread identifier
            context_id: Conversation context for state management
            session_context: Session state with agent tracking
            event_logger: Optional callback for logging tool execution
            
        Returns:
            Last tool output for fallback response if host agent doesn't generate text
        """
        with tracer.start_as_current_span("handle_tool_calls") as span:
            span.set_attribute("context_id", context_id)
            
            if not run.get('required_action'):
                return None
                
            required_action = run.get('required_action')
            if not required_action.get('submit_tool_outputs'):
                return None
                
            tool_calls = required_action['submit_tool_outputs']['tool_calls']
            
            # Add status message for tool calls starting
            self._add_status_message_to_conversation(f"🛠️ Executing {len(tool_calls)} tool call(s)", context_id)
            await self._emit_granular_agent_event(
                "foundry-host-agent", f"executing {len(tool_calls)} tool(s)", context_id,
                event_type="tool_call", metadata={"tool_count": len(tool_calls)}
            )
            
            tool_outputs = []
            successful_tool_outputs: List[Dict[str, Any]] = []
            last_tool_output = None
            
            # NEW: Collect all send_message tool calls for parallel execution
            send_message_tasks = []
            send_message_tool_calls = []
            other_tool_calls = []
            
            # Separate send_message calls from other tool calls
            for tool_call in tool_calls:
                function_name = tool_call['function']['name']
                arguments = tool_call['function']['arguments']
                
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                
                if function_name == "send_message":
                    # Collect send_message calls for parallel execution
                    send_message_tool_calls.append((tool_call, function_name, arguments))
                else:
                    # Keep other tool calls for sequential execution
                    other_tool_calls.append((tool_call, function_name, arguments))
            
            # Execute send_message calls in parallel
            if send_message_tool_calls:
                log_debug(f"Executing {len(send_message_tool_calls)} send_message calls in parallel")
                span.add_event("parallel_agent_calls_started", {
                    "agent_calls_count": len(send_message_tool_calls),
                    "run_id": run["id"]
                })
                
                # Add status message for parallel agent calls
                self._add_status_message_to_conversation(f"🚀 Executing {len(send_message_tool_calls)} agent calls in parallel", context_id)
                await self._emit_granular_agent_event(
                    "foundry-host-agent", f"calling {len(send_message_tool_calls)} agent(s) in parallel", context_id,
                    event_type="phase", metadata={"phase": "parallel_agents", "agent_count": len(send_message_tool_calls)}
                )
                
                # Create tasks for all send_message calls
                for tool_call, function_name, arguments in send_message_tool_calls:
                    agent_name = arguments.get("agent_name")
                    message = arguments.get("message", "")
                    # EXPLICIT FILE ROUTING: Extract file_uris and video_metadata from arguments
                    file_uris = arguments.get("file_uris", None)
                    video_metadata = arguments.get("video_metadata", None)
                    
                    # Add status message for each agent call
                    self._add_status_message_to_conversation(f"🛠️ Executing tool: send_message to {agent_name}", context_id)
                    await self._emit_granular_agent_event(
                        agent_name, f"calling {agent_name} agent", context_id,
                        event_type="agent_start", metadata={"agent_name": agent_name}
                    )
                    
                    # Enhanced agent selection tracking
                    span.add_event("parallel_agent_selected", {
                        "agent_name": agent_name,
                        "message_preview": message[:50] + "..." if len(message) > 50 else message,
                        "file_uris_count": len(file_uris) if file_uris else 0,
                        "has_video_metadata": bool(video_metadata)
                    })
                    
                    # Stream granular tool call to WebSocket for thinking box visibility
                    asyncio.create_task(self._emit_tool_call_event(agent_name, "send_message", arguments, context_id))
                    
                    # Log tool call event - use agent_name as actor so frontend can attribute correctly
                    if event_logger:
                        event_logger({
                            "id": str(uuid.uuid4()),
                            "actor": agent_name,  # Use actual agent name, not host
                            "args": arguments,
                            "name": function_name,
                            "type": "tool_call"
                        })
                    
                    # EXPLICIT FILE ROUTING: Pass file_uris and video_metadata to send_message
                    # This enables proper parallel execution without shared state issues
                    tool_context = DummyToolContext(session_context, self._azure_blob_client)
                    task = self.send_message(
                        agent_name, 
                        message, 
                        tool_context, 
                        suppress_streaming=True,
                        file_uris=file_uris,
                        video_metadata=video_metadata
                    )
                    send_message_tasks.append((tool_call, task))
                
                # Execute all send_message calls in parallel
                try:
                    # Wait for all parallel tasks to complete
                    parallel_results = await asyncio.gather(*[task for _, task in send_message_tasks], return_exceptions=True)
                    
                    # Process results and create tool outputs
                    for i, (tool_call, _) in enumerate(send_message_tasks):
                        result = parallel_results[i]
                        agent_name = send_message_tool_calls[i][2].get("agent_name")
                        
                        if isinstance(result, Exception):
                            log_error(f"Parallel agent call failed: {result}")
                            output = {"error": f"Agent call failed: {str(result)}"}
                            self._add_status_message_to_conversation(f"❌ Agent call to {agent_name} failed", context_id)
                            span.add_event("parallel_agent_call_failed", {
                                "agent_name": agent_name,
                                "error": str(result)
                            })
                            asyncio.create_task(self._emit_tool_response_event(agent_name, "send_message", "failed", str(result), context_id))
                        else:
                            output = result
                            self._add_status_message_to_conversation(f"✅ Agent call to {agent_name} completed", context_id)
                            span.add_event("parallel_agent_call_success", {
                                "agent_name": agent_name,
                                "output_type": type(output).__name__
                            })
                            asyncio.create_task(self._emit_tool_response_event(agent_name, "send_message", "success", None, context_id))
                        
                        # Log tool result event - use agent_name as actor so frontend can attribute correctly
                        if event_logger:
                            event_logger({
                                "id": str(uuid.uuid4()),
                                "actor": agent_name,  # Use actual agent name, not host
                                "name": "send_message",
                                "type": "tool_result",
                                "output": output
                            })
                        
                        # Format output for Azure AI Agents using clean text format
                        # The model expects readable text, not complex JSON wrappers
                        agent_name = send_message_tool_calls[i][2].get("agent_name")
                        normalized_text = self._format_agent_response_for_model(output, agent_name) if not isinstance(result, Exception) else json.dumps({"error": str(result), "agent": agent_name})

                        tool_outputs.append({
                            "tool_call_id": tool_call["id"],
                            "output": normalized_text
                        })

                        if not isinstance(result, Exception):
                            successful_tool_outputs.append({"agent": agent_name, "response": normalized_text})
                            last_tool_output = {"agent": agent_name, "response": normalized_text}
                    
                    self._add_status_message_to_conversation("✅ All parallel agent calls completed", context_id)
                    await self._emit_granular_agent_event(
                        "foundry-host-agent", "all agent calls completed", context_id,
                        event_type="info", metadata={"action": "all_agents_complete"}
                    )
                    span.add_event("parallel_agent_calls_completed", {
                        "successful_calls": len([r for r in parallel_results if not isinstance(r, Exception)]),
                        "failed_calls": len([r for r in parallel_results if isinstance(r, Exception)])
                    })
                    
                except Exception as e:
                    log_error(f"Error in parallel agent execution: {e}")
                    self._add_status_message_to_conversation(f"❌ Parallel execution failed: {str(e)}", context_id)
                    span.add_event("parallel_agent_execution_error", {
                        "error": str(e)
                    })
                    # Fallback to sequential execution if parallel fails
                    for tool_call, function_name, arguments in send_message_tool_calls:
                        output = {"error": f"Parallel execution failed: {str(e)}"}
                        tool_outputs.append({
                            "tool_call_id": tool_call["id"],
                            "output": json.dumps({
                                "kind": "function_response",
                                "name": function_name,
                                "response": output
                            })
                        })
            
            # Execute other tool calls sequentially
            for tool_call, function_name, arguments in other_tool_calls:
                self._add_status_message_to_conversation(f"🛠️ Executing tool: {function_name}", context_id)
                await self._emit_granular_agent_event(
                    "foundry-host-agent", f"executing {function_name} tool", context_id,
                    event_type="tool_call", metadata={"tool_name": function_name}
                )
                
                span.add_event(f"tool_call: {function_name}", {"function_name": function_name})
                await self._emit_tool_call_event("foundry-host-agent", function_name, arguments, context_id)
                
                if event_logger:
                    event_logger({
                        "id": str(uuid.uuid4()),
                        "actor": "foundry-host-agent",
                        "args": arguments,
                        "name": function_name,
                        "type": "tool_call"
                    })
                
                if function_name == "list_remote_agents":
                    output = self.list_remote_agents()
                    self._add_status_message_to_conversation(f"✅ Tool {function_name} completed", context_id)
                    await self._emit_tool_response_event("foundry-host-agent", function_name, "success", None, context_id)
                else:
                    output = {"error": f"Unknown function: {function_name}"}
                    self._add_status_message_to_conversation(f"❌ Unknown tool: {function_name}", context_id)
                    await self._emit_tool_response_event("foundry-host-agent", function_name, "failed", f"Unknown function: {function_name}", context_id)
                
                if event_logger:
                    event_logger({
                        "id": str(uuid.uuid4()),
                        "actor": "foundry-host-agent",
                        "name": function_name,
                        "type": "tool_result",
                        "output": output
                    })
                
                # Format output for Azure AI Agents
                normalized_output = self._normalize_function_response_text(output)
                if isinstance(normalized_output, list):
                    normalized_text = "\n\n".join(str(item) for item in normalized_output)
                elif isinstance(normalized_output, str):
                    normalized_text = normalized_output
                else:
                    normalized_text = str(normalized_output)

                payload = {
                    "kind": "function_response",
                    "name": function_name,
                    "response": normalized_text
                }

                tool_outputs.append({
                    "tool_call_id": tool_call["id"],
                    "output": json.dumps(payload)
                })

                successful_tool_outputs.append(payload)
                last_tool_output = payload
            
            # Submit tool outputs via HTTP API
            await self._http_submit_tool_outputs(thread_id, run["id"], tool_outputs)
            
            if successful_tool_outputs:
                combined_text = "\n\n---\n\n".join(
                    payload.get("response", "") for payload in successful_tool_outputs if isinstance(payload.get("response"), str)
                )
                return combined_text

            if isinstance(last_tool_output, dict):
                response_text = last_tool_output.get("response")
                if isinstance(response_text, str):
                    return response_text

            return last_tool_output

    async def convert_parts(self, parts: List[Part], tool_context: Any, context_id: str = None):
        """
        Convert A2A Parts to flattened format suitable for agent delegation.
        
        Handles:
        - DataPart with artifact metadata -> FilePart + DataPart for remote agents
        - Part wrappers (Part(root=FilePart)) -> unwrap to inner part
        - TextPart, FilePart, DataPart -> pass through
        - Dicts with artifact-uri -> wrap in DataPart
        - Refine-image payloads -> preserve for image editing workflow
        
        NOTE: Parts are stored in _latest_processed_parts for WORKFLOW orchestration only.
        The send_message method uses EXPLICIT FILE ROUTING via file_uris parameter.
        """
        rval = []
        session_context = getattr(tool_context, "state", None)
        
        # Initialize _latest_processed_parts for workflow orchestration (not for send_message routing)
        if session_context is not None and not hasattr(session_context, '_latest_processed_parts'):
            session_context._latest_processed_parts = []

        for p in parts:
            result = await self.convert_part(p, tool_context, context_id)
            if result is None:
                continue
            if isinstance(result, list):
                rval.extend(result)
            else:
                rval.append(result)

        # --- URI/Role tracking for image editing workflow ---
        # This tracks URIs to avoid duplicates and assigns roles (base/mask/overlay)
        uri_to_parts: Dict[str, List[Any]] = {}
        assigned_roles: Dict[str, str] = {}

        def _register_part_uri(part: Any, uri: Optional[str]) -> None:
            normalized_uri = self._normalize_uri(uri)
            if normalized_uri:
                uri_to_parts.setdefault(normalized_uri, []).append(part)

        def _register_role(uri: Optional[str], role: Optional[str]) -> None:
            if role:
                normalized_uri = self._normalize_uri(uri)
                if normalized_uri:
                    assigned_roles[normalized_uri] = str(role).lower()

        flattened_parts = []
        pending_file_parts: List[FilePart] = []
        refine_payload = None

        # --- Flatten and normalize all items ---
        # Items can be: DataPart, TextPart, FilePart, Part wrappers, dicts, strings
        for item in rval:
            # Unwrap Part wrappers first (Part(root=FilePart))
            if hasattr(item, 'root') and isinstance(item.root, (TextPart, FilePart, DataPart)):
                item = item.root  # Unwrap and continue with inner part
            
            # --- DataPart with video/image metadata (preserve for frontend) ---
            # Must check BEFORE artifact-uri check since these don't have artifact-uri
            if isinstance(item, DataPart) and isinstance(getattr(item, 'data', None), dict):
                if item.data.get('type') in ('video_metadata', 'image_metadata'):
                    # Keep the DataPart as-is - it contains video_id for remix
                    flattened_parts.append(item)
                    continue
            
            # --- DataPart with artifact metadata (needs FilePart conversion) ---
            if isinstance(item, DataPart) and isinstance(getattr(item, 'data', None), dict):
                artifact_uri = item.data.get("artifact-uri")
                existing_role = item.data.get("role") or (item.data.get("metadata") or {}).get("role")
                name_hint = item.data.get("file-name") or item.data.get("name") or item.data.get("artifact-id")
                role_value = self._infer_file_role(existing_role, name_hint)

                if role_value and str(role_value).lower() != (existing_role or "").lower():
                    item.data["role"] = role_value
                    metadata_block = item.data.get("metadata") or {}
                    metadata_block["role"] = role_value
                    item.data["metadata"] = metadata_block

                metadata = {
                    "artifact-id": item.data.get("artifact-id"),
                    "storage-type": item.data.get("storage-type"),
                    "file-name": item.data.get("file-name"),
                    "artifact-uri": artifact_uri,
                }
                existing_meta = (item.data.get("metadata") or {}).copy()
                if role_value:
                    metadata["role"] = role_value
                    existing_meta["role"] = role_value
                elif existing_role:
                    metadata["role"] = existing_role
                    existing_meta["role"] = existing_role
                metadata["metadata"] = existing_meta

                data_part = DataPart(data=metadata)
                flattened_parts.append(data_part)
                _register_part_uri(data_part, artifact_uri)
                if role_value:
                    _register_role(artifact_uri, role_value)

                # Also create FilePart for remote agents
                if artifact_uri:
                    file_with_uri_kwargs = {
                        "name": item.data.get("file-name", metadata["artifact-id"]) or metadata["artifact-id"],
                        "mimeType": item.data.get("media-type", "application/octet-stream"),
                        "uri": artifact_uri,
                    }
                    file_part_kwargs = {"file": FileWithUri(**file_with_uri_kwargs)}
                    if role_value:
                        file_part_kwargs["metadata"] = {"role": role_value}
                    
                    file_part = FilePart(**file_part_kwargs)
                    flattened_parts.append(file_part)
                    pending_file_parts.append(file_part)
                    _register_part_uri(file_part, artifact_uri)
                    if role_value:
                        _register_role(artifact_uri, role_value)

                if "extracted_content" in item.data:
                    flattened_parts.append(TextPart(text=str(item.data["extracted_content"])))
            
            # --- Simple TextPart/FilePart (pass through) ---
            elif isinstance(item, (TextPart, FilePart)):
                flattened_parts.append(item)
                _register_part_uri(item, extract_uri(item))
            
            # --- Simple DataPart without artifact-uri (stringify) ---
            elif isinstance(item, DataPart):
                flattened_parts.append(TextPart(text=str(item.data)))
            
            # --- Dict (artifact metadata or refine command) ---
            elif isinstance(item, dict):
                if item.get("kind") == "refine-image":
                    refine_payload = item
                elif "artifact-uri" in item or "artifact-id" in item:
                    artifact_data_part = DataPart(data=item)
                    flattened_parts.append(artifact_data_part)
                    _register_part_uri(artifact_data_part, item.get("artifact-uri"))
                    if item.get("role"):
                        _register_role(item.get("artifact-uri"), item.get("role"))
                else:
                    text = item.get("response") or item.get("text") or json.dumps(item, ensure_ascii=False)
                    flattened_parts.append(TextPart(text=text))
            
            # --- Fallback: stringify ---
            elif item is not None:
                flattened_parts.append(TextPart(text=str(item)))

        # Store in _latest_processed_parts for WORKFLOW ORCHESTRATION compatibility
        # (send_message uses explicit file_uris parameter instead of this storage)
        session_context = getattr(tool_context, "state", None)
        if session_context is not None:
            if not hasattr(session_context, '_latest_processed_parts'):
                session_context._latest_processed_parts = []
            # Store file parts for workflow deduplication and artifact collection
            file_parts_only = [p for p in flattened_parts if isinstance(p, FilePart)]
            if file_parts_only:
                session_context._latest_processed_parts.extend(file_parts_only)

        if refine_payload:
            refine_part = DataPart(data=refine_payload)
            flattened_parts.append(refine_part)

        # NOTE: pending_file_parts are already added to flattened_parts during the loop above
        # No need to extend again - that would cause duplicates

        # --- Role assignment for image editing workflow ---
        base_uri_hint = self._normalize_uri((refine_payload or {}).get("image_url"))
        mask_uri_hint = self._normalize_uri((refine_payload or {}).get("mask_url"))

        if base_uri_hint or mask_uri_hint:
            for part in flattened_parts:
                candidate_uri = self._normalize_uri(extract_uri(part))
                if base_uri_hint and candidate_uri == base_uri_hint:
                    self._apply_role_to_part(part, "base")
                    _register_role(candidate_uri, "base")
                if mask_uri_hint and candidate_uri == mask_uri_hint:
                    self._apply_role_to_part(part, "mask")
                    _register_role(candidate_uri, "mask")

        # Assign default 'overlay' role to unassigned user uploads (not generated artifacts)
        for uri_value, parts_list in uri_to_parts.items():
            if assigned_roles.get(uri_value):
                continue
            
            file_name_from_uri = uri_value.split('/')[-1].split('?')[0].lower() if uri_value else ""
            is_generated_artifact = "generated_" in file_name_from_uri or "edit_" in file_name_from_uri
            
            if is_generated_artifact:
                continue  # Don't assign role to agent-generated artifacts
            
            for part in parts_list:
                self._apply_role_to_part(part, "overlay")
            assigned_roles[uri_value] = "overlay"

        # Apply all assigned roles to parts
        for part in flattened_parts:
            uri = self._normalize_uri(extract_uri(part))
            if uri and assigned_roles.get(uri):
                self._apply_role_to_part(part, assigned_roles[uri])

        return flattened_parts

    async def convert_part(self, part: Part, tool_context: Any, context_id: str = None):
        """
        Convert A2A Part objects into formats suitable for processing and agent delegation.
        
        KEY FIXES for FilePart handling:
        1. HTTP URIs: If a FilePart already has an HTTP/HTTPS URI (from blob storage),
           pass it through directly - don't re-download and re-process.
        2. Metadata preservation: video_metadata/image_metadata DataParts are returned
           as-is to preserve their structure for downstream processing.
        
        Part types:
        - TextPart: Pass through, detect [refine-image] markers for editing workflow
        - DataPart: Return data dict, preserve wrapper for metadata types
        - FilePart: Upload to blob storage if needed, or pass through if already uploaded
        """
        # Handle dicts from streaming or patched remote agents
        if isinstance(part, dict):
            if part.get('kind') == 'text' and 'text' in part:
                return part['text']
            if part.get('kind') == 'data' and 'data' in part:
                return part['data']
            return json.dumps(part)
        
        if not hasattr(part, 'root'):
            return str(part)
        
        kind = part.root.kind
        
        # --- TextPart ---
        if kind == 'text':
            text_content = part.root.text or ""

            # Check for [refine-image] markers (image editing workflow)
            refine_matches = list(re.finditer(r"\[refine-image\]\s+(https?://\S+)", text_content, flags=re.IGNORECASE))
            if refine_matches:
                mask_matches = list(re.finditer(r"\[refine-mask\]\s+(https?://\S+)", text_content, flags=re.IGNORECASE))
                image_url = refine_matches[-1].group(1)
                mask_url = mask_matches[-1].group(1) if mask_matches else None

                cleaned_text = re.sub(r"\[refine-image\]\s+https?://\S+", "", text_content, flags=re.IGNORECASE)
                cleaned_text = re.sub(r"\[refine-mask\]\s+https?://\S+", "", cleaned_text, flags=re.IGNORECASE)

                refine_data = {"kind": "refine-image", "image_url": image_url}
                if mask_url:
                    refine_data["mask_url"] = mask_url

                self._store_parts_in_session(tool_context, DataPart(data=refine_data))
                return cleaned_text.strip() or "Refine the previous image."

            return text_content
        
        # --- DataPart ---
        elif kind == 'data':
            data = part.root.data
            # Skip token_usage - already extracted elsewhere
            if isinstance(data, dict) and data.get('type') == 'token_usage':
                return None
            # Preserve wrapper for metadata types (video_metadata, image_metadata)
            if isinstance(data, dict) and data.get('type') in ('video_metadata', 'image_metadata'):
                return part  # Keep full structure for artifact processing
            return data
        
        # --- FilePart ---
        elif kind == 'file':
            file_id = part.root.file.name
            
            # KEY FIX: Pass through FileParts that already have HTTP URIs (blob storage)
            # These come from agents that uploaded files - no need to re-process
            file_uri = getattr(part.root.file, 'uri', None)
            if file_uri and str(file_uri).startswith(('http://', 'https://')):
                return part.root  # Return FilePart directly
            
            # Emit status for file processing
            if context_id:
                await self._emit_granular_agent_event(
                    "foundry-host-agent", f"processing file: {file_id}", context_id,
                    event_type="info", metadata={"file": file_id, "action": "processing"}
                )
            
            file_role_attr = (part.root.metadata or {}).get('role') if getattr(part.root, 'metadata', None) else None

            # Load file bytes from URI, inline bytes, or HTTP download
            file_bytes, load_error = self._load_file_bytes(part.root.file, context_id)
            if load_error:
                return f"Error: {load_error}"
            
            # Security: Validate file size (50MB limit)
            if len(file_bytes) > 50 * 1024 * 1024:
                return DataPart(data={'error': 'File too large', 'max_size': '50MB'})
            
            # Infer role if not explicitly set
            if not file_role_attr:
                file_role_attr = self._infer_file_role(None, file_id)
            
            is_mask_artifact = (file_role_attr == "mask")
            artifact_response = None

            artifact_info: dict[str, Any] = {
                'file_name': file_id,
                'file_bytes': file_bytes,
            }
            if file_role_attr:
                artifact_info['role'] = str(file_role_attr).lower()
            
            # Save artifact using A2A protocol
            if not hasattr(tool_context, 'save_artifact'):
                log_error(f"tool_context missing save_artifact method")
                return DataPart(data={'error': f'File processing unavailable for {file_id}'})
            
            try:
                # Create A2A file part structure
                a2a_file_part = {
                    'kind': 'file',
                    'file': {
                        'name': file_id,
                        'mimeType': getattr(part.root.file, 'mimeType', 'application/octet-stream'),
                        'data': file_bytes,
                        'force_blob': is_mask_artifact,
                        **({'role': str(file_role_attr)} if file_role_attr else {}),
                    }
                }
                
                artifact_response = await tool_context.save_artifact(file_id, a2a_file_part)
                tool_context.actions.skip_summarization = True
                tool_context.actions.escalate = True
                
                if isinstance(artifact_response, DataPart) and hasattr(artifact_response, 'data'):
                    if file_role_attr:
                        artifact_response.data['role'] = str(file_role_attr).lower()
                        meta = artifact_response.data.get('metadata') or {}
                        meta['role'] = str(file_role_attr).lower()
                        artifact_response.data['metadata'] = meta
                    
                    artifact_info.update({
                        'artifact_id': artifact_response.data.get('artifact-id'),
                        'artifact_uri': artifact_response.data.get('artifact-uri'),
                        'storage_type': artifact_response.data.get('storage-type')
                    })
            except Exception as e:
                log_error(f"save_artifact failed: {e}")
                artifact_response = DataPart(data={'error': f'Failed to process file: {str(e)}'})
            
            if is_mask_artifact:
                log_debug(f"Skipping document processing for mask artifact: {file_id}")
                
                # Get artifact URI from response or info
                artifact_uri = None
                if isinstance(artifact_response, DataPart) and hasattr(artifact_response, 'data'):
                    artifact_uri = artifact_response.data.get('artifact-uri')
                if not artifact_uri:
                    artifact_uri = artifact_info.get('artifact_uri') or getattr(part.root.file, 'uri', None)
                
                # Build mask parts using helper
                mime_type = getattr(part.root.file, 'mimeType', 'application/octet-stream')
                if isinstance(artifact_response, DataPart) and hasattr(artifact_response, 'data'):
                    mime_type = artifact_response.data.get('media-type', mime_type)
                
                mask_metadata_part, mask_file_part = self._build_mask_parts(
                    file_id=file_id,
                    mime_type=mime_type,
                    artifact_uri=artifact_uri,
                    artifact_info=artifact_info,
                    file_bytes=file_bytes,
                    artifact_response=artifact_response if isinstance(artifact_response, DataPart) else None,
                )

                # Store parts in session context for later access
                self._store_parts_in_session(tool_context, mask_metadata_part, mask_file_part)

                # Emit completion status event for mask file
                if context_id:
                    await self._emit_granular_agent_event(
                        "foundry-host-agent", f"file processed successfully: {file_id}", context_id,
                        event_type="info", metadata={"file": file_id, "action": "complete", "type": "mask"}
                    )
                
                return [mask_metadata_part, mask_file_part]

            # Process file content (text extraction for documents)
            session_id = get_tenant_from_context(context_id) if context_id else None
            try:
                processing_result = await a2a_document_processor.process_file_part(
                    part.root.file, 
                    artifact_info,
                    session_id=session_id
                )
                
                if processing_result and isinstance(processing_result, dict) and processing_result.get("success"):
                    content = processing_result.get("content", "")
                    if context_id:
                        await self._emit_granular_agent_event(
                            "foundry-host-agent", f"file processed successfully: {file_id}", context_id,
                            event_type="info", metadata={"file": file_id, "action": "complete", "type": "document"}
                        )
                    
                    if isinstance(artifact_response, DataPart) and hasattr(artifact_response, 'data'):
                        artifact_response.data['extracted_content'] = content
                        artifact_response.data['content_preview'] = content[:500] + "..." if len(content) > 500 else content
            except Exception as e:
                log_debug(f"Document processing error for {file_id}: {e}")
            
            # Return artifact with optional FilePart for remote agents
            if isinstance(artifact_response, DataPart):
                artifact_uri = artifact_response.data.get('artifact-uri')
                if artifact_uri:
                    file_part_for_remote = FilePart(
                        kind='file',
                        file=FileWithUri(
                            name=file_id,
                            mimeType=artifact_response.data.get('media-type', getattr(part.root.file, 'mimeType', 'application/octet-stream')),
                            uri=artifact_uri,
                            role=str(file_role_attr).lower() if file_role_attr else None,
                        ),
                    )
                    self._store_parts_in_session(tool_context, artifact_response, Part(root=file_part_for_remote))
                
                return artifact_response
            
            return DataPart(data={'error': f'File {file_id} processed without artifact metadata'})

    async def register_remote_agent(self, agent_address: str, agent_card: Optional[AgentCard] = None) -> bool:
        """Handle self-registration from remote agents.
        
        Args:
            agent_address: The URL/address of the remote agent
            agent_card: Optional pre-built agent card (if not provided, will retrieve from address)
            
        Returns:
            bool: True if registration successful, False otherwise
        """
        try:
            log_debug(f"Self-registration request from agent at: {agent_address}")
            
            if agent_card:
                # Use provided agent card
                log_debug(f"Using provided agent card: {agent_card.name}")
                self.register_agent_card(agent_card)
            else:
                # Retrieve agent card from address
                log_debug(f"Retrieving agent card from: {agent_address}")
                await self.retrieve_card(agent_address)
            
            log_success(f"Successfully registered remote agent from: {agent_address}")
            log_info(f"Total registered agents: {len(self.remote_agent_connections)}")
            log_debug(f"Agent names: {list(self.remote_agent_connections.keys())}")
            
            # Agent will appear in UI sidebar within 15 seconds via periodic sync
            
            return True
            
        except Exception as e:
            log_error(f"Failed to register remote agent from {agent_address}: {e}")
            import traceback
            log_error(f"Registration error traceback: {traceback.format_exc()}")
            return False

    async def unregister_remote_agent(self, agent_name: str) -> bool:
        """Handle unregistration of remote agents.
        
        Args:
            agent_name: The name of the agent to unregister
            
        Returns:
            bool: True if unregistration successful, False otherwise
        """
        try:
            log_debug(f"Unregistration request for agent: {agent_name}")
            
            # Check if agent exists
            if agent_name not in self.remote_agent_connections and agent_name not in self.cards:
                log_error(f"Agent {agent_name} not found in registry")
                return False
            
            # Remove from remote_agent_connections
            if agent_name in self.remote_agent_connections:
                del self.remote_agent_connections[agent_name]
                log_info(f"Removed {agent_name} from remote_agent_connections")
            
            # Remove from cards
            if agent_name in self.cards:
                del self.cards[agent_name]
                log_info(f"Removed {agent_name} from cards")
            
            # Update the agents list used in prompts
            self.agents = json.dumps(self.list_remote_agents(), indent=2)
            log_info(f"Updated agents list for prompts")
            
            log_success(f"Successfully unregistered agent: {agent_name}")
            log_info(f"Total registered agents: {len(self.remote_agent_connections)}")
            log_debug(f"Agent names: {list(self.remote_agent_connections.keys())}")
            
            return True
            
        except Exception as e:
            log_error(f"Failed to unregister agent {agent_name}: {e}")
            import traceback
            log_error(f"Unregistration error traceback: {traceback.format_exc()}")
            return False

    @staticmethod
    def create_with_shared_client(remote_agent_addresses: List[str], task_callback: Optional[TaskUpdateCallback] = None, enable_task_evaluation: bool = True, create_agent_at_startup: bool = False):
        """
        Factory method to create a FoundryHostAgent2 with a shared httpx.AsyncClient and optional task evaluation.
        
        Note: create_agent_at_startup defaults to False since Responses API is stateless and doesn't need agent creation.
        Uses extended timeout to support Azure Container Apps cold starts (scale-to-zero scenarios).
        """
        # Use extended timeout to support cold starts from scale-to-zero (up to 60s for container startup)
        timeout_config = httpx.Timeout(
            connect=60.0,  # Time to establish connection (important for cold starts)
            read=180.0,    # Time to read response (agent processing time)
            write=30.0,    # Time to send request
            pool=10.0      # Time to get connection from pool
        )
        shared_client = httpx.AsyncClient(timeout=timeout_config)
        return FoundryHostAgent2(remote_agent_addresses, http_client=shared_client, task_callback=task_callback, enable_task_evaluation=enable_task_evaluation, create_agent_at_startup=create_agent_at_startup)

    def set_host_manager(self, host_manager):
        """Set reference to the host manager for UI integration."""
        self._host_manager = host_manager

    async def cancel_workflow(self, context_id: str, reason: str = "Cancelled by user") -> Dict[str, Any]:
        """
        Cancel a running workflow for the given context.
        
        This implements a two-level cancellation strategy:
        1. Level 1 (Graceful): Set cancellation flag, checked between agent steps
        2. Level 2 (A2A Cancel): Send cancel request to any active remote agents
        
        State cleanup:
        - Clears current_plan (stops workflow execution)
        - Clears pending_input_agent (resets HITL state)
        - Preserves host_turn_history (maintains context for next message)
        
        Args:
            context_id: The conversation/session context to cancel
            reason: Human-readable cancellation reason
            
        Returns:
            Dict with cancellation status and details
        """
        log_info(f"[CANCEL] Cancelling workflow for context: {context_id}")
        
        # Set cancellation flag (Level 1 - graceful stop)
        self._cancellation_tokens[context_id] = True
        
        # Get session context to access active tasks and state
        session_ctx = self.session_contexts.get(context_id)
        cancelled_agents = []
        
        # Level 2: Cancel any active A2A tasks
        active_tasks = self._active_agent_tasks.get(context_id, {})
        for agent_name, task_id in active_tasks.items():
            try:
                log_info(f"[CANCEL] Sending cancel to agent: {agent_name}, task: {task_id}")
                conn = self.remote_agent_connections.get(agent_name)
                if conn:
                    # Call A2A cancel endpoint
                    await conn.cancel_task(task_id)
                    cancelled_agents.append(agent_name)
                    log_info(f"[CANCEL] Successfully cancelled {agent_name}")
            except Exception as e:
                log_error(f"[CANCEL] Failed to cancel {agent_name}: {e}")
        
        # Clear active tasks for this context
        self._active_agent_tasks.pop(context_id, None)
        
        # State cleanup
        if session_ctx:
            # Save plan snapshot before clearing so the cancellation handler
            # can persist it to chat history for reload reconstruction
            if session_ctx.current_plan:
                try:
                    self._cancelled_plan_snapshots[context_id] = session_ctx.current_plan.model_dump(mode='json', exclude_none=True)
                except Exception:
                    pass
            # Clear current plan (stops the workflow)
            session_ctx.current_plan = None
            # Clear HITL pending state
            session_ctx.pending_input_agent = None
            session_ctx.pending_input_task_id = None
            # Note: host_turn_history is preserved for context continuity
            log_info(f"[CANCEL] Cleared plan and HITL state for context: {context_id}")
        
        return {
            "status": "cancelled",
            "context_id": context_id,
            "reason": reason,
            "cancelled_agents": cancelled_agents,
            "message": f"Workflow cancelled. {len(cancelled_agents)} agent(s) notified."
        }
    
    def is_cancelled(self, context_id: str) -> bool:
        """Check if a workflow has been cancelled."""
        return self._cancellation_tokens.get(context_id, False)
    
    def clear_cancellation(self, context_id: str):
        """Clear cancellation and interrupt flags (called when new message starts)."""
        self._cancellation_tokens.pop(context_id, None)
        self._interrupt_instructions.pop(context_id, None)

    async def interrupt_workflow(self, context_id: str, instruction: str) -> Dict[str, Any]:
        """
        Queue an interrupt instruction for a running workflow.
        
        Unlike cancel, this does NOT stop execution. It queues a new instruction
        that will be picked up between workflow steps, causing the orchestrator
        to re-plan around the new user direction while preserving completed work.
        
        Args:
            context_id: The conversation/session context to interrupt
            instruction: The new user instruction to redirect the workflow
            
        Returns:
            Dict with interrupt acknowledgment
        """
        log_info(f"[INTERRUPT] Queuing interrupt for context: {context_id}")
        log_info(f"[INTERRUPT] New instruction: {instruction[:100]}...")
        
        self._interrupt_instructions[context_id] = instruction
        
        return {
            "status": "interrupt_queued",
            "context_id": context_id,
            "instruction": instruction,
            "message": "Interrupt queued. Will redirect after current agent completes."
        }
    
    def get_interrupt(self, context_id: str) -> Optional[str]:
        """Pop and return a queued interrupt instruction, or None if no interrupt is pending."""
        return self._interrupt_instructions.pop(context_id, None)

    def _add_status_message_to_conversation(self, status_text: str, contextId: str):
        """Add a status message directly to the conversation for immediate UI display."""
        # Use WebSocket streaming for real-time status updates
        asyncio.create_task(self._emit_granular_agent_event("foundry-host-agent", status_text, contextId, event_type="info"))

    # NOTE: _emit_status_event and _emit_text_chunk are now inherited from EventEmitters

    @staticmethod
    def _normalize_function_response_text(raw_response: Any) -> Any:
        """Flatten tool payload wrappers so the UI receives plain text.

        Azure AI Foundry sometimes echoes the tool output JSON (or Python repr)
        directly into the thread. When that happens the chat renders the raw
        dictionary instead of the underlying text. This helper converts those
        structures back into strings.
        """

        if not isinstance(raw_response, str):
            if isinstance(raw_response, dict) and raw_response.get("kind") == "function_response":
                payload = raw_response.get("response")
                if isinstance(payload, list):
                    return "\n\n".join(str(item) for item in payload)
                if isinstance(payload, str):
                    return payload
                return payload
            return raw_response

        candidate = raw_response.strip()
        if not candidate:
            return raw_response

        parsed = None

        # Try JSON first
        try:
            parsed = json.loads(candidate)
        except Exception:
            # Fall back to Python literal (single-quoted) repr
            try:
                parsed = ast.literal_eval(candidate)
            except Exception:
                parsed = None

        if isinstance(parsed, dict) and parsed.get("kind") == "function_response":
            payload = parsed.get("response")
            if isinstance(payload, list):
                return "\n\n".join(str(item) for item in payload)
            if isinstance(payload, str):
                return payload
            return payload

        if isinstance(parsed, list):
            return [str(item) for item in parsed]

        return raw_response

