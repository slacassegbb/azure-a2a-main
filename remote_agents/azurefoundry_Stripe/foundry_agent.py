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
    Agent, ListSortOrder, ToolSet, McpTool, ToolApproval
)
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)


# Stripe MCP Server URL (deployed on Azure Container Apps)
STRIPE_MCP_URL = os.getenv(
    "STRIPE_MCP_URL", 
    "https://mcp-stripe.ambitioussky-6c709152.westus2.azurecontainerapps.io/sse"
)


class FoundryStripeAgent:
    """
    AI Foundry Agent with Stripe Payment Processing capabilities.
    Uses AgentsClient directly for the new SDK version with McpTool integration.
    """
    
    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self.agent: Optional[Agent] = None
        self.threads: Dict[str, str] = {}
        self._agents_client = None
        self._mcp_tool = None
        self._mcp_tool_resources = None
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
        """Create the AI Foundry agent with Stripe capabilities using McpTool."""
        if self.agent:
            logger.info("Agent already exists, returning existing instance")
            return self.agent
        
        logger.info("🚀 CREATING NEW AZURE FOUNDRY STRIPE AGENT...")
        
        # Create McpTool with Azure's native MCP integration
        logger.info("🔧 CREATING McpTool CONNECTION...")
        logger.info(f"   MCP Server: {STRIPE_MCP_URL}")
        
        tools = []
        
        try:
            # Test MCP server connectivity using health endpoint
            logger.info("🧪 TESTING MCP SERVER CONNECTIVITY...")
            async def test_mcp_basic():
                try:
                    # Test base URL (returns server info)
                    base_url = STRIPE_MCP_URL.rstrip('/sse')
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.get(base_url)
                        logger.info(f"   MCP Server Response: {response.status_code}")
                        logger.info(f"   Response Content (first 100 chars): {response.text[:100]}")
                        if response.status_code == 200:
                            logger.info("✅ MCP Server connectivity test PASSED")
                            return True
                        else:
                            logger.error(f"❌ MCP Server returned status: {response.status_code}")
                            return False
                except Exception as e:
                    logger.error(f"   MCP Server Test FAILED: {e}")
                    return False
            
            await test_mcp_basic()
            
            # Create MCP tool with all Stripe tools
            # NOTE: Stripe MCP tools do NOT have a prefix (e.g., "list_customers" not "stripe_list_customers")
            logger.info("🔧 CREATING McpTool OBJECT...")
            mcp_tool = McpTool(
                server_label="Stripe",
                server_url=STRIPE_MCP_URL,
                allowed_tools=[
                    # Customer Management
                    "create_customer",
                    "list_customers",
                    # Products & Prices
                    "create_product",
                    "list_products",
                    "create_price",
                    "list_prices",
                    # Payment Links
                    "create_payment_link",
                    # Invoices
                    "create_invoice",
                    "list_invoices",
                    "create_invoice_item",
                    "finalize_invoice",
                    # Balance & Payments
                    "retrieve_balance",
                    "create_refund",
                    "list_payment_intents",
                    # Subscriptions
                    "list_subscriptions",
                    "cancel_subscription",
                    "update_subscription",
                    # Coupons & Disputes
                    "list_coupons",
                    "create_coupon",
                    "update_dispute",
                    "list_disputes",
                    # Documentation
                    "search_stripe_documentation"
                ]
            )
            
            # Store the mcp_tool for resources access
            self._mcp_tool = mcp_tool
            logger.info("✅ McpTool object created successfully")

            # Set approval mode to "never" - MCP tools execute without human approval
            mcp_tool.set_approval_mode("never")
            logger.info("✅ Set approval mode to 'never'")
            
            # Set headers for MCP communication
            mcp_tool.update_headers("Content-Type", "application/json")
            mcp_tool.update_headers("User-Agent", "Azure-AI-Foundry-Agent")
            mcp_tool.update_headers("Accept", "application/json, text/event-stream")
            logger.info("✅ Set MCP headers")
            
            # Get tool definitions from MCP
            tools = list(mcp_tool.definitions)
            
            # Store MCP tool resources - needed for runs.create()
            self._mcp_tool_resources = mcp_tool.resources
            
            logger.info(f"🔍 MCP TOOL DETAILS:")
            logger.info(f"   Tools count: {len(tools)}")
            logger.info(f"   MCP Tool resources for run creation: {type(self._mcp_tool_resources)}")
            logger.info("✅ Added Stripe MCP server integration using McpTool")
            
        except Exception as e:
            logger.error(f"❌ FAILED TO CREATE MCP TOOL: {e}")
            import traceback
            logger.error(f"   Full traceback: {traceback.format_exc()}")
            logger.warning("⚠️ Continuing without MCP tools due to connection failure")
        
        # Get model deployment name
        model = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")
        
        # Stripe-specific instructions
        instructions = self._get_agent_instructions()
        
        logger.info(f"Creating Stripe agent with model: {model}")
        
        # Use AgentsClient to create agent with McpTool
        agents_client = self._get_agents_client()
        
        self.agent = agents_client.create_agent(
            model=model,
            name="AI Foundry Stripe Agent",
            instructions=instructions,
            tools=tools,
        )
        
        logger.info(f"✅ Created Stripe agent: {self.agent.id}")
        logger.info(f"   Tools: {len(tools)} definitions")
        return self.agent
    
    def _get_agent_instructions(self) -> str:
        """Get the agent instructions for Stripe payment processing."""
        return """You are an expert Stripe payment processing assistant. You help users manage their Stripe account.

## Your Capabilities

You have access to Stripe MCP tools that can:
- **Customer Management**: Create, list, and search customers
- **Products & Prices**: Create and list products and prices
- **Payment Links**: Create hosted checkout payment links
- **Invoices**: Create, list, finalize invoices and add line items
- **Balance & Payments**: Check balance, create refunds, list payment intents
- **Subscriptions**: List, update, and cancel subscriptions
- **Coupons & Disputes**: Manage coupons and disputes

## Important Payment Flow

⚠️ **To collect payments, use the INVOICE workflow:**
1. Create invoice: `create_invoice` with customer ID
2. Add line items: `create_invoice_item`
3. Finalize: `finalize_invoice`

OR use `create_payment_link` for a hosted checkout page.

## Response Format
- Use clear headers and bullet points
- Include Stripe IDs for reference
- Summarize results concisely

## CRITICAL: When You Need User Input
If you need clarification or confirmation:
- Start your response EXACTLY with: NEEDS_INPUT:
- Then provide your question
- Example: "NEEDS_INPUT: What email should I use for the customer?"
"""
    
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

    async def run_conversation_stream(self, thread_id: str, user_message: str):
        """Run conversation and yield responses."""
        logger.info(f"🚀 STARTING CONVERSATION STREAM")
        logger.info(f"   Thread ID: {thread_id}")
        logger.info(f"   User message: {user_message[:100]}...")
        
        if not self.agent:
            await self.create_agent()

        await self.add_message(thread_id, user_message)
        
        client = self._get_agents_client()
        
        # Create run with MCP tool resources
        mcp_tool = self._mcp_tool
        if mcp_tool and hasattr(mcp_tool, 'resources'):
            logger.info("🔧 Creating run with MCP tool_resources")
            run = client.runs.create(
                thread_id=thread_id, 
                agent_id=self.agent.id,
                tool_resources=mcp_tool.resources,
                max_prompt_tokens=25000,
                truncation_strategy={"type": "last_messages", "last_messages": 3}
            )
        else:
            logger.info("Creating run without MCP tool_resources")
            run = client.runs.create(
                thread_id=thread_id, 
                agent_id=self.agent.id,
                max_prompt_tokens=25000,
                truncation_strategy={"type": "last_messages", "last_messages": 3}
            )
        
        logger.info(f"   Run created: {run.id}")
        
        max_iterations = 25
        iterations = 0
        tool_calls_yielded = set()

        while run.status in ["queued", "in_progress", "requires_action"] and iterations < max_iterations:
            iterations += 1
            logger.info(f"   🔄 Iteration {iterations}: run.status = {run.status}")
            await asyncio.sleep(2)
            
            # Check for tool calls
            try:
                run_steps = client.run_steps.list(thread_id, run.id)
                for run_step in run_steps:
                    step_id = getattr(run_step, 'id', f'step_{iterations}')
                    if (hasattr(run_step, "step_details") and
                        hasattr(run_step.step_details, "type") and
                        run_step.step_details.type == "tool_calls" and
                        hasattr(run_step.step_details, "tool_calls")):
                        for idx, tool_call in enumerate(run_step.step_details.tool_calls):
                            tool_call_id = getattr(tool_call, 'id', f'{step_id}_call_{idx}')
                            if tool_call_id not in tool_calls_yielded:
                                tool_type = getattr(tool_call, 'type', 'unknown')
                                yield f"🛠️ Remote agent executing: {tool_type}"
                                tool_calls_yielded.add(tool_call_id)
            except Exception as e:
                logger.warning(f"   ⚠️ Error getting run steps: {e}")

            try:
                run = client.runs.get(thread_id=thread_id, run_id=run.id)
            except Exception as e:
                if "rate limit" in str(e).lower() or "429" in str(e):
                    await asyncio.sleep(15)
                    continue
                else:
                    yield f"Error: {str(e)}"
                    return

            if run.status == "failed":
                logger.error(f"❌ RUN FAILED: {run.last_error}")
                yield f"❌ **Run Failed:** {run.last_error}"
                return

            if run.status == "requires_action":
                logger.info(f"🔧 RUN REQUIRES ACTION")
                # MCP tools with approval_mode="never" should auto-execute
                # But if we get here, just wait for it to process
                await asyncio.sleep(2)

        # Get final response
        if run.status == "completed":
            # Extract token usage
            if hasattr(run, 'usage') and run.usage:
                self.last_token_usage = {
                    "prompt_tokens": run.usage.prompt_tokens,
                    "completion_tokens": run.usage.completion_tokens,
                    "total_tokens": run.usage.total_tokens
                }
                logger.warning(f"📊 Token usage: {self.last_token_usage}")
            
            # Get messages
            messages = client.messages.list(thread_id=thread_id, order=ListSortOrder.DESCENDING)
            for msg in messages:
                if msg.role == "assistant":
                    for content in msg.content:
                        if hasattr(content, 'text') and hasattr(content.text, 'value'):
                            yield content.text.value
                    break
        else:
            yield f"Run ended with status: {run.status}"

    async def run_conversation(self, thread_id: str, user_message: str) -> str:
        """Non-streaming version - collects all responses."""
        responses = []
        async for response in self.run_conversation_stream(thread_id, user_message):
            responses.append(response)
        return "\n".join(responses)

    async def chat(self, thread_id: str, user_message: str) -> str:
        """Alias for run_conversation - for executor compatibility."""
        return await self.run_conversation(thread_id, user_message)

