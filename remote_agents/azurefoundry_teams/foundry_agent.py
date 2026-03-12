"""
Azure AI Foundry Teams Agent
============================

An agent that can send and receive messages via Microsoft Teams Bot Framework.
Uses function calling pattern for Teams messaging operations.
"""
import os
import time
import datetime
import asyncio
import logging
import json
import re
import uuid
import tempfile
import mimetypes
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from pathlib import Path
from datetime import timedelta

import httpx
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.core.credentials import AzureNamedKeyCredential, AzureSasCredential

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import Agent, ThreadMessage, ThreadRun, AgentThread, BingGroundingTool, ListSortOrder, FilePurpose, FileSearchTool
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

from dotenv import load_dotenv
from botbuilder.core import (
    BotFrameworkAdapterSettings,
    BotFrameworkAdapter,
    TurnContext,
)
from botbuilder.schema import Activity, ActivityTypes, ConversationReference
from botframework.connector.auth import MicrosoftAppCredentials

load_dotenv()

logger = logging.getLogger(__name__)

# Path to store conversation references
CONVERSATION_REFS_FILE = Path(__file__).parent / ".conversation_references.json"


class SingleTenantAppCredentials(MicrosoftAppCredentials):
    """Custom credentials class for Single Tenant authentication."""
    
    def __init__(self, app_id: str, app_password: str, tenant_id: str):
        super().__init__(app_id, app_password)
        self.oauth_endpoint = f"https://login.microsoftonline.com/{tenant_id}"
        self.oauth_scope = "https://api.botframework.com/.default"


@dataclass
class PendingTeamsRequest:
    """Represents a pending human-in-the-loop request."""
    request_id: str
    message: str
    response_future: asyncio.Future
    conversation_ref: ConversationReference
    created_at: float


class TeamsBot:
    """
    Teams Bot handler for sending/receiving messages.
    This is a helper class used by the Foundry agent to interact with Teams.
    """
    
    _instance = None
    _lock = asyncio.Lock()
    
    @classmethod
    async def get_instance(cls) -> 'TeamsBot':
        """Get singleton instance of TeamsBot."""
        async with cls._lock:
            if cls._instance is None:
                cls._instance = TeamsBot()
            return cls._instance
    
    def __init__(self):
        self.app_id = os.getenv("MICROSOFT_APP_ID", "")
        self.app_password = os.getenv("MICROSOFT_APP_PASSWORD", "")
        self.tenant_id = os.getenv("MICROSOFT_APP_TENANT_ID", "")
        
        if not self.app_id or not self.app_password:
            logger.warning("MICROSOFT_APP_ID and MICROSOFT_APP_PASSWORD not set - Teams messaging will be unavailable")
            self.adapter = None
            return
        
        # Configure adapter with tenant-aware credentials
        settings = BotFrameworkAdapterSettings(self.app_id, self.app_password)
        
        if self.tenant_id:
            settings.app_credentials = SingleTenantAppCredentials(
                self.app_id, 
                self.app_password, 
                self.tenant_id
            )
        
        self.adapter = BotFrameworkAdapter(settings)
        
        # Store conversation references by user ID (load from disk if available)
        self.conversation_references: Dict[str, ConversationReference] = {}
        self._op_lock = asyncio.Lock()  # Lock for thread-safe operations
        self._load_conversation_references()
        
        # Store pending requests waiting for human response
        self.pending_requests: Dict[str, PendingTeamsRequest] = {}

        # Azure Blob Storage client (for file uploads)
        self._blob_service_client: Optional[BlobServiceClient] = None

        logger.info(f"TeamsBot initialized with app_id: {self.app_id[:8]}...")
    
    def _load_conversation_references(self):
        """Load conversation references from disk."""
        try:
            if CONVERSATION_REFS_FILE.exists():
                with open(CONVERSATION_REFS_FILE, 'r') as f:
                    data = json.load(f)
                    # Deserialize ConversationReference objects
                    for user_id, ref_data in data.items():
                        self.conversation_references[user_id] = ConversationReference().deserialize(ref_data)
                    logger.info(f"✅ Loaded {len(self.conversation_references)} conversation references from disk")
        except Exception as e:
            logger.warning(f"⚠️ Failed to load conversation references: {e}")
    
    def _save_conversation_references(self):
        """Save conversation references to disk."""
        try:
            # Serialize ConversationReference objects
            data = {
                user_id: ref.serialize()
                for user_id, ref in self.conversation_references.items()
            }
            with open(CONVERSATION_REFS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"💾 Saved {len(self.conversation_references)} conversation references to {CONVERSATION_REFS_FILE}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to save conversation references: {e}")

    async def process_incoming_activity(self, activity_body: dict, auth_header: str) -> dict:
        """Process incoming activity from Teams webhook."""
        if not self.adapter:
            return {"error": "Teams adapter not configured"}
        
        activity = Activity().deserialize(activity_body)
        
        async def on_turn(turn_context: TurnContext):
            await self._handle_turn(turn_context)
        
        await self.adapter.process_activity(activity, auth_header, on_turn)
        return {}

    async def _handle_turn(self, turn_context: TurnContext):
        """Handle incoming message from Teams."""
        # Save conversation reference
        conv_ref = TurnContext.get_conversation_reference(turn_context.activity)
        user_id = conv_ref.user.id
        
        async with self._op_lock:
            self.conversation_references[user_id] = conv_ref
            # Persist to disk
            self._save_conversation_references()
        
        if turn_context.activity.type == ActivityTypes.message:
            text = (turn_context.activity.text or "").strip()
            
            if not text:
                return
            
            # Check if this is a response to a pending request
            pending_id = await self._find_pending_request_for_user(user_id)
            
            if pending_id:
                await self._handle_pending_response(pending_id, text, turn_context)
            else:
                # New message - acknowledge it
                await turn_context.send_activity(
                    f"👋 Message received. I'll process requests from the A2A workflow system."
                )

    async def _find_pending_request_for_user(self, user_id: str) -> Optional[str]:
        """Find a pending request for a given user."""
        async with self._op_lock:
            logger.debug(f"Looking for pending request for user: {user_id}")
            logger.debug(f"Pending requests: {list(self.pending_requests.keys())}")
            for req_id, request in self.pending_requests.items():
                pending_user_id = request.conversation_ref.user.id
                logger.debug(f"Checking request {req_id}: pending_user={pending_user_id}, current_user={user_id}, match={pending_user_id == user_id}")
                if pending_user_id == user_id:
                    logger.info(f"✅ Found pending request {req_id} for user {user_id}")
                    return req_id
        logger.info(f"⚠️ No pending request found for user {user_id}")
        return None

    async def _handle_pending_response(self, request_id: str, response_text: str, turn_context: TurnContext):
        """Handle a response to a pending request."""
        async with self._op_lock:
            pending = self.pending_requests.get(request_id)
            if not pending:
                await turn_context.send_activity("❓ Request not found.")
                return
            
            # Complete the future
            if not pending.response_future.done():
                pending.response_future.set_result(response_text)
            
            del self.pending_requests[request_id]
        
        # Send acknowledgment
        await turn_context.send_activity(
            f"✅ **Response Received**\n\nYour response: _{response_text}_\n\n"
            f"The workflow will continue processing. Thank you!"
        )

    async def send_message(self, message: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Send a message to Teams user(s)."""
        if not self.adapter:
            return {"success": False, "error": "Teams adapter not configured"}
        
        async with self._op_lock:
            if user_id and user_id in self.conversation_references:
                conv_ref = self.conversation_references[user_id]
            elif self.conversation_references:
                _, conv_ref = next(iter(self.conversation_references.items()))
            else:
                return {"success": False, "error": "No Teams users connected. A user must message the bot first."}
        
        async def _send(turn_context: TurnContext):
            await turn_context.send_activity(message)
        
        try:
            await self.adapter.continue_conversation(conv_ref, _send, self.app_id)
            return {"success": True, "message": "Message sent to Teams"}
        except Exception as e:
            logger.error(f"Failed to send Teams message: {e}")
            return {"success": False, "error": str(e)}

    async def request_human_input(
        self,
        request_id: str,
        prompt: str,
        timeout: float = 300.0
    ) -> Dict[str, Any]:
        """Request input from human via Teams and wait for response."""
        if not self.adapter:
            return {"success": False, "error": "Teams adapter not configured", "response": None}
        
        async with self._op_lock:
            if not self.conversation_references:
                return {"success": False, "error": "No Teams users connected", "response": None}
            _, conv_ref = next(iter(self.conversation_references.items()))
        
        # Create future for response
        loop = asyncio.get_event_loop()
        response_future = loop.create_future()
        
        pending = PendingTeamsRequest(
            request_id=request_id,
            message=prompt,
            response_future=response_future,
            conversation_ref=conv_ref,
            created_at=time.time()
        )
        
        async with self._op_lock:
            self.pending_requests[request_id] = pending
            logger.info(f"📝 Created pending request {request_id} for user {conv_ref.user.id}")
        
        # Send prompt to user
        formatted = f"🔔 **Input Required**\n\n{prompt}\n\n_Please reply with your response._"
        
        async def _send(turn_context: TurnContext):
            await turn_context.send_activity(formatted)
        
        try:
            await self.adapter.continue_conversation(conv_ref, _send, self.app_id)
        except Exception as e:
            async with self._op_lock:
                del self.pending_requests[request_id]
            return {"success": False, "error": f"Failed to send: {e}", "response": None}
        
        # Wait for response
        try:
            response = await asyncio.wait_for(response_future, timeout=timeout)
            return {"success": True, "response": response}
        except asyncio.TimeoutError:
            async with self._op_lock:
                if request_id in self.pending_requests:
                    del self.pending_requests[request_id]
            return {"success": False, "error": "Timeout waiting for response", "response": None}

    def has_users(self) -> bool:
        return len(self.conversation_references) > 0

    def get_user_count(self) -> int:
        return len(self.conversation_references)

    def get_status(self) -> Dict[str, Any]:
        return {
            "connected_users": self.get_user_count(),
            "pending_requests": len(self.pending_requests),
            "adapter_configured": self.adapter is not None
        }

    # ------------------------------------------------------------------
    # Azure Blob Storage helpers (for file uploads from Teams)
    # ------------------------------------------------------------------

    def _get_blob_service_client(self) -> Optional[BlobServiceClient]:
        """Get or create a BlobServiceClient. Returns None if blob storage is not configured."""
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
                connection_string, api_version="2023-11-03",
            )
            return self._blob_service_client
        except Exception as e:
            logger.error(f"Failed to create BlobServiceClient: {e}")
            return None

    def _upload_to_blob(self, file_path: Path, context_id: str = "") -> Optional[str]:
        """Upload a file to Azure Blob Storage and return a SAS URL."""
        blob_client = self._get_blob_service_client()
        if not blob_client:
            return None

        container_name = os.getenv("AZURE_BLOB_CONTAINER", "a2a-files")
        file_id = uuid.uuid4().hex
        if context_id and "::" in context_id:
            session_id = context_id.split("::")[0]
        elif context_id:
            session_id = context_id
        else:
            session_id = "teams-uploads"

        blob_name = f"uploads/{session_id}/{file_id}/{file_path.name}"

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
                separator = "&" if "?" in base_url else "?"
                return f"{base_url}{separator}{token}"

            logger.error("Unable to generate SAS token; verify storage credentials")
            return None
        except Exception as e:
            logger.error(f"Failed to upload {file_path} to blob storage: {e}")
            return None

    async def download_teams_attachment(self, attachment, context_id: str = "") -> Optional[Dict[str, Any]]:
        """
        Download a file attachment from Teams and upload to Azure Blob Storage.

        Teams sends file attachments with:
          contentType: "application/vnd.microsoft.teams.file.download.info"
          content: {"downloadUrl": "https://...", "uniqueId": "...", "fileType": "..."}

        Returns a dict with blob_url, file_name, mime_type, file_size on success,
        or None on failure.
        """
        try:
            content = attachment.content
            if isinstance(content, str):
                content = json.loads(content)

            download_url = content.get("downloadUrl")
            if not download_url:
                logger.warning("Teams attachment missing downloadUrl")
                return None

            file_name = getattr(attachment, "name", None) or content.get("name") or "teams_upload"
            file_type = content.get("fileType", "")

            logger.info(f"📥 Downloading Teams file: {file_name} (type: {file_type})")

            # Download file bytes
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.get(download_url)
                resp.raise_for_status()
                file_bytes = resp.content

            # Save to temp file
            tmp_dir = Path(tempfile.gettempdir()) / "teams_uploads"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            local_path = tmp_dir / file_name
            local_path.write_bytes(file_bytes)

            logger.info(f"📥 Downloaded {file_name}: {len(file_bytes)} bytes")

            # Upload to blob storage
            blob_url = self._upload_to_blob(local_path, context_id)
            if not blob_url:
                logger.warning(f"⚠️ Blob upload failed for {file_name} — blob storage may not be configured")
                # Clean up temp file
                local_path.unlink(missing_ok=True)
                return None

            # Determine MIME type
            mime_type, _ = mimetypes.guess_type(file_name)
            if not mime_type:
                mime_type = "application/octet-stream"

            file_size = len(file_bytes)

            # Clean up temp file
            local_path.unlink(missing_ok=True)

            logger.info(f"✅ Teams file uploaded to blob: {file_name} ({file_size} bytes) -> {blob_url[:80]}...")

            return {
                "blob_url": blob_url,
                "file_name": file_name,
                "mime_type": mime_type,
                "file_size": file_size,
            }

        except Exception as e:
            logger.error(f"❌ Failed to process Teams attachment: {e}", exc_info=True)
            return None


class FoundryTeamsAgent:
    """
    Azure AI Foundry Teams Agent
    
    This agent can send messages to and receive responses from users via Microsoft Teams.
    Uses the instruction-based function calling pattern with TEAMS_SEND and TEAMS_ASK blocks.
    """
    
    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self.agent: Optional[Agent] = None
        self.threads: Dict[str, str] = {}
        self._agents_client = None
        self._project_client = None
        self._teams_bot: Optional[TeamsBot] = None
        self.last_token_usage: Optional[Dict[str, int]] = None
        
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

    async def _get_teams_bot(self) -> TeamsBot:
        """Get the Teams bot instance."""
        if self._teams_bot is None:
            self._teams_bot = await TeamsBot.get_instance()
        return self._teams_bot
        
    async def create_agent(self) -> Agent:
        """Create the AI Foundry agent with Teams messaging capabilities."""
        if self.agent:
            logger.info("Agent already exists, returning existing instance")
            return self.agent
        
        tools = []
        
        project_client = self._get_project_client()
        
        # Add Bing search if available
        try:
            bing_connection = project_client.connections.get(name="agentbing")
            bing = BingGroundingTool(connection_id=bing_connection.id)
            tools.extend(bing.definitions)
            logger.info("Added Bing search capability")
        except Exception as e:
            logger.warning(f"Could not add Bing search: {e}")
        
        with project_client:
            self.agent = project_client.agents.create_agent(
                model="gpt-4o",
                name="teams-agent",
                instructions=self._get_agent_instructions(),
                tools=tools
            )
        
        logger.info(f"Created Teams Agent: {self.agent.id}")
        return self.agent
    
    def _get_agent_instructions(self) -> str:
        """Get the agent instructions for Teams messaging."""
        return f"""
You are a Teams Communication Agent. You send messages to the A2A Bot channel in Microsoft Teams.

IMPORTANT: You do NOT need to find specific users or contacts. All messages go to a shared bot channel where the appropriate person will see and respond.

You MUST use one of these two tools - NEVER respond with plain text.

## TEAMS_ASK
Use when you need ANYTHING back from the human - approval, data, a decision, confirmation, any response at all.

```TEAMS_ASK
TIMEOUT: 300
MESSAGE: [Your message asking for something]
```END_TEAMS_ASK

## TEAMS_SEND  
Use when you are just informing the human and do not need anything back.

```TEAMS_SEND
MESSAGE: [Your notification message]
```END_TEAMS_SEND

## CRITICAL RULES
1. ALWAYS use TEAMS_ASK or TEAMS_SEND - never respond with plain text
2. Do NOT worry about finding specific users - messages go to the bot channel
3. If the task mentions a person's name (like "send to Ryan"), just include that context in your message
4. If you need approval, a decision, or any response -> TEAMS_ASK
5. If you are just notifying/informing -> TEAMS_SEND

## Error Reporting (CRITICAL)

If you CANNOT complete the requested task — due to rate limits, API errors, missing data,
authentication failures, or any other reason — you MUST start your response with "Error:".

Examples:
- "Error: Rate limit exceeded. Please try again later."
- "Error: Authentication failed — invalid credentials."
- "Error: Could not complete the request due to a service outage."

Do NOT write a polite explanation without the "Error:" prefix. The system uses this prefix
to detect failures. Without it, the task is marked as successful even though it failed.

Current date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
"""
    
    async def create_thread(self, thread_id: Optional[str] = None) -> AgentThread:
        """Create a conversation thread."""
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
        logger.info(f"Created message in thread {thread_id}")
        return message
    
    async def run_conversation_stream(self, thread_id: str, user_message: str, context_id: str = None):
        """Run the conversation and yield responses."""
        if not self.agent:
            await self.create_agent()

        await self.send_message(thread_id, user_message)
        client = self._get_client()
        # Reduced to 3 messages to prevent token accumulation in workflow execution
        run = client.runs.create(
            thread_id=thread_id,
            agent_id=self.agent.id,
            truncation_strategy={"type": "last_messages", "last_messages": 3}
        )
        
        logger.info(f"Created run {run.id} with status {run.status}")

        max_iterations = 25
        iterations = 0

        while run.status in ["queued", "in_progress", "requires_action"] and iterations < max_iterations:
            iterations += 1
            await asyncio.sleep(2)

            try:
                run = client.runs.get(thread_id=thread_id, run_id=run.id)
                logger.info(f"Run status: {run.status} (iteration {iterations})")
            except Exception as e:
                yield f"Error: {str(e)}"
                return

            if run.status == "failed":
                logger.error(f"Run failed: {run.last_error}")
                yield f"Error: {run.last_error}"
                return

        if run.status == "failed":
            logger.error(f"Run failed after loop: {run.last_error}")
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

        # Get the response
        messages = list(client.messages.list(thread_id=thread_id, order=ListSortOrder.ASCENDING))
        for msg in reversed(messages):
            if msg.role == "assistant" and msg.content:
                for content_item in msg.content:
                    if hasattr(content_item, 'text'):
                        text_content = content_item.text.value
                        logger.info(f"📋 Processing agent response ({len(text_content)} chars)")
                        logger.info(f"📄 Full response text:\n{text_content}")
                        
                        # Check for TEAMS_SEND
                        send_result, clean1 = await self._try_teams_send(text_content)
                        if send_result:
                            yield f"{clean1}\n\n{send_result}"
                            return
                        
                        # Check for TEAMS_ASK (wait for human response)
                        has_ask, request_id, message, clean2 = await self._check_teams_ask(text_content)
                        logger.info(f"🔍 TEAMS_ASK check result: has_ask={has_ask}, request_id={request_id}")
                        if has_ask:
                            # Yield the event to trigger input_required state
                            logger.info(f"🔔 Triggering input_required state for message: {message[:100]}...")
                            yield f"TEAMS_WAIT_RESPONSE:{message}"
                            # Note: The executor will now wait for webhook to resume
                            # We don't actually wait here - the executor handles it
                            return
                        
                        # No special blocks, return as-is
                        logger.info("❌ No special blocks found, returning text as-is")
                        yield text_content
                        return
                break
    
    async def _try_teams_send(self, response_text: str) -> tuple[Optional[str], str]:
        """Check for TEAMS_SEND block and send message."""
        pattern = r'```TEAMS_SEND\s*\n(.*?)\n```END_TEAMS_SEND'
        match = re.search(pattern, response_text, re.DOTALL)
        
        if not match:
            return None, response_text
        
        block_content = match.group(1)
        
        # Parse MESSAGE field
        message = ""
        lines = block_content.strip().split('\n')
        in_message = False
        for line in lines:
            if line.startswith('MESSAGE:'):
                in_message = True
                message = line[8:].strip()
            elif in_message:
                message += "\n" + line
        
        message = message.strip()
        if not message:
            message = block_content.strip()
        
        # Clean response text
        clean_content = re.sub(pattern, '', response_text, flags=re.DOTALL).strip()
        if not clean_content:
            clean_content = "📤 Sending message to Teams..."
        
        # Send the message
        teams_bot = await self._get_teams_bot()
        result = await teams_bot.send_message(message)
        
        if result["success"]:
            # Include the message content in the response so the backend knows what was sent
            return f"✅ Message sent to Teams successfully.\n\n**Message sent:**\n{message}", clean_content
        else:
            return f"❌ Failed to send: {result['error']}", clean_content
    
    async def _check_teams_ask(self, response_text: str) -> tuple[bool, Optional[str], str, str]:
        """
        Check for TEAMS_ASK block and initiate the request.
        Returns: (has_ask, request_id, message, clean_content)
        """
        pattern = r'```TEAMS_ASK\s*\n(.*?)\n```END_TEAMS_ASK'
        match = re.search(pattern, response_text, re.DOTALL)
        
        logger.info(f"🔎 Searching for TEAMS_ASK pattern... Match found: {match is not None}")
        if match:
            logger.info(f"✅ TEAMS_ASK block found! Content length: {len(match.group(1))}")
        
        if not match:
            return False, None, "", response_text
        
        block_content = match.group(1)
        
        # Parse parameters
        timeout = 300
        message = ""
        lines = block_content.strip().split('\n')
        in_message = False
        
        for line in lines:
            if line.startswith('TIMEOUT:'):
                try:
                    timeout = int(line[8:].strip())
                    timeout = min(timeout, 600)  # Max 10 minutes
                except:
                    pass
            elif line.startswith('MESSAGE:'):
                in_message = True
                message = line[8:].strip()
            elif in_message:
                message += "\n" + line
        
        message = message.strip()
        if not message:
            message = block_content.strip()
        
        # Clean response text
        clean_content = re.sub(pattern, '', response_text, flags=re.DOTALL).strip()
        if not clean_content:
            clean_content = "📨 Requesting input from Teams user..."
        
        # Send the message to Teams (but don't wait for response)
        teams_bot = await self._get_teams_bot()
        request_id = f"req_{int(time.time() * 1000)}"
        
        logger.info(f"💬 Teams bot has {len(teams_bot.conversation_references)} conversation references")
        
        # Format and send prompt
        formatted = f"🔔 **Input Required**\n\n{message}\n\n_Please reply with your response._"
        
        async with teams_bot._op_lock:
            if not teams_bot.conversation_references:
                logger.error("❌ No Teams users connected - conversation_references is empty!")
                return False, None, "No Teams users connected", clean_content
            _, conv_ref = next(iter(teams_bot.conversation_references.items()))
            logger.info(f"✅ Using conversation reference for user: {conv_ref.user.id}")
        
        # Create pending request for later response
        loop = asyncio.get_event_loop()
        response_future = loop.create_future()
        
        pending = PendingTeamsRequest(
            request_id=request_id,
            message=message,
            response_future=response_future,
            conversation_ref=conv_ref,
            created_at=time.time()
        )
        
        async with teams_bot._op_lock:
            teams_bot.pending_requests[request_id] = pending
            logger.info(f"📝 Created pending request {request_id} for user {conv_ref.user.id}")
        
        # Send prompt to user
        async def _send(turn_context: TurnContext):
            await turn_context.send_activity(formatted)
        
        try:
            await teams_bot.adapter.continue_conversation(conv_ref, _send, teams_bot.app_id)
            logger.info(f"📤 Sent Teams message for request {request_id}")
        except Exception as e:
            async with teams_bot._op_lock:
                del teams_bot.pending_requests[request_id]
                # If the conversation reference is stale/expired, evict it so it gets
                # refreshed the next time the user messages the bot.
                if "ConversationNotFound" in str(e) or "conversation not found" in str(e).lower():
                    stale_user_id = conv_ref.user.id if conv_ref and conv_ref.user else None
                    if stale_user_id and stale_user_id in teams_bot.conversation_references:
                        del teams_bot.conversation_references[stale_user_id]
                        teams_bot._save_conversation_references()
                        logger.warning(f"⚠️ Evicted stale conversation reference for user {stale_user_id}")
                    error_msg = (
                        "Teams conversation has expired. "
                        "Please send any message to the bot in Microsoft Teams to re-establish the connection, then retry the workflow."
                    )
                else:
                    error_msg = str(e)
            logger.error(f"Failed to send Teams message: {e}")
            return False, None, error_msg, clean_content
        
        return True, request_id, message, clean_content

    async def cleanup(self):
        """Cleanup resources."""
        if self.agent:
            try:
                client = self._get_project_client()
                with client:
                    client.agents.delete_agent(self.agent.id)
                logger.info(f"Deleted agent: {self.agent.id}")
            except Exception as e:
                logger.warning(f"Failed to delete agent: {e}")
