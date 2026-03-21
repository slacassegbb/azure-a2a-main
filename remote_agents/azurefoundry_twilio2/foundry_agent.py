"""
AI Foundry Twilio SMS Agent implementation.
Uses Azure AI Agents SDK with function calling to send SMS messages via Twilio.

This agent is designed to be the final step in a workflow, receiving message content
from previous agents and sending it via SMS to the user.

HITL (Human-in-the-Loop) Support:
- Uses TWILIO_ASK tool to send SMS and wait for human response
- Incoming SMS responses are received via Twilio webhook
- Responses are forwarded to host orchestrator via A2A input_required state
"""
import os
import sys
import time
import datetime
import asyncio
import logging
import json
import uuid
import tempfile
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from datetime import timedelta

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import (
    Agent, ThreadMessage, ThreadRun, AgentThread, ToolOutput,
    ListSortOrder, FunctionTool, ToolSet
)
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

# Twilio imports
from twilio.rest import Client as TwilioClient
from twilio.base.exceptions import TwilioRestException

# Azure Blob Storage imports
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.core.credentials import AzureNamedKeyCredential, AzureSasCredential
import httpx

# Add shared module to path for credential helper
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from shared.credential_helper import get_user_credentials

logger = logging.getLogger(__name__)


# HITL support
@dataclass
class PendingSMSRequest:
    """Tracks a pending SMS request waiting for human response."""
    context_id: str
    to_number: str
    question: str
    timestamp: float
    thread_id: Optional[str] = None


class FoundryTwilioAgent:
    """
    AI Foundry Twilio SMS Agent with function calling capabilities.
    
    This agent uses Azure AI Foundry to process requests and call the send_sms
    function when appropriate to deliver messages via Twilio.
    
    HITL Support:
    - pending_requests: Dict tracking SMS conversations waiting for human response
    - request_human_input(): Sends SMS and waits for response via webhook
    """
    
    # Class-level pending requests (shared across instances for webhook access)
    pending_requests: Dict[str, 'PendingSMSRequest'] = {}
    
    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self.agent: Optional[Agent] = None
        self.threads: Dict[str, str] = {}
        self._agents_client = None
        self._project_client = None
        self._twilio_client = None
        self._blob_service_client: Optional[BlobServiceClient] = None
        self.last_token_usage: Optional[Dict[str, int]] = None

        # Twilio configuration
        self.twilio_account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        self.twilio_auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        self.twilio_from_number = os.environ.get("TWILIO_FROM_NUMBER")
        self.twilio_default_to_number = os.environ.get("TWILIO_DEFAULT_TO_NUMBER")
        
    def _get_client(self) -> AgentsClient:
        """Get a cached AgentsClient instance."""
        if self._agents_client is None:
            self._agents_client = AgentsClient(
                endpoint=self.endpoint,
                credential=self.credential,
            )
        return self._agents_client
        
    def _get_project_client(self) -> AIProjectClient:
        """Get a cached AIProjectClient instance."""
        if self._project_client is None:
            self._project_client = AIProjectClient(
                endpoint=self.endpoint,
                credential=self.credential,
            )
        return self._project_client
    
    def _get_twilio_client(self) -> TwilioClient:
        """Get a cached Twilio client instance."""
        if self._twilio_client is None:
            if not self.twilio_account_sid or not self.twilio_auth_token:
                raise ValueError("Twilio credentials not configured. Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN")
            self._twilio_client = TwilioClient(self.twilio_account_sid, self.twilio_auth_token)
        return self._twilio_client
    
    def _get_blob_service_client(self) -> Optional[BlobServiceClient]:
        """Return a BlobServiceClient if Azure storage is configured."""
        force_blob = os.getenv("FORCE_AZURE_BLOB", "false").lower() == "true"
        if not force_blob:
            return None
        if self._blob_service_client is not None:
            return self._blob_service_client

        connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            logger.error("AZURE_STORAGE_CONNECTION_STRING must be set when FORCE_AZURE_BLOB=true")
            return None

        try:
            self._blob_service_client = BlobServiceClient.from_connection_string(
                connection_string,
                api_version="2023-11-03",
            )
            return self._blob_service_client
        except Exception as e:
            logger.error(f"Failed to create BlobServiceClient: {e}")
            return None

    def _upload_to_blob(self, file_path: Path) -> Optional[str]:
        """Upload a file to Azure Blob Storage and return a SAS-signed URL."""
        blob_client = self._get_blob_service_client()
        if not blob_client:
            return None

        container_name = os.getenv("AZURE_BLOB_CONTAINER", "a2a-files")
        file_id = uuid.uuid4().hex
        context_id = getattr(self, '_current_context_id', None)
        session_id = None
        if context_id and '::' in context_id:
            session_id = context_id.split('::')[0]

        if session_id:
            blob_name = f"uploads/{session_id}/{file_id}/{file_path.name}"
        else:
            blob_name = f"twilio-mms/{file_id}/{file_path.name}"

        try:
            container_client = blob_client.get_container_client(container_name)
            if not container_client.exists():
                container_client.create_container()
            with open(file_path, "rb") as data:
                container_client.upload_blob(name=blob_name, data=data, overwrite=True)

            sas_duration_minutes = int(os.getenv("AZURE_BLOB_SAS_DURATION_MINUTES", str(24 * 60)))
            sas_token: Optional[str] = None
            service_client = self._blob_service_client

            if service_client is not None:
                credential = getattr(service_client, "credential", None)
                account_key_value: Optional[str] = None

                if isinstance(credential, AzureNamedKeyCredential):
                    account_key_value = credential.key
                elif isinstance(credential, AzureSasCredential):
                    sas_token = credential.signature.lstrip("?")
                elif hasattr(credential, "account_key"):
                    account_key_value = getattr(credential, "account_key")
                elif hasattr(credential, "key"):
                    account_key_value = getattr(credential, "key")

                if callable(account_key_value):
                    account_key_value = account_key_value()
                if isinstance(account_key_value, bytes):
                    account_key_value = account_key_value.decode()

                if account_key_value:
                    try:
                        sas_token = generate_blob_sas(
                            account_name=service_client.account_name,
                            container_name=container_name,
                            blob_name=blob_name,
                            account_key=account_key_value,
                            permission=BlobSasPermissions(read=True),
                            expiry=datetime.datetime.utcnow() + timedelta(minutes=sas_duration_minutes),
                            protocol="https",
                            version="2023-11-03",
                        )
                    except Exception as sas_error:
                        logger.error(f"Failed to generate SAS URL with shared key: {sas_error}")

            if sas_token is None and self._blob_service_client is not None:
                try:
                    delegation_key = self._blob_service_client.get_user_delegation_key(
                        key_start_time=datetime.datetime.utcnow() - timedelta(minutes=5),
                        key_expiry_time=datetime.datetime.utcnow() + timedelta(minutes=sas_duration_minutes),
                    )
                    sas_token = generate_blob_sas(
                        account_name=self._blob_service_client.account_name,
                        container_name=container_name,
                        blob_name=blob_name,
                        user_delegation_key=delegation_key,
                        permission=BlobSasPermissions(read=True),
                        expiry=datetime.datetime.utcnow() + timedelta(minutes=sas_duration_minutes),
                        version="2023-11-03",
                    )
                except Exception as ude_err:
                    logger.warning(f"Failed to generate user delegation SAS: {ude_err}")

            if sas_token:
                base_url = blob_client.get_blob_client(container=container_name, blob=blob_name).url
                token = sas_token.lstrip("?")
                separator = '&' if '?' in base_url else '?'
                return f"{base_url}{separator}{token}"

            logger.error("Unable to generate SAS token for blob upload")
            return None
        except Exception as e:
            logger.error(f"Failed to upload {file_path} to blob storage: {e}")
            return None

    async def download_and_upload_media(self, media_url: str, media_content_type: str, context_id: str = "") -> Optional[Dict]:
        """Download MMS media from Twilio and upload to Azure Blob Storage.

        Returns dict with blob_url, mime_type, filename on success, None on failure.
        """
        try:
            self._current_context_id = context_id

            ext_map = {
                'image/jpeg': '.jpg', 'image/png': '.png', 'image/gif': '.gif',
                'image/webp': '.webp', 'image/heic': '.heic',
                'video/mp4': '.mp4', 'video/3gpp': '.3gp',
                'audio/mpeg': '.mp3', 'audio/ogg': '.ogg', 'audio/amr': '.amr',
                'application/pdf': '.pdf',
            }
            ext = ext_map.get(media_content_type, '.bin')
            filename = f"mms_{uuid.uuid4().hex[:8]}{ext}"

            # Download from Twilio (requires basic auth)
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    media_url,
                    auth=(self.twilio_account_sid, self.twilio_auth_token),
                    follow_redirects=True,
                )
                if response.status_code != 200:
                    logger.error(f"[MMS] Failed to download media: HTTP {response.status_code}")
                    return None
                media_bytes = response.content

            if len(media_bytes) > 5 * 1024 * 1024:
                logger.warning(f"[MMS] Media too large ({len(media_bytes)} bytes), skipping")
                return None

            # Save to temp file and upload to blob
            tmp_path = Path(tempfile.gettempdir()) / filename
            tmp_path.write_bytes(media_bytes)

            blob_url = self._upload_to_blob(tmp_path)

            try:
                tmp_path.unlink()
            except Exception:
                pass

            if blob_url:
                logger.info(f"[MMS] Uploaded {filename} ({media_content_type}, {len(media_bytes)} bytes) to blob")
                return {
                    'blob_url': blob_url,
                    'mime_type': media_content_type,
                    'filename': filename,
                    'size': len(media_bytes),
                }
            else:
                logger.error("[MMS] Failed to upload media to blob storage")
                return None

        except Exception as e:
            logger.error(f"[MMS] Error processing media: {e}", exc_info=True)
            return None

    def _validate_twilio_config(self) -> bool:
        """Validate Twilio configuration."""
        missing = []
        if not self.twilio_account_sid:
            missing.append("TWILIO_ACCOUNT_SID")
        if not self.twilio_auth_token:
            missing.append("TWILIO_AUTH_TOKEN")
        if not self.twilio_from_number:
            missing.append("TWILIO_FROM_NUMBER")

        if missing:
            logger.error(f"Missing Twilio configuration: {', '.join(missing)}")
            return False
        return True

    async def _resolve_to_number(self) -> Optional[str]:
        """Resolve the recipient phone number from user credentials or env var fallback.

        Uses the context_id (set per-request) to look up user-specific config.
        Falls back to TWILIO_DEFAULT_TO_NUMBER env var.
        """
        context_id = getattr(self, '_current_context_id', None)
        if context_id:
            try:
                user_creds = await get_user_credentials(context_id, "Twilio SMS Agent")
                if user_creds:
                    user_phone = user_creds.get("to_phone_number")
                    if user_phone:
                        logger.info(f"Resolved user phone number from credentials for context={context_id}")
                        return user_phone
            except Exception as e:
                logger.warning(f"Failed to resolve user credentials: {e}")
        return self.twilio_default_to_number
    
    def send_sms(self, message: str, to_number: Optional[str] = None,
                 media_urls: Optional[List[str]] = None) -> Dict:
        """
        Send an SMS or MMS message via Twilio.

        Args:
            message: The message body
            to_number: Recipient phone number (uses default if not provided)
            media_urls: Optional list of publicly accessible media URLs to attach (sends as MMS)

        Returns:
            Dict with success status and details
        """
        try:
            client = self._get_twilio_client()
            recipient = to_number or self.twilio_default_to_number

            if not recipient:
                return {
                    "success": False,
                    "error": "No recipient phone number provided and no default configured"
                }

            if len(message) > 1600:
                message = message[:1597] + "..."
                logger.warning("Message truncated to 1600 characters")

            create_kwargs = {
                'body': message,
                'from_': self.twilio_from_number,
                'to': recipient,
            }

            # Attach media URLs for MMS (Twilio allows up to 10)
            if media_urls:
                create_kwargs['media_url'] = media_urls[:10]
                logger.info(f"📎 Sending MMS with {len(media_urls[:10])} media attachment(s)")

            msg = client.messages.create(**create_kwargs)

            result = {
                "success": True,
                "message_sid": msg.sid,
                "from": self.twilio_from_number,
                "to": recipient,
                "status": msg.status,
                "body_length": len(message),
                "media_count": len(media_urls) if media_urls else 0,
            }

            msg_type = "MMS" if media_urls else "SMS"
            logger.info(f"✅ {msg_type} sent successfully: SID={msg.sid}, To={recipient}")
            return result

        except TwilioRestException as e:
            logger.error(f"❌ Twilio API error: {e}")
            return {
                "success": False,
                "error": str(e),
                "error_code": e.code if hasattr(e, 'code') else None
            }
        except Exception as e:
            logger.error(f"❌ Unexpected error sending message: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def send_mms(self, message: str, to_number: Optional[str] = None,
                 media_urls: Optional[List[str]] = None) -> Dict:
        """Send an MMS message with media attachments via Twilio."""
        try:
            client = self._get_twilio_client()
            recipient = to_number or self.twilio_default_to_number

            if not recipient:
                return {"success": False, "error": "No recipient phone number"}

            if len(message) > 1600:
                message = message[:1597] + "..."

            create_kwargs = {
                'body': message,
                'from_': self.twilio_from_number,
                'to': recipient,
            }
            if media_urls:
                create_kwargs['media_url'] = media_urls[:10]

            msg = client.messages.create(**create_kwargs)

            result = {
                "success": True,
                "message_sid": msg.sid,
                "from": self.twilio_from_number,
                "to": recipient,
                "status": msg.status,
                "body_length": len(message),
                "media_count": len(media_urls) if media_urls else 0,
            }
            logger.info(f"MMS sent: SID={msg.sid}, To={recipient}, media={len(media_urls or [])}")
            return result

        except TwilioRestException as e:
            logger.error(f"Twilio MMS API error: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error sending MMS: {e}")
            return {"success": False, "error": str(e)}

    def receive_sms(self, from_number: Optional[str] = None, limit: int = 10) -> Dict:
        """
        Retrieve recent SMS messages received by this Twilio number.
        
        Args:
            from_number: Optional filter to only get messages from a specific phone number
            limit: Maximum number of messages to retrieve (default: 10, max: 50)
            
        Returns:
            Dict with success status and list of messages
        """
        try:
            client = self._get_twilio_client()
            
            # Limit to reasonable bounds
            limit = min(max(1, limit), 50)
            
            # Build filter parameters
            filter_params = {
                'to': self.twilio_from_number,  # Messages received by our Twilio number
                'limit': limit
            }
            
            if from_number:
                filter_params['from_'] = from_number
            
            # Retrieve messages
            messages = client.messages.list(**filter_params)
            
            # Format message data
            message_list = []
            for msg in messages:
                message_list.append({
                    "message_sid": msg.sid,
                    "from": msg.from_,
                    "to": msg.to,
                    "body": msg.body,
                    "status": msg.status,
                    "direction": msg.direction,
                    "date_sent": msg.date_sent.isoformat() if msg.date_sent else None,
                    "date_created": msg.date_created.isoformat() if msg.date_created else None
                })
            
            result = {
                "success": True,
                "message_count": len(message_list),
                "messages": message_list
            }
            
            logger.info(f"✅ Retrieved {len(message_list)} SMS message(s)")
            return result
            
        except TwilioRestException as e:
            logger.error(f"❌ Twilio API error: {e}")
            return {
                "success": False,
                "error": str(e),
                "error_code": e.code if hasattr(e, 'code') else None
            }
        except Exception as e:
            logger.error(f"❌ Unexpected error retrieving SMS: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def twilio_ask(self, question: str, context_id: str, to_number: Optional[str] = None, thread_id: Optional[str] = None) -> Dict:
        """
        Send an SMS question and wait for human response via HITL.
        
        This function:
        1. Sends an SMS to the user with the question
        2. Stores the pending request for webhook processing
        3. Returns immediately - the response will come via webhook
        
        Args:
            question: The question or message to send to the user
            context_id: The A2A context ID for tracking this request
            to_number: Recipient phone number (uses default if not provided)
            thread_id: Optional thread ID for context tracking
            
        Returns:
            Dict with success status and pending request info
        """
        try:
            # First, send the SMS
            recipient = to_number or self.twilio_default_to_number
            
            if not recipient:
                return {
                    "success": False,
                    "error": "No recipient phone number provided and no default configured",
                    "hitl_triggered": False
                }
            
            # Send the SMS
            send_result = self.send_sms(question, recipient)
            
            if not send_result.get("success"):
                return {
                    "success": False,
                    "error": send_result.get("error", "Failed to send SMS"),
                    "hitl_triggered": False
                }
            
            # Store pending request for webhook processing
            pending_request = PendingSMSRequest(
                context_id=context_id,
                to_number=recipient,
                question=question,
                timestamp=time.time(),
                thread_id=thread_id
            )
            
            # Store by phone number for webhook lookup
            FoundryTwilioAgent.pending_requests[recipient] = pending_request
            
            logger.info(f"📱 HITL: Stored pending SMS request for {recipient}, context_id={context_id}")
            logger.info(f"📱 HITL: Question sent: {question[:100]}...")
            
            return {
                "success": True,
                "hitl_triggered": True,
                "message_sid": send_result.get("message_sid"),
                "to_number": recipient,
                "question": question,
                "context_id": context_id,
                "status": "waiting_for_response",
                "instruction": "SMS sent. Waiting for user response via webhook."
            }
            
        except Exception as e:
            logger.error(f"❌ Error in twilio_ask: {e}")
            return {
                "success": False,
                "error": str(e),
                "hitl_triggered": False
            }
    
    @classmethod
    def get_pending_request(cls, phone_number: str) -> Optional['PendingSMSRequest']:
        """Get a pending request by phone number."""
        return cls.pending_requests.get(phone_number)
    
    @classmethod
    def clear_pending_request(cls, phone_number: str) -> Optional['PendingSMSRequest']:
        """Clear and return a pending request by phone number."""
        return cls.pending_requests.pop(phone_number, None)
    
    @classmethod
    def get_all_pending_requests(cls) -> Dict[str, 'PendingSMSRequest']:
        """Get all pending requests."""
        return cls.pending_requests.copy()
    
    def _get_send_sms_tool_definition(self) -> Dict:
        """Get the function tool definition for send_sms."""
        return {
            "type": "function",
            "function": {
                "name": "send_sms",
                "description": """Send a text message (SMS) or multimedia message (MMS) via Twilio.

Use this function to:
- Send workflow results or summaries to a user's phone
- Deliver notifications or alerts via text message
- Send images, videos, or documents as MMS attachments
- Confirm completed actions with a text message

If media_urls are provided, the message is sent as MMS with the attached media.
If no phone number is provided, the default configured number will be used.""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The message content to send. Should be concise and informative. Max ~1600 characters."
                        },
                        "to_number": {
                            "type": "string",
                            "description": "Optional recipient phone number in E.164 format (e.g., +15147715943). If not provided, uses the default configured number."
                        },
                        "media_urls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of publicly accessible URLs to images, videos, or files to attach as MMS. URLs must be https:// and accessible by Twilio. Up to 10 attachments."
                        }
                    },
                    "required": ["message"],
                    "additionalProperties": False
                }
            }
        }
    
    def _get_receive_sms_tool_definition(self) -> Dict:
        """Get the function tool definition for receive_sms."""
        return {
            "type": "function",
            "function": {
                "name": "receive_sms",
                "description": """Retrieve recent SMS messages received by this Twilio number.
                
Use this function to:
- Check for replies from users after sending them an SMS
- Read incoming messages from a specific phone number
- Monitor recent SMS conversations
- Get the latest inbound messages

This retrieves messages from Twilio's message log, showing what users have texted to your Twilio number.""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "from_number": {
                            "type": "string",
                            "description": "Optional filter to only retrieve messages from a specific phone number in E.164 format (e.g., +15147715943). If not provided, retrieves from all senders."
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of recent messages to retrieve. Default is 10, maximum is 50.",
                            "minimum": 1,
                            "maximum": 50
                        }
                    },
                    "required": [],
                    "additionalProperties": False
                }
            }
        }
    
    def _get_twilio_ask_tool_definition(self) -> Dict:
        """Get the function tool definition for twilio_ask (HITL)."""
        return {
            "type": "function",
            "function": {
                "name": "twilio_ask",
                "description": """Send an SMS question to a user and wait for their response (Human-in-the-Loop).

IMPORTANT: Use this function when you need INTERACTIVE input from a human via SMS.

This function:
1. Sends an SMS to the user with your question
2. Pauses the workflow and waits for the user to reply via SMS
3. When the user replies, the response is automatically forwarded back to continue the workflow

Use this for:
- Asking for confirmation ("Do you want to proceed? Reply YES or NO")
- Gathering user input ("What is your order number?")
- Two-way conversations that require human decisions
- Approval workflows ("Please reply APPROVE or REJECT")

Do NOT use this for one-way notifications - use send_sms instead.""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The question or prompt to send to the user. Should be clear and tell the user what kind of response you expect."
                        },
                        "to_number": {
                            "type": "string",
                            "description": "Optional recipient phone number in E.164 format (e.g., +15147715943). If not provided, uses the default configured number."
                        }
                    },
                    "required": ["question"],
                    "additionalProperties": False
                }
            }
        }
        
    async def create_agent(self) -> Agent:
        """Create the AI Foundry agent with SMS sending, receiving, and HITL capabilities."""
        if self.agent:
            logger.info("Twilio SMS agent already exists, returning existing instance")
            return self.agent
        
        # Validate Twilio config before creating agent
        if not self._validate_twilio_config():
            raise ValueError("Twilio configuration is incomplete")
        
        tools = []
        
        # Add the send_sms function tool
        tools.append(self._get_send_sms_tool_definition())
        logger.info("Added send_sms function tool")
        
        # Add the receive_sms function tool
        tools.append(self._get_receive_sms_tool_definition())
        logger.info("Added receive_sms function tool")
        
        # Add the twilio_ask function tool (HITL)
        tools.append(self._get_twilio_ask_tool_definition())
        logger.info("Added twilio_ask function tool (HITL)")
        
        project_client = self._get_project_client()
        
        with project_client:
            self.agent = project_client.agents.create_agent(
                model=os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o"),
                name="foundry-twilio-sms-agent",
                instructions=self._get_agent_instructions(),
                tools=tools
            )
        
        logger.info(f"✅ Created Twilio SMS agent: {self.agent.id}")
        return self.agent
    
    def _get_agent_instructions(self) -> str:
        """Get the agent instructions for SMS messaging."""
        return f"""You are an SMS communication agent powered by Azure AI Foundry and Twilio.

## 🎯 YOUR PRIMARY ROLE: ALWAYS USE YOUR TOOLS

You are NOT a conversational AI - you are a TOOL EXECUTOR for SMS messaging.
When you receive ANY request, your DEFAULT behavior is to use one of your three tools.
NEVER respond with explanatory text unless a tool call fails.

## Your Capabilities
You have THREE tools available:

1. **send_sms**: Send a one-way SMS/MMS notification (fire and forget, no response expected). Include `media_urls` with image/video URLs to send as MMS.
2. **receive_sms**: Retrieve past SMS messages from the inbox
3. **twilio_ask**: Send an SMS question and WAIT for the user to reply (Human-in-the-Loop, pauses workflow)

## Decision Logic

When you receive a request:
1. **Is it a question?** → Use `twilio_ask` to send it via SMS and wait for reply
2. **Is it a statement/notification?** → Use `send_sms` to deliver it
3. **Is it asking about history?** → Use `receive_sms` to check inbox

## Phone Number Resolution

The `to_number` parameter is OPTIONAL. If the user does not specify a phone number, simply OMIT `to_number` from the tool call — the system will automatically resolve the recipient from the user's saved configuration.
NEVER ask the user for a phone number. Just call the tool without `to_number` and let the system handle it.

## Examples

✅ Request: "Send hello via SMS"
→ Action: `send_sms(message="Hello!")`
→ Reason: No phone number specified — system resolves it automatically

✅ Request: "What is your favorite food?"
→ Action: `twilio_ask(question="What is your favorite food?")`
→ Reason: This is a question that needs an SMS reply from the user

✅ Request: "Send 'Your balance is $100' to +15551234567"
→ Action: `send_sms(message="Your balance is $100", to_number="+15551234567")`
→ Reason: Explicit phone number provided

✅ Request: "Send the garden report with the image"
→ Action: `send_sms(message="Garden report: ...", media_urls=["https://blob.../garden.jpg"])`
→ Reason: Has an image URL from previous step — attach as MMS

✅ Request: "Check for replies"
→ Action: `receive_sms()`
→ Reason: Checking message history

❌ WRONG: Responding with "I can help you send an SMS..." - Just DO IT, don't explain!
❌ WRONG: Asking "What phone number should I send to?" - Just OMIT to_number and the system resolves it!

## IMPORTANT RULES

1. **The `message` and `question` parameters MUST NOT be empty!**
2. **ALWAYS use a tool - don't respond with conversational text**
3. **If you're unsure whether something is a question, assume it is and use twilio_ask**
4. **Your default action is to EXECUTE, not to EXPLAIN**
5. **NEVER ask the user for a phone number - omit `to_number` and the system resolves it automatically**

## Message Formatting Guidelines

Since SMS has character limits (~160 chars per segment, max ~1600 chars total):
- Be concise and direct
- Remove unnecessary formatting (no markdown, headers, or bullets)
- Focus on the key information
- If the original content is long, summarize it appropriately

## Examples of Good SMS Messages

For a balance inquiry result:
"Your Stripe balance: $1,234.56 (Available: $1,000.00, Pending: $234.56). As of Feb 2, 2026."

For a workflow completion:
"Task completed! Your document has been processed and sent to the review team. Reference: #12345"

For an alert:
"ALERT: Unusual activity detected on your account. Please review your recent transactions."

## Use Cases for Receiving Messages

- Check if a user has replied to your SMS
- Monitor incoming messages from specific phone numbers
- Retrieve conversation history
- Implement two-way SMS workflows (send question, wait for reply, process answer)

## Response Format

After sending an SMS, provide a brief confirmation:
```
📱 SMS SENT SUCCESSFULLY

**To**: [phone number]
**Message**: [content preview]
**Status**: [delivered/queued]
**Message SID**: [Twilio message ID]
```

After receiving messages, format them clearly:
```
📥 RECEIVED MESSAGES

**From**: +15551234567
**Date**: 2026-02-08 10:30:00
**Message**: "Yes, I confirm the order"

**From**: +15551234567
**Date**: 2026-02-08 10:25:00
**Message**: "What's my balance?"
```

If the SMS fails, explain the error and suggest alternatives.

## Error Reporting (CRITICAL)

If you CANNOT complete the requested task — due to rate limits, API errors, missing data,
authentication failures, or any other reason — you MUST start your response with "Error:".

Examples:
- "Error: Rate limit exceeded. Please try again later."
- "Error: Authentication failed — invalid credentials."
- "Error: Could not complete the request due to a service outage."

Do NOT write a polite explanation without the "Error:" prefix. The system uses this prefix
to detect failures. Without it, the task is marked as successful even though it failed.

Current date and time: {datetime.datetime.now().isoformat()}

Remember: You can both SEND and RECEIVE SMS messages. Always call the appropriate function!
"""

    async def create_thread(self, thread_id: Optional[str] = None) -> AgentThread:
        """Create or retrieve a conversation thread."""
        if thread_id and thread_id in self.threads:
            pass
            
        client = self._get_client()
        thread = client.threads.create()
        self.threads[thread.id] = thread.id
        logger.info(f"Created thread: {thread.id}")
        return thread
    
    async def send_message(self, thread_id: str, content: str, role: str = "user") -> ThreadMessage:
        """Send a message to the conversation thread."""
        client = self._get_client()
        message = client.messages.create(
            thread_id=thread_id,
            role=role,
            content=content
        )
        logger.info(f"Created message in thread {thread_id}: {message.id}")
        return message
    
    async def _handle_tool_calls(self, run: ThreadRun, thread_id: str):
        """Handle function tool calls from the agent."""
        client = self._get_client()
        
        if not hasattr(run, 'required_action') or not run.required_action:
            logger.warning("No required_action found in run")
            return
        
        if not hasattr(run.required_action, 'submit_tool_outputs'):
            logger.warning("No submit_tool_outputs in required_action")
            return
        
        tool_calls = run.required_action.submit_tool_outputs.tool_calls
        tool_outputs = []
        
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            logger.info(f"🔧 Executing function: {function_name} with args: {function_args}")
            
            if function_name == "send_sms":
                # Get the message from args
                sms_message = function_args.get("message", "")

                # Guard against empty messages
                if not sms_message or not sms_message.strip():
                    logger.error(f"❌ Empty message received from AI model. Full args: {function_args}")
                    result = {
                        "success": False,
                        "error": "Message body is empty. The AI model did not extract the message content properly."
                    }
                else:
                    # Resolve recipient: explicit arg > user credentials > env var default
                    to_number = function_args.get("to_number") or await self._resolve_to_number()
                    media_urls = function_args.get("media_urls")
                    result = self.send_sms(
                        message=sms_message,
                        to_number=to_number,
                        media_urls=media_urls
                    )
                tool_outputs.append(ToolOutput(
                    tool_call_id=tool_call.id,
                    output=json.dumps(result)
                ))
                logger.info(f"📱 SMS send result: {result}")
                
            elif function_name == "receive_sms":
                # Execute the receive_sms function
                result = self.receive_sms(
                    from_number=function_args.get("from_number"),
                    limit=function_args.get("limit", 10)
                )
                tool_outputs.append(ToolOutput(
                    tool_call_id=tool_call.id,
                    output=json.dumps(result)
                ))
                logger.info(f"📥 SMS receive result: Found {result.get('message_count', 0)} message(s)")
                
                # Print messages to terminal for visibility
                if result.get("success") and result.get("messages"):
                    print("\n" + "="*60)
                    print("📥 INCOMING SMS MESSAGES")
                    print("="*60)
                    for msg in result["messages"]:
                        print(f"\n🔹 From: {msg['from']}")
                        print(f"   To: {msg['to']}")
                        print(f"   Date: {msg['date_sent']}")
                        print(f"   Status: {msg['status']}")
                        print(f"   Message: {msg['body']}")
                        print(f"   SID: {msg['message_sid']}")
                    print("\n" + "="*60 + "\n")
                elif result.get("success"):
                    print("\n📭 No SMS messages found\n")
                else:
                    print(f"\n❌ Error retrieving messages: {result.get('error')}\n")
            
            elif function_name == "twilio_ask":
                # HITL: Send SMS and wait for response
                question = function_args.get("question", "")

                if not question or not question.strip():
                    logger.error(f"❌ Empty question received for twilio_ask. Full args: {function_args}")
                    result = {
                        "success": False,
                        "error": "Question is empty. Please provide a question to ask the user.",
                        "hitl_triggered": False
                    }
                else:
                    # Get context_id from thread tracking (will be passed via executor)
                    context_id = getattr(self, '_current_context_id', f"sms_{thread_id}")

                    # Resolve recipient: explicit arg > user credentials > env var default
                    to_number = function_args.get("to_number") or await self._resolve_to_number()

                    # Execute twilio_ask which sends SMS and stores pending request
                    result = self.twilio_ask(
                        question=question,
                        context_id=context_id,
                        to_number=to_number,
                        thread_id=thread_id
                    )
                    
                    if result.get("hitl_triggered"):
                        logger.info(f"📱 HITL triggered - waiting for SMS response from {result.get('to_number')}")
                        print("\n" + "="*60)
                        print("📱 HITL: SMS SENT - WAITING FOR HUMAN RESPONSE")
                        print("="*60)
                        print(f"   To: {result.get('to_number')}")
                        print(f"   Question: {question[:100]}...")
                        print(f"   Context ID: {context_id}")
                        print(f"   Status: Waiting for user to reply via SMS")
                        print("="*60 + "\n")
                
                tool_outputs.append(ToolOutput(
                    tool_call_id=tool_call.id,
                    output=json.dumps(result)
                ))
                    
            else:
                # Unknown function
                tool_outputs.append(ToolOutput(
                    tool_call_id=tool_call.id,
                    output=json.dumps({"error": f"Unknown function: {function_name}"})
                ))
        
        # Submit tool outputs
        if tool_outputs:
            client.runs.submit_tool_outputs(
                thread_id=thread_id,
                run_id=run.id,
                tool_outputs=tool_outputs
            )
            logger.info(f"Submitted {len(tool_outputs)} tool outputs")
    
    async def run_conversation_stream(self, thread_id: str, user_message: str, context_id: Optional[str] = None):
        """Async generator: yields progress messages and final response.
        
        Args:
            thread_id: The thread ID for this conversation
            user_message: The user's message
            context_id: Optional A2A context ID for HITL tracking
        """
        if not self.agent:
            await self.create_agent()
        
        # Store context_id for HITL tool calls
        self._current_context_id = context_id or f"sms_{thread_id}"

        await self.send_message(thread_id, user_message)
        client = self._get_client()
        run = client.runs.create(thread_id=thread_id, agent_id=self.agent.id)

        max_iterations = 25
        iterations = 0
        tool_calls_yielded = set()
        hitl_triggered = False

        while run.status in ["queued", "in_progress", "requires_action"] and iterations < max_iterations:
            iterations += 1
            await asyncio.sleep(2)
            
            # Check for tool calls in progress
            try:
                run_steps = client.run_steps.list(thread_id, run.id)
                for run_step in run_steps:
                    if (hasattr(run_step, "step_details") and
                        hasattr(run_step.step_details, "type") and
                        run_step.step_details.type == "tool_calls" and
                        hasattr(run_step.step_details, "tool_calls")):
                        for tool_call in run_step.step_details.tool_calls:
                            if tool_call and hasattr(tool_call, "type"):
                                tool_type = tool_call.type
                                if tool_type not in tool_calls_yielded:
                                    if hasattr(tool_call, 'function') and hasattr(tool_call.function, 'name'):
                                        func_name = tool_call.function.name
                                        yield f"🛠️ Calling function: {func_name}"
                                        # Check if this is a HITL call
                                        if func_name == "twilio_ask":
                                            hitl_triggered = True
                                    else:
                                        yield f"🛠️ Executing tool: {tool_type}"
                                    tool_calls_yielded.add(tool_type)
            except Exception:
                pass

            try:
                run = client.runs.get(thread_id=thread_id, run_id=run.id)
            except Exception as e:
                yield f"Error: {str(e)}"
                return

            if run.status == "failed":
                yield f"Error: {run.last_error}"
                return

            if run.status == "requires_action":
                logger.info(f"Run {run.id} requires action")
                try:
                    await self._handle_tool_calls(run, thread_id)
                    
                    # After handling tool calls, check if HITL was triggered
                    # If so, yield special HITL marker and return
                    if hitl_triggered and FoundryTwilioAgent.pending_requests:
                        # Find pending request for this context
                        for phone, pending in FoundryTwilioAgent.pending_requests.items():
                            if pending.context_id == self._current_context_id:
                                yield f"HITL_WAITING:{phone}:{pending.question[:100]}"
                                return
                                
                except Exception as e:
                    yield f"Error handling tool calls: {str(e)}"
                    return

        if run.status == "failed":
            yield f"Error: {run.last_error}"
            return

        if iterations >= max_iterations:
            yield "Error: Request timed out"
            return

        # Extract token usage
        if hasattr(run, 'usage') and run.usage:
            self.last_token_usage = {
                'prompt_tokens': getattr(run.usage, 'prompt_tokens', 0),
                'completion_tokens': getattr(run.usage, 'completion_tokens', 0),
                'total_tokens': getattr(run.usage, 'total_tokens', 0)
            }

        # Get the assistant's response
        messages = list(client.messages.list(thread_id=thread_id, order=ListSortOrder.ASCENDING))
        for msg in reversed(messages):
            if msg.role == "assistant" and msg.content:
                for content_item in msg.content:
                    if hasattr(content_item, 'text'):
                        yield content_item.text.value
                break

    async def cleanup(self):
        """Cleanup resources."""
        logger.info("Cleaning up Twilio SMS Agent")
        self._agents_client = None
        self._project_client = None
        self._twilio_client = None
        self._blob_service_client = None
        self.threads = {}
