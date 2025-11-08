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
UPLOADS_DIR = BASE_DIR / "uploads"
HOSTS_DIR = BASE_DIR / "hosts"

# Ensure critical directories exist when the backend boots
DATA_DIR.mkdir(parents=True, exist_ok=True)
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
from fastapi import FastAPI, UploadFile, File, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from service.server.server import ConversationServer
from service.websocket_streamer import get_websocket_streamer, cleanup_websocket_streamer
from service.websocket_server import start_websocket_server, stop_websocket_server, set_auth_service
from service.agent_registry import get_registry
from pydantic import BaseModel
from datetime import datetime, timedelta, UTC
import jwt
import hashlib
import json
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

# Authentication constants and classes
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")
ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")

@dataclass
class User:
    user_id: str
    email: str
    password_hash: str
    name: str
    role: str
    description: str
    skills: List[str]
    color: str
    created_at: datetime
    last_login: Optional[datetime] = None

class AuthService:
    """Handles user authentication and JWT token management using JSON file storage."""
    
    def __init__(self, users_file: Path | str = DATA_DIR / "users.json"):
        self.users_file = Path(users_file)
        self.users: Dict[str, User] = {}
        # Track active users (user_data dict keyed by user_id)
        self.active_users: Dict[str, Dict[str, Any]] = {}
        
        # Load users from JSON file
        self._load_users_from_file()
    
    def _load_users_from_file(self):
        """Load users from JSON file."""
        try:
            with open(self.users_file, 'r') as f:
                data = json.load(f)
                for user_data in data.get('users', []):
                    user = User(
                        user_id=user_data['user_id'],
                        email=user_data['email'],
                        password_hash=user_data['password_hash'],
                        name=user_data['name'],
                        role=user_data.get('role', ''),
                        description=user_data.get('description', ''),
                        skills=user_data.get('skills', []),
                        color=user_data.get('color', '#6B7280'),
                        created_at=datetime.fromisoformat(user_data['created_at'].replace('Z', '+00:00')),
                        last_login=datetime.fromisoformat(user_data['last_login'].replace('Z', '+00:00')) if user_data.get('last_login') else None
                    )
                    self.users[user.email] = user
            print(f"[AuthService] Loaded {len(self.users)} users from {self.users_file}")
        except FileNotFoundError:
            print(f"[AuthService] Users file {self.users_file} not found, creating with default users")
            self._create_default_users_file()
        except json.JSONDecodeError as e:
            print(f"[AuthService] Error parsing {self.users_file}: {e}")
            self._create_default_users_file()
        except Exception as e:
            print(f"[AuthService] Error loading users: {e}")
            self._create_default_users_file()
    
    def _create_default_users_file(self):
        """Create default users file with test users."""
        default_users = [
            {"email": "simon@example.com", "password": "simon123", "name": "Simon", "role": "Product Manager", "description": "Experienced product manager with focus on AI and automation tools", "skills": ["Product Strategy", "User Research", "Agile Development", "AI/ML Products"], "color": "#3B82F6"},
            {"email": "admin@example.com", "password": "admin123", "name": "Admin", "role": "System Administrator", "description": "Full system administrator with expertise in cloud infrastructure and security", "skills": ["System Administration", "Cloud Architecture", "Security", "DevOps"], "color": "#EF4444"},
            {"email": "test@example.com", "password": "test123", "name": "Test User", "role": "Software Developer", "description": "Full-stack developer specializing in web applications and APIs", "skills": ["JavaScript", "Python", "React", "Node.js", "API Development"], "color": "#10B981"},
        ]
        
        users_data = {"users": []}
        for i, user_data in enumerate(default_users, 1):
            password_hash = self._hash_password(user_data["password"])
            user_record = {
                "user_id": f"user_{i}",
                "email": user_data["email"],
                "password_hash": password_hash,
                "name": user_data["name"],
                "role": user_data["role"],
                "description": user_data["description"],
                "skills": user_data["skills"],
                "color": user_data["color"],
                "created_at": datetime.now(UTC).isoformat().replace('+00:00', 'Z'),
                "last_login": None
            }
            users_data["users"].append(user_record)
            
            # Also add to memory
            user = User(
                user_id=user_record["user_id"],
                email=user_record["email"],
                password_hash=password_hash,
                name=user_record["name"],
                role=user_record["role"],
                description=user_record["description"],
                skills=user_record["skills"],
                color=user_record["color"],
                created_at=datetime.now(UTC)
            )
            self.users[user.email] = user
        
        # Save to file
        with open(self.users_file, 'w') as f:
            json.dump(users_data, f, indent=2)
        print(f"[AuthService] Created {self.users_file} with {len(default_users)} default users")
    
    def _save_users_to_file(self):
        """Save current users to JSON file."""
        users_data = {"users": []}
        for user in self.users.values():
            user_record = {
                "user_id": user.user_id,
                "email": user.email,
                "password_hash": user.password_hash,
                "name": user.name,
                "role": user.role,
                "description": user.description,
                "skills": user.skills,
                "color": user.color,
                "created_at": user.created_at.isoformat().replace('+00:00', 'Z'),
                "last_login": user.last_login.isoformat().replace('+00:00', 'Z') if user.last_login else None
            }
            users_data["users"].append(user_record)
        
        with open(self.users_file, 'w') as f:
            json.dump(users_data, f, indent=2)
    
    def _hash_password(self, password: str) -> str:
        """Hash a password using SHA-256."""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def create_user(self, email: str, password: str, name: str, role: str = "User", description: str = "", skills: List[str] = None, color: str = "#6B7280") -> Optional[User]:
        """Create a new user and save to file."""
        if email in self.users:
            return None
            
        user_id = f"user_{len(self.users) + 1}"
        password_hash = self._hash_password(password)
        
        user = User(
            user_id=user_id,
            email=email,
            password_hash=password_hash,
            name=name,
            role=role,
            description=description,
            skills=skills or [],
            color=color,
            created_at=datetime.now(UTC)
        )
        
        self.users[email] = user
        # Save to file whenever a new user is created
        self._save_users_to_file()
        return user
    
    def authenticate_user(self, email: str, password: str) -> Optional[User]:
        """Authenticate a user with email and password - always reads from JSON file."""
        # Always reload users from file to get latest data
        self._load_users_from_file()
        
        user = self.users.get(email)
        if not user:
            return None
            
        password_hash = self._hash_password(password)
        if password_hash != user.password_hash:
            return None
            
        # Update last login and save to file
        user.last_login = datetime.now(UTC)
        self._save_users_to_file()
        return user
    
    def create_access_token(self, user: User, expires_delta: Optional[timedelta] = None) -> str:
        """Create a JWT access token for a user."""
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(hours=24)
            
        to_encode = {
            "sub": user.email,
            "user_id": user.user_id,
            "name": user.name,
            "exp": expire,
            "iat": datetime.utcnow()
        }
        
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify and decode a JWT token - always reads from JSON file."""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            email: str = payload.get("sub")
            if email is None:
                return None
                
            # Always reload users from file to get latest data
            self._load_users_from_file()
            
            # Check if user still exists
            user = self.users.get(email)
            if user is None:
                return None
                
            return {
                "user_id": payload.get("user_id"),
                "email": email,
                "name": payload.get("name"),
                "exp": payload.get("exp")
            }
        except jwt.ExpiredSignatureError:
            return None
        except jwt.JWTError:
            return None
    
    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        return self.users.get(email)
    
    def get_all_users(self) -> List[Dict[str, Any]]:
        """Get all users (without password hashes)."""
        return [
            {
                "user_id": user.user_id,
                "email": user.email,
                "name": user.name,
                "role": user.role,
                "description": user.description,
                "skills": user.skills,
                "color": user.color,
                "created_at": user.created_at.isoformat(),
                "last_login": user.last_login.isoformat() if user.last_login else None
            }
            for user in self.users.values()
        ]
    
    def add_active_user(self, user_data: Dict[str, Any]):
        """Add a user to the active users list."""
        user_id = user_data.get("user_id")
        if user_id:
            self.active_users[user_id] = user_data
            print(f"[AuthService] Added active user: {user_data.get('name', 'Unknown')} ({user_data.get('email', 'No email')})")
    
    def remove_active_user(self, user_data: Dict[str, Any]):
        """Remove a user from the active users list."""
        user_id = user_data.get("user_id")
        if user_id and user_id in self.active_users:
            removed_user = self.active_users.pop(user_id)
            print(f"[AuthService] Removed active user: {removed_user.get('name', 'Unknown')} ({removed_user.get('email', 'No email')})")
    
    def get_active_users(self) -> List[Dict[str, Any]]:
        """Get list of currently active users."""
        active_users_list = []
        for user_data in self.active_users.values():
            # Get full user details from our user storage
            user = self.get_user_by_email(user_data.get("email", ""))
            if user:
                active_users_list.append({
                    "user_id": user.user_id,
                    "email": user.email,
                    "name": user.name,
                    "role": user.role,
                    "description": user.description,
                    "skills": user.skills,
                    "color": user.color,
                    "created_at": user.created_at.isoformat(),
                    "last_login": user.last_login.isoformat() if user.last_login else None,
                    "status": "active"  # Mark as active since they're in the active list
                })
        return active_users_list


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup and shutdown."""
    global websocket_streamer, agent_server
    
    print("[INFO] Starting A2A Backend API...")
    
    # Start HTTP client
    httpx_client_wrapper.start()
    
    # Start WebSocket server for UI communication
    try:
        start_websocket_server(host="localhost", port=8080)
        print("[INFO] WebSocket server started successfully on ws://localhost:8080")
        
        # Give the WebSocket server a moment to start listening
        import asyncio
        await asyncio.sleep(2)
        
    except Exception as e:
        print(f"[ERROR] Failed to start WebSocket server: {e}")
        import traceback
        print(f"[ERROR] WebSocket server traceback: {traceback.format_exc()}")
    
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
    
    print("[INFO] A2A Backend API startup complete")
    
    yield
    
    # Cleanup
    print("[INFO] Shutting down A2A Backend API...")
    await httpx_client_wrapper.stop()
    await cleanup_websocket_streamer()
    stop_websocket_server()
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
            base_url = f"http://{agent_url}" if not agent_url.startswith('http') else agent_url
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
    async def get_active_users():
        """Get currently active/logged-in users."""
        try:
            active_users = auth_service.get_active_users()
            
            return {
                "success": True,
                "users": active_users,
                "total_active": len(active_users)
            }
            
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
    def upload_to_azure_blob(file_id: str, file_name: str, file_bytes: bytes, mime_type: str) -> str:
        """Upload file to Azure Blob Storage and return public SAS URL."""
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
                return f"/uploads/{file_id}"
            
            container_name = os.getenv('AZURE_BLOB_CONTAINER', 'a2a-files')
            
            # Generate blob name
            safe_file_name = file_name.replace('/', '_').replace('\\', '_')
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
            return f"/uploads/{file_id}"

    # Add file upload endpoint
    @app.post("/upload")
    async def upload_file(file: UploadFile = File(...)):
        """Upload a file and return file information for A2A processing."""
        try:
            # Generate unique file ID
            file_id = str(uuid.uuid4())
            
            # Get file extension
            file_extension = ""
            if file.filename and "." in file.filename:
                file_extension = "." + file.filename.split(".")[-1]
            
            # Create unique filename with extension
            filename = f"{file_id}{file_extension}"
            file_path = UPLOADS_DIR / filename

            # Read file content
            content = await file.read()
            
            from log_config import log_debug
            # Save file locally (as backup)
            with open(file_path, "wb") as buffer:
                buffer.write(content)
            
            log_debug(f"File uploaded: {file.filename} -> {filename} ({len(content)} bytes)")
            
            # Upload to Azure Blob and get public SAS URL
            blob_url = upload_to_azure_blob(
                file_id=file_id,
                file_name=file.filename or filename,
                file_bytes=content,
                mime_type=file.content_type or 'application/octet-stream'
            )
            
            return {
                "success": True,
                "filename": file.filename,
                "file_id": file_id,
                "uri": blob_url,  # Now returns Azure Blob SAS URL
                "size": len(content),
                "content_type": file.content_type
            }
            
        except Exception as e:
            print(f"[ERROR] File upload failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # Add voice upload endpoint with transcription
    @app.post("/upload-voice")
    async def upload_voice(file: UploadFile = File(...)):
        """Upload a voice recording, save as WAV, and transcribe to text using A2A document processor."""
        try:
            # Create voice recordings directory inside the backend folder
            voice_dir = BASE_DIR / "voice_recordings"
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
            
            log_debug(f"Voice file uploaded: {file.filename} -> {filename} ({len(content)} bytes)")
            
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
