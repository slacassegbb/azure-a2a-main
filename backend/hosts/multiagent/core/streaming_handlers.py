"""
Streaming Handlers - Task callback and streaming methods for FoundryHostAgent2.

This module contains methods related to:
- Remote agent task callbacks
- Streaming event handling
- Task status display and updates
- Response content extraction

These are extracted from foundry_agent_a2a.py to improve code organization.
The class is designed to be used as a mixin with FoundryHostAgent2.
"""

import asyncio
import re
import uuid
from typing import Any, Optional

# Import logging utilities
import sys
from pathlib import Path
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from log_config import log_debug, log_info

from a2a.types import (
    AgentCard,
    Part,
    Task,
    TaskState,
    TextPart,
)

from ..remote_agent_connection import TaskCallbackArg
from ..utils import get_context_id, get_task_id


class StreamingHandlers:
    """
    Mixin class providing streaming and task callback handler methods.
    
    This class is designed to be inherited by FoundryHostAgent2 along with
    other mixin classes. All methods use 'self' and expect the main class
    to have the required attributes (cards, remote_agent_connections, etc).
    """

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
            async def stream_activity():
                try:
                    await self._emit_granular_agent_event(
                        agent_name, status_text, event_type="agent_progress"
                    )
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

    def _default_task_callback(self, event: TaskCallbackArg, agent_card: AgentCard) -> Task:
        """Default task callback optimized for streaming remote agent execution.
        
        CONSOLIDATED: Uses _emit_task_event as the SINGLE source of truth for all
        remote agent status updates to prevent duplicate events in the UI.
        """
        agent_name = agent_card.name
        print(f"🔔 [CALLBACK] Task callback invoked from {agent_name}: {type(event).__name__}")
        import sys
        sys.stdout.flush()
        log_debug(f"[STREAMING] Task callback from {agent_name}: {type(event).__name__}")
        
        # Keep session context task mapping in sync per agent
        try:
            context_id_cb = get_context_id(event, None)
            task_id_cb = get_task_id(event, None)
            print(f"🔔 [CALLBACK] context_id_cb='{context_id_cb}', task_id_cb='{task_id_cb}'")
            if context_id_cb and task_id_cb:
                session_ctx = self.get_session_context(context_id_cb)
                session_ctx.agent_task_ids[agent_name] = task_id_cb
                # If status-update, capture state per agent
                if hasattr(event, 'kind') and getattr(event, 'kind', '') == 'status-update':
                    state_obj = getattr(getattr(event, 'status', None), 'state', None)
                    if state_obj is not None:
                        state_str = state_obj.value if hasattr(state_obj, 'value') else str(state_obj)
                        print(f"🔔 [CALLBACK] Setting agent_task_states['{agent_name}'] = '{state_str}'")
                        session_ctx.agent_task_states[agent_name] = state_str
                        
                        # HUMAN-IN-THE-LOOP: Track input_required state from remote agents
                        if state_str == 'input_required' or state_str == 'input-required':
                            session_ctx.pending_input_agent = agent_name
                            session_ctx.pending_input_task_id = task_id_cb
                            print(f"🔄 [HITL CALLBACK] Streaming callback detected input_required from '{agent_name}', context_id='{context_id_cb}'")
                            log_info(f"🔄 [HITL] Callback detected input_required from '{agent_name}', setting pending_input_agent (task_id: {task_id_cb})")
                        
                        # BUGFIX: Clear pending_input_agent when task completes or fails
                        # This prevents stale input_required flags from blocking subsequent workflow steps
                        elif state_str in ('completed', 'failed', 'canceled', 'cancelled'):
                            if session_ctx.pending_input_agent == agent_name:
                                print(f"🧹 [HITL CALLBACK] Clearing pending_input_agent (was '{agent_name}') - task {state_str}")
                                log_info(f"🧹 [HITL] Clearing pending_input_agent for '{agent_name}' - task {state_str}")
                                session_ctx.pending_input_agent = None
                                session_ctx.pending_input_task_id = None
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
            print(f"🔔 [STREAMING] Received event from {agent_name}: kind={event_kind}")
            
            # Only emit status-update and artifact-update to UI (NOT 'task' events)
            if event_kind in ['artifact-update', 'status-update']:
                log_debug(f"[STREAMING] Emitting via _emit_task_event for {agent_name}: {event_kind}")
                print(f"📤 [STREAMING] Calling _emit_task_event for {agent_name}: {event_kind}")
                self._emit_task_event(event, agent_card)
                
                # NOTE: _emit_granular_agent_event is NOT called here anymore
                # The custom streaming callback in foundry_agent_a2a.py already emits these events
                # with proper host_context_id before calling _default_task_callback.
                # Emitting here caused duplicate remote_agent_activity events in the UI.
            
            elif event_kind == 'task':
                log_debug(f"[STREAMING] Skipping UI emit for 'task' event from {agent_name} (internal tracking only)")
                # NOTE: _emit_granular_agent_event is NOT called here anymore
                # The custom streaming callback in foundry_agent_a2a.py already emits these events
                # with proper host_context_id before calling _default_task_callback.
                # Emitting here caused duplicate remote_agent_activity events in the UI.
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
        # Note: These are fallbacks for events that don't have taskId/contextId
        # This shouldn't happen in normal flow but protects against malformed events
        task_id = get_task_id(event, str(uuid.uuid4()))
        contextId_from_event = get_context_id(event, None)
        
        if not contextId_from_event:
            log_debug(f"⚠️ [_emit_task_event] Event from {agent_card.name} has no contextId, using UUID fallback")
            contextId = str(uuid.uuid4())
        else:
            contextId = contextId_from_event
        
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

    def _display_task_status_update(self, status_text: str, event: TaskCallbackArg):
        """Display a task status update in the UI as a message."""
        try:
            from a2a.types import Message, TextPart, Part
            
            message_id = str(uuid.uuid4())
            context_id = getattr(event, 'contextId', getattr(self._current_task, 'contextId', str(uuid.uuid4())))
            
            status_message = Message(
                messageId=message_id,
                contextId=context_id,
                role="agent",
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
            log_debug(f"⚠️ Error extracting message content: {e}")
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
            texts = [StreamingHandlers._extract_text_from_response(item) for item in obj]
            return "\n".join(t for t in texts if t)
        # Fallback - but avoid ugly repr
        result = str(obj)
        # If it looks like a Python repr, try to extract the text
        if result.startswith("kind='text'") and "text='" in result:
            match = re.search(r"text='([^']*)'", result)
            if match:
                return match.group(1).replace("\\n", "\n")
        return result
