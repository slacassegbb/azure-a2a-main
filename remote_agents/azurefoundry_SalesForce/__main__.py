import asyncio
import logging
import os
import traceback
import threading
import json
import datetime
import re
from typing import Dict, List, Optional

import click
import gradio as gr
import uvicorn

from foundry_agent_executor import create_foundry_agent_executor, initialize_foundry_agents_at_startup, FoundryAgentExecutor
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentSkill

load_dotenv()

# Configure logging - hide verbose Azure SDK logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Silence verbose Azure SDK HTTP logging
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)
logging.getLogger("azure").setLevel(logging.WARNING)


def _normalize_env_value(raw_value: str | None) -> str:
    if raw_value is None:
        return ''
    return raw_value.strip()


def _resolve_default_host() -> str:
    value = _normalize_env_value(os.getenv('A2A_ENDPOINT'))
    return value or 'localhost'


def _resolve_default_port() -> int:
    raw_port = _normalize_env_value(os.getenv('A2A_PORT'))
    if raw_port:
        try:
            return int(raw_port)
        except ValueError:
            logger.warning("Invalid A2A_PORT value '%s'; defaulting to 8000", raw_port)
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

# Import self-registration utility
try:
    from utils.self_registration import register_with_host_agent, get_host_agent_url
    SELF_REGISTRATION_AVAILABLE = True
    logger.info("✅ Self-registration utility loaded")
except ImportError:
    # Fallback if utils not available
    async def register_with_host_agent(agent_card, _host_url=None):
        logger.info("ℹ️ Self-registration utility not available - skipping registration")
        return False
    def get_host_agent_url() -> str:
        return ""
    SELF_REGISTRATION_AVAILABLE = False

DEFAULT_HOST = _resolve_default_host()
DEFAULT_PORT = _resolve_default_port()
DEFAULT_UI_PORT = 8085

# Global reference to the agent executor to check for pending tasks
agent_executor_instance = None

# Persist a single Azure Foundry thread per UI session
ui_thread_id: Optional[str] = None

HOST_AGENT_URL = _normalize_env_value(get_host_agent_url())


def create_a2a_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Create A2A server application for Azure Foundry agent."""
    global agent_executor_instance
    
    # Define agent skills
    skills = [
        AgentSkill(
            id='salesforce_data_query',
            name='Salesforce Data Query & Search',
            description="Query and search Salesforce data using SOQL and SOSL. Execute aggregate queries (COUNT, SUM, AVG), search across multiple objects, and retrieve detailed records.",
            tags=['salesforce', 'soql', 'sosl', 'query', 'search', 'data'],
            examples=[
                'Show me all accounts in the technology industry',
                'How many opportunities are in the pipeline?',
                'What is the average deal size this quarter?',
                'Find all contacts at companies starting with Tech',
                'List all open cases assigned to John'
            ],
        ),
        AgentSkill(
            id='salesforce_data_management',
            name='Salesforce Data Management',
            description="Create, update, and delete Salesforce records including Accounts, Contacts, Leads, Opportunities, and Cases using DML operations.",
            tags=['salesforce', 'crm', 'create', 'update', 'delete', 'dml'],
            examples=[
                'Create a new contact named John Smith at Acme Corp',
                'Update the opportunity status to Closed Won',
                'Create a new account for TechCorp Inc',
                'Delete the duplicate lead record'
            ],
        ),
        AgentSkill(
            id='salesforce_metadata',
            name='Salesforce Metadata Management',
            description="Describe Salesforce objects, create custom objects and fields, manage field-level security permissions, and explore org metadata.",
            tags=['salesforce', 'metadata', 'fields', 'objects', 'permissions', 'schema'],
            examples=[
                'What fields does the Account object have?',
                'Create a new custom field on the Lead object',
                'Show me the picklist values for the Status field',
                'What objects are available containing Order?'
            ],
        ),
        AgentSkill(
            id='salesforce_development',
            name='Salesforce Apex Development',
            description="Read and write Apex classes and triggers, execute anonymous Apex code for testing, and manage debug logs for troubleshooting.",
            tags=['salesforce', 'apex', 'code', 'triggers', 'development', 'debugging'],
            examples=[
                'Show me the code for the AccountTrigger',
                'Read the AccountService Apex class',
                'Run this Apex code to test the logic',
                'Enable debug logs for user admin@example.com'
            ],
        ),
        AgentSkill(
            id='web_search',
            name='Web Search',
            description="Search the web for current information using Bing or other integrated search tools.",
            tags=['web', 'search', 'bing', 'internet'],
            examples=[
                'Find the latest news about a company',
                'Search for Salesforce best practices',
                'Get current market information'
            ],
        ),
        AgentSkill(
            id='human_interaction',
            name='Human Expert Escalation',
            description="Escalate complex issues to human experts or facilitate human-in-the-loop interactions when automated responses are insufficient.",
            tags=['human-interaction', 'escalation', 'expert', 'human-capable'],
            examples=[
                'Escalate this issue to a human expert',
                'I need to speak with a person',
                'Connect me with a human agent'
            ],
        )
    ]

    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST

    # Create agent card
    agent_card = AgentCard(
        name='Salesforce CRM Agent',
        description="An intelligent agent specialized in Salesforce CRM management. Can create, search, and manage Salesforce records including Accounts, Contacts, Leads, Opportunities, and Cases. Also supports web search and document search capabilities.",
        url=resolve_agent_url(resolved_host_for_url, port),
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities={"streaming": True},
        skills=skills,
    )

    # Create agent executor
    agent_executor_instance = create_foundry_agent_executor(agent_card)

    # Create request handler
    request_handler = DefaultRequestHandler(
        agent_executor=agent_executor_instance, 
        task_store=InMemoryTaskStore()
    )

    # Create A2A application
    a2a_app = A2AStarletteApplication(
        agent_card=agent_card, 
        http_handler=request_handler
    )
    
    # Get routes
    routes = a2a_app.routes()
    
    # Add health check endpoint
    async def health_check(_request: Request) -> PlainTextResponse:
        return PlainTextResponse('AI Foundry Expert Agent is running!')
    
    routes.append(
        Route(
            path='/health',
            methods=['GET'],
            endpoint=health_check
        )
    )

    # Create Starlette app
    app = Starlette(routes=routes)
    
    return app


def run_a2a_server_in_thread(host: str, port: int):
    """Run A2A server in a separate thread."""
    print(f"Starting AI Foundry Expert Agent A2A server on {host}:{port}...")
    app = create_a2a_server(host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


async def register_agent_with_host(agent_card):
    """Register this agent with the host agent after startup."""
    if SELF_REGISTRATION_AVAILABLE:
        # Wait a moment for server to fully start
        await asyncio.sleep(2)
        try:
            if not HOST_AGENT_URL:
                logger.info("ℹ️ Host agent URL not configured; skipping registration attempt.")
                return

            logger.info(f"🤝 Attempting to register '{agent_card.name}' with host agent at {HOST_AGENT_URL}...")
            registration_success = await register_with_host_agent(agent_card, host_url=HOST_AGENT_URL)
            if registration_success:
                logger.info(f"🎉 '{agent_card.name}' successfully registered with host agent!")
            else:
                logger.info(f"📡 '{agent_card.name}' registration failed - host agent may be unavailable")
        except Exception as e:
            logger.warning(f"⚠️ Registration attempt failed: {e}")


def start_background_registration(agent_card):
    """Start background registration task."""
    if SELF_REGISTRATION_AVAILABLE:
        def run_registration():
            asyncio.run(register_agent_with_host(agent_card))
        
        registration_thread = threading.Thread(target=run_registration, daemon=True)
        registration_thread.start()
        logger.info(f"🚀 '{agent_card.name}' starting with background registration enabled")
    else:
        logger.info(f"📡 '{agent_card.name}' starting without self-registration")


async def launch_ui(host: str = "0.0.0.0", ui_port: int = DEFAULT_UI_PORT, a2a_port: int = DEFAULT_PORT):
    """Launch a streamlined Gradio UI alongside the A2A server."""
    print("Starting Salesforce CRM Agent UI and A2A server...")

    required_env_vars = [
        'AZURE_AI_FOUNDRY_PROJECT_ENDPOINT',
        'AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME'
    ]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing_vars)}"
        )

    print("🚀 Initializing AI Foundry agents at startup...")
    try:
        await initialize_foundry_agents_at_startup()
        print("✅ Agent initialization completed successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize agents at startup: {e}")
        raise

    a2a_thread = threading.Thread(
        target=run_a2a_server_in_thread,
        args=(host if host != "0.0.0.0" else DEFAULT_HOST, a2a_port),
        daemon=True,
    )
    a2a_thread.start()
    await asyncio.sleep(2)

    skills = [
        AgentSkill(
            id='salesforce_data_query',
            name='Salesforce Data Query & Search',
            description="Query and search Salesforce data using SOQL and SOSL. Execute aggregate queries (COUNT, SUM, AVG), search across multiple objects, and retrieve detailed records.",
            tags=['salesforce', 'soql', 'sosl', 'query', 'search', 'data'],
            examples=[
                'Show me all accounts in the technology industry',
                'How many opportunities are in the pipeline?',
                'What is the average deal size this quarter?'
            ],
        ),
        AgentSkill(
            id='salesforce_data_management',
            name='Salesforce Data Management',
            description="Create, update, and delete Salesforce records including Accounts, Contacts, Leads, Opportunities, and Cases using DML operations.",
            tags=['salesforce', 'crm', 'create', 'update', 'delete', 'dml'],
            examples=[
                'Create a new contact named John Smith at Acme Corp',
                'Update the opportunity status to Closed Won',
                'Create a new account for TechCorp Inc'
            ],
        ),
        AgentSkill(
            id='salesforce_metadata',
            name='Salesforce Metadata Management',
            description="Describe Salesforce objects, create custom objects and fields, manage field-level security permissions.",
            tags=['salesforce', 'metadata', 'fields', 'objects', 'permissions'],
            examples=[
                'What fields does the Account object have?',
                'Create a new custom field on the Lead object'
            ],
        ),
        AgentSkill(
            id='salesforce_development',
            name='Salesforce Apex Development',
            description="Read and write Apex classes and triggers, execute anonymous Apex code, manage debug logs.",
            tags=['salesforce', 'apex', 'code', 'triggers', 'development'],
            examples=[
                'Show me the code for the AccountTrigger',
                'Enable debug logs for user admin@example.com'
            ],
        ),
        AgentSkill(
            id='human_interaction',
            name='Human Expert Escalation',
            description="Escalate complex issues to human experts when needed.",
            tags=['human-interaction', 'escalation', 'expert', 'human-capable'],
            examples=[
                'I need to speak with a person',
                'Connect me with a human agent'
            ],
        )
    ]

    resolved_host_for_ui_card = host if host != "0.0.0.0" else DEFAULT_HOST
    agent_card = AgentCard(
        name='Salesforce CRM Agent',
        description="An intelligent Salesforce agent with full CRM data access, metadata management, and Apex development capabilities.",
        url=resolve_agent_url(resolved_host_for_ui_card, a2a_port),
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities={"streaming": True},
        skills=skills,
    )
    start_background_registration(agent_card)

    resolved_host_for_ui_url = host if host != "0.0.0.0" else DEFAULT_HOST
    display_host = resolved_host_for_ui_url
    ui_display_url = f"http://{display_host}:{ui_port}"
    a2a_display_url = resolve_agent_url(display_host, a2a_port).rstrip('/')

    def get_pending_status() -> str:
        """Return a human-readable summary of pending host-agent requests."""
        global agent_executor_instance
        if agent_executor_instance and agent_executor_instance._waiting_for_input:
            context_id, request_text = next(iter(agent_executor_instance._waiting_for_input.items()))
            preview = request_text.strip()
            if len(preview) > 500:
                preview = preview[:500] + "..."
            return f"**Pending Host Request**\n\nContext ID: `{context_id}`\n\n{preview}"
        return "No pending host requests."

    async def chat_response(message: str, history: List[dict]) -> List[dict]:
        history = history or []
        text = message.strip()
        if not text:
            return history

        global agent_executor_instance
        if agent_executor_instance and agent_executor_instance._waiting_for_input:
            context_id, _ = next(iter(agent_executor_instance._waiting_for_input.items()))
            history.append({"role": "user", "content": text})
            try:
                success = await agent_executor_instance.send_human_response(context_id, text)
            except Exception as e:
                logger.error(f"Error sending human response: {e}")
                history.append({"role": "assistant", "content": f"❌ Failed to send response: {e}"})
                return history
            if success:
                history.append({"role": "assistant", "content": "✅ Response sent to host agent."})
            else:
                history.append({"role": "assistant", "content": "❌ Could not send response to host agent. The task may have expired."})
            return history

        foundry_agent = await FoundryAgentExecutor.get_shared_agent()
        if not foundry_agent:
            history.append({"role": "assistant", "content": "❌ Agent not initialized. Please restart the application."})
            return history

        global ui_thread_id
        if not ui_thread_id:
            thread = await foundry_agent.create_thread()
            ui_thread_id = thread.id
        else:
            thread = await foundry_agent.create_thread(ui_thread_id)
        thread_id = thread.id

        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": "🤖 **Processing your request...**"})
        responses: List[str] = []
        try:
            async for response in foundry_agent.run_conversation_stream(thread_id, text):
                if isinstance(response, str):
                    stripped = response.strip()
                    if stripped and not any(phrase in stripped.lower() for phrase in [
                        "processing your request", "🤖 processing", "processing..."
                    ]):
                        responses.append(stripped)
                else:
                    responses.append(
                        f"An error occurred while processing your request: {response}. Please check the server logs for details."
                    )
        except Exception as e:
            logger.error(f"Error streaming response: {e}")
            responses.append(f"An error occurred while processing your request: {e}. Please check the server logs for details.")

        history.pop()  # remove processing placeholder
        if responses:
            for resp in responses:
                history.append({"role": "assistant", "content": resp})
        else:
            history.append({"role": "assistant", "content": "I processed your request but didn't receive a response. Please try again."})
        return history

    async def process_message(message: str, history: List[dict]):
        updated_history = await chat_response(message, history)
        return "", updated_history, get_pending_status()

    def reset_conversation():
        global ui_thread_id
        ui_thread_id = None
        return []

    def refresh_status():
        return get_pending_status()

    with gr.Blocks(theme=gr.themes.Ocean(), title="Salesforce CRM Agent Chat") as demo:
        gr.Markdown(f"**Direct UI Access:** {ui_display_url} | **A2A API Access:** {a2a_display_url}")
        status_display = gr.Markdown(value=get_pending_status())
        refresh_btn = gr.Button("🔄 Refresh Status", size="sm")
        refresh_btn.click(refresh_status, outputs=status_display, queue=False)
        timer = gr.Timer(5)
        timer.tick(refresh_status, outputs=status_display)

        chatbot_interface = gr.Chatbot(height=400, show_label=False, type="messages")
        agent_input = gr.Textbox(placeholder="Ask a question or provide expert input...", show_label=False)
        send_btn = gr.Button("Send", variant="primary")
        reset_btn = gr.Button("🗑️ Reset Chat", variant="secondary")

        send_btn.click(process_message, inputs=[agent_input, chatbot_interface], outputs=[agent_input, chatbot_interface, status_display])
        agent_input.submit(process_message, inputs=[agent_input, chatbot_interface], outputs=[agent_input, chatbot_interface, status_display])
        reset_btn.click(reset_conversation, outputs=chatbot_interface, queue=False)

    print(f"Launching Salesforce CRM Agent Gradio interface on {host}:{ui_port}...")
    demo.queue().launch(server_name=host, server_port=ui_port)
    print("Salesforce CRM Agent Gradio application has been shut down.")


async def main_async(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Launch A2A server mode for Azure Foundry agent with startup initialization."""
    # Verify required environment variables
    required_env_vars = [
        'AZURE_AI_FOUNDRY_PROJECT_ENDPOINT',
        'AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME'
    ]
    
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing_vars)}"
        )

    # Initialize agents at startup BEFORE starting server
    print("🚀 Initializing AI Foundry agents at startup...")
    try:
        await initialize_foundry_agents_at_startup()
        print("✅ Agent initialization completed successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize agents at startup: {e}")
        raise

    print(f"Starting AI Foundry Expert Agent A2A server on {host}:{port}...")
    app = create_a2a_server(host, port)
    
    # Create agent card for registration
    skills = [
        AgentSkill(
            id='salesforce_data_query',
            name='Salesforce Data Query & Search',
            description="Query and search Salesforce data using SOQL and SOSL. Execute aggregate queries (COUNT, SUM, AVG), search across multiple objects, and retrieve detailed records.",
            tags=['salesforce', 'soql', 'sosl', 'query', 'search', 'data'],
            examples=[
                'Show me all accounts in the technology industry',
                'How many opportunities are in the pipeline?',
                'What is the average deal size this quarter?',
                'Find all contacts at companies starting with Tech',
                'List all open cases assigned to John'
            ],
        ),
        AgentSkill(
            id='salesforce_data_management',
            name='Salesforce Data Management',
            description="Create, update, and delete Salesforce records including Accounts, Contacts, Leads, Opportunities, and Cases using DML operations.",
            tags=['salesforce', 'crm', 'create', 'update', 'delete', 'dml'],
            examples=[
                'Create a new contact named John Smith at Acme Corp',
                'Update the opportunity status to Closed Won',
                'Create a new account for TechCorp Inc',
                'Delete the duplicate lead record'
            ],
        ),
        AgentSkill(
            id='salesforce_metadata',
            name='Salesforce Metadata Management',
            description="Describe Salesforce objects, create custom objects and fields, manage field-level security permissions, and explore org metadata.",
            tags=['salesforce', 'metadata', 'fields', 'objects', 'permissions', 'schema'],
            examples=[
                'What fields does the Account object have?',
                'Create a new custom field on the Lead object',
                'Show me the picklist values for the Status field',
                'What objects are available containing Order?'
            ],
        ),
        AgentSkill(
            id='salesforce_development',
            name='Salesforce Apex Development',
            description="Read and write Apex classes and triggers, execute anonymous Apex code for testing, and manage debug logs for troubleshooting.",
            tags=['salesforce', 'apex', 'code', 'triggers', 'development', 'debugging'],
            examples=[
                'Show me the code for the AccountTrigger',
                'Read the AccountService Apex class',
                'Run this Apex code to test the logic',
                'Enable debug logs for user admin@example.com'
            ],
        ),
        AgentSkill(
            id='human_interaction',
            name='Human Expert Escalation',
            description="Escalate complex issues to human experts or facilitate human-in-the-loop interactions when automated responses are insufficient.",
            tags=['human-interaction', 'escalation', 'expert', 'human-capable'],
            examples=[
                'Escalate this issue to a human expert',
                'I need to speak with a person',
                'Connect me with a human agent'
            ],
        )
    ]

    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST

    agent_card = AgentCard(
        name='Salesforce CRM Agent',
        description="An intelligent Salesforce agent with full CRM data access (SOQL/SOSL queries, DML operations), metadata management (objects, fields, permissions), and Apex development capabilities (read/write code, debug logs).",
        url=resolve_agent_url(resolved_host_for_url, port),
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities={"streaming": True},
        skills=skills,
    )
    
    # Start background registration
    start_background_registration(agent_card)
    
    # Use uvicorn server directly instead of uvicorn.run() to avoid event loop conflicts
    import uvicorn.server
    config = uvicorn.Config(app, host=host, port=port)
    server = uvicorn.Server(config)
    await server.serve()


def main(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Synchronous wrapper for main_async."""
    asyncio.run(main_async(host, port))


@click.command()
@click.option('--host', 'host', default=DEFAULT_HOST, help='Host to bind to')
@click.option('--port', 'port', default=DEFAULT_PORT, help='Port for A2A server')
@click.option('--ui', is_flag=True, help='Launch Gradio UI (also runs A2A server)')
@click.option('--ui-port', 'ui_port', default=DEFAULT_UI_PORT, help='Port for Gradio UI (only used with --ui flag)')
def cli(host: str, port: int, ui: bool, ui_port: int):
    """AI Foundry Expert Agent - can run as A2A server or with Gradio UI + A2A server."""
    if ui:
        asyncio.run(launch_ui(host, ui_port, port))
    else:
        main(host, port)


if __name__ == '__main__':
    cli()
