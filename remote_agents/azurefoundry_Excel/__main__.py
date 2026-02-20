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
    return 9037

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
DEFAULT_UI_PORT = 9102
HOST_AGENT_URL = _normalize_env_value(get_host_agent_url())

agent_executor_instance = None
ui_session_id: Optional[str] = None


def _build_skills():
    """Define agent skills in one place."""
    return [
        AgentSkill(
            id='create_spreadsheet',
            name='Create Spreadsheet',
            description="Create and read Excel spreadsheets. Supports creating workbooks with data, formulas, tables, and formatting. Can also read and extract data from existing .xlsx files via URL or file path.",
            tags=['excel', 'spreadsheet', 'xlsx', 'data'],
            examples=[
                'Create a monthly budget spreadsheet with income and expenses',
                'Build a sales report with quarterly data and charts',
                'Make an inventory tracking sheet with formulas',
                'Design a project timeline spreadsheet',
            ],
        ),
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
        name='AI Foundry Excel Agent',
        description="An Azure AI Foundry agent that creates and reads Excel spreadsheets. Can create new .xlsx files and read/extract data from existing spreadsheets via URL.",
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
        return PlainTextResponse('AI Foundry Excel Agent is running!')

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

    with gr.Blocks(theme=gr.themes.Ocean(), title="AI Foundry Excel Agent") as demo:
        gr.Markdown(f"**UI:** http://{ui_host}:{ui_port} | **A2A:** {resolve_agent_url(ui_host, a2a_port).rstrip('/')}")
        status = gr.Markdown(value=get_pending_status())
        gr.Button("Refresh", size="sm").click(get_pending_status, outputs=status, queue=False)
        gr.Timer(5).tick(get_pending_status, outputs=status)
        chatbot = gr.Chatbot(height=400, show_label=False, type="messages")
        inp = gr.Textbox(placeholder="Describe the spreadsheet you want...", show_label=False)
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
    """AI Foundry Excel Agent - A2A server or Gradio UI."""
    if ui:
        asyncio.run(launch_ui(host, ui_port, port))
    else:
        asyncio.run(main_async(host, port))


if __name__ == '__main__':
    cli()
