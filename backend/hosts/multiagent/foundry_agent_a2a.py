import asyncio
import ast
import base64
import json
import uuid
import os
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import httpx
from dotenv import load_dotenv

# --- OpenTelemetry and Azure Monitor imports ---
from opentelemetry import trace
from azure.monitor.opentelemetry import configure_azure_monitor

from azure.identity import DefaultAzureCredential, ChainedTokenCredential, AzureCliCredential, ManagedIdentityCredential, EnvironmentCredential, ClientSecretCredential
from a2a.client import A2ACardResolver
from a2a.types import (
    AgentCard,
    Artifact,
    DataPart,
    FilePart,
    FileWithUri,
    Message,
    MessageSendConfiguration,
    MessageSendParams,
    Part,
    Task,
    TaskState,
    TextPart,
)
from .remote_agent_connection import RemoteAgentConnections, TaskUpdateCallback, TaskCallbackArg
from .a2a_memory_service import a2a_memory_service
from .a2a_document_processor import a2a_document_processor
from pydantic import BaseModel, Field
import time

ROOT_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(dotenv_path=ROOT_ENV_PATH, override=False)

logger = logging.getLogger(__name__)

# --- Configure Azure Monitor tracing ---
application_insights_connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
if application_insights_connection_string:
    configure_azure_monitor(connection_string=application_insights_connection_string)
tracer = trace.get_tracer(__name__)

def get_context_id(obj: Any, default: str = None) -> str:
    """
    Helper function to get contextId from an object, trying both contextId and context_id fields.
    A2A protocol officially uses contextId (camelCase), but this provides fallback compatibility.
    """
    try:
        # Try contextId first (official A2A protocol field name)
        if hasattr(obj, 'contextId') and obj.contextId is not None:
            return obj.contextId
        # Fallback to context_id for compatibility
        if hasattr(obj, 'context_id') and obj.context_id is not None:
            return obj.context_id
        # Use getattr as final fallback
        return getattr(obj, 'contextId', getattr(obj, 'context_id', default or str(uuid.uuid4())))
    except Exception:
        return default or str(uuid.uuid4())

def get_message_id(obj: Any, default: str = None) -> str:
    """
    Helper function to get messageId from an object, trying both messageId and message_id fields.
    A2A protocol officially uses messageId (camelCase), but this provides fallback compatibility.
    """
    try:
        # Try messageId first (official A2A protocol field name)
        if hasattr(obj, 'messageId') and obj.messageId is not None:
            return obj.messageId
        # Fallback to message_id for compatibility
        if hasattr(obj, 'message_id') and obj.message_id is not None:
            return obj.message_id
        # Use getattr as final fallback
        return getattr(obj, 'messageId', getattr(obj, 'message_id', default or str(uuid.uuid4())))
    except Exception:
        return default or str(uuid.uuid4())

def get_task_id(obj: Any, default: str = None) -> str:
    """
    Helper function to get taskId from an object, trying both taskId and task_id fields.
    A2A protocol officially uses taskId (camelCase), but this provides fallback compatibility.
    """
    try:
        # Try taskId first (official A2A protocol field name)
        if hasattr(obj, 'taskId') and obj.taskId is not None:
            return obj.taskId
        # Fallback to task_id for compatibility
        if hasattr(obj, 'task_id') and obj.task_id is not None:
            return obj.task_id
        # Try id field as alternative (Task objects use .id)
        if hasattr(obj, 'id') and obj.id is not None:
            return obj.id
        # Use getattr as final fallback
        return getattr(obj, 'taskId', getattr(obj, 'task_id', getattr(obj, 'id', default or str(uuid.uuid4()))))
    except Exception:
        return default or str(uuid.uuid4())

class SessionContext(BaseModel):
    """A2A protocol state management - threads handle conversation history.
    A2A protocol handles contextId, taskId, messageId for remote agent communication."""
    contextId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: Optional[str] = None
    message_id: Optional[str] = None
    task_state: Optional[str] = None
    session_active: bool = True
    retry_count: int = 0  # Add retry_count as a proper field
    # Maintain per-agent task IDs to avoid sending a taskId created by a different agent.
    agent_task_ids: dict[str, str] = Field(default_factory=dict)
    # Track per-agent task states so we avoid reusing terminal tasks
    agent_task_states: dict[str, str] = Field(default_factory=dict)
    # Per-agent cooldown (epoch seconds) after rate limiting
    agent_cooldowns: dict[str, float] = Field(default_factory=dict)

class FoundryHostAgent2:
    def __init__(
        self,
        remote_agent_addresses: List[str],
        http_client: httpx.AsyncClient,
        task_callback: Optional[TaskUpdateCallback] = None,
        enable_task_evaluation: bool = False,  # Keep enabled while fixing evaluation logic
        create_agent_at_startup: bool = True,  # New parameter to control startup behavior
    ):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        
        # Initialize Azure credential with better error handling and timeout
        try:
            print("🔍 DEBUG: Initializing Azure authentication with timeout handling...")
            print("💡 TIP: If you see authentication errors, run 'python test_azure_auth.py' to diagnose")
            
            # Use ChainedTokenCredential with timeout and fallback options
            from azure.identity import AzureCliCredential, DefaultAzureCredential, ChainedTokenCredential
            
            # Create Azure CLI credential with custom timeout (reduced from default 10s to 5s)
            cli_credential = AzureCliCredential(process_timeout=5)
            
            # Create a chained credential that tries CLI first, then falls back to DefaultAzureCredential
            self.credential = ChainedTokenCredential(
                cli_credential,
                DefaultAzureCredential(exclude_interactive_browser_credential=True)
            )
            print("✅ DEBUG: Using ChainedTokenCredential (AzureCLI + DefaultAzure) with 5s timeout")
                    
        except Exception as e:
            print(f"⚠️ DEBUG: Credential initialization failed: {e}")
            print("💡 DEBUG: Falling back to DefaultAzureCredential only")
            from azure.identity import DefaultAzureCredential
            self.credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
            print("✅ DEBUG: Using DefaultAzureCredential as fallback")
            
        self.agent: Optional[Dict[str, Any]] = None  # Changed from Agent to Dict
        self.task_callback = task_callback or self._default_task_callback
        self.httpx_client = http_client
        self.remote_agent_connections: Dict[str, RemoteAgentConnections] = {}
        self.cards: Dict[str, AgentCard] = {}
        self.agents: str = ''
        self.session_contexts: Dict[str, SessionContext] = {}
        self.threads: Dict[str, str] = {}  # contextId -> thread_id
        # Default context for persistent conversations (like ADK behavior)
        self.default_contextId = str(uuid.uuid4())
        # Track tasks per agent to support parallel execution
        self._agent_tasks: Dict[str, Optional[Task]] = {}  # agent_name -> current_task
        
        # Task evaluation settings
        self.enable_task_evaluation = enable_task_evaluation
        self.max_retries = 2

        # Initialize Azure Blob Storage client if configured
        self._azure_blob_client = None
        self._init_azure_blob_client()

        # Clear memory index for fresh testing
        self._clear_memory_on_startup()

        # Initialize messages list for status updates
        self._messages = []
        
        # Track host agent responses to prevent duplicates
        self._host_responses_sent = set()  # Track contextIds where host response was already sent
        
        # Reference to host manager for UI integration
        self._host_manager = None

        # Custom root instruction override for dynamic system prompt editing
        self.custom_root_instruction = None
        
        # Token caching to avoid repeated auth calls
        self._cached_token = None
        self._token_expiry = None

        # Store the create_agent_at_startup flag
        self._create_agent_at_startup = create_agent_at_startup

        # Initialize agent registry path inside the backend/data directory
        self._agent_registry_path = self._find_agent_registry_path()

        loop = asyncio.get_running_loop()
        loop.create_task(self.init_remote_agent_addresses(remote_agent_addresses))
        
        # Create agent at startup if requested (default behavior)
        if self._create_agent_at_startup:
            loop.create_task(self._create_agent_at_startup_task())

    def _find_agent_registry_path(self) -> Path:
        """Resolve the agent registry path within the backend/data directory."""
        backend_root = Path(__file__).resolve().parents[2]
        registry_path = backend_root / "data" / "agent_registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        if registry_path.exists():
            print(f"📋 Found agent registry at: {registry_path}")
        else:
            print(f"📋 Agent registry will be created at: {registry_path}")
        return registry_path

    def _load_agent_registry(self) -> List[Dict[str, Any]]:
        """Load agent registry from JSON file."""
        try:
            if self._agent_registry_path.exists():
                with open(self._agent_registry_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                print(f"📋 Agent registry file not found at {self._agent_registry_path}, returning empty list")
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
            print(f"📋 Saved agent registry with {len(agents)} agents to {self._agent_registry_path}")
        except Exception as e:
            print(f"❌ Error saving agent registry: {e}")

    def _agent_card_to_dict(self, card: AgentCard) -> Dict[str, Any]:
        """Convert AgentCard to dictionary format matching registry structure."""
        try:
            card_dict = {
                "name": card.name,
                "description": card.description,
                "version": getattr(card, 'version', '1.0.0'),
                "url": card.url,
                "defaultInputModes": getattr(card, 'defaultInputModes', ["text"]),
                "defaultOutputModes": getattr(card, 'defaultOutputModes', ["text"]),
            }
            
            # Add capabilities if present
            if hasattr(card, 'capabilities') and card.capabilities:
                capabilities_dict = {}
                if hasattr(card.capabilities, 'streaming'):
                    capabilities_dict["streaming"] = card.capabilities.streaming
                card_dict["capabilities"] = capabilities_dict
            
            # Add skills if present
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
            # Return minimal structure
            return {
                "name": getattr(card, 'name', 'Unknown'),
                "description": getattr(card, 'description', ''),
                "version": "1.0.0",
                "url": getattr(card, 'url', ''),
                "defaultInputModes": ["text"],
                "defaultOutputModes": ["text"]
            }

    def _update_agent_registry(self, card: AgentCard):
        """Update agent registry with new or updated agent card."""
        try:
            registry = self._load_agent_registry()
            card_dict = self._agent_card_to_dict(card)
            
            # Find existing agent by URL (unique identifier)
            existing_index = None
            for i, existing_agent in enumerate(registry):
                if existing_agent.get("url") == card.url:
                    existing_index = i
                    break
            
            if existing_index is not None:
                # Update existing agent
                registry[existing_index] = card_dict
                print(f"📋 Updated existing agent in registry: {card.name} at {card.url}")
            else:
                # Add new agent
                registry.append(card_dict)
                print(f"📋 Added new agent to registry: {card.name} at {card.url}")
            
            self._save_agent_registry(registry)
            
        except Exception as e:
            print(f"❌ Error updating agent registry: {e}")

    async def _create_agent_at_startup_task(self):
        """Background task to create the agent at startup with proper error handling."""
        try:
            print("🚀 Creating Azure AI Foundry agent at startup...")
            await self.create_agent()
            print("✅ Azure AI Foundry agent created successfully at startup!")
        except Exception as e:
            print(f"❌ Failed to create agent at startup: {e}")
            print("💡 Agent will be created lazily when first conversation occurs")
            # Don't raise - allow the application to continue and create agent lazily

    def _init_azure_blob_client(self):
        """Initialize Azure Blob Storage client if environment variables are configured."""
        try:
            azure_storage_connection_string = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
            azure_storage_account_name = os.getenv('AZURE_STORAGE_ACCOUNT_NAME')
            
            if azure_storage_connection_string:
                from azure.storage.blob.aio import BlobServiceClient
                self._azure_blob_client = BlobServiceClient.from_connection_string(azure_storage_connection_string)
                print(f"✅ Azure Blob Storage initialized with connection string")
                print(f"Connection string starts with: {azure_storage_connection_string[:50]}...")
            elif azure_storage_account_name:
                from azure.storage.blob.aio import BlobServiceClient
                # Use DefaultAzureCredential for authentication
                account_url = f"https://{azure_storage_account_name}.blob.core.windows.net"
                self._azure_blob_client = BlobServiceClient(account_url, credential=self.credential)
                print(f"✅ Azure Blob Storage initialized with managed identity: {account_url}")
            else:
                print(f"❌ Azure Blob Storage not configured - using local storage only")
                print(f"AZURE_STORAGE_CONNECTION_STRING: {azure_storage_connection_string}")
                print(f"AZURE_STORAGE_ACCOUNT_NAME: {azure_storage_account_name}")
                
        except ImportError as e:
            print(f"❌ Azure Storage SDK not installed - using local storage only")
            print(f"ImportError details: {e}")
        except Exception as e:
            print(f"❌ Failed to initialize Azure Blob Storage: {e}")
            print(f"Exception type: {type(e).__name__}")
            self._azure_blob_client = None

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
        """Get authentication headers for Azure AI Foundry API calls with caching and timeout handling"""
        print(f"🔍 DEBUG: Getting authentication token with timeout handling and caching")
        
        # Check if we have a valid cached token
        if self._cached_token and self._token_expiry:
            import datetime
            # Add 5 minute buffer before expiry
            buffer_time = datetime.datetime.now() + datetime.timedelta(minutes=5)
            if self._token_expiry > buffer_time:
                print(f"✅ DEBUG: Using cached token (expires: {self._token_expiry})")
                return {
                    "Authorization": f"Bearer {self._cached_token}",
                    "Content-Type": "application/json"
                }
        
        # Try to get token with retries and better timeout handling
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Use the correct authentication scope for Azure AI Foundry
                print(f"🔍 DEBUG: Token attempt {attempt + 1}/{max_retries}...")
                
                # Wrap the token call in asyncio.wait_for to add our own timeout
                import asyncio
                
                async def get_token_async():
                    # Run the synchronous get_token in a thread pool to avoid blocking
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(
                        None, 
                        lambda: self.credential.get_token("https://ai.azure.com/.default")
                    )
                
                # Apply a 8-second timeout (less than the 10s default)
                token = await asyncio.wait_for(get_token_async(), timeout=8.0)
                
                # Cache the token
                self._cached_token = token.token
                import datetime
                self._token_expiry = datetime.datetime.fromtimestamp(token.expires_on)
                
                headers = {
                    "Authorization": f"Bearer {token.token}",
                    "Content-Type": "application/json"
                }
                print(f"✅ DEBUG: Authentication headers obtained successfully (expires: {self._token_expiry})")
                return headers
                
            except asyncio.TimeoutError:
                error_name = "TimeoutError"
                error_msg = "Authentication request timed out after 8 seconds"
                print(f"⚠️ DEBUG: Auth attempt {attempt + 1} timed out after 8 seconds")
                
            except Exception as e:
                error_name = type(e).__name__
                error_msg = str(e)
                
                if attempt < max_retries - 1:
                    print(f"⚠️ DEBUG: Auth attempt {attempt + 1} failed ({error_name}), retrying in 3 seconds...")
                    print(f"⚠️ DEBUG: Error details: {error_msg}")
                    await asyncio.sleep(3)  # Wait 3 seconds before retry
                    continue
                else:
                    print(f"❌ DEBUG: Failed to get authentication token after {max_retries} attempts: {error_name}: {e}")
                    
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
        print(f"🔄 DEBUG: Clearing cached authentication token")
        self._cached_token = None
        self._token_expiry = None

    async def refresh_azure_cli_session(self):
        """Helper method to refresh Azure CLI session when authentication fails"""
        try:
            print(f"🔄 DEBUG: Attempting to refresh Azure CLI session...")
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
                print(f"✅ DEBUG: Azure CLI session refreshed successfully")
                self._clear_cached_token()  # Clear cache to use fresh token
                return True
            else:
                print(f"❌ DEBUG: Azure CLI refresh failed: {stderr.decode()}")
                return False
                
        except asyncio.TimeoutError:
            print(f"❌ DEBUG: Azure CLI refresh timed out")
            return False
        except Exception as e:
            print(f"❌ DEBUG: Error refreshing Azure CLI session: {e}")
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
                    print(f"🔄 DEBUG: Authentication failed (401), clearing cached token")
                    self._clear_cached_token()
                    print(f"❌ DEBUG: Failed to list messages: {response.status_code} - {response.text}")
                    return []
                else:
                    print(f"❌ DEBUG: Failed to list messages: {response.status_code} - {response.text}")
                    return []
        except Exception as e:
            print(f"❌ DEBUG: Exception in _http_list_messages: {e}")
            return []

    async def _http_create_run(self, thread_id: str, agent_id: str) -> Dict[str, Any]:
        """Create a run via HTTP API"""
        try:
            print(f"🔍 DEBUG: _http_create_run ENTRY - thread_id: {thread_id}, agent_id: {agent_id}")
            
            print(f"🔍 DEBUG: Getting auth headers...")
            headers = await self._get_auth_headers()
            print(f"🔍 DEBUG: Auth headers obtained successfully")
            
            endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
            api_url = f"{endpoint}/threads/{thread_id}/runs"
            print(f"🔍 DEBUG: API URL: {api_url}")
            
            payload = {
                "assistant_id": agent_id,  # Note: Azure AI Foundry uses 'assistant_id'
                "parallel_tool_calls": True  # EXPLICITLY enable parallel tool calls
            }
            print(f"🔍 DEBUG: Payload: {payload}")
            
            print(f"🔍 DEBUG: Creating HTTP client and making POST request...")
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    api_url,
                    headers=headers,
                    json=payload,
                    params={"api-version": "2025-05-15-preview"},
                    timeout=30.0
                )
                print(f"🔍 DEBUG: POST request completed - status: {response.status_code}")
                
                if response.status_code == 200 or response.status_code == 201:
                    run_data = response.json()
                    print(f"🔍 DEBUG: Run creation successful - returning data: {run_data}")
                    return run_data
                else:
                    print(f"❌ DEBUG: Failed to create run: {response.status_code} - {response.text}")
                    raise Exception(f"Failed to create run: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"❌ DEBUG: Exception in _http_create_run: {e}")
            import traceback
            print(f"❌ DEBUG: Traceback: {traceback.format_exc()}")
            raise

    async def _http_get_run(self, thread_id: str, run_id: str) -> Dict[str, Any]:
        """Get run status via HTTP API"""
        try:
            print(f"🔍 DEBUG: _http_get_run ENTRY - thread_id: {thread_id}, run_id: {run_id}")
            
            headers = await self._get_auth_headers()
            endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
            api_url = f"{endpoint}/threads/{thread_id}/runs/{run_id}"
            print(f"🔍 DEBUG: GET request to: {api_url}")
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    api_url,
                    headers=headers,
                    params={"api-version": "2025-05-15-preview"},
                    timeout=30.0
                )
                print(f"🔍 DEBUG: GET response status: {response.status_code}")
                
                if response.status_code == 200:
                    run_data = response.json()
                    print(f"🔍 DEBUG: Run status retrieved - status: {run_data.get('status', 'unknown')}")
                    return run_data
                else:
                    print(f"❌ DEBUG: Failed to get run: {response.status_code} - {response.text}")
                    raise Exception(f"Failed to get run: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"❌ DEBUG: Exception in _http_get_run: {e}")
            import traceback
            print(f"❌ DEBUG: Traceback: {traceback.format_exc()}")
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
                    print(f"❌ DEBUG: Failed to submit tool outputs: {response.status_code} - {response.text}")
                    raise Exception(f"Failed to submit tool outputs: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"❌ DEBUG: Exception in _http_submit_tool_outputs: {e}")
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
        # Respect the remote agent's advertised streaming capability so non-streaming agents continue to work
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
        
        # Update agent registry with new or updated agent card
        self._update_agent_registry(card)
        
        remote_connection = RemoteAgentConnections(self.httpx_client, card, self.task_callback)
        self.remote_agent_connections[card.name] = remote_connection
        self.cards[card.name] = card
        agent_info = []
        for ra in self.list_remote_agents():
            agent_info.append(json.dumps(ra))
        self.agents = '\n'.join(agent_info)
        
        # Add agent to host manager's agent list for UI visibility
        if hasattr(self, '_host_manager') and self._host_manager:
            # Check if already registered to avoid duplicates
            if not any(a.name == card.name for a in self._host_manager._agents):
                self._host_manager._agents.append(card)
                print(f"[DEBUG] ✅ Added {card.name} to host manager agent list")
            else:
                print(f"[DEBUG] ℹ️ Agent {card.name} already in host manager list")
        
        # Emit agent registration event to Event Hub for UI visibility
        self._emit_agent_registration_event(card)
        
        # Update agent instructions if agent already exists
        if self.agent:
            # Update the agent's instructions with the new agent list
            asyncio.create_task(self._update_agent_instructions())

    async def create_agent(self) -> Dict[str, Any]:
        if self.agent:
            print(f"🔍 DEBUG: Agent already exists, reusing agent ID: {self.agent.get('id', 'unknown')}")
            return self.agent
        
        print(f"🔍 DEBUG: No existing agent found, creating new agent...")
        print(f"🔍 DEBUG: AZURE_AI_FOUNDRY_PROJECT_ENDPOINT = {os.environ.get('AZURE_AI_FOUNDRY_PROJECT_ENDPOINT', 'NOT SET')}")
        print(f"🔍 DEBUG: AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME = {os.environ.get('AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME', 'NOT SET')}")
        
        # Validate required environment variables
        if not os.environ.get("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"):
            raise ValueError("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT environment variable is required")
        if not os.environ.get("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME"):
            raise ValueError("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME environment variable is required")
        
        # Use the correct Azure AI Foundry API endpoint format
        endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        
        # The endpoint should be in format: https://resource.services.ai.azure.com/api/projects/project-name
        # We need to use the assistants API endpoint: {endpoint}/assistants
        if "/api/projects/" in endpoint:
            # Use the full project endpoint + assistants path
            api_url = f"{endpoint}/assistants"
            print(f"🔍 DEBUG: Using assistants API URL: {api_url}")
        else:
            print(f"❌ ERROR: Invalid endpoint format. Expected format with /api/projects/")
            raise ValueError(f"Invalid endpoint format: {endpoint}")
        
        try:
            # Get authentication headers
            headers = await self._get_auth_headers()
            
            model_name = os.environ["AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME"]
            instructions = self.root_instruction('foundry-host-agent')
            tools = self._get_tools()
            
            print(f"🔍 DEBUG: Agent parameters:")
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
                
                print(f"🔍 DEBUG: API Response Status: {response.status_code}")
                
                if response.status_code == 200 or response.status_code == 201:
                    self.agent = response.json()
                    print(f"✅ DEBUG: Agent created successfully! ID: {self.agent['id']}")
                    logger.info(f"Created Foundry Host agent: {self.agent['id']}")
                    return self.agent
                elif response.status_code == 401:
                    print(f"🔄 DEBUG: Authentication failed (401), clearing cached token")
                    self._clear_cached_token()
                    print(f"❌ DEBUG: API request failed with status {response.status_code}")
                    print(f"❌ DEBUG: Response text: {response.text}")
                    raise Exception(f"Failed to create agent (authentication failed): {response.status_code} - {response.text}")
                else:
                    print(f"❌ DEBUG: API request failed with status {response.status_code}")
                    print(f"❌ DEBUG: Response text: {response.text}")
                    raise Exception(f"Failed to create agent: {response.status_code} - {response.text}")
            
        except Exception as e:
            print(f"❌ DEBUG: Exception in create_agent(): {type(e).__name__}: {e}")
            print(f"❌ DEBUG: Full traceback:")
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
        # Always provide tools - they work dynamically regardless of agent registration timing
        tools = [
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
        return tools

    def root_instruction(self, current_agent: str) -> str:
        # Check if we have a custom instruction override
        if self.custom_root_instruction:
            # Safely substitute known placeholders without breaking JSON braces or other content
            instruction = self.custom_root_instruction
            instruction = instruction.replace('{agents}', self.agents)
            instruction = instruction.replace('{current_agent}', current_agent)
            return instruction
        
        # Default instruction if no custom override
#         1. send_message(agent_name="AI Foundry Classification Triage Agent", message="[your classification request]")
# 2. send_message(agent_name="Sentiment Analysis Agent", message="[your sentiment analysis request]")
# 3. send_message(agent_name="ServiceNow, Web & Knowledge Agent", message="[your customer lookup request]") 

# Step 2 (only execute this step after step 1 is complete):

# 1. send_message(agent_name="ServiceNow, Web & Knowledge Agent", message="[create servicenow incident request]") 

# Output: A very detailed hyper-personalized response to the user's complaint including all the details of the work you did and all the infromation you gathered for this user.

        return f""" You are an intelligent **Multi-Agent Orchestrator** designed to coordinate specialized agents to produce complete, personalized responses.  
Your goal is to understand the user’s request, engage the right agents in the right order, and respond in a friendly, professional tone.

---

### 🧩 CORE BEHAVIOR
Before answering any user request, always:
1. Analyze the available agents (listed at the end of this prompt).
2. Identify which agents are relevant.
3. Plan the collaboration strategy.


### 🚨 HUMAN ESCALATION RULE
If the user says anything like “I want to talk to a human,”  
you **must** call:
send_message(
agent_name="ServiceNow, Web & Knowledge Agent",
message="User explicitly requested to speak with a human representative. Please assist with this request."
)

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
- Personalized language adapted to the user’s tone and profile.  
- A friendly and professional closing.  
- For Step 1, always end with:  
  > “If you’d like me to continue with the next actions, please reply: **continue to Step 2**.”  
- For Step 2, end with a confirmation that the process is complete or escalated.

If you lack sufficient info, ask clarifying questions before proceeding.

---

### 🧩 AVAILABLE AGENTS
{self.agents}

### 🧠 CURRENT AGENT
{current_agent}

---

### 💬 SUMMARY
- Run **Step 1** first and stop.  
- Only run **Step 2** if the user clearly asks to continue.  
- Always show which agents you used and summarize their work.  
- Always communicate in the user’s primary language (or the language of their message).  
- Be friendly, helpful, and professional."""

    def list_remote_agents(self):
        return [
            {'name': card.name, 'description': card.description}
            for card in self.cards.values()
        ]

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
                    print(f"[DEBUG] Error streaming remote agent activity: {e}")
                    pass
            
            # Create background task (non-blocking)
            try:
                asyncio.create_task(stream_activity())
            except RuntimeError:
                # Handle case where no event loop is running
                print(f"[DEBUG] No event loop available for streaming agent activity from {agent_name}")
                pass
                
        except Exception as e:
            print(f"[DEBUG] Error in _stream_remote_agent_activity: {e}")
            # Don't let streaming errors break the callback
            pass

    async def _emit_tool_call_event(self, agent_name: str, tool_name: str, arguments: dict):
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
                    "timestamp": __import__('datetime').datetime.utcnow().isoformat()
                }
                
                success = await streamer._send_event("tool_call", event_data, None)
                if success:
                    print(f"[DEBUG] Streamed tool call: {agent_name} - {tool_name}")
                else:
                    print(f"[DEBUG] Failed to stream tool call: {agent_name}")
            else:
                print(f"[DEBUG] WebSocket streamer not available for tool call")
                
        except Exception as e:
            print(f"[DEBUG] Error emitting tool call event: {e}")
            pass

    async def _emit_tool_response_event(self, agent_name: str, tool_name: str, status: str, error_message: str = None):
        """Emit tool response event to WebSocket for granular UI visibility."""
        try:
            # Import here to avoid circular imports
            from service.websocket_streamer import get_websocket_streamer
            
            streamer = await get_websocket_streamer()
            if streamer:
                event_data = {
                    "agentName": agent_name,
                    "toolName": tool_name,
                    "status": status,
                    "timestamp": __import__('datetime').datetime.utcnow().isoformat()
                }
                
                if error_message:
                    event_data["error"] = error_message
                
                success = await streamer._send_event("tool_response", event_data, None)
                if success:
                    print(f"[DEBUG] Streamed tool response: {agent_name} - {tool_name} - {status}")
                else:
                    print(f"[DEBUG] Failed to stream tool response: {agent_name}")
            else:
                print(f"[DEBUG] WebSocket streamer not available for tool response")
                
        except Exception as e:
            print(f"[DEBUG] Error emitting tool response event: {e}")
            pass

    async def _emit_granular_agent_event(self, agent_name: str, status_text: str):
        """Emit granular agent activity event to WebSocket for thinking box visibility."""
        try:
            # Import here to avoid circular imports
            from service.websocket_streamer import get_websocket_streamer
            
            streamer = await get_websocket_streamer()
            if streamer:
                event_data = {
                    "agentName": agent_name,
                    "content": status_text,
                    "timestamp": __import__('datetime').datetime.utcnow().isoformat()
                }
                
                # Use the remote_agent_activity event type for granular visibility
                success = await streamer._send_event("remote_agent_activity", event_data, None)
                if success:
                    print(f"[DEBUG] Streamed remote agent activity: {agent_name} - {status_text}")
                else:
                    print(f"[DEBUG] Failed to stream remote agent activity: {agent_name}")
            else:
                print(f"[DEBUG] WebSocket streamer not available for remote agent activity")
                
        except Exception as e:
            print(f"[DEBUG] Error emitting granular agent event: {e}")
            # Don't let streaming errors break the main flow
            pass

    def _default_task_callback(self, event: TaskCallbackArg, agent_card: AgentCard) -> Task:
        """Default task callback optimized for streaming remote agent execution.
        
        Handles TaskStatusUpdateEvent and TaskArtifactUpdateEvent for granular UI visibility.
        Enhanced with granular WebSocket streaming for UI visibility.
        """
        agent_name = agent_card.name
        print(f"[STREAMING] Task callback from {agent_name}: {type(event).__name__}")
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
        except Exception as _:
            # Non-fatal; continue normal processing
            pass
        
        # Only emit events for specific meaningful state changes, not every streaming update
        # This prevents duplicates while maintaining granular visibility
        if hasattr(event, 'kind'):
            event_kind = getattr(event, 'kind', 'unknown')
            print(f"[STREAMING] Event kind from {agent_name}: {event_kind}")
            
            # Only emit for initial task creation and final completion states
            if event_kind == 'task':
                # Initial task creation
                asyncio.create_task(self._emit_granular_agent_event(agent_name, "task started"))
            elif event_kind == 'artifact-update':
                # Final artifact completion
                status_text = "completed with artifact"
                if hasattr(event, 'artifact') and event.artifact:
                    status_text = "artifact generated"
                asyncio.create_task(self._emit_granular_agent_event(agent_name, status_text))
            elif event_kind == 'status-update':
                # Handle status updates - these contain completion/failure states!
                if hasattr(event, 'status') and event.status and hasattr(event.status, 'state'):
                    state_value = event.status.state
                    if hasattr(state_value, 'value'):
                        state_str = state_value.value
                    else:
                        state_str = str(state_value)
                    
                    print(f"[STREAMING] Status update from {agent_name}: {state_str}")
                    
                    # Emit all meaningful task states for full UI visibility
                    # This includes all A2A protocol states: submitted, working, input-required, completed, canceled, failed, unknown
                    if state_str in ['completed', 'failed', 'canceled', 'submitted', 'input-required', 'unknown', 'working']:
                        print(f"[STREAMING] Emitting task state for {agent_name}: {state_str}")
                        # Use the _emit_task_event for proper A2A-compliant streaming
                        self._emit_task_event(event, agent_card)
                    else:
                        # Log unrecognized states for debugging
                        print(f"[STREAMING] Unrecognized task state from {agent_name}: {state_str}")
                        # Still emit it in case it's a valid state we don't know about
                        self._emit_task_event(event, agent_card)
            # Skip other intermediate events
        
        # Get or create task for this specific agent
        current_task = self._agent_tasks.get(agent_name)
        
        if isinstance(event, Task):
            # Initial task creation - store per agent
            print(f"[PARALLEL] Storing new task for {agent_name}")
            self._agent_tasks[agent_name] = event
            return event
        
        elif hasattr(event, 'kind'):
            if event.kind == 'task':
                # Initial task event - store per agent
                print(f"[PARALLEL] Storing task event for {agent_name}")
                self._agent_tasks[agent_name] = event
                return event
            
            elif event.kind == 'status-update' and current_task:
                # Update existing task status for this agent
                print(f"[PARALLEL] Updating task status for {agent_name}")
                if hasattr(event, 'status'):
                    current_task.status = event.status
                return current_task
            
            elif event.kind == 'artifact-update' and current_task:
                # Add artifact to existing task for this agent
                print(f"[PARALLEL] Adding artifact for {agent_name}")
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
        print(f"[PARALLEL] Created fallback task for {agent_name}")
        return fallback_task

    def _emit_task_event(self, task: TaskCallbackArg, agent_card: AgentCard):
        """Emit event for task callback, with enhanced agent name context for UI status tracking."""
        print(f"[DEBUG] Emitting task event for agent: {agent_card.name}")
        print(f"[DEBUG] Agent capabilities: {agent_card.capabilities if hasattr(agent_card, 'capabilities') else 'None'}")
        
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
            
            print(f"[DEBUG] Status update extracted: {task_state} for {agent_card.name}")
            
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
                print(f"[DEBUG] Added event to host manager for agent: {agent_card.name}")
            
            # Stream A2A-compliant task events to WebSocket with agent context
            print(f"[DEBUG] Streaming A2A task event to WebSocket for agent: {agent_card.name}, state: {task_state}")
            try:
                import asyncio

                async def stream_task_event():
                    try:
                        from service.websocket_streamer import get_websocket_streamer

                        streamer = await get_websocket_streamer()
                        if not streamer:
                            print("[DEBUG] ⚠️ WebSocket streamer not available for task event")
                            return

                        event_data = {
                            "taskId": task_id or str(uuid.uuid4()),
                            "conversationId": contextId or str(uuid.uuid4()),
                            "contextId": contextId,
                            "state": task_state,
                            "artifactsCount": len(getattr(task, 'artifacts', [])),
                            "agentName": agent_card.name,
                            "timestamp": datetime.datetime.utcnow().isoformat(),
                        }

                        event_type = "task_updated"
                        if hasattr(task, 'kind') and task.kind == 'status-update':
                            event_type = "task_updated"
                        elif not hasattr(task, 'kind'):
                            event_type = "task_created"

                        success = await streamer._send_event(event_type, event_data, contextId)
                        if success:
                            print(f"[DEBUG] ✅ A2A task event streamed: {agent_card.name} -> {task_state}")
                        else:
                            print(f"[DEBUG] ❌ Failed to stream A2A task event: {agent_card.name} -> {task_state}")
                    except Exception as e:
                        print(f"[DEBUG] ❌ Error streaming A2A task event: {e}")
                        import traceback
                        traceback.print_exc()

                asyncio.create_task(stream_task_event())

            except Exception as e:
                print(f"[DEBUG] ❌ Error setting up A2A task event streaming: {e}")
                pass

    def _emit_agent_registration_event(self, agent_card: AgentCard):
        """Emit agent registration event to Event Hub for UI sidebar visibility."""
        print(f"[DEBUG] Emitting agent registration event for: {agent_card.name}")
        try:
            import asyncio
            
            # Try to get the current default context
            default_context_id = getattr(self, 'default_contextId', str(uuid.uuid4()))
            
            async def stream_registration_event():
                try:
                    from service.websocket_streamer import get_websocket_streamer

                    streamer = await get_websocket_streamer()
                    if not streamer:
                        print(f"[DEBUG] ⚠️ WebSocket streamer not available for agent registration")
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
                        print(f"[DEBUG] ✅ Agent registration event streamed to WebSocket for {agent_card.name}")
                    else:
                        print(f"[DEBUG] ❌ Failed to stream agent registration event to WebSocket for {agent_card.name}")
                except Exception as e:
                    print(f"[DEBUG] ❌ Error streaming agent registration event: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Create background task for Event Hub streaming
            asyncio.create_task(stream_registration_event())
            
        except Exception as e:
            print(f"[DEBUG] ❌ Error setting up agent registration event streaming: {e}")
            pass

    def _display_task_status_update(self, status_text: str, event: TaskCallbackArg):
        """Display a task status update in the UI as a message."""
        print(f"[DEBUG] _display_task_status_update called with: {status_text}")
        try:
            # Create a message to display in the UI
            from a2a.types import Message, TextPart, Part
            import uuid
            
            message_id = str(uuid.uuid4())
            context_id = getattr(event, 'contextId', getattr(self._current_task, 'contextId', str(uuid.uuid4())))
            print(f"[DEBUG] Created message_id: {message_id}, context_id: {context_id}")
            
            # Create a message with the status update
            status_message = Message(
                messageId=message_id,
                contextId=context_id,
                role="agent",  # Use agent role for status updates
                parts=[Part(root=TextPart(text=f"[Status] {status_text}"))]
            )
            
            # Add to the conversation history through the host manager
            if self._host_manager:
                print(f"[DEBUG] Host manager found, getting conversation for context_id: {context_id}")
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
                        print(f"[DEBUG] Using fallback conversation: {conversation.conversation_id}")
                
                if conversation:
                    conversation.messages.append(status_message)
                    print(f"[DEBUG] ✅ Added status message to conversation: {status_text}")
                else:
                    print(f"[DEBUG] ❌ No conversation found for context_id: {context_id}")
            else:
                print(f"[DEBUG] ❌ No host manager reference available")
            
            # Also add to local messages list
            if hasattr(self, '_messages'):
                self._messages.append(status_message)
                print(f"[DEBUG] Added to local messages list")
            
            # Also add to the conversation state that the UI reads from
            # This ensures the status messages appear in the conversation flow
            if hasattr(self, 'session_contexts') and context_id in self.session_contexts:
                session_context = self.session_contexts[context_id]
                if not hasattr(session_context, 'messages'):
                    session_context.messages = []
                session_context.messages.append(status_message)
                print(f"[DEBUG] Added to session context messages")
            
            print(f"[DEBUG] Status message created successfully: {status_text}")
            
        except Exception as e:
            print(f"[DEBUG] ❌ Error displaying task status update: {e}")
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
        """Extract text content from a message object."""
        try:
            if hasattr(message, 'parts'):
                for part in message.parts:
                    if hasattr(part, 'root') and hasattr(part.root, 'text'):
                        return part.root.text
                    elif hasattr(part, 'text'):
                        return part.text
            elif hasattr(message, 'content'):
                return str(message.content)
            return ""
        except:
            return ""

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
            print(f"🔍 DEBUG: Thread already exists for context {context_id}, returning existing ID: {self.threads[context_id]}")
            return {"id": self.threads[context_id]}
        
        print(f"🔍 DEBUG: Creating new thread for context {context_id}")
        
        try:
            print(f"🔍 DEBUG: Getting authentication headers...")
            # Get authentication headers
            headers = await self._get_auth_headers()
            print(f"🔍 DEBUG: Auth headers obtained successfully")
            
            # Get the API URL for threads
            endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
            api_url = f"{endpoint}/threads"
            print(f"🔍 DEBUG: Thread creation API URL: {api_url}")
            
            print(f"🔍 DEBUG: Making POST request to create thread...")
            # Create thread via HTTP API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    api_url,
                    headers=headers,
                    json={},  # Empty body for thread creation
                    params={"api-version": "2025-05-15-preview"},
                    timeout=30.0
                )
                
                print(f"🔍 DEBUG: Thread creation response status: {response.status_code}")
                
                if response.status_code == 200 or response.status_code == 201:
                    thread_data = response.json()
                    thread_id = thread_data["id"]
                    print(f"✅ DEBUG: Thread created successfully! ID: {thread_id}")
                    
                    # Store the thread ID
                    self.threads[context_id] = thread_id
                    
                    return thread_data
                else:
                    print(f"❌ DEBUG: Thread creation failed with status {response.status_code}")
                    print(f"❌ DEBUG: Response text: {response.text}")
                    raise Exception(f"Failed to create thread: {response.status_code} - {response.text}")
                    
        except Exception as e:
            print(f"❌ DEBUG: Exception in create_thread(): {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            raise

    async def send_message_to_thread(self, thread_id: str, content: str, role: str = "user") -> Dict[str, Any]:
        print(f"🔍 DEBUG: send_message_to_thread ENTRY - thread_id: {thread_id}, role: {role}")
        print(f"🔍 DEBUG: Message content length: {len(content)} chars")
        
        try:
            print(f"🔍 DEBUG: Getting auth headers...")
            # Get authentication headers
            headers = await self._get_auth_headers()
            print(f"🔍 DEBUG: Auth headers obtained successfully")
            
            # Get the API URL for messages
            endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
            api_url = f"{endpoint}/threads/{thread_id}/messages"
            print(f"🔍 DEBUG: Message API URL: {api_url}")
            
            # Prepare message payload
            payload = {
                "role": role,
                "content": content
            }
            print(f"🔍 DEBUG: Message payload prepared")
            
            print(f"🔍 DEBUG: Making POST request to send message...")
            # Send message via HTTP API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    api_url,
                    headers=headers,
                    json=payload,
                    params={"api-version": "2025-05-15-preview"},
                    timeout=30.0
                )
                
                print(f"🔍 DEBUG: Message creation response status: {response.status_code}")
                
                if response.status_code == 200 or response.status_code == 201:
                    message_data = response.json()
                    print(f"✅ DEBUG: Message sent successfully! ID: {message_data.get('id', 'N/A')}")
                    return message_data
                elif response.status_code == 401:
                    print(f"🔄 DEBUG: Authentication failed (401), clearing cached token")
                    self._clear_cached_token()
                    print(f"❌ DEBUG: Message creation failed with status {response.status_code}")
                    print(f"❌ DEBUG: Response text: {response.text}")
                    raise Exception(f"Failed to send message (authentication failed): {response.status_code} - {response.text}")
                else:
                    print(f"❌ DEBUG: Message creation failed with status {response.status_code}")
                    print(f"❌ DEBUG: Response text: {response.text}")
                    raise Exception(f"Failed to send message: {response.status_code} - {response.text}")
                    
        except Exception as e:
            print(f"❌ DEBUG: Exception in send_message_to_thread(): {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            raise

    async def _search_relevant_memory(self, query: str, agent_name: str = None, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search for relevant memory interactions to provide context to remote agents"""
        
        try:
            # Build filters if agent name is specified
            filters = {}
            if agent_name:
                filters["agent_name"] = agent_name
            
            # Search for similar interactions
            memory_results = await a2a_memory_service.search_similar_interactions(
                query=query,
                filters=filters,
                top_k=top_k
            )
            
            return memory_results
            
        except Exception as e:
            return []

    def clear_memory_index(self) -> bool:
        """Clear all stored interactions from the memory index"""
        try:
            success = a2a_memory_service.clear_all_interactions()
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
            azure_endpoint = os.getenv("AZURE_CONTENT_UNDERSTANDING_ENDPOINT", os.getenv("AZURE_AI_SERVICE_ENDPOINT", "")) or "https://agentaiservicesim.openai.azure.com/"  # Fallback retained for compatibility
            model_name = os.environ.get("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME")
            
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

    async def send_message(
        self,
        agent_name: str,
        message: str,
        tool_context: Any,
        suppress_streaming: bool = True,  # Default to True - only host agent should respond to user
    ):
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
            contextualized_message = await self._add_context_to_message(message, session_context, thread_id=None)

            # Respect any active cooldown for this agent due to throttling
            try:
                cool_until = session_context.agent_cooldowns.get(agent_name, 0)
                now_ts = time.time()
                if cool_until and cool_until > now_ts:
                    wait_s = min(60, max(0, int(cool_until - now_ts)))
                    if wait_s > 0:
                        asyncio.create_task(self._emit_granular_agent_event(agent_name, f"throttled; waiting {wait_s}s"))
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

            # Create the request with contextualized message
            request = MessageSendParams(
                id=str(uuid.uuid4()),
                message=Message(
                    role='user',
                    parts=[TextPart(text=contextualized_message)],
                    messageId=messageId,
                    contextId=contextId,
                    taskId=taskId,
                ),
                configuration=MessageSendConfiguration(
                    acceptedOutputModes=['text', 'text/plain', 'image/png'],
                ),
            )
            
            print(f"🚀 [PARALLEL] Calling agent: {agent_name} with context: {contextId}")
            
            # Track start time for processing duration
            start_time = time.time()
            
            try:
                # ENHANCED: Use a detailed task callback for streaming execution
                # to capture granular remote agent activities for UI visibility
                def streaming_task_callback(event, agent_card):
                    """Enhanced callback for streaming execution that captures detailed agent activities"""
                    agent_name = agent_card.name
                    print(f"[STREAMING] Detailed callback from {agent_name}: {type(event).__name__}")
                    
                    # Emit granular events based on the type of update
                    if hasattr(event, 'kind'):
                        event_kind = getattr(event, 'kind', 'unknown')
                        
                        if event_kind == 'status-update':
                            # Extract detailed status information
                            status_text = "processing"
                            if hasattr(event, 'status') and event.status:
                                if hasattr(event.status, 'message') and event.status.message:
                                    if hasattr(event.status.message, 'parts') and event.status.message.parts:
                                        for part in event.status.message.parts:
                                            if hasattr(part, 'root') and hasattr(part.root, 'text'):
                                                status_text = part.root.text
                                                break
                                elif hasattr(event.status, 'state'):
                                    state = event.status.state
                                    if hasattr(state, 'value'):
                                        state_value = state.value
                                    else:
                                        state_value = str(state)
                                    status_text = f"status: {state_value}"
                            
                            # Stream detailed status to UI
                            asyncio.create_task(self._emit_granular_agent_event(agent_name, status_text))
                            
                        elif event_kind == 'artifact-update':
                            # Agent is generating artifacts
                            asyncio.create_task(self._emit_granular_agent_event(agent_name, "generating artifact"))
                        
                        elif event_kind == 'task':
                            # Initial task creation
                            asyncio.create_task(self._emit_granular_agent_event(agent_name, "task started"))
                    
                    # Call the original callback for task management
                    return self._default_task_callback(event, agent_card)
                
                response = await client.send_message(request, streaming_task_callback)
                print(f"✅ [STREAMING] Agent {agent_name} responded successfully!")
                
            except Exception as e:
                print(f"❌ [STREAMING] Agent {agent_name} failed: {e}")
                
                import traceback
                print(f"❌ Full traceback: {traceback.format_exc()}")
                raise
            
            print(f"[STREAMING] Processing response from {agent_name}: {type(response)}")
            
            # Simplified response processing for streaming execution
            if isinstance(response, Task):
                task = response
                
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
                if task.status.state == TaskState.completed:
                    response_parts = []
                    if task.status.message:
                        response_parts.extend(
                            await self.convert_parts(task.status.message.parts, tool_context)
                        )
                    if task.artifacts:
                        for artifact in task.artifacts:
                            response_parts.extend(
                                await self.convert_parts(artifact.parts, tool_context)
                            )
                    
                    # Store interaction in background (don't await to avoid blocking streaming execution)
                    asyncio.create_task(self._store_a2a_interaction_background(
                        outbound_request=request,
                        inbound_response=response,
                        agent_name=agent_name,
                        processing_time=time.time() - start_time,
                        span=span
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
                            asyncio.create_task(self._emit_granular_agent_event(agent_name, f"rate limited; retrying in {retry_after}s (attempt {retry_attempt}/{max_rate_limit_retries})"))
                        except Exception:
                            pass

                        await asyncio.sleep(min(60, retry_after))

                        retry_request = MessageSendParams(
                            id=str(uuid.uuid4()),
                            message=Message(
                                role='user',
                                parts=[TextPart(text=contextualized_message)],
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
                            print(f"[STREAMING] Retry after rate limit failed for {agent_name}: {e}")
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
                                return retry_parts

                            if task2.status.state == TaskState.input_required:
                                if task2.status.message:
                                    return await self.convert_parts(task2.status.message.parts, tool_context)
                                return [f"Agent {agent_name} requires additional input"]

                            if task2.status.state == TaskState.failed:
                                retry_after = _parse_retry_after_from_task(task2)
                                if retry_after:
                                    continue

                            return [f"Agent {agent_name} is processing your request"]

                        if isinstance(retry_response, Message):
                            return await self.convert_parts(retry_response.parts, tool_context)

                        return [str(retry_response)]

                    return [f"Agent {agent_name} failed to complete the task"]

                elif task.status.state == TaskState.input_required:
                    print(f"⚠️ [STREAMING] Agent {agent_name} requires input")
                    if task.status.message:
                        response_parts = await self.convert_parts(task.status.message.parts, tool_context)
                        return response_parts
                    return [f"Agent {agent_name} requires additional input"]
                    
                else:
                    # Handle working/pending states
                    return [f"Agent {agent_name} is processing your request"]
                    
            elif isinstance(response, Message):
                # Direct message response
                result = await self.convert_parts(response.parts, tool_context)
                
                # Store interaction in background
                asyncio.create_task(self._store_a2a_interaction_background(
                    outbound_request=request,
                    inbound_response=response,
                    agent_name=agent_name,
                    processing_time=time.time() - start_time,
                    span=span
                ))
                
                return result
                
            elif isinstance(response, str):
                print(f"[STREAMING] String response from {agent_name}: {response[:200]}...")
                return [response]
                
            else:
                print(f"[STREAMING] Unknown response type from {agent_name}: {type(response)}")
                return [str(response)]
            
            print(f"send_message called for agent: {agent_name}")
            print(f"Original message: {message}")
            print(f"Contextualized message: {contextualized_message}")
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
                print(f"[DEBUG] Response type: {type(response)}")
                print(f"[DEBUG] Response content preview: {str(response)[:500]}...")
                
                # Add more detailed debugging for Task responses
                if hasattr(response, 'status') and hasattr(response.status, 'message'):
                    print(f"[DEBUG] Task response has status message with {len(response.status.message.parts) if response.status.message.parts else 0} parts")
                    if response.status.message.parts:
                        for i, part in enumerate(response.status.message.parts):
                            if hasattr(part.root, 'text'):
                                print(f"[DEBUG] Task message part {i}: {part.root.text[:300]}...")
                            else:
                                print(f"[DEBUG] Task message part {i}: {type(part.root)}")
                
                # Add debugging for Message responses
                elif hasattr(response, 'parts'):
                    print(f"[DEBUG] Message response has {len(response.parts) if response.parts else 0} parts")
                    if response.parts:
                        for i, part in enumerate(response.parts):
                            if hasattr(part.root, 'text'):
                                print(f"[DEBUG] Message part {i}: {part.root.text[:300]}...")
                            else:
                                print(f"[DEBUG] Message part {i}: {type(part.root)}")
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
                        print(f"[DEBUG] Task status message parts: {len(task.status.message.parts) if task.status.message.parts else 0}")
                        for i, part in enumerate(task.status.message.parts):
                            if hasattr(part.root, 'text'):
                                print(f"[DEBUG] Status message part {i}: {part.root.text[:200]}...")
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
                        print(f"[DEBUG] Task has {len(task.artifacts)} artifacts")
                        for i, artifact in enumerate(task.artifacts):
                            print(f"[DEBUG] Artifact {i} parts: {len(artifact.parts) if artifact.parts else 0}")
                            for j, part in enumerate(artifact.parts):
                                if hasattr(part.root, 'text'):
                                    print(f"[DEBUG] Artifact {i} part {j}: {part.root.text[:200]}...")
                        response_parts.extend(
                            await self.convert_parts(artifact.parts, tool_context)
                        )
                    
                    # NOTE: Individual agent responses are always suppressed by default
                    # Only the host agent should send responses to the main chat
                    if not suppress_streaming:
                        print(f"[DEBUG] Streaming remote agent response to WebSocket for agent: {agent_name} (OVERRIDE - normally suppressed)")
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
                                        print(f"[DEBUG] Remote agent response event streamed: {event_data}")
                                    else:
                                        print("[DEBUG] Failed to stream remote agent response event")
                                else:
                                    print("[DEBUG] WebSocket streamer not available for remote agent response")
                            except Exception as e:
                                print(f"[DEBUG] Error streaming remote agent response to Event Hub: {e}")
                                # Don't let Event Hub errors break the main flow
                                pass
                            
                        except ImportError:
                            # Event Hub module not available, continue without streaming
                            print("[DEBUG] Event Hub module not available for response")
                            pass
                        except Exception as e:
                            print(f"[DEBUG] Error setting up remote agent response streaming: {e}")
                            # Don't let Event Hub errors break the main flow
                            pass
                    else:
                        print(f"[DEBUG] Individual agent response streaming suppressed for agent: {agent_name} (default behavior - only host agent responds to user)")
                        print(f"[DEBUG] Context ID: {contextId}, Response parts count: {len(response_parts)}")
                        print(f"[DEBUG] suppress_streaming = {suppress_streaming} (should be True for individual agents)")
                    
                    print(f"[DEBUG] Final response_parts count: {len(response_parts)}")
                    for i, part in enumerate(response_parts):
                        if isinstance(part, str):
                            print(f"[DEBUG] Response part {i}: {part[:200]}...")
                        else:
                            print(f"[DEBUG] Response part {i}: {type(part)} - {str(part)[:200]}...")
                    
                    span.set_attribute("response.parts_count", len(response_parts))
                    
                elif task.status.state == TaskState.input_required:
                    span.add_event("input_required", {
                        "task_id": task.id,
                        "agent_name": agent_name,
                        "reason": "Agent requires additional input to proceed"
                    })
                    tool_context.actions.skip_summarization = True
                    tool_context.actions.escalate = True
                    
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
                    span=span
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
                    print(f"[DEBUG] Streaming remote agent direct message to WebSocket for agent: {agent_name} (OVERRIDE - normally suppressed)")
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
                                    print(f"[DEBUG] Remote agent direct message event streamed: {event_data}")
                                else:
                                    print("[DEBUG] Failed to stream remote agent direct message event")
                            else:
                                print("[DEBUG] WebSocket streamer not available for direct message")
                        except Exception as e:
                            print(f"[DEBUG] Error streaming remote agent direct message to Event Hub: {e}")
                            # Don't let Event Hub errors break the main flow
                            pass
                        
                    except ImportError:
                        # Event Hub module not available, continue without streaming
                        print("[DEBUG] Event Hub module not available for direct message")
                        pass
                    except Exception as e:
                        print(f"[DEBUG] Error setting up direct message streaming: {e}")
                        # Don't let Event Hub errors break the main flow
                        pass
                else:
                    print(f"[DEBUG] Individual agent direct message streaming suppressed for agent: {agent_name} (default behavior - only host agent responds to user)")
                    print(f"[DEBUG] Context ID: {contextId}, Result count: {len(result)}")
                    print(f"[DEBUG] suppress_streaming = {suppress_streaming} (should be True for individual agents)")
                
                # Store A2A interaction in memory
                await self._store_a2a_interaction(
                    outbound_request=request,
                    inbound_response=response,
                    agent_name=agent_name,
                    processing_time=time.time() - start_time,
                    span=span
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
                    span=span
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
                    span=span
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
                    span=span
                )
                
                return result
            elif isinstance(response, str):
                span.add_event("string_response", {
                    "agent_name": agent_name,
                    "response_length": len(response)
                })
                print(f"[DEBUG] String response received: {response[:200]}...")
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
                    span=span
                )
                
                return response

    async def _add_context_to_message(self, message: str, session_context: SessionContext, thread_id: str = None) -> str:
        """Add relevant conversation context and memory insights to the message for better agent responses.
        
        Following Google A2A best practices: host manages context and includes it in agent messages.
        Uses semantic search to find relevant context rather than chronological thread history.
        """
        context_parts = []
        
        # Primary approach: Use semantic memory search for relevant context
        try:
            print(f"🧠 Searching memory for semantically relevant context...")
            print(f"About to call _search_relevant_memory...")
            memory_results = await self._search_relevant_memory(
                query=message,
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
                            if len(content_summary) > 2000:
                                content_summary = content_summary[:2000] + "..."
                            context_parts.append(f"  {i}. From {agent_name}: {content_summary}")
                        else:
                            print(f"⚠️ No content found in memory result {i} from {agent_name}")
                    
                    except Exception as e:
                        print(f"⚠️ Error processing memory result {i}: {e}")
                        continue
            
            else:
                print(f"🧠 No relevant memory context found")
        
        except Exception as e:
            print(f"❌ Error searching memory: {e}")
            context_parts.append("Note: Unable to retrieve relevant context from memory")
        
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
        span: Any
    ):
        """Background task for storing A2A interactions without blocking parallel execution"""
        try:
            await self._store_a2a_interaction(
                outbound_request=outbound_request,
                inbound_response=inbound_response,
                agent_name=agent_name,
                processing_time=processing_time,
                span=span
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
        span: Any
    ):
        """Store complete A2A protocol payloads"""
        try:
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
            
            # Store in memory service
            success = await a2a_memory_service.store_interaction(interaction_data)
            
            if success:
                print(f"[A2A Memory] Stored A2A payloads for {agent_name}")
                span.add_event("memory_stored", {"agent_name": agent_name})
            else:
                print(f"[A2A Memory] Failed to store A2A payloads for {agent_name}")
                span.add_event("memory_store_failed", {"agent_name": agent_name})
                
        except Exception as e:
            print(f"[A2A Memory] Error storing A2A payloads: {str(e)}")
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
            print(f"Exception type: {type(e).__name__}")
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
        print(f"🚀 _store_user_host_interaction: STARTING")
        print(f"- user_message_text: {user_message_text[:100]}...")
        print(f"- host_response count: {len(host_response)}")
        print(f"- context_id: {context_id}")
        print(f"- user_message_parts type: {type(user_message_parts)}")
        print(f"- user_message_parts length: {len(user_message_parts) if user_message_parts else 0}")
        
        try:
            print(f"📝 Step 1: About to create A2A Message object...")
            
            # Create real A2A Message object for outbound
            print(f"📝 Step 1a: Creating outbound_message with uuid...")
            message_id = str(uuid.uuid4())
            print(f"📝 Step 1b: Generated messageId: {message_id}")
            
            print(f"📝 Step 1c: About to create Message object...")
            # Clean file bytes from parts before storing in memory
            cleaned_parts = self._clean_file_bytes_from_parts(user_message_parts, artifact_info)
            print(f"📝 Step 1d: Cleaned {len(user_message_parts)} parts for memory storage")
            
            outbound_message = Message(
                messageId=message_id,
                contextId=context_id,
                taskId=None,
                role="user",  # User→Host message
                parts=cleaned_parts  # Use cleaned A2A Parts without file bytes
            )
            print(f"✅ Step 1: Created outbound_message successfully")
            
            # Create real A2A MessageSendParams
            print(f"📝 Step 2: About to create MessageSendParams...")
            request_id = str(uuid.uuid4())
            print(f"📝 Step 2a: Generated request ID: {request_id}")
            
            print(f"📝 Step 2b: About to create MessageSendConfiguration...")
            config = MessageSendConfiguration(
                acceptedOutputModes=["text", "text/plain", "image/png"]
            )
            print(f"✅ Step 2c: Created MessageSendConfiguration")
            
            print(f"📝 Step 2d: About to create MessageSendParams...")
            outbound_request = MessageSendParams(
                id=request_id,
                message=outbound_message,
                configuration=config
            )
            print(f"✅ Step 2: Created MessageSendParams successfully")
            
            # Create real A2A Message object for inbound response
            print(f"📝 Step 3: Creating inbound response parts...")
            response_parts = []
            for i, response in enumerate(host_response):
                print(f"📝 Step 3.{i+1}: Creating Part for response {i+1}")
                text_part = TextPart(kind="text", text=response)
                part = Part(root=text_part)
                response_parts.append(part)
                print(f"✅ Step 3.{i+1}: Created Part successfully")
            
            print(f"📝 Step 4: Creating inbound Message...")
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
            print(f"📝 Step 6: Storing User→Host interaction in memory...")
            
            # Create interaction data structure like the working Host→Remote Agent code
            interaction_data = {
                "interaction_id": str(uuid.uuid4()),
                "agent_name": "host_agent",
                "processing_time_seconds": 1.0,
                "timestamp": datetime.utcnow().isoformat() + 'Z',
                "outbound_payload": outbound_dict,
                "inbound_payload": inbound_dict
            }
            
            # Store in memory service
            success = await a2a_memory_service.store_interaction(interaction_data)
            
            if success:
                print(f"✅ Step 6: User→Host interaction stored successfully")
                print(f"🎉 User→Host A2A interaction now available for semantic search")
            else:
                print(f"❌ Step 6: Failed to store User→Host interaction")
                print(f"⚠️ User→Host interaction storage failed")
                
        except Exception as e:
            print(f"❌ EXCEPTION in _store_user_host_interaction: {e}")
            print(f"Exception type: {type(e).__name__}")
            import traceback
            print(f"Full traceback: {traceback.format_exc()}")
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

    async def run_conversation_with_parts(self, message_parts: List[Part], context_id: Optional[str] = None, event_logger=None) -> Any:
        """Run conversation with A2A message parts (including files)."""
        print(f"⭐ ENTRY: run_conversation_with_parts called with {len(message_parts) if message_parts else 0} parts")
        try:
            print(f"🔍 Step A: About to create tracer span...")
            scenario = "run_conversation_with_parts"
            with tracer.start_as_current_span(scenario) as span:
                print(f"🔍 Step B: Created tracer span successfully")
                
                print(f"🔍 Step C1: About to call span.set_attribute...")
                span.set_attribute("context_id", context_id or self.default_context_id)
                print(f"🔍 Step C2: span.set_attribute completed")
                print(f"🔍 Step D: Set span attribute")
            print(f"run_conversation_with_parts called with {len(message_parts)} parts")
            
            if not context_id:
                context_id = self.default_context_id
            print(f"🔍 Step E: Set context_id to {context_id}")
            
            # Extract text message for thread
            print(f"🔍 Step F: About to extract text message...")
            user_message = ""
            for part in message_parts:
                if hasattr(part, 'root') and part.root.kind == 'text':
                    user_message = part.root.text
                    break
            print(f"🔍 Step G: Extracted text message")
            
            print(f"Extracted user message: {user_message}")
            print(f"Processing {len(message_parts)} parts including files")
            
            # Ensure agent is created (may be lazy creation if startup creation failed)
            print(f"🔍 Step H: About to ensure agent exists...")
            print(f"🔍 DEBUG: Current agent state: {self.agent is not None}")
            if self.agent:
                print(f"🔍 DEBUG: Agent exists with ID: {self.agent.get('id', 'unknown')}")
            else:
                print("⚠️ Agent not created at startup, creating now (lazy creation)...")
                print(f"🔍 DEBUG: Calling create_agent()...")
                await self.create_agent()
                print(f"🔍 DEBUG: create_agent() completed")
            print(f"🔍 Step I: Agent ready with ID: {self.agent.get('id', 'unknown') if self.agent else 'STILL_NULL'}")
            
            session_context = self.get_session_context(context_id)
            
            # Create or get thread
            thread_created = False
            if context_id not in self.threads:
                print(f"🔍 DEBUG: Creating new thread for context_id: {context_id}")
                thread = await self.create_thread(context_id)
                self.threads[context_id] = thread["id"]  # Use dictionary access
                thread_created = True
                print(f"🔍 DEBUG: New thread created with ID: {thread['id']}")
            else:
                print(f"🔍 DEBUG: Reusing existing thread for context_id: {context_id}, thread_id: {self.threads[context_id]}")
            thread_id = self.threads[context_id]
            
            print(f"🔍 DEBUG: =================== THREAD READY, STARTING MESSAGE PROCESSING ===================")
            print(f"🔍 DEBUG: Thread ID: {thread_id}")
            print(f"🔍 DEBUG: About to process {len(message_parts)} message parts")
            
            # Process all message parts (including files) BEFORE sending to thread
            #tool_context = DummyToolContext(session_context, self.azure_blob_client)
            tool_context = DummyToolContext(SessionContext(), self._azure_blob_client)
            processed_parts = []
            print(f"🔍 DEBUG: processed_parts list initialized")
            
            # Count files to show appropriate status
            print(f"🔍 DEBUG: Counting files in message parts...")
            file_count = 0
            for part in message_parts:
                if hasattr(part, 'root') and hasattr(part.root, 'kind') and part.root.kind == 'file':
                    file_count += 1
            print(f"🔍 DEBUG: Found {file_count} files in {len(message_parts)} parts")
            
            if file_count > 0:
                print(f"🔍 DEBUG: Emitting file processing status...")
                try:
                    if file_count == 1:
                        await self._emit_status_event("processing uploaded file", context_id)
                    else:
                        await self._emit_status_event(f"processing {file_count} uploaded files", context_id)
                    print(f"🔍 DEBUG: File processing status emitted successfully")
                except Exception as e:
                    print(f"❌ DEBUG: Exception emitting file processing status: {e}")
                    # Don't let status emission failures stop the main flow
            
            print(f"🔍 PART DEBUG: About to process {len(message_parts)} parts:")
            for i, part in enumerate(message_parts):
                print(f"🔍 PART DEBUG: Part {i}: {type(part)} - hasattr root: {hasattr(part, 'root')}")
                if hasattr(part, 'root'):
                    print(f"🔍 PART DEBUG: Part {i} root kind: {getattr(part.root, 'kind', 'no kind attr')}")
                    if hasattr(part.root, 'kind') and part.root.kind == 'file':
                        print(f"🔍 PART DEBUG: Part {i} is FILE - name: {getattr(part.root.file, 'name', 'no name')}, uri: {getattr(part.root.file, 'uri', 'no uri')}")
                
                print(f"🔍 PART DEBUG: About to call convert_part for part {i}")
                try:
                    processed_result = await self.convert_part(part, tool_context, context_id)
                    print(f"🔍 PART DEBUG: convert_part result for part {i}: {type(processed_result)} - {str(processed_result)[:100]}...")
                    processed_parts.append(processed_result)
                except Exception as e:
                    print(f"❌ CRITICAL ERROR in convert_part for part {i}: {e}")
                    import traceback
                    print(f"❌ CONVERT_PART TRACEBACK: {traceback.format_exc()}")
                    raise
            
            print(f"Processed {len(processed_parts)} parts")
            
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
            
            print(f"Enhanced message: {enhanced_message}")
            
            # Send enhanced message to thread
            print(f"🔍 About to send message to thread...")
            await self._emit_status_event("sending message to AI thread", context_id)
            await self.send_message_to_thread(thread_id, enhanced_message)
            print(f"🔍 Message sent to thread successfully")
            
            # Continue with standard conversation flow using HTTP API
            print(f"🔍 DEBUG: =================== STARTING RUN CREATION ===================")
            print(f"🔍 DEBUG: About to create run with agent_id: {self.agent['id']} (FIRST PATH)")
            await self._emit_status_event("creating AI agent run", context_id)
            
            print(f"🔍 DEBUG: Calling _http_create_run...")
            run = await self._http_create_run(thread_id, self.agent['id'])
            print(f"🔍 DEBUG: Run created successfully with ID: {run['id']}, status: {run['status']} (FIRST PATH)")
            print(f"🔍 DEBUG: =================== RUN CREATED SUCCESSFULLY ===================")
            await self._emit_status_event(f"AI run started - status: {run['status']}", context_id)
            
            # Poll until completion, handle tool calls
            max_iterations = 30
            iterations = 0
            last_tool_output = None
            tool_calls_count = 0
            
            print(f"🔍 DEBUG: Starting polling loop for run {run['id']} (FIRST PATH)")
            while run["status"] in ["queued", "in_progress", "requires_action"] and iterations < max_iterations:
                iterations += 1
                print(f"🔍 DEBUG: Polling iteration {iterations}, current status: {run['status']} (FIRST PATH)")
                
                # Emit status for different run states
                if run["status"] == "queued":
                    await self._emit_status_event("AI request queued for processing", context_id)
                elif run["status"] == "in_progress":
                    await self._emit_status_event("AI is analyzing and processing", context_id)
                elif run["status"] == "requires_action":
                    await self._emit_status_event("AI requires tools - executing actions", context_id)
                
                import asyncio; await asyncio.sleep(1)
                print(f"🔍 DEBUG: About to get run status for iteration {iterations} (FIRST PATH)")
                run = await self._http_get_run(thread_id, run["id"])
                print(f"🔍 DEBUG: Got run status: {run['status']} (iteration {iterations}) (FIRST PATH)")
                
                if run["status"] == "failed":
                    print(f"🔍 DEBUG: Run failed, breaking from loop (FIRST PATH)")
                    await self._emit_status_event("AI run failed", context_id)
                    break
                    
                if run["status"] == "requires_action":
                    print(f"🔍 DEBUG: Run requires action, handling tool calls (FIRST PATH)")
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
                        print(f"🔥 OPTIMIZED: Processing {len(batch_tool_calls)} tool calls in batch")
                    
                    # Now execute all tool calls in parallel fashion
                    if all_tool_calls:
                        print(f"🔥 OPTIMIZED: Executing {len(all_tool_calls)} tool calls in parallel")
                        
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
            
            print(f"🔍 DEBUG: Polling loop completed. Final status: {run['status']}, iterations: {iterations} (FIRST PATH)")
            await self._emit_status_event("AI processing completed, generating response", context_id)
            
            # Get response messages
            print(f"🔍 DEBUG: About to retrieve messages from thread (FIRST PATH)")
            await self._emit_status_event("retrieving AI response", context_id)
            messages = await self._http_list_messages(thread_id)
            print(f"🔍 DEBUG: Retrieved {len(messages)} messages from thread (FIRST PATH)")
            
            responses = []
            assistant_messages_found = 0
            
            for i, msg in enumerate(messages):
                print(f"🔍 DEBUG: Message {i}: role={msg.get('role')}, has_content={bool(msg.get('content'))} (FIRST PATH)")
                if msg.get("content"):
                    print(f"🔍 DEBUG: Message {i} content count: {len(msg['content'])} (FIRST PATH)")
                    for j, content in enumerate(msg['content']):
                        print(f"🔍 DEBUG: Content {j}: type={content.get('type')}, has_text={bool(content.get('text'))} (FIRST PATH)")
                        if content.get("text"):
                            print(f"🔍 DEBUG: Text object: {content.get('text')} (FIRST PATH)")
                else:
                    print(f"🔍 DEBUG: Message {i} has no content! (FIRST PATH)")
                
                if msg.get("role") == "assistant" and msg.get("content"):
                    assistant_messages_found += 1
                    print(f"🔍 DEBUG: Processing assistant message {assistant_messages_found} (FIRST PATH)")
                    current_responses = []
                    for content in msg["content"]:
                        if content.get("type") == "text" and content.get("text", {}).get("value"):
                            text_value = content["text"]["value"]
                            print(f"🔍 DEBUG: Found text value: {text_value[:100]}... (FIRST PATH)")
                            if not text_value or "couldn't retrieve" in text_value.lower() or "no response" in text_value.lower():
                                print(f"🔍 DEBUG: Skipping invalid text value (FIRST PATH)")
                                continue
                            current_responses.append(text_value)
                            print(f"🔍 DEBUG: Added response to current list (FIRST PATH)")
                    if current_responses:
                        print(f"🔍 DEBUG: Found responses in message {i}, updating latest responses (FIRST PATH)")
                        responses = current_responses  # Keep updating to get the most recent responses
                else:
                    if msg.get("role") != "assistant":
                        print(f"🔍 DEBUG: Skipping message {i} - not assistant role: {msg.get('role')} (FIRST PATH)")
                    else:
                        print(f"🔍 DEBUG: Skipping message {i} - assistant but no content (FIRST PATH)")
            
            # If no valid assistant message found, surface tool output as fallback
            if not responses and last_tool_output:
                print(f"🔍 DEBUG: No assistant responses found, using tool output as fallback (FIRST PATH)")

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
            
            print(f"🔍 DEBUG: After message processing - responses count: {len(responses) if responses else 0} (FIRST PATH)")
            if responses:
                print(f"🔍 DEBUG: First response: {responses[0][:100]}... (FIRST PATH)")
                
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
                
                # If we have extracted content, replace the host agent's response with the extracted content
                if has_extracted_content:
                    extracted_content_message = (
                        "The file has been processed. Here is the extracted content:\n\n" + 
                        "\n\n---\n\n".join(extracted_contents)
                    )
                    
                    # CRITICAL FIX: Send the extracted content to the thread so it's available for follow-up questions
                    print(f"📝 Sending extracted content to thread for future context...")
                    await self.send_message_to_thread(thread_id, extracted_content_message, role="assistant")
                    
                    final_responses = [extracted_content_message]
                else:
                    # Use the original host agent response
                    final_responses = responses if responses else ["No response received"]
                    
                    # Add file upload acknowledgment if files were uploaded but no content extracted
                    if processed_parts and any(isinstance(p, DataPart) for p in processed_parts):
                        final_responses.append(f"File processing completed. {len([p for p in processed_parts if isinstance(p, DataPart)])} file(s) uploaded and stored as artifacts.")
                
                print(f"🔍 DEBUG: final_responses set to: {final_responses} (FIRST PATH)")
                print(f"🔍 DEBUG: final_responses count: {len(final_responses)} (FIRST PATH)")
                
                # Note: Conversation history is now managed by OpenAI threads - no need to store separately
                
                # Store User→Host A2A interaction (fire-and-forget)
                print(f"About to store User→Host interaction for context_id: {context_id}")
                
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
                
                print(f"🔍 DEBUG: About to return final_responses: {final_responses} (FIRST PATH)")
                
                # FIXED: Don't stream here if host manager is handling it to prevent duplicates
                # The host manager will stream the response, so we skip streaming here
                print(f"[DEBUG] Skipping foundry agent direct streaming - host manager will handle response streaming")
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
                                    print(f"[DEBUG] Host agent final response event streamed: {event_data}")
                                else:
                                    print("[DEBUG] Failed to stream host agent final response event")
                            else:
                                print("[DEBUG] WebSocket streamer not available for host agent final response")
                        except Exception as e:
                            print(f"[DEBUG] Error streaming host agent final response to Event Hub: {e}")
                            # Don't let Event Hub errors break the main flow
                            pass
                        
                    except ImportError:
                        # Event Hub module not available, continue without streaming
                        print("[DEBUG] Event Hub module not available for host agent response")
                        pass
                    except Exception as e:
                        print(f"[DEBUG] Error setting up host agent response streaming: {e}")
                        # Don't let Event Hub errors break the main flow
                        pass
                else:
                    print(f"[DEBUG] Host agent response already sent for context {context_id}, skipping duplicate")
                
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
            contextualized_message = await self._add_context_to_message(user_message, session_context, thread_id=thread_id)
            
            # Send contextualized message to thread
            await self.send_message_to_thread(thread_id, contextualized_message)
            print(f"🔍 DEBUG: Message sent to thread successfully, moving to next step...")
            
            # Debug: Check agent tools before running
            print(f"========= AGENT TOOLS DEBUG ==========")
            print(f"Agent ID: {self.agent['id']}")
            print(f"Agent tools: {self.agent.get('tools', 'No tools attribute')}")
            print(f"Available remote agents: {list(self.remote_agent_connections.keys())}")
            print(f"User message: '{user_message}'")
            print(f"==========================================")
            
            # Run the agent using HTTP API
            print(f"🔍 DEBUG: About to create run with agent_id: {self.agent['id']}")
            run = await self._http_create_run(thread_id, self.agent['id'])
            print(f"🔍 DEBUG: Run created successfully with ID: {run['id']}, status: {run['status']}")
            
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
            
            print(f"🔍 DEBUG: Starting polling loop for run {run['id']}")
            while run["status"] in ["queued", "in_progress", "requires_action"] and iterations < max_iterations:
                iterations += 1
                print(f"🔍 DEBUG: Polling iteration {iterations}, current status: {run['status']}")
                
                import asyncio; await asyncio.sleep(1)
                
                print(f"🔍 DEBUG: About to get run status for iteration {iterations}")
                run = await self._http_get_run(thread_id, run["id"])
                print(f"🔍 DEBUG: Got run status: {run['status']} (iteration {iterations})")
                
                # Debug: Check if run has required_action
                if run.get('required_action'):
                    print(f"🔍 DEBUG: Run has required_action: {run['required_action']}")
                else:
                    print(f"🔍 DEBUG: Run has NO required_action - agent should be responding directly")
                
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
                        print(f"🔥 OPTIMIZED: Processing {len(batch_tool_calls)} tool calls in batch")
                    
                    # Now execute all tool calls in parallel fashion
                    if all_tool_calls:
                        print(f"🔥 OPTIMIZED: Executing {len(all_tool_calls)} tool calls in parallel")
                        
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
            
            print(f"🔍 DEBUG: Polling loop completed. Final status: {run['status']}, iterations: {iterations}")
            
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
                print(f"[DEBUG] Skipping foundry agent direct streaming (run_conversation) - host manager will handle response streaming")
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
                                    print(f"[DEBUG] Host agent final response event streamed (run_conversation): {event_data}")
                                else:
                                    print("[DEBUG] Failed to stream host agent final response event (run_conversation)")
                            else:
                                print("[DEBUG] WebSocket streamer not available for host agent final response (run_conversation)")
                        except Exception as e:
                            print(f"[DEBUG] Error streaming host agent final response to Event Hub (run_conversation): {e}")
                            # Don't let Event Hub errors break the main flow
                            pass
                        
                    except ImportError:
                        # Event Hub module not available, continue without streaming
                        print("[DEBUG] Event Hub module not available for host agent response (run_conversation)")
                        pass
                    except Exception as e:
                        print(f"[DEBUG] Error setting up host agent response streaming (run_conversation): {e}")
                        # Don't let Event Hub errors break the main flow
                        pass
                else:
                    print(f"[DEBUG] Host agent response already sent for context {context_id}, skipping duplicate (run_conversation)")
                
                return final_responses

    async def _handle_tool_calls(self, run: Dict[str, Any], thread_id: str, context_id: str, session_context: SessionContext, event_logger=None):
        with tracer.start_as_current_span("handle_tool_calls") as span:
            span.set_attribute("context_id", context_id)
            print(f"_handle_tool_calls called for thread_id: {thread_id}, context_id: {context_id}")
            
            if not run.get('required_action'):
                print("[DEBUG] No required_action in run.")
                return None
                
            required_action = run.get('required_action')
            if not required_action.get('submit_tool_outputs'):
                print("[DEBUG] No submit_tool_outputs in required_action.")
                return None
                
            tool_calls = required_action['submit_tool_outputs']['tool_calls']
            print(f"🔥 OPTIMIZED: Processing {len(tool_calls)} tool calls")
            
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
                print(f"🚀 Executing {len(send_message_tool_calls)} send_message calls in parallel")
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
                    asyncio.create_task(self._emit_tool_call_event(agent_name, "send_message", arguments))
                    
                    # Log tool call event
                    if event_logger:
                        event_logger({
                            "id": str(uuid.uuid4()),
                            "actor": "foundry-host-agent",
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
                            asyncio.create_task(self._emit_tool_response_event(agent_name, "send_message", "failed", str(result)))
                        else:
                            output = result
                            self._add_status_message_to_conversation(f"✅ Agent call to {agent_name} completed", context_id)
                            span.add_event("parallel_agent_call_success", {
                                "agent_name": agent_name,
                                "output_type": type(output).__name__
                            })
                            # Stream tool success to WebSocket
                            asyncio.create_task(self._emit_tool_response_event(agent_name, "send_message", "success", None))
                        
                        # Log tool result event
                        if event_logger:
                            event_logger({
                                "id": str(uuid.uuid4()),
                                "actor": "foundry-host-agent",
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
                await self._emit_tool_call_event("foundry-host-agent", function_name, arguments)
                
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
                    output = self.list_remote_agents()
                    self._add_status_message_to_conversation(f"✅ Tool {function_name} completed", context_id)
                    span.add_event("agents_listed", {
                        "available_agents_count": len(output),
                        "agent_names": [agent.get("name", "unknown") for agent in output] if output else []
                    })
                    # Stream tool success to WebSocket
                    await self._emit_tool_response_event("foundry-host-agent", function_name, "success")
                else:
                    output = {"error": f"Unknown function: {function_name}"}
                    self._add_status_message_to_conversation(f"❌ Unknown tool: {function_name}", context_id)
                    span.add_event("unknown_function_called", {
                        "function_name": function_name,
                        "available_functions": ["list_remote_agents", "send_message"]
                    })
                    # Stream tool failure to WebSocket
                    await self._emit_tool_response_event("foundry-host-agent", function_name, "failed", f"Unknown function: {function_name}")
                
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
            print(f"🔥 OPTIMIZED: Submitting {len(tool_outputs)} tool outputs in one batch")
            await self._http_submit_tool_outputs(thread_id, run["id"], tool_outputs)
            
            if successful_tool_outputs:
                combined_text = "\n\n---\n\n".join(
                    payload.get("response", "") for payload in successful_tool_outputs if isinstance(payload.get("response"), str)
                )
                aggregated_payload = {
                    "kind": "function_response",
                    "name": "aggregated_send_message",
                    "response": combined_text
                }
                return aggregated_payload
            
            return last_tool_output

    async def convert_parts(self, parts: List[Part], tool_context: Any, context_id: str = None):
        rval = []
        print(f"convert_parts: processing {len(parts)} parts")
        for i, p in enumerate(parts):
            result = await self.convert_part(p, tool_context, context_id)
            rval.append(result)
        
        return rval

    async def convert_part(self, part: Part, tool_context: Any, context_id: str = None):
        # Don't print the entire part (contains large base64 data)
        if hasattr(part, 'root') and part.root.kind == 'file':
            file_name = getattr(part.root.file, 'name', 'unknown')
            mime_type = getattr(part.root.file, 'mimeType', 'unknown')
            print(f"convert_part: FilePart - name: {file_name}, mimeType: {mime_type}")
            
            # Emit status event for file processing
            if context_id:
                await self._emit_status_event(f"processing file: {file_name}", context_id)
        else:
            print(f"convert_part: {type(part)} - kind: {getattr(part.root, 'kind', 'unknown') if hasattr(part, 'root') else 'no root'}")
        
        # Handle dicts coming from streaming conversions or patched remote agents
        if isinstance(part, dict):
            # Simple heuristic: if it looks like {'kind': 'text', 'text': '...'}
            if part.get('kind') == 'text' and 'text' in part:
                text_content = part['text']
                print(f"[DEBUG] convert_part: dict text content: {text_content[:200]}...")
                return text_content
            if part.get('kind') == 'data' and 'data' in part:
                return part['data']
            # Fallthrough – stringify the dict
            return json.dumps(part)

        # Fallback to standard A2A Part handling
        if hasattr(part, 'root') and part.root.kind == 'text':
            text_content = part.root.text
            print(f"[DEBUG] convert_part: text part content: {text_content[:200]}...")
            return text_content
        elif hasattr(part, 'root') and part.root.kind == 'data':
            print(f"DataPart data: {part.root.data} (type: {type(part.root.data)})")
            return part.root.data
        elif hasattr(part, 'root') and part.root.kind == 'file':
            # A2A protocol compliant file handling with enterprise security
            file_id = part.root.file.name
            print(f"🔍 FILE DEBUG: Starting file processing for: {file_id}")
            
            file_bytes = None
            
            # Check if this is an uploaded file with URI
            if hasattr(part.root.file, 'uri') and part.root.file.uri:
                print(f"🔍 FILE DEBUG: Found URI: {part.root.file.uri}")
                # This is an uploaded file, read from uploads directory
                if part.root.file.uri.startswith('/uploads/'):
                    file_uuid = part.root.file.uri.split('/')[-1]
                    upload_dir = "uploads"
                    print(f"🔍 FILE DEBUG: Looking for file with UUID: {file_uuid} in {upload_dir}")
                    
                    # Find the actual file with this UUID (may have extension)
                    try:
                        import os
                        print(f"🔍 FILE DEBUG: About to list files in {upload_dir}")
                        uploaded_files = os.listdir(upload_dir)
                        print(f"🔍 FILE DEBUG: Found {len(uploaded_files)} files")
                        
                        for uploaded_filename in uploaded_files:
                            print(f"🔍 FILE DEBUG: Checking file: {uploaded_filename}")
                            if uploaded_filename.startswith(file_uuid):
                                file_path = os.path.join(upload_dir, uploaded_filename)
                                print(f"🔍 FILE DEBUG: Reading file: {file_path}")
                                with open(file_path, 'rb') as f:
                                    file_bytes = f.read()
                                print(f"📄 FILE DEBUG: Loaded uploaded file: {len(file_bytes)} bytes from {file_path}")
                                break
                        else:
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
                    return f"Error: Failed to decode file {file_id}: {str(e)}"
            
            if not file_bytes:
                print(f"❌ No file bytes loaded")
                return f"Error: Could not load file data for {file_id}"
            
            # For uploaded files, process them directly with the document processor
            if hasattr(part.root.file, 'uri') and part.root.file.uri and part.root.file.uri.startswith('/uploads/'):
                print(f"📄 FILE DEBUG: Processing uploaded file with document processor...")
                try:
                    if not file_bytes:
                        print(f"❌ FILE DEBUG: No file bytes loaded, cannot process")
                        return f"File: {file_id} (could not load file data)"
                    
                    # For PDFs, let's use a simple approach - just indicate we processed it
                    # Process document with document processor
                    artifact_info = {
                        'artifact_uri': part.root.file.uri,
                        'file_name': file_id,
                        'file_bytes': file_bytes
                    }
                    
                    print(f"FILE DEBUG: Calling document processor for {file_id}")
                    processing_result = await a2a_document_processor.process_file_part(part.root.file, artifact_info)
                    
                    if processing_result and isinstance(processing_result, dict) and processing_result.get("success"):
                        content = processing_result.get("content", "")
                        print(f"FILE DEBUG: Document processing successful, content length: {len(content)}")
                        
                        # Emit completion status event
                        if context_id:
                            await self._emit_status_event(f"file processed successfully: {file_id}", context_id)
                        
                        return f"File: {file_id}\nContent:\n{content}"
                    else:
                        error = processing_result.get("error", "Unknown error") if isinstance(processing_result, dict) else "Processing failed"
                        print(f"FILE DEBUG: Document processing failed: {error}")
                        return f"File: {file_id} (processing failed: {error})"
                        # Simple PDF content extraction (placeholder for now)
                        print(f"� FILE DEBUG: Processing PDF file {file_id} ({len(file_bytes)} bytes)")
                        
                except Exception as e:
                    print(f"❌ FILE DEBUG: Error processing uploaded file: {e}")
                    import traceback
                    print(f"❌ FILE DEBUG: Processing traceback: {traceback.format_exc()}")
                    return f"File: {file_id} (processing error: {str(e)})"
            
            # Enhanced security: Validate file before processing
            if len(file_bytes) > 50 * 1024 * 1024:  # 50MB limit
                return DataPart(data={'error': 'File too large', 'max_size': '50MB'})
            
            print(f"File validation passed, proceeding with artifact creation")
            
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
                            'mimeType': part.root.file.mimeType,
                            'data': file_bytes  # Raw bytes, not base64
                        }
                    }
                    print(f"Successfully created A2A file part")
                    
                    print(f"Calling save_artifact...")
                    # save_artifact now returns A2A compliant DataPart with artifact metadata
                    artifact_response = await tool_context.save_artifact(file_id, a2a_file_part)
                    tool_context.actions.skip_summarization = True
                    tool_context.actions.escalate = True
                    
                    print(f"save_artifact completed, now processing file content...")
                    
                    # Process file content and store in A2A memory service
                    try:
                        # Extract artifact info for document processing
                        artifact_info = None
                        if isinstance(artifact_response, DataPart) and hasattr(artifact_response, 'data'):
                            artifact_info = {
                                'artifact_id': artifact_response.data.get('artifact-id'),
                                'artifact_uri': artifact_response.data.get('artifact-uri'),
                                'file_name': artifact_response.data.get('file-name'),
                                'storage_type': artifact_response.data.get('storage-type')
                            }
                            
                            # For local files, get the file bytes directly from tool_context
                            if artifact_info.get('storage_type') == 'local':
                                artifact_id = artifact_info.get('artifact_id')
                                if hasattr(tool_context, '_artifacts') and artifact_id in tool_context._artifacts:
                                    artifact_data = tool_context._artifacts[artifact_id]
                                    if 'file_bytes' in artifact_data:
                                        artifact_info['file_bytes'] = artifact_data['file_bytes']
                                        print(f"Added file bytes to artifact_info for local file: {len(artifact_data['file_bytes'])} bytes")
                        
                        # Process the file and store extracted content in memory
                        processing_result = await a2a_document_processor.process_file_part(part, artifact_info)
                        if processing_result.get("success"):
                            print(f"✅ File content processed and stored in memory service")
                            # Add extracted content to artifact response for immediate display
                            if isinstance(artifact_response, DataPart) and hasattr(artifact_response, 'data'):
                                artifact_response.data['extracted_content'] = processing_result.get("content", "")
                                artifact_response.data['content_preview'] = processing_result.get("content", "")[:500] + "..." if len(processing_result.get("content", "")) > 500 else processing_result.get("content", "")
                        else:
                            print(f"⚠️ File content processing failed: {processing_result.get('error', 'Unknown error')}")
                            
                    except Exception as e:
                        print(f"⚠️ Error during document processing: {e}")
                        # Don't fail the whole file upload if document processing fails
                        import traceback
                        print(f"Document processing traceback: {traceback.format_exc()}")
                    
                    print(f"save_artifact completed, returning response")
                    # Return the full A2A artifact response
                    return artifact_response
                except Exception as e:
                    print(f"Exception in save_artifact process: {e}")
                    import traceback
                    print(f"Full traceback: {traceback.format_exc()}")
                    return DataPart(data={'error': f'Failed to process file: {str(e)}'})
            else:
                print(f"ERROR: tool_context has no save_artifact method")
                return DataPart(data={'error': 'Artifact storage not available'})
        return f'Unknown type: {getattr(part, "kind", None)}'

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
            
            print(f"✅ Successfully registered remote agent from: {agent_address}")
            print(f"📊 Total registered agents: {len(self.remote_agent_connections)}")
            print(f"📋 Agent names: {list(self.remote_agent_connections.keys())}")
            
            # Agent will appear in UI sidebar within 15 seconds via periodic sync
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to register remote agent from {agent_address}: {e}")
            import traceback
            print(f"❌ Registration error traceback: {traceback.format_exc()}")
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
        asyncio.create_task(self._emit_granular_agent_event("foundry-host-agent", status_text))

    async def _emit_status_event(self, status_text: str, context_id: str):
        """Emit status event to Event Hub for real-time frontend updates."""
        # Use WebSocket streaming for real-time status updates
        await self._emit_granular_agent_event("foundry-host-agent", status_text)

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
    def __init__(self, session_context: SessionContext, azure_blob_client=None):
        self.state = session_context
        self._artifacts = {}  # A2A compliant artifact storage with metadata
        self._azure_blob_client = azure_blob_client  # Pass Azure client from host agent
        
        # Create local storage directory for uploaded files
        self.storage_dir = os.path.join(os.getcwd(), "host_agent_files")
        os.makedirs(self.storage_dir, exist_ok=True)
        
        # A2A Artifact service base URL (for URI references)
        self.artifact_base_url = f"http://localhost:8000/artifacts"  # Configurable for production
        
        class Actions:
            skip_summarization = False
            escalate = False
        self.actions = Actions()
    
    async def save_artifact(self, file_id: str, file_part):
        """Save artifact following A2A protocol best practices with Azure Blob Storage support."""
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
            
            if isinstance(file_part, dict):
                # Handle A2A-native format
                if file_part.get('kind') == 'file' and 'file' in file_part:
                    file_info = file_part['file']
                    file_bytes = file_info['data']
                    mime_type = file_info.get('mimeType', 'application/octet-stream')
                    print(f"Extracted {len(file_bytes)} bytes from A2A file part")
                else:
                    print(f"Could not extract file bytes from A2A file part: {file_part.keys()}")
                    return DataPart(data={'error': 'Invalid A2A file format'})
            elif hasattr(file_part, 'inline_data') and hasattr(file_part.inline_data, 'data'):
                # Handle Google ADK format (fallback)
                file_bytes = file_part.inline_data.data
                mime_type = getattr(file_part.inline_data, 'mime_type', 'application/octet-stream')
                print(f"Extracted {len(file_bytes)} bytes from inline_data")
            elif hasattr(file_part, 'data'):
                file_bytes = file_part.data
                mime_type = 'application/octet-stream'
                print(f"Extracted {len(file_bytes)} bytes from data attribute")
            else:
                print(f"Could not extract file bytes from artifact: {type(file_part)}")
                return DataPart(data={'error': 'Invalid file format'})
            
            print(f"File size: {len(file_bytes)} bytes, MIME type: {mime_type}")
            
            # Enhanced security: Validate file before processing
            if len(file_bytes) > 50 * 1024 * 1024:  # 50MB limit
                return DataPart(data={'error': 'File too large', 'max_size': '50MB'})
            
            # Determine storage strategy based on file size and configuration
            use_azure_blob = self._should_use_azure_blob(len(file_bytes))
            
            if use_azure_blob and hasattr(self, '_azure_blob_client'):
                # A2A URI mechanism with Azure Blob Storage
                print(f"Using Azure Blob Storage for large file")
                file_uri = await self._upload_to_azure_blob(artifact_id, file_id, file_bytes, mime_type)
                
                # Create A2A compliant Artifact with URI reference
                # Following official A2A specification: FilePart.file = FileWithUri
                file_part = FilePart(
                    kind="file",
                    file=FileWithUri(
                        name=file_id,
                        mimeType=mime_type,
                        uri=file_uri  # Azure Blob URI with SAS token
                    )
                )
                
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
                        "accessMethod": "uri"
                    }
                )
                
                # Store metadata in memory (URI-based, no local file bytes)
                self._artifacts[artifact_id] = {
                    'artifact': artifact,
                    'storage_type': 'azure_blob',
                    'uri': file_uri,
                    'created_at': datetime.utcnow().isoformat()
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
                file_part = FilePart(
                    kind="file",
                    file=FileWithUri(
                        name=file_id,
                        mimeType=mime_type,
                        uri=f"{self.artifact_base_url}/{artifact_id}"  # Local HTTP endpoint
                    )
                )
                
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
                        "accessMethod": "uri"
                    }
                )
                
                # Store in memory with full artifact metadata
                self._artifacts[artifact_id] = {
                    'artifact': artifact,
                    'file_bytes': file_bytes,
                    'local_path': file_path,
                    'storage_type': 'local',
                    'created_at': datetime.utcnow().isoformat()
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
            
            return response
            
        except Exception as e:
            print(f"Error saving A2A artifact: {e}")
            import traceback
            print(f"Full traceback: {traceback.format_exc()}")
            return DataPart(data={
                'error': f'Failed to save artifact: {str(e)}',
                'file-name': file_id,
                'status': 'failed'
            })
    
    def _should_use_azure_blob(self, file_size_bytes: int) -> bool:
        """Determine whether to use Azure Blob based on file size and configuration."""
        # Use Azure Blob for files larger than 1MB or if always enabled
        size_threshold = int(os.getenv('AZURE_BLOB_SIZE_THRESHOLD', 1024 * 1024))  # 1MB default
        force_azure = os.getenv('FORCE_AZURE_BLOB', 'false').lower() == 'true'
        has_azure_config = hasattr(self, '_azure_blob_client') and self._azure_blob_client is not None
        
        print(f"Azure Blob decision factors:")
        print(f"   - File size: {file_size_bytes:,} bytes")
        print(f"   - Size threshold: {size_threshold:,} bytes")
        print(f"   - Force Azure: {force_azure}")
        print(f"   - Has Azure client: {has_azure_config}")
        print(f"   - Size exceeds threshold: {file_size_bytes > size_threshold}")
        
        decision = has_azure_config and (file_size_bytes > size_threshold or force_azure)
        print(f"🎯 Azure Blob decision: {'YES' if decision else 'NO'}")
        
        return decision
    
    async def _upload_to_azure_blob(self, artifact_id: str, file_name: str, file_bytes: bytes, mime_type: str) -> str:
        """Upload file to Azure Blob Storage and return A2A-compliant URI with SAS token."""
        from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions, ContentSettings
        from datetime import datetime, timedelta
        import os
        
        try:
            # Generate blob name with artifact ID for uniqueness
            blob_name = f"a2a-artifacts/{artifact_id}/{file_name}"
            
            # Upload to Azure Blob
            blob_client = self._azure_blob_client.get_blob_client(
                container=os.getenv('AZURE_BLOB_CONTAINER', 'a2a-files'),
                blob=blob_name
            )
            
            # Create proper ContentSettings object
            content_settings = ContentSettings(
                content_type=mime_type,
                content_disposition=f'attachment; filename="{file_name}"'
            )
            
            # Upload with metadata
            await blob_client.upload_blob(
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
            
            # Extract account key from connection string for SAS token generation
            connection_string = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
            account_key = None
            if connection_string:
                # Parse connection string to extract account key
                for part in connection_string.split(';'):
                    if part.startswith('AccountKey='):
                        account_key = part.split('=', 1)[1]
                        break
            
            if account_key:
                # Generate SAS token for secure access (A2A best practice)
                sas_token = generate_blob_sas(
                    account_name=blob_client.account_name,
                    container_name=blob_client.container_name,
                    blob_name=blob_name,
                    account_key=account_key,
                    permission=BlobSasPermissions(read=True),
                    expiry=datetime.utcnow() + timedelta(hours=24)  # 24-hour access
                )
                
                # Return A2A-compliant URI with SAS token
                blob_uri = f"{blob_client.url}?{sas_token}"
            else:
                # Fallback: return blob URL without SAS token (less secure)
                blob_uri = blob_client.url
                print(f"Warning: No account key found for SAS token generation")
            
            return blob_uri
            
        except Exception as e:
            print(f"Error uploading to Azure Blob: {e}")
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
