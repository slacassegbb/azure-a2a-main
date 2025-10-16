import asyncio
import logging
import os
import traceback
from collections.abc import AsyncIterator
from pprint import pformat
import threading

import click
import gradio as gr
import uvicorn

from foundry_agent_executor import create_foundry_agent_executor
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import self-registration utility
try:
    from utils.self_registration import register_with_host_agent
    SELF_REGISTRATION_AVAILABLE = True
    logger.info("✅ Self-registration utility loaded")
except ImportError:
    # Fallback if utils not available
    async def register_with_host_agent(agent_card, host_url=None):
        logger.info("ℹ️ Self-registration utility not available - skipping registration")
        return False
    SELF_REGISTRATION_AVAILABLE = False

DEFAULT_HOST = 'localhost'
DEFAULT_PORT = 8000
DEFAULT_UI_PORT = 8085

# UI Configuration
APP_NAME = "foundry_expert_app"
USER_ID = "default_user"
SESSION_ID = "default_session"

# Global reference to the agent executor to check for pending tasks
agent_executor_instance = None

# Global state for UI notifications
pending_request_notification = {"has_pending": False, "request_text": "", "context_id": ""}

CITIBANK_HOST_AGENT_URL = "https://citibank-host-agent.whiteplant-4c581c75.canadaeast.azurecontainerapps.io"


def create_a2a_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Create A2A server application for Azure Foundry agent."""
    global agent_executor_instance
    
    # Define agent skills
    skills = [
        AgentSkill(
            id='servicenow_management',
            name='ServiceNow Management',
            description="Create, search, and manage ServiceNow incidents, users, and knowledge base articles. Simulates ServiceNow actions with realistic synthetic data.",
            tags=['servicenow', 'incident', 'it', 'support'],
            examples=[
                'Create a new ServiceNow incident',
                'Search for incidents assigned to a user',
                'Update incident status',
                'List ServiceNow users',
                'Search ServiceNow knowledge base'
            ],
        ),
        AgentSkill(
            id='citibank_actions',
            name='Citi Bank Actions',
            description="Simulate any action on the Citi Bank system (block card, check balance, report fraud, etc.) and return synthetic responses.",
            tags=['citibank', 'banking', 'finance', 'card'],
            examples=[
                'Block a credit card',
                'Check account balance',
                'Report a fraudulent transaction',
                'Simulate a generic Citi Bank action'
            ],
        ),
        AgentSkill(
            id='web_search',
            name='Web Search',
            description="Search the web for current information using Bing or other integrated search tools.",
            tags=['web', 'search', 'bing', 'internet'],
            examples=[
                'Find the latest news about a company',
                'Search for troubleshooting steps online',
                'Get current weather information'
            ],
        ),
        AgentSkill(
            id='file_knowledge_search',
            name='File & Knowledge Search',
            description="Search through uploaded documents, files, and knowledge bases for specific information.",
            tags=['file', 'document', 'knowledge', 'search'],
            examples=[
                'Search uploaded PDF for a keyword',
                'Find information in a user manual',
                'Extract data from a document'
            ],
        )
    ]

    # Create agent card
    agent_card = AgentCard(
        name='ServiceNow, CitiBank, Web & Knowledge Agent',
        description="An intelligent agent specialized in ServiceNow management, Citi Bank system actions, web search, and file/knowledge/document search. Can simulate ServiceNow incidents, users, and knowledge base operations, perform any Citi Bank action (block card, check balance, report fraud, etc.), search the web for current information, and search through uploaded documents/files for specific information, all with realistic synthetic responses.",
       # url=f'http://{host}:{port}/',
        #url=f'https://agent1.ngrok.app/agent1/',
        url=f'http://localhost:8000/',
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
    async def health_check(request: Request) -> PlainTextResponse:
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
            logger.info(f"🤝 Attempting to register '{agent_card.name}' with host agent...")
            registration_success = await register_with_host_agent(agent_card, host_url=CITIBANK_HOST_AGENT_URL)
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
    history: list[gr.ChatMessage],
) -> AsyncIterator[gr.ChatMessage]:
    """Get response from Azure Foundry agent for Gradio UI."""
    global agent_executor_instance
    try:
        # Check if there are pending input_required tasks (user is responding to a request)
        if agent_executor_instance and agent_executor_instance._waiting_for_input:
            # Get the first pending task (in a real system, you might want to be more specific)
            context_id = next(iter(agent_executor_instance._waiting_for_input.keys()))
            request_text = agent_executor_instance._waiting_for_input[context_id]
            
            # If the user message is just checking for requests
            if message.lower().strip() in ["", "status", "check", "pending"] or len(message.strip()) == 0:
                yield gr.ChatMessage(
                    role="assistant",
                    content=f"🤖 **Pending Host Agent Request:**\n\n{request_text}\n\n*Please provide your expert response by typing your answer below.*"
                )
                return
            
            # This is the human expert's response
            yield gr.ChatMessage(
                role="assistant",
                content=f"✅ **Sending your response to Host Agent...**\n\nExpert Response: \"{message}\""
            )
            
            # Send the human response to complete the waiting task
            success = await agent_executor_instance.send_human_response(context_id, message)
            
            if success:
                yield gr.ChatMessage(
                    role="assistant",
                    content="✅ **Response sent successfully!** The Host Agent has received your expert input and will continue processing."
                )
                # Clear the pending request notification
                global pending_request_notification
                pending_request_notification = {"has_pending": False, "request_text": "", "context_id": ""}
            else:
                yield gr.ChatMessage(
                    role="assistant",
                    content="❌ **Error:** Could not send response to Host Agent. The task may have expired."
                )
            
            return
        
        # Regular foundry agent interaction
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
            content="🤖 **Processing your request...**",
        )
        
        # Run the conversation using the streaming method
        response_count = 0
        async for response in foundry_agent.run_conversation_stream(thread_id, message):
            print("[DEBUG] get_foundry_response: response=", response)
            if isinstance(response, str):
                if response.strip():
                    # Filter out processing messages
                    if not any(phrase in response.lower() for phrase in [
                        "processing your request", "🤖 processing", "processing..."
                    ]):
                        yield gr.ChatMessage(role="assistant", content=response)
                        response_count += 1
            else:
                # handle other types if needed
                print(f"[DEBUG] get_foundry_response: Unexpected response type: {type(response)}")
                yield gr.ChatMessage(
                    role="assistant",
                    content=f"An error occurred while processing your request: {str(response)}. Please check the server logs for details.",
                )
                response_count += 1
        
        # If no responses were yielded, show a default message
        if response_count == 0:
            yield gr.ChatMessage(
                role="assistant", 
                content="I processed your request but didn't receive a response. Please try again."
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
    print("Starting AI Foundry Expert Agent with both UI and A2A server...")
    
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
            id='servicenow_management',
            name='ServiceNow Management',
            description="Create, search, and manage ServiceNow incidents, users, and knowledge base articles. Simulates ServiceNow actions with realistic synthetic data.",
            tags=['servicenow', 'incident', 'it', 'support'],
            examples=[
                'Create a new ServiceNow incident',
                'Search for incidents assigned to a user',
                'Update incident status',
                'List ServiceNow users',
                'Search ServiceNow knowledge base'
            ],
        ),
        AgentSkill(
            id='citibank_actions',
            name='Citi Bank Actions',
            description="Simulate any action on the Citi Bank system (block card, check balance, report fraud, etc.) and return synthetic responses.",
            tags=['citibank', 'banking', 'finance', 'card'],
            examples=[
                'Block a credit card',
                'Check account balance',
                'Report a fraudulent transaction',
                'Simulate a generic Citi Bank action'
            ],
        ),
        AgentSkill(
            id='web_search',
            name='Web Search',
            description="Search the web for current information using Bing or other integrated search tools.",
            tags=['web', 'search', 'bing', 'internet'],
            examples=[
                'Find the latest news about a company',
                'Search for troubleshooting steps online',
                'Get current weather information'
            ],
        ),
        AgentSkill(
            id='file_knowledge_search',
            name='File & Knowledge Search',
            description="Search through uploaded documents, files, and knowledge bases for specific information.",
            tags=['file', 'document', 'knowledge', 'search'],
            examples=[
                'Search uploaded PDF for a keyword',
                'Find information in a user manual',
                'Extract data from a document'
            ],
        )
    ]

    agent_card = AgentCard(
        name='ServiceNow, CitiBank, Web & Knowledge Agent',
        description="An intelligent agent specialized in ServiceNow management, Citi Bank system actions, web search, and file/knowledge/document search. Can simulate ServiceNow incidents, users, and knowledge base operations, perform any Citi Bank action (block card, check balance, report fraud, etc.), search the web for current information, and search through uploaded documents/files for specific information, all with realistic synthetic responses.",
        #url=f'http://{host if host != "0.0.0.0" else DEFAULT_HOST}:{a2a_port}/',
        #url=f'https://agent1.ngrok.app/agent1/',
        url=f'http://localhost:8000/',
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities=AgentCapabilities(streaming=True),
        skills=skills,
    )
    
    # Start background registration
    start_background_registration(agent_card)

    def check_pending_requests():
        """Check for pending expert requests."""
        if agent_executor_instance and agent_executor_instance._waiting_for_input:
            context_id = next(iter(agent_executor_instance._waiting_for_input.keys()))
            request_text = agent_executor_instance._waiting_for_input[context_id]
            return f"""
## 🚨 URGENT: PENDING REQUEST FROM HOST AGENT

**Request:** {request_text}

**Action Required:** Please respond in the chat below to provide your expert input.

---
"""
        return "✅ **Status:** No pending requests - Ready for new expert consultations"

    with gr.Blocks(theme=gr.themes.Ocean(), title="AI Foundry Expert Agent") as demo:
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
        ## 🤖 AI Foundry Expert Agent
        
        **Direct UI Access:** http://localhost:{ui_port}  
        **A2A API Access:** http://localhost:{a2a_port}
        
        **Expert Consultation Mode:** This agent can receive requests from other agents that require human expert input.
        When you see a "Host Agent Request", please provide your expert analysis or response.
        """)
        
        # Add a status display that refreshes automatically
        with gr.Row():
            status_display = gr.Markdown(value=check_pending_requests())
            refresh_btn = gr.Button("🔄 Refresh Status", size="sm")
            refresh_btn.click(fn=check_pending_requests, outputs=status_display)
        
        # Set up automatic refresh using timer (every 2 seconds)
        timer = gr.Timer(2)
        timer.tick(fn=check_pending_requests, outputs=status_display)
        
        # Add a hidden component that triggers refresh via JavaScript
        refresh_timer = gr.HTML("""
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
        
        chat_interface = gr.ChatInterface(
            get_foundry_response,
            title="",  # Title is now in markdown above
            description="Ask me questions directly, or respond to expert consultation requests from other agents.",
            examples=[
                "What's my schedule for today?",
                "Help me optimize my calendar",
                "Provide expert analysis on this scenario",
                "Check for pending requests"
            ],
        )

    print(f"Launching AI Foundry Expert Agent Gradio interface on {host}:{ui_port}...")
    demo.queue().launch(
        server_name=host,
        server_port=ui_port,
    )
    print("AI Foundry Expert Agent Gradio application has been shut down.")


def main(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Launch A2A server mode for Azure Foundry agent."""
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

    print(f"Starting AI Foundry Expert Agent A2A server on {host}:{port}...")
    app = create_a2a_server(host, port)
    
    # Create agent card for registration
    skills = [
        AgentSkill(
            id='servicenow_management',
            name='ServiceNow Management',
            description="Create, search, and manage ServiceNow incidents, users, and knowledge base articles. Simulates ServiceNow actions with realistic synthetic data.",
            tags=['servicenow', 'incident', 'it', 'support'],
            examples=[
                'Create a new ServiceNow incident',
                'Search for incidents assigned to a user',
                'Update incident status',
                'List ServiceNow users',
                'Search ServiceNow knowledge base'
            ],
        ),
        AgentSkill(
            id='citibank_actions',
            name='Citi Bank Actions',
            description="Simulate any action on the Citi Bank system (block card, check balance, report fraud, etc.) and return synthetic responses.",
            tags=['citibank', 'banking', 'finance', 'card'],
            examples=[
                'Block a credit card',
                'Check account balance',
                'Report a fraudulent transaction',
                'Simulate a generic Citi Bank action'
            ],
        ),
        AgentSkill(
            id='web_search',
            name='Web Search',
            description="Search the web for current information using Bing or other integrated search tools.",
            tags=['web', 'search', 'bing', 'internet'],
            examples=[
                'Find the latest news about a company',
                'Search for troubleshooting steps online',
                'Get current weather information'
            ],
        ),
        AgentSkill(
            id='file_knowledge_search',
            name='File & Knowledge Search',
            description="Search through uploaded documents, files, and knowledge bases for specific information.",
            tags=['file', 'document', 'knowledge', 'search'],
            examples=[
                'Search uploaded PDF for a keyword',
                'Find information in a user manual',
                'Extract data from a document'
            ],
        )
    ]

    agent_card = AgentCard(
        name='ServiceNow, CitiBank, Web & Knowledge Agent',
        description="An intelligent agent specialized in ServiceNow management, Citi Bank system actions, web search, and file/knowledge/document search. Can simulate ServiceNow incidents, users, and knowledge base operations, perform any Citi Bank action (block card, check balance, report fraud, etc.), search the web for current information, and search through uploaded documents/files for specific information, all with realistic synthetic responses.",
        #url=f'http://{host}:{port}/',
        #url=f'https://agent1.ngrok.app/agent1/',
        url=f'http://localhost:8000/',
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
    """AI Foundry Expert Agent - can run as A2A server or with Gradio UI + A2A server."""
    if ui:
        asyncio.run(launch_ui(host, ui_port, port))
    else:
        main(host, port)


if __name__ == '__main__':
    cli()
