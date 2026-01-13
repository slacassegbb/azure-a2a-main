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
    """Manages WebSocket connections and event broadcasting."""
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.authenticated_connections: Dict[WebSocket, AuthenticatedConnection] = {}
        self.event_history: List[Dict[str, Any]] = []
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
    
    async def connect(self, websocket: WebSocket, token: Optional[str] = None):
        """Accept a new WebSocket connection with optional authentication."""
        await websocket.accept()
        self.active_connections.add(websocket)
        
        # Handle authentication if token provided
        user_data = None
        if token and auth_service:
            user_data = auth_service.verify_token(token)
            if user_data:
                auth_conn = AuthenticatedConnection(websocket, user_data)
                self.authenticated_connections[websocket] = auth_conn
                
                # Add user to active users list in auth service
                if auth_service:
                    auth_service.add_active_user(user_data)
                    logger.info(f"Added user to active list: {auth_conn.username}")
                    
                    # Broadcast user connected event to all clients
                    await self.broadcast_user_list_update()
                else:
                    logger.warning("Auth service not available - cannot track active user")
                logger.info(f"Authenticated WebSocket connection for user: {auth_conn.username} ({auth_conn.email})")
            else:
                logger.warning("Invalid token provided for WebSocket connection")
        
        if not user_data:
            logger.info("Anonymous WebSocket connection established")
        
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
    
    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        self.active_connections.discard(websocket)
        
        # Remove from authenticated connections if present
        if websocket in self.authenticated_connections:
            auth_conn = self.authenticated_connections.pop(websocket)
            
            # Remove user from active users list in auth service
            if auth_service:
                auth_service.remove_active_user(auth_conn.user_data)
                
                # Broadcast user disconnected event to all clients
                import asyncio
                asyncio.create_task(self.broadcast_user_list_update())
            
            logger.info(f"Authenticated user {auth_conn.username} disconnected")
        
        total_connections = len(self.active_connections)
        authenticated_connections = len(self.authenticated_connections)
        logger.info(f"WebSocket client disconnected. Total: {total_connections}, Authenticated: {authenticated_connections}")
    
    def get_connection_info(self, websocket: WebSocket) -> Optional[AuthenticatedConnection]:
        """Get connection info for a websocket."""
        return self.authenticated_connections.get(websocket)
    
    def get_authenticated_users(self) -> List[Dict[str, Any]]:
        """Get list of currently authenticated users."""
        return [
            {
                "user_id": conn.user_id,
                "username": conn.username,
                "email": conn.email,
                "connected_at": conn.connected_at
            }
            for conn in self.authenticated_connections.values()
        ]
    
    async def broadcast_user_list_update(self):
        """Broadcast user list update to all connected clients."""
        try:
            if auth_service:
                active_users = auth_service.get_active_users()
                event_data = {
                    "eventType": "user_list_update",
                    "data": {
                        "active_users": active_users,
                        "total_active": len(active_users)
                    },
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                }
                await self.broadcast_event(event_data)
                logger.info(f"Broadcasted user list update: {len(active_users)} active users")
        except Exception as e:
            logger.error(f"Failed to broadcast user list update: {e}")
    
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
            
            # Broadcast to all connected clients
            await self.broadcast_event(event_data)
            print(f"[WEBSOCKET] Emitted agent status update: {status_event.get('agent_name')} -> {status_event.get('status')}")
            
        except Exception as e:
            logger.error(f"Failed to emit agent status update: {e}")
    
    async def broadcast_event(self, event_data: Dict[str, Any]) -> int:
        """Broadcast an event to all connected clients.
        
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
            self.disconnect(websocket)
        
        event_type = event_data.get('eventType', 'unknown')
        logger.info(f"Broadcasted {event_type} event to {sent_count} clients")
        return sent_count
    
    def get_status(self) -> Dict[str, Any]:
        """Get server status."""
        return {
            "status": "healthy",
            "active_connections": len(self.active_connections),
            "event_history_count": len(self.event_history),
            "max_history": self.max_history
        }


# Global WebSocket manager
websocket_manager = WebSocketManager()


def create_websocket_app() -> FastAPI:
    """Create FastAPI app with WebSocket support."""
    app = FastAPI(title="A2A WebSocket Server", version="1.0.0")
    
    @app.websocket("/events")
    async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = Query(None)):
        """WebSocket endpoint for real-time event streaming with optional authentication."""
        logger.info(f"[WebSocket] New connection attempt from {websocket.client}")
        
        await websocket_manager.connect(websocket, token)
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
            websocket_manager.disconnect(websocket)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            websocket_manager.disconnect(websocket)
    
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
            # Handle shared message that should be broadcast to all clients
            message_data = message.get("message", {})
            
            # Create the event to broadcast
            shared_event = {
                "eventType": "shared_message",
                "data": {
                    "message": message_data
                }
            }
            
            # Broadcast to all clients (including sender)
            await websocket_manager.broadcast_event(shared_event)
            logger.info(f"Shared message broadcasted: {message_data.get('content', '')[:50]}...")
        
        elif message_type == "shared_inference_started":
            # Handle shared inference started event
            inference_data = message.get("data", {})
            
            # Create the event to broadcast
            inference_event = {
                "eventType": "shared_inference_started",
                "data": inference_data
            }
            
            # Broadcast to all clients (including sender)
            await websocket_manager.broadcast_event(inference_event)
            logger.info(f"Shared inference started broadcasted for conversation: {inference_data.get('conversationId')}")
        
        elif message_type == "shared_inference_ended":
            # Handle shared inference ended event
            inference_data = message.get("data", {})
            
            # Create the event to broadcast
            inference_event = {
                "eventType": "shared_inference_ended", 
                "data": inference_data
            }
            
            # Broadcast to all clients (including sender)
            await websocket_manager.broadcast_event(inference_event)
            logger.info(f"Shared inference ended broadcasted for conversation: {inference_data.get('conversationId')}")
        
        elif message_type == "ping":
            # Handle ping/pong for keepalive
            await websocket.send_text(json.dumps({"type": "pong"}))
        
        else:
            logger.warning(f"Unknown message type: {message_type}")
    
    @app.post("/events")
    async def post_event(event_data: Dict[str, Any]):
        """HTTP endpoint for posting events to WebSocket clients."""
        try:
            client_count = await websocket_manager.broadcast_event(event_data)
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
    async def get_connected_users():
        """Get list of currently connected authenticated users."""
        try:
            users = websocket_manager.get_authenticated_users()
            return JSONResponse({
                "success": True,
                "users": users,
                "total_connections": len(websocket_manager.active_connections),
                "authenticated_connections": len(users)
            })
        except Exception as e:
            logger.error(f"Error getting connected users: {e}")
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
