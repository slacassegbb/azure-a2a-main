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

from foundry_agent import FoundryEmailAgent

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import AgentCard, DataPart, FilePart, FileWithBytes, FileWithUri, Message, Part, TaskState, TextPart
from a2a.utils.message import new_agent_text_message

logger = logging.getLogger(__name__)
# Set to INFO to hide verbose debug logs (can be changed to DEBUG for troubleshooting)
logger.setLevel(logging.INFO)


class FoundryTemplateAgentExecutor(AgentExecutor):
    """
    An AgentExecutor template for Azure AI Foundry-based agents.
    This handles A2A protocol integration, file handling, and streaming responses.
    Customize the agent behavior in foundry_agent.py, not here.
    """

    # Class-level shared agent instance to avoid multiple agent creations
    _shared_foundry_agent: Optional[FoundryEmailAgent] = None
    _agent_lock = asyncio.Lock()
    _last_request_time: float = 0
    _min_request_interval: float = 5.0  # Increase to 5 seconds minimum between requests
    _request_semaphore = asyncio.Semaphore(1)  # Max 1 concurrent request
    _api_call_count: int = 0
    _api_call_window_start: float = 0
    _max_api_calls_per_minute: int = 15  # Much more conservative - 15 calls per minute
    _startup_complete: bool = False

    @classmethod
    async def get_shared_agent(cls) -> Optional[FoundryEmailAgent]:
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
                    cls._shared_foundry_agent = FoundryEmailAgent()
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

    async def _get_or_create_agent(self) -> FoundryEmailAgent:
        """Get the shared Foundry Email agent (with fallback to lazy creation)."""
        async with FoundryTemplateAgentExecutor._agent_lock:
            if not FoundryTemplateAgentExecutor._shared_foundry_agent:
                if FoundryTemplateAgentExecutor._startup_complete:
                    # Startup was supposed to happen but failed
                    raise RuntimeError("Email agent startup initialization failed - agent not available")

                # Fallback to lazy creation if startup wasn't called
                logger.warning("⚠️ Email agent not initialized at startup, falling back to lazy creation...")
                FoundryTemplateAgentExecutor._shared_foundry_agent = FoundryEmailAgent()
                await FoundryTemplateAgentExecutor._shared_foundry_agent.create_agent()
                logger.info("Fallback email agent creation completed")
            return FoundryTemplateAgentExecutor._shared_foundry_agent

    async def _get_or_create_thread(
        self,
        context_id: str,
        agent: Optional[FoundryEmailAgent] = None
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
            print("[Email Executor] Received file references:")
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
        async with FoundryTemplateAgentExecutor._request_semaphore:
            # Check API call rate limiting
            current_time = time.time()
            
            # Reset the window if it's been more than a minute
            if current_time - FoundryTemplateAgentExecutor._api_call_window_start > 60:
                FoundryTemplateAgentExecutor._api_call_count = 0
                FoundryTemplateAgentExecutor._api_call_window_start = current_time
            
            # Check if we're approaching the API limit
            if FoundryTemplateAgentExecutor._api_call_count >= FoundryTemplateAgentExecutor._max_api_calls_per_minute:
                wait_time = 60 - (current_time - FoundryTemplateAgentExecutor._api_call_window_start)
                if wait_time > 0:
                    logger.warning(f"API rate limit protection: waiting {wait_time:.1f}s to reset window")
                    await asyncio.sleep(wait_time)
                    # Reset counters
                    FoundryTemplateAgentExecutor._api_call_count = 0
                    FoundryTemplateAgentExecutor._api_call_window_start = time.time()
            
            # Enforce minimum interval between requests - THIS IS THE KEY FIX
            time_since_last = current_time - FoundryTemplateAgentExecutor._last_request_time
            if time_since_last < FoundryTemplateAgentExecutor._min_request_interval:
                sleep_time = FoundryTemplateAgentExecutor._min_request_interval - time_since_last
                logger.warning(f"🚦 RATE LIMITING: Waiting {sleep_time:.2f}s between user requests (last request was {time_since_last:.2f}s ago)")
                await asyncio.sleep(sleep_time)
            
            FoundryTemplateAgentExecutor._last_request_time = time.time()
            
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


def create_foundry_agent_executor(card: AgentCard) -> FoundryTemplateAgentExecutor:
    return FoundryTemplateAgentExecutor(card)


async def initialize_foundry_template_agents_at_startup():
    """
    Convenience function to initialize shared agent resources at application startup.
    Call this once during your application's startup phase.
    """
    await FoundryTemplateAgentExecutor.initialize_at_startup()
