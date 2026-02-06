"""
Azure AI Foundry Teams Agent - Main Entry Point
================================================

An A2A agent that enables human-in-the-loop workflows via Microsoft Teams.
Runs both the A2A server and a Teams Bot webhook endpoint.
"""
import asyncio
import logging
import os
import traceback
from collections.abc import AsyncIterator
from typing import List
import threading

import click
import uvicorn

from foundry_agent_executor import create_foundry_agent_executor, initialize_teams_agents_at_startup, FoundryTeamsAgentExecutor
from foundry_agent import TeamsBot
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, JSONResponse
from starlette.routing import Route

from botbuilder.schema import Activity

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentSkill, Task

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Silence verbose Azure SDK logging
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
            logger.warning("Invalid A2A_PORT value '%s'; defaulting to 8021", raw_port)
    return 8021


def _resolve_bot_port() -> int:
    raw_port = _normalize_env_value(os.getenv('TEAMS_BOT_PORT'))
    if raw_port:
        try:
            return int(raw_port)
        except ValueError:
            logger.warning("Invalid TEAMS_BOT_PORT value '%s'; defaulting to 3978", raw_port)
    return 3978


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


# Default ports
DEFAULT_HOST = _resolve_default_host()
DEFAULT_PORT = _resolve_default_port()
DEFAULT_BOT_PORT = _resolve_bot_port()

HOST_AGENT_URL = _normalize_env_value(get_host_agent_url())

# Global reference to the agent executor
agent_executor_instance = None
# Global TeamsBot instance for webhook handling
teams_bot_instance = None


def _build_agent_skills() -> List[AgentSkill]:
    """
    Teams Agent Skills - Human-in-the-loop via Microsoft Teams
    """
    return [
        AgentSkill(
            id='teams_send_message',
            name='Send Teams Message',
            description="Send a message to a user via Microsoft Teams. Use this to communicate with humans, ask questions, or provide updates.",
            tags=['teams', 'message', 'send', 'communicate', 'notify', 'human'],
            examples=[
                'Send a message to the user asking for approval',
                'Notify the team lead about the status update',
                'Ask the manager for their decision',
                'Send a Teams message requesting input',
            ],
        ),
        AgentSkill(
            id='teams_wait_response',
            name='Wait for Human Response',
            description="Wait for a human to respond via Microsoft Teams. Use this for approval workflows, getting feedback, or any scenario requiring human input. The workflow will pause until the human responds.",
            tags=['teams', 'wait', 'response', 'human-in-the-loop', 'approval', 'input', 'feedback'],
            examples=[
                'Wait for approval from the manager',
                'Get the user\'s decision on the proposal',
                'Wait for feedback before proceeding',
                'Ask for confirmation and wait for response',
            ],
        ),
        AgentSkill(
            id='teams_human_escalation',
            name='Human Escalation',
            description="Escalate a task to a human via Teams when the AI cannot proceed autonomously. The human can provide guidance, make decisions, or take over the task.",
            tags=['escalation', 'human', 'help', 'assistance', 'decision', 'override'],
            examples=[
                'Escalate this to a human for review',
                'I need human assistance with this decision',
                'This requires human judgment',
                'Request human intervention',
            ],
        ),
    ]


def _create_agent_card(host: str, port: int) -> AgentCard:
    """
    Teams Agent Card
    
    Defines the agent's identity for registration and discovery in the A2A ecosystem.
    """
    skills = _build_agent_skills()
    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST
    
    return AgentCard(
        name='Teams Agent',
        description="Human-in-the-loop agent via Microsoft Teams. Can SEND messages to users, WAIT for human responses, and ESCALATE decisions requiring human judgment. Uses A2A input_required state for pause/resume workflows.",
        url=resolve_agent_url(resolved_host_for_url, port),
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities={"streaming": True, "humanInTheLoop": True},
        skills=skills,
    )


async def handle_teams_webhook(request: Request) -> JSONResponse:
    """
    Handle incoming messages from Microsoft Teams.
    This is called when a user sends a message to the bot.
    """
    global teams_bot_instance, agent_executor_instance
    
    try:
        body = await request.json()
        activity = Activity().deserialize(body)
        
        if not teams_bot_instance:
            teams_bot_instance = await TeamsBot.get_instance()
        
        if not teams_bot_instance.adapter:
            logger.error("Teams adapter not configured - missing credentials")
            return JSONResponse({"error": "Bot not configured"}, status_code=500)
        
        # Get auth header
        auth_header = request.headers.get("Authorization", "")
        
        # Backend URL for forwarding human responses
        backend_url = os.environ.get("BACKEND_URL", "http://localhost:12000")
        
        async def process_activity(turn_context):
            """Process the incoming activity."""
            # Store conversation reference for proactive messaging
            conversation_ref = TurnContext.get_conversation_reference(turn_context.activity)
            user_id = conversation_ref.user.id if conversation_ref.user else "unknown"
            teams_bot_instance.conversation_references[user_id] = conversation_ref
            # Persist to disk
            teams_bot_instance._save_conversation_references()
            
            if turn_context.activity.type == "message":
                user_message = turn_context.activity.text or ""
                logger.info(f"📥 Received Teams message from {user_id}: {user_message[:100]}...")
                
                # Check if there's a pending request waiting for this response
                if agent_executor_instance:
                    # DEBUG: Log what's in _waiting_for_input
                    waiting_contexts = list(agent_executor_instance._waiting_for_input.keys())
                    logger.info(f"🔍 DEBUG: _waiting_for_input has {len(waiting_contexts)} pending contexts: {waiting_contexts}")
                    
                    # Look for a pending request that matches this user
                    # Use LIFO (most recent first) - the human is most likely responding to the latest request
                    pending_items = list(agent_executor_instance._waiting_for_input.items())
                    pending_items.reverse()  # Most recent first
                    
                    for context_id, request_info in pending_items:
                        logger.info(f"🔍 DEBUG: Checking context {context_id}, request_info type: {type(request_info)}")
                        if isinstance(request_info, dict):
                            # Found a pending request - forward to backend via A2A message
                            logger.info(f"📤 Forwarding human response to backend for context {context_id}")
                            
                            # Store the thread_id before clearing so the executor can use it
                            # We need to pass this through somehow...
                            thread_id = request_info.get("thread_id")
                            wait_info = request_info.get("wait_info", "")
                            
                            # Clear the pending request NOW - we're about to forward it
                            # The executor will receive the context_id and can look up the thread
                            # from _active_threads if needed
                            agent_executor_instance.clear_pending_context(context_id)
                            
                            # Store the HITL resume info so the executor can find it
                            # Key by context_id so the executor can retrieve it
                            if not hasattr(agent_executor_instance, '_hitl_resume_info'):
                                agent_executor_instance._hitl_resume_info = {}
                            agent_executor_instance._hitl_resume_info[context_id] = {
                                "thread_id": thread_id,
                                "wait_info": wait_info,
                            }
                            logger.info(f"💾 Stored HITL resume info for {context_id}: thread={thread_id}")
                            
                            # Forward to backend's message API (A2A format)
                            try:
                                import aiohttp
                                async with aiohttp.ClientSession() as session:
                                    # Backend expects A2A Message format with params wrapper
                                    payload = {
                                        "params": {
                                            "contextId": context_id,
                                            "parts": [
                                                {"root": {"kind": "text", "text": user_message}}
                                            ]
                                        }
                                    }
                                    logger.info(f"📤 Sending to backend: {payload}")
                                    async with session.post(
                                        f"{backend_url}/message/send",
                                        json=payload,
                                        timeout=aiohttp.ClientTimeout(total=30)
                                    ) as resp:
                                        if resp.status == 200:
                                            logger.info(f"✅ Human response forwarded to backend successfully")
                                            # Send acknowledgment
                                            await turn_context.send_activity(
                                                f"✅ **Response Received**\n\n"
                                                f"Your response: _{user_message}_\n\n"
                                                f"The workflow is continuing with your input. Thank you!"
                                            )
                                        else:
                                            error_text = await resp.text()
                                            logger.error(f"❌ Backend returned {resp.status}: {error_text}")
                                            await turn_context.send_activity(
                                                f"⚠️ There was an issue processing your response. Please try again."
                                            )
                            except Exception as e:
                                logger.error(f"❌ Error forwarding to backend: {e}")
                                await turn_context.send_activity(
                                    f"⚠️ Could not reach the backend. Please try again later."
                                )
                            return
                
                # If no pending request, acknowledge and store for later
                await turn_context.send_activity(
                    f"📬 Message received. I'll process this when an agent needs your input."
                )
            
            elif turn_context.activity.type == "conversationUpdate":
                # New user joined
                if turn_context.activity.members_added:
                    for member in turn_context.activity.members_added:
                        if member.id != turn_context.activity.recipient.id:
                            await turn_context.send_activity(
                                "👋 Hello! I'm the Teams Agent for human-in-the-loop workflows. "
                                "When an AI agent needs your input, I'll send you a message here."
                            )
        
        # Process the activity
        from botbuilder.core import TurnContext
        await teams_bot_instance.adapter.process_activity(activity, auth_header, process_activity)
        
        return JSONResponse({"status": "ok"})
        
    except Exception as e:
        logger.error(f"Error processing Teams webhook: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


def create_combined_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Create combined A2A + Teams Bot server application."""
    global agent_executor_instance

    agent_card = _create_agent_card(host, port)
    agent_executor_instance = create_foundry_agent_executor(agent_card)
    
    task_store = InMemoryTaskStore()

    request_handler = DefaultRequestHandler(
        agent_executor=agent_executor_instance, 
        task_store=task_store
    )

    a2a_app = A2AStarletteApplication(
        agent_card=agent_card, 
        http_handler=request_handler
    )
    
    routes = a2a_app.routes()
    
    # Health check endpoint
    async def health_check(_: Request) -> PlainTextResponse:
        bot_status = "configured" if os.getenv("MICROSOFT_APP_ID") else "not configured"
        return PlainTextResponse(f'Teams Agent is running! Bot status: {bot_status}')
    
    routes.append(Route(path='/health', methods=['GET'], endpoint=health_check))
    
    # Teams Bot webhook endpoint (for receiving messages from Teams)
    routes.append(Route(path='/api/messages', methods=['POST'], endpoint=handle_teams_webhook))

    app = Starlette(routes=routes)
    
    return app


async def register_agent_with_host(agent_card):
    """Register this agent with the host agent after startup."""
    if SELF_REGISTRATION_AVAILABLE:
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


def main(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Launch A2A server mode for the Teams Agent with startup initialization."""
    required_env_vars = [
        'AZURE_AI_FOUNDRY_PROJECT_ENDPOINT',
        'AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME'
    ]
    
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        logger.warning(
            f"Missing Azure AI Foundry environment variables: {', '.join(missing_vars)}. "
            "Agent will start but Azure AI features may not work."
        )

    # Check Teams Bot configuration
    teams_vars = ['MICROSOFT_APP_ID', 'MICROSOFT_APP_PASSWORD']
    missing_teams = [var for var in teams_vars if not os.getenv(var)]
    if missing_teams:
        logger.warning(
            f"Missing Teams Bot environment variables: {', '.join(missing_teams)}. "
            "Teams messaging features will be unavailable."
        )

    print("🚀 Initializing Teams Agent at startup...")
    try:
        asyncio.run(initialize_teams_agents_at_startup())
        print("✅ Agent initialization completed successfully!")
    except Exception as e:
        print(f"⚠️ Agent initialization warning: {e}")
        # Don't raise - allow server to start anyway

    print(f"Starting Teams Agent on {host}:{port}...")
    print(f"  - A2A endpoint: http://{host}:{port}/")
    print(f"  - Teams webhook: http://{host}:{port}/api/messages")
    print(f"  - Health check: http://{host}:{port}/health")
    
    app = create_combined_server(host, port)
    
    agent_card = _create_agent_card(host, port)
    start_background_registration(agent_card)
    
    uvicorn.run(app, host=host, port=port)


@click.command()
@click.option('--host', 'host', default=DEFAULT_HOST, help='Host to bind to')
@click.option('--port', 'port', default=DEFAULT_PORT, help='Port for A2A + Teams Bot server')
def cli(host: str, port: int):
    """
    Teams Agent - Human-in-the-loop workflows via Microsoft Teams.
    
    Runs combined A2A server + Teams Bot webhook on the same port.
    
    Configure Teams Bot in Azure Bot Service to point messaging endpoint to:
    https://your-domain/api/messages
    """
    main(host, port)


if __name__ == '__main__':
    cli()
