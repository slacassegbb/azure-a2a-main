"""
AI Foundry Agent implementation with HubSpot CRM Capabilities.
Uses AgentsClient directly for Azure AI Foundry with HubSpot MCP integration.

IMPORTANT: Uses the FLATTENED HubSpot MCP server for Azure AI Foundry compatibility.
The official @hubspot/mcp-server has nested schemas that cause issues with Azure.
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


# HubSpot MCP Server URL (FLATTENED version on Azure Container Apps)
HUBSPOT_MCP_URL = os.getenv(
    "HUBSPOT_MCP_URL", 
    "https://mcp-hubspot-flat.ambitioussky-6c709152.westus2.azurecontainerapps.io/sse"
)


class FoundryHubSpotAgent:
    """
    AI Foundry Agent with HubSpot CRM capabilities.
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
        """Create the AI Foundry agent with HubSpot MCP capabilities."""
        if self.agent:
            logger.info("Agent already exists, returning existing instance")
            return self.agent
        
        logger.info("🚀 CREATING NEW AZURE FOUNDRY HUBSPOT AGENT...")
        
        # Create MCP tool for HubSpot
        logger.info("🔍 CREATING HUBSPOT MCP TOOL CONNECTION...")
        logger.info(f"   Server URL: {HUBSPOT_MCP_URL}")
        logger.info(f"   Server Label: HubSpot")
        
        try:
            # Test MCP server connectivity
            logger.info("🧪 TESTING HUBSPOT MCP SERVER CONNECTIVITY...")
            import httpx
            
            try:
                headers = {"Accept": "text/event-stream"}
                async with httpx.AsyncClient(timeout=5.0) as client:
                    async with client.stream("GET", HUBSPOT_MCP_URL, headers=headers) as response:
                        if response.status_code == 200:
                            logger.info("✅ HubSpot MCP Server connectivity test PASSED")
            except Exception as e:
                logger.warning(f"⚠️ MCP connectivity test: {e}")
            
            # Create MCP tool with ALL 10 flattened HubSpot tools
            logger.info("🔧 CREATING McpTool OBJECT FOR HUBSPOT...")
            
            mcp_tool = McpTool(
                server_label="HubSpot",
                server_url=HUBSPOT_MCP_URL,
                allowed_tools=[
                    # Account & Info
                    "hubspot_get_user_details",
                    # Object Operations (CRUD)
                    "hubspot_list_objects",
                    "hubspot_search_objects",
                    "hubspot_get_object",
                    "hubspot_update_object",
                    # Create Operations
                    "hubspot_create_contact",
                    "hubspot_create_company",
                    "hubspot_create_deal",
                    # Associations & Engagements
                    "hubspot_list_associations",
                    "hubspot_create_note",
                ]
            )
            self._mcp_tool = mcp_tool
            logger.info("✅ HubSpot McpTool object created successfully")

            mcp_tool.set_approval_mode("never")
            logger.info("✅ Set approval mode to 'never'")
            
            # Set headers
            mcp_tool.update_headers("Content-Type", "application/json")
            mcp_tool.update_headers("User-Agent", "Azure-AI-Foundry-HubSpot-Agent")
            mcp_tool.update_headers("Accept", "application/json, text/event-stream")
            logger.info("✅ Set MCP headers")
            
            # Use ToolSet
            toolset = ToolSet()
            toolset.add(mcp_tool)
            self._toolset = toolset
            
            # Store MCP tool resources for run creation
            self._mcp_tool_resources = mcp_tool.resources
            
            logger.info(f"🔍 HUBSPOT MCP TOOL DETAILS:")
            logger.info(f"   Tools count: {len(mcp_tool.definitions) if mcp_tool.definitions else 0}")
            logger.info(f"   MCP Tool resources: {self._mcp_tool_resources}")
            logger.info("✅ Added HubSpot MCP server integration")
            
        except Exception as e:
            logger.error(f"❌ FAILED TO CREATE HUBSPOT MCP TOOL: {e}")
            import traceback
            logger.error(f"   Full traceback: {traceback.format_exc()}")
            self._toolset = ToolSet()  # Empty toolset
            logger.warning("⚠️ Continuing without HubSpot MCP tools")
        
        # Get model deployment name
        model = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")
        
        # HubSpot-specific instructions
        instructions = """You are an expert HubSpot CRM assistant. You help users manage their HubSpot account including:

## Your Capabilities:
1. **Contact Management** - Create, search, list, and update contacts
2. **Company Management** - Create, search, list, and update companies
3. **Deal Management** - Create, search, list, and update deals and opportunities
4. **Associations** - View relationships between contacts, companies, and deals
5. **Notes & Engagements** - Create notes and engagement records on CRM objects
6. **Account Info** - View account details, owners, and permissions

## Important Guidelines:
- Always use the HubSpot MCP tools to perform operations
- When listing items, summarize the key information clearly
- For contact operations, include relevant details like email, name, and company
- For deal operations, always include deal name, stage, and amount when available
- Be proactive in suggesting related actions
- When creating objects, confirm the required fields are provided
- If an operation fails, explain what went wrong and suggest alternatives

## Search Filter Syntax:
When using hubspot_search_objects, filters use this format:
- "property OPERATOR value" (e.g., "email EQ john@example.com")
- Operators: EQ, NEQ, LT, LTE, GT, GTE, CONTAINS_TOKEN
- Multiple filters are ANDed together (filter1, filter2, filter3)

## Response Format:
- Use clear headers and bullet points for readability
- Include HubSpot record URLs when available for easy navigation
- Include relevant IDs for reference
- Summarize results concisely but completely
"""
        
        logger.info(f"Creating HubSpot agent with model: {model}")
        
        # Use AgentsClient directly to create agent
        agents_client = self._get_agents_client()
        
        self.agent = agents_client.create_agent(
            model=model,
            name="AI Foundry HubSpot Agent",
            instructions=instructions,
            toolset=self._toolset,
        )
        
        logger.info(f"✅ Created HubSpot agent: {self.agent.id}")
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
_hubspot_agent_instance: Optional[FoundryHubSpotAgent] = None


async def get_hubspot_agent() -> FoundryHubSpotAgent:
    """Get or create the global HubSpot agent instance."""
    global _hubspot_agent_instance
    if _hubspot_agent_instance is None:
        _hubspot_agent_instance = FoundryHubSpotAgent()
        await _hubspot_agent_instance.create_agent()
    return _hubspot_agent_instance
