"""WebSocket Integration for A2A Data Streaming

This module provides integration with WebSocket to stream all UX data
from the A2A system to external consumers like TypeScript frontends.
This replaces Azure Event Hub for local development.
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Set
import httpx

from state.state import StateMessage, StateConversation, StateTask, StateEvent
from a2a.types import Message

# Add backend directory to path for log_config import
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from log_config import log_debug

logger = logging.getLogger(__name__)


def get_context_id(obj: Any, default: str = None) -> str:
    """
    Helper function to get contextId from an object, trying both contextId and context_id fields.
    A2A protocol officially uses contextId (camelCase), but this provides fallback compatibility.
    """
    try:
        # Try contextId first (official A2A protocol field name)
        if hasattr(obj, 'contextId') and obj.contextId is not None:
            return obj.contextId
        # Fallback to context_id for compatibility
        if hasattr(obj, 'context_id') and obj.context_id is not None:
            return obj.context_id
        # Final fallback using getattr
        return getattr(obj, 'contextId', getattr(obj, 'context_id', default or ''))
    except Exception:
        return default or ''


def get_message_id(obj: Any, default: str = None) -> str:
    """
    Helper function to get messageId from an object, trying both messageId and message_id fields.
    A2A protocol officially uses messageId (camelCase), but this provides fallback compatibility.
    """
    try:
        # Try messageId first (official A2A protocol field name)
        if hasattr(obj, 'messageId') and obj.messageId is not None:
            return obj.messageId
        # Fallback to message_id for compatibility
        if hasattr(obj, 'message_id') and obj.message_id is not None:
            return obj.message_id
        # Use getattr as final fallback
        return getattr(obj, 'messageId', getattr(obj, 'message_id', default or ''))
    except Exception:
        return default or ''


def get_task_id(obj: Any, default: str = None) -> str:
    """
    Helper function to get taskId from an object, trying both taskId and task_id fields.
    A2A protocol officially uses taskId (camelCase), but this provides fallback compatibility.
    """
    try:
        # Try taskId first (official A2A protocol field name)
        if hasattr(obj, 'taskId') and obj.taskId is not None:
            return obj.taskId
        # Fallback to task_id for compatibility
        if hasattr(obj, 'task_id') and obj.task_id is not None:
            return obj.task_id
        # Try id field as alternative (Task objects use .id)
        if hasattr(obj, 'id') and obj.id is not None:
            return obj.id
        # Use getattr as final fallback
        return getattr(obj, 'taskId', getattr(obj, 'task_id', getattr(obj, 'id', default or '')))
    except Exception:
        return default or ''


class WebSocketStreamer:
    """WebSocket client for streaming A2A events to the UI.
    
    This replaces Azure Event Hub functionality with local WebSocket communication.
    The WebSocket server runs alongside the FastAPI backend server.
    """
    
    def __init__(self, websocket_url: str | None = None):
        websocket_url = websocket_url or os.environ.get("WEBSOCKET_SERVER_URL", "http://localhost:8080")
        """Initialize the WebSocket streamer.
        
        Args:
            websocket_url: Base URL for the WebSocket server (for HTTP POST events)
        """
        self.websocket_url = websocket_url
        self.events_endpoint = f"{websocket_url}/events"
        self.http_client = None
        self.is_initialized = False
        # Track emitted files per conversation to prevent duplicates within same conversation only
        self._emitted_file_uris: Dict[str, Set[str]] = {}  # {conversation_id: {file_uri, ...}}
        
        logger.info(f"WebSocket streamer initialized with URL: {websocket_url}")
    
    async def initialize(self) -> bool:
        """Initialize the WebSocket streamer.
        
        Returns:
            bool: True if initialization successful, False otherwise
        """
        try:
            # Create HTTP client for sending events
            # Increased timeout to 30s to handle message events that may take longer to broadcast
            self.http_client = httpx.AsyncClient(timeout=30.0)
            
            # Test connection to WebSocket server with retries
            health_url = f"{self.websocket_url}/health"
            
            # Try multiple times to connect (WebSocket server might be starting up)
            for attempt in range(3):
                try:
                    response = await self.http_client.get(health_url)
                    
                    if response.status_code == 200:
                        self.is_initialized = True
                        logger.info("✅ WebSocket streamer initialized successfully")
                        log_debug(f"WebSocket streamer connected to {self.websocket_url}")
                        return True
                    else:
                        logger.warning(f"WebSocket server health check failed: {response.status_code}")
                        
                except httpx.ConnectError:
                    if attempt < 2:  # Don't log error on last attempt
                        logger.info(f"WebSocket server not ready, attempt {attempt + 1}/3...")
                        await asyncio.sleep(1)  # Wait 1 second before retry
                    continue
                except Exception as e:
                    logger.warning(f"WebSocket connection attempt {attempt + 1} failed: {e}")
                    if attempt < 2:
                        await asyncio.sleep(1)
                    continue
            
            # If we get here, all attempts failed
            logger.error(f"❌ Failed to connect to WebSocket server at {self.websocket_url}")
            # Still mark as initialized but warn it might not work
            self.is_initialized = True  # Allow it to try sending events anyway
            log_debug("WebSocket streamer initialized but connection uncertain")
            return True
                
        except Exception as e:
            logger.error(f"❌ Failed to initialize WebSocket streamer: {e}")
            return False
    
    async def cleanup(self):
        """Cleanup WebSocket streamer resources."""
        try:
            if self.http_client:
                await self.http_client.aclose()
                self.http_client = None
            self.is_initialized = False
            logger.info("WebSocket streamer cleaned up")
        except Exception as e:
            logger.error(f"Error during WebSocket streamer cleanup: {e}")
    
    async def _send_event(self, event_type: str, data: Dict[str, Any], partition_key: Optional[str] = None) -> bool:
        """Send an event via WebSocket.
        
        Args:
            event_type: Type of event (e.g., 'message', 'conversation', 'task', 'event')
            data: Event data dictionary
            partition_key: Optional partition key (ignored for WebSocket, kept for compatibility)
            
        Returns:
            bool: True if event sent successfully, False otherwise
        """
        if not self.is_initialized or not self.http_client:
            logger.error(f"WebSocket streamer not initialized, cannot send {event_type} event")
            log_debug(f"WebSocket streamer not available for {event_type}")
            return False
        
        try:
            # Prepare event payload (same format as Event Hub)
            event_payload = {
                "eventType": event_type,
                "timestamp": datetime.now().isoformat(),
                **data
            }
            
            log_debug(f"Sending WebSocket event {event_type}: {event_payload}")
            
            # Send via HTTP POST to WebSocket server
            response = await self.http_client.post(
                self.events_endpoint,
                json=event_payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                client_count = result.get('clientCount', 0)
                log_debug(f"✅ Event {event_type} sent successfully to {client_count} WebSocket clients")
                logger.info(f"✅ Event {event_type} sent successfully to {client_count} WebSocket clients")
                return True
            else:
                response_text = response.text[:500] if hasattr(response, 'text') else 'No response text'
                logger.error(f"❌ Failed to send {event_type} event: HTTP {response.status_code}, Response: {response_text}")
                log_debug(f"❌ Failed to send {event_type} event: HTTP {response.status_code}, Response: {response_text}")
                return False
                
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"❌ Error sending {event_type} event: {e}")
            logger.error(f"Full traceback: {error_details}")
            log_debug(f"❌ Error sending {event_type} event: {e}")
            log_debug(f"Full traceback: {error_details}")
            return False

    # === Message Events ===
    
    async def stream_message_sent(self, message: Message, conversation_id: str) -> bool:
        """Stream a message sent event."""
        data = {
            "conversationId": conversation_id,
            "messageId": get_message_id(message),
            "message": self._extract_message_content(message),
            "contextId": get_context_id(message),
            "direction": "sent"
        }
        return await self._send_event("message", data, conversation_id)
    
    async def stream_message_received(self, message: Message, conversation_id: str) -> bool:
        """Stream a message received event."""
        data = {
            "conversationId": conversation_id,
            "messageId": get_message_id(message),
            "message": self._extract_message_content(message),
            "contextId": get_context_id(message),
            "direction": "received"
        }
        return await self._send_event("message", data, conversation_id)
    
    # === Conversation Events ===
    
    async def stream_conversation_created(self, conversation: StateConversation) -> bool:
        """Stream a conversation created event."""
        data = {
            "conversationId": conversation.id,
            "title": conversation.title,
            "contextId": get_context_id(conversation),
            "action": "created"
        }
        return await self._send_event("conversation", data, conversation.id)
    
    async def stream_conversation_updated(self, conversation: StateConversation) -> bool:
        """Stream a conversation updated event."""
        data = {
            "conversationId": conversation.id,
            "title": conversation.title,
            "contextId": get_context_id(conversation),
            "action": "updated"
        }
        return await self._send_event("conversation", data, conversation.id)
    
    # === Task Events ===
    
    async def stream_task_created(self, task: StateTask, conversation_id: str) -> bool:
        """Stream a task created event."""
        data = {
            "conversationId": conversation_id,
            "taskId": get_task_id(task),
            "task": task.model_dump() if hasattr(task, 'model_dump') else task.__dict__,
            "contextId": get_context_id(task),
            "action": "created"
        }
        return await self._send_event("task", data, conversation_id)
    
    async def stream_task_updated(self, task: StateTask, conversation_id: str) -> bool:
        """Stream a task updated event."""
        data = {
            "conversationId": conversation_id,
            "taskId": get_task_id(task),
            "task": task.model_dump() if hasattr(task, 'model_dump') else task.__dict__,
            "contextId": get_context_id(task),
            "action": "updated"
        }
        return await self._send_event("task", data, conversation_id)
    
    # === General Events ===
    
    async def stream_event_occurred(self, event: StateEvent) -> bool:
        """Stream a general event."""
        data = {
            "eventId": event.id if hasattr(event, 'id') else '',
            "event": event.model_dump() if hasattr(event, 'model_dump') else event.__dict__,
            "contextId": get_context_id(event)
        }
        return await self._send_event("event", data)
    
    # === File Events ===
    
    async def stream_file_uploaded(self, file_info: Dict[str, Any], conversation_id: str) -> bool:
        """Stream a file uploaded event.
        
        Deduplicates based on file URI to prevent duplicate entries in File History
        when the same file is emitted from multiple sources (streaming + final response).
        Deduplication is scoped per conversation to avoid blocking files in new conversations.
        """
        file_uri = file_info.get('uri', '')
        
        # Initialize conversation tracking if needed
        if conversation_id not in self._emitted_file_uris:
            self._emitted_file_uris[conversation_id] = set()
        
        # Deduplicate: Skip if this URI was already emitted in THIS conversation
        if file_uri in self._emitted_file_uris[conversation_id]:
            logger.debug(f"Skipping duplicate file_uploaded event for URI in conversation {conversation_id[:8]}...: {file_uri[:80]}...")
            return True  # Return True to indicate no error
        
        # Mark URI as emitted for this conversation
        self._emitted_file_uris[conversation_id].add(file_uri)
        
        data = {
            "conversationId": conversation_id,
            "fileInfo": file_info,
            "contextId": file_info.get('contextId', ''),
            "action": "uploaded"
        }
        return await self._send_event("file", data, conversation_id)
    
    # === Form Events ===
    
    async def stream_form_submitted(self, form_data: Dict[str, Any], conversation_id: str) -> bool:
        """Stream a form submitted event."""
        data = {
            "conversationId": conversation_id,
            "formData": form_data,
            "contextId": form_data.get('contextId', ''),
            "action": "submitted"
        }
        return await self._send_event("form", data, conversation_id)
    
    # === Agent Events ===
    
    async def stream_agent_registered(self, agent_path: str, agent_name: Optional[str] = None) -> bool:
        """Stream agent registration event."""
        # Extract agent name from path if not provided
        if not agent_name and agent_path:
            # Extract name from path like "/agents/data_analyst" -> "data_analyst"
            agent_name = agent_path.split('/')[-1] if '/' in agent_path else agent_path
        
        data = {
            "agentPath": agent_path,
            "agentName": agent_name or "Unknown Agent",
            "status": "registered",
            "timestamp": datetime.now().isoformat(),
            "avatar": f"/api/agents/{agent_name}/avatar" if agent_name else "/placeholder.svg"
        }
        return await self._send_event("agent_registered", data)
    
    async def stream_agent_self_registered(self, agent_info: Dict[str, Any]) -> bool:
        """Stream self-registration event for agents that register themselves."""
        data = {
            "agentName": agent_info.get("name", "Unknown Agent"),
            "agentType": agent_info.get("type", "generic"),
            "agentPath": agent_info.get("path", ""),
            "status": "registered",
            "capabilities": agent_info.get("capabilities", []),
            "timestamp": datetime.now().isoformat(),
            "avatar": agent_info.get("avatar", "/placeholder.svg")
        }
        return await self._send_event("agent_registered", data)
    
    def _extract_agent_name_from_path(self, agent_path: str) -> str:
        """Extract agent name from a path like '/agents/data_analyst' -> 'data_analyst'"""
        if not agent_path:
            return "Unknown Agent"
        # Remove leading/trailing slashes and split
        path_parts = agent_path.strip('/').split('/')
        # Return the last part (agent name)
        return path_parts[-1] if path_parts else "Unknown Agent"
    
    # === Helper Methods ===
    
    def _extract_message_content(self, message: Message) -> List[Dict[str, Any]]:
        """Extract message content into a serializable format.
        
        Args:
            message: A2A Message object
            
        Returns:
            List of content parts as dictionaries
        """
        try:
            if hasattr(message, 'parts') and message.parts:
                content = []
                for part in message.parts:
                    if hasattr(part, 'text') and part.text:
                        content.append({
                            "type": "text",
                            "content": part.text
                        })
                    elif hasattr(part, 'data') and part.data:
                        content.append({
                            "type": "data",
                            "content": str(part.data)[:1000]  # Truncate large data
                        })
                    elif hasattr(part, 'file') and part.file:
                        file_obj = part.file
                        mime_type = getattr(file_obj, 'mimeType', '')
                        file_dict = {
                            "type": "file",
                            "content": f"File: {getattr(file_obj, 'name', 'unknown')}",
                            "mimeType": mime_type  # Always include mimeType for frontend filtering
                        }
                        # Include URI if available (for images and other files)
                        if hasattr(file_obj, 'uri') and file_obj.uri:
                            file_dict["uri"] = str(file_obj.uri)
                            file_dict["fileName"] = getattr(file_obj, 'name', 'unknown')
                            # Check if it's an image based on URI or mimeType
                            if mime_type.startswith('image/') or any(ext in str(file_obj.uri).lower() for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                                file_dict["type"] = "image"
                            # Check if it's a video based on mimeType or URI
                            elif mime_type.startswith('video/') or any(ext in str(file_obj.uri).lower() for ext in ['.mp4', '.webm', '.mov', '.avi']):
                                file_dict["type"] = "video"
                        content.append(file_dict)
                return content
            else:
                return [{"type": "text", "content": str(message)}]
        except Exception as e:
            logger.warning(f"Failed to extract message content: {e}")
            return [{"type": "text", "content": str(message)}]


# Global WebSocket streamer instance
_websocket_streamer = None


async def get_websocket_streamer() -> Optional[WebSocketStreamer]:
    """Get or create the global WebSocket streamer instance.
    
    Returns:
        WebSocketStreamer instance if available, None if initialization fails
    """
    global _websocket_streamer
    
    if _websocket_streamer is None:
        # Get WebSocket server URL from environment or use default
        websocket_url = os.environ.get('WEBSOCKET_SERVER_URL', 'http://localhost:8080')
        
        _websocket_streamer = WebSocketStreamer(websocket_url)
        
        # Initialize the streamer
        success = await _websocket_streamer.initialize()
        if not success:
            logger.warning("Failed to initialize WebSocket streamer")
            # Keep the instance but mark it as not initialized
    
    return _websocket_streamer


async def cleanup_websocket_streamer():
    """Cleanup the global WebSocket streamer instance."""
    global _websocket_streamer
    
    if _websocket_streamer:
        await _websocket_streamer.cleanup()
        _websocket_streamer = None
        logger.info("WebSocket streamer cleaned up")


