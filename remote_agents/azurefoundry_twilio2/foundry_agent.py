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
from typing import Optional, Dict, List, Any
from dataclasses import dataclass

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
    
    def send_sms(self, message: str, to_number: Optional[str] = None) -> Dict:
        """
        Send an SMS message via Twilio.
        
        Args:
            message: The SMS message body
            to_number: Recipient phone number (uses default if not provided)
            
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
            
            # Truncate message if too long for SMS (160 chars for single SMS)
            if len(message) > 1600:
                message = message[:1597] + "..."
                logger.warning("Message truncated to 1600 characters for SMS")
            
            msg = client.messages.create(
                body=message,
                from_=self.twilio_from_number,
                to=recipient
            )
            
            result = {
                "success": True,
                "message_sid": msg.sid,
                "from": self.twilio_from_number,
                "to": recipient,
                "status": msg.status,
                "body_length": len(message)
            }
            
            logger.info(f"✅ SMS sent successfully: SID={msg.sid}, To={recipient}")
            return result
            
        except TwilioRestException as e:
            logger.error(f"❌ Twilio API error: {e}")
            return {
                "success": False,
                "error": str(e),
                "error_code": e.code if hasattr(e, 'code') else None
            }
        except Exception as e:
            logger.error(f"❌ Unexpected error sending SMS: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
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
                "description": """Send an SMS text message via Twilio to notify a user.
                
Use this function to:
- Send workflow results or summaries to a user's phone
- Deliver notifications or alerts via SMS
- Confirm completed actions with a text message

The message should be clear and concise since SMS has character limits.
If no phone number is provided, the default configured number will be used.""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The SMS message content to send. Should be concise and informative. Max ~1600 characters."
                        },
                        "to_number": {
                            "type": "string",
                            "description": "Optional recipient phone number in E.164 format (e.g., +15147715943). If not provided, uses the default configured number."
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

1. **send_sms**: Send a one-way SMS notification (fire and forget, no response expected)
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
                    result = self.send_sms(
                        message=sms_message,
                        to_number=to_number
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
        self.threads = {}
