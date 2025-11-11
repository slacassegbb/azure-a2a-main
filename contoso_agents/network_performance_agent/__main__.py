"""
Contoso Network Performance Agent - Entry point

Runs the A2A server with self-registration to host agent
"""

import asyncio
import logging
import os
import threading
from typing import List

import click
import uvicorn

from .foundry_agent_executor import (
    create_foundry_agent_executor,
    initialize_foundry_agents_at_startup,
)
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
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(
    logging.WARNING
)
logging.getLogger("azure.identity").setLevel(logging.WARNING)
logging.getLogger("azure").setLevel(logging.WARNING)


def _normalize_env_value(raw_value: str | None) -> str:
    if raw_value is None:
        return ""
    return raw_value.strip()


def _resolve_default_host() -> str:
    value = _normalize_env_value(os.getenv("A2A_ENDPOINT"))
    return value or "localhost"


def _resolve_default_port() -> int:
    raw_port = _normalize_env_value(os.getenv("A2A_PORT"))
    if raw_port:
        try:
            return int(raw_port)
        except ValueError:
            logger.warning("Invalid A2A_PORT value '%s'; defaulting to 8105", raw_port)
    return 8105


def resolve_agent_url(bind_host: str, bind_port: int) -> str:
    endpoint = _normalize_env_value(os.getenv("A2A_ENDPOINT"))
    if endpoint:
        if endpoint.startswith(("http://", "https://")):
            return endpoint.rstrip("/") + "/"
        host_for_url = endpoint
    else:
        host_for_url = bind_host if bind_host != "0.0.0.0" else _resolve_default_host()

    return f"http://{host_for_url}:{bind_port}/"


# Import self-registration utility
try:
    from .utils.self_registration import register_with_host_agent, get_host_agent_url

    SELF_REGISTRATION_AVAILABLE = True
    logger.info("✅ Self-registration utility loaded")
except ImportError as e:
    # Fallback if utils not available
    logger.warning(f"⚠️ Self-registration import failed: {e}")
    async def register_with_host_agent(agent_card, host_url=None):
        logger.info(
            "ℹ️ Self-registration utility not available - skipping registration"
        )
        return False

    def get_host_agent_url() -> str:
        return ""

    SELF_REGISTRATION_AVAILABLE = False

DEFAULT_HOST = _resolve_default_host()
DEFAULT_PORT = _resolve_default_port()

HOST_AGENT_URL = _normalize_env_value(get_host_agent_url())

# Global reference to the agent executor
agent_executor_instance = None


def _build_agent_skills() -> List[AgentSkill]:
    """
    Define the network performance agent's skills/capabilities.
    """
    return [
        AgentSkill(
            id="network_diagnostics",
            name="Network Performance Diagnostics",
            description="Perform comprehensive network diagnostics including ping tests to modem/pods/devices, device discovery with IP addresses, latency and packet loss analysis. Can trigger network resets when performance issues detected or as preventive measure. Identifies critical issues requiring technician dispatch.",
            tags=["network", "diagnostics", "performance", "ping", "latency"],
            examples=[
                "Run network diagnostics",
                "Check network performance for customer",
                "Test latency and packet loss",
                "Discover devices on network",
                "Should we reset the network?",
            ],
        ),
    ]


def _create_agent_card(host: str, port: int) -> AgentCard:
    """
    Define the network performance agent's identity.
    """
    skills = _build_agent_skills()
    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST

    return AgentCard(
        name="Contoso Network Performance Agent",
        description="Performs comprehensive network diagnostics for Contoso internet customers. Capabilities: ping tests to modem/pods/devices, device discovery with IP addresses, latency and packet loss analysis, proactive network reset recommendations. Can trigger network resets when performance issues detected or as preventive measure before declaring all clear. Identifies critical issues requiring technician dispatch.",
        url=resolve_agent_url(resolved_host_for_url, port),
        version="1.0.0",
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        capabilities={"streaming": True},
        skills=skills,
    )


def create_a2a_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Create A2A server application for Contoso Network Performance agent."""
    global agent_executor_instance

    # Get agent card (defined once in _create_agent_card function)
    agent_card = _create_agent_card(host, port)

    agent_executor_instance = create_foundry_agent_executor(agent_card)

    # Create request handler
    request_handler = DefaultRequestHandler(
        agent_executor=agent_executor_instance, task_store=InMemoryTaskStore()
    )

    # Create A2A application
    a2a_app = A2AStarletteApplication(
        agent_card=agent_card, http_handler=request_handler
    )

    # Get routes
    routes = a2a_app.routes()

    # Add health check endpoint
    async def health_check(_: Request) -> PlainTextResponse:
        return PlainTextResponse("Contoso Network Performance Agent is running!")

    routes.append(Route(path="/health", methods=["GET"], endpoint=health_check))

    # Create Starlette app
    app = Starlette(routes=routes)

    return app


async def register_agent_with_host(agent_card):
    """Register this agent with the host agent after startup."""
    if SELF_REGISTRATION_AVAILABLE:
        # Wait a moment for server to fully start
        await asyncio.sleep(2)
        try:
            if not HOST_AGENT_URL:
                logger.info(
                    "ℹ️ Host agent URL not configured; skipping registration attempt."
                )
                return

            logger.info(
                f"🤝 Attempting to register '{agent_card.name}' with host agent at {HOST_AGENT_URL}..."
            )
            registration_success = await register_with_host_agent(
                agent_card, host_url=HOST_AGENT_URL
            )
            if registration_success:
                logger.info(
                    f"🎉 '{agent_card.name}' successfully registered with host agent!"
                )
            else:
                logger.info(
                    f"📡 '{agent_card.name}' registration failed - host agent may be unavailable"
                )
        except Exception as e:
            logger.warning(f"⚠️ Registration attempt failed: {e}")


def start_background_registration(agent_card):
    """Start background registration task."""
    if SELF_REGISTRATION_AVAILABLE:

        def run_registration():
            asyncio.run(register_agent_with_host(agent_card))

        registration_thread = threading.Thread(target=run_registration, daemon=True)
        registration_thread.start()
        logger.info(
            f"🚀 '{agent_card.name}' starting with background registration enabled"
        )
    else:
        logger.info(f"📡 '{agent_card.name}' starting without self-registration")


def main(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Launch A2A server mode for Contoso Network Performance Agent with startup initialization."""
    # Verify required environment variables
    required_env_vars = [
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME",
    ]

    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing_vars)}"
        )

    # Initialize agent at startup BEFORE starting server
    logger.info("🚀 Initializing Contoso Network Performance Agent at startup...")
    try:
        asyncio.run(initialize_foundry_agents_at_startup())
        logger.info("✅ Agent initialization completed successfully!")
    except Exception as e:
        logger.error(f"❌ Failed to initialize agents at startup: {e}")
        raise

    logger.info(
        f"Starting Contoso Network Performance Agent A2A server on {host}:{port}..."
    )
    app = create_a2a_server(host, port)

    # Get agent card and start background registration
    agent_card = _create_agent_card(host, port)
    start_background_registration(agent_card)

    uvicorn.run(app, host=host, port=port)


@click.command()
@click.option("--host", "host", default=DEFAULT_HOST, help="Host to bind to")
@click.option("--port", "port", default=DEFAULT_PORT, help="Port for A2A server")
def cli(host: str, port: int):
    """
    Contoso Network Performance Agent - run as an A2A server.

    Performs comprehensive network diagnostics for Contoso customers.
    """
    main(host, port)


if __name__ == "__main__":
    cli()
