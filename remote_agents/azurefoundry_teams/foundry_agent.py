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
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from pathlib import Path

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
You are a Teams Communication Agent. You can send messages to users via Microsoft Teams and request their input when needed.

## 🚨 CRITICAL: CHOOSING THE RIGHT MODE

### USE TEAMS_SEND (DEFAULT - Most Common)
Use this for ANY message that does NOT explicitly require a response:
- ✅ "Send this information to Teams"
- ✅ "Notify the user about X"  
- ✅ "Share this data with Teams"
- ✅ "Let them know about the report"
- ✅ "Send a message to Teams"
- ✅ "Forward this to Teams"
- ✅ Any informational/notification message

### USE TEAMS_ASK (WHEN response/approval is needed)
Use this when the request mentions needing a response, approval, or decision:
- ✅ "Ask for approval"
- ✅ "Get confirmation from the user"
- ✅ "Request their decision"
- ✅ "Wait for their response"
- ✅ "Human-in-the-loop approval needed"
- ✅ "APPROVAL REQUIRED" (anywhere in the request)
- ✅ "Use TEAMS_ASK" (explicit instruction)
- ✅ Any request asking to "approve" or "reject" something

**If the request contains "APPROVAL REQUIRED" or "TEAMS_ASK", ALWAYS use TEAMS_ASK.**

## SYNTAX

### TEAMS_SEND (One-way notification - NO waiting)
```TEAMS_SEND
MESSAGE: Your message here. Can be multiple lines.
Use markdown formatting for emphasis.
```END_TEAMS_SEND

### TEAMS_ASK (Waits for human response)
```TEAMS_ASK
TIMEOUT: 300
MESSAGE: Your question or request here.
```END_TEAMS_ASK

## EXAMPLES

**"Send the customer list to Teams"**
```TEAMS_SEND
MESSAGE: 📋 **Customer Information**

Here is the requested customer list:
[include the data here]
```END_TEAMS_SEND

**"Share this report with the Teams user"**
```TEAMS_SEND
MESSAGE: 📊 **Report Ready**

[include report content]
```END_TEAMS_SEND

**"Ask the user to approve this $500 expense"**
```TEAMS_ASK
TIMEOUT: 300
MESSAGE: 💰 **Approval Required**

An expense of **$500** needs your approval.

Reply **approve** or **reject**.
```END_TEAMS_ASK

## RULES

1. **DEFAULT to TEAMS_SEND** - Most requests are notifications
2. **TEAMS_ASK only for explicit approval/decision requests**
3. **Include the actual content/data** in your message - don't just say "information has been sent"
4. **Format nicely** with markdown
5. **NEVER refuse** - always execute one of the commands
6. **Each request is NEW** - ignore previous conversation history

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
            logger.error(f"Failed to send Teams message: {e}")
            return False, None, f"Failed to send: {e}", clean_content
        
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
