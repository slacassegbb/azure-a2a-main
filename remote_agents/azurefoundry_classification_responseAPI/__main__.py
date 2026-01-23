import asyncio
import logging
import os
import traceback
from collections.abc import AsyncIterator
import threading

import click
import gradio as gr
import uvicorn

from foundry_agent_executor import create_foundry_agent_executor, initialize_foundry_classification_agents_at_startup
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
            logger.warning("Invalid A2A_PORT value '%s'; defaulting to 8001", raw_port)
    return 8001


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

# Updated ports to avoid conflicts with both azurefoundry_SN and azurefoundry_Deep_Search agents
DEFAULT_HOST = _resolve_default_host()
DEFAULT_PORT = _resolve_default_port()  # Changed from 10009 to avoid conflict
DEFAULT_UI_PORT = 8089  # Changed from 8087 to avoid conflict

# UI Configuration - Updated for Classification Triage agent
# Global reference to the agent executor to check for pending tasks
agent_executor_instance = None

HOST_AGENT_URL = _normalize_env_value(get_host_agent_url())


def create_a2a_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Create A2A server application for Azure Foundry Classification Triage agent."""
    global agent_executor_instance
    
    # Define agent skills for classification and triage support
    skills = [
        AgentSkill(
            id='incident_classification',
            name='Incident Classification',
            description="Classify customer incidents into categories such as Fraud, Technical Issues, Payment Issues, Card Issues, Account Services, Security, and Inquiries",
            tags=['classification', 'incident', 'triage', 'categorization'],
            examples=[
                'I lost my card while traveling',
                'There is an unauthorized charge on my account',
                'I cannot log into my banking app',
                'My payment failed to go through'
            ],
        ),
        AgentSkill(
            id='priority_assessment',
            name='Priority Assessment',
            description="Determine urgency, impact, and priority levels for incidents using ServiceNow standard mapping",
            tags=['priority', 'urgency', 'impact', 'assessment', 'servicenow'],
            examples=[
                'Assess priority for fraud incident',
                'Determine urgency for account blocked',
                'Evaluate impact of system outage',
                'Calculate priority matrix for technical issue'
            ],
        ),
        AgentSkill(
            id='routing_triage',
            name='Routing & Triage',
            description="Route incidents to appropriate teams and provide triage recommendations based on classification",
            tags=['routing', 'triage', 'escalation', 'team-assignment'],
            examples=[
                'Route fraud case to security team',
                'Escalate critical payment issue',
                'Assign technical issue to IT support',
                'Triage account service request'
            ],
        ),
        AgentSkill(
            id='field_mapping',
            name='ServiceNow Field Mapping',
            description="Map incident details to proper ServiceNow fields including category, subcategory, description, and metadata",
            tags=['servicenow', 'mapping', 'fields', 'metadata'],
            examples=[
                'Map incident to ServiceNow fields',
                'Generate proper short description',
                'Categorize into subcategory',
                'Create structured ticket data'
            ],
        ),
        AgentSkill(
            id='keyword_analysis',
            name='Keyword Analysis',
            description="Analyze customer messages for classification keywords and context cues to determine incident type",
            tags=['keywords', 'analysis', 'context', 'nlp'],
            examples=[
                'Analyze message for fraud keywords',
                'Identify technical issue indicators',
                'Extract payment problem signals',
                'Detect security concerns'
            ],
        )
    ]

    # Create agent card
    agent_card = AgentCard(
        name='AI Foundry Classification Triage Agent',
        description="An intelligent incident classification and triage agent powered by Azure AI Foundry. Specializes in analyzing customer issues, classifying incidents into proper categories, assessing priority levels, and routing cases to appropriate teams using ServiceNow standards.",
        #url=f'http://{host}:{port}/',
        #url=f'https://agent1.ngrok.app/agent2/',
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
        return PlainTextResponse('AI Foundry Insurance Classification Agent is running!')
    
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
    print(f"Starting AI Foundry Classification Triage Agent A2A server on {host}:{port}...")
    app = create_a2a_server(host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


async def register_agent_with_host(agent_card):
    """Register this agent with the host agent after startup."""
    if SELF_REGISTRATION_AVAILABLE:
        # Wait a moment for server to fully start
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


async def get_foundry_response(
    message: str,
    _history: list[gr.ChatMessage],
) -> AsyncIterator[gr.ChatMessage]:
    """Get response from Azure Foundry Classification Triage agent for Gradio UI."""
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
            content="🎯 **Analyzing and classifying your incident...**",
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
                        "analyzing and classifying", "🎯 analyzing"
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
                content="I analyzed your message but couldn't classify it properly. Please provide more details about your issue or try describing it differently."
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
    print("Starting AI Foundry Classification Triage Agent with both UI and A2A server...")
    
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

    # Initialize classification agents at startup BEFORE starting servers
    print("🚀 Initializing AI Foundry Classification agents at startup...")
    try:
        await initialize_foundry_classification_agents_at_startup()
        print("✅ Classification agent initialization completed successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize classification agents at startup: {e}")
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
            id='incident_classification',
            name='Incident Classification',
            description="Classify customer incidents into categories such as Fraud, Technical Issues, Payment Issues, Card Issues, Account Services, Security, and Inquiries",
            tags=['classification', 'incident', 'triage', 'categorization'],
            examples=[
                'I lost my card while traveling',
                'There is an unauthorized charge on my account',
                'I cannot log into my banking app',
                'My payment failed to go through'
            ],
        ),
        AgentSkill(
            id='priority_assessment',
            name='Priority Assessment',
            description="Determine urgency, impact, and priority levels for incidents using ServiceNow standard mapping",
            tags=['priority', 'urgency', 'impact', 'assessment', 'servicenow'],
            examples=[
                'Assess priority for fraud incident',
                'Determine urgency for account blocked',
                'Evaluate impact of system outage',
                'Calculate priority matrix for technical issue'
            ],
        ),
        AgentSkill(
            id='routing_triage',
            name='Routing & Triage',
            description="Route incidents to appropriate teams and provide triage recommendations based on classification",
            tags=['routing', 'triage', 'escalation', 'team-assignment'],
            examples=[
                'Route fraud case to security team',
                'Escalate critical payment issue',
                'Assign technical issue to IT support',
                'Triage account service request'
            ],
        ),
        AgentSkill(
            id='field_mapping',
            name='ServiceNow Field Mapping',
            description="Map incident details to proper ServiceNow fields including category, subcategory, description, and metadata",
            tags=['servicenow', 'mapping', 'fields', 'metadata'],
            examples=[
                'Map incident to ServiceNow fields',
                'Generate proper short description',
                'Categorize into subcategory',
                'Create structured ticket data'
            ],
        ),
        AgentSkill(
            id='keyword_analysis',
            name='Keyword Analysis',
            description="Analyze customer messages for classification keywords and context cues to determine incident type",
            tags=['keywords', 'analysis', 'context', 'nlp'],
            examples=[
                'Analyze message for fraud keywords',
                'Identify technical issue indicators',
                'Extract payment problem signals',
                'Detect security concerns'
            ],
        )
    ]

    agent_card = AgentCard(
        name='AI Foundry Classification Triage Agent',
        description="An intelligent incident classification and triage agent powered by Azure AI Foundry. Specializes in analyzing customer issues, classifying incidents into proper categories, assessing priority levels, and routing cases to appropriate teams using ServiceNow standards.",
        #url=f'http://{host if host != "0.0.0.0" else DEFAULT_HOST}:{a2a_port}/',
        #url=f'https://agent1.ngrok.app/agent2/',
        url=resolve_agent_url(host, a2a_port),
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities=AgentCapabilities(streaming=True),
        skills=skills,
    )
    
    # Start background registration
    start_background_registration(agent_card)

    def check_system_status():
        """Check system status for the Classification Triage Agent."""
        return "✅ **Status:** Classification Triage Agent Ready - Send me incidents to classify and route!"

    with gr.Blocks(theme=gr.themes.Ocean(), title="AI Foundry Classification Triage Agent") as demo:
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
        display_host = host if host != "0.0.0.0" else DEFAULT_HOST
        ui_display_url = f"http://{display_host}:{ui_port}"
        a2a_display_url = resolve_agent_url(display_host, a2a_port).rstrip('/')
        gr.Markdown(f"""
        ## 🎯 AI Foundry Classification Triage Agent
        
        **Direct UI Access:** {ui_display_url}  
        **A2A API Access:** {a2a_display_url}
        
        **Incident Classification & Triage:** This agent specializes in analyzing and classifying customer incidents using ServiceNow standards:
        
        ### 📋 **Classification Categories:**
        - **Fraud** - Unauthorized transactions, phishing, account takeover
        - **Technical Issues** - App/website problems, login failures, system errors
        - **Payment Issues** - Failed payments, delayed transfers, ATM errors
        - **Card Issues** - Lost/stolen cards, blocked cards, declined transactions  
        - **Account Services** - Address changes, credit requests, account closure
        - **Security** - Compromised accounts, suspicious activity, credential issues
        - **Inquiries** - General questions, fee explanations, product information
        
        ### ⚡ **Priority Assessment:**
        Automatically determines urgency, impact, and priority levels using ServiceNow matrix.
        
        Send me any customer incident and I'll classify, prioritize, and route it appropriately!
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
            description="Send me any customer incident and I'll analyze, classify, and provide triage recommendations with proper ServiceNow field mappings.",
            examples=[
                "I lost my credit card while traveling in Europe",
                "There's an unauthorized charge of $500 on my account from yesterday",
                "I can't log into my mobile banking app - it keeps saying invalid credentials",
                "My wire transfer to Canada was supposed to arrive 3 days ago but still hasn't",
                "Someone called claiming to be from the bank asking for my password",
                "ATM dispensed no cash but charged my account $200"
            ],
        )

    print(f"Launching AI Foundry Classification Triage Agent Gradio interface on {host}:{ui_port}...")
    demo.queue().launch(
        server_name=host,
        server_port=ui_port,
    )
    print("AI Foundry Classification Triage Agent Gradio application has been shut down.")


def main(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Launch A2A server mode for Azure Foundry Classification Triage agent with startup initialization."""
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

    # Initialize classification agents at startup BEFORE starting server
    print("🚀 Initializing AI Foundry Classification agents at startup...")
    try:
        asyncio.run(initialize_foundry_classification_agents_at_startup())
        print("✅ Classification agent initialization completed successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize classification agents at startup: {e}")
        raise

    print(f"Starting AI Foundry Classification Triage Agent A2A server on {host}:{port}...")
    app = create_a2a_server(host, port)
    
    # Create agent card for registration
    skills = [
        AgentSkill(
            id='incident_classification',
            name='Incident Classification',
            description="Classify customer incidents into categories such as Fraud, Technical Issues, Payment Issues, Card Issues, Account Services, Security, and Inquiries",
            tags=['classification', 'incident', 'triage', 'categorization'],
            examples=[
                'I lost my card while traveling',
                'There is an unauthorized charge on my account',
                'I cannot log into my banking app',
                'My payment failed to go through'
            ],
        ),
        AgentSkill(
            id='priority_assessment',
            name='Priority Assessment',
            description="Determine urgency, impact, and priority levels for incidents using ServiceNow standard mapping",
            tags=['priority', 'urgency', 'impact', 'assessment', 'servicenow'],
            examples=[
                'Assess priority for fraud incident',
                'Determine urgency for account blocked',
                'Evaluate impact of system outage',
                'Calculate priority matrix for technical issue'
            ],
        ),
        AgentSkill(
            id='routing_triage',
            name='Routing & Triage',
            description="Route incidents to appropriate teams and provide triage recommendations based on classification",
            tags=['routing', 'triage', 'escalation', 'team-assignment'],
            examples=[
                'Route fraud case to security team',
                'Escalate critical payment issue',
                'Assign technical issue to IT support',
                'Triage account service request'
            ],
        ),
        AgentSkill(
            id='field_mapping',
            name='ServiceNow Field Mapping',
            description="Map incident details to proper ServiceNow fields including category, subcategory, description, and metadata",
            tags=['servicenow', 'mapping', 'fields', 'metadata'],
            examples=[
                'Map incident to ServiceNow fields',
                'Generate proper short description',
                'Categorize into subcategory',
                'Create structured ticket data'
            ],
        ),
        AgentSkill(
            id='keyword_analysis',
            name='Keyword Analysis',
            description="Analyze customer messages for classification keywords and context cues to determine incident type",
            tags=['keywords', 'analysis', 'context', 'nlp'],
            examples=[
                'Analyze message for fraud keywords',
                'Identify technical issue indicators',
                'Extract payment problem signals',
                'Detect security concerns'
            ],
        )
    ]

    agent_card = AgentCard(
        name='AI Foundry Classification Triage Agent',
        description="An intelligent incident classification and triage agent powered by Azure AI Foundry. Specializes in analyzing customer issues, classifying incidents into proper categories, assessing priority levels, and routing cases to appropriate teams using ServiceNow standards.",
        #url=f'http://{host}:{port}/',
        #url=f'https://agent1.ngrok.app/agent2/',
        url=resolve_agent_url(host, port),
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
    """AI Foundry Classification Triage Agent - can run as A2A server or with Gradio UI + A2A server."""
    if ui:
        asyncio.run(launch_ui(host, ui_port, port))
    else:
        main(host, port)


if __name__ == '__main__':
    cli()
