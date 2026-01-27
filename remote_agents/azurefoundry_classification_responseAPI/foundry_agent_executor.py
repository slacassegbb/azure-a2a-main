"""
AI Foundry Classification Triage Agent Executor for A2A framework.
Adapted from ADK agent executor pattern to work with Azure AI Foundry agents for incident classification and triage.
"""
import asyncio
import logging
import base64
import os
import tempfile
import time
from typing import Optional, Dict, List

from foundry_agent import FoundryClassificationAgent

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
# Set to INFO to hide verbose debug logs (can be changed to DEBUG for troubleshooting)
logger.setLevel(logging.INFO)


class FoundryClassificationAgentExecutor(AgentExecutor):
    """
    An AgentExecutor that runs Azure AI Foundry-based classification triage agents for incident management.
    Adapted from the ADK agent executor pattern.
    """

    # Class-level shared agent instance to avoid multiple agent creations
    _shared_foundry_agent: Optional[FoundryClassificationAgent] = None
    _agent_lock = asyncio.Lock()
    _last_request_time: float = 0
    _min_request_interval: float = 1.0  # Reduced for parallel execution
    _request_semaphore = asyncio.Semaphore(3)  # Allow 3 concurrent requests for parallel execution
    _api_call_count: int = 0
    _api_call_window_start: float = 0
    _max_api_calls_per_minute: int = 30  # Increased for parallel execution
    _startup_complete: bool = False

    @classmethod
    async def get_shared_agent(cls) -> Optional[FoundryClassificationAgent]:
        """Get the shared agent that was initialized at startup (if available)."""
        async with cls._agent_lock:
            return cls._shared_foundry_agent
    
    @classmethod
    async def initialize_at_startup(cls) -> None:
        """Initialize the shared classification agent at startup instead of on first request."""
        async with cls._agent_lock:
            if not cls._shared_foundry_agent:
                logger.info("🚀 Initializing Foundry Classification agent at startup...")
                try:
                    cls._shared_foundry_agent = FoundryClassificationAgent()
                    await cls._shared_foundry_agent.initialize_agent()
                    cls._startup_complete = True
                    logger.info("✅ Foundry Classification agent startup initialization completed successfully")
                except Exception as e:
                    logger.error(f"❌ Failed to initialize classification agent at startup: {e}")
                    cls._shared_foundry_agent = None
                    cls._startup_complete = False
                    raise

    def __init__(self, card: AgentCard):
        self._active_threads: Dict[str, str] = {}  # context_id -> thread_id mapping
        self._waiting_for_input: Dict[str, str] = {}
        self._pending_updaters: Dict[str, TaskUpdater] = {}
        self._input_events: Dict[str, asyncio.Event] = {}

    async def _get_or_create_agent(self) -> FoundryClassificationAgent:
        """Get the shared Foundry Classification agent (with fallback to lazy creation)."""
        async with FoundryClassificationAgentExecutor._agent_lock:
            if not FoundryClassificationAgentExecutor._shared_foundry_agent:
                if FoundryClassificationAgentExecutor._startup_complete:
                    # Startup was supposed to happen but failed
                    raise RuntimeError("Classification agent startup initialization failed - agent not available")
                
                # Fallback to lazy creation if startup wasn't called
                logger.warning("⚠️ Classification agent not initialized at startup, falling back to lazy creation...")
                FoundryClassificationAgentExecutor._shared_foundry_agent = FoundryClassificationAgent()
                await FoundryClassificationAgentExecutor._shared_foundry_agent.initialize_agent()
                logger.info("Fallback classification agent creation completed")
            return FoundryClassificationAgentExecutor._shared_foundry_agent

    async def _get_or_create_thread(
        self,
        context_id: str,
        agent: Optional[FoundryClassificationAgent] = None,
        force_new: bool = False
    ) -> str:
        if agent is None:
            agent = await self._get_or_create_agent()
        # Force new thread for parallel requests to avoid thread conflicts
        if force_new:
            thread_id = agent.create_thread()  # Returns string directly, not async
            logger.info(f"Created new thread {thread_id} for parallel request (context: {context_id})")
            self._active_threads[context_id] = thread_id
            return thread_id
        # Reuse thread if it exists for this context_id
        if context_id in self._active_threads:
            return self._active_threads[context_id]
        # Otherwise, create a new thread and store it
        thread_id = agent.create_thread()  # Returns string directly, not async
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
            
            # Emit initial working status
            logger.info(f"📡 Emitting initial status update to host via task_updater...")
            await task_updater.update_status(
                TaskState.working,
                message=new_agent_text_message("🧠 Processing request...", context_id=context_id)
            )
            logger.info(f"✅ Initial status update sent successfully")
            
            # Use streaming to collect response chunks
            responses = []
            chunk_count = 0
            last_update_time = time.time()
            update_interval = 1.0  # Send status update every second
            
            logger.info(f"🔄 Starting streaming loop...")
            async for chunk in agent.run_conversation_stream(user_message, thread_id):
                chunk_count += 1
                responses.append(chunk)
                
                # Send periodic status updates while streaming (every second)
                current_time = time.time()
                if current_time - last_update_time >= update_interval:
                    char_count = len(''.join(responses))
                    logger.info(f"📡 Emitting progress update: {char_count} chars, {chunk_count} chunks...")
                    await task_updater.update_status(
                        TaskState.working,
                        message=new_agent_text_message(
                            f"🤖 Generating response... ({char_count} chars)", 
                            context_id=context_id
                        )
                    )
                    logger.info(f"✅ Progress update sent successfully")
                    last_update_time = current_time
            
            logger.info(f"✅ Streaming loop completed: {len(responses)} total chunks")
            
            # Emit the final response
            if responses:
                # Join all response chunks into final response
                final_response = "".join(responses)
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
        
        # CRITICAL: Apply rate limiting at the execute level to control between different user requests
        async with FoundryClassificationAgentExecutor._request_semaphore:
            # Check API call rate limiting
            current_time = time.time()
            
            # Reset the window if it's been more than a minute
            if current_time - FoundryClassificationAgentExecutor._api_call_window_start > 60:
                FoundryClassificationAgentExecutor._api_call_count = 0
                FoundryClassificationAgentExecutor._api_call_window_start = current_time
            
            # Log if approaching API limit (but don't block for parallel execution)
            if FoundryClassificationAgentExecutor._api_call_count >= FoundryClassificationAgentExecutor._max_api_calls_per_minute:
                logger.warning(f"⚠️ API call count ({FoundryClassificationAgentExecutor._api_call_count}) at limit, requests may be throttled by Azure")
            
            FoundryClassificationAgentExecutor._api_call_count += 1
            FoundryClassificationAgentExecutor._last_request_time = time.time()
            
            # Now proceed with the actual request processing
            updater = TaskUpdater(event_queue, context.task_id, context.context_id)
            if not context.current_task:
                await updater.submit()
            await updater.start_work()
            # CRITICAL: Use context_id from the incoming message (host's context), not the SDK's internal context
            # This ensures events are routed to the correct WebSocket tenant
            
            # Debug: Inspect message object structure
            logger.info(f"🔍 DEBUG Message object attributes: {dir(context.message) if context.message else 'No message'}")
            if context.message:
                logger.info(f"🔍 DEBUG Message.__dict__: {vars(context.message)}")
                logger.info(f"🔍 DEBUG hasattr context_id: {hasattr(context.message, 'context_id')}")
                logger.info(f"🔍 DEBUG hasattr contextId: {hasattr(context.message, 'contextId')}")
                # Try both snake_case and camelCase (Pydantic aliasing)
                if hasattr(context.message, 'context_id'):
                    logger.info(f"🔍 DEBUG message.context_id value: {context.message.context_id}")
                if hasattr(context.message, 'contextId'):
                    logger.info(f"🔍 DEBUG message.contextId value: {context.message.contextId}")
            
            # Extract context_id - try both attribute names due to Pydantic aliasing
            message_context_id = None
            if context.message:
                # Try snake_case first (Python attribute)
                if hasattr(context.message, 'context_id') and context.message.context_id:
                    message_context_id = context.message.context_id
                # Fall back to camelCase (serialized name)
                elif hasattr(context.message, 'contextId') and context.message.contextId:
                    message_context_id = context.message.contextId
            
            # Ultimate fallback to SDK's context_id
            if not message_context_id:
                message_context_id = context.context_id
            
            logger.info(f"Using contextId: message={message_context_id}, sdk={context.context_id}")
            await self._process_request(
                context.message.parts if context.message else [],
                message_context_id,  # Use message's context_id for tenant routing
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


def create_foundry_agent_executor(card: AgentCard) -> FoundryClassificationAgentExecutor:
    return FoundryClassificationAgentExecutor(card)


async def initialize_foundry_classification_agents_at_startup():
    """
    Convenience function to initialize shared classification agent resources at application startup.
    Call this once during your application's startup phase.
    
    Example usage in your main application:
    
    ```python
    # In your main startup code (e.g., main.py or app initialization)
    import asyncio
    from foundry_agent_executor import initialize_foundry_classification_agents_at_startup
    
    async def startup():
        print("🚀 Starting classification application...")
        await initialize_foundry_classification_agents_at_startup()
        print("✅ Classification agent initialization complete, ready to handle requests")
    
    # Run at startup
    asyncio.run(startup())
    ```
    """
    await FoundryClassificationAgentExecutor.initialize_at_startup()