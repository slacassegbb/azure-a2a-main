import asyncio
import logging
import os
import traceback
from collections.abc import AsyncIterator
from typing import List
import threading

import click
import gradio as gr
import uvicorn

from foundry_agent_executor import create_foundry_agent_executor, initialize_foundry_template_agents_at_startup
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
            logger.warning("Invalid A2A_PORT value '%s'; defaulting to 9020", raw_port)
    return 9020


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
    async def register_with_host_agent(agent_card, host_url=None):
        logger.info("ℹ️ Self-registration utility not available - skipping registration")
        return False
    def get_host_agent_url() -> str:
        return ""
    SELF_REGISTRATION_AVAILABLE = False

# ⚠️ CUSTOMIZATION: Update these default ports to avoid conflicts with other agents
DEFAULT_HOST = _resolve_default_host()
DEFAULT_PORT = _resolve_default_port()  # Default: 9020 (set in A2A_PORT env var)
DEFAULT_UI_PORT = 9120  # Default UI port for Gradio interface

HOST_AGENT_URL = _normalize_env_value(get_host_agent_url())

# Global reference to the agent executor to check for pending tasks
agent_executor_instance = None


def _build_agent_skills() -> List[AgentSkill]:
    """
    Interview Agent Skills - Lead Capture Focus
    
    This agent's primary purpose is to capture lead information (name, email, company, use case)
    so that subsequent agents can generate reports and send follow-ups.
    """
    return [
        AgentSkill(
            id='lead_capture',
            name='Lead Information Capture',
            description="Capture essential lead information including name, email, company, and use case. Designed to efficiently gather contact details for follow-up with personalized reports.",
            tags=['lead', 'capture', 'contact', 'email', 'qualification'],
            examples=[
                'I want to learn more about AI solutions for my business',
                'Can you help me understand what AI could do for my company?',
                'We need to automate some of our business processes',
                'Tell me about your AI consulting services',
            ],
        ),
        AgentSkill(
            id='use_case_discovery',
            name='Use Case Discovery',
            description="Quickly understand what the customer wants to accomplish with AI so we can provide relevant recommendations in a follow-up report.",
            tags=['discovery', 'use-case', 'requirements', 'ai-needs'],
            examples=[
                'I need help with customer service automation',
                'We want to use AI for document processing',
                'Looking to implement RAG for our knowledge base',
            ],
        ),
        AgentSkill(
            id='contact_collection',
            name='Contact Information Collection',
            description="Gather contact details (name, email) to send personalized AI consultation reports and recommendations.",
            tags=['contact', 'email', 'follow-up', 'report'],
            examples=[
                'Sure, my email is...',
                'You can reach me at...',
                'Send the report to...',
            ],
        ),
    ]


def _create_agent_card(host: str, port: int) -> AgentCard:
    """
    Interview Agent Card
    
    Defines the agent's identity for registration and discovery in the A2A ecosystem.
    This information appears in the agent catalog and determines how the agent is routed.
    """
    skills = _build_agent_skills()
    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST
    
    return AgentCard(
        name='AI Consulting Interview Agent',
        description="A lead capture agent that efficiently gathers contact information (name, email, company) and use case details from potential customers. Outputs structured lead data for downstream agents to generate personalized reports and send follow-up emails.",
        url=resolve_agent_url(resolved_host_for_url, port),
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities={"streaming": True, "input_required": True},
        skills=skills,
    )


def create_a2a_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Create A2A server application for your custom agent."""
    global agent_executor_instance

    # Get agent card (defined once in _create_agent_card function)
    agent_card = _create_agent_card(host, port)

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
        return PlainTextResponse('AI Consulting Interview Agent is running!')
    
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
    print(f"Starting AI Foundry Template Agent A2A server on {host}:{port}...")
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


async def get_foundry_response(
    message: str,
    _history: list[gr.ChatMessage],
) -> AsyncIterator[gr.ChatMessage]:
    """Get response from the Azure Foundry agent for the Gradio UI."""
    global agent_executor_instance
    try:
        # Use the same shared agent instance as the A2A executor
        if agent_executor_instance is None:
            # Initialize the executor if not already done
            agent_executor_instance = create_foundry_agent_executor(
                AgentCard(name="UI Agent", description="UI Agent", url="", version="1.0.0")
            )
        
        # Get the shared agent from the executor
        foundry_agent = await agent_executor_instance._get_or_create_agent()
        
        # Use the same shared thread as the A2A executor to minimize API calls
        thread_id = await agent_executor_instance._get_or_create_thread("ui_context", foundry_agent)
        
        # Send a status update (⚠️ CUSTOMIZATION: Update this message)
        yield gr.ChatMessage(
            role="assistant",
            content="🤔 **Processing your request...**",
        )
        
        # Run the conversation using the streaming method
        response_count = 0
        async for response in foundry_agent.run_conversation_stream(thread_id, message):
            print("[DEBUG] get_foundry_response: response=", response)
            if isinstance(response, str):
                if response.strip():
                    # Filter out processing messages
                    if not any(phrase in response.lower() for phrase in [
                        "processing your request", "🤖 processing", "processing...",
                        "🤔 processing"
                    ]):
                        yield gr.ChatMessage(role="assistant", content=response)
                        response_count += 1
            else:
                # handle other types if needed
                logger.debug(f"get_foundry_response: Unexpected response type: {type(response)}")
                yield gr.ChatMessage(
                    role="assistant",
                    content=f"An error occurred while processing your request: {str(response)}. Please check the server logs for details.",
                )
                response_count += 1
        
        # If no responses were yielded, show a default message
        if response_count == 0:
            yield gr.ChatMessage(
                role="assistant",
                content="I processed your request but didn't generate a response. Please try rephrasing your question or providing more context."
            )
            
    except Exception as e:
        logger.error(f"Error in get_foundry_response (Type: {type(e)}): {e}")
        traceback.print_exc()
        yield gr.ChatMessage(
            role="assistant",
            content=f"An error occurred while processing your request: {str(e)}. Please check the server logs for details.",
        )


async def launch_ui(host: str = "0.0.0.0", ui_port: int = DEFAULT_UI_PORT, a2a_port: int = DEFAULT_PORT):
    """Launch Gradio UI and A2A server simultaneously for the template agent."""
    print("Starting AI Foundry Template Agent with both UI and A2A server...")
    
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

    # Initialize agent at startup BEFORE starting servers
    print("🚀 Initializing AI Foundry agent at startup...")
    try:
        await initialize_foundry_template_agents_at_startup()
        print("✅ Agent initialization completed successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize agent at startup: {e}")
        raise

    # Start A2A server in a separate thread
    a2a_thread = threading.Thread(
        target=run_a2a_server_in_thread,
        args=(host if host != "0.0.0.0" else DEFAULT_HOST, a2a_port),
        daemon=True
    )
    a2a_thread.start()
    
    # Give the A2A server a moment to start
    await asyncio.sleep(2)
    
    # Get agent card and start background registration
    agent_card = _create_agent_card(host, a2a_port)
    start_background_registration(agent_card)

    def check_system_status():
        """Check system status for the agent."""
        return "✅ **Status:** Interview Agent Ready to Qualify Leads!"

    display_host = resolved_host_for_url
    ui_display_url = f"http://{display_host}:{ui_port}"
    a2a_display_url = resolve_agent_url(display_host, a2a_port).rstrip('/')

    with gr.Blocks(theme=gr.themes.Ocean(), title="AI Consulting Interview Agent") as demo:
        gr.Image(
            "static/a2a.png",  # ⚠️ CUSTOMIZATION: Replace with your own logo
            width=100,
            height=100,
            scale=0,
            show_label=False,
            show_download_button=False,
            container=False,
            show_fullscreen_button=False,
        )
        gr.Markdown(f"""
        ## 🎤 AI Consulting Interview Agent

        **Direct UI Access:** {ui_display_url}  
        **A2A API Access:** {a2a_display_url}

        I'm your intelligent interview assistant designed to conduct consultative discovery conversations
        to understand your AI and automation needs.

        **What I do:**
        - Conduct thoughtful interviews to understand your business challenges
        - Probe intelligently to gather comprehensive information
        - Assess your technical environment and requirements
        - Identify stakeholders and decision-making processes
        - Qualify leads and recommend appropriate next steps

        ### Core Capabilities
        - **Lead Qualification:** Systematic discovery of business needs and AI opportunities
        - **Business Assessment:** Deep understanding of pain points and success criteria  
        - **Technical Discovery:** Evaluation of infrastructure, data, and team capabilities
        - **Stakeholder Mapping:** Identification of decision-makers and approval processes
        - **Consultation Scheduling:** Coordinating next steps with AI specialists

        💡 **Tip:** I ask questions one at a time to have a natural conversation. Feel free to elaborate!
        """)

        # Add a status display that refreshes automatically
        with gr.Row():
            status_display = gr.Markdown(value=check_system_status())
            refresh_btn = gr.Button("🔄 Refresh Status", size="sm")
            refresh_btn.click(fn=check_system_status, outputs=status_display)

        # Set up automatic refresh using timer (every 5 seconds)
        timer = gr.Timer(5)
        timer.tick(fn=check_system_status, outputs=status_display)

        # Add a hidden component that triggers refresh via JavaScript
        gr.HTML("""
        <script>
        setInterval(function() {
            // Find the refresh button by its text content
            const buttons = document.querySelectorAll('button');
            for (let btn of buttons) {
                if (btn.textContent.includes('🔄 Refresh Status')) {
                    btn.click();
                    break;
                }
            }
        }, 3000);
        </script>
        """, visible=False)

        async def _ui_process(message, history):
            if foundry_agent_executor._last_received_files:
                print("[Template UI] Latest file references from host agent:")
                for file_info in foundry_agent_executor._last_received_files:
                    print(
                        f"  • name={file_info.get('name')} uri={file_info.get('uri')} mime={file_info.get('mime')}"
                    )
            chunks = []
            async for chunk in get_foundry_response(message, history):
                chunks.append(chunk)
            if not chunks:
                return []
            if len(chunks) == 1:
                return chunks[0]
            return chunks

        gr.ChatInterface(
            _ui_process,
            title="",
            description="Tell me about your company and what brings you here today. I'll ask follow-up questions to understand your needs.",
        )

    print(f"Launching AI Consulting Interview Agent Gradio interface on {host}:{ui_port}...")
    demo.queue().launch(
        server_name=host,
        server_port=ui_port,
    )
    print("AI Consulting Interview Agent Gradio application has been shut down.")


def main(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Launch A2A server mode for the Azure Foundry interview agent with startup initialization."""
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

    # Initialize agent at startup BEFORE starting server
    print("🚀 Initializing AI Foundry agent at startup...")
    try:
        asyncio.run(initialize_foundry_template_agents_at_startup())
        print("✅ Agent initialization completed successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize agent at startup: {e}")
        raise

    print(f"Starting AI Foundry Template Agent A2A server on {host}:{port}...")
    app = create_a2a_server(host, port)
    
    # Get agent card and start background registration
    agent_card = _create_agent_card(host, port)
    start_background_registration(agent_card)
    
    uvicorn.run(app, host=host, port=port)


@click.command()
@click.option('--host', 'host', default=DEFAULT_HOST, help='Host to bind to')
@click.option('--port', 'port', default=DEFAULT_PORT, help='Port for A2A server')
@click.option('--ui', is_flag=True, help='Launch Gradio UI (also runs A2A server)')
@click.option('--ui-port', 'ui_port', default=DEFAULT_UI_PORT, help='Port for Gradio UI (only used with --ui flag)')
def cli(host: str, port: int, ui: bool, ui_port: int):
    """
    AI Foundry Template Agent - run as an A2A server or with Gradio UI + A2A server.
    
    ⚠️ CUSTOMIZATION: Update this help text to describe your agent.
    """
    if ui:
        asyncio.run(launch_ui(host, ui_port, port))
    else:
        main(host, port)


if __name__ == '__main__':
    cli()
