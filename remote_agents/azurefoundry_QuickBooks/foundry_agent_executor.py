"""
AI Foundry Agent Executor for A2A framework - QuickBooks Agent.
Uses the Responses API with native MCP tool support.
"""
import asyncio
import logging
import base64
import os
import tempfile
import time
from typing import Optional, Dict, Any, List

from foundry_agent import FoundryQuickBooksAgent

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    AgentCard,
    FilePart,
    FileWithBytes,
    FileWithUri,
    DataPart,
    Message,
    Part,
    TaskState,
    TextPart,
)
from a2a.utils.message import new_agent_text_message

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class FoundryAgentExecutor(AgentExecutor):
    """
    An AgentExecutor that runs Azure AI Foundry QuickBooks agents.
    """

    # Class-level shared agent instance
    _shared_foundry_agent: Optional[FoundryQuickBooksAgent] = None
    _agent_lock = asyncio.Lock()
    _last_request_time: float = 0
    _min_request_interval: float = 1.0
    _request_semaphore = asyncio.Semaphore(3)
    _api_call_count: int = 0
    _api_call_window_start: float = 0
    _max_api_calls_per_minute: int = 30
    _startup_complete: bool = False

    @classmethod
    async def get_shared_agent(cls) -> Optional[FoundryQuickBooksAgent]:
        """Get the shared agent that was initialized at startup."""
        async with cls._agent_lock:
            return cls._shared_foundry_agent

    @classmethod
    async def initialize_at_startup(cls) -> None:
        """Initialize the shared agent at startup."""
        async with cls._agent_lock:
            if not cls._shared_foundry_agent:
                logger.info("🚀 Initializing QuickBooks Foundry agent at startup...")
                try:
                    cls._shared_foundry_agent = FoundryQuickBooksAgent()
                    await cls._shared_foundry_agent.create_agent()
                    cls._startup_complete = True
                    logger.info("✅ QuickBooks Foundry agent startup initialization completed")
                except Exception as e:
                    logger.error(f"❌ Failed to initialize QuickBooks agent at startup: {e}")
                    cls._shared_foundry_agent = None
                    cls._startup_complete = False
                    raise

    def __init__(self, card: AgentCard):
        self._active_sessions: Dict[str, str] = {}
        self._waiting_for_input: Dict[str, str] = {}
        self._pending_updaters: Dict[str, TaskUpdater] = {}
        self._input_events: Dict[str, asyncio.Event] = {}

    async def _get_or_create_agent(self) -> FoundryQuickBooksAgent:
        """Get the shared Foundry QuickBooks agent."""
        async with FoundryAgentExecutor._agent_lock:
            if not FoundryAgentExecutor._shared_foundry_agent:
                if FoundryAgentExecutor._startup_complete:
                    raise RuntimeError("Agent startup initialization failed")

                logger.warning("⚠️ Agent not initialized at startup, falling back to lazy creation...")
                FoundryAgentExecutor._shared_foundry_agent = FoundryQuickBooksAgent()
                await FoundryAgentExecutor._shared_foundry_agent.create_agent()
                logger.info("Fallback QuickBooks agent creation completed")
            return FoundryAgentExecutor._shared_foundry_agent

    async def _get_or_create_session(
        self,
        context_id: str,
        agent: Optional[FoundryQuickBooksAgent] = None,
        force_new: bool = False
    ) -> str:
        if agent is None:
            agent = await self._get_or_create_agent()
        if force_new or context_id not in self._active_sessions:
            session_id = await agent.create_session()
            logger.info(f"Created new session {session_id} for context: {context_id}")
            self._active_sessions[context_id] = session_id
            return session_id
        return self._active_sessions[context_id]

    def _notify_ui_of_pending_request(self, context_id: str, request_text: str):
        """Log pending requests so dashboards can poll executor state."""
        logger.info(
            "UI pending request update",
            extra={"context_id": context_id, "request_preview": request_text[:120]}
        )

    async def send_human_response(self, context_id: str, human_response: str) -> bool:
        """Send human response to complete a pending input_required task."""
        if context_id in self._waiting_for_input and context_id in self._pending_updaters:
            updater = self._pending_updaters[context_id]
            await updater.complete(
                message=new_agent_text_message(human_response, context_id=context_id)
            )
            if context_id in self._input_events:
                self._input_events[context_id].set()
            logger.info(f"Completed input_required task for context {context_id}")
            return True
        logger.warning(f"No pending input_required task for context {context_id}")
        return False

    async def _process_request(
        self,
        message_parts: List[Part],
        context_id: str,
        task_updater: TaskUpdater,
        request_context: RequestContext = None,
    ) -> None:
        try:
            user_message = self._convert_parts_to_text(message_parts)
            logger.info(f"Processing QuickBooks request: {user_message[:100]}...")

            agent = await self._get_or_create_agent()
            # Reuse session for same context_id to maintain conversation continuity
            session_id = await self._get_or_create_session(context_id, agent, force_new=False)

            # Use streaming to filter out status messages
            responses = []
            tools_called = []
            seen_tools = set()

            async for event in agent.run_conversation_stream(session_id, user_message):
                # Check if this is a tool call status message
                if event.startswith("🛠️ Remote agent executing:"):
                    tool_description = event.replace("🛠️ Remote agent executing: ", "").strip()
                    if tool_description not in seen_tools:
                        seen_tools.add(tool_description)
                        tools_called.append(tool_description)
                        # Send as real-time status update
                        logger.info(f"📡 Sending task_updater.update_status(working) for: {tool_description}")
                        await task_updater.update_status(
                            TaskState.working,
                            message=new_agent_text_message(
                                f"🛠️ Remote agent executing: {tool_description}", context_id=context_id
                            )
                        )
                # Check if this is a processing message
                elif event.startswith("🤖") or event.startswith("🧠") or event.startswith("🔍") or event.startswith("📝"):
                    await task_updater.update_status(
                        TaskState.working,
                        message=new_agent_text_message(event, context_id=context_id)
                    )
                # Check if this is an error
                elif event.startswith("Error:") or event.startswith("❌") or "Run Failed" in event:
                    # Check for unrecoverable auth errors
                    auth_error_keywords = [
                        "connection is inactive", "invalid_grant", "token expired",
                        "authentication required", "re-authenticate", "refresh token",
                        "unauthorized", "401"
                    ]
                    is_auth_error = any(kw.lower() in event.lower() for kw in auth_error_keywords)

                    error_msg = event
                    if is_auth_error:
                        error_msg = f"⚠️ QuickBooks authentication error: {event}. Please re-authenticate the QuickBooks connection manually."
                        logger.error(f"🔐 AUTH ERROR DETECTED: {event}")

                    await task_updater.failed(
                        message=new_agent_text_message(error_msg, context_id=context_id)
                    )
                    return
                # Check for human escalation
                elif event.strip().upper().startswith("HUMAN_ESCALATION_REQUIRED"):
                    responses.append(event)

                    # Build the full request text with conversation history
                    conversation_history = ""
                    if request_context:
                        for attr_name in ('task', 'current_task'):
                            task_obj = getattr(request_context, attr_name, None)
                            if task_obj and hasattr(task_obj, 'history') and task_obj.history:
                                for msg in task_obj.history:
                                    if hasattr(msg, 'parts') and msg.parts:
                                        for part in msg.parts:
                                            if hasattr(part, 'root') and hasattr(part.root, 'text'):
                                                text = part.root.text
                                                if text.strip():
                                                    conversation_history += f"{text}\n"

                    full_request_text = ""
                    if conversation_history.strip():
                        full_request_text += f"Conversation History:\n{conversation_history}\n\n"
                    full_request_text += f"Current Request: {user_message}"

                    # Set up pending request for human input
                    self._waiting_for_input[context_id] = full_request_text
                    self._pending_updaters[context_id] = task_updater
                    self._input_events[context_id] = asyncio.Event()
                    self._notify_ui_of_pending_request(context_id, full_request_text)
                    await task_updater.update_status(
                        TaskState.input_required,
                        message=new_agent_text_message(
                            f"Human expert input required: {user_message}", context_id=context_id
                        ),
                        final=True
                    )
                    # Wait for human input
                    await self._input_events[context_id].wait()
                    # After human input, clean up
                    self._waiting_for_input.pop(context_id, None)
                    self._pending_updaters.pop(context_id, None)
                    self._input_events.pop(context_id, None)
                    return
                # Check for NEEDS_INPUT block (agent needs user clarification)
                elif "```NEEDS_INPUT" in event or event.strip().startswith("NEEDS_INPUT:"):
                    import re
                    block_pattern = r'```NEEDS_INPUT\s*\n(.*?)\n```END_NEEDS_INPUT'
                    block_match = re.search(block_pattern, event, re.DOTALL)

                    if block_match:
                        question = block_match.group(1).strip()
                    else:
                        question = event.replace("NEEDS_INPUT:", "", 1).strip()

                    logger.info(f"⏸️ QuickBooks agent needs user input: {question[:100]}...")

                    # Store context for resume
                    self._waiting_for_input[context_id] = {
                        "question": question,
                        "session_id": session_id,
                    }

                    import uuid
                    message_parts_out = [TextPart(text=question)]

                    # Add token usage if available
                    if hasattr(agent, 'last_token_usage') and agent.last_token_usage:
                        message_parts_out.append(DataPart(data={
                            'type': 'token_usage',
                            **agent.last_token_usage
                        }))

                    await task_updater.update_status(
                        TaskState.input_required,
                        message=Message(
                            role="agent",
                            messageId=str(uuid.uuid4()),
                            parts=message_parts_out,
                            contextId=context_id
                        ),
                        final=True
                    )
                    logger.info(f"📱 Returning input_required state - waiting for user response")
                    return
                else:
                    responses.append(event)

            # Emit the final response
            if responses:
                final_response = responses[-1]

                # Check if final response contains NEEDS_INPUT (in case it wasn't caught in streaming)
                import re
                block_pattern = r'```NEEDS_INPUT\s*\n(.*?)\n```END_NEEDS_INPUT'
                block_match = re.search(block_pattern, final_response, re.DOTALL)

                if block_match or final_response.strip().startswith("NEEDS_INPUT:"):
                    if block_match:
                        question = block_match.group(1).strip()
                    else:
                        question = final_response.replace("NEEDS_INPUT:", "", 1).strip()

                    logger.info(f"⏸️ QuickBooks agent needs user input (from final): {question[:100]}...")

                    self._waiting_for_input[context_id] = {
                        "question": question,
                        "session_id": session_id,
                    }

                    import uuid
                    message_parts_out = [TextPart(text=question)]

                    if hasattr(agent, 'last_token_usage') and agent.last_token_usage:
                        message_parts_out.append(DataPart(data={
                            'type': 'token_usage',
                            **agent.last_token_usage
                        }))

                    await task_updater.update_status(
                        TaskState.input_required,
                        message=Message(
                            role="agent",
                            messageId=str(uuid.uuid4()),
                            parts=message_parts_out,
                            contextId=context_id
                        ),
                        final=True
                    )
                    return

                response_preview = final_response[:500] + "..." if len(final_response) > 500 else final_response
                logger.info(f"📤 QuickBooks agent response: {response_preview}")

                # Check for auth errors in response text
                auth_error_keywords = [
                    "connection is inactive", "invalid_grant", "token expired",
                    "authentication required", "re-authenticate", "refresh token",
                    "unauthorized", "401", "oauth", "credentials"
                ]
                is_auth_error = any(kw.lower() in final_response.lower() for kw in auth_error_keywords)

                if is_auth_error:
                    logger.error(f"🔐 AUTH ERROR IN RESPONSE: {final_response[:200]}")
                    error_msg = f"⚠️ QuickBooks authentication error - please re-authenticate the connection manually.\n\nDetails: {final_response}"
                    await task_updater.failed(
                        message=new_agent_text_message(error_msg, context_id=context_id)
                    )
                    return

                import uuid

                if final_response.lstrip().startswith("Error:"):
                    await task_updater.failed(
                        message=new_agent_text_message(final_response, context_id=context_id)
                    )
                    return

                message_parts_out = [TextPart(text=final_response)]

                # Add token usage if available
                if hasattr(agent, 'last_token_usage') and agent.last_token_usage:
                    message_parts_out.append(DataPart(data={
                        'type': 'token_usage',
                        **agent.last_token_usage
                    }))
                    logger.info(f"💰 Including token usage in response: {agent.last_token_usage}")

                await task_updater.complete(
                    message=Message(
                        role="agent",
                        messageId=str(uuid.uuid4()),
                        parts=message_parts_out,
                        contextId=context_id
                    )
                )
            else:
                logger.warning("⚠️ No response from QuickBooks agent")
                import uuid

                message_parts_out = [TextPart(text="No response generated")]

                if hasattr(agent, 'last_token_usage') and agent.last_token_usage:
                    message_parts_out.append(DataPart(data={
                        'type': 'token_usage',
                        **agent.last_token_usage
                    }))

                await task_updater.failed(
                    message=Message(
                        role="agent",
                        messageId=str(uuid.uuid4()),
                        parts=message_parts_out,
                        contextId=context_id
                    )
                )

        except Exception as e:
            logger.error(f"Error processing QuickBooks request: {e}")
            await task_updater.failed(
                message=new_agent_text_message(f"Error: {e}", context_id=context_id)
            )

    def _convert_parts_to_text(self, parts: List[Part]) -> str:
        """Convert message parts to plain text."""
        texts: List[str] = []
        for part in parts:
            p = part.root
            if isinstance(p, TextPart):
                texts.append(p.text)
            elif isinstance(p, FilePart):
                if isinstance(p.file, FileWithUri):
                    texts.append(f"[File at {p.file.uri}]")
                elif isinstance(p.file, FileWithBytes):
                    try:
                        data = base64.b64decode(p.file.bytes)
                        fname = p.file.name or "file"
                        path = os.path.join(tempfile.gettempdir(), fname)
                        with open(path, 'wb') as f:
                            f.write(data)
                        texts.append(f"[Saved {fname} to {path}]")
                    except Exception as ex:
                        texts.append(f"[Error saving file: {ex}]")
            elif isinstance(p, DataPart):
                try:
                    import json as _json
                    payload = getattr(p, "data", None)
                    if payload is None:
                        payload = getattr(p, "value", None)
                    summary = payload if isinstance(payload, str) else _json.dumps(payload)[:500]
                    texts.append(f"[Data: {summary}]")
                except Exception:
                    texts.append("[Data payload]")
        return " ".join(texts)

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ):
        logger.info(f"Executing QuickBooks request for context {context.context_id}")

        async with FoundryAgentExecutor._request_semaphore:
            current_time = time.time()

            if current_time - FoundryAgentExecutor._api_call_window_start > 60:
                FoundryAgentExecutor._api_call_count = 0
                FoundryAgentExecutor._api_call_window_start = current_time

            if FoundryAgentExecutor._api_call_count >= FoundryAgentExecutor._max_api_calls_per_minute:
                logger.warning(f"⚠️ API call count at limit")

            FoundryAgentExecutor._api_call_count += 1
            FoundryAgentExecutor._last_request_time = time.time()

            updater = TaskUpdater(event_queue, context.task_id, context.context_id)
            if not context.current_task:
                await updater.submit()
            await updater.start_work()
            await self._process_request(
                context.message.parts if context.message else [],
                context.context_id,
                updater,
                context,
            )
            logger.info(f"Completed QuickBooks execution for {context.context_id}")

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        logger.info(f"Cancelling context {context.context_id}")
        if context.context_id in self._input_events:
            self._input_events[context.context_id].set()
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.failed(
            message=new_agent_text_message("Task cancelled", context_id=context.context_id)
        )

    async def cleanup(self):
        self._active_sessions.clear()
        self._waiting_for_input.clear()
        self._pending_updaters.clear()
        self._input_events.clear()
        logger.info("QuickBooks executor cleaned up")


def create_foundry_agent_executor(card: AgentCard) -> FoundryAgentExecutor:
    return FoundryAgentExecutor(card)


async def initialize_foundry_agents_at_startup():
    """Initialize shared QuickBooks agent resources at application startup."""
    await FoundryAgentExecutor.initialize_at_startup()
