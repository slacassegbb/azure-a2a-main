"""Production backend API server for A2A system.

This starts a FastAPI-only server with WebSocket integration for local development.
Configured with open CORS and hardcoded environment variables.
Exposes only the API endpoints, no UI.

Usage:
    python backend_production.py
"""

import os
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
from log_config import log_debug

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


class HTTPXClientWrapper:
    """Wrapper to return the singleton client where needed."""

    async_client: httpx.AsyncClient = None

    def start(self):
        """ Instantiate the client. Call from the FastAPI startup hook."""
        # Some remote agents (e.g., image generators) stream results slowly, so we
        # need a generous read timeout to avoid dropping long-running SSE streams.
        self.async_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=120.0,
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


async def execute_scheduled_workflow(workflow_name: str, session_id: str, timeout: int = 300):
    """Execute a workflow for the scheduler. Returns result dict.
    
    Note: We use a unique scheduler-specific session ID to prevent
    scheduled workflow messages from appearing in the user's active UI.
    """
    global agent_server
    
    # Generate a unique scheduler session ID to isolate from user sessions
    # This prevents scheduled workflow messages from appearing in the user's conversation
    scheduler_session_id = f"scheduler_{uuid.uuid4().hex[:12]}"
    
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
    global_registry = get_registry()
    session_registry = get_session_registry()
    
    # Extract unique agent names from workflow steps
    agent_names_needed = []
    for step in (workflow.steps or []):
        name = step.get('agentName') or step.get('agent')
        if name and name not in agent_names_needed:
            agent_names_needed.append(name)
    
    print(f"[SCHEDULER] Workflow '{workflow_name}' needs agents: {agent_names_needed}")
    
    # Look up each agent in global registry and enable for scheduler session
    missing_agents = []
    enabled_count = 0
    for agent_name in agent_names_needed:
        agent_config = global_registry.get_agent(agent_name)
        if agent_config:
            # Enable this agent for the scheduler session (use isolated scheduler_session_id)
            was_enabled = session_registry.enable_agent(scheduler_session_id, agent_config)
            if was_enabled:
                enabled_count += 1
                print(f"[SCHEDULER] ✅ Enabled agent '{agent_name}' for session {scheduler_session_id}")
            else:
                print(f"[SCHEDULER] ℹ️ Agent '{agent_name}' already enabled for session {scheduler_session_id}")
        else:
            missing_agents.append(agent_name)
            print(f"[SCHEDULER] ❌ Agent '{agent_name}' NOT FOUND in global registry!")
    
    if missing_agents:
        return {
            "success": False, 
            "error": f"Missing agents in registry: {', '.join(missing_agents)}. Available agents can be found in the Agent Catalog."
        }
    
    print(f"[SCHEDULER] Enabled {enabled_count} agents for session {scheduler_session_id}")
    # --- END ENABLE AGENTS ---
    
    # Build workflow text
    print(f"[SCHEDULER] 📝 Building workflow text from {len(workflow.steps or [])} steps...")
    sorted_steps = sorted(workflow.steps or [], key=lambda s: s.get('order', 0))
    workflow_lines = []
    for i, step in enumerate(sorted_steps):
        agent_name = step.get('agentName') or step.get('agent') or 'Unknown Agent'
        default_desc = 'Use the ' + agent_name + ' agent'
        description = step.get('description', default_desc)
        workflow_lines.append(f"{i+1}. [{agent_name}] {description}")
    workflow_text = "\n".join(workflow_lines)
    
    initial_message = f'Run the "{workflow.name}" workflow.'
    conversation_id = str(uuid.uuid4())
    message_id = f"msg_{uuid.uuid4().hex[:8]}"
    # Use scheduler_session_id for context to isolate from user's active session
    context_id = f"{scheduler_session_id}::{conversation_id}"
    
    print(f"[SCHEDULER] 📝 Workflow text:\n{workflow_text}")
    print(f"[SCHEDULER] 📨 Context ID: {context_id} (isolated from user session {session_id})")
    
    if not agent_server:
        print(f"[SCHEDULER] ❌ agent_server is None!")
        return {"success": False, "error": "Agent server is None"}
    
    if not hasattr(agent_server, 'manager'):
        print(f"[SCHEDULER] ❌ agent_server has no 'manager' attribute!")
        return {"success": False, "error": "Agent server has no manager"}
    
    print(f"[SCHEDULER] ✅ agent_server.manager exists: {type(agent_server.manager)}")
    
    from a2a.types import Message, Part, TextPart, Role
    
    message = Message(
        messageId=message_id,
        contextId=context_id,
        role=Role.user,
        parts=[Part(root=TextPart(text=initial_message))]
    )
    
    print(f"[SCHEDULER] 📩 Message created: {initial_message}")
    
    # Use a shorter timeout for testing (60 seconds instead of 300)
    effective_timeout = min(timeout, 120)
    print(f"[SCHEDULER] ⏱️ Timeout set to {effective_timeout}s")
    
    try:
        start_time = time.time()
        
        print(f"[SCHEDULER] ⏳ Calling agent_server.manager.process_message()...")
        print(f"[SCHEDULER] ⏳ This may take a while if agents are being called...")
        
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
        print(f"[SCHEDULER] ✅ Workflow execution completed in {elapsed_time:.1f}s")
        
        result_text = ""
        if responses:
            if isinstance(responses, list):
                result_text = "\n\n".join(str(r) for r in responses)
            else:
                result_text = str(responses)
        
        print(f"[SCHEDULER] 📄 Result length: {len(result_text)} chars")
        if len(result_text) > 500:
            print(f"[SCHEDULER] 📄 Result preview: {result_text[:500]}...")
        else:
            print(f"[SCHEDULER] 📄 Result: {result_text}")
        
        return {
            "success": True,
            "completed": True,
            "workflow_name": workflow.name,
            "execution_time_seconds": round(elapsed_time, 2),
            "result": result_text
        }
        
    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        print(f"[SCHEDULER] ⏰ TIMEOUT after {elapsed:.1f}s (limit was {effective_timeout}s)")
        return {"success": False, "error": f"Workflow execution timed out after {effective_timeout} seconds"}
    except Exception as e:
        print(f"[SCHEDULER] ❌ Error executing workflow: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup and shutdown."""
    global websocket_streamer, agent_server, workflow_scheduler
    
    print("[INFO] Starting A2A Backend API...")
    
    # Start HTTP client
    httpx_client_wrapper.start()
    
    # WebSocket endpoint is now mounted directly on the main app (see below)
    # No need for a separate server on port 8080
    print("[INFO] WebSocket endpoint available at /events on the main API port")
    
    # Initialize WebSocket streamer with error handling
    try:
        websocket_streamer = await get_websocket_streamer()
        if websocket_streamer:
            print("[INFO] WebSocket streamer initialized successfully")
        else:
            print("[WARNING] WebSocket streamer not available - check configuration")
    except Exception as e:
        print(f"[ERROR] Failed to initialize WebSocket streamer: {type(e).__name__}: {e}")
        print(f"[ERROR] Error details: {str(e)}")
        websocket_streamer = None
    
    # Initialize the conversation server (this registers all the API routes)
    try:
        agent_server = ConversationServer(app, httpx_client_wrapper())
        print("[INFO] Conversation server initialized successfully")
    except Exception as e:
        print(f"[ERROR] Failed to initialize conversation server: {type(e).__name__}: {e}")
        print(f"[ERROR] Error details: {str(e)}")
        # Continue startup even if this fails
    
    # Initialize the workflow scheduler
    try:
        from service.scheduler_service import get_workflow_scheduler, initialize_scheduler, APSCHEDULER_AVAILABLE
        if APSCHEDULER_AVAILABLE:
            workflow_scheduler = get_workflow_scheduler()
            workflow_scheduler.set_workflow_executor(execute_scheduled_workflow)
            await workflow_scheduler.start()
            print(f"[INFO] Workflow scheduler started with {len(workflow_scheduler.schedules)} schedules")
        else:
            print("[WARNING] APScheduler not installed - scheduled workflows disabled")
            print("[INFO] Install with: pip install apscheduler")
    except Exception as e:
        print(f"[WARNING] Failed to initialize workflow scheduler: {type(e).__name__}: {e}")
        # Continue startup even if scheduler fails
    
    print("[INFO] A2A Backend API startup complete")
    
    yield
    
    # Cleanup
    print("[INFO] Shutting down A2A Backend API...")
    
    # Stop workflow scheduler
    if workflow_scheduler:
        try:
            await workflow_scheduler.stop()
            print("[INFO] Workflow scheduler stopped")
        except Exception as e:
            print(f"[WARNING] Error stopping workflow scheduler: {e}")
    
    await httpx_client_wrapper.stop()
    await cleanup_websocket_streamer()
    print("[INFO] A2A Backend API shutdown complete")


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

    @app.get("/api/agents/search")
    async def search_agents(query: str = None, tags: str = None):
        """Search agents by query or tags."""
        try:
            registry = get_registry()
            tag_list = tags.split(',') if tags else None
            agents = registry.search_agents(query=query, tags=tag_list)
            return {
                "success": True,
                "agents": agents
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
            print(f"[ERROR] Login error: {e}")
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
            print(f"[ERROR] Get users error: {e}")
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
            print(f"[ERROR] Get active users error: {e}")
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
            # Check if user already exists
            auth_service._load_users_from_file()  # Reload to get latest data
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
            print(f"[ERROR] Registration error: {e}")
            return LoginResponse(
                success=False,
                message="Registration failed due to server error"
            )

    @app.get("/api/auth/me")
    async def get_current_user_info(current_user: dict = Depends(get_current_user)):
        """Get current user information from JWT token."""
        return {
            "success": True,
            "user": current_user
        }

    @app.get("/api/auth/users")
    async def get_all_users():
        """Get all users (for development/admin purposes)."""
        return {
            "success": True,
            "users": auth_service.get_all_users()
        }

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
    
    @app.get("/api/workflows/list")
    async def list_available_workflows():
        """
        List all available workflows (no authentication required).
        Useful for discovering workflows before running them via API.
        
        Example curl:
            curl http://localhost:12000/api/workflows/list
        """
        workflows = workflow_service.get_all_workflows()
        return {
            "workflows": [
                {
                    "id": w.id,
                    "name": w.name,
                    "description": w.description,
                    "steps_count": len(w.steps) if w.steps else 0,
                    "owner": w.user_id
                }
                for w in workflows
            ]
        }
    
    class WorkflowRunRequest(BaseModel):
        workflow_id: Optional[str] = None
        workflow_name: Optional[str] = None
        session_id: Optional[str] = None
        conversation_id: Optional[str] = None
        initial_message: Optional[str] = None  # Override first step description
        wait_for_completion: bool = False  # If True, wait and return the result
        timeout: int = 300  # Timeout in seconds for synchronous mode (default 5 min)
    
    @app.post("/api/workflows/run")
    async def run_workflow(request: WorkflowRunRequest):
        """
        Execute a workflow by ID or name.
        
        This endpoint allows triggering a workflow execution programmatically
        without going through the UI. The workflow's first step description
        is used as the initial message to kick off the orchestration.
        
        Modes:
        - Async (default): Returns immediately with IDs, workflow runs in background
        - Sync (wait_for_completion=true): Waits for workflow to complete and returns result
        
        Example curl (async - returns immediately):
            curl -X POST http://localhost:12000/api/workflows/run \\
                -H "Content-Type: application/json" \\
                -d '{"workflow_name": "Customer Support Pipeline"}'
        
        Example curl (sync - waits for result):
            curl -X POST http://localhost:12000/api/workflows/run \\
                -H "Content-Type: application/json" \\
                -d '{"workflow_name": "Customer Support Pipeline", "wait_for_completion": true}'
        
        Or by ID:
            curl -X POST http://localhost:12000/api/workflows/run \\
                -H "Content-Type: application/json" \\
                -d '{"workflow_id": "custom-1738435200000", "wait_for_completion": true}'
        """
        import uuid
        import asyncio
        import threading
        from service.server.server import main_loop
        
        # Find the workflow
        workflow = None
        if request.workflow_id:
            workflow = workflow_service.get_workflow(request.workflow_id)
        elif request.workflow_name:
            # Search by name
            all_workflows = workflow_service.get_all_workflows()
            for w in all_workflows:
                if w.name.lower() == request.workflow_name.lower():
                    workflow = w
                    break
        
        if not workflow:
            raise HTTPException(
                status_code=404, 
                detail=f"Workflow not found: {request.workflow_id or request.workflow_name}"
            )
        
        # Generate workflow text from steps
        if not workflow.steps:
            raise HTTPException(status_code=400, detail="Workflow has no steps defined")
        
        # Sort steps by order
        sorted_steps = sorted(workflow.steps, key=lambda s: s.get('order', 0))
        
        # Generate workflow text (same format as frontend - include agent name for routing)
        workflow_lines = []
        for i, step in enumerate(sorted_steps):
            agent_name = step.get('agentName', 'unknown')
            default_desc = 'Use the ' + agent_name + ' agent'
            description = step.get('description', default_desc)
            # Include agent name so orchestrator knows which agent to route to
            workflow_lines.append(f"{i+1}. [{agent_name}] {description}")
        workflow_text = "\n".join(workflow_lines)
        
        # DEBUG: Log the workflow details
        print(f"[WorkflowRun] 📋 WORKFLOW STEPS:")
        for line in workflow_lines:
            print(f"   {line}")
        print(f"[WorkflowRun] 🎯 Workflow Goal: {workflow.goal}")
        
        # Get initial message - always use standard execution message
        # The goal is used separately for completion evaluation, not as the trigger
        if request.initial_message:
            initial_message = request.initial_message
        else:
            # Standard execution message - the workflow steps define what to do
            initial_message = f'Run the "{workflow.name}" workflow.'
        
        # Generate IDs
        session_id = request.session_id or str(uuid.uuid4())
        conversation_id = request.conversation_id or str(uuid.uuid4())
        message_id = f"msg_{uuid.uuid4().hex[:8]}"
        context_id = f"{session_id}::{conversation_id}"
        
        print(f"[WorkflowRun] Starting workflow: {workflow.name}")
        print(f"[WorkflowRun] Initial message: {initial_message}")
        print(f"[WorkflowRun] Context ID: {context_id}")
        print(f"[WorkflowRun] Wait for completion: {request.wait_for_completion}")
        
        # Check if agent_server is available
        if not agent_server or not hasattr(agent_server, 'manager'):
            raise HTTPException(status_code=503, detail="Agent server not available")
        
        # Enable agents in session registry from global registry
        # This ensures the workflow's agents are available for this session
        from service.agent_registry import get_registry, get_session_registry
        registry = get_registry()
        session_registry = get_session_registry()
        
        # Extract agent names from workflow steps
        agent_names = [step.get('agentName') for step in sorted_steps if step.get('agentName')]
        print(f"[WorkflowRun] 🔧 Enabling {len(agent_names)} agents for session {session_id}: {agent_names}")
        
        for agent_name in agent_names:
            agent_config = registry.get_agent(agent_name)
            if agent_config:
                session_registry.enable_agent(session_id, agent_config)
                print(f"[WorkflowRun] ✅ Enabled agent: {agent_name} with URL: {agent_config.get('url', 'N/A')}")
            else:
                print(f"[WorkflowRun] ⚠️ Agent not found in registry: {agent_name}")
        
        # Create the message
        from a2a.types import Message, Part, TextPart, Role
        
        message = Message(
            messageId=message_id,
            contextId=context_id,
            role=Role.user,
            parts=[Part(root=TextPart(text=initial_message))]
        )
        
        # Process message with workflow
        try:
            if request.wait_for_completion:
                # SYNCHRONOUS MODE: Wait for completion and return result
                print(f"[WorkflowRun] Running in SYNC mode (timeout: {request.timeout}s)")
                
                import time
                start_time = time.time()
                
                # Submit the coroutine to the main event loop
                future = asyncio.run_coroutine_threadsafe(
                    agent_server.manager.process_message(
                        message, 
                        agent_mode=None,  # Auto-detect from workflow
                        enable_inter_agent_memory=True,
                        workflow=workflow_text,
                        workflow_goal=workflow.goal  # Pass the workflow's goal for completion evaluation
                    ), 
                    main_loop
                )
                
                # Wait for the result with timeout
                try:
                    responses = future.result(timeout=request.timeout)
                    elapsed_time = time.time() - start_time
                    
                    print(f"[WorkflowRun] ✅ Workflow completed in {elapsed_time:.2f}s")
                    print(f"[WorkflowRun] Responses: {len(responses) if responses else 0}")
                    
                    # Format the responses
                    result_text = ""
                    if responses:
                        if isinstance(responses, list):
                            result_text = "\n\n".join(str(r) for r in responses)
                        else:
                            result_text = str(responses)
                    
                    return {
                        "success": True,
                        "completed": True,
                        "message": f"Workflow '{workflow.name}' completed",
                        "workflow_id": workflow.id,
                        "workflow_name": workflow.name,
                        "session_id": session_id,
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "initial_message": initial_message,
                        "steps_count": len(sorted_steps),
                        "execution_time_seconds": round(elapsed_time, 2),
                        "result": result_text
                    }
                    
                except asyncio.TimeoutError:
                    elapsed_time = time.time() - start_time
                    print(f"[WorkflowRun] ⏱️ Workflow timed out after {elapsed_time:.2f}s")
                    raise HTTPException(
                        status_code=408, 
                        detail=f"Workflow timed out after {request.timeout} seconds. Use wait_for_completion=false for long-running workflows."
                    )
                    
            else:
                # ASYNC MODE: Fire and forget (original behavior)
                print(f"[WorkflowRun] Running in ASYNC mode (fire-and-forget)")
                t = threading.Thread(
                    target=lambda: asyncio.run_coroutine_threadsafe(
                        agent_server.manager.process_message(
                            message, 
                            agent_mode=None,  # Auto-detect from workflow
                            enable_inter_agent_memory=True,
                            workflow=workflow_text,
                            workflow_goal=workflow.goal  # Pass the workflow's goal for completion evaluation
                        ), 
                        main_loop
                    )
                )
                t.start()
                
                return {
                    "success": True,
                    "completed": False,
                    "message": f"Workflow '{workflow.name}' started (async mode)",
                    "workflow_id": workflow.id,
                    "workflow_name": workflow.name,
                    "session_id": session_id,
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "initial_message": initial_message,
                    "steps_count": len(sorted_steps),
                    "note": "Workflow is running in the background. Connect to WebSocket to receive updates."
                }
                
        except HTTPException:
            raise
        except Exception as e:
            print(f"[WorkflowRun] Error starting workflow: {e}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Failed to start workflow: {str(e)}")

    # ==================== ACTIVE WORKFLOW (SESSION-SCOPED) ====================
    # Stores active workflow state per session, synced across collaborative sessions
    
    # In-memory store for active workflows per session
    # Format: { session_id: { "workflow": str, "name": str, "goal": str } }
    active_workflows_store: Dict[str, Dict[str, str]] = {}
    
    class ActiveWorkflowRequest(BaseModel):
        workflow: str = ""
        name: str = ""
        goal: str = ""
    
    @app.get("/api/active-workflow")
    async def get_active_workflow(session_id: str = Query(..., description="Session ID to get active workflow for")):
        """
        Get the active workflow for a session.
        Used by all users in a collaborative session to see the same active workflow.
        
        Example curl:
            curl "http://localhost:12000/api/active-workflow?session_id=abc123"
        """
        if session_id in active_workflows_store:
            return active_workflows_store[session_id]
        return {"workflow": "", "name": "", "goal": ""}
    
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
            active_workflows_store[session_id] = {
                "workflow": request.workflow,
                "name": request.name,
                "goal": request.goal
            }
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
                print(f"[ActiveWorkflow] Failed to broadcast: {e}")
        return {"success": True, "session_id": session_id}
    
    @app.delete("/api/active-workflow")
    async def clear_active_workflow(session_id: str = Query(..., description="Session ID to clear active workflow for")):
        """
        Clear the active workflow for a session.
        
        Example curl:
            curl -X DELETE "http://localhost:12000/api/active-workflow?session_id=abc123"
        """
        if session_id in active_workflows_store:
            del active_workflows_store[session_id]
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
                print(f"[ActiveWorkflow] Failed to broadcast clear: {e}")
        return {"success": True, "session_id": session_id}

    # ==================== MULTI-WORKFLOW API ENDPOINTS ====================
    # New API for managing multiple active workflows per session
    
    # Store for multi-workflow state (separate from legacy single workflow)
    multi_workflows_store: Dict[str, List[Dict[str, Any]]] = {}
    
    @app.get("/api/active-workflows")
    async def get_active_workflows(session_id: str = Query(..., description="Session ID")):
        """
        Get all active workflows for a session.
        Returns empty list if no workflows are active.
        """
        workflows = multi_workflows_store.get(session_id, [])
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
        multi_workflows_store[session_id] = workflows
        
        # Broadcast update to all users in session
        try:
            if websocket_streamer:
                await websocket_streamer._send_event(
                    "active_workflows_changed",
                    {"contextId": session_id, "workflows": workflows},
                    partition_key=session_id
                )
        except Exception as e:
            print(f"[ActiveWorkflows] Failed to broadcast: {e}")
        
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
        
        if session_id not in multi_workflows_store:
            multi_workflows_store[session_id] = []
        
        # Avoid duplicates by ID
        existing_ids = {w.get("id") for w in multi_workflows_store[session_id]}
        if workflow.get("id") not in existing_ids:
            multi_workflows_store[session_id].append(workflow)
        
        workflows = multi_workflows_store[session_id]
        
        # Broadcast update
        try:
            if websocket_streamer:
                await websocket_streamer._send_event(
                    "active_workflows_changed",
                    {"contextId": session_id, "workflows": workflows},
                    partition_key=session_id
                )
        except Exception as e:
            print(f"[ActiveWorkflows] Failed to broadcast add: {e}")
        
        return {"success": True, "workflows": workflows}
    
    @app.delete("/api/active-workflows/{workflow_id}")
    async def remove_active_workflow(
        workflow_id: str,
        session_id: str = Query(..., description="Session ID")
    ):
        """
        Remove a specific workflow from the active workflows list.
        """
        if session_id in multi_workflows_store:
            multi_workflows_store[session_id] = [
                w for w in multi_workflows_store[session_id] 
                if w.get("id") != workflow_id
            ]
        
        workflows = multi_workflows_store.get(session_id, [])
        
        # Broadcast update
        try:
            if websocket_streamer:
                await websocket_streamer._send_event(
                    "active_workflows_changed",
                    {"contextId": session_id, "workflows": workflows},
                    partition_key=session_id
                )
        except Exception as e:
            print(f"[ActiveWorkflows] Failed to broadcast remove: {e}")
        
        return {"success": True, "workflows": workflows}
    
    @app.delete("/api/active-workflows")
    async def clear_active_workflows(session_id: str = Query(..., description="Session ID")):
        """
        Clear all active workflows for a session.
        """
        if session_id in multi_workflows_store:
            del multi_workflows_store[session_id]
        
        # Broadcast update
        try:
            if websocket_streamer:
                await websocket_streamer._send_event(
                    "active_workflows_changed",
                    {"contextId": session_id, "workflows": []},
                    partition_key=session_id
                )
        except Exception as e:
            print(f"[ActiveWorkflows] Failed to broadcast clear: {e}")
        
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
            print(f"[ERROR] Failed to list workflows: {e}")
            import traceback
            traceback.print_exc()
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
    
    @app.get("/api/schedules/debug")
    async def debug_scheduler():
        """
        Debug endpoint to check APScheduler status.
        
        Example curl:
            curl http://localhost:12000/api/schedules/debug
        """
        scheduler = get_workflow_scheduler()
        jobs = []
        if scheduler.scheduler:
            for job in scheduler.scheduler.get_jobs():
                jobs.append({
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger)
                })
        return {
            "scheduler_running": scheduler._is_running,
            "scheduler_exists": scheduler.scheduler is not None,
            "jobs_count": len(jobs),
            "jobs": jobs,
            "schedules_in_memory": len(scheduler.schedules)
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
            print(f"[Scheduler] Error creating schedule: {e}")
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
            print(f"[Scheduler] Error updating schedule: {e}")
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
    async def clear_memory():
        """Clear all stored interactions from the Azure vector memory index."""
        try:
            # Access the host agent through the conversation server's manager
            if agent_server and hasattr(agent_server, 'manager'):
                # Ensure the host agent is initialized
                await agent_server.manager.ensure_host_agent_initialized()
                
                # Access the FoundryHostAgent2 instance and clear memory
                if hasattr(agent_server.manager, '_host_agent') and agent_server.manager._host_agent:
                    success = agent_server.manager._host_agent.clear_memory_index()
                    if success:
                        return {
                            "success": True,
                            "message": "Memory index cleared successfully"
                        }
                    else:
                        return {
                            "success": False,
                            "message": "Failed to clear memory index"
                        }
                else:
                    return {
                        "success": False,
                        "message": "Host agent not initialized"
                    }
            else:
                return {
                    "success": False,
                    "message": "Agent server not available"
                }
        except Exception as e:
            print(f"Error clearing memory: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "message": f"Error clearing memory: {str(e)}"
            }

    @app.post("/start-agent")
    async def start_agent(request: Request):
        """Start an agent by executing a command on the local system."""
        try:
            import subprocess
            import os
            import time
            import json
            
            from log_config import log_debug
            # Parse the JSON body
            body = await request.json()
            agent_id = body.get("agentId")
            command = body.get("command")
            args = body.get("args", [])
            working_directory = body.get("workingDirectory")
            
            log_debug(f"Starting agent {agent_id}")
            log_debug(f"Command: {command} {' '.join(args)}")
            log_debug(f"Working directory: {working_directory}")
            
            # Security check - only allow specific agents and paths
            allowed_agents = ["classification-triage"]
            if agent_id not in allowed_agents:
                print(f"[ERROR] Agent {agent_id} not in allowed list")
                return {
                    "success": False,
                    "message": f"Agent {agent_id} is not configured for remote startup"
                }
            
            # Verify the working directory exists
            if not os.path.exists(working_directory):
                print(f"[ERROR] Working directory does not exist: {working_directory}")
                return {
                    "success": False,
                    "message": f"Working directory does not exist: {working_directory}"
                }
            
            # Build the full command
            full_command = [command] + args
            log_debug(f"Full command: {full_command}")
            
            # For Windows, create a batch file that runs the command and keeps the window open
            if os.name == 'nt':
                import tempfile
                
                # Create batch file content with headers and command display
                batch_content = f"""@echo off
echo ================================================
echo Starting Agent: {agent_id}
echo Directory: {working_directory}
echo Command: {' '.join(full_command)}
echo ================================================
echo.
cd /d "{working_directory}"
{' '.join(full_command)}
echo.
echo ================================================
echo Command finished. Exit code: %errorlevel%
echo ================================================
pause
"""
                
                # Create temporary batch file
                with tempfile.NamedTemporaryFile(mode='w', suffix='.bat', delete=False) as batch_file:
                    batch_file.write(batch_content)
                    batch_path = batch_file.name
                
                log_debug(f"Created batch file: {batch_path}")
                log_debug(f"Batch content: {batch_content}")
                
                # Create PowerShell script file that inherits current environment
                ps_content = f"""Write-Host "================================================"
Write-Host "Starting Agent: {agent_id}"
Write-Host "Directory: {working_directory}"
Write-Host "Command: {' '.join(full_command)}"
Write-Host "================================================"
Write-Host ""
Set-Location "{working_directory}"
{' '.join(full_command)}
Write-Host ""
Write-Host "================================================"
Write-Host "Command finished. Exit code: $LASTEXITCODE"
Write-Host "================================================"
Read-Host "Press Enter to close this window"
"""
                
                # Create temporary PowerShell script file
                with tempfile.NamedTemporaryFile(mode='w', suffix='.ps1', delete=False) as ps_file:
                    ps_file.write(ps_content)
                    ps_path = ps_file.name
                
                log_debug(f"Created PowerShell script: {ps_path}")
                log_debug(f"PowerShell content: {ps_content}")
                
                # Start the PowerShell script in a new window
                # Inherit current environment to preserve Azure authentication
                env = os.environ.copy()
                process = subprocess.Popen(
                    ['powershell', '-Command', f'Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "{ps_path}"'],
                    shell=True,
                    env=env
                )
            else:
                # For non-Windows systems
                process = subprocess.Popen(
                    full_command,
                    cwd=working_directory,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
            
            # Give the process a moment to start
            time.sleep(1)
            
            # For Windows 'start' command, exit code 0 means the window was opened successfully
            # Don't treat this as an error
            poll_result = process.poll()
            if poll_result is not None and poll_result != 0:
                # Process terminated with an actual error (not 0)
                stdout, stderr = process.communicate()
                print(f"[ERROR] Process terminated with error code {poll_result}")
                print(f"[ERROR] STDOUT: {stdout}")
                print(f"[ERROR] STDERR: {stderr}")
                
                # Handle None values properly
                error_msg = stderr[:200] if stderr else "No error output"
                
                return {
                    "success": False,
                    "message": f"Agent failed to start. Exit code: {poll_result}. Error: {error_msg}",
                    "stdout": stdout,
                    "stderr": stderr
                }
            
            print(f"[SUCCESS] Agent {agent_id} console window opened successfully")
            return {
                "success": True,
                "message": f"Agent {agent_id} started successfully in new console window",
                "process_id": process.pid,
                "command": f"{command} {' '.join(args)}",
                "working_directory": working_directory
            }
            
        except Exception as e:
            print(f"[ERROR] Exception starting agent: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "message": f"Error starting agent: {str(e)}"
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
                print(f"✅ Using managed identity for blob storage: {account_url}")
            elif connection_string:
                # Use connection string authentication (legacy)
                blob_service_client = BlobServiceClient.from_connection_string(connection_string)
                print(f"✅ Using connection string for blob storage")
            else:
                print(f"[WARN] No Azure Storage configuration found, returning local path")
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
                    from log_config import log_debug
                    blob_url = f"{blob_client.url}?{sas_token}"
                    log_debug(f"File uploaded to Azure Blob: {blob_url[:100]}...")
                    return blob_url
            
            # For managed identity, return blob URL directly (container must be public or use user delegation SAS)
            print(f"[INFO] File uploaded to Azure Blob (managed identity): {blob_client.url}")
            return blob_client.url
                
        except Exception as e:
            print(f"[ERROR] Azure Blob upload failed: {e}, falling back to local storage")
            import traceback
            traceback.print_exc()
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
            print(f"[ERROR] File upload failed: {e}")
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
            print(f"[INFO] Found {len(processed_filenames)} processed files in memory for session {session_id}")
            
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
                        print(f"[DEBUG] Skipping 0-byte blob: {blob.name}")
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
                
                print(f"[INFO] Listed {len(files)} files from blob storage for session: {session_id}")
                
            except Exception as blob_error:
                print(f"[WARN] Blob storage unavailable, falling back to local filesystem: {blob_error}")
                
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
                
                print(f"[INFO] Listed {len(files)} files from local filesystem for session: {session_id}")
            
            # Also include agent-generated files from the registry
            try:
                from service.agent_file_registry import get_agent_files
                agent_files = get_agent_files(session_id)
                if agent_files:
                    files.extend(agent_files)
                    print(f"[INFO] Added {len(agent_files)} agent-generated files for session: {session_id}")
            except Exception as agent_files_error:
                print(f"[WARN] Failed to get agent files: {agent_files_error}")
            
            # Sort by upload date (most recent first)
            files.sort(key=lambda f: f.get('uploadedAt', ''), reverse=True)
            
            return {
                "success": True,
                "files": files
            }
            
        except Exception as e:
            print(f"[ERROR] Failed to list files: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e)
            }

    @app.delete("/api/files/{file_id}")
    async def delete_file(file_id: str, request: Request):
        """Delete a file from blob storage and local filesystem.
        
        Gracefully handles expired/missing files - always returns success
        even if the file doesn't exist (idempotent operation).
        """
        try:
            # Extract session_id from header
            session_id = request.headers.get("X-Session-ID")
            if not session_id:
                return {"success": False, "error": "Missing X-Session-ID header"}
            
            deleted_from_blob = False
            deleted_from_local = False
            
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
                
                # Search for blobs matching this file_id
                # Could be: uploads/{session_id}/{file_id}/* or image-generator/{file_id}/*
                deleted_count = 0
                for blob in container_client.list_blobs():
                    # Check if this blob matches the file_id
                    if file_id in blob.name:
                        parts = blob.name.split('/')
                        # Verify it's actually the file_id we want (not just a substring match)
                        if file_id in parts:
                            try:
                                blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob.name)
                                blob_client.delete_blob()
                                deleted_count += 1
                                print(f"[INFO] Deleted blob: {blob.name}")
                            except Exception as delete_err:
                                # Ignore errors (file might be expired/already deleted)
                                print(f"[WARN] Could not delete blob {blob.name}: {delete_err}")
                
                if deleted_count > 0:
                    deleted_from_blob = True
                    print(f"[INFO] Deleted {deleted_count} blob(s) for file_id: {file_id}")
                else:
                    print(f"[INFO] No blobs found for file_id: {file_id} (might be expired/already deleted)")
                
            except Exception as blob_error:
                # Don't fail if blob storage is unavailable or file doesn't exist
                print(f"[WARN] Blob storage delete failed (this is OK): {blob_error}")
            
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
                                    print(f"[INFO] Deleted local file: {file_path}")
                                elif file_path.is_dir():
                                    import shutil
                                    shutil.rmtree(file_path)
                                    deleted_from_local = True
                                    print(f"[INFO] Deleted local directory: {file_path}")
                            except Exception as delete_err:
                                print(f"[WARN] Could not delete local file {file_path}: {delete_err}")
            except Exception as local_error:
                print(f"[WARN] Local filesystem delete failed (this is OK): {local_error}")
            
            # Always return success (idempotent operation)
            return {
                "success": True,
                "deleted_from_blob": deleted_from_blob,
                "deleted_from_local": deleted_from_local,
                "message": "File deleted successfully" if (deleted_from_blob or deleted_from_local) else "File not found (might be expired or already deleted)"
            }
        
        except Exception as e:
            # Even on error, return success to prevent UI errors
            print(f"[ERROR] Error deleting file: {e}")
            import traceback
            traceback.print_exc()
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
            
            print(f"[INFO] Processing file: {filename} (id: {file_id}, session: {session_id})")
            
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
                            print(f"[INFO] Downloaded {len(file_bytes)} bytes from Azure Blob")
                except Exception as blob_err:
                    print(f"[WARN] Could not download from blob: {blob_err}")
            
            # Try local filesystem
            if file_bytes is None:
                local_path = UPLOADS_DIR / session_id / file_id
                if local_path.exists():
                    for file_path in local_path.iterdir():
                        if file_path.is_file():
                            with open(file_path, 'rb') as f:
                                file_bytes = f.read()
                            print(f"[INFO] Read {len(file_bytes)} bytes from local filesystem")
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
                    print(f"[INFO] Document processing completed for: {filename}")
                    
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
                                        print(f"[INFO] Set blob metadata status=analyzed for: {blob_path}")
                                        break
                                except Exception:
                                    continue
                    except Exception as meta_err:
                        print(f"[WARN] Could not set blob metadata: {meta_err}")
                    
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
                    print(f"[WARN] Document processing failed for {filename}: {error_msg}")
                    return {
                        "success": False,
                        "error": error_msg
                    }
                    
            except ImportError as e:
                print(f"[ERROR] Could not import document processor: {e}")
                return {"success": False, "error": "Document processor not available"}
            except Exception as process_err:
                print(f"[ERROR] Document processing error: {process_err}")
                import traceback
                traceback.print_exc()
                return {"success": False, "error": str(process_err)}
        
        except Exception as e:
            print(f"[ERROR] Error in process_file endpoint: {e}")
            import traceback
            traceback.print_exc()
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
                    print(f"[WARNING] Audio transcription returned empty result")
                    return {
                        "success": False,
                        "error": "Could not transcribe audio - no speech detected or transcription failed",
                        "filename": file.filename or filename,
                        "file_id": file_id
                    }
                    
            except ImportError as e:
                print(f"[ERROR] Could not import document processor: {e}")
                return {
                    "success": False,
                    "error": "Audio transcription service not available",
                    "filename": file.filename or filename,
                    "file_id": file_id
                }
            except Exception as e:
                print(f"[ERROR] Audio transcription failed: {e}")
                print(f"[ERROR] Exception type: {type(e).__name__}")
                
                # Try to get more details if it's a RuntimeError from the Azure service
                if "Request failed" in str(e):
                    print(f"[ERROR] Azure Content Understanding service request failed")
                    print(f"[ERROR] This usually indicates an issue with the audio file format, content, or service configuration")
                
                return {
                    "success": False,
                    "error": f"Transcription failed: {str(e)}",
                    "filename": file.filename or filename,
                    "file_id": file_id
                }
            
        except Exception as e:
            print(f"[ERROR] Voice upload failed: {e}")
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

    print(f"[INFO] Starting A2A Backend API server on {host}:{port}")
    print(f"[INFO] Health check available at: http://{host}:{port}/health")
    print(f"[INFO] API docs available at: http://{host}:{port}/docs")
    print(f"[INFO] OpenAPI spec available at: http://{host}:{port}/openapi.json")

    uvicorn.run(
        app,
        host=host,
        port=port,
        timeout_graceful_shutdown=5,
        access_log=True,  # Enable access logs for API monitoring
    )


if __name__ == '__main__':
    main()
