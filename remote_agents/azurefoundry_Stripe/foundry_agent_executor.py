"""
AI Foundry Agent Executor for A2A framework - Stripe Agent.
Adapted from the QuickBooks agent executor pattern.
"""
import asyncio
import logging
import base64
import os
import tempfile
import time
from typing import Optional, Dict, Any, List

from foundry_agent import FoundryStripeAgent

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
    An AgentExecutor that runs Azure AI Foundry Stripe agents.
    """

    # Class-level shared agent instance
    _shared_foundry_agent: Optional[FoundryStripeAgent] = None
    _agent_lock = asyncio.Lock()
    _last_request_time: float = 0
    _min_request_interval: float = 1.0
    _request_semaphore = asyncio.Semaphore(3)
    _api_call_count: int = 0
    _api_call_window_start: float = 0
    _max_api_calls_per_minute: int = 30
    _startup_complete: bool = False

    @classmethod
    async def get_shared_agent(cls) -> Optional[FoundryStripeAgent]:
        """Get the shared agent that was initialized at startup."""
        async with cls._agent_lock:
            return cls._shared_foundry_agent
    
    @classmethod
    async def initialize_at_startup(cls) -> None:
        """Initialize the shared agent at startup."""
        async with cls._agent_lock:
            if not cls._shared_foundry_agent:
                logger.info("🚀 Initializing Stripe Foundry agent at startup...")
                try:
                    cls._shared_foundry_agent = FoundryStripeAgent()
                    await cls._shared_foundry_agent.create_agent()
                    cls._startup_complete = True
                    logger.info("✅ Stripe Foundry agent startup initialization completed")
                except Exception as e:
                    logger.error(f"❌ Failed to initialize Stripe agent at startup: {e}")
                    cls._shared_foundry_agent = None
                    cls._startup_complete = False
                    raise

    def __init__(self, card: AgentCard):
        self._active_sessions: Dict[str, str] = {}
        self._waiting_for_input: Dict[str, str] = {}
        self._pending_updaters: Dict[str, TaskUpdater] = {}
        self._input_events: Dict[str, asyncio.Event] = {}

    async def _get_or_create_agent(self) -> FoundryStripeAgent:
        """Get the shared Foundry Stripe agent."""
        async with FoundryAgentExecutor._agent_lock:
            if not FoundryAgentExecutor._shared_foundry_agent:
                if FoundryAgentExecutor._startup_complete:
                    raise RuntimeError("Agent startup initialization failed")
                
                logger.warning("⚠️ Agent not initialized at startup, falling back to lazy creation...")
                FoundryAgentExecutor._shared_foundry_agent = FoundryStripeAgent()
                await FoundryAgentExecutor._shared_foundry_agent.create_agent()
                logger.info("Fallback Stripe agent creation completed")
            return FoundryAgentExecutor._shared_foundry_agent

    async def _get_or_create_session(
        self,
        context_id: str,
        agent: Optional[FoundryStripeAgent] = None,
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

    async def _process_request(
        self,
        message_parts: List[Part],
        context_id: str,
        task_updater: TaskUpdater,
        request_context: RequestContext = None,
    ) -> None:
        try:
            user_message = self._convert_parts_to_text(message_parts)
            logger.info(f"Processing Stripe request: {user_message[:100]}...")
            
            agent = await self._get_or_create_agent()
            # Reuse session for same context_id to maintain conversation continuity
            session_id = await self._get_or_create_session(context_id, agent, force_new=False)

            # Use streaming to filter out status messages (like QuickBooks executor)
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
                        # Send as real-time status update, DON'T add to responses
                        logger.info(f"📡 Sending task_updater.update_status(working) for: {tool_description}")
                        await task_updater.update_status(
                            TaskState.working,
                            message=Message(
                                role="agent",
                                messageId=str(__import__('uuid').uuid4()),
                                parts=[TextPart(text=f"🛠️ Remote agent executing: {tool_description}")],
                                contextId=context_id
                            )
                        )
                # Check if this is an error
                elif event.startswith("Error:") or event.startswith("❌"):
                    logger.error(f"❌ Stripe agent error: {event}")
                    await task_updater.failed(
                        message=Message(
                            role="agent",
                            messageId=str(__import__('uuid').uuid4()),
                            parts=[TextPart(text=event)],
                            contextId=context_id
                        )
                    )
                    return
                else:
                    # This is actual response text - keep it
                    responses.append(event)

            # Join all response text (excluding status messages)
            response = "\n".join(responses) if responses else None

            if response:
                response_preview = response[:500] + "..." if len(response) > 500 else response
                logger.info(f"📤 Stripe agent response: {response_preview}")
                
                import uuid
                
                # Check if agent needs user input (HITL pattern)
                if response.strip().startswith("NEEDS_INPUT:"):
                    # Extract the question (remove the marker)
                    question = response.replace("NEEDS_INPUT:", "", 1).strip()
                    logger.info(f"⏸️ Stripe agent needs user input: {question[:100]}...")
                    
                    # Store context for resume
                    self._waiting_for_input[context_id] = {
                        "question": question,
                        "session_id": session_id,
                    }
                    
                    message_parts = [TextPart(text=question)]
                    
                    # Add token usage if available
                    if hasattr(agent, 'last_token_usage') and agent.last_token_usage:
                        message_parts.append(DataPart(data={
                            'type': 'token_usage',
                            **agent.last_token_usage
                        }))
                    
                    # Signal input_required - workflow will pause and resume when user responds
                    # CRITICAL: Must set final=True so the SSE stream knows this is the last event
                    await task_updater.update_status(
                        TaskState.input_required,
                        message=Message(
                            role="agent",
                            messageId=str(uuid.uuid4()),
                            parts=message_parts,
                            contextId=context_id
                        ),
                        final=True  # This closes the event queue properly
                    )
                    logger.info(f"📱 Returning input_required state - waiting for user response")
                    return
                
                # Normal completion
                message_parts = [TextPart(text=response)]
                
                # Add token usage if available
                if hasattr(agent, 'last_token_usage') and agent.last_token_usage:
                    message_parts.append(DataPart(data={
                        'type': 'token_usage',
                        **agent.last_token_usage
                    }))
                
                await task_updater.complete(
                    message=Message(
                        role="agent",
                        messageId=str(uuid.uuid4()),
                        parts=message_parts,
                        contextId=context_id
                    )
                )
            else:
                logger.warning("⚠️ No response from Stripe agent")
                import uuid
                await task_updater.complete(
                    message=Message(
                        role="agent",
                        messageId=str(uuid.uuid4()),
                        parts=[TextPart(text="No response generated")],
                        contextId=context_id
                    )
                )
                    
        except Exception as e:
            logger.error(f"Error processing Stripe request: {e}")
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
        logger.info(f"Executing Stripe request for context {context.context_id}")
        
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
            logger.info(f"Completed Stripe execution for {context.context_id}")

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
        logger.info("Stripe executor cleaned up")


def create_foundry_agent_executor(card: AgentCard) -> FoundryAgentExecutor:
    return FoundryAgentExecutor(card)


async def initialize_foundry_agents_at_startup():
    """Initialize shared Stripe agent resources at application startup."""
    await FoundryAgentExecutor.initialize_at_startup()
