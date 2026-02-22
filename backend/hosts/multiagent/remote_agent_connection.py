from typing import Callable
import sys
import asyncio
from pathlib import Path
import httpx
from a2a.client import A2AClient
from a2a.client.errors import A2AClientHTTPError
from a2a.types import (
    AgentCard,
    Task,
    Message,
    MessageSendParams,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
    SendMessageRequest,
    SendStreamingMessageRequest,
    JSONRPCErrorResponse,
)
from uuid import uuid4

# Add backend directory to path for log_config import
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from log_config import log_debug, log_info, log_warning, log_error

TaskCallbackArg = Task | TaskStatusUpdateEvent | TaskArtifactUpdateEvent
TaskUpdateCallback = Callable[[TaskCallbackArg, AgentCard], Task]

# Timeout for agent message calls (3 minutes - generous for slow agents)
AGENT_MESSAGE_TIMEOUT = 180.0


class RemoteAgentConnections:
    """A class to hold the connections to the remote agents."""

    def __init__(self, client: httpx.AsyncClient, agent_card: AgentCard, task_callback: TaskUpdateCallback | None = None):
        self.agent_client = A2AClient(client, agent_card)
        self.card = agent_card
        self.pending_tasks = set()
        self.task_callback = task_callback

    def get_agent(self) -> AgentCard:
        return self.card

    async def send_message(
        self,
        request: MessageSendParams,
        task_callback: TaskUpdateCallback | None = None,
    ) -> Task | Message | None:
        # Use provided callback or fall back to instance callback
        callback = task_callback or self.task_callback
        capabilities = getattr(self.card, 'capabilities', None)
        
        # Debug: Log capabilities to understand the structure
        log_debug(f"[STREAMING] Agent: {self.card.name}")
        log_debug(f"[STREAMING] Capabilities type: {type(capabilities)}")
        log_debug(f"[STREAMING] Capabilities value: {capabilities}")
        
        # Check for streaming support - handle both dict and object cases
        streaming_supported = False
        if capabilities:
            if isinstance(capabilities, dict):
                streaming_supported = bool(capabilities.get('streaming', False))
                log_debug(f"[STREAMING] Dict access: streaming={streaming_supported}")
            elif hasattr(capabilities, 'streaming'):
                streaming_supported = bool(getattr(capabilities, 'streaming', False))
                log_debug(f"[STREAMING] Attr access: streaming={streaming_supported}")

        log_debug(f"[STREAMING] Final streaming_supported: {streaming_supported}")

        if streaming_supported:
            try:
                log_debug(f"[STREAMING] Starting streaming for {self.card.name}")
                task = None
                async for response in self.agent_client.send_message_streaming(
                    SendStreamingMessageRequest(id=str(uuid4()), params=request)
                ):
                    if not response.root.result:
                        log_debug(f"RemoteAgentConnections.send_message (streaming): response.root.result is None or error:: {response.root}")
                        return response.root.error
                    # In the case a message is returned, that is the end of the interaction.
                    event = response.root.result
                    log_debug(f"[STREAMING] Event from {self.card.name}: {type(event).__name__}")
                    log_debug(f"RemoteAgentConnections.send_message (streaming): event:: {event}")
                    if isinstance(event, Message):
                        return event

                    # Otherwise we are in the Task + TaskUpdate cycle.
                    if callback and event:
                        log_debug(f"[STREAMING] Invoking callback for {self.card.name}")
                        task = callback(event, self.card)
                    if hasattr(event, 'final') and event.final:
                        break
                log_debug(f"RemoteAgentConnections.send_message (streaming): final task:: {task}")
                return task
            except A2AClientHTTPError as exc:
                error_text = str(exc)
                if exc.status_code == 400 and 'Invalid SSE response' in error_text:
                    log_debug(f"Streaming not supported for {self.card.name}; falling back to non-streaming. Error: {error_text}")
                    if capabilities and hasattr(capabilities, 'streaming'):
                        try:
                            capabilities.streaming = False
                        except Exception:
                            pass
                    streaming_supported = False
                else:
                    raise

        # Non-streaming fallback path (either not supported or streaming failed)
        try:
            log_debug(f"[SEND_MESSAGE] Calling {self.card.name} (non-streaming, timeout={AGENT_MESSAGE_TIMEOUT}s)...")
            response = await asyncio.wait_for(
                self.agent_client.send_message(
                    SendMessageRequest(id=str(uuid4()), params=request)
                ),
                timeout=AGENT_MESSAGE_TIMEOUT
            )
            log_debug(f"[SEND_MESSAGE] Got response from {self.card.name}")
        except asyncio.TimeoutError:
            log_warning(f"[SEND_MESSAGE] TIMEOUT calling {self.card.name} after {AGENT_MESSAGE_TIMEOUT}s")
            raise TimeoutError(f"Agent {self.card.name} did not respond within {AGENT_MESSAGE_TIMEOUT} seconds")
        
        log_debug(f"RemoteAgentConnections.send_message (non-streaming): response.root:: {response.root}")
        if isinstance(response.root, JSONRPCErrorResponse):
            return response.root.error
        if isinstance(response.root.result, Message):
            return response.root.result
        if callback:
            callback(response.root.result, self.card)
        return response.root.result

    async def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a running task on this remote agent.
        
        Note: A2A protocol cancel support varies by agent implementation.
        This attempts to cancel but gracefully handles agents that don't support it.
        
        Args:
            task_id: The A2A task ID to cancel
            
        Returns:
            True if cancel was acknowledged, False otherwise
        """
        try:
            log_debug(f"[CANCEL] Attempting to cancel task {task_id} on {self.card.name}")
            
            # Check if the A2A client has a cancel method
            if hasattr(self.agent_client, 'cancel_task'):
                await self.agent_client.cancel_task(task_id)
                log_debug(f"[CANCEL] Task {task_id} cancelled on {self.card.name}")
                return True
            else:
                # Fallback: Try HTTP POST to cancel endpoint
                # A2A protocol defines /tasks/cancel as the cancel endpoint
                base_url = getattr(self.agent_client, 'base_url', None)
                if base_url and hasattr(self.agent_client, '_client'):
                    try:
                        response = await self.agent_client._client.post(
                            f"{base_url}/tasks/cancel",
                            json={"task_id": task_id}
                        )
                        if response.status_code == 200:
                            log_debug(f"[CANCEL] Task {task_id} cancelled via HTTP on {self.card.name}")
                            return True
                    except Exception as http_err:
                        log_debug(f"[CANCEL] HTTP cancel failed for {self.card.name}: {http_err}")

                log_debug(f"[CANCEL] Agent {self.card.name} doesn't support cancel, ignoring")
                return False
                
        except Exception as e:
            log_debug(f"[CANCEL] Error cancelling task on {self.card.name}: {e}")
            return False
