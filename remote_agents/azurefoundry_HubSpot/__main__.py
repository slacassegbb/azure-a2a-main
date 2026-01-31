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
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

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
            logger.warning("Invalid A2A_PORT value '%s'; defaulting to 9040", raw_port)
    return 9040  # Default port for HubSpot agent


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
DEFAULT_UI_PORT = 8097  # UI port for HubSpot agent

# Global reference to the agent executor to check for pending tasks
agent_executor_instance = None

# Persist a single Azure Foundry thread per UI session
ui_thread_id: Optional[str] = None

HOST_AGENT_URL = _normalize_env_value(get_host_agent_url())


def create_a2a_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Create A2A server application for Azure Foundry HubSpot agent."""
    global agent_executor_instance
    
    # Define agent skills - HUBSPOT CRM SPECIFIC
    skills = [
        AgentSkill(
            id='hubspot_contacts',
            name='HubSpot Contact Management',
            description="Create, search, update, and manage contact records in HubSpot CRM. Access contact details, track interactions, and manage contact properties.",
            tags=['hubspot', 'contacts', 'crm', 'people'],
            examples=[
                'List all my HubSpot contacts',
                'Create a new contact with email john@example.com',
                'Search for contacts with the last name Smith',
                'Get contact details for contact ID 123',
                'Update the phone number for a contact'
            ],
        ),
        AgentSkill(
            id='hubspot_companies',
            name='HubSpot Company Management',
            description="Create, search, update, and manage company records in HubSpot CRM. Track company information, industry, and relationships.",
            tags=['hubspot', 'companies', 'crm', 'organizations'],
            examples=[
                'List all companies in HubSpot',
                'Create a new company called Acme Corp',
                'Search for companies in the tech industry',
                'Get company details for company ID 456',
                'Update company website information'
            ],
        ),
        AgentSkill(
            id='hubspot_deals',
            name='HubSpot Deal Management',
            description="Create, search, update, and manage deals/opportunities in HubSpot CRM. Track deal stages, amounts, and close dates.",
            tags=['hubspot', 'deals', 'crm', 'sales', 'opportunities'],
            examples=[
                'List all open deals',
                'Create a new deal for $50,000',
                'Search for deals closing this month',
                'Update deal stage to Closed Won',
                'Show me deals in the negotiation stage'
            ],
        ),
        AgentSkill(
            id='hubspot_associations',
            name='HubSpot Associations & Relationships',
            description="View and manage relationships between HubSpot objects. See which contacts are associated with which companies and deals.",
            tags=['hubspot', 'associations', 'relationships', 'crm'],
            examples=[
                'Show me all contacts associated with company ID 123',
                'What deals are linked to this contact?',
                'List associations between contacts and companies',
                'Find all companies connected to this deal'
            ],
        ),
        AgentSkill(
            id='hubspot_notes',
            name='HubSpot Notes & Engagements',
            description="Create notes and engagement records on HubSpot CRM objects. Track interactions, meetings, and communications.",
            tags=['hubspot', 'notes', 'engagements', 'crm', 'activities'],
            examples=[
                'Add a note to contact ID 123',
                'Create a meeting note for a deal',
                'Log an interaction with a company',
                'Add follow-up notes after a call'
            ],
        ),
        AgentSkill(
            id='hubspot_account',
            name='HubSpot Account Information',
            description="View HubSpot account details, owners, and permissions. Get information about the connected HubSpot portal.",
            tags=['hubspot', 'account', 'portal', 'owners'],
            examples=[
                'What HubSpot account am I connected to?',
                'List all owners in this HubSpot portal',
                'Show me account details',
                'What permissions do I have?'
            ],
        ),
        AgentSkill(
            id='web_search',
            name='Web Search',
            description="Search the web for current information using Bing or other integrated search tools.",
            tags=['web', 'search', 'bing', 'internet'],
            examples=[
                'Search for HubSpot best practices',
                'Find information about PCI compliance',
                'Get the latest HubSpot API updates'
            ],
        ),
        AgentSkill(
            id='human_interaction',
            name='Human Expert Escalation',
            description="Escalate complex CRM issues to human experts or facilitate human-in-the-loop interactions when automated responses are insufficient.",
            tags=['human-interaction', 'escalation', 'expert', 'human-capable'],
            examples=[
                'Escalate this CRM issue to a human expert',
                'I need to speak with a person about data migration',
                'Connect me with support for a complex workflow'
            ],
        )
    ]

    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST

    # Create agent card - HUBSPOT SPECIFIC
    agent_card = AgentCard(
        name='AI Foundry HubSpot Agent',
        description="An intelligent agent specialized in HubSpot CRM management. Can manage contacts, companies, deals, tickets, notes, and associations. Also supports web search and document search capabilities.",
        url=resolve_agent_url(resolved_host_for_url, port),
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities=AgentCapabilities(streaming=True),
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
        return PlainTextResponse('AI Foundry HubSpot Agent is running!')
    
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
    print(f"Starting AI Foundry HubSpot Agent A2A server on {host}:{port}...")
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
    print("Starting HubSpot Payment Agent UI and A2A server...")

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

    # HubSpot-specific UI skills
    skills = [
        AgentSkill(
            id='hubspot_customers',
            name='HubSpot Customer Management',
            description="Create, search, update, and manage customer records in HubSpot.",
            tags=['hubspot', 'customers', 'payments'],
            examples=[
                'List all my HubSpot customers',
                'Create a new customer with email john@example.com',
                'Search for customers named Smith'
            ],
        ),
        AgentSkill(
            id='hubspot_payments',
            name='HubSpot Payment Processing',
            description="Create payment intents, process charges, and handle refunds.",
            tags=['hubspot', 'payments', 'charges'],
            examples=[
                'Create a payment intent for $100',
                'List recent payments',
                'Process a refund for payment pi_abc'
            ],
        ),
        AgentSkill(
            id='hubspot_subscriptions',
            name='HubSpot Subscriptions',
            description="Manage recurring subscriptions and billing cycles.",
            tags=['hubspot', 'subscriptions', 'billing'],
            examples=[
                'List all active subscriptions',
                'Create a subscription for customer cus_123',
                'Cancel subscription sub_abc'
            ],
        ),
        AgentSkill(
            id='hubspot_invoices',
            name='HubSpot Invoice Management',
            description="Create, send, and manage invoices in HubSpot.",
            tags=['hubspot', 'invoices', 'billing'],
            examples=[
                'List all unpaid invoices',
                'Create an invoice for customer cus_123',
                'Show me overdue invoices'
            ],
        ),
        AgentSkill(
            id='hubspot_balance',
            name='HubSpot Balance & Payouts',
            description="Check balance, view funds, and manage payouts.",
            tags=['hubspot', 'balance', 'payouts'],
            examples=[
                'What is my current HubSpot balance?',
                'Show me available funds',
                'List recent payouts'
            ],
        ),
    ]

    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST
    agent_card = AgentCard(
        name='AI Foundry HubSpot Agent',
        description="An intelligent agent specialized in HubSpot payment processing. Manages customers, payments, subscriptions, invoices, and balance.",
        url=resolve_agent_url(resolved_host_for_url, a2a_port),
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities=AgentCapabilities(streaming=True),
        skills=skills,
    )

    # Start background registration
    start_background_registration(agent_card)

    # Build Gradio UI
    with gr.Blocks(
        title="HubSpot Payment Agent",
        theme=gr.themes.Soft(primary_hue="purple"),  # Purple theme for HubSpot
        css="""
            .gradio-container { max-width: 1200px !important; }
            .chat-message { padding: 12px; border-radius: 8px; margin: 4px 0; }
            .skills-list { font-size: 0.9em; }
            #hubspot-logo { max-height: 40px; }
        """,
    ) as demo:
        gr.Markdown(
            """
            # 💳 HubSpot Payment Agent
            
            **AI-powered payment processing assistant** - Manage customers, payments, subscriptions, and invoices.
            
            *Powered by Azure AI Foundry + HubSpot MCP*
            """
        )

        with gr.Row():
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(
                    label="Chat",
                    height=500,
                    show_copy_button=True,
                    type="messages",
                )
                with gr.Row():
                    msg = gr.Textbox(
                        label="Your message",
                        placeholder="e.g., 'List all customers' or 'What is my balance?'",
                        scale=6,
                        show_label=False,
                    )
                    send_btn = gr.Button("Send", variant="primary", scale=1)
                    clear_btn = gr.Button("Clear", scale=1)

            with gr.Column(scale=1):
                gr.Markdown("### 💳 HubSpot Capabilities")
                gr.Markdown(
                    """
                    **Customers**
                    - List, create, search customers
                    - View customer details
                    
                    **Payments**
                    - Create payment intents
                    - Process charges & refunds
                    
                    **Subscriptions**
                    - Manage recurring billing
                    - Create/cancel subscriptions
                    
                    **Invoices**
                    - Create and send invoices
                    - Track payment status
                    
                    **Balance**
                    - Check available funds
                    - View pending balance
                    """,
                    elem_classes=["skills-list"],
                )
                
                gr.Markdown("### 📊 Quick Actions")
                example_queries = gr.Examples(
                    examples=[
                        "What is my current HubSpot balance?",
                        "List all my customers",
                        "Show me all active subscriptions",
                        "List recent payment intents",
                        "Create a customer with email test@example.com",
                    ],
                    inputs=msg,
                    label="Try these:",
                )

        # Chat logic
        async def chat_with_agent(message: str, history: list):
            global ui_thread_id
            if not message.strip():
                yield history, ""
                return

            # Add user message
            history = history + [{"role": "user", "content": message}]
            yield history, ""

            try:
                from foundry_agent import FoundryHubSpotAgent
                agent = FoundryHubSpotAgent()
                await agent.create_agent()

                # Create or reuse thread
                if ui_thread_id is None:
                    thread = agent._get_project_client().agents.threads.create()
                    ui_thread_id = thread.id
                    logger.info(f"Created new UI thread: {ui_thread_id}")

                # Get response
                response_text = ""
                async for chunk in agent.run_with_streaming(ui_thread_id, message):
                    if isinstance(chunk, str):
                        response_text += chunk
                    elif hasattr(chunk, 'text'):
                        response_text += chunk.text

                history = history + [{"role": "assistant", "content": response_text}]
                yield history, ""

            except Exception as e:
                error_msg = f"❌ Error: {str(e)}"
                logger.error(f"Chat error: {e}")
                logger.error(traceback.format_exc())
                history = history + [{"role": "assistant", "content": error_msg}]
                yield history, ""

        def clear_chat():
            global ui_thread_id
            ui_thread_id = None
            return [], ""

        # Wire up events
        msg.submit(chat_with_agent, [msg, chatbot], [chatbot, msg])
        send_btn.click(chat_with_agent, [msg, chatbot], [chatbot, msg])
        clear_btn.click(clear_chat, outputs=[chatbot, msg])

    # Launch Gradio
    demo.queue()
    demo.launch(
        server_name=host,
        server_port=ui_port,
        share=False,
        show_error=True,
    )


@click.command()
@click.option('--host', default=DEFAULT_HOST, help='Hostname for A2A server')
@click.option('--port', default=DEFAULT_PORT, type=int, help='Port for A2A server')
@click.option('--ui', is_flag=True, default=False, help='Launch Gradio UI')
@click.option('--ui-port', default=DEFAULT_UI_PORT, type=int, help='Port for Gradio UI')
def main(host: str, port: int, ui: bool, ui_port: int):
    """AI Foundry HubSpot Payment Agent with A2A protocol support."""
    print("\n" + "=" * 60)
    print("💳 AI Foundry HubSpot Payment Agent")
    print("=" * 60)
    print(f"Host: {host}")
    print(f"A2A Port: {port}")
    if ui:
        print(f"UI Port: {ui_port}")
    print("=" * 60 + "\n")

    if ui:
        asyncio.run(launch_ui(host, ui_port, port))
    else:
        # Just run A2A server
        print("🚀 Initializing AI Foundry agents at startup...")
        
        async def init_and_run():
            try:
                await initialize_foundry_agents_at_startup()
                print("✅ Agent initialization completed successfully!")
            except Exception as e:
                print(f"❌ Failed to initialize agents at startup: {e}")
                raise
            
            # Create agent card for registration
            skills = [
                AgentSkill(
                    id='hubspot_customers',
                    name='HubSpot Customer Management',
                    description="Create, search, update, and manage customer records in HubSpot.",
                    tags=['hubspot', 'customers', 'payments'],
                    examples=['List all my HubSpot customers'],
                ),
                AgentSkill(
                    id='hubspot_payments',
                    name='HubSpot Payment Processing',
                    description="Create payment intents, process charges, and handle refunds.",
                    tags=['hubspot', 'payments', 'charges'],
                    examples=['Create a payment intent for $100'],
                ),
                AgentSkill(
                    id='hubspot_balance',
                    name='HubSpot Balance',
                    description="Check balance and view available funds.",
                    tags=['hubspot', 'balance'],
                    examples=['What is my current HubSpot balance?'],
                ),
            ]
            
            resolved_host = host if host != "0.0.0.0" else DEFAULT_HOST
            agent_card = AgentCard(
                name='AI Foundry HubSpot Agent',
                description="Intelligent agent for HubSpot payment processing - customers, payments, subscriptions, invoices, and balance.",
                url=resolve_agent_url(resolved_host, port),
                version='1.0.0',
                defaultInputModes=['text'],
                defaultOutputModes=['text'],
                capabilities=AgentCapabilities(streaming=True),
                skills=skills,
            )
            
            # Start background registration
            start_background_registration(agent_card)
            
            # Run the A2A server
            app = create_a2a_server(host, port)
            config = uvicorn.Config(app, host=host, port=port, log_level="info")
            server = uvicorn.Server(config)
            await server.serve()
        
        asyncio.run(init_and_run())


if __name__ == "__main__":
    main()
