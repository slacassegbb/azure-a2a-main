"""
Event Emitters - WebSocket event emission methods for FoundryHostAgent2.

This module contains all _emit_* methods that send real-time events to the
frontend via WebSocket. These include:
- Task status updates
- Agent registration events  
- Tool call/response events
- File artifact events
- Text streaming chunks
- Granular agent activity events

These are extracted from foundry_agent_a2a.py to improve code organization.
The class is designed to be used as a mixin with FoundryHostAgent2.
"""

import asyncio
import contextvars
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from a2a.types import AgentCard, Task

from ..utils import get_context_id, get_task_id
from ..remote_agent_connection import TaskCallbackArg

# Import the shared context variable from the main module
# This is used for async-safe context_id tracking
try:
    from ..foundry_agent_a2a import _current_context_id, _current_parallel_call_id
except ImportError:
    # Fallback: create local context variables if import fails
    _current_context_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('current_context_id', default=None)
    _current_parallel_call_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('parallel_call_id', default=None)

# Import logging utilities
import sys
from pathlib import Path
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from log_config import log_debug, log_info, log_error


class EventEmitters:
    """
    Mixin class providing WebSocket event emission methods.
    
    This class is designed to be inherited by FoundryHostAgent2 along with
    other mixin classes. All methods use 'self' and expect the main class
    to have the required attributes (task_callback, _agent_tasks, etc).
    """

    async def _emit_tool_call_event(self, agent_name: str, tool_name: str, arguments: dict, context_id: str = None):
        """Emit tool call event to WebSocket for granular UI visibility."""
        try:
            from service.websocket_streamer import get_websocket_streamer
            
            streamer = await get_websocket_streamer()
            if streamer:
                event_data = {
                    "agentName": agent_name,
                    "toolName": tool_name,
                    "arguments": arguments,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
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

    async def _emit_outgoing_message_event(self, target_agent_name: str, message: str, context_id: str):
        """Emit outgoing message event to WebSocket for DAG display."""
        try:
            from service.websocket_streamer import get_websocket_streamer
            
            streamer = await get_websocket_streamer()
            if streamer:
                event_data = {
                    "sourceAgent": "Host Agent",
                    "targetAgent": target_agent_name,
                    "message": message,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "contextId": context_id
                }
                
                log_debug(f"[OUTGOING MESSAGE] {target_agent_name}: {message[:100]}...")
                await streamer._send_event("outgoing_agent_message", event_data, context_id)
                
        except Exception as e:
            log_debug(f"Error emitting outgoing message event: {e}")

    async def _emit_tool_response_event(self, agent_name: str, tool_name: str, status: str, error_message: str = None, context_id: str = None):
        """Emit tool response event to WebSocket for granular UI visibility."""
        try:
            from service.websocket_streamer import get_websocket_streamer
            
            streamer = await get_websocket_streamer()
            if streamer:
                event_data = {
                    "agentName": agent_name,
                    "toolName": tool_name,
                    "status": status,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
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
                task_state = "completed" if status == "success" else "failed"
                
                if not context_id:
                    log_debug(f"⚠️ [_emit_tool_response_event] No context_id for agent {agent_name}, cannot emit task_updated")
                    return
                
                task_updated_data = {
                    "taskId": str(uuid.uuid4()),
                    "conversationId": context_id,
                    "contextId": context_id,
                    "state": task_state,
                    "agentName": agent_name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "content": f"Agent {status}" if not error_message else error_message
                }
                log_debug(f"[SIDEBAR] Emitting task_updated for {agent_name}: state={task_state}")
                await streamer._send_event("task_updated", task_updated_data, context_id)
            else:
                log_debug(f"WebSocket streamer not available for tool response")
                
        except Exception as e:
            log_debug(f"Error emitting tool response event: {e}")

    async def _emit_simple_task_status(
        self, 
        agent_name: str, 
        state: str, 
        context_id: str, 
        task_id: str = None
    ) -> bool:
        """
        Emit a simple task status update to the sidebar via WebSocket.
        
        This is a lightweight helper for emitting task state changes (submitted, working, 
        completed, failed) without the complexity of full Task object handling.
        """
        try:
            from service.websocket_streamer import get_websocket_streamer
            streamer = await get_websocket_streamer()
            if streamer:
                event_data = {
                    "taskId": task_id or str(uuid.uuid4()),
                    "conversationId": context_id,
                    "contextId": context_id,
                    "state": state,
                    "agentName": agent_name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                log_debug(f"[SIDEBAR] Emitting task_updated for {agent_name}: state={state}")
                return await streamer._send_event("task_updated", event_data, context_id)
            else:
                log_debug(f"No WebSocket streamer available for task status: {agent_name}/{state}")
                return False
        except Exception as e:
            log_debug(f"Error emitting task status {state} for {agent_name}: {e}")
            return False

    async def _emit_file_artifact_event(
        self,
        filename: str,
        uri: str,
        context_id: str,
        agent_name: str,
        content_type: str = "image/png",
        size: int = 0,
        status: str = "uploaded"
    ) -> bool:
        """
        Emit a file artifact event to notify the UI of a new file from an agent.
        
        Args:
            status: File processing status - 'uploaded', 'processing', or 'analyzed'
                    Use 'processing' when the file will be auto-indexed so the UI shows animation.
        """
        try:
            from service.websocket_streamer import get_websocket_streamer
            streamer = await get_websocket_streamer()
            if streamer:
                # Extract file_id from unified blob path: uploads/{session_id}/{file_id}/{filename}
                # This ensures the WebSocket event file_id matches the blob storage file_id
                file_id = None
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(uri)
                    path_parts = parsed.path.split('/')
                    # Find 'uploads' in path and get file_id (2 positions after uploads)
                    for i, part in enumerate(path_parts):
                        if part == 'uploads' and i + 2 < len(path_parts):
                            # path_parts[i+1] = session_id, path_parts[i+2] = file_id
                            file_id = path_parts[i + 2]
                            break
                except Exception as e:
                    log_debug(f"Could not extract file_id from URI {uri}: {e}")
                
                # Fallback: hash the blob path (sans SAS query params) for deterministic ID
                # that matches file_processing_completed events
                if not file_id:
                    import hashlib
                    from urllib.parse import urlparse
                    _parsed = urlparse(uri)
                    _base_uri = f"{_parsed.scheme}://{_parsed.netloc}{_parsed.path}"
                    file_id = hashlib.md5(_base_uri.encode()).hexdigest()[:16]
                    log_debug(f"Using hash-based file_id for {filename}: {file_id}")
                
                file_info = {
                    "file_id": file_id,
                    "filename": filename,
                    "uri": uri,
                    "size": size,
                    "content_type": content_type,
                    "source_agent": agent_name,
                    "contextId": context_id,
                    "status": status  # 'uploaded', 'processing', or 'analyzed'
                }
                await streamer.stream_file_uploaded(file_info, context_id)
                log_debug(f"File uploaded event sent: {filename} from {agent_name} (id={file_id}, status={status})")
                return True
            else:
                log_debug(f"No WebSocket streamer available for file event: {filename}")
                return False
        except Exception as e:
            log_debug(f"Error emitting file artifact event: {e}")
            return False

    async def _emit_file_analyzed_event(
        self,
        filename: str,
        uri: str,
        context_id: str,
        session_id: str,
        status: str = "analyzed"
    ) -> bool:
        """
        Emit a file_processing_completed event to notify the UI that a file has been processed.
        This updates the file status in the file history UI.
        
        Args:
            status: Final status - 'analyzed' (success) or 'error' (failed)
        """
        try:
            from service.websocket_streamer import get_websocket_streamer
            
            streamer = await get_websocket_streamer()
            if streamer:
                # Extract file_id from unified blob path: uploads/{session_id}/{file_id}/{filename}
                # The URI looks like: https://storage.blob.../a2a-files/uploads/{session_id}/{file_id}/{filename}?sas=...
                file_id = None
                try:
                    # Parse the URI to extract file_id from path
                    from urllib.parse import urlparse
                    parsed = urlparse(uri)
                    path_parts = parsed.path.split('/')
                    # Find 'uploads' in path and get file_id (2 positions after session_id)
                    for i, part in enumerate(path_parts):
                        if part == 'uploads' and i + 2 < len(path_parts):
                            # path_parts[i+1] = session_id, path_parts[i+2] = file_id
                            file_id = path_parts[i + 2]
                            break
                except Exception as e:
                    print(f"⚠️ Could not parse file_id from URI {uri}: {e}")
                
                # Fallback: hash the blob path (sans SAS query params) for deterministic ID
                if not file_id:
                    import hashlib
                    _parsed = urlparse(uri)
                    _base_uri = f"{_parsed.scheme}://{_parsed.netloc}{_parsed.path}"
                    file_id = hashlib.md5(_base_uri.encode()).hexdigest()[:16]
                    print(f"⚠️ Using fallback hash ID for {filename}: {file_id}")
                
                event_data = {
                    "fileId": file_id,
                    "filename": filename,
                    "status": status,  # 'analyzed' or 'error'
                    "contextId": context_id
                }
                
                await streamer._send_event("file_processing_completed", event_data, context_id)
                print(f"📤 File {status} event sent: {filename} (id={file_id})")
                log_debug(f"File analyzed event sent: {filename}")
                return True
            else:
                log_debug(f"No WebSocket streamer available for file analyzed event: {filename}")
                return False
        except Exception as e:
            print(f"❌ Error emitting file analyzed event: {e}")
            log_debug(f"Error emitting file analyzed event: {e}")
            return False

    async def _emit_granular_agent_event(self, agent_name: str, status_text: str, context_id: str = None, event_type: str = None, metadata: dict = None):
        """Emit granular agent activity event to WebSocket for thinking box visibility.
        
        Args:
            agent_name: Name of the agent emitting the event
            status_text: Human-readable status text
            context_id: Routing context ID
            event_type: Structured event type for frontend rendering. One of:
                - "phase": Workflow phase marker (e.g., "Planning step 1...")
                - "reasoning": AI planner reasoning text
                - "agent_start": Agent is starting work
                - "agent_progress": Agent is working (tool calls, status updates)
                - "agent_complete": Agent finished successfully
                - "agent_error": Agent encountered an error
                - "tool_call": MCP tool being called
                - "info": General informational message
            metadata: Optional dict with extra structured data (e.g., step_number, tool_name, agent_output)
        """
        try:
            from service.websocket_streamer import get_websocket_streamer
            from utils.tenant import get_conversation_from_context
            
            streamer = await get_websocket_streamer()
            if streamer:
                # Use contextvars for async-safe context_id (prevents race conditions)
                stored_host_context = _current_context_id.get() or getattr(self, '_current_host_context_id', None)
                routing_context_id = context_id or stored_host_context
                
                if not routing_context_id:
                    log_debug(f"⚠️ [_emit_granular_agent_event] No context_id for {agent_name}, skipping")
                    return
                
                # Extract conversationId from contextId (format: session_id::conversation_id)
                conversation_id = get_conversation_from_context(routing_context_id)
                
                event_data = {
                    "agentName": agent_name,
                    "content": status_text,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "contextId": routing_context_id,
                    "conversationId": conversation_id,
                }
                
                # Add structured type if provided
                if event_type:
                    event_data["eventType"] = event_type
                
                # Add metadata if provided
                if metadata:
                    event_data["metadata"] = metadata

                # Include parallel_call_id if set (for differentiating parallel calls to same agent)
                parallel_call_id = _current_parallel_call_id.get()
                if parallel_call_id:
                    if "metadata" not in event_data:
                        event_data["metadata"] = {}
                    event_data["metadata"]["parallel_call_id"] = parallel_call_id

                # DEBUG: Log what we're sending
                print(f"📡 [WS_EMIT] Sending remote_agent_activity: agent={agent_name}, type={event_type}, convId={conversation_id}")
                
                success = await streamer._send_event("remote_agent_activity", event_data, routing_context_id)
                if not success:
                    log_debug(f"Failed to stream remote agent activity: {agent_name}")
                    print(f"❌ [WS_EMIT] Failed to send event for {agent_name}")
                else:
                    print(f"✅ [WS_EMIT] Successfully sent event for {agent_name}")
            else:
                log_debug(f"WebSocket streamer not available for remote agent activity")
                print(f"⚠️ [WS_EMIT] No WebSocket streamer available for {agent_name}")
                
        except Exception as e:
            log_debug(f"Error emitting granular agent event: {e}")
            print(f"❌ [WS_EMIT] Error emitting event for {agent_name}: {e}")

    async def _emit_plan_update(self, plan, context_id: str, reasoning: str = None):
        """Emit the full workflow plan to WebSocket for frontend rendering.
        
        This is the source of truth for workflow state. The frontend should render
        the plan directly instead of piecing together individual events.
        
        Args:
            plan: AgentModePlan Pydantic model with goal, tasks, and state
            context_id: Routing context ID
            reasoning: Optional orchestrator reasoning for current step
        """
        try:
            from service.websocket_streamer import get_websocket_streamer
            from utils.tenant import get_conversation_from_context
            
            streamer = await get_websocket_streamer()
            if streamer:
                stored_host_context = _current_context_id.get() or getattr(self, '_current_host_context_id', None)
                routing_context_id = context_id or stored_host_context
                
                if not routing_context_id:
                    log_debug(f"⚠️ [_emit_plan_update] No context_id, skipping")
                    return
                
                conversation_id = get_conversation_from_context(routing_context_id)
                
                # Serialize the plan - handle both Pydantic models and dicts
                if hasattr(plan, 'model_dump'):
                    plan_data = plan.model_dump(mode='json')
                else:
                    plan_data = plan
                
                event_data = {
                    "plan": plan_data,
                    "reasoning": reasoning,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "contextId": routing_context_id,
                    "conversationId": conversation_id,
                }
                
                success = await streamer._send_event("plan_update", event_data, routing_context_id)
                if success:
                    log_debug(f"📋 Plan update emitted: {len(plan_data.get('tasks', []))} tasks")
                else:
                    log_debug(f"Failed to stream plan update")
            else:
                log_debug(f"WebSocket streamer not available for plan update")
                
        except Exception as e:
            log_debug(f"Error emitting plan update: {e}")

    async def _emit_status_event(self, status_text: str, context_id: str, event_type: str = "info"):
        """Emit status event to WebSocket for real-time frontend updates."""
        await self._emit_granular_agent_event("foundry-host-agent", status_text, context_id, event_type=event_type)

    async def _emit_text_chunk(self, chunk: str, context_id: str):
        """
        Emit text chunk to WebSocket for real-time streaming display.
        
        This enables ChatGPT-style token-by-token streaming in the UI.
        """
        try:
            from service.websocket_streamer import get_websocket_streamer
            websocket_streamer = await get_websocket_streamer()
            
            if websocket_streamer:
                await websocket_streamer._send_event(
                    "message_chunk",
                    {
                        "contextId": context_id,
                        "chunk": chunk,
                        "timestamp": datetime.now().isoformat()
                    },
                    partition_key=context_id
                )
        except Exception as e:
            log_error(f"Failed to emit text chunk: {e}")

    def _emit_task_event(self, task: TaskCallbackArg, agent_card: AgentCard):
        """Emit event for task callback, with enhanced agent name context for UI status tracking."""
        agent_name = agent_card.name
        
        # WORKFLOW MODE: Suppress redundant status events from remote agents
        contextId = get_context_id(task, None)
        if contextId:
            try:
                session_ctx = self.get_session_context(contextId)
                if session_ctx.agent_mode:
                    if hasattr(task, 'kind') and task.kind == 'status-update':
                        if hasattr(task, 'status') and task.status:
                            state_obj = getattr(task.status, 'state', 'working')
                            task_state = state_obj.value if hasattr(state_obj, 'value') else str(state_obj)
                            
                            # Suppress intermediate states in workflow mode
                            if task_state in ['working', 'submitted', 'pending']:
                                return task
            except Exception:
                pass
        
        content = None
        task_id = None
        task_state = None
        
        # Extract task state and ID
        if hasattr(task, 'kind') and task.kind == 'status-update':
            task_id = get_task_id(task, None)
            if hasattr(task, 'status') and task.status:
                state_obj = getattr(task.status, 'state', 'working')
                task_state = state_obj.value if hasattr(state_obj, 'value') else str(state_obj)
            else:
                task_state = 'working'
            
            if hasattr(task, 'status') and task.status and task.status.message:
                content = task.status.message
            else:
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
            task_state = 'completed'
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
            if hasattr(task.status, 'state'):
                if hasattr(task.status.state, 'value'):
                    task_state = task.status.state.value
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
        
        # Create Event object and stream to WebSocket
        if content:
            event_obj = type('Event', (), {
                'id': str(uuid.uuid4()),
                'actor': agent_card.name,
                'content': content,
                'timestamp': datetime.now(timezone.utc).timestamp(),
            })()
            
            if hasattr(self, '_host_manager') and self._host_manager:
                self._host_manager.add_event(event_obj)
            
            try:
                async def stream_task_event():
                    try:
                        from service.websocket_streamer import get_websocket_streamer

                        streamer = await get_websocket_streamer()
                        if not streamer:
                            return

                        text_content = ""
                        if content and hasattr(content, 'parts'):
                            for part in content.parts:
                                if hasattr(part, 'root') and hasattr(part.root, 'text'):
                                    text_content = part.root.text
                                    break
                        
                        # Suppress full response in workflow mode
                        try:
                            session_ctx = self.get_session_context(contextId)
                            if session_ctx.agent_mode and text_content and task_state == 'completed':
                                text_content = ""
                        except Exception:
                            pass

                        # Use contextvars for async-safe context_id (prevents race conditions)
                        routing_context_id = (_current_context_id.get() or
                                             getattr(self, '_current_host_context_id', None) or 
                                             contextId or 
                                             getattr(self, 'default_contextId', str(uuid.uuid4())))
                        
                        event_data = {
                            "taskId": task_id or str(uuid.uuid4()),
                            "conversationId": routing_context_id or str(uuid.uuid4()),
                            "contextId": routing_context_id,
                            "state": task_state,
                            "artifactsCount": len(getattr(task, 'artifacts', [])),
                            "agentName": agent_card.name,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "content": text_content if text_content else None,
                        }
                        
                        if agent_card.name in self.agent_token_usage:
                            event_data["tokenUsage"] = self.agent_token_usage[agent_card.name]

                        event_type = "task_updated"
                        if not hasattr(task, 'kind'):
                            event_type = "task_created"
                        
                        await streamer._send_event(event_type, event_data, routing_context_id)
                        
                    except Exception as e:
                        log_error(f"Error streaming A2A task event: {e}")

                asyncio.create_task(stream_task_event())

            except Exception:
                pass

    def _emit_agent_registration_event(self, agent_card: AgentCard):
        """Emit agent registration event to WebSocket for UI sidebar visibility."""
        try:
            routing_context_id = "system_agent_registry"
            
            async def stream_registration_event():
                try:
                    from service.websocket_streamer import get_websocket_streamer

                    streamer = await get_websocket_streamer()
                    if not streamer:
                        return

                    event_data = {
                        "agentName": agent_card.name,
                        "status": "registered",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "avatar": "/placeholder.svg?height=32&width=32",
                        "agentPath": getattr(agent_card, 'url', ''),
                    }

                    await streamer._send_event("agent_registered", event_data, routing_context_id)
                except Exception as e:
                    log_error(f"Error streaming agent registration event: {e}")
            
            asyncio.create_task(stream_registration_event())
            
        except Exception:
            pass
