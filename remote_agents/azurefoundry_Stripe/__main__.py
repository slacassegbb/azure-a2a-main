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
            logger.warning("Invalid A2A_PORT value '%s'; defaulting to 9030", raw_port)
    return 9030  # Default port for Stripe agent


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
DEFAULT_UI_PORT = 8095  # UI port for Stripe agent

# Global reference to the agent executor to check for pending tasks
agent_executor_instance = None

# Persist a single session ID per UI session
ui_session_id: Optional[str] = None

HOST_AGENT_URL = _normalize_env_value(get_host_agent_url())


def create_a2a_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Create A2A server application for Azure Foundry Stripe agent."""
    global agent_executor_instance
    
    # Define agent skills - STRIPE SPECIFIC
    skills = [
        AgentSkill(
            id='stripe_customers',
            name='Stripe Customer Management',
            description="Create, search, update, and manage customer records in Stripe. Access customer details, payment methods, and subscription history.",
            tags=['stripe', 'customers', 'payments', 'crm'],
            examples=[
                'List all my Stripe customers',
                'Create a new customer with email john@example.com',
                'Search for customers with the name Smith',
                'Get customer details for cus_123abc',
                'Delete customer cus_xyz789'
            ],
        ),
        AgentSkill(
            id='stripe_payments',
            name='Stripe Payment Processing',
            description="Create and manage payment intents, process charges, handle refunds, and track payment status in Stripe.",
            tags=['stripe', 'payments', 'charges', 'refunds', 'payment-intents'],
            examples=[
                'Create a payment intent for $100',
                'List recent payment intents',
                'Show me all successful payments',
                'Process a refund for payment pi_abc123',
                'Check the status of payment intent pi_xyz'
            ],
        ),
        AgentSkill(
            id='stripe_subscriptions',
            name='Stripe Subscription Management',
            description="Create, update, cancel, and manage recurring subscriptions. Handle subscription schedules and billing cycles.",
            tags=['stripe', 'subscriptions', 'recurring', 'billing'],
            examples=[
                'List all active subscriptions',
                'Create a subscription for customer cus_123',
                'Cancel subscription sub_abc',
                'Update subscription to a different plan',
                'Show me subscriptions expiring this month'
            ],
        ),
        AgentSkill(
            id='stripe_products_prices',
            name='Stripe Products & Pricing',
            description="Manage your product catalog and pricing in Stripe. Create products, set prices, and manage pricing tiers.",
            tags=['stripe', 'products', 'prices', 'catalog', 'pricing'],
            examples=[
                'List all products',
                'Create a new product called Premium Plan',
                'Set up a $29/month price for a product',
                'Get price details for price_123',
                'Show me all active prices'
            ],
        ),
        AgentSkill(
            id='stripe_invoices',
            name='Stripe Invoice Management',
            description="Create, send, and manage invoices in Stripe. Track invoice status, payments, and handle invoice items.",
            tags=['stripe', 'invoices', 'billing', 'accounts receivable'],
            examples=[
                'List all unpaid invoices',
                'Create an invoice for customer cus_123',
                'Send invoice inv_abc to the customer',
                'Finalize and send pending invoice',
                'Show me overdue invoices'
            ],
        ),
        AgentSkill(
            id='stripe_balance',
            name='Stripe Balance & Payouts',
            description="Check your Stripe balance, view available and pending funds, and manage payouts to your bank account.",
            tags=['stripe', 'balance', 'payouts', 'funds'],
            examples=[
                'What is my current Stripe balance?',
                'Show me available funds',
                'List recent payouts',
                'How much is pending in my account?'
            ],
        ),
        AgentSkill(
            id='web_search',
            name='Web Search',
            description="Search the web for current information using Bing or other integrated search tools.",
            tags=['web', 'search', 'bing', 'internet'],
            examples=[
                'Search for Stripe best practices',
                'Find information about PCI compliance',
                'Get the latest Stripe API updates'
            ],
        ),
        AgentSkill(
            id='human_interaction',
            name='Human Expert Escalation',
            description="Escalate complex payment issues to human experts or facilitate human-in-the-loop interactions when automated responses are insufficient.",
            tags=['human-interaction', 'escalation', 'expert', 'human-capable'],
            examples=[
                'Escalate this payment issue to a human expert',
                'I need to speak with a person about a dispute',
                'Connect me with support for a chargeback'
            ],
        )
    ]

    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST

    # Create agent card - STRIPE SPECIFIC
    agent_card = AgentCard(
        name='AI Foundry Stripe Agent',
        description="An intelligent agent specialized in Stripe payment processing. Can manage customers, payments, subscriptions, invoices, products, and check balance/payouts. Also supports web search and document search capabilities.",
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
        return PlainTextResponse('AI Foundry Stripe Agent is running!')
    
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
    print(f"Starting AI Foundry Stripe Agent A2A server on {host}:{port}...")
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
    print("Starting Stripe Payment Agent UI and A2A server...")

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

    # Stripe-specific UI skills
    skills = [
        AgentSkill(
            id='stripe_customers',
            name='Stripe Customer Management',
            description="Create, search, update, and manage customer records in Stripe.",
            tags=['stripe', 'customers', 'payments'],
            examples=[
                'List all my Stripe customers',
                'Create a new customer with email john@example.com',
                'Search for customers named Smith'
            ],
        ),
        AgentSkill(
            id='stripe_payments',
            name='Stripe Payment Processing',
            description="Create payment intents, process charges, and handle refunds.",
            tags=['stripe', 'payments', 'charges'],
            examples=[
                'Create a payment intent for $100',
                'List recent payments',
                'Process a refund for payment pi_abc'
            ],
        ),
        AgentSkill(
            id='stripe_subscriptions',
            name='Stripe Subscriptions',
            description="Manage recurring subscriptions and billing cycles.",
            tags=['stripe', 'subscriptions', 'billing'],
            examples=[
                'List all active subscriptions',
                'Create a subscription for customer cus_123',
                'Cancel subscription sub_abc'
            ],
        ),
        AgentSkill(
            id='stripe_invoices',
            name='Stripe Invoice Management',
            description="Create, send, and manage invoices in Stripe.",
            tags=['stripe', 'invoices', 'billing'],
            examples=[
                'List all unpaid invoices',
                'Create an invoice for customer cus_123',
                'Show me overdue invoices'
            ],
        ),
        AgentSkill(
            id='stripe_balance',
            name='Stripe Balance & Payouts',
            description="Check balance, view funds, and manage payouts.",
            tags=['stripe', 'balance', 'payouts'],
            examples=[
                'What is my current Stripe balance?',
                'Show me available funds',
                'List recent payouts'
            ],
        ),
    ]

    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST
    agent_card = AgentCard(
        name='AI Foundry Stripe Agent',
        description="An intelligent agent specialized in Stripe payment processing. Manages customers, payments, subscriptions, invoices, and balance.",
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
        title="Stripe Payment Agent",
        theme=gr.themes.Soft(primary_hue="purple"),  # Purple theme for Stripe
        css="""
            .gradio-container { max-width: 1200px !important; }
            .chat-message { padding: 12px; border-radius: 8px; margin: 4px 0; }
            .skills-list { font-size: 0.9em; }
            #stripe-logo { max-height: 40px; }
        """,
    ) as demo:
        gr.Markdown(
            """
            # 💳 Stripe Payment Agent
            
            **AI-powered payment processing assistant** - Manage customers, payments, subscriptions, and invoices.
            
            *Powered by Azure AI Foundry + Stripe MCP*
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
                gr.Markdown("### 💳 Stripe Capabilities")
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
                        "What is my current Stripe balance?",
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
            global ui_session_id
            if not message.strip():
                yield history, ""
                return

            # Add user message
            history = history + [{"role": "user", "content": message}]
            yield history, ""

            try:
                from foundry_agent import FoundryStripeAgent
                agent = FoundryStripeAgent()
                await agent.create_agent()

                # Create or reuse session
                if ui_session_id is None:
                    ui_session_id = await agent.create_session()
                    logger.info(f"Created new UI session: {ui_session_id}")

                # Get response via streaming
                response_text = ""
                async for chunk in agent.run_conversation_stream(ui_session_id, message):
                    if isinstance(chunk, str) and not chunk.startswith("🛠️ Remote agent executing:"):
                        response_text += chunk

                history = history + [{"role": "assistant", "content": response_text}]
                yield history, ""

            except Exception as e:
                error_msg = f"❌ Error: {str(e)}"
                logger.error(f"Chat error: {e}")
                logger.error(traceback.format_exc())
                history = history + [{"role": "assistant", "content": error_msg}]
                yield history, ""

        def clear_chat():
            global ui_session_id
            ui_session_id = None
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
    """AI Foundry Stripe Payment Agent with A2A protocol support."""
    print("\n" + "=" * 60)
    print("💳 AI Foundry Stripe Payment Agent")
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
                    id='stripe_customers',
                    name='Stripe Customer Management',
                    description="Create, search, update, and manage customer records in Stripe.",
                    tags=['stripe', 'customers', 'payments'],
                    examples=['List all my Stripe customers'],
                ),
                AgentSkill(
                    id='stripe_payments',
                    name='Stripe Payment Processing',
                    description="Create payment intents, process charges, and handle refunds.",
                    tags=['stripe', 'payments', 'charges'],
                    examples=['Create a payment intent for $100'],
                ),
                AgentSkill(
                    id='stripe_balance',
                    name='Stripe Balance',
                    description="Check balance and view available funds.",
                    tags=['stripe', 'balance'],
                    examples=['What is my current Stripe balance?'],
                ),
            ]
            
            resolved_host = host if host != "0.0.0.0" else DEFAULT_HOST
            agent_card = AgentCard(
                name='AI Foundry Stripe Agent',
                description="Intelligent agent for Stripe payment processing - customers, payments, subscriptions, invoices, and balance.",
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
