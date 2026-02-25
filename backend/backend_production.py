"""Production backend API server for A2A system.

This starts a FastAPI-only server with WebSocket integration for local development.
Configured with open CORS and hardcoded environment variables.
Exposes only the API endpoints, no UI.

Usage:
    python backend_production.py
"""

import os
import asyncio
from pathlib import Path

# Resolve important backend directories up front so path-dependent imports work
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RUNTIME_DIR = BASE_DIR / ".runtime"
UPLOADS_DIR = RUNTIME_DIR / "uploads"
HOSTS_DIR = BASE_DIR / "hosts"

# Ensure critical directories exist when the backend boots
DATA_DIR.mkdir(parents=True, exist_ok=True)
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Ensure backend directory is on sys.path for consistent imports regardless of cwd
import sys
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv

ROOT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ROOT_ENV_PATH, override=False)

# Set default environment variables if not provided
os.environ.setdefault("A2A_HOST", "FOUNDRY")
# Configure for managed identity authentication (recommended for production)
os.environ.setdefault("A2A_UI_HOST", "0.0.0.0")
os.environ.setdefault("A2A_UI_PORT", "12000")
os.environ.setdefault("DEBUG_MODE", "false")

# Azure Content Understanding Configuration (defaults to matching AI Foundry)
os.environ.setdefault("AZURE_AI_SERVICE_ENDPOINT", os.environ.get("AZURE_CONTENT_UNDERSTANDING_ENDPOINT", ""))
os.environ.setdefault("AZURE_AI_SERVICE_API_VERSION", os.environ.get("AZURE_CONTENT_UNDERSTANDING_API_VERSION", "2024-12-01-preview"))

# WebSocket Configuration for local development
os.environ.setdefault("WEBSOCKET_SERVER_URL", "http://localhost:8080")

# Configure for Managed Identity authentication
# Replace with your managed identity's client ID

# When running in Azure Container Apps, this will automatically use managed identity

# Import logging config
from log_config import log_debug, log_info, log_warning, log_error, log_success

log_debug(f"Environment loaded, A2A_HOST: {os.environ.get('A2A_HOST')}")
log_debug(f"WebSocket URL: {os.environ.get('WEBSOCKET_SERVER_URL')}")
log_debug(f"Azure Tenant ID: {os.environ.get('AZURE_TENANT_ID')}")

import httpx
import uvicorn
import uuid
import mimetypes
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Request, HTTPException, Depends, WebSocket, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from service.server.server import ConversationServer
from service.websocket_streamer import get_websocket_streamer, cleanup_websocket_streamer
from service.websocket_server import set_auth_service
from service.agent_registry import get_registry
from pydantic import BaseModel
from datetime import datetime, timedelta, UTC
import jwt
import hashlib
import json
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

# Import AuthService from the lightweight module
# This avoids code duplication and keeps auth logic in one place
from service.auth_service import AuthService, User, SECRET_KEY, ALGORITHM

# Import ActiveWorkflowService for persisted workflow state
from service import active_workflow_service


def generate_workflow_text(steps: List[Dict[str, Any]], connections: List[Dict[str, Any]]) -> str:
    """
    Convert workflow steps + connections into text format for the orchestrator.

    Uses BFS over the connection graph to detect:
    - Parallel branches (1a, 1b) when a node has multiple outgoing edges
    - Evaluation branching (IF-TRUE / IF-FALSE)
    """
    if not steps:
        return ""

    from collections import deque

    sorted_steps = sorted(steps, key=lambda s: s.get('order', 0))
    step_by_id = {s.get('id'): s for s in sorted_steps}

    # Build adjacency maps (only non-conditional edges for parallel detection)
    outgoing = {}       # step_id -> [(target_id, condition)]
    outgoing_free = {}  # step_id -> [target_id] (non-conditional only)
    incoming_ids = set()
    connected_ids = set()

    for conn in (connections or []):
        from_id = conn.get('fromStepId')
        to_id = conn.get('toStepId')
        condition = conn.get('condition')
        if from_id:
            outgoing.setdefault(from_id, []).append((to_id, condition))
            if condition is None:
                outgoing_free.setdefault(from_id, []).append(to_id)
        if from_id:
            connected_ids.add(from_id)
        if to_id:
            connected_ids.add(to_id)
            incoming_ids.add(to_id)

    # If no connections, fall back to simple sequential ordering
    if not connections:
        lines = []
        for i, step in enumerate(sorted_steps):
            agent_name = step.get('agentName') or step.get('agent') or 'Unknown Agent'
            desc = step.get('description') or f'Use the {agent_name} agent'
            lines.append(f"{i + 1}. [{agent_name}] {desc}")
        return "\n".join(lines)

    # Identify branch targets of EVALUATE steps
    branch_target_ids = set()
    for step in sorted_steps:
        agent_name = step.get('agentName') or step.get('agent') or ''
        if agent_name.upper() == 'EVALUATE':
            step_id = step.get('id')
            for target_id, condition in outgoing.get(step_id, []):
                if condition in ('true', 'false'):
                    branch_target_ids.add(target_id)

    # BFS with parallel detection
    root_ids = [s.get('id') for s in sorted_steps
                if s.get('id') in connected_ids and s.get('id') not in incoming_ids]

    entries = []  # [{"step_number": int, "sub_letter": str|None, "step": dict}]
    visited = set()
    current_step_num = 0

    queue = deque()  # (step_id, parent_num, parallel_siblings, sibling_index)
    if len(root_ids) > 1:
        for idx, rid in enumerate(root_ids):
            queue.append((rid, 0, root_ids, idx))
    else:
        for rid in root_ids:
            queue.append((rid, 0, [], 0))

    while queue:
        step_id, parent_num, siblings, sib_idx = queue.popleft()
        if step_id in visited:
            continue
        visited.add(step_id)

        step = step_by_id.get(step_id)
        if not step:
            continue

        if len(siblings) > 1:
            step_number = parent_num + 1
            sub_letter = chr(97 + sib_idx)  # 'a', 'b', 'c'...
        else:
            current_step_num += 1
            step_number = current_step_num
            sub_letter = None

        entries.append({"step_number": step_number, "sub_letter": sub_letter, "step": step})

        # Enqueue children (non-conditional edges only)
        children = outgoing_free.get(step_id, [])
        if len(children) > 1:
            for cidx, child_id in enumerate(children):
                queue.append((child_id, step_number, children, cidx))
        elif len(children) == 1:
            queue.append((children[0], step_number, [], 0))

        # Update current_step_num after last parallel sibling
        if len(siblings) > 1 and sib_idx == len(siblings) - 1:
            current_step_num = step_number

    # Sort entries by step number, then sub-letter
    entries.sort(key=lambda e: (e["step_number"], e["sub_letter"] or ''))

    # Sequential numbering pass — parallel siblings share the same number
    seq_num = 0
    last_orig = -1
    step_num_map = {}  # step_id -> seq_num

    for entry in entries:
        sid = entry["step"].get("id")
        if sid in branch_target_ids:
            continue
        if entry["step_number"] != last_orig:
            seq_num += 1
            last_orig = entry["step_number"]
        step_num_map[sid] = seq_num

        # Also assign numbers to branch targets of eval steps
        agent_name = entry["step"].get('agentName') or entry["step"].get('agent') or ''
        if agent_name.upper() == 'EVALUATE':
            for target_id, condition in outgoing.get(sid, []):
                if condition in ('true', 'false') and target_id not in step_num_map:
                    seq_num += 1
                    step_num_map[target_id] = seq_num

    # Generate output lines
    lines = []
    for entry in entries:
        sid = entry["step"].get("id")
        if sid in branch_target_ids:
            continue

        num = step_num_map.get(sid, entry["step_number"])
        label = f"{num}{entry['sub_letter']}" if entry["sub_letter"] else f"{num}"
        agent_name = entry["step"].get('agentName') or entry["step"].get('agent') or 'Unknown Agent'
        desc = entry["step"].get('description') or f'Use the {agent_name} agent'
        lines.append(f"{label}. [{agent_name}] {desc}")

        # Emit IF-TRUE/IF-FALSE for eval steps
        if agent_name.upper() == 'EVALUATE':
            for target_id, condition in outgoing.get(sid, []):
                if condition in ('true', 'false') and target_id in step_by_id:
                    target_step = step_by_id[target_id]
                    target_agent = target_step.get('agentName') or target_step.get('agent') or 'Unknown Agent'
                    target_desc = target_step.get('description') or f'Use the {target_agent} agent'
                    branch_num = step_num_map.get(target_id, 0)
                    branch_label = "IF-TRUE" if condition == "true" else "IF-FALSE"
                    lines.append(f"   {branch_label} → {branch_num}. [{target_agent}] {target_desc}")

    return "\n".join(lines)


class HTTPXClientWrapper:
    """Wrapper to return the singleton client where needed."""

    async_client: httpx.AsyncClient = None

    def start(self):
        """ Instantiate the client. Call from the FastAPI startup hook."""
        # Some remote agents (e.g., image generators) stream results slowly, so we
        # need a generous read timeout to avoid dropping long-running SSE streams.
        # Azure Container Apps with replicas=0 can take 30-60s for cold starts.
        self.async_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=60.0,   # Increased from 10s to handle Azure Container Apps cold starts
                read=180.0,     # Increased from 120s for long-running agent operations
                write=120.0,
                pool=30.0,
            )
        )

    async def stop(self):
        """ Gracefully shutdown. Call from FastAPI shutdown hook."""
        await self.async_client.aclose()
        self.async_client = None

    def __call__(self):
        """ Calling the instantiated HTTPXClientWrapper returns the wrapped singleton."""
        # Ensure we don't use it if not started / running
        assert self.async_client is not None
        return self.async_client


# Setup the server global objects
httpx_client_wrapper = HTTPXClientWrapper()
agent_server = None
websocket_streamer = None
workflow_scheduler = None


def test_database_connection():
    """Test PostgreSQL database connection on startup."""
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        log_info("No DATABASE_URL found - using local JSON storage")
        return False

    log_info("DATABASE_URL found - testing PostgreSQL connection...")
    
    try:
        import psycopg2
        
        # Parse connection string to hide password in logs
        if "@" in database_url:
            parts = database_url.split("@")
            safe_url = f"postgresql://***:***@{parts[1]}"
        else:
            safe_url = database_url
        
        log_info(f"Connecting to: {safe_url}")
        
        # Test connection
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        # Test query
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        
        cursor.close()
        conn.close()
        
        log_info("Database connection successful!")
        log_info(f"PostgreSQL version: {version[:50]}...")
        return True
        
    except ImportError:
        log_error("psycopg2 not installed. Run: pip install psycopg2-binary")
        return False
    except Exception as e:
        log_error(f"Database connection failed: {e}")
        log_error("Falling back to local JSON storage")
        return False


async def execute_scheduled_workflow(workflow_name: str, session_id: str, timeout: int = 300):
    """Execute a workflow for the scheduler. Returns result dict.
    
    Note: Uses the user's original session_id to access their memory and files.
    This allows scheduled workflows to access uploaded documents and previous context.
    """
    global agent_server
    
    # Use the user's original session_id to access their memory/files
    # This allows scheduled workflows to search memory and access uploaded documents
    scheduler_session_id = session_id
    
    from service.workflow_service import WorkflowService
    from service.agent_registry import get_registry, get_session_registry
    import threading
    import asyncio
    import time
    
    workflow_service = WorkflowService()
    
    # Find workflow by name
    workflow = workflow_service.get_workflow_by_name(workflow_name)
    if not workflow:
        return {"success": False, "error": f"Workflow '{workflow_name}' not found"}
    
    # --- ENABLE AGENTS FOR SCHEDULER SESSION ---
    # The scheduler session doesn't have agents enabled like a user browser session.
    # We need to look up required agents from the global registry and enable them.
    # IMPORTANT: Scheduled workflows always use production URLs (public URLs for Azure agents)
    global_registry = get_registry()
    session_registry = get_session_registry()
    
    # Extract unique agent names from workflow steps
    agent_names_needed = []
    for step in (workflow.steps or []):
        name = step.get('agentName') or step.get('agent')
        if name and name not in agent_names_needed:
            agent_names_needed.append(name)
    
    log_debug(f"[SCHEDULER] Workflow '{workflow_name}' needs agents: {agent_names_needed}")
    
    # Look up each agent in global registry and enable for scheduler session
    # For scheduled workflows, always use production_url if available
    missing_agents = []
    enabled_count = 0
    for agent_name in agent_names_needed:
        agent_config = global_registry.get_agent(agent_name)
        if agent_config:
            # Force production URL for scheduled workflows
            if 'production_url' in agent_config and agent_config['production_url']:
                agent_config = agent_config.copy()
                agent_config['url'] = agent_config['production_url']
                log_debug(f"[SCHEDULER] Using production URL for '{agent_name}': {agent_config['url']}")
            elif 'url' in agent_config:
                log_debug(f"[SCHEDULER] Using URL for '{agent_name}': {agent_config['url']}")
            else:
                log_warning(f"[SCHEDULER] No URL found for '{agent_name}'")
            
            # Enable this agent for the scheduler session (use isolated scheduler_session_id)
            was_enabled = session_registry.enable_agent(scheduler_session_id, agent_config)
            if was_enabled:
                enabled_count += 1
                log_debug(f"[SCHEDULER] Enabled agent '{agent_name}' for session {scheduler_session_id}")
            else:
                log_debug(f"[SCHEDULER] Agent '{agent_name}' already enabled for session {scheduler_session_id}")
        else:
            missing_agents.append(agent_name)
            log_error(f"[SCHEDULER] Agent '{agent_name}' NOT FOUND in global registry!")
    
    if missing_agents:
        return {
            "success": False, 
            "error": f"Missing agents in registry: {', '.join(missing_agents)}. Available agents can be found in the Agent Catalog."
        }
    
    log_debug(f"[SCHEDULER] Enabled {enabled_count} agents for session {scheduler_session_id}")
    # --- END ENABLE AGENTS ---
    
    # Build workflow text (supports evaluation steps with branching)
    log_debug(f"[SCHEDULER] Building workflow text from {len(workflow.steps or [])} steps...")
    workflow_text = generate_workflow_text(workflow.steps or [], workflow.connections or [])

    initial_message = f'Run the "{workflow.name}" workflow.'
    conversation_id = str(uuid.uuid4())
    message_id = f"msg_{uuid.uuid4().hex[:8]}"
    # Use scheduler_session_id for context to isolate from user's active session
    context_id = f"{scheduler_session_id}::{conversation_id}"
    
    log_debug(f"[SCHEDULER] Workflow text:\n{workflow_text}")
    log_debug(f"[SCHEDULER] Context ID: {context_id} (isolated from user session {session_id})")
    
    if not agent_server:
        log_error("[SCHEDULER] agent_server is None!")
        return {"success": False, "error": "Agent server is None"}

    if not hasattr(agent_server, 'manager'):
        log_error("[SCHEDULER] agent_server has no 'manager' attribute!")
        return {"success": False, "error": "Agent server has no manager"}

    log_debug(f"[SCHEDULER] agent_server.manager exists: {type(agent_server.manager)}")
    
    from a2a.types import Message, Part, TextPart, Role
    
    message = Message(
        messageId=message_id,
        contextId=context_id,
        role=Role.user,
        parts=[Part(root=TextPart(text=initial_message))]
    )
    
    log_debug(f"[SCHEDULER] Message created: {initial_message}")
    
    # Use a shorter timeout for testing (60 seconds instead of 300)
    effective_timeout = min(timeout, 120)
    log_debug(f"[SCHEDULER] Timeout set to {effective_timeout}s")
    
    try:
        start_time = time.time()
        
        log_debug("[SCHEDULER] Calling agent_server.manager.process_message()...")
        log_debug("[SCHEDULER] This may take a while if agents are being called...")
        
        # Await directly since we're already in an async context on the main loop
        responses = await asyncio.wait_for(
            agent_server.manager.process_message(
                message, 
                agent_mode=None,
                enable_inter_agent_memory=True,
                workflow=workflow_text,
                workflow_goal=workflow.goal
            ),
            timeout=effective_timeout
        )
        
        elapsed_time = time.time() - start_time
        log_debug(f"[SCHEDULER] Workflow execution completed in {elapsed_time:.1f}s")
        
        result_text = ""
        if responses:
            if isinstance(responses, list):
                result_text = "\n\n".join(str(r) for r in responses)
            else:
                result_text = str(responses)
        
        log_debug(f"[SCHEDULER] Result length: {len(result_text)} chars")
        if len(result_text) > 500:
            log_debug(f"[SCHEDULER] Result preview: {result_text[:500]}...")
        else:
            log_debug(f"[SCHEDULER] Result: {result_text}")
        
        return {
            "success": True,
            "completed": True,
            "workflow_name": workflow.name,
            "execution_time_seconds": round(elapsed_time, 2),
            "result": result_text
        }
        
    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        log_warning(f"[SCHEDULER] TIMEOUT after {elapsed:.1f}s (limit was {effective_timeout}s)")
        return {"success": False, "error": f"Workflow execution timed out after {effective_timeout} seconds"}
    except Exception as e:
        log_error(f"[SCHEDULER] Error executing workflow: {e}")
        return {"success": False, "error": str(e)}


async def wake_up_remote_agents():
    """Wake up all remote agents with public URLs on backend startup.
    
    This is useful when agents are running on scale-to-zero containers (like Azure Container Apps).
    Sending a health check request will wake them up so they're ready when users make queries.
    This runs asynchronously in the background without blocking startup.
    """
    import asyncio
    
    log_info("[STARTUP] Waking up remote agents with public URLs...")
    
    try:
        registry = get_registry()
        agents = registry.get_all_agents()
        
        # Filter agents with public URLs (https://)
        remote_agents = [
            agent for agent in agents 
            if agent.get('url', '').startswith('https://')
        ]
        
        if not remote_agents:
            log_info("[STARTUP] No remote agents with public URLs found")
            return

        log_info(f"[STARTUP] Found {len(remote_agents)} remote agents to wake up")
        
        # Wake up agents in parallel with a short timeout
        async def ping_agent(agent: dict) -> tuple:
            """Ping an agent's health endpoint to wake it up."""
            url = agent.get('url', '').rstrip('/')
            name = agent.get('name', 'Unknown')
            health_url = f"{url}/health"
            
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(health_url)
                    if response.status_code == 200:
                        log_debug(f"[STARTUP] {name}: AWAKE (status: {response.status_code})")
                        return (name, True)
                    else:
                        log_warning(f"[STARTUP] {name}: responded with status {response.status_code}")
                        return (name, False)
            except httpx.TimeoutException:
                log_debug(f"[STARTUP] {name}: still waking up (timeout - container starting)")
                return (name, False)
            except Exception as e:
                log_warning(f"[STARTUP] {name}: error - {type(e).__name__}: {e}")
                return (name, False)
        
        # Background task to ping agents without blocking startup
        async def ping_agents_background():
            """Run agent pings in background and log results."""
            tasks = [ping_agent(agent) for agent in remote_agents]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Summary
            awake_count = sum(1 for r in results if isinstance(r, tuple) and r[1])
            log_info(f"[STARTUP] Wake-up complete: {awake_count}/{len(remote_agents)} agents responded")
        
        # Fire and forget - don't wait for completion
        asyncio.create_task(ping_agents_background())
        log_info("[STARTUP] Wake-up pings sent (running in background)")

    except Exception as e:
        log_error(f"[STARTUP] Error during agent wake-up: {type(e).__name__}: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup and shutdown."""
    global websocket_streamer, agent_server, workflow_scheduler
    
    log_info("Starting A2A Backend API...")
    
    # Start HTTP client
    httpx_client_wrapper.start()
    
    # WebSocket endpoint is now mounted directly on the main app (see below)
    # No need for a separate server on port 8080
    log_info("WebSocket endpoint available at /events on the main API port")
    
    # Initialize WebSocket streamer with error handling
    try:
        websocket_streamer = await get_websocket_streamer()
        if websocket_streamer:
            log_info("WebSocket streamer initialized successfully")
        else:
            log_warning("WebSocket streamer not available - check configuration")
    except Exception as e:
        log_error(f"Failed to initialize WebSocket streamer: {type(e).__name__}: {e}")
        log_error(f"Error details: {str(e)}")
        websocket_streamer = None
    
    # Initialize the conversation server (lightweight — routes only, no heavy init)
    try:
        agent_server = ConversationServer(app, httpx_client_wrapper())
        log_info("Conversation server initialized successfully")
    except Exception as e:
        log_error(f"Failed to initialize conversation server: {type(e).__name__}: {e}")
        log_error(f"Error details: {str(e)}")
        # Continue startup even if this fails

    # Define deferred init (scheduled right before yield, so it runs AFTER the port opens)
    async def _deferred_init():
        try:
            if agent_server and hasattr(agent_server, 'manager') and hasattr(agent_server.manager, 'initialize_async'):
                log_info("Starting deferred heavy initialization (DB + agent)...")
                await agent_server.manager.initialize_async()
                log_info("Deferred initialization complete -- host agent ready")
        except Exception as e:
            log_error(f"Deferred initialization failed: {type(e).__name__}: {e}")

    # Initialize the workflow scheduler
    try:
        from service.scheduler_service import get_workflow_scheduler, initialize_scheduler, APSCHEDULER_AVAILABLE
        if APSCHEDULER_AVAILABLE:
            workflow_scheduler = get_workflow_scheduler()
            workflow_scheduler.set_workflow_executor(execute_scheduled_workflow)
            await workflow_scheduler.start()
            log_info(f"Workflow scheduler started with {len(workflow_scheduler.schedules)} schedules")
        else:
            log_warning("APScheduler not installed - scheduled workflows disabled")
            log_info("Install with: pip install apscheduler")
    except Exception as e:
        log_warning(f"Failed to initialize workflow scheduler: {type(e).__name__}: {e}")
        # Continue startup even if scheduler fails
    
    # Wake up all remote agents with public URLs (for scale-to-zero containers)
    try:
        await wake_up_remote_agents()
    except Exception as e:
        log_warning(f"Failed to wake up remote agents: {type(e).__name__}: {e}")
        # Continue startup even if wake-up fails
    
    log_info("A2A Backend API startup complete")

    # Schedule heavy init RIGHT BEFORE yield — no await points between here and
    # yield, so the task cannot run until after the server port is open.
    asyncio.create_task(_deferred_init())

    yield
    
    # Cleanup
    log_info("Shutting down A2A Backend API...")
    
    # Stop workflow scheduler
    if workflow_scheduler:
        try:
            await workflow_scheduler.stop()
            log_info("Workflow scheduler stopped")
        except Exception as e:
            log_warning(f"Error stopping workflow scheduler: {e}")

    await httpx_client_wrapper.stop()
    await cleanup_websocket_streamer()
    log_info("A2A Backend API shutdown complete")


def main():
    """Main entry point for the production API server."""
    app = FastAPI(
        title="A2A Backend API",
        description="Agent-to-Agent communication backend with WebSocket integration",
        version="1.0.0",
        lifespan=lifespan
    )

    # Initialize auth service
    auth_service = AuthService()
    
    # Connect the auth service to the websocket server
    set_auth_service(auth_service)

    # Add CORS middleware with very open settings for container deployment
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Allow all origins for container deployment
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add a simple health check endpoint
    @app.get("/health")
    async def health_check():
        """Health check endpoint for container orchestration."""
        return {
            "status": "healthy",
            "service": "a2a-backend-api",
            "version": "1.0.0",
            "websocket_enabled": websocket_streamer is not None,
            "auth_method": "managed_identity",
            "client_id": os.environ.get("AZURE_CLIENT_ID", "not_set")
        }

    # Host Agent Model Selection
    @app.get("/api/host-agent/model")
    async def get_host_model():
        """Return the current host agent model deployment name and debug info."""
        try:
            if agent_server and hasattr(agent_server, 'manager'):
                model = agent_server.manager.get_host_model()
                # Include debug info about the client configuration
                debug_info = {}
                host_agent = getattr(agent_server.manager, '_host_agent', None)
                if host_agent:
                    client = getattr(host_agent, 'openai_client', None)
                    debug_info["client_type"] = type(client).__name__ if client else "None"
                    debug_info["client_base_url"] = str(getattr(client, '_base_url', getattr(client, 'base_url', 'unknown'))) if client else "None"
                    debug_info["alt_endpoint"] = getattr(host_agent, '_alt_endpoint', 'not_set')
                    debug_info["model_endpoints"] = getattr(host_agent, '_model_endpoints', {})
                    debug_info["alt_clients_cached"] = list(getattr(host_agent, '_alt_openai_clients', {}).keys())
                    debug_info["has_original_client"] = getattr(host_agent, '_original_openai_client', None) is not None
                return {"success": True, "model": model, "debug": debug_info}
            return {"success": False, "error": "Host agent not available"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.put("/api/host-agent/model")
    async def set_host_model(request: Request):
        """Switch the host agent model deployment (takes effect immediately)."""
        try:
            body = await request.json()
            model = body.get("model", "").strip()
            if not model:
                return {"success": False, "error": "Missing 'model' field"}
            if agent_server and hasattr(agent_server, 'manager'):
                agent_server.manager.set_host_model(model)
                return {"success": True, "model": model}
            return {"success": False, "error": "Host agent not available"}
        except ValueError as ve:
            return {"success": False, "error": str(ve)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # Agent Registry Endpoints
    @app.get("/api/agents")
    async def get_all_agents():
        """Get all agents from the registry."""
        try:
            registry = get_registry()
            agents = registry.get_all_agents()
            return {
                "success": True,
                "agents": agents
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    @app.get("/api/agents/{agent_name}")
    async def get_agent(agent_name: str):
        """Get a specific agent by name."""
        try:
            registry = get_registry()
            agent = registry.get_agent(agent_name)
            if agent:
                return {
                    "success": True,
                    "agent": agent
                }
            else:
                return {
                    "success": False,
                    "error": "Agent not found"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    @app.post("/api/agents")
    async def add_agent(request: Request):
        """Add a new agent to the registry."""
        try:
            agent_data = await request.json()
            registry = get_registry()
            success = registry.add_agent(agent_data)
            if success:
                return {
                    "success": True,
                    "message": "Agent added successfully"
                }
            else:
                return {
                    "success": False,
                    "error": "Agent with this name already exists"
                }
        except ValueError as e:
            return {
                "success": False,
                "error": str(e)
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    @app.put("/api/agents/{agent_name}")
    async def update_agent(agent_name: str, request: Request):
        """Update an existing agent in the registry."""
        try:
            agent_data = await request.json()
            registry = get_registry()
            success = registry.update_agent(agent_name, agent_data)
            if success:
                return {
                    "success": True,
                    "message": "Agent updated successfully"
                }
            else:
                return {
                    "success": False,
                    "error": "Agent not found"
                }
        except ValueError as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    @app.patch("/api/agents")
    async def upsert_agent(request: Request):
        """Update an existing agent or add as new if it doesn't exist."""
        try:
            agent_data = await request.json()
            registry = get_registry()
            success = registry.update_or_add_agent(agent_data)
            if success:
                return {
                    "success": True,
                    "message": "Agent updated or added successfully"
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to update or add agent"
                }
        except ValueError as e:
            return {
                "success": False,
                "error": str(e)
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    @app.delete("/api/agents/{agent_name}")
    async def delete_agent(agent_name: str):
        """Delete an agent from the registry."""
        try:
            registry = get_registry()
            success = registry.remove_agent(agent_name)
            if success:
                return {
                    "success": True,
                    "message": "Agent deleted successfully"
                }
            else:
                return {
                    "success": False,
                    "error": "Agent not found"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    @app.get("/api/agents/health/{agent_url:path}")
    async def check_agent_health(agent_url: str):
        """Check health status of an agent."""
        try:
            from log_config import log_debug
            import httpx
            # Clean up the URL to avoid double slashes
            # Default to https:// for Azure Container Apps (localhost uses http://)
            if not agent_url.startswith('http'):
                base_url = f"https://{agent_url}" if not agent_url.startswith('localhost') else f"http://{agent_url}"
            else:
                base_url = agent_url
            # Remove trailing slash and add /health
            health_url = base_url.rstrip('/') + '/health'
            log_debug(f"Health check: agent_url='{agent_url}' -> health_url='{health_url}'")
            
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(health_url)
                log_debug(f"Health response: {response.status_code}")
                return {
                    "success": True,
                    "online": response.status_code == 200,
                    "status_code": response.status_code
                }
        except Exception as e:
            from log_config import log_debug
            log_debug(f"Health check error: {e}")
            return {
                "success": True,
                "online": False,
                "error": str(e)
            }

    # Authentication Models
    class LoginRequest(BaseModel):
        email: str
        password: str

    class RegisterRequest(BaseModel):
        email: str
        password: str
        name: str
        role: str
        description: str = ""
        skills: List[str] = []
        color: str = "#6B7280"

    class LoginResponse(BaseModel):
        success: bool
        access_token: str = None
        user_info: dict = None
        message: str = None

    # Security scheme for JWT
    security = HTTPBearer()

    def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
        """Dependency to get current authenticated user from JWT token."""
        token = credentials.credentials
        user_data = auth_service.verify_token(token)
        if not user_data:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        return user_data

    # Authentication Endpoints
    @app.post("/api/auth/login", response_model=LoginResponse)
    async def login(request: LoginRequest):
        """Authenticate user and return JWT token."""
        try:
            user = auth_service.authenticate_user(request.email, request.password)
            if not user:
                return LoginResponse(
                    success=False,
                    message="Invalid email or password"
                )
            
            # Create access token
            access_token = auth_service.create_access_token(user)
            
            return LoginResponse(
                success=True,
                access_token=access_token,
                user_info={
                    "user_id": user.user_id,
                    "email": user.email,
                    "name": user.name,
                    "role": user.role,
                    "description": user.description,
                    "skills": user.skills,
                    "color": user.color
                },
                message="Login successful"
            )
            
        except Exception as e:
            log_error(f"Login error: {e}")
            return LoginResponse(
                success=False,
                message="Login failed due to server error"
            )

    @app.get("/api/auth/users")
    async def get_connected_users():
        """Get all registered users."""
        try:
            all_users = auth_service.get_all_users()
            
            return {
                "success": True,
                "users": all_users
            }
            
        except Exception as e:
            log_error(f"Get users error: {e}")
            return {
                "success": False,
                "users": [],
                "message": "Failed to get users"
            }

    @app.get("/api/auth/active-users")
    async def get_active_users(current_user: dict = Depends(get_current_user)):
        """Get currently active/logged-in user for this session.
        
        For multi-tenancy, this endpoint returns only the current session's user,
        not all active users across the system.
        """
        try:
            # Get full user details for the current session user
            user = auth_service.get_user_by_email(current_user.get("email", ""))
            
            if user:
                user_data = {
                    "user_id": user.user_id,
                    "email": user.email,
                    "name": user.name,
                    "role": user.role,
                    "description": user.description,
                    "skills": user.skills,
                    "color": user.color,
                    "created_at": user.created_at.isoformat(),
                    "last_login": user.last_login.isoformat() if user.last_login else None,
                    "status": "active"
                }
                return {
                    "success": True,
                    "users": [user_data],  # Only this session's user
                    "total_active": 1,
                    "session_isolated": True
                }
            else:
                return {
                    "success": True,
                    "users": [],
                    "total_active": 0,
                    "session_isolated": True
                }
            
        except HTTPException:
            raise  # Re-raise auth exceptions
        except Exception as e:
            log_error(f"Get active users error: {e}")
            return {
                "success": False,
                "users": [],
                "total_active": 0,
                "message": "Failed to get active users"
            }

    @app.post("/api/auth/register", response_model=LoginResponse)
    async def register(request: RegisterRequest):
        """Register a new user."""
        try:
            # Check if user already exists - reload from database/file to get latest data
            if auth_service.use_database:
                auth_service._load_users_from_database()
            else:
                auth_service._load_users_from_file()
            
            if request.email in auth_service.users:
                return LoginResponse(
                    success=False,
                    message="User with this email already exists"
                )
            
            # Create new user
            user = auth_service.create_user(
                email=request.email,
                password=request.password,
                name=request.name,
                role=request.role,
                description=request.description,
                skills=request.skills,
                color=request.color
            )
            
            if not user:
                return LoginResponse(
                    success=False,
                    message="Failed to create user"
                )
            
            return LoginResponse(
                success=True,
                message="Registration successful! Please log in."
            )
            
        except Exception as e:
            log_error(f"Registration error: {e}")
            return LoginResponse(
                success=False,
                message="Registration failed due to server error"
            )

    # ==========================================================================
    # Workflow API Endpoints
    # ==========================================================================
    
    from service.workflow_service import get_workflow_service
    workflow_service = get_workflow_service()
    
    class WorkflowCreate(BaseModel):
        id: str
        name: str
        description: str = ""
        category: str = "Custom"
        goal: str = ""
        steps: List[Dict[str, Any]]
        connections: List[Dict[str, Any]]
    
    class WorkflowUpdate(BaseModel):
        name: Optional[str] = None
        description: Optional[str] = None
        category: Optional[str] = None
        goal: Optional[str] = None
        steps: Optional[List[Dict[str, Any]]] = None
        connections: Optional[List[Dict[str, Any]]] = None
    
    @app.get("/api/workflows")
    async def get_workflows(current_user: dict = Depends(get_current_user)):
        """Get all workflows for the current user."""
        user_id = current_user.get("user_id")
        workflows = workflow_service.get_user_workflows(user_id)
        return {
            "success": True,
            "workflows": [workflow_service.workflow_to_dict(w) for w in workflows]
        }
    
    @app.get("/api/workflows/all")
    async def get_all_workflows():
        """Get all workflows (for shared catalog - no auth required)."""
        workflows = workflow_service.get_all_workflows()
        return {
            "success": True,
            "workflows": [workflow_service.workflow_to_dict(w) for w in workflows]
        }
    
    @app.get("/api/workflows/{workflow_id}")
    async def get_workflow(workflow_id: str):
        """Get a specific workflow by ID."""
        workflow = workflow_service.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return {
            "success": True,
            "workflow": workflow_service.workflow_to_dict(workflow)
        }
    
    @app.post("/api/workflows")
    async def create_workflow(workflow_data: WorkflowCreate, current_user: dict = Depends(get_current_user)):
        """Create a new workflow for the current user."""
        user_id = current_user.get("user_id")
        
        # Check if workflow with this ID already exists
        existing = workflow_service.get_workflow(workflow_data.id)
        if existing:
            # Update instead of create if it exists and belongs to user
            if existing.user_id == user_id:
                updated = workflow_service.update_workflow(
                    workflow_id=workflow_data.id,
                    user_id=user_id,
                    name=workflow_data.name,
                    description=workflow_data.description,
                    category=workflow_data.category,
                    steps=workflow_data.steps,
                    connections=workflow_data.connections
                )
                return {
                    "success": True,
                    "message": "Workflow updated",
                    "workflow": workflow_service.workflow_to_dict(updated)
                }
            else:
                raise HTTPException(status_code=403, detail="Workflow belongs to another user")
        
        workflow = workflow_service.create_workflow(
            workflow_id=workflow_data.id,
            name=workflow_data.name,
            user_id=user_id,
            description=workflow_data.description,
            category=workflow_data.category,
            goal=workflow_data.goal,
            steps=workflow_data.steps,
            connections=workflow_data.connections
        )
        return {
            "success": True,
            "message": "Workflow created",
            "workflow": workflow_service.workflow_to_dict(workflow)
        }
    
    @app.put("/api/workflows/{workflow_id}")
    async def update_workflow(workflow_id: str, workflow_data: WorkflowUpdate, current_user: dict = Depends(get_current_user)):
        """Update an existing workflow."""
        user_id = current_user.get("user_id")
        
        workflow = workflow_service.update_workflow(
            workflow_id=workflow_id,
            user_id=user_id,
            name=workflow_data.name,
            description=workflow_data.description,
            category=workflow_data.category,
            goal=workflow_data.goal,
            steps=workflow_data.steps,
            connections=workflow_data.connections
        )
        
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found or access denied")
        
        return {
            "success": True,
            "message": "Workflow updated",
            "workflow": workflow_service.workflow_to_dict(workflow)
        }
    
    @app.delete("/api/workflows/{workflow_id}")
    async def delete_workflow(workflow_id: str, current_user: dict = Depends(get_current_user)):
        """Delete a workflow."""
        user_id = current_user.get("user_id")
        
        success = workflow_service.delete_workflow(workflow_id, user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Workflow not found or access denied")
        
        return {
            "success": True,
            "message": "Workflow deleted"
        }
    
    # ==================== NATURAL LANGUAGE QUERY API ====================
    # Synchronous API endpoint for sending natural language queries
    # Supports intelligent workflow routing
    
    class QueryRequest(BaseModel):
        query: str  # The natural language query
        user_id: str  # REQUIRED: User ID to filter workflows (only user's workflows are considered)
        session_id: Optional[str] = None  # Optional session ID (auto-generated if not provided)
        conversation_id: Optional[str] = None  # Optional conversation ID
        timeout: int = 300  # Timeout in seconds (default 5 min)
        enable_routing: bool = True  # Whether to enable intelligent workflow routing
        activated_workflow_ids: Optional[List[str]] = None  # Optional list of activated workflow IDs to filter by
        workflow: Optional[str] = None  # Optional explicit workflow to execute (bypasses routing)
    
    @app.post("/api/query")
    async def execute_query(
        request: QueryRequest,
        credentials: HTTPAuthorizationCredentials = Depends(security)
    ):
        """
        Execute a natural language query with intelligent workflow routing.
        
        This endpoint provides a simple API for sending queries that automatically:
        - Enables all available session agents
        - Routes to appropriate workflows belonging to the specified user
        - Orchestrates multi-agent execution
        - Returns the result synchronously
        
        REQUIRED: 
        - Authorization header with Bearer token
        - user_id must be provided to filter workflows by user.
        
        Example curl:
            curl -X POST http://localhost:12000/api/query \\
                -H "Content-Type: application/json" \\
                -H "Authorization: Bearer YOUR_TOKEN" \\
                -d '{"query": "check my balance and list customers", "user_id": "user_3"}'
        
        With custom session:
            curl -X POST http://localhost:12000/api/query \\
                -H "Content-Type: application/json" \\
                -H "Authorization: Bearer YOUR_TOKEN" \\
                -d '{"query": "what invoices are overdue?", "user_id": "user_3", "session_id": "my-session-123"}'
        """
        # Verify token
        user = auth_service.verify_token(credentials.credentials)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid authentication token")
        
        # Verify the request's user_id matches the authenticated user
        if request.user_id != user["user_id"]:
            raise HTTPException(
                status_code=403, 
                detail=f"User ID mismatch: authenticated as {user['user_id']}, requested {request.user_id}"
            )
        
        import uuid
        import asyncio
        import time
        from service.server.server import main_loop
        from a2a.types import Message, Part, TextPart, Role
        from service.agent_registry import get_registry, get_session_registry
        
        log_debug(f"[Query API] Received query: {request.query}")
        log_debug(f"[Query API] User ID: {request.user_id} (authenticated: {user['email']})")
        
        # Generate IDs
        session_id = request.session_id or str(uuid.uuid4())
        conversation_id = request.conversation_id or str(uuid.uuid4())
        message_id = f"msg_{uuid.uuid4().hex[:8]}"
        context_id = f"{session_id}::{conversation_id}"
        
        log_debug(f"[Query API] Session ID: {session_id}")
        log_debug(f"[Query API] Context ID: {context_id}")
        
        # Check if agent_server is available
        if not agent_server or not hasattr(agent_server, 'manager'):
            raise HTTPException(status_code=503, detail="Agent server not available")
        
        # Get agents enabled for this session (user must enable them in UI first)
        session_registry = get_session_registry()
        session_agents = session_registry.get_session_agents(session_id)
        
        if not session_agents:
            raise HTTPException(
                status_code=400, 
                detail="No agents enabled for this session. Please enable agents from the Agents tab first."
            )
        
        log_debug(f"[Query API] Using {len(session_agents)} pre-enabled session agents")
        for agent_config in session_agents:
            log_debug(f"[Query API] Session agent: {agent_config.get('name', 'unknown')}")
        
        # Build available workflows for intelligent routing (if enabled)
        available_workflows = []
        if request.enable_routing:
            from service.workflow_service import get_workflow_service
            workflow_service = get_workflow_service()
            all_workflows = workflow_service.get_all_workflows()
            
            # Filter workflows by user_id - only include workflows belonging to this user
            user_workflows = [w for w in all_workflows if w.user_id == request.user_id]
            log_debug(f"[Query API] Filtered to {len(user_workflows)} workflows for user '{request.user_id}' (out of {len(all_workflows)} total)")
            
            # Further filter by activated workflow IDs if provided
            if request.activated_workflow_ids:
                activated_ids = set(request.activated_workflow_ids)
                user_workflows = [w for w in user_workflows if w.id in activated_ids]
                log_debug(f"[Query API] Filtered to {len(user_workflows)} activated workflows (from {len(activated_ids)} activated IDs)")
            
            for w in user_workflows:
                if w.steps:
                    # Sort steps by order
                    sorted_steps = sorted(w.steps, key=lambda s: s.get('order', 0))
                    # Generate workflow text in the format the orchestrator expects
                    workflow_lines = []
                    for i, step in enumerate(sorted_steps):
                        agent_name = step.get('agentName', 'unknown')
                        default_desc = f'Use the {agent_name} agent'
                        description = step.get('description', default_desc)
                        workflow_lines.append(f"{i+1}. [{agent_name}] {description}")
                    workflow_text = "\n".join(workflow_lines)
                    
                    workflow_info = {
                        "id": w.id,
                        "name": w.name,
                        "goal": w.goal or "",
                        "workflow": workflow_text,  # Include the formatted steps!
                        "agents": [step.get('agentName', '') for step in sorted_steps if step.get('agentName')]
                    }
                    available_workflows.append(workflow_info)
            log_debug(f"[Query API] Found {len(available_workflows)} workflows for routing")
        
        # Create the message
        message = Message(
            messageId=message_id,
            contextId=context_id,
            role=Role.user,
            parts=[Part(root=TextPart(text=request.query))]
        )
        
        # Process message with routing enabled
        try:
            # If explicit workflow provided, use it directly (workflow designer test mode)
            explicit_workflow = request.workflow if request.workflow else None
            if explicit_workflow:
                log_debug("[Query API] Using explicit workflow (workflow designer mode)")

            log_debug(f"[Query API] Processing query (timeout: {request.timeout}s)")
            start_time = time.time()
            
            # Submit the coroutine to the main event loop
            future = asyncio.run_coroutine_threadsafe(
                agent_server.manager.process_message(
                    message, 
                    agent_mode=None,  # Auto-detect based on routing
                    enable_inter_agent_memory=True,
                    workflow=explicit_workflow,  # Use explicit workflow if provided, else let routing decide
                    available_workflows=available_workflows if (available_workflows and not explicit_workflow) else None
                ), 
                main_loop
            )
            
            # Wait for the result with timeout
            try:
                responses = future.result(timeout=request.timeout)
                elapsed_time = time.time() - start_time
                
                log_debug(f"[Query API] Query completed in {elapsed_time:.2f}s")
                
                # Format the responses
                result_text = ""
                if responses:
                    if isinstance(responses, list):
                        result_text = "\n\n".join(str(r) for r in responses)
                    else:
                        result_text = str(responses)
                
                # Emit final_response event to WebSocket so frontend can clear inferencing state
                # This is especially important for voice queries which don't use streaming
                try:
                    from service.websocket_streamer import get_websocket_streamer
                    async def emit_final_response():
                        streamer = await get_websocket_streamer()
                        if streamer:
                            await streamer._send_event(
                                "final_response",
                                {
                                    "contextId": context_id,
                                    "conversationId": conversation_id,
                                    "result": result_text[:500] if result_text else "",  # Truncate for event
                                    "isComplete": True,
                                },
                                context_id
                            )
                            log_debug(f"[Query API] Emitted final_response event for conversation: {conversation_id}")
                    asyncio.run_coroutine_threadsafe(emit_final_response(), main_loop)
                except Exception as e:
                    log_warning(f"[Query API] Failed to emit final_response event: {e}")
                
                return {
                    "success": True,
                    "query": request.query,
                    "session_id": session_id,
                    "conversation_id": conversation_id,
                    "execution_time_seconds": round(elapsed_time, 2),
                    "result": result_text
                }
                
            except asyncio.TimeoutError:
                elapsed_time = time.time() - start_time
                log_warning(f"[Query API] Query timed out after {elapsed_time:.2f}s")
                raise HTTPException(
                    status_code=408, 
                    detail=f"Query timed out after {request.timeout} seconds"
                )
                
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"[Query API] Error processing query: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to process query: {str(e)}")

    # ==================== ACTIVE WORKFLOW (SESSION-SCOPED) ====================
    # Stores active workflow state per session, synced across collaborative sessions
    # Now persisted to PostgreSQL via active_workflow_service
    
    class ActiveWorkflowRequest(BaseModel):
        workflow: str = ""
        name: str = ""
        goal: str = ""
    
    @app.get("/api/active-workflow")
    async def get_active_workflow_endpoint(session_id: str = Query(..., description="Session ID to get active workflow for")):
        """
        Get the active workflow for a session.
        Used by all users in a collaborative session to see the same active workflow.
        
        Example curl:
            curl "http://localhost:12000/api/active-workflow?session_id=abc123"
        """
        return active_workflow_service.get_active_workflow(session_id)
    
    @app.post("/api/active-workflow")
    async def set_active_workflow(
        session_id: str = Query(..., description="Session ID to set active workflow for"),
        request: ActiveWorkflowRequest = None
    ):
        """
        Set the active workflow for a session.
        This is synced across all users in the collaborative session.
        
        Example curl:
            curl -X POST "http://localhost:12000/api/active-workflow?session_id=abc123" \\
                 -H "Content-Type: application/json" \\
                 -d '{"workflow": "1. [Agent A] Do something", "name": "My Workflow", "goal": "Accomplish task"}'
        """
        if request:
            # Store in database via service
            active_workflow_service.set_active_workflow(
                session_id,
                request.workflow,
                request.name,
                request.goal
            )
            # Broadcast to all users in this session via WebSocket
            # Use _send_event with session_id as contextId for smart routing
            try:
                if websocket_streamer:
                    await websocket_streamer._send_event(
                        "active_workflow_changed",
                        {
                            "contextId": session_id,
                            "workflow": request.workflow,
                            "name": request.name,
                            "goal": request.goal
                        },
                        partition_key=session_id
                    )
            except Exception as e:
                log_warning(f"[ActiveWorkflow] Failed to broadcast: {e}")
        return {"success": True, "session_id": session_id}
    
    @app.delete("/api/active-workflow")
    async def clear_active_workflow(session_id: str = Query(..., description="Session ID to clear active workflow for")):
        """
        Clear the active workflow for a session.
        
        Example curl:
            curl -X DELETE "http://localhost:12000/api/active-workflow?session_id=abc123"
        """
        # Clear from database via service
        active_workflow_service.clear_active_workflow(session_id)
        # Broadcast to all users in this session via WebSocket
        try:
            if websocket_streamer:
                await websocket_streamer._send_event(
                    "active_workflow_changed",
                    {
                        "contextId": session_id,
                        "workflow": "",
                        "name": "",
                        "goal": ""
                    },
                    partition_key=session_id
                )
        except Exception as e:
            log_warning(f"[ActiveWorkflow] Failed to broadcast clear: {e}")
        return {"success": True, "session_id": session_id}

    # ==================== MULTI-WORKFLOW API ENDPOINTS ====================
    # New API for managing multiple active workflows per session
    # Uses database-backed service for persistence across restarts
    
    @app.get("/api/active-workflows")
    async def get_active_workflows(session_id: str = Query(..., description="Session ID")):
        """
        Get all active workflows for a session.
        Returns empty list if no workflows are active.
        """
        workflows = active_workflow_service.get_active_workflows(session_id)
        return {"workflows": workflows}
    
    @app.post("/api/active-workflows")
    async def set_active_workflows(
        session_id: str = Query(..., description="Session ID"),
        request: Request = None
    ):
        """
        Set all active workflows for a session (replaces existing).
        """
        body = await request.json()
        workflows = body.get("workflows", [])
        active_workflow_service.set_active_workflows(session_id, workflows)
        
        # Broadcast update to all users in session
        try:
            if websocket_streamer:
                await websocket_streamer._send_event(
                    "active_workflows_changed",
                    {"contextId": session_id, "workflows": workflows},
                    partition_key=session_id
                )
        except Exception as e:
            log_warning(f"[ActiveWorkflows] Failed to broadcast: {e}")
        
        return {"success": True, "workflows": workflows}
    
    @app.post("/api/active-workflows/add")
    async def add_active_workflow(
        session_id: str = Query(..., description="Session ID"),
        request: Request = None
    ):
        """
        Add a single workflow to the active workflows list.
        """
        body = await request.json()
        workflow = body
        
        workflows = active_workflow_service.add_active_workflow(session_id, workflow)
        
        # Broadcast update
        try:
            if websocket_streamer:
                await websocket_streamer._send_event(
                    "active_workflows_changed",
                    {"contextId": session_id, "workflows": workflows},
                    partition_key=session_id
                )
        except Exception as e:
            log_warning(f"[ActiveWorkflows] Failed to broadcast add: {e}")
        
        return {"success": True, "workflows": workflows}
    
    @app.delete("/api/active-workflows/{workflow_id}")
    async def remove_active_workflow(
        workflow_id: str,
        session_id: str = Query(..., description="Session ID")
    ):
        """
        Remove a specific workflow from the active workflows list.
        """
        workflows = active_workflow_service.remove_active_workflow(session_id, workflow_id)
        
        # Broadcast update
        try:
            if websocket_streamer:
                await websocket_streamer._send_event(
                    "active_workflows_changed",
                    {"contextId": session_id, "workflows": workflows},
                    partition_key=session_id
                )
        except Exception as e:
            log_warning(f"[ActiveWorkflows] Failed to broadcast remove: {e}")
        
        return {"success": True, "workflows": workflows}
    
    @app.delete("/api/active-workflows")
    async def clear_active_workflows(session_id: str = Query(..., description="Session ID")):
        """
        Clear all active workflows for a session.
        """
        active_workflow_service.clear_active_workflows(session_id)
        
        # Broadcast update
        try:
            if websocket_streamer:
                await websocket_streamer._send_event(
                    "active_workflows_changed",
                    {"contextId": session_id, "workflows": []},
                    partition_key=session_id
                )
        except Exception as e:
            log_warning(f"[ActiveWorkflows] Failed to broadcast clear: {e}")
        
        return {"success": True, "workflows": []}

    # ==================== WORKFLOW SCHEDULER ENDPOINTS ====================
    
    from service.scheduler_service import (
        get_workflow_scheduler, 
        ScheduleType, 
        ScheduledWorkflow,
        initialize_scheduler
    )
    
    # Request models for scheduler
    class CreateScheduleRequest(BaseModel):
        workflow_id: str
        workflow_name: str
        session_id: str
        schedule_type: str  # "once", "interval", "daily", "weekly", "monthly", "cron"
        enabled: bool = True
        
        # Schedule parameters
        run_at: Optional[str] = None          # For ONCE: ISO datetime
        interval_minutes: Optional[int] = None # For INTERVAL
        time_of_day: Optional[str] = None     # For DAILY/WEEKLY/MONTHLY: "HH:MM"
        days_of_week: Optional[List[int]] = None  # For WEEKLY: 0=Mon, 6=Sun
        day_of_month: Optional[int] = None    # For MONTHLY: 1-31
        cron_expression: Optional[str] = None # For CRON
        timezone: str = "UTC"
        
        # Execution settings
        timeout: int = 300
        retry_on_failure: bool = False
        max_retries: int = 3
        max_runs: Optional[int] = None        # Maximum number of runs (None = unlimited)
        
        # Metadata
        description: Optional[str] = None
        tags: List[str] = []
    
    class UpdateScheduleRequest(BaseModel):
        enabled: Optional[bool] = None
        schedule_type: Optional[str] = None
        run_at: Optional[str] = None
        interval_minutes: Optional[int] = None
        time_of_day: Optional[str] = None
        days_of_week: Optional[List[int]] = None
        day_of_month: Optional[int] = None
        cron_expression: Optional[str] = None
        timezone: Optional[str] = None
        timeout: Optional[int] = None
        retry_on_failure: Optional[bool] = None
        max_retries: Optional[int] = None
        max_runs: Optional[int] = None
        description: Optional[str] = None
        tags: Optional[List[str]] = None
    
    @app.get("/api/schedules/workflows")
    async def list_schedulable_workflows(current_user: dict = Depends(get_current_user)):
        """
        List all saved workflows available for scheduling for the current user.
        
        Example curl:
            curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:12000/api/schedules/workflows
        """
        try:
            from service.workflow_service import get_workflow_service
            workflow_service = get_workflow_service()
            user_id = current_user.get("user_id")
            user_workflows = workflow_service.get_user_workflows(user_id)
            # Return a simplified list with just id and name
            return [
                {"id": w.id, "name": w.name}
                for w in user_workflows
            ]
        except Exception as e:
            log_error(f"Failed to list workflows: {e}")
            return []
    
    @app.get("/api/schedules")
    async def list_schedules(workflow_id: Optional[str] = None, session_id: Optional[str] = None):
        """
        List all scheduled workflows, optionally filtered by session.
        
        Example curl:
            curl http://localhost:12000/api/schedules
            curl http://localhost:12000/api/schedules?session_id=user_123
            curl http://localhost:12000/api/schedules?workflow_id=custom-123
        """
        scheduler = get_workflow_scheduler()
        schedules = scheduler.list_schedules(workflow_id, session_id)
        return {
            "schedules": [s.to_dict() for s in schedules],
            "count": len(schedules)
        }
    
    @app.get("/api/schedules/upcoming")
    async def get_upcoming_runs(limit: int = 10):
        """
        Get upcoming scheduled workflow runs.
        
        Example curl:
            curl http://localhost:12000/api/schedules/upcoming
        """
        scheduler = get_workflow_scheduler()
        upcoming = scheduler.get_upcoming_runs(limit)
        return {
            "upcoming": upcoming,
            "count": len(upcoming)
        }
    
    @app.get("/api/schedules/history")
    async def get_schedule_history(schedule_id: Optional[str] = None, session_id: Optional[str] = None, limit: int = 50):
        """
        Get run history for scheduled workflows, optionally filtered by session.
        
        Example curl:
            curl http://localhost:12000/api/schedules/history
            curl http://localhost:12000/api/schedules/history?session_id=user_123
            curl http://localhost:12000/api/schedules/history?schedule_id={id}
        """
        scheduler = get_workflow_scheduler()
        history = scheduler.get_run_history(schedule_id, session_id, limit)
        return {
            "history": history,
            "count": len(history)
        }
    
    @app.get("/api/schedules/{schedule_id}")
    async def get_schedule(schedule_id: str):
        """
        Get a specific schedule by ID.
        
        Example curl:
            curl http://localhost:12000/api/schedules/{schedule_id}
        """
        scheduler = get_workflow_scheduler()
        schedule = scheduler.get_schedule(schedule_id)
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return schedule.to_dict()
    
    @app.post("/api/schedules")
    async def create_schedule(request: CreateScheduleRequest):
        """
        Create a new scheduled workflow.
        
        Example curl (run every 5 minutes):
            curl -X POST http://localhost:12000/api/schedules \\
                -H "Content-Type: application/json" \\
                -d '{"workflow_id": "custom-123", "workflow_name": "My Workflow", "session_id": "user_3", "schedule_type": "interval", "interval_minutes": 5}'
        
        Example curl (run daily at 9am):
            curl -X POST http://localhost:12000/api/schedules \\
                -H "Content-Type: application/json" \\
                -d '{"workflow_id": "custom-123", "workflow_name": "My Workflow", "session_id": "user_3", "schedule_type": "daily", "time_of_day": "09:00"}'
        
        Example curl (run once at specific time):
            curl -X POST http://localhost:12000/api/schedules \\
                -H "Content-Type: application/json" \\
                -d '{"workflow_id": "custom-123", "workflow_name": "My Workflow", "session_id": "user_3", "schedule_type": "once", "run_at": "2026-02-02T10:00:00Z"}'
        """
        try:
            scheduler = get_workflow_scheduler()
            
            # Convert schedule_type string to enum
            try:
                schedule_type = ScheduleType(request.schedule_type)
            except ValueError:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Invalid schedule_type. Must be one of: {[t.value for t in ScheduleType]}"
                )
            
            schedule = scheduler.create_schedule(
                workflow_id=request.workflow_id,
                workflow_name=request.workflow_name,
                session_id=request.session_id,
                schedule_type=schedule_type,
                enabled=request.enabled,
                run_at=request.run_at,
                interval_minutes=request.interval_minutes,
                time_of_day=request.time_of_day,
                days_of_week=request.days_of_week,
                day_of_month=request.day_of_month,
                cron_expression=request.cron_expression,
                timezone=request.timezone,
                timeout=request.timeout,
                retry_on_failure=request.retry_on_failure,
                max_retries=request.max_retries,
                max_runs=request.max_runs,
                description=request.description,
                tags=request.tags
            )
            
            return {
                "success": True,
                "message": f"Schedule created for workflow '{request.workflow_name}'",
                "schedule": schedule.to_dict()
            }
            
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"[Scheduler] Error creating schedule: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create schedule: {str(e)}")
    
    @app.put("/api/schedules/{schedule_id}")
    async def update_schedule(schedule_id: str, request: UpdateScheduleRequest):
        """
        Update a scheduled workflow.
        
        Example curl:
            curl -X PUT http://localhost:12000/api/schedules/{schedule_id} \\
                -H "Content-Type: application/json" \\
                -d '{"enabled": false}'
        """
        try:
            scheduler = get_workflow_scheduler()
            
            # Build update dict from non-None fields
            update_data = {}
            for field, value in request.model_dump().items():
                if value is not None:
                    if field == 'schedule_type':
                        update_data[field] = ScheduleType(value)
                    else:
                        update_data[field] = value
            
            schedule = scheduler.update_schedule(schedule_id, **update_data)
            if not schedule:
                raise HTTPException(status_code=404, detail="Schedule not found")
            
            return {
                "success": True,
                "message": "Schedule updated",
                "schedule": schedule.to_dict()
            }
            
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"[Scheduler] Error updating schedule: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to update schedule: {str(e)}")
    
    @app.delete("/api/schedules/{schedule_id}")
    async def delete_schedule(schedule_id: str):
        """
        Delete a scheduled workflow.
        
        Example curl:
            curl -X DELETE http://localhost:12000/api/schedules/{schedule_id}
        """
        scheduler = get_workflow_scheduler()
        success = scheduler.delete_schedule(schedule_id)
        if not success:
            raise HTTPException(status_code=404, detail="Schedule not found")
        
        return {
            "success": True,
            "message": "Schedule deleted"
        }
    
    @app.post("/api/schedules/{schedule_id}/toggle")
    async def toggle_schedule(schedule_id: str, enabled: bool):
        """
        Enable or disable a scheduled workflow.
        
        Example curl:
            curl -X POST "http://localhost:12000/api/schedules/{schedule_id}/toggle?enabled=false"
        """
        scheduler = get_workflow_scheduler()
        schedule = scheduler.toggle_schedule(schedule_id, enabled)
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        
        return {
            "success": True,
            "message": f"Schedule {'enabled' if enabled else 'disabled'}",
            "schedule": schedule.to_dict()
        }
    
    @app.post("/api/schedules/{schedule_id}/run-now")
    async def run_schedule_now(schedule_id: str, session_id: Optional[str] = None, wait: bool = False):
        """
        Immediately execute a scheduled workflow (doesn't affect the regular schedule).
        
        If session_id is provided, the workflow runs in that session (visible in user's chat).
        Otherwise, it uses the schedule's default session.
        
        If wait=true, the request blocks until workflow completes and returns full results.
        
        Example curl:
            curl -X POST http://localhost:12000/api/schedules/{schedule_id}/run-now
            curl -X POST "http://localhost:12000/api/schedules/{schedule_id}/run-now?session_id=sess_abc123"
            curl -X POST "http://localhost:12000/api/schedules/{schedule_id}/run-now?wait=true"
        """
        import time
        from datetime import datetime
        
        scheduler = get_workflow_scheduler()
        schedule = scheduler.get_schedule(schedule_id)
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        
        # Use the provided session_id or fall back to schedule's default
        effective_session_id = session_id if session_id else schedule.session_id
        
        # Track start time for history
        start_time = time.time()
        started_at = datetime.utcnow().isoformat()
        
        # Use the existing workflow run logic
        run_request = WorkflowRunRequest(
            workflow_id=schedule.workflow_id,
            workflow_name=schedule.workflow_name,
            session_id=effective_session_id,
            wait_for_completion=wait,  # Use the wait parameter
            timeout=schedule.timeout
        )
        
        result = await run_workflow(run_request)
        
        # Calculate execution time and store in history
        execution_time = time.time() - start_time
        completed_at = datetime.utcnow().isoformat()
        
        # Store run in history
        scheduler._add_run_history(
            schedule_id=schedule_id,
            workflow_id=schedule.workflow_id,
            workflow_name=schedule.workflow_name,
            session_id=effective_session_id,
            status="success" if result.get('success', False) else "failed",
            result=result.get('result') or result.get('message', 'Workflow started'),
            error=result.get('error'),
            started_at=started_at,
            completed_at=completed_at,
            execution_time=execution_time
        )
        
        return result

    # ==================== END SCHEDULER ENDPOINTS ====================

    @app.post("/clear-memory")
    async def clear_memory(request: Request):
        """Clear stored interactions from the Azure vector memory index for a specific user."""
        try:
            # Get user_id from request body
            body = await request.json()
            user_id = body.get('user_id')
            
            if not user_id:
                return {
                    "success": False,
                    "message": "user_id is required"
                }
            
            # Import and use a2a_memory_service directly to avoid context_id transformation
            from hosts.multiagent.a2a_memory_service import a2a_memory_service
            
            # Clear memory for this specific session_id (user_id)
            success = a2a_memory_service.clear_all_interactions(session_id=user_id)
            
            if success:
                return {
                    "success": True,
                    "message": f"Memory index cleared successfully for user {user_id}"
                }
            else:
                return {
                    "success": False,
                    "message": "Failed to clear memory index"
                }
        except Exception as e:
            log_error(f"Error clearing memory: {e}")
            return {
                "success": False,
                "message": f"Error clearing memory: {str(e)}"
            }

    # Helper function to upload to Azure Blob Storage
    def upload_to_azure_blob(file_id: str, file_name: str, file_bytes: bytes, mime_type: str, session_id: str = None) -> str:
        """Upload file to Azure Blob Storage and return public SAS URL.
        
        Args:
            file_id: Unique file identifier
            file_name: Original filename
            file_bytes: File content bytes
            mime_type: MIME type of the file
            session_id: Optional session ID for tenant isolation (scopes blob path)
        """
        # Build local fallback path (session-scoped if session_id provided)
        local_fallback = f"/uploads/{session_id}/{file_id}" if session_id else f"/uploads/{file_id}"
        
        try:
            from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions, ContentSettings
            from azure.identity import DefaultAzureCredential
            
            # Get Azure connection details
            connection_string = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
            storage_account_name = os.getenv('AZURE_STORAGE_ACCOUNT_NAME')
            
            # Initialize blob client with managed identity or connection string
            if storage_account_name and not connection_string:
                # Use managed identity authentication
                account_url = f"https://{storage_account_name}.blob.core.windows.net"
                credential = DefaultAzureCredential()
                blob_service_client = BlobServiceClient(account_url, credential=credential)
                log_debug(f"Using managed identity for blob storage: {account_url}")
            elif connection_string:
                # Use connection string authentication (legacy)
                blob_service_client = BlobServiceClient.from_connection_string(connection_string)
                log_debug("Using connection string for blob storage")
            else:
                log_warning("No Azure Storage configuration found, returning local path")
                return local_fallback
            
            container_name = os.getenv('AZURE_BLOB_CONTAINER', 'a2a-files')
            
            # Generate blob name with session scope for tenant isolation
            safe_file_name = file_name.replace('/', '_').replace('\\', '_')
            if session_id:
                blob_name = f"uploads/{session_id}/{file_id}/{safe_file_name}"
            else:
                blob_name = f"uploads/{file_id}/{safe_file_name}"
            
            # Upload to blob
            blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
            content_settings = ContentSettings(
                content_type=mime_type,
                content_disposition=f'inline; filename="{file_name}"'
            )
            
            blob_client.upload_blob(
                file_bytes,
                content_settings=content_settings,
                metadata={
                    'file_id': file_id,
                    'original_name': file_name,
                    'upload_time': datetime.now(UTC).isoformat()
                },
                overwrite=True
            )
            
            # Generate SAS token if using connection string (has account key)
            if connection_string:
                account_key = None
                for part in connection_string.split(';'):
                    if part.startswith('AccountKey='):
                        account_key = part.split('=', 1)[1]
                        break
                
                if account_key:
                    sas_token = generate_blob_sas(
                        account_name=blob_client.account_name,
                        container_name=container_name,
                        blob_name=blob_name,
                        account_key=account_key,
                        permission=BlobSasPermissions(read=True),
                        expiry=datetime.now(UTC) + timedelta(hours=24),
                        version="2023-11-03"
                    )
                    blob_url = f"{blob_client.url}?{sas_token}"
                    log_warning(f"[BLOB_UPLOAD] SUCCESS (connection string + SAS): {blob_url[:100]}...")
                    return blob_url
            
            # For managed identity, return blob URL directly (container must be public or use user delegation SAS)
            log_warning(f"[BLOB_UPLOAD] SUCCESS (managed identity): {blob_client.url}")
            return blob_client.url

        except Exception as e:
            import traceback
            log_error(f"[BLOB_UPLOAD] Azure Blob upload FAILED: {e}")
            log_error(f"[BLOB_UPLOAD] Traceback: {traceback.format_exc()}")
            log_error(f"[BLOB_UPLOAD] Falling back to local path: {local_fallback}")
            return local_fallback

    # Add file upload endpoint
    @app.post("/upload")
    async def upload_file(file: UploadFile = File(...), request: Request = None):
        """Upload a file and return file information for A2A processing.
        
        Supports session isolation via X-Session-ID header.
        Files are stored in session-scoped directories.
        """
        try:
            # Extract session_id from header for tenant isolation
            session_id = None
            if request:
                session_id = request.headers.get("X-Session-ID")
            
            # Generate unique file ID
            file_id = str(uuid.uuid4())
            
            # Get file extension
            file_extension = ""
            if file.filename and "." in file.filename:
                file_extension = "." + file.filename.split(".")[-1]
            
            # Create unique filename with extension
            filename = f"{file_id}{file_extension}"
            
            # Session-scoped file path
            if session_id:
                session_upload_dir = UPLOADS_DIR / session_id
                session_upload_dir.mkdir(parents=True, exist_ok=True)
                file_path = session_upload_dir / filename
                local_uri = f"/uploads/{session_id}/{filename}"
            else:
                file_path = UPLOADS_DIR / filename
                local_uri = f"/uploads/{filename}"

            # Read file content
            content = await file.read()
            
            from log_config import log_debug
            # Save file locally (as backup)
            with open(file_path, "wb") as buffer:
                buffer.write(content)
            
            log_debug(f"File uploaded: {file.filename} -> {file_path} ({len(content)} bytes) [session: {session_id or 'none'}]")
            
            # Upload to Azure Blob and get public SAS URL (session-scoped)
            blob_url = upload_to_azure_blob(
                file_id=file_id,
                file_name=file.filename or filename,
                file_bytes=content,
                mime_type=file.content_type or 'application/octet-stream',
                session_id=session_id
            )
            
            return {
                "success": True,
                "filename": file.filename,
                "file_id": file_id,
                "uri": blob_url,  # Now returns Azure Blob SAS URL
                "size": len(content),
                "content_type": file.content_type,
                "session_id": session_id
            }
            
        except Exception as e:
            log_error(f"File upload failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # Add endpoint to list user files
    @app.get("/api/files")
    async def list_user_files(request: Request):
        """List all files for a user from blob storage (with local fallback).
        
        Returns files stored under uploads/{session_id}/ in blob storage,
        or from local filesystem if blob storage is unavailable.
        """
        try:
            # Extract session_id from header
            session_id = request.headers.get("X-Session-ID")
            if not session_id:
                return {"success": False, "error": "Missing X-Session-ID header"}
            
            files = []
            
            # Get processed filenames from Azure Search (fast single query)
            from hosts.multiagent.a2a_memory_service import a2a_memory_service
            processed_filenames = a2a_memory_service.get_processed_filenames(session_id)
            log_debug(f"Found {len(processed_filenames)} processed files in memory for session {session_id}")
            
            # Try blob storage first
            try:
                from azure.storage.blob import BlobServiceClient
                from azure.identity import DefaultAzureCredential
                from datetime import datetime, UTC
                
                # Get Azure connection details
                connection_string = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
                storage_account_name = os.getenv('AZURE_STORAGE_ACCOUNT_NAME')
                
                if storage_account_name and not connection_string:
                    # Use managed identity
                    account_url = f"https://{storage_account_name}.blob.core.windows.net"
                    credential = DefaultAzureCredential()
                    blob_service_client = BlobServiceClient(account_url, credential=credential)
                elif connection_string:
                    # Use connection string
                    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
                else:
                    raise Exception("No Azure Storage configuration found")
                
                container_name = os.getenv('AZURE_BLOB_CONTAINER', 'a2a-files')
                container_client = blob_service_client.get_container_client(container_name)
                
                # List blobs for this session - filter by path prefix for speed
                prefix = f"uploads/{session_id}/"
                for blob in container_client.list_blobs(name_starts_with=prefix):
                    # Skip if 0 bytes (empty/failed uploads)
                    if blob.size == 0:
                        log_debug(f"Skipping 0-byte blob: {blob.name}")
                        continue
                    
                    # Parse blob path to extract file_id and filename
                    parts = blob.name.split('/')
                    if len(parts) >= 4:
                        # uploads/{session_id}/{file_id}/{filename}
                        file_id = parts[2]
                        filename = parts[3]
                        
                        # Get status from Azure Search (processed files are "in memory")
                        file_status = "analyzed" if filename in processed_filenames else "uploaded"
                        
                        # Generate fresh SAS URL
                        blob_url = None
                        if connection_string:
                            from azure.storage.blob import generate_blob_sas, BlobSasPermissions
                            from datetime import timedelta
                            
                            account_key = None
                            for part in connection_string.split(';'):
                                if part.startswith('AccountKey='):
                                    account_key = part.split('=', 1)[1]
                                    break
                            
                            if account_key:
                                # Generate fresh 7-day SAS token
                                sas_token = generate_blob_sas(
                                    account_name=blob_service_client.account_name,
                                    container_name=container_name,
                                    blob_name=blob.name,
                                    account_key=account_key,
                                    permission=BlobSasPermissions(read=True),
                                    expiry=datetime.now(UTC) + timedelta(days=7),  # 7 days instead of 24 hours
                                    version="2023-11-03"
                                )
                                blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob.name)
                                blob_url = f"{blob_client.url}?{sas_token}"
                        
                        files.append({
                            "id": file_id,
                            "filename": filename,
                            "originalName": filename,
                            "size": blob.size,
                            "contentType": blob.content_settings.content_type if blob.content_settings else "application/octet-stream",
                            "uploadedAt": blob.last_modified.isoformat() if blob.last_modified else None,
                            "uri": blob_url or blob.name,
                            "status": file_status
                        })
                
                log_debug(f"Listed {len(files)} files from blob storage for session: {session_id}")

            except Exception as blob_error:
                log_warning(f"Blob storage unavailable, falling back to local filesystem: {blob_error}")
                
                # Fallback to local filesystem
                local_dir = UPLOADS_DIR / session_id
                if local_dir.exists():
                    for file_path in local_dir.rglob("*"):
                        if file_path.is_file():
                            # Try to extract file_id from parent directory structure
                            rel_path = file_path.relative_to(local_dir)
                            file_id = str(rel_path.parent) if rel_path.parent != Path('.') else str(uuid.uuid4())
                            filename = file_path.name
                            
                            # Get status from Azure Search (processed files are "in memory")
                            file_status = "analyzed" if filename in processed_filenames else "uploaded"
                            
                            files.append({
                                "id": file_id,
                                "filename": filename,
                                "originalName": filename,
                                "size": file_path.stat().st_size,
                                "contentType": "application/octet-stream",
                                "uploadedAt": datetime.fromtimestamp(file_path.stat().st_mtime, UTC).isoformat(),
                                "uri": f"/uploads/{session_id}/{file_id}",
                                "status": file_status
                            })
                
                log_debug(f"Listed {len(files)} files from local filesystem for session: {session_id}")
            
            # NO DEDUPLICATION - show all files from blob storage as-is
            # Each file has a unique ID (file_id from path), even if filenames are identical
            # The file history should be the source of truth for what's in blob storage
            
            # Sort by upload date (most recent first)
            files.sort(key=lambda f: f.get('uploadedAt', ''), reverse=True)
            
            return {
                "success": True,
                "files": files
            }
            
        except Exception as e:
            log_error(f"Failed to list files: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    @app.delete("/api/files/{file_id}")
    async def delete_file(file_id: str, request: Request, filename: str = None):
        """Delete a file from blob storage, local filesystem, and memory index.
        
        Gracefully handles expired/missing files - always returns success
        even if the file doesn't exist (idempotent operation).
        
        Args:
            file_id: The unique file ID
            filename: Optional filename (query param) to also delete from memory index
        """
        try:
            # Extract session_id from header
            session_id = request.headers.get("X-Session-ID")
            if not session_id:
                return {"success": False, "error": "Missing X-Session-ID header"}
            
            deleted_from_blob = False
            deleted_from_local = False
            deleted_from_memory = False
            
            # Try to delete from blob storage
            try:
                from azure.storage.blob import BlobServiceClient
                from azure.identity import DefaultAzureCredential
                
                # Get Azure connection details
                connection_string = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
                storage_account_name = os.getenv('AZURE_STORAGE_ACCOUNT_NAME')
                
                if storage_account_name and not connection_string:
                    # Use managed identity
                    account_url = f"https://{storage_account_name}.blob.core.windows.net"
                    credential = DefaultAzureCredential()
                    blob_service_client = BlobServiceClient(account_url, credential=credential)
                elif connection_string:
                    # Use connection string
                    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
                else:
                    raise Exception("No Azure Storage configuration found")
                
                container_name = os.getenv('AZURE_BLOB_CONTAINER', 'a2a-files')
                container_client = blob_service_client.get_container_client(container_name)
                
                # Delete from uploads/{session_id}/{file_id}/*
                deleted_count = 0
                prefix = f"uploads/{session_id}/{file_id}/"
                
                for blob in container_client.list_blobs(name_starts_with=prefix):
                    try:
                        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob.name)
                        blob_client.delete_blob()
                        deleted_count += 1
                        log_debug(f"Deleted blob: {blob.name}")
                    except Exception as delete_err:
                        # Ignore errors (file might be expired/already deleted)
                        log_warning(f"Could not delete blob {blob.name}: {delete_err}")
                
                # FALLBACK: Also check legacy agent-specific paths (image-generator, video-generator, email-attachments)
                if deleted_count == 0:
                    legacy_prefixes = [
                        f"image-generator/{file_id}/",
                        f"video-generator/{file_id}/",
                        f"email-attachments/{file_id}/"
                    ]
                    for legacy_prefix in legacy_prefixes:
                        for blob in container_client.list_blobs(name_starts_with=legacy_prefix):
                            try:
                                blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob.name)
                                blob_client.delete_blob()
                                deleted_count += 1
                                log_debug(f"Deleted legacy blob: {blob.name}")
                            except Exception as delete_err:
                                log_warning(f"Could not delete legacy blob {blob.name}: {delete_err}")
                
                if deleted_count > 0:
                    deleted_from_blob = True
                    log_debug(f"Deleted {deleted_count} blob(s) for file_id: {file_id}")
                else:
                    log_debug(f"No blobs found for file_id: {file_id} (might be expired/already deleted)")
                
            except Exception as blob_error:
                # Don't fail if blob storage is unavailable or file doesn't exist
                log_warning(f"Blob storage delete failed (this is OK): {blob_error}")
            
            # Try to delete from local filesystem
            try:
                local_dir = UPLOADS_DIR / session_id
                if local_dir.exists():
                    for file_path in local_dir.rglob("*"):
                        if file_id in str(file_path):
                            try:
                                if file_path.is_file():
                                    file_path.unlink()
                                    deleted_from_local = True
                                    log_debug(f"Deleted local file: {file_path}")
                                elif file_path.is_dir():
                                    import shutil
                                    shutil.rmtree(file_path)
                                    deleted_from_local = True
                                    log_debug(f"Deleted local directory: {file_path}")
                            except Exception as delete_err:
                                log_warning(f"Could not delete local file {file_path}: {delete_err}")
            except Exception as local_error:
                log_warning(f"Local filesystem delete failed (this is OK): {local_error}")
            
            # Try to delete from memory index (if filename provided)
            if filename:
                try:
                    from hosts.multiagent.a2a_memory_service import a2a_memory_service
                    deleted_from_memory = a2a_memory_service.delete_by_filename(session_id, filename)
                    if deleted_from_memory:
                        log_debug(f"Deleted memory chunks for file: {filename}")
                    else:
                        log_debug(f"No memory chunks found for file: {filename}")
                except Exception as memory_error:
                    log_warning(f"Memory index delete failed (this is OK): {memory_error}")
            
            # Delete from agent file registry
            deleted_from_registry = False
            try:
                from service.agent_file_registry import delete_agent_file
                deleted_from_registry = delete_agent_file(session_id, file_id)
                if deleted_from_registry:
                    log_debug(f"Deleted file from agent file registry: {file_id}")
                else:
                    log_debug(f"File not found in agent file registry: {file_id}")
            except Exception as registry_error:
                log_warning(f"Agent file registry delete failed (this is OK): {registry_error}")
            
            # Always return success (idempotent operation)
            return {
                "success": True,
                "deleted_from_blob": deleted_from_blob,
                "deleted_from_local": deleted_from_local,
                "deleted_from_memory": deleted_from_memory,
                "deleted_from_registry": deleted_from_registry,
                "message": "File deleted successfully" if (deleted_from_blob or deleted_from_local or deleted_from_memory or deleted_from_registry) else "File not found (might be expired or already deleted)"
            }
        
        except Exception as e:
            # Even on error, return success to prevent UI errors
            log_error(f"Error deleting file: {e}")
            return {
                "success": True,  # Still return success
                "error": str(e),
                "message": "Delete operation completed with errors (this is OK for expired files)"
            }

    @app.post("/api/files/process")
    async def process_file(request: Request):
        """Process an uploaded file through document processing and store results in memory.
        
        This endpoint extracts text/content from documents, analyzes images,
        and stores the results in the A2A memory service for semantic search.
        """
        try:
            # Extract session_id from header
            session_id = request.headers.get("X-Session-ID")
            if not session_id:
                return {"success": False, "error": "Missing X-Session-ID header"}
            
            # Parse request body
            body = await request.json()
            file_id = body.get("file_id")
            filename = body.get("filename")
            uri = body.get("uri")
            content_type = body.get("content_type", "application/octet-stream")
            
            if not file_id or not filename:
                return {"success": False, "error": "Missing file_id or filename"}
            
            log_debug(f"Processing file: {filename} (id: {file_id}, session: {session_id})")
            
            # Try to get file bytes from blob storage or local filesystem
            file_bytes = None
            
            # Try Azure Blob Storage first
            if uri and "blob.core.windows.net" in uri:
                try:
                    import httpx
                    async with httpx.AsyncClient() as client:
                        response = await client.get(uri, timeout=60.0)
                        if response.status_code == 200:
                            file_bytes = response.content
                            log_debug(f"Downloaded {len(file_bytes)} bytes from Azure Blob")
                except Exception as blob_err:
                    log_warning(f"Could not download from blob: {blob_err}")
            
            # Try local filesystem
            if file_bytes is None:
                local_path = UPLOADS_DIR / session_id / file_id
                if local_path.exists():
                    for file_path in local_path.iterdir():
                        if file_path.is_file():
                            with open(file_path, 'rb') as f:
                                file_bytes = f.read()
                            log_debug(f"Read {len(file_bytes)} bytes from local filesystem")
                            break
            
            if file_bytes is None:
                return {"success": False, "error": "Could not retrieve file content"}
            
            # Import the document processor
            try:
                from hosts.multiagent.a2a_document_processor import process_file_part
                
                # Create a file-like object for processing
                class FilePart:
                    def __init__(self, name, data):
                        self.name = name
                        self.data = data
                
                file_part = FilePart(filename, file_bytes)
                artifact_info = {
                    "file_name": filename,
                    "id": file_id,
                    "content_type": content_type
                }
                
                # Process the file
                result = await process_file_part(file_part, artifact_info, session_id=session_id)
                
                if result.get("success"):
                    log_debug(f"Document processing completed for: {filename}")
                    
                    # Update blob metadata to mark as analyzed
                    try:
                        connection_string = os.getenv('AZURE_BLOB_CONNECTION_STRING')
                        container_name = os.getenv('AZURE_BLOB_CONTAINER', 'a2a-files')
                        if connection_string:
                            from azure.storage.blob import BlobServiceClient
                            blob_service_client = BlobServiceClient.from_connection_string(connection_string)
                            
                            # Try different blob paths
                            blob_paths = [
                                f"uploads/{session_id}/{file_id}/{filename}",
                                f"image-generator/{file_id}/{filename}",
                            ]
                            
                            for blob_path in blob_paths:
                                try:
                                    blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_path)
                                    if blob_client.exists():
                                        blob_client.set_blob_metadata({"status": "analyzed"})
                                        log_debug(f"Set blob metadata status=analyzed for: {blob_path}")
                                        break
                                except Exception:
                                    continue
                    except Exception as meta_err:
                        log_warning(f"Could not set blob metadata: {meta_err}")
                    
                    return {
                        "success": True,
                        "file_id": file_id,
                        "filename": filename,
                        "content_length": len(result.get("content", "")),
                        "file_type": result.get("file_type"),
                        "message": "Document processed and stored in memory"
                    }
                else:
                    error_msg = result.get("error", "Unknown processing error")
                    log_warning(f"Document processing failed for {filename}: {error_msg}")
                    return {
                        "success": False,
                        "error": error_msg
                    }
                    
            except ImportError as e:
                log_error(f"Could not import document processor: {e}")
                return {"success": False, "error": "Document processor not available"}
            except Exception as process_err:
                log_error(f"Document processing error: {process_err}")
                return {"success": False, "error": str(process_err)}

        except Exception as e:
            log_error(f"Error in process_file endpoint: {e}")
            return {"success": False, "error": str(e)}

    # Add voice upload endpoint with transcription
    @app.post("/upload-voice")
    async def upload_voice(file: UploadFile = File(...), request: Request = None):
        """Upload a voice recording, save as WAV, and transcribe to text using A2A document processor.
        
        Supports session isolation via X-Session-ID header.
        """
        try:
            # Extract session_id from header for tenant isolation
            session_id = None
            if request:
                session_id = request.headers.get("X-Session-ID")
            
            # Create voice recordings directory (session-scoped if session_id provided)
            voice_dir = RUNTIME_DIR / "voice_recordings"
            if session_id:
                voice_dir = voice_dir / session_id
            voice_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate unique file ID
            file_id = str(uuid.uuid4())
            
            # Ensure WAV extension
            filename = f"voice_{file_id}.wav"
            file_path = voice_dir / filename

            from log_config import log_debug
            # Save file
            with open(file_path, "wb") as buffer:
                content = await file.read()
                buffer.write(content)
            
            log_debug(f"Voice file uploaded: {file.filename} -> {file_path} ({len(content)} bytes) [session: {session_id or 'none'}]")
            
            # Import the document processor to handle audio transcription
            try:
                # Add backend root to sys.path to ensure hosts package is importable
                import sys
                
                if str(BASE_DIR) not in sys.path:
                    sys.path.insert(0, str(BASE_DIR))

                # Now import using the full module path inside backend/hosts
                from hosts.multiagent.a2a_document_processor import process_audio

                # Process audio file to get transcription
                log_debug(f"Processing audio file for transcription: {file_path}")

                # Change to the multiagent directory so relative paths work
                original_cwd = os.getcwd()
                try:
                    multiagent_dir = HOSTS_DIR / "multiagent"
                    os.chdir(multiagent_dir)

                    transcript = process_audio(str(file_path), return_text=True)
                finally:
                    # Always restore original working directory
                    os.chdir(original_cwd)
                
                if transcript and transcript.strip():
                    log_debug(f"Audio transcription successful. Length: {len(transcript)} characters")
                    return {
                        "success": True,
                        "filename": file.filename or filename,
                        "file_id": file_id,
                        "uri": f"/voice_recordings/{filename}",
                        "size": len(content),
                        "content_type": "audio/wav",
                        "transcript": transcript.strip(),
                        "message": "Voice recording transcribed successfully"
                    }
                else:
                    log_warning("Audio transcription returned empty result")
                    return {
                        "success": False,
                        "error": "Could not transcribe audio - no speech detected or transcription failed",
                        "filename": file.filename or filename,
                        "file_id": file_id
                    }
                    
            except ImportError as e:
                log_error(f"Could not import document processor: {e}")
                return {
                    "success": False,
                    "error": "Audio transcription service not available",
                    "filename": file.filename or filename,
                    "file_id": file_id
                }
            except Exception as e:
                log_error(f"Audio transcription failed: {e} (type: {type(e).__name__})")

                # Try to get more details if it's a RuntimeError from the Azure service
                if "Request failed" in str(e):
                    log_error("Azure Content Understanding service request failed - check audio file format, content, or service configuration")

                return {
                    "success": False,
                    "error": f"Transcription failed: {str(e)}",
                    "filename": file.filename or filename,
                    "file_id": file_id
                }

        except Exception as e:
            log_error(f"Voice upload failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }


    # Add a root endpoint that shows available endpoints
    @app.get("/")
    async def root():
        """Root endpoint with API information."""
        return {
            "service": "A2A Backend API",
            "version": "1.0.0",
            "status": "running",
            "endpoints": {
                "health": "/health",
                "docs": "/docs",
                "openapi": "/openapi.json",
                "conversations": "/conversations/*",
                "agents": "/agents/*",
                "websocket": "ws://localhost:8080/events"
            },
            "websocket_enabled": websocket_streamer is not None,
            "auth_method": "managed_identity"
        }

    # Setup the connection details from environment
    host = os.environ.get('A2A_UI_HOST', '0.0.0.0')
    port = int(os.environ.get('A2A_UI_PORT', '12000'))

    log_info(f"Starting A2A Backend API server on {host}:{port}")
    log_info(f"Health check available at: http://{host}:{port}/health")
    log_info(f"API docs available at: http://{host}:{port}/docs")
    log_info(f"OpenAPI spec available at: http://{host}:{port}/openapi.json")

    # Test database connection
    test_database_connection()

    # Configure uvicorn with log config
    import logging.config
    
    # Create a custom log config that filters schedule API logs
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "suppress_schedules": {
                "()": lambda: type('SuppressScheduleFilter', (logging.Filter,), {
                    'filter': lambda self, record: "GET /api/schedules" not in record.getMessage()
                })()
            }
        },
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(message)s",
                "use_colors": True
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
            }
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr"
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "filters": ["suppress_schedules"]
            }
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO"},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False}
        }
    }

    uvicorn.run(
        app,
        host=host,
        port=port,
        timeout_graceful_shutdown=5,
        log_config=log_config
    )


if __name__ == '__main__':
    main()
