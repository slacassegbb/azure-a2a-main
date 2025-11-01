import asyncio
import logging
import os
import traceback
from collections.abc import AsyncIterator
import threading

import click
import gradio as gr
import uvicorn

from foundry_agent_executor import create_foundry_agent_executor, initialize_foundry_deep_search_agents_at_startup
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
            logger.warning("Invalid A2A_PORT value '%s'; defaulting to 8002", raw_port)
    return 8002


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

# Updated ports to avoid conflicts with azurefoundry_SN agent
DEFAULT_HOST = _resolve_default_host()
DEFAULT_PORT = _resolve_default_port()  # Changed from 10007 to avoid conflict
DEFAULT_UI_PORT = 8087  # Changed from 8085 to avoid conflict

HOST_AGENT_URL = _normalize_env_value(get_host_agent_url())

# Global reference to the agent executor to check for pending tasks
agent_executor_instance = None

def create_a2a_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Create A2A server application for Azure Foundry Deep Search Knowledge agent."""
    global agent_executor_instance
    
    # Define agent skills for deep search knowledge support
    skills = [
        AgentSkill(
            id='document_search',
            name='Document Search',
            description="Deep search through customer support documents including account management, billing, payments, complaints, and technical support",
            tags=['search', 'documents', 'knowledge-base', 'customer-support'],
            examples=[
                'How do I close my account?',
                'What are the fees for wire transfers?',
                'How to dispute a charge on my account?',
                'What do I do if I suspect fraud on my card?'
            ],
        ),
        AgentSkill(
            id='account_support',
            name='Account Support',
            description="Comprehensive support for account opening, closure, and management procedures",
            tags=['account', 'opening', 'closure', 'management'],
            examples=[
                'Steps to open a new account',
                'Account closure procedures',
                'Required documents for account setup',
                'Account management best practices'
            ],
        ),
        AgentSkill(
            id='billing_payments',
            name='Billing & Payments',
            description="Information about billing, payments, fees, and charges",
            tags=['billing', 'payments', 'fees', 'charges'],
            examples=[
                'Understanding monthly fees',
                'Payment methods and options',
                'How to set up automatic payments',
                'Fee schedule and billing cycle information'
            ],
        ),
        AgentSkill(
            id='fraud_security',
            name='Fraud & Security',
            description="Guidance on fraud prevention, unauthorized transactions, and security measures",
            tags=['fraud', 'security', 'unauthorized', 'protection'],
            examples=[
                'What to do if my card is stolen',
                'Reporting unauthorized transactions',
                'Security features and protections',
                'Fraud prevention tips'
            ],
        ),
        AgentSkill(
            id='technical_support',
            name='Technical Support',
            description="Online banking, mobile app, and technical assistance",
            tags=['technical', 'online-banking', 'mobile', 'troubleshooting'],
            examples=[
                'Online banking login issues',
                'Mobile app troubleshooting',
                'Password reset procedures',
                'Technical feature guidance'
            ],
        )
    ]

    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST

    # Create agent card
    agent_card = AgentCard(
        name='AI Foundry Deep Search Knowledge Agent',
        description="An intelligent customer support agent powered by Azure AI Foundry with deep search capabilities through comprehensive support documentation covering account management, billing, payments, fraud protection, and technical support.",
        #url=f'http://{host}:{port}/',
        #url=f'https://agent1.ngrok.app/agent3/',
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
    async def health_check(_: Request) -> PlainTextResponse:
        return PlainTextResponse('AI Foundry Deep Search Agent is running!')
    
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
    print(f"Starting AI Foundry Deep Search Knowledge Agent A2A server on {host}:{port}...")
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
    """Get response from Azure Foundry Deep Search Knowledge agent for Gradio UI."""
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
            content="🔍 **Searching knowledge base and processing your request...**",
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
                        "searching knowledge base", "🔍 searching"
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
                content="I searched through the knowledge base but didn't find a specific answer to your question. Please try rephrasing your question or ask about a different topic."
            )
            
    except Exception as e:
        logger.error(f"Error in get_foundry_response (Type: {type(e)}): {e}")
        traceback.print_exc()
        yield gr.ChatMessage(
            role="assistant",
            content=f"An error occurred while processing your request: {str(e)}. Please check the server logs for details.",
        )


async def launch_ui(host: str = "0.0.0.0", ui_port: int = DEFAULT_UI_PORT, a2a_port: int = DEFAULT_PORT):
    """Launch Gradio UI and A2A server simultaneously."""
    print("Starting AI Foundry Deep Search Knowledge Agent with both UI and A2A server...")
    
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

    # Initialize deep search agents at startup BEFORE starting servers
    print("🚀 Initializing AI Foundry Deep Search agents at startup...")
    try:
        await initialize_foundry_deep_search_agents_at_startup()
        print("✅ Deep search agent initialization completed successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize deep search agents at startup: {e}")
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
    skills = [
        AgentSkill(
            id='document_search',
            name='Document Search',
            description="Deep search through customer support documents including account management, billing, payments, complaints, and technical support",
            tags=['search', 'documents', 'knowledge-base', 'customer-support'],
            examples=[
                'How do I close my account?',
                'What are the fees for wire transfers?',
                'How to dispute a charge on my account?',
                'What do I do if I suspect fraud on my card?'
            ],
        ),
        AgentSkill(
            id='account_support',
            name='Account Support',
            description="Comprehensive support for account opening, closure, and management procedures",
            tags=['account', 'opening', 'closure', 'management'],
            examples=[
                'Steps to open a new account',
                'Account closure procedures',
                'Required documents for account setup',
                'Account management best practices'
            ],
        ),
        AgentSkill(
            id='billing_payments',
            name='Billing & Payments',
            description="Information about billing, payments, fees, and charges",
            tags=['billing', 'payments', 'fees', 'charges'],
            examples=[
                'Understanding monthly fees',
                'Payment methods and options',
                'How to set up automatic payments',
                'Fee schedule and billing cycle information'
            ],
        ),
        AgentSkill(
            id='fraud_security',
            name='Fraud & Security',
            description="Guidance on fraud prevention, unauthorized transactions, and security measures",
            tags=['fraud', 'security', 'unauthorized', 'protection'],
            examples=[
                'What to do if my card is stolen',
                'Reporting unauthorized transactions',
                'Security features and protections',
                'Fraud prevention tips'
            ],
        ),
        AgentSkill(
            id='technical_support',
            name='Technical Support',
            description="Online banking, mobile app, and technical assistance",
            tags=['technical', 'online-banking', 'mobile', 'troubleshooting'],
            examples=[
                'Online banking login issues',
                'Mobile app troubleshooting',
                'Password reset procedures',
                'Technical feature guidance'
            ],
        )
    ]

    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST

    agent_card = AgentCard(
        name='AI Foundry Deep Search Knowledge Agent',
        description="An intelligent customer support agent powered by Azure AI Foundry with deep search capabilities through comprehensive support documentation covering account management, billing, payments, fraud protection, and technical support.",
        #url=f'http://{host if host != "0.0.0.0" else DEFAULT_HOST}:{a2a_port}/',
        #url=f'https://agent1.ngrok.app/agent3/',
        url=resolve_agent_url(resolved_host_for_url, a2a_port),
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities=AgentCapabilities(streaming=True),
        skills=skills,
    )
    
    # Start background registration
    start_background_registration(agent_card)

    def check_system_status():
        """Check system status for the Deep Search Knowledge Agent."""
        return "✅ **Status:** Deep Search Knowledge Agent Ready - Ask any customer support question!"

    display_host = resolved_host_for_url
    ui_display_url = f"http://{display_host}:{ui_port}"
    a2a_display_url = resolve_agent_url(display_host, a2a_port).rstrip('/')

    with gr.Blocks(theme=gr.themes.Ocean(), title="AI Foundry Deep Search Knowledge Agent") as demo:
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
        ## 📚 AI Foundry Deep Search Knowledge Agent
        
        **Direct UI Access:** {ui_display_url}  
        **A2A API Access:** {a2a_display_url}
        
        **Customer Support Knowledge Base:** This agent provides comprehensive customer support assistance through deep search capabilities across:
        - Account Opening & Closure procedures
        - Billing, Payments & Fee information  
        - Complaint & Dispute Resolution
        - Fraud Prevention & Unauthorized Transaction handling
        - Fund Transfers & Payment processing
        - Technical Support for Online Banking & Mobile Apps
        
        Ask any customer support question and I'll search through the comprehensive documentation to provide accurate answers.
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
        
        gr.ChatInterface(
            get_foundry_response,
            title="",  # Title is now in markdown above
            description="Ask me any customer support question and I'll search through comprehensive documentation to help you.",
            examples=[
                "How do I close my account?",
                "What are the fees for international wire transfers?",
                "I think there's fraud on my account, what should I do?",
                "How do I dispute a charge?",
                "My online banking isn't working, can you help?",
                "What documents do I need to open a new account?"
            ],
        )

    print(f"Launching AI Foundry Deep Search Knowledge Agent Gradio interface on {host}:{ui_port}...")
    demo.queue().launch(
        server_name=host,
        server_port=ui_port,
    )
    print("AI Foundry Deep Search Knowledge Agent Gradio application has been shut down.")


def main(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Launch A2A server mode for Azure Foundry Deep Search Knowledge agent with startup initialization."""
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

    # Initialize deep search agents at startup BEFORE starting server
    print("🚀 Initializing AI Foundry Deep Search agents at startup...")
    try:
        asyncio.run(initialize_foundry_deep_search_agents_at_startup())
        print("✅ Deep search agent initialization completed successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize deep search agents at startup: {e}")
        raise

    print(f"Starting AI Foundry Deep Search Knowledge Agent A2A server on {host}:{port}...")
    app = create_a2a_server(host, port)
    
    # Create agent card for registration
    skills = [
        AgentSkill(
            id='document_search',
            name='Document Search',
            description="Deep search through customer support documents including account management, billing, payments, complaints, and technical support",
            tags=['search', 'documents', 'knowledge-base', 'customer-support'],
            examples=[
                'How do I close my account?',
                'What are the fees for wire transfers?',
                'How to dispute a charge on my account?',
                'What do I do if I suspect fraud on my card?'
            ],
        ),
        AgentSkill(
            id='account_support',
            name='Account Support',
            description="Comprehensive support for account opening, closure, and management procedures",
            tags=['account', 'opening', 'closure', 'management'],
            examples=[
                'Steps to open a new account',
                'Account closure procedures',
                'Required documents for account setup',
                'Account management best practices'
            ],
        ),
        AgentSkill(
            id='billing_payments',
            name='Billing & Payments',
            description="Information about billing, payments, fees, and charges",
            tags=['billing', 'payments', 'fees', 'charges'],
            examples=[
                'Understanding monthly fees',
                'Payment methods and options',
                'How to set up automatic payments',
                'Fee schedule and billing cycle information'
            ],
        ),
        AgentSkill(
            id='fraud_security',
            name='Fraud & Security',
            description="Guidance on fraud prevention, unauthorized transactions, and security measures",
            tags=['fraud', 'security', 'unauthorized', 'protection'],
            examples=[
                'What to do if my card is stolen',
                'Reporting unauthorized transactions',
                'Security features and protections',
                'Fraud prevention tips'
            ],
        ),
        AgentSkill(
            id='technical_support',
            name='Technical Support',
            description="Online banking, mobile app, and technical assistance",
            tags=['technical', 'online-banking', 'mobile', 'troubleshooting'],
            examples=[
                'Online banking login issues',
                'Mobile app troubleshooting',
                'Password reset procedures',
                'Technical feature guidance'
            ],
        )
    ]

    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST

    agent_card = AgentCard(
        name='AI Foundry Deep Search Knowledge Agent',
        description="An intelligent customer support agent powered by Azure AI Foundry with deep search capabilities through comprehensive support documentation covering account management, billing, payments, fraud protection, and technical support.",
        #url=f'http://{host}:{port}/',
        #url=f'https://agent1.ngrok.app/agent3/',
        url=resolve_agent_url(resolved_host_for_url, port),
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities=AgentCapabilities(streaming=True),
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
    """AI Foundry Deep Search Knowledge Agent - can run as A2A server or with Gradio UI + A2A server."""
    if ui:
        asyncio.run(launch_ui(host, ui_port, port))
    else:
        main(host, port)


if __name__ == '__main__':
    cli()
