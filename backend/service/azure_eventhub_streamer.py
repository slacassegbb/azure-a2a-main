"""Azure Event Hub Integration for A2A Data Streaming

This module provides integration with Azure Event Hub to stream all UX data
from the A2A system to external consumers like TypeScript frontends.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
from azure.eventhub.aio import EventHubProducerClient
from azure.eventhub import EventData
from azure.identity.aio import DefaultAzureCredential
from azure.core.exceptions import AzureError
import uuid

from state.state import StateMessage, StateConversation, StateTask, StateEvent
from a2a.types import Message


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
        # Final fallback using getattr
        return getattr(obj, 'messageId', getattr(obj, 'message_id', default or str(uuid.uuid4())))
    except Exception:
        return default or str(uuid.uuid4())


logger = logging.getLogger(__name__)


class EventHubStreamer:
    """
    Azure Event Hub streamer for A2A system data.
    
    This class captures and streams all key data from the A2A system including:
    - Messages (user inputs, agent responses)
    - Conversations (creation, updates, state changes)
    - Tasks (creation, progress, completion)
    - Events (system events, agent interactions)
    - File uploads and attachments
    - Form submissions and responses
    """

    def __init__(
        self,
        event_hub_namespace: Optional[str] = None,
        event_hub_name: Optional[str] = None,
        connection_string: Optional[str] = None,
        use_managed_identity: bool = True
    ):
        """
        Initialize the Event Hub streamer.
        
        Args:
            event_hub_namespace: Azure Event Hub namespace (e.g., 'myehns.servicebus.windows.net')
            event_hub_name: Name of the Event Hub
            connection_string: Connection string (alternative to managed identity)
            use_managed_identity: Whether to use Azure Managed Identity for authentication
        """
        self.event_hub_namespace = event_hub_namespace or os.getenv('AZURE_EVENTHUB_NAMESPACE')
        self.event_hub_name = event_hub_name or os.getenv('AZURE_EVENTHUB_NAME')
        self.connection_string = connection_string or os.getenv('AZURE_EVENTHUB_CONNECTION_STRING')
        self.use_managed_identity = use_managed_identity
        
        self._producer_client: Optional[EventHubProducerClient] = None
        self._credential = None
        self._is_initialized = False
        
        # Validate configuration
        if not self.event_hub_name:
            logger.warning("Event Hub name not provided - Event Hub features will be disabled")
            logger.info("To enable Event Hub, set AZURE_EVENTHUB_NAME environment variable")
            return  # Don't raise exception, just disable Event Hub
        
        if not self.connection_string and not self.event_hub_namespace:
            logger.warning("Neither connection string nor Event Hub namespace provided")
            logger.info("To enable Event Hub, set AZURE_EVENTHUB_CONNECTION_STRING or AZURE_EVENTHUB_NAMESPACE")
            logger.info("Event Hub features will be disabled")
            return  # Don't raise exception, just disable Event Hub

    async def initialize(self) -> bool:
        """
        Initialize the Event Hub client with smart authentication fallback.
        Tries connection string first, then falls back to managed identity if that fails.
        
        Returns:
            bool: True if initialization successful, False otherwise
        """
        try:
            logger.info("=== Event Hub Initialization Debug ===")
            logger.info(f"Event Hub Name: {self.event_hub_name}")
            logger.info(f"Event Hub Namespace: {self.event_hub_namespace}")
            logger.info(f"Has Connection String: {bool(self.connection_string)}")
            
            # Strategy 1: Try connection string first (if available)
            if self.connection_string:
                logger.info("Attempting connection string authentication (primary method)...")
                success = await self._try_connection_string_auth()
                if success:
                    logger.info("✅ Connection string authentication successful!")
                    return True
                else:
                    logger.warning("❌ Connection string authentication failed, trying managed identity fallback...")
            
            # Strategy 2: Fall back to managed identity
            if self.event_hub_namespace:
                logger.info("Attempting managed identity authentication (fallback method)...")
                success = await self._try_managed_identity_auth()
                if success:
                    logger.info("✅ Managed identity authentication successful!")
                    return True
                else:
                    logger.error("❌ Managed identity authentication also failed")
            
            logger.error("❌ All authentication methods failed")
            self._is_initialized = False
            return False
            
        except Exception as e:
            logger.error(f"Failed to initialize Event Hub client: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error details: {str(e)}")
            self._is_initialized = False
            return False

    async def _try_connection_string_auth(self) -> bool:
        """Try to authenticate using connection string."""
        try:
            # Mask the connection string for security
            masked_conn = self.connection_string[:20] + "***" + self.connection_string[-10:] if len(self.connection_string) > 30 else "***"
            logger.info(f"Connection string (masked): {masked_conn}")
            
            # Use connection string authentication
            self._producer_client = EventHubProducerClient.from_connection_string(
                self.connection_string,
                eventhub_name=self.event_hub_name
            )
            logger.info("Event Hub producer client created with connection string")
            
            # Test the connection
            return await self._test_connection("connection string")
            
        except Exception as e:
            logger.warning(f"Connection string authentication failed: {e}")
            return False

    async def _try_managed_identity_auth(self) -> bool:
        """Try to authenticate using managed identity."""
        try:
            logger.info("Using Managed Identity authentication")
            logger.info("This requires the container to have proper Azure role assignments")
            
            # Use Managed Identity authentication
            self._credential = DefaultAzureCredential()
            
            # Construct the fully qualified namespace
            if self.event_hub_namespace.endswith('.servicebus.windows.net'):
                fully_qualified_namespace = self.event_hub_namespace
            else:
                fully_qualified_namespace = f"{self.event_hub_namespace}.servicebus.windows.net"
            
            logger.info(f"Fully qualified namespace: {fully_qualified_namespace}")
            logger.info(f"Event Hub name: {self.event_hub_name}")
            
            self._producer_client = EventHubProducerClient(
                fully_qualified_namespace=fully_qualified_namespace,
                eventhub_name=self.event_hub_name,
                credential=self._credential
            )
            logger.info("Event Hub producer client created with Managed Identity")
            logger.info("Required Azure roles: 'Azure Event Hubs Data Sender' or 'Azure Event Hubs Data Owner'")
            
            # Test the connection
            return await self._test_connection("managed identity")
            
        except Exception as e:
            logger.warning(f"Managed identity authentication failed: {e}")
            return False

    async def _test_connection(self, auth_method: str) -> bool:
        """Test the Event Hub connection."""
        try:
            logger.info(f"Testing Event Hub connection with {auth_method}...")
            eventhub_properties = await self._producer_client.get_eventhub_properties()
            
            # Handle both dict and object responses from Azure SDK
            if hasattr(eventhub_properties, 'name'):
                # Object response
                name = eventhub_properties.name
                partition_ids = eventhub_properties.partition_ids
            else:
                # Dict response
                name = eventhub_properties.get('name', 'unknown')
                partition_ids = eventhub_properties.get('partition_ids', [])
            
            logger.info(f"Event Hub properties retrieved: {name}, partitions: {partition_ids}")
            logger.info(f"✅ {auth_method.title()} connection test successful!")
            
            self._is_initialized = True
            return True
            
        except Exception as conn_test_error:
            logger.warning(f"{auth_method.title()} connection test failed: {conn_test_error}")
            logger.warning(f"Connection test error type: {type(conn_test_error).__name__}")
            
            # Provide specific guidance based on error type
            if "AuthenticationError" in str(type(conn_test_error).__name__) or "auth" in str(conn_test_error).lower():
                if auth_method == "connection string":
                    logger.warning("Connection string authentication failed - check if the connection string is valid")
                else:
                    logger.warning("Managed Identity authentication failed")
                    logger.warning("Ensure the container has the following Azure role assignments:")
                    logger.warning("  - 'Azure Event Hubs Data Sender' (recommended for producer-only access)")
                    logger.warning("  - OR 'Azure Event Hubs Data Owner' (for full access)")
                    logger.warning("Assign these roles to the container's managed identity or user-assigned identity")
            elif "not found" in str(conn_test_error).lower() or "does not exist" in str(conn_test_error).lower():
                logger.warning(f"Event Hub namespace or Event Hub '{self.event_hub_name}' not found")
                logger.warning("Please verify the Event Hub namespace and name are correct")
            
            self._is_initialized = False
            return False

    async def close(self):
        """Close the Event Hub client and credential."""
        try:
            if self._producer_client:
                await self._producer_client.close()
            if self._credential:
                await self._credential.close()
            self._is_initialized = False
            logger.info("Event Hub client closed successfully")
        except Exception as e:
            logger.error(f"Error closing Event Hub client: {e}")

    async def _send_event(self, event_type: str, data: Dict[str, Any], partition_key: Optional[str] = None) -> bool:
        """
        Send a single event to Event Hub.
        
        Args:
            event_type: Type of event (e.g., 'message', 'conversation', 'task', 'event')
            data: Event data dictionary
            partition_key: Optional partition key for event ordering
            
        Returns:
            bool: True if event sent successfully, False otherwise
        """
        logger.info(f"=== Attempting to send {event_type} event ===")
        logger.info(f"Event Hub initialized: {self._is_initialized}")
        logger.info(f"Producer client exists: {self._producer_client is not None}")
        logger.info(f"Partition key: {partition_key}")
        logger.info(f"Data keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
        
        if not self._is_initialized or not self._producer_client:
            logger.error(f"Event Hub client not initialized, cannot send {event_type} event")
            logger.error(f"_is_initialized: {self._is_initialized}")
            logger.error(f"_producer_client: {self._producer_client}")
            return False

        max_retries = 2
        for attempt in range(max_retries):
            try:
                logger.info(f"Send attempt {attempt + 1} for {event_type} event")
                
                # Create event envelope with metadata
                event_envelope = {
                    "eventType": event_type,
                    "timestamp": datetime.utcnow().isoformat(),
                    "eventId": str(uuid.uuid4()),
                    "source": "a2a-system",
                    "data": data
                }
                
                # Log the event envelope size and structure
                event_json = json.dumps(event_envelope)
                logger.info(f"Event envelope size: {len(event_json)} bytes")
                logger.debug(f"Event envelope: {event_json}")
                
                # Create Event Hub event
                event_data = EventData(event_json)
                logger.info(f"EventData object created successfully")
                
                # Send event to Event Hub - reuse the existing connection
                logger.info(f"Sending to Event Hub with partition_key: {partition_key}")
                if partition_key:
                    # Send with partition key for event ordering
                    await self._producer_client.send_batch([event_data], partition_key=partition_key)
                    logger.info(f"Successfully sent {event_type} event with partition key")
                else:
                    # Send without partition key
                    await self._producer_client.send_batch([event_data])
                    logger.info(f"Successfully sent {event_type} event without partition key")
                
                logger.info(f"✅ Event {event_type} sent successfully to Event Hub")
                return True
                
            except AzureError as e:
                logger.error(f"❌ Azure error sending {event_type} event (attempt {attempt + 1}): {e}")
                logger.error(f"Azure error type: {type(e).__name__}")
                logger.error(f"Azure error details: {str(e)}")
                
                # Try to recover connection on failure
                if attempt < max_retries - 1:
                    logger.warning(f"Attempting to recover Event Hub connection...")
                    try:
                        # Close existing connection first
                        if self._producer_client:
                            await self._producer_client.close()
                            logger.info("Closed existing producer client")
                    except Exception as close_error:
                        logger.warning(f"Error closing producer client: {close_error}")
                    
                    recovery_success = await self.initialize()
                    if not recovery_success:
                        logger.error("Failed to recover Event Hub connection")
                        return False
                    else:
                        logger.info("Event Hub connection recovered successfully")
                else:
                    logger.error(f"❌ Failed to send {event_type} event after {max_retries} attempts")
                    return False
            except Exception as e:
                logger.error(f"❌ Unexpected error sending {event_type} event: {e}")
                logger.error(f"Unexpected error type: {type(e).__name__}")
                logger.error(f"Unexpected error details: {str(e)}")
                return False
        
        logger.error(f"❌ All retry attempts failed for {event_type} event")
        return False

    async def diagnose_connection(self) -> Dict[str, Any]:
        """
        Diagnose Event Hub connection and configuration issues.
        
        Returns:
            Dictionary with diagnostic information
        """
        diagnosis = {
            "config_status": "unknown",
            "connection_status": "unknown",
            "client_status": "unknown",
            "test_send_status": "unknown",
            "errors": [],
            "recommendations": []
        }
        
        try:
            logger.info("=== Event Hub Connection Diagnosis ===")
            
            # Check configuration
            logger.info("1. Checking configuration...")
            if not self.event_hub_name:
                diagnosis["errors"].append("Event Hub name is missing")
                diagnosis["recommendations"].append("Set AZURE_EVENTHUB_NAME environment variable")
            
            if not self.connection_string and not self.event_hub_namespace:
                diagnosis["errors"].append("Neither connection string nor namespace provided")
                diagnosis["recommendations"].append("Set AZURE_EVENTHUB_CONNECTION_STRING or AZURE_EVENTHUB_NAMESPACE")
            
            if self.connection_string:
                diagnosis["config_status"] = "connection_string"
                logger.info("✅ Configuration: Using connection string")
            elif self.event_hub_namespace:
                diagnosis["config_status"] = "managed_identity"
                logger.info("✅ Configuration: Using managed identity")
            
            # Check initialization
            logger.info("2. Checking initialization...")
            if not self._is_initialized:
                logger.info("Initializing Event Hub client...")
                init_success = await self.initialize()
                if not init_success:
                    diagnosis["errors"].append("Failed to initialize Event Hub client")
                    return diagnosis
            
            diagnosis["client_status"] = "initialized"
            logger.info("✅ Client initialized successfully")
            
            # Test connection
            logger.info("3. Testing connection...")
            try:
                properties = await self._producer_client.get_eventhub_properties()
                diagnosis["connection_status"] = "connected"
                
                # Handle both dict and object responses
                if hasattr(properties, 'name'):
                    diagnosis["eventhub_properties"] = {
                        "name": properties.name,
                        "partition_count": len(properties.partition_ids),
                        "partition_ids": properties.partition_ids
                    }
                else:
                    name = properties.get('name', 'unknown')
                    partition_ids = properties.get('partition_ids', [])
                    diagnosis["eventhub_properties"] = {
                        "name": name,
                        "partition_count": len(partition_ids),
                        "partition_ids": partition_ids
                    }
                
                logger.info(f"✅ Connection test successful: {diagnosis['eventhub_properties']['name']}")
            except Exception as conn_error:
                diagnosis["errors"].append(f"Connection test failed: {conn_error}")
                diagnosis["connection_status"] = "failed"
                logger.error(f"❌ Connection test failed: {conn_error}")
                return diagnosis
            
            # Test sending a simple event
            logger.info("4. Testing event sending...")
            test_data = {
                "test": True,
                "timestamp": datetime.utcnow().isoformat(),
                "message": "Event Hub diagnostic test"
            }
            
            send_success = await self._send_event("diagnostic_test", test_data)
            if send_success:
                diagnosis["test_send_status"] = "success"
                logger.info("✅ Test event sent successfully")
            else:
                diagnosis["errors"].append("Failed to send test event")
                diagnosis["test_send_status"] = "failed"
                logger.error("❌ Test event send failed")
            
        except Exception as e:
            diagnosis["errors"].append(f"Diagnostic error: {e}")
            logger.error(f"❌ Diagnostic error: {e}")
        
        return diagnosis

    def is_properly_configured(self) -> bool:
        """Check if Event Hub is properly configured."""
        return bool(
            self.event_hub_name and 
            (self.connection_string or self.event_hub_namespace)
        )

    def get_configuration_summary(self) -> Dict[str, Any]:
        """Get a summary of the current configuration."""
        return {
            "event_hub_name": self.event_hub_name,
            "event_hub_namespace": self.event_hub_namespace,
            "has_connection_string": bool(self.connection_string),
            "authentication_method": "connection_string" if self.connection_string else "managed_identity",
            "is_configured": self.is_properly_configured(),
            "is_initialized": self._is_initialized
        }

    # Message streaming methods
    async def stream_message_sent(self, message: Message, conversation_id: str) -> bool:
        """Stream outgoing message data."""
        data = {
            "messageId": get_message_id(message),
            "conversationId": conversation_id,
            "contextId": get_context_id(message),
            "role": message.role.name if message.role else "unknown",
            "content": self._extract_message_content(message),
            "direction": "outgoing"
        }
        return await self._send_event("message", data, conversation_id)

    async def stream_message_received(self, message: Message, conversation_id: str) -> bool:
        """Stream incoming message data."""
        data = {
            "messageId": get_message_id(message),
            "conversationId": conversation_id,
            "contextId": get_context_id(message),
            "role": message.role.name if message.role else "unknown",
            "content": self._extract_message_content(message),
            "direction": "incoming"
        }
        return await self._send_event("message", data, conversation_id)

    async def stream_conversation_created(self, conversation: StateConversation) -> bool:
        """Stream conversation creation event."""
        data = {
            "conversationId": conversation.conversation_id,
            "conversationName": conversation.conversation_name,
            "isActive": conversation.is_active,
            "messageCount": len(conversation.message_ids)
        }
        return await self._send_event("conversation_created", data, conversation.conversation_id)

    async def stream_conversation_updated(self, conversation: StateConversation) -> bool:
        """Stream conversation update event."""
        data = {
            "conversationId": conversation.conversation_id,
            "conversationName": conversation.conversation_name,
            "isActive": conversation.is_active,
            "messageCount": len(conversation.message_ids)
        }
        return await self._send_event("conversation_updated", data, conversation.conversation_id)

    async def stream_task_created(self, task: StateTask, conversation_id: str) -> bool:
        """Stream task creation event."""
        data = {
            "taskId": task.task_id,
            "conversationId": conversation_id,
            "contextId": get_context_id(task),
            "state": task.state,
            "artifactsCount": len(task.artifacts) if task.artifacts else 0
        }
        return await self._send_event("task_created", data, conversation_id)

    async def stream_task_updated(self, task: StateTask, conversation_id: str) -> bool:
        """Stream task update event."""
        data = {
            "taskId": task.task_id,
            "conversationId": conversation_id,
            "contextId": get_context_id(task),
            "state": task.state,
            "artifactsCount": len(task.artifacts) if task.artifacts else 0
        }
        return await self._send_event("task_updated", data, conversation_id)

    async def stream_event_occurred(self, event: StateEvent) -> bool:
        """Stream system event."""
        data = {
            "eventId": event.id,
            "conversationId": get_context_id(event),
            "actor": event.actor,
            "role": event.role,
            "content": event.content
        }
        return await self._send_event("system_event", data, get_context_id(event))

    async def stream_file_uploaded(self, file_info: Dict[str, Any], conversation_id: str) -> bool:
        """Stream file upload event."""
        data = {
            "fileName": file_info.get("name"),
            "fileSize": len(file_info.get("bytes", "")),
            "mimeType": file_info.get("mimeType"),
            "conversationId": conversation_id,
            "uploadTimestamp": datetime.utcnow().isoformat()
        }
        return await self._send_event("file_uploaded", data, conversation_id)

    async def stream_form_submitted(self, form_data: Dict[str, Any], conversation_id: str) -> bool:
        """Stream form submission event."""
        data = {
            "conversationId": conversation_id,
            "formData": form_data,
            "submissionTimestamp": datetime.utcnow().isoformat()
        }
        return await self._send_event("form_submitted", data, conversation_id)

    async def stream_api_key_updated(self, success: bool) -> bool:
        """Stream API key update event."""
        data = {
            "success": success,
            "timestamp": datetime.utcnow().isoformat()
        }
        return await self._send_event("api_key_updated", data)

    async def stream_agent_registered(self, agent_path: str, agent_name: Optional[str] = None) -> bool:
        """Stream agent registration event."""
        data = {
            "agentPath": agent_path,
            "agentName": agent_name or self._extract_agent_name_from_path(agent_path),
            "status": "registered",
            "timestamp": datetime.utcnow().isoformat(),
            "avatar": f"/api/agents/{agent_name or self._extract_agent_name_from_path(agent_path)}/avatar"
        }
        return await self._send_event("agent_registered", data)

    async def stream_agent_self_registered(self, agent_info: Dict[str, Any]) -> bool:
        """Stream self-registration event for agents that register themselves."""
        data = {
            "agentName": agent_info.get("name", "Unknown Agent"),
            "agentType": agent_info.get("type", "generic"),
            "capabilities": agent_info.get("capabilities", []),
            "status": "online",
            "timestamp": datetime.utcnow().isoformat(),
            "avatar": agent_info.get("avatar", "/placeholder.svg?height=32&width=32"),
            "endpoint": agent_info.get("endpoint"),
            "metadata": agent_info.get("metadata", {})
        }
        return await self._send_event("agent_self_registered", data)

    def _extract_agent_name_from_path(self, agent_path: str) -> str:
        """Extract agent name from file path."""
        import os
        # Get filename without extension
        filename = os.path.basename(agent_path)
        name_without_ext = os.path.splitext(filename)[0]
        # Convert to title case and replace underscores with spaces
        return name_without_ext.replace('_', ' ').title()

    def _extract_message_content(self, message: Message) -> List[Dict[str, Any]]:
        """Extract and structure message content for streaming."""
        content = []
        if message.parts:
            for part in message.parts:
                if hasattr(part.root, 'text'):
                    content.append({
                        "type": "text",
                        "content": part.root.text,
                        "mediaType": "text/plain"
                    })
                elif hasattr(part.root, 'file'):
                    file_part = part.root.file
                    content.append({
                        "type": "file",
                        "fileName": file_part.name if hasattr(file_part, 'name') else "unknown",
                        "fileSize": len(file_part.bytes) if hasattr(file_part, 'bytes') else 0,
                        "mediaType": "application/octet-stream"
                    })
        return content


# Global instance for singleton pattern
_event_hub_streamer: Optional[EventHubStreamer] = None


async def get_event_hub_streamer() -> Optional[EventHubStreamer]:
    """
    Get the global EventHubStreamer instance.
    
    Returns:
        EventHubStreamer instance if properly configured, None otherwise
    """
    global _event_hub_streamer
    
    logger.info("=== Getting Event Hub Streamer Instance ===")
    
    if _event_hub_streamer is None:
        try:
            logger.info("Creating new EventHubStreamer instance...")
            
            # Check environment variables
            connection_string = os.getenv("AZURE_EVENTHUB_CONNECTION_STRING")
            event_hub_name = os.getenv("AZURE_EVENTHUB_NAME", "a2a-events")
            event_hub_namespace = os.getenv("AZURE_EVENTHUB_NAMESPACE")
            
            logger.info(f"Environment variables:")
            logger.info(f"  AZURE_EVENTHUB_NAME: {event_hub_name}")
            logger.info(f"  AZURE_EVENTHUB_NAMESPACE: {event_hub_namespace}")
            logger.info(f"  AZURE_EVENTHUB_CONNECTION_STRING: {'SET' if connection_string else 'NOT SET'}")
            
            if not event_hub_namespace and not connection_string:
                logger.warning("Neither AZURE_EVENTHUB_NAMESPACE nor AZURE_EVENTHUB_CONNECTION_STRING is set")
                logger.warning("Event Hub features will be disabled")
                return None
            
            _event_hub_streamer = EventHubStreamer(
                connection_string=connection_string,
                event_hub_namespace=event_hub_namespace,
                event_hub_name=event_hub_name
            )
            logger.info("EventHubStreamer object created, attempting initialization...")
            
            success = await _event_hub_streamer.initialize()
            if not success:
                logger.warning("Event Hub streamer initialization failed")
                logger.warning("This is not critical - A2A system will continue without Event Hub streaming")
                logger.warning("To enable Event Hub, ensure managed identity has 'Azure Event Hubs Data Sender' role")
                _event_hub_streamer = None
            else:
                logger.info("✅ Event Hub streamer initialized successfully!")
                
        except Exception as e:
            logger.warning(f"Event Hub streamer creation failed: {e}")
            logger.warning("This is not critical - A2A system will continue without Event Hub streaming")
            logger.debug("Event Hub error details:", exc_info=True)
            _event_hub_streamer = None
    else:
        logger.debug("Using existing Event Hub streamer instance")
    
    return _event_hub_streamer


async def cleanup_event_hub_streamer():
    """Cleanup the global EventHubStreamer instance."""
    global _event_hub_streamer
    if _event_hub_streamer:
        await _event_hub_streamer.close()
        _event_hub_streamer = None
