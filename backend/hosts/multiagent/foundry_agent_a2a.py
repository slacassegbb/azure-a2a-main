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
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Iterable, Literal
import httpx
from dotenv import load_dotenv
from openai import AsyncAzureOpenAI

# OpenTelemetry for distributed tracing and monitoring
from opentelemetry import trace
from azure.monitor.opentelemetry import configure_azure_monitor

# Azure authentication - supports multiple credential types for flexibility
from azure.identity import DefaultAzureCredential, ChainedTokenCredential, AzureCliCredential, ManagedIdentityCredential, EnvironmentCredential, ClientSecretCredential

# Azure AI Foundry Agent Service - Official SDK for enterprise agents
from azure.ai.projects.aio import AIProjectClient
from azure.ai.agents.models import (
    AsyncFunctionTool,
    AsyncToolSet,
    MessageDeltaChunk,
    ThreadMessage,
    ThreadRun,
    RunStep,
    AgentStreamEvent,
    MessageRole,
    FilePurpose,
)

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
    WorkflowStepType,
    ParsedWorkflowStep,
    ParsedWorkflowGroup,
    ParsedWorkflow,
    TaskStateEnum,
    GoalStatus,
)
from .workflow_parser import WorkflowParser
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
from .event_emitters import EventEmitters
from .agent_registry import AgentRegistry
from .streaming_handlers import StreamingHandlers
from .memory_operations import MemoryOperations
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


# Note: SessionContext, AgentModeTask, AgentModePlan, NextStep, WorkflowStepType,
# ParsedWorkflowStep, ParsedWorkflowGroup, ParsedWorkflow, and WorkflowParser
# have been extracted to models.py and workflow_parser.py
# 
# Utility functions (get_context_id, get_message_id, get_task_id, normalize_env_bool,
# normalize_env_int) have been extracted to utils.py
#
# Event emitter methods (_emit_*) have been extracted to event_emitters.py
#
# Agent registry methods have been extracted to agent_registry.py


class FoundryHostAgent2(EventEmitters, AgentRegistry, StreamingHandlers, MemoryOperations):
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
            print("💡 TIP: If you see authentication errors, run 'python test_azure_auth.py' to diagnose")
            
            from azure.identity.aio import AzureCliCredential, DefaultAzureCredential, ManagedIdentityCredential
            
            # Detect if we're running in Azure Container Apps (managed identity)
            is_azure_container = os.environ.get('CONTAINER_APP_NAME') or os.environ.get('WEBSITE_INSTANCE_ID')
            
            if is_azure_container:
                # Use DefaultAzureCredential in Azure (will use managed identity)
                log_foundry_debug("🔵 Running in Azure Container Apps - using DefaultAzureCredential (Managed Identity)")
                self.credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
                log_foundry_debug("✅ Using DefaultAzureCredential for managed identity")
            else:
                # Use AzureCliCredential locally
                cli_credential = AzureCliCredential(process_timeout=5)
                self.credential = cli_credential
                log_foundry_debug("✅ Using AzureCliCredential for local development")
                    
        except Exception as e:
            log_foundry_debug(f"⚠️ Credential initialization failed: {e}")
            print("💡 DEBUG: Falling back to DefaultAzureCredential only")
            from azure.identity.aio import DefaultAzureCredential
            self.credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
            log_foundry_debug("✅ Using DefaultAzureCredential as fallback")
        
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
        
        # FOUNDRY AGENT SERVICE: Store thread IDs for conversation management
        self.thread_ids: Dict[str, str] = {}  # context_id -> thread_id
        
        # REMOVED: self.default_contextId = str(uuid.uuid4())
        # We NEVER want to use a UUID fallback - context_id must come from the request
        self.default_contextId = None
        self._agent_tasks: Dict[str, Optional[Task]] = {}
        self.agent_token_usage: Dict[str, dict] = {}  # Store token usage per agent
        self.host_token_usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}  # Host agent tokens
        
        self.enable_task_evaluation = enable_task_evaluation
        self._active_conversations: Dict[str, str] = {}
        self.max_retries = 2
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
        
        # Maximum characters for memory search summaries
        self.memory_summary_max_chars = max(
            200,
            normalize_env_int(os.environ.get("A2A_MEMORY_SUMMARY_MAX_CHARS"), 2000),
        )

        self._azure_blob_client = None
        self._init_azure_blob_client()
        self._clear_memory_on_startup()
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
    
    async def _ensure_project_client(self):
        """
        Initialize Azure AI Project Client and Agents Client if not already done.
        
        IMPORTANT: AIProjectClient must be created in the same event loop where it's used.
        If the event loop has changed, we need to recreate the client.
        """
        current_loop = asyncio.get_running_loop()
        
        # Check if we need to recreate the client for a new event loop
        if self.project_client is not None:
            # Check if the client's loop is still the current loop
            try:
                # If the client was created in a different loop, recreate it
                if hasattr(self, '_project_client_loop') and self._project_client_loop != current_loop:
                    log_foundry_debug("� Event loop changed, recreating AIProjectClient...")
                    # Close the old client if possible
                    if hasattr(self.project_client, 'close'):
                        try:
                            await self.project_client.close()
                        except:
                            pass
                    self.project_client = None
                    self.agents_client = None
                    self.credential = None
            except:
                pass
        
        # Recreate credential if needed
        if self.credential is None:
            from azure.identity.aio import AzureCliCredential, DefaultAzureCredential
            
            # Detect if we're running in Azure Container Apps (managed identity)
            is_azure_container = os.environ.get('CONTAINER_APP_NAME') or os.environ.get('WEBSITE_INSTANCE_ID')
            
            if is_azure_container:
                # Use DefaultAzureCredential in Azure (will use managed identity)
                self.credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
                log_foundry_debug("Recreated DefaultAzureCredential (Managed Identity) for new event loop")
            else:
                # Use AzureCliCredential locally
                self.credential = AzureCliCredential(process_timeout=5)
                log_foundry_debug("Recreated AzureCliCredential for new event loop")
        
        if self.project_client is None:
            log_foundry_debug("�🔧 Initializing AIProjectClient...")
            self.project_client = AIProjectClient(
                endpoint=self.endpoint,
                credential=self.credential,
            )
            self._project_client_loop = current_loop
            log_foundry_debug("✅ AIProjectClient initialized")
        
        if self.agents_client is None:
            log_foundry_debug("🔧 Getting AgentsClient from project...")
            self.agents_client = self.project_client.agents
            log_foundry_debug("✅ AgentsClient ready")
    
    async def _initialize_function_tools(self):
        """
        Initialize function tools for the agent.
        
        Returns AsyncFunctionTool configured with our agent coordination functions.
        """
        # Define the functions that the agent can call
        # AsyncFunctionTool expects a LIST of functions, not a dict
        user_functions = [
            self.list_remote_agents_sync,
            self.send_message_sync,
        ]
        
        # Create async function tool
        functions = AsyncFunctionTool(user_functions)
        
        # Create toolset and add functions
        toolset = AsyncToolSet()
        toolset.add(functions)
        
        # Enable automatic function call execution (synchronous method)
        self.agents_client.enable_auto_function_calls(toolset)
        
        return toolset

    # Note: set_session_agents, _find_agent_registry_path, _load_agent_registry,
    # _save_agent_registry, _agent_card_to_dict, _update_agent_registry have been
    # extracted to agent_registry.py

    async def _create_agent_at_startup_task(self):
        """Background task to create the agent at startup with proper error handling."""
        try:
            log_debug("🚀 Creating Azure AI Foundry agent at startup...")
            await self.create_agent()
            print("✅ Azure AI Foundry agent created successfully at startup!")
        except Exception as e:
            print(f"❌ Failed to create agent at startup: {e}")
            print("💡 Agent will be created lazily when first conversation occurs")
            # Don't raise - allow the application to continue and create agent lazily

    def _init_azure_blob_client(self):
        """Initialize Azure Blob Storage client if environment variables are configured."""
        try:
            self._azure_blob_client = None
            self._azure_blob_container = os.getenv('AZURE_BLOB_CONTAINER', 'a2a-files')
            azure_storage_connection_string = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
            azure_storage_account_name = os.getenv('AZURE_STORAGE_ACCOUNT_NAME')
            
            if azure_storage_connection_string:
                from azure.storage.blob import BlobServiceClient
                self._azure_blob_client = BlobServiceClient.from_connection_string(
                    azure_storage_connection_string,
                    api_version="2023-11-03",
                )
                log_debug("Azure Blob Storage initialized with connection string")
            elif azure_storage_account_name:
                from azure.storage.blob import BlobServiceClient
                account_url = f"https://{azure_storage_account_name}.blob.core.windows.net"
                self._azure_blob_client = BlobServiceClient(
                    account_url,
                    credential=self.credential,
                    api_version="2023-11-03",
                )
                log_debug(f"Azure Blob Storage initialized with managed identity: {account_url}")
            else:
                log_debug("Azure Blob Storage not configured - using local storage")
                self._azure_blob_container = None
            
            if self._azure_blob_client:
                log_debug(f"Target Azure Blob container: {self._azure_blob_container}")
                loop = asyncio.get_running_loop()
                loop.create_task(self._verify_blob_connection())

        except ImportError as e:
            log_debug(f"Azure Storage SDK not installed - using local storage: {e}")
        except Exception as e:
            log_error(f"Failed to initialize Azure Blob Storage: {e}")
            self._azure_blob_client = None

    async def _verify_blob_connection(self):
        """Log diagnostics about the configured Azure Blob container."""
        if not self._azure_blob_client or not self._azure_blob_container:
            print("ℹ️ Azure Blob verification skipped: client or container not set")
            return

        try:
            print("🔍 Azure Blob check: resolving container client...")
            container_client = self._azure_blob_client.get_container_client(self._azure_blob_container)

            print("🔍 Azure Blob check: ensuring container exists...")
            try:
                await asyncio.to_thread(container_client.create_container)
                print(f"✅ Azure Blob container '{self._azure_blob_container}' created")
            except Exception as create_err:
                from azure.core.exceptions import ResourceExistsError
                if isinstance(create_err, ResourceExistsError):
                    print(f"ℹ️ Azure Blob container '{self._azure_blob_container}' already exists")
                else:
                    raise

            print("🔍 Azure Blob check: listing blobs (up to 5 entries)...")
            blob_count = 0
            for blob in container_client.list_blobs(name_starts_with="a2a-artifacts/"):
                print(f"   • Existing blob: {blob.name} (size={blob.size})")
                blob_count += 1
                if blob_count >= 5:
                    print("   • ... additional blobs omitted ...")
                    break
            if blob_count == 0:
                print("   • No blobs found yet in this container")

            print("🔍 Azure Blob check: uploading connectivity probe...")
            probe_blob_name = f"a2a-artifacts/_connectivity_probe_.txt"
            probe_client = container_client.get_blob_client(probe_blob_name)
            probe_payload = f"connection verified at {datetime.now(timezone.utc).isoformat()}"
            await asyncio.to_thread(probe_client.upload_blob, probe_payload, overwrite=True)
            print(f"✅ Azure Blob probe uploaded: {probe_blob_name}")

        except Exception as e:
            print(f"❌ Azure Blob verification failed: {e}")
            import traceback
            print(traceback.format_exc())

    def _clear_memory_on_startup(self):
        """Clear memory index automatically on startup for clean testing"""
        print(f"🧹 Auto-clearing memory index on startup...")
        try:
            success = a2a_memory_service.clear_all_interactions()
            if success:
                print(f"✅ Memory index auto-cleared successfully")
            else:
                print(f"⚠️ Memory index auto-clear had no effect (may be empty)")
        except Exception as e:
            print(f"⚠️ Error auto-clearing memory index: {e}")
            print(f"Continuing with startup...")

    async def _get_auth_headers(self) -> Dict[str, str]:
        """
        Obtain Azure authentication headers with token caching for performance.
        
        Implements:
        - Token caching with 5-minute expiry buffer to avoid auth failures
        - Automatic retry logic (3 attempts) with exponential backoff
        - Timeout protection (8 seconds) to prevent hanging
        - Helpful error messages for common authentication issues
        
        Returns:
            Dict containing Authorization and Content-Type headers
        """
        log_foundry_debug(f"Getting authentication token with timeout handling and caching")
        
        # Return cached token if still valid (with 5-minute safety buffer)
        if self._cached_token and self._token_expiry:
            from datetime import datetime as dt, timedelta
            # Add 5 minute buffer before expiry
            buffer_time = dt.now() + timedelta(minutes=5)
            if self._token_expiry > buffer_time:
                log_foundry_debug(f"✅ Using cached token (expires: {self._token_expiry})")
                return {
                    "Authorization": f"Bearer {self._cached_token}",
                    "Content-Type": "application/json"
                }
        
        # Token acquisition with retry logic for reliability
        max_retries = 3
        for attempt in range(max_retries):
            try:
                log_foundry_debug(f"Token attempt {attempt + 1}/{max_retries}...")
                
                # Get token with proper async handling
                import asyncio
                import inspect
                
                # Check if get_token is async or sync
                get_token_method = self.credential.get_token
                
                if inspect.iscoroutinefunction(get_token_method):
                    # Async credential - await directly with timeout
                    log_foundry_debug("Using async credential.get_token()")
                    token = await asyncio.wait_for(
                        self.credential.get_token("https://ai.azure.com/.default"),
                        timeout=8.0
                    )
                else:
                    # Sync credential - run in executor to avoid blocking
                    log_foundry_debug("Using sync credential.get_token() in executor")
                    async def get_token_async():
                        loop = asyncio.get_event_loop()
                        return await loop.run_in_executor(
                            None, 
                            lambda: self.credential.get_token("https://ai.azure.com/.default")
                        )
                    
                    token = await asyncio.wait_for(get_token_async(), timeout=8.0)
                
                # Cache the token
                self._cached_token = token.token
                from datetime import datetime as dt
                self._token_expiry = dt.fromtimestamp(token.expires_on)
                
                headers = {
                    "Authorization": f"Bearer {token.token}",
                    "Content-Type": "application/json"
                }
                log_foundry_debug(f"✅ Authentication headers obtained successfully (expires: {self._token_expiry})")
                return headers
                
            except asyncio.TimeoutError:
                error_name = "TimeoutError"
                error_msg = "Authentication request timed out after 8 seconds"
                log_foundry_debug(f"⚠️ Auth attempt {attempt + 1} timed out after 8 seconds")
                
            except Exception as e:
                error_name = type(e).__name__
                error_msg = str(e)
                
                if attempt < max_retries - 1:
                    log_foundry_debug(f"⚠️ Auth attempt {attempt + 1} failed ({error_name}), retrying in 3 seconds...")
                    log_foundry_debug(f"⚠️ Error details: {error_msg}")
                    await asyncio.sleep(3)  # Wait 3 seconds before retry
                    continue
                else:
                    log_foundry_debug(f"❌ Failed to get authentication token after {max_retries} attempts: {error_name}: {e}")
                    
                    # Provide specific help based on error type
                    if "CredentialUnavailableError" in error_name and "Azure CLI" in error_msg:
                        print("💡 DEBUG: Azure CLI authentication failed. Try:")
                        print("   1. az login --tenant <your-tenant-id>")
                        print("   2. az account set --subscription <your-subscription-id>")
                        print("   3. Set environment variables for service principal auth")
                    elif "TimeoutError" in error_name or "timed out" in error_msg.lower():
                        print("💡 DEBUG: Authentication timed out. Try:")
                        print("   1. Check your network connection")
                        print("   2. Run 'az login' to refresh your session")
                        print("   3. Consider using service principal authentication for better reliability")
                    elif "ChainedTokenCredential" in error_msg:
                        print("💡 DEBUG: All credential types failed. Options:")
                        print("   1. Set environment variables: AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET")
                        print("   2. Run 'az login' and try again")
                        print("   3. Run from Azure environment (VM, Container App, etc.)")
                    
                    raise

    def _clear_cached_token(self):
        """Clear cached authentication token to force refresh on next request"""
        log_foundry_debug(f"🔄 Clearing cached authentication token")
        self._cached_token = None
        self._token_expiry = None

    async def refresh_azure_cli_session(self):
        """Helper method to refresh Azure CLI session when authentication fails"""
        try:
            log_foundry_debug(f"🔄 Attempting to refresh Azure CLI session...")
            import subprocess
            import asyncio
            
            # Run az account get-access-token to refresh session
            process = await asyncio.create_subprocess_exec(
                'az', 'account', 'get-access-token', '--output', 'json',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10.0)
            
            if process.returncode == 0:
                log_foundry_debug(f"✅ Azure CLI session refreshed successfully")
                self._clear_cached_token()  # Clear cache to use fresh token
                return True
            else:
                log_foundry_debug(f"❌ Azure CLI refresh failed: {stderr.decode()}")
                return False
                
        except asyncio.TimeoutError:
            log_foundry_debug(f"❌ Azure CLI refresh timed out")
            return False
        except Exception as e:
            log_foundry_debug(f"❌ Error refreshing Azure CLI session: {e}")
            return False

    def _format_tools_for_responses_api(self) -> List[Dict[str, Any]]:
        """
        Format agent tools for Responses API.
        
        Returns tools in the Responses API format for function calling.
        Uses _get_tools() to get the tool definitions.
        
        Returns:
            List of tool definitions in Responses API format
        """
        # Use _get_tools() which has the correct tool definitions
        tools = self._get_tools()
        print(f"🔧 [TOOLS] _format_tools_for_responses_api returning {len(tools)} tools")
        for tool in tools:
            print(f"  • Tool: {tool.get('name', 'unknown')}")
        return tools

    def _get_openai_endpoint(self) -> str:
        """
        Convert AI Foundry endpoint to OpenAI /v1/ endpoint format.
        
        Converts from: https://RESOURCE.services.ai.azure.com/subscriptions/.../
        To: https://RESOURCE.openai.azure.com/openai/v1/
        """
        endpoint = self.endpoint
        
        if "services.ai.azure.com" in endpoint:
            # Extract resource name from AI Foundry endpoint
            # Example: https://simonfoundry.services.ai.azure.com/...
            parts = endpoint.split("//")[1].split(".")[0]
            openai_endpoint = f"https://{parts}.openai.azure.com/openai/v1/"
            log_foundry_debug(f"Converted endpoint: {endpoint} -> {openai_endpoint}")
            return openai_endpoint
        else:
            # Already in OpenAI format or needs manual /openai/v1/ suffix
            openai_endpoint = endpoint if endpoint.endswith("/openai/v1/") else f"{endpoint.rstrip('/')}/openai/v1/"
            log_foundry_debug(f"Using endpoint as-is: {openai_endpoint}")
            return openai_endpoint

    def _get_openai_client(self):
        """
        Get client configured for Responses API via direct HTTP calls.
        
        Note: The Responses API is accessed via direct HTTP to /openai/v1/responses,
        not through the OpenAI SDK's standard client interface.
        
        This method is kept for compatibility but the actual HTTP calls
        are made directly in _create_response_with_streaming.
        """
        # This is now a placeholder - actual HTTP calls are made directly
        return None

    def _get_client(self):
        """Legacy method - now throws error to identify remaining SDK usage"""
        raise NotImplementedError(
            "❌ _get_client() is no longer supported! "
            "The foundry_agent_a2a.py now uses HTTP API calls instead of the azure.ai.agents SDK. "
            "This error indicates that some code is still trying to use the old SDK approach. "
            "Please update the calling code to use HTTP-based methods."
        )

    async def _create_response_with_streaming(
        self,
        user_message: str,
        context_id: str,
        session_context: SessionContext,
        tools: List[Dict[str, Any]],
        instructions: str,
        event_logger=None
    ) -> Dict[str, Any]:
        """
        Create a response using Azure AI Foundry Agent Service with streaming.
        
        Returns:
            Dict with keys: id, text, tool_calls, status, usage
        """
        try:
            await self._ensure_project_client()
            if not self.agent:
                await self.create_agent()
            
            # Get or create thread for this context
            if context_id not in self.thread_ids:
                thread = await self.agents_client.threads.create()
                self.thread_ids[context_id] = thread.id
            
            thread_id = self.thread_ids[context_id]
            
            # Cancel any active runs before creating new message
            try:
                runs = self.agents_client.runs.list(thread_id=thread_id)
                async for run in runs:
                    if run.status in ["in_progress", "requires_action", "queued"]:
                        try:
                            await self.agents_client.runs.cancel(thread_id=thread_id, run_id=run.id)
                        except Exception:
                            pass
            except Exception:
                pass
            
            # Create message in thread
            message = await self.agents_client.messages.create(
                thread_id=thread_id,
                role=MessageRole.USER,
                content=user_message
            )
            
            # Stream the run
            full_text = ""
            run_id = None
            status = "completed"
            tool_calls_to_execute = []
            
            stream = await self.agents_client.runs.stream(
                thread_id=thread_id,
                agent_id=self.agent_id,
                tool_choice="required"
            )
            
            async with stream as event_handler:
                async for event in event_handler:
                    if hasattr(event, 'event') and hasattr(event, 'data'):
                        event_type = event.event
                        event_data = event.data
                    elif isinstance(event, tuple):
                        event_type, event_data, *_ = event
                    else:
                        event_data = event
                        event_type = type(event).__name__
                    
                    if isinstance(event_data, MessageDeltaChunk):
                        chunk = event_data.text
                        if chunk:
                            full_text += chunk
                            await self._emit_text_chunk(chunk, context_id)
                    
                    elif isinstance(event_data, ThreadRun):
                        run_id = event_data.id
                        status = event_data.status
                        status_str = str(status).lower() if status else ""
                        if "requires_action" in status_str and hasattr(event_data, 'required_action'):
                            required_action = event_data.required_action
                            if required_action and hasattr(required_action, 'submit_tool_outputs'):
                                tool_calls_to_execute = required_action.submit_tool_outputs.tool_calls
                    
                    elif event_type == AgentStreamEvent.ERROR:
                        raise Exception(f"Streaming error: {event_data}")
                    
                    elif event_type == AgentStreamEvent.DONE:
                        break
            
            # MULTI-TURN TOOL EXECUTION LOOP
            max_tool_iterations = 30
            tool_iteration = 0
            
            def status_requires_action(s):
                return s and "requires_action" in str(s).lower()
            
            while status_requires_action(status) and tool_calls_to_execute and tool_iteration < max_tool_iterations:
                tool_iteration += 1
                
                # Emit tool call events for UI visibility
                for tool_call in tool_calls_to_execute:
                    asyncio.create_task(self._emit_granular_agent_event(
                        "foundry-host-agent", f"🛠️ Calling: {tool_call.function.name}", context_id
                    ))
                
                # Separate send_message calls for parallel execution
                send_message_calls = [tc for tc in tool_calls_to_execute if tc.function.name == "send_message_sync"]
                other_calls = [tc for tc in tool_calls_to_execute if tc.function.name != "send_message_sync"]
                tool_outputs = []
                
                # Execute send_message calls in PARALLEL if there are multiple
                if len(send_message_calls) > 1:
                    async def execute_send_message(tool_call):
                        """Execute a single send_message call and return result"""
                        try:
                            arguments = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                            agent_name = arguments.get("agent_name")
                            result = await self.send_message_sync(
                                agent_name=agent_name,
                                message=arguments.get("message")
                            )
                            result_str = self._format_agent_response_for_model(result, agent_name)
                            return {"tool_call_id": tool_call.id, "output": result_str}
                        except Exception as e:
                            log_error(f"send_message_sync error: {e}")
                            return {"tool_call_id": tool_call.id, "output": json.dumps({"error": str(e)})}
                    
                    parallel_results = await asyncio.gather(
                        *[execute_send_message(tc) for tc in send_message_calls],
                        return_exceptions=True
                    )
                    
                    for idx, result in enumerate(parallel_results):
                        if isinstance(result, Exception):
                            if idx < len(send_message_calls):
                                tool_outputs.append({
                                    "tool_call_id": send_message_calls[idx].id,
                                    "output": json.dumps({"error": str(result)})
                                })
                        else:
                            tool_outputs.append(result)
                
                elif len(send_message_calls) == 1:
                    tool_call = send_message_calls[0]
                    try:
                        arguments = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                        agent_name = arguments.get("agent_name")
                        result = await self.send_message_sync(
                            agent_name=agent_name,
                            message=arguments.get("message")
                        )
                        result_str = self._format_agent_response_for_model(result, agent_name)
                        tool_outputs.append({"tool_call_id": tool_call.id, "output": result_str})
                    except Exception as e:
                        log_error(f"send_message_sync error: {e}")
                        tool_outputs.append({"tool_call_id": tool_call.id, "output": json.dumps({"error": str(e)})})
                
                # Execute other (non-send_message) tool calls sequentially
                for tool_call in other_calls:
                    function_name = tool_call.function.name
                    try:
                        if function_name == "list_remote_agents_sync":
                            result = self.list_remote_agents_sync()
                        else:
                            result = {"error": f"Unknown function: {function_name}"}
                        
                        # Convert result to JSON string
                        if hasattr(result, 'model_dump'):
                            result_str = json.dumps(result.model_dump(mode='json'))
                        elif isinstance(result, str):
                            result_str = result
                        else:
                            result_str = json.dumps(result)
                        
                        tool_outputs.append({"tool_call_id": tool_call.id, "output": result_str})
                    except Exception as e:
                        log_error(f"Tool {function_name} error: {e}")
                        tool_outputs.append({"tool_call_id": tool_call.id, "output": json.dumps({"error": str(e)})})
                
                # Submit tool outputs and continue streaming
                try:
                    stream = await self.agents_client.runs.submit_tool_outputs_stream(
                        thread_id=thread_id,
                        run_id=run_id,
                        tool_outputs=tool_outputs
                    )
                except TypeError as e:
                    # If it requires event_handler, provide one
                    if "event_handler" in str(e):
                        from azure.ai.agents.models import AsyncAgentEventHandler
                        
                        class ResponseCapturingHandler(AsyncAgentEventHandler):
                            def __init__(self):
                                super().__init__()
                                self.response_text = ""
                                self.final_status = None
                                self.tool_calls = []
                            
                            async def on_message_delta(self, delta):
                                if hasattr(delta, 'text') and delta.text:
                                    self.response_text += delta.text
                                    await self._emit_text_chunk(delta.text, context_id)
                            
                            async def on_thread_run(self, run):
                                self.final_status = run.status
                                status_str = str(run.status).lower() if run.status else ""
                                if "requires_action" in status_str and hasattr(run, 'required_action'):
                                    required_action = run.required_action
                                    if required_action and hasattr(required_action, 'submit_tool_outputs'):
                                        self.tool_calls = required_action.submit_tool_outputs.tool_calls or []
                        
                        handler = ResponseCapturingHandler()
                        handler._emit_text_chunk = self._emit_text_chunk
                        
                        result = await self.agents_client.runs.submit_tool_outputs_stream(
                            thread_id=thread_id,
                            run_id=run_id,
                            tool_outputs=tool_outputs,
                            event_handler=handler
                        )
                        
                        await handler.until_done()
                        
                        full_text += handler.response_text
                        if handler.final_status:
                            status = handler.final_status
                        
                        tool_calls_to_execute = handler.tool_calls if handler.tool_calls else []
                        stream = None
                    else:
                        raise
                
                # If we have a stream, process it
                if stream is not None:
                    tool_calls_to_execute = []
                    
                    async with stream as event_handler:
                        async for event in event_handler:
                            if hasattr(event, 'event') and hasattr(event, 'data'):
                                event_type = event.event
                                event_data = event.data
                            elif isinstance(event, tuple):
                                event_type, event_data, *_ = event
                            else:
                                event_data = event
                                event_type = type(event).__name__
                            
                            if isinstance(event_data, MessageDeltaChunk):
                                chunk = event_data.text
                                if chunk:
                                    full_text += chunk
                                    await self._emit_text_chunk(chunk, context_id)
                            
                            elif isinstance(event_data, ThreadRun):
                                run_id = event_data.id
                                status = event_data.status
                                
                                status_str = str(status).lower() if status else ""
                                if "requires_action" in status_str and hasattr(event_data, 'required_action'):
                                    required_action = event_data.required_action
                                    if required_action and hasattr(required_action, 'submit_tool_outputs'):
                                        tool_calls_to_execute = required_action.submit_tool_outputs.tool_calls
                            
                            elif event_type == AgentStreamEvent.DONE:
                                break
            
            return {
                "id": run_id,
                "text": full_text,
                "tool_calls": [],
                "status": status,
                "usage": None
            }
            
        except Exception as e:
            log_error(f"Error in _create_response_with_streaming: {e}")
            raise

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
                
                task = self.send_message(
                    agent_name=arguments["agent_name"],
                    message=arguments["message"],
                    tool_context=tool_context,
                    suppress_streaming=True
                )
                tasks.append((tool_call, task))
            
            # Execute in parallel
            results = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)
            
            for (tool_call, _), result in zip(tasks, results):
                if isinstance(result, Exception):
                    output = {"error": str(result)}
                else:
                    output = result
                
                tool_outputs.append({
                    "type": "function_call_output",
                    "call_id": tool_call["id"],
                    "output": json.dumps(output)
                })
        else:
            # Sequential execution for agent mode
            for tool_call in send_message_calls:
                arguments = json.loads(tool_call["function"]["arguments"]) if isinstance(tool_call["function"]["arguments"], str) else tool_call["function"]["arguments"]
                
                tool_context = type('obj', (object,), {'state': session_context})()
                
                try:
                    output = await self.send_message(
                        agent_name=arguments["agent_name"],
                        message=arguments["message"],
                        tool_context=tool_context,
                        suppress_streaming=True
                    )
                except Exception as e:
                    output = {"error": str(e)}
                
                tool_outputs.append({
                    "type": "function_call_output",
                    "call_id": tool_call["id"],
                    "output": json.dumps(output)
                })
        
        # Execute other tool calls sequentially
        for tool_call in other_calls:
            function_name = tool_call["function"]["name"]
            arguments = json.loads(tool_call["function"]["arguments"]) if isinstance(tool_call["function"]["arguments"], str) else tool_call["function"]["arguments"]
            
            await self._emit_tool_call_event("foundry-host-agent", function_name, arguments, context_id)
            
            if function_name == "list_remote_agents":
                output = self.list_remote_agents()
            else:
                output = {"error": f"Unknown function: {function_name}"}
            
            tool_outputs.append({
                "type": "function_call_output",
                "call_id": tool_call["id"],
                "output": json.dumps(output)
            })
        
        log_foundry_debug(f"Tool execution complete - {len(tool_outputs)} outputs")
        return tool_outputs

    # Note: init_remote_agent_addresses, retrieve_card, register_agent_card
    # have been extracted to agent_registry.py

    async def create_agent(self) -> Any:
        """
        Create an agent using Azure AI Foundry Agent Service.
        
        This creates a persistent agent that:
        - Appears in Azure AI Foundry portal
        - Has full Application Insights telemetry
        - Supports streaming responses
        - Has managed conversation state (threads)
        
        Returns:
            Agent object from Azure AI Foundry
        """
        if self.agent:
            log_foundry_debug(f"Agent already exists, reusing agent ID: {self.agent_id}")
            return self.agent
        
        log_foundry_debug(f"Creating new agent with Azure AI Foundry Agent Service...")
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
            
            model_name = os.environ["AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME"]
            instructions = self.root_instruction('foundry-host-agent')
            
            log_foundry_debug(f"Agent parameters:")
            print(f"  - model: {model_name}")
            print(f"  - name: foundry-host-agent")
            print(f"  - instructions length: {len(instructions)}")
            
            # Initialize function tools
            toolset = await self._initialize_function_tools()
            
            log_foundry_debug(f"  - tools: initialized with AsyncFunctionTool")
            
            # Create agent using Foundry Agent Service SDK
            log_foundry_debug("Calling agents_client.create_agent()...")
            self.agent = await self.agents_client.create_agent(
                model=model_name,
                name="foundry-host-agent",
                instructions=instructions,
                toolset=toolset,
            )
            
            self.agent_id = self.agent.id
            log_foundry_debug(f"✅ Agent created successfully! ID: {self.agent_id}")
            
            # Debug: Log what tools the agent has
            if hasattr(self.agent, 'tools'):
                print(f"🔧 Agent tools: {self.agent.tools}")
            else:
                print(f"🔧 Agent object attributes: {[a for a in dir(self.agent) if not a.startswith('_')]}")
            
            logger.info(f"Created Foundry Host agent: {self.agent_id}")
            print(f"🎉 Agent visible in Azure AI Foundry portal: {self.agent_id}")
            
            return self.agent
            
        except Exception as e:
            log_foundry_debug(f"❌ Exception in create_agent(): {type(e).__name__}: {e}")
            log_foundry_debug(f"❌ Full traceback:")
            import traceback
            traceback.print_exc()
            raise
    
    # Note: list_remote_agents_sync has been extracted to agent_registry.py
    
    async def send_message_sync(self, agent_name: str, message: str):
        """
        Async wrapper for send_message - for use with AsyncFunctionTool.
        
        Azure AI Agents SDK's AsyncFunctionTool.execute() checks if the function
        is async (using inspect.iscoroutinefunction) and awaits it if needed.
        Since send_message is async, this wrapper must also be async.
        """
        print(f"\n🔥🔥🔥 [SEND_MESSAGE_SYNC] CALLED by Azure SDK!")
        print(f"🔥 agent_name: {agent_name}")
        print(f"🔥 message: {message[:100]}...")
        
        # Use the current host context ID - NO FALLBACK to UUID!
        context_id_to_use = getattr(self, '_current_host_context_id', None)
        
        log_debug(f"🔍 [send_message_sync] _current_host_context_id: {context_id_to_use}")
        log_debug(f"🔍 [send_message_sync] session_contexts keys: {list(self.session_contexts.keys())}")
        
        # CRITICAL: If we don't have the current context_id, this is a bug
        if not context_id_to_use:
            raise ValueError(f"send_message_sync called but _current_host_context_id not set! This should be set by run_conversation_with_parts. Available keys: {list(self.session_contexts.keys())}")
        
        # Get existing session context or create new one with proper contextId
        session_ctx = self.session_contexts.get(context_id_to_use)
        if not session_ctx:
            log_debug(f"🔍 [send_message_sync] SessionContext NOT FOUND, creating new one with contextId={context_id_to_use}")
            session_ctx = SessionContext(
                agent_mode=False,
                host_task=None,
                plan=None,
                contextId=context_id_to_use  # CRITICAL: Pass contextId to prevent UUID generation
            )
        else:
            log_debug(f"🔍 [send_message_sync] SessionContext FOUND with contextId={session_ctx.contextId}")
        
        # Create a task context mock
        tool_context = type('obj', (object,), {
            'state': session_ctx
        })()
        
        # Call the async send_message - SDK will await it
        # NOTE: suppress_streaming=False allows status updates to flow to sidebar
        return await self.send_message(
            agent_name=agent_name,
            message=message,
            tool_context=tool_context,
            suppress_streaming=False  # Enable streaming for sidebar status updates!
        )

    def _format_agent_response_for_model(self, response_parts: list, agent_name: str) -> str:
        """
        Format the response parts from send_message into clean text for the model.
        
        The model expects readable text as tool output, not complex nested JSON.
        This extracts text content from response_parts and formats it cleanly.
        
        Args:
            response_parts: List of Part objects from send_message
            agent_name: Name of the agent that responded
            
        Returns:
            Clean text string suitable for tool output
        """
        import json
        
        if not response_parts:
            return json.dumps({
                "agent": agent_name,
                "status": "completed",
                "response": "Agent completed the task but returned no text content."
            })
        
        text_parts = []
        file_parts = []
        data_parts = []
        
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
                    else:
                        # Data part
                        data_parts.append(part)
                
                # Check for file content
                if hasattr(part_root, 'file') or hasattr(part, 'file'):
                    file_obj = getattr(part_root, 'file', None) or getattr(part, 'file', None)
                    if file_obj:
                        file_name = getattr(file_obj, 'name', 'unknown_file')
                        file_parts.append(file_name)
                        
            except Exception as e:
                log_foundry_debug(f"Error processing part: {e}")
                # Try to convert to string as fallback
                try:
                    if hasattr(part, 'model_dump'):
                        text_parts.append(str(part.model_dump(mode='json')))
                    else:
                        text_parts.append(str(part))
                except:
                    pass
        
        # Build clean response
        response_text = "\n\n".join(text_parts) if text_parts else ""
        
        result = {
            "agent": agent_name,
            "status": "completed",
            "response": response_text if response_text else "Task completed successfully."
        }
        
        if file_parts:
            result["files_generated"] = file_parts
            
        if data_parts:
            result["additional_data"] = len(data_parts)
        
        return json.dumps(result, ensure_ascii=False)

    async def _update_agent_instructions(self):
        """Update the agent's instructions with the current agent list"""
        if not self.agent:
            print(f"⚠️ No agent exists to update")
            return
            
        try:
            print(f"🔄 Updating agent instructions with {len(self.cards)} registered agents...")
            
            headers = await self._get_auth_headers()
            endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
            agent_id = self.agent['id']
            api_url = f"{endpoint}/assistants/{agent_id}"
            
            # Get updated instructions with current agent list
            updated_instructions = self.root_instruction('foundry-host-agent')
            
            # Prepare the update payload
            payload = {
                "instructions": updated_instructions
            }
            
            # Make the HTTP request to update the assistant
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    api_url,
                    headers=headers,
                    json=payload,
                    params={"api-version": "2025-05-15-preview"},
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    print(f"✅ Agent instructions updated successfully!")
                    print(f"   Agent now knows about: {', '.join(self.cards.keys())}")
                else:
                    print(f"❌ Failed to update agent instructions: {response.status_code} - {response.text}")
                    
        except Exception as e:
            print(f"❌ Error updating agent instructions: {e}")
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
                "description": "Send a message to a remote agent.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_name": {"type": "string", "description": "The name of the agent to send the task to."},
                        "message": {"type": "string", "description": "The message to send to the agent."},
                    },
                    "required": ["agent_name", "message"],
                },
            },
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
            print(f"🤖 [Agent Mode] Calling Azure OpenAI for structured output...")
            await self._emit_status_event("Planning next task with AI...", context_id)
            
            # Extract base endpoint from AI Foundry project endpoint
            endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
            model_name = os.environ["AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME"]
            
            # Extract base endpoint from project endpoint
            base_endpoint = endpoint.split('/api/projects')[0] if '/api/projects' in endpoint else endpoint
            print(f"🤖 [Agent Mode] Azure endpoint: {base_endpoint}")
            print(f"🤖 [Agent Mode] Model deployment: {model_name}")
            
            # Get Azure credential token
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            credential = DefaultAzureCredential()
            token_provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")
            
            # Create Azure OpenAI client with token auth
            client = AsyncAzureOpenAI(
                azure_endpoint=base_endpoint,
                azure_ad_token_provider=token_provider,
                api_version="2024-08-01-preview"  # Version that supports structured outputs
            )
            
            print(f"🤖 [Agent Mode] Making structured output request with OpenAI SDK...")
            
            # Use OpenAI SDK's parse method for structured outputs
            completion = await client.beta.chat.completions.parse(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format=response_model,
                temperature=0.7,
                max_tokens=2000
            )
            
            parsed = completion.choices[0].message.parsed
            print(f"🤖 [Agent Mode] Got structured response: {parsed.model_dump_json()[:200]}...")
            
            # Extract token usage from orchestration call
            if hasattr(completion, 'usage') and completion.usage:
                self.host_token_usage["prompt_tokens"] += completion.usage.prompt_tokens or 0
                self.host_token_usage["completion_tokens"] += completion.usage.completion_tokens or 0
                self.host_token_usage["total_tokens"] += completion.usage.total_tokens or 0
                print(f"🎟️ [Host Agent] Orchestration tokens: +{completion.usage.total_tokens} (total: {self.host_token_usage['total_tokens']})")
            
            return parsed
                    
        except Exception as e:
            log_error(f"[Agent Mode] Error calling Azure OpenAI: {e}")
            import traceback
            traceback.print_exc()
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
            endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
            model_name = os.environ["AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME"]
            base_endpoint = endpoint.split('/api/projects')[0] if '/api/projects' in endpoint else endpoint
            
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
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
                max_tokens=100
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

    async def _execute_parsed_workflow(
        self,
        parsed_workflow: ParsedWorkflow,
        user_message: str,
        context_id: str,
        session_context: SessionContext
    ) -> List[str]:
        """
        Execute a pre-parsed workflow with support for parallel step groups.
        
        This method uses the Pydantic AgentModePlan for proper state management,
        retry logic, HITL support, and artifact tracking - just like the dynamic
        orchestration loop, but with a pre-defined workflow structure.
        
        Parallel groups (e.g., steps 2a, 2b) are executed concurrently using 
        asyncio.gather() while still creating proper AgentModeTask objects for
        state persistence.
        
        Args:
            parsed_workflow: The parsed workflow with sequential and parallel groups
            user_message: Original user message for context
            context_id: Conversation identifier
            session_context: Session state
            
        Returns:
            List of output strings from all executed steps
        """
        log_info(f"🚀 [Workflow] Executing parsed workflow with {len(parsed_workflow.groups)} groups")
        print(f"📋 [Workflow] Parsed structure:\n{parsed_workflow}")
        
        # Use the class method for extracting clean text from A2A response objects
        extract_text_from_response = self._extract_text_from_response
        
        # Initialize Pydantic plan for state tracking (just like dynamic orchestration)
        plan = AgentModePlan(goal=user_message, goal_status="incomplete")
        all_task_outputs = []
        
        # Log initial plan
        print(f"\n{'='*80}")
        log_debug(f"📋 [Parsed Workflow] INITIAL PLAN")
        print(f"{'='*80}")
        print(f"Goal: {plan.goal}")
        print(f"Groups: {len(parsed_workflow.groups)}")
        print(f"{'='*80}\n")
        
        for group_idx, group in enumerate(parsed_workflow.groups):
            group_type = "PARALLEL" if group.group_type == WorkflowStepType.PARALLEL else "SEQUENTIAL"
            log_info(f"📦 [Workflow] Executing group {group.group_number} ({group_type}, {len(group.steps)} steps)")
            
            if group.group_type == WorkflowStepType.PARALLEL:
                # ============================================================
                # PARALLEL EXECUTION with proper state tracking
                # ============================================================
                await self._emit_status_event(
                    f"Executing parallel group {group.group_number} ({len(group.steps)} agents simultaneously)...",
                    context_id
                )
                
                # Create AgentModeTask objects for each parallel step
                parallel_tasks: List[AgentModeTask] = []
                for step in group.steps:
                    task = AgentModeTask(
                        task_id=str(uuid.uuid4()),
                        task_description=f"[Step {step.step_label}] {step.description}",
                        recommended_agent=None,  # Will be resolved during execution
                        state="pending"
                    )
                    plan.tasks.append(task)
                    parallel_tasks.append(task)
                
                # Execute all steps in parallel
                async def execute_parallel_step(step: ParsedWorkflowStep, task: AgentModeTask):
                    """Execute a single step and update its task state."""
                    task.state = "running"
                    task.updated_at = datetime.now(timezone.utc)
                    
                    try:
                        result = await self._execute_workflow_step_with_state(
                            step=step,
                            task=task,
                            session_context=session_context,
                            context_id=context_id,
                            user_message=user_message,
                            extract_text_fn=extract_text_from_response
                        )
                        return result
                    except Exception as e:
                        task.state = "failed"
                        task.error_message = str(e)
                        task.updated_at = datetime.now(timezone.utc)
                        log_error(f"[Workflow] Parallel step {step.step_label} failed: {e}")
                        return {"error": str(e), "step_label": step.step_label}
                
                # Run in parallel
                results = await asyncio.gather(
                    *[execute_parallel_step(step, task) for step, task in zip(group.steps, parallel_tasks)],
                    return_exceptions=True
                )
                
                # Collect results and check for HITL pause
                for i, result in enumerate(results):
                    step = group.steps[i]
                    task = parallel_tasks[i]
                    
                    if isinstance(result, Exception):
                        log_error(f"[Workflow] Parallel step {step.step_label} exception: {result}")
                        all_task_outputs.append(f"[Step {step.step_label} Error]: {str(result)}")
                    elif isinstance(result, dict):
                        # Check for HITL pause
                        if result.get("hitl_pause"):
                            log_info(f"⏸️ [Workflow] HITL pause triggered by step {step.step_label}")
                            # Store workflow state for resumption
                            session_context.pending_workflow = str(parsed_workflow)
                            session_context.pending_workflow_outputs = all_task_outputs.copy()
                            session_context.pending_workflow_user_message = user_message
                            return all_task_outputs
                        
                        if result.get("output"):
                            all_task_outputs.append(f"[Step {step.step_label} - {result.get('agent', 'unknown')}]: {result['output']}")
                        elif result.get("error"):
                            all_task_outputs.append(f"[Step {step.step_label} Error]: {result['error']}")
                
                log_info(f"✅ [Workflow] Parallel group {group.group_number} completed")
                
            else:
                # ============================================================
                # SEQUENTIAL EXECUTION with proper state tracking
                # ============================================================
                step = group.steps[0]
                
                # Create AgentModeTask for this step
                task = AgentModeTask(
                    task_id=str(uuid.uuid4()),
                    task_description=f"[Step {step.step_label}] {step.description}",
                    recommended_agent=None,
                    state="running"
                )
                plan.tasks.append(task)
                
                await self._emit_status_event(f"Executing step {step.step_label}: {step.description[:50]}...", context_id)
                
                try:
                    result = await self._execute_workflow_step_with_state(
                        step=step,
                        task=task,
                        session_context=session_context,
                        context_id=context_id,
                        user_message=user_message,
                        extract_text_fn=extract_text_from_response
                    )
                    
                    # Check for HITL pause
                    if result.get("hitl_pause"):
                        log_info(f"⏸️ [Workflow] HITL pause triggered by step {step.step_label}")
                        session_context.pending_workflow = str(parsed_workflow)
                        session_context.pending_workflow_outputs = all_task_outputs.copy()
                        session_context.pending_workflow_user_message = user_message
                        return all_task_outputs
                    
                    if result.get("output"):
                        all_task_outputs.append(f"[Step {step.step_label} - {result.get('agent', 'unknown')}]: {result['output']}")
                    elif result.get("error"):
                        all_task_outputs.append(f"[Step {step.step_label} Error]: {result['error']}")
                    
                except Exception as e:
                    task.state = "failed"
                    task.error_message = str(e)
                    task.updated_at = datetime.now(timezone.utc)
                    log_error(f"[Workflow] Sequential step {step.step_label} failed: {e}")
                    all_task_outputs.append(f"[Step {step.step_label} Error]: {str(e)}")
                
                log_info(f"✅ [Workflow] Sequential step {step.step_label} completed")
        
        # Mark plan as completed
        plan.goal_status = "completed"
        plan.updated_at = datetime.now(timezone.utc)
        
        # Log final plan summary
        print(f"\n{'='*80}")
        print(f"🎬 [Parsed Workflow] FINAL PLAN SUMMARY")
        print(f"{'='*80}")
        print(f"Goal: {plan.goal}")
        print(f"Final Status: {plan.goal_status}")
        print(f"Total Tasks Created: {len(plan.tasks)}")
        print(f"\nTask Breakdown:")
        for i, task in enumerate(plan.tasks, 1):
            print(f"  {i}. [{task.state.upper()}] {task.task_description[:60]}...")
            print(f"     Agent: {task.recommended_agent or 'None'}")
            if task.error_message:
                print(f"     Error: {task.error_message}")
        print(f"\nTask Outputs Collected: {len(all_task_outputs)}")
        print(f"{'='*80}\n")
        
        log_info(f"🎉 [Workflow] All {len(parsed_workflow.groups)} groups completed, collected {len(all_task_outputs)} outputs")
        return all_task_outputs
    
    def _make_step_result(
        self,
        step_label: str,
        agent: str | None,
        state: str,
        output: str | None = None,
        error: str | None = None,
        hitl_pause: bool = False
    ) -> Dict[str, Any]:
        """Create a standardized workflow step result dict."""
        result = {
            "step_label": step_label,
            "agent": agent,
            "state": state,
            "error": error,
            "output": output
        }
        if hitl_pause:
            result["hitl_pause"] = True
        return result
    
    def _deduplicate_workflow_files(self, session_context: SessionContext) -> None:
        """Deduplicate files for multi-step workflows to prevent context explosion."""
        if not hasattr(session_context, '_latest_processed_parts'):
            return
        if len(session_context._latest_processed_parts) <= 1:
            return
            
        from collections import defaultdict
        
        MAX_GENERATED_FILES = 3
        editing_roles = {}
        generated_artifacts = []
        
        for part in reversed(session_context._latest_processed_parts):
            role = None
            if isinstance(part, DataPart) and isinstance(part.data, dict):
                role = part.data.get('role')
            elif hasattr(part, 'root') and isinstance(part.root, DataPart) and isinstance(part.root.data, dict):
                role = part.root.data.get('role')
            
            if role in ['base', 'mask', 'overlay']:
                if role not in editing_roles:
                    editing_roles[role] = part
            else:
                if len(generated_artifacts) < MAX_GENERATED_FILES:
                    generated_artifacts.append(part)
        
        session_context._latest_processed_parts = list(editing_roles.values()) + generated_artifacts
    
    async def _execute_workflow_step_with_state(
        self,
        step: ParsedWorkflowStep,
        task: AgentModeTask,
        session_context: SessionContext,
        context_id: str,
        user_message: str,
        extract_text_fn
    ) -> Dict[str, Any]:
        """
        Execute a single workflow step with full state tracking.
        
        Includes HITL detection, artifact collection, and proper error handling.
        """
        # Resolve agent (by hint or LLM selection)
        agent_name = self._resolve_agent_for_step(step)
        
        if not agent_name:
            available_agents = [{"name": card.name, "description": card.description} for card in self.cards.values()]
            agent_name = await self._select_agent_for_task(step.description, available_agents, context_id)
        
        if not agent_name or agent_name not in self.cards:
            task.state = "failed"
            task.error_message = "No suitable agent found"
            task.updated_at = datetime.now(timezone.utc)
            return self._make_step_result(step.step_label, None, "failed", error="No suitable agent found")
        
        # Update task with resolved agent
        task.recommended_agent = agent_name
        task.updated_at = datetime.now(timezone.utc)
        
        await self._emit_granular_agent_event(
            agent_name=agent_name,
            status_text=f"Starting: {step.description[:50]}...",
            context_id=context_id
        )
        
        # Deduplicate files for multi-step workflows
        self._deduplicate_workflow_files(session_context)
        
        try:
            task_message = f"{step.description}\n\nContext: {user_message}"
            dummy_context = DummyToolContext(session_context, self._azure_blob_client)
            
            responses = await self.send_message(
                agent_name=agent_name,
                message=task_message,
                tool_context=dummy_context,
                suppress_streaming=False
            )
            
            if not responses:
                task.state = "failed"
                task.error_message = "No response from agent"
                task.updated_at = datetime.now(timezone.utc)
                return self._make_step_result(step.step_label, agent_name, "failed", error="No response from agent")
            
            response_obj = responses[0] if isinstance(responses, list) else responses
            
            # Check for HITL (input_required)
            if session_context.pending_input_agent:
                task.state = "input_required"
                task.updated_at = datetime.now(timezone.utc)
                output_text = extract_text_fn(response_obj)
                return self._make_step_result(step.step_label, agent_name, "input_required", output=output_text, hitl_pause=True)
            
            # Process response
            output_text = self._process_workflow_response(response_obj, task, session_context, extract_text_fn)
            
            if task.state == "failed":
                return self._make_step_result(step.step_label, agent_name, "failed", error=task.error_message)
            
            return self._make_step_result(step.step_label, agent_name, "completed", output=output_text)
                
        except Exception as e:
            task.state = "failed"
            task.error_message = str(e)
            task.updated_at = datetime.now(timezone.utc)
            log_error(f"[Workflow] Error executing step {step.step_label}: {e}")
            return self._make_step_result(step.step_label, agent_name, "failed", error=str(e))
    
    def _resolve_agent_for_step(self, step: ParsedWorkflowStep) -> str | None:
        """Resolve agent name from step hint."""
        if not step.agent_hint:
            return None
        for card_name in self.cards.keys():
            if step.agent_hint.lower() in card_name.lower():
                return card_name
        return None
    
    def _process_workflow_response(
        self,
        response_obj: Any,
        task: AgentModeTask,
        session_context: SessionContext,
        extract_text_fn
    ) -> str:
        """Process workflow response and update task state. Returns output text."""
        if isinstance(response_obj, Task):
            task.state = response_obj.status.state
            task.output = {
                "task_id": response_obj.id,
                "state": response_obj.status.state,
                "result": response_obj.result if hasattr(response_obj, 'result') else None,
                "artifacts": [a.model_dump() for a in response_obj.artifacts] if response_obj.artifacts else []
            }
            task.updated_at = datetime.now(timezone.utc)
            
            if task.state == "failed":
                task.error_message = response_obj.status.message or "Task failed"
                return ""
            
            output_text = str(response_obj.result) if response_obj.result else ""
            
            # Collect artifacts
            if response_obj.artifacts:
                artifact_texts = self._collect_artifacts(response_obj.artifacts, session_context)
                if artifact_texts:
                    output_text = f"{output_text}\n\nArtifacts:\n" + "\n".join(artifact_texts)
            
            return output_text
        else:
            # Simple string response
            task.state = "completed"
            output_text = extract_text_fn(response_obj)
            task.output = {"result": output_text}
            task.updated_at = datetime.now(timezone.utc)
            return output_text
    
    def _collect_artifacts(self, artifacts: list, session_context: SessionContext) -> List[str]:
        """Collect artifacts from response and add to session context. Returns descriptions."""
        artifact_descriptions = []
        
        if not hasattr(session_context, '_latest_processed_parts'):
            session_context._latest_processed_parts = []
        
        for artifact in artifacts:
            if not hasattr(artifact, 'parts'):
                continue
            for part in artifact.parts:
                session_context._latest_processed_parts.append(part)
                
                if hasattr(part, 'root'):
                    if hasattr(part.root, 'file'):
                        file_name = getattr(part.root.file, 'name', 'unknown')
                        artifact_descriptions.append(f"[File: {file_name}]")
                    elif hasattr(part.root, 'text'):
                        artifact_descriptions.append(part.root.text)
        
        return artifact_descriptions

    async def _execute_orchestrated_task(
        self,
        task: AgentModeTask,
        session_context: SessionContext,
        context_id: str,
        workflow: Optional[str],
        user_message: str,
        extract_text_fn,
        previous_task_outputs: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Execute a single orchestrated task with full state management.
        
        This method handles:
        - File deduplication for multi-step workflows
        - Agent calling via send_message
        - HITL (input_required) detection
        - Response parsing (A2A Task or legacy format)
        - Artifact collection
        - State updates on the AgentModeTask
        
        Args:
            task: The AgentModeTask to execute
            session_context: Session state
            context_id: Conversation identifier  
            workflow: Optional workflow definition
            user_message: Original user message
            extract_text_fn: Function to extract text from responses
            
        Returns:
            Dict with output, hitl_pause flag, and error info
        """
        recommended_agent = task.recommended_agent
        task_desc = task.task_description
        
        log_debug(f"🚀 [Agent Mode] Executing task: {task_desc[:50]}...")
        
        # Stream task creation event
        await self._emit_granular_agent_event(
            agent_name=recommended_agent or "orchestrator",
            status_text=f"Executing: {task_desc[:50]}...",
            context_id=context_id
        )
        
        if not recommended_agent or recommended_agent not in self.cards:
            task.state = "failed"
            task.error_message = f"Agent '{recommended_agent}' not found"
            task.updated_at = datetime.now(timezone.utc)
            log_error(f"[Agent Mode] Agent not found: {recommended_agent}")
            return {"error": task.error_message, "output": None}
        
        log_debug(f"🎯 [Agent Mode] Calling agent: {recommended_agent}")
        
        # Build enhanced task message with previous task output for sequential context
        # This enables agents to build upon previous work in the workflow
        enhanced_task_message = task_desc
        
        # For sequential workflows: Include ONLY the immediately previous task output as context
        # This allows step N to access the output from step N-1 without context window explosion
        if previous_task_outputs and len(previous_task_outputs) > 0:
            print(f"📋 [Agent Mode] Including previous task output as context (limited to last step only)")
            # Truncate to prevent context overflow (keep first 1000 chars)
            prev_output = previous_task_outputs[0]
            if len(prev_output) > 1000:
                prev_output = prev_output[:1000] + "... [truncated for context window management]"
            
            enhanced_task_message = f"""{task_desc}

## Context from Previous Step:
{prev_output}

Use the above output from the previous workflow step to complete your task."""
        
        # File deduplication for multi-step workflows
        self._deduplicate_workflow_files(session_context)
        
        # Create tool context and call agent
        dummy_context = DummyToolContext(session_context, self._azure_blob_client)
        
        responses = await self.send_message(
            agent_name=recommended_agent,
            message=enhanced_task_message,  # ✅ Now includes previous task outputs!
            tool_context=dummy_context,
            suppress_streaming=True  # Suppress agent's internal streaming to avoid duplicates in workflow mode
        )
        
        if not responses or len(responses) == 0:
            task.state = "failed"
            task.error_message = "No response from agent"
            task.updated_at = datetime.now(timezone.utc)
            log_error(f"[Agent Mode] No response from agent")
            return {"error": "No response from agent", "output": None}
        
        response_obj = responses[0] if isinstance(responses, list) else responses
        
        # Check for HITL (input_required)
        if session_context.pending_input_agent:
            log_info(f"⏸️ [Agent Mode] Agent '{recommended_agent}' returned input_required")
            task.state = "input_required"
            task.updated_at = datetime.now(timezone.utc)
            
            output_text = extract_text_fn(response_obj)
            log_info(f"⏸️ [Agent Mode] Waiting for user response to '{recommended_agent}'")
            await self._emit_status_event(f"Waiting for your response...", context_id)
            
            return {"output": output_text, "hitl_pause": True}
        
        # Parse response
        if isinstance(response_obj, Task):
            task.state = response_obj.status.state
            task.output = {
                "task_id": response_obj.id,
                "state": response_obj.status.state,
                "result": response_obj.result if hasattr(response_obj, 'result') else None,
                "artifacts": [a.model_dump() for a in response_obj.artifacts] if response_obj.artifacts else []
            }
            task.updated_at = datetime.now(timezone.utc)
            
            if task.state == "failed":
                task.error_message = response_obj.status.message or "Task failed"
                log_error(f"[Agent Mode] Task failed: {task.error_message}")
                return {"error": task.error_message, "output": None}
            
            output_text = str(response_obj.result) if response_obj.result else ""
            
            # Collect artifacts using helper
            if response_obj.artifacts:
                artifact_texts = self._collect_artifacts(response_obj.artifacts, session_context)
                if artifact_texts:
                    output_text = f"{output_text}\n\nArtifacts:\n" + "\n".join(artifact_texts)
            
            return {"output": output_text, "hitl_pause": False}
        else:
            # Simple string response (legacy format)
            task.state = "completed"
            output_text = extract_text_fn(response_obj)
            task.output = {"result": output_text}
            task.updated_at = datetime.now(timezone.utc)
            return {"output": output_text, "hitl_pause": False}

    async def _agent_mode_orchestration_loop(
        self,
        user_message: str,
        context_id: str,
        session_context: SessionContext,
        event_logger=None,
        workflow: Optional[str] = None
    ) -> List[str]:
        """
        Execute agent-mode orchestration: AI-driven task decomposition and multi-agent coordination.
        
        This is the core intelligence loop that:
        1. Uses Azure OpenAI to analyze the user's goal and available agents
        2. Breaks down complex requests into discrete, delegable tasks
        3. Selects the best agent for each task based on skills and capabilities
        4. Executes tasks sequentially or in parallel as appropriate
        5. Synthesizes results from multiple agents into coherent responses
        6. Adapts to failures, rate limits, and user feedback dynamically
        
        The loop continues until the goal is marked "completed" by the orchestrator LLM
        or the maximum iteration limit is reached (safety mechanism).
        
        Args:
            user_message: The user's original request or follow-up message
            context_id: Conversation identifier for state management
            session_context: Session state with agent task tracking
            event_logger: Optional callback for logging orchestration events
            workflow: Optional predefined workflow steps to enforce
            
        Returns:
            List of response strings from executed tasks for final synthesis
        """
        log_debug(f"🎯 [Agent Mode] Starting orchestration loop for goal: {user_message[:100]}...")
        
        # Reset host token usage for this workflow
        self.host_token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        
        await self._emit_status_event("Initializing orchestration...", context_id)
        
        # =====================================================================
        # LLM ORCHESTRATION PATH: All workflows go through the orchestrator
        # =====================================================================
        # The LLM orchestrator handles both sequential and parallel workflows.
        # For parallel steps (e.g., 2a., 2b.), the LLM will return next_tasks
        # with parallel=True, and we execute them via asyncio.gather().
        # =====================================================================
        # orchestrator LLM decides which agents to call and in what order.
        # =====================================================================
        
        # Handle conversation continuity - distinguish new goals from follow-up clarifications
        if context_id in self._active_conversations and not workflow:
            original_goal = self._active_conversations[context_id]
            goal_text = f"{original_goal}\n\n[Additional Information Provided]: {user_message}"
        else:
            goal_text = user_message
            if context_id not in self._active_conversations:
                self._active_conversations[context_id] = user_message
        
        # Use the class method for extracting clean text from A2A response objects
        extract_text_from_response = self._extract_text_from_response
        
        # Initialize execution plan with empty task list
        plan = AgentModePlan(goal=goal_text, goal_status="incomplete")
        iteration = 0
        max_iterations = 20
        workflow_step_count = 0
        
        # Accumulate outputs from all completed tasks
        all_task_outputs = []
        
        # System prompt that guides the orchestrator's decision-making
        # This is the "brain" that decides which agents to use and when
        system_prompt = """You are the Host Orchestrator in an A2A multi-agent system.

PRIMARY RESPONSIBILITIES:
- **FIRST**: Check if a MANDATORY WORKFLOW exists below - if it does, you MUST complete ALL workflow steps before marking goal as "completed"
- Evaluate whether the user's goal is achieved by analyzing all completed tasks and their outputs
- If incomplete, propose the next task(s) that move closer to the goal
- Select the most appropriate agent based on their specialized skills

DECISION-MAKING RULES:
- Analyze the ENTIRE plan history - don't ignore previous tasks or outputs
- Never repeat completed tasks unless explicitly retrying a failure
- Keep each task atomic and delegable to a single agent
- Match tasks to agents using their "skills" field for best results
- If no agent fits, set recommended_agent=null
- Mark goal_status="completed" ONLY when: (1) ALL MANDATORY WORKFLOW steps are completed (if workflow exists), AND (2) the objective is fully achieved

### 🔀 PARALLEL EXECUTION SUPPORT
When the workflow contains parallel steps (indicated by letter suffixes like 2a., 2b., 2c.):
- These steps can be executed SIMULTANEOUSLY - they do not depend on each other
- Use `next_tasks` (list) instead of `next_task` (single) to propose multiple parallel tasks
- Set `parallel=true` to indicate these tasks should run concurrently
- Example: For steps "2a. Legal review" and "2b. Technical assessment":
  ```json
  {
    "goal_status": "incomplete",
    "next_task": null,
    "next_tasks": [
      {"task_description": "Legal review of requirements", "recommended_agent": "Legal Agent"},
      {"task_description": "Technical assessment", "recommended_agent": "Tech Agent"}
    ],
    "parallel": true,
    "reasoning": "Steps 2a and 2b can run in parallel as they are independent"
  }
  ```
- After parallel tasks complete, proceed to the next sequential step (e.g., step 3)
- If NO parallel steps, use `next_task` (single) and set `parallel=false`

MULTI-AGENT STRATEGY:
- **MAXIMIZE AGENT UTILIZATION**: Break complex goals into specialized subtasks
- Use multiple agents when their combined expertise adds value
- Don't force one agent to handle everything when others can help
- The same agent can be used multiple times for related subtasks

FAILURE HANDLING:
- Consider failed tasks in planning
- You can retry with modifications or try alternative agents/approaches

### 🔄 TASK DECOMPOSITION PRINCIPLES
- **Read ALL Agent Skills First**: Before creating any task, carefully read through the skill descriptions of ALL available agents to understand what each can provide.
- **Identify Skill Dependencies**: Determine if completing the goal requires outputs from multiple agents. If Agent B needs information/context that Agent A specializes in, Agent A must be tasked first.
- **Match Task to Skill Domain**: Each task should align with exactly ONE agent's skill domain. If a concept in the goal matches words in an agent's skill name or description, that agent should handle that aspect.
- **Information Producers vs Consumers**: Some agents produce information/context/specifications (e.g., skills about "guidelines", "direction", "specifications"). Others consume that information to execute (e.g., skills about "generate", "create", "build"). Producers come first.
- **Sequential Task Chain**: When the goal involves multiple skill domains, create Task 1 for the information producer, let it complete, then Task 2 for the executor using Task 1's output.
- **No Shortcuts**: Don't try to have one agent do another agent's specialty work. Decompose properly even if it means more tasks.

### 🎯 DELEGATION FIRST PRINCIPLE
- ALWAYS delegate to an appropriate agent if you have ANY actionable information related to the goal
- **BUT** check if the task requires prerequisite skills from a different agent - if so, delegate to that agent FIRST
- Each agent should work within their skill domain - use the "skills" field to match task requirements to agent capabilities
- Tasks should arrive at agents with all necessary context already gathered by appropriate upstream agents
"""
        
        # Inject workflow if provided
        print(f"🔍 [Agent Mode] Checking workflow: workflow={workflow}, stripped={workflow.strip() if workflow else 'N/A'}")
        if workflow and workflow.strip():
            workflow_section = f"""

### 🔥 MANDATORY WORKFLOW - FOLLOW ALL STEPS IN ORDER 🔥
**CRITICAL**: The following workflow steps are MANDATORY and must ALL be completed before marking the goal as "completed".
Do NOT skip steps. Do NOT mark goal as completed until ALL workflow steps are done.

{workflow.strip()}

**IMPORTANT**: 
- Execute sequential steps (1, 2, 3) one after another
- **PARALLEL STEPS** (e.g., 2a, 2b, 2c): When you see steps with letter suffixes, these can run SIMULTANEOUSLY
  - Use `next_tasks` (list) with `parallel=true` to execute them concurrently
  - Wait for ALL parallel tasks to complete before moving to the next sequential step
- Only mark goal_status="completed" after ALL workflow steps are finished
- If a step fails, you may retry or adapt, but you must complete all steps
"""
            system_prompt += workflow_section
            log_debug(f"📋 [Agent Mode] ✅ Injected workflow into planner prompt ({len(workflow)} chars)")
        
        # Add workflow-specific completion logic if workflow is present
        if workflow and workflow.strip():
            workflow_step_count = len([line for line in workflow.strip().split('\n') if line.strip() and (line.strip()[0].isdigit() or line.strip().startswith('-'))])
            log_debug(f"📊 [Agent Mode] Workflow step count: {workflow_step_count}")
            
            system_prompt += f"""

### 🚨 CRITICAL: WHEN TO STOP (WORKFLOW MODE)
- A WORKFLOW IS ACTIVE with **{workflow_step_count} MANDATORY STEPS** - You MUST complete ALL {workflow_step_count} workflow steps before marking goal as "completed"
- **STEP COUNTING**: The workflow has EXACTLY {workflow_step_count} steps. Count your completed tasks carefully!
- **VERIFICATION CHECKLIST**:
  1. Count the number of workflow steps above (should be {workflow_step_count})
  2. Count the number of successfully completed tasks in your plan
  3. Match each workflow step to a completed task
  4. If completed tasks < {workflow_step_count}, goal_status MUST be "incomplete"
- **COMPLETION CRITERIA** - Mark goal_status="completed" ONLY when:
  1. You have AT LEAST {workflow_step_count} successfully completed tasks, AND
  2. Each workflow step has been addressed by a completed task, AND
  3. All completed tasks succeeded (or agents are waiting for user input)
- **WARNING**: Do NOT mark as completed after only 1, 2, or 3 steps if the workflow has {workflow_step_count} steps!
- If ANY workflow step is missing or incomplete, goal_status MUST be "incomplete" and you must create the next task"""
        else:
            system_prompt += """

### 🚨 CRITICAL: WHEN TO STOP (LOOP DETECTION & USER INPUT)
- ONLY mark goal as "completed" in these specific cases:
  1. The goal is actually fully accomplished with successful task outputs
  2. You have 2+ completed tasks where agents explicitly asked the USER for information
  3. The last agent response clearly states they need user input to proceed
- If NO tasks have been created yet, DO NOT mark as completed - create a task first!
- When agents request information, synthesize their questions and present to the user
- When the user provides information in a follow-up, create a NEW task with that information"""
        
        while plan.goal_status == "incomplete" and iteration < max_iterations:
            iteration += 1
            print(f"🔄 [Agent Mode] Iteration {iteration}/{max_iterations}")
            await self._emit_status_event(f"Planning step {iteration}...", context_id)
            
            # Build user prompt with current plan state
            available_agents = []
            for card in self.cards.values():
                agent_info = {
                    "name": card.name,
                    "description": card.description
                }
                
                # Add skills if present
                if hasattr(card, 'skills') and card.skills:
                    skills_list = []
                    for skill in card.skills:
                        skill_dict = {
                            "id": getattr(skill, 'id', ''),
                            "name": getattr(skill, 'name', ''),
                            "description": getattr(skill, 'description', ''),
                        }
                        skills_list.append(skill_dict)
                    agent_info['skills'] = skills_list
                
                available_agents.append(agent_info)
            
            user_prompt = f"""Goal:
{plan.goal}

Current Plan (JSON):
{json.dumps(plan.model_dump(), indent=2, default=str)}

Available Agents (JSON):
{json.dumps(available_agents, indent=2)}

Analyze the plan and determine the next step. Proceed autonomously - do NOT ask the user for permission or confirmation."""
            
            # Get next step from orchestrator
            try:
                next_step = await self._call_azure_openai_structured(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_model=NextStep,
                    context_id=context_id
                )
                
                log_debug(f"🤖 [Agent Mode] Orchestrator: {next_step.reasoning[:100]}... | status={next_step.goal_status}")
                await self._emit_status_event(f"Reasoning: {next_step.reasoning}", context_id)
                
                # Update plan status
                plan.goal_status = next_step.goal_status
                plan.updated_at = datetime.now(timezone.utc)
                
                if next_step.goal_status == "completed":
                    completed_tasks_count = len([t for t in plan.tasks if t.state == "completed"])
                    log_info(f"✅ [Agent Mode] Goal completed after {iteration} iterations ({completed_tasks_count} tasks)")
                    await self._emit_status_event("Goal achieved! Generating final response...", context_id)
                    break
                
                # =========================================================
                # TASK EXECUTION: Handle both sequential and parallel tasks
                # =========================================================
                
                # Determine which tasks to execute
                tasks_to_execute = []
                is_parallel = next_step.parallel and next_step.next_tasks
                
                if is_parallel and next_step.next_tasks:
                    log_info(f"🔀 [Agent Mode] PARALLEL execution: {len(next_step.next_tasks)} tasks")
                    await self._emit_status_event(f"Executing {len(next_step.next_tasks)} tasks in parallel...", context_id)
                    for task_dict in next_step.next_tasks:
                        tasks_to_execute.append({
                            "task_description": task_dict.get("task_description"),
                            "recommended_agent": task_dict.get("recommended_agent")
                        })
                elif next_step.next_task:
                    # SEQUENTIAL EXECUTION: Single task via next_task
                    tasks_to_execute.append({
                        "task_description": next_step.next_task.get("task_description"),
                        "recommended_agent": next_step.next_task.get("recommended_agent")
                    })
                
                if not tasks_to_execute:
                    print(f"⚠️ [Agent Mode] No tasks to execute, breaking loop")
                    break
                
                # Validate all tasks have descriptions
                for task_dict in tasks_to_execute:
                    if not task_dict.get("task_description"):
                        print(f"⚠️ [Agent Mode] Task missing description, skipping")
                        tasks_to_execute.remove(task_dict)
                
                if not tasks_to_execute:
                    print(f"⚠️ [Agent Mode] No valid tasks after validation, breaking loop")
                    break
                
                # Create AgentModeTask objects for all tasks
                pydantic_tasks = []
                for task_dict in tasks_to_execute:
                    task = AgentModeTask(
                        task_id=str(uuid.uuid4()),
                        task_description=task_dict["task_description"],
                        recommended_agent=task_dict.get("recommended_agent"),
                        state="pending"
                    )
                    plan.tasks.append(task)
                    pydantic_tasks.append(task)
                    log_debug(f"📋 [Agent Mode] Created task: {task.task_description[:50]}...")
                
                # Execute tasks (parallel or sequential)
                if is_parallel:
                    # ============================================
                    # PARALLEL EXECUTION via asyncio.gather()
                    # ============================================
                    import asyncio as async_lib  # Import locally to avoid any scoping issues
                    log_info(f"🔀 [Agent Mode] Executing {len(pydantic_tasks)} tasks IN PARALLEL")
                    await self._emit_status_event(f"Executing {len(pydantic_tasks)} tasks simultaneously...", context_id)
                    
                    async def execute_task_parallel(task: AgentModeTask) -> Dict[str, Any]:
                        """Execute a single task and return result dict."""
                        task.state = "running"
                        task.updated_at = datetime.now(timezone.utc)
                        
                        try:
                            # For parallel tasks, pass only the LAST task output (from the step before parallel group)
                            # Don't pass all accumulated outputs - that would grow context exponentially
                            previous_output = [all_task_outputs[-1]] if all_task_outputs else None
                            
                            result = await self._execute_orchestrated_task(
                                task=task,
                                session_context=session_context,
                                context_id=context_id,
                                workflow=workflow,
                                user_message=user_message,
                                extract_text_fn=extract_text_from_response,
                                previous_task_outputs=previous_output  # ✅ Only LAST output
                            )
                            return result
                        except Exception as e:
                            task.state = "failed"
                            task.error_message = str(e)
                            task.updated_at = datetime.now(timezone.utc)
                            log_error(f"[Agent Mode] Parallel task failed: {e}")
                            return {"error": str(e), "task_id": task.task_id}
                    
                    # Run all tasks in parallel
                    try:
                        results = await async_lib.gather(
                            *[execute_task_parallel(t) for t in pydantic_tasks],
                            return_exceptions=True
                        )
                    except Exception as gather_error:
                        log_error(f"[Agent Mode] asyncio.gather failed: {gather_error}")
                        raise
                    
                    # Process results
                    hitl_pause = False
                    for i, result in enumerate(results):
                        task = pydantic_tasks[i]
                        if isinstance(result, Exception):
                            task.state = "failed"
                            task.error_message = str(result)
                        elif isinstance(result, dict):
                            if result.get("hitl_pause"):
                                hitl_pause = True
                                if result.get("output"):
                                    all_task_outputs.append(result["output"])
                            elif result.get("output"):
                                all_task_outputs.append(result["output"])
                        task.updated_at = datetime.now(timezone.utc)
                    
                    # If any task triggered HITL pause, pause the workflow
                    if hitl_pause:
                        session_context.pending_workflow = workflow
                        session_context.pending_workflow_outputs = all_task_outputs.copy()
                        session_context.pending_workflow_user_message = user_message
                        return all_task_outputs
                    
                    log_info(f"✅ [Agent Mode] {len(pydantic_tasks)} parallel tasks completed")
                    
                else:
                    # ============================================
                    # SEQUENTIAL EXECUTION (single task)
                    # ============================================
                    task = pydantic_tasks[0]
                    task.state = "running"
                    task.updated_at = datetime.now(timezone.utc)
                    
                    try:
                        previous_output = [all_task_outputs[-1]] if all_task_outputs else None
                        
                        result = await self._execute_orchestrated_task(
                            task=task,
                            session_context=session_context,
                            context_id=context_id,
                            workflow=workflow,
                            user_message=user_message,
                            extract_text_fn=extract_text_from_response,
                            previous_task_outputs=previous_output
                        )
                        
                        if result.get("hitl_pause"):
                            if result.get("output"):
                                all_task_outputs.append(result["output"])
                            session_context.pending_workflow = workflow
                            session_context.pending_workflow_outputs = all_task_outputs.copy()
                            session_context.pending_workflow_user_message = user_message
                            return all_task_outputs
                        
                        if result.get("output"):
                            all_task_outputs.append(result["output"])
                        
                    except Exception as e:
                        task.state = "failed"
                        task.error_message = str(e)
                        log_error(f"[Agent Mode] Task execution error: {e}")
                    
                    finally:
                        task.updated_at = datetime.now(timezone.utc)
                
            except Exception as e:
                log_error(f"[Agent Mode] Orchestration error: {e}")
                await self._emit_status_event(f"Error in orchestration: {str(e)}", context_id)
                break
        
        if iteration >= max_iterations:
            log_debug(f"⚠️ [Agent Mode] Reached max iterations ({max_iterations})")
            await self._emit_status_event("Maximum iterations reached, completing...", context_id)
        
        log_info(f"🎬 [Agent Mode] Complete: {len(all_task_outputs)} outputs, {iteration} iterations, {len(plan.tasks)} tasks")
        
        # Emit host token usage to frontend
        try:
            from service.websocket_streamer import get_websocket_streamer
            
            async def emit_host_tokens():
                streamer = await get_websocket_streamer()
                if streamer:
                    event_data = {
                        "agentName": "foundry-host-agent",
                        "tokenUsage": self.host_token_usage,
                        "state": "completed",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    await streamer._send_event("host_token_usage", event_data, context_id)
            
            asyncio.create_task(emit_host_tokens())
        except Exception:
            pass  # Don't let token emission failures break the flow
        
        return all_task_outputs

    async def get_current_root_instruction(self) -> str:
        """Get the current root instruction (custom or default)"""
        return self.root_instruction('foundry-host-agent')

    async def update_root_instruction(self, new_instruction: str) -> bool:
        """Update the root instruction and apply it to the Azure AI Foundry agent"""
        try:
            print(f"🔄 Updating root instruction...")
            print(f"   New instruction length: {len(new_instruction)} characters")
            
            # Store the custom instruction
            self.custom_root_instruction = new_instruction
            
            # Update the Azure AI Foundry agent with the new instruction
            await self._update_agent_instructions()
            
            print(f"✅ Root instruction updated successfully!")
            return True
            
        except Exception as e:
            print(f"❌ Error updating root instruction: {e}")
            return False

    async def reset_root_instruction(self) -> bool:
        """Reset to default root instruction"""
        try:
            print(f"🔄 Resetting to default root instruction...")
            
            # Clear the custom instruction
            self.custom_root_instruction = None
            
            # Update the Azure AI Foundry agent with the default instruction
            await self._update_agent_instructions()
            
            print(f"✅ Root instruction reset to default!")
            return True
            
        except Exception as e:
            print(f"❌ Error resetting root instruction: {e}")
            return False

    # Note: _stream_remote_agent_activity, _default_task_callback, _display_task_status_update,
    # _get_status_display_text, _extract_message_content, _extract_text_from_response
    # have been extracted to streaming_handlers.py
    def get_session_context(self, context_id: str) -> SessionContext:
        log_debug(f"🔍 [get_session_context] Called with context_id: {context_id}")
        log_debug(f"🔍 [get_session_context] Existing session_contexts keys: {list(self.session_contexts.keys())}")
        
        if context_id not in self.session_contexts:
            # Clear host response tracking for new conversations
            if context_id in self._host_responses_sent:
                self._host_responses_sent.remove(context_id)
            log_debug(f"🔍 [get_session_context] Creating NEW SessionContext with contextId={context_id}")
            self.session_contexts[context_id] = SessionContext(contextId=context_id)
        else:
            log_debug(f"🔍 [get_session_context] FOUND existing SessionContext for key={context_id}")
            
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

            print(f"Making direct Azure OpenAI call for evaluation...")
            
            # Use the same Azure AI Foundry approach as the rest of the system
            from openai import AsyncAzureOpenAI
            from azure.identity import get_bearer_token_provider
            
            # Use the same endpoint and credentials as the main agent
            azure_endpoint = os.getenv("AZURE_CONTENT_UNDERSTANDING_ENDPOINT") or os.getenv("AZURE_AI_SERVICE_ENDPOINT")
            model_name = os.environ.get("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME")
            
            if not azure_endpoint:
                print(f"❌ Missing Azure endpoint configuration")
                return {"is_successful": True, "reason": "Missing endpoint config"}
            
            if not model_name:
                print(f"❌ Missing model deployment name")
                return {"is_successful": True, "reason": "Missing model config"}
            
            # Use DefaultAzureCredential like the rest of the system
            token_provider = get_bearer_token_provider(
                self.credential, 
                "https://cognitiveservices.azure.com/.default"
            )
            
            # Create Azure OpenAI client with same auth as main system
            client = AsyncAzureOpenAI(
                azure_endpoint=azure_endpoint,
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
                max_tokens=200,
                temperature=0.1
            )
            
            evaluation_response = response.choices[0].message.content
            print(f"Direct OpenAI evaluation response: {evaluation_response}")
            
            # Parse JSON response
            try:
                import json
                # Extract JSON from response (in case there's extra text)
                start_idx = evaluation_response.find('{')
                end_idx = evaluation_response.rfind('}') + 1
                if start_idx >= 0 and end_idx > start_idx:
                    json_str = evaluation_response[start_idx:end_idx]
                    evaluation_result = json.loads(json_str)
                    print(f"✅ Parsed evaluation result: {evaluation_result}")
                    
                    # Add default fields if missing from simplified response
                    if "retry_suggestion" not in evaluation_result:
                        evaluation_result["retry_suggestion"] = "Try rephrasing your request or provide more details"
                    if "alternative_agent" not in evaluation_result:
                        evaluation_result["alternative_agent"] = None
                    if "needs_clarification" not in evaluation_result:
                        evaluation_result["needs_clarification"] = None
                        
                    return evaluation_result
                else:
                    print(f"❌ No valid JSON found in evaluation response")
                    return {"is_successful": True, "reason": "Could not parse evaluation"}
                    
            except json.JSONDecodeError as e:
                print(f"❌ JSON parsing error: {e}")
                return {"is_successful": True, "reason": "Could not parse evaluation"}
                
        except Exception as e:
            print(f"❌ Error during task evaluation: {e}")
            # Default to successful if evaluation fails to avoid blocking user
            return {"is_successful": True, "reason": f"Evaluation error: {str(e)}"}

    async def _log_evaluation_result(self, original_request: str, task_response: Task, agent_name: str):
        """Background evaluation for monitoring - doesn't affect user experience"""
        try:
            print(f"[BACKGROUND] Running evaluation for monitoring...")
            evaluation = await self._evaluate_task_completion(original_request, task_response, agent_name)
            
            # Just log the results for monitoring/analytics
            if evaluation.get("is_successful", True):
                print(f"✅ [BACKGROUND] Task evaluation: SUCCESS - {evaluation.get('reason', '')}")
            else:
                print(f"⚠️ [BACKGROUND] Task evaluation: FAILED - {evaluation.get('reason', '')}")
                print(f"💡 [BACKGROUND] Suggestion: {evaluation.get('retry_suggestion', 'None')}")
                
            # Could store results for analytics dashboard
            # await self._store_evaluation_analytics(original_request, task_response, agent_name, evaluation)
            
        except Exception as e:
            print(f"❌ [BACKGROUND] Evaluation error (non-blocking): {e}")
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
        Store processed parts in session context for later access.
        
        Parts are appended to session_context._latest_processed_parts list.
        This is used to make file artifacts accessible to remote agents.
        """
        session_context = getattr(tool_context, "state", None)
        if session_context is None:
            return
        latest_parts = getattr(session_context, "_latest_processed_parts", None)
        if latest_parts is None:
            latest_parts = []
            setattr(session_context, "_latest_processed_parts", latest_parts)
        for p in parts:
            if p is not None:
                latest_parts.append(p)

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
                role_attr = getattr(candidate_part.file, "role", None)
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

    async def _handle_pending_input_agent(
        self,
        session_context: Any,
        message_parts: list,
        context_id: str,
        event_logger: Any
    ) -> Optional[list]:
        """
        Handle Human-In-The-Loop (HITL) routing when an agent is waiting for input_required response.
        
        If an agent previously returned input_required, route the user's response directly
        to that agent instead of going through normal orchestration. Also handles resuming
        paused workflows after the agent completes.
        
        Args:
            session_context: The session context with pending agent state
            message_parts: The user's message parts
            context_id: The context/session ID
            event_logger: Event logger for tracking
            
        Returns:
            Response list if HITL was handled, None if no pending agent (fall through to normal flow)
        """
        if not session_context.pending_input_agent:
            return None
            
        pending_agent = session_context.pending_input_agent
        pending_task_id = session_context.pending_input_task_id
        pending_workflow = session_context.pending_workflow
        pending_workflow_outputs = session_context.pending_workflow_outputs or []
        
        log_info(f"🔄 [HITL] Found pending input_required agent: '{pending_agent}' (task_id: {pending_task_id})")
        log_info(f"🔄 [HITL] Routing user response directly to waiting agent instead of orchestration")
        if pending_workflow:
            log_info(f"🔄 [HITL] Workflow will resume after agent completes ({len(pending_workflow_outputs)} outputs collected)")
        
        # Clear the pending state before routing
        session_context.pending_input_agent = None
        session_context.pending_input_task_id = None
        
        # Extract user message from parts
        hitl_user_message = ""
        for part in message_parts:
            if hasattr(part, 'root') and part.root.kind == 'text':
                hitl_user_message = part.root.text
                break
        
        # Helper to extract clean text from responses
        def clean_response(resp):
            if isinstance(resp, list):
                return [self._extract_text_from_response(r) for r in resp]
            return [self._extract_text_from_response(resp)]
        
        try:
            tool_context = DummyToolContext(session_context, self._azure_blob_client)
            hitl_response = await self.send_message(
                agent_name=pending_agent,
                message=hitl_user_message,
                tool_context=tool_context,
                suppress_streaming=False
            )
            log_info(f"🔄 [HITL] Response from agent '{pending_agent}': {str(hitl_response)[:200]}...")
            
            # Check if agent is STILL requesting input (multi-turn HITL)
            if session_context.pending_input_agent:
                log_info(f"🔄 [HITL] Agent still requires more input - staying paused")
                return clean_response(hitl_response)
            
            # Agent completed! Check if we need to resume a paused workflow
            if pending_workflow:
                log_info(f"▶️ [HITL] Agent completed - RESUMING WORKFLOW")
                
                # Add this agent's response to the collected outputs
                hitl_outputs = clean_response(hitl_response)
                all_outputs = pending_workflow_outputs + hitl_outputs
                
                # Clear workflow pause state
                session_context.pending_workflow = None
                session_context.pending_workflow_outputs = []
                session_context.pending_workflow_user_message = None
                
                log_info(f"▶️ [HITL] Resuming workflow with {len(all_outputs)} total outputs")
                
                # Continue the workflow from where we left off
                remaining_outputs = await self._agent_mode_orchestration_loop(
                    user_message="Continue the workflow. The previous step has completed.",
                    context_id=context_id,
                    session_context=session_context,
                    event_logger=event_logger,
                    workflow=pending_workflow
                )
                
                # Clean any remaining outputs too
                clean_remaining = [self._extract_text_from_response(out) for out in remaining_outputs]
                return all_outputs + clean_remaining
            
            return clean_response(hitl_response)
            
        except Exception as e:
            log_error(f"🔄 [HITL] Error routing to pending agent '{pending_agent}': {e}")
            import traceback
            traceback.print_exc()
            # Return None to fall through to normal processing
            return None

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
        
        log_debug(f"📝 [Context] Updated host_turn_history with response from {agent_name} ({len(combined)} chars)")
        logger.debug(
            "[A2A] Cached host turn for agent %s (len=%d, history=%d)",
            agent_name,
            len(combined),
            len(getattr(session_context, "host_turn_history", [])),
        )

    async def send_message(
        self,
        agent_name: str,
        message: str,
        tool_context: Any,
        suppress_streaming: bool = True,
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
        
        Args:
            agent_name: Name of the target remote agent
            message: The message/task to send to the agent
            tool_context: Context object with session state and artifact storage
            suppress_streaming: If True, don't stream to main chat (used for sub-agent calls)
                               If False, stream to UI (used for direct user-facing responses)
        
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
            
            # Check if agent exists (quick validation)
            if agent_name not in self.remote_agent_connections:
                available_agents = list(self.remote_agent_connections.keys())
                raise ValueError(f"Agent '{agent_name}' not found. Available agents: {available_agents}")
            
            client = self.remote_agent_connections[agent_name]
            if not client:
                raise ValueError(f"Client not available for {agent_name}")

            # Add conversation context to message (this can be optimized further)
            contextualized_message = await self._add_context_to_message(
                message,
                session_context,
                thread_id=None,
                target_agent_name=agent_name,
            )

            # Respect any active cooldown for this agent due to throttling
            try:
                cool_until = session_context.agent_cooldowns.get(agent_name, 0)
                now_ts = time.time()
                if cool_until and cool_until > now_ts:
                    wait_s = min(60, max(0, int(cool_until - now_ts)))
                    if wait_s > 0:
                        asyncio.create_task(self._emit_granular_agent_event(agent_name, f"throttled; waiting {wait_s}s", session_context.contextId))
                        await asyncio.sleep(wait_s)
            except Exception:
                pass
            
            # Use per-agent taskId only if the previous task for this agent is not in a terminal state
            taskId = None
            last_task_id = session_context.agent_task_ids.get(agent_name)
            last_task_state = session_context.agent_task_states.get(agent_name)
            # Continue same task only if we believe it's in-progress or awaiting input
            if last_task_id and last_task_state in {"working", "submitted", "input-required"}:
                taskId = last_task_id
            contextId = session_context.contextId
            messageId = str(uuid.uuid4())  # Generate fresh message ID for this specific call

            prepared_parts: List[Any] = [Part(root=TextPart(text=contextualized_message))]
            session_parts = []
            if hasattr(session_context, "_latest_processed_parts"):
                session_parts = getattr(session_context, "_latest_processed_parts", []) or []
            
            # DEBUG: Log what we're about to send
            log_foundry_debug(f"Before sending to {agent_name}:")
            log_debug(f"  • _latest_processed_parts exists: {hasattr(session_context, '_latest_processed_parts')}")
            log_debug(f"  • session_parts count: {len(session_parts)}")
            log_debug(f"  • agent_mode: {getattr(session_context, 'agent_mode', False)}")

            if session_parts:
                log_debug(f"📦 Prepared {len(session_parts)} parts for remote agent {agent_name}")
                for prepared_part in session_parts:
                    if isinstance(prepared_part, Part):
                        prepared_parts.append(prepared_part)
                    elif isinstance(prepared_part, (TextPart, DataPart, FilePart)):
                        prepared_parts.append(Part(root=prepared_part))
                    elif isinstance(prepared_part, dict):
                        prepared_parts.append(Part(root=DataPart(data=prepared_part)))
                    elif hasattr(prepared_part, "root"):
                        prepared_parts.append(Part(root=prepared_part.root))
                    elif prepared_part is not None:
                        prepared_parts.append(Part(root=TextPart(text=str(prepared_part))))

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
            
            log_debug(f"🚀 Calling agent: {agent_name} with context: {contextId}")
            
            # Track start time for processing duration
            start_time = time.time()
            
            # Create a user-friendly query preview for status messages
            query_preview = message[:60] + "..." if len(message) > 60 else message
            query_preview = " ".join(query_preview.split())
            
            # ========================================================================
            # EMIT WORKFLOW MESSAGE: Clear "Calling agent" message for workflow panel
            # ========================================================================
            asyncio.create_task(self._emit_granular_agent_event(agent_name, f"Contacting {agent_name}...", contextId))
            
            # ========================================================================
            # EMIT INITIAL STATUS: "submitted" - task has been sent to remote agent
            # This is for the SIDEBAR to show the agent is starting work
            # ========================================================================
            asyncio.create_task(self._emit_simple_task_status(agent_name, "submitted", contextId, taskId))
            
            try:
                # CRITICAL: Store HOST's contextId for use in callbacks
                # Callbacks receive events with remote agent's contextId, but we need
                # to route WebSocket events using the host's session contextId
                self._current_host_context_id = contextId
                host_context_id = contextId
                
                # SIMPLIFIED: Callback for streaming execution that handles file artifacts
                # Status events are handled ONLY in _default_task_callback -> _emit_task_event
                # Track if we've emitted "working" status for this callback session
                _working_emitted = {"emitted": False}
                
                def streaming_task_callback(event, agent_card):
                    """Enhanced callback for streaming execution that captures detailed agent activities"""
                    agent_name = agent_card.name
                    log_debug(f"🎬 [streaming_task_callback] CALLED for {agent_name}: {type(event).__name__}")
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
                            # Extract detailed status information
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
                                                    # Register in agent file registry for file history persistence
                                                    session_id = host_context_id.split('::')[0] if '::' in host_context_id else host_context_id
                                                    from service.agent_file_registry import register_agent_file
                                                    register_agent_file(
                                                        session_id=session_id,
                                                        uri=artifact_uri,
                                                        filename=part.root.data.get("file-name", "agent-artifact.png"),
                                                        content_type="image/png",
                                                        source_agent=agent_name
                                                    )
                                                    # Emit file_uploaded event - USE HOST'S contextId for routing!
                                                    asyncio.create_task(self._emit_file_artifact_event(
                                                        filename=part.root.data.get("file-name", "agent-artifact.png"),
                                                        uri=artifact_uri,
                                                        context_id=host_context_id,
                                                        agent_name=agent_name,
                                                        content_type="image/png",
                                                        size=part.root.data.get("file-size", 0)
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
                                                        # Register in agent file registry for file history persistence
                                                        session_id = host_context_id.split('::')[0] if '::' in host_context_id else host_context_id
                                                        from service.agent_file_registry import register_agent_file
                                                        register_agent_file(
                                                            session_id=session_id,
                                                            uri=str(file_uri),
                                                            filename=file_name,
                                                            content_type=mime_type,
                                                            source_agent=agent_name
                                                        )
                                                        # Emit file_uploaded event - USE HOST'S contextId for routing!
                                                        asyncio.create_task(self._emit_file_artifact_event(
                                                            filename=file_name,
                                                            uri=str(file_uri),
                                                            context_id=host_context_id,
                                                            agent_name=agent_name,
                                                            content_type=mime_type,
                                                            size=0
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
                            
                            # Stream detailed status to UI - USE HOST'S contextId for routing!
                            asyncio.create_task(self._emit_granular_agent_event(agent_name, status_text, host_context_id))
                            
                        elif event_kind == 'artifact-update':
                            # Agent is generating artifacts - USE HOST'S contextId for routing!
                            elapsed_seconds = int(time.time() - start_time)
                            elapsed_str = f" ({elapsed_seconds}s)" if elapsed_seconds >= 5 else ""
                            asyncio.create_task(self._emit_granular_agent_event(agent_name, f"{agent_name} is preparing results{elapsed_str}", host_context_id))
                        
                        elif event_kind == 'task':
                            # Initial task creation - USE HOST'S contextId for routing!
                            asyncio.create_task(self._emit_granular_agent_event(agent_name, f"{agent_name} has started working on: \"{query_preview}\"", host_context_id))
                    
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
                log_debug(f"✅ Agent {agent_name} responded successfully")
                
            except Exception as e:
                log_debug(f"❌ Agent {agent_name} failed: {e}")
                import traceback
                log_debug(f"❌ Traceback: {traceback.format_exc()}")
                raise
            
            # Process response based on type
            if isinstance(response, Task):
                task = response
                log_debug(f"📊 Task response from {agent_name}: state={task.status.state if hasattr(task, 'status') else 'N/A'}")
                
                # Update session context
                context_id = get_context_id(task)
                if context_id:
                    session_context.contextId = context_id
                t_id = get_task_id(task)
                session_context.agent_task_ids[agent_name] = t_id
                try:
                    state_val = task.status.state.value if hasattr(task.status.state, 'value') else str(task.status.state)
                except Exception:
                    state_val = "working"
                session_context.agent_task_states[agent_name] = state_val
                
                # Handle task states
                if task.status.state == TaskState.completed:
                    asyncio.create_task(self._emit_simple_task_status(agent_name, "completed", contextId, taskId))
                    asyncio.create_task(self._emit_granular_agent_event(agent_name, f"{agent_name} has completed the task successfully", contextId))
                    
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
                    for item in response_parts:
                        is_file = isinstance(item, FilePart) or (hasattr(item, 'root') and isinstance(item.root, FilePart))
                        is_data = isinstance(item, DataPart) or (hasattr(item, 'root') and isinstance(item.root, DataPart))
                        if is_file or is_data:
                            if not hasattr(session_context, '_agent_generated_artifacts'):
                                session_context._agent_generated_artifacts = []
                            session_context._agent_generated_artifacts.append(item)

                    self._update_last_host_turn(session_context, agent_name, response_parts)
                    
                    # Store interaction in background
                    asyncio.create_task(self._store_a2a_interaction_background(
                        outbound_request=request,
                        inbound_response=response,
                        agent_name=agent_name,
                        processing_time=time.time() - start_time,
                        span=span,
                        context_id=contextId
                    ))
                    
                    return response_parts
                    
                elif task.status.state == TaskState.failed:
                    log_debug(f"Task failed for {agent_name}")
                    retry_after = self._parse_retry_after_from_task(task)
                    max_rate_limit_retries = 3
                    retry_attempt = 0

                    while retry_after and retry_after > 0 and retry_attempt < max_rate_limit_retries:
                        retry_attempt += 1
                        session_context.agent_task_states[agent_name] = 'failed'
                        session_context.agent_cooldowns[agent_name] = time.time() + retry_after
                        try:
                            asyncio.create_task(self._emit_granular_agent_event(agent_name, f"rate limited; retrying in {retry_after}s (attempt {retry_attempt}/{max_rate_limit_retries})", session_context.contextId))
                        except Exception:
                            pass

                        await asyncio.sleep(min(60, retry_after))

                        retry_request = MessageSendParams(
                            id=str(uuid.uuid4()),
                            message=Message(
                                role='user',
                                parts=[Part(root=TextPart(text=contextualized_message))],
                                messageId=str(uuid.uuid4()),
                                contextId=session_context.contextId,
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

                    return [f"Agent {agent_name} failed to complete the task"]

                elif task.status.state == TaskState.input_required:
                    log_debug(f"⚠️ [STREAMING] Agent {agent_name} requires input")
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
                
                # Store interaction in background
                asyncio.create_task(self._store_a2a_interaction_background(
                    outbound_request=request,
                    inbound_response=response,
                    agent_name=agent_name,
                    processing_time=time.time() - start_time,
                    span=span,
                    context_id=contextId
                ))
                
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
        enable_memory = getattr(session_context, 'enable_inter_agent_memory', True)
        is_agent_mode = hasattr(session_context, 'agent_mode') and session_context.agent_mode
        mode_label = "Agent Mode" if is_agent_mode else "Standard Mode"
        
        context_parts = []
        
        # Primary approach: Use semantic memory search for relevant context (only if enabled)
        try:
            memory_results = await self._search_relevant_memory(
                query=message,
                context_id=session_context.contextId,
                agent_name=None,
                top_k=5
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
                        
                        # Method 1: Look for direct content field in inbound response
                        if 'inbound_payload' in result and result['inbound_payload']:
                            inbound = result['inbound_payload']
                            
                            # Parse JSON string if needed
                            if isinstance(inbound, str):
                                try:
                                    inbound = json.loads(inbound)
                                except json.JSONDecodeError:
                                    inbound = {}
                            
                            # Try direct content field (DocumentProcessor format)
                            if isinstance(inbound, dict) and 'content' in inbound:
                                content_summary = str(inbound['content'])
                            
                            # Try parts array (A2A Message structure)
                            elif isinstance(inbound, dict) and 'parts' in inbound:
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
                            
                            if isinstance(outbound, dict) and 'message' in outbound and 'parts' in outbound['message']:
                                parts_content = []
                                for part in outbound['message']['parts']:
                                    if isinstance(part, dict) and 'root' in part and 'text' in part['root']:
                                        parts_content.append(str(part['root']['text']))
                                if parts_content:
                                    content_summary = " ".join(parts_content)
                        
                        # Method 3: Fallback - try to extract any text from the raw result
                        if not content_summary:
                            # Convert entire result to string and look for meaningful content
                            result_str = str(result)
                            if len(result_str) > 50:  # Only if there's substantial content
                                content_summary = result_str
                        
                        # Add to context if we found content
                        if content_summary:
                            # Truncate long content for context efficiency
                            if len(content_summary) > self.memory_summary_max_chars:
                                content_summary = content_summary[: self.memory_summary_max_chars] + "..."
                            context_parts.append(f"  {i}. From {agent_name}: {content_summary}")
                        else:
                            print(f"⚠️ No content found in memory result {i} from {agent_name}")
                    
                    except Exception as e:
                        print(f"⚠️ Error processing memory result {i}: {e}")
                        continue
            
            else:
                log_debug(f"🧠 No relevant memory context found")
        
        except Exception as e:
            print(f"❌ Error searching memory: {e}")
            context_parts.append("Note: Unable to retrieve relevant context from memory")
        else:
            log_debug(f"🎯 [{mode_label}] Inter-agent memory disabled - skipping vector search")
        
        # Include recent host-side turns (previous agent outputs)
        # Behavior depends on mode and inter-agent memory setting:
        # - Agent Mode + Memory OFF: Only immediate previous agent (limit=1)
        # - Agent Mode + Memory ON: Last few agents (limit=self.last_host_turns)
        # - Standard Mode: Always use self.last_host_turns setting
        if self.include_last_host_turn:
            history: List[Dict[str, str]] = list(getattr(session_context, "host_turn_history", []))

            # Back-compat: fall back to single cached turn if list empty
            if not history and getattr(session_context, "last_host_turn_text", None):
                history = [
                    {
                        "agent": getattr(session_context, "last_host_turn_agent", "host_agent"),
                        "text": getattr(session_context, "last_host_turn_text", ""),
                    }
                ]

            # Determine how many previous responses to include
            if is_agent_mode and not enable_memory:
                # Agent Mode with memory OFF: Only pass immediate previous agent
                max_turns = 1
                log_debug(f"🎯 [Agent Mode] Memory disabled - passing only immediate previous agent output")
            else:
                # Standard mode or Agent Mode with memory ON: Use configured limit
                max_turns = self.last_host_turns
                log_debug(f"🎯 [{mode_label}] Passing up to {max_turns} recent agent outputs")

            selected: List[Dict[str, str]] = []
            for entry in reversed(history):  # newest first
                agent = entry.get("agent")
                text = (entry.get("text") or "").strip()
                if not text:
                    continue
                if target_agent_name and agent == target_agent_name:
                    continue
                selected.append({"agent": agent or "host_agent", "text": text})
                if len(selected) >= max_turns:
                    break

            if selected:
                logger.debug(
                    "[A2A] Injecting %d host turn(s) into message for %s",
                    len(selected),
                    target_agent_name or "unknown",
                )
                context_parts.append("Previous context from host conversation:")
                for idx, entry in enumerate(selected, start=1):
                    truncated_text = entry["text"]
                    if len(truncated_text) > self.last_host_turn_max_chars:
                        truncated_text = truncated_text[: self.last_host_turn_max_chars] + "..."
                    context_parts.append(f"  {idx}. From {entry['agent']}: {truncated_text}")
            else:
                logger.debug(
                    "[A2A] No eligible host turns to inject for agent %s",
                    target_agent_name,
                )

        # Fallback: Add minimal recent thread context only if memory search failed
        if not context_parts and thread_id:
            try:
                print(f"🧵 Fallback: Using recent thread context (memory search failed)")
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
                print(f"🧵 Added {len(context_parts)-1} recent messages to context")
            except Exception as e:
                print(f"❌ Error accessing thread context: {e}")
        
        # Combine context with original message
        if context_parts:
            full_context = "\n".join(context_parts)
            return f"{full_context}\n\nCurrent request: {message}"
        else:
            return message

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
            print(f"❌ Background A2A interaction storage failed for {agent_name}: {e}")
            # Don't let storage errors affect parallel execution

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
        
        Why we store interactions:
        - Enable "has this been asked before?" queries
        - Learn from past agent responses and patterns
        - Provide context for multi-turn conversations
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
                    log_debug(f"📡 [A2A PAYLOAD] Emitted A2A payload to WebSocket for {agent_name}")
                else:
                    log_debug("⚠️ WebSocket streamer not available for A2A payload emission")
            except Exception as ws_error:
                log_debug(f"⚠️ Failed to emit A2A payload to WebSocket: {ws_error}")
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
        artifact_info: Dict[int, Dict[str, str]] = None
    ):
        """Safe wrapper for User→Host memory storage that won't block conversation"""
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
            print(f"❌ User→Host interaction storage failed: {e}")
            log_error(f"Exception type: {type(e).__name__}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")

    async def _store_user_host_interaction(
        self,
        user_message_parts: List[Part],
        user_message_text: str,
        host_response: List[str],
        context_id: str,
        span: Any,
        artifact_info: Dict[int, Dict[str, str]] = None
    ):
        """Store User→Host A2A protocol exchange"""
        log_debug(f"🚀 _store_user_host_interaction: STARTING")
        print(f"- user_message_text: {user_message_text[:100]}...")
        print(f"- host_response count: {len(host_response)}")
        print(f"- context_id: {context_id}")
        print(f"- user_message_parts type: {type(user_message_parts)}")
        print(f"- user_message_parts length: {len(user_message_parts) if user_message_parts else 0}")
        
        try:
            log_debug(f"📝 Step 1: About to create A2A Message object...")
            
            # Create real A2A Message object for outbound
            log_debug(f"📝 Step 1a: Creating outbound_message with uuid...")
            message_id = str(uuid.uuid4())
            log_debug(f"📝 Step 1b: Generated messageId: {message_id}")
            
            log_debug(f"📝 Step 1c: About to create Message object...")
            # Clean file bytes from parts before storing in memory
            cleaned_parts = self._clean_file_bytes_from_parts(user_message_parts, artifact_info)
            log_debug(f"📝 Step 1d: Cleaned {len(user_message_parts)} parts for memory storage")
            
            outbound_message = Message(
                messageId=message_id,
                contextId=context_id,
                taskId=None,
                role="user",  # User→Host message
                parts=cleaned_parts  # Use cleaned A2A Parts without file bytes
            )
            print(f"✅ Step 1: Created outbound_message successfully")
            
            # Create real A2A MessageSendParams
            log_debug(f"📝 Step 2: About to create MessageSendParams...")
            request_id = str(uuid.uuid4())
            log_debug(f"📝 Step 2a: Generated request ID: {request_id}")
            
            log_debug(f"📝 Step 2b: About to create MessageSendConfiguration...")
            config = MessageSendConfiguration(
                acceptedOutputModes=["text", "text/plain", "image/png"]
            )
            print(f"✅ Step 2c: Created MessageSendConfiguration")
            
            log_debug(f"📝 Step 2d: About to create MessageSendParams...")
            outbound_request = MessageSendParams(
                id=request_id,
                message=outbound_message,
                configuration=config
            )
            print(f"✅ Step 2: Created MessageSendParams successfully")
            
            # Create real A2A Message object for inbound response
            log_debug(f"📝 Step 3: Creating inbound response parts...")
            response_parts = []
            for i, response in enumerate(host_response):
                # Skip artifact dicts - they're for UI display, not for memory storage
                if isinstance(response, dict) and ('artifact-uri' in response or 'artifact-id' in response):
                    log_debug(f"📝 Step 3.{i+1}: Skipping artifact dict (not storing in memory)")
                    continue
                    
                log_debug(f"📝 Step 3.{i+1}: Creating Part for response {i+1}")
                # Convert non-string responses to JSON string
                if isinstance(response, str):
                    text = response
                else:
                    text = json.dumps(response, ensure_ascii=False)
                text_part = TextPart(text=text)  # Don't pass kind - it's inferred from the class
                part = Part(root=text_part)
                response_parts.append(part)
                print(f"✅ Step 3.{i+1}: Created Part successfully")
            
            log_debug(f"📝 Step 4: Creating inbound Message...")
            inbound_message_id = str(uuid.uuid4())
            inbound_message = Message(
                messageId=inbound_message_id,
                contextId=context_id,
                taskId=None,
                role="agent",  # Host→User response (A2A uses 'agent' not 'assistant')
                parts=response_parts
            )
            print(f"✅ Step 4: Created inbound Message successfully")
            
            # Test model_dump before calling memory service
            try:
                outbound_dict = outbound_request.model_dump()
                print(f"✅ Step 5a: outbound_request.model_dump() worked")
            except Exception as e:
                return
                
            try:
                inbound_dict = inbound_message.model_dump()
            except Exception as e:
                return
            
            # Store the User→Host A2A interaction using real A2A objects
            log_debug(f"📝 Step 6: Storing User→Host interaction in memory...")
            
            # Extract session_id for tenant isolation
            session_id = get_tenant_from_context(context_id) if context_id else None
            
            if not session_id:
                log_debug(f"[A2A Memory] Warning: No session_id available, skipping user-host interaction storage for tenant isolation")
                return
            
            # Create interaction data structure like the working Host→Remote Agent code
            interaction_data = {
                "interaction_id": str(uuid.uuid4()),
                "agent_name": "host_agent",
                "processing_time_seconds": 1.0,
                "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                "outbound_payload": outbound_dict,
                "inbound_payload": inbound_dict
            }
            
            # Store in memory service with session_id for tenant isolation
            success = await a2a_memory_service.store_interaction(interaction_data, session_id=session_id)
            
            if success:
                print(f"✅ Step 6: User→Host interaction stored successfully (session: {session_id})")
                log_success(f"🎉 User→Host A2A interaction now available for semantic search")
            else:
                print(f"❌ Step 6: Failed to store User→Host interaction")
                print(f"⚠️ User→Host interaction storage failed")
                
        except Exception as e:
            print(f"❌ EXCEPTION in _store_user_host_interaction: {e}")
            log_error(f"Exception type: {type(e).__name__}")
            import traceback
            log_error(f"Full traceback: {traceback.format_exc()}")
            span.add_event("user_host_memory_store_error", {
                "context_id": context_id,
                "error": str(e)
            })

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

    async def run_conversation_with_parts(self, message_parts: List[Part], context_id: Optional[str] = None, event_logger=None, agent_mode: bool = False, enable_inter_agent_memory: bool = False, workflow: Optional[str] = None) -> Any:
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
        4. **Mode Selection**: Route to agent-mode orchestration or standard conversation
        5. **Response Synthesis**: Combine results from multiple agents if needed
        
        Agent Mode vs Standard Mode:
        - **Agent Mode**: AI orchestrator breaks down request into specialized tasks
        - **Standard Mode**: Single LLM call with tool use for agent delegation
        
        Args:
            message_parts: List of A2A Part objects (text, files, data)
            context_id: Conversation identifier for state management
            event_logger: Optional callback for logging conversation events
            agent_mode: If True, use multi-agent orchestration loop
            enable_inter_agent_memory: If True, agents can access conversation context
            workflow: Optional predefined workflow steps to execute
            
        Returns:
            List of response strings from the host agent
        """
        """Run conversation with A2A message parts (including files)."""
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
            
            log_debug(f"🔍 [run_conversation_with_parts] ENTRY - context_id param: {context_id}")
            
            # CRITICAL: context_id must be provided by caller (foundry_host_manager.process_message)
            # It should NEVER be None - if it is, that's a bug in the caller
            if not context_id:
                raise ValueError(f"context_id is required but was None or empty. This is a bug - foundry_host_manager should always provide context_id")
            
            log_debug(f"🔍 [run_conversation_with_parts] Using context_id: {context_id}")
            
            # CRITICAL: Store the context_id so send_message_sync can access it
            # This is THE source of truth for the current request's contextId
            self._current_host_context_id = context_id
            log_debug(f"🔍 [run_conversation_with_parts] SET _current_host_context_id to: {context_id}")
            
            # Extract text message for thread
            log_debug(f"Step: About to extract text message...")
            user_message = ""
            for part in message_parts:
                if hasattr(part, 'root') and part.root.kind == 'text':
                    user_message = part.root.text
                    break
            log_debug(f"Step: Extracted text message")
            
            log_debug(f"Extracted user message: {user_message}")
            print(f"Processing {len(message_parts)} parts including files")
            
            # Ensure agent is created (may be lazy creation if startup creation failed)
            log_debug(f"Step: About to ensure agent exists...")
            log_foundry_debug(f"Current agent state: {self.agent is not None}")
            if self.agent:
                log_foundry_debug(f"Agent exists with ID: {self.agent.get('id', 'unknown')}")
            else:
                print("⚠️ Agent not created at startup, creating now (lazy creation)...")
                log_foundry_debug(f"Calling create_agent()...")
                await self.create_agent()
                log_foundry_debug(f"create_agent() completed")
            log_debug(f"Step: Agent ready with ID: {self.agent.get('id', 'unknown') if self.agent else 'STILL_NULL'}")
            
            session_context = self.get_session_context(context_id)
            # Set agent mode in session context
            session_context.agent_mode = agent_mode
            session_context.enable_inter_agent_memory = enable_inter_agent_memory
            log_foundry_debug(f"Agent mode set to: {agent_mode}, Inter-agent memory: {enable_inter_agent_memory}")
            
            # HUMAN-IN-THE-LOOP: Check if an agent is waiting for input_required response
            hitl_result = await self._handle_pending_input_agent(
                session_context=session_context,
                message_parts=message_parts,
                context_id=context_id,
                event_logger=event_logger
            )
            if hitl_result is not None:
                return hitl_result
                
            # Reset any cached parts from prior turns so we don't resend stale attachments
            if hasattr(session_context, "_latest_processed_parts"):
                file_count_before = len(session_context._latest_processed_parts)
                log_foundry_debug(f"_latest_processed_parts has {file_count_before} parts before clearing check")
                log_foundry_debug(f"session_context.agent_mode = {session_context.agent_mode}")
                # In agent mode, preserve files so they flow between agents
                # In user mode, clear stale attachments from previous turns
                if not session_context.agent_mode:
                    print(f"⚠️ WARNING: Clearing {file_count_before} file parts because agent_mode is False")
                    session_context._latest_processed_parts = []
                    session_context._agent_generated_artifacts = []
                else:
                    # Keep files but log for debugging
                    file_count = len(session_context._latest_processed_parts)
                    print(f"📎 [Agent Mode] Preserving {file_count} file parts for agent-to-agent communication")
                    # Log file details for debugging
                    for idx, part in enumerate(session_context._latest_processed_parts):
                        if hasattr(part, 'root'):
                            if isinstance(part.root, FilePart):
                                file_name = getattr(part.root.file, 'name', 'unknown')
                                file_role = (part.root.metadata or {}).get("role", "no-role")
                                print(f"  • File {idx}: {file_name} (role={file_role})")
                            elif isinstance(part.root, DataPart) and isinstance(part.root.data, dict):
                                role = part.root.data.get('role', 'no-role')
                                name = part.root.data.get('file-name', 'unknown')
                                uri = part.root.data.get('artifact-uri', 'no-uri')
                                print(f"  • DataPart {idx}: {name} (role={role}, uri={uri[:50]}...)")
                        elif isinstance(part, dict):
                            role = part.get('role', 'no-role')
                            name = part.get('file-name', part.get('name', 'unknown'))
                            print(f"  • Dict {idx}: {name} (role={role})")
            
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
                        await self._emit_status_event("processing uploaded file", context_id)
                    else:
                        await self._emit_status_event(f"processing {file_count} uploaded files", context_id)
                    log_foundry_debug(f"File processing status emitted successfully")
                except Exception as e:
                    log_foundry_debug(f"❌ Exception emitting file processing status: {e}")
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
                    print(f"❌ CRITICAL ERROR in convert_part for part {i}: {e}")
                    import traceback
                    print(f"❌ CONVERT_PART TRACEBACK: {traceback.format_exc()}")
                    raise
            
            log_debug(f"Processed {len(processed_parts)} parts")

            # Convert processed results into A2A Part wrappers for delegation
            prepared_parts_for_agents: List[Part] = []
            for processed in processed_parts:
                prepared_parts_for_agents.extend(self._wrap_item_for_agent(processed))

            # Store prepared parts for sending to agents (includes user uploads for refinement)
            session_context._latest_processed_parts = prepared_parts_for_agents
            session_context._agent_generated_artifacts = []
            log_debug(f"📦 Prepared {len(prepared_parts_for_agents)} parts to attach for remote agents")
            
            # If files were processed, include information about them in the message
            file_info = []
            file_contents = []
            for result in processed_parts:
                if isinstance(result, DataPart) and hasattr(result, 'data'):
                    if 'artifact-id' in result.data:
                        file_info.append(f"File uploaded: {result.data.get('file-name', 'unknown')} (Artifact ID: {result.data['artifact-id']})")
                elif isinstance(result, str) and result.startswith("File:") and "Content:" in result:
                    # This is processed file content from uploaded files
                    print(f"📄 Found processed file content: {len(result)} characters")
                    file_contents.append(result)
            
            # Emit completion status if files were processed
            if file_count > 0 and (file_info or file_contents):
                if file_count == 1:
                    await self._emit_status_event("file processing completed", context_id)
                else:
                    await self._emit_status_event(f"all {file_count} files processed successfully", context_id)
            
            # Enhance user message with file information and content
            enhanced_message = user_message
            if file_info:
                enhanced_message = f"{user_message}\n\n[Files uploaded: {'; '.join(file_info)}]"
            if file_contents:
                enhanced_message = f"{enhanced_message}\n\n{''.join(file_contents)}"

            # Add image edit guidance if base/mask attachments detected
            image_guidance = self._build_image_edit_guidance(processed_parts)
            if image_guidance:
                enhanced_message = f"{image_guidance}\n\n{enhanced_message}" if enhanced_message else image_guidance
            
            log_debug(f"Enhanced message prepared")
            
            # =====================================================================
            # MODE DETECTION: Auto-detect based on workflow presence
            # =====================================================================
            use_orchestration = workflow and workflow.strip()
            
            if use_orchestration:
                log_debug(f"🎯 [Workflow Mode] Workflow detected - using orchestration loop")
                await self._emit_status_event("Starting workflow orchestration...", context_id)
                
                # Use agent mode orchestration loop
                try:
                    orchestration_outputs = await self._agent_mode_orchestration_loop(
                        user_message=enhanced_message,
                        context_id=context_id,
                        session_context=session_context,
                        event_logger=event_logger,
                        workflow=workflow
                    )
                    
                    # WORKFLOW MODE: Combine outputs into single response without calling agents
                    # The orchestration loop has executed all workflow steps in order
                    print(f"✅ [Workflow Mode] Workflow completed - {len(orchestration_outputs)} task outputs")
                    log_debug(f"✅ [Workflow Mode] All workflow steps completed, combining outputs")
                    
                    # Combine all task outputs into a single coherent response
                    if orchestration_outputs:
                        combined_response = "\n\n".join(orchestration_outputs)
                        log_debug(f"✅ [Workflow Mode] Combined {len(orchestration_outputs)} outputs into single response")
                    else:
                        combined_response = "Workflow completed successfully."
                    
                    # Return as single response (not a list)
                    final_responses = [combined_response]
                    
                    # Store the interaction and return
                    log_debug("About to store User→Host interaction for context_id: {context_id}")
                    await self._store_user_host_interaction_safe(
                        user_message_parts=message_parts,
                        user_message_text=enhanced_message,
                        host_response=final_responses,
                        context_id=context_id,
                        span=span
                    )
                    
                    log_debug(f"🎯 [Workflow Mode] Orchestration complete, returning 1 combined response")
                    return final_responses
                    
                except Exception as e:
                    log_error(f"[Agent Mode] Orchestration error: {e}")
                    import traceback
                    traceback.print_exc()
                    
                    # Get error type and message
                    error_type = type(e).__name__
                    error_msg = str(e) if str(e) else error_type
                    
                    # If synthesis failed but we have agent outputs, return them directly
                    if orchestration_outputs:
                        print(f"⚠️ [Agent Mode] Synthesis failed ({error_msg}), but returning {len(orchestration_outputs)} agent outputs directly")
                        final_responses = orchestration_outputs
                        
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
                                log_debug(f"📦 [Agent Mode] Including {len(artifact_dicts)} agent-generated artifact(s) in fallback response")
                                final_responses.extend(artifact_dicts)
                        
                        return final_responses
                    else:
                        # No outputs to return, show error
                        final_responses = [f"Agent Mode orchestration encountered an error: {error_msg}"]
                        return final_responses
            
            # Continue with standard conversation flow using Responses API (streaming)
            log_foundry_debug(f"=================== STARTING RESPONSE CREATION ===================")
            log_foundry_debug(f"Creating response with Responses API (streaming)")
            await self._emit_status_event("creating AI response with streaming", context_id)
            
            # Get tools for this agent
            tools = self._format_tools_for_responses_api()
            
            # Create streaming response
            response = await self._create_response_with_streaming(
                user_message=enhanced_message,
                context_id=context_id,
                session_context=session_context,
                tools=tools,
                instructions=self.agent.get('instructions', ''),
                event_logger=event_logger
            )
            
            log_foundry_debug(f"Response created successfully with ID: {response['id']}, status: {response['status']}")
            log_foundry_debug(f"=================== RESPONSE CREATED SUCCESSFULLY ===================")
            await self._emit_status_event(f"AI response created - status: {response['status']}", context_id)
            
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
                await self._emit_status_event(f"executing tools (attempt {tool_iteration})", context_id)
                
                # Execute all tool calls from this response
                tool_outputs = await self._execute_tool_calls_from_response(
                    tool_calls=response.get('tool_calls', []),
                    context_id=context_id,
                    session_context=session_context,
                    event_logger=event_logger
                )
                
                if tool_outputs:
                    last_tool_output = tool_outputs
                    await self._emit_status_event("tool execution completed, continuing conversation", context_id)
                    
                    # Create a new response with tool outputs to continue the conversation
                    # The tool outputs become part of the conversation history via previous_response_id chaining
                    response = await self._create_response_with_streaming(
                        user_message="",  # Empty message, tool outputs are in conversation history
                        context_id=context_id,
                        session_context=session_context,
                        tools=tools,
                        instructions=self.agent.get('instructions', ''),
                        event_logger=event_logger
                    )
                    log_foundry_debug(f"Created follow-up response after tool execution: {response['id']}, status: {response['status']}")
                else:
                    log_debug(f"⚠️ No tool outputs generated, breaking tool loop")
                    break
            
            log_foundry_debug(f"Tool handling loop completed. Final status: {response['status']}, iterations: {tool_iteration}")
            await self._emit_status_event("AI processing completed, finalizing response", context_id)
            
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
                if hasattr(session_context, '_agent_generated_artifacts'):
                    artifact_file_parts = []  # FilePart objects (standard format)
                    video_metadata_parts = []  # DataParts with video_metadata (for video_id tracking)
                    
                    for part in session_context._agent_generated_artifacts:
                        # Check if this is a video_metadata DataPart - keep it for later
                        target = getattr(part, 'root', part)
                        if isinstance(target, DataPart) and isinstance(target.data, dict):
                            if target.data.get('type') == 'video_metadata':
                                video_metadata_parts.append(part)
                                print(f"📎 [VideoRemix] Collected video_metadata with video_id: {target.data.get('video_id')}")
                                continue  # Don't convert to FilePart
                        
                        # Use utility to extract URI from any format
                        uri = extract_uri(part)
                        if uri and uri.startswith('http'):
                            # Convert to FilePart if not already
                            if is_file_part(part):
                                # Already a FilePart, use directly
                                actual_part = part.root if hasattr(part, 'root') and is_file_part(part.root) else part
                                artifact_file_parts.append(actual_part)
                                log_debug(f"📦 Found FilePart artifact: {uri[:80]}...")
                            else:
                                # Convert legacy DataPart to FilePart
                                file_part = convert_artifact_dict_to_file_part(part)
                                if file_part:
                                    artifact_file_parts.append(file_part)
                                    log_debug(f"📦 Converted DataPart to FilePart: {uri[:80]}...")
                    
                    # Group video FileParts with their metadata to preserve video_id for remix
                    if artifact_file_parts:
                        log_debug(f"📦 [Standard Mode] Including {len(artifact_file_parts)} FilePart artifact(s) in response")
                        
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
                            print(f"📦 [VideoRemix] Created combined message with {len(artifact_file_parts)} FileParts and {len(video_metadata_parts)} video_metadata")
                        
                        for idx, fp in enumerate(artifact_file_parts):
                            file_obj = getattr(fp, 'file', None)
                            uri = getattr(file_obj, 'uri', '') if file_obj else ''
                            filename = getattr(file_obj, 'name', 'unknown') if file_obj else 'unknown'
                            print(f"  • FilePart Artifact {idx+1}: {filename} (URI: {uri[:80]}...)")

                # If we have extracted content, prepend it to the response
                if has_extracted_content:
                    extracted_content_message = (
                        "The file has been processed. Here is the extracted content:\n\n" + 
                        "\n\n---\n\n".join(extracted_contents)
                    )
                    log_debug(f"📝 Prepending extracted content to response...")
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
                
                # Store User→Host A2A interaction (fire-and-forget)
                log_debug(f"About to store User→Host interaction for context_id: {context_id}")
                
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
                    artifact_info=artifact_info  # Pass artifact info for URI replacement
                ))
                
                log_foundry_debug(f"About to return final_responses: {final_responses} (FIRST PATH)")
                
                return final_responses
        
        except Exception as e:
            print(f"❌ CRITICAL ERROR in run_conversation_with_parts: {e}")
            import traceback
            print(f"❌ FULL TRACEBACK: {traceback.format_exc()}")
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
            await self._emit_status_event(f"executing {len(tool_calls)} tool(s)", context_id)
            
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
                await self._emit_status_event(f"calling {len(send_message_tool_calls)} agent(s) in parallel", context_id)
                
                # Create tasks for all send_message calls
                for tool_call, function_name, arguments in send_message_tool_calls:
                    agent_name = arguments.get("agent_name")
                    message = arguments.get("message", "")
                    
                    # Add status message for each agent call
                    self._add_status_message_to_conversation(f"🛠️ Executing tool: send_message to {agent_name}", context_id)
                    await self._emit_status_event(f"calling {agent_name} agent", context_id)
                    
                    # Enhanced agent selection tracking
                    span.add_event("parallel_agent_selected", {
                        "agent_name": agent_name,
                        "message_preview": message[:50] + "..." if len(message) > 50 else message
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
                    
                    # FIXED: Use shared session context for parallel execution
                    # This ensures all parallel agents share the same conversation context
                    # Note: suppress_streaming=True prevents duplicate responses in chat (only host responds)
                    # while remote agent streaming for thinking box visibility works through task callback
                    tool_context = DummyToolContext(session_context, self._azure_blob_client)
                    task = self.send_message(agent_name, message, tool_context, suppress_streaming=True)
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
                    await self._emit_status_event("all agent calls completed", context_id)
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
                await self._emit_status_event(f"executing {function_name} tool", context_id)
                
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
        rval = []
        log_debug(f"convert_parts: processing {len(parts)} parts")
        session_context = getattr(tool_context, "state", None)
        
        # In agent mode, preserve existing parts; otherwise start fresh
        if session_context is not None:
            if hasattr(session_context, "agent_mode") and session_context.agent_mode:
                # Agent mode: Preserve existing files from previous agents
                latest_parts = getattr(session_context, "_latest_processed_parts", [])
                log_debug(f"📎 [Agent Mode] Preserving {len(latest_parts)} existing file parts from previous agents")
            else:
                # User mode: Start fresh for each response
                latest_parts: List[Any] = []
            setattr(session_context, "_latest_processed_parts", latest_parts)
        else:
            latest_parts: List[Any] = []

        for i, p in enumerate(parts):
            result = await self.convert_part(p, tool_context, context_id)
            if result is None:
                continue
            if isinstance(result, list):
                rval.extend(result)
            else:
                rval.append(result)

        # URI tracking for deduplication
        uri_to_parts: Dict[str, List[Any]] = {}
        assigned_roles: Dict[str, str] = {}

        def _register_part_uri(part: Any, uri: Optional[str]) -> None:
            normalized_uri = self._normalize_uri(uri)
            if not normalized_uri:
                return
            uri_to_parts.setdefault(normalized_uri, []).append(part)

        def _register_role(uri: Optional[str], role: Optional[str]) -> None:
            if not role:
                return
            normalized_uri = self._normalize_uri(uri)
            if not normalized_uri:
                return
            assigned_roles[normalized_uri] = str(role).lower()

        # Use centralized utility for URI extraction
        def _local_extract_uri(part: Any) -> Optional[str]:
            return extract_uri(part)

        flattened_parts = []
        pending_file_parts: List[FilePart] = []
        refine_payload = None

        for item in rval:
            if isinstance(item, DataPart):
                if hasattr(item, "data") and isinstance(item.data, dict):
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

                    if artifact_uri:
                        # Create FileWithUri for remote agent processing
                        file_with_uri_kwargs = {
                            "name": item.data.get("file-name", metadata["artifact-id"]) or metadata["artifact-id"],
                            "mimeType": item.data.get("media-type", "application/octet-stream"),
                            "uri": artifact_uri,
                        }
                        
                        # Create FilePart with metadata containing role (remote agents check p.metadata.role)
                        file_part_kwargs = {"file": FileWithUri(**file_with_uri_kwargs)}
                        if role_value:
                            file_part_kwargs["metadata"] = {"role": role_value}
                            log_debug(f"🎭 Creating FilePart with metadata role='{role_value}' for {file_with_uri_kwargs['name']}")
                        
                        file_part = FilePart(**file_part_kwargs)
                        flattened_parts.append(file_part)
                        pending_file_parts.append(file_part)
                        _register_part_uri(file_part, artifact_uri)
                        if role_value:
                            _register_role(artifact_uri, role_value)

                    if "extracted_content" in item.data:
                        flattened_parts.append(
                            TextPart(text=str(item.data["extracted_content"]))
                        )
                else:
                    flattened_parts.append(TextPart(text=str(item.data)))
            elif isinstance(item, (TextPart, FilePart, DataPart)):
                flattened_parts.append(item)
                _register_part_uri(item, _local_extract_uri(item))
            elif isinstance(item, dict):
                if item.get("kind") == "refine-image":
                    refine_payload = item
                elif "artifact-uri" in item or "artifact-id" in item:
                    # This is artifact metadata from an agent - wrap in DataPart
                    artifact_uri = item.get("artifact-uri", "")
                    log_debug(f"📦 [DEBUG] Wrapping artifact dict in DataPart:")
                    log_debug(f"   artifact-uri (first 150 chars): {artifact_uri[:150]}")
                    log_debug(f"   Has SAS token (?): {'?' in artifact_uri}")
                    artifact_data_part = DataPart(data=item)
                    flattened_parts.append(artifact_data_part)
                    # Don't add to latest_parts here - it will be added via extend below to avoid duplicates
                    _register_part_uri(artifact_data_part, item.get("artifact-uri"))
                    if item.get("role"):
                        _register_role(item.get("artifact-uri"), item.get("role"))
                else:
                    text = item.get("response") or item.get("text") or json.dumps(item, ensure_ascii=False)
                    flattened_parts.append(TextPart(text=text))
            elif item is not None:
                flattened_parts.append(TextPart(text=str(item)))

        # Add all flattened parts to latest_parts (includes artifacts already wrapped in DataParts above)
        latest_parts.extend(flattened_parts)

        if refine_payload:
            refine_part = DataPart(data=refine_payload)
            flattened_parts.append(refine_part)
            latest_parts.append(refine_part)

        # If we collected file parts, ensure downstream agents can access them
        if pending_file_parts:
            latest_parts.extend(pending_file_parts)

        base_uri_hint = self._normalize_uri((refine_payload or {}).get("image_url"))
        mask_uri_hint = self._normalize_uri((refine_payload or {}).get("mask_url"))

        if base_uri_hint or mask_uri_hint:
            for part in flattened_parts:
                candidate_uri = self._normalize_uri(_local_extract_uri(part))
                if base_uri_hint and candidate_uri == base_uri_hint:
                    self._apply_role_to_part(part, "base")
                    _register_role(candidate_uri, "base")
                if mask_uri_hint and candidate_uri == mask_uri_hint:
                    self._apply_role_to_part(part, "mask")
                    _register_role(candidate_uri, "mask")

        for uri_value, parts_list in uri_to_parts.items():
            if assigned_roles.get(uri_value):
                continue
            
            # Check if this is a generated/edited artifact - don't assign default overlay role
            # Extract filename from URI to check
            file_name_from_uri = uri_value.split('/')[-1].split('?')[0].lower() if uri_value else ""
            is_generated_artifact = "generated_" in file_name_from_uri or "edit_" in file_name_from_uri
            
            if is_generated_artifact:
                log_debug(f"Skipping default 'overlay' role for generated artifact: {file_name_from_uri}")
                # Don't assign any role - keep generated artifacts separate for display
                continue
            
            # For other files (user uploads, logos, etc.), assign overlay as default
            for part in parts_list:
                self._apply_role_to_part(part, "overlay")
            assigned_roles[uri_value] = "overlay"

        def _apply_assigned_roles(parts: Iterable[Any]) -> None:
            for part in parts:
                uri = self._normalize_uri(_local_extract_uri(part))
                if not uri:
                    continue
                role_for_uri = assigned_roles.get(uri)
                if role_for_uri:
                    self._apply_role_to_part(part, role_for_uri)

        _apply_assigned_roles(flattened_parts)
        _apply_assigned_roles(latest_parts)

        # DEBUG: Log what we're returning
        log_foundry_debug(f"convert_parts returning {len(flattened_parts)} parts:")
        for idx, part in enumerate(flattened_parts):
            if isinstance(part, (TextPart, DataPart, FilePart)):
                log_debug(f"  • Part {idx}: {type(part).__name__} (kind={getattr(part, 'kind', 'N/A')})")
            elif isinstance(part, dict):
                log_debug(f"  • Part {idx}: dict with keys={list(part.keys())}")
            elif isinstance(part, str):
                log_debug(f"  • Part {idx}: string (length={len(part)})")
            else:
                log_debug(f"  • Part {idx}: {type(part)}")

        return flattened_parts

    async def convert_part(self, part: Part, tool_context: Any, context_id: str = None):
        """
        Convert A2A Part objects into formats suitable for processing and agent delegation.
        
        Part types and their handling:
        
        1. **TextPart**: Simple text content, passed through unchanged
        
        2. **FilePart**: Uploaded files requiring processing
           - Extract text from PDFs, Word docs, etc. using document processor
           - Store in Azure Blob Storage or local filesystem
           - Generate artifact URIs for agent access
           - Handle special cases like image masks for editing
        
        3. **DataPart**: Structured data or metadata
           - JSON objects with agent-specific information
           - Configuration parameters
           - File metadata and references
        
        File processing workflow:
        - Validate file size (50MB limit for security)
        - Determine storage strategy (blob vs local based on size)
        - Extract text content using Azure AI Document Intelligence
        - Create artifact with unique ID and accessible URI
        - Return metadata for agent consumption
        
        Special handling for image editing:
        - Base images: Source image to be edited
        - Mask images: Transparency mask defining edit regions
        - Overlay images: Images to composite onto base
        
        Args:
            part: A2A Part object to convert
            tool_context: Context with artifact storage and session state
            context_id: Optional conversation context for status updates
            
        Returns:
            Converted part(s) ready for agent consumption or host processing
        """
        # Don't print the entire part (contains large base64 data)
        if hasattr(part, 'root') and part.root.kind == 'file':
            file_name = getattr(part.root.file, 'name', 'unknown')
            mime_type = getattr(part.root.file, 'mimeType', 'unknown')
            log_debug(f"convert_part: FilePart - name: {file_name}, mimeType: {mime_type}")
            
            # Emit status event for file processing
            if context_id:
                await self._emit_status_event(f"processing file: {file_name}", context_id)
        else:
            log_debug(f"convert_part: {type(part)} - kind: {getattr(part.root, 'kind', 'unknown') if hasattr(part, 'root') else 'no root'}")
        
        # Handle dicts coming from streaming conversions or patched remote agents
        if isinstance(part, dict):
            # Simple heuristic: if it looks like {'kind': 'text', 'text': '...'}
            if part.get('kind') == 'text' and 'text' in part:
                text_content = part['text']
                log_debug(f"convert_part: dict text content: {text_content[:200]}...")
                return text_content
            if part.get('kind') == 'data' and 'data' in part:
                return part['data']
            # Fallthrough – stringify the dict
            return json.dumps(part)

        # Fallback to standard A2A Part handling
        if hasattr(part, 'root') and part.root.kind == 'text':
            text_content = part.root.text or ""
            log_debug(f"convert_part: text part content: {text_content[:200]}...")

            # Check for [refine-image] markers (image editing workflow)
            refine_matches = list(re.finditer(r"\[refine-image\]\s+(https?://\S+)", text_content, flags=re.IGNORECASE))
            if refine_matches:
                mask_matches = list(re.finditer(r"\[refine-mask\]\s+(https?://\S+)", text_content, flags=re.IGNORECASE))
                image_url = refine_matches[-1].group(1)
                mask_url = mask_matches[-1].group(1) if mask_matches else None

                # Strip markers from text
                cleaned_text = re.sub(r"\[refine-image\]\s+https?://\S+", "", text_content, flags=re.IGNORECASE)
                cleaned_text = re.sub(r"\[refine-mask\]\s+https?://\S+", "", cleaned_text, flags=re.IGNORECASE)

                refine_data = {"kind": "refine-image", "image_url": image_url}
                if mask_url:
                    refine_data["mask_url"] = mask_url

                self._store_parts_in_session(tool_context, DataPart(data=refine_data))
                log_debug(f"convert_part: captured refine request with image_url={image_url}")

                return cleaned_text.strip() or "Refine the previous image."

            return text_content
        elif hasattr(part, 'root') and part.root.kind == 'data':
            data = part.root.data
            # Skip token_usage DataParts - already extracted earlier, not for main chat
            if isinstance(data, dict) and data.get('type') == 'token_usage':
                return None
            log_debug(f"DataPart data: {data} (type: {type(data)})")
            # IMPORTANT: Preserve DataPart wrapper for metadata types that need to flow through
            # (video_metadata, image_metadata, etc.) so they can be detected by artifact processing
            if isinstance(data, dict) and data.get('type') in ('video_metadata', 'image_metadata'):
                log_debug(f"📎 [VideoRemix] Preserving DataPart wrapper for {data.get('type')} with video_id={data.get('video_id')}")
                return part  # Return the full Part(root=DataPart(...)) to preserve structure
            return data
        elif hasattr(part, 'root') and part.root.kind == 'file':
            # A2A protocol compliant file handling
            file_id = part.root.file.name
            log_debug(f"Processing file: {file_id}")
            
            file_role_attr = getattr(part.root.file, 'role', None)
            
            # Load file bytes from URI, inline bytes, or HTTP download
            file_bytes, load_error = self._load_file_bytes(part.root.file, context_id)
            if load_error:
                log_debug(f"File load error: {load_error}")
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
                    await self._emit_status_event(f"file processed successfully: {file_id}", context_id)
                
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
                        await self._emit_status_event(f"file processed successfully: {file_id}", context_id)
                    
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
            print(f"🤝 Self-registration request from agent at: {agent_address}")
            
            if agent_card:
                # Use provided agent card
                print(f"✅ Using provided agent card: {agent_card.name}")
                self.register_agent_card(agent_card)
            else:
                # Retrieve agent card from address
                print(f"🔍 Retrieving agent card from: {agent_address}")
                await self.retrieve_card(agent_address)
            
            log_success(f"Successfully registered remote agent from: {agent_address}")
            print(f"📊 Total registered agents: {len(self.remote_agent_connections)}")
            log_debug(f"📋 Agent names: {list(self.remote_agent_connections.keys())}")
            
            # Agent will appear in UI sidebar within 15 seconds via periodic sync
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to register remote agent from {agent_address}: {e}")
            import traceback
            print(f"❌ Registration error traceback: {traceback.format_exc()}")
            return False

    async def unregister_remote_agent(self, agent_name: str) -> bool:
        """Handle unregistration of remote agents.
        
        Args:
            agent_name: The name of the agent to unregister
            
        Returns:
            bool: True if unregistration successful, False otherwise
        """
        try:
            print(f"🗑️ Unregistration request for agent: {agent_name}")
            
            # Check if agent exists
            if agent_name not in self.remote_agent_connections and agent_name not in self.cards:
                print(f"❌ Agent {agent_name} not found in registry")
                return False
            
            # Remove from remote_agent_connections
            if agent_name in self.remote_agent_connections:
                del self.remote_agent_connections[agent_name]
                print(f"✅ Removed {agent_name} from remote_agent_connections")
            
            # Remove from cards
            if agent_name in self.cards:
                del self.cards[agent_name]
                print(f"✅ Removed {agent_name} from cards")
            
            # Update the agents list used in prompts
            self.agents = json.dumps(self.list_remote_agents(), indent=2)
            print(f"✅ Updated agents list for prompts")
            
            log_success(f"Successfully unregistered agent: {agent_name}")
            print(f"📊 Total registered agents: {len(self.remote_agent_connections)}")
            log_debug(f"📋 Agent names: {list(self.remote_agent_connections.keys())}")
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to unregister agent {agent_name}: {e}")
            import traceback
            print(f"❌ Unregistration error traceback: {traceback.format_exc()}")
            return False

    @staticmethod
    def create_with_shared_client(remote_agent_addresses: List[str], task_callback: Optional[TaskUpdateCallback] = None, enable_task_evaluation: bool = True, create_agent_at_startup: bool = False):
        """
        Factory method to create a FoundryHostAgent2 with a shared httpx.AsyncClient and optional task evaluation.
        
        Note: create_agent_at_startup defaults to False since Responses API is stateless and doesn't need agent creation.
        """
        shared_client = httpx.AsyncClient()
        return FoundryHostAgent2(remote_agent_addresses, http_client=shared_client, task_callback=task_callback, enable_task_evaluation=enable_task_evaluation, create_agent_at_startup=create_agent_at_startup)

    def set_host_manager(self, host_manager):
        """Set reference to the host manager for UI integration."""
        self._host_manager = host_manager

    def _add_status_message_to_conversation(self, status_text: str, contextId: str):
        """Add a status message directly to the conversation for immediate UI display."""
        # Use WebSocket streaming for real-time status updates
        asyncio.create_task(self._emit_granular_agent_event("foundry-host-agent", status_text, contextId))

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

