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
from typing import Optional, Dict

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import (
    Agent, ListSortOrder, McpTool, ToolSet
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
    Uses AgentsClient directly for the new SDK version.
    """
    
    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self.agent: Optional[Agent] = None
        self.threads: Dict[str, str] = {}
        self._agents_client = None
        self._mcp_tool = None
        self._mcp_tool_resources = None
        self._toolset = None
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
        """Create the AI Foundry agent with Stripe MCP capabilities."""
        if self.agent:
            logger.info("Agent already exists, returning existing instance")
            return self.agent
        
        logger.info("🚀 CREATING NEW AZURE FOUNDRY STRIPE AGENT...")
        
        # Create MCP tool for Stripe
        logger.info("🔍 CREATING STRIPE MCP TOOL CONNECTION...")
        logger.info(f"   Server URL: {STRIPE_MCP_URL}")
        logger.info(f"   Server Label: Stripe")
        
        try:
            # Test MCP server connectivity
            logger.info("🧪 TESTING STRIPE MCP SERVER CONNECTIVITY...")
            import httpx
            
            try:
                headers = {"Accept": "text/event-stream"}
                async with httpx.AsyncClient(timeout=5.0) as client:
                    async with client.stream("GET", STRIPE_MCP_URL, headers=headers) as response:
                        if response.status_code == 200:
                            logger.info("✅ Stripe MCP Server connectivity test PASSED")
            except Exception as e:
                logger.warning(f"⚠️ MCP connectivity test: {e}")
            
            # Create MCP tool with ALL 22 Stripe tools
            logger.info("🔧 CREATING McpTool OBJECT FOR STRIPE...")
            
            mcp_tool = McpTool(
                server_label="Stripe",
                server_url=STRIPE_MCP_URL,
                allowed_tools=[
                    # Customer Management
                    "list_customers",
                    "create_customer",
                    "retrieve_customer",
                    "update_customer",
                    "delete_customer",
                    "search_customers",
                    # Payment Intents
                    "list_payment_intents",
                    "create_payment_intent",
                    "retrieve_payment_intent",
                    "confirm_payment_intent",
                    "cancel_payment_intent",
                    # Subscriptions
                    "list_subscriptions",
                    "create_subscription",
                    "retrieve_subscription",
                    "update_subscription",
                    "cancel_subscription",
                    # Products & Prices
                    "list_products",
                    "create_product",
                    "list_prices",
                    "create_price",
                    # Invoices
                    "list_invoices",
                    "create_invoice",
                    # Balance
                    "retrieve_balance",
                ]
            )
            self._mcp_tool = mcp_tool
            logger.info("✅ Stripe McpTool object created successfully")

            mcp_tool.set_approval_mode("never")
            logger.info("✅ Set approval mode to 'never'")
            
            # Set headers
            mcp_tool.update_headers("Content-Type", "application/json")
            mcp_tool.update_headers("User-Agent", "Azure-AI-Foundry-Stripe-Agent")
            mcp_tool.update_headers("Accept", "application/json, text/event-stream")
            logger.info("✅ Set MCP headers")
            
            # Use ToolSet
            toolset = ToolSet()
            toolset.add(mcp_tool)
            self._toolset = toolset
            
            # Store MCP tool resources for run creation
            self._mcp_tool_resources = mcp_tool.resources
            
            logger.info(f"🔍 STRIPE MCP TOOL DETAILS:")
            logger.info(f"   Tools count: {len(mcp_tool.definitions) if mcp_tool.definitions else 0}")
            logger.info(f"   MCP Tool resources: {self._mcp_tool_resources}")
            logger.info("✅ Added Stripe MCP server integration")
            
        except Exception as e:
            logger.error(f"❌ FAILED TO CREATE STRIPE MCP TOOL: {e}")
            import traceback
            logger.error(f"   Full traceback: {traceback.format_exc()}")
            self._toolset = ToolSet()  # Empty toolset
            logger.warning("⚠️ Continuing without Stripe MCP tools")
        
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

## Important Guidelines:
- Always use the Stripe MCP tools to perform operations
- When listing items, summarize the key information clearly
- For customer operations, include relevant details like email and name
- For payment operations, always confirm amounts and currencies
- Be proactive in suggesting related actions
- When displaying monetary amounts, format them clearly with currency symbols
- If an operation fails, explain what went wrong and suggest alternatives

## Response Format:
- Use clear headers and bullet points for readability
- Include relevant IDs (customer IDs, payment IDs) for reference
- Summarize results concisely but completely
"""
        
        logger.info(f"Creating Stripe agent with model: {model}")
        
        # Use AgentsClient directly to create agent
        agents_client = self._get_agents_client()
        
        self.agent = agents_client.create_agent(
            model=model,
            name="AI Foundry Stripe Agent",
            instructions=instructions,
            toolset=self._toolset,
        )
        
        logger.info(f"✅ Created Stripe agent: {self.agent.id}")
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
        """Run the agent on a thread and wait for completion."""
        if not self.agent:
            await self.create_agent()
        
        agents_client = self._get_agents_client()
        
        # Create run with MCP tool resources
        run = agents_client.runs.create(
            thread_id=thread_id,
            agent_id=self.agent.id,
            tool_resources=self._mcp_tool_resources,
        )
        
        logger.info(f"Created run {run.id} on thread {thread_id}")
        
        # Poll for completion
        import time
        start_time = time.time()
        while run.status in ["queued", "in_progress"]:
            if time.time() - start_time > timeout:
                logger.error(f"Run {run.id} timed out after {timeout}s")
                raise TimeoutError(f"Run timed out after {timeout} seconds")
            
            await asyncio.sleep(1)
            run = agents_client.runs.get(thread_id=thread_id, run_id=run.id)
            logger.debug(f"Run status: {run.status}")
        
        # Store token usage
        if hasattr(run, 'usage') and run.usage:
            self.last_token_usage = {
                "prompt_tokens": run.usage.prompt_tokens,
                "completion_tokens": run.usage.completion_tokens,
                "total_tokens": run.usage.total_tokens,
            }
            logger.info(f"Token usage: {self.last_token_usage}")
        
        if run.status == "failed":
            logger.error(f"Run failed: {run.last_error}")
            raise RuntimeError(f"Run failed: {run.last_error}")
        
        logger.info(f"Run {run.id} completed with status: {run.status}")
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
