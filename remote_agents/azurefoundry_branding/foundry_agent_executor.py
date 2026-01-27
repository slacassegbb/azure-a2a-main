"""
AI Foundry Branding & Content Agent Executor for the A2A framework.
Adapted from the ADK agent executor pattern to work with Azure AI Foundry agents
focused on brand-safe ideation, creative direction, and content reviews.
"""
import asyncio
import logging
import base64
import os
import tempfile
import time
from typing import Optional, Dict, List

from foundry_agent import FoundryBrandingAgent

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import AgentCard, DataPart, FilePart, FileWithBytes, FileWithUri, Message, Part, TaskState, TextPart
from a2a.utils.message import new_agent_text_message

logger = logging.getLogger(__name__)
# Set to INFO to hide verbose debug logs (can be changed to DEBUG for troubleshooting)
logger.setLevel(logging.INFO)


class FoundryBrandingAgentExecutor(AgentExecutor):
    """
    An AgentExecutor that runs Azure AI Foundry-based branding agents for
    consistent content strategy, creative direction, and brand compliance reviews.
    Adapted from the ADK agent executor pattern.
    """

    # Class-level shared agent instance to avoid multiple agent creations
    _shared_foundry_agent: Optional[FoundryBrandingAgent] = None
    _agent_lock = asyncio.Lock()
    _last_request_time: float = 0
    _min_request_interval: float = 1.0  # Reduced for parallel execution
    _request_semaphore = asyncio.Semaphore(3)  # Allow 3 concurrent requests for parallel execution
    _api_call_count: int = 0
    _api_call_window_start: float = 0
    _max_api_calls_per_minute: int = 30  # Increased for parallel execution
    _startup_complete: bool = False

    @classmethod
    async def get_shared_agent(cls) -> Optional[FoundryBrandingAgent]:
        """Get the shared agent that was initialized at startup (if available)."""
        async with cls._agent_lock:
            return cls._shared_foundry_agent
    
    @classmethod
    async def initialize_at_startup(cls) -> None:
        """Initialize the shared branding agent at startup instead of on first request."""
        async with cls._agent_lock:
            if not cls._shared_foundry_agent:
                logger.info("🚀 Initializing Foundry Branding agent at startup...")
                try:
                    cls._shared_foundry_agent = FoundryBrandingAgent()
                    await cls._shared_foundry_agent.create_agent()
                    cls._startup_complete = True
                    logger.info("✅ Foundry Branding agent startup initialization completed successfully")
                except Exception as e:
                    logger.error(f"❌ Failed to initialize branding agent at startup: {e}")
                    cls._shared_foundry_agent = None
                    cls._startup_complete = False
                    raise

    def __init__(self, card: AgentCard):
        self._active_threads: Dict[str, str] = {}  # context_id -> thread_id mapping
        self._waiting_for_input: Dict[str, str] = {}
        self._pending_updaters: Dict[str, TaskUpdater] = {}
        self._input_events: Dict[str, asyncio.Event] = {}
        self._last_received_files: List[Dict[str, str]] = []

    async def _get_or_create_agent(self) -> FoundryBrandingAgent:
        """Get the shared Foundry Branding agent (with fallback to lazy creation)."""
        async with FoundryBrandingAgentExecutor._agent_lock:
            if not FoundryBrandingAgentExecutor._shared_foundry_agent:
                if FoundryBrandingAgentExecutor._startup_complete:
                    # Startup was supposed to happen but failed
                    raise RuntimeError("Branding agent startup initialization failed - agent not available")

                # Fallback to lazy creation if startup wasn't called
                logger.warning("⚠️ Branding agent not initialized at startup, falling back to lazy creation...")
                FoundryBrandingAgentExecutor._shared_foundry_agent = FoundryBrandingAgent()
                await FoundryBrandingAgentExecutor._shared_foundry_agent.create_agent()
                logger.info("Fallback branding agent creation completed")
            return FoundryBrandingAgentExecutor._shared_foundry_agent

    async def _get_or_create_thread(
        self,
        context_id: str,
        agent: Optional[FoundryBrandingAgent] = None,
        force_new: bool = False
    ) -> str:
        if agent is None:
            agent = await self._get_or_create_agent()
        # Force new thread for parallel requests to avoid thread conflicts
        if force_new:
            thread = await agent.create_thread()
            thread_id = thread.id
            logger.info(f"Created new thread {thread_id} for parallel request (context: {context_id})")
            self._active_threads[context_id] = thread_id
            return thread_id
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
        logger.info(f"Executing request for context {context.context_id}")
        
        # CRITICAL: Apply rate limiting at the execute level to control between different user requests
        async with FoundryBrandingAgentExecutor._request_semaphore:
            # Check API call rate limiting
            current_time = time.time()
            
            # Reset the window if it's been more than a minute
            if current_time - FoundryBrandingAgentExecutor._api_call_window_start > 60:
                FoundryBrandingAgentExecutor._api_call_count = 0
                FoundryBrandingAgentExecutor._api_call_window_start = current_time
            
            # Log if approaching API limit (but don't block for parallel execution)
            if FoundryBrandingAgentExecutor._api_call_count >= FoundryBrandingAgentExecutor._max_api_calls_per_minute:
                logger.warning(f"⚠️ API call count ({FoundryBrandingAgentExecutor._api_call_count}) at limit, requests may be throttled by Azure")
            
            FoundryBrandingAgentExecutor._api_call_count += 1
            FoundryBrandingAgentExecutor._last_request_time = time.time()
            
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


def create_foundry_agent_executor(card: AgentCard) -> FoundryBrandingAgentExecutor:
    return FoundryBrandingAgentExecutor(card)


async def initialize_foundry_branding_agents_at_startup():
    """
    Convenience function to initialize shared branding agent resources at application startup.
    Call this once during your application's startup phase.

    Example usage in your main application:

    ```python
    # In your main startup code (e.g., main.py or app initialization)
    import asyncio
    from foundry_agent_executor import initialize_foundry_branding_agents_at_startup

    async def startup():
        print("🚀 Starting branding application...")
        await initialize_foundry_branding_agents_at_startup()
        print("✅ Branding agent initialization complete, ready to handle requests")

    # Run at startup
    asyncio.run(startup())
    ```
    """
    await FoundryBrandingAgentExecutor.initialize_at_startup()