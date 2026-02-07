"""
AI Foundry Agent implementation with Stripe Payment Processing Capabilities.
Uses AgentsClient directly for Azure AI Foundry with Stripe MCP integration.

IMPORTANT: QUOTA REQUIREMENTS FOR AZURE AI FOUNDRY AGENTS
=========================================================

Based on Microsoft support documentation, Azure AI Foundry agents require a 
MINIMUM of 20,000 TPM (Tokens Per Minute) to function properly without rate limiting.
"""
import os
import asyncio
import logging
import json
from typing import Optional, Dict, Any
import httpx

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import (
    Agent, ListSortOrder, ToolSet
)
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)


# Stripe MCP Server URL (deployed on Azure Container Apps)
STRIPE_MCP_URL = os.getenv(
    "STRIPE_MCP_URL", 
    "https://mcp-stripe.ambitioussky-6c709152.westus2.azurecontainerapps.io/sse"
)


class MCPClient:
    """
    Direct MCP client that calls MCP servers via HTTP/SSE without loading all tool schemas.
    This reduces token usage by ~15k tokens compared to Azure's McpTool approach.
    
    Supports two communication patterns:
    1. Direct POST to /sse (QuickBooks style)
    2. Session-based: GET /sse for session, then POST to /message?sessionId=XXX (Stripe style)
    """
    
    def __init__(self, server_url: str, use_sessions: bool = True):
        self.server_url = server_url
        self.client = httpx.AsyncClient(timeout=30.0)
        self.use_sessions = use_sessions
    
    async def _establish_session(self) -> str:
        """
        Establish a NEW session with the MCP server by connecting to /sse.
        The Stripe MCP server creates a session, returns the ID, then closes the connection.
        Subsequent messages use POST /message?sessionId=XXX with responses in HTTP body.
        
        NOTE: Sessions are ephemeral - need a new session for each request!
        """
        try:
            logger.info("🔗 Establishing new MCP session...")
            headers = {"Accept": "text/event-stream"}
            
            # Connect to get session ID - server will close connection after sending it
            async with self.client.stream("GET", self.server_url, headers=headers) as response:
                response.raise_for_status()
                
                # Read the SSE event that contains the session endpoint
                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    
                    # Look for the endpoint event with session ID
                    # Format: "event: endpoint\ndata: /message?sessionId=XXX\n\n"
                    if "event: endpoint" in buffer and "sessionId=" in buffer:
                        # Extract session ID from the endpoint URL
                        import re
                        match = re.search(r'sessionId=([a-f0-9\-]+)', buffer)
                        if match:
                            session_id = match.group(1)
                            logger.info(f"✅ New session: {session_id}")
                            return session_id
                    
                    # Safety: don't read indefinitely
                    if len(buffer) > 1000:
                        break
                
                raise Exception("Failed to extract session ID from SSE stream")
            
        except Exception as e:
            logger.error(f"❌ Failed to establish MCP session: {e}")
            raise
        
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call an MCP tool directly using JSON-RPC over HTTP/SSE.
        
        Args:
            tool_name: Name of the MCP tool to call (e.g., "list_customers")
            arguments: Tool arguments as a dictionary
            
        Returns:
            Tool execution result as a dictionary
        """
        try:
            # Establish session if using session-based communication
            if self.use_sessions:
                session_id = await self._establish_session()
                endpoint_url = self.server_url.replace("/sse", f"/message?sessionId={session_id}")
                
                # MCP JSON-RPC request format
                request_payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": arguments
                    }
                }
                
                headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "Azure-AI-Foundry-Agent",
                    "ngrok-skip-browser-warning": "true"
                }
                
                logger.info(f"🔧 Calling MCP tool: {tool_name}")
                logger.debug(f"   Endpoint: {endpoint_url}")
                logger.debug(f"   Arguments: {json.dumps(arguments, indent=2)}")
                
                # Send message via POST - response comes back directly in HTTP response
                response = await self.client.post(
                    endpoint_url,
                    json=request_payload,
                    headers=headers
                )
                
                response.raise_for_status()
                
                # Parse JSON-RPC response directly from HTTP response
                result = response.json()
                
                if "error" in result:
                    error_msg = result["error"].get("message", "Unknown error")
                    logger.error(f"❌ MCP error: {error_msg}")
                    return {"error": error_msg}
                
                if "result" in result and "content" in result["result"]:
                    content = result["result"]["content"]
                    if isinstance(content, list) and len(content) > 0:
                        text_content = content[0].get("text", "")
                        logger.info(f"✅ Tool response: {text_content[:200]}...")
                        return {"result": text_content}
                
                logger.warning("⚠️ Unexpected response format")
                return {"result": str(result)}
                
            else:
                # Direct POST mode (QuickBooks style)
                endpoint_url = self.server_url
            
                # MCP JSON-RPC request format
                request_payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": arguments
                    }
                }
                
                headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "User-Agent": "Azure-AI-Foundry-Agent",
                    "ngrok-skip-browser-warning": "true"
                }
                
                logger.info(f"🔧 Calling MCP tool: {tool_name}")
                logger.debug(f"   Endpoint: {endpoint_url}")
                logger.debug(f"   Arguments: {json.dumps(arguments, indent=2)}")
                
                response = await self.client.post(
                    endpoint_url,
                    json=request_payload,
                    headers=headers
                )
                
                response.raise_for_status()
                
                # Parse response format
                response_text = response.text
                logger.debug(f"   Raw response: {response_text[:500]}...")
                
                # SSE format: "event: message\ndata: {json}\n\n"
                # Parse SSE events
                if response_text.startswith("event:"):
                    # Parse SSE format
                    lines = response_text.split('\n')
                    for i, line in enumerate(lines):
                        if line.startswith('data:'):
                            json_data = line[5:].strip()
                            result = json.loads(json_data)
                            
                            if "error" in result:
                                error_msg = result["error"].get("message", "Unknown error")
                                logger.error(f"❌ MCP error: {error_msg}")
                                return {"error": error_msg}
                            
                            if "result" in result and "content" in result["result"]:
                                content = result["result"]["content"]
                                if isinstance(content, list) and len(content) > 0:
                                    text_content = content[0].get("text", "")
                                    logger.info(f"✅ Tool response: {text_content[:200]}...")
                                    return {"result": text_content}
                else:
                    # Direct JSON response
                    result = response.json()
                    if "error" in result:
                        error_msg = result["error"].get("message", "Unknown error")
                        logger.error(f"❌ MCP error: {error_msg}")
                        return {"error": error_msg}
                    
                    if "result" in result and "content" in result["result"]:
                        content = result["result"]["content"]
                        if isinstance(content, list) and len(content) > 0:
                            text_content = content[0].get("text", "")
                            logger.info(f"✅ Tool response: {text_content[:200]}...")
                            return {"result": text_content}
                
                logger.warning("⚠️ Unexpected response format")
                return {"result": str(response_text)}
            
        except asyncio.TimeoutError:
            logger.error("❌ Timeout waiting for MCP response")
            return {"error": "Timeout waiting for response from MCP server"}
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ HTTP error: {e.response.status_code} - {e.response.text}")
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
        except Exception as e:
            logger.error(f"❌ Tool call failed: {e}")
            return {"error": str(e)}
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


class FoundryStripeAgent:
    """
    AI Foundry Agent with Stripe Payment Processing capabilities.
    Uses AgentsClient directly for the new SDK version with custom MCP integration.
    """
    
    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self.agent: Optional[Agent] = None
        self.threads: Dict[str, str] = {}
        self._agents_client = None
        self._mcp_client: Optional[MCPClient] = None
        self.last_token_usage: Optional[Dict[str, int]] = None
        
    def _get_agents_client(self) -> AgentsClient:
        """Get a cached AgentsClient instance."""
        if self._agents_client is None:
            self._agents_client = AgentsClient(
                endpoint=self.endpoint,
                credential=self.credential,
            )
        return self._agents_client
        
    async def create_agent(self) -> Agent:
        """Create the AI Foundry agent with Stripe capabilities using custom MCP client."""
        if self.agent:
            logger.info("Agent already exists, returning existing instance")
            return self.agent
        
        logger.info("🚀 CREATING NEW AZURE FOUNDRY STRIPE AGENT...")
        
        # Initialize direct MCP client (bypasses Azure's McpTool to save ~15k tokens per request)
        # use_sessions=False means direct POST to /sse (like QuickBooks)
        logger.info("🔍 INITIALIZING DIRECT STRIPE MCP CLIENT...")
        logger.info(f"   Server URL: {STRIPE_MCP_URL}")
        self._mcp_client = MCPClient(STRIPE_MCP_URL, use_sessions=False)
        
        # Test connectivity
        logger.info("🧪 TESTING STRIPE MCP SERVER CONNECTIVITY...")
        try:
            headers = {"Accept": "text/event-stream"}
            async with httpx.AsyncClient(timeout=5.0) as client:
                async with client.stream("GET", STRIPE_MCP_URL, headers=headers) as response:
                    if response.status_code == 200:
                        logger.info("✅ Stripe MCP Server connectivity test PASSED")
        except Exception as e:
            logger.warning(f"⚠️ MCP connectivity test: {e}")
        
        # Define custom tool that replaces all 22 Stripe MCP tool schemas with a single tool
        # This reduces prompt token usage from ~18k to ~3k per request
        custom_stripe_tool = {
            "type": "function",
            "function": {
                "name": "stripe_action",
                "description": "Execute Stripe payment operations including customer management, payments, subscriptions, products, and invoices. This is a unified interface to all Stripe operations.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                # Customer Management (6 tools)
                                "list_customers",
                                "create_customer",
                                "retrieve_customer",
                                "update_customer",
                                "delete_customer",
                                "search_customers",
                                # Payment Intents (5 tools)
                                "list_payment_intents",
                                "create_payment_intent",
                                "retrieve_payment_intent",
                                "confirm_payment_intent",
                                "cancel_payment_intent",
                                # Subscriptions (5 tools)
                                "list_subscriptions",
                                "create_subscription",
                                "retrieve_subscription",
                                "update_subscription",
                                "cancel_subscription",
                                # Products & Prices (4 tools)
                                "list_products",
                                "create_product",
                                "list_prices",
                                "create_price",
                                # Invoices (2 tools)
                                "list_invoices",
                                "create_invoice",
                                # Balance (1 tool)
                                "retrieve_balance",
                            ],
                            "description": "The Stripe action to perform"
                        },
                        "params": {
                            "type": "object",
                            "description": "Parameters specific to the action being performed (e.g., email for create_customer, amount for create_payment_intent)"
                        }
                    },
                    "required": ["action", "params"]
                }
            }
        }
        
        logger.info("✅ Created custom stripe_action tool (replaces 22 tool schemas)")
        
        # Get model deployment name
        model = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")
        
        # Stripe-specific instructions
        instructions = """You are an expert Stripe payment processing assistant. You help users manage their Stripe account including:

## Your Capabilities:
1. **Customer Management** - Create, search, list, update, and delete customers
2. **Payment Processing** - Create and manage payment intents, confirm payments
3. **Subscriptions** - Create, update, cancel, and list recurring subscriptions
4. **Products & Pricing** - Manage product catalog and pricing
5. **Invoices** - Create and send invoices
6. **Balance** - Check available and pending balance

## CRITICAL: Use Context Provided
You will receive context from previous interactions that may include:
- Invoice details with amounts, customer names, and currencies
- Document extracts with payment information
- Previous conversation history

**ALWAYS extract information from the provided context FIRST before asking questions.**
- If an invoice shows "Total: $25,928.00 USD" for "Cay Digital, LLC" - USE THAT DATA
- Calculate totals from line items if needed
- Search for the customer in Stripe by name/email from the context

## Important Guidelines:
- Always use the Stripe MCP tools to perform operations
- When listing items, summarize the key information clearly
- For customer operations, include relevant details like email and name
- Be proactive in suggesting related actions
- When displaying monetary amounts, format them clearly with currency symbols
- If an operation fails, explain what went wrong and suggest alternatives

## Response Format:
- Use clear headers and bullet points for readability
- Include relevant IDs (customer IDs, payment IDs) for reference
- Summarize results concisely but completely

## When to Use NEEDS_INPUT:
ONLY ask for user input when information is GENUINELY MISSING from context:
- Start your response EXACTLY with: NEEDS_INPUT:
- Then provide your question or request for information
- Example: "NEEDS_INPUT: I found the invoice total is $25,928.00 USD for Cay Digital, LLC. Should I proceed with creating the payment?"

**DO NOT ask for information that's already in the context!**
- If the invoice has the amount - don't ask "what is the amount?"
- If the customer name is in the document - don't ask "who is the customer?"
- If the currency is specified - don't ask "what currency?"

Instead, CONFIRM what you found and ask if you should proceed:
"NEEDS_INPUT: I found Invoice #2512-036-1 for Cay Digital, LLC totaling $25,928.00 USD. Should I search for this customer in Stripe and create the payment?"
"""
        
        logger.info(f"Creating Stripe agent with model: {model}")
        
        # Use AgentsClient directly to create agent with custom tool
        agents_client = self._get_agents_client()
        
        # Create agent with single custom tool
        self.agent = agents_client.create_agent(
            model=model,
            name="AI Foundry Stripe Agent",
            instructions=instructions,
            tools=[custom_stripe_tool],
        )
        
        logger.info(f"✅ Created Stripe agent: {self.agent.id}")
        logger.info(f"   Agent uses custom stripe_action tool (saves ~15k tokens per request)")
        return self.agent
    
    async def create_thread(self) -> str:
        """Create a new conversation thread."""
        agents_client = self._get_agents_client()
        thread = agents_client.threads.create()
        logger.info(f"Created new thread: {thread.id}")
        return thread.id
    
    async def add_message(self, thread_id: str, content: str, role: str = "user"):
        """Add a message to a thread."""
        agents_client = self._get_agents_client()
        message = agents_client.messages.create(
            thread_id=thread_id,
            role=role,
            content=content,
        )
        logger.info(f"Added {role} message to thread {thread_id}")
        return message
    
    async def run_and_wait(self, thread_id: str, timeout: int = 120):
        """Run the agent on a thread and wait for completion, handling tool calls."""
        if not self.agent:
            await self.create_agent()
        
        agents_client = self._get_agents_client()
        
        # Create run without MCP tool resources (using custom tool instead)
        # Reduced to 3 messages to prevent token accumulation in workflow execution
        tool_resources = None
        
        run = agents_client.runs.create(
            thread_id=thread_id,
            agent_id=self.agent.id,
            tool_resources=tool_resources,
            truncation_strategy={"type": "last_messages", "last_messages": 3},
            max_prompt_tokens=25000,
        )
        
        logger.info(f"Created run {run.id} on thread {thread_id}")
        
        # Poll for completion and handle tool calls
        import time
        start_time = time.time()
        max_iterations = 20
        iteration = 0
        
        while run.status in ["queued", "in_progress", "requires_action"]:
            iteration += 1
            if iteration > max_iterations:
                logger.error(f"Run {run.id} exceeded max iterations ({max_iterations})")
                raise RuntimeError(f"Run exceeded maximum iterations")
            
            if time.time() - start_time > timeout:
                logger.error(f"Run {run.id} timed out after {timeout}s")
                raise TimeoutError(f"Run timed out after {timeout} seconds")
            
            # Handle tool calls if needed
            if run.status == "requires_action":
                logger.info("🔧 RUN REQUIRES ACTION - HANDLING TOOL CALLS")
                
                required_action = run.required_action
                if required_action and hasattr(required_action, 'submit_tool_outputs'):
                    tool_calls = required_action.submit_tool_outputs.tool_calls
                    tool_outputs = []
                    
                    for tool_call in tool_calls:
                        if tool_call.function.name == "stripe_action":
                            try:
                                # Parse arguments
                                args = json.loads(tool_call.function.arguments)
                                action = args.get("action")
                                params = args.get("params", {})
                                
                                logger.info(f"🔧 Executing Stripe action: {action}")
                                
                                # Call MCP tool directly
                                result = await self._mcp_client.call_tool(action, params)
                                
                                # Format result as JSON string
                                output = json.dumps(result)
                                tool_outputs.append({
                                    "tool_call_id": tool_call.id,
                                    "output": output
                                })
                                
                                logger.info(f"✅ Stripe action succeeded: {action}")
                                
                            except Exception as e:
                                logger.error(f"❌ Stripe action failed: {action}")
                                logger.error(f"   Error: {e}")
                                tool_outputs.append({
                                    "tool_call_id": tool_call.id,
                                    "output": json.dumps({"error": str(e)})
                                })
                    
                    # Submit tool outputs
                    if tool_outputs:
                        logger.info(f"📤 Submitting {len(tool_outputs)} tool output(s)")
                        run = agents_client.runs.submit_tool_outputs(
                            thread_id=thread_id,
                            run_id=run.id,
                            tool_outputs=tool_outputs
                        )
            
            await asyncio.sleep(1)
            run = agents_client.runs.get(thread_id=thread_id, run_id=run.id)
            logger.debug(f"Run status: {run.status} (iteration {iteration})")
        
        # Store token usage
        if hasattr(run, 'usage') and run.usage:
            self.last_token_usage = {
                "prompt_tokens": run.usage.prompt_tokens,
                "completion_tokens": run.usage.completion_tokens,
                "total_tokens": run.usage.total_tokens,
            }
            logger.info(f"💰 Token usage: {self.last_token_usage}")
        
        if run.status == "failed":
            logger.error(f"Run failed: {run.last_error}")
            raise RuntimeError(f"Run failed: {run.last_error}")
        
        logger.info(f"✅ Run {run.id} completed with status: {run.status}")
        return run
    
    async def get_response(self, thread_id: str) -> str:
        """Get the latest assistant response from a thread."""
        agents_client = self._get_agents_client()
        messages = agents_client.messages.list(
            thread_id=thread_id,
            order=ListSortOrder.DESCENDING,
            limit=10,
        )
        
        for message in messages:
            if message.role == "assistant":
                response_text = ""
                for content in message.content:
                    if hasattr(content, 'text'):
                        response_text += content.text.value
                return response_text
        
        return ""
    
    async def run_with_streaming(self, thread_id: str, user_message: str):
        """Run the agent with streaming response."""
        if not self.agent:
            await self.create_agent()
        
        # Add user message
        await self.add_message(thread_id, user_message)
        
        # Run and wait
        await self.run_and_wait(thread_id)
        
        # Get response
        response = await self.get_response(thread_id)
        
        # Yield response
        yield response
    
    async def chat(self, thread_id: str, user_message: str) -> str:
        """Simple chat interface - add message, run, return response."""
        if not self.agent:
            await self.create_agent()
        
        # Add user message
        await self.add_message(thread_id, user_message)
        
        # Run and wait
        await self.run_and_wait(thread_id)
        
        # Get and return response
        return await self.get_response(thread_id)
    
    async def cleanup(self):
        """Clean up agent resources."""
        if self.agent:
            try:
                agents_client = self._get_agents_client()
                agents_client.delete_agent(self.agent.id)
                logger.info(f"Deleted agent: {self.agent.id}")
                self.agent = None
            except Exception as e:
                logger.warning(f"Failed to delete agent: {e}")


# Global singleton for the agent
_stripe_agent_instance: Optional[FoundryStripeAgent] = None


async def get_stripe_agent() -> FoundryStripeAgent:
    """Get or create the global Stripe agent instance."""
    global _stripe_agent_instance
    if _stripe_agent_instance is None:
        _stripe_agent_instance = FoundryStripeAgent()
        await _stripe_agent_instance.create_agent()
    return _stripe_agent_instance
