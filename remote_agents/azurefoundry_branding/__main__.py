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

from foundry_agent_executor import create_foundry_agent_executor, initialize_foundry_branding_agents_at_startup
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

# Updated ports to avoid conflicts with other agents
DEFAULT_HOST = _resolve_default_host()
DEFAULT_PORT = _resolve_default_port()  # Branding agent A2A port
DEFAULT_UI_PORT = 9120  # Branding agent UI port

HOST_AGENT_URL = _normalize_env_value(get_host_agent_url())

# Global reference to the agent executor to check for pending tasks
agent_executor_instance = None


def _build_branding_skills() -> List[AgentSkill]:
    """Return the standard set of skills advertised by the branding agent."""
    return [
        AgentSkill(
            id='brand_strategy_alignment',
            name='Brand Strategy Alignment',
            description="Map campaign goals, audiences, and messaging pillars to the Company Branding Guide, ensuring voice, tone, and terminology remain on-brand.",
            tags=['branding', 'strategy', 'messaging', 'tone'],
            examples=[
                'Outline messaging pillars for a product-launch email aligned to the brand voice',
                'Review draft tagline options and recommend the on-brand choice with rationale',
                'Summarize how a campaign concept supports our innovation + trust positioning',
                'Identify missing brand attributes in a draft hero statement and propose fixes'
            ],
        ),
        AgentSkill(
            id='visual_identity_direction',
            name='Visual Identity Direction',
            description="Provide art direction, mood, and composition notes anchored in brand colors, lighting, and imagery guidelines from `company_branding.md`.",
            tags=['visual', 'design', 'palette', 'composition'],
            examples=[
                'Translate the brand palette into a prompt for a hero illustration',
                'Advise on lighting and depth for a LinkedIn carousel background',
                'Recommend iconography and layout for a landing page hero graphic',
                'Evaluate a storyboard concept for adherence to brand mood and colors'
            ],
        ),
        AgentSkill(
            id='brand_voice_copywriting',
            name='Brand Voice Copywriting',
            description="Draft or refine copy so it reflects the confident, professional, forward-looking voice defined in the branding guide.",
            tags=['copywriting', 'voice', 'tone', 'editing'],
            examples=[
                'Rewrite social captions to emphasize calm confidence and innovation',
                'Transform a technical paragraph into on-brand website copy',
                'Craft CTA variations that stay within voice and typography rules',
                'Edit onboarding email copy to remove off-brand phrasing'
            ],
        ),
        AgentSkill(
            id='generative_prompt_engineering',
            name='Generative Prompt Engineering',
            description="Create positive and negative prompts for image/video generation that encode brand palette, lighting, typography, and prohibited elements.",
            tags=['prompt', 'imaging', 'ai-art', 'guidelines'],
            examples=[
                'Draft a stable diffusion prompt for a brand-aligned product hero image',
                'Provide Midjourney prompt + negatives for a futuristic workspace scene',
                'Generate prompt variants for thumbnails following brand composition rules',
                'Audit an existing AI prompt and adjust it to match company branding'
            ],
        ),
        AgentSkill(
            id='brand_review_feedback',
            name='Brand Review & QA',
            description="Evaluate supplied copy, prompts, or visuals and document brand compliance gaps with actionable corrections.",
            tags=['review', 'qa', 'compliance', 'feedback'],
            examples=[
                'Assess a video script for voice consistency and suggest edits',
                'Flag off-brand colors in a design mock and propose replacements',
                'Provide a brand compliance checklist for a cross-channel campaign',
                'Summarize risks before publishing content created by external partners'
            ],
        ),
    ]

def create_a2a_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Create A2A server application for the Azure Foundry Branding & Content agent."""
    global agent_executor_instance

    # Define agent skills for branding and content orchestration
    skills = _build_branding_skills()

    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST

    agent_card = AgentCard(
        name='AI Foundry Branding & Content Agent',
        description="An intelligent branding partner powered by Azure AI Foundry. Delivers on-brand messaging, visual direction, and creative prompts grounded in the Company Branding Guide.",
        url=resolve_agent_url(resolved_host_for_url, port),
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities={"streaming": True},
        skills=skills,
    )

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
        return PlainTextResponse('AI Foundry Branding & Content Agent is running!')
    
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
    print(f"Starting AI Foundry Branding & Content Agent A2A server on {host}:{port}...")
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
    """Get response from the Azure Foundry Branding & Content agent for the Gradio UI."""
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
        
        # Send a status update
        yield gr.ChatMessage(
            role="assistant",
            content="📏 **Reviewing your loss details and building an estimate...**",
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
                        "reviewing your loss", "📏 reviewing"
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
                content="I reviewed the loss details but need more information to produce an estimate. Please share additional inspection findings or costs."
            )
            
    except Exception as e:
        logger.error(f"Error in get_foundry_response (Type: {type(e)}): {e}")
        traceback.print_exc()
        yield gr.ChatMessage(
            role="assistant",
            content=f"An error occurred while processing your request: {str(e)}. Please check the server logs for details.",
        )


async def launch_ui(host: str = "0.0.0.0", ui_port: int = DEFAULT_UI_PORT, a2a_port: int = DEFAULT_PORT):
    """Launch Gradio UI and A2A server simultaneously for the assessment agent."""
    print("Starting AI Foundry Branding & Content Agent with both UI and A2A server...")
    
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

    # Initialize assessment agents at startup BEFORE starting servers
    print("🚀 Initializing AI Foundry Branding agent at startup...")
    try:
        await initialize_foundry_branding_agents_at_startup()
        print("✅ Branding agent initialization completed successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize branding agent at startup: {e}")
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
    
    # Start background registration for UI mode
    skills = _build_branding_skills()

    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST

    agent_card = AgentCard(
        name='AI Foundry Branding & Content Agent',
        description="An intelligent branding partner powered by Azure AI Foundry. Provides on-brand messaging, visual direction, and creative prompts grounded in the Company Branding Guide.",
        url=resolve_agent_url(resolved_host_for_url, a2a_port),
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities={"streaming": True},
        skills=skills,
    )
    
    # Start background registration
    start_background_registration(agent_card)

    def check_system_status():
        """Check system status for the Branding Agent."""
        return "✅ **Status:** Branding Agent Ready – Share your campaign goals, assets, or prompts for on-brand guidance!"

    display_host = resolved_host_for_url
    ui_display_url = f"http://{display_host}:{ui_port}"
    a2a_display_url = resolve_agent_url(display_host, a2a_port).rstrip('/')

    with gr.Blocks(theme=gr.themes.Ocean(), title="AI Foundry Branding & Content Agent") as demo:
        gr.Image(
            "static/a2a.png",
            width=100,
            height=100,
            scale=0,
            show_label=False,
            show_download_button=False,
            container=False,
            show_fullscreen_button=False,
        )
        gr.Markdown(f"""
        ## 🎨 AI Foundry Branding & Content Agent

        **Direct UI Access:** {ui_display_url}  
        **A2A API Access:** {a2a_display_url}

        **What it does:**
        - Grounds every decision in `documents/company_branding.md`
        - Translates briefs into on-brand copy, prompts, and visual direction
        - Reviews supplied assets for tone, visuals, and compliance gaps

        ### Core Capabilities
        - Brand strategy alignment & messaging pillars
        - Visual identity direction (palette, lighting, composition)
        - Brand voice copywriting and editorial refinement
        - Generative prompt engineering with positive/negative cues
        - Brand QA with actionable feedback and checklists
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
                print("[Branding UI] Latest file references from host agent:")
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
            description="Share campaign goals, draft copy, or visual needs and I'll deliver on-brand messaging, prompts, and review notes.",
            examples=[
                "Draft LinkedIn carousel copy and art direction for our AI automation launch.",
                "Review this hero headline and rewrite it to match our brand voice.",
                "Create a generative image prompt for a futuristic workspace in brand colors.",
                "Audit this video script for tone alignment and suggest adjustments.",
                "Summarize the key branding rules we must follow for a webinar invite."
            ],
        )

    print(f"Launching AI Foundry Branding & Content Agent Gradio interface on {host}:{ui_port}...")
    demo.queue().launch(
        server_name=host,
        server_port=ui_port,
    )
    print("AI Foundry Branding & Content Agent Gradio application has been shut down.")


def main(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Launch A2A server mode for the Azure Foundry Branding & Content agent with startup initialization."""
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

    # Initialize branding agent at startup BEFORE starting server
    print("🚀 Initializing AI Foundry Branding agent at startup...")
    try:
        asyncio.run(initialize_foundry_branding_agents_at_startup())
        print("✅ Branding agent initialization completed successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize branding agent at startup: {e}")
        raise

    print(f"Starting AI Foundry Branding & Content Agent A2A server on {host}:{port}...")
    app = create_a2a_server(host, port)
    
    # Create agent card for registration
    skills = _build_branding_skills()

    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST

    agent_card = AgentCard(
        name='AI Foundry Branding & Content Agent',
        description="An intelligent branding partner powered by Azure AI Foundry. Provides on-brand messaging, visual direction, and creative prompts grounded in the Company Branding Guide.",
        url=resolve_agent_url(resolved_host_for_url, port),
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities={"streaming": True},
        skills=skills,
    )
    
    # Start background registration
    start_background_registration(agent_card)
    
    uvicorn.run(app, host=host, port=port)


@click.command()
@click.option('--host', 'host', default=DEFAULT_HOST, help='Host to bind to')
@click.option('--port', 'port', default=DEFAULT_PORT, help='Port for A2A server')
@click.option('--ui', is_flag=True, help='Launch Gradio UI (also runs A2A server)')
@click.option('--ui-port', 'ui_port', default=DEFAULT_UI_PORT, help='Port for Gradio UI (only used with --ui flag)')
def cli(host: str, port: int, ui: bool, ui_port: int):
    """AI Foundry Branding & Content Agent - run as an A2A server or with Gradio UI + A2A server."""
    if ui:
        asyncio.run(launch_ui(host, ui_port, port))
    else:
        main(host, port)


if __name__ == '__main__':
    cli()
