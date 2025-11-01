from typing import Callable
import sys
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

from log_config import log_debug

TaskCallbackArg = Task | TaskStatusUpdateEvent | TaskArtifactUpdateEvent
TaskUpdateCallback = Callable[[TaskCallbackArg, AgentCard], Task]


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
        streaming_supported = bool(getattr(capabilities, 'streaming', False)) if capabilities else False

        if streaming_supported:
            try:
                task = None
                async for response in self.agent_client.send_message_streaming(
                    SendStreamingMessageRequest(id=str(uuid4()), params=request)
                ):
                    if not response.root.result:
                        log_debug(f"RemoteAgentConnections.send_message (streaming): response.root.result is None or error:: {response.root}")
                        return response.root.error
                    # In the case a message is returned, that is the end of the interaction.
                    event = response.root.result
                    log_debug(f"RemoteAgentConnections.send_message (streaming): event:: {event}")
                    if isinstance(event, Message):
                        return event

                    # Otherwise we are in the Task + TaskUpdate cycle.
                    if callback and event:
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
        response = await self.agent_client.send_message(
            SendMessageRequest(id=str(uuid4()), params=request)
        )
        log_debug(f"RemoteAgentConnections.send_message (non-streaming): response.root:: {response.root}")
        if isinstance(response.root, JSONRPCErrorResponse):
            return response.root.error
        if isinstance(response.root.result, Message):
            return response.root.result
        if callback:
            callback(response.root.result, self.card)
        return response.root.result
