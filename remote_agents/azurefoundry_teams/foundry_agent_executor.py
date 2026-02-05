"""
Azure AI Foundry Teams Agent Executor
=====================================

This executor handles A2A protocol integration for the Teams agent.
It manages the human-in-the-loop workflow using input_required state.
"""
import asyncio
import logging
import base64
import os
import tempfile
import time
from typing import Optional, Dict, List

from foundry_agent import FoundryTeamsAgent

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import AgentCard, DataPart, FilePart, FileWithBytes, FileWithUri, Message, Part, TaskState, TextPart
from a2a.utils.message import new_agent_text_message, new_agent_parts_message

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class FoundryTeamsAgentExecutor(AgentExecutor):
    """
    AgentExecutor for Teams-based human-in-the-loop workflows.
    Uses A2A input_required state when waiting for human responses via Teams.
    """

    # Class-level shared agent instance
    _shared_foundry_agent: Optional[FoundryTeamsAgent] = None
    _agent_lock = asyncio.Lock()
    _last_request_time: float = 0
    _min_request_interval: float = 1.0
    _request_semaphore = asyncio.Semaphore(3)
    _api_call_count: int = 0
    _api_call_window_start: float = 0
    _max_api_calls_per_minute: int = 30
    _startup_complete: bool = False

    @classmethod
    async def get_shared_agent(cls) -> Optional[FoundryTeamsAgent]:
        """Get the shared agent that was initialized at startup."""
        async with cls._agent_lock:
            return cls._shared_foundry_agent
    
    @classmethod
    async def initialize_at_startup(cls) -> None:
        """Initialize the shared agent at startup."""
        async with cls._agent_lock:
            if not cls._shared_foundry_agent:
                logger.info("🚀 Initializing Teams Foundry agent at startup...")
                try:
                    cls._shared_foundry_agent = FoundryTeamsAgent()
                    await cls._shared_foundry_agent.create_agent()
                    cls._startup_complete = True
                    logger.info("✅ Teams Foundry agent startup initialization completed")
                except Exception as e:
                    logger.error(f"❌ Failed to initialize agent at startup: {e}")
                    cls._shared_foundry_agent = None
                    cls._startup_complete = False
                    raise

    def __init__(self, card: AgentCard):
        self._active_threads: Dict[str, str] = {}  # context_id -> thread_id
        self._waiting_for_input: Dict[str, dict] = {}  # context_id -> {wait_info, thread_id}

    async def _get_or_create_agent(self) -> FoundryTeamsAgent:
        """Get the shared Foundry Teams agent."""
        async with FoundryTeamsAgentExecutor._agent_lock:
            if not FoundryTeamsAgentExecutor._shared_foundry_agent:
                if FoundryTeamsAgentExecutor._startup_complete:
                    raise RuntimeError("Teams agent startup initialization failed - agent not available")
                
                logger.warning("⚠️ Teams agent not initialized at startup, falling back to lazy creation...")
                FoundryTeamsAgentExecutor._shared_foundry_agent = FoundryTeamsAgent()
                await FoundryTeamsAgentExecutor._shared_foundry_agent.create_agent()
                logger.info("Fallback Teams agent creation completed")
            return FoundryTeamsAgentExecutor._shared_foundry_agent

    async def _get_or_create_thread(
        self,
        context_id: str,
        agent: Optional[FoundryTeamsAgent] = None,
        force_new: bool = False
    ) -> str:
        """Get or create a thread for the given context."""
        if agent is None:
            agent = await self._get_or_create_agent()
        
        if force_new:
            thread = await agent.create_thread()
            thread_id = thread.id
            logger.info(f"Created new thread {thread_id} for context: {context_id}")
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
        """Process an A2A request, handling human-in-the-loop via Teams."""
        
        try:
            user_message = self._convert_parts_to_text(message_parts)
            if user_message:
                preview = user_message if len(user_message) <= 2000 else user_message[:2000] + "..."
                logger.info(
                    "🧾 A2A conversation payload (%d chars) for context %s:\n%s",
                    len(user_message),
                    context_id,
                    preview,
                )
            else:
                logger.info("🧾 Received empty A2A conversation payload for context %s", context_id)
            
            agent = await self._get_or_create_agent()
            
            # ========================================================================
            # HITL RESUME: Check if this is a human response to a pending request
            # If so, reuse the existing thread and provide context
            # ========================================================================
            logger.info(f"🔍 [HITL CHECK] Incoming context_id: {context_id}")
            logger.info(f"🔍 [HITL CHECK] _waiting_for_input keys: {list(self._waiting_for_input.keys())}")
            
            pending_info = self._waiting_for_input.get(context_id)
            if pending_info:
                # This is a human response to a pending HITL request
                thread_id = pending_info.get("thread_id")
                original_prompt = pending_info.get("wait_info", "")
                
                logger.info(f"🔄 [HITL RESUME] Resuming with existing thread {thread_id} for context {context_id}")
                logger.info(f"🔄 [HITL RESUME] Original prompt: {original_prompt[:100]}...")
                logger.info(f"🔄 [HITL RESUME] Human response: {user_message}")
                
                # Clear the pending state
                del self._waiting_for_input[context_id]
                
                # Enhance the message with context so the LLM understands this is a response
                user_message = f"""The user has responded to the approval request.

**Original request sent to user:**
{original_prompt}

**User's response:**
{user_message}

Based on the user's response, please confirm what action was taken. If they approved, confirm the approval. If they rejected, confirm the rejection. Use TEAMS_SEND to notify the user of the outcome."""
                
                logger.info(f"🔄 [HITL RESUME] Enhanced message for LLM:\n{user_message[:500]}...")
            else:
                # New request - create a new thread
                thread_id = await self._get_or_create_thread(context_id, agent, force_new=True)
            
            responses = []
            
            async for event in agent.run_conversation_stream(thread_id, user_message, context_id=context_id):
                # Check for TEAMS_WAIT_RESPONSE - this means we need input_required state
                if event.startswith("TEAMS_WAIT_RESPONSE:"):
                    wait_info = event.replace("TEAMS_WAIT_RESPONSE:", "").strip()
                    logger.info(f"📱 Agent waiting for Teams response: {wait_info}")
                    
                    # Store context for resume - will be handled by a follow-up A2A message
                    self._waiting_for_input[context_id] = {
                        "wait_info": wait_info,
                        "thread_id": thread_id,
                    }
                    
                    # Set task to input_required state and RETURN immediately
                    # The backend will store this as a pending HITL agent
                    # When human responds, webhook will forward to backend which sends new A2A message
                    await task_updater.update_status(
                        TaskState.input_required,
                        message=new_agent_text_message(
                            f"📱 Waiting for human response via Microsoft Teams.\n\nMessage sent to user: {wait_info}",
                            context_id=context_id
                        )
                    )
                    
                    # Return immediately - don't block. Human response will come as new A2A message.
                    logger.info(f"📱 Returning input_required state - human response will arrive as new message")
                    return
                
                # Check for processing messages (but NOT completion messages that indicate actual work done)
                # Messages with "✅" indicate successful completion and should be treated as responses
                is_processing_only = (event.startswith("🛠️") or event.startswith("📱") or event.startswith("📤") or event.startswith("📥"))
                has_completion = "✅" in event or "Message sent to Teams successfully" in event
                
                if is_processing_only and not has_completion:
                    processing_msg = new_agent_text_message(event, context_id=context_id)
                    await task_updater.update_status(TaskState.working, message=processing_msg)
                    continue
                
                # Check for errors
                if event.startswith("Error:"):
                    await task_updater.failed(
                        message=new_agent_text_message(event, context_id=context_id)
                    )
                    return
                
                # Regular response
                responses.append(event)
            
            # Emit final response
            if responses:
                final_response = responses[-1]
                response_preview = final_response[:500] + "..." if len(final_response) > 500 else final_response
                logger.info(f"📤 Agent response ({len(final_response)} chars): {response_preview}")
                
                final_parts = [Part(root=TextPart(text=final_response))]
                
                # Add token usage if available
                if hasattr(agent, 'last_token_usage') and agent.last_token_usage:
                    final_parts.append(Part(root=DataPart(data={
                        'type': 'token_usage',
                        **agent.last_token_usage
                    })))
                
                await task_updater.complete(
                    message=new_agent_parts_message(parts=final_parts, context_id=context_id)
                )
            else:
                logger.warning("⚠️ No response generated by Teams agent")
                await task_updater.complete(
                    message=new_agent_text_message("No response generated", context_id=context_id)
                )
                    
        except Exception as e:
            logger.error(f"Error in Teams agent: {e}", exc_info=True)
            await task_updater.failed(
                message=new_agent_text_message(f"Error: {e}", context_id=context_id)
            )

    def get_pending_context(self, context_id: str) -> dict | None:
        """
        Get pending input context for a given context_id.
        Used by webhook to check if there's a pending request.
        """
        return self._waiting_for_input.get(context_id)
    
    def clear_pending_context(self, context_id: str):
        """Clear pending input context after it's been handled."""
        if context_id in self._waiting_for_input:
            del self._waiting_for_input[context_id]

    def _convert_parts_to_text(self, parts: List[Part]) -> str:
        """Convert message parts to plain text."""
        texts: List[str] = []
        for part in parts:
            p = part.root
            if isinstance(p, TextPart):
                texts.append(p.text)
            elif isinstance(p, DataPart):
                if isinstance(p.data, dict):
                    uri = p.data.get("artifact-uri")
                    file_name = p.data.get("file-name", "file")
                    if uri:
                        texts.append(f"[File reference: {file_name} at {uri}]")
                    else:
                        texts.append(str(p.data))
                else:
                    texts.append(str(p.data))
            elif hasattr(p, 'file'):
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
        return " ".join(texts)

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ):
        """Execute an A2A request."""
        logger.info(f"Executing Teams request for context {context.context_id}")
        
        async with FoundryTeamsAgentExecutor._request_semaphore:
            # Rate limiting
            current_time = time.time()
            if current_time - FoundryTeamsAgentExecutor._api_call_window_start > 60:
                FoundryTeamsAgentExecutor._api_call_count = 0
                FoundryTeamsAgentExecutor._api_call_window_start = current_time
            
            if FoundryTeamsAgentExecutor._api_call_count >= FoundryTeamsAgentExecutor._max_api_calls_per_minute:
                logger.warning(f"⚠️ API call count at limit, requests may be throttled")
            
            FoundryTeamsAgentExecutor._api_call_count += 1
            FoundryTeamsAgentExecutor._last_request_time = time.time()
            
            # Process request
            updater = TaskUpdater(event_queue, context.task_id, context.context_id)
            if not context.current_task:
                await updater.submit()
            await updater.start_work()
            await self._process_request(
                context.message.parts if context.message else [],
                context.context_id,
                updater,
            )
            logger.info(f"Completed Teams execution for {context.context_id}")

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        """Cancel a pending request."""
        logger.info(f"Cancelling Teams context {context.context_id}")
        if context.context_id in self._input_events:
            self._input_events[context.context_id].set()
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.failed(
            message=new_agent_text_message("Task cancelled", context_id=context.context_id)
        )

    async def cleanup(self):
        """Clean up resources."""
        self._active_threads.clear()
        self._waiting_for_input.clear()
        self._pending_updaters.clear()
        self._input_events.clear()
        logger.info("Teams executor cleaned up")


def create_foundry_agent_executor(card: AgentCard) -> FoundryTeamsAgentExecutor:
    """Factory function to create the executor."""
    return FoundryTeamsAgentExecutor(card)


async def initialize_teams_agents_at_startup():
    """Initialize shared agent resources at application startup."""
    await FoundryTeamsAgentExecutor.initialize_at_startup()
