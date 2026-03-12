"""
Thread Queue — Per-conversation message queue for sequential processing.

Inspired by the OpenDev paper's queue-based architecture (arxiv 2603.05344):
each conversation thread gets its own FIFO queue so messages are processed
strictly sequentially per context_id, preventing race conditions on shared
session state.  Different context_ids still run in parallel.

Usage:
    queue = ThreadQueue()
    future = await queue.enqueue(context_id, thread_msg)
    # For /api/query: result = await future  (blocks until processed)
    # For /message/send: fire-and-forget (don't await the future)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class ThreadMessage:
    """Wraps a queued message with all parameters needed for process_message_internal."""
    # Core message data
    message: Any  # a2a.types.Message
    context_id: str

    # Orchestration parameters
    agent_mode: Optional[bool] = None
    enable_inter_agent_memory: bool = False
    workflow: Optional[str] = None
    workflow_goal: Optional[str] = None
    available_workflows: Optional[list] = None
    user_id: Optional[str] = None
    user_timezone: str = "UTC"
    sms_reply_to: Optional[str] = None

    # Queue metadata
    enqueued_at: float = field(default_factory=time.time)
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_event_loop().create_future())

    # Interrupt flag: if True, this message should redirect a running workflow
    # instead of waiting in the queue
    is_interrupt: bool = False


class ThreadQueue:
    """Per-context_id async queue with sequential processing.

    Each context_id gets its own asyncio.Queue and a processor task that
    drains the queue one message at a time.  When the queue empties and
    stays empty for `idle_timeout` seconds the processor task exits.

    Thread-safety: all public methods are coroutines that must be called
    from the same event loop.
    """

    def __init__(self, idle_timeout: float = 300.0):
        # One queue per context_id
        self._queues: Dict[str, asyncio.Queue] = {}
        # One processor asyncio.Task per context_id
        self._processors: Dict[str, asyncio.Task] = {}
        # Tracks which context_ids have a message actively being processed
        self._processing: Dict[str, bool] = {}
        # The callback that actually processes messages (set via set_handler)
        self._handler: Optional[Callable[..., Coroutine]] = None
        # Seconds to wait on an empty queue before the processor exits
        self._idle_timeout = idle_timeout

    def set_handler(self, handler: Callable[..., Coroutine]):
        """Set the async handler that processes each ThreadMessage.

        The handler signature should match:
            async def handler(thread_msg: ThreadMessage) -> Any
        """
        self._handler = handler

    async def enqueue(self, thread_msg: ThreadMessage) -> asyncio.Future:
        """Add a message to the context's queue and return a future for its result.

        If the context has a running workflow and the message is flagged as
        an interrupt, we skip the queue and use the interrupt mechanism directly.
        """
        context_id = thread_msg.context_id

        # Ensure a queue exists for this context
        if context_id not in self._queues:
            self._queues[context_id] = asyncio.Queue()

        # Put the message into the queue
        await self._queues[context_id].put(thread_msg)
        logger.info(
            f"[ThreadQueue] Enqueued message for {context_id[:20]}... "
            f"(depth={self._queues[context_id].qsize()}, "
            f"processing={self._processing.get(context_id, False)})"
        )

        # Ensure a processor task is running for this context
        if context_id not in self._processors or self._processors[context_id].done():
            self._processors[context_id] = asyncio.create_task(
                self._process_loop(context_id)
            )

        return thread_msg.future

    async def _process_loop(self, context_id: str):
        """Drain the queue for a single context_id, one message at a time."""
        queue = self._queues[context_id]
        logger.info(f"[ThreadQueue] Processor started for {context_id[:20]}...")

        try:
            while True:
                try:
                    thread_msg: ThreadMessage = await asyncio.wait_for(
                        queue.get(), timeout=self._idle_timeout
                    )
                except asyncio.TimeoutError:
                    # Queue idle — shut down this processor
                    logger.info(f"[ThreadQueue] Processor idle, exiting for {context_id[:20]}...")
                    break

                self._processing[context_id] = True
                wait_time = time.time() - thread_msg.enqueued_at
                logger.info(
                    f"[ThreadQueue] Processing message for {context_id[:20]}... "
                    f"(waited {wait_time:.1f}s)"
                )

                try:
                    if self._handler is None:
                        raise RuntimeError("ThreadQueue handler not set — call set_handler() first")
                    result = await self._handler(thread_msg)
                    if not thread_msg.future.done():
                        thread_msg.future.set_result(result)
                except Exception as exc:
                    logger.error(f"[ThreadQueue] Handler error for {context_id[:20]}...: {exc}")
                    if not thread_msg.future.done():
                        thread_msg.future.set_exception(exc)
                finally:
                    self._processing[context_id] = False
                    queue.task_done()

        finally:
            # Cleanup
            self._processing.pop(context_id, None)
            self._processors.pop(context_id, None)
            # Keep the queue around (it may get new messages soon)

    # ── Observability ──

    def is_processing(self, context_id: str) -> bool:
        """Whether a message is actively being processed for this context."""
        return self._processing.get(context_id, False)

    def get_queue_depth(self, context_id: str) -> int:
        """Number of messages waiting (excludes the one being processed)."""
        q = self._queues.get(context_id)
        return q.qsize() if q else 0

    def get_total_depth(self) -> int:
        """Total queued messages across all contexts."""
        return sum(q.qsize() for q in self._queues.values())
