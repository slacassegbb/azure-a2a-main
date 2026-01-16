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
from datetime import datetime
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
from pydantic import BaseModel, Field

# Tenant utilities for multi-tenancy support
from utils.tenant import get_tenant_from_context
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

def get_context_id(obj: Any, default: str = None) -> str:
    """
    Extract contextId from an object with fallback support for both camelCase and snake_case naming conventions.
    Returns a new UUID if no context ID is found.
    """
    try:
        if hasattr(obj, 'contextId') and obj.contextId is not None:
            return obj.contextId
        if hasattr(obj, 'context_id') and obj.context_id is not None:
            return obj.context_id
        return getattr(obj, 'contextId', getattr(obj, 'context_id', default or str(uuid.uuid4())))
    except Exception:
        return default or str(uuid.uuid4())

def get_message_id(obj: Any, default: str = None) -> str:
    """
    Extract messageId from an object with fallback support for both camelCase and snake_case naming conventions.
    Returns a new UUID if no message ID is found.
    """
    try:
        if hasattr(obj, 'messageId') and obj.messageId is not None:
            return obj.messageId
        if hasattr(obj, 'message_id') and obj.message_id is not None:
            return obj.message_id
        return getattr(obj, 'messageId', getattr(obj, 'message_id', default or str(uuid.uuid4())))
    except Exception:
        return default or str(uuid.uuid4())

def get_task_id(obj: Any, default: str = None) -> str:
    """
    Extract taskId from an object with fallback support for multiple naming conventions (taskId, task_id, or id).
    Returns a new UUID if no task ID is found.
    """
    try:
        if hasattr(obj, 'taskId') and obj.taskId is not None:
            return obj.taskId
        if hasattr(obj, 'task_id') and obj.task_id is not None:
            return obj.task_id
        if hasattr(obj, 'id') and obj.id is not None:
            return obj.id
        return getattr(obj, 'taskId', getattr(obj, 'task_id', getattr(obj, 'id', default or str(uuid.uuid4()))))
    except Exception:
        return default or str(uuid.uuid4())


def _normalize_env_bool(raw_value: str | None, default: bool = False) -> bool:
    """Parse boolean environment variable with support for common true/false representations."""
    if raw_value is None:
        return default
    normalized = raw_value.strip().strip('"').strip("'").lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _normalize_env_int(raw_value: str | None, default: int) -> int:
    """Parse integer environment variable with support for quoted values."""
    if raw_value is None:
        return default
    try:
        return int(raw_value.strip().strip('"').strip("'"))
    except (TypeError, ValueError):
        return default

class SessionContext(BaseModel):
    """
    Session state management for A2A protocol conversations.
    Tracks conversation context, task states, and agent coordination across multi-agent workflows.
    """
    contextId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: Optional[str] = None
    message_id: Optional[str] = None
    task_state: Optional[str] = None
    session_active: bool = True
    retry_count: int = 0
    agent_mode: bool = False
    enable_inter_agent_memory: bool = True
    agent_task_ids: dict[str, str] = Field(default_factory=dict)
    agent_task_states: dict[str, str] = Field(default_factory=dict)
    agent_cooldowns: dict[str, float] = Field(default_factory=dict)
    last_host_turn_text: Optional[str] = Field(default=None)
    last_host_turn_agent: Optional[str] = Field(default=None)
    host_turn_history: List[Dict[str, str]] = Field(default_factory=list)
    # Human-in-the-loop tracking: which agent is waiting for user input
    pending_input_agent: Optional[str] = Field(default=None, description="Agent name waiting for input_required response")
    pending_input_task_id: Optional[str] = Field(default=None, description="Task ID of the pending input_required task")
    # Workflow state for pausing/resuming on input_required
    pending_workflow: Optional[str] = Field(default=None, description="Workflow definition to resume after HITL completes")
    pending_workflow_outputs: List[str] = Field(default_factory=list, description="Task outputs collected before HITL pause")
    pending_workflow_user_message: Optional[str] = Field(default=None, description="Original user message for workflow")


# Agent Mode Orchestration Models
TaskStateEnum = Literal["pending", "running", "completed", "failed", "cancelled"]
GoalStatus = Literal["incomplete", "completed"]


class AgentModeTask(BaseModel):
    """Individual task within a multi-agent workflow plan."""
    task_id: str = Field(..., description="Unique A2A task identifier.")
    task_description: str = Field(..., description="Single remote-agent instruction.")
    recommended_agent: Optional[str] = Field(None, description="Agent name to execute this task.")
    output: Optional[Dict[str, Any]] = Field(None, description="A2A remote-agent output payload.")
    state: TaskStateEnum = Field("pending", description="Current A2A task state.")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    error_message: Optional[str] = Field(None, description="Error message if task failed.")


class AgentModePlan(BaseModel):
    """Multi-agent workflow plan with task decomposition and state tracking."""
    goal: str = Field(..., description="User query or objective.")
    goal_status: GoalStatus = Field("incomplete", description="Completion state of the goal.")
    tasks: List[AgentModeTask] = Field(default_factory=list, description="List of all tasks in the plan.")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class NextStep(BaseModel):
    """Orchestrator decision for the next action in a multi-agent workflow."""
    goal_status: GoalStatus = Field(..., description="Whether the goal is completed or not.")
    next_task: Optional[Dict[str, Optional[str]]] = Field(
        None,
        description='{"task_description": str, "recommended_agent": str|None} if incomplete, else null.'
    )
    reasoning: str = Field(..., description="Short explanation of the decision.")


class FoundryHostAgent2:
    def __init__(
        self,
        remote_agent_addresses: List[str],
        http_client: httpx.AsyncClient,
        task_callback: Optional[TaskUpdateCallback] = None,
        enable_task_evaluation: bool = False,
        create_agent_at_startup: bool = True,
    ):
        """
        Initialize the Foundry Host Agent with Azure AI Foundry backend and multi-agent coordination.
        
        Args:
            remote_agent_addresses: List of remote agent URLs to connect to
            http_client: Shared HTTP client for agent communication
            task_callback: Optional callback for task status updates
            enable_task_evaluation: Whether to evaluate task completion quality
            create_agent_at_startup: Whether to create the Azure AI agent immediately
        """
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        
        try:
            log_foundry_debug("Initializing Azure authentication with timeout handling...")
            print("💡 TIP: If you see authentication errors, run 'python test_azure_auth.py' to diagnose")
            
            from azure.identity import AzureCliCredential, DefaultAzureCredential, ChainedTokenCredential
            
            cli_credential = AzureCliCredential(process_timeout=5)
            
            self.credential = ChainedTokenCredential(
                cli_credential,
                DefaultAzureCredential(exclude_interactive_browser_credential=True)
            )
            log_foundry_debug("✅ Using ChainedTokenCredential (AzureCLI + DefaultAzure) with 5s timeout")
                    
        except Exception as e:
            log_foundry_debug(f"⚠️ Credential initialization failed: {e}")
            print("💡 DEBUG: Falling back to DefaultAzureCredential only")
            from azure.identity import DefaultAzureCredential
            self.credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
            log_foundry_debug("✅ Using DefaultAzureCredential as fallback")
            
        self.agent: Optional[Dict[str, Any]] = None
        self.task_callback = task_callback or self._default_task_callback
        self.httpx_client = http_client
        self.remote_agent_connections: Dict[str, RemoteAgentConnections] = {}
        self.cards: Dict[str, AgentCard] = {}
        self.agents: str = ''
        self.session_contexts: Dict[str, SessionContext] = {}
        self.threads: Dict[str, str] = {}
        self.default_contextId = str(uuid.uuid4())
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
        self.last_host_turn_max_chars = _normalize_env_int(
            os.environ.get("A2A_LAST_HOST_TURN_MAX_CHARS"),
            1500,  # Default: ~500 tokens of context
        )
        
        # Number of recent agent interactions to include in context (1-5 turns)
        self.last_host_turns = max(
            1,
            min(
                5,
                _normalize_env_int(os.environ.get("A2A_LAST_HOST_TURNS"), 1),
            ),
        )
        
        # Maximum characters for memory search summaries
        self.memory_summary_max_chars = max(
            200,
            _normalize_env_int(os.environ.get("A2A_MEMORY_SUMMARY_MAX_CHARS"), 2000),
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

    async def set_session_agents(self, session_agents: List[Dict[str, Any]]):
        """Set the available agents for this session/request.
        
        This clears existing agents and sets only the provided session agents.
        Called before processing each request to ensure session isolation.
        
        Args:
            session_agents: List of agent dicts with url, name, description, skills, etc.
        """
        # Clear existing agents
        self.cards.clear()
        self.remote_agent_connections.clear()
        self.agents = ''
        
        # Register each session agent
        for agent_data in session_agents:
            agent_url = agent_data.get('url')
            if agent_url:
                try:
                    await self.retrieve_card(agent_url)
                    log_debug(f"✅ Session agent registered: {agent_data.get('name', agent_url)}")
                except Exception as e:
                    log_debug(f"⚠️ Failed to register session agent {agent_url}: {e}")
        
        log_debug(f"📋 Session now has {len(self.cards)} agents: {list(self.cards.keys())}")

    def _find_agent_registry_path(self) -> Path:
        """Resolve the agent registry path within the backend/data directory."""
        backend_root = Path(__file__).resolve().parents[2]
        registry_path = backend_root / "data" / "agent_registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        if registry_path.exists():
            log_debug(f"📋 Found agent registry at: {registry_path}")
        else:
            log_debug(f"📋 Agent registry will be created at: {registry_path}")
        return registry_path

    def _load_agent_registry(self) -> List[Dict[str, Any]]:
        """Load agent registry from JSON file."""
        try:
            if self._agent_registry_path.exists():
                with open(self._agent_registry_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                log_debug(f"📋 Agent registry file not found at {self._agent_registry_path}, returning empty list")
                return []
        except Exception as e:
            print(f"❌ Error loading agent registry: {e}")
            return []

    def _save_agent_registry(self, agents: List[Dict[str, Any]]):
        """Save agent registry to JSON file."""
        try:
            # Ensure directory exists
            self._agent_registry_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self._agent_registry_path, 'w', encoding='utf-8') as f:
                json.dump(agents, f, indent=2, ensure_ascii=False)
            log_debug(f"📋 Saved agent registry with {len(agents)} agents to {self._agent_registry_path}")
        except Exception as e:
            print(f"❌ Error saving agent registry: {e}")

    def _agent_card_to_dict(self, card: AgentCard) -> Dict[str, Any]:
        """Convert AgentCard object to dictionary for JSON serialization in the agent registry."""
        try:
            card_dict = {
                "name": card.name,
                "description": card.description,
                "version": getattr(card, 'version', '1.0.0'),
                "url": card.url,
                "defaultInputModes": getattr(card, 'defaultInputModes', ["text"]),
                "defaultOutputModes": getattr(card, 'defaultOutputModes', ["text"]),
            }
            
            if hasattr(card, 'capabilities') and card.capabilities:
                capabilities_dict = {}
                if hasattr(card.capabilities, 'streaming'):
                    capabilities_dict["streaming"] = card.capabilities.streaming
                card_dict["capabilities"] = capabilities_dict
            
            if hasattr(card, 'skills') and card.skills:
                skills_list = []
                for skill in card.skills:
                    skill_dict = {
                        "id": getattr(skill, 'id', ''),
                        "name": getattr(skill, 'name', ''),
                        "description": getattr(skill, 'description', ''),
                        "examples": getattr(skill, 'examples', []),
                        "tags": getattr(skill, 'tags', [])
                    }
                    skills_list.append(skill_dict)
                card_dict["skills"] = skills_list
            
            return card_dict
        except Exception as e:
            print(f"❌ Error converting agent card to dict: {e}")
            return {
                "name": getattr(card, 'name', 'Unknown'),
                "description": getattr(card, 'description', ''),
                "version": "1.0.0",
                "url": getattr(card, 'url', ''),
                "defaultInputModes": ["text"],
                "defaultOutputModes": ["text"]
            }

    def _update_agent_registry(self, card: AgentCard):
        """Persist agent card to registry file, updating existing entries or adding new ones."""
        try:
            registry = self._load_agent_registry()
            card_dict = self._agent_card_to_dict(card)
            
            existing_index = None
            # First, check by name (primary identifier)
            for i, existing_agent in enumerate(registry):
                if existing_agent.get("name") == card.name:
                    existing_index = i
                    break
            
            # If not found by name, check by URL (for backward compatibility)
            if existing_index is None:
                for i, existing_agent in enumerate(registry):
                    if existing_agent.get("url") == card.url:
                        existing_index = i
                        break
            
            if existing_index is not None:
                registry[existing_index] = card_dict
                log_debug(f"📋 Updated existing agent in registry: {card.name} at {card.url}")
            else:
                registry.append(card_dict)
                log_debug(f"📋 Added new agent to registry: {card.name} at {card.url}")
            
            self._save_agent_registry(registry)
            
        except Exception as e:
            print(f"❌ Error updating agent registry: {e}")

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
                print("✅ Azure Blob Storage initialized with connection string (sync client)")
                print(f"Connection string starts with: {azure_storage_connection_string[:50]}...")
                print(f"Azure storage account: {self._azure_blob_client.account_name}")
            elif azure_storage_account_name:
                from azure.storage.blob import BlobServiceClient
                account_url = f"https://{azure_storage_account_name}.blob.core.windows.net"
                self._azure_blob_client = BlobServiceClient(
                    account_url,
                    credential=self.credential,
                    api_version="2023-11-03",
                )
                print(f"✅ Azure Blob Storage initialized with managed identity (sync client): {account_url}")
            else:
                print("❌ Azure Blob Storage not configured - using local storage only")
                print(f"AZURE_STORAGE_CONNECTION_STRING: {azure_storage_connection_string}")
                print(f"AZURE_STORAGE_ACCOUNT_NAME: {azure_storage_account_name}")
                self._azure_blob_container = None
            
            if self._azure_blob_client:
                print(f"🪣 Target Azure Blob container: {self._azure_blob_container}")
                loop = asyncio.get_running_loop()
                loop.create_task(self._verify_blob_connection())
            else:
                print("ℹ️ Azure Blob client not initialized; uploads will use local storage")

        except ImportError as e:
            print("❌ Azure Storage SDK not installed - using local storage only")
            print(f"ImportError details: {e}")
        except Exception as e:
            print(f"❌ Failed to initialize Azure Blob Storage: {e}")
            log_error(f"Exception type: {type(e).__name__}")
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
            probe_payload = f"connection verified at {datetime.utcnow().isoformat()}"
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
            import datetime
            # Add 5 minute buffer before expiry
            buffer_time = datetime.datetime.now() + datetime.timedelta(minutes=5)
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
                
                # Execute synchronous token acquisition in thread pool to avoid blocking async event loop
                import asyncio
                
                async def get_token_async():
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(
                        None, 
                        lambda: self.credential.get_token("https://ai.azure.com/.default")
                    )
                
                # 8-second timeout prevents indefinite hanging on slow networks
                token = await asyncio.wait_for(get_token_async(), timeout=8.0)
                
                # Cache the token
                self._cached_token = token.token
                import datetime
                self._token_expiry = datetime.datetime.fromtimestamp(token.expires_on)
                
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

    def _get_client(self):
        """Legacy method - now throws error to identify remaining SDK usage"""
        raise NotImplementedError(
            "❌ _get_client() is no longer supported! "
            "The foundry_agent_a2a.py now uses HTTP API calls instead of the azure.ai.agents SDK. "
            "This error indicates that some code is still trying to use the old SDK approach. "
            "Please update the calling code to use HTTP-based methods."
        )

    async def _http_list_messages(self, thread_id: str, limit: int = None) -> List[Dict[str, Any]]:
        """List messages in a thread via HTTP API"""
        try:
            headers = await self._get_auth_headers()
            endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
            api_url = f"{endpoint}/threads/{thread_id}/messages"
            
            params = {"api-version": "2025-05-15-preview"}
            if limit:
                params["limit"] = str(limit)
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    api_url,
                    headers=headers,
                    params=params,
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    # Return messages in reverse order (most recent first)
                    messages = data.get("data", [])
                    return list(reversed(messages))
                elif response.status_code == 401:
                    log_foundry_debug(f"🔄 Authentication failed (401), clearing cached token")
                    self._clear_cached_token()
                    log_foundry_debug(f"❌ Failed to list messages: {response.status_code} - {response.text}")
                    return []
                else:
                    log_foundry_debug(f"❌ Failed to list messages: {response.status_code} - {response.text}")
                    return []
        except Exception as e:
            log_foundry_debug(f"❌ Exception in _http_list_messages: {e}")
            return []

    async def _http_create_run(self, thread_id: str, agent_id: str, session_context: Optional[SessionContext] = None) -> Dict[str, Any]:
        """Create a run via HTTP API"""
        try:
            log_foundry_debug(f"_http_create_run ENTRY - thread_id: {thread_id}, agent_id: {agent_id}")
            
            log_foundry_debug(f"Getting auth headers...")
            headers = await self._get_auth_headers()
            log_foundry_debug(f"Auth headers obtained successfully")
            
            endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
            api_url = f"{endpoint}/threads/{thread_id}/runs"
            log_foundry_debug(f"API URL: {api_url}")
            
            # Determine parallel_tool_calls and instructions based on agent mode
            agent_mode = session_context.agent_mode if session_context else False
            parallel_tool_calls = not agent_mode  # When agent mode is ON, parallel is OFF
            log_foundry_debug(f"Agent Mode: {agent_mode}, Parallel Tool Calls: {parallel_tool_calls}")
            
            # Get instructions based on agent mode
            instructions = self.root_instruction('foundry-host-agent', agent_mode)
            
            payload = {
                "assistant_id": agent_id,  # Note: Azure AI Foundry uses 'assistant_id'
                "parallel_tool_calls": parallel_tool_calls,
                "instructions": instructions  # Override instructions based on agent mode
            }
            log_foundry_debug(f"Payload: {payload}")
            
            log_foundry_debug(f"Creating HTTP client and making POST request...")
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    api_url,
                    headers=headers,
                    json=payload,
                    params={"api-version": "2025-05-15-preview"},
                    timeout=30.0
                )
                log_foundry_debug(f"POST request completed - status: {response.status_code}")
                
                if response.status_code == 200 or response.status_code == 201:
                    run_data = response.json()
                    log_foundry_debug(f"Run creation successful - returning data: {run_data}")
                    return run_data
                else:
                    log_foundry_debug(f"❌ Failed to create run: {response.status_code} - {response.text}")
                    raise Exception(f"Failed to create run: {response.status_code} - {response.text}")
        except Exception as e:
            log_foundry_debug(f"❌ Exception in _http_create_run: {e}")
            import traceback
            log_foundry_debug(f"❌ Traceback: {traceback.format_exc()}")
            raise

    async def _http_get_run(self, thread_id: str, run_id: str) -> Dict[str, Any]:
        """Get run status via HTTP API"""
        try:
            log_foundry_debug(f"_http_get_run ENTRY - thread_id: {thread_id}, run_id: {run_id}")
            
            headers = await self._get_auth_headers()
            endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
            api_url = f"{endpoint}/threads/{thread_id}/runs/{run_id}"
            log_foundry_debug(f"GET request to: {api_url}")
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    api_url,
                    headers=headers,
                    params={"api-version": "2025-05-15-preview"},
                    timeout=30.0
                )
                log_foundry_debug(f"GET response status: {response.status_code}")
                
                if response.status_code == 200:
                    run_data = response.json()
                    log_foundry_debug(f"Run status retrieved - status: {run_data.get('status', 'unknown')}")
                    return run_data
                else:
                    log_foundry_debug(f"❌ Failed to get run: {response.status_code} - {response.text}")
                    raise Exception(f"Failed to get run: {response.status_code} - {response.text}")
        except Exception as e:
            log_foundry_debug(f"❌ Exception in _http_get_run: {e}")
            import traceback
            log_foundry_debug(f"❌ Traceback: {traceback.format_exc()}")
            raise

    async def _http_submit_tool_outputs(self, thread_id: str, run_id: str, tool_outputs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Submit tool outputs via HTTP API"""
        try:
            headers = await self._get_auth_headers()
            endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
            api_url = f"{endpoint}/threads/{thread_id}/runs/{run_id}/submit_tool_outputs"
            
            payload = {
                "tool_outputs": tool_outputs
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    api_url,
                    headers=headers,
                    json=payload,
                    params={"api-version": "2025-05-15-preview"},
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    log_foundry_debug(f"❌ Failed to submit tool outputs: {response.status_code} - {response.text}")
                    raise Exception(f"Failed to submit tool outputs: {response.status_code} - {response.text}")
        except Exception as e:
            log_foundry_debug(f"❌ Exception in _http_submit_tool_outputs: {e}")
            raise

    async def init_remote_agent_addresses(self, remote_agent_addresses: List[str]):
        async with asyncio.TaskGroup() as task_group:
            for address in remote_agent_addresses:
                task_group.create_task(self.retrieve_card(address))

    async def retrieve_card(self, address: str):
        card_resolver = A2ACardResolver(self.httpx_client, address, '/.well-known/agent.json')
        card = await card_resolver.get_agent_card()
        self.register_agent_card(card)

    def register_agent_card(self, card: AgentCard):
        """
        Register a remote agent by its card, establishing connection and updating UI state.
        Handles both new registrations and updates to existing agents.
        """
        if hasattr(card, 'capabilities') and card.capabilities:
            streaming_flag = getattr(card.capabilities, 'streaming', None)
            if streaming_flag is True:
                print(f"🔄 [STREAMING] {card.name} supports streaming; enabling granular UI visibility")
            elif streaming_flag is False:
                print(f"ℹ️ [STREAMING] {card.name} does not support streaming; using non-streaming mode")
            else:
                print(f"ℹ️ [STREAMING] {card.name} did not specify streaming capability; defaulting to non-streaming mode")
                try:
                    card.capabilities.streaming = False
                except Exception:
                    pass
        
        self._update_agent_registry(card)
        
        remote_connection = RemoteAgentConnections(self.httpx_client, card, self.task_callback)
        self.remote_agent_connections[card.name] = remote_connection
        self.cards[card.name] = card
        agent_info = []
        for ra in self.list_remote_agents():
            agent_info.append(json.dumps(ra))
        self.agents = '\n'.join(agent_info)
        
        if hasattr(self, '_host_manager') and self._host_manager:
            existing_index = next((i for i, a in enumerate(self._host_manager._agents) if a.name == card.name), None)
            
            if existing_index is not None:
                self._host_manager._agents[existing_index] = card
                log_debug(f"🔄 Updated {card.name} in host manager agent list")
            else:
                self._host_manager._agents.append(card)
                log_debug(f"✅ Added {card.name} to host manager agent list")
        
        self._emit_agent_registration_event(card)
        
        if self.agent:
            asyncio.create_task(self._update_agent_instructions())

    async def create_agent(self) -> Dict[str, Any]:
        if self.agent:
            log_foundry_debug(f"Agent already exists, reusing agent ID: {self.agent.get('id', 'unknown')}")
            return self.agent
        
        log_foundry_debug(f"No existing agent found, creating new agent...")
        log_foundry_debug(f"AZURE_AI_FOUNDRY_PROJECT_ENDPOINT = {os.environ.get('AZURE_AI_FOUNDRY_PROJECT_ENDPOINT', 'NOT SET')}")
        log_foundry_debug(f"AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME = {os.environ.get('AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME', 'NOT SET')}")
        
        # Validate required environment variables
        if not os.environ.get("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"):
            raise ValueError("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT environment variable is required")
        if not os.environ.get("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME"):
            raise ValueError("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME environment variable is required")
        
        # Use the correct Azure AI Foundry API endpoint format
        endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        
        # The endpoint should be in format: {base_url}/api/projects/{project-name}
        # We need to use the assistants API endpoint: {endpoint}/assistants
        if "/api/projects/" in endpoint:
            # Use the full project endpoint + assistants path
            api_url = f"{endpoint}/assistants"
            log_foundry_debug(f"Using assistants API URL: {api_url}")
        else:
            print(f"❌ ERROR: Invalid endpoint format. Expected format with /api/projects/")
            raise ValueError(f"Invalid endpoint format: {endpoint}")
        
        try:
            # Get authentication headers
            headers = await self._get_auth_headers()
            
            model_name = os.environ["AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME"]
            instructions = self.root_instruction('foundry-host-agent')
            tools = self._get_tools()
            
            log_foundry_debug(f"Agent parameters:")
            print(f"  - model: {model_name}")
            print(f"  - name: foundry-host-agent")
            print(f"  - instructions length: {len(instructions)}")
            print(f"  - tools count: {len(tools)}")
            
            # Prepare the request payload
            payload = {
                "model": model_name,
                "name": "foundry-host-agent",
                "instructions": instructions,
                "tools": tools
            }
            
            # Make the HTTP request to create the assistant
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    api_url,
                    headers=headers,
                    json=payload,
                    params={"api-version": "2025-05-15-preview"},
                    timeout=30.0
                )
                
                log_foundry_debug(f"API Response Status: {response.status_code}")
                
                if response.status_code == 200 or response.status_code == 201:
                    self.agent = response.json()
                    log_foundry_debug(f"✅ Agent created successfully! ID: {self.agent['id']}")
                    logger.info(f"Created Foundry Host agent: {self.agent['id']}")
                    return self.agent
                elif response.status_code == 401:
                    log_foundry_debug(f"🔄 Authentication failed (401), clearing cached token")
                    self._clear_cached_token()
                    log_foundry_debug(f"❌ API request failed with status {response.status_code}")
                    log_foundry_debug(f"❌ Response text: {response.text}")
                    raise Exception(f"Failed to create agent (authentication failed): {response.status_code} - {response.text}")
                else:
                    log_foundry_debug(f"❌ API request failed with status {response.status_code}")
                    log_foundry_debug(f"❌ Response text: {response.text}")
                    raise Exception(f"Failed to create agent: {response.status_code} - {response.text}")
            
        except Exception as e:
            log_foundry_debug(f"❌ Exception in create_agent(): {type(e).__name__}: {e}")
            log_foundry_debug(f"❌ Full traceback:")
            import traceback
            traceback.print_exc()
            raise

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
        """Define Azure AI Foundry function tools for agent coordination."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_remote_agents",
                    "description": "List the available remote agents you can use to delegate the task.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
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
            },
        ]

    def root_instruction(self, current_agent: str, agent_mode: bool = False) -> str:
        """
        Generate system prompt for the host agent based on operational mode.
        Supports custom instruction overrides and agent-mode vs standard orchestration prompts.
        """
        if self.custom_root_instruction:
            instruction = self.custom_root_instruction
            instruction = instruction.replace('{agents}', self.agents)
            instruction = instruction.replace('{current_agent}', current_agent)
            return instruction

        if agent_mode:
            return f"""You are a specialized **Agent Coordinator** operating in agent-to-agent communication mode.
                
                In this mode, you act as a direct facilitator between specialized agents, focusing on:
                1. **Sequential delegation**: Route tasks to agents one at a time based on their expertise and skills
                2. **Clear communication**: Provide precise instructions to each agent
                3. **Information synthesis**: Collect responses and prepare coherent answers
                4. **Minimal intervention**: Let agents handle their specialized tasks independently
                
                ### 🤖 AVAILABLE AGENTS
                {self.agents}
                
                Each agent may have a "skills" field listing their specific capabilities. Use these skills to select the best agent for each task.
                
                ### 🧠 CURRENT AGENT
                {current_agent}
                
                ### 📋 GUIDELINES
                - Route each request to the most appropriate single agent based on their skills
                - Wait for responses before coordinating with additional agents if needed
                - Synthesize agent responses into clear, direct answers
                - Maintain professional, efficient communication
                
                Focus on precision and clarity in agent-to-agent coordination."""

                ### 🚨 USE THIS FOR HUMAN ESCALATION IF NEEDED:HUMAN ESCALATION RULE, CHANGE AGENT NAME TO THE APPROPRIATE AGENT
                #If the user says anything like "I want to talk to a human,"  
                #you **must** call:
                #send_message(
                #    agent_name="ServiceNow, Web & Knowledge Agent",
                #    message="User explicitly requested to speak with a human representative. Please assist with this request."
                #)

        return f""" You are an intelligent **Multi-Agent Orchestrator** designed to coordinate specialized agents to produce complete, personalized responses.  
                Your goal is to understand the user's request, engage the right agents in the right order, and respond in a friendly, professional tone.

                ---

                ### 🧩 CORE BEHAVIOR
                Before answering any user request, always:
                1. Analyze the available agents (listed at the end of this prompt), including their skills.
                2. Identify which agents are relevant based on their specialized capabilities.
                3. Plan the collaboration strategy leveraging each agent's skills.



                ---

                ### 🧠 DECISION PRIORITIES
                1. **Answer directly** if information exists in the current conversation context.  
                2. **Coordinate multiple agents** when the request is complex.  
                3. **Delegate to a single agent** only if clearly within one domain.  
                4. **Document/claim workflows** → use all available relevant agents.  
                5. Always provide transparency about which agents were used and why.

                ---

                ### 📋 RESPONSE REQUIREMENTS
                Every response must include:
                - A clear summary of what you did and why.  
                - Which agents were engaged, their purposes, and short summaries of their responses.  
                - A friendly and professional summary of the response.  
                - Keep it short and to the point.


                IMPORTANT: Do NOT ask for clarification or confirmation - just proceed to the next step autonomously.

                ---

                ### 🧩 AVAILABLE AGENTS
                {self.agents}
                
                Each agent may have a "skills" field listing their specific capabilities. Use these skills to select the best agent(s) for each task.

                ### 🧠 CURRENT AGENT
                {current_agent}

                ---

                ### 💬 SUMMARY
                - Always show which agents you used and summarize their work.  
                - Be friendly, helpful, and professional."""

    def list_remote_agents(self, context_id: Optional[str] = None):
        """
        List available remote agents, filtered by session if context_id is provided.
        If context_id is provided, only returns agents that are enabled for the session.
        """
        agents = []
        
        # Extract session_id from context_id (format: "user_X::conversation_id")
        session_id = None
        if context_id and "::" in context_id:
            session_id = context_id.split("::")[0]
        
        # Get session-enabled agents if we have a session_id
        session_agent_urls = set()
        if session_id:
            from service.agent_registry import get_session_registry
            session_registry = get_session_registry()
            session_agents = session_registry.get_session_agents(session_id)
            session_agent_urls = {agent.get('url') for agent in session_agents if agent.get('url')}
        
        for card in self.cards.values():
            # Filter by session if session_id is provided
            # card.url is the agent's endpoint URL
            if session_id and hasattr(card, 'url') and card.url:
                # Only include agents that are enabled for this session
                if card.url not in session_agent_urls:
                    continue
            
            agent_info = {
                'name': card.name,
                'description': card.description
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
            
            agents.append(agent_info)
        return agents

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
        log_debug(f"📋 [Agent Mode] Workflow parameter received: {workflow[:100] if workflow else 'None'}")
        
        # Reset host token usage for this workflow
        self.host_token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        
        await self._emit_status_event("Initializing Agent Mode orchestration...", context_id)
        
        # Handle conversation continuity - distinguish new goals from follow-up clarifications
        # FIXED: Don't treat workflow iterations as follow-ups - they should continue in one loop
        if context_id in self._active_conversations and not workflow:
            # User is providing additional information for an existing goal (only for non-workflow mode)
            original_goal = self._active_conversations[context_id]
            goal_text = f"{original_goal}\n\n[Additional Information Provided]: {user_message}"
            print(f"🔄 [Agent Mode] Follow-up detected - appending to original goal")
        else:
            # Fresh conversation OR workflow mode - establish goal
            goal_text = user_message
            if context_id not in self._active_conversations:
                self._active_conversations[context_id] = user_message
                print(f"🆕 [Agent Mode] New conversation started")
            else:
                print(f"🔄 [Agent Mode] Continuing workflow - NOT treating as follow-up")
        
        # Use the class method for extracting clean text from A2A response objects
        extract_text_from_response = self._extract_text_from_response
        
        # Initialize execution plan with empty task list
        plan = AgentModePlan(goal=goal_text, goal_status="incomplete")
        iteration = 0
        max_iterations = 20  # Safety limit to prevent infinite loops
        workflow_step_count = 0  # Will be set if workflow is provided
        
        # Accumulate outputs from all completed tasks
        all_task_outputs = []
        
        # Log initial plan
        print(f"\n{'='*80}")
        log_debug(f"📋 [Agent Mode] INITIAL PLAN")
        print(f"{'='*80}")
        print(f"Goal: {plan.goal}")
        print(f"Status: {plan.goal_status}")
        print(f"Tasks: {len(plan.tasks)} (empty initially)")
        print(f"{'='*80}\n")
        
        # System prompt that guides the orchestrator's decision-making
        # This is the "brain" that decides which agents to use and when
        system_prompt = """You are the Host Orchestrator in an A2A multi-agent system.

PRIMARY RESPONSIBILITIES:
- **FIRST**: Check if a MANDATORY WORKFLOW exists below - if it does, you MUST complete ALL workflow steps before marking goal as "completed"
- Evaluate whether the user's goal is achieved by analyzing all completed tasks and their outputs
- If incomplete, propose exactly ONE next task that moves closer to the goal
- Select the most appropriate agent based on their specialized skills

DECISION-MAKING RULES:
- Analyze the ENTIRE plan history - don't ignore previous tasks or outputs
- Never repeat completed tasks unless explicitly retrying a failure
- Keep each task atomic and delegable to a single agent
- Match tasks to agents using their "skills" field for best results
- If no agent fits, set recommended_agent=null
- Mark goal_status="completed" ONLY when: (1) ALL MANDATORY WORKFLOW steps are completed (if workflow exists), AND (2) the objective is fully achieved

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
- Execute each step in sequence
- Wait for each step to complete before moving to the next
- Only mark goal_status="completed" after ALL workflow steps are finished
- If a step fails, you may retry or adapt, but you must complete all steps
"""
            system_prompt += workflow_section
            log_debug(f"📋 [Agent Mode] ✅ Injected workflow into planner prompt ({len(workflow)} chars)")
            log_debug(f"📋 [Agent Mode] Workflow section preview:\n{workflow_section[:500]}...")
        else:
            log_debug(f"📋 [Agent Mode] ❌ No workflow to inject (workflow is None or empty)")
        
        # Add workflow-specific completion logic if workflow is present
        if workflow and workflow.strip():
            # Count the workflow steps to make it explicit
            workflow_step_count = len([line for line in workflow.strip().split('\n') if line.strip() and (line.strip()[0].isdigit() or line.strip().startswith('-'))])
            print(f"📊 [Agent Mode] Detected {workflow_step_count} steps in workflow")
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
                # Log system prompt for debugging (first 2000 chars)
                print(f"🔍 [Agent Mode] System prompt being sent to Azure OpenAI (first 2000 chars):\n{system_prompt[:2000]}...")
                print(f"🔍 [Agent Mode] System prompt contains 'MANDATORY WORKFLOW': {'MANDATORY WORKFLOW' in system_prompt}")
                
                next_step = await self._call_azure_openai_structured(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_model=NextStep,
                    context_id=context_id
                )
                
                print(f"🤖 [Agent Mode] Orchestrator decision: {next_step.reasoning}")
                print(f"🤖 [Agent Mode] Goal status: {next_step.goal_status}")
                await self._emit_status_event(f"Reasoning: {next_step.reasoning}", context_id)
                
                # Update plan status
                plan.goal_status = next_step.goal_status
                plan.updated_at = datetime.utcnow()
                
                # Log plan state after orchestrator decision
                print(f"\n{'='*80}")
                log_debug(f"📋 [Agent Mode] PLAN STATE (Iteration {iteration})")
                print(f"{'='*80}")
                print(f"Goal: {plan.goal}")
                print(f"Goal Status: {plan.goal_status}")
                print(f"Total Tasks: {len(plan.tasks)}")
                for i, task in enumerate(plan.tasks, 1):
                    print(f"\n  Task {i}:")
                    print(f"    Description: {task.task_description}")
                    print(f"    Agent: {task.recommended_agent or 'None'}")
                    print(f"    State: {task.state}")
                    if task.error_message:
                        print(f"    Error: {task.error_message}")
                    if task.output:
                        output_preview = str(task.output).replace('\n', ' ')[:100]
                        print(f"    Output: {output_preview}...")
                print(f"\n  Next Step Reasoning: {next_step.reasoning}")
                if next_step.next_task:
                    print(f"  Next Task: {next_step.next_task.get('task_description', 'N/A')}")
                    print(f"  Target Agent: {next_step.next_task.get('recommended_agent', 'N/A')}")
                print(f"{'='*80}\n")
                
                if next_step.goal_status == "completed":
                    completed_tasks_count = len([t for t in plan.tasks if t.state == "completed"])
                    log_info(f"✅ [Agent Mode] Goal marked as completed after {iteration} iterations")
                    log_info(f"📊 [Agent Mode] Completed tasks: {completed_tasks_count} / Expected workflow steps: {workflow_step_count if workflow and workflow.strip() else 'N/A'}")
                    if workflow and workflow.strip() and completed_tasks_count < workflow_step_count:
                        print(f"⚠️  [Agent Mode] WARNING: Only {completed_tasks_count} tasks completed but workflow has {workflow_step_count} steps!")
                        print(f"⚠️  [Agent Mode] LLM reasoning: {next_step.reasoning}")
                    await self._emit_status_event("Goal achieved! Generating final response...", context_id)
                    break
                
                # Execute next task if provided
                if next_step.next_task:
                    task_desc = next_step.next_task.get("task_description")
                    recommended_agent = next_step.next_task.get("recommended_agent")
                    
                    if not task_desc:
                        print(f"⚠️ [Agent Mode] No task description provided, breaking loop")
                        break
                    
                    # Create new task
                    task = AgentModeTask(
                        task_id=str(uuid.uuid4()),
                        task_description=task_desc,
                        recommended_agent=recommended_agent,
                        state="running"
                    )
                    plan.tasks.append(task)
                    
                    log_debug(f"📋 [Agent Mode] New task: {task_desc}")
                    log_debug(f"🎯 [Agent Mode] Target agent: {recommended_agent or 'None specified'}")
                    await self._emit_status_event(f"Executing: {task_desc}", context_id)
                    
                    # Stream task creation event
                    await self._emit_granular_agent_event(
                        agent_name=recommended_agent or "orchestrator",
                        status_text=f"Task created: {task_desc}",
                        context_id=context_id
                    )
                    
                    # Execute the task by delegating to the selected remote agent
                    try:
                        if recommended_agent and recommended_agent in self.cards:
                            log_debug(f"🚀 [Agent Mode] Calling agent: {recommended_agent}")
                            
                            # File deduplication for agent mode workflows
                            # Keep only the most recent files to prevent accumulation across workflow iterations
                            if hasattr(session_context, '_latest_processed_parts') and len(session_context._latest_processed_parts) > 1:
                                from collections import defaultdict
                                old_count = len(session_context._latest_processed_parts)
                                
                                # Maximum number of generated files to keep (most recent N)
                                # This prevents accumulation when workflows have many iterations
                                MAX_GENERATED_FILES = 3
                                
                                # Separate artifacts with editing roles (base/mask/overlay) from generated outputs
                                editing_roles = defaultdict(lambda: None)  # For base/mask/overlay - keep latest only
                                generated_artifacts = []  # For generated images/files - keep only most recent N
                                
                                for part in reversed(session_context._latest_processed_parts):  # reversed = most recent first
                                    role = None
                                    if isinstance(part, DataPart) and isinstance(part.data, dict):
                                        role = part.data.get('role')
                                    elif hasattr(part, 'root') and isinstance(part.root, DataPart) and isinstance(part.root.data, dict):
                                        role = part.root.data.get('role')
                                    
                                    # Deduplicate ONLY editing roles (base, mask, overlay)
                                    # These are meant for iterative editing workflows
                                    if role in ['base', 'mask', 'overlay']:
                                        if role not in editing_roles:
                                            editing_roles[role] = part
                                    else:
                                        # Keep only the most recent N generated artifacts to prevent accumulation
                                        # This prevents passing 17+ files to agents like Image Analysis
                                        if len(generated_artifacts) < MAX_GENERATED_FILES:
                                            generated_artifacts.append(part)
                                
                                # Combine: editing roles (deduplicated) + most recent N generated artifacts  
                                # Keep generated_artifacts in newest-first order (from reversed iteration)
                                # This ensures the LATEST generated image is FIRST, so it's used as base for next edit
                                deduplicated_parts = list(editing_roles.values()) + generated_artifacts
                                session_context._latest_processed_parts = deduplicated_parts
                                print(f"📎 [Agent Mode] File management: {old_count} files → {len(deduplicated_parts)} files")
                                print(f"   • Editing roles (deduplicated): {len(editing_roles)} (base/mask/overlay)")
                                print(f"   • Generated artifacts (kept {len(generated_artifacts)} most recent, max {MAX_GENERATED_FILES})")
                            
                            # Create dummy tool context for send_message
                            dummy_context = DummyToolContext(session_context, self._azure_blob_client)
                            
                            # Call send_message (existing method)
                            responses = await self.send_message(
                                agent_name=recommended_agent,
                                message=task_desc,
                                tool_context=dummy_context,
                                suppress_streaming=False  # Show in UI
                            )
                            
                            # Parse and record task execution results
                            # Extract state information from A2A Task protocol response
                            if responses and len(responses) > 0:
                                response_obj = responses[0] if isinstance(responses, list) else responses
                                
                                # WORKFLOW PAUSE: Check if agent returned input_required
                                # This is detected via session_context.pending_input_agent being set
                                if session_context.pending_input_agent:
                                    log_info(f"⏸️ [Agent Mode] Agent '{recommended_agent}' returned input_required - PAUSING WORKFLOW")
                                    task.state = "input_required"
                                    
                                    # Collect any output from the agent's question (properly extract text)
                                    output_text = extract_text_from_response(response_obj)
                                    if output_text:
                                        all_task_outputs.append(output_text)
                                    
                                    # Store workflow state for resumption after HITL
                                    session_context.pending_workflow = workflow
                                    session_context.pending_workflow_outputs = all_task_outputs.copy()
                                    session_context.pending_workflow_user_message = user_message
                                    
                                    log_info(f"⏸️ [Agent Mode] Workflow paused. Collected {len(all_task_outputs)} outputs so far.")
                                    log_info(f"⏸️ [Agent Mode] Waiting for user response to '{recommended_agent}'")
                                    await self._emit_status_event(f"Waiting for your response to continue...", context_id)
                                    
                                    # Return current outputs - workflow will resume after HITL
                                    return all_task_outputs
                                
                                # A2A Task response includes detailed state and artifacts
                                if isinstance(response_obj, Task):
                                    task.state = response_obj.status.state
                                    task.output = {
                                        "task_id": response_obj.id,
                                        "state": response_obj.status.state,
                                        "result": response_obj.result if hasattr(response_obj, 'result') else None,
                                        "artifacts": [a.model_dump() for a in response_obj.artifacts] if response_obj.artifacts else []
                                    }
                                    
                                    if task.state == "failed":
                                        task.error_message = response_obj.status.message or "Task failed"
                                        log_error(f"[Agent Mode] Task failed: {task.error_message}")
                                    else:
                                        log_info(f"✅ [Agent Mode] Task completed with state: {task.state}")
                                        # Collect text result
                                        output_text = str(response_obj.result) if response_obj.result else ""
                                        
                                        # Also collect any artifacts (files, images, etc.) from this task
                                        if response_obj.artifacts:
                                            artifact_descriptions = []
                                            for artifact in response_obj.artifacts:
                                                if hasattr(artifact, 'parts'):
                                                    for part in artifact.parts:
                                                        # Add to _latest_processed_parts for agent-to-agent communication
                                                        if not hasattr(session_context, '_latest_processed_parts'):
                                                            session_context._latest_processed_parts = []
                                                        session_context._latest_processed_parts.append(part)
                                                        
                                                        # NOTE: Not adding to _agent_generated_artifacts here
                                                        # It will be added later during streaming processing (send_message)
                                                        # to avoid duplicates since send_message processes _latest_processed_parts
                                                        
                                                        if hasattr(part, 'root'):
                                                            # File parts (images, documents, etc.)
                                                            if hasattr(part.root, 'file'):
                                                                file_info = part.root.file
                                                                file_name = getattr(file_info, 'name', 'unknown')
                                                                file_url = getattr(file_info, 'uri', None)
                                                                artifact_descriptions.append(f"[File: {file_name}]")
                                                                if file_url:
                                                                    artifact_descriptions.append(f"URI: {file_url}")
                                                            # Text parts in artifacts
                                                            elif hasattr(part.root, 'text'):
                                                                artifact_descriptions.append(part.root.text)
                                            
                                            if artifact_descriptions:
                                                artifacts_summary = "\n".join(artifact_descriptions)
                                                all_task_outputs.append(f"{output_text}\n\nArtifacts:\n{artifacts_summary}")
                                            else:
                                                all_task_outputs.append(output_text)
                                        else:
                                            all_task_outputs.append(output_text)
                                else:
                                    # Simple string response (legacy format) - extract text properly
                                    task.state = "completed"
                                    output_text = extract_text_from_response(response_obj)
                                    task.output = {"result": output_text}
                                    all_task_outputs.append(output_text)
                                    log_info(f"✅ [Agent Mode] Task completed successfully")
                            else:
                                # No response indicates communication failure
                                task.state = "failed"
                                task.error_message = "No response from agent"
                                log_error(f"[Agent Mode] No response from agent")
                        else:
                            task.state = "failed"
                            task.error_message = f"Agent '{recommended_agent}' not found"
                            log_error(f"[Agent Mode] Agent not found: {recommended_agent}")
                    
                    except Exception as e:
                        task.state = "failed"
                        task.error_message = str(e)
                        log_error(f"[Agent Mode] Task execution error: {e}")
                    
                    finally:
                        task.updated_at = datetime.utcnow()
                        print(f"📊 [Agent Mode] Task final state: {task.state}")
                        
                        # Log task completion details
                        print(f"\n{'~'*80}")
                        log_info(f"✅ [Agent Mode] TASK COMPLETED")
                        print(f"{'~'*80}")
                        print(f"Task ID: {task.task_id}")
                        print(f"Description: {task.task_description}")
                        print(f"Agent: {task.recommended_agent or 'None'}")
                        print(f"Final State: {task.state}")
                        if task.error_message:
                            print(f"Error: {task.error_message}")
                        if task.output:
                            print(f"Output: {json.dumps(task.output, indent=2, default=str)[:500]}...")
                        print(f"{'~'*80}\n")
                
            except Exception as e:
                log_error(f"[Agent Mode] Orchestration error: {e}")
                await self._emit_status_event(f"Error in orchestration: {str(e)}", context_id)
                break
        
        if iteration >= max_iterations:
            print(f"⚠️ [Agent Mode] Reached maximum iterations ({max_iterations})")
            await self._emit_status_event("Maximum iterations reached, completing...", context_id)
        
        # Log final plan summary
        print(f"\n{'='*80}")
        print(f"🎬 [Agent Mode] FINAL PLAN SUMMARY")
        print(f"{'='*80}")
        print(f"Goal: {plan.goal}")
        print(f"Final Status: {plan.goal_status}")
        print(f"Total Iterations: {iteration}")
        print(f"Total Tasks Created: {len(plan.tasks)}")
        print(f"\nTask Breakdown:")
        for i, task in enumerate(plan.tasks, 1):
            print(f"  {i}. [{task.state.upper()}] {task.task_description[:60]}...")
            print(f"     Agent: {task.recommended_agent or 'None'}")
        print(f"\nTask Outputs Collected: {len(all_task_outputs)}")
        print(f"{'='*80}\n")
        
        # Generate final response from all outputs
        print(f"🎬 [Agent Mode] Orchestration complete. {len(all_task_outputs)} task outputs collected")
        print(f"🎟️ [Host Agent] Final token usage: {self.host_token_usage}")
        
        # Emit host token usage to frontend
        try:
            from service.websocket_streamer import get_websocket_streamer
            import asyncio
            
            async def emit_host_tokens():
                streamer = await get_websocket_streamer()
                if streamer:
                    event_data = {
                        "agentName": "foundry-host-agent",
                        "tokenUsage": self.host_token_usage,
                        "state": "completed",
                        "timestamp": __import__('datetime').datetime.utcnow().isoformat()
                    }
                    await streamer._send_event("host_token_usage", event_data, context_id)
                    print(f"📡 [Host Agent] Emitted token usage to frontend: {self.host_token_usage['total_tokens']} tokens")
            
            asyncio.create_task(emit_host_tokens())
        except Exception as e:
            print(f"⚠️ [Host Agent] Error emitting token usage: {e}")
        
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

    def _stream_remote_agent_activity(self, event: TaskCallbackArg, agent_card: AgentCard):
        """Stream remote agent activity to WebSocket for granular UI visibility in thinking box."""
        try:
            agent_name = agent_card.name
            
            # Skip streaming if we've already handled this event type in the detailed callback
            # This prevents duplicate events from being sent to the UI
            if hasattr(event, 'kind'):
                # The detailed streaming callback already handles these event types
                return
            
            status_text = f"processing request"
            
            # Extract granular status from different event types
            if isinstance(event, Task):
                if hasattr(event.status, 'state'):
                    state = event.status.state
                    if hasattr(state, 'value'):
                        state_value = state.value
                    else:
                        state_value = str(state)
                    
                    if state_value == 'working':
                        status_text = "analyzing request"
                    elif state_value == 'completed':
                        status_text = "response ready"
                    elif state_value == 'failed':
                        status_text = "request failed"
                    elif state_value == 'input_required':
                        status_text = "requires additional input"
                    else:
                        status_text = f"status: {state_value}"
            
            # Stream to WebSocket using async background task (only for Task objects, not streaming events)
            import asyncio
            async def stream_activity():
                try:
                    # Use the _emit_status_event method for consistency
                    await self._emit_granular_agent_event(agent_name, status_text)
                except Exception as e:
                    log_debug(f"Error streaming remote agent activity: {e}")
                    pass
            
            # Create background task (non-blocking)
            try:
                asyncio.create_task(stream_activity())
            except RuntimeError:
                # Handle case where no event loop is running
                log_debug(f"No event loop available for streaming agent activity from {agent_name}")
                pass
                
        except Exception as e:
            log_debug(f"Error in _stream_remote_agent_activity: {e}")
            # Don't let streaming errors break the callback
            pass

    async def _emit_tool_call_event(self, agent_name: str, tool_name: str, arguments: dict, context_id: str = None):
        """Emit tool call event to WebSocket for granular UI visibility."""
        try:
            # Import here to avoid circular imports
            from service.websocket_streamer import get_websocket_streamer
            
            streamer = await get_websocket_streamer()
            if streamer:
                event_data = {
                    "agentName": agent_name,
                    "toolName": tool_name,
                    "arguments": arguments,
                    "timestamp": __import__('datetime').datetime.utcnow().isoformat(),
                    "contextId": context_id
                }
                
                success = await streamer._send_event("tool_call", event_data, context_id)
                if success:
                    log_debug(f"Streamed tool call: {agent_name} - {tool_name}")
                else:
                    log_debug(f"Failed to stream tool call: {agent_name}")
            else:
                log_debug(f"WebSocket streamer not available for tool call")
                
        except Exception as e:
            log_debug(f"Error emitting tool call event: {e}")
            pass

    async def _emit_outgoing_message_event(self, target_agent_name: str, message: str, context_id: str):
        """Emit outgoing message event to WebSocket for DAG display."""
        try:
            # Import here to avoid circular imports
            from service.websocket_streamer import get_websocket_streamer
            
            streamer = await get_websocket_streamer()
            if streamer:
                event_data = {
                    "sourceAgent": "Host Agent",  # Host Agent is sending the message
                    "targetAgent": target_agent_name,  # Remote agent receiving the message
                    "message": message,
                    "timestamp": __import__('datetime').datetime.utcnow().isoformat(),
                    "contextId": context_id
                }
                
                print(f"📤 [OUTGOING MESSAGE EVENT] Emitting to frontend:")
                print(f"   • Target Agent: {target_agent_name}")
                print(f"   • Message: {message[:100]}..." if len(message) > 100 else f"   • Message: {message}")
                print(f"   • Context ID: {context_id}")
                
                await streamer._send_event("outgoing_agent_message", event_data, context_id)
                print(f"✅ [OUTGOING MESSAGE EVENT] Emitted successfully")
                
        except Exception as e:
            print(f"❌ [OUTGOING MESSAGE EVENT] Error: {e}")
            log_debug(f"Error emitting outgoing message event: {e}")
            pass

    async def _emit_tool_response_event(self, agent_name: str, tool_name: str, status: str, error_message: str = None, context_id: str = None):
        """Emit tool response event to WebSocket for granular UI visibility."""
        try:
            # Import here to avoid circular imports
            from service.websocket_streamer import get_websocket_streamer
            import datetime
            
            streamer = await get_websocket_streamer()
            if streamer:
                event_data = {
                    "agentName": agent_name,
                    "toolName": tool_name,
                    "status": status,
                    "timestamp": datetime.datetime.utcnow().isoformat(),
                    "contextId": context_id
                }
                
                if error_message:
                    event_data["error"] = error_message
                
                success = await streamer._send_event("tool_response", event_data, context_id)
                if success:
                    log_debug(f"Streamed tool response: {agent_name} - {tool_name} - {status}")
                else:
                    log_debug(f"Failed to stream tool response: {agent_name}")
                
                # ALSO emit task_updated so the frontend sidebar updates correctly
                # This is the single source of truth for agent sidebar status
                task_state = "completed" if status == "success" else "failed"
                task_updated_data = {
                    "taskId": str(uuid.uuid4()),
                    "conversationId": context_id or getattr(self, 'default_contextId', str(uuid.uuid4())),
                    "contextId": context_id or getattr(self, 'default_contextId', None),
                    "state": task_state,
                    "agentName": agent_name,
                    "timestamp": datetime.datetime.utcnow().isoformat(),
                    "content": f"Agent {status}" if not error_message else error_message
                }
                print(f"🎯 [SIDEBAR] Emitting task_updated for {agent_name}: state={task_state}")
                result = await streamer._send_event("task_updated", task_updated_data, context_id)
                print(f"🎯 [SIDEBAR] task_updated sent, success={result}")
            else:
                log_debug(f"WebSocket streamer not available for tool response")
                
        except Exception as e:
            log_debug(f"Error emitting tool response event: {e}")
            pass

    async def _emit_granular_agent_event(self, agent_name: str, status_text: str, context_id: str = None):
        """Emit granular agent activity event to WebSocket for thinking box visibility."""
        try:
            # Import here to avoid circular imports
            from service.websocket_streamer import get_websocket_streamer
            
            streamer = await get_websocket_streamer()
            if streamer:
                event_data = {
                    "agentName": agent_name,
                    "content": status_text,
                    "timestamp": __import__('datetime').datetime.utcnow().isoformat(),
                    "contextId": context_id
                }
                
                # Use the remote_agent_activity event type for granular visibility
                success = await streamer._send_event("remote_agent_activity", event_data, context_id)
                if success:
                    log_debug(f"Streamed remote agent activity: {agent_name} - {status_text}")
                else:
                    log_debug(f"Failed to stream remote agent activity: {agent_name}")
            else:
                log_debug(f"WebSocket streamer not available for remote agent activity")
                
        except Exception as e:
            log_debug(f"Error emitting granular agent event: {e}")
            # Don't let streaming errors break the main flow
            pass

    def _default_task_callback(self, event: TaskCallbackArg, agent_card: AgentCard) -> Task:
        """Default task callback optimized for streaming remote agent execution.
        
        CONSOLIDATED: Uses _emit_task_event as the SINGLE source of truth for all
        remote agent status updates to prevent duplicate events in the UI.
        """
        agent_name = agent_card.name
        log_debug(f"[STREAMING] Task callback from {agent_name}: {type(event).__name__}")
        
        # Keep session context task mapping in sync per agent
        try:
            context_id_cb = get_context_id(event, None)
            task_id_cb = get_task_id(event, None)
            if context_id_cb and task_id_cb:
                session_ctx = self.get_session_context(context_id_cb)
                session_ctx.agent_task_ids[agent_name] = task_id_cb
                # If status-update, capture state per agent
                if hasattr(event, 'kind') and getattr(event, 'kind', '') == 'status-update':
                    state_obj = getattr(getattr(event, 'status', None), 'state', None)
                    if state_obj is not None:
                        state_str = state_obj.value if hasattr(state_obj, 'value') else str(state_obj)
                        session_ctx.agent_task_states[agent_name] = state_str
                        
                        # HUMAN-IN-THE-LOOP: Track input_required state from remote agents
                        if state_str == 'input_required' or state_str == 'input-required':
                            session_ctx.pending_input_agent = agent_name
                            session_ctx.pending_input_task_id = task_id_cb
                            log_info(f"🔄 [HITL] Callback detected input_required from '{agent_name}', setting pending_input_agent (task_id: {task_id_cb})")
        except Exception as e:
            # Non-fatal; continue normal processing
            log_debug(f"[STREAMING] Error in task callback context tracking: {e}")
            pass
        
        # CONSOLIDATED: Only status-update and artifact-update events should update the UI
        # 'task' events are for internal task creation/tracking, not UI status updates
        # Emitting 'task' events was causing late "working" events to overwrite "completed" status
        if hasattr(event, 'kind'):
            event_kind = getattr(event, 'kind', 'unknown')
            log_debug(f"[STREAMING] Event kind from {agent_name}: {event_kind}")
            
            # Only emit status-update and artifact-update to UI (NOT 'task' events)
            if event_kind in ['artifact-update', 'status-update']:
                log_debug(f"[STREAMING] Emitting via _emit_task_event for {agent_name}: {event_kind}")
                self._emit_task_event(event, agent_card)
            elif event_kind == 'task':
                log_debug(f"[STREAMING] Skipping UI emit for 'task' event from {agent_name} (internal tracking only)")
            # Skip other intermediate events
        
        # Get or create task for this specific agent
        current_task = self._agent_tasks.get(agent_name)
        
        if isinstance(event, Task):
            # Initial task creation - store per agent
            log_debug(f"[PARALLEL] Storing new task for {agent_name}")
            self._agent_tasks[agent_name] = event
            return event
        
        elif hasattr(event, 'kind'):
            if event.kind == 'task':
                # Initial task event - store per agent
                log_debug(f"[PARALLEL] Storing task event for {agent_name}")
                self._agent_tasks[agent_name] = event
                return event
            
            elif event.kind == 'status-update' and current_task:
                # Update existing task status for this agent
                log_debug(f"[PARALLEL] Updating task status for {agent_name}")
                if hasattr(event, 'status'):
                    current_task.status = event.status
                return current_task
            
            elif event.kind == 'artifact-update' and current_task:
                # Add artifact to existing task for this agent
                log_debug(f"[PARALLEL] Adding artifact for {agent_name}")
                if hasattr(event, 'artifact'):
                    if not current_task.artifacts:
                        current_task.artifacts = []
                    current_task.artifacts.append(event.artifact)
                return current_task
        
        # Fallback: return current task for this agent or create a minimal one
        if current_task:
            return current_task
        
        # Create minimal task for this agent
        task_id = get_task_id(event, str(uuid.uuid4()))
        contextId = get_context_id(event, str(uuid.uuid4()))
        
        from a2a.types import TaskStatus, TaskState
        status = TaskStatus(
            state=getattr(event, 'state', TaskState.working),
            message=None,
            timestamp=None
        )
        
        fallback_task = Task(
            id=task_id,
            contextId=contextId,
            status=status,
            history=[],
            artifacts=[]
        )
        
        # Store for this agent
        self._agent_tasks[agent_name] = fallback_task
        log_debug(f"[PARALLEL] Created fallback task for {agent_name}")
        return fallback_task

    def _emit_task_event(self, task: TaskCallbackArg, agent_card: AgentCard):
        """Emit event for task callback, with enhanced agent name context for UI status tracking."""
        log_debug(f"Emitting task event for agent: {agent_card.name}")
        log_debug(f"Agent capabilities: {agent_card.capabilities if hasattr(agent_card, 'capabilities') else 'None'}")
        
        content = None
        contextId = get_context_id(task, None)
        task_id = None
        task_state = None
        
        # Extract task state and ID
        if hasattr(task, 'kind') and task.kind == 'status-update':
            task_id = get_task_id(task, None)
            # Extract state from status object, handling enum types
            if hasattr(task, 'status') and task.status:
                state_obj = getattr(task.status, 'state', 'working')
                if hasattr(state_obj, 'value'):
                    task_state = state_obj.value  # Extract enum value
                else:
                    task_state = str(state_obj)
            else:
                task_state = 'working'
            
            log_debug(f"Status update extracted: {task_state} for {agent_card.name}")
            
            if hasattr(task, 'status') and task.status and task.status.message:
                content = task.status.message
            else:
                # Create a status message
                from a2a.types import Message, Part, TextPart, Role
                content = Message(
                    parts=[Part(root=TextPart(text=f"Task status: {task_state}"))],
                    role=Role.agent,
                    messageId=str(uuid.uuid4()),
                    contextId=contextId,
                    taskId=task_id,
                )
        elif hasattr(task, 'kind') and task.kind == 'artifact-update':
            task_id = get_task_id(task, None)
            task_state = 'completed'  # Artifact updates typically indicate completion
            if hasattr(task, 'artifact') and task.artifact:
                from a2a.types import Message, Role
                content = Message(
                    parts=task.artifact.parts,
                    role=Role.agent,
                    messageId=str(uuid.uuid4()),
                    contextId=contextId,
                    taskId=task_id,
                )
        elif isinstance(task, Task):
            task_id = task.id
            contextId = get_context_id(task, contextId)
            # Extract task state from TaskState enum
            if hasattr(task.status, 'state'):
                if hasattr(task.status.state, 'value'):
                    task_state = task.status.state.value  # Extract enum value
                else:
                    task_state = str(task.status.state)
            
            if task.status and task.status.message:
                content = task.status.message
            elif task.artifacts:
                from a2a.types import Message, Role
                parts = []
                for a in task.artifacts:
                    parts.extend(a.parts)
                content = Message(
                    parts=parts,
                    role=Role.agent,
                    messageId=str(uuid.uuid4()),
                    taskId=task_id,
                    contextId=contextId,
                )
        
        # Create default content if none found
        if not content:
            from a2a.types import Message, Part, TextPart, Role
            status_text = f"Task update for {agent_card.name}"
            if task_state:
                status_text = f"Task status: {task_state}"
            
            content = Message(
                parts=[Part(root=TextPart(text=status_text))],
                role=Role.agent,
                messageId=str(uuid.uuid4()),
                taskId=task_id or str(uuid.uuid4()),
                contextId=contextId or str(uuid.uuid4()),
            )
        
        # Create Event object like ADK version, but with enhanced agent context
        if content:
            import datetime
            event_obj = type('Event', (), {
                'id': str(uuid.uuid4()),
                'actor': agent_card.name,  # Use the actual agent name
                'content': content,
                'timestamp': datetime.datetime.utcnow().timestamp(),
            })()
            
            # Add to host manager events if available
            if hasattr(self, '_host_manager') and self._host_manager:
                self._host_manager.add_event(event_obj)
                log_debug(f"Added event to host manager for agent: {agent_card.name}")
            
            # Stream A2A-compliant task events to WebSocket with agent context
            # CONSOLIDATED: Single event emission point for remote agent status
            log_debug(f"Streaming A2A task event to WebSocket for agent: {agent_card.name}, state: {task_state}")
            try:
                import asyncio

                async def stream_task_event():
                    try:
                        from service.websocket_streamer import get_websocket_streamer

                        streamer = await get_websocket_streamer()
                        if not streamer:
                            log_debug("⚠️ WebSocket streamer not available for task event")
                            return

                        # Extract text content from message parts if available
                        text_content = ""
                        if content and hasattr(content, 'parts'):
                            for part in content.parts:
                                if hasattr(part, 'root') and hasattr(part.root, 'text'):
                                    text_content = part.root.text
                                    break

                        # CONSOLIDATED: Include ALL relevant data in single task_updated event
                        # This is the ONLY event emitted for remote agent status updates
                        event_data = {
                            "taskId": task_id or str(uuid.uuid4()),
                            "conversationId": contextId or str(uuid.uuid4()),
                            "contextId": contextId,
                            "state": task_state,
                            "artifactsCount": len(getattr(task, 'artifacts', [])),
                            "agentName": agent_card.name,
                            "timestamp": datetime.datetime.utcnow().isoformat(),
                            # Include message content so frontend has everything in one event
                            "content": text_content if text_content else None,
                        }
                        
                        # Add token usage if available for this agent
                        if agent_card.name in self.agent_token_usage:
                            event_data["tokenUsage"] = self.agent_token_usage[agent_card.name]

                        event_type = "task_updated"
                        if hasattr(task, 'kind') and task.kind == 'status-update':
                            event_type = "task_updated"
                        elif not hasattr(task, 'kind'):
                            event_type = "task_created"

                        # DEBUG: Log what we're sending to the frontend
                        print(f"📡 [A2A STREAM] Emitting {event_type} for {agent_card.name}: state={task_state}")
                        
                        success = await streamer._send_event(event_type, event_data, contextId)
                        if success:
                            log_debug(f"✅ A2A task event streamed: {agent_card.name} -> {task_state}")
                        else:
                            log_debug(f"❌ Failed to stream A2A task event: {agent_card.name} -> {task_state}")
                        
                        # REMOVED: Secondary remote_agent_activity emission
                        # All data is now included in the task_updated event above
                        
                    except Exception as e:
                        log_debug(f"❌ Error streaming A2A task event: {e}")
                        import traceback
                        traceback.print_exc()

                asyncio.create_task(stream_task_event())

            except Exception as e:
                log_debug(f"❌ Error setting up A2A task event streaming: {e}")
                pass

    def _emit_agent_registration_event(self, agent_card: AgentCard):
        """Emit agent registration event to WebSocket for UI sidebar visibility."""
        log_debug(f"Emitting agent registration event for: {agent_card.name}")
        try:
            import asyncio
            
            # Try to get the current default context
            default_context_id = getattr(self, 'default_contextId', str(uuid.uuid4()))
            
            async def stream_registration_event():
                try:
                    from service.websocket_streamer import get_websocket_streamer

                    streamer = await get_websocket_streamer()
                    if not streamer:
                        log_debug(f"⚠️ WebSocket streamer not available for agent registration")
                        return

                    event_data = {
                        "agentName": agent_card.name,
                        "status": "registered",
                        "timestamp": __import__('datetime').datetime.utcnow().isoformat(),
                        "avatar": "/placeholder.svg?height=32&width=32",
                        "agentPath": getattr(agent_card, 'url', ''),
                    }

                    success = await streamer._send_event("agent_registered", event_data, default_context_id)
                    if success:
                        log_debug(f"✅ Agent registration event streamed to WebSocket for {agent_card.name}")
                    else:
                        log_debug(f"❌ Failed to stream agent registration event to WebSocket for {agent_card.name}")
                except Exception as e:
                    log_debug(f"❌ Error streaming agent registration event: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Create background task for WebSocket streaming
            asyncio.create_task(stream_registration_event())
            
        except Exception as e:
            log_debug(f"❌ Error setting up agent registration event streaming: {e}")
            pass

    def _display_task_status_update(self, status_text: str, event: TaskCallbackArg):
        """Display a task status update in the UI as a message."""
        log_debug(f"_display_task_status_update called with: {status_text}")
        try:
            # Create a message to display in the UI
            from a2a.types import Message, TextPart, Part
            import uuid
            
            message_id = str(uuid.uuid4())
            context_id = getattr(event, 'contextId', getattr(self._current_task, 'contextId', str(uuid.uuid4())))
            log_debug(f"Created message_id: {message_id}, context_id: {context_id}")
            
            # Create a message with the status update
            status_message = Message(
                messageId=message_id,
                contextId=context_id,
                role="agent",  # Use agent role for status updates
                parts=[Part(root=TextPart(text=f"[Status] {status_text}"))]
            )
            
            # Add to the conversation history through the host manager
            if self._host_manager:
                log_debug(f"Host manager found, getting conversation for context_id: {context_id}")
                # Try to find the conversation with the given context_id first
                conversation = self._host_manager.get_conversation(context_id)
                
                # If not found, try to find any active conversation (fallback)
                if not conversation and self._host_manager.conversations:
                    # Use the most recent active conversation
                    active_conversations = [c for c in self._host_manager.conversations if c.is_active]
                    if active_conversations:
                        conversation = active_conversations[-1]  # Most recent
                        # Create a new message with the correct context_id to match the found conversation
                        status_message = Message(
                            messageId=message_id,
                            contextId=conversation.conversation_id,  # Use the correct contextId
                            role="agent",  # Use agent role for status updates
                            parts=[Part(root=TextPart(text=f"[Status] {status_text}"))]
                        )
                        log_debug(f"Using fallback conversation: {conversation.conversation_id}")
                
                if conversation:
                    conversation.messages.append(status_message)
                    log_debug(f"✅ Added status message to conversation: {status_text}")
                else:
                    log_debug(f"❌ No conversation found for context_id: {context_id}")
            else:
                log_debug(f"❌ No host manager reference available")
            
            # Also add to local messages list
            if hasattr(self, '_messages'):
                self._messages.append(status_message)
                log_debug(f"Added to local messages list")
            
            # Also add to the conversation state that the UI reads from
            # This ensures the status messages appear in the conversation flow
            if hasattr(self, 'session_contexts') and context_id in self.session_contexts:
                session_context = self.session_contexts[context_id]
                if not hasattr(session_context, 'messages'):
                    session_context.messages = []
                session_context.messages.append(status_message)
                log_debug(f"Added to session context messages")
            
            log_debug(f"Status message created successfully: {status_text}")
            
        except Exception as e:
            log_debug(f"❌ Error displaying task status update: {e}")
            import traceback
            traceback.print_exc()

    def _get_status_display_text(self, status) -> str:
        """Convert task status to display text."""
        if hasattr(status, 'state'):
            state = status.state
            if hasattr(state, 'value'):
                state_value = state.value
            else:
                state_value = str(state)
            
            state_map = {
                'submitted': 'Task submitted',
                'working': 'Task working',
                'completed': 'Task completed',
                'failed': 'Task failed',
                'canceled': 'Task canceled',
                'input-required': 'Input required',
                'unknown': 'Task status unknown'
            }
            
            return state_map.get(state_value, f"Task {state_value}")
        
        return "Status update"

    def _extract_message_content(self, message) -> str:
        """Extract text content from a message object or dictionary."""
        try:
            # Handle dictionary format (from HTTP API responses)
            if isinstance(message, dict):
                content = message.get('content', [])
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get('type') == 'text':
                            text = item.get('text', {})
                            # Handle nested text object or direct string
                            if isinstance(text, dict):
                                return text.get('value', '')
                            return str(text)
                elif isinstance(content, str):
                    return content
                return ""
            
            # Handle object format (from SDK responses)
            if hasattr(message, 'parts'):
                for part in message.parts:
                    if hasattr(part, 'root') and hasattr(part.root, 'text'):
                        return part.root.text
                    elif hasattr(part, 'text'):
                        return part.text
            elif hasattr(message, 'content'):
                return str(message.content)
            return ""
        except Exception as e:
            log_foundry_debug(f"⚠️ Error extracting message content: {e}")
            return ""

    @staticmethod
    def _extract_text_from_response(obj) -> str:
        """Extract clean text from various A2A response types.
        
        Handles Part, TextPart, DataPart objects and avoids ugly Python repr output.
        """
        if obj is None:
            return ""
        if isinstance(obj, str):
            return obj
        # Handle Part objects with root
        if hasattr(obj, 'root'):
            root = obj.root
            if hasattr(root, 'text'):
                return root.text
            if hasattr(root, 'kind') and root.kind == 'text' and hasattr(root, 'text'):
                return root.text
            if hasattr(root, 'data'):
                return str(root.data)
        # Handle TextPart/DataPart directly
        if hasattr(obj, 'kind'):
            if obj.kind == 'text' and hasattr(obj, 'text'):
                return obj.text
            if obj.kind == 'data' and hasattr(obj, 'data'):
                return str(obj.data)
        # Handle dict
        if isinstance(obj, dict):
            if 'text' in obj:
                return obj['text']
            return str(obj)
        # Handle list - extract text from each item
        if isinstance(obj, list):
            texts = [FoundryHostAgent2._extract_text_from_response(item) for item in obj]
            return "\n".join(t for t in texts if t)
        # Fallback - but avoid ugly repr
        result = str(obj)
        # If it looks like a Python repr, try to extract the text
        if result.startswith("kind='text'") and "text='" in result:
            import re
            match = re.search(r"text='([^']*)'", result)
            if match:
                return match.group(1).replace("\\n", "\n")
        return result

    def get_session_context(self, context_id: str) -> SessionContext:
        if context_id not in self.session_contexts:
            # Clear host response tracking for new conversations
            if context_id in self._host_responses_sent:
                self._host_responses_sent.remove(context_id)
            self.session_contexts[context_id] = SessionContext(contextId=context_id)
        return self.session_contexts[context_id]

    async def create_thread(self, context_id: str) -> Dict[str, Any]:
        if context_id in self.threads:
            # Return thread info instead of thread object
            log_foundry_debug(f"Thread already exists for context {context_id}, returning existing ID: {self.threads[context_id]}")
            return {"id": self.threads[context_id]}
        
        log_foundry_debug(f"Creating new thread for context {context_id}")
        
        try:
            log_foundry_debug(f"Getting authentication headers...")
            # Get authentication headers
            headers = await self._get_auth_headers()
            log_foundry_debug(f"Auth headers obtained successfully")
            
            # Get the API URL for threads
            endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
            api_url = f"{endpoint}/threads"
            log_foundry_debug(f"Thread creation API URL: {api_url}")
            
            log_foundry_debug(f"Making POST request to create thread...")
            # Create thread via HTTP API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    api_url,
                    headers=headers,
                    json={},  # Empty body for thread creation
                    params={"api-version": "2025-05-15-preview"},
                    timeout=30.0
                )
                
                log_foundry_debug(f"Thread creation response status: {response.status_code}")
                
                if response.status_code == 200 or response.status_code == 201:
                    thread_data = response.json()
                    thread_id = thread_data["id"]
                    log_foundry_debug(f"✅ Thread created successfully! ID: {thread_id}")
                    
                    # Store the thread ID
                    self.threads[context_id] = thread_id
                    
                    return thread_data
                else:
                    log_foundry_debug(f"❌ Thread creation failed with status {response.status_code}")
                    log_foundry_debug(f"❌ Response text: {response.text}")
                    raise Exception(f"Failed to create thread: {response.status_code} - {response.text}")
                    
        except Exception as e:
            log_foundry_debug(f"❌ Exception in create_thread(): {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            raise

    async def send_message_to_thread(self, thread_id: str, content: str, role: str = "user") -> Dict[str, Any]:
        log_foundry_debug(f"send_message_to_thread ENTRY - thread_id: {thread_id}, role: {role}")
        log_foundry_debug(f"Message content length: {len(content)} chars")
        
        try:
            log_foundry_debug(f"Getting auth headers...")
            # Get authentication headers
            headers = await self._get_auth_headers()
            log_foundry_debug(f"Auth headers obtained successfully")
            
            # Get the API URL for messages
            endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
            api_url = f"{endpoint}/threads/{thread_id}/messages"
            log_foundry_debug(f"Message API URL: {api_url}")
            
            # Prepare message payload
            payload = {
                "role": role,
                "content": content
            }
            log_foundry_debug(f"Message payload prepared")
            
            log_foundry_debug(f"Making POST request to send message...")
            # Send message via HTTP API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    api_url,
                    headers=headers,
                    json=payload,
                    params={"api-version": "2025-05-15-preview"},
                    timeout=30.0
                )
                
                log_foundry_debug(f"Message creation response status: {response.status_code}")
                
                if response.status_code == 200 or response.status_code == 201:
                    message_data = response.json()
                    log_foundry_debug(f"✅ Message sent successfully! ID: {message_data.get('id', 'N/A')}")
                    return message_data
                elif response.status_code == 401:
                    log_foundry_debug(f"🔄 Authentication failed (401), clearing cached token")
                    self._clear_cached_token()
                    log_foundry_debug(f"❌ Message creation failed with status {response.status_code}")
                    log_foundry_debug(f"❌ Response text: {response.text}")
                    raise Exception(f"Failed to send message (authentication failed): {response.status_code} - {response.text}")
                else:
                    log_foundry_debug(f"❌ Message creation failed with status {response.status_code}")
                    log_foundry_debug(f"❌ Response text: {response.text}")
                    raise Exception(f"Failed to send message: {response.status_code} - {response.text}")
                    
        except Exception as e:
            log_foundry_debug(f"❌ Exception in send_message_to_thread(): {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            raise

    async def _search_relevant_memory(self, query: str, context_id: str, agent_name: str = None, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search for relevant memory interactions to provide context to remote agents.
        
        Args:
            query: The search query
            context_id: The context ID for tenant-scoped search
            agent_name: Optional agent name to filter by
            top_k: Number of results to return
        """
        
        try:
            # Extract session_id for tenant isolation
            session_id = get_tenant_from_context(context_id)
            
            # Build filters if agent name is specified
            filters = {}
            if agent_name:
                filters["agent_name"] = agent_name
            
            # Search for similar interactions (tenant-scoped)
            memory_results = await a2a_memory_service.search_similar_interactions(
                query=query,
                session_id=session_id,
                filters=filters,
                top_k=top_k
            )
            
            return memory_results
            
        except Exception as e:
            return []

    def clear_memory_index(self, context_id: str = None) -> bool:
        """Clear stored interactions from the memory index.
        
        Args:
            context_id: If provided, only clear interactions for this session.
                       If None, clears ALL interactions (admin use only).
        """
        try:
            session_id = None
            if context_id:
                session_id = get_tenant_from_context(context_id)
            
            success = a2a_memory_service.clear_all_interactions(session_id=session_id)
            if success:
                return success
            else:
                return False
        except Exception as e:
            return False

    async def _create_memory_artifact(self, memory_results: List[Dict[str, Any]], query: str) -> Optional[Artifact]:
        """Create a memory artifact from search results to send to remote agents"""
        if not memory_results:
            return None
            
        try:
            print(f"Creating memory artifact from {len(memory_results)} interactions")
            
            # Process memory results into structured format
            session_timeline = []
            agent_patterns = {}
            file_references = []
            related_interactions = []
            
            for result in memory_results:
                try:
                    # Parse the stored JSON payloads
                    outbound_payload = json.loads(result.get('outbound_payload', '{}'))
                    inbound_payload = json.loads(result.get('inbound_payload', '{}'))
                    
                    agent_name = result.get('agent_name', 'unknown')
                    timestamp = result.get('timestamp', '')
                    processing_time = result.get('processing_time_seconds', 0)
                    
                    # Extract interaction summary
                    interaction_summary = {
                        "timestamp": timestamp,
                        "agent_name": agent_name,
                        "processing_time_seconds": processing_time,
                        "interaction_type": "host_to_remote" if agent_name != "host_agent" else "user_to_host"
                    }
                    
                    # Extract user request from outbound payload
                    if outbound_payload.get('message', {}).get('parts'):
                        parts = outbound_payload['message']['parts']
                        text_parts = [p.get('text', '') for p in parts if p.get('text')]
                        if text_parts:
                            interaction_summary["user_request"] = text_parts[0][:200] + "..." if len(text_parts[0]) > 200 else text_parts[0]
                    
                    # Extract agent response from inbound payload
                    if inbound_payload.get('artifacts'):
                        artifacts = inbound_payload['artifacts']
                        for artifact in artifacts:
                            if artifact.get('parts'):
                                text_parts = [p.get('text', '') for p in artifact['parts'] if p.get('text')]
                                if text_parts:
                                    interaction_summary["agent_response"] = text_parts[0][:200] + "..." if len(text_parts[0]) > 200 else text_parts[0]
                                    break
                    
                    session_timeline.append(interaction_summary)
                    
                    # Track agent patterns
                    if agent_name not in agent_patterns:
                        agent_patterns[agent_name] = {
                            "interaction_count": 0,
                            "avg_processing_time": 0,
                            "common_requests": []
                        }
                    
                    agent_patterns[agent_name]["interaction_count"] += 1
                    agent_patterns[agent_name]["avg_processing_time"] = (
                        agent_patterns[agent_name]["avg_processing_time"] + processing_time
                    ) / 2
                    
                    # Extract file references
                    if outbound_payload.get('message', {}).get('parts'):
                        for part in outbound_payload['message']['parts']:
                            if part.get('file') and 'artifact_uri' in str(part.get('file', {})):
                                file_ref = {
                                    "timestamp": timestamp,
                                    "agent_name": agent_name,
                                    "file_info": part['file']
                                }
                                file_references.append(file_ref)
                    
                    # Store complete interaction for reference
                    related_interactions.append({
                        "timestamp": timestamp,
                        "agent_name": agent_name,
                        "outbound_summary": str(outbound_payload)[:500] + "...",
                        "inbound_summary": str(inbound_payload)[:500] + "..."
                    })
                    
                except Exception as e:
                    continue
            
            # Create the memory artifact data
            memory_data = {
                "search_query": query,
                "search_timestamp": datetime.utcnow().isoformat() + 'Z',
                "total_results": len(memory_results),
                "session_timeline": sorted(session_timeline, key=lambda x: x.get('timestamp', '')),
                "agent_patterns": agent_patterns,
                "file_references": file_references,
                "related_interactions": related_interactions[:3]  # Limit to top 3 most relevant
            }
            
            # Create the artifact
            memory_artifact = Artifact(
                name="relevant_memory",
                description=f"Historical context and patterns relevant to: {query}",
                parts=[
                    DataPart(data=memory_data)
                ]
            )
            
            print(f"✅ Created memory artifact with {len(session_timeline)} timeline entries")
            print(f"✅ Memory artifact includes {len(agent_patterns)} agent patterns")
            print(f"✅ Memory artifact includes {len(file_references)} file references")
            
            return memory_artifact
            
        except Exception as e:
            import traceback
            print(f"❌ Error creating memory artifact: {e}")
            print(f"❌ Traceback: {traceback.format_exc()}")
            return None

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
        with tracer.start_as_current_span("send_message") as span:
            span.set_attribute("agent_name", agent_name)
            span.set_attribute("suppress_streaming", suppress_streaming)
            session_context = tool_context.state  # Should be SessionContext
            if not isinstance(session_context, SessionContext):
                raise TypeError(
                    "tool_context.state must be a SessionContext instance for A2A-compliant send_message"
                )

            # FIXED: Only generate IDs if they don't exist (preserve shared context for parallel calls)
            import uuid
            if not hasattr(session_context, 'contextId') or not session_context.contextId:
                session_context.contextId = str(uuid.uuid4())
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
            print(f"  • _latest_processed_parts exists: {hasattr(session_context, '_latest_processed_parts')}")
            print(f"  • session_parts count: {len(session_parts)}")
            print(f"  • agent_mode: {getattr(session_context, 'agent_mode', False)}")

            if session_parts:
                log_debug(f"📦 Prepared {len(session_parts)} parts for remote agent {agent_name} (context {contextId})")
                for idx, prepared_part in enumerate(session_parts):
                    part_root = getattr(prepared_part, "root", prepared_part)
                    kind = getattr(part_root, "kind", getattr(part_root, "type", type(part_root).__name__))
                    print(f"  • Prepared part {idx}: kind={kind}")
                    
                    # Enhanced file part logging with role information
                    if isinstance(part_root, FilePart) and hasattr(part_root, "file"):
                        file_obj = part_root.file
                        file_name = getattr(file_obj, 'name', 'unknown')
                        file_uri = getattr(file_obj, 'uri', 'no-uri')
                        # Check role in metadata (primary location for remote agents)
                        file_role = (part_root.metadata or {}).get("role", None) if hasattr(part_root, "metadata") else None
                        print(f"    → FilePart: name={file_name} role={file_role or 'no-role'}")
                        print(f"    → URI: {file_uri[:80]}..." if len(file_uri) > 80 else f"    → URI: {file_uri}")
                    elif hasattr(part_root, "file") and getattr(part_root.file, "uri", None):
                        print(f"    → file name={getattr(part_root.file, 'name', 'unknown')} uri={part_root.file.uri}")
                    
                    # Enhanced DataPart logging with role information
                    if isinstance(part_root, DataPart) and getattr(part_root, "data", None):
                        data_keys = list(part_root.data.keys()) if isinstance(part_root.data, dict) else []
                        print(f"    → data keys={data_keys}")
                        if isinstance(part_root.data, dict):
                            role = part_root.data.get("role", "no-role")
                            artifact_uri = part_root.data.get("artifact-uri", "")
                            file_name = part_root.data.get("file-name", "unknown")
                            if role != "no-role" or artifact_uri:
                                print(f"    → DataPart file: {file_name} role={role}")
                                if artifact_uri:
                                    print(f"    → Artifact URI: {artifact_uri[:80]}..." if len(artifact_uri) > 80 else f"    → Artifact URI: {artifact_uri}")

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
                id=str(uuid.uuid4()),
                message=Message(
                    role='user',
                    parts=prepared_parts,
                    messageId=messageId,
                    contextId=contextId,
                    taskId=taskId,
                ),
                configuration=MessageSendConfiguration(
                    acceptedOutputModes=['text', 'text/plain', 'image/png'],
                ),
            )
            
            log_debug(f"🚀 [PARALLEL] Calling agent: {agent_name} with context: {contextId}")
            
            # Track start time for processing duration
            start_time = time.time()
            
            try:
                # SIMPLIFIED: Callback for streaming execution that handles file artifacts
                # Status events are handled ONLY in _default_task_callback -> _emit_task_event
                def streaming_task_callback(event, agent_card):
                    """Callback for streaming execution - handles file artifacts only.
                    
                    CONSOLIDATED: Status updates are emitted ONLY via _emit_task_event
                    to prevent duplicate events in the UI.
                    """
                    agent_name = agent_card.name
                    log_debug(f"[STREAMING] Callback from {agent_name}: {type(event).__name__}")
                    
                    # Only handle file artifacts here - status events go through _emit_task_event
                    if hasattr(event, 'kind') and event.kind == 'status-update':
                        if hasattr(event, 'status') and event.status:
                            if hasattr(event.status, 'message') and event.status.message:
                                if hasattr(event.status.message, 'parts') and event.status.message.parts:
                                    # Process parts to find image artifacts (but NOT emit status events)
                                    for part in event.status.message.parts:
                                        # Check for image artifacts in DataPart
                                        if hasattr(part, 'root') and hasattr(part.root, 'data') and isinstance(part.root.data, dict):
                                            artifact_uri = part.root.data.get('artifact-uri')
                                            if artifact_uri:
                                                log_debug(f"Found image artifact in streaming event: {artifact_uri}")
                                                # Emit file_uploaded event
                                                async def emit_file_event(part_data=part.root.data, uri=artifact_uri):
                                                    try:
                                                        from service.websocket_streamer import get_websocket_streamer
                                                        streamer = await get_websocket_streamer()
                                                        if streamer:
                                                            file_info = {
                                                                "file_id": str(uuid.uuid4()),
                                                                "filename": part_data.get("file-name", "agent-artifact.png"),
                                                                "uri": uri,
                                                                "size": part_data.get("file-size", 0),
                                                                "content_type": "image/png",
                                                                "source_agent": agent_name,
                                                                "contextId": get_context_id(event)
                                                            }
                                                            await streamer.stream_file_uploaded(file_info, get_context_id(event))
                                                            log_debug(f"File uploaded event sent for streaming artifact: {file_info['filename']}")
                                                    except Exception as e:
                                                        log_debug(f"Error emitting file_uploaded event: {e}")
                                                asyncio.create_task(emit_file_event())
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
                                                    # Emit file_uploaded event
                                                    async def emit_file_event_fp():
                                                        try:
                                                            from service.websocket_streamer import get_websocket_streamer
                                                            streamer = await get_websocket_streamer()
                                                            if streamer:
                                                                file_info = {
                                                                    "file_id": str(uuid.uuid4()),
                                                                    "filename": file_name,
                                                                    "uri": file_uri,
                                                                    "size": 0,
                                                                    "content_type": mime_type,
                                                                    "source_agent": agent_name,
                                                                    "contextId": get_context_id(event)
                                                                }
                                                                await streamer.stream_file_uploaded(file_info, get_context_id(event))
                                                                log_debug(f"File uploaded event sent for streaming FilePart: {file_info['filename']}")
                                                        except Exception as e:
                                                            log_debug(f"Error emitting file_uploaded event for FilePart: {e}")
                                                    asyncio.create_task(emit_file_event_fp())
                    
                    # REMOVED: _emit_granular_agent_event calls that caused duplicate events
                    # Status events are now emitted ONLY via _default_task_callback -> _emit_task_event
                    
                    # Call the original callback for task management (which handles status emission)
                    return self._default_task_callback(event, agent_card)
                
                # Emit outgoing message event for DAG display (use original message, not contextualized)
                clean_message = message
                if isinstance(message, dict):
                    clean_message = message.get('text', message.get('message', str(message)))
                elif not isinstance(message, str):
                    clean_message = str(message)
                
                # Truncate very long messages for DAG display
                if len(clean_message) > 500:
                    clean_message = clean_message[:497] + "..."
                
                # IMPORTANT: Emit "working" status BEFORE any other events
                # This tells the frontend a new task is starting for this agent,
                # so it can advance to the next step before activity messages arrive
                async def emit_working_status():
                    try:
                        from service.websocket_streamer import get_websocket_streamer
                        streamer = await get_websocket_streamer()
                        if streamer:
                            event_data = {
                                "taskId": taskId or str(uuid.uuid4()),
                                "conversationId": contextId,
                                "contextId": contextId,
                                "state": "working",
                                "agentName": agent_name,
                                "artifactsCount": 0,
                                "timestamp": __import__('datetime').datetime.utcnow().isoformat(),
                            }
                            await streamer._send_event("task_updated", event_data, contextId)
                            log_debug(f"📡 Emitted working status for {agent_name} BEFORE calling agent")
                    except Exception as e:
                        log_debug(f"Error emitting pre-call working status: {e}")
                
                await emit_working_status()
                
                asyncio.create_task(self._emit_outgoing_message_event(agent_name, clean_message, contextId))
                
                response = await client.send_message(request, streaming_task_callback)
                print(f"✅ [STREAMING] Agent {agent_name} responded successfully!")
                
            except Exception as e:
                print(f"❌ [STREAMING] Agent {agent_name} failed: {e}")
                
                import traceback
                print(f"❌ Full traceback: {traceback.format_exc()}")
                raise
            
            print(f"🔄 [STREAMING] Processing response from {agent_name}: {type(response)}")
            
            # Simplified response processing for streaming execution
            if isinstance(response, Task):
                task = response
                
                # DEBUG: Log task response structure
                print(f"📊 Received Task response from {agent_name}:")
                print(f"  • Task ID: {task.id if hasattr(task, 'id') else 'N/A'}")
                print(f"  • Task state: {task.status.state if hasattr(task, 'status') else 'N/A'}")
                print(f"  • Has status.message: {hasattr(task, 'status') and hasattr(task.status, 'message') and task.status.message is not None}")
                print(f"  • Has artifacts: {hasattr(task, 'artifacts') and task.artifacts is not None}")
                if hasattr(task, 'artifacts') and task.artifacts:
                    print(f"  • Artifacts count: {len(task.artifacts)}")
                
                # Update session context only with essential info
                context_id = get_context_id(task)
                if context_id:
                    session_context.contextId = context_id
                # Record the task id for this specific agent only
                t_id = get_task_id(task)
                session_context.agent_task_ids[agent_name] = t_id
                # Track latest state for this agent's task
                try:
                    state_val = task.status.state.value if hasattr(task.status.state, 'value') else str(task.status.state)
                except Exception:
                    state_val = "working"
                session_context.agent_task_states[agent_name] = state_val
                
                # Handle task states
                print(f"🔍 Checking task state: {task.status.state} == TaskState.completed? {task.status.state == TaskState.completed}")
                print(f"🔍 task.status.state type: {type(task.status.state)}, TaskState.completed type: {type(TaskState.completed)}")
                if task.status.state == TaskState.completed:
                    response_parts = []
                    
                    # DEBUG: Check what's in the task
                    print(f"✅ Task completed - checking contents:")
                    print(f"  • task.status.message exists: {task.status.message is not None}")
                    if task.status.message:
                        print(f"  • task.status.message.parts count: {len(task.status.message.parts) if task.status.message.parts else 0}")
                    print(f"  • task.artifacts exists: {task.artifacts is not None}")
                    if task.artifacts:
                        print(f"  • task.artifacts count: {len(task.artifacts)}")
                        for idx, art in enumerate(task.artifacts):
                            print(f"  • artifact[{idx}].parts count: {len(art.parts) if art.parts else 0}")
                    
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
                                    print(f"💰 [TASK] Extracted token usage for {agent_name}: {self.agent_token_usage[agent_name]}")
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
                            # Note: Artifacts will be added to _agent_generated_artifacts with deduplication
                            # in the processing loop below (lines 3131-3168)

                    # DEBUG: Log what's now in _latest_processed_parts after conversion
                    if hasattr(session_context, "_latest_processed_parts"):
                        latest = session_context._latest_processed_parts
                        print(f"📦 After convert_parts, _latest_processed_parts has {len(latest)} items total (accumulated)")
                        
                    # Add DataParts from THIS response to _agent_generated_artifacts for UI display
                    # Use response_parts (from THIS agent) instead of _latest_processed_parts (accumulated)
                    mode = "Agent Mode" if session_context.agent_mode else "Standard Mode"
                    print(f"🔍 [{mode}] Checking response_parts ({len(response_parts)} items) for DataParts to add...")
                    for item in response_parts:
                        if isinstance(item, DataPart) or (hasattr(item, 'root') and isinstance(item.root, DataPart)):
                            if not hasattr(session_context, '_agent_generated_artifacts'):
                                session_context._agent_generated_artifacts = []
                            session_context._agent_generated_artifacts.append(item)
                            print(f"📎 [STREAMING - {mode}] Added DataPart from THIS response to _agent_generated_artifacts")
                    
                    if hasattr(session_context, '_agent_generated_artifacts'):
                        print(f"✅ [{mode}] Total _agent_generated_artifacts: {len(session_context._agent_generated_artifacts)}")

                    self._update_last_host_turn(session_context, agent_name, response_parts)
                    
                    # Store interaction in background (don't await to avoid blocking streaming execution)
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
                    print(f"❌ [STREAMING] Task failed for {agent_name}")
                    # Detect rate limit and retry once after suggested delay
                    def _parse_retry_after_from_task(t) -> int:
                        try:
                            if hasattr(t, 'status') and t.status and getattr(t.status, 'message', None):
                                parts = getattr(t.status.message, 'parts', []) or []
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

                    retry_after = _parse_retry_after_from_task(task)
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
                                retry_after = _parse_retry_after_from_task(task2)
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
                    print(f"⚠️ [STREAMING] Agent {agent_name} requires input")
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
                log_debug(f"[STREAMING] String response from {agent_name}: {response[:200]}...")
                self._update_last_host_turn(session_context, agent_name, [response])
                return [response]
                
            else:
                log_debug(f"[STREAMING] Unknown response type from {agent_name}: {type(response)}")
                return [str(response)]
            
            print(f"send_message called for agent: {agent_name}")
            print(f"Original message: {message}")
            print(f"Contextualized message: {contextualized_message}")

            if hasattr(session_context, "_latest_processed_parts") and session_context._latest_processed_parts:
                log_debug(f"📦 Prepared {len(session_context._latest_processed_parts)} parts for remote agent {agent_name} (context {contextId})")
                for idx, prepared_part in enumerate(session_context._latest_processed_parts):
                    part_root = getattr(prepared_part, "root", prepared_part)
                    kind = getattr(part_root, "kind", getattr(part_root, "type", "unknown"))
                    print(f"  • Prepared part {idx}: kind={kind}")
                    if hasattr(part_root, "file") and getattr(part_root.file, "uri", None):
                        print(f"    → file name={getattr(part_root.file, 'name', 'unknown')} uri={part_root.file.uri}")
                    if isinstance(part_root, DataPart) and getattr(part_root, "data", None):
                        print(f"    → data keys={list(part_root.data.keys())}")

            print(f"MessageSendParams (as dict): {request.model_dump()}")
            
            # Track start time for processing duration
            start_time = time.time()
            
            # ENHANCED DEBUG: Add detailed logging around the hang point
            print(f" ABOUT TO CALL client.send_message...")
            print(f" Client type: {type(client)}")
            print(f" Client object: {client}")
            print(f" Request type: {type(request)}")
            print(f" Task callback type: {type(self.task_callback)}")
            print(f" About to make the actual call...")
            
            try:
                response = await client.send_message(request, self.task_callback)
                print(f"✅ client.send_message RETURNED successfully!")
                log_debug(f"Response type: {type(response)}")
                log_debug(f"Response content preview: {str(response)[:500]}...")
                
                # Add more detailed debugging for Task responses
                if hasattr(response, 'status') and hasattr(response.status, 'message'):
                    log_debug(f"Task response has status message with {len(response.status.message.parts) if response.status.message.parts else 0} parts")
                    if response.status.message.parts:
                        for i, part in enumerate(response.status.message.parts):
                            if hasattr(part.root, 'text'):
                                log_debug(f"Task message part {i}: {part.root.text[:300]}...")
                            else:
                                log_debug(f"Task message part {i}: {type(part.root)}")
                
                # Add debugging for Message responses
                elif hasattr(response, 'parts'):
                    log_debug(f"Message response has {len(response.parts) if response.parts else 0} parts")
                    if response.parts:
                        for i, part in enumerate(response.parts):
                            if hasattr(part.root, 'text'):
                                log_debug(f"Message part {i}: {part.root.text[:300]}...")
                            else:
                                log_debug(f"Message part {i}: {type(part.root)}")
            except Exception as e:
                print(f"❌ client.send_message FAILED with exception: {e}")
                print(f"❌ Exception type: {type(e).__name__}")
                import traceback
                print(f"❌ Full traceback: {traceback.format_exc()}")
                raise
            
            print(f"Raw response from remote agent: {response}")
            print(f"Response type: {type(response)}")
            
            # Track response type and processing
            span.set_attribute("response.type", type(response).__name__)
            
            # Check for Task first - this is the primary A2A response type
            if isinstance(response, Task):
                # Handle Task object as in ADK HostAgent
                task = response
                
                # Initialize response_parts for all task states
                response_parts = []
                
                # Enhanced task state tracking
                old_state = "unknown"
                new_state = task.status.state.value if hasattr(task.status.state, 'value') else str(task.status.state)
                span.set_attribute("task.state.current", new_state)
                span.set_attribute("task.id", task.id)
                
                # Track state transition
                span.add_event("task_state_change", {
                    "task_id": task.id,
                    "old_state": old_state,
                    "new_state": new_state,
                    "agent_name": agent_name
                })
                
                session_context.session_active = task.status.state not in [
                    TaskState.completed,
                    TaskState.canceled,
                    TaskState.failed,
                    TaskState.unknown,
                ]
                
                span.set_attribute("session.active_after_response", session_context.session_active)
                
                context_id_val = get_context_id(task)
                if context_id_val:
                    span.set_attribute("context.id_updated", context_id_val != session_context.contextId)
                    session_context.contextId = context_id_val
                # Record the task id for this specific agent only
                session_context.agent_task_ids[agent_name] = task.id
                session_context.task_state = new_state
                session_context.agent_task_states[agent_name] = new_state
                
                # ENHANCED: Handle different task states with evaluation and graceful failure handling
                if task.status.state == TaskState.completed:
                    # SUCCESS: Reset retry count and optionally evaluate
                    if hasattr(tool_context, 'actions'):
                        tool_context.actions.skip_summarization = False
                        tool_context.actions.escalate = False

                    # Clear any pending input_required state since this agent completed successfully
                    if session_context.pending_input_agent == agent_name:
                        log_info(f"🔄 [HITL] Clearing pending input state for completed agent '{agent_name}'")
                        session_context.pending_input_agent = None
                        session_context.pending_input_task_id = None

                    self._reset_retry_count(session_context)
                    
                    if self.enable_task_evaluation:
                        print(f"🔍 Evaluating completed task with direct OpenAI call...")
                        evaluation = await self._evaluate_task_completion(message, task, agent_name)
                        
                        span.set_attribute("evaluation.performed", True)
                        span.set_attribute("evaluation.is_successful", evaluation.get("is_successful", True))
                        span.set_attribute("evaluation.reason", evaluation.get("reason", ""))
                        
                        if not evaluation.get("is_successful", True):
                            print(f"❌ Task evaluation failed: {evaluation.get('reason')}")
                            span.add_event("evaluation_failed", {
                                "reason": evaluation.get("reason"),
                                "retry_suggestion": evaluation.get("retry_suggestion"),
                                "alternative_agent": evaluation.get("alternative_agent")
                            })
                            
                            # Check if we should retry
                            if retry_count < self.max_retries:
                                self._increment_retry_count(session_context)
                                print(f"🔄 Retrying ({retry_count + 1}/{self.max_retries}) with feedback...")
                                
                                # Retry with feedback to same agent
                                if evaluation.get("retry_suggestion"):
                                    retry_message = f"""Your previous response wasn't quite right. {evaluation['reason']}

{evaluation['retry_suggestion']}

Original request: {message}"""
                                    return await self.send_message(agent_name, retry_message, tool_context, suppress_streaming=True)
                            
                            # Max retries reached - convert to input_required
                            else:
                                print(f"❌ Max retries reached, asking user for guidance...")
                                tool_context.actions.skip_summarization = True
                                tool_context.actions.escalate = True
                                
                                options = self._generate_failure_recovery_options(task, agent_name, message)
                                
                                failure_msg = (
                                    f"I've tried multiple approaches but the results aren't quite right. " +
                                    f"Issue: {evaluation.get('reason', 'Response does not fully address your request')}\n\n" +
                                    f"How would you like me to proceed?\n" + 
                                    "\n".join([f"{i+1}. {option}" for i, option in enumerate(options)]) +
                                    f"\n\nPlease choose a number or tell me what you'd like to do differently."
                                )
                                return [failure_msg]
                    
                    # Task completed successfully (evaluation passed or disabled)
                    self._reset_retry_count(session_context)
                    
                    # Task completed successfully (or evaluation passed)
                    response_parts = []
                    if task.status.message:
                        log_debug(f"Task status message parts: {len(task.status.message.parts) if task.status.message.parts else 0}")
                        for i, part in enumerate(task.status.message.parts):
                            if hasattr(part.root, 'text'):
                                log_debug(f"Status message part {i}: {part.root.text[:200]}...")
                        response_parts.extend(
                            await self.convert_parts(task.status.message.parts, tool_context)
                        )
                    if task.artifacts:
                        span.set_attribute("response.artifacts_count", len(task.artifacts))
                        span.add_event("artifacts_received", {
                            "count": len(task.artifacts),
                            "agent_name": agent_name,
                            "task_id": task.id
                        })
                        log_debug(f"Task has {len(task.artifacts)} artifacts")
                        for i, artifact in enumerate(task.artifacts):
                            log_debug(f"Artifact {i} parts: {len(artifact.parts) if artifact.parts else 0}")
                            for j, part in enumerate(artifact.parts):
                                if hasattr(part.root, 'text'):
                                    log_debug(f"Artifact {i} part {j}: {part.root.text[:200]}...")
                        response_parts.extend(
                            await self.convert_parts(artifact.parts, tool_context)
                        )
                    
                    # NOTE: Individual agent responses are always suppressed by default
                    # Only the host agent should send responses to the main chat
                    if not suppress_streaming:
                        log_debug(f"Streaming remote agent response to WebSocket for agent: {agent_name} (OVERRIDE - normally suppressed)")
                        try:
                            from websocket_streamer import get_websocket_streamer
                            
                            # Make WebSocket streaming synchronous to avoid interfering with parallel execution
                            try:
                                streamer = await get_websocket_streamer()
                                if streamer:
                                    # Extract response text for event
                                    response_text = ""
                                    if response_parts:
                                        response_text = " ".join([str(part) for part in response_parts])
                                    elif task.status.message and task.status.message.parts:
                                        for part in task.status.message.parts:
                                            if hasattr(part.root, 'text'):
                                                response_text += part.root.text + " "
                                    
                                    # Send in A2A MessageEventData format
                                    event_data = {
                                        "messageId": str(uuid.uuid4()),
                                        "conversationId": contextId or "",
                                        "contextId": contextId or "",
                                        "role": "assistant",
                                        "content": [
                                            {
                                                "type": "text",
                                                "content": response_text.strip(),
                                                "mediaType": "text/plain"
                                            }
                                        ],
                                        "direction": "incoming",
                                        "agentName": agent_name,
                                        "timestamp": __import__('datetime').datetime.utcnow().isoformat()
                                    }
                                    
                                    # Await the streaming to completion before continuing
                                    success = await streamer._send_event("message", event_data, contextId)
                                    if success:
                                        log_debug(f"Remote agent response event streamed: {event_data}")
                                    else:
                                        log_debug("Failed to stream remote agent response event")
                                else:
                                    log_debug("WebSocket streamer not available for remote agent response")
                            except Exception as e:
                                log_debug(f"Error streaming remote agent response to WebSocket: {e}")
                                # Don't let WebSocket errors break the main flow
                                pass
                            
                        except ImportError:
                            # WebSocket module not available, continue without streaming
                            log_debug("WebSocket module not available for response")
                            pass
                        except Exception as e:
                            log_debug(f"Error setting up remote agent response streaming: {e}")
                            # Don't let WebSocket errors break the main flow
                            pass
                    else:
                        log_debug(f"Individual agent response streaming suppressed for agent: {agent_name} (default behavior - only host agent responds to user)")
                        log_debug(f"Context ID: {contextId}, Response parts count: {len(response_parts)}")
                        log_debug(f"suppress_streaming = {suppress_streaming} (should be True for individual agents)")
                    
                    log_debug(f"Final response_parts count: {len(response_parts)}")
                    for i, part in enumerate(response_parts):
                        if isinstance(part, str):
                            log_debug(f"Response part {i}: {part[:200]}...")
                        else:
                            log_debug(f"Response part {i}: {type(part)} - {str(part)[:200]}...")
                    
                    span.set_attribute("response.parts_count", len(response_parts))
                    
                elif task.status.state == TaskState.input_required:
                    span.add_event("input_required", {
                        "task_id": task.id,
                        "agent_name": agent_name,
                        "reason": "Agent requires additional input to proceed"
                    })
                    tool_context.actions.skip_summarization = True
                    tool_context.actions.escalate = True
                    
                    # Track which agent is waiting for input so we can route follow-up messages
                    session_context.pending_input_agent = agent_name
                    session_context.pending_input_task_id = task.id
                    log_info(f"🔄 [HITL] Agent '{agent_name}' set to input_required, awaiting user response (task_id: {task.id})")
                    
                    # For input_required, provide the status message if available
                    if task.status.message:
                        response_parts.extend(
                            await self.convert_parts(task.status.message.parts, tool_context)
                        )
                    else:
                        response_parts.append("Task requires additional input to proceed.")
                    
                elif task.status.state == TaskState.canceled:
                    span.add_event("task_cancelled", {
                        "task_id": task.id,
                        "agent_name": agent_name
                    })
                    raise ValueError(f'Agent {agent_name} task {task.id} is cancelled')
                    
                elif task.status.state == TaskState.failed:
                    span.add_event("task_failed", {
                        "task_id": task.id,
                        "agent_name": agent_name
                    })
                    
                    # ENHANCED: Graceful failure handling instead of crashing
                    failure_reason = self._extract_failure_reason(task)
                    print(f"❌ Task failed: {failure_reason}")
                    
                    # Check if we should retry
                    if retry_count < self.max_retries:
                        self._increment_retry_count(session_context)
                        print(f"🔄 Retrying task (attempt {retry_count + 1}/{self.max_retries})...")
                        
                        # Try same agent again (maybe it was a temporary issue)
                        span.add_event("task_retry", {
                            "attempt": retry_count + 1,
                            "max_retries": self.max_retries,
                            "failure_reason": failure_reason
                        })
                        
                        return await self.send_message(agent_name, message, tool_context, suppress_streaming=True)
                    
                    # Max retries reached - convert to input_required instead of crashing
                    else:
                        print(f"❌ Max retries reached, converting failure to input_required...")
                        tool_context.actions.skip_summarization = True
                        tool_context.actions.escalate = True
                        
                        options = self._generate_failure_recovery_options(task, agent_name, message)
                        
                        span.add_event("failure_converted_to_input_required", {
                            "failure_reason": failure_reason,
                            "retry_attempts": retry_count,
                            "recovery_options_count": len(options)
                        })
                        
                        failure_msg = (
                            f"I encountered an issue: {failure_reason}\n\n" +
                            f"After {retry_count} attempts, I need your guidance. How would you like me to proceed?\n" +
                            "\n".join([f"{i+1}. {option}" for i, option in enumerate(options)]) +
                            f"\n\nPlease choose a number or tell me what you'd like to do differently."
                        )
                        return [failure_msg]
                
                else:
                    # Handle any other task states (working, unknown, etc.)
                    span.add_event("task_state_other", {
                        "task_id": task.id,
                        "agent_name": agent_name,
                        "state": new_state
                    })
                    
                    # For other states, try to extract available content
                    if task.status.message:
                        response_parts.extend(
                            await self.convert_parts(task.status.message.parts, tool_context)
                        )
                    
                    if task.artifacts:
                        for artifact in task.artifacts:
                            response_parts.extend(
                                await self.convert_parts(artifact.parts, tool_context)
                            )
                    
                    # If no content available, provide status message
                    if not response_parts:
                        response_parts.append(f"Task is in {new_state} state.")
                    
                # Store A2A interaction in memory
                await self._store_a2a_interaction(
                    outbound_request=request,
                    inbound_response=response,
                    agent_name=agent_name,
                    processing_time=time.time() - start_time,
                    span=span,
                    context_id=contextId
                )
                
                return response_parts
                
            elif isinstance(response, Message):
                span.add_event("direct_message_response", {
                    "agent_name": agent_name,
                    "message_id": get_message_id(response, "unknown")
                })
                # Update session context from Message if it has task/context info
                task_id_val = get_task_id(response, None)
                if task_id_val:
                    # Record the task id for this specific agent only
                    session_context.agent_task_ids[agent_name] = task_id_val
                context_id_val = get_context_id(response)
                if context_id_val:
                    session_context.contextId = context_id_val
                result = await self.convert_parts(response.parts, tool_context)
                span.set_attribute("response.parts_count", len(result))
                
                # NOTE: Individual agent message responses are always suppressed by default
                # Only the host agent should send responses to the main chat
                if not suppress_streaming:
                    log_debug(f"Streaming remote agent direct message to WebSocket for agent: {agent_name} (OVERRIDE - normally suppressed)")
                    try:
                        from websocket_streamer import get_websocket_streamer
                        
                        # Make WebSocket streaming synchronous to avoid interfering with parallel execution
                        try:
                            streamer = await get_websocket_streamer()
                            if streamer:
                                # Extract response text for event
                                response_text = ""
                                if result:
                                    response_text = " ".join([str(part) for part in result])
                                elif response.parts:
                                    for part in response.parts:
                                        if hasattr(part.root, 'text'):
                                            response_text += part.root.text + " "
                                
                                # Send in A2A MessageEventData format
                                event_data = {
                                    "messageId": response.messageId if hasattr(response, 'messageId') else str(uuid.uuid4()),
                                    "conversationId": contextId or "",
                                    "contextId": contextId or "",
                                    "role": "assistant",
                                    "content": [
                                        {
                                            "type": "text",
                                            "content": response_text.strip(),
                                            "mediaType": "text/plain"
                                        }
                                    ],
                                    "direction": "incoming",
                                    "agentName": agent_name,
                                    "timestamp": __import__('datetime').datetime.utcnow().isoformat()
                                }
                                
                                # Await the streaming to completion before continuing
                                success = await streamer._send_event("message", event_data, contextId)
                                if success:
                                    log_debug(f"Remote agent direct message event streamed: {event_data}")
                                else:
                                    log_debug("Failed to stream remote agent direct message event")
                            else:
                                log_debug("WebSocket streamer not available for direct message")
                        except Exception as e:
                            log_debug(f"Error streaming remote agent direct message to WebSocket: {e}")
                            # Don't let WebSocket errors break the main flow
                            pass
                        
                    except ImportError:
                        # WebSocket module not available, continue without streaming
                        log_debug("WebSocket module not available for direct message")
                        pass
                    except Exception as e:
                        log_debug(f"Error setting up direct message streaming: {e}")
                        # Don't let WebSocket errors break the main flow
                        pass
                else:
                    log_debug(f"Individual agent direct message streaming suppressed for agent: {agent_name} (default behavior - only host agent responds to user)")
                    log_debug(f"Context ID: {contextId}, Result count: {len(result)}")
                    log_debug(f"suppress_streaming = {suppress_streaming} (should be True for individual agents)")
                
                # Store A2A interaction in memory
                await self._store_a2a_interaction(
                    outbound_request=request,
                    inbound_response=response,
                    agent_name=agent_name,
                    processing_time=time.time() - start_time,
                    span=span,
                    context_id=contextId
                )
                
                return result
            elif isinstance(response, list):
                span.add_event("list_response", {
                    "agent_name": agent_name,
                    "list_length": len(response)
                })
                # Assume it's a list of Part-like dicts, convert each
                result = await self.convert_parts(response, tool_context)
                span.set_attribute("response.parts_count", len(result))
                
                # Store A2A interaction in memory
                await self._store_a2a_interaction(
                    outbound_request=request,
                    inbound_response=response,
                    agent_name=agent_name,
                    processing_time=time.time() - start_time,
                    span=span,
                    context_id=contextId
                )
                
                return result
            elif hasattr(response, 'parts'):
                span.add_event("parts_response", {
                    "agent_name": agent_name,
                    "parts_count": len(response.parts) if response.parts else 0
                })
                result = await self.convert_parts(response.parts, tool_context)
                span.set_attribute("response.parts_count", len(result))
                
                # Store A2A interaction in memory
                await self._store_a2a_interaction(
                    outbound_request=request,
                    inbound_response=response,
                    agent_name=agent_name,
                    processing_time=time.time() - start_time,
                    span=span,
                    context_id=contextId
                )
                
                return result
            elif hasattr(response, 'status') and hasattr(response.status, 'message') and response.status.message:
                span.add_event("status_message_response", {
                    "agent_name": agent_name,
                    "status_type": type(response.status).__name__
                })
                result = await self.convert_parts(response.status.message.parts, tool_context)
                span.set_attribute("response.parts_count", len(result))
                
                # Store A2A interaction in memory
                await self._store_a2a_interaction(
                    outbound_request=request,
                    inbound_response=response,
                    agent_name=agent_name,
                    processing_time=time.time() - start_time,
                    span=span,
                    context_id=contextId
                )
                
                return result
            elif isinstance(response, str):
                span.add_event("string_response", {
                    "agent_name": agent_name,
                    "response_length": len(response)
                })
                log_debug(f"String response received: {response[:200]}...")
                # Return string response directly without processing through convert_parts
                # This preserves any formatting including sources
                return [response]
            else:
                span.add_event("unknown_response_type", {
                    "agent_name": agent_name,
                    "response_type": type(response).__name__
                })
                print(f"Unknown response type, returning as-is: {response}")
                
                # Store A2A interaction in memory (unknown response type)
                await self._store_a2a_interaction(
                    outbound_request=request,
                    inbound_response=response,
                    agent_name=agent_name,
                    processing_time=time.time() - start_time,
                    span=span,
                    context_id=contextId
                )
                
                return response

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
        if enable_memory:
            log_debug(f"🎯 [{mode_label}] Inter-agent memory enabled - searching vector memory")
        try:
            log_debug(f"🧠 Searching memory for semantically relevant context...")
            log_debug(f"About to call _search_relevant_memory...")
            memory_results = await self._search_relevant_memory(
                query=message,
                context_id=session_context.contextId,
                agent_name=None,  # Search across all interactions for maximum relevance
                top_k=5  # Get top 5 most relevant pieces of context
            )
            print(f"✅ _search_relevant_memory completed, got {len(memory_results) if memory_results else 0} results")
            
            if memory_results:
                context_parts.append("Relevant context from previous interactions:")
                print(f"Processing {len(memory_results)} memory results...")
                
                # Debug: Show structure of first result
                if memory_results:
                    first_result = memory_results[0]
                    print(f"First result keys: {list(first_result.keys()) if isinstance(first_result, dict) else 'Not a dict'}")
                    if isinstance(first_result, dict) and 'a2a_inbound_response' in first_result:
                        inbound = first_result['a2a_inbound_response']
                        print(f"Inbound response type: {type(inbound)}")
                        if isinstance(inbound, dict):
                            print(f"Inbound response keys: {list(inbound.keys())}")
                        elif isinstance(inbound, str):
                            print(f"Inbound response (string): {inbound[:200]}...")
                
                # Process memory results to extract key information
                for i, result in enumerate(memory_results, 1):
                    try:
                        # Extract the most relevant parts from each memory result
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
                                        # Look for text in various structures
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
                "timestamp": datetime.utcnow().isoformat() + 'Z',
                
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
                "timestamp": datetime.utcnow().isoformat() + 'Z',
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
            
            if not context_id:
                context_id = self.default_context_id
            log_debug(f"Step: Set context_id to {context_id}")
            
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
            # If so, route this message directly to that agent instead of normal orchestration
            if session_context.pending_input_agent:
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
                
                # Route directly to the waiting agent
                try:
                    tool_context = DummyToolContext(session_context, self._azure_blob_client)
                    hitl_response = await self.send_message(
                        agent_name=pending_agent,
                        message=hitl_user_message,
                        tool_context=tool_context,
                        suppress_streaming=False
                    )
                    log_info(f"🔄 [HITL] Response from agent '{pending_agent}': {str(hitl_response)[:200]}...")
                    
                    # Helper to extract clean text from responses
                    def clean_response(resp):
                        if isinstance(resp, list):
                            return [self._extract_text_from_response(r) for r in resp]
                        return [self._extract_text_from_response(resp)]
                    
                    # Check if agent is STILL requesting input (multi-turn HITL)
                    if session_context.pending_input_agent:
                        log_info(f"🔄 [HITL] Agent still requires more input - staying paused")
                        # Keep the pending workflow state for next turn
                        return clean_response(hitl_response)
                    
                    # Agent completed! Check if we need to resume a paused workflow
                    if pending_workflow:
                        log_info(f"▶️ [HITL] Agent completed - RESUMING WORKFLOW")
                        
                        # Add this agent's response to the collected outputs (properly extract text)
                        hitl_outputs = clean_response(hitl_response)
                        all_outputs = pending_workflow_outputs + hitl_outputs
                        
                        # Clear workflow pause state
                        session_context.pending_workflow = None
                        session_context.pending_workflow_outputs = []
                        session_context.pending_workflow_user_message = None
                        
                        log_info(f"▶️ [HITL] Resuming workflow with {len(all_outputs)} total outputs")
                        
                        # Continue the workflow from where we left off
                        # The orchestrator will pick up from the next step
                        remaining_outputs = await self._agent_mode_orchestration_loop(
                            user_message="Continue the workflow. The previous step has completed.",
                            context_id=context_id,
                            session_context=session_context,
                            event_logger=event_logger,
                            workflow=pending_workflow
                        )
                        
                        # Clean any remaining outputs too
                        clean_remaining = []
                        for out in remaining_outputs:
                            clean_remaining.append(self._extract_text_from_response(out))
                        
                        return all_outputs + clean_remaining
                    
                    return clean_response(hitl_response)
                except Exception as e:
                    log_error(f"🔄 [HITL] Error routing to pending agent '{pending_agent}': {e}")
                    # Fall through to normal processing if routing fails
                    import traceback
                    traceback.print_exc()
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
            
            # Create or get thread
            thread_created = False
            if context_id not in self.threads:
                log_foundry_debug(f"Creating new thread for context_id: {context_id}")
                thread = await self.create_thread(context_id)
                self.threads[context_id] = thread["id"]  # Use dictionary access
                thread_created = True
                log_foundry_debug(f"New thread created with ID: {thread['id']}")
            else:
                log_foundry_debug(f"Reusing existing thread for context_id: {context_id}, thread_id: {self.threads[context_id]}")
            thread_id = self.threads[context_id]
            
            log_foundry_debug(f"=================== THREAD READY, STARTING MESSAGE PROCESSING ===================")
            log_foundry_debug(f"Thread ID: {thread_id}")
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

            def _wrap_for_agent(item: Any) -> List[Part]:
                wrapped: List[Part] = []

                if isinstance(item, Part):
                    wrapped.append(item)
                elif isinstance(item, DataPart):
                    wrapped.append(Part(root=item))

                    if isinstance(item.data, dict):
                        artifact_uri = item.data.get("artifact-uri")
                        file_name = item.data.get("file-name") or item.data.get("artifact-id") or "uploaded-file"
                        mime_type = item.data.get("mime", "application/octet-stream")
                        role_value = (item.data.get("role") or (item.data.get("metadata") or {}).get("role"))

                        metadata_block = item.data.get("metadata") or {}
                        if role_value and metadata_block.get("role") != role_value:
                            metadata_block = {**metadata_block, "role": role_value}
                            item.data["metadata"] = metadata_block
                        if role_value and item.data.get("role") != role_value:
                            item.data["role"] = role_value

                        if artifact_uri:
                            wrapped.append(
                                Part(
                                    root=FilePart(
                                        file=FileWithUri(
                                            name=file_name,
                                            mimeType=mime_type,
                                            uri=artifact_uri,
                                            role=role_value,
                                        )
                                    )
                                )
                            )

                        if item.data.get("extracted_content"):
                            wrapped.append(
                                Part(root=TextPart(text=str(item.data["extracted_content"])))
                            )

                elif isinstance(item, FilePart):
                    wrapped.append(Part(root=item))

                elif isinstance(item, TextPart):
                    wrapped.append(Part(root=item))

                elif isinstance(item, str):
                    wrapped.append(Part(root=TextPart(text=item)))

                elif isinstance(item, dict):
                    wrapped.append(Part(root=DataPart(data=item)))

                elif item is not None:
                    wrapped.append(Part(root=TextPart(text=str(item))))

                return wrapped

            for processed in processed_parts:
                prepared_parts_for_agents.extend(_wrap_for_agent(processed))

            # Store prepared parts for sending to agents (includes user uploads for refinement)
            session_context._latest_processed_parts = prepared_parts_for_agents
            # Clear the list for agent-generated artifacts (only NEW files from agents shown in response)
            session_context._agent_generated_artifacts = []
            log_debug(f"📦 Prepared {len(prepared_parts_for_agents)} parts to attach for remote agents")
            log_debug(f"📤 Cleared agent-generated artifacts list (will only show NEW files from agents)")
            
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

            has_base_attachment = False
            has_mask_attachment = False
            base_filenames: List[str] = []
            mask_filenames: List[str] = []

            def _flatten_processed(items: Iterable[Any]) -> Iterable[Any]:
                for item in items:
                    if isinstance(item, (list, tuple, set)):
                        yield from _flatten_processed(item)
                    else:
                        yield item

            for result in _flatten_processed(processed_parts):
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
                        has_base_attachment = True
                        name_hint = candidate_data.get("file-name") or candidate_data.get("name")
                        if name_hint:
                            base_filenames.append(str(name_hint))
                    if role_val == "mask":
                        has_mask_attachment = True
                        name_hint = candidate_data.get("file-name") or candidate_data.get("name")
                        if name_hint:
                            mask_filenames.append(str(name_hint))

                if candidate_part:
                    role_attr = getattr(candidate_part.file, "role", None)
                    part_name = getattr(candidate_part.file, "name", "")
                    name_attr = part_name.lower()
                    role_lower = str(role_attr).lower() if role_attr else ""
                    if role_lower == "base" or name_attr.endswith("_base.png"):
                        has_base_attachment = True
                        if part_name:
                            base_filenames.append(part_name)
                    if role_lower == "mask" or "_mask" in name_attr or "-mask" in name_attr:
                        has_mask_attachment = True
                        if part_name:
                            mask_filenames.append(part_name)

            if has_base_attachment:
                guidance_lines = [
                    "IMPORTANT: Treat this request as an image edit using the provided attachments.",
                    "Reuse the supplied base image exactly; do not regenerate a new scene or subject.",
                ]
                if base_filenames:
                    unique_base = ", ".join(sorted({str(name) for name in base_filenames}))
                    guidance_lines.append(f"Base image attachment(s): {unique_base}.")
                if has_mask_attachment:
                    guidance_lines.append(
                        "Apply the requested changes strictly within the transparent region of the provided mask and leave all other pixels unchanged."
                    )
                    if mask_filenames:
                        unique_masks = ", ".join(sorted({str(name) for name in mask_filenames}))
                        guidance_lines.append(f"Mask attachment(s): {unique_masks} (must include transparency).")
                else:
                    guidance_lines.append(
                        "Apply the requested changes directly to the supplied base image only."
                    )

                guidance_block = "\n".join(guidance_lines)
                if enhanced_message:
                    enhanced_message = f"{guidance_block}\n\n{enhanced_message}"
                else:
                    enhanced_message = guidance_block
            
            log_debug(f"Enhanced message: {enhanced_message}")
            
            # Send enhanced message to thread
            log_debug(f"About to send message to thread...")
            await self._emit_status_event("sending message to AI thread", context_id)
            await self.send_message_to_thread(thread_id, enhanced_message)
            print(f"🔍 Message sent to thread successfully")
            
            # Check if we're in Agent Mode
            if session_context.agent_mode:
                log_debug(f"🎯 [Agent Mode] Agent Mode ENABLED - using orchestration loop")
                await self._emit_status_event("Agent Mode: Starting task orchestration...", context_id)
                
                # Use agent mode orchestration loop
                try:
                    orchestration_outputs = await self._agent_mode_orchestration_loop(
                        user_message=enhanced_message,
                        context_id=context_id,
                        session_context=session_context,
                        event_logger=event_logger,
                        workflow=workflow
                    )
                    
                    # Generate final synthesis using Azure AI Foundry agent
                    print(f"🎬 [Agent Mode] Generating final response synthesis...")
                    await self._emit_status_event("Synthesizing final response...", context_id)
                    
                    # Create synthesis prompt with all task outputs
                    # Tell the agent NOT to use tools, just synthesize
                    synthesis_prompt = f"""Based on the following task outputs, provide a comprehensive answer to the user's question: "{enhanced_message}"

Task Outputs:
{chr(10).join(f"- {output}" for output in orchestration_outputs)}

IMPORTANT: Do NOT call any tools (send_message, list_remote_agents). Simply synthesize these outputs into a clear, cohesive response. Do NOT ask for confirmation or what to do next."""
                    
                    # Send synthesis prompt to thread
                    await self.send_message_to_thread(thread_id, synthesis_prompt, "user")
                    
                    # Create run for synthesis
                    log_foundry_debug(f"Creating synthesis run...")
                    run = await self._http_create_run(thread_id, self.agent['id'], session_context)
                    log_foundry_debug(f"Synthesis run created: {run['id']}")
                    
                    # Poll for completion
                    max_iterations = 30
                    poll_iteration = 0
                    import asyncio
                    while run['status'] in ['queued', 'in_progress']:
                        poll_iteration += 1
                        if poll_iteration > max_iterations:
                            print(f"⚠️ [Agent Mode] Synthesis polling timeout")
                            break
                        
                        await asyncio.sleep(2)
                        run = await self._http_get_run(thread_id, run['id'])
                        log_foundry_debug(f"Synthesis run status: {run['status']}")
                    
                    # If requires_action, submit empty outputs to force completion
                    if run['status'] == 'requires_action':
                        print(f"⚠️ [Agent Mode] Synthesis trying to call tools - forcing skip")
                        try:
                            # Get the tool calls and submit empty responses
                            tool_calls = run.get('required_action', {}).get('submit_tool_outputs', {}).get('tool_calls', [])
                            if tool_calls:
                                tool_outputs = [
                                    {"tool_call_id": tc['id'], "output": "Tool calls not allowed during synthesis. Please provide final answer based on provided information."}
                                    for tc in tool_calls
                                ]
                                run = await self._http_submit_tool_outputs(thread_id, run['id'], tool_outputs)
                                # Continue polling
                                poll_iteration = 0
                                while run['status'] in ['queued', 'in_progress'] and poll_iteration < max_iterations:
                                    poll_iteration += 1
                                    await asyncio.sleep(2)
                                    run = await self._http_get_run(thread_id, run['id'])
                                    log_foundry_debug(f"Synthesis run status after tool skip: {run['status']}")
                        except Exception as e:
                            print(f"⚠️ [Agent Mode] Error skipping synthesis tools: {e}")
                    
                    # Get final response from thread
                    if run['status'] == 'completed':
                        # Extract token usage from synthesis run
                        if 'usage' in run and run['usage']:
                            usage = run['usage']
                            self.host_token_usage["prompt_tokens"] += usage.get('prompt_tokens', 0) or 0
                            self.host_token_usage["completion_tokens"] += usage.get('completion_tokens', 0) or 0
                            self.host_token_usage["total_tokens"] += usage.get('total_tokens', 0) or 0
                            print(f"🎟️ [Host Agent] Synthesis tokens: +{usage.get('total_tokens', 0)} (total: {self.host_token_usage['total_tokens']})")
                        
                        messages = await self._http_list_messages(thread_id, limit=1)
                        if messages:
                            log_foundry_debug(f"Retrieved {len(messages)} message(s) from synthesis thread")
                            log_foundry_debug(f"Message structure: {type(messages[0])}")
                            log_foundry_debug(f"Message keys: {messages[0].keys() if isinstance(messages[0], dict) else 'N/A'}")
                            if isinstance(messages[0], dict) and 'content' in messages[0]:
                                log_foundry_debug(f"Content structure: {messages[0]['content'][:500] if isinstance(messages[0]['content'], str) else messages[0]['content']}")
                            
                            final_response = self._extract_message_content(messages[0])
                            log_info(f"✅ [Agent Mode] Final synthesis extracted: {final_response[:200] if final_response else '(EMPTY!)'}...")
                            
                            # Include ONLY agent-generated artifacts (not user uploads)
                            # This ensures the UI can display NEW images with "Refine this image" buttons
                            final_responses = [final_response]
                            log_foundry_debug(f"Checking for agent-generated artifacts to include in final response...")
                            log_foundry_debug(f"session_context has _agent_generated_artifacts: {hasattr(session_context, '_agent_generated_artifacts')}")
                            if hasattr(session_context, '_agent_generated_artifacts'):
                                log_foundry_debug(f"_agent_generated_artifacts length: {len(session_context._agent_generated_artifacts)}")
                                artifact_dicts = []
                                for idx, part in enumerate(session_context._agent_generated_artifacts):
                                    log_foundry_debug(f"Part {idx}: type={type(part)}")
                                    
                                    # Check for wrapped Part objects with .root
                                    if hasattr(part, 'root'):
                                        log_foundry_debug(f"Part {idx} has .root, root type: {type(part.root)}")
                                        if isinstance(part.root, DataPart) and isinstance(part.root.data, dict) and 'artifact-uri' in part.root.data:
                                            log_foundry_debug(f"Part {idx} wrapped DataPart with artifact-uri ✓")
                                            artifact_dicts.append(part.root.data)
                                    
                                    # Check for unwrapped DataPart objects (no .root)
                                    elif isinstance(part, DataPart):
                                        log_foundry_debug(f"Part {idx} is unwrapped DataPart, data type: {type(part.data)}")
                                        if isinstance(part.data, dict) and 'artifact-uri' in part.data:
                                            log_foundry_debug(f"Part {idx} unwrapped DataPart with artifact-uri ✓")
                                            artifact_dicts.append(part.data)
                                
                                log_foundry_debug(f"Found {len(artifact_dicts)} artifact dicts from remote agents")
                                if artifact_dicts:
                                    log_debug(f"📦 [Agent Mode] Including {len(artifact_dicts)} artifact(s) from remote agents in final response for UI display")
                                    final_responses.extend(artifact_dicts)
                                    for idx, artifact_data in enumerate(artifact_dicts):
                                        uri = artifact_data.get('artifact-uri', '')
                                        filename = artifact_data.get('file-name', 'unknown')
                                        print(f"  • Artifact {idx+1} from remote agent: {filename} (URI has SAS: {'?' in uri})")
                                else:
                                    print(f"⚠️ [DEBUG] No artifact dicts found (agent doesn't generate files)")
                            else:
                                print(f"⚠️ [DEBUG] session_context does not have _agent_generated_artifacts")
                        else:
                            print(f"⚠️ [Agent Mode] No messages in synthesis response")
                            final_responses = ["Task orchestration completed successfully."]
                    else:
                        print(f"⚠️ [Agent Mode] Synthesis run did not complete: {run['status']}")
                        final_responses = ["Task orchestration completed but synthesis failed."]
                    
                    # Store the interaction and return
                    log_debug("About to store User→Host interaction for context_id: {context_id}")
                    await self._store_user_host_interaction_safe(
                        user_message_parts=message_parts,
                        user_message_text=enhanced_message,
                        host_response=final_responses,
                        context_id=context_id,
                        span=span
                    )
                    
                    log_debug(f"🎯 [Agent Mode] Orchestration complete, returning {len(final_responses)} responses")
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
                                if hasattr(part, 'root') and isinstance(part.root, DataPart) and isinstance(part.root.data, dict) and 'artifact-uri' in part.root.data:
                                    artifact_dicts.append(part.root.data)
                                elif isinstance(part, DataPart) and isinstance(part.data, dict) and 'artifact-uri' in part.data:
                                    artifact_dicts.append(part.data)
                            
                            if artifact_dicts:
                                log_debug(f"📦 [Agent Mode] Including {len(artifact_dicts)} agent-generated artifact(s) in fallback response")
                                final_responses.extend(artifact_dicts)
                        
                        return final_responses
                    else:
                        # No outputs to return, show error
                        final_responses = [f"Agent Mode orchestration encountered an error: {error_msg}"]
                        return final_responses
            
            # Continue with standard conversation flow using HTTP API
            log_foundry_debug(f"=================== STARTING RUN CREATION ===================")
            log_foundry_debug(f"About to create run with agent_id: {self.agent['id']} (FIRST PATH)")
            await self._emit_status_event("creating AI agent run", context_id)
            
            log_foundry_debug(f"Calling _http_create_run...")
            run = await self._http_create_run(thread_id, self.agent['id'], session_context)
            log_foundry_debug(f"Run created successfully with ID: {run['id']}, status: {run['status']} (FIRST PATH)")
            log_foundry_debug(f"=================== RUN CREATED SUCCESSFULLY ===================")
            await self._emit_status_event(f"AI run started - status: {run['status']}", context_id)
            
            # Poll until completion, handle tool calls
            max_iterations = 30
            iterations = 0
            last_tool_output = None
            tool_calls_count = 0
            
            log_foundry_debug(f"Starting polling loop for run {run['id']} (FIRST PATH)")
            while run["status"] in ["queued", "in_progress", "requires_action"] and iterations < max_iterations:
                iterations += 1
                log_foundry_debug(f"Polling iteration {iterations}, current status: {run['status']} (FIRST PATH)")
                
                # Emit status for different run states
                if run["status"] == "queued":
                    await self._emit_status_event("AI request queued for processing", context_id)
                elif run["status"] == "in_progress":
                    await self._emit_status_event("AI is analyzing and processing", context_id)
                elif run["status"] == "requires_action":
                    await self._emit_status_event("AI requires tools - executing actions", context_id)
                
                import asyncio; await asyncio.sleep(1)
                log_foundry_debug(f"About to get run status for iteration {iterations} (FIRST PATH)")
                run = await self._http_get_run(thread_id, run["id"])
                log_foundry_debug(f"Got run status: {run['status']} (iteration {iterations}) (FIRST PATH)")
                
                if run["status"] == "failed":
                    log_foundry_debug(f"Run failed, breaking from loop (FIRST PATH)")
                    await self._emit_status_event("AI run failed", context_id)
                    break
                    
                if run["status"] == "requires_action":
                    log_foundry_debug(f"Run requires action, handling tool calls (FIRST PATH)")
                    tool_calls_count += 1
                    await self._emit_status_event(f"executing tools (attempt {tool_calls_count})", context_id)
                    
                    # OPTIMIZED: Process all available tool calls in one batch
                    all_tool_calls = []
                    current_run = run
                    
                    # Collect tool calls - we can only get the current batch
                    # We CANNOT submit empty outputs as the Azure API requires outputs for all tool_calls
                    if current_run.get('required_action') and current_run['required_action'].get('submit_tool_outputs'):
                        batch_tool_calls = current_run['required_action']['submit_tool_outputs']['tool_calls']
                        all_tool_calls.extend(batch_tool_calls)
                        log_debug(f"🔥 OPTIMIZED: Processing {len(batch_tool_calls)} tool calls in batch")
                    
                    # Now execute all tool calls in parallel fashion
                    if all_tool_calls:
                        log_debug(f"🔥 OPTIMIZED: Executing {len(all_tool_calls)} tool calls in parallel")
                        
                        # Ensure the run has the tool calls properly set up
                        if not run.get('required_action'):
                            run['required_action'] = {}
                        if not run['required_action'].get('submit_tool_outputs'):
                            run['required_action']['submit_tool_outputs'] = {}
                        run['required_action']['submit_tool_outputs']['tool_calls'] = all_tool_calls
                        
                        # Now process all tool calls in parallel
                        tool_output = await self._handle_tool_calls(run, thread_id, context_id, session_context, event_logger=event_logger)
                        if tool_output:
                            last_tool_output = tool_output
                            await self._emit_status_event("tool execution completed", context_id)
                    
                    # Get the latest run status after all tool executions
                    run = await self._http_get_run(thread_id, run["id"])
            
            log_foundry_debug(f"Polling loop completed. Final status: {run['status']}, iterations: {iterations} (FIRST PATH)")
            await self._emit_status_event("AI processing completed, generating response", context_id)
            
            # Get response messages
            log_foundry_debug(f"About to retrieve messages from thread (FIRST PATH)")
            await self._emit_status_event("retrieving AI response", context_id)
            messages = await self._http_list_messages(thread_id)
            log_foundry_debug(f"Retrieved {len(messages)} messages from thread (FIRST PATH)")
            
            responses = []
            assistant_messages_found = 0
            
            for i, msg in enumerate(messages):
                log_foundry_debug(f"Message {i}: role={msg.get('role')}, has_content={bool(msg.get('content'))} (FIRST PATH)")
                if msg.get("content"):
                    log_foundry_debug(f"Message {i} content count: {len(msg['content'])} (FIRST PATH)")
                    for j, content in enumerate(msg['content']):
                        log_foundry_debug(f"Content {j}: type={content.get('type')}, has_text={bool(content.get('text'))} (FIRST PATH)")
                        if content.get("text"):
                            log_foundry_debug(f"Text object: {content.get('text')} (FIRST PATH)")
                else:
                    log_foundry_debug(f"Message {i} has no content! (FIRST PATH)")
                
                if msg.get("role") == "assistant" and msg.get("content"):
                    assistant_messages_found += 1
                    log_foundry_debug(f"Processing assistant message {assistant_messages_found} (FIRST PATH)")
                    current_responses = []
                    for content in msg["content"]:
                        if content.get("type") == "text" and content.get("text", {}).get("value"):
                            text_value = content["text"]["value"]
                            log_foundry_debug(f"Found text value: {text_value[:100]}... (FIRST PATH)")
                            if not text_value or "couldn't retrieve" in text_value.lower() or "no response" in text_value.lower():
                                log_foundry_debug(f"Skipping invalid text value (FIRST PATH)")
                                continue
                            current_responses.append(text_value)
                            log_foundry_debug(f"Added response to current list (FIRST PATH)")
                    if current_responses:
                        log_foundry_debug(f"Found responses in message {i}, updating latest responses (FIRST PATH)")
                        responses = current_responses  # Keep updating to get the most recent responses
                else:
                    if msg.get("role") != "assistant":
                        log_foundry_debug(f"Skipping message {i} - not assistant role: {msg.get('role')} (FIRST PATH)")
                    else:
                        log_foundry_debug(f"Skipping message {i} - assistant but no content (FIRST PATH)")
            
            # If no valid assistant message found, surface tool output as fallback
            if not responses and last_tool_output:
                log_foundry_debug(f"No assistant responses found, using tool output as fallback (FIRST PATH)")

                def _flatten_tool_output(output):
                    if isinstance(output, list):
                        joined = "\n\n".join(str(item) for item in output)
                        normalized = self._normalize_function_response_text(joined)
                        if isinstance(normalized, list):
                            return [str(item) for item in normalized]
                        return [normalized if isinstance(normalized, str) else str(normalized)]

                    if isinstance(output, str):
                        normalized = self._normalize_function_response_text(output)
                        return [normalized if isinstance(normalized, str) else str(normalized)]

                    return [str(output)]

                payload_to_flatten = last_tool_output.get("response") if isinstance(last_tool_output, dict) and "response" in last_tool_output else last_tool_output
                responses = _flatten_tool_output(payload_to_flatten)
            
            log_foundry_debug(f"After message processing - responses count: {len(responses) if responses else 0} (FIRST PATH)")
            if responses:
                log_foundry_debug(f"First response: {responses[0][:100]}... (FIRST PATH)")
                
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
                if hasattr(session_context, '_agent_generated_artifacts'):
                    artifact_dicts = []
                    for part in session_context._agent_generated_artifacts:
                        # Check for wrapped Part objects with .root
                        if hasattr(part, 'root'):
                            if isinstance(part.root, DataPart) and isinstance(part.root.data, dict) and 'artifact-uri' in part.root.data:
                                artifact_dicts.append(part.root.data)
                        # Check for unwrapped DataPart objects (no .root)
                        elif isinstance(part, DataPart):
                            if isinstance(part.data, dict) and 'artifact-uri' in part.data:
                                artifact_dicts.append(part.data)
                    
                    if artifact_dicts:
                        log_debug(f"📦 [Standard Mode] Including {len(artifact_dicts)} agent-generated artifact(s) in response for UI display")
                        final_responses.extend(artifact_dicts)
                        for idx, artifact_data in enumerate(artifact_dicts):
                            uri = artifact_data.get('artifact-uri', '')
                            filename = artifact_data.get('file-name', 'unknown')
                            print(f"  • Artifact {idx+1}: {filename} (URI: {uri[:80]}...)")

                # If we have extracted content, prepend it and save to thread context
                if has_extracted_content:
                    extracted_content_message = (
                        "The file has been processed. Here is the extracted content:\n\n" + 
                        "\n\n---\n\n".join(extracted_contents)
                    )
                    log_debug(f"📝 Sending extracted content to thread for future context...")
                    await self.send_message_to_thread(thread_id, extracted_content_message, role="assistant")
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
                
                # FIXED: Don't stream here if host manager is handling it to prevent duplicates
                # The host manager will stream the response, so we skip streaming here
                log_debug(f"Skipping foundry agent direct streaming - host manager will handle response streaming")
                # Stream the host agent's final aggregated response to WebSocket
                # NOTE: Disabled to prevent duplicate messages - host manager handles streaming
                if False and context_id not in self._host_responses_sent:
                    self._host_responses_sent.add(context_id)
                    try:
                        from websocket_streamer import get_websocket_streamer
                        
                        try:
                            streamer = await get_websocket_streamer()
                            if streamer:
                                # Combine all final responses into a single message
                                final_response_text = ""
                                if final_responses:
                                    final_response_text = "\n\n".join([str(response) for response in final_responses])
                                
                                # Send as host agent message event
                                event_data = {
                                    "messageId": str(uuid.uuid4()),
                                    "conversationId": context_id or "",
                                    "contextId": context_id or "",
                                    "role": "assistant",
                                    "content": [
                                        {
                                            "type": "text",
                                            "content": final_response_text.strip(),
                                            "mediaType": "text/plain"
                                        }
                                    ],
                                    "direction": "incoming",
                                    "agentName": "foundry-host-agent",  # Host agent name
                                    "timestamp": __import__('datetime').datetime.utcnow().isoformat(),
                                    "source": "run_conversation_with_parts"  # Track which method sent this
                                }
                                
                                # Stream the final aggregated response
                                success = await streamer._send_event("message", event_data, context_id)
                                if success:
                                    log_debug(f"Host agent final response event streamed: {event_data}")
                                else:
                                    log_debug("Failed to stream host agent final response event")
                            else:
                                log_debug("WebSocket streamer not available for host agent final response")
                        except Exception as e:
                            log_debug(f"Error streaming host agent final response to WebSocket: {e}")
                            # Don't let WebSocket errors break the main flow
                            pass
                        
                    except ImportError:
                        # WebSocket module not available, continue without streaming
                        log_debug("WebSocket module not available for host agent response")
                        pass
                    except Exception as e:
                        log_debug(f"Error setting up host agent response streaming: {e}")
                        # Don't let WebSocket errors break the main flow
                        pass
                else:
                    log_debug(f"Host agent response already sent for context {context_id}, skipping duplicate")
                
                return final_responses
        
        except Exception as e:
            print(f"❌ CRITICAL ERROR in run_conversation_with_parts: {e}")
            import traceback
            print(f"❌ FULL TRACEBACK: {traceback.format_exc()}")
            raise

    async def run_conversation(self, user_message: str, context_id: Optional[str] = None, event_logger=None) -> Any:
        scenario = "run_conversation"
        with tracer.start_as_current_span(scenario) as span:
            
            span.set_attribute("context_id", context_id or self.default_context_id)
            print(f"run_conversation called for user_message: {user_message}")
            if not context_id:
                context_id = self.default_context_id  # Use persistent default context like ADK
            
            # Enhanced telemetry for conversation tracking
            span.set_attribute("conversation.user_message_length", len(user_message))
            span.set_attribute("conversation.user_message_summary", user_message[:100] + "..." if len(user_message) > 100 else user_message)
            span.set_attribute("conversation.context_id", context_id)
            span.set_attribute("conversation.is_default_context", context_id == self.default_context_id)
            
            # Ensure agent is created (may be lazy creation if startup creation failed)
            if not self.agent:
                print("⚠️ Agent not created at startup, creating now (lazy creation)...")
                await self.create_agent()
            
            session_context = self.get_session_context(context_id)
            
            # Track conversation state
            span.set_attribute("conversation.history_source", "openai_thread")
            span.set_attribute("conversation.is_new", context_id not in self.threads)
            span.set_attribute("session.active", session_context.session_active)
            
            # Create or get thread
            thread_created = False
            if context_id not in self.threads:
                thread = await self.create_thread(context_id)
                self.threads[context_id] = thread["id"]  # Use dictionary access
                thread_created = True
            thread_id = self.threads[context_id]
            
            span.set_attribute("thread.created", thread_created)
            span.set_attribute("thread.id", thread_id)
            
            # Add conversation start event
            span.add_event("conversation_started", {
                "context_id": context_id,
                "thread_id": thread_id,
                "message_preview": user_message[:50] + "..." if len(user_message) > 50 else user_message,
                "history_source": "openai_thread",
                "thread_created": thread_created
            })
            
            # Add conversation context to message before sending to thread
            contextualized_message = await self._add_context_to_message(
                user_message,
                session_context,
                thread_id=thread_id,
                target_agent_name=None,
            )
            
            # Send contextualized message to thread
            await self.send_message_to_thread(thread_id, contextualized_message)
            log_foundry_debug(f"Message sent to thread successfully, moving to next step...")
            
            # Debug: Check agent tools before running
            print(f"========= AGENT TOOLS DEBUG ==========")
            print(f"Agent ID: {self.agent['id']}")
            print(f"Agent tools: {self.agent.get('tools', 'No tools attribute')}")
            print(f"Available remote agents: {list(self.remote_agent_connections.keys())}")
            print(f"User message: '{user_message}'")
            print(f"==========================================")
            
            # Run the agent using HTTP API
            log_foundry_debug(f"About to create run with agent_id: {self.agent['id']}")
            run = await self._http_create_run(thread_id, self.agent['id'], session_context)
            log_foundry_debug(f"Run created successfully with ID: {run['id']}, status: {run['status']}")
            
            # Track run initiation
            span.set_attribute("run.id", run["id"])
            span.set_attribute("run.initial_status", run["status"])
            span.add_event("agent_run_started", {
                "run_id": run["id"],
                "agent_id": self.agent['id'],
                "thread_id": thread_id
            })
            
            # Poll until completion, handle tool calls
            max_iterations = 30
            iterations = 0
            last_tool_output = None
            tool_calls_count = 0
            
            log_foundry_debug(f"Starting polling loop for run {run['id']}")
            while run["status"] in ["queued", "in_progress", "requires_action"] and iterations < max_iterations:
                iterations += 1
                log_foundry_debug(f"Polling iteration {iterations}, current status: {run['status']}")
                
                import asyncio; await asyncio.sleep(1)
                
                log_foundry_debug(f"About to get run status for iteration {iterations}")
                run = await self._http_get_run(thread_id, run["id"])
                log_foundry_debug(f"Got run status: {run['status']} (iteration {iterations})")
                
                # Debug: Check if run has required_action
                if run.get('required_action'):
                    log_foundry_debug(f"Run has required_action: {run['required_action']}")
                else:
                    log_foundry_debug(f"Run has NO required_action - agent should be responding directly")
                
                # Track status changes
                span.add_event("run_status_change", {
                    "run_id": run["id"],
                    "status": run["status"],
                    "iteration": iterations
                })
                
                if run["status"] == "failed":
                    span.add_event("run_failed", {
                        "run_id": run["id"],
                        "iteration": iterations
                    })
                    print(f"❌ Host Agent run FAILED: {run['id']}")
                    print(f"❌ Run status: {run['status']}")
                    if run.get('last_error'):
                        print(f"❌ Run last_error: {run['last_error']}")
                    if run.get('failed_at'):
                        print(f"❌ Failed at: {run['failed_at']}")
                    print(f"❌ This is why the Host Agent isn't generating a new response!")
                    break
                    
                if run["status"] == "requires_action":
                    tool_calls_count += 1
                    span.add_event("tool_calls_required", {
                        "run_id": run["id"],
                        "tool_call_sequence": tool_calls_count,
                        "iteration": iterations
                    })
                    
                    # OPTIMIZED: Process all available tool calls in one batch
                    all_tool_calls = []
                    current_run = run
                    
                    # Collect tool calls - we can only get the current batch
                    # We CANNOT submit empty outputs as the Azure API requires outputs for all tool_calls
                    if current_run.get('required_action') and current_run['required_action'].get('submit_tool_outputs'):
                        batch_tool_calls = current_run['required_action']['submit_tool_outputs']['tool_calls']
                        all_tool_calls.extend(batch_tool_calls)
                        log_debug(f"🔥 OPTIMIZED: Processing {len(batch_tool_calls)} tool calls in batch")
                    
                    # Now execute all tool calls in parallel fashion
                    if all_tool_calls:
                        log_debug(f"🔥 OPTIMIZED: Executing {len(all_tool_calls)} tool calls in parallel")
                        
                        # Ensure the run has the tool calls properly set up
                        if not run.get('required_action'):
                            run['required_action'] = {}
                        if not run['required_action'].get('submit_tool_outputs'):
                            run['required_action']['submit_tool_outputs'] = {}
                        run['required_action']['submit_tool_outputs']['tool_calls'] = all_tool_calls
                        
                        # Now process all tool calls in parallel
                        tool_output = await self._handle_tool_calls(run, thread_id, context_id, session_context, event_logger=event_logger)
                        if tool_output:
                            last_tool_output = tool_output
                    
                    # Get the latest run status after all tool executions
                    run = await self._http_get_run(thread_id, run["id"])
            
            log_foundry_debug(f"Polling loop completed. Final status: {run['status']}, iterations: {iterations}")
            
            # Track final run state
            span.set_attribute("run.final_status", run["status"])
            span.set_attribute("run.iterations", iterations)
            span.set_attribute("run.tool_calls_count", tool_calls_count)
            span.set_attribute("run.max_iterations_reached", iterations >= max_iterations)
            
            # Get response messages
            messages = await self._http_list_messages(thread_id)
            responses = []
            assistant_messages_found = 0
            
            print(f"Found {len(messages)} messages in thread")
            for i, msg in enumerate(messages):
                print(f"Message {i}: role={msg.get('role')}, has_content={bool(msg.get('content'))}")
                if msg.get('content'):
                    print(f"Message {i} content count: {len(msg['content'])}")
                    for j, content in enumerate(msg['content']):
                        if content.get('type') == 'text' and content.get('text', {}).get('value'):
                            text_value = content['text']['value']
                            print(f"Message {i}.{j}: '{text_value[:100]}...'")
                
                if msg.get("role") == "assistant" and msg.get("content"):
                    assistant_messages_found += 1
                    current_responses = []
                    for content in msg["content"]:
                        if content.get("type") == "text" and content.get("text", {}).get("value"):
                            text_value = content["text"]["value"]
                            # Check for fallback/generic message
                            if not text_value or "couldn't retrieve" in text_value.lower() or "no response" in text_value.lower():
                                continue
                            current_responses.append(text_value)
                    if current_responses:
                        responses = current_responses  # Keep updating to get the most recent responses
                
                span.set_attribute("response.assistant_messages_found", assistant_messages_found)
                span.set_attribute("response.valid_responses_count", len(responses))
                
                print(f"Assistant messages found: {assistant_messages_found}")
                print(f"Valid responses count: {len(responses)}")
                print(f"Last tool output type: {type(last_tool_output)}")
                print(f"Last tool output: {last_tool_output}")
                
                # If no valid assistant message, surface tool output
                response_source = "assistant_message"
                if not responses and last_tool_output:
                    response_source = "tool_output"
                    print(f"Using tool output as response source")
                    # Extract the actual response content from the structured tool output
                    if isinstance(last_tool_output, dict) and "response" in last_tool_output:
                        tool_response = last_tool_output["response"]
                    else:
                        tool_response = last_tool_output

                    if isinstance(tool_response, list):
                        normalized_items = []
                        for item in tool_response:
                            if isinstance(item, str):
                                normalized = self._normalize_function_response_text(item)
                                if isinstance(normalized, str):
                                    normalized_items.append(normalized)
                                else:
                                    normalized_items.append(str(normalized))
                            else:
                                normalized_items.append(str(item))
                        responses = normalized_items
                    elif isinstance(tool_response, str):
                        normalized = self._normalize_function_response_text(tool_response)
                        responses = [normalized if isinstance(normalized, str) else str(normalized)]
                    else:
                        responses = [str(tool_response)]
                else:
                    print(f"Using assistant message as response source")
                
                span.set_attribute("response.source", response_source)
                
                # Note: Conversation history is now managed by OpenAI threads - no need to store separately
                
                # Track response characteristics
                if responses:
                    response_text = responses[0]
                    span.set_attribute("response.length", len(response_text))
                    span.set_attribute("response.summary", response_text[:100] + "..." if len(response_text) > 100 else response_text)
                
                # Add conversation completion event
                span.add_event("conversation_completed", {
                    "context_id": context_id,
                    "responses_count": len(responses),
                    "response_source": response_source,
                    "tool_calls_made": tool_calls_count,
                    "final_run_status": run["status"],
                    "conversation_turns": "managed_by_thread"
                })
                
                final_responses = responses if responses else ["No response received"]
                span.set_attribute("conversation.success", len(responses) > 0)
                
                # TODO: Temporarily disable User→Host A2A interaction storage - causes hang
                print(f"User→Host memory storage temporarily disabled")
                # user_message_parts = [Part(root=TextPart(kind="text", text=user_message))]
                # processing_time_seconds = time.time() - start_time
                # await self._store_user_host_interaction(
                #     user_message_parts=user_message_parts,
                #     user_message_text=user_message,
                #     host_response=final_responses,
                #     context_id=context_id,
                #     processing_time=processing_time_seconds,
                #     span=span
                # )
                
                # FIXED: Don't stream here if host manager is handling it to prevent duplicates
                # The host manager will stream the response, so we skip streaming here
                log_debug(f"Skipping foundry agent direct streaming (run_conversation) - host manager will handle response streaming")
                # Stream the host agent's final response to WebSocket (for the other conversation path)
                # NOTE: Disabled to prevent duplicate messages - host manager handles streaming
                if False and context_id not in self._host_responses_sent:
                    self._host_responses_sent.add(context_id)
                    try:
                        from websocket_streamer import get_websocket_streamer
                        
                        try:
                            streamer = await get_websocket_streamer()
                            if streamer:
                                # Combine all final responses into a single message
                                final_response_text = ""
                                if final_responses:
                                    final_response_text = "\n\n".join([str(response) for response in final_responses])
                                
                                # Send as host agent message event
                                event_data = {
                                    "messageId": str(uuid.uuid4()),
                                    "conversationId": context_id or "",
                                    "contextId": context_id or "",
                                    "role": "assistant",
                                    "content": [
                                        {
                                            "type": "text",
                                            "content": final_response_text.strip(),
                                            "mediaType": "text/plain"
                                        }
                                    ],
                                    "direction": "incoming",
                                    "agentName": "foundry-host-agent",  # Host agent name
                                    "timestamp": __import__('datetime').datetime.utcnow().isoformat(),
                                    "source": "run_conversation"  # Track which method sent this
                                }
                                
                                # Stream the final response
                                success = await streamer._send_event("message", event_data, context_id)
                                if success:
                                    log_debug(f"Host agent final response event streamed (run_conversation): {event_data}")
                                else:
                                    log_debug("Failed to stream host agent final response event (run_conversation)")
                            else:
                                log_debug("WebSocket streamer not available for host agent final response (run_conversation)")
                        except Exception as e:
                            log_debug(f"Error streaming host agent final response to WebSocket (run_conversation): {e}")
                            # Don't let WebSocket errors break the main flow
                            pass
                        
                    except ImportError:
                        # WebSocket module not available, continue without streaming
                        log_debug("WebSocket module not available for host agent response (run_conversation)")
                        pass
                    except Exception as e:
                        log_debug(f"Error setting up host agent response streaming (run_conversation): {e}")
                        # Don't let WebSocket errors break the main flow
                        pass
                else:
                    log_debug(f"Host agent response already sent for context {context_id}, skipping duplicate (run_conversation)")
                
                return final_responses

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
            print(f"_handle_tool_calls called for thread_id: {thread_id}, context_id: {context_id}")
            
            if not run.get('required_action'):
                log_debug("No required_action in run.")
                return None
                
            required_action = run.get('required_action')
            if not required_action.get('submit_tool_outputs'):
                log_debug("No submit_tool_outputs in required_action.")
                return None
                
            tool_calls = required_action['submit_tool_outputs']['tool_calls']
            log_debug(f"🔥 OPTIMIZED: Processing {len(tool_calls)} tool calls")
            
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
            
            # NEW: Execute send_message calls in parallel
            if send_message_tool_calls:
                log_debug(f"🚀 Executing {len(send_message_tool_calls)} send_message calls in parallel")
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
                            print(f"❌ Parallel agent call failed: {result}")
                            output = {"error": f"Agent call failed: {str(result)}"}
                            self._add_status_message_to_conversation(f"❌ Agent call to {agent_name} failed", context_id)
                            span.add_event("parallel_agent_call_failed", {
                                "agent_name": agent_name,
                                "error": str(result)
                            })
                            # Stream tool failure to WebSocket
                            asyncio.create_task(self._emit_tool_response_event(agent_name, "send_message", "failed", str(result), context_id))
                        else:
                            output = result
                            self._add_status_message_to_conversation(f"✅ Agent call to {agent_name} completed", context_id)
                            span.add_event("parallel_agent_call_success", {
                                "agent_name": agent_name,
                                "output_type": type(output).__name__
                            })
                            # Stream tool success to WebSocket
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
                        
                        # Format output for Azure AI Agents (normalize to string)
                        normalized_output = self._normalize_function_response_text(output)
                        if isinstance(normalized_output, list):
                            normalized_text = "\n\n".join(str(item) for item in normalized_output)
                        elif isinstance(normalized_output, str):
                            normalized_text = normalized_output
                        else:
                            normalized_text = str(normalized_output)

                        tool_output_payload = {
                            "kind": "function_response",
                            "name": "send_message",
                            "response": normalized_text
                        }

                        tool_outputs.append({
                            "tool_call_id": tool_call["id"],
                            "output": json.dumps(tool_output_payload)
                        })

                        if not isinstance(result, Exception):
                            successful_tool_outputs.append(tool_output_payload)
                            last_tool_output = tool_output_payload
                    
                    print(f"✅ Parallel agent calls completed successfully")
                    self._add_status_message_to_conversation("✅ All parallel agent calls completed", context_id)
                    await self._emit_status_event("all agent calls completed", context_id)
                    span.add_event("parallel_agent_calls_completed", {
                        "successful_calls": len([r for r in parallel_results if not isinstance(r, Exception)]),
                        "failed_calls": len([r for r in parallel_results if isinstance(r, Exception)])
                    })
                    
                except Exception as e:
                    print(f"❌ Error in parallel agent execution: {e}")
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
            
            # Execute other tool calls sequentially (as before)
            for tool_call, function_name, arguments in other_tool_calls:
                print(f"Handling tool: {function_name}, args: {arguments}")
                
                # Add status message for each tool call
                self._add_status_message_to_conversation(f"🛠️ Executing tool: {function_name}", context_id)
                await self._emit_status_event(f"executing {function_name} tool", context_id)
                
                # Enhanced tool call tracking
                span.add_event(f"tool_call: {function_name}", {
                    "function_name": function_name,
                    "tool_call_id": tool_call["id"],
                    "arguments_keys": list(arguments.keys()) if isinstance(arguments, dict) else [],
                    "arguments_summary": str(arguments)[:200] + "..." if len(str(arguments)) > 200 else str(arguments)
                })
                
                # Stream tool call to WebSocket for thinking box visibility
                await self._emit_tool_call_event("foundry-host-agent", function_name, arguments, context_id)
                
                # Log tool call event and add span event
                if event_logger:
                    event_logger({
                        "id": str(uuid.uuid4()),
                        "actor": "foundry-host-agent",
                        "args": arguments,
                        "name": function_name,
                        "type": "tool_call"
                    })
                
                if function_name == "list_remote_agents":
                    output = self.list_remote_agents(context_id=context_id)
                    self._add_status_message_to_conversation(f"✅ Tool {function_name} completed", context_id)
                    span.add_event("agents_listed", {
                        "available_agents_count": len(output),
                        "agent_names": [agent.get("name", "unknown") for agent in output] if output else []
                    })
                    # Stream tool success to WebSocket
                    await self._emit_tool_response_event("foundry-host-agent", function_name, "success", None, context_id)
                else:
                    output = {"error": f"Unknown function: {function_name}"}
                    self._add_status_message_to_conversation(f"❌ Unknown tool: {function_name}", context_id)
                    span.add_event("unknown_function_called", {
                        "function_name": function_name,
                        "available_functions": ["list_remote_agents", "send_message"]
                    })
                    # Stream tool failure to WebSocket
                    await self._emit_tool_response_event("foundry-host-agent", function_name, "failed", f"Unknown function: {function_name}", context_id)
                
                # Log tool result event
                if event_logger:
                    event_logger({
                        "id": str(uuid.uuid4()),
                        "actor": "foundry-host-agent",
                        "name": function_name,
                        "type": "tool_result",
                        "output": output
                    })
                
                # Track tool execution outcome
                if isinstance(output, dict) and "error" in output:
                    span.add_event("tool_execution_error", {
                        "function_name": function_name,
                        "error": output["error"]
                    })
                elif output:
                    span.add_event("tool_execution_success", {
                        "function_name": function_name,
                        "output_type": type(output).__name__,
                        "output_size": len(str(output))
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
            
            # Track overall tool execution summary
            total_calls = len(send_message_tool_calls) + len(other_tool_calls)
            span.set_attribute("tools.total_calls", total_calls)
            span.set_attribute("tools.parallel_calls", len(send_message_tool_calls))
            span.set_attribute("tools.sequential_calls", len(other_tool_calls))
            span.set_attribute("tools.successful_calls", len([o for o in tool_outputs if o]))
            
            # Submit tool outputs
            span.add_event("tool_outputs_submitted", {
                "tool_outputs_count": len(tool_outputs),
                "parallel_calls": len(send_message_tool_calls),
                "sequential_calls": len(other_tool_calls),
                "run_id": run["id"],
                "thread_id": thread_id
            })
            
            # Submit tool outputs via HTTP API
            log_debug(f"🔥 OPTIMIZED: Submitting {len(tool_outputs)} tool outputs in one batch")
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
                print(f"📎 [Agent Mode] Preserving {len(latest_parts)} existing file parts from previous agents")
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

        def _infer_role(explicit_role: Optional[str], name_hint: Optional[str]) -> Optional[str]:
            if explicit_role:
                return str(explicit_role).lower()

            if not name_hint:
                return None

            name_lower = str(name_hint).lower()

            # Check for generated/edited outputs FIRST (before role keywords)
            # This ensures generated masks/overlays/bases are ALL kept for display, not deduplicated
            # The receiving agent will use the FIRST file as base (fallback behavior)
            if "generated_" in name_lower or "edit_" in name_lower:
                return None  # No role = kept as separate artifact, agent uses first as base

            # Only assign roles to USER-UPLOADED files (for editing workflows)
            if "mask" in name_lower or name_lower.endswith("-mask.png") or name_lower.endswith("_mask.png"):
                return "mask"

            if (
                name_lower.endswith("-base.png")
                or name_lower.endswith("_base.png")
                or "_base" in name_lower
            ):
                return "base"

            image_exts = (
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".bmp",
                ".webp",
                ".tif",
                ".tiff",
                ".heic",
                ".heif",
                ".jfif",
                ".apng",
            )

            if name_lower.endswith(image_exts) or "logo" in name_lower:
                return "overlay"

            return None

        uri_to_parts: Dict[str, List[Any]] = {}
        assigned_roles: Dict[str, str] = {}

        def _normalize_uri(value: Optional[str]) -> Optional[str]:
            if not value:
                return None
            normalized = str(value).strip()
            if not normalized:
                return None
            base, _, _ = normalized.partition("?")
            return base.lower()

        def _register_part_uri(part: Any, uri: Optional[str]) -> None:
            normalized_uri = _normalize_uri(uri)
            if not normalized_uri:
                return
            uri_to_parts.setdefault(normalized_uri, []).append(part)

        def _register_role(uri: Optional[str], role: Optional[str]) -> None:
            if not role:
                return
            normalized_uri = _normalize_uri(uri)
            if not normalized_uri:
                return
            assigned_roles[normalized_uri] = str(role).lower()

        def _apply_role_to_part(part: Any, role: Optional[str]) -> None:
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

        def _extract_uri_from_part(part: Any) -> Optional[str]:
            target = part.root if isinstance(part, Part) else part
            if isinstance(target, DataPart) and isinstance(target.data, dict):
                return target.data.get("artifact-uri") or target.data.get("uri")
            if isinstance(target, FilePart):
                file_obj = target.file
                if isinstance(file_obj, FileWithUri):
                    return getattr(file_obj, "uri", None)
            return None

        flattened_parts = []
        pending_file_parts: List[FilePart] = []
        refine_payload = None

        for item in rval:
            if isinstance(item, DataPart):
                if hasattr(item, "data") and isinstance(item.data, dict):
                    artifact_uri = item.data.get("artifact-uri")
                    existing_role = item.data.get("role") or (item.data.get("metadata") or {}).get("role")
                    name_hint = item.data.get("file-name") or item.data.get("name") or item.data.get("artifact-id")
                    role_value = _infer_role(existing_role, name_hint)

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
                            print(f"🎭 Creating FilePart with metadata role='{role_value}' for {file_with_uri_kwargs['name']}")
                        
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
                _register_part_uri(item, _extract_uri_from_part(item))
            elif isinstance(item, dict):
                if item.get("kind") == "refine-image":
                    refine_payload = item
                elif "artifact-uri" in item or "artifact-id" in item:
                    # This is artifact metadata from an agent - wrap in DataPart
                    artifact_uri = item.get("artifact-uri", "")
                    log_debug(f"📦 [DEBUG] Wrapping artifact dict in DataPart:")
                    print(f"   artifact-uri (first 150 chars): {artifact_uri[:150]}")
                    print(f"   Has SAS token (?): {'?' in artifact_uri}")
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

        base_uri_hint = _normalize_uri((refine_payload or {}).get("image_url"))
        mask_uri_hint = _normalize_uri((refine_payload or {}).get("mask_url"))

        if base_uri_hint or mask_uri_hint:
            for part in flattened_parts:
                candidate_uri = _normalize_uri(_extract_uri_from_part(part))
                if base_uri_hint and candidate_uri == base_uri_hint:
                    _apply_role_to_part(part, "base")
                    _register_role(candidate_uri, "base")
                if mask_uri_hint and candidate_uri == mask_uri_hint:
                    _apply_role_to_part(part, "mask")
                    _register_role(candidate_uri, "mask")

        for uri_value, parts_list in uri_to_parts.items():
            if assigned_roles.get(uri_value):
                continue
            
            # Check if this is a generated/edited artifact - don't assign default overlay role
            # Extract filename from URI to check
            file_name_from_uri = uri_value.split('/')[-1].split('?')[0].lower() if uri_value else ""
            is_generated_artifact = "generated_" in file_name_from_uri or "edit_" in file_name_from_uri
            
            if is_generated_artifact:
                print(f"🔍 Skipping default 'overlay' role for generated artifact: {file_name_from_uri}")
                # Don't assign any role - keep generated artifacts separate for display
                continue
            
            # For other files (user uploads, logos, etc.), assign overlay as default
            for part in parts_list:
                _apply_role_to_part(part, "overlay")
            assigned_roles[uri_value] = "overlay"

        def _apply_assigned_roles(parts: Iterable[Any]) -> None:
            for part in parts:
                uri = _normalize_uri(_extract_uri_from_part(part))
                if not uri:
                    continue
                role_for_uri = assigned_roles.get(uri)
                if role_for_uri:
                    _apply_role_to_part(part, role_for_uri)

        _apply_assigned_roles(flattened_parts)
        _apply_assigned_roles(latest_parts)

        # DEBUG: Log what we're returning
        log_foundry_debug(f"convert_parts returning {len(flattened_parts)} parts:")
        for idx, part in enumerate(flattened_parts):
            if isinstance(part, (TextPart, DataPart, FilePart)):
                print(f"  • Part {idx}: {type(part).__name__} (kind={getattr(part, 'kind', 'N/A')})")
            elif isinstance(part, dict):
                print(f"  • Part {idx}: dict with keys={list(part.keys())}")
            elif isinstance(part, str):
                print(f"  • Part {idx}: string (length={len(part)})")
            else:
                print(f"  • Part {idx}: {type(part)}")

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

            refine_matches = list(re.finditer(r"\[refine-image\]\s+(https?://\S+)", text_content, flags=re.IGNORECASE))
            mask_matches = list(re.finditer(r"\[refine-mask\]\s+(https?://\S+)", text_content, flags=re.IGNORECASE))

            if refine_matches:
                image_url = refine_matches[-1].group(1)
                mask_url = mask_matches[-1].group(1) if mask_matches else None

                cleaned_text = re.sub(r"\[refine-image\]\s+https?://\S+", "", text_content, flags=re.IGNORECASE)
                cleaned_text = re.sub(r"\[refine-mask\]\s+https?://\S+", "", cleaned_text, flags=re.IGNORECASE)

                refine_data = {"kind": "refine-image", "image_url": image_url}
                if mask_url:
                    refine_data["mask_url"] = mask_url

                session_context = getattr(tool_context, "state", None)
                if session_context is not None:
                    latest_parts = getattr(session_context, "_latest_processed_parts", None)
                    if latest_parts is None:
                        latest_parts = []
                        setattr(session_context, "_latest_processed_parts", latest_parts)
                    latest_parts.append(DataPart(data=refine_data))
                    log_debug(f"convert_part: captured refine request with image_url={image_url}")

                return cleaned_text or "Refine the previous image."

            return text_content
        elif hasattr(part, 'root') and part.root.kind == 'data':
            data = part.root.data
            # Skip token_usage DataParts - already extracted earlier, not for main chat
            if isinstance(data, dict) and data.get('type') == 'token_usage':
                return None
            print(f"DataPart data: {data} (type: {type(data)})")
            return data
        elif hasattr(part, 'root') and part.root.kind == 'file':
            # A2A protocol compliant file handling with enterprise security
            file_id = part.root.file.name
            print(f"🔍 FILE DEBUG: Starting file processing for: {file_id}")
            
            file_bytes = None
            summary_text = None
            artifact_response = None
            file_role_attr = getattr(part.root.file, 'role', None)
            
            # Check if this is an uploaded file with URI
            if hasattr(part.root.file, 'uri') and part.root.file.uri:
                print(f"🔍 FILE DEBUG: Found URI: {part.root.file.uri}")
                # This is an uploaded file, read from uploads directory
                if part.root.file.uri.startswith('/uploads/'):
                    file_uuid = part.root.file.uri.split('/')[-1]
                    upload_dir = "uploads"
                    
                    # Extract session_id from context_id for tenant isolation
                    session_id = None
                    if context_id and '::' in context_id:
                        session_id = context_id.split('::')[0]
                    
                    print(f"🔍 FILE DEBUG: Looking for file with UUID: {file_uuid} in {upload_dir} (session: {session_id})")
                    
                    # Find the actual file with this UUID (may have extension)
                    try:
                        import os
                        
                        # Try session-scoped directory first (new format)
                        if session_id:
                            session_upload_dir = os.path.join(upload_dir, session_id)
                            if os.path.exists(session_upload_dir):
                                print(f"🔍 FILE DEBUG: Checking session-scoped directory: {session_upload_dir}")
                                uploaded_files = os.listdir(session_upload_dir)
                                for uploaded_filename in uploaded_files:
                                    if uploaded_filename.startswith(file_uuid):
                                        file_path = os.path.join(session_upload_dir, uploaded_filename)
                                        print(f"🔍 FILE DEBUG: Reading file from session dir: {file_path}")
                                        with open(file_path, 'rb') as f:
                                            file_bytes = f.read()
                                        print(f"📄 FILE DEBUG: Loaded uploaded file: {len(file_bytes)} bytes from {file_path}")
                                        break
                        
                        # Fall back to flat directory (legacy format)
                        if file_bytes is None and os.path.exists(upload_dir):
                            print(f"🔍 FILE DEBUG: Falling back to flat directory: {upload_dir}")
                            uploaded_files = os.listdir(upload_dir)
                            print(f"🔍 FILE DEBUG: Found {len(uploaded_files)} entries")
                            
                            for uploaded_filename in uploaded_files:
                                # Skip directories (session folders)
                                if os.path.isdir(os.path.join(upload_dir, uploaded_filename)):
                                    continue
                                print(f"🔍 FILE DEBUG: Checking file: {uploaded_filename}")
                                if uploaded_filename.startswith(file_uuid):
                                    file_path = os.path.join(upload_dir, uploaded_filename)
                                    print(f"🔍 FILE DEBUG: Reading file: {file_path}")
                                    with open(file_path, 'rb') as f:
                                        file_bytes = f.read()
                                    print(f"📄 FILE DEBUG: Loaded uploaded file: {len(file_bytes)} bytes from {file_path}")
                                    break
                        
                        if file_bytes is None:
                            print(f"❌ FILE DEBUG: Uploaded file not found for UUID: {file_uuid}")
                            return f"Error: Could not find uploaded file {file_id}"
                    except Exception as e:
                        print(f"❌ FILE DEBUG: Error reading uploaded file: {e}")
                        import traceback
                        print(f"❌ FILE DEBUG: Traceback: {traceback.format_exc()}")
                        return f"Error: Could not read uploaded file {file_id}: {str(e)}"
            else:
                # Try to get bytes from the file part (legacy format)
                try:
                    if hasattr(part.root.file, 'bytes') and part.root.file.bytes:
                        if isinstance(part.root.file.bytes, str):
                            # bytes field is a base64 string, decode it
                            file_bytes = base64.b64decode(part.root.file.bytes)
                        else:
                            # bytes field is already binary data
                            file_bytes = part.root.file.bytes
                    else:
                        print(f"❌ No file bytes or URI found in file part")
                        return f"Error: No file data found for {file_id}"
                except Exception as e:
                    print(f"❌ Error decoding file bytes: {e}")
                    print(f"❌ FILE DEBUG: Decoding traceback: {traceback.format_exc()}")
                    return f"Error: Failed to decode file {file_id}: {str(e)}"
            
            if not file_bytes:
                http_uri = getattr(part.root.file, 'uri', None)
                if http_uri and str(http_uri).lower().startswith(("http://", "https://")):
                    try:
                        import httpx

                        with httpx.Client(timeout=60.0, follow_redirects=True) as http_client:
                            resp = http_client.get(http_uri)
                            resp.raise_for_status()
                            file_bytes = resp.content
                        print(f"✅ FILE DEBUG: Downloaded file from URI: {len(file_bytes)} bytes")
                    except Exception as download_err:
                        print(f"❌ FILE DEBUG: Failed to fetch remote file {http_uri}: {download_err}")
                        return f"Error: Could not load file data for {file_id}: {download_err}"

                    # Continue processing - don't return early, let document processor handle it
                else:
                    print(f"❌ No file bytes loaded and no valid URI")
                    return f"Error: Could not load file data for {file_id}"
            
            # Enhanced security: Validate file before processing
            if len(file_bytes) > 50 * 1024 * 1024:  # 50MB limit
                return DataPart(data={'error': 'File too large', 'max_size': '50MB'})
            
            print(f"File validation passed, proceeding with artifact creation")
            
            file_id_lower = (file_id or "").lower()
            is_mask_artifact = (
                file_id_lower.endswith("-mask.png")
                or file_id_lower.endswith("_mask.png")
                or "-mask" in file_id_lower
                or "_mask" in file_id_lower
            )
            if not file_role_attr and file_id_lower.endswith("_base.png"):
                file_role_attr = "base"
            if not file_role_attr and not is_mask_artifact:
                image_exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")
                if any(file_id_lower.endswith(ext) for ext in image_exts):
                    file_role_attr = "overlay"

            artifact_info: dict[str, Any] = {
                'file_name': file_id,
                'file_bytes': file_bytes,
            }
            if file_role_attr:
                artifact_info['role'] = str(file_role_attr).lower()
            
            # Use save_artifact following A2A best practices (pure A2A implementation)
            if hasattr(tool_context, 'save_artifact'):
                print(f"tool_context has save_artifact method")
                try:
                    # Create A2A-native file part without Google ADK dependencies
                    print(f"Creating A2A-native file part with {len(file_bytes)} bytes")
                    
                    # Create a simple file part structure compatible with A2A protocol
                    a2a_file_part = {
                        'kind': 'file',
                        'file': {
                            'name': file_id,
                            'mimeType': getattr(part.root.file, 'mimeType', 'application/octet-stream'),
                            'data': file_bytes,  # Raw bytes, not base64
                            'force_blob': is_mask_artifact,
                            **({'role': str(file_role_attr)} if file_role_attr else {}),
                        }
                    }
                    print(f"Successfully created A2A file part")
                    
                    print(f"Calling save_artifact...")
                    # save_artifact now returns A2A compliant DataPart with artifact metadata
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
                        
                        # For local files, get the file bytes directly from tool_context
                        if artifact_info.get('storage_type') == 'local':
                            artifact_id = artifact_info.get('artifact_id')
                            if hasattr(tool_context, '_artifacts') and artifact_id in tool_context._artifacts:
                                artifact_data = tool_context._artifacts[artifact_id]
                                if 'file_bytes' in artifact_data:
                                    artifact_info['file_bytes'] = artifact_data['file_bytes']
                                    print(f"Added file bytes to artifact_info for local file: {len(artifact_data['file_bytes'])} bytes")
                except Exception as e:
                    print(f"Exception in save_artifact process: {e}")
                    import traceback
                    log_error(f"Full traceback: {traceback.format_exc()}")
                    artifact_response = DataPart(data={'error': f'Failed to process file: {str(e)}'})
            else:
                print(f"ERROR: tool_context has no save_artifact method")
            
            if is_mask_artifact:
                print(f"Skipping document processing for mask artifact: {file_id}")
                mask_metadata_part: Optional[DataPart] = None
                mask_file_part: Optional[FilePart] = None

                if isinstance(artifact_response, DataPart) and hasattr(artifact_response, 'data'):
                    artifact_response.data['description'] = artifact_response.data.get('description', 'image mask attachment')
                    artifact_response.data['skip-document-processing'] = True
                    artifact_response.data['role'] = 'mask'
                    metadata = artifact_response.data.get('metadata') or {}
                    metadata['role'] = 'mask'
                    artifact_response.data['metadata'] = metadata
                    mask_metadata_part = artifact_response

                    artifact_uri = artifact_response.data.get('artifact-uri')
                    if artifact_uri:
                        mask_file_part = FilePart(
                            kind="file",
                            file=FileWithUri(
                                name=file_id,
                                mimeType=artifact_response.data.get('media-type', getattr(part.root.file, 'mimeType', 'application/octet-stream')),
                                uri=artifact_uri,
                                role="mask",
                            ),
                        )
                else:
                    artifact_uri = artifact_info.get('artifact_uri') or getattr(part.root.file, 'uri', None)
                    metadata = {
                        'artifact-id': artifact_info.get('artifact_id') or str(uuid.uuid4()),
                        'artifact-uri': artifact_uri,
                        'storage-type': artifact_info.get('storage_type', 'unknown'),
                        'file-name': artifact_info.get('file_name'),
                        'description': 'image mask attachment',
                        'skip-document-processing': True,
                        'role': 'mask',
                        'metadata': {'role': 'mask'},
                    }
                    mask_metadata_part = DataPart(data=metadata)

                    if artifact_uri:
                        mask_file_part = FilePart(
                            kind="file",
                            file=FileWithUri(
                                name=file_id,
                                mimeType=getattr(part.root.file, 'mimeType', 'application/octet-stream'),
                                uri=artifact_uri,
                                role="mask",
                            ),
                        )

                if mask_file_part is None:
                    print(f"No accessible URI for mask; embedding bytes for {file_id}")
                    mask_file_part = FilePart(
                        kind="file",
                        file=FileWithBytes(
                            name=file_id,
                            mimeType=getattr(part.root.file, 'mimeType', 'application/octet-stream'),
                            bytes=file_bytes,
                            role="mask",
                        )
                    )

                session_context = getattr(tool_context, "state", None)
                if session_context is not None:
                    latest_parts = getattr(session_context, "_latest_processed_parts", None)
                    if latest_parts is None:
                        latest_parts = []
                        setattr(session_context, "_latest_processed_parts", latest_parts)
                    latest_parts.append(mask_metadata_part)
                    latest_parts.append(mask_file_part)

                return [mask_metadata_part, mask_file_part]

            # Process the file content and store in A2A memory service
            try:
                print(f"FILE DEBUG: Calling document processor for {file_id}")
                # Extract session_id for tenant isolation
                session_id = get_tenant_from_context(context_id) if context_id else None
                processing_result = await a2a_document_processor.process_file_part(
                    part.root.file, 
                    artifact_info,
                    session_id=session_id
                )
                
                if processing_result and isinstance(processing_result, dict) and processing_result.get("success"):
                    content = processing_result.get("content", "")
                    print(f"FILE DEBUG: Document processing successful, content length: {len(content)}")
                    
                    # Emit completion status event
                    if context_id:
                        await self._emit_status_event(f"file processed successfully: {file_id}", context_id)
                    
                    summary_text = f"File: {file_id}\nContent:\n{content}"
                    
                    if isinstance(artifact_response, DataPart) and hasattr(artifact_response, 'data'):
                        artifact_response.data['extracted_content'] = content
                        artifact_response.data['content_preview'] = content[:500] + "..." if len(content) > 500 else content
                else:
                    error = processing_result.get("error", "Unknown error") if isinstance(processing_result, dict) else "Processing failed"
                    print(f"FILE DEBUG: Document processing failed: {error}")
                    summary_text = f"File: {file_id} (processing failed: {error})"
            except Exception as e:
                print(f"❌ FILE DEBUG: Error processing uploaded file: {e}")
                import traceback
                print(f"❌ FILE DEBUG: Processing traceback: {traceback.format_exc()}")
                summary_text = f"File: {file_id} (processing error: {str(e)})"
            
            if isinstance(artifact_response, DataPart):
                print(f"save_artifact completed, returning response with data: {artifact_response.data}")
                
                # IMPORTANT: For non-mask files, also create and store a FilePart so remote agents can access the file
                # Remote agents need FilePart objects with URIs, not just DataPart metadata
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
                    
                    # Store both the DataPart (for host) and FilePart (for remote agents)
                    session_context = getattr(tool_context, "state", None)
                    if session_context is not None:
                        latest_parts = getattr(session_context, "_latest_processed_parts", None)
                        if latest_parts is None:
                            latest_parts = []
                            setattr(session_context, "_latest_processed_parts", latest_parts)
                        latest_parts.append(artifact_response)  # DataPart for host
                        latest_parts.append(Part(root=file_part_for_remote))  # FilePart for remote agents
                        print(f"✅ Stored both DataPart and FilePart for non-mask file {file_id} with role={file_role_attr}")
                
                return artifact_response
            
            if summary_text:
                return summary_text
            
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
    def create_with_shared_client(remote_agent_addresses: List[str], task_callback: Optional[TaskUpdateCallback] = None, enable_task_evaluation: bool = True, create_agent_at_startup: bool = True):
        """
        Factory method to create a FoundryHostAgent2 with a shared httpx.AsyncClient and optional task evaluation.
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

    async def _emit_status_event(self, status_text: str, context_id: str):
        """Emit status event to WebSocket for real-time frontend updates."""
        # Use WebSocket streaming for real-time status updates
        await self._emit_granular_agent_event("foundry-host-agent", status_text, context_id)

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

# Update DummyToolContext to use SessionContext
class DummyToolContext:
    """
    Tool context for artifact management during conversation processing.
    
    This class provides storage and retrieval for files and data artifacts that flow
    through multi-agent conversations. It implements a hybrid storage strategy:
    
    **Small files (<1MB)**: Stored locally for fast access
    **Large files (>1MB)**: Stored in Azure Blob Storage with SAS token URIs
    
    Artifacts are assigned unique IDs and made accessible to remote agents via:
    - HTTP URIs for local files (served by backend API)
    - Azure Blob SAS URIs with time-limited read access (24 hours)
    
    The context also tracks processing actions:
    - skip_summarization: Flag to bypass response summarization
    - escalate: Flag to indicate human intervention needed
    """
    def __init__(self, session_context: SessionContext, azure_blob_client=None):
        self.state = session_context
        self._artifacts = {}  # Maps artifact_id -> {artifact, file_bytes, uri, etc.}
        self._azure_blob_client = azure_blob_client
        
        # Local filesystem storage for smaller artifacts
        self.storage_dir = os.path.join(os.getcwd(), "host_agent_files")
        os.makedirs(self.storage_dir, exist_ok=True)
        
        # Base URL for artifact retrieval (configurable per deployment)
        self.artifact_base_url = f"http://localhost:8000/artifacts"
        
        # Action flags for conversation flow control
        class Actions:
            skip_summarization = False  # Skip host response if agent already provided full answer
            escalate = False  # Escalate to human if agent cannot complete task
        self.actions = Actions()
    
    async def save_artifact(self, file_id: str, file_part):
        """
        Save a file artifact with intelligent storage selection and A2A protocol compliance.
        
        Storage Strategy (hybrid approach for optimal performance and cost):
        
        **Azure Blob Storage** (for files >1MB or when FORCE_AZURE_BLOB=true):
        - Scalable: Handle files up to 50MB
        - Accessible: Generate SAS tokens for secure agent access
        - Durable: Enterprise-grade reliability and backup
        - Cost-effective: Pay only for storage used
        
        **Local Filesystem** (for files <1MB):
        - Fast: No network latency for small files
        - Simple: Direct filesystem access
        - Development-friendly: Easy debugging
        
        Security Measures:
        - 50MB file size limit to prevent DoS attacks
        - SAS tokens with 24-hour expiry for time-limited access
        - Virus scanning hooks (pending field can be extended)
        - Unique artifact IDs prevent path traversal attacks
        
        A2A Protocol Compliance:
        - Returns DataPart with artifact-id and artifact-uri
        - Supports FileWithUri for agent-to-agent file passing
        - Maintains metadata (upload time, size, content type)
        - Preserves file roles (base, mask, overlay) for image editing
        
        Args:
            file_id: Original filename from user upload
            file_part: A2A file part or dict with file data
            
        Returns:
            DataPart with artifact-id, artifact-uri, and storage metadata
        """
        import uuid
        import os
        from datetime import datetime, timedelta
        
        print(f"save_artifact called for file: {file_id}")
        
        # Generate unique artifact ID (A2A best practice)
        artifact_id = str(uuid.uuid4())
        print(f"Generated artifact ID: {artifact_id}")
        
        try:
            # Extract file data with robust error handling (A2A-native format)
            print(f"Extracting file data from file_part type: {type(file_part)}")
            file_role = None
            
            if isinstance(file_part, dict):
                # Handle A2A-native format
                if file_part.get('kind') == 'file' and 'file' in file_part:
                    file_info = file_part['file']
                    file_bytes = file_info['data']
                    mime_type = file_info.get('mimeType', 'application/octet-stream')
                    log_debug(f"Extracted {len(file_bytes)} bytes from A2A file part")
                    file_role = file_info.get('role')
                else:
                    print(f"Could not extract file bytes from A2A file part: {file_part.keys()}")
                    return DataPart(data={'error': 'Invalid A2A file format'})
            elif hasattr(file_part, 'inline_data') and hasattr(file_part.inline_data, 'data'):
                # Handle Google ADK format (fallback)
                file_bytes = file_part.inline_data.data
                mime_type = getattr(file_part.inline_data, 'mime_type', 'application/octet-stream')
                log_debug(f"Extracted {len(file_bytes)} bytes from inline_data")
                file_role = getattr(file_part.inline_data, 'role', None)
            elif hasattr(file_part, 'data'):
                file_bytes = file_part.data
                mime_type = 'application/octet-stream'
                log_debug(f"Extracted {len(file_bytes)} bytes from data attribute")
                file_role = getattr(file_part, 'role', None)
            else:
                print(f"Could not extract file bytes from artifact: {type(file_part)}")
                return DataPart(data={'error': 'Invalid file format'})
            
            print(f"File size: {len(file_bytes)} bytes, MIME type: {mime_type}")
            
            # Enhanced security: Validate file before processing
            if len(file_bytes) > 50 * 1024 * 1024:  # 50MB limit
                return DataPart(data={'error': 'File too large', 'max_size': '50MB'})
            
            # Determine storage strategy based on file size and configuration
            use_azure_blob = self._should_use_azure_blob(len(file_bytes))
            
            force_blob_flag = False
            if isinstance(file_part, dict) and file_part.get('kind') == 'file' and 'file' in file_part:
                force_blob_flag = file_part['file'].get('force_blob', False)

            file_uri: Optional[str] = None

            if (use_azure_blob or force_blob_flag) and hasattr(self, '_azure_blob_client'):
                # A2A URI mechanism with Azure Blob Storage
                print(f"Using Azure Blob Storage for large file")
                try:
                    file_uri = self._upload_to_azure_blob(artifact_id, file_id, file_bytes, mime_type)
                    print(f"✅ Azure Blob upload succeeded: {file_uri[:80]}...")
                except Exception as blob_err:
                    print(f"❌ Azure Blob upload exception caught:")
                    print(f"   Exception type: {type(blob_err).__name__}")
                    print(f"   Exception message: {str(blob_err)}")
                    import traceback
                    print(f"   Full traceback:")
                    for line in traceback.format_exc().split('\n'):
                        if line.strip():
                            print(f"   {line}")
                    # Fall back to local storage path below
                    file_uri = None
                
            normalized_role = str(file_role).lower() if file_role else None

            if file_uri:
                # Create A2A compliant Artifact with URI reference
                file_with_uri = FileWithUri(
                    name=file_id,
                    mimeType=mime_type,
                    uri=file_uri,
                    role=normalized_role,
                )
                file_part = FilePart(kind="file", file=file_with_uri)

                artifact = Artifact(
                    artifactId=artifact_id,
                    name=file_id,
                    description=f"File uploaded via A2A protocol: {file_id}",
                    parts=[file_part],
                    metadata={
                        "uploadTime": datetime.utcnow().isoformat(),
                        "fileSize": len(file_bytes),
                        "storageType": "azure_blob",
                        "contentType": mime_type,
                        "securityScan": "pending",
                        "accessMethod": "uri",
                        **({"role": normalized_role} if normalized_role else {}),
                    }
                )

                self._artifacts[artifact_id] = {
                    'artifact': artifact,
                    'storage_type': 'azure_blob',
                    'uri': file_uri,
                    'created_at': datetime.utcnow().isoformat(),
                    'role': normalized_role,
                }

                print(f"A2A Artifact stored in Azure Blob: {artifact_id} -> {file_uri}")

            else:
                # Local storage with inline bytes (current implementation)
                print(f"Using local storage for file")
                safe_filename = file_id.replace('/', '_').replace('\\', '_')
                file_path = os.path.join(self.storage_dir, f"host_received_{safe_filename}")
                
                with open(file_path, 'wb') as f:
                    f.write(file_bytes)
                
                # Create A2A compliant Artifact object with local reference
                # Following official A2A specification: FilePart.file = FileWithUri
                file_with_uri = FileWithUri(
                    name=file_id,
                    mimeType=mime_type,
                    uri=f"{self.artifact_base_url}/{artifact_id}",  # Local HTTP endpoint
                    role=normalized_role,
                )
                file_part = FilePart(kind="file", file=file_with_uri)
                
                artifact = Artifact(
                    artifactId=artifact_id,
                    name=file_id,
                    description=f"File uploaded via A2A protocol: {file_id}",
                    parts=[file_part],
                    metadata={
                        "uploadTime": datetime.utcnow().isoformat(),
                        "fileSize": len(file_bytes),
                        "localPath": file_path,
                        "storageType": "local",
                        "contentType": mime_type,
                        "securityScan": "pending",
                        "accessMethod": "uri",
                        **({"role": normalized_role} if normalized_role else {}),
                    }
                )
                
                # Store in memory with full artifact metadata
                self._artifacts[artifact_id] = {
                    'artifact': artifact,
                    'file_bytes': file_bytes,
                    'local_path': file_path,
                    'storage_type': 'local',
                    'created_at': datetime.utcnow().isoformat(),
                    'role': normalized_role,
                }
                
                print(f"A2A Artifact stored locally: {artifact_id} for file: {file_id}")
                print(f"File saved to: {file_path} ({len(file_bytes)} bytes)")
            
            # Return A2A compliant DataPart with artifact reference
            # According to A2A spec, FilePart.file should have the URI
            artifact_uri = file_part.file.uri
            
            response = DataPart(data={
                'artifact-id': artifact_id,
                'artifact-uri': artifact_uri,
                'file-name': file_id,
                'storage-type': 'azure_blob' if use_azure_blob else 'local',
                'status': 'stored',
                'message': f'File {file_id} successfully stored as A2A artifact {artifact_id}'
            })
            if file_role:
                response.data['role'] = str(file_role).lower()
                response.data['metadata'] = {**response.data.get('metadata', {}), 'role': str(file_role).lower()}
            
            return response
            
        except Exception as e:
            print(f"Error saving A2A artifact: {e}")
            import traceback
            log_error(f"Full traceback: {traceback.format_exc()}")
            return DataPart(data={
                'error': f'Failed to save artifact: {str(e)}',
                'file-name': file_id,
                'status': 'failed'
            })
    
    def _should_use_azure_blob(self, file_size_bytes: int) -> bool:
        """Determine whether to use Azure Blob based on file size and configuration."""
        # Use Azure Blob for files larger than threshold or when forced via env flag.
        raw_threshold = os.getenv('AZURE_BLOB_SIZE_THRESHOLD')
        size_threshold = _normalize_env_int(raw_threshold, 1024 * 1024)
        force_azure = _normalize_env_bool(os.getenv('FORCE_AZURE_BLOB'), False)
        has_azure_config = self._azure_blob_client is not None
 
        print(f"Azure Blob decision factors:")
        print(f"   - File size: {file_size_bytes:,} bytes")
        print(f"   - Size threshold: {size_threshold:,} bytes")
        print(f"   - Force Azure: {force_azure}")
        print(f"   - Has Azure client: {has_azure_config}")
        print(f"   - Size exceeds threshold: {file_size_bytes > size_threshold}")
 
        decision = has_azure_config and (force_azure or file_size_bytes > size_threshold)
        log_debug(f"🎯 Azure Blob decision: {'YES' if decision else 'NO'}")
 
        return decision
    
    def _upload_to_azure_blob(self, artifact_id: str, file_name: str, file_bytes: bytes, mime_type: str) -> str:
        """Upload file to Azure Blob Storage and return A2A-compliant URI with SAS token."""
        from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions, ContentSettings
        from datetime import datetime, timedelta
        import os
        
        try:
            print(f"🔥 _upload_to_azure_blob ENTRY (SYNC)")
            print(f"   artifact_id: {artifact_id}")
            print(f"   file_name: {file_name}")
            print(f"   file_bytes size: {len(file_bytes)} bytes")
            print(f"   mime_type: {mime_type}")
            print(f"   self._azure_blob_client: {self._azure_blob_client}")
            
            if not self._azure_blob_client:
                print(f"❌ _upload_to_azure_blob: Azure Blob client is None!")
                raise Exception("Azure Blob client not initialized")
            
            # Generate blob name with artifact ID for uniqueness
            safe_file_name = file_name.replace('/', '_').replace('\\', '_')
            blob_name = f"a2a-artifacts/{artifact_id}/{safe_file_name}"
            print(f"   blob_name: {blob_name}")
            
            # Upload to Azure Blob
            container_name = os.getenv('AZURE_BLOB_CONTAINER', 'a2a-files')
            print(f"   container_name: {container_name}")
            
            blob_client = self._azure_blob_client.get_blob_client(
                container=container_name,
                blob=blob_name
            )
            print(f"   blob_client created: {blob_client}")
            
            # Create proper ContentSettings object
            content_settings = ContentSettings(
                content_type=mime_type,
                content_disposition=f'attachment; filename="{file_name}"'
            )
            print(f"   content_settings created")
            
            # Upload with metadata (synchronous call)
            print(f"   🔄 Starting blob upload...")
            blob_client.upload_blob(
                file_bytes,
                content_settings=content_settings,
                metadata={
                    'artifact_id': artifact_id,
                    'original_name': file_name,
                    'upload_time': datetime.utcnow().isoformat(),
                    'a2a_protocol': 'true'
                },
                overwrite=True
            )
            print(f"   ✅ Blob uploaded successfully!")
            
            # Extract account key from connection string for SAS token generation
            connection_string = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
            account_key = None
            if connection_string:
                # Parse connection string to extract account key
                for part in connection_string.split(';'):
                    if part.startswith('AccountKey='):
                        account_key = part.split('=', 1)[1]
                        break
            
            sas_token = None
            if account_key:
                print(f"   🔐 Generating SAS token with account key...")
                sas_token = generate_blob_sas(
                    account_name=blob_client.account_name,
                    container_name=blob_client.container_name,
                    blob_name=blob_name,
                    account_key=account_key,
                    permission=BlobSasPermissions(read=True),
                    expiry=datetime.utcnow() + timedelta(hours=24),
                    version="2023-11-03",
                )
            else:
                # Attempt user-delegation SAS when using Azure AD credentials
                try:
                    print(f"   🔐 Requesting user delegation key for SAS...")
                    delegation_key = self._azure_blob_client.get_user_delegation_key(
                        key_start_time=datetime.utcnow() - timedelta(minutes=5),
                        key_expiry_time=datetime.utcnow() + timedelta(hours=24),
                    )
                    sas_token = generate_blob_sas(
                        account_name=blob_client.account_name,
                        container_name=blob_client.container_name,
                        blob_name=blob_name,
                        user_delegation_key=delegation_key,
                        permission=BlobSasPermissions(read=True),
                        expiry=datetime.utcnow() + timedelta(hours=24),
                        version="2023-11-03",
                    )
                    print(f"   ✅ User delegation SAS generated")
                except Exception as ude_err:
                    print(f"   ⚠️ Failed to generate user delegation SAS: {ude_err}")

            if sas_token:
                blob_uri = f"{blob_client.url}?{sas_token}"
                print(f"   ✅ SAS token generated: {blob_uri[:80]}...")
            else:
                raise RuntimeError("Unable to generate SAS token for blob upload")
            
            print(f"🔥 _upload_to_azure_blob EXIT - returning URI")
            return blob_uri
            
        except Exception as e:
            print(f"❌ _upload_to_azure_blob ERROR: {e}")
            print(f"   Exception type: {type(e).__name__}")
            import traceback
            print(f"   Full traceback:")
            for line in traceback.format_exc().split('\n'):
                print(f"   {line}")
            raise Exception(f"Azure Blob upload failed: {str(e)}")
    
    def get_artifact(self, artifact_id: str):
        """Retrieve saved artifact by ID (A2A compliant)."""
        artifact_data = self._artifacts.get(artifact_id)
        if artifact_data:
            return artifact_data['artifact']
        return None
    
    def get_artifact_data(self, artifact_id: str):
        """Retrieve full artifact data including file bytes (A2A compliant)."""
        return self._artifacts.get(artifact_id)
    
    def list_artifacts(self):
        """List all stored artifacts (A2A compliant)."""
        return [data['artifact'] for data in self._artifacts.values()]
