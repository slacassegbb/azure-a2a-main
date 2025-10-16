"""
AI Foundry Agent Executor for A2A framework.
Adapted from ADK agent executor pattern to work with Azure AI Foundry agents.
"""
import asyncio
import logging
import base64
import os
import tempfile
import time
import uuid
from typing import Optional, Dict, Any, List
import re

from foundry_agent import FoundryLegalAgent

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    AgentCard,
    FilePart,
    FileWithBytes,
    FileWithUri,
    Part,
    TaskState,
    TextPart,
)
from a2a.utils.message import new_agent_text_message

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def extract_and_format_context(user_message: str) -> (str, str):
    """Extract context and current request from the user message string."""
    context_match = re.search(
        r"Relevant context from previous interactions:(.*)Current request:(.*)",
        user_message,
        re.DOTALL
    )
    if context_match:
        context_block = context_match.group(1).strip()
        current_request = context_match.group(2).strip()
        # Optionally, further parse context_block for better formatting
        return context_block, current_request
    else:
        # Fallback: treat the whole message as the current request
        return "", user_message


class FoundryLegalAgentExecutor(AgentExecutor):
    """
    An AgentExecutor that runs Azure AI Foundry-based legal agents.
    Adapted from the ADK agent executor pattern.
    """

    # Class-level shared agent instance to avoid multiple agent creations
    _shared_foundry_agent: Optional[FoundryLegalAgent] = None
    _agent_lock = asyncio.Lock()
    _last_request_time: float = 0
    _min_request_interval: float = 5.0  # Increase to 5 seconds minimum between requests
    _request_semaphore = asyncio.Semaphore(1)  # Max 1 concurrent request
    _api_call_count: int = 0
    _api_call_window_start: float = 0
    _max_api_calls_per_minute: int = 15  # Much more conservative - 15 calls per minute
    _startup_complete: bool = False

    @classmethod
    async def get_shared_agent(cls) -> Optional[FoundryLegalAgent]:
        """Get the shared legal agent that was initialized at startup (if available)."""
        async with cls._agent_lock:
            return cls._shared_foundry_agent
    
    @classmethod
    async def initialize_at_startup(cls) -> None:
        """Initialize the shared legal agent at startup instead of on first request."""
        async with cls._agent_lock:
            if not cls._shared_foundry_agent:
                logger.info("🚀 Initializing Foundry legal agent at startup...")
                try:
                    cls._shared_foundry_agent = FoundryLegalAgent()
                    await cls._shared_foundry_agent.create_agent()
                    cls._startup_complete = True
                    logger.info("✅ Foundry legal agent startup initialization completed successfully")
                except Exception as e:
                    logger.error(f"❌ Failed to initialize legal agent at startup: {e}")
                    cls._shared_foundry_agent = None
                    cls._startup_complete = False
                    raise

    def __init__(self, card: AgentCard):
        self._card = card
        self._active_threads: Dict[str, str] = {}  # context_id -> thread_id mapping
        self._waiting_for_input: Dict[str, str] = {}
        self._pending_updaters: Dict[str, TaskUpdater] = {}
        self._input_events: Dict[str, asyncio.Event] = {}

    async def _get_or_create_agent(self) -> FoundryLegalAgent:
        """Get the shared Foundry Legal agent (with fallback to lazy creation)."""
        async with FoundryLegalAgentExecutor._agent_lock:
            if not FoundryLegalAgentExecutor._shared_foundry_agent:
                if FoundryLegalAgentExecutor._startup_complete:
                    # Startup was supposed to happen but failed
                    raise RuntimeError("Agent startup initialization failed - agent not available")
                
                # Fallback to lazy creation if startup wasn't called
                logger.warning("⚠️ Agent not initialized at startup, falling back to lazy creation...")
                FoundryLegalAgentExecutor._shared_foundry_agent = FoundryLegalAgent()
                await FoundryLegalAgentExecutor._shared_foundry_agent.create_agent()
                logger.info("Fallback agent creation completed")
            return FoundryLegalAgentExecutor._shared_foundry_agent

    async def _get_or_create_thread(
        self,
        context_id: str,
        agent: Optional[FoundryLegalAgent] = None
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

    def _notify_ui_of_pending_request(self, context_id: str, request_text: str):
        """Notify the UI about a new pending request."""
        try:
            from __main__ import pending_request_notification
            pending_request_notification.update({
                "has_pending": True,
                "request_text": request_text,
                "context_id": context_id
            })
            logger.info(f"UI notified of pending request for context {context_id}")
        except ImportError:
            logger.debug("UI notification not available (A2A-only mode)")

    def _get_conversation_context_from_request(self, request_context: RequestContext) -> str:
        """Extract conversation context from the RequestContext."""
        try:
            if not request_context:
                logger.info("No RequestContext available")
                return ""
            
            # Debug: Let's see what's actually in the RequestContext
            logger.info(f"RequestContext attributes: {dir(request_context)}")
            logger.info(f"RequestContext type: {type(request_context)}")
            
            # Check if we have a task
            if hasattr(request_context, 'task') and request_context.task:
                logger.info(f"Found task: {request_context.task}")
                if hasattr(request_context.task, 'history') and request_context.task.history:
                    logger.info(f"Found {len(request_context.task.history)} messages in task history")
                    
                    context_messages = []
                    for msg in request_context.task.history:
                        if hasattr(msg, 'role') and hasattr(msg, 'parts'):
                            # Extract text content from message parts
                            text_content = ""
                            for part in msg.parts:
                                if hasattr(part, 'root') and hasattr(part.root, 'text'):
                                    text_content += part.root.text
                            
                            if text_content.strip():
                                if msg.role == 'user':
                                    context_messages.append(f"User: {text_content.strip()}")
                                    logger.info(f"Added user context: {text_content.strip()[:50]}...")
                                elif msg.role == 'agent':
                                    # Truncate long assistant responses
                                    content = text_content.strip()
                                    if len(content) > 200:
                                        content = content[:197] + "..."
                                    context_messages.append(f"Assistant: {content}")
                                    logger.info(f"Added assistant context: {content[:50]}...")
                    
                    # Return the last 4 messages for context (2 exchanges)
                    recent_context = context_messages[-4:] if len(context_messages) > 4 else context_messages
                    result = "\n".join(recent_context)
                    logger.info(f"Final conversation context from RequestContext: {result[:100]}...")
                    return result
                else:
                    logger.info("Task has no history")
            else:
                logger.info("No task found in RequestContext")
            
            # Check if we have a userMessage
            if hasattr(request_context, 'userMessage') and request_context.userMessage:
                logger.info(f"Found userMessage: {request_context.userMessage}")
                # For now, just return the user message as context
                if hasattr(request_context.userMessage, 'parts'):
                    text_content = ""
                    for part in request_context.userMessage.parts:
                        if hasattr(part, 'root') and hasattr(part.root, 'text'):
                            text_content += part.root.text
                    if text_content.strip():
                        return f"User: {text_content.strip()}"
            
            logger.info("No conversation context found in RequestContext")
            return ""
            
        except Exception as e:
            logger.warning(f"Failed to extract conversation context from RequestContext: {e}")
            return ""

    async def _get_conversation_context(self, agent, thread_id: str) -> str:
        """Retrieve conversation context from the Azure AI Foundry thread."""
        try:
            client = agent._get_client()
            from azure.ai.agents.models import ListSortOrder
            messages = list(client.messages.list(thread_id=thread_id, order=ListSortOrder.ASCENDING))
            
            logger.info(f"Retrieved {len(messages)} messages from thread {thread_id}")
            
            if len(messages) <= 1:  # Only the current message
                logger.info("Only current message found, no previous context")
                return ""
            
            # Get the last few messages for context (excluding the current message)
            context_messages = []
            for i, msg in enumerate(messages[:-1]):  # Exclude the current message
                logger.info(f"Processing message {i}: role={msg.role}, content_count={len(msg.content) if msg.content else 0}")
                
                if msg.role == "user" and msg.content:
                    # Get user message content
                    user_content = ""
                    for content_item in msg.content:
                        if hasattr(content_item, 'text') and hasattr(content_item.text, 'value'):
                            user_content += content_item.text.value
                    if user_content.strip():
                        context_messages.append(f"User: {user_content.strip()}")
                        logger.info(f"Added user context: {user_content.strip()[:50]}...")
                
                elif msg.role == "assistant" and msg.content:
                    # Get assistant message content
                    assistant_content = ""
                    for content_item in msg.content:
                        if hasattr(content_item, 'text') and hasattr(content_item.text, 'value'):
                            assistant_content += content_item.text.value
                    if assistant_content.strip():
                        # Truncate long assistant responses
                        content = assistant_content.strip()
                        if len(content) > 200:
                            content = content[:197] + "..."
                        context_messages.append(f"Assistant: {content}")
                        logger.info(f"Added assistant context: {content[:50]}...")
            
            # Return the last 4 messages for context (2 exchanges)
            recent_context = context_messages[-4:] if len(context_messages) > 4 else context_messages
            result = "\n".join(recent_context)
            logger.info(f"Final conversation context: {result[:100]}...")
            return result
            
        except Exception as e:
            logger.warning(f"Failed to retrieve conversation context: {e}")
            return ""

    async def _should_require_human_input(self, user_message: str) -> bool:
        """Determine if human expert input is required via simple keyword matching."""
        human_keywords = [
            "human", "representative", "speak with", "transfer", "agent", "support staff"
        ]
        lower = user_message.lower()
        requires = any(k in lower for k in human_keywords)
        logger.info(f"Human input required: {requires}")
        return requires

    async def send_human_response(self, context_id: str, human_response: str) -> bool:
        """Send human response to complete a pending input_required task."""
        if context_id in self._waiting_for_input and context_id in self._pending_updaters:
            updater = self._pending_updaters[context_id]
            await updater.complete(
                message=new_agent_text_message(
                    f"Expert Response: {human_response}", context_id=context_id
                )
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
            logger.info(f"Converted user message: {user_message}")
            logger.info(f"Message parts count: {len(message_parts)}")
            for i, part in enumerate(message_parts):
                logger.info(f"Part {i}: {part}")
                if hasattr(part, 'root'):
                    logger.info(f"Part {i} root: {part.root}")
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
                # Check for human escalation
                elif event.strip().upper().startswith("HUMAN_ESCALATION_REQUIRED"):
                    responses.append(event)
                    
                    # Debug: Let's see what's in the RequestContext from the host agent
                    logger.info(f"RequestContext type: {type(request_context)}")
                    logger.info(f"RequestContext attributes: {dir(request_context)}")
                    
                    # Try to get conversation history from different sources
                    conversation_history = ""
                    
                    # Method 1: Check if we have a task with history
                    if hasattr(request_context, 'task') and request_context.task:
                        logger.info(f"Task attributes: {dir(request_context.task)}")
                        if hasattr(request_context.task, 'history'):
                            logger.info(f"Task history length: {len(request_context.task.history) if request_context.task.history else 0}")
                            if request_context.task.history:
                                for i, msg in enumerate(request_context.task.history):
                                    logger.info(f"History message {i}: {msg}")
                                    # Extract text content from message
                                    if hasattr(msg, 'parts') and msg.parts:
                                        for part in msg.parts:
                                            if hasattr(part, 'root') and hasattr(part.root, 'text'):
                                                text = part.root.text
                                                if text.strip():
                                                    conversation_history += f"{text}\n"
                    
                    # Method 2: Check if we have a current_task with history
                    if hasattr(request_context, 'current_task') and request_context.current_task:
                        logger.info(f"Current task attributes: {dir(request_context.current_task)}")
                        if hasattr(request_context.current_task, 'history'):
                            logger.info(f"Current task history length: {len(request_context.current_task.history) if request_context.current_task.history else 0}")
                            if request_context.current_task.history:
                                for i, msg in enumerate(request_context.current_task.history):
                                    logger.info(f"Current task history message {i}: {msg}")
                                    # Extract text content from message
                                    if hasattr(msg, 'parts') and msg.parts:
                                        for part in msg.parts:
                                            if hasattr(part, 'root') and hasattr(part.root, 'text'):
                                                text = part.root.text
                                                if text.strip():
                                                    conversation_history += f"{text}\n"
                    
                    # Method 3: Check if we have related_tasks with history
                    if hasattr(request_context, 'related_tasks') and request_context.related_tasks:
                        logger.info(f"Related tasks count: {len(request_context.related_tasks)}")
                        for i, task in enumerate(request_context.related_tasks):
                            if hasattr(task, 'history') and task.history:
                                logger.info(f"Related task {i} history length: {len(task.history)}")
                                for j, msg in enumerate(task.history):
                                    logger.info(f"Related task {i} history message {j}: {msg}")
                                    # Extract text content from message
                                    if hasattr(msg, 'parts') and msg.parts:
                                        for part in msg.parts:
                                            if hasattr(part, 'root') and hasattr(part.root, 'text'):
                                                text = part.root.text
                                                if text.strip():
                                                    conversation_history += f"{text}\n"
                    
                    logger.info(f"Extracted conversation history: {conversation_history}")
                    logger.info(f"Using raw user message from host agent: {user_message}")
                    
                    # Build the full request text with conversation history
                    full_request_text = ""
                    if conversation_history.strip():
                        full_request_text += f"Conversation History:\n{conversation_history}\n\n"
                    full_request_text += f"Current Request: {user_message}"
                    
                    logger.info(f"Full request text: {full_request_text}")
                    
                    # Set up pending request for human input
                    self._waiting_for_input[context_id] = full_request_text
                    self._pending_updaters[context_id] = task_updater
                    self._input_events[context_id] = asyncio.Event()
                    self._notify_ui_of_pending_request(context_id, full_request_text)
                    await task_updater.update_status(
                        TaskState.input_required,
                        message=new_agent_text_message(
                            f"Human expert input required: {user_message}", context_id=context_id
                        )
                    )
                    # Wait for human input
                    await self._input_events[context_id].wait()
                    # After human input, clean up
                    self._waiting_for_input.pop(context_id, None)
                    self._pending_updaters.pop(context_id, None)
                    self._input_events.pop(context_id, None)
                    return
                # Otherwise, treat as a regular response
                else:
                    responses.append(event)
            
            # Emit the final response
            if responses:
                await task_updater.complete(
                    message=new_agent_text_message(responses[-1], context_id=context_id)
                )
            else:
                await task_updater.complete(
                    message=new_agent_text_message("No response generated", context_id=context_id)
                )
                    
        except Exception as e:
            await task_updater.failed(
                message=new_agent_text_message(f"Error: {e}", context_id=context_id)
            )

    async def _run_agent_with_monitoring(
        self, 
        agent, 
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
                # Check for human escalation
                elif event.strip().upper().startswith("HUMAN_ESCALATION_REQUIRED"):
                    responses.append(event)
                    return (responses, tools_called)
                # Otherwise, treat as a regular response
                else:
                    responses.append(event)
                    
        except Exception as e:
            await task_updater.failed(
                message=new_agent_text_message(f"Agent execution error: {e}", context_id=context_id)
            )
            return ([], [])
            
        return (responses, tools_called)

    async def _cleanup_thread_later(self, agent: FoundryLegalAgent, thread_id: str):
        """Clean up a thread after a delay to avoid interfering with active runs."""
        try:
            # Wait much longer to ensure any active runs are complete and rate limits reset
            await asyncio.sleep(60)  # Wait 1 minute before cleanup
            client = agent._get_client()
            client.threads.delete(thread_id)
            logger.info(f"Delayed cleanup: deleted Azure thread {thread_id}")
        except Exception as e:
            logger.warning(f"Delayed cleanup failed for thread {thread_id}: {e}")

    def _convert_parts_to_text(self, parts: List[Part]) -> str:
        """Convert message parts to plain text, saving any files locally."""
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
        return " ".join(texts)

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ):
        logger.info(f"Executing request for context {context.context_id}")
        
        # CRITICAL: Apply rate limiting at the execute level to control between different user requests
        async with FoundryLegalAgentExecutor._request_semaphore:
            # Check API call rate limiting
            current_time = time.time()
            
            # Reset the window if it's been more than a minute
            if current_time - FoundryLegalAgentExecutor._api_call_window_start > 60:
                FoundryLegalAgentExecutor._api_call_count = 0
                FoundryLegalAgentExecutor._api_call_window_start = current_time
            
            # Check if we're approaching the API limit
            if FoundryLegalAgentExecutor._api_call_count >= FoundryLegalAgentExecutor._max_api_calls_per_minute:
                wait_time = 60 - (current_time - FoundryLegalAgentExecutor._api_call_window_start)
                if wait_time > 0:
                    logger.warning(f"API rate limit protection: waiting {wait_time:.1f}s to reset window")
                    await asyncio.sleep(wait_time)
                    # Reset counters
                    FoundryLegalAgentExecutor._api_call_count = 0
                    FoundryLegalAgentExecutor._api_call_window_start = time.time()
            
            # Enforce minimum interval between requests - THIS IS THE KEY FIX
            time_since_last = current_time - FoundryLegalAgentExecutor._last_request_time
            if time_since_last < FoundryLegalAgentExecutor._min_request_interval:
                sleep_time = FoundryLegalAgentExecutor._min_request_interval - time_since_last
                logger.warning(f"🚦 RATE LIMITING: Waiting {sleep_time:.2f}s between user requests (last request was {time_since_last:.2f}s ago)")
                await asyncio.sleep(sleep_time)
            
            FoundryLegalAgentExecutor._last_request_time = time.time()
            
            # Now proceed with the actual request processing
            updater = TaskUpdater(event_queue, context.task_id, context.context_id)
            if not context.current_task:
                await updater.submit()
            await updater.start_work()
            await self._process_request(
                context.message.parts if context.message else [],
                context.context_id,
                updater,
                context,  # Pass the full RequestContext
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


def create_foundry_legal_agent_executor(card: AgentCard) -> FoundryLegalAgentExecutor:
    return FoundryLegalAgentExecutor(card)


async def create_foundry_legal_agent_executor_with_startup(card: AgentCard) -> FoundryLegalAgentExecutor:
    """Create executor and initialize the shared legal agent at startup."""
    await FoundryLegalAgentExecutor.initialize_at_startup()
    return FoundryLegalAgentExecutor(card)


async def initialize_foundry_legal_agents_at_startup():
    """
    Convenience function to initialize shared legal agent resources at application startup.
    Call this once during your application's startup phase.
    
    Example usage in your main application:
    
    ```python
    # In your main startup code (e.g., main.py or app initialization)
    import asyncio
    from foundry_agent_executor import initialize_foundry_legal_agents_at_startup
    
    async def startup():
        print("🚀 Starting legal application...")
        await initialize_foundry_legal_agents_at_startup()
        print("✅ Legal agent initialization complete, ready to handle requests")
    
    # Run at startup
    asyncio.run(startup())
    ```
    """
    await FoundryLegalAgentExecutor.initialize_at_startup()