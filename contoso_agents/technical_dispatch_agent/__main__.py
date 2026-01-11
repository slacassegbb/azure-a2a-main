"""
Contoso Technical Dispatch Agent - Entry point with Human-in-the-Loop UI

Runs the A2A server with self-registration and provides Gradio UI for human expert escalations
"""

import asyncio
import logging
import os
import threading
import time
from typing import List

import click
import gradio as gr
import uvicorn
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from foundry_agent_executor import (
    create_foundry_agent_executor,
    initialize_foundry_agents_at_startup,
    TechnicalDispatchAgentExecutor,
)
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

# Global executor instance for UI access
executor_instance: TechnicalDispatchAgentExecutor | None = None


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
            logger.warning("Invalid A2A_PORT value '%s'; defaulting to 8106", raw_port)
    return 8106


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
    from utils.self_registration import register_with_host_agent, get_host_agent_url

    SELF_REGISTRATION_AVAILABLE = True
    logger.info("✅ Self-registration utility loaded")
except ImportError:
    # Fallback if utils not available
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


def _build_agent_skills() -> List[AgentSkill]:
    """
    Define the technical dispatch agent's skills/capabilities.
    """
    return [
        AgentSkill(
            id="dispatch_scheduling",
            name="Technician Dispatch Scheduling",
            description="Schedule technician appointments for in-home visits when hardware/infrastructure issues require physical intervention. Also escalate complex cases to human experts via human-in-the-loop for edge cases, billing/account problems, or specialized technical scenarios.",
            tags=[
                "dispatch",
                "technician",
                "scheduling",
                "escalation",
                "human-in-loop",
            ],
            examples=[
                "Schedule a technician visit",
                "I need a tech to come to my house",
                "Escalate to human expert",
                "This issue needs specialist attention",
                "Schedule appointment for equipment replacement",
            ],
        ),
    ]


def _create_agent_card(host: str, port: int) -> AgentCard:
    """
    Define the technical dispatch agent's identity.
    """
    skills = _build_agent_skills()
    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST

    return AgentCard(
        name="Contoso Technical Dispatch Agent",
        description="Final decision agent for Contoso customer support workflow. Capabilities: (1) Schedule technician appointments for in-home visits when hardware/infrastructure issues require physical intervention. (2) Escalate complex cases to human experts via human-in-the-loop for edge cases where all diagnostics pass but customer still experiences issues, billing/account problems, or specialized technical scenarios. Integrates complete diagnostic history from all previous agents (authentication, outage, modem, plan, network) to make informed dispatch decisions.",
        url=resolve_agent_url(resolved_host_for_url, port),
        version="1.0.0",
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        capabilities={"streaming": True, "human_in_loop": True},
        skills=skills,
    )


def create_a2a_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Create A2A server application for Contoso Technical Dispatch agent."""
    global executor_instance

    # Get agent card (defined once in _create_agent_card function)
    agent_card = _create_agent_card(host, port)

    executor_instance = create_foundry_agent_executor(agent_card)

    # Create request handler
    request_handler = DefaultRequestHandler(
        agent_executor=executor_instance, task_store=InMemoryTaskStore()
    )

    # Create A2A application
    a2a_app = A2AStarletteApplication(
        agent_card=agent_card, http_handler=request_handler
    )

    # Get routes
    routes = a2a_app.routes()

    # Add health check endpoint
    async def health_check(_: Request) -> PlainTextResponse:
        return PlainTextResponse("Contoso Technical Dispatch Agent is running!")

    routes.append(Route(path="/health", methods=["GET"], endpoint=health_check))

    # Create Starlette app
    app = Starlette(routes=routes)

    return app


def run_a2a_server_in_thread(host: str, port: int) -> None:
    """Run A2A server in a separate thread"""
    logger.info(f"Starting Technical Dispatch A2A server on {host}:{port}")
    app = create_a2a_server(host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


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


def create_hitl_ui(ui_port: int, agent_card: AgentCard) -> gr.Blocks:
    """
    Create Gradio UI for human-in-the-loop escalations

    This UI allows human experts to:
    1. View pending escalation requests with full diagnostic context
    2. Respond to escalated cases
    3. Monitor active escalations
    """

    def get_pending_status() -> str:
        """Get current pending escalations"""
        global executor_instance
        if executor_instance is None:
            return "⚠️ Executor not initialized"

        pending = TechnicalDispatchAgentExecutor.get_pending_escalations()

        if not pending:
            return "✅ No pending escalations\n\nAll customer issues are being handled by automated systems or have been resolved."

        # Format pending escalations
        status_lines = ["🚨 PENDING HUMAN ESCALATIONS\n"]
        for context_id, request_text in pending.items():
            status_lines.append(f"**Context ID:** `{context_id}`")
            status_lines.append(f"\n{request_text}\n")
            status_lines.append("-" * 80)

        return "\n".join(status_lines)

    async def handle_human_response(
        context_id: str, response: str, history: List[dict]
    ) -> tuple[str, str, List[dict]]:
        """Handle human expert response to escalation"""
        global executor_instance

        history = history or []

        if not context_id or not context_id.strip():
            error_msg = "❌ Please enter a Context ID"
            history.append({"role": "assistant", "content": error_msg})
            return "", get_pending_status(), history

        if not response or not response.strip():
            error_msg = "❌ Please enter a response"
            history.append({"role": "assistant", "content": error_msg})
            return "", get_pending_status(), history

        if executor_instance is None:
            error_msg = "❌ Executor not initialized"
            history.append({"role": "assistant", "content": error_msg})
            return "", get_pending_status(), history

        # Add human response to history
        history.append(
            {"role": "user", "content": f"[Context: {context_id}] {response}"}
        )

        try:
            success = await executor_instance.send_human_response(
                context_id.strip(), response.strip()
            )

            if success:
                success_msg = f"✅ Response sent successfully for context `{context_id}`"
                history.append({"role": "assistant", "content": success_msg})
                logger.info(f"✅ Human expert response sent for {context_id}")
            else:
                error_msg = f"❌ No pending escalation found for context `{context_id}`"
                history.append({"role": "assistant", "content": error_msg})
                logger.warning(f"⚠️ No escalation found for {context_id}")

        except Exception as e:
            error_msg = f"❌ Error sending response: {str(e)}"
            history.append({"role": "assistant", "content": error_msg})
            logger.error(f"❌ Error sending human response: {e}", exc_info=True)

        return "", get_pending_status(), history

    def refresh_status() -> str:
        """Refresh pending escalations status"""
        return get_pending_status()

    # Create Gradio interface
    with gr.Blocks(title="Contoso Technical Dispatch - Human Expert Console") as ui:
        gr.Markdown(
            """
        # 🚨 Contoso Technical Dispatch - Human Expert Console
        
        This interface allows human experts to handle escalated customer cases that require manual intervention.
        
        ## When Cases Are Escalated:
        - **False Alarms**: All diagnostics pass but customer still reports issues
        - **Billing/Account Issues**: Service suspension or payment problems
        - **Complex Technical Cases**: Specialized issues beyond automated troubleshooting
        
        ## Your Role:
        Review the complete diagnostic history and provide expert resolution guidance.
        """
        )

        with gr.Row():
            with gr.Column(scale=2):
                status_display = gr.Markdown(
                    value=get_pending_status(), label="Pending Escalations", height=400
                )

                refresh_btn = gr.Button("🔄 Refresh Status", variant="secondary")
                refresh_btn.click(fn=refresh_status, outputs=status_display)

            with gr.Column(scale=1):
                gr.Markdown("### Respond to Escalation")

                context_id_input = gr.Textbox(
                    label="Context ID",
                    placeholder="Enter context ID from escalation",
                    lines=1,
                )

                response_input = gr.Textbox(
                    label="Expert Response",
                    placeholder="Enter your resolution guidance for the customer...",
                    lines=10,
                )

                submit_btn = gr.Button("📤 Send Response", variant="primary")

                gr.Markdown(
                    """
                **Response Guidelines:**
                - Provide clear, actionable resolution steps
                - Reference specific diagnostic results when relevant
                - Include any follow-up actions needed
                - Be empathetic and professional
                """
                )

        gr.Markdown("---")

        with gr.Row():
            chat_history = gr.Chatbot(
                label="Response History", height=300, type="messages"
            )

        # Wire up submit button
        submit_btn.click(
            fn=handle_human_response,
            inputs=[context_id_input, response_input, chat_history],
            outputs=[response_input, status_display, chat_history],
        )

        gr.Markdown(
            """
        ---
        ## Quick Reference:
        
        **Common False Alarm Resolutions:**
        - Verify customer is on correct WiFi network
        - Check device-specific DNS settings (try 8.8.8.8)
        - Test with direct ethernet connection
        - Clear browser cache and try incognito mode
        - Disable VPN/proxy if active
        - Check parental controls or MAC filtering
        
        **Billing Issue Resolutions:**
        - Review account payment status
        - Check for service suspension
        - Offer payment arrangement options
        - Verify no pending cancellation requests
        
        **Complex Technical Resolutions:**
        - Escalate to network engineering if needed
        - Coordinate with field operations
        - Check for infrastructure maintenance in area
        - Review CMTS/DSLAM status
        """
        )

    return ui


def main(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    ui_port: int = 8086,
    enable_ui: bool = True,
):
    """Launch A2A server mode for Contoso Technical Dispatch Agent with startup initialization and optional UI."""
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
    logger.info("=" * 80)
    logger.info("🚀 Starting Contoso Technical Dispatch Agent with Human-in-the-Loop")
    logger.info("=" * 80)
    logger.info("Initializing agent at startup...")
    try:
        asyncio.run(initialize_foundry_agents_at_startup())
        logger.info("✅ Agent initialization completed successfully!")
    except Exception as e:
        logger.error(f"❌ Failed to initialize agents at startup: {e}")
        raise

    logger.info(f"A2A Server: {host}:{port}")
    if enable_ui:
        logger.info(f"Human Expert UI will be at: http://{host}:{ui_port}")
    logger.info("=" * 80)

    # Get agent card
    agent_card = _create_agent_card(host, port)

    if enable_ui:
        # Start A2A server in background thread
        a2a_thread = threading.Thread(
            target=run_a2a_server_in_thread,
            args=(host, port),
            daemon=True,
        )
        a2a_thread.start()

        # Wait for server to start
        time.sleep(3)

        # Register with host agent
        start_background_registration(agent_card)

        # Launch Gradio UI for human experts
        logger.info("🎨 Launching Human Expert UI...")
        ui = create_hitl_ui(ui_port, agent_card)
        ui.launch(
            server_name=host,
            server_port=ui_port,
            share=False,
        )
    else:
        # Run A2A server in main thread without UI
        logger.info("📡 Running in A2A-only mode (no UI)")
        start_background_registration(agent_card)
        app = create_a2a_server(host, port)
        uvicorn.run(app, host=host, port=port)


@click.command()
@click.option("--host", "host", default=DEFAULT_HOST, help="Host to bind to")
@click.option("--port", "port", default=DEFAULT_PORT, help="Port for A2A server")
@click.option(
    "--ui-port", "ui_port", default=8086, type=int, help="Port for human expert UI"
)
@click.option(
    "--enable-ui",
    "enable_ui",
    is_flag=True,
    default=True,
    help="Enable the human expert Gradio UI",
)
def cli(host: str, port: int, ui_port: int, enable_ui: bool):
    """
    Contoso Technical Dispatch Agent - run as an A2A server with optional Human-in-the-Loop UI.

    Final decision agent for scheduling technician visits and escalating to human experts.
    """
    main(host, port, ui_port, enable_ui)


if __name__ == "__main__":
    cli()
