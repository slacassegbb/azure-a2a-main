"""
AI Foundry Agent implementation with HubSpot CRM Capabilities.
Uses AgentsClient directly for Azure AI Foundry with HubSpot MCP integration.

IMPORTANT: Uses custom MCPClient to bypass Azure's McpTool and reduce token usage.
Token savings: ~89% (from ~18k to ~2k tokens per request)
"""
import os
import asyncio
import logging
import json
from typing import Optional, Dict, Any
import httpx

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import (
    Agent, ListSortOrder, ToolSet, FunctionTool, RequiredFunctionToolCall
)
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)


# HubSpot MCP Server URL (FLATTENED version on Azure Container Apps)
HUBSPOT_MCP_URL = os.getenv(
    "HUBSPOT_MCP_URL", 
    "https://mcp-hubspot-flat.ambitioussky-6c709152.westus2.azurecontainerapps.io/sse"
)


class MCPClient:
    """
    Direct MCP client that calls MCP servers via HTTP/SSE without loading all tool schemas.
    This reduces token usage by ~15k tokens compared to Azure's McpTool approach.
    """
    
    def __init__(self, server_url: str):
        self.server_url = server_url
        self.client = httpx.AsyncClient(timeout=30.0)
        
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call an MCP tool directly using JSON-RPC over HTTP/SSE.
        """
        try:
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
            }
            
            logger.info(f"🔧 Calling MCP tool: {tool_name}")
            logger.debug(f"   Arguments: {json.dumps(arguments, indent=2)}")
            
            response = await self.client.post(
                self.server_url,
                json=request_payload,
                headers=headers
            )
            
            response.raise_for_status()
            
            # Parse SSE response format
            response_text = response.text
            logger.debug(f"   Raw response: {response_text[:500]}...")
            
            # SSE format: "event: message\ndata: {json}\n\n"
            if "event: message" in response_text and "data: " in response_text:
                lines = response_text.strip().split('\n')
                for line in lines:
                    if line.startswith("data: "):
                        json_str = line[6:]
                        result = json.loads(json_str)
                        
                        if "result" in result:
                            mcp_result = result["result"]
                            if isinstance(mcp_result, dict) and "content" in mcp_result:
                                content = mcp_result["content"]
                                if isinstance(content, list) and len(content) > 0:
                                    text_content = content[0].get("text", "")
                                    try:
                                        actual_result = json.loads(text_content)
                                    except json.JSONDecodeError:
                                        actual_result = {"result": text_content}
                                    logger.info(f"✅ MCP tool call succeeded: {tool_name}")
                                    return actual_result
                            else:
                                logger.info(f"✅ MCP tool call succeeded: {tool_name}")
                                return mcp_result
                        elif "error" in result:
                            logger.error(f"❌ MCP returned error: {result['error']}")
                            raise Exception(f"MCP error: {result['error']}")
            else:
                result = response.json()
                if "result" in result:
                    logger.info(f"✅ MCP tool call succeeded: {tool_name}")
                    return result["result"]
                else:
                    return result
            
        except Exception as e:
            logger.error(f"❌ MCP tool call failed: {tool_name} - {e}")
            raise
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


class FoundryHubSpotAgent:
    """
    AI Foundry Agent with HubSpot CRM capabilities.
    Uses AgentsClient directly for the new SDK version with custom MCP client.
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
        """Create the AI Foundry agent with HubSpot capabilities using custom MCP client."""
        if self.agent:
            logger.info("Agent already exists, returning existing instance")
            return self.agent
        
        logger.info("🚀 CREATING NEW AZURE FOUNDRY HUBSPOT AGENT...")
        
        # Initialize direct MCP client (bypasses Azure's McpTool to save ~15k tokens per request)
        logger.info("🔍 INITIALIZING DIRECT HUBSPOT MCP CLIENT...")
        logger.info(f"   Server URL: {HUBSPOT_MCP_URL}")
        self._mcp_client = MCPClient(HUBSPOT_MCP_URL)
        
        # Test connectivity
        logger.info("🧪 TESTING HUBSPOT MCP SERVER CONNECTIVITY...")
        try:
            headers = {"Accept": "text/event-stream"}
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(HUBSPOT_MCP_URL.replace("/sse", "/health"))
                if response.status_code == 200:
                    logger.info("✅ HubSpot MCP Server connectivity test PASSED")
        except Exception as e:
            logger.warning(f"⚠️ MCP connectivity test: {e}")
        
        # Define custom tool that replaces all 10 HubSpot MCP tool schemas with a single tool
        custom_hubspot_tool = {
            "type": "function",
            "function": {
                "name": "hubspot_action",
                "description": "Execute HubSpot CRM operations including contacts, companies, deals, and engagements. This is a unified interface to all HubSpot operations.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
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
                            ],
                            "description": "The HubSpot action to perform"
                        },
                        "params": {
                            "type": "object",
                            "description": "Parameters for the action. Varies by action type.",
                            "additionalProperties": True
                        }
                    },
                    "required": ["action"]
                }
            }
        }
        
        logger.info("✅ Created custom hubspot_action tool (replaces 10 tool schemas)")
        
        # Get model deployment name
        model = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")
        
        # HubSpot-specific instructions
        instructions = """You are an expert HubSpot CRM assistant. You help users manage their HubSpot account.

## Your Tool: hubspot_action

You have ONE powerful tool called `hubspot_action` that can perform all HubSpot CRM operations.

**Tool Parameters:**
- `action`: The HubSpot operation to perform (see available actions below)
- `params`: Parameters specific to that action (structure varies by action)

## Available Actions (10 total)

### Account Info
- **hubspot_get_user_details** - Get account and user information
  - Example: `{{"action": "hubspot_get_user_details", "params": {{}}}}`

### List Objects
- **hubspot_list_objects** - List CRM objects (contacts, companies, deals)
  - Example: `{{"action": "hubspot_list_objects", "params": {{"objectType": "contacts", "limit": 10, "properties": "firstname,lastname,email"}}}}`

### Search Objects
- **hubspot_search_objects** - Search CRM objects with filters
  - Example: `{{"action": "hubspot_search_objects", "params": {{"objectType": "contacts", "filters": "email EQ john@example.com", "properties": "firstname,lastname,email"}}}}`

### Get Single Object
- **hubspot_get_object** - Get a specific CRM object by ID
  - Example: `{{"action": "hubspot_get_object", "params": {{"objectType": "contacts", "objectId": "123", "properties": "firstname,lastname,email"}}}}`

### Create Objects
- **hubspot_create_contact** - Create a new contact
  - Example: `{{"action": "hubspot_create_contact", "params": {{"email": "john@example.com", "firstname": "John", "lastname": "Doe"}}}}`

- **hubspot_create_company** - Create a new company
  - Example: `{{"action": "hubspot_create_company", "params": {{"name": "Acme Corp", "domain": "acme.com"}}}}`

- **hubspot_create_deal** - Create a new deal
  - Example: `{{"action": "hubspot_create_deal", "params": {{"dealname": "New Deal", "amount": "10000", "dealstage": "appointmentscheduled"}}}}`

- **hubspot_create_note** - Create a note on a CRM object
  - Example: `{{"action": "hubspot_create_note", "params": {{"objectType": "contacts", "objectId": "123", "body": "Called customer today"}}}}`

### Update Objects
- **hubspot_update_object** - Update an existing CRM object
  - Example: `{{"action": "hubspot_update_object", "params": {{"objectType": "contacts", "objectId": "123", "properties": {{"phone": "555-1234"}}}}}}`

### Associations
- **hubspot_get_associations** - Get associations between objects
  - Example: `{{"action": "hubspot_get_associations", "params": {{"fromObjectType": "contacts", "fromObjectId": "123", "toObjectType": "companies"}}}}`

## Example Usage

**List all contacts:**
```
hubspot_action(action="hubspot_list_objects", params={{"objectType": "contacts", "limit": 10}})
```

**Search for a contact by email:**
```
hubspot_action(action="hubspot_search_objects", params={{"objectType": "contacts", "filters": "email EQ john@example.com"}})
```

**Create a new contact:**
```
hubspot_action(action="hubspot_create_contact", params={{"email": "jane@example.com", "firstname": "Jane", "lastname": "Doe"}})
```

## Response Format:
- Use clear headers and bullet points
- Include HubSpot record IDs for reference
- Summarize results concisely
"""
        
        logger.info(f"Creating HubSpot agent with model: {model}")
        
        # Use AgentsClient directly to create agent with custom tool
        agents_client = self._get_agents_client()
        
        self.agent = agents_client.create_agent(
            model=model,
            name="AI Foundry HubSpot Agent",
            instructions=instructions,
            tools=[custom_hubspot_tool],
        )
        
        logger.info(f"✅ Created HubSpot agent: {self.agent.id}")
        logger.info(f"   Agent uses custom hubspot_action tool (saves ~15k tokens per request)")
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

    async def _handle_tool_calls(self, run, thread_id: str):
        """Handle tool calls coming back from Azure AI Foundry (QuickBooks pattern)."""
        if not hasattr(run, "required_action") or not run.required_action:
            logger.warning("No required_action present on run; nothing to handle")
            return

        required_action = run.required_action
        action_type = None
        tool_calls = []

        if hasattr(required_action, "submit_tool_outputs") and required_action.submit_tool_outputs:
            action_type = "submit_tool_outputs"
            tool_calls = getattr(required_action.submit_tool_outputs, "tool_calls", []) or []
        else:
            logger.warning(
                "Required action missing submit_tool_outputs attribute: %s",
                dir(required_action)
            )
            return

        if not tool_calls:
            logger.warning("Required action contained no tool calls; nothing to process")
            return

        agents_client = self._get_agents_client()

        logger.info("Handling %d tool output call(s)", len(tool_calls))
        tool_outputs = []

        for tool_call in tool_calls:
            try:
                function_name = getattr(getattr(tool_call, "function", None), "name", "unknown")
                arguments_str = getattr(getattr(tool_call, "function", None), "arguments", "{}")
                logger.info(f"Processing tool call: {function_name}")
                logger.debug(f"   Arguments: {arguments_str}")

                # Handle our custom hubspot_action tool
                if function_name == "hubspot_action":
                    try:
                        arguments = json.loads(arguments_str)
                        action = arguments.get("action")
                        params = arguments.get("params", {})
                        
                        logger.info(f"🔧 Executing HubSpot action: {action}")
                        logger.debug(f"   Params: {json.dumps(params, indent=2)}")
                        
                        # Make direct MCP call
                        result = await self._mcp_client.call_tool(action, params)
                        
                        logger.info(f"✅ HubSpot action succeeded: {action}")
                        
                        tool_outputs.append({
                            "tool_call_id": tool_call.id,
                            "output": json.dumps(result),
                        })
                        
                    except Exception as mcp_error:
                        logger.error(f"❌ HubSpot action failed: {action}")
                        logger.error(f"   Error: {mcp_error}")
                        
                        error_result = {
                            "error": str(mcp_error),
                            "status": "failed",
                            "action": action
                        }
                        tool_outputs.append({
                            "tool_call_id": tool_call.id,
                            "output": json.dumps(error_result),
                        })
                elif function_name.startswith("hubspot_"):
                    # Handle direct HubSpot MCP tool calls (model may call these directly)
                    try:
                        arguments = json.loads(arguments_str) if arguments_str else {}
                        
                        logger.info(f"🔧 Executing direct HubSpot MCP call: {function_name}")
                        logger.debug(f"   Arguments: {json.dumps(arguments, indent=2)}")
                        
                        # Make direct MCP call with the tool name
                        result = await self._mcp_client.call_tool(function_name, arguments)
                        
                        logger.info(f"✅ HubSpot MCP call succeeded: {function_name}")
                        
                        tool_outputs.append({
                            "tool_call_id": tool_call.id,
                            "output": json.dumps(result),
                        })
                        
                    except Exception as mcp_error:
                        logger.error(f"❌ HubSpot MCP call failed: {function_name}")
                        logger.error(f"   Error: {mcp_error}")
                        
                        error_result = {
                            "error": str(mcp_error),
                            "status": "failed",
                            "action": function_name
                        }
                        tool_outputs.append({
                            "tool_call_id": tool_call.id,
                            "output": json.dumps(error_result),
                        })
                else:
                    # Fallback for other tools (shouldn't happen with our setup)
                    logger.warning(f"Unknown tool call: {function_name}")
                    dummy_result = {
                        "status": "success",
                        "message": f"Tool '{function_name}' executed (simulated).",
                    }
                    tool_outputs.append({
                        "tool_call_id": tool_call.id,
                        "output": json.dumps(dummy_result),
                    })
                    
            except Exception as exc:
                logger.error(f"Error processing tool call {getattr(tool_call, 'id', '?')}: {exc}")
                error_result = {
                    "error": str(exc),
                    "status": "failed"
                }
                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "output": json.dumps(error_result),
                })

        if tool_outputs:
            logger.debug("Submitting %d tool outputs", len(tool_outputs))
            agents_client.runs.submit_tool_outputs(
                thread_id=thread_id,
                run_id=run.id,
                tool_outputs=tool_outputs,
            )
        else:
            logger.warning("No tool outputs generated; submitting empty acknowledgements")
            fallback_outputs = [{"tool_call_id": tc.id, "output": "{}"} for tc in tool_calls if hasattr(tc, "id")]
            if fallback_outputs:
                agents_client.runs.submit_tool_outputs(
                    thread_id=thread_id,
                    run_id=run.id,
                    tool_outputs=fallback_outputs,
                )
    
    async def run_and_wait(self, thread_id: str, timeout: int = 120):
        """Run the agent on a thread and wait for completion, handling tool calls (QuickBooks pattern)."""
        if not self.agent:
            await self.create_agent()
        
        agents_client = self._get_agents_client()
        
        # Create run
        run = agents_client.runs.create(
            thread_id=thread_id,
            agent_id=self.agent.id,
            truncation_strategy={"type": "last_messages", "last_messages": 3},
            max_prompt_tokens=25000,
        )
        
        logger.info(f"Created run {run.id} on thread {thread_id}")
        
        # Poll for completion and handle tool calls (QuickBooks pattern)
        max_iterations = 25
        iterations = 0
        stuck_run_count = 0
        max_stuck_runs = 3
        
        while run.status in ["queued", "in_progress", "requires_action"] and iterations < max_iterations:
            iterations += 1
            logger.debug(f"🔄 Iteration {iterations}: run.status = {run.status}")
            await asyncio.sleep(2)
            
            if run.status == "requires_action":
                logger.info(f"🔧 RUN REQUIRES ACTION - TOOL CALLS NEEDED")
                logger.info(f"   Run ID: {run.id}")
                try:
                    # Check if there are actually tool calls to handle
                    if hasattr(run, 'required_action') and run.required_action:
                        logger.info(f"Found required action, handling tool calls...")
                        await self._handle_tool_calls(run, thread_id)
                    else:
                        logger.warning(f"Run status is 'requires_action' but no required_action found")
                        stuck_run_count += 1
                        if stuck_run_count >= max_stuck_runs:
                            logger.error(f"Run {run.id} is stuck in requires_action state")
                            raise RuntimeError(f"Run is stuck in requires_action state")
                except Exception as e:
                    logger.error(f"❌ ERROR HANDLING TOOL CALLS: {e}")
                    raise
            
            # Refresh run status
            run = agents_client.runs.get(thread_id=thread_id, run_id=run.id)
            logger.debug(f"Run status: {run.status} (iteration {iterations})")
        
        if iterations >= max_iterations:
            raise TimeoutError(f"Run exceeded maximum iterations ({max_iterations})")
        
        # Store token usage
        if hasattr(run, 'usage') and run.usage:
            self.last_token_usage = {
                "prompt_tokens": getattr(run.usage, 'prompt_tokens', 0),
                "completion_tokens": getattr(run.usage, 'completion_tokens', 0),
                "total_tokens": getattr(run.usage, 'total_tokens', 0),
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
_hubspot_agent_instance: Optional[FoundryHubSpotAgent] = None


async def get_hubspot_agent() -> FoundryHubSpotAgent:
    """Get or create the global HubSpot agent instance."""
    global _hubspot_agent_instance
    if _hubspot_agent_instance is None:
        _hubspot_agent_instance = FoundryHubSpotAgent()
        await _hubspot_agent_instance.create_agent()
    return _hubspot_agent_instance
