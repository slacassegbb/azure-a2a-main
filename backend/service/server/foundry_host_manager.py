import uuid
import asyncio
import sys
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
import httpx
import json

# Ensure backend root (which contains hosts and utils) is importable
BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from log_config import log_debug, log_info, log_success, log_error

from a2a.types import AgentCard, Message, Task, TextPart, DataPart, TaskStatus, TaskState, FilePart, FileWithUri, FileWithBytes, Part
from hosts.multiagent.foundry_agent_a2a import FoundryHostAgent2
from service.server.application_manager import ApplicationManager
from service.types import Conversation, Event
from utils.agent_card import get_agent_card
from utils.file_parts import extract_uri, convert_artifact_dict_to_file_part, create_file_part
from service.agent_registry import get_session_registry

# Tenant separator used in contextId format: sessionId::conversationId
TENANT_SEPARATOR = '::'

def parse_session_from_context(context_id: str) -> str:
    """Extract session_id from contextId (format: sessionId::conversationId)"""
    if context_id and TENANT_SEPARATOR in context_id:
        return context_id.split(TENANT_SEPARATOR, 1)[0]
    return ''


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
        # Final fallback using getattr
        return getattr(obj, 'contextId', getattr(obj, 'context_id', default or ''))
    except Exception:
        return default or ''


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
        # Final fallback using getattr
        return getattr(obj, 'messageId', getattr(obj, 'message_id', default or str(uuid.uuid4())))
    except Exception:
        return default or str(uuid.uuid4())


class FoundryHostManager(ApplicationManager):
    def __init__(self, http_client: httpx.AsyncClient, *args, **kwargs):
        log_debug("FoundryHostManager __init__ called")
        self._conversations: List[Conversation] = []
        self._messages: List[Message] = []
        self._tasks: List[Task] = []
        self._events: List[Event] = []
        self._pending_message_ids: List[str] = []
        self._agents: List[AgentCard] = []
        
        # Store initialization parameters
        self._http_client = http_client
        self._host_agent = None
        self._host_agent_initialized = False
        
        # Note: File deduplication is now handled by websocket_streamer per-conversation tracking
        # Removed self._emitted_file_uris to avoid duplicate deduplication systems
        
        self._context_to_conversation: Dict[str, str] = {}
        self._pending_artifacts: Dict[str, List[Dict[str, Any]]] = {}
        self.user_id = 'test_user'
        self.app_name = 'A2A'
        self._task_map: Dict[str, str] = {}
        self._next_id: Dict[str, str] = {}
        
        # Initialize the agent immediately at startup instead of lazy loading
        log_debug("Initializing Foundry agent at startup...")
        try:
            # Create agent immediately at startup - no lazy loading
            self._host_agent = FoundryHostAgent2([], self._http_client, create_agent_at_startup=True)
            # Set the host manager reference for UI integration
            self._host_agent.set_host_manager(self)
            self._host_agent_initialized = True
            log_debug("Foundry agent initialized successfully at startup!")
        except Exception as e:
            log_debug(f"Failed to initialize Foundry agent at startup: {e}")
            # Don't raise to prevent backend from crashing
            self._host_agent_initialized = False

    def _ensure_host_agent_initialized(self):
        """Ensure agent is initialized - should already be done at startup."""
        if not self._host_agent_initialized:
            log_debug("Agent not initialized at startup, creating now...")
            try:
                self._host_agent = FoundryHostAgent2([], self._http_client, create_agent_at_startup=True)
                # Set the host manager reference for UI integration
                self._host_agent.set_host_manager(self)
                self._host_agent_initialized = True
                log_debug("Foundry agent initialized successfully (fallback)")
            except Exception as e:
                log_debug(f"Failed to initialize Foundry agent: {e}")
                raise

    async def ensure_host_agent_initialized(self):
        """Ensure the host agent is initialized before use."""
        if not self._host_agent_initialized:
            self._ensure_host_agent_initialized()

    async def create_conversation(self) -> Conversation:
        conversation_id = str(uuid.uuid4())
        c = Conversation(conversation_id=conversation_id, is_active=True)
        self._conversations.append(c)
        return c

    def foundry_content_to_message(self, resp, context_id, task_id=None):
        log_debug(f"foundry_content_to_message called with resp type: {type(resp)}")
        log_debug(f"Response content: {resp}")
        
        parts = []
        
        # Handle FilePart directly (preferred format for file artifacts)
        if isinstance(resp, FilePart):
            file_obj = getattr(resp, 'file', None)
            uri = getattr(file_obj, 'uri', None) if file_obj else None
            log_debug(f"Processing as direct FilePart - uri: {uri[:80] if uri else 'none'}...")
            parts.append(Part(root=resp))
            return Message(
                role='agent',
                parts=parts,
                contextId=context_id,
                taskId=task_id,
                messageId=str(uuid.uuid4()),
            )
        
        # Handle list of dicts (artifact wrapper)
        if isinstance(resp, list) and resp and isinstance(resp[0], dict) and 'kind' in resp[0]:
            log_debug(f"Processing as list of dicts with kind")
            items = resp
        # Handle single dict with 'kind'
        elif isinstance(resp, dict) and 'kind' in resp:
            log_debug(f"Processing as single dict with kind")
            items = [resp]
        # Handle single dict with artifact metadata - CONVERT TO FilePart (not DataPart)
        # This ensures all file references use the standard A2A FilePart format
        elif isinstance(resp, dict) and ('artifact-uri' in resp or 'artifact-id' in resp):
            artifact_uri = resp.get('artifact-uri', '')
            log_debug(f"Processing as artifact dict - converting to FilePart: {artifact_uri[:150] if artifact_uri else 'no-uri'}")
            if artifact_uri:
                # Use utility to create proper FilePart
                file_part = create_file_part(
                    uri=artifact_uri,
                    name=resp.get('file-name', 'artifact'),
                    mime_type=resp.get('media-type', resp.get('mime', 'image/png'))
                )
                parts.append(Part(root=file_part))
            else:
                # Fallback for artifact-id without URI (shouldn't happen, but be safe)
                log_debug(f"WARNING: artifact dict without URI, using DataPart fallback")
                parts.append(Part(root=DataPart(data=resp)))
            return Message(
                role='agent',
                parts=parts,
                contextId=context_id,
                taskId=task_id,
                messageId=str(uuid.uuid4()),
            )
        # Handle A2A Part object directly (e.g., from HITL flow)
        elif hasattr(resp, 'root') and hasattr(resp.root, 'kind'):
            root = resp.root
            kind = root.kind
            log_debug(f"Processing as A2A Part object with kind: {kind}")
            if kind == 'text':
                text_content = getattr(root, 'text', '')
                log_debug(f"Part text: {text_content[:200]}...")
                parts.append(Part(root=TextPart(text=text_content)))
            elif kind == 'data':
                data_content = getattr(root, 'data', {})
                log_debug(f"Part data: {data_content}")
                parts.append(Part(root=DataPart(data=data_content)))
            elif kind == 'file':
                log_debug(f"Part file: {getattr(root, 'file', None)}")
                parts.append(Part(root=FilePart(file=getattr(root, 'file', None))))
            else:
                log_debug(f"Unknown Part kind: {kind}")
                parts.append(Part(root=TextPart(text=str(root))))
            return Message(
                role='agent',
                parts=parts,
                contextId=context_id,
                taskId=task_id,
                messageId=str(uuid.uuid4()),
            )
        # Handle TextPart, DataPart, FilePart directly (unwrapped from Part)
        elif hasattr(resp, 'kind'):
            kind = resp.kind
            log_debug(f"Processing as raw A2A type with kind: {kind}")
            if kind == 'text':
                text_content = getattr(resp, 'text', '')
                log_debug(f"TextPart text: {text_content[:200]}...")
                parts.append(Part(root=TextPart(text=text_content)))
            elif kind == 'data':
                data_content = getattr(resp, 'data', {})
                log_debug(f"DataPart data: {data_content}")
                parts.append(Part(root=DataPart(data=data_content)))
            elif kind == 'file':
                log_debug(f"FilePart file: {getattr(resp, 'file', None)}")
                parts.append(Part(root=FilePart(file=getattr(resp, 'file', None))))
            else:
                log_debug(f"Unknown raw kind: {kind}")
                parts.append(Part(root=TextPart(text=str(resp))))
            return Message(
                role='agent',
                parts=parts,
                contextId=context_id,
                taskId=task_id,
                messageId=str(uuid.uuid4()),
            )
        # Handle Message object
        elif hasattr(resp, 'parts'):
            log_debug(f"Processing as Message object with {len(resp.parts) if resp.parts else 0} parts")
            for part in resp.parts:
                root = getattr(part, 'root', part)
                kind = getattr(root, 'kind', None)
                if kind == 'text':
                    text_content = getattr(root, 'text', str(root))
                    log_debug(f"Text part: {text_content[:200]}...")
                    parts.append(Part(root=TextPart(text=text_content)))
                elif kind == 'data':
                    data_content = getattr(root, 'data', {})
                    log_debug(f"Data part: {data_content}")
                    parts.append(Part(root=DataPart(data=data_content)))
                elif kind == 'file':
                    log_debug(f"File part: {getattr(root, 'file', None)}")
                    parts.append(Part(root=FilePart(file=getattr(root, 'file', None))))
                else:
                    log_debug(f"Unknown part kind: {kind}, content: {str(root)[:200]}...")
                    parts.append(Part(root=TextPart(text=str(root))))
            return Message(
                role=getattr(resp, 'role', 'agent'),
                parts=parts,
                contextId=context_id,
                taskId=task_id,
                messageId=str(uuid.uuid4()),
            )
        elif isinstance(resp, str):
            # Plain string response
            log_debug(f"Processing as plain string: {resp[:200]}...")
            return Message(
                role='agent',
                parts=[Part(root=TextPart(text=resp))],
                contextId=context_id,
                taskId=task_id,
                messageId=str(uuid.uuid4()),
            )
        else:
            # Fallback: treat as plain text but warn
            log_debug(f"WARNING: Unknown response type {type(resp)}, stringifying: {str(resp)[:200]}...")
            return Message(
                role='agent',
                parts=[Part(root=TextPart(text=str(resp)))],
                contextId=context_id,
                taskId=task_id,
                messageId=str(uuid.uuid4()),
            )
        # If we got here, items is a list of dicts with 'kind'
        log_debug(f"Processing {len(items)} items with kind")
        for i, item in enumerate(items):
            log_debug(f"Item {i}: {item}")
            if item['kind'] == 'text':
                log_debug(f"Text item: {item['text'][:200]}...")
                parts.append(Part(root=TextPart(text=item['text'])))
            elif item['kind'] == 'data':
                log_debug(f"Data item: {item['data']}")
                parts.append(Part(root=DataPart(data=item['data'])))
            elif item['kind'] == 'file':
                log_debug(f"File item: {item['file']}")
                parts.append(Part(root=FilePart(file=item['file'])))
        return Message(
            role='agent',
            parts=parts,
            contextId=context_id,
            taskId=task_id,
            messageId=str(uuid.uuid4()),
        )

    async def process_message(self, message: Message, agent_mode: bool = None, enable_inter_agent_memory: bool = False, workflow: str = None):
        await self.ensure_host_agent_initialized()
        message_id = get_message_id(message)
        if message_id:
            self._pending_message_ids.append(message_id)
        
        # DEBUG: Log what get_context_id returns
        extracted_context_id = get_context_id(message)
        log_debug(f"🔍 [process_message] get_context_id returned: {extracted_context_id}")
        
        context_id = extracted_context_id or str(uuid.uuid4())
        log_debug(f"🔍 [process_message] Final context_id (after UUID fallback): {context_id}")
        
        # Auto-detect agent_mode based on workflow presence (backward compatible)
        # If agent_mode is explicitly passed, use it; otherwise detect from workflow
        effective_agent_mode = agent_mode if agent_mode is not None else (workflow is not None and workflow.strip() != "")
        log_debug(f"process_message: Agent Mode = {effective_agent_mode} (explicit={agent_mode}), Inter-Agent Memory = {enable_inter_agent_memory}, Workflow = {workflow[:50] if workflow else None}")
        conversation = self.get_conversation(context_id)
        if not conversation:
            conversation = Conversation(conversation_id=context_id, is_active=True)
            self._conversations.append(conversation)
            
            # Stream conversation creation to WebSocket
            log_debug("Streaming conversation creation to WebSocket...")
            try:
                from service.websocket_streamer import get_websocket_streamer
                
                streamer = await get_websocket_streamer()
                if streamer:
                    # Send in A2A ConversationCreatedEventData format
                    event_data = {
                        "conversationId": context_id,
                        "conversationName": f"Chat {context_id[:8]}...",
                        "isActive": True,
                        "messageCount": 0
                    }
                    
                    success = await streamer._send_event("conversation_created", event_data, context_id)
                    if success:
                        log_debug(f"Conversation creation streamed: {event_data}")
                    else:
                        log_debug("Failed to stream conversation creation")
                else:
                    log_debug("WebSocket streamer not available for conversation creation")
                
            except Exception as e:
                log_debug(f"Error streaming conversation creation: {e}")
                import traceback
                traceback.print_exc()
        
        log_debug("About to append message to conversation...")
        self._messages.append(message)
        if conversation:
            conversation.messages.append(message)
        log_debug("About to add event...")
        self.add_event(Event(
            id=str(uuid.uuid4()),
            actor='user',
            content=message,
            timestamp=__import__('datetime').datetime.utcnow().timestamp(),
        ))
        log_debug("About to create task...")
        # Create a Task for this request (ADK parity)
        task_id = str(uuid.uuid4())
        task_description = message.parts[0].root.text if message.parts else "Agent task"
        task = Task(
            id=task_id,
            contextId=context_id,
            status=TaskStatus(state=TaskState.working),
            description=task_description,
            history=[message],
        )
        self.add_task(task)
        
        # Stream task creation to WebSocket
        log_debug("Streaming task creation to WebSocket...")
        try:
            from service.websocket_streamer import get_websocket_streamer
            
            streamer = await get_websocket_streamer()
            if streamer:
                # Send in A2A TaskCreatedEventData format
                event_data = {
                    "taskId": task_id,
                    "conversationId": context_id,
                    "contextId": context_id,
                    "state": "created",
                    "artifactsCount": 0
                }
                
                success = await streamer._send_event("task_created", event_data, context_id)
                if success:
                    log_debug(f"Task creation streamed to WebSocket: {event_data}")
                else:
                    log_debug("Failed to stream task creation to WebSocket")
            else:
                log_debug("WebSocket streamer not available for task creation")
            
        except Exception as e:
            log_debug(f"Error streaming task creation to WebSocket: {e}")
            import traceback
            traceback.print_exc()
        
        log_debug("Task creation complete, setting up event logger...")
        # Route to FoundryHostAgent
        tool_call_events = []
        def event_logger(event_dict):
            # Convert tool call event dict to Event with enhanced details and stream to WebSocket
            from a2a.types import Message, Part, TextPart
            
            # Extract agent name from event or use default
            agent_name = event_dict.get('actor', 'host_agent')
            
            # Create detailed text based on event type
            if 'args' in event_dict:
                text = f"TOOL CALL: {event_dict['name']} with arguments: {event_dict['args']}"
                # Try to extract agent_name from args if it's a send_message tool
                if event_dict['name'] == 'send_message' and isinstance(event_dict['args'], dict):
                    if 'agent_name' in event_dict['args']:
                        agent_name = event_dict['args']['agent_name']
                        log_debug(f"Extracted agent name from tool call: {agent_name}")
            elif 'output' in event_dict:
                text = f"TOOL RESULT: {event_dict['name']} {event_dict['output']}"
            else:
                text = f"EVENT: {event_dict}"
            
            msg = Message(
                role='agent',
                parts=[Part(root=TextPart(text=text))],
                contextId=context_id,
                messageId=event_dict['id'],
            )
            event_obj = Event(
                id=event_dict['id'],
                actor=agent_name,
                content=msg,
                timestamp=__import__('datetime').datetime.utcnow().timestamp(),
            )
            self._events.append(event_obj)
            tool_call_events.append(event_obj)
            
            # Stream tool call events to WebSocket immediately for real-time frontend updates
            if 'args' in event_dict:
                log_debug(f"Streaming tool call event to WebSocket for agent: {agent_name}")
                try:
                    from service.websocket_streamer import get_websocket_streamer
                    import asyncio
                    
                    async def stream_tool_call():
                        try:
                            streamer = await get_websocket_streamer()
                            if streamer:
                                # Send in A2A ToolCallEventData format with structured details
                                event_data = {
                                    "toolCallId": event_dict['id'],
                                    "conversationId": context_id or "",
                                    "contextId": context_id or "",
                                    "toolName": event_dict['name'],
                                    "arguments": event_dict['args'],
                                    "agentName": agent_name,
                                    "timestamp": __import__('datetime').datetime.utcnow().isoformat()
                                }
                                
                                success = await streamer._send_event("tool_call", event_data, context_id)
                                if success:
                                    log_debug(f"Tool call event streamed: {event_data}")
                                else:
                                    log_debug("Failed to stream tool call event")
                            else:
                                log_debug("WebSocket streamer not available for tool call")
                        except Exception as e:
                            log_debug(f"Error streaming tool call to WebSocket: {e}")
                            # Don't let WebSocket errors break the main flow
                            pass
                    
                    # Use background task for event_logger callback (can't make this function async)
                    asyncio.create_task(stream_tool_call())
                    
                except ImportError:
                    # WebSocket module not available, continue without streaming
                    log_debug("WebSocket module not available for tool call")
                    pass
                except Exception as e:
                    log_debug(f"Error setting up tool call streaming: {e}")
                    # Don't let WebSocket errors break the main flow
                    pass
            # Stream tool response events to WebSocket for granular visibility
            elif 'output' in event_dict:
                log_debug(f"Streaming tool response event to WebSocket for agent: {agent_name}")
                try:
                    from service.websocket_streamer import get_websocket_streamer
                    import asyncio
                    
                    async def stream_tool_response():
                        try:
                            streamer = await get_websocket_streamer()
                            if streamer:
                                # Determine status from output
                                output = event_dict['output']
                                status = "success"
                                error_message = None
                                
                                if isinstance(output, dict) and "error" in output:
                                    status = "failed"
                                    error_message = output["error"]
                                elif "error" in str(output).lower() or "failed" in str(output).lower():
                                    status = "failed"
                                    error_message = str(output)
                                
                                event_data = {
                                    "toolCallId": event_dict['id'],
                                    "conversationId": context_id or "",
                                    "contextId": context_id or "",
                                    "toolName": event_dict['name'],
                                    "status": status,
                                    "agentName": agent_name,
                                    "timestamp": __import__('datetime').datetime.utcnow().isoformat()
                                }
                                
                                if error_message:
                                    event_data["error"] = error_message
                                
                                success = await streamer._send_event("tool_response", event_data, context_id)
                                if success:
                                    log_debug(f"Tool response event streamed: {event_data}")
                                else:
                                    log_debug("Failed to stream tool response event")
                            else:
                                log_debug("WebSocket streamer not available for tool response")
                        except Exception as e:
                            log_debug(f"Error streaming tool response to WebSocket: {e}")
                            # Don't let WebSocket errors break the main flow
                            pass
                    
                    # Use background task for event_logger callback (can't make this function async)
                    asyncio.create_task(stream_tool_response())
                    
                except ImportError:
                    # WebSocket module not available, continue without streaming
                    log_debug("WebSocket module not available for tool response")
                    pass
                except Exception as e:
                    log_debug(f"Error setting up tool response streaming: {e}")
                    # Don't let WebSocket errors break the main flow
                    pass
        
        # Set session-specific agents before processing
        session_id = parse_session_from_context(context_id)
        print(f"🟢 [MANAGER] Parsed session_id: {session_id}")
        if session_id:
            session_registry = get_session_registry()
            session_agents = session_registry.get_session_agents(session_id)
            print(f"� [MANAGER] Retrieved {len(session_agents)} agents from session registry for {session_id[:12]}")
            for idx, agent in enumerate(session_agents):
                print(f"🟢 [MANAGER]   Agent {idx+1}: {agent.get('name')} - {agent.get('url')}")
            print(f"🟢 [MANAGER] Calling set_session_agents...")
            await self._host_agent.set_session_agents(session_agents)
            print(f"🟢 [MANAGER] After set_session_agents, host has {len(self._host_agent.cards)} agents")
        else:
            print("⚠️ [MANAGER] No session ID found in context, host agent will have no agents")
        
        # Pass the entire message with all parts (including files) to the host agent
        user_text = message.parts[0].root.text if message.parts and message.parts[0].root.kind == 'text' else ""
        log_debug(f"About to call run_conversation_with_parts with message parts: {len(message.parts)} parts, agent_mode: {effective_agent_mode}, enable_inter_agent_memory: {enable_inter_agent_memory}, workflow: {workflow[:50] if workflow else None}")
        responses = await self._host_agent.run_conversation_with_parts(message.parts, context_id, event_logger=event_logger, agent_mode=effective_agent_mode, enable_inter_agent_memory=enable_inter_agent_memory, workflow=workflow)
        log_debug(f"FoundryHostAgent responses count: {len(responses) if responses else 'None'}")
        log_debug(f"FoundryHostAgent responses: {responses}")
        
        if not responses:
            log_debug("WARNING: No responses from FoundryHostAgent - this will cause no messages to be sent to frontend!")
            # Remove from pending since we're not going to get a response
            if message_id in self._pending_message_ids:
                self._pending_message_ids.remove(message_id)
            return []
        # Build mapping of agent names from tool call events
        # These are used for status_agent_name to send correct task_updated events to frontend
        print(f"📋 [TOOL_EVENTS] Processing {len(tool_call_events)} tool call events")
        for i, te in enumerate(tool_call_events):
            print(f"📋 [TOOL_EVENT {i}] actor={te.actor}, id={te.id}")
        
        agent_names_from_tools = []
        for tool_event in tool_call_events:
            # The actor field contains the agent name (set in event_logger when it's a send_message)
            # Only include if it's not the host agent itself
            if tool_event.actor and tool_event.actor not in ['host_agent', 'foundry-host-agent']:
                if tool_event.actor not in agent_names_from_tools:  # Avoid duplicates
                    agent_names_from_tools.append(tool_event.actor)
                    log_debug(f"Found agent name from tool event actor: {tool_event.actor}")
        
        log_debug(f"Agent names from tool calls: {agent_names_from_tools}")
        print(f"🎯 [SIDEBAR FIX] Found {len(agent_names_from_tools)} agent names from tool calls: {agent_names_from_tools}")
        log_debug(f"Number of responses: {len(responses)}")
        log_debug(f"All foundry responses will be attributed to foundry-host-agent")
        
        completed_agents: set[str] = set()

        async def stream_task_status_update(target_agent: str, target_state: TaskState):
            try:
                from service.websocket_streamer import get_websocket_streamer

                streamer = await get_websocket_streamer()
                if not streamer:
                    log_debug("WebSocket streamer not available for task status")
                    return

                status_str = target_state.name if hasattr(target_state, 'name') else str(target_state)
                event_data = {
                    "taskId": task_id,
                    "conversationId": context_id,
                    "contextId": context_id,
                    "state": status_str,
                    "agentName": target_agent,
                    "artifactsCount": 0,
                }

                success = await streamer._send_event("task_updated", event_data, context_id)
                if success:
                    log_debug(f"Task status update streamed: {event_data}")
                else:
                    log_debug("Failed to stream task status update")
            except Exception as e:
                log_debug(f"SPECIFIC ERROR in task status streaming: {e}")
                import traceback
                traceback.print_exc()

        for resp_index, resp in enumerate(responses):
            log_debug(f"Response {resp_index}: type={type(resp)}, is_dict={isinstance(resp, dict)}")
            if isinstance(resp, dict):
                log_debug(f"Response {resp_index} dict keys: {list(resp.keys())}")
                log_debug(f"Response {resp_index} has artifact-uri: {'artifact-uri' in resp}")
            print("[DEBUG] Response parts:", getattr(resp, 'parts', None))
            msg = self.foundry_content_to_message(resp, context_id, task_id)
            log_debug(f"Message created with {len(msg.parts) if hasattr(msg, 'parts') else 0} parts")
            if conversation:
                conversation.messages.append(msg)
            if not hasattr(task, 'history') or task.history is None:
                task.history = []
            task.history.append(msg)
            
            # FIXED: Always attribute foundry agent responses to "foundry-host-agent" 
            # instead of trying to map unified responses to individual agent names
            # This prevents duplicate messages with wrong agent attribution
            actor_name = "foundry-host-agent"
            status_agent_name = (
                agent_names_from_tools[resp_index]
                if resp_index < len(agent_names_from_tools)
                else actor_name
            )
            print(f"🎯 [SIDEBAR] Response {resp_index}: status_agent_name={status_agent_name} (from list: {agent_names_from_tools})")
            log_debug(f"Using agent name for response {resp_index}: {status_agent_name}")
            
            self.add_event(Event(
                id=str(uuid.uuid4()),
                actor=actor_name,
                content=msg,
                timestamp=__import__('datetime').datetime.utcnow().timestamp(),
            ))
            
            # Stream message to WebSocket for frontend in expected format
            log_debug("Streaming message to WebSocket...")
            try:
                from service.websocket_streamer import get_websocket_streamer
                
                streamer = await get_websocket_streamer()
                if streamer:
                    # Send in A2A MessageEventData format with proper agent attribution
                    # Use status_agent_name (actual remote agent) not actor_name (host)
                    event_data = {
                        "messageId": get_message_id(msg) or str(uuid.uuid4()),
                        "conversationId": context_id,
                        "contextId": context_id,
                        "role": "assistant",
                        "content": [],
                        "direction": "incoming",
                        "agentName": status_agent_name,
                        "timestamp": __import__('datetime').datetime.utcnow().isoformat(),
                    }

                    log_debug(f"WebSocket streaming - resp type: {type(resp)}, msg has parts: {hasattr(msg, 'parts')}")
                    if hasattr(msg, "parts"):
                        log_debug(f"Processing message with {len(msg.parts)} parts")
                    
                    if isinstance(resp, str):
                        event_data["content"].append({
                            "type": "text",
                            "content": resp,
                            "mediaType": "text/plain",
                        })
                    elif hasattr(msg, "parts"):
                        text_parts = []
                        image_parts = []
                        
                        # First pass: collect video_metadata from DataParts (for video_id tracking)
                        video_metadata_by_uri = {}
                        for part in msg.parts:
                            root = part.root if hasattr(part, 'root') else part
                            if isinstance(root, DataPart) and isinstance(root.data, dict):
                                if root.data.get("type") == "video_metadata":
                                    uri = root.data.get("uri")
                                    if uri:
                                        video_metadata_by_uri[uri] = {
                                            "video_id": root.data.get("video_id"),
                                            "generation_id": root.data.get("generation_id"),
                                            "original_video_id": root.data.get("original_video_id"),
                                        }
                                        log_debug(f"Collected video metadata for URI: video_id={root.data.get('video_id')}")
                        
                        # Second pass: process all parts
                        for part in msg.parts:
                            log_debug(f"Processing part: {type(part)}, has root: {hasattr(part, 'root')}")
                            root = part.root if hasattr(part, 'root') else part
                            if isinstance(root, TextPart):
                                text_parts.append(root.text)
                            elif isinstance(root, FilePart):
                                # Handle FilePart with FileWithUri (from Image Generator, Video agents, etc.)
                                file_obj = getattr(root, 'file', None)
                                if file_obj:
                                    file_uri = getattr(file_obj, 'uri', None)
                                    if file_uri:
                                        log_debug(f"Found FilePart with URI: {file_uri}")
                                        # Determine type based on mimeType or file extension
                                        mime_type = getattr(file_obj, 'mimeType', '')
                                        file_name = getattr(file_obj, 'name', 'agent-artifact')
                                        # Check mimeType first, then fall back to extension
                                        if mime_type.startswith('video/'):
                                            part_type = "video"
                                            default_name = "video.mp4"
                                        elif any(ext in file_uri.lower() for ext in ['.mp4', '.webm', '.mov', '.avi']):
                                            part_type = "video"
                                            default_name = "video.mp4"
                                        else:
                                            part_type = "image"
                                            default_name = "image.png"
                                        
                                        # Look up video metadata by URI (for video_id)
                                        metadata = video_metadata_by_uri.get(file_uri, {})
                                        
                                        file_part_data = {
                                            "type": part_type,
                                            "uri": file_uri,
                                            "fileName": file_name if file_name != 'agent-artifact' else default_name,
                                            "fileSize": getattr(file_obj, 'size', 0),
                                            "mediaType": mime_type or ("video/mp4" if part_type == "video" else "image/png"),
                                            "storageType": "azure_blob",
                                            "status": "completed",
                                        }
                                        
                                        # Add video metadata if available (for remix functionality)
                                        if metadata.get("video_id"):
                                            file_part_data["videoId"] = metadata["video_id"]
                                            log_debug(f"Added videoId to file part: {metadata['video_id']}")
                                        if metadata.get("generation_id"):
                                            file_part_data["generationId"] = metadata["generation_id"]
                                        if metadata.get("original_video_id"):
                                            file_part_data["originalVideoId"] = metadata["original_video_id"]
                                        
                                        image_parts.append(file_part_data)
                                    else:
                                        log_debug(f"FilePart has no URI, skipping: {file_obj}")
                            elif isinstance(root, DataPart) and isinstance(root.data, dict):
                                # Skip video_metadata DataParts (already processed in first pass)
                                if root.data.get("type") == "video_metadata":
                                    continue
                                    
                                artifact_uri = root.data.get("artifact-uri")
                                log_debug(f"Found DataPart with dict, has artifact-uri: {bool(artifact_uri)}")
                                if artifact_uri:
                                    log_debug(f"Adding artifact to content: {root.data.get('file-name')}")
                                    # Determine type based on mime or media-type
                                    media_type = root.data.get("media-type") or root.data.get("mime", "")
                                    file_name = root.data.get("file-name", "")
                                    if media_type.startswith('video/') or any(ext in artifact_uri.lower() for ext in ['.mp4', '.webm', '.mov', '.avi']):
                                        part_type = "video"
                                        default_media = "video/mp4"
                                    else:
                                        part_type = "image"
                                        default_media = "image/png"
                                    image_parts.append({
                                        "type": part_type,
                                        "uri": artifact_uri,
                                        "fileName": file_name,
                                        "fileSize": root.data.get("file-size"),
                                        "mediaType": media_type or default_media,
                                        "storageType": root.data.get("storage-type", "azure_blob"),
                                        "status": root.data.get("status"),
                                        "sourceUrl": root.data.get("source-url"),
                                    })
                                elif root.data.get("type") not in ["token_usage", "video_metadata"]:
                                    # Only add non-token_usage and non-video_metadata DataParts as text
                                    text_parts.append(json.dumps(root.data))
                        if text_parts:
                            event_data["content"].append({
                                "type": "text",
                                "content": "\n\n".join(text_parts),
                                "mediaType": "text/plain",
                            })
                        if image_parts:
                            pending_list = self._pending_artifacts.setdefault(context_id, [])
                            pending_list.extend(image_parts)
                        for image_part in image_parts:
                            event_data["content"].append(image_part)
                    else:
                        event_data["content"].append({
                            "type": "text",
                            "content": str(resp),
                            "mediaType": "text/plain",
                        })

                    if not any(item.get("type") == "image" for item in event_data["content"]):
                        pending_images = self._pending_artifacts.pop(context_id, [])
                        for image_part in pending_images:
                            event_data["content"].append(image_part)
                    else:
                        self._pending_artifacts.pop(context_id, None)

                    success = await streamer._send_event("message", event_data, context_id)
                    print(f"📁 [FILE_HISTORY] Checking {len(event_data['content'])} content items for images...")
                    for content_item in event_data["content"]:
                        if content_item.get("type") == "image":
                            print(f"📁 [FILE_HISTORY] Found image content with uri: {content_item.get('uri', 'no-uri')[:80]}...")
                            log_debug(f"Found file content with uri: {content_item.get('uri')}")
                        if content_item.get("type") == "image" and content_item.get("uri"):
                            file_uri = content_item.get("uri")
                            # Emit file_uploaded event so it appears in File History
                            # Deduplication is handled by websocket streamer's per-conversation tracking
                            file_info = {
                                "file_id": str(uuid.uuid4()),
                                "filename": content_item.get("fileName", "agent-artifact.png"),
                                "uri": file_uri,
                                "size": content_item.get("fileSize", 0),
                                "content_type": content_item.get("mediaType", "image/png"),
                                "source_agent": status_agent_name,
                                "contextId": context_id
                            }
                            print(f"📁 [FILE_HISTORY] Emitting file_uploaded event for: {file_info['filename']}")
                            await streamer.stream_file_uploaded(file_info, context_id)
                            log_debug(f"File uploaded event sent for agent artifact: {file_info['filename']}")
                            
                            # Register file in agent file registry for session persistence
                            # Extract session_id from context_id (format: sessionId::conversationId)
                            try:
                                from service.agent_file_registry import register_agent_file
                                session_id = context_id.split('::')[0] if '::' in context_id else context_id
                                register_agent_file(
                                    session_id=session_id,
                                    file_id=file_info["file_id"],
                                    filename=file_info["filename"],
                                    uri=file_uri,
                                    content_type=file_info["content_type"],
                                    size=file_info.get("size", 0),
                                    source_agent=status_agent_name
                                )
                                print(f"📁 [FILE_REGISTRY] Registered agent file for session {session_id[:8]}...")
                            except Exception as reg_error:
                                print(f"⚠️ [FILE_REGISTRY] Failed to register file: {reg_error}")
                            
                            await streamer._send_event(
                                "remote_agent_activity",
                                {
                                    "agentName": status_agent_name,
                                    "content": f"Image available: {content_item['uri']}",
                                    "timestamp": __import__('datetime').datetime.utcnow().isoformat(),
                                },
                                context_id,
                            )
                    if success:
                        log_debug(f"Message streamed to WebSocket: {event_data}")
                    else:
                        log_debug("Failed to stream message to WebSocket")
                else:
                    log_debug("WebSocket streamer not available")
                
            except Exception as e:
                log_debug(f"Error streaming to WebSocket: {e}")
                import traceback
                traceback.print_exc()
            
            # Determine task state from response
            # Priority: 1) A2A protocol status, 2) Session context (HITL), 3) Default to completed
            state = TaskState.completed
            
            # Check if response has proper A2A status object (from remote agents)
            if hasattr(resp, 'status') and hasattr(resp.status, 'state'):
                state = resp.status.state
            
            # NOTE: We removed the text-based heuristics that tried to infer state from response content.
            # These were unreliable - matching "failed" or "error" in conversational text is wrong.
            # If we got here with a response, the operation succeeded. Actual failures are caught
            # by exception handling earlier in the flow.
            
            # HUMAN-IN-THE-LOOP: Check if a remote agent set input_required state
            # This is tracked in the session context's pending_input_agent field
            try:
                session_ctx = self._host_agent.get_session_context(context_id)
                if session_ctx and session_ctx.pending_input_agent:
                    log_debug(f"🔄 [HITL] Detected pending_input_agent: {session_ctx.pending_input_agent}, overriding state to input_required")
                    state = TaskState.input_required
                    # Use the pending agent name for accurate status attribution
                    status_agent_name = session_ctx.pending_input_agent
            except Exception as e:
                log_debug(f"Error checking pending_input_agent: {e}")
            task.status.state = state
            task.status.message = msg
            self.update_task(task)
            
            # Stream task status update to WebSocket
            log_debug(f"Streaming task status update to WebSocket: {state}")
            try:
                asyncio.create_task(stream_task_status_update(status_agent_name, state))
                completed_agents.add(status_agent_name)
            except Exception as e:
                log_debug(f"Error scheduling task status update: {e}")
            
            if task.status.message and (not conversation.messages or conversation.messages[-1] != task.status.message):
                conversation.messages.append(task.status.message)
                self.add_event(Event(
                    id=str(uuid.uuid4()),
                    actor=actor_name,
                    content=task.status.message,
                    timestamp=__import__('datetime').datetime.utcnow().timestamp(),
                ))
            if state == TaskState.input_required:
                pass
            elif state == TaskState.canceled:
                pass
            elif state == TaskState.failed:
                pass
        if message_id in self._pending_message_ids:
            self._pending_message_ids.remove(message_id)

        # NOTE: We only emit task_updated events for agents that actually participated
        # in this workflow. The A2A protocol handles completion events properly.
        # Do NOT emit "completed" for all registered agents - that's wrong!

        return responses

    def add_task(self, task: Task):
        self._tasks.append(task)

    def update_task(self, task: Task):
        for i, t in enumerate(self._tasks):
            if t.id == task.id:
                self._tasks[i] = task
                return

    def attach_message_to_task(self, message: Message, task_id: str):
        if message:
            self._task_map[get_message_id(message)] = task_id

    def insert_message_history(self, task: Task, message: Message):
        if not message:
            return
        if task.history is None:
            task.history = []
        message_id = get_message_id(message)
        if not message_id:
            return
        if task.history and (
            task.status.message
            and get_message_id(task.status.message)
            not in [get_message_id(x) for x in task.history]
        ):
            task.history.append(task.status.message)
        elif not task.history and task.status.message:
            task.history = [task.status.message]

    def add_event(self, event: Event):
        # Append event in true order
        event.timestamp = event.timestamp or __import__('datetime').datetime.utcnow().timestamp()
        self._events.append(event)

    def get_conversation(self, conversation_id: Optional[str]) -> Optional[Conversation]:
        for c in self._conversations:
            if c.conversation_id == conversation_id:
                return c
        return None

    def get_pending_messages(self) -> list[tuple[str, str]]:
        return [(msg_id, "") for msg_id in self._pending_message_ids]

    def register_agent(self, url):
        agent_card = get_agent_card(url)
        if not agent_card.url:
            agent_card.url = url
        self._agents.append(agent_card)
        
        # Only register with host agent if it's already initialized
        if self._host_agent_initialized and self._host_agent:
            if hasattr(self._host_agent, 'register_agent_card'):
                self._host_agent.register_agent_card(agent_card)
            if hasattr(self._host_agent, 'update_instructions_with_agents'):
                self._host_agent.update_instructions_with_agents()

    async def handle_self_registration(self, agent_address: str, agent_card: Optional[AgentCard] = None) -> bool:
        """Handle self-registration requests from remote agents.
        
        This method is called when remote agents register themselves on startup.
        
        Args:
            agent_address: The URL/address of the remote agent
            agent_card: Optional pre-built agent card
            
        Returns:
            bool: True if registration successful, False otherwise
        """
        try:
            log_debug(f"🤝 Host manager handling self-registration from: {agent_address}")
            
            # Ensure agent is initialized before registration
            await self.ensure_host_agent_initialized()
            
            # Use the FoundryHostAgent's registration method
            success = await self._host_agent.register_remote_agent(agent_address, agent_card)
            
            if success:
                # Also add to our local agent list for UI consistency
                if not agent_card:
                    agent_card = get_agent_card(agent_address)
                    if not agent_card.url:
                        agent_card.url = agent_address
                
                # Find existing agent by URL
                existing_index = next((i for i, a in enumerate(self._agents) if a.url == agent_address), None)
                
                if existing_index is not None:
                    # Update existing agent card
                    old_name = self._agents[existing_index].name
                    self._agents[existing_index] = agent_card
                    log_debug(f"🔄 Updated {agent_card.name} in UI agent list (was: {old_name})")
                else:
                    # Add new agent
                    self._agents.append(agent_card)
                    log_debug(f"✅ Added {agent_card.name} to UI agent list")
                
                # Persist to agent registry file for persistence across restarts
                try:
                    from service.agent_registry import get_registry
                    registry = get_registry()
                    
                    # Convert agent card to dict format for registry
                    agent_dict = agent_card.model_dump()
                    
                    # Check if agent already exists in registry (by name or URL)
                    existing_agent = registry.get_agent(agent_card.name)
                    if existing_agent:
                        # Update existing agent in registry
                        registry.update_agent(agent_card.name, agent_dict)
                        log_debug(f"💾 Updated {agent_card.name} in persistent agent registry")
                    else:
                        # Add new agent to registry
                        if registry.add_agent(agent_dict):
                            log_debug(f"💾 Persisted {agent_card.name} to agent registry file")
                        else:
                            log_debug(f"⚠️ Agent {agent_card.name} already exists in registry (skipped)")
                except Exception as persist_error:
                    log_debug(f"⚠️ Failed to persist agent to registry: {persist_error}")
                
                # Trigger immediate WebSocket sync to update UI in real-time
                # This happens for both new and updated agents
                try:
                    from service.websocket_server import get_websocket_server
                    websocket_server = get_websocket_server()
                    if websocket_server:
                        websocket_server.trigger_immediate_sync()
                        log_debug(f"🔔 Triggered immediate agent registry sync for {agent_card.name}")
                    else:
                        log_debug(f"⚠️ WebSocket server not available for immediate sync")
                except Exception as sync_error:
                    log_debug(f"⚠️ Failed to trigger immediate sync: {sync_error}")
                
            return success
            
        except Exception as e:
            log_debug(f"❌ Host manager registration error: {e}")
            return False

    async def unregister_agent(self, agent_name: str) -> bool:
        """Handle agent unregistration requests.
        
        This method is called when an agent needs to be removed from the host.
        
        Args:
            agent_name: The name of the agent to unregister
            
        Returns:
            bool: True if unregistration successful, False otherwise
        """
        try:
            log_debug(f"🗑️ Host manager handling unregistration for: {agent_name}")
            
            # Ensure agent is initialized
            await self.ensure_host_agent_initialized()
            
            # Use the FoundryHostAgent's unregistration method
            success = await self._host_agent.unregister_remote_agent(agent_name)
            
            if success:
                # Also remove from our local agent list for UI consistency
                self._agents = [a for a in self._agents if a.name != agent_name]
                log_debug(f"✅ Removed {agent_name} from UI agent list")
                
                # Trigger immediate WebSocket sync to update UI
                try:
                    from service.websocket_server import get_websocket_server
                    websocket_server = get_websocket_server()
                    if websocket_server:
                        websocket_server.trigger_immediate_sync()
                        log_debug(f"🔔 Triggered immediate agent registry sync after removing {agent_name}")
                    else:
                        log_debug(f"⚠️ WebSocket server not available for immediate sync")
                except Exception as sync_error:
                    log_debug(f"⚠️ Failed to trigger immediate sync: {sync_error}")
            else:
                log_debug(f"❌ Agent {agent_name} not found or unregistration failed")
                
            return success
            
        except Exception as e:
            log_debug(f"❌ Host manager unregistration error: {e}")
            import traceback
            log_debug(f"❌ Unregistration traceback: {traceback.format_exc()}")
            return False

    @property
    def agents(self) -> list:
        return self._agents

    @property
    def conversations(self) -> list:
        # print("[DEBUG] FoundryHostManager.conversations called, returning:", len(self._conversations), "conversations")
        return self._conversations

    @property
    def tasks(self) -> list:
        # print("[DEBUG] FoundryHostManager.tasks called, returning:", len(self._tasks), "tasks")
        return self._tasks

    @property
    def events(self) -> list[Event]:
        # Return the true event log in append order
        return self._events

    def sanitize_message(self, message):
        # For Foundry, just return the message as-is
        return message 

    async def get_current_root_instruction(self) -> str:
        """Get the current root instruction from the Foundry agent"""
        await self.ensure_host_agent_initialized()
        if self._host_agent:
            return await self._host_agent.get_current_root_instruction()
        raise Exception("Host agent not available")

    async def update_root_instruction(self, new_instruction: str) -> bool:
        """Update the root instruction in the Foundry agent"""
        await self.ensure_host_agent_initialized()
        if self._host_agent:
            return await self._host_agent.update_root_instruction(new_instruction)
        return False

    async def reset_root_instruction(self) -> bool:
        """Reset the root instruction to default in the Foundry agent"""
        await self.ensure_host_agent_initialized()
        if self._host_agent:
            return await self._host_agent.reset_root_instruction()
        return False
