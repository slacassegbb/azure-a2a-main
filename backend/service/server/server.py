import asyncio
import base64
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import cast, Any, Dict
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

from a2a.types import FilePart, FileWithUri, Message, Part, TextPart, DataPart, Role
from fastapi import APIRouter, FastAPI, Request, Response
from service.websocket_streamer import get_websocket_streamer
from service.websocket_server import get_websocket_server
from service.agent_registry import get_registry, get_session_registry
from service import chat_history_service

# Add backend directory to path for log_config import
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from log_config import log_debug

from service.types import (
    Conversation,
    CreateConversationResponse,
    GetEventResponse,
    ListAgentResponse,
    ListConversationResponse,
    ListMessageResponse,
    ListTaskResponse,
    MessageInfo,
    PendingMessageResponse,
    RegisterAgentResponse,
    SendMessageResponse,
)

from .adk_host_manager import ADKHostManager, get_message_id
from .application_manager import ApplicationManager
from .in_memory_manager import InMemoryFakeAgentManager

# In-memory mapping of messageId -> userId for user color lookup
message_user_map: Dict[str, str] = {}


async def trigger_websocket_agent_refresh():
    """Trigger agent registry refresh on the WebSocket server via HTTP.
    
    This is used when backend and WebSocket run in separate containers.
    Falls back to direct call if in same process.
    """
    try:
        # First try direct call if websocket server is in same process
        websocket_server = get_websocket_server()
        if websocket_server:
            websocket_server.trigger_immediate_sync()
            log_debug("🔔 Triggered immediate agent registry sync (direct)")
            return True
        
        # Otherwise use HTTP call to WebSocket server
        websocket_url = os.environ.get("WEBSOCKET_SERVER_URL", "http://localhost:8080")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(f"{websocket_url}/refresh-agents")
            if response.status_code == 200:
                log_debug("🔔 Triggered immediate agent registry sync via HTTP")
                return True
            else:
                log_debug(f"⚠️ HTTP refresh-agents returned {response.status_code}")
                return False
    except Exception as e:
        log_debug(f"⚠️ Failed to trigger agent refresh: {e}")
        return False


def get_context_id(obj, default: str = None) -> str:
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


def serialize_capabilities(capabilities) -> dict:
    """
    Serialize agent capabilities object to a dictionary for JSON serialization.
    Handles both dict and object types.
    """
    if isinstance(capabilities, dict):
        return capabilities
    
    if not capabilities:
        return {
            'streaming': False,
            'pushNotifications': False,
            'stateTransitionHistory': False,
            'extensions': []
        }
    
    return {
        'streaming': getattr(capabilities, 'streaming', False),
        'pushNotifications': getattr(capabilities, 'pushNotifications', False),
        'stateTransitionHistory': getattr(capabilities, 'stateTransitionHistory', False),
        'extensions': getattr(capabilities, 'extensions', [])
    }


from .foundry_host_manager import FoundryHostManager

ROOT_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(dotenv_path=ROOT_ENV_PATH, override=False)

# Create a persistent event loop for async tasks
main_loop = asyncio.new_event_loop()
asyncio.set_event_loop(main_loop)
main_loop_thread = threading.Thread(target=main_loop.run_forever, daemon=True)
main_loop_thread.start()

class ConversationServer:
    """ConversationServer is the backend to serve the agent interactions in the UI

    This defines the interface that is used by the Mesop system to interact with
    agents and provide details about the executions.
    """

    def __init__(self, app: FastAPI, http_client: httpx.AsyncClient):
        agent_manager = os.environ.get('A2A_HOST', 'FOUNDRY')
        self.manager: ApplicationManager

        # Clear session agents on startup (they should not persist across restarts)
        session_registry = get_session_registry()
        session_registry.clear_all()
        print("[Server] Session agent registry cleared on startup")

        # Get API key from environment
        api_key = os.environ.get('GOOGLE_API_KEY', '')
        uses_vertex_ai = (
            os.environ.get('GOOGLE_GENAI_USE_VERTEXAI', '').upper() == 'TRUE'
        )

        if agent_manager.upper() == 'ADK':
            self.manager = ADKHostManager(
                http_client,
                api_key=api_key,
                uses_vertex_ai=uses_vertex_ai,
            )
        elif agent_manager.upper() == 'FOUNDRY':
            self.manager = FoundryHostManager(http_client)
        else:
            self.manager = InMemoryFakeAgentManager()
        self._file_cache = {}  # dict[str, FilePart] maps file id to message data
        self._message_to_cache = {}  # dict[str, str] maps message id to cache id
        self._health_cache: Dict[str, tuple] = {}  # agent_url -> (status, timestamp)

        app.add_api_route(
            '/conversation/create', self._create_conversation, methods=['POST']
        )
        app.add_api_route(
            '/conversation/list', self._list_conversation, methods=['POST']
        )
        app.add_api_route(
            '/conversation/delete', self._delete_conversation, methods=['POST']
        )
        app.add_api_route(
            '/conversation/delete-all', self._delete_all_conversations, methods=['POST']
        )
        app.add_api_route(
            '/conversation/update-title', self._update_conversation_title, methods=['POST']
        )
        app.add_api_route('/message/send', self._send_message, methods=['POST'])
        app.add_api_route('/events/get', self._get_events, methods=['POST'])
        app.add_api_route(
            '/message/list', self._list_messages, methods=['POST']
        )
        app.add_api_route(
            '/message/pending', self._pending_messages, methods=['POST']
        )
        app.add_api_route('/task/list', self._list_tasks, methods=['POST'])
        app.add_api_route(
            '/agent/register', self._register_agent, methods=['POST']
        )
        app.add_api_route(
            '/agent/register-by-address', self._register_agent_by_address, methods=['POST']
        )
        app.add_api_route(
            '/agent/self-register', self._self_register_agent, methods=['POST']
        )
        app.add_api_route(
            '/agent/unregister', self._unregister_agent, methods=['POST']
        )
        app.add_api_route('/agent/list', self._list_agents, methods=['POST'])
        app.add_api_route('/agents', self._get_agents, methods=['GET'])
        app.add_api_route(
            '/message/file/{file_id}', self._files, methods=['GET']
        )
        app.add_api_route(
            '/api_key/update', self._update_api_key, methods=['POST']
        )
        
        # Add root instruction management endpoints
        app.add_api_route(
            '/agent/root-instruction', self._get_root_instruction, methods=['GET']
        )
        app.add_api_route(
            '/agent/root-instruction', self._update_root_instruction, methods=['PUT']
        )
        app.add_api_route(
            '/agent/root-instruction/reset', self._reset_root_instruction, methods=['POST']
        )
        
        # Workflow control endpoints
        app.add_api_route('/workflow/cancel', self._cancel_workflow, methods=['POST'])
        app.add_api_route('/workflow/interrupt', self._interrupt_workflow, methods=['POST'])

        # Session-scoped agent endpoints
        app.add_api_route('/agents/catalog', self._get_catalog, methods=['GET'])
        app.add_api_route('/agents/session/enable', self._enable_session_agent, methods=['POST'])
        app.add_api_route('/agents/session/disable', self._disable_session_agent, methods=['POST'])
        app.add_api_route('/agents/session', self._get_session_agents, methods=['GET'])

    # Update API key in manager
    def update_api_key(self, api_key: str):
        """Update API key in the manager"""
        if hasattr(self.manager, 'update_api_key'):
            self.manager.update_api_key(api_key)

    def _extract_agent_name_from_address(self, agent_address: str) -> str:
        """Extract agent name from agent address/URL."""
        try:
            # Try to extract from URL path or use the last part
            from urllib.parse import urlparse
            parsed = urlparse(agent_address)
            if parsed.path:
                # Get the last non-empty path component
                path_parts = [part for part in parsed.path.split('/') if part]
                if path_parts:
                    name = path_parts[-1]
                else:
                    name = parsed.netloc or agent_address
            else:
                name = parsed.netloc or agent_address
            
            # Clean up the name
            return name.replace('-', ' ').replace('_', ' ').title()
        except:
            # Fallback to using the address as-is
            return agent_address.split('/')[-1].replace('-', ' ').replace('_', ' ').title()

    async def _create_conversation(self):
        c = await self.manager.create_conversation()
        return CreateConversationResponse(result=c)

    def _transform_message_data(self, message_data: dict) -> dict:
        """Transform message data from frontend format to backend format.
        
        Frontend sends: {'root': {'kind': 'text', 'text': 'hello'}}
        Backend expects: Part objects with direct properties
        """
        if 'parts' in message_data:
            transformed_parts = []
            for part in message_data['parts']:
                if 'root' in part:
                    root = part['root']
                    if root.get('kind') == 'text':
                        # Create Part with TextPart root (matching foundry agent expectations)
                        from a2a.types import Part as A2APart, TextPart as A2ATextPart
                        transformed_parts.append(A2APart(root=A2ATextPart(text=root['text'])))
                    elif root.get('kind') == 'data':
                        # Create Part with DataPart root
                        from a2a.types import Part as A2APart, DataPart as A2ADataPart
                        transformed_parts.append(A2APart(root=A2ADataPart(data=root['data'])))
                    elif root.get('kind') == 'file':
                        # Create Part with FilePart root (matching foundry agent expectations)
                        from a2a.types import Part as A2APart, FilePart as A2AFilePart
                        file_data = root['file']
                        
                        # Extract role if present (needed for mask/base detection)
                        file_kwargs = {
                            'name': file_data.get('name', ''),
                            'uri': file_data.get('uri', ''),
                            'mimeType': file_data.get('mime_type', 'application/octet-stream')
                        }
                        
                        # Create FilePart with metadata containing role
                        file_part_kwargs = {'file': FileWithUri(**file_kwargs)}
                        if file_data.get('role'):
                            file_part_kwargs['metadata'] = {'role': file_data.get('role')}
                            print(f"🎭 [server.py] Setting metadata role='{file_data.get('role')}' for file: {file_data.get('name', 'unknown')}")
                        
                        transformed_parts.append(A2APart(root=A2AFilePart(**file_part_kwargs)))
                    else:
                        # Fallback: treat as text
                        from a2a.types import Part as A2APart, TextPart as A2ATextPart
                        transformed_parts.append(A2APart(root=A2ATextPart(text=str(root))))
                else:
                    # Part is already in correct format
                    transformed_parts.append(part)
            message_data['parts'] = transformed_parts
        return message_data

    async def _send_message(self, request: Request):
        message_data = await request.json()
        # Extract agent mode, inter-agent memory, and workflow from params if present
        # agent_mode defaults to None to allow auto-detection based on workflow presence
        agent_mode = message_data.get('params', {}).get('agentMode', None)
        enable_inter_agent_memory = message_data.get('params', {}).get('enableInterAgentMemory', False)
        workflow = message_data.get('params', {}).get('workflow')
        workflow_goal = message_data.get('params', {}).get('workflowGoal')  # Goal from workflow designer
        available_workflows = message_data.get('params', {}).get('availableWorkflows')  # List of workflow metadata for multi-workflow routing
        user_id = message_data.get('params', {}).get('userId')  # Extract userId for color lookup
        log_debug(f"_send_message: Agent Mode = {agent_mode}, Inter-Agent Memory = {enable_inter_agent_memory}, Workflow = {workflow[:50] if workflow else None}, WorkflowGoal = {workflow_goal[:50] if workflow_goal else None}, AvailableWorkflows = {len(available_workflows) if available_workflows else 0}")
        
        # DEBUG: Log the full workflow text to verify all steps are included
        if workflow:
            print(f"📋 [_send_message] FULL WORKFLOW TEXT ({len(workflow)} chars):")
            for line in workflow.split('\n'):
                print(f"    {line}")
        
        # DEBUG: Log the contextId from frontend
        frontend_context_id = message_data.get('params', {}).get('contextId')
        log_debug(f"🔍 [_send_message] Frontend sent contextId: {frontend_context_id}")
        
        # Transform the message data to handle frontend format
        transformed_params = self._transform_message_data(message_data['params'])
        
        # DEBUG: Check if contextId survived transformation
        log_debug(f"🔍 [_send_message] After transform, contextId: {transformed_params.get('contextId')}")
        
        # Add required fields if missing
        if 'messageId' not in transformed_params:
            import uuid
            transformed_params['messageId'] = str(uuid.uuid4())
        if 'role' not in transformed_params:
            from a2a.types import Role
            transformed_params['role'] = Role.user
        
        message = Message(**transformed_params)
        log_debug(f"Message created with {len(message.parts)} parts: {[type(p).__name__ for p in message.parts]}")
        message = self.manager.sanitize_message(message)
        
        # Store userId mapping for this message (for user color lookup later)
        msg_id = get_message_id(message)
        print(f"[DEBUG] _send_message: user_id={user_id}, msg_id={msg_id}")
        if user_id and msg_id:
            message_user_map[msg_id] = user_id
            print(f"[DEBUG] Stored userId mapping: {msg_id} -> {user_id}, map now has {len(message_user_map)} entries")
            log_debug(f"_send_message: Stored userId mapping: {msg_id} -> {user_id}")
        
        log_debug(f"_send_message: Processing message asynchronously for contextId: {get_context_id(message)}")
        
        # Process message asynchronously (original pattern)
        if isinstance(self.manager, ADKHostManager):
            loop = asyncio.get_event_loop()
            t = threading.Thread(
                target=lambda: cast(ADKHostManager, self.manager).process_message_threadsafe(message, loop)
            )
        else:
            t = threading.Thread(
                target=lambda: asyncio.run_coroutine_threadsafe(self.manager.process_message(message, agent_mode, enable_inter_agent_memory, workflow, workflow_goal, available_workflows), main_loop)
            )
        t.start()
        
        log_debug("_send_message: Started background processing thread")
        
        # Return immediately with message metadata (frontend expects this)
        return SendMessageResponse(
            result=MessageInfo(
                message_id=get_message_id(message),
                context_id=get_context_id(message, ''),
            )
        )

    async def _list_messages(self, request: Request):
        message_data = await request.json()
        conversation_id = message_data['params']
        conversation = self.manager.get_conversation(conversation_id)
        if conversation:
            return ListMessageResponse(
                result=self.cache_content(conversation.messages)
            )
        return ListMessageResponse(result=[])

    def cache_content(self, messages: list[Message]):
        """Process messages for API response.
        
        For FileParts:
        - If file has a valid HTTP/HTTPS URI (blob storage), preserve it as-is
        - If file has embedded bytes, cache them and replace with local reference
        
        This ensures blob storage URIs (from Image Generator, etc.) are preserved
        and images persist across page refreshes.
        """
        rval = []
        for m in messages:
            message_id = get_message_id(m)
            if not message_id:
                rval.append(m)
                continue
            new_parts: list[Part] = []
            for i, p in enumerate(m.parts):
                part = p.root
                if part.kind != 'file':
                    new_parts.append(p)
                    continue
                
                # Check if this FilePart already has a valid HTTP/HTTPS URI (blob storage)
                # If so, preserve it - don't replace with local cache reference
                file_obj = part.file
                if hasattr(file_obj, 'uri') and file_obj.uri:
                    uri_str = str(file_obj.uri)
                    if uri_str.startswith(('http://', 'https://')):
                        # Keep the original blob storage URI
                        log_debug(f"📸 Preserving blob URI for file: {uri_str[:80]}...")
                        new_parts.append(p)
                        continue
                
                # Only cache files with embedded bytes (FileWithBytes)
                if not hasattr(file_obj, 'bytes') or not file_obj.bytes:
                    # No bytes and no valid URI - skip this part
                    log_debug(f"⚠️ FilePart has no bytes and no valid URI, skipping")
                    new_parts.append(p)
                    continue
                
                message_part_id = f'{message_id}:{i}'
                if message_part_id in self._message_to_cache:
                    cache_id = self._message_to_cache[message_part_id]
                else:
                    cache_id = str(uuid.uuid4())
                    self._message_to_cache[message_part_id] = cache_id
                # Replace embedded bytes with a local url reference
                new_parts.append(
                    Part(
                        root=FilePart(
                            file=FileWithUri(
                                mimeType=part.file.mimeType,
                                uri=f'/message/file/{cache_id}',
                            )
                        )
                    )
                )
                if cache_id not in self._file_cache:
                    self._file_cache[cache_id] = part
            m.parts = new_parts
            rval.append(m)
        return rval

    async def _pending_messages(self):
        return PendingMessageResponse(
            result=self.manager.get_pending_messages()
        )

    async def _list_conversation(self, request: Request):
        """List conversations, optionally filtered by session ID.
        
        Request body can include:
        - sessionId: Filter conversations for this session (tenant isolation)
        
        Combines in-memory conversations with database persisted conversations.
        """
        try:
            message_data = await request.json()
            session_id = message_data.get('params', {}).get('sessionId') if isinstance(message_data.get('params'), dict) else None
            
            # If sessionId is provided, load conversations from database for that session
            if session_id:
                # First, get any conversations from database for this session
                db_conversations = chat_history_service.list_conversations(session_id)
                log_debug(f"[_list_conversation] Loaded {len(db_conversations)} conversations from database for session {session_id}")
                
                # Convert database conversations to Conversation objects
                filtered_conversations = []
                seen_conv_ids = set()
                
                for db_conv in db_conversations:
                    full_conv_id = db_conv.get("conversation_id", "")
                    # Strip session prefix for frontend display
                    conv_id_only = full_conv_id.split('::', 1)[1] if '::' in full_conv_id else full_conv_id
                    
                    if conv_id_only in seen_conv_ids:
                        continue
                    seen_conv_ids.add(conv_id_only)
                    
                    # Load messages for this conversation
                    messages = chat_history_service.get_messages(full_conv_id)
                    
                    # Convert to Message objects
                    message_objects = []
                    for msg_data in messages:
                        try:
                            parts = []
                            for part_data in msg_data.get("parts", []):
                                if isinstance(part_data, dict):
                                    kind = part_data.get("kind") or part_data.get("root", {}).get("kind")
                                    if kind == "text":
                                        text = part_data.get("text") or part_data.get("root", {}).get("text", "")
                                        parts.append(Part(root=TextPart(text=text)))
                                    elif kind == "data":
                                        data = part_data.get("data") or part_data.get("root", {}).get("data", {})
                                        parts.append(Part(root=DataPart(data=data)))
                                    elif kind == "file":
                                        file_data = part_data.get("file") or part_data.get("root", {}).get("file", {})
                                        fp_kwargs = {"file": FileWithUri(
                                            name=file_data.get("name", ""),
                                            uri=file_data.get("uri", ""),
                                            mimeType=file_data.get("mimeType", "application/octet-stream")
                                        )}
                                        # Preserve metadata (e.g. role='mask') for proper rendering
                                        part_meta = part_data.get("metadata") or part_data.get("root", {}).get("metadata")
                                        if part_meta:
                                            fp_kwargs["metadata"] = part_meta
                                        parts.append(Part(root=FilePart(**fp_kwargs)))

                            if parts:
                                msg_kwargs = {
                                    "messageId": msg_data.get("messageId") or msg_data.get("message_id", str(uuid.uuid4())),
                                    "role": Role.user if msg_data.get("role") == "user" else Role.agent,
                                    "parts": parts,
                                    "contextId": msg_data.get("context_id", full_conv_id),
                                }
                                # Preserve message-level metadata (agentName, workflow_plan, etc.)
                                if msg_data.get("metadata"):
                                    msg_kwargs["metadata"] = msg_data["metadata"]
                                message_objects.append(Message(**msg_kwargs))
                        except Exception as e:
                            log_debug(f"Error converting message: {e}")
                            continue
                    
                    conv = Conversation(
                        conversation_id=conv_id_only,
                        name=db_conv.get("name", ""),
                        is_active=db_conv.get("is_active", True),
                        task_ids=db_conv.get("task_ids", []),
                        messages=message_objects
                    )
                    filtered_conversations.append(conv)
                
                # Also include any in-memory conversations for this session not in database
                for conv in self.manager.conversations:
                    if conv.conversation_id.startswith(f"{session_id}::"):
                        conv_id_only = conv.conversation_id.split('::', 1)[1]
                        if conv_id_only not in seen_conv_ids:
                            conv_copy = Conversation(
                                conversation_id=conv_id_only,
                                name=conv.name,
                                is_active=conv.is_active,
                                task_ids=conv.task_ids,
                                messages=conv.messages
                            )
                            filtered_conversations.append(conv_copy)
                
                log_debug(f"[_list_conversation] Returning {len(filtered_conversations)} conversations for session {session_id}")
                return ListConversationResponse(result=filtered_conversations, message_user_map=message_user_map)
            
            # No session filter - return all in-memory conversations
            return ListConversationResponse(result=self.manager.conversations, message_user_map=message_user_map)
        except Exception as e:
            log_debug(f"Error in _list_conversation: {e}")
            return ListConversationResponse(result=self.manager.conversations, message_user_map=message_user_map)

    async def _delete_conversation(self, request: Request):
        """Delete a conversation by ID.
        
        Since conversations are stored with sessionId::conversationId format,
        but frontend sends just conversationId (stripped during list), 
        we need to reconstruct the full ID or match on the conversationId part.
        """
        try:
            message_data = await request.json()
            params = message_data.get('params', {})
            conversation_id = params.get('conversationId')
            session_id = params.get('sessionId')
            
            if not conversation_id:
                return {"success": False, "error": "conversationId required"}
            
            log_debug(f"🗑️  Delete request - conversationId: {conversation_id}, sessionId: {session_id}")
            log_debug(f"🗑️  Conversations in memory: {[c.conversation_id for c in self.manager.conversations]}")
            
            # Reconstruct full contextId if session provided
            full_id = f"{session_id}::{conversation_id}" if session_id else None
            
            # Find the conversation to delete
            conversations = self.manager.conversations
            original_length = len(conversations)
            
            # Filter out the conversation - modify the private _conversations list directly
            filtered = [
                c for c in conversations
                if not (
                    c.conversation_id == conversation_id or  # Match short ID
                    c.conversation_id == full_id or          # Match full ID
                    c.conversation_id.endswith(f"::{conversation_id}")  # Match if ends with ::conversationId
                )
            ]
            
            # Update the internal list (access private variable since property has no setter)
            self.manager._conversations = filtered
            
            # Also delete from database
            try:
                # Try both the short ID and full ID
                chat_history_service.delete_conversation(conversation_id)
                if full_id:
                    chat_history_service.delete_conversation(full_id)
            except Exception as db_error:
                log_debug(f"Error deleting from database: {db_error}")
            
            if len(filtered) == original_length:
                log_debug(f"⚠️  Conversation not found: {conversation_id}")
                return {"success": False, "error": "Conversation not found"}
            
            log_debug(f"✅  Deleted! Remaining: {[c.conversation_id for c in self.manager.conversations]}")
            return {"success": True}
        except Exception as e:
            log_debug(f"❌  Error: {e}")
            return {"success": False, "error": str(e)}

    async def _update_conversation_title(self, request: Request):
        """Update a conversation's title/name."""
        try:
            message_data = await request.json()
            params = message_data.get('params', {})
            conversation_id = params.get('conversationId')
            title = params.get('title')
            
            if not conversation_id:
                return {"success": False, "error": "conversationId required"}
            if not title:
                return {"success": False, "error": "title required"}
            
            log_debug(f"📝  Update title request - conversationId: {conversation_id}, title: {title}")
            
            # Update in database
            try:
                chat_history_service.update_conversation_name(conversation_id, title)
                log_debug(f"✅  Title updated in database")
            except Exception as db_error:
                log_debug(f"Error updating title in database: {db_error}")
                return {"success": False, "error": str(db_error)}
            
            # Also update in memory if conversation exists
            for conv in self.manager.conversations:
                if conv.conversation_id == conversation_id or conv.conversation_id.endswith(f"::{conversation_id}"):
                    conv.name = title
                    log_debug(f"✅  Title updated in memory")
                    break
            
            return {"success": True}
        except Exception as e:
            log_debug(f"❌  Error updating title: {e}")
            return {"success": False, "error": str(e)}

    async def _delete_all_conversations(self, request: Request):
        """Delete all conversations for a session.
        
        This clears both in-memory conversations and database records.
        """
        try:
            message_data = await request.json()
            params = message_data.get('params', {})
            session_id = params.get('sessionId')
            
            if not session_id:
                return {"success": False, "error": "sessionId required"}
            
            log_debug(f"🗑️  Delete ALL conversations request for session: {session_id}")
            
            # Clear from in-memory manager
            conversations = self.manager.conversations
            original_length = len(conversations)
            
            # Filter out all conversations for this session
            filtered = [
                c for c in conversations
                if not (
                    c.conversation_id.startswith(f"{session_id}::") or
                    c.conversation_id == session_id
                )
            ]
            
            # Update the internal list
            self.manager._conversations = filtered
            
            deleted_memory_count = original_length - len(filtered)
            log_debug(f"🗑️  Deleted {deleted_memory_count} conversations from memory")
            
            # Delete from database
            try:
                chat_history_service.delete_all_conversations(session_id)
            except Exception as db_error:
                log_debug(f"Error deleting all from database: {db_error}")
            
            log_debug(f"✅  Deleted all conversations for session {session_id}")
            return {"success": True, "deleted_count": deleted_memory_count}
        except Exception as e:
            log_debug(f"❌  Error deleting all conversations: {e}")
            return {"success": False, "error": str(e)}

    def _get_events(self):
        return GetEventResponse(result=self.manager.events)

    def _list_tasks(self):
        return ListTaskResponse(result=self.manager.tasks)

    async def _register_agent(self, request: Request):
        message_data = await request.json()
        url = message_data['params']
        self.manager.register_agent(url)
        return RegisterAgentResponse()

    async def _self_register_agent(self, request: Request):
        """Handle self-registration requests from remote agents."""
        try:
            message_data = await request.json()
            
            # Extract agent address from request
            agent_address = message_data.get('agent_address') or message_data.get('url')
            agent_card_data = message_data.get('agent_card')
            
            log_debug(f"🤝 Self-registration request received:")
            log_debug(f"  - Agent address: {agent_address}")
            log_debug(f"  - Has agent card: {agent_card_data is not None}")
            
            if not agent_address:
                log_debug("❌ No agent address provided in self-registration request")
                return {"success": False, "error": "agent_address required"}
            
            # Handle self-registration based on manager type
            if isinstance(self.manager, FoundryHostManager):
                # Parse agent card if provided
                agent_card = None
                if agent_card_data:
                    from a2a.types import AgentCard
                    agent_card = AgentCard(**agent_card_data)
                
                # Use the manager's self-registration handler
                success = await self.manager.handle_self_registration(agent_address, agent_card)
                
                if success:
                    log_debug(f"✅ Self-registration successful for: {agent_address}")
                    
                    # Trigger immediate WebSocket sync to update UI in real-time
                    try:
                        import os
                        import httpx
                        websocket_url = os.environ.get("WEBSOCKET_SERVER_URL", "http://localhost:8080")
                        sync_url = f"{websocket_url}/agents/sync"
                        log_debug(f"🔔 Triggering immediate sync via HTTP POST to: {sync_url}")
                        
                        async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
                            response = await client.post(sync_url)
                            if response.status_code == 200:
                                log_debug("✅ Immediate agent registry sync triggered successfully")
                            else:
                                log_debug(f"⚠️ Sync trigger returned status {response.status_code}")
                    except Exception as sync_error:
                        log_debug(f"⚠️ Failed to trigger immediate sync: {sync_error}")
                    
                    # Stream agent self-registration over WebSocket
                    log_debug("🌊 Attempting to stream agent self-registration to WebSocket...")
                    try:
                        streamer = await get_websocket_streamer()
                        if streamer:
                            capabilities = agent_card.capabilities if agent_card else {}
                            capabilities = serialize_capabilities(capabilities)

                            agent_info = {
                                "name": agent_card.name if agent_card else self._extract_agent_name_from_address(agent_address),
                                "type": "generic",  # Hardcoded since AgentCard doesn't have type attribute
                                "capabilities": capabilities,
                                "endpoint": agent_address,
                                "metadata": agent_card_data if agent_card_data else {}
                            }
                            log_debug(f"🌊 Agent info for WebSocket streaming: {agent_info}")
                            stream_success = await streamer.stream_agent_self_registered(agent_info)
                            if stream_success:
                                log_debug("✅ Agent self-registration event streamed over WebSocket successfully")
                            else:
                                log_debug("⚠️ WebSocket streaming not available - agent registration will proceed without streaming")
                        else:
                            log_debug("⚠️ WebSocket streamer not configured - agent registration will proceed without streaming")
                    except Exception as e:
                        log_debug(f"⚠️ WebSocket streaming error (non-blocking): {e}")
                        # Streaming errors should not block agent registration
                    
                    # Trigger immediate WebSocket sync to update UI for all clients
                    try:
                        await trigger_websocket_agent_refresh()
                    except Exception as sync_error:
                        log_debug(f"⚠️ Failed to trigger immediate sync: {sync_error}")
                    
                    return {"success": True, "message": f"Agent {agent_address} registered successfully"}
                else:
                    log_debug(f"❌ Self-registration failed for: {agent_address}")
                    return {"success": False, "error": "Registration failed"}
            else:
                # Fallback to regular registration for other manager types
                log_debug(f"ℹ️ Using fallback registration for manager type: {type(self.manager).__name__}")
                self.manager.register_agent(agent_address)
                
                # Stream agent registration over WebSocket
                print(f"[DEBUG] 🌊 Attempting to stream agent registration to WebSocket (fallback)...")
                try:
                    streamer = await get_websocket_streamer()
                    if streamer:
                        stream_success = await streamer.stream_agent_registered(agent_address)
                        if stream_success:
                            print(f"[DEBUG] ✅ Agent registration event streamed over WebSocket successfully (fallback)")
                        else:
                            print(f"[DEBUG] ⚠️ WebSocket streaming not available - agent registration will proceed without streaming (fallback)")
                    else:
                        print(f"[DEBUG] ⚠️ WebSocket streamer not configured - agent registration will proceed without streaming (fallback)")
                except Exception as e:
                    print(f"[DEBUG] ⚠️ WebSocket streaming error (non-blocking, fallback): {e}")
                    # Streaming errors should not block agent registration
                
                # Trigger immediate WebSocket sync to update UI for all clients
                try:
                    await trigger_websocket_agent_refresh()
                except Exception as sync_error:
                    print(f"[DEBUG] ⚠️ Failed to trigger immediate sync (fallback): {sync_error}")
                
                return {"success": True, "message": f"Agent {agent_address} registered successfully (fallback)"}
                
                return {"success": True, "message": f"Agent {agent_address} registered successfully (fallback)"}
                
        except Exception as e:
            print(f"[DEBUG] ❌ Self-registration error: {e}")
            import traceback
            print(f"[DEBUG] ❌ Self-registration traceback: {traceback.format_exc()}")
            return {"success": False, "error": str(e)}

    async def _unregister_agent(self, request: Request):
        """Handle agent unregistration requests."""
        try:
            message_data = await request.json()
            agent_name = message_data.get('agentName')
            
            print(f"[DEBUG] 🗑️ Unregister agent request: {agent_name}")
            
            if not agent_name:
                print(f"[DEBUG] ❌ No agent name provided in unregister request")
                return {"success": False, "error": "agentName required"}
            
            # Handle unregistration based on manager type
            if isinstance(self.manager, FoundryHostManager):
                success = await self.manager.unregister_agent(agent_name)
                
                if success:
                    print(f"[DEBUG] ✅ Agent unregistered successfully: {agent_name}")
                    
                    # Trigger immediate WebSocket sync to update UI
                    try:
                        await trigger_websocket_agent_refresh()
                    except Exception as sync_error:
                        print(f"[DEBUG] ⚠️ Failed to trigger immediate sync: {sync_error}")
                    
                    return {"success": True, "message": f"Agent {agent_name} unregistered successfully"}
                else:
                    print(f"[DEBUG] ❌ Agent unregistration failed: {agent_name}")
                    return {"success": False, "error": "Agent not found or unregistration failed"}
            else:
                print(f"[DEBUG] ❌ Unregistration not supported for manager type: {type(self.manager).__name__}")
                return {"success": False, "error": "Unregistration not supported for this manager type"}
                
        except Exception as e:
            print(f"[DEBUG] ❌ Unregister agent error: {e}")
            import traceback
            print(f"[DEBUG] ❌ Unregister agent traceback: {traceback.format_exc()}")
            return {"success": False, "error": str(e)}

    async def _register_agent_by_address(self, request: Request):
        """Register a remote agent by its address/URL."""
        try:
            message_data = await request.json()
            agent_address = message_data.get('address')
            
            print(f"[DEBUG] 🔗 Register agent by address request: {agent_address}")
            
            if not agent_address:
                return {"success": False, "error": "Agent address is required"}
            
            # Validate URL format
            try:
                from urllib.parse import urlparse
                parsed = urlparse(agent_address)
                if not parsed.scheme or not parsed.netloc:
                    return {"success": False, "error": "Invalid URL format"}
            except Exception:
                return {"success": False, "error": "Invalid URL format"}
            
            # Handle registration based on manager type
            if isinstance(self.manager, FoundryHostManager):
                print(f"[DEBUG] 🚀 Using FoundryHostManager for agent registration")
                
                # Ensure the host agent is initialized before use
                await self.manager.ensure_host_agent_initialized()
                
                # Use the existing register_remote_agent method from foundry_agent_a2a.py
                success = await self.manager._host_agent.register_remote_agent(agent_address)
                
                if success:
                    print(f"[DEBUG] ✅ Agent registration successful: {agent_address}")

                    # Persist to database registry so agent survives restarts
                    try:
                        card = self.manager._host_agent.cards.get(
                            next((name for name in self.manager._host_agent.cards
                                  if agent_address.rstrip('/') in getattr(self.manager._host_agent.cards[name], 'url', '')),
                                 None)
                        )
                        if card:
                            registry = get_registry()
                            agent_dict = {
                                "name": card.name,
                                "description": getattr(card, 'description', ''),
                                "version": getattr(card, 'version', '1.0.0'),
                                "local_url": agent_address.rstrip('/') + '/',
                                "production_url": agent_address.rstrip('/') + '/',
                                "defaultInputModes": getattr(card, 'defaultInputModes', ['text']),
                                "defaultOutputModes": getattr(card, 'defaultOutputModes', ['text']),
                                "capabilities": {"streaming": getattr(card.capabilities, 'streaming', False)} if hasattr(card, 'capabilities') and card.capabilities else {},
                                "skills": [{"id": getattr(s, 'id', ''), "name": getattr(s, 'name', ''), "description": getattr(s, 'description', ''), "examples": getattr(s, 'examples', []), "tags": getattr(s, 'tags', [])} for s in card.skills] if hasattr(card, 'skills') and card.skills else [],
                            }
                            registry.update_or_add_agent(agent_dict)
                            print(f"[DEBUG] ✅ Agent persisted to database registry: {card.name}")
                    except Exception as db_error:
                        print(f"[DEBUG] ⚠️ Failed to persist agent to database: {db_error}")

                    # Trigger immediate WebSocket sync to update UI in real-time
                    try:
                        import os
                        import httpx
                        websocket_url = os.environ.get("WEBSOCKET_SERVER_URL", "http://localhost:8080")
                        sync_url = f"{websocket_url}/agents/sync"
                        print(f"[DEBUG] 🔔 Triggering immediate sync via HTTP POST to: {sync_url}")

                        async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
                            response = await client.post(sync_url)
                            if response.status_code == 200:
                                print(f"[DEBUG] ✅ Immediate agent registry sync triggered successfully")
                            else:
                                print(f"[DEBUG] ⚠️ Sync trigger returned status {response.status_code}")
                    except Exception as sync_error:
                        print(f"[DEBUG] ⚠️ Failed to trigger immediate sync: {sync_error}")

                    return {"success": True, "message": f"Agent at {agent_address} registered successfully"}
                else:
                    print(f"[DEBUG] ❌ Agent registration failed: {agent_address}")
                    return {"success": False, "error": f"Failed to register agent at {agent_address}"}
            else:
                # Fallback for other manager types
                print(f"[DEBUG] ℹ️ Using fallback registration for manager type: {type(self.manager).__name__}")
                self.manager.register_agent(agent_address)
                return {"success": True, "message": f"Agent at {agent_address} registered successfully"}
                
        except Exception as e:
            print(f"[DEBUG] ❌ Register agent by address error: {e}")
            import traceback
            print(f"[DEBUG] ❌ Register agent by address traceback: {traceback.format_exc()}")
            return {"success": False, "error": f"Registration failed: {str(e)}"}

    async def _list_agents(self):
        return ListAgentResponse(result=self.manager.agents)

    async def _check_agent_health(self, agent_url: str) -> bool:
        """Simple health check for remote agents with caching."""
        if not agent_url:
            return False
        
        current_time = time.time()
        
        # Check cache first (cache for 30 seconds to reduce load and prevent flapping)
        if agent_url in self._health_cache:
            status, timestamp = self._health_cache[agent_url]
            if current_time - timestamp < 30.0:  # Increased from 10 to 30 seconds to reduce flapping
                log_debug(f"Using cached health status for {agent_url}: {'✓' if status else '✗'}")
                return status
        
        try:
            # Parse the URL to construct health endpoint
            parsed = urlparse(agent_url)
            if not parsed.hostname:
                self._health_cache[agent_url] = (False, current_time)
                return False
            
            # Construct health check URL - preserve the path and add /health
            base_url = agent_url.rstrip('/')  # Remove trailing slash
            health_url = f"{base_url}/health"
            
            # Health check with shorter timeout for faster UI responsiveness
            timeout_value = 3.0  # Reduced from 8.0 to 3.0 for faster catalog loading
            log_debug(f"Health check timeout set to: {timeout_value}s for {health_url}")
            async with httpx.AsyncClient(timeout=timeout_value) as client:  # More generous timeout for network latency
                response = await client.get(health_url)
                is_healthy = response.status_code == 200
                log_debug(f"Health check {health_url}: {'✓ ONLINE' if is_healthy else '✗ OFFLINE'} (status: {response.status_code})")
                self._health_cache[agent_url] = (is_healthy, current_time)
                return is_healthy
        except Exception as e:
            error_msg = str(e)
            log_debug(f"Health check failed for {agent_url}: {error_msg}")
            log_debug(f"Exception type: {type(e).__name__}")
            # Cache failure result
            self._health_cache[agent_url] = (False, current_time)
            return False

    async def _get_agents(self):
        """Get current agent registry in a simple format for WebSocket sync.
        
        Reads agents from the persistent registry file and performs health checks
        on each agent URL to determine online/offline status.
        """
        try:
            log_debug("Starting agent registry sync with health checks...")
            
            # Use module-level imported get_registry (same as _get_catalog uses)
            registry = get_registry()
            registry_agents = registry.get_all_agents()
            
            # First, collect all agent URLs for concurrent health checks
            agent_urls = [agent.get('url') for agent in registry_agents if agent.get('name')]
            
            # Do concurrent health checks for all agents at once
            health_tasks = [self._check_agent_health(url) for url in agent_urls]
            health_results = await asyncio.gather(*health_tasks, return_exceptions=True)
            
            # Convert health check results to a mapping
            health_map = {}
            for i, url in enumerate(agent_urls):
                if i < len(health_results) and not isinstance(health_results[i], Exception):
                    health_map[url] = health_results[i]
                else:
                    health_map[url] = False  # Default to offline on error
            
            # Convert to detailed format for UI
            agent_list = []
            for agent in registry_agents:
                agent_name = agent.get('name')
                if agent_name:
                    agent_url = agent.get('url')
                    agent_status = health_map.get(agent_url, False)
                    
                    # Get capabilities from dict (handle legacy list format)
                    raw_caps = agent.get('capabilities')
                    if isinstance(raw_caps, dict):
                        caps = raw_caps
                    else:
                        caps = {}  # Default to empty dict if capabilities is a list or None
                    
                    agent_data = {
                        'name': agent_name,
                        'description': agent.get('description', ''),
                        'url': agent_url,
                        'version': agent.get('version', ''),
                        'iconUrl': agent.get('iconUrl'),
                        'provider': agent.get('provider'),
                        'documentationUrl': agent.get('documentationUrl'),
                        'capabilities': {
                            'streaming': caps.get('streaming', False),
                            'pushNotifications': caps.get('pushNotifications', False),
                            'stateTransitionHistory': caps.get('stateTransitionHistory', False),
                            'extensions': caps.get('extensions', [])
                        },
                        'skills': agent.get('skills', []),
                        'defaultInputModes': agent.get('defaultInputModes', []),
                        'defaultOutputModes': agent.get('defaultOutputModes', []),
                        'type': 'remote',  # Mark as remote agent
                        'status': 'online' if agent_status else 'offline'
                    }
                    agent_list.append(agent_data)
            
            log_debug(f"Completed agent registry sync: {len(agent_list)} agents processed")
            return {
                "success": True,
                "agents": agent_list,
                "count": len(agent_list)
            }
        except Exception as e:
            import traceback
            print(f"[DEBUG] Error in agent registry sync: {str(e)}")
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
                "agents": [],
                "count": 0
            }

    def _files(self, file_id):
        if file_id not in self._file_cache:
            raise Exception('file not found')
        part = self._file_cache[file_id]
        if 'image' in part.file.mimeType:
            return Response(
                content=base64.b64decode(part.file.bytes),
                media_type=part.file.mimeType,
            )
        return Response(content=part.file.bytes, media_type=part.file.mimeType)

    async def _update_api_key(self, request: Request):
        """Update the API key"""
        try:
            data = await request.json()
            api_key = data.get('api_key', '')

            if api_key:
                # Update in the manager
                self.update_api_key(api_key)
                return {'status': 'success'}
            return {'status': 'error', 'message': 'No API key provided'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    async def _get_root_instruction(self):
        """Get the current root instruction"""
        try:
            if hasattr(self.manager, 'get_current_root_instruction'):
                instruction = await self.manager.get_current_root_instruction()
                return {
                    'status': 'success',
                    'instruction': instruction
                }
            else:
                return {
                    'status': 'error',
                    'message': 'Root instruction management not supported by current manager'
                }
        except Exception as e:
            return {
                'status': 'error',
                'message': str(e)
            }

    async def _update_root_instruction(self, request: Request):
        """Update the root instruction"""
        try:
            data = await request.json()
            new_instruction = data.get('instruction', '')

            if not new_instruction.strip():
                return {
                    'status': 'error',
                    'message': 'No instruction provided or instruction is empty'
                }

            if hasattr(self.manager, 'update_root_instruction'):
                success = await self.manager.update_root_instruction(new_instruction)
                if success:
                    return {
                        'status': 'success',
                        'message': 'Root instruction updated successfully'
                    }
                else:
                    return {
                        'status': 'error',
                        'message': 'Failed to update root instruction'
                    }
            else:
                return {
                    'status': 'error',
                    'message': 'Root instruction management not supported by current manager'
                }
        except Exception as e:
            return {
                'status': 'error',
                'message': str(e)
            }

    async def _reset_root_instruction(self):
        """Reset to default root instruction"""
        try:
            if hasattr(self.manager, 'reset_root_instruction'):
                success = await self.manager.reset_root_instruction()
                if success:
                    return {
                        'status': 'success',
                        'message': 'Root instruction reset to default successfully'
                    }
                else:
                    return {
                        'status': 'error',
                        'message': 'Failed to reset root instruction'
                    }
            else:
                return {
                    'status': 'error',
                    'message': 'Root instruction management not supported by current manager'
                }
        except Exception as e:
            return {
                'status': 'error',
                'message': str(e)
            }

    # ==================== WORKFLOW CONTROL ENDPOINTS ====================

    async def _cancel_workflow(self, request: Request):
        """Cancel a running workflow. Called by the WebSocket server via HTTP."""
        data = await request.json()
        context_id = data.get("context_id", "")

        if not context_id:
            return {"status": "error", "message": "No context_id provided"}

        if hasattr(self.manager, '_host_agent') and self.manager._host_agent:
            result = await self.manager._host_agent.cancel_workflow(
                context_id=context_id,
                reason=data.get("reason", "Cancelled by user")
            )
            return result

        return {"status": "error", "message": "Orchestrator not available"}

    async def _interrupt_workflow(self, request: Request):
        """Interrupt/redirect a running workflow. Called by the WebSocket server via HTTP."""
        data = await request.json()
        context_id = data.get("context_id", "")
        instruction = data.get("instruction", "")

        if not context_id or not instruction:
            return {"status": "error", "message": "Missing context_id or instruction"}

        if hasattr(self.manager, '_host_agent') and self.manager._host_agent:
            result = await self.manager._host_agent.interrupt_workflow(
                context_id=context_id,
                instruction=instruction
            )
            return result

        return {"status": "error", "message": "Orchestrator not available"}

    # ==================== SESSION AGENT ENDPOINTS ====================

    async def _get_catalog(self):
        """Get all agents from the catalog."""
        registry = get_registry()
        agents = registry.get_all_agents()
        return {'status': 'success', 'agents': agents}

    async def _enable_session_agent(self, request: Request):
        """Enable an agent for a session."""
        body = await request.json()
        session_id = body.get('session_id')
        agent = body.get('agent')
        
        print(f"🟢 [API /agents/session/enable] session_id='{session_id}', agent={agent.get('name') if agent else None}")
        
        if not session_id or not agent:
            return {'status': 'error', 'message': 'session_id and agent required'}
        
        session_registry = get_session_registry()
        session_registry.enable_agent(session_id, agent)
        
        # Broadcast session_agent_enabled event via WebSocket
        try:
            websocket_url = os.environ.get("WEBSOCKET_SERVER_URL", "http://localhost:8080")
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{websocket_url}/events",
                    json={
                        "eventType": "session_agent_enabled",
                        "contextId": session_id,
                        "agent": agent
                    },
                    timeout=5.0
                )
                log_debug(f"🔔 Broadcasted session_agent_enabled for {agent.get('name')}")
        except Exception as e:
            log_debug(f"⚠️ Failed to broadcast session_agent_enabled: {e}")
        
        return {'status': 'success', 'agent': agent}

    async def _disable_session_agent(self, request: Request):
        """Disable an agent for a session."""
        body = await request.json()
        session_id = body.get('session_id')
        agent_url = body.get('agent_url')
        
        if not session_id or not agent_url:
            return {'status': 'error', 'message': 'session_id and agent_url required'}
        
        session_registry = get_session_registry()
        removed = session_registry.disable_agent(session_id, agent_url)
        
        # Broadcast session_agent_disabled event via WebSocket
        if removed:
            try:
                websocket_url = os.environ.get("WEBSOCKET_SERVER_URL", "http://localhost:8080")
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"{websocket_url}/events",
                        json={
                            "eventType": "session_agent_disabled",
                            "contextId": session_id,
                            "agent_url": agent_url
                        },
                        timeout=5.0
                    )
                    log_debug(f"🔔 Broadcasted session_agent_disabled for {agent_url}")
            except Exception as e:
                log_debug(f"⚠️ Failed to broadcast session_agent_disabled: {e}")
        
        return {'status': 'success', 'removed': removed}

    async def _get_session_agents(self, request: Request):
        """Get all agents enabled for a session."""
        session_id = request.query_params.get('session_id')
        
        if not session_id:
            return {'status': 'error', 'message': 'session_id required'}
        
        session_registry = get_session_registry()
        agents = session_registry.get_session_agents(session_id)
        return {'status': 'success', 'agents': agents}
