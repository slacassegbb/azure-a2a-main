"""
AI Foundry Twilio SMS Agent Executor for A2A framework.
Handles sending SMS messages via Twilio using Azure AI Foundry function calling.
"""
import asyncio
import logging
import base64
import os
import tempfile
import time
from typing import Optional, Dict, List

from foundry_agent import FoundryTwilioAgent

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    AgentCard,
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


class FoundryTwilioAgentExecutor(AgentExecutor):
    """
    An AgentExecutor that runs Azure AI Foundry-based Twilio SMS agent.
    """

    # Class-level shared agent instance
    _shared_foundry_agent: Optional[FoundryTwilioAgent] = None
    _agent_lock = asyncio.Lock()
    _last_request_time: float = 0
    _min_request_interval: float = 1.0
    _request_semaphore = asyncio.Semaphore(3)
    _api_call_count: int = 0
    _api_call_window_start: float = 0
    _max_api_calls_per_minute: int = 30
    _startup_complete: bool = False

    @classmethod
    async def get_shared_agent(cls) -> Optional[FoundryTwilioAgent]:
        """Get the shared agent that was initialized at startup."""
        async with cls._agent_lock:
            return cls._shared_foundry_agent
    
    @classmethod
    async def initialize_at_startup(cls) -> None:
        """Initialize the shared Twilio agent at startup."""
        async with cls._agent_lock:
            if not cls._shared_foundry_agent:
                logger.info("🚀 Initializing Foundry Twilio SMS agent at startup...")
                try:
                    cls._shared_foundry_agent = FoundryTwilioAgent()
                    await cls._shared_foundry_agent.create_agent()
                    cls._startup_complete = True
                    logger.info("✅ Foundry Twilio SMS agent startup initialization completed successfully")
                except Exception as e:
                    logger.error(f"❌ Failed to initialize Twilio agent at startup: {e}")
                    cls._shared_foundry_agent = None
                    cls._startup_complete = False
                    raise

    def __init__(self, card: AgentCard):
        self._active_threads: Dict[str, str] = {}
        self._waiting_for_input: Dict[str, str] = {}
        self._pending_updaters: Dict[str, TaskUpdater] = {}
        self._input_events: Dict[str, asyncio.Event] = {}

    async def _get_or_create_agent(self) -> FoundryTwilioAgent:
        """Get the shared Twilio agent (with fallback to lazy creation)."""
        async with FoundryTwilioAgentExecutor._agent_lock:
            if not FoundryTwilioAgentExecutor._shared_foundry_agent:
                if FoundryTwilioAgentExecutor._startup_complete:
                    raise RuntimeError("Twilio agent startup initialization failed - agent not available")
                
                logger.warning("⚠️ Twilio agent not initialized at startup, falling back to lazy creation...")
                FoundryTwilioAgentExecutor._shared_foundry_agent = FoundryTwilioAgent()
                await FoundryTwilioAgentExecutor._shared_foundry_agent.create_agent()
                logger.info("Fallback Twilio agent creation completed")
            return FoundryTwilioAgentExecutor._shared_foundry_agent

    async def _get_or_create_thread(
        self,
        context_id: str,
        agent: Optional[FoundryTwilioAgent] = None,
        force_new: bool = False
    ) -> str:
        if agent is None:
            agent = await self._get_or_create_agent()
        if force_new:
            thread = await agent.create_thread()
            thread_id = thread.id
            logger.info(f"Created new thread {thread_id} for request (context: {context_id})")
            self._active_threads[context_id] = thread_id
            return thread_id
        if context_id in self._active_threads:
            return self._active_threads[context_id]
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
            # Use force_new=True to create separate threads for parallel requests
            thread_id = await self._get_or_create_thread(context_id, agent, force_new=True)
            
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
                
                # Build message parts with text and optional token usage
                import uuid
                message_parts = [TextPart(text=final_response)]
                
                # Add token usage if available
                if hasattr(agent, 'last_token_usage') and agent.last_token_usage:
                    message_parts.append(DataPart(data={
                        'type': 'token_usage',
                        **agent.last_token_usage
                    }))
                    logger.info(f"💰 Including token usage in response: {agent.last_token_usage}")
                
                await task_updater.complete(
                    message=Message(
                        role="agent",
                        messageId=str(uuid.uuid4()),
                        parts=message_parts,
                        contextId=context_id
                    )
                )
            else:
                logger.warning("⚠️ No response generated by agent")
                
                # Build message parts (even for error case)
                import uuid
                message_parts = [TextPart(text="No response generated")]
                
                # Add token usage even if no response (in case run consumed tokens)
                if hasattr(agent, 'last_token_usage') and agent.last_token_usage:
                    message_parts.append(DataPart(data={
                        'type': 'token_usage',
                        **agent.last_token_usage
                    }))
                    logger.info(f"💰 Including token usage in response: {agent.last_token_usage}")
                
                await task_updater.complete(
                    message=Message(
                        role="agent",
                        messageId=str(uuid.uuid4()),
                        parts=message_parts,
                        contextId=context_id
                    )
                )
                    
        except Exception as e:
            await task_updater.failed(
                message=new_agent_text_message(f"Error: {e}", context_id=context_id)
            )

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
        
        # Apply rate limiting at the execute level
        async with FoundryTwilioAgentExecutor._request_semaphore:
            current_time = time.time()
            
            # Reset the window if it's been more than a minute
            if current_time - FoundryTwilioAgentExecutor._api_call_window_start > 60:
                FoundryTwilioAgentExecutor._api_call_count = 0
                FoundryTwilioAgentExecutor._api_call_window_start = current_time
            
            # Log if approaching API limit
            if FoundryTwilioAgentExecutor._api_call_count >= FoundryTwilioAgentExecutor._max_api_calls_per_minute:
                logger.warning(f"⚠️ API call count ({FoundryTwilioAgentExecutor._api_call_count}) at limit")
            
            FoundryTwilioAgentExecutor._api_call_count += 1
            FoundryTwilioAgentExecutor._last_request_time = time.time()
            
            # Proceed with request processing
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


def create_foundry_agent_executor(card: AgentCard) -> FoundryTwilioAgentExecutor:
    return FoundryTwilioAgentExecutor(card)


async def initialize_foundry_twilio_agents_at_startup():
    """
    Initialize shared Twilio SMS agent resources at application startup.
    """
    await FoundryTwilioAgentExecutor.initialize_at_startup()