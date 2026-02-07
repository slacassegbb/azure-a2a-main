"""
AI Foundry Agent implementation with HubSpot CRM Capabilities.
Uses AgentsClient directly for Azure AI Foundry with HubSpot MCP integration.

Uses native McpTool to enable the LLM to see filter parameters and reduce token usage
through smart filtering (e.g., searching for specific contacts instead of listing all).
"""
import os
import asyncio
import logging
import json
from typing import Optional, Dict, Any
import httpx

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import (
    Agent, ListSortOrder, ToolSet, McpTool
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
    AI Foundry Agent with HubSpot CRM capabilities using native McpTool.
    
    Uses McpTool which exposes filter parameters to the LLM, enabling smart filtering
    to reduce token usage (e.g., 3k tokens for filtered query vs 19k for unfiltered).
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
        
    def _get_client(self) -> AgentsClient:
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
        
        logger.info("Creating new Azure Foundry HubSpot agent...")
        logger.info(f"   MCP Server URL: {HUBSPOT_MCP_URL}")
        
        try:
            # Test MCP server connectivity
            logger.info("Testing MCP server connectivity...")
            async with httpx.AsyncClient(timeout=10.0) as http_client:
                try:
                    async with http_client.stream("GET", HUBSPOT_MCP_URL, headers={"Accept": "text/event-stream"}) as response:
                        logger.info(f"   MCP Server Response: {response.status_code}")
                        if response.status_code == 200:
                            logger.info("MCP Server connectivity test PASSED")
                except asyncio.TimeoutError:
                    logger.info("MCP Server connectivity test PASSED (SSE stream timeout - expected)")
                except Exception as e:
                    logger.warning(f"MCP connectivity test warning: {e}")
            
            # Create MCP tool with all HubSpot tools
            logger.info("Creating McpTool with HubSpot tools...")
            mcp_tool = McpTool(
                server_label="HubSpot",
                server_url=HUBSPOT_MCP_URL,
                # All 10 HubSpot tools (with hubspot_ prefix)
                allowed_tools=[
                    "hubspot_get_user_details",
                    "hubspot_list_objects",
                    "hubspot_search_objects",
                    "hubspot_get_object",
                    "hubspot_create_contact",
                    "hubspot_create_company",
                    "hubspot_create_deal",
                    "hubspot_update_object",
                    "hubspot_list_associations",
                    "hubspot_create_note"
                ]
            )
            
            self._mcp_tool = mcp_tool
            logger.info("McpTool object created successfully")

            mcp_tool.set_approval_mode("never")
            logger.info("Set approval mode to never")
            
            mcp_tool.update_headers("Content-Type", "application/json")
            mcp_tool.update_headers("User-Agent", "Azure-AI-Foundry-Agent")
            mcp_tool.update_headers("Accept", "application/json, text/event-stream")
            logger.info("Set MCP headers")
            
            toolset = ToolSet()
            toolset.add(mcp_tool)
            self._toolset = toolset
            
            self._mcp_tool_resources = mcp_tool.resources
            
            logger.info(f"MCP Tool Details:")
            logger.info(f"   Tools: {len(mcp_tool.definitions) if mcp_tool.definitions else 0}")
            logger.info(f"   Resources: {self._mcp_tool_resources}")
            
        except Exception as e:
            logger.error(f"Failed to create MCP tool: {e}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            raise
        
        client = self._get_client()
        
        self.agent = client.create_agent(
            model="gpt-4o",
            name="foundry-hubspot-agent",
            instructions=self._get_agent_instructions(),
            toolset=self._toolset
        )
        
        logger.info(f"Created AI Foundry HubSpot agent: {self.agent.id}")
        return self.agent
    
    def _get_agent_instructions(self) -> str:
        return """You are a specialized HubSpot CRM assistant with direct access to HubSpot data.

## Your Capabilities
You can perform the following CRM operations:
- **Contacts**: List, search, create, update contacts
- **Companies**: List, search, create, update companies  
- **Deals**: List, search, create, update deals
- **Associations**: View relationships between objects
- **Notes**: Add notes to records

## CRITICAL: Smart Filtering Rules
To minimize API costs and response times, ALWAYS use filters when possible:

1. **hubspot_search_objects** - Use this with filters for finding specific records:
   - Search by email, name, company, or other properties
   - Always specify just the properties you need
   
2. **hubspot_list_objects** - Use pagination (limit parameter) when browsing:
   - Default to small limits (10-25 records)
   - Only request needed properties

3. **hubspot_get_object** - Use when you have a specific object ID

## Response Format
- Be concise and focused on the CRM data
- Format contact/company/deal information clearly
- When showing lists, summarize key fields
- Mention record counts and if there are more records available

## Error Handling
- If a search returns no results, suggest alternative search terms
- If an operation fails, explain what went wrong
- Offer to try alternative approaches when appropriate"""

    async def create_thread(self) -> str:
        """Create a new thread for conversation."""
        client = self._get_client()
        thread = client.threads.create()
        logger.info(f"Created new thread: {thread.id}")
        return thread.id

    async def run_conversation_stream(self, thread_id: str, user_message: str):
        """Streaming version - yields responses as they come."""
        if not self.agent:
            await self.create_agent()
        
        client = self._get_client()
        
        # Add user message
        client.messages.create(
            thread_id=thread_id,
            role="user",
            content=user_message
        )
        logger.info(f"Added user message to thread {thread_id}")
        
        # Create run
        logger.info("Creating run with MCP tool resources...")
        mcp_tool = self._mcp_tool
        if self._mcp_tool_resources:
            run = client.runs.create(
                thread_id=thread_id, 
                agent_id=self.agent.id,
                tool_resources=self._mcp_tool_resources,
                max_prompt_tokens=25000,
                truncation_strategy={"type": "last_messages", "last_messages": 3}
            )
        else:
            run = client.runs.create(
                thread_id=thread_id, 
                agent_id=self.agent.id,
                max_prompt_tokens=25000,
                truncation_strategy={"type": "last_messages", "last_messages": 3}
            )
        
        logger.info(f"   Run created: {run.id}")
        
        # Check if run failed immediately (before the while loop)
        if run.status == "failed":
            logger.error(f"❌ RUN FAILED IMMEDIATELY ON CREATION!")
            logger.error(f"   Run ID: {run.id}")
            logger.error(f"   Last error: {run.last_error}")
            yield f"❌ **Run Failed Immediately:** {run.last_error}"
            return
        
        max_iterations = 25
        iterations = 0
        retry_count = 0
        max_retries = 3
        tool_calls_yielded = set()

        while run.status in ["queued", "in_progress", "requires_action"] and iterations < max_iterations:
            iterations += 1
            logger.info(f"   Iteration {iterations}: run.status = {run.status}")
            
            # Use adaptive polling: start fast, slow down to reduce API calls and token usage
            # First 3 polls: 2s (fast startup)
            # Next 5 polls: 3s (moderate)
            # After that: 5s (conserve TPM)
            if iterations <= 3:
                poll_interval = 2
            elif iterations <= 8:
                poll_interval = 3
            else:
                poll_interval = 5
            
            await asyncio.sleep(poll_interval)
            
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
                logger.warning(f"   Error getting run steps: {e}")

            try:
                run = client.runs.get(thread_id=thread_id, run_id=run.id)
            except Exception as e:
                if "rate limit" in str(e).lower() or "429" in str(e):
                    retry_count += 1
                    if retry_count <= max_retries:
                        backoff_time = min(15 * (2 ** retry_count), 45)
                        logger.warning(f"🔄 Rate limit on polling - retry {retry_count}/{max_retries} after {backoff_time}s")
                        await asyncio.sleep(backoff_time)
                        continue
                    else:
                        yield "Error: Rate limit exceeded, please try again later"
                        return
                else:
                    yield f"Error: {str(e)}"
                    return

            if run.status == "failed":
                logger.error(f"❌ RUN FAILED!")
                logger.error(f"   Run ID: {run.id}")
                logger.error(f"   Last error: {run.last_error}")
                
                # Check for rate limit error and retry with exponential backoff
                error_code = None
                error_message = None
                if run.last_error:
                    if hasattr(run.last_error, 'code'):
                        error_code = run.last_error.code
                    if hasattr(run.last_error, 'message'):
                        error_message = run.last_error.message
                    
                    # CHECK FOR RATE LIMIT ERROR - Retry with exponential backoff
                    if error_code == 'rate_limit_exceeded' or (error_message and 'rate limit' in error_message.lower()):
                        logger.warning(f"🔄 RATE LIMIT DETECTED - Implementing retry logic")
                        retry_count += 1
                        if retry_count <= max_retries:
                            # Exponential backoff: 15s, 30s, 60s
                            backoff_time = min(15 * (2 ** retry_count), 60)
                            logger.warning(f"   Retry {retry_count}/{max_retries} after {backoff_time}s backoff")
                            yield f"⏳ Rate limit hit - retrying in {backoff_time}s (attempt {retry_count}/{max_retries})..."
                            await asyncio.sleep(backoff_time)
                            
                            # Reset run and continue the loop
                            logger.info(f"🔄 Retrying run creation after rate limit backoff...")
                            if self._mcp_tool_resources:
                                run = client.runs.create(
                                    thread_id=thread_id, 
                                    agent_id=self.agent.id,
                                    tool_resources=self._mcp_tool_resources,
                                    max_prompt_tokens=25000,
                                    truncation_strategy={"type": "last_messages", "last_messages": 3}
                                )
                            else:
                                run = client.runs.create(
                                    thread_id=thread_id, 
                                    agent_id=self.agent.id,
                                    max_prompt_tokens=25000,
                                    truncation_strategy={"type": "last_messages", "last_messages": 3}
                                )
                            logger.info(f"   New run created: {run.id}")
                            iterations = 0  # Reset iteration counter for the new run
                            continue  # Continue the while loop with the new run
                        else:
                            logger.error(f"❌ Max retries ({max_retries}) exceeded for rate limit")
                            yield f"❌ Rate limit exceeded after {max_retries} retries - please wait and try again later"
                            return
                
                yield f"❌ Run Failed: {run.last_error}"
                return

        # Get token usage
        if hasattr(run, 'usage') and run.usage:
            self.last_token_usage = {
                "prompt_tokens": getattr(run.usage, 'prompt_tokens', 0),
                "completion_tokens": getattr(run.usage, 'completion_tokens', 0),
                "total_tokens": getattr(run.usage, 'total_tokens', 0)
            }
            logger.info(f"Token usage: {self.last_token_usage}")

        # Get final response
        messages = list(client.messages.list(thread_id=thread_id, order=ListSortOrder.DESCENDING, limit=5))
        
        if messages:
            latest = messages[0]
            if hasattr(latest, 'content'):
                for content_item in latest.content:
                    if hasattr(content_item, 'text') and hasattr(content_item.text, 'value'):
                        yield content_item.text.value
                        return
        
        yield "No response generated."

    async def run_conversation(self, thread_id: str, user_message: str) -> str:
        """Non-streaming version - collects all responses."""
        responses = []
        async for response in self.run_conversation_stream(thread_id, user_message):
            responses.append(response)
        return "\n".join(responses)

    async def chat(self, thread_id: str, user_message: str) -> str:
        """Alias for run_conversation - for executor compatibility."""
        return await self.run_conversation(thread_id, user_message)


    async def process_message(self, message: str, session_id: str = "default"):
        logger.info(f"Processing HubSpot message: {message[:100]}...")
        
        if not self.agent:
            await self.create_agent()
        
        client = self._get_client()
        
        if session_id not in self.threads:
            thread = client.threads.create()
            self.threads[session_id] = thread.id
            logger.info(f"Created new thread: {thread.id}")
        
        thread_id = self.threads[session_id]
        
        client.messages.create(
            thread_id=thread_id,
            role="user",
            content=message
        )
        logger.info(f"Added user message to thread {thread_id}")
        
        logger.info("Creating run with MCP tool resources...")
        
        if self._mcp_tool_resources:
            run = client.runs.create(
                thread_id=thread_id, 
                agent_id=self.agent.id,
                tool_resources=self._mcp_tool_resources,
                max_prompt_tokens=25000,
                truncation_strategy={"type": "last_messages", "last_messages": 3}
            )
        else:
            run = client.runs.create(
                thread_id=thread_id, 
                agent_id=self.agent.id,
                max_prompt_tokens=25000,
                truncation_strategy={"type": "last_messages", "last_messages": 3}
            )
        
        logger.info(f"   Run created: {run.id}")
        
        # Check if run failed immediately (before the while loop)
        if run.status == "failed":
            logger.error(f"❌ RUN FAILED IMMEDIATELY ON CREATION!")
            logger.error(f"   Run ID: {run.id}")
            logger.error(f"   Last error: {run.last_error}")
            yield f"❌ **Run Failed Immediately:** {run.last_error}"
            return
        
        max_iterations = 25
        iterations = 0
        retry_count = 0
        max_retries = 3
        tool_calls_yielded = set()

        while run.status in ["queued", "in_progress", "requires_action"] and iterations < max_iterations:
            iterations += 1
            logger.info(f"   Iteration {iterations}: run.status = {run.status}")
            
            # Use adaptive polling: start fast, slow down to reduce API calls and token usage
            if iterations <= 3:
                poll_interval = 2
            elif iterations <= 8:
                poll_interval = 3
            else:
                poll_interval = 5
            
            await asyncio.sleep(poll_interval)
            
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
                                yield f"Remote agent executing: {tool_type}"
                                tool_calls_yielded.add(tool_call_id)
            except Exception as e:
                logger.warning(f"   Error getting run steps: {e}")

            try:
                run = client.runs.get(thread_id=thread_id, run_id=run.id)
            except Exception as e:
                if "rate limit" in str(e).lower() or "429" in str(e):
                    retry_count += 1
                    if retry_count <= max_retries:
                        backoff_time = min(15 * (2 ** retry_count), 45)
                        logger.warning(f"🔄 Rate limit on polling - retry {retry_count}/{max_retries} after {backoff_time}s")
                        await asyncio.sleep(backoff_time)
                        continue
                    else:
                        yield "Error: Rate limit exceeded, please try again later"
                        return
                else:
                    yield f"Error: {str(e)}"
                    return

            if run.status == "failed":
                logger.error(f"❌ RUN FAILED!")
                logger.error(f"   Run ID: {run.id}")
                logger.error(f"   Last error: {run.last_error}")
                
                # Check for rate limit error and retry with exponential backoff
                error_code = None
                error_message = None
                if run.last_error:
                    if hasattr(run.last_error, 'code'):
                        error_code = run.last_error.code
                    if hasattr(run.last_error, 'message'):
                        error_message = run.last_error.message
                    
                    # CHECK FOR RATE LIMIT ERROR - Retry with exponential backoff
                    if error_code == 'rate_limit_exceeded' or (error_message and 'rate limit' in error_message.lower()):
                        logger.warning(f"🔄 RATE LIMIT DETECTED - Implementing retry logic")
                        retry_count += 1
                        if retry_count <= max_retries:
                            backoff_time = min(15 * (2 ** retry_count), 60)
                            logger.warning(f"   Retry {retry_count}/{max_retries} after {backoff_time}s backoff")
                            yield f"⏳ Rate limit hit - retrying in {backoff_time}s (attempt {retry_count}/{max_retries})..."
                            await asyncio.sleep(backoff_time)
                            
                            # Reset run and continue the loop
                            if self._mcp_tool_resources:
                                run = client.runs.create(
                                    thread_id=thread_id, 
                                    agent_id=self.agent.id,
                                    tool_resources=self._mcp_tool_resources,
                                    max_prompt_tokens=25000,
                                    truncation_strategy={"type": "last_messages", "last_messages": 3}
                                )
                            else:
                                run = client.runs.create(
                                    thread_id=thread_id, 
                                    agent_id=self.agent.id,
                                    max_prompt_tokens=25000,
                                    truncation_strategy={"type": "last_messages", "last_messages": 3}
                                )
                            logger.info(f"   New run created: {run.id}")
                            iterations = 0
                            continue
                        else:
                            yield f"❌ Rate limit exceeded after {max_retries} retries - please wait and try again later"
                            return
                
                yield f"Run Failed: {run.last_error}"
                return

        if hasattr(run, 'usage') and run.usage:
            self.last_token_usage = {
                "prompt_tokens": getattr(run.usage, 'prompt_tokens', 0),
                "completion_tokens": getattr(run.usage, 'completion_tokens', 0),
                "total_tokens": getattr(run.usage, 'total_tokens', 0)
            }
            logger.info(f"Token usage: {self.last_token_usage}")

        messages = list(client.messages.list(thread_id=thread_id, order=ListSortOrder.DESCENDING, limit=5))
        
        if messages:
            latest = messages[0]
            if hasattr(latest, 'content'):
                for content_item in latest.content:
                    if hasattr(content_item, 'text') and hasattr(content_item.text, 'value'):
                        response_text = content_item.text.value
                        yield response_text
                        return
        
        yield "No response generated."
    
    def get_agent_card(self) -> Dict[str, Any]:
        return {
            "name": "HubSpot CRM Agent",
            "description": "AI agent for HubSpot CRM operations - manage contacts, companies, deals, and more",
            "url": f"http://localhost:{os.getenv('A2A_PORT', '8021')}",
            "version": "1.0.0",
            "capabilities": {
                "streaming": True,
                "pushNotifications": False,
                "stateTransitionHistory": False
            },
            "defaultInputModes": ["text"],
            "defaultOutputModes": ["text"],
            "skills": [
                {
                    "id": "hubspot_contacts",
                    "name": "Contact Management",
                    "description": "List, search, create, and update HubSpot contacts",
                    "tags": ["crm", "contacts", "hubspot"]
                },
                {
                    "id": "hubspot_companies", 
                    "name": "Company Management",
                    "description": "List, search, create, and update HubSpot companies",
                    "tags": ["crm", "companies", "hubspot"]
                },
                {
                    "id": "hubspot_deals",
                    "name": "Deal Management", 
                    "description": "List, search, create, and update HubSpot deals",
                    "tags": ["crm", "deals", "hubspot"]
                }
            ]
        }
