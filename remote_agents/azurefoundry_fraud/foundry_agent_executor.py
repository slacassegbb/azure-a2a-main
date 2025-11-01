"""
AI Foundry Fraud Intelligence Agent Executor for A2A framework.
Adapted from ADK agent executor pattern to work with Azure AI Foundry agents for multi-line fraud detection.
"""
import asyncio
import logging
import base64
import os
import tempfile
import time
from typing import Optional, Dict, List

from foundry_agent import FoundryFraudAgent

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    AgentCard,
    FileWithBytes,
    FileWithUri,
    DataPart,
    Part,
    TaskState,
    TextPart,
)
from a2a.utils.message import new_agent_text_message

logger = logging.getLogger(__name__)
# Set to INFO to hide verbose debug logs (can be changed to DEBUG for troubleshooting)
logger.setLevel(logging.INFO)


class FoundryFraudAgentExecutor(AgentExecutor):
    """
    An AgentExecutor that runs Azure AI Foundry-based fraud intelligence agents for claim analysis and escalation support.
    Adapted from the ADK agent executor pattern.
    """

    # Class-level shared agent instance to avoid multiple agent creations
    _shared_foundry_agent: Optional[FoundryFraudAgent] = None
    _agent_lock = asyncio.Lock()
    _last_request_time: float = 0
    _min_request_interval: float = 5.0  # Increase to 5 seconds minimum between requests
    _request_semaphore = asyncio.Semaphore(1)  # Max 1 concurrent request
    _api_call_count: int = 0
    _api_call_window_start: float = 0
    _max_api_calls_per_minute: int = 15  # Much more conservative - 15 calls per minute
    _startup_complete: bool = False

    @classmethod
    async def get_shared_agent(cls) -> Optional[FoundryFraudAgent]:
        """Get the shared agent that was initialized at startup (if available)."""
        async with cls._agent_lock:
            return cls._shared_foundry_agent
    
    @classmethod
    async def initialize_at_startup(cls) -> None:
        """Initialize the shared fraud agent at startup instead of on first request."""
        async with cls._agent_lock:
            if not cls._shared_foundry_agent:
                logger.info("🚀 Initializing Foundry Fraud agent at startup...")
                try:
                    cls._shared_foundry_agent = FoundryFraudAgent()
                    await cls._shared_foundry_agent.create_agent()
                    cls._startup_complete = True
                    logger.info("✅ Foundry Fraud agent startup initialization completed successfully")
                except Exception as e:
                    logger.error(f"❌ Failed to initialize fraud agent at startup: {e}")
                    cls._shared_foundry_agent = None
                    cls._startup_complete = False
                    raise

    def __init__(self, card: AgentCard):
        self._active_threads: Dict[str, str] = {}  # context_id -> thread_id mapping
        self._waiting_for_input: Dict[str, str] = {}
        self._pending_updaters: Dict[str, TaskUpdater] = {}
        self._input_events: Dict[str, asyncio.Event] = {}

    async def _get_or_create_agent(self) -> FoundryFraudAgent:
        """Get the shared Foundry Fraud agent (with fallback to lazy creation)."""
        async with FoundryFraudAgentExecutor._agent_lock:
            if not FoundryFraudAgentExecutor._shared_foundry_agent:
                if FoundryFraudAgentExecutor._startup_complete:
                    raise RuntimeError("Fraud agent startup initialization failed - agent not available")

                logger.warning("⚠️ Fraud agent not initialized at startup, falling back to lazy creation...")
                FoundryFraudAgentExecutor._shared_foundry_agent = FoundryFraudAgent()
                await FoundryFraudAgentExecutor._shared_foundry_agent.create_agent()
                logger.info("Fallback fraud agent creation completed")
            return FoundryFraudAgentExecutor._shared_foundry_agent

    async def _get_or_create_thread(
        self,
        context_id: str,
        agent: Optional[FoundryFraudAgent] = None
    ) -> str:
        if agent is None:
            agent = await self._get_or_create_agent()
        # Reuse thread if it exists for this context_id
        if context_id in self._active_threads:
            return self._active_threads[context_id]
        # Otherwise, create a new thread and store it
        thread = await agent.create_thread()
        thread_id = thread.id
        self._active_threads[context_id] = thread_id
        return thread_id



    async def _process_request(
        self,
        message_parts: List[Part],
        context_id: str,
        task_updater: TaskUpdater,
    ) -> None:
        try:
            user_message = self._convert_parts_to_text(message_parts)
            agent = await self._get_or_create_agent()
            thread_id = await self._get_or_create_thread(context_id, agent)
            
            # Use streaming to show tool calls in real-time
            responses = []
            tools_called = []
            seen_tools = set()
            
            async for event in agent.run_conversation_stream(thread_id, user_message):
                # Check if this is a tool call event from remote agent
                if event.startswith("🛠️ Remote agent executing:"):
                    tool_description = event.replace("🛠️ Remote agent executing: ", "").strip()
                    if tool_description not in seen_tools:
                        seen_tools.add(tool_description)
                        tools_called.append(tool_description)
                        # Emit tool call in real-time
                        tool_event_msg = new_agent_text_message(
                            f"🛠️ Remote agent executing: {tool_description}", context_id=context_id
                        )
                        await task_updater.update_status(
                            TaskState.working,
                            message=tool_event_msg
                        )
                # Check if this is a processing message
                elif event.startswith("🤖") or event.startswith("🧠") or event.startswith("🔍") or event.startswith("📝"):
                    # Emit processing message in real-time
                    processing_msg = new_agent_text_message(
                        event, context_id=context_id
                    )
                    await task_updater.update_status(
                        TaskState.working,
                        message=processing_msg
                    )
                # Check if this is an error
                elif event.startswith("Error:"):
                    await task_updater.failed(
                        message=new_agent_text_message(event, context_id=context_id)
                    )
                    return

                # Otherwise, treat as a regular response
                else:
                    responses.append(event)
            
            # Emit the final response
            if responses:
                final_response = responses[-1]
                # Log a preview of the response (first 500 chars)
                response_preview = final_response[:500] + "..." if len(final_response) > 500 else final_response
                logger.info(f"📤 Agent response ({len(final_response)} chars): {response_preview}")
                await task_updater.complete(
                    message=new_agent_text_message(final_response, context_id=context_id)
                )
            else:
                logger.warning("⚠️ No response generated by agent")
                await task_updater.complete(
                    message=new_agent_text_message("No response generated", context_id=context_id)
                )
                    
        except Exception as e:
            await task_updater.failed(
                message=new_agent_text_message(f"Error: {e}", context_id=context_id)
            )

    async def _handle_tool_calls(
        self,
        agent: FoundryFraudAgent,
        thread_id: str,
        user_message: str,
        task_updater: TaskUpdater,
        context_id: str
    ):
        """Run the agent with real-time monitoring of tool calls and status updates."""
        responses = []
        tools_called = []
        seen_tools = set()
        
        try:
            async for event in agent.run_conversation_stream(thread_id, user_message):
                # Check if this is a tool call event from remote agent
                if event.startswith("🛠️ Remote agent executing:"):
                    tool_description = event.replace("🛠️ Remote agent executing: ", "").strip()
                    if tool_description not in seen_tools:
                        seen_tools.add(tool_description)
                        tools_called.append(tool_description)
                        # Emit tool call in real-time
                        tool_event_msg = new_agent_text_message(
                            f"🛠️ {tool_description}", context_id=context_id
                        )
                        await task_updater.update_status(
                            TaskState.working,
                            message=tool_event_msg
                        )
                # Check if this is a processing message
                elif event.startswith("🤖") or event.startswith("🧠") or event.startswith("🔍") or event.startswith("📝"):
                    # Emit processing message in real-time
                    processing_msg = new_agent_text_message(
                        event, context_id=context_id
                    )
                    await task_updater.update_status(
                        TaskState.working,
                        message=processing_msg
                    )
                # Check if this is an error
                elif event.startswith("Error:"):
                    await task_updater.failed(
                        message=new_agent_text_message(event, context_id=context_id)
                    )
                    return ([], [])

                # Otherwise, treat as a regular response
                else:
                    responses.append(event)
                    
        except Exception as e:
            await task_updater.failed(
                message=new_agent_text_message(f"Agent execution error: {e}", context_id=context_id)
            )
            return ([], [])
            
        return (responses, tools_called)

    def _convert_parts_to_text(self, parts: List[Part]) -> str:
        """Convert message parts to plain text, saving any files locally."""
        texts: List[str] = []
        for part in parts:
            p = part.root
            if isinstance(p, TextPart):
                texts.append(p.text)
            elif hasattr(p, "file") and isinstance(p.file, FileWithUri):
                texts.append(f"[File at {p.file.uri}]")
            elif hasattr(p, "file") and isinstance(p.file, FileWithBytes):
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
                # Include a compact representation of structured data
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
        logger.info(f"Executing request for context {context.context_id}")
        
        # CRITICAL: Apply rate limiting at the execute level to control between different user requests
        async with FoundryFraudAgentExecutor._request_semaphore:
            # Check API call rate limiting
            current_time = time.time()
            
            # Reset the window if it's been more than a minute
            if current_time - FoundryFraudAgentExecutor._api_call_window_start > 60:
                FoundryFraudAgentExecutor._api_call_count = 0
                FoundryFraudAgentExecutor._api_call_window_start = current_time
            
            # Check if we're approaching the API limit
            if FoundryFraudAgentExecutor._api_call_count >= FoundryFraudAgentExecutor._max_api_calls_per_minute:
                wait_time = 60 - (current_time - FoundryFraudAgentExecutor._api_call_window_start)
                if wait_time > 0:
                    logger.warning(f"API rate limit protection: waiting {wait_time:.1f}s to reset window")
                    await asyncio.sleep(wait_time)
                    # Reset counters
                    FoundryFraudAgentExecutor._api_call_count = 0
                    FoundryFraudAgentExecutor._api_call_window_start = time.time()
            
            # Enforce minimum interval between requests - THIS IS THE KEY FIX
            time_since_last = current_time - FoundryFraudAgentExecutor._last_request_time
            if time_since_last < FoundryFraudAgentExecutor._min_request_interval:
                sleep_time = FoundryFraudAgentExecutor._min_request_interval - time_since_last
                logger.warning(f"🚦 RATE LIMITING: Waiting {sleep_time:.2f}s between user requests (last request was {time_since_last:.2f}s ago)")
                await asyncio.sleep(sleep_time)
            
            FoundryFraudAgentExecutor._last_request_time = time.time()
            
            # Now proceed with the actual request processing
            updater = TaskUpdater(event_queue, context.task_id, context.context_id)
            if not context.current_task:
                await updater.submit()
            await updater.start_work()
            await self._process_request(
                context.message.parts if context.message else [],
                context.context_id,
                updater,
            )
            logger.info(f"Completed execution for {context.context_id}")

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        logger.info(f"Cancelling context {context.context_id}")
        if context.context_id in self._input_events:
            self._input_events[context.context_id].set()
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.failed(
            message=new_agent_text_message("Task cancelled", context_id=context.context_id)
        )

    async def cleanup(self):
        self._active_threads.clear()
        self._waiting_for_input.clear()
        self._pending_updaters.clear()
        self._input_events.clear()
        logger.info("Executor cleaned up")


def create_foundry_agent_executor(card: AgentCard) -> FoundryFraudAgentExecutor:
    return FoundryFraudAgentExecutor(card)
 
 
async def initialize_foundry_fraud_agents_at_startup() -> None:
    """Initialize the shared fraud agent during application startup."""
    await FoundryFraudAgentExecutor.initialize_at_startup()