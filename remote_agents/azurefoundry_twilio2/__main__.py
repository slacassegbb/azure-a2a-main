"""
Twilio SMS Agent - A2A Remote Agent for sending SMS messages via Azure AI Foundry.
"""
import asyncio
import logging
import os
import threading

import click
import uvicorn

from foundry_agent_executor import create_foundry_agent_executor, initialize_foundry_twilio_agents_at_startup
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

# Configure logging
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
            logger.warning("Invalid A2A_PORT value '%s'; defaulting to 8016", raw_port)
    return 8016


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
    async def register_with_host_agent(agent_card, host_url=None):
        logger.info("ℹ️ Self-registration utility not available - skipping registration")
        return False
    def get_host_agent_url() -> str:
        return ""
    SELF_REGISTRATION_AVAILABLE = False


DEFAULT_HOST = _resolve_default_host()
DEFAULT_PORT = _resolve_default_port()

HOST_AGENT_URL = _normalize_env_value(get_host_agent_url())

# Global reference to agent executor
agent_executor_instance = None


def create_a2a_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Create A2A server application for Twilio SMS agent."""
    global agent_executor_instance
    
    # Define agent skills for SMS messaging
    skills = [
        AgentSkill(
            id='send_sms',
            name='Send SMS Message',
            description="Send an SMS text message to a phone number via Twilio. Can receive message content from previous workflow steps and deliver it via SMS notification.",
            tags=['sms', 'text', 'message', 'notification', 'twilio', 'phone', 'send'],
            examples=[
                'Send SMS: Your account balance is $1,234.56',
                'Text me a summary of the results',
                'Send a notification via SMS',
                'Message my phone with the workflow output'
            ],
        ),
        AgentSkill(
            id='receive_sms',
            name='Receive SMS Messages',
            description="Retrieve and read recent SMS messages received by this Twilio number. Check for user replies, monitor incoming messages, and retrieve conversation history.",
            tags=['sms', 'text', 'message', 'receive', 'inbox', 'twilio', 'phone', 'read'],
            examples=[
                'Check my SMS messages',
                'Has anyone texted me?',
                'Show me recent SMS replies',
                'Read messages from +15147715943',
                'Get the last 10 SMS messages'
            ],
        ),
        AgentSkill(
            id='notify_user',
            name='User Notification',
            description="Notify a user via SMS with workflow results, alerts, or important updates. Ideal as the final step in a workflow to deliver results to users' phones.",
            tags=['notify', 'alert', 'update', 'result', 'delivery', 'workflow'],
            examples=[
                'Notify me when the task is complete',
                'Send the final results via text message',
                'Alert the user with the summary',
                'Deliver the workflow output by SMS'
            ],
        ),
    ]

    # Create agent card
    agent_card = AgentCard(
        name='Twilio SMS Agent',
        description="A two-way SMS communication agent powered by Azure AI Foundry and Twilio. Send SMS messages to users and retrieve incoming messages. Perfect for notifications, alerts, user replies, and two-way SMS conversations. Can be used as the final step in a workflow to deliver results, or to monitor user responses.",
        url=resolve_agent_url(host, port),
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
    async def health_check(_: Request) -> PlainTextResponse:
        return PlainTextResponse('Twilio SMS Agent is running!')
    
    routes.append(
        Route(
            path='/health',
            methods=['GET'],
            endpoint=health_check
        )
    )

    # Create Starlette app
    app = Starlette(routes=routes)
    
    return app, agent_card


async def register_agent_with_host(agent_card):
    """Register this agent with the host agent after startup."""
    if SELF_REGISTRATION_AVAILABLE:
        await asyncio.sleep(2)
        try:
            logger.info(f"🤝 Attempting to register '{agent_card.name}' with host agent...")
            registration_success = await register_with_host_agent(agent_card, host_url=HOST_AGENT_URL or None)
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


def main(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Launch A2A server mode for Twilio SMS agent."""
    # Verify required environment variables
    required_env_vars = [
        'AZURE_AI_FOUNDRY_PROJECT_ENDPOINT',
        'TWILIO_ACCOUNT_SID',
        'TWILIO_AUTH_TOKEN',
        'TWILIO_FROM_NUMBER'
    ]
    
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing_vars)}\n"
            f"Please set them in your .env file."
        )

    # Initialize Twilio agent at startup
    print("🚀 Initializing Twilio SMS agent at startup...")
    try:
        asyncio.run(initialize_foundry_twilio_agents_at_startup())
        print("✅ Twilio SMS agent initialization completed successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize Twilio agent at startup: {e}")
        raise

    print(f"Starting Twilio SMS Agent A2A server on {host}:{port}...")
    app, agent_card = create_a2a_server(host, port)
    
    # Start background registration
    start_background_registration(agent_card)
    
    uvicorn.run(app, host=host, port=port)


@click.command()
@click.option('--host', 'host', default=DEFAULT_HOST, help='Host to bind to')
@click.option('--port', 'port', default=DEFAULT_PORT, help='Port for A2A server')
def cli(host: str, port: int):
    """Twilio SMS Agent - A2A server for sending SMS notifications via Azure AI Foundry."""
    main(host, port)


if __name__ == '__main__':
    cli()
