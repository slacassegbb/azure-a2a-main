# Code Patterns

Complete file templates. Replace `{{PLACEHOLDER}}` markers with actual values.

## Placeholder Reference

| Placeholder | Derived From | Example |
|---|---|---|
| `{{DOMAIN}}` | User input | Jira |
| `{{DOMAIN_LOWER}}` | lowercase(domain) | jira |
| `{{DOMAIN_UPPER}}` | UPPERCASE(domain) | JIRA |
| `{{AGENT_CLASS}}` | Foundry{Domain}Agent | FoundryJiraAgent |
| `{{AGENT_DISPLAY_NAME}}` | AI Foundry {Domain} Agent | AI Foundry Jira Agent |
| `{{AGENT_DESCRIPTION}}` | User input | An intelligent Jira agent... |
| `{{A2A_PORT}}` | From port-allocation.md | 8025 |
| `{{SKILLS_LIST}}` | Generated AgentSkill objects | See Skills Pattern below |
| `{{AGENT_INSTRUCTIONS}}` | User input | You are a Jira assistant... |
| `{{MCP_URL_ENV_VAR}}` | {DOMAIN_UPPER}_MCP_URL | JIRA_MCP_URL |
| `{{MCP_SERVER_LABEL}}` | Domain name | Jira |
| `{{MCP_DEFAULT_URL}}` | User input | https://mcp-jira.example.com/sse |
| `{{MCP_ALLOWED_TOOLS}}` | User input | ["jira_search", "jira_create"] |

---

## foundry_agent.py (with MCP)

```python
"""
AI Foundry Agent with {{DOMAIN}} capabilities.
Uses the Responses API with native MCP tool support.
"""
import os
import time
import datetime
import asyncio
import logging
from typing import Optional, Dict

import httpx
from openai import AsyncAzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

logger = logging.getLogger(__name__)

{{MCP_URL_ENV_VAR}}_URL = os.getenv("{{MCP_URL_ENV_VAR}}", "{{MCP_DEFAULT_URL}}")

{{DOMAIN_UPPER}}_ALLOWED_TOOLS = [
    {{MCP_ALLOWED_TOOLS}}
]


class {{AGENT_CLASS}}:
    """AI Foundry Agent with {{DOMAIN}} capabilities via Responses API."""

    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self._client: Optional[AsyncAzureOpenAI] = None
        self._initialized = False
        self._response_ids: Dict[str, str] = {}
        self.last_token_usage: Optional[Dict[str, int]] = None
        self._mcp_tool_config = {
            "type": "mcp",
            "server_label": "{{MCP_SERVER_LABEL}}",
            "server_url": {{MCP_URL_ENV_VAR}}_URL,
            "require_approval": "never",
            "allowed_tools": {{DOMAIN_UPPER}}_ALLOWED_TOOLS,
            "headers": {
                "Content-Type": "application/json",
                "User-Agent": "Azure-AI-Foundry-Agent",
                "Accept": "application/json, text/event-stream",
            },
        }

    def _get_client(self) -> AsyncAzureOpenAI:
        if self._client is None:
            if "services.ai.azure.com" in self.endpoint:
                resource_name = self.endpoint.split("//")[1].split(".")[0]
                openai_endpoint = f"https://{resource_name}.openai.azure.com/openai/v1/"
            else:
                openai_endpoint = (
                    self.endpoint
                    if self.endpoint.endswith("/openai/v1/")
                    else f"{self.endpoint.rstrip('/')}/openai/v1/"
                )
            token_provider = get_bearer_token_provider(
                self.credential, "https://cognitiveservices.azure.com/.default",
            )
            self._client = AsyncAzureOpenAI(
                base_url=openai_endpoint,
                azure_ad_token_provider=token_provider,
                api_version="preview",
            )
        return self._client

    async def create_agent(self) -> None:
        if self._initialized:
            return
        logger.info("Initializing {{DOMAIN}} agent (Responses API)...")
        try:
            base_url = {{MCP_URL_ENV_VAR}}_URL.rstrip("/sse")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(base_url)
                logger.info(f"MCP Server status: {response.status_code}")
        except Exception as e:
            logger.warning(f"MCP Server test failed: {e} (continuing anyway)")
        self._get_client()
        self._initialized = True

    def _get_agent_instructions(self) -> str:
        return f"""{{AGENT_INSTRUCTIONS}}

Current date: {datetime.datetime.now().isoformat()}

## NEEDS_INPUT - Human-in-the-Loop

Use NEEDS_INPUT to pause and ask the user a question:

```NEEDS_INPUT
Your question here
```END_NEEDS_INPUT
"""

    async def create_session(self) -> str:
        return f"session_{int(time.time())}_{os.urandom(4).hex()}"

    async def run_conversation_stream(self, session_id: str, user_message: str):
        if not self._initialized:
            await self.create_agent()

        client = self._get_client()
        model = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")

        kwargs = {
            "model": model,
            "instructions": self._get_agent_instructions(),
            "input": [{"role": "user", "content": user_message}],
            "tools": [self._mcp_tool_config],
            "stream": True,
            "max_output_tokens": 4000,
        }
        if session_id in self._response_ids:
            kwargs["previous_response_id"] = self._response_ids[session_id]

        retry_count = 0
        max_retries = 3
        while retry_count <= max_retries:
            try:
                stream_start = time.time()
                response = await client.responses.create(**kwargs)
                text_chunks = []
                tool_calls_seen = set()
                mcp_failures = []
                tool_call_times = {}

                async for event in response:
                    event_type = getattr(event, 'type', None)

                    if event_type == "response.output_text.delta":
                        text_chunks.append(event.delta)
                    elif event_type == "response.mcp_call.in_progress":
                        tool_name = getattr(event, 'name', 'mcp_tool')
                        if tool_name not in tool_calls_seen:
                            tool_calls_seen.add(tool_name)
                            tool_call_times[tool_name] = time.time()
                            yield f"\U0001f6e0\ufe0f Remote agent executing: {self._get_tool_description(tool_name)}"
                    elif event_type == "response.mcp_call.completed":
                        pass
                    elif event_type == "response.mcp_call.failed":
                        tool_name = getattr(event, 'name', None) or getattr(event, 'item_id', 'mcp_tool')
                        mcp_failures.append(tool_name)
                    elif event_type == "response.failed":
                        resp = getattr(event, 'response', None)
                        error_obj = getattr(resp, 'error', None) if resp else None
                        yield f"Error: {getattr(error_obj, 'message', 'Unknown error') if error_obj else 'Unknown error'}"
                        return
                    elif event_type == "response.output_item.added":
                        item = getattr(event, 'item', None)
                        if item and getattr(item, 'type', None) in ("mcp_call", "mcp_tool_call"):
                            tool_name = getattr(item, 'name', None) or getattr(item, 'tool_name', 'mcp_tool')
                            if tool_name not in tool_calls_seen:
                                tool_calls_seen.add(tool_name)
                                tool_call_times[tool_name] = time.time()
                                yield f"\U0001f6e0\ufe0f Remote agent executing: {self._get_tool_description(tool_name)}"
                    elif event_type in ("response.completed", "response.done"):
                        resp = getattr(event, 'response', None)
                        if resp:
                            usage = getattr(resp, 'usage', None)
                            if usage:
                                self.last_token_usage = {
                                    "prompt_tokens": getattr(usage, 'prompt_tokens', 0) or getattr(usage, 'input_tokens', 0),
                                    "completion_tokens": getattr(usage, 'completion_tokens', 0) or getattr(usage, 'output_tokens', 0),
                                    "total_tokens": getattr(usage, 'total_tokens', 0),
                                }
                            resp_id = getattr(resp, 'id', None)
                            if resp_id:
                                self._response_ids[session_id] = resp_id

                if text_chunks:
                    full_text = "".join(text_chunks)
                    if mcp_failures:
                        yield f"Error: MCP tool(s) failed ({', '.join(mcp_failures)}). {full_text}"
                    else:
                        yield full_text
                else:
                    yield "Error: Agent completed but no response text was generated"
                return

            except Exception as e:
                error_str = str(e).lower()
                if "rate_limit" in error_str or "429" in error_str or "too many requests" in error_str:
                    retry_count += 1
                    if retry_count <= max_retries:
                        backoff = min(15 * (2 ** retry_count), 60)
                        yield f"Rate limit hit - retrying in {backoff}s..."
                        await asyncio.sleep(backoff)
                        continue
                    yield f"Rate limit exceeded after {max_retries} retries"
                else:
                    yield f"Error: {e}"
                return

    def _get_tool_description(self, tool_name: str) -> str:
        """Override with domain-specific tool descriptions."""
        return tool_name.replace("_", " ").title() if tool_name else "mcp_tool"

    async def run_conversation(self, session_id: str, user_message: str) -> str:
        return "\n".join([r async for r in self.run_conversation_stream(session_id, user_message)])

    async def chat(self, session_id: str, user_message: str) -> str:
        return await self.run_conversation(session_id, user_message)
```

### foundry_agent.py without MCP

Same structure but remove:
- MCP URL constant and ALLOWED_TOOLS list
- `_mcp_tool_config` from `__init__`
- `"tools"` key from kwargs (or set `"tools": []`)
- MCP event handling (`response.mcp_call.*`, output_item MCP checks)
- `_get_tool_description` method
- MCP connectivity test in `create_agent()`

---

## foundry_agent_executor.py

This file is nearly identical across all agents. Only the import and class name change.

```python
"""
AI Foundry Agent Executor for A2A framework - {{DOMAIN}} Agent.
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

from foundry_agent import {{AGENT_CLASS}}

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
    _shared_foundry_agent: Optional[{{AGENT_CLASS}}] = None
    _agent_lock = asyncio.Lock()
    _last_request_time: float = 0
    _min_request_interval: float = 1.0
    _request_semaphore = asyncio.Semaphore(3)
    _api_call_count: int = 0
    _api_call_window_start: float = 0
    _max_api_calls_per_minute: int = 30
    _startup_complete: bool = False

    @classmethod
    async def get_shared_agent(cls) -> Optional[{{AGENT_CLASS}}]:
        async with cls._agent_lock:
            return cls._shared_foundry_agent

    @classmethod
    async def initialize_at_startup(cls) -> None:
        async with cls._agent_lock:
            if not cls._shared_foundry_agent:
                try:
                    cls._shared_foundry_agent = {{AGENT_CLASS}}()
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

    async def _get_or_create_agent(self) -> {{AGENT_CLASS}}:
        async with FoundryAgentExecutor._agent_lock:
            if not FoundryAgentExecutor._shared_foundry_agent:
                if FoundryAgentExecutor._startup_complete:
                    raise RuntimeError("Agent startup initialization failed")
                FoundryAgentExecutor._shared_foundry_agent = {{AGENT_CLASS}}()
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
                # Check for NEEDS_INPUT in final response
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

                parts_out = [TextPart(text=final_response)]
                if hasattr(agent, 'last_token_usage') and agent.last_token_usage:
                    parts_out.append(DataPart(data={'type': 'token_usage', **agent.last_token_usage}))
                await task_updater.complete(
                    message=Message(role="agent", messageId=str(uuid.uuid4()), parts=parts_out, contextId=context_id)
                )
            else:
                await task_updater.complete(
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
```

---

## __main__.py

```python
import asyncio
import logging
import os
import threading
from typing import List, Optional

import click
import gradio as gr
import uvicorn

from foundry_agent_executor import (
    create_foundry_agent_executor, initialize_foundry_agents_at_startup, FoundryAgentExecutor,
)
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)
logging.getLogger("azure").setLevel(logging.WARNING)


def _normalize_env_value(raw: str | None) -> str:
    return raw.strip() if raw else ''

def _resolve_default_host() -> str:
    return _normalize_env_value(os.getenv('A2A_ENDPOINT')) or 'localhost'

def _resolve_default_port() -> int:
    raw = _normalize_env_value(os.getenv('A2A_PORT'))
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return 8000

def resolve_agent_url(bind_host: str, bind_port: int) -> str:
    endpoint = _normalize_env_value(os.getenv('A2A_ENDPOINT'))
    if endpoint:
        if endpoint.startswith(('http://', 'https://')):
            return endpoint.rstrip('/') + '/'
        host_for_url = endpoint
    else:
        host_for_url = bind_host if bind_host != "0.0.0.0" else _resolve_default_host()
    return f"http://{host_for_url}:{bind_port}/"

try:
    from utils.self_registration import register_with_host_agent, get_host_agent_url
    SELF_REGISTRATION_AVAILABLE = True
except ImportError:
    async def register_with_host_agent(agent_card, _host_url=None):
        return False
    def get_host_agent_url() -> str:
        return ""
    SELF_REGISTRATION_AVAILABLE = False

DEFAULT_HOST = _resolve_default_host()
DEFAULT_PORT = _resolve_default_port()
DEFAULT_UI_PORT = 8085
HOST_AGENT_URL = _normalize_env_value(get_host_agent_url())

agent_executor_instance = None
ui_session_id: Optional[str] = None


def _build_skills():
    """Define agent skills in one place."""
    return [
        {{SKILLS_LIST}}
        AgentSkill(
            id='human_interaction',
            name='Human Expert Escalation',
            description="Escalate complex issues to human experts when needed.",
            tags=['human-interaction', 'escalation', 'expert', 'human-capable'],
            examples=['I need to speak with a person', 'Connect me with a human agent'],
        ),
    ]


def _build_agent_card(host: str, port: int):
    resolved = host if host != "0.0.0.0" else DEFAULT_HOST
    return AgentCard(
        name='{{AGENT_DISPLAY_NAME}}',
        description="{{AGENT_DESCRIPTION}}",
        url=resolve_agent_url(resolved, port),
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities=AgentCapabilities(streaming=True),
        skills=_build_skills(),
    )


def create_a2a_server(host=DEFAULT_HOST, port=DEFAULT_PORT):
    global agent_executor_instance
    agent_card = _build_agent_card(host, port)
    agent_executor_instance = create_foundry_agent_executor(agent_card)
    request_handler = DefaultRequestHandler(agent_executor=agent_executor_instance, task_store=InMemoryTaskStore())
    a2a_app = A2AStarletteApplication(agent_card=agent_card, http_handler=request_handler)
    routes = a2a_app.routes()

    async def health_check(_request: Request) -> PlainTextResponse:
        return PlainTextResponse('{{AGENT_DISPLAY_NAME}} is running!')

    routes.append(Route(path='/health', methods=['GET'], endpoint=health_check))
    return Starlette(routes=routes)


async def register_agent_with_host(agent_card):
    if SELF_REGISTRATION_AVAILABLE and HOST_AGENT_URL:
        await asyncio.sleep(2)
        try:
            await register_with_host_agent(agent_card, host_url=HOST_AGENT_URL)
        except Exception as e:
            logger.warning(f"Registration failed: {e}")


def start_background_registration(agent_card):
    if SELF_REGISTRATION_AVAILABLE:
        threading.Thread(target=lambda: asyncio.run(register_agent_with_host(agent_card)), daemon=True).start()


async def launch_ui(host="0.0.0.0", ui_port=DEFAULT_UI_PORT, a2a_port=DEFAULT_PORT):
    required = ['AZURE_AI_FOUNDRY_PROJECT_ENDPOINT', 'AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME']
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        raise ValueError(f"Missing: {', '.join(missing)}")

    await initialize_foundry_agents_at_startup()

    threading.Thread(
        target=lambda: uvicorn.run(create_a2a_server(host if host != "0.0.0.0" else DEFAULT_HOST, a2a_port),
                                   host=host if host != "0.0.0.0" else DEFAULT_HOST, port=a2a_port, log_level="info"),
        daemon=True,
    ).start()
    await asyncio.sleep(2)

    agent_card = _build_agent_card(host, a2a_port)
    start_background_registration(agent_card)

    ui_host = host if host != "0.0.0.0" else DEFAULT_HOST

    def get_pending_status():
        global agent_executor_instance
        if agent_executor_instance and agent_executor_instance._waiting_for_input:
            cid, text = next(iter(agent_executor_instance._waiting_for_input.items()))
            return f"**Pending Request**\n\nContext: `{cid}`\n\n{str(text)[:500]}"
        return "No pending requests."

    async def chat_response(message, history):
        history = history or []
        text = message.strip()
        if not text:
            return history

        global agent_executor_instance
        if agent_executor_instance and agent_executor_instance._waiting_for_input:
            cid, _ = next(iter(agent_executor_instance._waiting_for_input.items()))
            history.append({"role": "user", "content": text})
            try:
                ok = await agent_executor_instance.send_human_response(cid, text)
                history.append({"role": "assistant", "content": "Response sent." if ok else "Could not send response."})
            except Exception as e:
                history.append({"role": "assistant", "content": f"Error: {e}"})
            return history

        foundry_agent = await FoundryAgentExecutor.get_shared_agent()
        if not foundry_agent:
            history.append({"role": "assistant", "content": "Agent not initialized."})
            return history

        global ui_session_id
        if not ui_session_id:
            ui_session_id = await foundry_agent.create_session()

        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": "Processing..."})
        responses = []
        try:
            async for r in foundry_agent.run_conversation_stream(ui_session_id, text):
                if isinstance(r, str) and r.strip() and "processing" not in r.lower():
                    responses.append(r.strip())
        except Exception as e:
            responses.append(f"Error: {e}")
        history.pop()
        for r in (responses or ["No response received."]):
            history.append({"role": "assistant", "content": r})
        return history

    async def process_message(message, history):
        return "", await chat_response(message, history), get_pending_status()

    with gr.Blocks(theme=gr.themes.Ocean(), title="{{AGENT_DISPLAY_NAME}}") as demo:
        gr.Markdown(f"**UI:** http://{ui_host}:{ui_port} | **A2A:** {resolve_agent_url(ui_host, a2a_port).rstrip('/')}")
        status = gr.Markdown(value=get_pending_status())
        gr.Button("Refresh", size="sm").click(get_pending_status, outputs=status, queue=False)
        gr.Timer(5).tick(get_pending_status, outputs=status)
        chatbot = gr.Chatbot(height=400, show_label=False, type="messages")
        inp = gr.Textbox(placeholder="Ask a question...", show_label=False)
        gr.Button("Send", variant="primary").click(process_message, [inp, chatbot], [inp, chatbot, status])
        inp.submit(process_message, [inp, chatbot], [inp, chatbot, status])
        gr.Button("Reset", variant="secondary").click(lambda: (globals().update(ui_session_id=None), [])[1], outputs=chatbot, queue=False)

    demo.queue().launch(server_name=host, server_port=ui_port)


async def main_async(host=DEFAULT_HOST, port=DEFAULT_PORT):
    required = ['AZURE_AI_FOUNDRY_PROJECT_ENDPOINT', 'AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME']
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        raise ValueError(f"Missing: {', '.join(missing)}")

    await initialize_foundry_agents_at_startup()
    app = create_a2a_server(host, port)
    start_background_registration(_build_agent_card(host, port))

    config = uvicorn.Config(app, host=host, port=port)
    await uvicorn.Server(config).serve()


@click.command()
@click.option('--host', default=DEFAULT_HOST)
@click.option('--port', default=DEFAULT_PORT, type=int)
@click.option('--ui', is_flag=True, help='Launch Gradio UI')
@click.option('--ui-port', default=DEFAULT_UI_PORT, type=int)
def cli(host, port, ui, ui_port):
    """{{AGENT_DISPLAY_NAME}} - A2A server or Gradio UI."""
    if ui:
        asyncio.run(launch_ui(host, ui_port, port))
    else:
        asyncio.run(main_async(host, port))


if __name__ == '__main__':
    cli()
```

**Key improvement**: Skills and agent card are defined once via `_build_skills()` and `_build_agent_card()` — no triple duplication.

---

## pyproject.toml

```toml
[project]
name = "aifoundry-{{DOMAIN_LOWER}}-agent"
version = "0.1.0"
description = "{{AGENT_DESCRIPTION}}"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "a2a-sdk[http-server]>=0.2.6",
    "openai>=1.0.0",
    "azure-identity>=1.23.0",
    "uvicorn>=0.34.2",
    "click>=8.0.0",
    "python-dotenv>=1.0.0",
    "starlette>=0.35.0",
    "httpx>=0.25.0",
    "gradio>=4.0.0",
    "pandas>=2.0.0",
]
```

---

## Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl ca-certificates apt-transport-https lsb-release gnupg \
    && curl -sL https://aka.ms/InstallAzureCLIDeb | bash \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock* ./
RUN uv pip install --system -e .
COPY . .

ENV A2A_PORT={{A2A_PORT}}
ENV A2A_HOST=0.0.0.0
EXPOSE ${A2A_PORT}

CMD ["sh", "-c", "uv run . --host ${A2A_HOST} --port ${A2A_PORT}"]
```

---

## .env.example

```bash
# Azure AI Foundry Configuration
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=""
AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME="gpt-4o"

# Network
A2A_ENDPOINT=localhost
A2A_PORT={{A2A_PORT}}

# Host agent registration
A2A_HOST=http://localhost:12000

# Logging
LOG_LEVEL=INFO

# MCP (include only if MCP enabled)
# {{MCP_URL_ENV_VAR}}=""
```

---

## Skills Pattern

```python
AgentSkill(
    id='{{DOMAIN_LOWER}}_{{feature_id}}',
    name='{{Domain}} {{Feature Name}}',
    description="What this capability does.",
    tags=['{{DOMAIN_LOWER}}', '{{tag1}}', '{{tag2}}'],
    examples=['Example query 1', 'Example query 2'],
),
```
