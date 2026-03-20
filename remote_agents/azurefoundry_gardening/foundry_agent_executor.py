"""
AI Foundry Agent Executor for A2A framework - Gardening Agent.
Handles artifact return (garden images) following the same pattern as the Image Generator agent.
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

from foundry_agent import FoundryGardeningAgent

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    AgentCard, DataPart, FilePart, FileWithBytes, FileWithUri,
    Message, Part, TaskState, TextPart,
)
from a2a.utils.message import new_agent_text_message, new_agent_parts_message

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class FoundryAgentExecutor(AgentExecutor):
    _shared_foundry_agent: Optional[FoundryGardeningAgent] = None
    _agent_lock = asyncio.Lock()
    _last_request_time: float = 0
    _min_request_interval: float = 1.0
    _request_semaphore = asyncio.Semaphore(3)
    _api_call_count: int = 0
    _api_call_window_start: float = 0
    _max_api_calls_per_minute: int = 30
    _startup_complete: bool = False

    @classmethod
    async def get_shared_agent(cls) -> Optional[FoundryGardeningAgent]:
        async with cls._agent_lock:
            return cls._shared_foundry_agent

    @classmethod
    async def initialize_at_startup(cls) -> None:
        async with cls._agent_lock:
            if not cls._shared_foundry_agent:
                logger.info("Initializing Foundry Gardening agent at startup...")
                try:
                    cls._shared_foundry_agent = FoundryGardeningAgent()
                    await cls._shared_foundry_agent.create_agent()
                    cls._startup_complete = True
                    logger.info("Foundry Gardening agent startup initialization completed successfully")
                except Exception as e:
                    logger.error(f"Failed to initialize gardening agent at startup: {e}")
                    cls._shared_foundry_agent = None
                    cls._startup_complete = False
                    raise

    def __init__(self, card: AgentCard):
        self._active_sessions: Dict[str, str] = {}
        self._waiting_for_input: Dict[str, str] = {}
        self._pending_updaters: Dict[str, TaskUpdater] = {}
        self._input_events: Dict[str, asyncio.Event] = {}

    async def _get_or_create_agent(self) -> FoundryGardeningAgent:
        async with FoundryAgentExecutor._agent_lock:
            if not FoundryAgentExecutor._shared_foundry_agent:
                if FoundryAgentExecutor._startup_complete:
                    raise RuntimeError("Gardening agent startup initialization failed")
                FoundryAgentExecutor._shared_foundry_agent = FoundryGardeningAgent()
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

            async for event in agent.run_conversation_stream(session_id, user_message, context_id=context_id):
                if any(event.startswith(p) for p in ("Fetching", "Uploading", "Analyzing", "Scanning", "Could not")):
                    # Status updates during image processing
                    if event not in seen_tools:
                        seen_tools.add(event)
                        await task_updater.update_status(
                            TaskState.working,
                            message=new_agent_text_message(event, context_id=context_id)
                        )
                elif event.startswith("Error:") or event.startswith("\u274c"):
                    await task_updater.failed(message=new_agent_text_message(event, context_id=context_id))
                    return
                else:
                    responses.append(event)

            # Check for artifacts (garden images)
            artifacts = agent.pop_latest_artifacts()
            artifact_parts = []
            if artifacts:
                logger.info(f"Found {len(artifacts)} garden image artifacts to return")
                for artifact in artifacts:
                    if isinstance(artifact, dict) and artifact.get("artifact-uri"):
                        file_with_uri = FileWithUri(
                            name=artifact.get("file-name", "garden_image.jpg"),
                            uri=artifact["artifact-uri"],
                            mimeType=artifact.get("mime", "image/jpeg")
                        )
                        artifact_parts.append(Part(root=FilePart(file=file_with_uri)))
                        logger.info(f"  FilePart: {artifact.get('file-name')} -> {artifact['artifact-uri'][:80]}...")
                    else:
                        artifact_parts.append(Part(root=DataPart(data=artifact)))

                # Send artifact message immediately
                artifact_message = new_agent_parts_message(parts=artifact_parts, context_id=context_id)
                await task_updater.update_status(TaskState.working, message=artifact_message)

            if responses:
                final_response = responses[-1]

                # Build final parts: text + artifacts
                final_parts = [Part(root=TextPart(text=final_response))]
                if artifact_parts:
                    final_parts.extend(artifact_parts)

                # Add token usage
                if hasattr(agent, 'last_token_usage') and agent.last_token_usage:
                    final_parts.append(Part(root=DataPart(data={'type': 'token_usage', **agent.last_token_usage})))

                await task_updater.complete(
                    message=new_agent_parts_message(parts=final_parts, context_id=context_id)
                )
            else:
                if artifact_parts:
                    final_parts = [Part(root=TextPart(text="Here's the latest view of your garden."))]
                    final_parts.extend(artifact_parts)
                    if hasattr(agent, 'last_token_usage') and agent.last_token_usage:
                        final_parts.append(Part(root=DataPart(data={'type': 'token_usage', **agent.last_token_usage})))
                    await task_updater.complete(
                        message=new_agent_parts_message(parts=final_parts, context_id=context_id)
                    )
                else:
                    await task_updater.complete(
                        message=Message(role="agent", messageId=str(uuid.uuid4()),
                                        parts=[TextPart(text="No response generated")], contextId=context_id)
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
