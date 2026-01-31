"""
AI Foundry Agent implementation with QuickBooks Online Accounting Capabilities.
Adapted from the ADK agent pattern to work with Azure AI Foundry.

IMPORTANT: QUOTA REQUIREMENTS FOR AZURE AI FOUNDRY AGENTS
=========================================================

Based on Microsoft support documentation and user reports, Azure AI Foundry agents
require a MINIMUM of 20,000 TPM (Tokens Per Minute) to function properly without
rate limiting issues.

If you're experiencing "Rate limit exceeded" errors with normal usage:

1. Check your current TPM quota in Azure AI Foundry portal:
   - Go to Management > Quota
   - Look for your model deployment TPM allocation

2. If your TPM is below 20,000, request a quota increase:
   - In Azure portal, create a support request
   - Select "Service and subscription limits (quotas)" as Issue type
   - Select "Cognitive Services" as Quota type
   - Request at least 20,000 TPM for your model
   - Specify you need it for Azure AI Foundry agents with Bing Search

3. Consider using different regions:
   - Some regions have higher default quotas
   - US West 3 with Global Standard deployment type often works
   - Try gpt-4o instead of gpt-4 if available

4. Alternative deployment types:
   - Global Standard deployments often have higher limits
   - Data Zone deployments may have different quota availability

Common symptoms when TPM is too low:
- Rate limit errors on the first or second request
- "Try again in X seconds" even with minimal usage
- Agents failing during file search setup or Bing search operations

Reference: https://learn.microsoft.com/en-us/answers/questions/2237624/getting-rate-limit-exceeded-when-testing-ai-agent
"""
import os
import datetime
import asyncio
import logging
import json
from typing import Optional, Dict, List, Any

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import Agent, ThreadMessage, ThreadRun, AgentThread, BingGroundingTool, ListSortOrder, FilePurpose, FileSearchTool, McpTool, ToolApproval, ToolSet
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
import glob
import re

logger = logging.getLogger(__name__)


class FoundryQuickBooksAgent:
    """
    AI Foundry Agent with QuickBooks Online accounting capabilities.
    This class adapts the ADK agent pattern for Azure AI Foundry with QuickBooks MCP integration.
    
    QUOTA REQUIREMENTS: Ensure your model deployment has at least 20,000 TPM
    allocated to avoid rate limiting issues with Azure AI Foundry agents.
    """
    
    # Class-level shared resources for file search (created once)
    _shared_vector_store = None
    _shared_uploaded_files = []
    _shared_file_search_tool = None
    _file_search_setup_lock = asyncio.Lock()
    
    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self.agent: Optional[Agent] = None
        self.threads: Dict[str, str] = {}  # thread_id -> thread_id mapping
        self._file_search_tool = None  # Cache the file search tool
        self._agents_client = None  # Cache the agents client
        self._project_client = None  # Cache the project client
        self._mcp_tool = None  # Cache the MCP tool for header access during approvals
        self._mcp_tool_resources = None  # Cache MCP tool resources for run creation
        self.last_token_usage: Optional[Dict[str, int]] = None  # Store token usage from last run
        
    def _get_client(self) -> AgentsClient:
        """Get a cached AgentsClient instance to reduce API calls."""
        if self._agents_client is None:
            self._agents_client = AgentsClient(
                endpoint=self.endpoint,
                credential=self.credential,
            )
        return self._agents_client
        
    def _get_project_client(self) -> AIProjectClient:
        """Get a cached AIProjectClient instance to reduce API calls."""
        if self._project_client is None:
            self._project_client = AIProjectClient(
                endpoint=self.endpoint,
                credential=self.credential,
            )
        return self._project_client
    
    async def _setup_file_search(self, files_directory: str = "documents") -> Optional[FileSearchTool]:
        """Upload files from local directory and create vector store for file search - ONCE per class."""
        async with FoundryQuickBooksAgent._file_search_setup_lock:
            # If we already have a shared file search tool, return it
            if FoundryQuickBooksAgent._shared_file_search_tool is not None:
                logger.info("Reusing existing shared file search tool")
                return FoundryQuickBooksAgent._shared_file_search_tool
            
            try:
                # Check if files directory exists
                if not os.path.exists(files_directory):
                    logger.info(f"No {files_directory} directory found, skipping file search setup")
                    return None
                
                # Find all supported files in the directory
                supported_extensions = ['*.txt', '*.md', '*.pdf', '*.docx', '*.json', '*.csv']
                file_paths = set()  # Use set to avoid duplicates
                for ext in supported_extensions:
                    file_paths.update(glob.glob(os.path.join(files_directory, ext)))
                    file_paths.update(glob.glob(os.path.join(files_directory, "**", ext), recursive=True))
                
                file_paths = list(file_paths)  # Convert back to list
                
                if not file_paths:
                    logger.info(f"No supported files found in {files_directory}, skipping file search setup")
                    return None
                
                logger.info(f"Found {len(file_paths)} files to upload: {[os.path.basename(f) for f in file_paths]}")
                
                # Upload files ONCE
                file_ids = []
                project_client = self._get_project_client()
                for file_path in file_paths:
                    try:
                        logger.info(f"Uploading file: {os.path.basename(file_path)}")
                        file = project_client.agents.files.upload_and_poll(
                            file_path=file_path, 
                            purpose=FilePurpose.AGENTS
                        )
                        file_ids.append(file.id)
                        FoundryQuickBooksAgent._shared_uploaded_files.append(file.id)
                        logger.info(f"Uploaded file: {os.path.basename(file_path)} (ID: {file.id})")
                    except Exception as e:
                        logger.warning(f"Failed to upload {file_path}: {e}")
                
                if not file_ids:
                    logger.warning("No files were successfully uploaded")
                    return None
                
                # Create vector store ONCE using project client
                logger.info("Creating shared vector store with uploaded files...")
                FoundryQuickBooksAgent._shared_vector_store = project_client.agents.vector_stores.create_and_poll(
                    file_ids=file_ids, 
                    name="shared_vectorstore"
                )
                logger.info(f"Created shared vector store: {FoundryQuickBooksAgent._shared_vector_store.id}")
                
                # Create file search tool ONCE
                file_search = FileSearchTool(vector_store_ids=[FoundryQuickBooksAgent._shared_vector_store.id])
                logger.info(f"File search capability prepared, type: {type(file_search)}")
                logger.debug(f"FileSearchTool object: {file_search}")
                
                # Verify the object has the expected attributes
                if not hasattr(file_search, 'definitions'):
                    logger.error(f"FileSearchTool missing 'definitions' attribute. Object: {file_search}")
                    return None
                if not hasattr(file_search, 'resources'):
                    logger.error(f"FileSearchTool missing 'resources' attribute. Object: {file_search}")
                    return None
                
                # Cache the shared file search tool
                FoundryQuickBooksAgent._shared_file_search_tool = file_search
                logger.info("Cached shared file search tool for future use")
                    
                return file_search
                    
            except Exception as e:
                logger.error(f"Error setting up file search: {e}")
                return None
        
    async def create_agent(self) -> Agent:
        """Create the AI Foundry agent with QuickBooks MCP, web search, and file search capabilities."""
        if self.agent:
            logger.info("Agent already exists, returning existing instance")
            return self.agent
        
        logger.info("🚀 CREATING NEW AZURE FOUNDRY AGENT...")
        
        # Start with MCP tools using the new McpTool class - FIXED FOR AZURE FOUNDRY
        logger.info("🔍 CREATING MCP TOOL CONNECTION...")
        logger.info(f"   Server URL: https://b216cb9d1f7a.ngrok-free.app/sse")
        logger.info(f"   Server Label: QuickBooks")
        
        try:
            # Test MCP server connectivity first
            logger.info("🧪 TESTING MCP SERVER CONNECTIVITY...")
            import httpx
            import asyncio
            
            async def test_mcp_basic():
                try:
                    # Test SSE endpoint properly - don't try to read the full response
                    # Include ngrok-skip-browser-warning header to avoid ngrok interstitial page
                    headers = {
                        "ngrok-skip-browser-warning": "true",
                        "Accept": "text/event-stream"
                    }
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        async with client.stream("GET", "https://b216cb9d1f7a.ngrok-free.app/sse", headers=headers) as response:
                            logger.info(f"   MCP Server Response: {response.status_code}")
                            logger.info(f"   Response Headers: {dict(response.headers)}")
                            
                            # For SSE endpoints, just check status and headers
                            if response.status_code == 200:
                                # Check if it looks like an SSE endpoint
                                content_type = response.headers.get('content-type', '')
                                if 'text/event-stream' in content_type or 'text/plain' in content_type:
                                    logger.info("✅ MCP Server connectivity test PASSED (SSE endpoint detected)")
                                    return True
                                else:
                                    # Try to read a small amount of content to verify it's working
                                    try:
                                        content_chunk = ""
                                        async for chunk in response.aiter_text():
                                            content_chunk += chunk
                                            if len(content_chunk) > 100:  # Just read first 100 chars
                                                break
                                        logger.info(f"   Response Content (first 100 chars): {content_chunk[:100]}")
                                        logger.info("✅ MCP Server connectivity test PASSED")
                                        return True
                                    except asyncio.TimeoutError:
                                        # This is expected for SSE endpoints
                                        logger.info("✅ MCP Server connectivity test PASSED (SSE stream detected)")
                                        return True
                            else:
                                logger.error(f"❌ MCP Server returned status: {response.status_code}")
                                return False
                            
                except asyncio.TimeoutError:
                    # For SSE endpoints, timeout during streaming is actually success
                    logger.info("✅ MCP Server connectivity test PASSED (SSE stream timeout - expected)")
                    return True
                except Exception as e:
                    logger.error(f"   MCP Server Test FAILED: {e}")
                    logger.error(f"   Error type: {type(e)}")
                    import traceback
                    logger.error(f"   Full traceback: {traceback.format_exc()}")
                    return False
            
            # Run the connectivity test
            await test_mcp_basic()
            
            # Create MCP tool - ALL 15 tools work with simplified flat schemas!
            logger.info("🔧 CREATING McpTool OBJECT...")
            # QuickBooks MCP server via ngrok
            self._mcp_server_url = "https://b216cb9d1f7a.ngrok-free.app/sse"
            logger.info(f"🔧 Using MCP server URL: {self._mcp_server_url}")
            mcp_tool = McpTool(
                server_label="QuickBooks",
                server_url=self._mcp_server_url,
                # ALL 15 QuickBooks tools with simplified flat schemas
                allowed_tools=[
                    # Query & Reports
                    "qbo_query",            # SQL-like queries (SELECT * FROM Customer)
                    "qbo_report",           # Financial reports (ProfitAndLoss, BalanceSheet, CashFlow)
                    "qbo_company_info",     # Get company information
                    # Customer Tools
                    "qbo_search_customers", # Search customers (filter by displayName, active, limit)
                    "qbo_get_customer",     # Get customer by ID
                    "qbo_create_customer",  # Create customer (displayName, email, phone, companyName)
                    "qbo_update_customer",  # Update customer
                    "qbo_delete_customer",  # Deactivate customer
                    # Invoice Tools
                    "qbo_search_invoices",  # Search invoices (filter by customerId, docNumber, limit)
                    "qbo_get_invoice",      # Get invoice by ID
                    "qbo_create_invoice",   # Create invoice (customerId, lineItems, dueDate)
                    # Other Entity Tools
                    "qbo_search_accounts",  # Search chart of accounts
                    "qbo_search_items",     # Search products/services
                    "qbo_search_vendors",   # Search vendors/suppliers
                    "qbo_search_bills"      # Search bills/payables
                ]
            )
            # Store the mcp_tool so we can access headers during tool approvals
            self._mcp_tool = mcp_tool
            logger.info("✅ McpTool object created successfully")

            mcp_tool.set_approval_mode("never")  # Disable approval requirement
            logger.info("✅ Set approval mode to 'never'")
            
            # Set headers using the official method from Microsoft documentation
            # CRITICAL: ngrok-skip-browser-warning is required for ngrok to work with Azure
            # CRITICAL: Accept must include BOTH application/json and text/event-stream for Streamable HTTP
            mcp_tool.update_headers("Content-Type", "application/json")
            mcp_tool.update_headers("User-Agent", "Azure-AI-Foundry-Agent")
            mcp_tool.update_headers("ngrok-skip-browser-warning", "true")
            mcp_tool.update_headers("Accept", "application/json, text/event-stream")
            logger.info("✅ Set MCP headers using update_headers method (including ngrok-skip-browser-warning)")
            
            # Log the headers that will be used
            if hasattr(mcp_tool, 'headers'):
                logger.info(f"✅ MCP headers stored: {mcp_tool.headers}")
            
            # Use ToolSet as recommended by Microsoft sample
            toolset = ToolSet()
            toolset.add(mcp_tool)
            self._toolset = toolset  # Store for use with create_and_process
            self._mcp_tool = mcp_tool  # Store MCP tool reference
            
            # Also keep definitions for compatibility
            tools = mcp_tool.definitions
            
            # CRITICAL FIX: Store MCP tool resources - needed for runs.create() per Microsoft docs!
            # The mcp_tool.resources contains the server connection info needed at runtime
            self._mcp_tool_resources = mcp_tool.resources
            tool_resources = None  # For agent creation, but we'll use _mcp_tool_resources for run creation
            
            logger.info(f"🔍 MCP TOOL DETAILS:")
            logger.info(f"   Tools count: {len(tools) if tools else 0}")
            logger.info(f"   Tool definitions: {[str(t) for t in tools[:3]] if tools else 'None'}")
            logger.info(f"   MCP Tool resources (for run creation): {self._mcp_tool_resources}")
            logger.info(f"   MCP Tool resources type: {type(self._mcp_tool_resources)}")
            logger.info("🔧 CRITICAL: mcp_tool.resources will be passed to runs.create()")
            
            logger.info("✅ Added QuickBooks MCP server integration using McpTool")
            
        except Exception as e:
            logger.error(f"❌ FAILED TO CREATE MCP TOOL: {e}")
            logger.error(f"   Error type: {type(e)}")
            import traceback
            logger.error(f"   Full traceback: {traceback.format_exc()}")
            
            # Fallback: create empty tools list if MCP fails
            tools = []
            tool_resources = None
            logger.warning("⚠️ Continuing without MCP tools due to connection failure")
        
        # Using QuickBooks MCP tools only - no local simulation tools needed
        logger.info("🔧 Using QuickBooks MCP tools from remote server")
        
        project_client = self._get_project_client()
        
        # Add Bing search tool if available
        try:
            bing_connection = project_client.connections.get(name="agentbing")
            bing = BingGroundingTool(connection_id=bing_connection.id)
            tools.extend(bing.definitions)
            logger.info("Added Bing search capability")
        except Exception as e:
            logger.warning(f"Could not add Bing search: {e}")
            logger.info("Agent will work without web search capabilities")
        
        # Add file search tool if files are available
        if self._file_search_tool is None:
            self._file_search_tool = await self._setup_file_search()
        
        if self._file_search_tool:
            logger.info(f"Using file search tool, type: {type(self._file_search_tool)}")
            
            if hasattr(self._file_search_tool, 'definitions'):
                tools.extend(self._file_search_tool.definitions)
                logger.info("Extended tools with file search definitions")
            
            if hasattr(self._file_search_tool, 'resources'):
                # Use file search resources for agent creation
                tool_resources = self._file_search_tool.resources
                logger.info("Using file search tool resources for agent creation")
                
            logger.info("Added file search capability")
        
        # Use context manager and create agent with ToolSet (Microsoft recommended approach)
        with project_client:
            # Use toolset approach for MCP as per Microsoft sample
            if hasattr(self, '_toolset') and self._toolset:
                logger.info("🔧 Creating agent with ToolSet (Microsoft recommended for MCP)")
                self.agent = project_client.agents.create_agent(
                    model="gpt-4o",
                    name="foundry-QB-agent",
                    instructions=self._get_agent_instructions(),
                    toolset=self._toolset
                )
            elif tool_resources:
                self.agent = project_client.agents.create_agent(
                    model="gpt-4o",
                    name="foundry-QB-agent",
                    instructions=self._get_agent_instructions(),
                    tools=tools,
                    tool_resources=tool_resources
                )
            else:
                self.agent = project_client.agents.create_agent(
                    model="gpt-4o",
                    name="foundry-QB-agent",
                    instructions=self._get_agent_instructions(),
                    tools=tools
                )
        
        logger.info(f"Created AI Foundry agent: {self.agent.id}")
        
        # Debug: Log what Azure stored for the agent
        logger.warning(f"🔍 AGENT DEBUG INFO:")
        logger.warning(f"   Agent ID: {self.agent.id}")
        logger.warning(f"   Agent name: {getattr(self.agent, 'name', 'N/A')}")
        logger.warning(f"   Agent model: {getattr(self.agent, 'model', 'N/A')}")
        if hasattr(self.agent, 'tools'):
            logger.warning(f"   Agent tools count: {len(self.agent.tools) if self.agent.tools else 0}")
            for i, tool in enumerate(self.agent.tools or []):
                tool_type = getattr(tool, 'type', 'unknown')
                logger.warning(f"   Tool {i+1}: type={tool_type}")
                if tool_type == 'mcp':
                    logger.warning(f"      server_label: {getattr(tool, 'server_label', 'N/A')}")
                    logger.warning(f"      server_url: {getattr(tool, 'server_url', 'N/A')}")
                    logger.warning(f"      allowed_tools: {getattr(tool, 'allowed_tools', 'N/A')}")
        return self.agent
    
    def _get_agent_instructions(self) -> str:
        """Get the agent instructions for QuickBooks Online accounting capabilities."""
        return f"""
You are a QuickBooks Online accounting assistant powered by Azure AI Foundry.

## Your Available Tools (15 total)

### Query & Reports
- **qbo_query** - Run SQL-like queries (e.g., SELECT * FROM Customer WHERE Balance > 0)
- **qbo_report** - Generate financial reports (ProfitAndLoss, BalanceSheet, CashFlow, CustomerSales)
- **qbo_company_info** - Get company information

### Customer Tools
- **qbo_search_customers** - Search customers (filter by displayName, active, limit)
- **qbo_get_customer** - Get customer details by ID
- **qbo_create_customer** - Create new customer (displayName, email, phone, companyName)
- **qbo_update_customer** - Update existing customer
- **qbo_delete_customer** - Deactivate customer

### Invoice Tools
- **qbo_search_invoices** - Search invoices (filter by customerId, docNumber, limit)
- **qbo_get_invoice** - Get invoice details by ID
- **qbo_create_invoice** - Create invoice (customerId, lineItems, dueDate)

### Other Entity Tools
- **qbo_search_accounts** - Search chart of accounts
- **qbo_search_items** - Search products/services
- **qbo_search_vendors** - Search vendors/suppliers
- **qbo_search_bills** - Search bills/payables

## Example Queries
- "Show all customers with outstanding balances" → use qbo_query: SELECT * FROM Customer WHERE Balance > 0
- "Create a new customer ABC Corp" → use qbo_create_customer
- "Find all unpaid invoices" → use qbo_search_invoices or qbo_query: SELECT * FROM Invoice WHERE Balance > 0
- "Run a profit and loss report" → use qbo_report with type ProfitAndLoss

Current date: {datetime.datetime.now().isoformat()}
"""
    
    async def create_thread(self, thread_id: Optional[str] = None) -> AgentThread:
        """Create or retrieve a conversation thread."""
        client = self._get_client()
        # Reuse existing thread if caller provides an id
        if thread_id:
            try:
                thread = client.threads.get(thread_id)
                # Cache and return existing thread
                self.threads[thread.id] = thread.id
                logger.info(f"Reusing existing thread: {thread.id}")
                return thread
            except Exception:
                # If the provided id is not found, create a new one
                logger.info(f"Provided thread_id not found. Creating a new thread.")
        # Default: create a new thread
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
    
    async def run_conversation_stream(self, thread_id: str, user_message: str):
        """Async generator: yields progress/tool call messages and final assistant response(s) in real time."""
        logger.info(f"🚀 STARTING CONVERSATION STREAM")
        logger.info(f"   Thread ID: {thread_id}")
        logger.info(f"   User message: {user_message[:100]}{'...' if len(user_message) > 100 else ''}")
        
        if not self.agent:
            logger.info("   Agent not found, creating new agent...")
            await self.create_agent()
            logger.info(f"   Agent created: {self.agent.id}")

        # Inject a minimal system hint to bias tool choice when appropriate for QuickBooks
        try:
            import re as _re
            # Detect QuickBooks-related terms
            if _re.search(r"\b(customer|invoice|bill|vendor|payment|account|item|employee|estimate|purchase|journal)\b", user_message, flags=_re.IGNORECASE):
                hint = (
                    "SYSTEM TOOL HINT: The user is asking about QuickBooks data. "
                    "Use the appropriate qbo_* tools for customers, invoices, bills, vendors, etc. "
                    "For reports, use qbo_report. For company info, use qbo_company_info."
                )
                await self.send_message(thread_id, hint, role="system")
        except Exception:
            pass

        # Removed URL-specific, low-level tool hint to avoid hardcoding server endpoints

        await self.send_message(thread_id, user_message)
        logger.info("   User message sent to thread")
        
        client = self._get_client()
        
        # Get MCP tool resources if available
        mcp_tool = getattr(self, '_mcp_tool', None)
        
        # Create run with tool_resources for MCP (as per Microsoft sample)
        if mcp_tool and hasattr(mcp_tool, 'resources'):
            logger.info("🔧 Creating run with MCP tool_resources")
            run = client.runs.create(
                thread_id=thread_id, 
                agent_id=self.agent.id,
                tool_resources=mcp_tool.resources
            )
        else:
            logger.info("Creating run without MCP tool_resources")
            run = client.runs.create(
                thread_id=thread_id, 
                agent_id=self.agent.id
            )
        
        logger.info(f"   Run completed: {run.id}")
        logger.warning(f"   📊 Final run status: {run.status}")
        logger.warning(f"   📊 Run model: {getattr(run, 'model', 'N/A')}")
        
        # Check if run failed immediately (before the while loop)
        if run.status == "failed":
            logger.error(f"❌ RUN FAILED IMMEDIATELY ON CREATION!")
            logger.error(f"   This means Azure couldn't even start processing the request")
            logger.error(f"   Run ID: {run.id}")
            logger.error(f"   Last error: {run.last_error}")
            logger.error(f"   Full run object attributes: {dir(run)}")
            if hasattr(run, 'incomplete_details') and run.incomplete_details:
                logger.error(f"   Incomplete details: {run.incomplete_details}")
            yield f"❌ **Run Failed Immediately:** {run.last_error}"
            return

        max_iterations = 25
        iterations = 0
        retry_count = 0
        max_retries = 3
        tool_calls_yielded = set()
        stuck_run_count = 0
        max_stuck_runs = 3

        while run.status in ["queued", "in_progress", "requires_action"] and iterations < max_iterations:
            iterations += 1
            logger.warning(f"   🔄 Iteration {iterations}: run.status = {run.status}")
            await asyncio.sleep(2)
            
            # Check for new tool calls in real-time (only show what we can actually detect)
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
                                    # Show actual tool calls that we can detect
                                    tool_description = self._get_tool_description(tool_type, tool_call)
                                    yield f"🛠️ Remote agent executing: {tool_description}"
                                    tool_calls_yielded.add(tool_type)
            except Exception as e:
                # Continue if we can't get run steps yet
                pass

            try:
                run = client.runs.get(thread_id=thread_id, run_id=run.id)
            except Exception as e:
                if "rate limit" in str(e).lower() or "429" in str(e):
                    retry_count += 1
                    if retry_count <= max_retries:
                        backoff_time = min(15 * (2 ** retry_count), 45)
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
                logger.error(f"   Full run object: {run}")
                
                # Detailed error analysis
                if run.last_error:
                    logger.error(f"   🔍 LAST_ERROR DETAILS:")
                    logger.error(f"      Type: {type(run.last_error)}")
                    logger.error(f"      Attributes: {dir(run.last_error)}")
                    if hasattr(run.last_error, 'code'):
                        logger.error(f"      Error code: {run.last_error.code}")
                    if hasattr(run.last_error, 'message'):
                        logger.error(f"      Error message: {run.last_error.message}")
                    # Try to serialize the error
                    try:
                        import json
                        if hasattr(run.last_error, '__dict__'):
                            logger.error(f"      Error dict: {run.last_error.__dict__}")
                    except:
                        pass
                
                # Try to get detailed error information from run steps
                try:
                    client = self._get_client()
                    run_steps = client.run_steps.list(thread_id, run.id)
                    logger.error(f"🔍 ANALYZING RUN STEPS FOR DETAILED ERROR INFO:")
                    logger.error(f"   run_steps type: {type(run_steps)}")
                    logger.error(f"   run_steps object: {run_steps}")
                    logger.error(f"   run_steps attributes: {dir(run_steps)}")
                    logger.error(f"   Total run steps: {len(run_steps.data) if hasattr(run_steps, 'data') else 'unknown'}")
                    
                    # Try different ways to access the steps
                    steps_list = []
                    if hasattr(run_steps, 'data'):
                        steps_list = run_steps.data
                        logger.error(f"   Using run_steps.data: {len(steps_list)} steps")
                    elif hasattr(run_steps, '__iter__'):
                        steps_list = list(run_steps)
                        logger.error(f"   Using list(run_steps): {len(steps_list)} steps")
                    else:
                        logger.error(f"   Cannot iterate over run_steps")
                    
                    for i, step in enumerate(steps_list):
                        logger.error(f"   Step {i+1}:")
                        logger.error(f"     ID: {getattr(step, 'id', 'N/A')}")
                        logger.error(f"     Type: {getattr(step, 'type', 'N/A')}")
                        logger.error(f"     Status: {getattr(step, 'status', 'N/A')}")
                        logger.error(f"     Created at: {getattr(step, 'created_at', 'N/A')}")
                        
                        if hasattr(step, 'last_error') and step.last_error:
                            logger.error(f"     ❌ STEP ERROR: {step.last_error}")
                        
                        if hasattr(step, 'step_details'):
                            details = step.step_details
                            logger.error(f"     Step details type: {getattr(details, 'type', 'N/A')}")
                            
                            # Check for tool call details
                            if hasattr(details, 'tool_calls') and details.tool_calls:
                                logger.error(f"     Tool calls in this step: {len(details.tool_calls)}")
                                for j, tool_call in enumerate(details.tool_calls):
                                    logger.error(f"       Tool call {j+1}:")
                                    logger.error(f"         ID: {getattr(tool_call, 'id', 'N/A')}")
                                    logger.error(f"         Type: {getattr(tool_call, 'type', 'N/A')}")
                                    
                                    if hasattr(tool_call, 'function'):
                                        func = tool_call.function
                                        logger.error(f"         Function name: {getattr(func, 'name', 'N/A')}")
                                        logger.error(f"         Function args: {getattr(func, 'arguments', 'N/A')}")
                                    
                                    # Check for MCP-specific details
                                    if getattr(tool_call, 'type', None) == 'mcp':
                                        logger.error(f"         🔧 MCP TOOL CALL DETECTED!")
                                        logger.error(f"         MCP tool call object: {tool_call}")
                                        
                                        # Try to get more MCP-specific info
                                        for attr in dir(tool_call):
                                            if not attr.startswith('_'):
                                                try:
                                                    value = getattr(tool_call, attr)
                                                    logger.error(f"         MCP {attr}: {value}")
                                                except:
                                                    logger.error(f"         MCP {attr}: <could not access>")
                        
                        logger.error(f"     Full step object: {step}")
                        
                except Exception as step_error:
                    logger.error(f"❌ Could not analyze run steps: {step_error}")
                    logger.error(f"   Step error type: {type(step_error)}")
                    import traceback
                    logger.error(f"   Step analysis traceback: {traceback.format_exc()}")
                    
                    # Try alternative approach to get error details
                    logger.error(f"🔍 ATTEMPTING ALTERNATIVE ERROR ANALYSIS...")
                    try:
                        # Check if we can get any information about why the run failed
                        logger.error(f"   Run status: {getattr(run, 'status', 'unknown')}")
                        logger.error(f"   Run failed_at: {getattr(run, 'failed_at', 'unknown')}")
                        logger.error(f"   Run started_at: {getattr(run, 'started_at', 'unknown')}")
                        logger.error(f"   Run created_at: {getattr(run, 'created_at', 'unknown')}")
                        
                        # Check if there's any additional error information
                        if hasattr(run, 'last_error') and run.last_error:
                            error = run.last_error
                            logger.error(f"   Error code: {getattr(error, 'code', 'N/A')}")
                            logger.error(f"   Error message: {getattr(error, 'message', 'N/A')}")
                            
                            # Try to get more error details if available
                            for attr in dir(error):
                                if not attr.startswith('_'):
                                    try:
                                        value = getattr(error, attr)
                                        logger.error(f"   Error {attr}: {value}")
                                    except:
                                        pass
                        
                        # Log the full run object for debugging
                        logger.error(f"   Full run attributes:")
                        for attr in dir(run):
                            if not attr.startswith('_'):
                                try:
                                    value = getattr(run, attr)
                                    logger.error(f"     {attr}: {value}")
                                except:
                                    logger.error(f"     {attr}: <could not access>")
                                    
                    except Exception as alt_error:
                        logger.error(f"❌ Alternative analysis also failed: {alt_error}")
                        
                    # This suggests Azure Foundry failed before creating run steps
                    # Likely an MCP connection/protocol issue
                    logger.error(f"🔧 HYPOTHESIS: Azure Foundry failed during MCP tool execution")
                    logger.error(f"   This suggests the McpTool could not communicate with the MCP server")
                    logger.error(f"   Even though initial connectivity test passed")
                    logger.error(f"   Check MCP server logs for any requests during this timeframe")
                
                yield f"❌ **Run Failed:** {run.last_error}"
                return

            if run.status == "requires_action":
                logger.info(f"🔧 RUN REQUIRES ACTION - TOOL CALLS NEEDED")
                logger.info(f"   Run ID: {run.id}")
                logger.info(f"   Required action: {run.required_action}")
                try:
                    # Check if there are actually tool calls to handle
                    if hasattr(run, 'required_action') and run.required_action:
                        logger.info(f"Found required action: {run.required_action}")
                        await self._handle_tool_calls(run, thread_id)
                    else:
                        logger.warning(f"Run status is 'requires_action' but no required_action found - this may indicate a stuck run")
                        stuck_run_count += 1
                        if stuck_run_count >= max_stuck_runs:
                            logger.error(f"Run {run.id} is stuck in requires_action state without tool calls after {stuck_run_count} attempts")
                            yield f"Error: Run is stuck in requires_action state - please try again"
                            return
                        # Try to get the run again to see if it has progressed
                        run = client.runs.get(thread_id=thread_id, run_id=run.id)
                except Exception as e:
                    logger.error(f"❌ ERROR HANDLING TOOL CALLS: {e}")
                    yield f"Error handling tool calls: {str(e)}"
                    return

        if run.status == "failed":
            yield f"Error: {run.last_error}"
            return

        if iterations >= max_iterations:
            yield "Error: Request timed out"
            return

        # Extract token usage from completed run
        if hasattr(run, 'usage') and run.usage:
            self.last_token_usage = {
                'prompt_tokens': getattr(run.usage, 'prompt_tokens', 0),
                'completion_tokens': getattr(run.usage, 'completion_tokens', 0),
                'total_tokens': getattr(run.usage, 'total_tokens', 0)
            }
            logger.debug(f"💰 Token usage: {self.last_token_usage}")
        else:
            self.last_token_usage = None

        # After run is complete, yield the assistant's response(s) with citation formatting
        messages = list(client.messages.list(thread_id=thread_id, order=ListSortOrder.ASCENDING))
        logger.debug(f"Found {len(messages)} messages in thread")
        for msg in reversed(messages):
            logger.debug(f"Processing message: role={msg.role}, content_count={len(msg.content) if msg.content else 0}")
            if msg.role == "assistant" and msg.content:
                for content_item in msg.content:
                    logger.debug(f"Processing content item: type={type(content_item)}")
                    if hasattr(content_item, 'text'):
                        text_content = content_item.text.value
                        logger.debug(f"Original text content: {text_content[:200]}...")
                        citations = []
                        # Extract citations as before
                        if hasattr(content_item.text, 'annotations') and content_item.text.annotations:
                            logger.debug(f"Found {len(content_item.text.annotations)} annotations")
                            main_text = content_item.text.value if hasattr(content_item.text, 'value') else str(content_item.text)
                            for i, annotation in enumerate(content_item.text.annotations):
                                logger.debug(f"Processing annotation {i}: {type(annotation)}")
                                # File citations
                                if hasattr(annotation, 'file_citation') and annotation.file_citation:
                                    file_citation = annotation.file_citation
                                    quote = getattr(file_citation, 'quote', '') or ''
                                    file_id = getattr(file_citation, 'file_id', '') or ''
                                    annotation_text = getattr(annotation, 'text', '') or ''
                                    citation_context = self._extract_citation_context(main_text, annotation, quote)
                                    citation_text = self._create_meaningful_citation_text(quote, citation_context, file_id)
                                    citations.append({
                                        'type': 'file',
                                        'text': citation_text,
                                        'file_id': file_id,
                                        'quote': quote,
                                        'context': citation_context,
                                        'annotation_text': annotation_text
                                    })
                                    logger.debug(f"Added file citation: {citation_text}")
                                # File path citations
                                elif hasattr(annotation, 'file_path') and annotation.file_path:
                                    file_path = annotation.file_path
                                    file_id = getattr(file_path, 'file_id', '') or ''
                                    try:
                                        project_client = self._get_project_client()
                                        file_info = project_client.agents.files.get(file_id)
                                        if hasattr(file_info, 'filename') and file_info.filename:
                                            citation_text = file_info.filename
                                        else:
                                            citation_text = f"File Reference (ID: {file_id[-8:]})"
                                    except Exception as e:
                                        citation_text = f"File Reference (ID: {file_id[-8:]})"
                                    citations.append({
                                        'type': 'file_path',
                                        'text': citation_text,
                                        'file_id': file_id
                                    })
                                    logger.debug(f"Added file_path citation: {citation_text}")
                                # URL citations
                                elif hasattr(annotation, 'url_citation') and annotation.url_citation:
                                    url_citation = annotation.url_citation
                                    url = getattr(url_citation, 'url', '') or '#'
                                    title = getattr(url_citation, 'title', '') or 'Web Source'
                                    citations.append({
                                        'type': 'web',
                                        'text': title,
                                        'url': url
                                    })
                                    logger.debug(f"Added URL citation: {title} -> {url}")
                        else:
                            logger.debug(f"No annotations found in content item")
                        
                        logger.debug(f"Total citations found: {len(citations)}")
                        if citations:
                            logger.debug(f"Citations: {citations}")
                        else:
                            logger.debug(f"No citations found - this is why sources are missing!")
                        formatted_response = self._format_response_with_citations(text_content, citations)
                        logger.debug(f"Formatted response: {formatted_response[:200]}...")
                        logger.debug(f"Full formatted response length: {len(formatted_response)}")
                        logger.debug(f"Sources section in response: {'📚 Sources:' in formatted_response}")
                        if '📚 Sources:' in formatted_response:
                            sources_start = formatted_response.find('📚 Sources:')
                            logger.debug(f"Sources section: {formatted_response[sources_start:sources_start+200]}...")
                        yield formatted_response
                break
    
    def _format_response_with_citations(self, text_content: str, citations: List[Dict]) -> str:
        """Format the response text with clickable citations for Gradio UI."""
        if not citations:
            return text_content
        
        logger.debug(f"Processing {len(citations)} citations before deduplication")
        
        # Smart deduplication that preserves meaningful content
        unique_citations = []
        seen_citations = set()
        
        for citation in citations:
            # Create a unique key based on meaningful content
            if citation['type'] == 'web':
                key = f"web_{citation.get('url', '')}"
            elif citation['type'] in ['file', 'file_path']:
                file_id = citation.get('file_id', '')
                quote = citation.get('quote', '').strip()
                context = citation.get('context', '').strip()
                
                # Use content-based uniqueness for better deduplication
                if quote and len(quote) > 20:
                    # Use first 50 chars of quote for uniqueness
                    content_key = quote[:50].lower().replace(' ', '').replace('\n', '')
                    key = f"file_content_{content_key}"
                elif context and len(context) > 20:
                    # Use first 50 chars of context for uniqueness
                    content_key = context[:50].lower().replace(' ', '').replace('\n', '')
                    key = f"file_context_{content_key}"
                else:
                    # Fallback to file_id
                    key = f"file_{file_id}"
            else:
                # For other types, use text content
                text_key = citation.get('text', '')[:50].lower().replace(' ', '')
                key = f"{citation['type']}_{text_key}"
            
            # Only add if we haven't seen this content before
            if key not in seen_citations:
                seen_citations.add(key)
                unique_citations.append(citation)
        
        logger.debug(f"After deduplication: {len(unique_citations)} unique citations")
        
        # Start with the main text and clean up citation markers
        formatted_text = text_content
        
        # Remove Azure AI Foundry citation markers like 【4:0†source】
        formatted_text = re.sub(r'【\d+:\d+†source】', '', formatted_text)
        
        # Add a sources section if we have citations
        if unique_citations:
            formatted_text += "\n\n**📚 Sources:**\n"
            
            citation_num = 1
            for citation in unique_citations:
                if citation['type'] == 'web':
                    formatted_text += f"{citation_num}. 🌐 [{citation.get('text', 'Web Source')}]({citation.get('url', '#')})\n"
                elif citation['type'] in ['file', 'file_path']:
                    # Use our improved method to get meaningful citation text
                    meaningful_text = self._get_readable_file_name(citation)
                    formatted_text += f"{citation_num}. 📄 **{meaningful_text}** *(from uploaded documents)*\n"
                citation_num += 1
            
            logger.info(f"Generated sources section with {len(unique_citations)} citations")
        
        return formatted_text
    

    
    def _extract_citation_context(self, main_text: str, annotation, quote: str) -> str:
        """Extract meaningful context around a citation from the main response text."""
        try:
            # If we have a quote, try to find it in the main text and get surrounding context
            if quote and len(quote.strip()) > 10:
                import re
                # Look for the quote or similar content in the main text
                quote_words = quote.strip().split()[:5]  # First 5 words
                if len(quote_words) >= 2:
                    pattern = r'.{0,50}' + re.escape(' '.join(quote_words[:2])) + r'.{0,50}'
                    match = re.search(pattern, main_text, re.IGNORECASE)
                    if match:
                        context = match.group(0).strip()
                        return context
            
            # Fallback: Try to get context around citation markers
            if hasattr(annotation, 'text') and annotation.text:
                marker = annotation.text
                # Look for the citation marker in the main text
                marker_pos = main_text.find(marker)
                if marker_pos != -1:
                    # Extract 100 characters before and after the marker
                    start = max(0, marker_pos - 100)
                    end = min(len(main_text), marker_pos + len(marker) + 100)
                    context = main_text[start:end].strip()
                    # Clean up the context
                    context = context.replace(marker, '').strip()
                    if context:
                        return context
            
            return ""
        except Exception as e:
            logger.debug(f"Error extracting citation context: {e}")
            return ""

    def _create_meaningful_citation_text(self, quote: str, context: str, file_id: str) -> str:
        """Create meaningful citation text using available information."""
        
        # Priority 1: Use substantial quote content
        if quote and len(quote.strip()) > 20:
            clean_quote = quote.replace('\n', ' ').replace('\r', ' ').strip()
            if len(clean_quote) > 100:
                clean_quote = clean_quote[:97] + "..."
            return f'Document excerpt: "{clean_quote}"'
        
        # Priority 2: Use extracted context
        if context and len(context.strip()) > 20:
            clean_context = context.replace('\n', ' ').replace('\r', ' ').strip()
            if len(clean_context) > 100:
                clean_context = clean_context[:97] + "..."
            return f'Document content: "{clean_context}"'
        
        # Priority 3: Try to get meaningful filename
        if file_id:
            try:
                project_client = self._get_project_client()
                file_info = project_client.agents.files.get(file_id)
                if hasattr(file_info, 'filename') and file_info.filename:
                    # Clean up the filename for display
                    filename = file_info.filename
                    if filename.endswith('.pdf'):
                        filename = filename[:-4]  # Remove .pdf extension
                    return f'Document: "{filename}"'
            except Exception as e:
                logger.debug(f"Could not retrieve filename for {file_id}: {e}")
        
        # Priority 4: Use shortened file ID
        if file_id and len(file_id) > 8:
            return f"Document (ID: {file_id[-8:]})"
        elif file_id:
            return f"Document (ID: {file_id})"
        
        # Fallback
        return "Referenced document"

    def _get_readable_file_name(self, citation: Dict) -> str:
        """Derive a human-readable label for a citation entry."""
        quote = citation.get('quote', '').strip()
        if quote and len(quote) > 20:
            clean_quote = quote.replace('\n', ' ').replace('\r', ' ')
            if len(clean_quote) > 100:
                clean_quote = clean_quote[:97] + "..."
            return f'"{clean_quote}"'

        citation_text = citation.get('text', '').strip()
        if citation_text and len(citation_text) > 10:
            clean_text = citation_text.replace('\n', ' ').replace('\r', ' ')
            if len(clean_text) > 100:
                clean_text = clean_text[:97] + "..."
            return clean_text

        context = citation.get('context', '').strip()
        if context and len(context) > 20:
            clean_context = context.replace('\n', ' ').replace('\r', ' ')
            if len(clean_context) > 100:
                clean_context = clean_context[:97] + "..."
            return clean_context

        file_id = citation.get('file_id') or citation.get('file_path')
        if file_id:
            try:
                project_client = self._get_project_client()
                file_info = project_client.agents.files.get(file_id)
                if hasattr(file_info, 'filename') and file_info.filename:
                    cleaned_name = file_info.filename.replace('_', ' ')
                    if len(cleaned_name) > 80:
                        cleaned_name = cleaned_name[:77] + '...'
                    return cleaned_name
            except Exception as e:
                logger.debug(f"Could not fetch filename for citation: {e}")

        if citation_text:
            return citation_text

        return "Referenced document"

    async def _handle_tool_calls(self, run: ThreadRun, thread_id: str):
        """Handle tool calls or approval requests coming back from Azure AI Foundry."""
        if not hasattr(run, "required_action") or not run.required_action:
            logger.warning("No required_action present on run; nothing to handle")
            return

        required_action = run.required_action
        action_type = None
        tool_calls = []

        if hasattr(required_action, "submit_tool_outputs") and required_action.submit_tool_outputs:
            action_type = "submit_tool_outputs"
            tool_calls = getattr(required_action.submit_tool_outputs, "tool_calls", []) or []
        elif hasattr(required_action, "submit_tool_approval") and required_action.submit_tool_approval:
            action_type = "submit_tool_approval"
            tool_calls = getattr(required_action.submit_tool_approval, "tool_calls", []) or []
        else:
            logger.warning(
                "Required action missing submit_tool_outputs/submit_tool_approval attributes: %s",
                dir(required_action)
            )
            return

        if not tool_calls:
            logger.warning("Required action contained no tool calls; nothing to process")
            return

        client = self._get_client()

        if action_type == "submit_tool_outputs":
            logger.info("Handling %d tool output call(s)", len(tool_calls))
            tool_outputs = []

            for tool_call in tool_calls:
                try:
                    function_name = getattr(getattr(tool_call, "function", None), "name", "unknown")
                    arguments = getattr(getattr(tool_call, "function", None), "arguments", "{}")
                    logger.info("Processing tool output call %s with args %s", function_name, arguments)

                    dummy_result = {
                        "status": "success",
                        "message": f"Tool '{function_name}' executed (simulated).",
                        "data": {
                            "result": "simulated_result",
                            "arguments": arguments,
                        },
                    }

                    tool_outputs.append({
                        "tool_call_id": tool_call.id,
                        "output": json.dumps(dummy_result),
                    })
                except Exception as exc:
                    logger.error("Error constructing tool output for call %s: %s", getattr(tool_call, "id", "?"), exc)

            if tool_outputs:
                logger.debug("Submitting %d tool outputs", len(tool_outputs))
                client.runs.submit_tool_outputs(
                    thread_id=thread_id,
                    run_id=run.id,
                    tool_outputs=tool_outputs,
                )
            else:
                logger.warning("No tool outputs generated; submitting empty acknowledgements")
                fallback_outputs = [{"tool_call_id": tc.id, "output": "{}"} for tc in tool_calls if hasattr(tc, "id")]
                if fallback_outputs:
                    client.runs.submit_tool_outputs(
                        thread_id=thread_id,
                        run_id=run.id,
                        tool_outputs=fallback_outputs,
                    )

            return

        # Otherwise handle submit_tool_approval
        logger.info("Handling %d tool approval request(s)", len(tool_calls))
        approvals = []

        # Get the MCP headers to include with tool approvals
        # This is CRITICAL for ngrok - without the ngrok-skip-browser-warning header,
        # ngrok will return an HTML interstitial page instead of JSON
        mcp_headers = {}
        if self._mcp_tool and hasattr(self._mcp_tool, 'headers'):
            mcp_headers = self._mcp_tool.headers
            logger.info(f"Using MCP headers for tool approvals: {mcp_headers}")
        else:
            # Fallback: construct headers manually if mcp_tool not available
            mcp_headers = {
                "Content-Type": "application/json",
                "User-Agent": "Azure-AI-Foundry-Agent",
                "ngrok-skip-browser-warning": "true",
                "Accept": "application/json, text/event-stream"
            }
            logger.warning(f"MCP tool not available, using fallback headers: {mcp_headers}")

        for tool_call in tool_calls:
            try:
                approvals.append(ToolApproval(tool_call_id=tool_call.id, approve=True, headers=mcp_headers))
                logger.info("Prepared approval for tool call %s with headers", tool_call.id)
            except Exception as exc:
                logger.error("Could not prepare approval for tool call %s: %s", getattr(tool_call, "id", "?"), exc)

        if not approvals:
            logger.warning("No approvals generated; skipping submission")
            return

        client.runs.submit_tool_outputs(
            thread_id=thread_id,
            run_id=run.id,
            tool_approvals=approvals,
        )
        logger.info("Submitted %d tool approval(s)", len(approvals))


    async def run_conversation(self, thread_id: str, user_message: str):
        """Collects all streamed messages and returns as a tuple (responses, tools_called) for host agent compatibility."""
        results = []
        tools_called = []
        tool_descriptions = []  # Track enhanced tool descriptions
        
        async for msg in self.run_conversation_stream(thread_id, user_message):
            results.append(msg)
            # Extract tool call info from progress messages
            if msg.startswith("🛠️ Remote agent executing:"):
                tool_description = msg.replace("🛠️ Remote agent executing: ", "").strip()
                if tool_description not in tool_descriptions:
                    tool_descriptions.append(tool_description)
                    # Extract a simple tool name for backward compatibility
                    if ":" in tool_description:
                        tool_name = tool_description.split(":")[0].strip()
                    else:
                        tool_name = tool_description
                    if tool_name not in tools_called:
                        tools_called.append(tool_description)  # Use the full description

        # After streaming is complete, collect all actual tool calls from run steps
        try:
            client = self._get_client()
            # Find the most recent run for this thread
            runs = client.runs.list(thread_id=thread_id)
            if runs.data:
                latest_run = runs.data[0]  # Most recent run
                run_steps = client.run_steps.list(thread_id, latest_run.id)
                step_count = 0
                logger.info("Listing all run steps:")
               
                for run_step in run_steps:
                    step_count += 1
                    logger.info(f"Step {step_count}: {run_step}")
                   
                    if (run_step.step_details and
                        hasattr(run_step.step_details, "type") and
                        run_step.step_details.type == "tool_calls" and
                        hasattr(run_step.step_details, "tool_calls")):
                        for tool_call in run_step.step_details.tool_calls:
                            if tool_call and hasattr(tool_call, "type"):
                                tool_type = tool_call.type
                                tool_description = self._get_tool_description(tool_type, tool_call)
                                if tool_description not in tools_called:
                                    tools_called.append(tool_description)
                                    logger.info(f"Found tool call: {tool_description}")
        except Exception as e:
            logger.error(f"Error collecting tool calls: {e}")
        
        return (results, tools_called)

    def _get_tool_description(self, tool_type: str, tool_call) -> str:
        """Helper to get a more meaningful tool description from the tool call."""
        try:
            # Try to get the actual function name from the tool call
            if hasattr(tool_call, 'function') and hasattr(tool_call.function, 'name'):
                function_name = tool_call.function.name
                # Try to get arguments if available
                if hasattr(tool_call.function, 'arguments'):
                    try:
                        import json
                        args = json.loads(tool_call.function.arguments)
                        # Create a more descriptive message based on function name and args
                        if function_name == "bing_grounding" or function_name == "web_search":
                            query = args.get('query', '')
                            if query:
                                return f"Searching the web for: '{query[:50]}{'...' if len(query) > 50 else ''}'"
                            else:
                                return "Performing web search"
                        elif function_name == "file_search":
                            query = args.get('query', '')
                            if query:
                                return f"Searching documents for: '{query[:50]}{'...' if len(query) > 50 else ''}'"
                            else:
                                return "Searching through uploaded documents"
                        # Handle QuickBooks MCP tools
                        elif function_name.startswith("qbo_"):
                            # Parse the QuickBooks tool name
                            tool_parts = function_name.replace("qbo_", "").split("_")
                            action = tool_parts[0] if tool_parts else "executing"
                            entity = "_".join(tool_parts[1:]) if len(tool_parts) > 1 else "data"
                            
                            if action == "search":
                                return f"Searching QuickBooks {entity.replace('_', ' ')}"
                            elif action == "get":
                                entity_id = args.get('id', args.get('entity_id', ''))
                                if entity_id:
                                    return f"Getting QuickBooks {entity.replace('_', ' ')}: {entity_id}"
                                return f"Getting QuickBooks {entity.replace('_', ' ')}"
                            elif action == "create":
                                return f"Creating QuickBooks {entity.replace('_', ' ')}"
                            elif action == "update":
                                return f"Updating QuickBooks {entity.replace('_', ' ')}"
                            elif action == "delete":
                                return f"Deleting QuickBooks {entity.replace('_', ' ')}"
                            elif action == "query":
                                query_str = args.get('query', '')
                                if query_str:
                                    return f"Executing QuickBooks query: '{query_str[:50]}{'...' if len(query_str) > 50 else ''}'"
                                return "Executing QuickBooks query"
                            elif action == "company":
                                return "Getting QuickBooks company info"
                            elif action == "report":
                                report_type = args.get('report_type', args.get('type', ''))
                                if report_type:
                                    return f"Generating QuickBooks report: {report_type}"
                                return "Generating QuickBooks report"
                            else:
                                return f"QuickBooks: {function_name.replace('qbo_', '').replace('_', ' ').title()}"
                        elif function_name.startswith("search_") or function_name.startswith("get_") or function_name.startswith("create_") or function_name.startswith("list_"):
                            # Generic QuickBooks operations
                            return f"QuickBooks: {function_name.replace('_', ' ').title()}"
                        else:
                            return f"Executing {function_name}"
                    except (json.JSONDecodeError, AttributeError):
                        return f"Executing {function_name}"
                else:
                    return f"Executing {function_name}"
            else:
                # Fallback to tool type if function name not available
                return f"Executing {tool_type}"
        except Exception as e:
            # Final fallback
            return f"Executing tool: {tool_type}"




async def create_foundry_quickbooks_agent() -> FoundryQuickBooksAgent:
    """Factory function to create and initialize a Foundry QuickBooks Online agent."""
    agent = FoundryQuickBooksAgent()
    await agent.create_agent()
    return agent


async def demo_agent_interaction():
    """Demo function showing how to use the Foundry QuickBooks Online agent."""
    agent = await create_foundry_quickbooks_agent()
    
    try:
        # Create a conversation thread
        thread = await agent.create_thread()
        
        # Example interaction
        message = "Hello! Can you show me all accounts in the technology industry?"
        print(f"\nUser: {message}")
        async for response in agent.run_conversation(thread.id, message):
            print(f"Assistant: {response}")
                
    finally:
        logger.info("Demo completed - agent preserved for reuse")


if __name__ == "__main__":
    asyncio.run(demo_agent_interaction())