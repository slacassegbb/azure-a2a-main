import logging
import os
import asyncio
from pathlib import Path

import click

print("[DEBUG] Starting google_adk __main__.py")

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)
from agent import SentimentAnalysisAgent
from agent_executor import SentimentAnalysisAgentExecutor
from dotenv import load_dotenv

# Load the project root .env first so shared secrets are available.
ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ROOT_ENV_PATH, override=False)
# Then allow a local .env next to the agent to override if desired.
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

#CITIBANK_HOST_AGENT_URL = "https://citibank-host-agent.whiteplant-4c581c75.canadaeast.azurecontainerapps.io"
CITIBANK_HOST_AGENT_URL = "http://localhost:12000"
#CITIBANK_HOST_AGENT_URL = "https://contoso-a2a.whiteplant-4c581c75.canadaeast.azurecontainerapps.io"


class MissingAPIKeyError(Exception):
    """Exception for missing API key."""

    pass


# Self-registration function now imported from utils.self_registration


@click.command()
@click.option('--host', default='localhost')
@click.option('--port', default=8003)
def main(host, port):
    try:
        # Check for API key only if Vertex AI is not configured
        if not os.getenv('GOOGLE_GENAI_USE_VERTEXAI') == 'TRUE':
            if not os.getenv('GOOGLE_API_KEY'):
                raise MissingAPIKeyError(
                    'GOOGLE_API_KEY environment variable not set and GOOGLE_GENAI_USE_VERTEXAI is not TRUE.'
                )

        capabilities = AgentCapabilities(streaming=True)
        skill = AgentSkill(
            id='sentiment_analysis',
            name='Sentiment Analysis Tool',
            description='Analyzes the sentiment of a customer given context and personalizes the experience based on sentiment and context.',
            tags=['sentiment', 'analysis', 'personalization'],
            examples=[
                'How does the customer feel about our service?',
                'Analyze the sentiment of this feedback: "I love the new features!"',
                'What is the mood of this message: "I am frustrated with the wait time."',
            ],
        )
        agent_card = AgentCard(
            name='Sentiment Analysis Agent',
            description='This agent determines the sentiment of a customer given context, and personalizes the experience based on sentiment and context.',
            #url=f'http://{host}:{port}/',
            #url=f'https://agent1.ngrok.app/agent4/',
            url=f'http://localhost:8003/',
            version='1.0.0',
            defaultInputModes=SentimentAnalysisAgent.SUPPORTED_CONTENT_TYPES,
            defaultOutputModes=SentimentAnalysisAgent.SUPPORTED_CONTENT_TYPES,
            capabilities=capabilities,
            skills=[skill],
        )
        request_handler = DefaultRequestHandler(
            agent_executor=SentimentAnalysisAgentExecutor(),
            task_store=InMemoryTaskStore(),
        )
        server = A2AStarletteApplication(
            agent_card=agent_card, http_handler=request_handler
        )
        
        # Get routes from A2A application
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.responses import PlainTextResponse
        from starlette.requests import Request
        
        routes = server.routes()
        
        # Add health check endpoint
        async def health_check(request: Request) -> PlainTextResponse:
            return PlainTextResponse('Sentiment Analysis Agent is running!')
        
        routes.append(
            Route(
                path='/health',
                methods=['GET'],
                endpoint=health_check
            )
        )
        
        # Create Starlette app with all routes
        app = Starlette(routes=routes)
        
        # Background self-registration task
        async def register_after_startup():
            print("[DEBUG] Entered register_after_startup")
            """Register with host agent after a short delay to ensure server is ready."""
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
        
        # Start background registration
        if SELF_REGISTRATION_AVAILABLE:
            import threading
            def run_registration():
                print("[DEBUG] Entered run_registration thread")
                asyncio.run(register_after_startup())
            
            registration_thread = threading.Thread(target=run_registration, daemon=True)
            print("[DEBUG] About to start registration thread")
            registration_thread.start()
            logger.info(f"🚀 '{agent_card.name}' starting with background registration enabled")
        else:
            logger.info(f"📡 '{agent_card.name}' starting without self-registration")
        
        import uvicorn

        uvicorn.run(app, host=host, port=port)
    except MissingAPIKeyError as e:
        logger.error(f'Error: {e}')
        exit(1)
    except Exception as e:
        logger.error(f'An error occurred during server startup: {e}')
        exit(1)


if __name__ == '__main__':
    main()
