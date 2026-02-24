"""
AI Foundry Agent Executor for A2A framework - Time Series Agent.
"""
import asyncio
import logging
import base64
import os
import re
import tempfile
import time
import uuid
from typing import Optional, Dict, Any, List

from foundry_agent import FoundryTimeSeriesAgent

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    AgentCard, FilePart, FileWithBytes, FileWithUri,
    DataPart, Message, Part, TaskState, TextPart,
)
from a2a.utils.message import new_agent_text_message

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class FoundryAgentExecutor(AgentExecutor):
    _shared_foundry_agent: Optional[FoundryTimeSeriesAgent] = None
    _agent_lock = asyncio.Lock()
    _last_request_time: float = 0
    _min_request_interval: float = 1.0
    _request_semaphore = asyncio.Semaphore(3)
    _api_call_count: int = 0
    _api_call_window_start: float = 0
    _max_api_calls_per_minute: int = 30
    _startup_complete: bool = False

    @classmethod
    async def get_shared_agent(cls) -> Optional[FoundryTimeSeriesAgent]:
        async with cls._agent_lock:
            return cls._shared_foundry_agent

    @classmethod
    async def initialize_at_startup(cls) -> None:
        async with cls._agent_lock:
            if not cls._shared_foundry_agent:
                try:
                    cls._shared_foundry_agent = FoundryTimeSeriesAgent()
                    await cls._shared_foundry_agent.create_agent()
                    cls._startup_complete = True
                except Exception as e:
                    cls._shared_foundry_agent = None
                    cls._startup_complete = False
                    raise

    def __init__(self, card: AgentCard):
        self._active_sessions: Dict[str, str] = {}
        self._waiting_for_input: Dict[str, str] = {}
        self._pending_updaters: Dict[str, TaskUpdater] = {}
        self._input_events: Dict[str, asyncio.Event] = {}

    async def _get_or_create_agent(self) -> FoundryTimeSeriesAgent:
        async with FoundryAgentExecutor._agent_lock:
            if not FoundryAgentExecutor._shared_foundry_agent:
                if FoundryAgentExecutor._startup_complete:
                    raise RuntimeError("Agent startup initialization failed")
                FoundryAgentExecutor._shared_foundry_agent = FoundryTimeSeriesAgent()
                await FoundryAgentExecutor._shared_foundry_agent.create_agent()
            return FoundryAgentExecutor._shared_foundry_agent

    async def _get_or_create_session(self, context_id: str, agent=None, force_new=False) -> str:
        if agent is None:
            agent = await self._get_or_create_agent()
        if force_new or context_id not in self._active_sessions:
            session_id = await agent.create_session()
            self._active_sessions[context_id] = session_id
            return session_id
        return self._active_sessions[context_id]

    async def send_human_response(self, context_id: str, human_response: str) -> bool:
        if context_id in self._waiting_for_input and context_id in self._pending_updaters:
            updater = self._pending_updaters[context_id]
            await updater.complete(message=new_agent_text_message(human_response, context_id=context_id))
            if context_id in self._input_events:
                self._input_events[context_id].set()
            return True
        return False

    async def _process_request(self, message_parts, context_id, task_updater, request_context=None):
        try:
            user_message = self._convert_parts_to_text(message_parts)
            agent = await self._get_or_create_agent()
            session_id = await self._get_or_create_session(context_id, agent)
            responses = []
            seen_tools = set()

            async for event in agent.run_conversation_stream(session_id, user_message):
                if event.startswith("\U0001f6e0\ufe0f Remote agent executing:"):
                    tool_desc = event.replace("\U0001f6e0\ufe0f Remote agent executing: ", "").strip()
                    if tool_desc not in seen_tools:
                        seen_tools.add(tool_desc)
                        await task_updater.update_status(
                            TaskState.working,
                            message=new_agent_text_message(event, context_id=context_id)
                        )
                elif event.startswith("Error:") or event.startswith("\u274c"):
                    await task_updater.failed(message=new_agent_text_message(event, context_id=context_id))
                    return
                elif "```NEEDS_INPUT" in event or event.strip().startswith("NEEDS_INPUT:"):
                    block_match = re.search(r'```NEEDS_INPUT\s*\n(.*?)\n```END_NEEDS_INPUT', event, re.DOTALL)
                    question = block_match.group(1).strip() if block_match else event.replace("NEEDS_INPUT:", "", 1).strip()
                    self._waiting_for_input[context_id] = {"question": question, "session_id": session_id}
                    parts_out = [TextPart(text=question)]
                    if hasattr(agent, 'last_token_usage') and agent.last_token_usage:
                        parts_out.append(DataPart(data={'type': 'token_usage', **agent.last_token_usage}))
                    await task_updater.update_status(
                        TaskState.input_required,
                        message=Message(role="agent", messageId=str(uuid.uuid4()), parts=parts_out, contextId=context_id),
                        final=True
                    )
                    return
                else:
                    responses.append(event)

            if responses:
                final_response = responses[-1]
                block_match = re.search(r'```NEEDS_INPUT\s*\n(.*?)\n```END_NEEDS_INPUT', final_response, re.DOTALL)
                if block_match or final_response.strip().startswith("NEEDS_INPUT:"):
                    question = block_match.group(1).strip() if block_match else final_response.replace("NEEDS_INPUT:", "", 1).strip()
                    self._waiting_for_input[context_id] = {"question": question, "session_id": session_id}
                    parts_out = [TextPart(text=question)]
                    if hasattr(agent, 'last_token_usage') and agent.last_token_usage:
                        parts_out.append(DataPart(data={'type': 'token_usage', **agent.last_token_usage}))
                    await task_updater.update_status(
                        TaskState.input_required,
                        message=Message(role="agent", messageId=str(uuid.uuid4()), parts=parts_out, contextId=context_id),
                        final=True
                    )
                    return

                # Check final response for "Error:" prefix
                if final_response.lstrip().startswith("Error:"):
                    await task_updater.failed(
                        message=new_agent_text_message(final_response, context_id=context_id)
                    )
                    return

                parts_out = [TextPart(text=final_response)]
                if hasattr(agent, 'last_token_usage') and agent.last_token_usage:
                    parts_out.append(DataPart(data={'type': 'token_usage', **agent.last_token_usage}))
                await task_updater.complete(
                    message=Message(role="agent", messageId=str(uuid.uuid4()), parts=parts_out, contextId=context_id)
                )
            else:
                await task_updater.failed(
                    message=Message(role="agent", messageId=str(uuid.uuid4()), parts=[TextPart(text="No response generated")], contextId=context_id)
                )
        except Exception as e:
            await task_updater.failed(message=new_agent_text_message(f"Error: {e}", context_id=context_id))

    def _convert_parts_to_text(self, parts: List[Part]) -> str:
        texts = []
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
            elif isinstance(p, DataPart):
                try:
                    import json as _json
                    payload = getattr(p, "data", None) or getattr(p, "value", None)
                    texts.append(f"[Data: {payload if isinstance(payload, str) else _json.dumps(payload)[:500]}]")
                except Exception:
                    texts.append("[Data payload]")
        return " ".join(texts)

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        async with FoundryAgentExecutor._request_semaphore:
            current_time = time.time()
            if current_time - FoundryAgentExecutor._api_call_window_start > 60:
                FoundryAgentExecutor._api_call_count = 0
                FoundryAgentExecutor._api_call_window_start = current_time
            FoundryAgentExecutor._api_call_count += 1
            FoundryAgentExecutor._last_request_time = time.time()

            updater = TaskUpdater(event_queue, context.task_id, context.context_id)
            if not context.current_task:
                await updater.submit()
            await updater.start_work()
            await self._process_request(
                context.message.parts if context.message else [],
                context.context_id, updater, context,
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        if context.context_id in self._input_events:
            self._input_events[context.context_id].set()
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.failed(message=new_agent_text_message("Task cancelled", context_id=context.context_id))

    async def cleanup(self):
        self._active_sessions.clear()
        self._waiting_for_input.clear()
        self._pending_updaters.clear()
        self._input_events.clear()


def create_foundry_agent_executor(card: AgentCard) -> FoundryAgentExecutor:
    return FoundryAgentExecutor(card)


async def initialize_foundry_agents_at_startup():
    await FoundryAgentExecutor.initialize_at_startup()
