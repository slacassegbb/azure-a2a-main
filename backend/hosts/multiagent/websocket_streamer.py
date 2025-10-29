"""WebSocket Integration for A2A Data Streaming

This module provides integration with WebSocket to stream all UX data
from the A2A system to external consumers like TypeScript frontends.
This replaces Azure Event Hub for local development.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable, Set
import httpx

# Note: State classes may not be available in this context, so use duck typing
try:
    from state.state import StateMessage, StateConversation, StateTask, StateEvent
except ImportError:
    # Fallback for when state module is not available
    StateMessage = None
    StateConversation = None
    StateTask = None
    StateEvent = None

try:
    from a2a.types import Message
except ImportError:
    # Fallback for when a2a.types is not available
    Message = None

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
        self.agents_endpoint = f"{websocket_url}/agents"
        self.http_client = None
        self.is_initialized = False
        self._agent_registry_callback = None
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
            self.http_client = httpx.AsyncClient(timeout=5.0)
            
            # Test connection to WebSocket server
            health_url = f"{self.websocket_url}/health"
            response = await self.http_client.get(health_url)
            
            if response.status_code == 200:
                self.is_initialized = True
                logger.info("✅ WebSocket streamer initialized successfully")
                return True
            else:
                logger.warning(f"WebSocket server health check failed: {response.status_code}")
                return False
                
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
    
    def register_agent_registry_callback(self, callback):
        """Register a callback function to get current agent registry.
        
        Args:
            callback: Function that returns list of current agents
        """
        self._agent_registry_callback = callback
        logger.info("Agent registry callback registered")
    
    async def notify_agent_registry_to_websocket_server(self):
        """Notify the WebSocket server about the agent registry callback."""
        if not self._agent_registry_callback:
            logger.warning("No agent registry callback registered")
            return False
            
        try:
            # For now, we'll use HTTP to communicate with the WebSocket server
            # In a more sophisticated setup, we could have a direct connection
            agents = self._agent_registry_callback()
            
            # Send the current agents as a special event
            await self._send_event("agents_sync", {
                "agents": agents,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            })
            
            logger.info(f"Synced {len(agents)} agents to WebSocket server")
            return True
            
        except Exception as e:
            logger.error(f"Error notifying WebSocket server about agent registry: {e}")
            return False
    
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
            return False
        
        try:
            # Prepare event payload (same format as Event Hub)
            event_payload = {
                "eventType": event_type,
                "timestamp": datetime.now().isoformat(),
                **data
            }
            
            # Send via HTTP POST to WebSocket server
            response = await self.http_client.post(
                self.events_endpoint,
                json=event_payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                client_count = result.get('clientCount', 0)
                logger.info(f"✅ Event {event_type} sent successfully to {client_count} WebSocket clients")
                return True
            else:
                logger.error(f"❌ Failed to send {event_type} event: HTTP {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error sending {event_type} event: {e}")
            return False

    # === Message Events ===
    
    async def stream_message_sent(self, message, conversation_id: str) -> bool:
        """Stream a message sent event."""
        data = {
            "conversationId": conversation_id,
            "messageId": get_message_id(message),
            "message": self._extract_message_content(message),
            "contextId": get_context_id(message),
            "direction": "sent"
        }
        return await self._send_event("message", data, conversation_id)
    
    async def stream_message_received(self, message, conversation_id: str) -> bool:
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
    
    async def stream_conversation_created(self, conversation) -> bool:
        """Stream a conversation created event."""
        data = {
            "conversationId": getattr(conversation, 'id', ''),
            "title": getattr(conversation, 'title', ''),
            "contextId": get_context_id(conversation),
            "action": "created"
        }
        return await self._send_event("conversation", data, getattr(conversation, 'id', ''))
    
    async def stream_conversation_updated(self, conversation) -> bool:
        """Stream a conversation updated event."""
        data = {
            "conversationId": getattr(conversation, 'id', ''),
            "title": getattr(conversation, 'title', ''),
            "contextId": get_context_id(conversation),
            "action": "updated"
        }
        return await self._send_event("conversation", data, getattr(conversation, 'id', ''))
    
    # === Task Events ===
    
    async def stream_task_created(self, task, conversation_id: str) -> bool:
        """Stream a task created event."""
        data = {
            "conversationId": conversation_id,
            "taskId": get_task_id(task),
            "task": task.model_dump() if hasattr(task, 'model_dump') else task.__dict__,
            "contextId": get_context_id(task),
            "action": "created"
        }
        return await self._send_event("task", data, conversation_id)
    
    async def stream_task_updated(self, task, conversation_id: str) -> bool:
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
    
    async def stream_event_occurred(self, event) -> bool:
        """Stream a general event."""
        data = {
            "eventId": getattr(event, 'id', ''),
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
    
    # === Helper Methods ===
    
    def _extract_message_content(self, message) -> List[Dict[str, Any]]:
        """Extract message content into a serializable format.
        
        Args:
            message: A2A Message object or similar
            
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
                        content.append({
                            "type": "file",
                            "content": f"File: {getattr(part.file, 'name', 'unknown')}"
                        })
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


