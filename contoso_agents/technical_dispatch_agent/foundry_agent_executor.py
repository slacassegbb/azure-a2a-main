"""
Azure AI Foundry A2A Agent Template - Executor
===============================================

This executor handles A2A protocol integration for your custom agent.
Typically you won't need to modify this file unless you want to add custom
file handling or change execution behavior.
"""
import asyncio
import logging
import base64
import os
import tempfile
import time
from typing import Optional, Dict, List

from foundry_agent import FoundryTechnicalDispatchAgent

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import AgentCard, DataPart, FilePart, FileWithBytes, FileWithUri, Part, TaskState, TextPart
from a2a.utils.message import new_agent_text_message

logger = logging.getLogger(__name__)
# Set to INFO to hide verbose debug logs (can be changed to DEBUG for troubleshooting)
logger.setLevel(logging.INFO)


class FoundryTechnicalDispatchAgentExecutor(AgentExecutor):
    """
    An AgentExecutor template for Azure AI Foundry-based agents.
    This handles A2A protocol integration, file handling, and streaming responses.
    Customize the agent behavior in foundry_agent.py, not here.
    """

    # Class-level shared agent instance to avoid multiple agent creations
    _shared_foundry_agent: Optional[FoundryTechnicalDispatchAgent] = None
    _agent_lock = asyncio.Lock()
    _last_request_time: float = 0
    _min_request_interval: float = 5.0  # Increase to 5 seconds minimum between requests
    _request_semaphore = asyncio.Semaphore(1)  # Max 1 concurrent request
    _api_call_count: int = 0
    _api_call_window_start: float = 0
    _max_api_calls_per_minute: int = 15  # Much more conservative - 15 calls per minute
    _startup_complete: bool = False
    
    # HITL (Human-in-the-Loop) escalation tracking
    _pending_escalations: Dict[str, str] = {}  # context_id -> escalation_request_text
    _escalation_responses: Dict[str, str] = {}  # context_id -> human_response_text
    _escalation_lock = asyncio.Lock()

    @classmethod
    async def get_shared_agent(cls) -> Optional[FoundryTechnicalDispatchAgent]:
        """Get the shared agent that was initialized at startup (if available)."""
        async with cls._agent_lock:
            return cls._shared_foundry_agent
    
    @classmethod
    def get_pending_escalations(cls) -> Dict[str, str]:
        """Get all pending human escalations (for Gradio UI)."""
        return dict(cls._pending_escalations)
    
    @classmethod
    async def _send_human_response_internal(cls, context_id: str, response: str) -> bool:
        """
        Internal classmethod to send human expert response to a pending escalation.
        Returns True if escalation was found and response sent, False otherwise.
        """
        async with cls._escalation_lock:
            if context_id not in cls._pending_escalations:
                logger.warning(f"No pending escalation found for context {context_id}")
                return False
            
            # Store the human response
            cls._escalation_responses[context_id] = response
            logger.info(f"✅ Human response stored for context {context_id}")
        
        # Find the executor instance that's waiting for this context
        # and trigger its event to continue processing
        # Note: This is done by setting the event in the instance's _input_events dict
        # which will be checked in the _process_request method
        
        return True
    
    @classmethod
    async def get_shared_agent(cls) -> Optional[FoundryTechnicalDispatchAgent]:
        """Get the shared agent that was initialized at startup (if available)."""
        async with cls._agent_lock:
            return cls._shared_foundry_agent
    
    @classmethod
    async def initialize_at_startup(cls) -> None:
        """Initialize the shared agent at startup instead of on first request."""
        async with cls._agent_lock:
            if not cls._shared_foundry_agent:
                logger.info("🚀 Initializing Foundry agent at startup...")
                try:
                    cls._shared_foundry_agent = FoundryTechnicalDispatchAgent()
                    await cls._shared_foundry_agent.create_agent()
                    cls._startup_complete = True
                    logger.info("✅ Foundry agent startup initialization completed successfully")
                except Exception as e:
                    logger.error(f"❌ Failed to initialize agent at startup: {e}")
                    cls._shared_foundry_agent = None
                    cls._startup_complete = False
                    raise

    def __init__(self, card: AgentCard):
        self._active_threads: Dict[str, str] = {}  # context_id -> thread_id mapping
        self._waiting_for_input: Dict[str, str] = {}
        self._pending_updaters: Dict[str, TaskUpdater] = {}
        self._input_events: Dict[str, asyncio.Event] = {}
        self._last_received_files: List[Dict[str, str]] = []
    
    async def send_human_response(self, context_id: str, response: str) -> bool:
        """Instance method wrapper for sending human response and triggering event."""
        # First store the response at class level using the internal classmethod
        success = await self.__class__._send_human_response_internal(context_id, response)
        
        if success and context_id in self._input_events:
            # Trigger the event to continue processing
            self._input_events[context_id].set()
            logger.info(f"✅ Triggered event for context {context_id}")
        
        return success

    async def _get_or_create_agent(self) -> FoundryTechnicalDispatchAgent:
        """Get the shared Foundry Technical Dispatch agent (with fallback to lazy creation)."""
        async with FoundryTechnicalDispatchAgentExecutor._agent_lock:
            if not FoundryTechnicalDispatchAgentExecutor._shared_foundry_agent:
                if FoundryTechnicalDispatchAgentExecutor._startup_complete:
                    # Startup was supposed to happen but failed
                    raise RuntimeError("Technical Dispatch agent startup initialization failed - agent not available")

                # Fallback to lazy creation if startup wasn't called
                logger.warning("⚠️ Technical Dispatch agent not initialized at startup, falling back to lazy creation...")
                FoundryTechnicalDispatchAgentExecutor._shared_foundry_agent = FoundryTechnicalDispatchAgent()
                await FoundryTechnicalDispatchAgentExecutor._shared_foundry_agent.create_agent()
                logger.info("Fallback technical dispatch agent creation completed")
            return FoundryTechnicalDispatchAgentExecutor._shared_foundry_agent

    async def _get_or_create_thread(
        self,
        context_id: str,
        agent: Optional[FoundryTechnicalDispatchAgent] = None
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
        logger.info(f"🟡 [AUTH EXECUTOR] _process_request called with {len(message_parts)} parts")
        received_files: List[Dict[str, str]] = []
        if message_parts:
            for part in message_parts:
                if hasattr(part, "root"):
                    root_part = part.root

                    if isinstance(root_part, FilePart):
                        file_obj = root_part.file
                        if isinstance(file_obj, FileWithUri):
                            received_files.append({
                                "name": getattr(file_obj, "name", "unknown"),
                                "uri": getattr(file_obj, "uri", ""),
                                "mime": getattr(file_obj, "mimeType", ""),
                            })
                        elif isinstance(file_obj, FileWithBytes):
                            received_files.append({
                                "name": getattr(file_obj, "name", "unknown"),
                                "uri": "",
                                "mime": getattr(file_obj, "mimeType", ""),
                                "bytes": len(getattr(file_obj, "bytes", b""))
                            })

                    elif isinstance(root_part, DataPart):
                        data = getattr(root_part, "data", None)
                        if isinstance(data, dict) and data.get("artifact-uri"):
                            received_files.append({
                                "name": data.get("file-name", "unknown"),
                                "uri": data.get("artifact-uri", ""),
                                "mime": data.get("mime", ""),
                            })

        if received_files:
            self._last_received_files = received_files
            print("[Branding Executor] Received file references:")
            for file_meta in received_files:
                print(f"  • name={file_meta.get('name')} uri={file_meta.get('uri')} mime={file_meta.get('mime')}")
            logger.info("📎 Received file references in A2A message", extra={"files": received_files, "context_id": context_id})
        else:
            logger.info("📎 No file references received in A2A message for context %s", context_id)
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
                
                # Check for HITL escalation
                if "HUMAN_ESCALATION_REQUIRED" in final_response:
                    logger.info(f"🚨 Human escalation detected for context {context_id}")
                    
                    # Set up pending request for human input
                    self._waiting_for_input[context_id] = final_response
                    self._pending_updaters[context_id] = task_updater
                    self._input_events[context_id] = asyncio.Event()
                    
                    # Track in class-level escalations for Gradio UI
                    async with FoundryTechnicalDispatchAgentExecutor._escalation_lock:
                        FoundryTechnicalDispatchAgentExecutor._pending_escalations[context_id] = final_response
                    
                    # Notify that human input is required
                    await task_updater.update_status(
                        TaskState.input_required,
                        message=new_agent_text_message(
                            f"Human expert input required for escalation: {context_id}", 
                            context_id=context_id
                        )
                    )
                    
                    logger.info(f"⏳ Waiting for human response for context {context_id}...")
                    # Wait for human input
                    await self._input_events[context_id].wait()
                    
                    # Get the human response
                    human_response = FoundryTechnicalDispatchAgentExecutor._escalation_responses.get(context_id)
                    if human_response:
                        logger.info(f"✅ Received human response for context {context_id}")
                        # Send human response back through agent and get final response
                        final_responses = []
                        async for event in agent.run_conversation_stream(thread_id, f"[HUMAN EXPERT RESPONSE]: {human_response}"):
                            if not event.startswith("🤖") and not event.startswith("🧠"):
                                final_responses.append(event)
                        
                        if final_responses:
                            final_response = final_responses[-1]
                        
                        logger.info(f"✅ Final response after human input: {final_response[:200]}...")
                    
                    # Clean up
                    self._waiting_for_input.pop(context_id, None)
                    self._pending_updaters.pop(context_id, None)
                    self._input_events.pop(context_id, None)
                    async with FoundryTechnicalDispatchAgentExecutor._escalation_lock:
                        FoundryTechnicalDispatchAgentExecutor._pending_escalations.pop(context_id, None)
                        FoundryTechnicalDispatchAgentExecutor._escalation_responses.pop(context_id, None)
                
                await task_updater.complete(
                    message=new_agent_text_message(final_response, context_id=context_id)
                )
            else:
                logger.warning("⚠️ No response generated by agent")
                await task_updater.complete(
                    message=new_agent_text_message("No response generated", context_id=context_id)
                )
                    
        except Exception as e:
            logger.error(f"❌ [AUTH EXECUTOR] Exception in _process_request: {e}", exc_info=True)
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
            elif isinstance(p.file, FileWithUri):
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
        logger.info(f"🔵 [AUTH EXECUTOR] Starting execute for context {context.context_id}")
        logger.info(f"🔵 [AUTH EXECUTOR] Request has message: {context.message is not None}")
        if context.message:
            logger.info(f"🔵 [AUTH EXECUTOR] Message has {len(context.message.parts)} parts")
        
        try:
            # CRITICAL: Apply rate limiting at the execute level to control between different user requests
            async with FoundryTechnicalDispatchAgentExecutor._request_semaphore:
                # Check API call rate limiting
                current_time = time.time()
                
                # Reset the window if it's been more than a minute
                if current_time - FoundryTechnicalDispatchAgentExecutor._api_call_window_start > 60:
                    FoundryTechnicalDispatchAgentExecutor._api_call_count = 0
                    FoundryTechnicalDispatchAgentExecutor._api_call_window_start = current_time
                
                # Check if we're approaching the API limit
                if FoundryTechnicalDispatchAgentExecutor._api_call_count >= FoundryTechnicalDispatchAgentExecutor._max_api_calls_per_minute:
                    wait_time = 60 - (current_time - FoundryTechnicalDispatchAgentExecutor._api_call_window_start)
                    if wait_time > 0:
                        logger.warning(f"API rate limit protection: waiting {wait_time:.1f}s to reset window")
                        await asyncio.sleep(wait_time)
                        # Reset counters
                        FoundryTechnicalDispatchAgentExecutor._api_call_count = 0
                        FoundryTechnicalDispatchAgentExecutor._api_call_window_start = time.time()
                
                # Enforce minimum interval between requests - THIS IS THE KEY FIX
                time_since_last = current_time - FoundryTechnicalDispatchAgentExecutor._last_request_time
                if time_since_last < FoundryTechnicalDispatchAgentExecutor._min_request_interval:
                    sleep_time = FoundryTechnicalDispatchAgentExecutor._min_request_interval - time_since_last
                    logger.warning(f"🚦 RATE LIMITING: Waiting {sleep_time:.2f}s between user requests (last request was {time_since_last:.2f}s ago)")
                    await asyncio.sleep(sleep_time)
                
                FoundryTechnicalDispatchAgentExecutor._last_request_time = time.time()
                
                logger.info(f"🔵 [AUTH EXECUTOR] Creating task updater")
                # Now proceed with the actual request processing
                updater = TaskUpdater(event_queue, context.task_id, context.context_id)
                if not context.current_task:
                    await updater.submit()
                
                logger.info(f"🔵 [AUTH EXECUTOR] Starting work on task {context.task_id}")
                await updater.start_work()
                
                logger.info(f"🔵 [AUTH EXECUTOR] Processing request with {len(context.message.parts if context.message else [])} parts")
                await self._process_request(
                    context.message.parts if context.message else [],
                    context.context_id,
                    updater,
                )
                logger.info(f"✅ [AUTH EXECUTOR] Completed execution for {context.context_id}")
        except Exception as e:
            logger.error(f"❌ [AUTH EXECUTOR] Error in execute: {e}", exc_info=True)
            raise

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


def create_foundry_agent_executor(card: AgentCard) -> FoundryTechnicalDispatchAgentExecutor:
    return FoundryTechnicalDispatchAgentExecutor(card)


# Alias for backward compatibility
TechnicalDispatchAgentExecutor = FoundryTechnicalDispatchAgentExecutor


async def initialize_foundry_agents_at_startup():
    """
    Convenience function to initialize shared agent resources at application startup.
    Call this once during your application's startup phase.

    Example usage in your main application:

    ```python
    # In your main startup code (e.g., main.py or app initialization)
    import asyncio
    from foundry_agent_executor import initialize_foundry_template_agents_at_startup

    async def startup():
        print("🚀 Starting agent application...")
        await initialize_foundry_template_agents_at_startup()
        print("✅ Agent initialization complete, ready to handle requests")

    # Run at startup
    asyncio.run(startup())
    ```
    """
    await FoundryTechnicalDispatchAgentExecutor.initialize_at_startup()
