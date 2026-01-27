"""WebSocket Server for A2A Events

This module provides a WebSocket server that runs alongside FastAPI
to stream events to the UI in real-time.
"""

import asyncio
import json
import logging
import os
import threading
import time
import requests
import sys
import urllib3
from pathlib import Path

# Disable SSL warnings for Azure Container Apps internal communication
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from typing import Dict, Any, Set, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import JSONResponse
import uvicorn
from urllib.parse import parse_qs

# Add backend directory to path for log_config import
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from log_config import log_websocket_debug, log_info, log_error, log_warning
from utils.tenant import get_tenant_from_context, is_tenant_aware_context
from service.collaborative_sessions import get_session_manager, CollaborativeSessionManager, get_online_users_from_connections

logger = logging.getLogger(__name__)

# Import the real AuthService
auth_service = None

def set_auth_service(service):
    """Set the AuthService instance to be used by the WebSocket server."""
    global auth_service
    auth_service = service
    logger.info(f"[WebSocket] AuthService set: {type(service)}")

class AuthenticatedConnection:
    """Represents an authenticated WebSocket connection."""
    def __init__(self, websocket: WebSocket, user_data: Dict[str, Any]):
        self.websocket = websocket
        self.user_data = user_data
        self.connected_at = time.time()
    
    @property
    def user_id(self) -> str:
        return self.user_data.get("user_id", "anonymous")
    
    @property
    def username(self) -> str:
        return self.user_data.get("name", "Anonymous")
    
    @property
    def email(self) -> str:
        return self.user_data.get("email", "")


class WebSocketManager:
    """Manages WebSocket connections and event broadcasting with tenant isolation."""
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.authenticated_connections: Dict[WebSocket, AuthenticatedConnection] = {}
        # Tenant isolation: Map tenant_id -> set of WebSocket connections
        self.tenant_connections: Dict[str, Set[WebSocket]] = {}
        # Map WebSocket -> tenant_id for reverse lookup
        self.connection_tenants: Dict[WebSocket, str] = {}
        # Map user_id -> set of WebSockets for sending direct messages (user may have multiple tabs)
        self.user_connections: Dict[str, Set[WebSocket]] = {}
        self.event_history: List[Dict[str, Any]] = []
        # Tenant-scoped event history
        self.tenant_event_history: Dict[str, List[Dict[str, Any]]] = {}
        self.max_history = 100
        # Backend URL for fetching agent registry
        # In Azure Container Apps, use internal service discovery or full URL
        self.backend_host = os.getenv("BACKEND_HOST", "localhost")
        self.backend_port = int(os.getenv("BACKEND_PORT", "12000"))
        # Session ID generated at server startup - used to detect backend restarts
        # Frontend clears file history when session_id changes
        import uuid
        self.session_id = str(uuid.uuid4())
        logger.info(f"WebSocket server session ID: {self.session_id}")
    
    def get_agent_registry(self) -> List[Dict[str, Any]]:
        """Get current agent registry from the backend."""
        max_retries = 1
        retry_delay = 3
        
        for attempt in range(max_retries + 1):
            try:
                # Try to get agents from the backend's agent registry
                # Use https for port 443 (Azure Container Apps public endpoint)
                if self.backend_port == 443:
                    backend_url = f"https://{self.backend_host}/agents"
                else:
                    backend_url = f"http://{self.backend_host}:{self.backend_port}/agents"
                
                logger.info(f"Fetching agent registry from: {backend_url}")
                # Disable SSL verification for Azure Container Apps internal communication
                response = requests.get(backend_url, timeout=20, verify=False)
                
                if response.status_code == 200:
                    agents_data = response.json()
                    
                    # Convert backend agent format to UI format
                    agents = []
                    for agent_data in agents_data.get('agents', []):
                        agent_info = {
                            'name': agent_data.get('name', 'Unknown Agent'),
                            'description': agent_data.get('description', ''),
                            'url': agent_data.get('url'),
                            'version': agent_data.get('version', ''),
                            'iconUrl': agent_data.get('iconUrl'),
                            'provider': agent_data.get('provider'),
                            'documentationUrl': agent_data.get('documentationUrl'),
                            'capabilities': agent_data.get('capabilities', {}),
                            'skills': agent_data.get('skills', []),
                            'defaultInputModes': agent_data.get('defaultInputModes', []),
                            'defaultOutputModes': agent_data.get('defaultOutputModes', []),
                            'status': agent_data.get('status', 'unknown'),  # Use actual status from backend
                            'avatar': agent_data.get('iconUrl') or '/placeholder.svg?height=32&width=32',
                            'type': agent_data.get('type', 'remote')
                        }
                        agents.append(agent_info)
                    
                    logger.info(f"Retrieved {len(agents)} agents from backend registry")
                    return agents
                else:
                    if attempt < max_retries:
                        time.sleep(retry_delay)
                        continue
                    
            except Exception as e:
                log_websocket_debug(f"Error getting agents from backend (attempt {attempt + 1}): {e}")
                if attempt < max_retries:
                    log_websocket_debug(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.warning(f"Could not get agent registry from backend after {max_retries + 1} attempts: {e}")
        
        # Fallback to empty list if backend not available after all retries
        log_websocket_debug("Returning empty agent list after all retry attempts failed")
        return []
    
    def register_tenant_connection(self, websocket: WebSocket, tenant_id: str):
        """Register a WebSocket connection for a specific tenant.
        
        Args:
            websocket: The WebSocket connection
            tenant_id: The tenant identifier
        """
        # Add to tenant connections set
        if tenant_id not in self.tenant_connections:
            self.tenant_connections[tenant_id] = set()
        self.tenant_connections[tenant_id].add(websocket)
        
        # Track reverse mapping
        self.connection_tenants[websocket] = tenant_id
        
        logger.info(f"Registered connection for tenant: {tenant_id[:20]}... (total tenant connections: {len(self.tenant_connections[tenant_id])})")
    
    def unregister_tenant_connection(self, websocket: WebSocket):
        """Unregister a WebSocket connection from its tenant.
        
        Args:
            websocket: The WebSocket connection to unregister
        """
        tenant_id = self.connection_tenants.pop(websocket, None)
        if tenant_id and tenant_id in self.tenant_connections:
            self.tenant_connections[tenant_id].discard(websocket)
            # Clean up empty tenant sets
            if not self.tenant_connections[tenant_id]:
                del self.tenant_connections[tenant_id]
                # Also clean up tenant event history
                self.tenant_event_history.pop(tenant_id, None)
            logger.info(f"Unregistered connection for tenant: {tenant_id[:20]}...")
    
    async def connect(self, websocket: WebSocket, token: Optional[str] = None, tenant_id: Optional[str] = None):
        """Accept a new WebSocket connection with optional authentication and tenant.
        
        Args:
            websocket: The WebSocket connection
            token: Optional authentication token
            tenant_id: Optional tenant identifier for multi-tenancy isolation
        """
        await websocket.accept()
        self.active_connections.add(websocket)
        
        # Handle authentication first to get user_id
        user_data = None
        user_id = None
        if token and auth_service:
            logger.info(f"[WebSocket Auth] Token received, attempting verification...")
            user_data = auth_service.verify_token(token)
            if user_data:
                user_id = user_data.get('user_id')
                logger.info(f"[WebSocket Auth] Token verified successfully for user_id: {user_id}")
        
        # Validate and register tenant connection
        # If tenant_id doesn't match user's own session, validate it's a valid collaborative session
        actual_tenant_id = tenant_id
        if tenant_id and user_id:
            # Check if this is the user's own session (user_id matches tenant_id)
            if tenant_id == user_id:
                # User's own session - register normally
                self.register_tenant_connection(websocket, tenant_id)
            else:
                # Different tenant - check if it's a valid collaborative session they're a member of
                session = collaborative_session_manager.get_session(tenant_id)
                if session and session.is_member(user_id):
                    # Valid collaborative session - register with the collaborative session's tenant
                    logger.info(f"[WebSocket] User {user_id} connecting to collaborative session {tenant_id[:20]}...")
                    self.register_tenant_connection(websocket, tenant_id)
                else:
                    # Invalid/stale collaborative session - use user's own session instead
                    logger.warning(f"[WebSocket] User {user_id} tried to connect with invalid collaborative session {tenant_id[:20]}..., using their own session")
                    actual_tenant_id = user_id
                    self.register_tenant_connection(websocket, user_id)
                    # Notify frontend to clear stale session
                    try:
                        await websocket.send_text(json.dumps({
                            "eventType": "session_invalid",
                            "reason": "collaborative_session_not_found",
                            "message": "Collaborative session no longer exists. Using your own session."
                        }))
                    except:
                        pass
        elif tenant_id:
            # Anonymous user with tenant - register normally
            self.register_tenant_connection(websocket, tenant_id)
        
        # Now complete authentication setup
        if user_data:
            auth_conn = AuthenticatedConnection(websocket, user_data)
            self.authenticated_connections[websocket] = auth_conn
            
            # Track user_id -> websocket for direct messaging (collaborative sessions)
            user_id = user_data.get('user_id')
            if user_id:
                if user_id not in self.user_connections:
                    self.user_connections[user_id] = set()
                self.user_connections[user_id].add(websocket)
                logger.info(f"[WebSocket Auth] Registered user connection: {user_id} (total: {len(self.user_connections[user_id])})")
            
            # Add user to active users list in auth service
            if auth_service:
                auth_service.add_active_user(user_data)
                logger.info(f"[WebSocket Auth] Added user to active list: {auth_conn.username}")
                
                # Send session-specific user info to this connection only
                # (multi-tenancy: each session only sees their own user)
                await self.send_session_user_update(websocket, auth_conn)
                logger.info(f"[WebSocket Auth] Sent session-specific user_list_update to {auth_conn.username}")
                
                # Send any pending session invitations to this user
                await self.send_pending_invitations(websocket, user_id)
            else:
                logger.warning("[WebSocket Auth] Auth service not available - cannot track active user")
            logger.info(f"[WebSocket Auth] Authenticated connection established for user: {auth_conn.username} ({auth_conn.email})")
        elif token and not auth_service:
            logger.warning(f"[WebSocket Auth] Token provided but auth_service is None!")
        elif not token:
            logger.info("[WebSocket Auth] No token provided - anonymous connection")
        
        if not user_data:
            logger.info("[WebSocket Auth] Established anonymous WebSocket connection")
        
        # Send recent history to new client (excluding message-related events)
        # Message events are loaded via conversation API, replaying them causes duplicates
        skip_event_types = {'message', 'shared_message', 'shared_inference_ended'}
        for event in self.event_history[-10:]:  # Send last 10 events
            if event.get('eventType') in skip_event_types:
                continue
            try:
                await websocket.send_text(json.dumps(event))
            except:
                pass  # Client might have disconnected immediately
        
        # Send current agent registry as initial state
        try:
            agents = self.get_agent_registry()
            if agents:
                registry_event = {
                    'eventType': 'agent_registry_sync',
                    'data': {
                        'agents': agents
                    },
                    'timestamp': time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                }
                await websocket.send_text(json.dumps(registry_event))
                logger.info(f"Sent agent registry with {len(agents)} agents to new client")
        except Exception as e:
            logger.error(f"Failed to send agent registry to new client: {e}")
        
        # Send authentication status
        auth_status = {
            'eventType': 'auth_status',
            'data': {
                'authenticated': user_data is not None,
                'user': user_data if user_data else None
            },
            'timestamp': time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        }
        try:
            await websocket.send_text(json.dumps(auth_status))
        except:
            pass
        
        # Send session ID - frontend uses this to detect backend restarts and clear file history
        session_event = {
            'eventType': 'session_started',
            'data': {
                'sessionId': self.session_id
            },
            'timestamp': time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        }
        try:
            await websocket.send_text(json.dumps(session_event))
            logger.info(f"Sent session ID to new client: {self.session_id[:8]}...")
        except:
            pass
        
        total_connections = len(self.active_connections)
        authenticated_connections = len(self.authenticated_connections)
        logger.info(f"WebSocket client connected. Total: {total_connections}, Authenticated: {authenticated_connections}")
    
    async def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        self.active_connections.discard(websocket)
        
        # Unregister from tenant connections
        self.unregister_tenant_connection(websocket)
        
        # Remove from authenticated connections if present
        if websocket in self.authenticated_connections:
            auth_conn = self.authenticated_connections.pop(websocket)
            user_id = auth_conn.user_data.get('user_id')
            
            # Clean up user_connections for collaborative sessions
            if user_id and user_id in self.user_connections:
                self.user_connections[user_id].discard(websocket)
                if not self.user_connections[user_id]:
                    del self.user_connections[user_id]
                    logger.info(f"[Collaborative] User {auth_conn.username} has no more active connections")
            
            # Remove user from active users list in auth service
            if auth_service:
                auth_service.remove_active_user(auth_conn.user_data)
                logger.info(f"[WebSocket Auth] Removed user from active list: {auth_conn.username}")
                
                # No need to broadcast to other sessions (multi-tenancy isolation)
                # Each session only tracks their own user, so no update needed for others
                logger.info(f"[WebSocket Auth] Session for {auth_conn.username} ended (no broadcast needed - session isolated)")
            
            logger.info(f"Authenticated user {auth_conn.username} disconnected")
        
        total_connections = len(self.active_connections)
        authenticated_connections = len(self.authenticated_connections)
        tenant_count = len(self.tenant_connections)
        logger.info(f"WebSocket client disconnected. Total: {total_connections}, Authenticated: {authenticated_connections}, Tenants: {tenant_count}")
    
    def get_connection_info(self, websocket: WebSocket) -> Optional[AuthenticatedConnection]:
        """Get connection info for a websocket."""
        return self.authenticated_connections.get(websocket)
    
    async def send_session_user_update(self, websocket: WebSocket, auth_conn: AuthenticatedConnection):
        """Send session-specific user info to a specific WebSocket connection.
        
        For multi-tenancy, each session only receives their own user info.
        For collaborative sessions, includes all session members.
        
        Args:
            websocket: The WebSocket connection to send to
            auth_conn: The authenticated connection info
        """
        try:
            session_users = []
            
            # Get this user's tenant/session ID
            tenant_id = self.connection_tenants.get(websocket)
            user_id = auth_conn.user_data.get('user_id') if auth_conn.user_data else None
            
            # Check if this user is in a collaborative session
            collaborative_session = None
            if tenant_id:
                collaborative_session = collaborative_session_manager.get_session(tenant_id)
            
            if collaborative_session:
                # In a collaborative session - get all members
                all_member_ids = collaborative_session.get_all_member_ids()
                logger.info(f"[WebSocket] User {auth_conn.username} is in collaborative session with {len(all_member_ids)} members: {all_member_ids}")
                
                for member_id in all_member_ids:
                    # Try to get user data for each member
                    member_data = None
                    if auth_service:
                        # member_id is like "user_123" - need to find the user
                        # Check authenticated connections to find the user's email
                        for conn, conn_info in self.authenticated_connections.items():
                            conn_user_id = conn_info.user_data.get('user_id') if conn_info.user_data else None
                            if conn_user_id == member_id:
                                user = auth_service.get_user_by_email(conn_info.email)
                                if user:
                                    member_data = {
                                        "user_id": user.user_id,
                                        "email": user.email,
                                        "name": user.name,
                                        "role": user.role,
                                        "description": user.description,
                                        "skills": user.skills,
                                        "color": user.color,
                                        "created_at": user.created_at.isoformat(),
                                        "last_login": user.last_login.isoformat() if user.last_login else None,
                                        "status": "active",
                                        "is_session_owner": member_id == collaborative_session.owner_user_id
                                    }
                                break
                    
                    if member_data:
                        session_users.append(member_data)
            else:
                # Not in collaborative session - just show this user
                if auth_service:
                    user = auth_service.get_user_by_email(auth_conn.email)
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
                        session_users.append(user_data)
            
            event_data = {
                "eventType": "user_list_update",
                "data": {
                    "active_users": session_users,
                    "total_active": len(session_users),
                    "session_isolated": True,
                    "is_collaborative": collaborative_session is not None
                },
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            }
            await websocket.send_text(json.dumps(event_data))
            logger.info(f"[WebSocket] Sent session user update to {auth_conn.username}: {len(session_users)} user(s)")
        except Exception as e:
            logger.error(f"Failed to send session user update to {auth_conn.username}: {e}")
    
    async def send_pending_invitations(self, websocket: WebSocket, user_id: str):
        """Send any pending session invitations to a newly connected user.
        
        Args:
            websocket: The WebSocket connection to send invitations to
            user_id: The user ID to check for pending invitations
        """
        try:
            session_manager = get_session_manager()
            pending = session_manager.get_pending_invitations_for_user(user_id)
            
            for invitation in pending:
                event_data = {
                    "eventType": "session_invite_received",
                    "invitation_id": invitation.invitation_id,
                    "from_user_id": invitation.from_user_id,
                    "from_username": invitation.from_user_name,
                    "session_id": invitation.session_id,
                    "expires_in_seconds": max(0, int(invitation.expires_at - time.time())),
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                }
                await websocket.send_text(json.dumps(event_data))
                logger.info(f"[Collaborative] Sent pending invitation {invitation.invitation_id} to {user_id}")
        except Exception as e:
            logger.error(f"Failed to send pending invitations to {user_id}: {e}")
    
    async def emit_agent_status_update(self, status_event: Dict[str, Any]):
        """Emit agent status update event to all connected clients."""
        try:
            # Format the event for the frontend
            event_data = {
                "eventType": "agent_status_update",
                "agentName": status_event.get("agent_name"),
                "status": status_event.get("status"),
                "message": status_event.get("message"),
                "timestamp": status_event.get("timestamp"),
                "taskId": status_event.get("task_id"),
                "contextId": status_event.get("context_id")
            }
            
            # Broadcast to tenant if contextId present, skip if no context (multi-tenant isolation)
            context_id = status_event.get("context_id")
            if context_id:
                tenant_id = get_tenant_from_context(context_id)
                await self.broadcast_to_tenant(event_data, tenant_id)
            else:
                logger.debug(f"Skipping agent status broadcast - no context_id provided (multi-tenant isolation)")
            print(f"[WEBSOCKET] Emitted agent status update: {status_event.get('agent_name')} -> {status_event.get('status')}")
            
        except Exception as e:
            logger.error(f"Failed to emit agent status update: {e}")
    
    async def broadcast_to_tenant(self, event_data: Dict[str, Any], tenant_id: str) -> int:
        """Broadcast an event only to connections belonging to a specific tenant.
        
        Args:
            event_data: Event data to broadcast
            tenant_id: The tenant to broadcast to
            
        Returns:
            Number of clients that received the event
        """
        # Add timestamp if not present
        if 'timestamp' not in event_data:
            event_data['timestamp'] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        
        # Store in tenant-specific history
        if tenant_id not in self.tenant_event_history:
            self.tenant_event_history[tenant_id] = []
        self.tenant_event_history[tenant_id].append(event_data)
        if len(self.tenant_event_history[tenant_id]) > self.max_history:
            self.tenant_event_history[tenant_id].pop(0)
        
        # Get connections for this tenant
        tenant_websockets = self.tenant_connections.get(tenant_id, set())
        
        if not tenant_websockets:
            logger.debug(f"No connections for tenant {tenant_id[:20]}..., skipping broadcast (no fallback)")
            return 0
        
        # Broadcast only to tenant's connections
        message = json.dumps(event_data)
        disconnected_clients = set()
        sent_count = 0
        
        for websocket in tenant_websockets.copy():
            try:
                await websocket.send_text(message)
                sent_count += 1
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket client: {e}")
                disconnected_clients.add(websocket)
        
        # Remove disconnected clients
        for websocket in disconnected_clients:
            await self.disconnect(websocket)
        
        event_type = event_data.get('eventType', 'unknown')
        logger.info(f"Broadcasted {event_type} event to {sent_count} clients for tenant {tenant_id[:20]}...")
        return sent_count
    
    async def broadcast_event(self, event_data: Dict[str, Any]) -> int:
        """Broadcast an event to all connected clients (global broadcast).
        
        Args:
            event_data: Event data to broadcast
            
        Returns:
            Number of clients that received the event
        """
        # Add timestamp if not present
        if 'timestamp' not in event_data:
            event_data['timestamp'] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        
        # Store in history
        self.event_history.append(event_data)
        if len(self.event_history) > self.max_history:
            self.event_history.pop(0)
        
        # Broadcast to all clients
        message = json.dumps(event_data)
        disconnected_clients = set()
        sent_count = 0
        
        for websocket in self.active_connections.copy():
            try:
                await websocket.send_text(message)
                sent_count += 1
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket client: {e}")
                disconnected_clients.add(websocket)
        
        # Remove disconnected clients
        for websocket in disconnected_clients:
            await self.disconnect(websocket)
        
        event_type = event_data.get('eventType', 'unknown')
        logger.info(f"Broadcasted {event_type} event to {sent_count} clients (global)")
        return sent_count
    
    async def smart_broadcast(self, event_data: Dict[str, Any]) -> int:
        """Smart broadcast that auto-detects tenant from event data.
        
        Looks for contextId or conversationId in event data to extract tenant.
        Also broadcasts to collaborative session members who joined this session.
        Skips broadcast if no tenant info found (multi-tenant isolation).
        
        Args:
            event_data: Event data to broadcast
            
        Returns:
            Number of clients that received the event
        """
        # Try to extract tenant from various fields in the event
        context_id = None
        data = event_data.get('data', {})
        
        # Check common fields that might contain contextId
        context_id = (
            event_data.get('contextId') or
            event_data.get('context_id') or
            data.get('contextId') or
            data.get('context_id') or
            data.get('conversationId') or
            data.get('conversation_id')
        )
        
        if context_id:
            sent_count = 0
            session_id = None
            
            # First try the raw context_id as tenant (for simple session IDs like "user_3")
            if context_id in self.tenant_connections:
                session_id = context_id
                sent_count = await self.broadcast_to_tenant(event_data, context_id)
            else:
                # Then try extracting tenant from tenant::conversation format
                tenant_id = get_tenant_from_context(context_id)
                if tenant_id in self.tenant_connections:
                    session_id = tenant_id
                    sent_count = await self.broadcast_to_tenant(event_data, tenant_id)
            
            # Also broadcast to collaborative session members
            # These are users who joined this session but have different user_ids
            if session_id:
                session = collaborative_session_manager.get_session(session_id)
                if session:
                    for member_id in session.get_all_member_ids():
                        # Skip the session owner (already sent via tenant broadcast)
                        if member_id == session_id:
                            continue
                        # Send to member's connections
                        if member_id in self.user_connections:
                            for ws in self.user_connections[member_id]:
                                try:
                                    await ws.send_text(json.dumps(event_data))
                                    sent_count += 1
                                except Exception as e:
                                    logger.error(f"Failed to send to collaborative member {member_id}: {e}")
                    if session.member_user_ids:
                        logger.debug(f"Broadcasted to {len(session.member_user_ids)} collaborative session members")
            
            if sent_count == 0:
                logger.debug(f"No tenant connections found for context_id: {context_id[:20]}..., skipping broadcast")
            
            return sent_count
        
        # No context_id found - skip broadcast (multi-tenant isolation)
        logger.debug(f"Skipping smart_broadcast - no contextId found in event data")
        return 0
    
    def get_status(self) -> Dict[str, Any]:
        """Get server status."""
        return {
            "status": "healthy",
            "active_connections": len(self.active_connections),
            "authenticated_connections": len(self.authenticated_connections),
            "tenant_count": len(self.tenant_connections),
            "event_history_count": len(self.event_history),
            "max_history": self.max_history
        }


# Global WebSocket manager
websocket_manager = WebSocketManager()

# Global collaborative session manager
collaborative_session_manager = get_session_manager()


def create_websocket_app() -> FastAPI:
    """Create FastAPI app with WebSocket support."""
    app = FastAPI(title="A2A WebSocket Server", version="1.0.0")
    
    @app.websocket("/events")
    async def websocket_endpoint(
        websocket: WebSocket, 
        token: Optional[str] = Query(None),
        tenant_id: Optional[str] = Query(None, alias="tenantId")
    ):
        """WebSocket endpoint for real-time event streaming with optional authentication and tenant isolation.
        
        Query Parameters:
            token: Optional JWT authentication token
            tenantId: Optional tenant identifier for multi-tenancy isolation
        """
        logger.info(f"[WebSocket] New connection attempt from {websocket.client}, tenant: {tenant_id[:20] if tenant_id else 'none'}...")
        
        await websocket_manager.connect(websocket, token, tenant_id)
        logger.info(f"[WebSocket] Client connected successfully: {websocket.client}")
        
        try:
            while True:
                # Keep connection alive and handle client messages
                data = await websocket.receive_text()
                
                # Parse incoming message
                try:
                    message = json.loads(data)
                    await handle_websocket_message(websocket, message)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON received from {websocket.client}: {data}")
                    
        except WebSocketDisconnect:
            logger.info(f"[WebSocket] Client disconnected: {websocket.client}")
            await websocket_manager.disconnect(websocket)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            await websocket_manager.disconnect(websocket)
    
    async def handle_websocket_message(websocket: WebSocket, message: Dict[str, Any]):
        """Handle incoming WebSocket messages from clients."""
        message_type = message.get("type")
        
        if message_type == "chat":
            # Handle chat message
            auth_conn = websocket_manager.get_connection_info(websocket)
            if auth_conn:
                # Authenticated user sending chat message
                chat_event = {
                    "eventType": "chat_message", 
                    "data": {
                        "user_id": auth_conn.user_id,
                        "username": auth_conn.username,
                        "message": message.get("text", ""),
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                    }
                }
                
                # Broadcast to all clients
                await websocket_manager.broadcast_event(chat_event)
                logger.info(f"Chat message from {auth_conn.username}: {message.get('text', '')[:50]}...")
            else:
                # Anonymous user - reject chat
                error_event = {
                    "eventType": "error",
                    "data": {
                        "message": "Authentication required for chat"
                    }
                }
                await websocket.send_text(json.dumps(error_event))
        
        elif message_type == "shared_message":
            # Handle shared message that should be broadcast to tenant's clients
            message_data = message.get("message", {})
            
            # Create the event to broadcast
            shared_event = {
                "eventType": "shared_message",
                "data": {
                    "message": message_data
                }
            }
            
            # Use smart_broadcast to send to tenant AND collaborative session members
            sender_tenant = websocket_manager.connection_tenants.get(websocket)
            if sender_tenant:
                # Add contextId for smart_broadcast to route to collaborative members
                shared_event["contextId"] = sender_tenant
                await websocket_manager.smart_broadcast(shared_event, sender_tenant)
            else:
                logger.debug(f"Skipping shared_message broadcast - no tenant found (multi-tenant isolation)")
            logger.info(f"Shared message broadcasted: {message_data.get('content', '')[:50]}...")
        
        elif message_type == "shared_inference_started":
            # Handle shared inference started event
            inference_data = message.get("data", {})
            
            # Create the event to broadcast
            inference_event = {
                "eventType": "shared_inference_started",
                "data": inference_data
            }
            
            # Broadcast to sender's tenant AND collaborative session members
            sender_tenant = websocket_manager.connection_tenants.get(websocket)
            if sender_tenant:
                # Add contextId for smart_broadcast to route to collaborative members
                inference_event["contextId"] = sender_tenant
                await websocket_manager.smart_broadcast(inference_event, sender_tenant)
            else:
                logger.debug(f"Skipping shared_inference_started broadcast - no tenant found (multi-tenant isolation)")
            logger.info(f"Shared inference started broadcasted for conversation: {inference_data.get('conversationId')}")
        
        elif message_type == "shared_inference_ended":
            # Handle shared inference ended event
            inference_data = message.get("data", {})
            
            # Create the event to broadcast
            inference_event = {
                "eventType": "shared_inference_ended", 
                "data": inference_data
            }
            
            # Broadcast to sender's tenant AND collaborative session members
            sender_tenant = websocket_manager.connection_tenants.get(websocket)
            if sender_tenant:
                # Add contextId for smart_broadcast to route to collaborative members
                inference_event["contextId"] = sender_tenant
                await websocket_manager.smart_broadcast(inference_event, sender_tenant)
            else:
                logger.debug(f"Skipping shared_inference_ended broadcast - no tenant found (multi-tenant isolation)")
            logger.info(f"Shared inference ended broadcasted for conversation: {inference_data.get('conversationId')}")
        
        elif message_type == "ping":
            # Handle ping/pong for keepalive
            await websocket.send_text(json.dumps({"type": "pong"}))
        
        elif message_type == "get_online_users":
            # Get list of online users for invitation UI
            await handle_get_online_users(websocket, message)
        
        elif message_type == "get_session_users":
            # Get current session's user list (re-request after subscribing)
            await handle_get_session_users(websocket)
        
        elif message_type == "session_invite":
            # Handle sending a session invitation
            await handle_session_invite(websocket, message)
        
        elif message_type == "session_invite_response":
            # Handle responding to an invitation
            await handle_session_invite_response(websocket, message)
        
        elif message_type == "leave_collaborative_session":
            # Handle leaving a collaborative session
            await handle_leave_session(websocket, message)
        
        else:
            logger.warning(f"Unknown message type: {message_type}")
    
    # Collaborative Session Handlers
    async def handle_get_session_users(websocket: WebSocket):
        """Handle request to get current session's user list.
        
        This allows the frontend to re-request the user list after subscribing,
        solving the race condition where the initial user_list_update arrives
        before the component has subscribed.
        """
        auth_conn = websocket_manager.get_connection_info(websocket)
        if auth_conn:
            await websocket_manager.send_session_user_update(websocket, auth_conn)
            logger.info(f"[WebSocket] Sent session users on request to {auth_conn.username}")
        else:
            # Not authenticated - send empty list
            await websocket.send_text(json.dumps({
                "eventType": "user_list_update",
                "data": {
                    "active_users": [],
                    "total_active": 0,
                    "session_isolated": True
                },
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            }))
            logger.info("[WebSocket] Sent empty session users (not authenticated)")

    async def handle_get_online_users(websocket: WebSocket, message: Dict[str, Any]):
        """Handle request to get list of online users for invitation."""
        logger.info("[Collaborative] Received get_online_users request")
        auth_conn = websocket_manager.get_connection_info(websocket)
        if not auth_conn:
            await websocket.send_text(json.dumps({
                "eventType": "online_users",
                "users": [],
                "error": "Not authenticated"
            }))
            return
        
        current_user_id = auth_conn.user_data.get('user_id')
        online_users = get_online_users_from_connections(
            websocket_manager.user_connections,
            websocket_manager.authenticated_connections,
            exclude_user_id=current_user_id
        )
        
        await websocket.send_text(json.dumps({
            "eventType": "online_users",
            "users": online_users
        }))
        logger.info(f"[Collaborative] Sent online users list to {auth_conn.username}: {len(online_users)} users")
    
    async def handle_session_invite(websocket: WebSocket, message: Dict[str, Any]):
        """Handle sending a session invitation to another user."""
        auth_conn = websocket_manager.get_connection_info(websocket)
        if not auth_conn:
            await websocket.send_text(json.dumps({
                "eventType": "session_invite_error",
                "error": "Not authenticated"
            }))
            return
        
        target_user_id = message.get("target_user_id")
        target_username = message.get("target_username", "")
        session_id = message.get("session_id")
        
        if not target_user_id or not session_id:
            await websocket.send_text(json.dumps({
                "eventType": "session_invite_error",
                "error": "Missing target_user_id or session_id"
            }))
            return
        
        from_user_id = auth_conn.user_data.get('user_id')
        from_username = auth_conn.username
        
        # Create the invitation
        invitation = collaborative_session_manager.create_invitation(
            session_id=session_id,
            from_user_id=from_user_id,
            from_user_name=from_username,
            to_user_id=target_user_id,
            to_user_name=target_username
        )
        
        if not invitation:
            await websocket.send_text(json.dumps({
                "eventType": "session_invite_error",
                "error": "Could not create invitation"
            }))
            return
        
        # Send invitation to target user's connections
        logger.info(f"[Collaborative] Looking for target user {target_user_id} in user_connections. Available users: {list(websocket_manager.user_connections.keys())}")
        if target_user_id in websocket_manager.user_connections:
            invite_message = json.dumps({
                "eventType": "session_invite_received",
                "invitation_id": invitation.invitation_id,
                "from_user_id": from_user_id,
                "from_username": from_username,
                "session_id": session_id,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(invitation.created_at))
            })
            for target_ws in websocket_manager.user_connections[target_user_id]:
                try:
                    await target_ws.send_text(invite_message)
                    logger.info(f"[Collaborative] Sent invite to {target_user_id} successfully")
                except Exception as e:
                    logger.error(f"[Collaborative] Failed to send invite to {target_user_id}: {e}")
        else:
            logger.warning(f"[Collaborative] Target user {target_user_id} not found in user_connections - storing invitation for later delivery")
        
        # Confirm to sender
        await websocket.send_text(json.dumps({
            "eventType": "session_invite_sent",
            "invitation_id": invitation.invitation_id,
            "to_user_id": target_user_id
        }))
        logger.info(f"[Collaborative] {from_username} invited user {target_user_id} to session {session_id[:8]}...")
    
    async def handle_session_invite_response(websocket: WebSocket, message: Dict[str, Any]):
        """Handle response to a session invitation."""
        auth_conn = websocket_manager.get_connection_info(websocket)
        if not auth_conn:
            return
        
        invitation_id = message.get("invitation_id")
        accepted = message.get("accepted", False)
        user_id = auth_conn.user_data.get('user_id')
        
        if not invitation_id:
            await websocket.send_text(json.dumps({
                "eventType": "session_invite_response_error",
                "error": "Missing invitation_id"
            }))
            return
        
        # Get the invitation first to notify inviter
        invitation = collaborative_session_manager.get_invitation(invitation_id)
        if not invitation:
            await websocket.send_text(json.dumps({
                "eventType": "session_invite_response_error",
                "error": "Invalid or expired invitation"
            }))
            return
        
        # Accept or decline the invitation
        if accepted:
            session = collaborative_session_manager.accept_invitation(invitation_id, user_id)
            if not session:
                await websocket.send_text(json.dumps({
                    "eventType": "session_invite_response_error",
                    "error": "Could not accept invitation"
                }))
                return
        else:
            success = collaborative_session_manager.decline_invitation(invitation_id, user_id)
            if not success:
                await websocket.send_text(json.dumps({
                    "eventType": "session_invite_response_error",
                    "error": "Could not decline invitation"
                }))
                return
        
        # Notify the inviter about the response
        if invitation.from_user_id in websocket_manager.user_connections:
            response_message = json.dumps({
                "eventType": "session_invite_response_received",
                "invitation_id": invitation_id,
                "from_user_id": user_id,
                "from_username": auth_conn.username,
                "accepted": accepted,
                "session_id": invitation.session_id
            })
            for inviter_ws in websocket_manager.user_connections[invitation.from_user_id]:
                try:
                    await inviter_ws.send_text(response_message)
                except Exception as e:
                    logger.error(f"[Collaborative] Failed to notify inviter: {e}")
        
        if accepted:
            # Get updated member list and notify all session members
            session = collaborative_session_manager.get_session(invitation.session_id)
            if session:
                members = collaborative_session_manager.get_session_members(invitation.session_id)
                member_update = json.dumps({
                    "eventType": "session_members_updated",
                    "session_id": invitation.session_id,
                    "members": members
                })
                
                # Notify all members (including owner)
                all_members = session.get_all_member_ids()
                for member_id in all_members:
                    if member_id in websocket_manager.user_connections:
                        for member_ws in websocket_manager.user_connections[member_id]:
                            try:
                                await member_ws.send_text(member_update)
                                # Also send updated user list so Session Users panel updates
                                member_auth = websocket_manager.get_connection_info(member_ws)
                                if member_auth:
                                    await websocket_manager.send_session_user_update(member_ws, member_auth)
                            except:
                                pass
        
        logger.info(f"[Collaborative] User {auth_conn.username} {'accepted' if accepted else 'declined'} invitation {invitation_id}")
    
    async def handle_leave_session(websocket: WebSocket, message: Dict[str, Any]):
        """Handle leaving a collaborative session."""
        auth_conn = websocket_manager.get_connection_info(websocket)
        if not auth_conn:
            return
        
        session_id = message.get("session_id")
        user_id = auth_conn.user_data.get('user_id')
        
        if not session_id:
            return
        
        # Get session before leaving to notify remaining members
        session = collaborative_session_manager.get_session(session_id)
        members_before = set(session.get_all_member_ids()) if session else set()
        
        success = collaborative_session_manager.leave_session(session_id, user_id)
        
        if success and members_before:
            # Notify remaining members (those who were in the session minus the leaving user)
            remaining_members = members_before - {user_id}
            members = collaborative_session_manager.get_session_members(session_id)
            member_update = json.dumps({
                "eventType": "session_members_updated",
                "session_id": session_id,
                "members": members,
                "left_user": auth_conn.username
            })
            
            for member_id in remaining_members:
                if member_id in websocket_manager.user_connections:
                    for member_ws in websocket_manager.user_connections[member_id]:
                        try:
                            await member_ws.send_text(member_update)
                        except:
                            pass
        
        await websocket.send_text(json.dumps({
            "type": "left_session",
            "session_id": session_id
        }))
        logger.info(f"[Collaborative] User {auth_conn.username} left session {session_id[:8]}...")
    
    @app.post("/events")
    async def post_event(event_data: Dict[str, Any]):
        """HTTP endpoint for posting events to WebSocket clients.
        
        Uses smart_broadcast to auto-detect tenant from contextId in event data.
        """
        try:
            client_count = await websocket_manager.smart_broadcast(event_data)
            return JSONResponse({
                "success": True,
                "clientCount": client_count,
                "eventType": event_data.get('eventType', 'unknown')
            })
        except Exception as e:
            logger.error(f"Error broadcasting event: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.post("/refresh-agents")
    async def refresh_agents():
        """HTTP endpoint to trigger immediate agent registry refresh."""
        try:
            websocket_manager.trigger_immediate_sync()
            return JSONResponse({
                "success": True,
                "message": "Agent registry refresh triggered"
            })
        except Exception as e:
            logger.error(f"Error triggering agent refresh: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/users")
    async def get_connection_stats():
        """Get WebSocket connection statistics (no user details for privacy).
        
        For multi-tenancy, individual user details are not exposed.
        Use the main API's /api/auth/active-users with authentication instead.
        """
        try:
            return JSONResponse({
                "success": True,
                "total_connections": len(websocket_manager.active_connections),
                "authenticated_connections": len(websocket_manager.authenticated_connections),
                "tenant_count": len(websocket_manager.tenant_connections),
                "message": "User details not exposed for privacy. Use /api/auth/active-users with auth token."
            })
        except Exception as e:
            logger.error(f"Error getting connection stats: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/agents")
    async def get_agents():
        """Get current agent registry."""
        try:
            agents = websocket_manager.get_agent_registry()
            return JSONResponse({
                "success": True,
                "agents": agents,
                "count": len(agents)
            })
        except Exception as e:
            logger.error(f"Error getting agent registry: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.post("/agents/sync")
    async def sync_agents():
        """Manually trigger agent registry sync to all clients."""
        try:
            agents = websocket_manager.get_agent_registry()
            registry_event = {
                'eventType': 'agent_registry_sync',
                'data': {
                    'agents': agents
                },
                'timestamp': time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            }
            client_count = await websocket_manager.broadcast_event(registry_event)
            return JSONResponse({
                "success": True,
                "clientCount": client_count,
                "agentCount": len(agents)
            })
        except Exception as e:
            logger.error(f"Error syncing agents: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return JSONResponse(websocket_manager.get_status())
    
    @app.get("/")
    async def root():
        """Root endpoint with server info."""
        return JSONResponse({
            "service": "A2A WebSocket Server",
            "version": "1.0.0",
            "endpoints": {
                "websocket": "/events (WebSocket)",
                "post_event": "/events (POST)",
                "health": "/health (GET)"
            },
            **websocket_manager.get_status()
        })
    
    return app


class WebSocketServerThread:
    """WebSocket server that runs in a background thread."""
    
    def __init__(self, host: str = "localhost", port: int = 8080):
        self.host = host
        self.port = port
        self.server_thread: Optional[threading.Thread] = None
        self.running = False
        self.app = create_websocket_app()
        self.sync_timer: Optional[threading.Timer] = None
        self.sync_interval = 15  # Sync agent registry every 15 seconds for faster updates
        self.sync_lock = threading.Lock()  # Prevent concurrent syncs
        self.sync_in_progress = False  # Track if sync is currently running
    
    def start(self):
        """Start the WebSocket server in a background thread."""
        log_websocket_debug(f"start() method called! running={self.running}")
        
        if self.running:
            logger.warning("WebSocket server is already running")
            log_websocket_debug("Already running, returning early")
            return
        
        logger.info(f"Starting WebSocket server on {self.host}:{self.port}")
        log_websocket_debug(f"Starting WebSocket server on {self.host}:{self.port}")
        
        self.running = True
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()
        
        # Wait for the server to actually start listening
        import socket
        import time
        max_wait = 10  # Maximum 10 seconds
        wait_time = 0
        
        while wait_time < max_wait:
            try:
                # Test if the port is actually listening
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex((self.host, self.port))
                sock.close()
                
                if result == 0:
                    log_websocket_debug(f"Server is listening on {self.host}:{self.port}")
                    break
                else:
                    log_websocket_debug(f"Waiting for server to start listening... ({wait_time}s)")
                    time.sleep(0.5)
                    wait_time += 0.5
            except Exception as e:
                log_websocket_debug(f"Error checking if server is ready: {e}")
                time.sleep(0.5)
                wait_time += 0.5
        
        if wait_time >= max_wait:
            logger.error("WebSocket server failed to start listening within timeout")
            log_websocket_debug("Server failed to start listening within timeout")
        
        # Start periodic agent registry sync
        try:
            logger.info(f"Starting WebSocket server periodic sync (every {self.sync_interval}s)")
            log_websocket_debug("About to call _schedule_agent_sync()")
            self._schedule_agent_sync()
            log_websocket_debug("_schedule_agent_sync() completed successfully")
            logger.info("WebSocket periodic sync scheduled successfully")
        except Exception as e:
            logger.error(f"Failed to start periodic sync: {e}")
            log_websocket_debug(f"Failed to start periodic sync: {e}")
            import traceback
            logger.error(f"Sync startup traceback: {traceback.format_exc()}")
            log_websocket_debug(f"Traceback: {traceback.format_exc()}")
        
        # Wait a moment for server to start
        time.sleep(1)
        logger.info(f"WebSocket server started on ws://{self.host}:{self.port}")
        log_websocket_debug("WebSocket server startup complete")
    
    def _schedule_agent_sync(self):
        """Schedule periodic agent registry sync."""
        log_websocket_debug(f"_schedule_agent_sync() called, running={self.running}")
        logger.info(f"⏰ Scheduler called (running={self.running}, sync_in_progress={self.sync_in_progress})")
        
        if not self.running:
            logger.warning("⚠️ Scheduler called but server not running, stopping sync")
            log_websocket_debug("Not running, returning early from _schedule_agent_sync")
            return
        
        # Check if sync is already in progress
        if self.sync_in_progress:
            logger.info("ℹ️ Sync already in progress, skipping this cycle but rescheduling next")
            log_websocket_debug("Sync already in progress, skipping this cycle")
            # Still schedule the next sync
            log_websocket_debug(f"Creating timer for next sync in {self.sync_interval} seconds")
            self.sync_timer = threading.Timer(self.sync_interval, self._schedule_agent_sync)
            self.sync_timer.daemon = True
            self.sync_timer.start()
            logger.info(f"✅ Next sync scheduled in {self.sync_interval}s (skipped current)")
            log_websocket_debug("Timer started successfully")
            return
            
        logger.info(f"🚀 Starting new sync cycle (interval: {self.sync_interval}s)")
        log_websocket_debug("About to start sync thread")
        
        # Run sync in background thread
        threading.Thread(target=self._run_sync, daemon=True).start()
        log_websocket_debug("Sync thread started")
        
        # Schedule next sync
        log_websocket_debug(f"Creating timer for next sync in {self.sync_interval} seconds")
        self.sync_timer = threading.Timer(self.sync_interval, self._schedule_agent_sync)
        self.sync_timer.daemon = True
        self.sync_timer.start()
        logger.info(f"✅ Next sync scheduled in {self.sync_interval}s")
        log_websocket_debug("Timer started successfully")
    
    def _run_sync(self):
        """Run agent registry sync in a separate thread."""
        # Use lock to prevent concurrent syncs
        if not self.sync_lock.acquire(blocking=False):
            log_websocket_debug("Could not acquire sync lock, another sync is running")
            return
            
        try:
            self.sync_in_progress = True
            log_websocket_debug("_run_sync() starting...")
            logger.info("WebSocket sync thread starting...")
            # Create a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            log_websocket_debug("Event loop created, calling _sync_agent_registry()")
            loop.run_until_complete(self._sync_agent_registry())
            loop.close()
            log_websocket_debug("_run_sync() completed successfully")
            logger.info("WebSocket sync thread completed")
        except Exception as e:
            log_websocket_debug(f"_run_sync() failed: {e}")
            logger.error(f"Failed to run agent sync: {e}")
            import traceback
            logger.error(f"Sync traceback: {traceback.format_exc()}")
            log_websocket_debug(f"Traceback: {traceback.format_exc()}")
        finally:
            self.sync_in_progress = False
            self.sync_lock.release()
            log_websocket_debug("Sync lock released")
    
    def trigger_immediate_sync(self):
        """Trigger an immediate agent registry sync (non-blocking)."""
        if self.sync_in_progress:
            log_websocket_debug("Sync already in progress, skipping immediate sync")
            logger.info("Sync already in progress, skipping immediate sync")
            return
        threading.Thread(target=self._run_sync, daemon=True).start()
        logger.info("Manual agent registry sync triggered")
    
    async def _sync_agent_registry(self):
        """Sync agent registry to all connected clients."""
        sync_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        logger.info(f"🔄 Starting agent registry sync at {sync_time}")
        
        try:
            logger.info("  📡 Fetching agent list from backend...")
            agents = websocket_manager.get_agent_registry()
            logger.info(f"  ✅ Retrieved {len(agents)} agents from registry")
            log_websocket_debug(f"Retrieved {len(agents)} agents from registry")
            
            if agents:
                # Log agent statuses for debugging
                agent_statuses = [(agent.get('name', 'unknown'), agent.get('status', 'unknown')) for agent in agents]
                logger.info(f"  📊 Agent statuses: {agent_statuses}")
                
                # Send full registry sync
                registry_event = {
                    'eventType': 'agent_registry_sync',
                    'data': {
                        'agents': agents
                    },
                    'timestamp': sync_time
                }
                logger.info(f"  📤 Broadcasting to WebSocket clients...")
                client_count = await websocket_manager.broadcast_event(registry_event)
                logger.info(f"  ✅ Synced {len(agents)} agents to {client_count} clients")
                log_websocket_debug(f"Sent registry sync to {client_count} clients")
            else:
                logger.info("  ℹ️  No agents to sync, broadcasting empty list...")
                registry_event = {
                    'eventType': 'agent_registry_sync',
                    'data': {
                        'agents': []
                    },
                    'timestamp': sync_time
                }
                client_count = await websocket_manager.broadcast_event(registry_event)
                logger.info(f"  ✅ Synced 0 agents to {client_count} clients")
                
            logger.info(f"✅ Sync completed successfully at {sync_time}")
                
        except Exception as e:
            logger.error(f"❌ Failed to sync agent registry: {e}")
            log_websocket_debug(f"Sync failed: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            log_websocket_debug(f"Traceback: {traceback.format_exc()}")
    
    def _run_server(self):
        """Run the WebSocket server."""
        try:
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Run the server
            uvicorn.run(
                self.app,
                host=self.host,
                port=self.port,
                log_level="warning",  # Reduce noise
                access_log=False
            )
        except Exception as e:
            logger.error(f"WebSocket server error: {e}")
        finally:
            self.running = False
    
    def stop(self):
        """Stop the WebSocket server."""
        self.running = False
        
        # Cancel periodic sync timer
        if self.sync_timer:
            self.sync_timer.cancel()
            self.sync_timer = None
        
        if self.server_thread and self.server_thread.is_alive():
            # Note: uvicorn doesn't have a clean shutdown mechanism when run this way
            # In a production environment, you'd use a proper process manager
            logger.info("WebSocket server thread stopping...")
    
    async def broadcast_event(self, event_data: Dict[str, Any]) -> int:
        """Broadcast an event to all connected clients."""
        return await websocket_manager.broadcast_event(event_data)
    
    async def smart_broadcast(self, event_data: Dict[str, Any]) -> int:
        """Smart broadcast that auto-detects tenant from event data."""
        return await websocket_manager.smart_broadcast(event_data)
    
    def get_status(self) -> Dict[str, Any]:
        """Get server status."""
        return {
            **websocket_manager.get_status(),
            "running": self.running,
            "host": self.host,
            "port": self.port
        }


# Global WebSocket server instance
_websocket_server: Optional[WebSocketServerThread] = None


def start_websocket_server(host: str = "localhost", port: int = 8080) -> WebSocketServerThread:
    """Start the global WebSocket server."""
    global _websocket_server
    
    if _websocket_server is None or not _websocket_server.running:
        _websocket_server = WebSocketServerThread(host, port)
        _websocket_server.start()
    
    return _websocket_server


def stop_websocket_server():
    """Stop the global WebSocket server."""
    global _websocket_server
    
    if _websocket_server:
        _websocket_server.stop()
        _websocket_server = None
        logger.info("WebSocket server stopped")


def get_websocket_server() -> Optional[WebSocketServerThread]:
    """Get the global WebSocket server instance."""
    return _websocket_server


if __name__ == "__main__":
    # For testing the server standalone
    app = create_websocket_app()
    uvicorn.run(app, host="localhost", port=8080)
