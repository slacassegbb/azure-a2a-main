"""
AI Foundry Twilio SMS Agent Executor for A2A framework.
Handles sending SMS messages via Twilio using Azure AI Foundry function calling.

HITL (Human-in-the-Loop) Support:
- Tracks pending SMS conversations waiting for human responses
- Emits input_required state when waiting for SMS replies
- Resumes conversations when human responses arrive via webhook
"""
import asyncio
import logging
import base64
import os
import tempfile
import time
from typing import Optional, Dict, List, Any

from foundry_agent import FoundryTwilioAgent, PendingSMSRequest

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
from a2a.utils.message import new_agent_text_message, new_agent_parts_message

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class FoundryTwilioAgentExecutor(AgentExecutor):
    """
    An AgentExecutor that runs Azure AI Foundry-based Twilio SMS agent.
    
    HITL Support:
    - _waiting_for_input: Tracks context IDs waiting for human SMS responses
    - _hitl_resume_info: Stores context for resuming after human response
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
    
    # HITL: Class-level tracking for webhook access
    _waiting_for_input: Dict[str, Dict[str, Any]] = {}  # context_id -> wait info
    _hitl_resume_info: Dict[str, Dict[str, Any]] = {}   # context_id -> resume context

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
            
            # Check if this is a HITL resume (human response arriving)
            if context_id in FoundryTwilioAgentExecutor._hitl_resume_info:
                resume_info = FoundryTwilioAgentExecutor._hitl_resume_info.pop(context_id)
                logger.info(f"📱 HITL RESUME: Processing human response for context {context_id}")
                logger.info(f"📱 Original question: {resume_info.get('question', 'N/A')[:50]}...")
                logger.info(f"📱 Human response: {user_message[:100]}...")
                
                # Enhanced message with context for the LLM
                enhanced_message = f"""HUMAN RESPONSE RECEIVED via SMS:

The user was asked: "{resume_info.get('question', 'a question')}"

The user replied via SMS: "{user_message}"

Please process this human response and continue the workflow accordingly."""
                user_message = enhanced_message
            
            # Check if this message is already in waiting_for_input context
            if context_id in FoundryTwilioAgentExecutor._waiting_for_input:
                wait_info = FoundryTwilioAgentExecutor._waiting_for_input.pop(context_id)
                logger.info(f"📱 Found waiting context for {context_id}, processing as HITL resume")
                
                enhanced_message = f"""HUMAN RESPONSE RECEIVED via SMS:

The user was asked: "{wait_info.get('question', 'a question')}"

The user replied via SMS: "{user_message}"

Please process this human response and continue the workflow accordingly."""
                user_message = enhanced_message
            
            agent = await self._get_or_create_agent()
            # Use force_new=True to create separate threads for parallel requests
            thread_id = await self._get_or_create_thread(context_id, agent, force_new=True)
            
            # Use streaming to show tool calls in real-time
            responses = []
            tools_called = []
            seen_tools = set()
            
            async for event in agent.run_conversation_stream(thread_id, user_message, context_id=context_id):
                # Check for HITL waiting signal
                if event.startswith("HITL_WAITING:"):
                    # Parse HITL signal: HITL_WAITING:phone_number:question
                    parts = event.split(":", 2)
                    phone_number = parts[1] if len(parts) > 1 else "unknown"
                    question = parts[2] if len(parts) > 2 else "Waiting for response"
                    
                    # Store waiting info for webhook
                    FoundryTwilioAgentExecutor._waiting_for_input[context_id] = {
                        "phone_number": phone_number,
                        "question": question,
                        "thread_id": thread_id,
                        "timestamp": time.time()
                    }
                    
                    logger.info(f"📱 HITL: Setting input_required state for context {context_id}")
                    logger.info(f"📱 HITL: Waiting for SMS response from {phone_number}")
                    
                    # Emit input_required state
                    await task_updater.update_status(
                        TaskState.input_required,
                        message=new_agent_text_message(
                            f"📱 Waiting for human response via SMS.\n\nMessage sent to {phone_number}: {question}",
                            context_id=context_id
                        ),
                        final=True  # This closes the event queue properly
                    )
                    
                    # Return immediately - don't block. Human response will come as new A2A message.
                    logger.info(f"📱 Returning input_required state - human SMS response will arrive as new message")
                    return
                
                # Check if this is a tool call event from remote agent
                if event.startswith("🛠️ Remote agent executing:") or event.startswith("🛠️ Calling function:"):
                    tool_description = event.replace("🛠️ Remote agent executing: ", "").replace("🛠️ Calling function: ", "").strip()
                    if tool_description not in seen_tools:
                        seen_tools.add(tool_description)
                        tools_called.append(tool_description)
                        # Emit tool call in real-time
                        tool_event_msg = new_agent_text_message(
                            f"🛠️ Executing: {tool_description}", context_id=context_id
                        )
                        await task_updater.update_status(
                            TaskState.working,
                            message=tool_event_msg
                        )
                # Check if this is a processing message
                elif event.startswith("🤖") or event.startswith("🧠") or event.startswith("🔍") or event.startswith("📝") or event.startswith("📱"):
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
                logger.warning("⚠️ No response generated by agent")
                
                # Build message parts (even for error case)
                import uuid
                message_parts = [TextPart(text="No response generated")]
                
                # Add token usage even if no response (in case run consumed tokens)
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
        FoundryTwilioAgentExecutor._waiting_for_input.clear()
        FoundryTwilioAgentExecutor._hitl_resume_info.clear()
        self._pending_updaters.clear()
        self._input_events.clear()
        logger.info("Executor cleaned up")

    @classmethod
    def get_pending_context(cls, context_id: str) -> Optional[Dict[str, Any]]:
        """
        Get pending input context for a given context_id.
        Used by webhook to check if there's a pending request.
        """
        return cls._waiting_for_input.get(context_id)
    
    @classmethod
    def get_pending_context_by_phone(cls, phone_number: str) -> Optional[tuple]:
        """
        Get pending input context for a given phone number.
        Returns (context_id, wait_info) tuple if found.
        """
        for context_id, wait_info in cls._waiting_for_input.items():
            if wait_info.get("phone_number") == phone_number:
                return (context_id, wait_info)
        return None
    
    @classmethod
    def clear_pending_context(cls, context_id: str) -> Optional[Dict[str, Any]]:
        """Clear pending input context after it's been handled."""
        return cls._waiting_for_input.pop(context_id, None)
    
    @classmethod
    def set_hitl_resume_info(cls, context_id: str, info: Dict[str, Any]):
        """Store info needed to resume HITL conversation."""
        cls._hitl_resume_info[context_id] = info
        logger.info(f"📱 HITL: Stored resume info for context {context_id}")
    
    @classmethod 
    def get_all_waiting_contexts(cls) -> Dict[str, Dict[str, Any]]:
        """Get all contexts waiting for human input."""
        return cls._waiting_for_input.copy()


def create_foundry_agent_executor(card: AgentCard) -> FoundryTwilioAgentExecutor:
    return FoundryTwilioAgentExecutor(card)


async def initialize_foundry_twilio_agents_at_startup():
    """
    Initialize shared Twilio SMS agent resources at application startup.
    """
    await FoundryTwilioAgentExecutor.initialize_at_startup()