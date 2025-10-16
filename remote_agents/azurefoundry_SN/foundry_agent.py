"""
AI Foundry Agent implementation with ServiceNow Capabilities.
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
import time
import datetime
import asyncio
import logging
import json
from typing import Optional, Dict, Any, List

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import Agent, ThreadMessage, ThreadRun, AgentThread, ToolOutput, MessageRole, BingGroundingTool, ListSortOrder, FilePurpose, FileSearchTool, McpTool, RequiredMcpToolCall, SubmitToolApprovalAction, ToolApproval
from azure.ai.agents.operations import ThreadsOperations
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
import glob

logger = logging.getLogger(__name__)


class FoundrySNAgent:
    """
    AI Foundry Agent with calendar management and web search capabilities.
    This class adapts the ADK calendar agent pattern for Azure AI Foundry.
    
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
        self.vector_store = None
        self.uploaded_files = []
        self._file_search_tool = None  # Cache the file search tool
        self._agents_client = None  # Cache the agents client
        self._project_client = None  # Cache the project client
        
    def is_initialized(self) -> bool:
        """Check if the agent has been created and initialized."""
        return self.agent is not None
        
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
        async with FoundrySNAgent._file_search_setup_lock:
            # If we already have a shared file search tool, return it
            if FoundrySNAgent._shared_file_search_tool is not None:
                logger.info("Reusing existing shared file search tool")
                return FoundrySNAgent._shared_file_search_tool
            
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
                        FoundrySNAgent._shared_uploaded_files.append(file.id)
                        logger.info(f"Uploaded file: {os.path.basename(file_path)} (ID: {file.id})")
                    except Exception as e:
                        logger.warning(f"Failed to upload {file_path}: {e}")
                
                if not file_ids:
                    logger.warning("No files were successfully uploaded")
                    return None
                
                # Create vector store ONCE using project client
                logger.info("Creating shared vector store with uploaded files...")
                FoundrySNAgent._shared_vector_store = project_client.agents.vector_stores.create_and_poll(
                    file_ids=file_ids, 
                    name="shared_vectorstore"
                )
                logger.info(f"Created shared vector store: {FoundrySNAgent._shared_vector_store.id}")
                
                # Create file search tool ONCE
                file_search = FileSearchTool(vector_store_ids=[FoundrySNAgent._shared_vector_store.id])
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
                FoundrySNAgent._shared_file_search_tool = file_search
                logger.info("Cached shared file search tool for future use")
                    
                return file_search
                    
            except Exception as e:
                logger.error(f"Error setting up file search: {e}")
                return None
        
    async def create_agent(self) -> Agent:
        """Create the AI Foundry agent with ServiceNow MCP, web search, and file search capabilities."""
        if self.agent:
            logger.info("Agent already exists, returning existing instance")
            return self.agent
        
        logger.info("🚀 CREATING NEW AZURE FOUNDRY AGENT...")
        
        # Start with MCP tools using the new McpTool class - FIXED FOR AZURE FOUNDRY
        logger.info("🔍 CREATING MCP TOOL CONNECTION...")
        logger.info(f"   Server URL: https://agent1.ngrok.app/mcp/")
        logger.info(f"   Server Label: ServiceNow")
        
        try:
            # Test MCP server connectivity first
            logger.info("🧪 TESTING MCP SERVER CONNECTIVITY...")
            import httpx
            import asyncio
            
            async def test_mcp_basic():
                try:
                    # Test SSE endpoint properly - don't try to read the full response
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        async with client.stream("GET", "https://agent1.ngrok.app/mcp/") as response:
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
            connectivity_ok = await test_mcp_basic()
            
            # Create MCP tool with specific allowed tools to avoid discovery timeout issues
            logger.info("🔧 CREATING McpTool OBJECT...")
            self._mcp_server_url = "https://agent1.ngrok.app/mcp/"
            mcp_tool = McpTool(
                server_label="ServiceNow",
                server_url=self._mcp_server_url,
                allowed_tools=[]  # Let Azure discover all available tools automatically (per Microsoft docs)
            )
            logger.info("✅ McpTool object created successfully")

            mcp_tool.set_approval_mode("never")  # Disable approval requirement
            logger.info("✅ Set approval mode to 'never'")
            
            # Set headers using the official method from Microsoft documentation
            mcp_tool.update_headers("Content-Type", "application/json")
            mcp_tool.update_headers("User-Agent", "Azure-AI-Foundry-Agent")
            logger.info("✅ Set MCP headers using update_headers method")
            
            # Store reference to mcp_tool for later use
            self._mcp_tool = mcp_tool

            tools = mcp_tool.definitions
            
            # Don't set tool_resources here - let file search handle it
            tool_resources = None
            
            logger.info(f"🔍 MCP TOOL DETAILS:")
            logger.info(f"   Tools count: {len(tools) if tools else 0}")
            logger.info(f"   Tool definitions: {[str(t) for t in tools[:3]] if tools else 'None'}")
            logger.info(f"   Tool resources: {tool_resources}")
            logger.info("🔧 FIXED: Using correct tool_resources format with server_label as key")
            
            logger.info("✅ Added ServiceNow MCP server integration using McpTool")
            
        except Exception as e:
            logger.error(f"❌ FAILED TO CREATE MCP TOOL: {e}")
            logger.error(f"   Error type: {type(e)}")
            import traceback
            logger.error(f"   Full traceback: {traceback.format_exc()}")
            
            # Fallback: create empty tools list if MCP fails
            tools = []
            tool_resources = None
            logger.warning("⚠️ Continuing without MCP tools due to connection failure")
        
        # 🔧 CRITICAL FIX: Remove Salesforce tools so Azure uses ServiceNow MCP tools
        # salesforce_tools = self._get_servicenow_tools()
        # tools.extend(salesforce_tools)
        # logger.info("Added ServiceNow function tools for simulation")
        logger.info("🔧 REMOVED Salesforce tools - forcing Azure to use ServiceNow MCP tools")
        
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
        
        # Use context manager and create agent with all tools
        with project_client:
            if tool_resources:
                self.agent = project_client.agents.create_agent(
                    model="gpt-4o",
                    name="foundry-SF-agent",
                    instructions=self._get_agent_instructions(),
                    tools=tools,
                    tool_resources=tool_resources
                )
            else:
                self.agent = project_client.agents.create_agent(
                    model="gpt-4o",
                    name="foundry-SF-agent",
                    instructions=self._get_agent_instructions(),
                    tools=tools
                )
        
        logger.info(f"Created AI Foundry agent: {self.agent.id}")
        return self.agent
    
    def _get_agent_instructions(self) -> str:
        """Get the agent instructions for calendar, web search, file search, and ServiceNow capabilities."""
        return f"""
You are an intelligent knowledge and ServiceNow assistant powered by Azure AI Foundry.

**CRITICAL ESCALATION RULE**: If you see "User explicitly requested to speak with a human representative" or similar human escalation requests, immediately output ONLY 'HUMAN_ESCALATION_REQUIRED' and nothing else.

Your capabilities include:
- Searching the web for current information when needed
- Searching through uploaded documents and files for specific information
- Managing ServiceNow incidents and records
- Checking calendar availability and managing events
        - ALWAYS: when looking up customer information, use file_search (uploaded docs) to retreive information from the customer's profile (MCP TOOL call is for incidents only)
        - INCIDENT LOOKUPS: Always retrieve incident data via the ServiceNow MCP tools (sn_search_incidents, sn_get_incident, sn_get_user_incidents). Never rely on file_search or document summaries for incident details.

ServiceNow capabilities:
- Create new incidents with proper categorization (priority, severity, status)
- Search for existing cases and records
- Update incident status and add comments/work notes
- Query ServiceNow tables and retrieve specific records
- Get all incidents for a specific user by username in one call
- List available users to help find the correct username
- For knowledge/troubleshooting information, use file_search (uploaded docs) and web search in parallel when appropriate

Available ServiceNow Tools (you have both MCP and direct versions):
- **sn_create_incident**: Create new incidents with full details and categorization
- **sn_search_incidents**: Search for existing incidents with filters
- **sn_get_incident**: Get detailed information for a specific incident
- **sn_get_user_incidents**: Get all incidents associated with a specific user
- **sn_update_incident**: Update incident status, notes, and assignments
- **sn_list_users**: List available users, optionally filtered by department
        
        Reporting requirements (when asked to "show everything" or "list all details"):
        - Present the actual ServiceNow data in a clear, readable format
        - Show user details (name, username, email, department, etc.)
        - List incidents with their actual fields (number, short_description, description, state, priority, severity, caller_id, assigned_to, opened_at, etc.)
        - Include the actual values from ServiceNow, not technical payloads
        - Format the data in a human-readable way with proper labels
        
        CRITICAL: When asked to update incidents, you MUST:
        1. Call sn_update_incident with the actual incident number
        2. Include the exact arguments sent (state, work_notes, etc.)
        3. Show the before/after incident state
        4. Confirm the update was successful
        
        CRITICAL: When asked to "show everything" or "list all details":
        1. Display EVERY incident record found with ALL fields visible
        2. Show the exact tool calls made and their arguments
        3. Include the complete results from each tool call
        4. Do NOT summarize or say "multiple incidents found" - show the actual records
        5. For updates, show the exact request sent and the result received

Available Bank Actions (simulated):
- **block_card**: Block a credit card (requires card_number parameter)
- **unblock_card**: Unblock a previously blocked card (requires card_number parameter)
- **check_balance**: Check account balance (requires account_id parameter)
- **report_fraud**: Report fraudulent activity (requires card_number parameter)
- **create_dispute**: Create a transaction dispute (requires transaction_id, amount, merchant_name, reason parameters)
- **issue_refund**: Issue a refund for a transaction (requires transaction_id, amount, merchant_name, refund_type parameters)
- **check_transaction**: Check details of a specific transaction (requires transaction_id parameter)
 
        IMPORTANT - ServiceNow Response Instructions:
        Do NOT fabricate ServiceNow data. Always execute the appropriate ServiceNow MCP tools and base responses strictly on real tool results. If a lookup returns no records, state that explicitly.

Key guidelines:
        - INCIDENT NUMBER ENFORCEMENT: If the user message contains an incident number matching /\bINC\d{6,}\b/ (e.g., INC0010009), you MUST call sn_get_incident(number) BEFORE replying. Do not answer without executing this tool. If no record is found, state that explicitly and then suggest next actions.
        - Person-to-incidents ENFORCEMENT: If the user asks for a person's incidents (e.g., "David Miller's incidents"), you MUST call sn_search_incidents with the person's name (or username/email). Do not answer without executing this tool.
        - ABSOLUTE RULE for person lookups: NEVER fabricate caller filters manually. Run sn_search_incidents first with the provided name. If sn_search_incidents returns no results and you have a confirmed username, you MAY then call sn_get_user_incidents as a secondary check.
        - INCIDENT RESPONSES: Do NOT use file_search or rely on uploaded documents for incident information. Always cite results pulled directly from the ServiceNow MCP tools.
- When users need current information from the web, use your web search capability
- When users ask about information that might be in documents, use your file search capability
- When users want to create, search, or manage ServiceNow incidents/records, use your ServiceNow tools
        - When users request banking actions (block card, create dispute, issue refund, etc.), use the bank_action function

Bank Action Guidelines:
- **ALWAYS use bank_action function for banking operations**: When users ask to block/unblock cards, create disputes, issue refunds, check balances, report fraud, or check transactions
- **Don't ask for card numbers if not provided**: If a user asks to "block David Miller's card" but doesn't provide a card number, simulate the action with a generic card number or ask for clarification
- **Bank actions take priority over ServiceNow lookups**: If someone asks to "block David Miller's card", use bank_action first, not sn_search_user
- **Use realistic simulated data**: Generate appropriate card numbers, transaction IDs, and amounts when not provided
- **Provide detailed explanations**: After performing bank actions, explain what was done, what the results mean, and any next steps the customer should take
- **Include customer-friendly language**: Use clear, non-technical language that customers can understand

Function Selection Guidelines:

**Use bank_action for:**
- "Block David Miller's credit card" → bank_action with action="block_card"
- "Create a dispute for transaction TXN123" → bank_action with action="create_dispute"
- "Issue a refund for $50" → bank_action with action="issue_refund"
- "Check my account balance" → bank_action with action="check_balance"
- "Report fraud on my card" → bank_action with action="report_fraud"

**Example detailed responses:**
- For card blocking: "David Miller's credit card ending in 5678 (Account #1234567890) has been blocked. Card issued 03/15/2022, credit limit $10,000. Replacement card #9876543210 will arrive by 02/03/2025."
- For disputes: "Dispute DSP789012 created for transaction TXN123456 ($50.00 at Walmart on 01/25/2025). Account #1234567890, card ending in 5678."
- For refunds: "Refund REF345678 issued for $75.50 from Target (TXN789012). Will credit account #1234567890 within 3-5 business days."
- For fraud reports: "Fraud report FRD847392 submitted for card ending in 5678. Account #1234567890, last transaction $25.99 at Amazon on 01/26/2025."

**Use ServiceNow functions for:**
- "Show me David Miller's incidents" → sn_get_user_incidents
        - "Get details for incident INC0010009" → sn_get_incident
- "Create a support incident for David Miller" → sn_create_incident
- "List all users" → sn_list_users


Current date and time: {datetime.datetime.now().isoformat()}

When users ask about current information, want to search through documents, or need ServiceNow assistance, use your available tools to provide accurate and helpful responses.

CRITICAL - Human Escalation Protocol:
**MANDATORY**: If the user requests to speak to a human, needs human help, asks for escalation to a real person, or if you see "User explicitly requested to speak with a human representative" in the context, you MUST:

1. Output EXACTLY this text as your FIRST and ONLY response: 'HUMAN_ESCALATION_REQUIRED'
2. Do NOT provide any other text or explanation
3. Do NOT say "has been escalated" or similar - just output 'HUMAN_ESCALATION_REQUIRED'
4. Wait for a human expert to take over

EXAMPLES that require escalation:
- "I want to speak to a human"
- "Connect me with a person" 
- "I need human help"
- "User explicitly requested to speak with a human representative"

For all other requests, handle them yourself. Do NOT escalate unless the user clearly requests it.
"""
    
    def _get_calendar_tools(self) -> List[Dict[str, Any]]:
        """Define calendar tools for the agent."""
        calendar_tools = [
            {
                "type": "function",
                "function": {
                    "name": "check_availability",
                    "description": "Check if a time slot is available in the user's calendar",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_time": {
                                "type": "string",
                                "description": "Start time in RFC3339 format"
                            },
                            "end_time": {
                                "type": "string", 
                                "description": "End time in RFC3339 format"
                            },
                            "calendar_id": {
                                "type": "string",
                                "description": "Calendar ID (defaults to 'primary')",
                                "default": "primary"
                            }
                        },
                        "required": ["start_time", "end_time"]
                    }
                }
            },
            {
                "type": "function", 
                "function": {
                    "name": "get_upcoming_events",
                    "description": "Get upcoming events from the user's calendar",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of events to return",
                                "default": 10
                            },
                            "time_range_hours": {
                                "type": "integer", 
                                "description": "Number of hours from now to check",
                                "default": 24
                            }
                        }
                    }
                }
            }
        ]
        
        # Add ServiceNow tools (legacy function-style examples retained for reference, but not used)
        salesforce_tools = [
            {
                "type": "function",
                "function": {
                    "name": "create_case",
                    "description": "Create a new incident in ServiceNow",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subject": {
                                "type": "string",
                                "description": "Brief description of the case"
                            },
                            "description": {
                                "type": "string",
                                "description": "Detailed description of the case"
                            },
                            "priority": {
                                "type": "integer",
                                "description": "Priority level (1=Critical, 2=High, 3=Medium, 4=Low, 5=Planning)",
                                "enum": [1, 2, 3, 4, 5]
                            },
                            "severity": {
                                "type": "integer",
                                "description": "Severity level (1=Critical, 2=High, 3=Medium, 4=Low)",
                                "enum": [1, 2, 3, 4]
                            },
                            "status": {
                                "type": "string",
                                "description": "Case status (New, In Progress, Resolved, Closed)",
                                "enum": ["New", "In Progress", "Resolved", "Closed"]
                            }
                        },
                        "required": ["subject"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_records",
                    "description": "Search for records in ServiceNow tables",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query (e.g., 'Priority=1', 'Status=New')"
                            },
                            "object": {
                                "type": "string",
                                "description": "ServiceNow table to search (default: Incident)",
                                "default": "Case"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of records to return",
                                "default": 10
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_case",
                    "description": "Get a specific case by number or Id",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "case_id": {
                                "type": "string",
                                "description": "Case number (e.g., 500123456) or Id"
                            }
                        },
                        "required": ["case_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_user",
                    "description": "Search for a user profile in ServiceNow by name, username, or email. Use this when asked to 'search for user X', 'find user X profile', or 'look up user X'. Returns user profile information.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "search_term": {
                                "type": "string",
                                "description": "The name, username, or email to search for (e.g., 'john.doe', 'John Doe', 'john@company.com')"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of users to return",
                                "default": 5
                            }
                        },
                        "required": ["search_term"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_user_cases",
                    "description": "Get all cases for a specific user by name/username. Use this when asked to 'find user X and list cases', 'show cases for user X', or 'get cases for David Miller'. Returns case list, not user profile.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "username": {
                                "type": "string",
                                "description": "The username, full name, or email to search for (e.g., 'john.doe', 'John Doe', 'john@company.com')"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of cases to return",
                                "default": 10
                            }
                        },
                        "required": ["username"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_users",
                    "description": "List available users in ServiceNow for debugging purposes",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of users to return",
                                "default": 5
                            }
                        }
                    }
                }
            }
        ]
        
        return calendar_tools + salesforce_tools
    
    def _get_salesforce_tools(self) -> List[Dict[str, Any]]:
        """Define ServiceNow-like function tools for testing and simulation (kept for reference)."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "sf_create_case",
                    "description": "Create a new incident in ServiceNow",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subject": {
                                "type": "string",
                                "description": "Brief description of the case"
                            },
                            "description": {
                                "type": "string",
                                "description": "Detailed description of the case"
                            },
                            "category": {
                                "type": "string",
                                "description": "Case category (Fraud, Technical Issue, Payment Issue, Card Issue, Account Service, Security, Inquiry, Other)",
                                "enum": ["Fraud", "Technical Issue", "Payment Issue", "Card Issue", "Account Service", "Security", "Inquiry", "Other"]
                            },
                            "priority": {
                                "type": "integer",
                                "description": "Priority level (1=Critical, 2=High, 3=Medium, 4=Low, 5=Planning)",
                                "enum": [1, 2, 3, 4, 5]
                            },
                            "severity": {
                                "type": "integer",
                                "description": "Severity level (1=Critical, 2=High, 3=Medium, 4=Low)",
                                "enum": [1, 2, 3, 4]
                            },
                            "contact_id": {
                                "type": "string",
                                "description": "Username or ID of the person reporting the case"
                            }
                        },
                        "required": ["subject"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_search_cases",
                    "description": "Search for existing incidents in ServiceNow",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query (e.g., 'Category=Fraud', 'Status=New', 'ContactId=john.doe')"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of records to return",
                                "default": 10
                            },
                            "category": {
                                "type": "string",
                                "description": "Filter by category"
                            },
                            "status": {
                                "type": "string",
                                "description": "Filter by status (New, In Progress, Resolved, Closed)"
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_get_case",
                    "description": "Get a specific incident by number or sys_id",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "case_id": {
                                "type": "string",
                                "description": "Case number (e.g., 500123456) or Id"
                            }
                        },
                        "required": ["case_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_search_user",
                    "description": "Search for user profiles in ServiceNow",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "search_term": {
                                "type": "string",
                                "description": "Name, username, or email to search for"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of users to return",
                                "default": 5
                            }
                        },
                        "required": ["search_term"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_get_user_cases",
                    "description": "Get all incidents for a specific user",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "username": {
                                "type": "string",
                                "description": "Username, full name, or email"
                            },
                            "status": {
                                "type": "string",
                                "description": "Filter by case status (optional)"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of cases to return",
                                "default": 10
                            }
                        },
                        "required": ["username"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_update_case",
                    "description": "Update an existing incident in ServiceNow",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "case_id": {
                                "type": "string",
                                "description": "Case number or Id to update"
                            },
                            "status": {
                                "type": "string",
                                "description": "New status (New, In Progress, Resolved, Closed)"
                            },
                            "work_notes": {
                                "type": "string",
                                "description": "Work notes to add to the case"
                            },
                            "owner_id": {
                                "type": "string",
                                "description": "Assign case to a user"
                            },
                            "resolution_notes": {
                                "type": "string",
                                "description": "Resolution notes when closing case"
                            }
                        },
                        "required": ["case_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_list_users",
                    "description": "List available users in ServiceNow",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of users to return",
                                "default": 10
                            },
                            "department": {
                                "type": "string",
                                "description": "Filter by department"
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_search_knowledge",
                    "description": "Search ServiceNow knowledge base articles",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query for knowledge articles"
                            },
                            "category": {
                                "type": "string",
                                "description": "Filter by knowledge category"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of articles to return",
                                "default": 5
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {   
                    "name": "bank_action",
                    "description": "Simulate any action on the Bank system (e.g., block card, check balance, report fraud, create dispute, issue refund, etc.) and return a synthetic response.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "description": "The Bank action to perform (e.g., 'block_card', 'check_balance', 'report_fraud', 'create_dispute', 'issue_refund', 'unblock_card', 'check_transaction', etc.)"
                            },
                            "parameters": {
                                "type": "object",
                                "description": "Parameters required for the action (e.g., card_number, amount, reason, transaction_id, merchant_name, etc.)"
                            }
                        },
                        "required": ["action"]
                    }
                }
            }
        ]


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

        # Inject a minimal system hint to bias tool choice when appropriate
        try:
            import re as _re
            inc_match = _re.search(r"\bINC\d{6,}\b", user_message, flags=_re.IGNORECASE)
            if inc_match:
                inc_number = inc_match.group(0).upper()
                hint = (
                    f"SYSTEM TOOL HINT: The user provided incident number {inc_number}. "
                    f"Call the ServiceNow MCP tool 'sn_get_incident' with number='{inc_number}'. "
                    f"Do not answer without executing this tool."
                )
                await self.send_message(thread_id, hint, role="system")
            else:
                if _re.search(r"\b(incidents? for|\bshow (me )?.*incidents? (for|of))\b", user_message, flags=_re.IGNORECASE):
                    hint = (
                        "SYSTEM TOOL HINT: Resolve the user first, then fetch incidents. "
                        "Prefer calling 'sn_get_user_incidents' with the provided name or username. "
                        "If not available, call 'search_records' on table='incident' with an encoded query over caller_id/opened_by/assigned_to using the name."
                    )
                    await self.send_message(thread_id, hint, role="system")

                # Compound customer support requests (person + topic + timeframe + optional update)
                try:
                    name_match = _re.search(r"Customer\s+([A-Z][a-z]+\s+[A-Z][a-z]+)", user_message)
                    keyword_present = _re.search(r"\bVPN\b", user_message, flags=_re.IGNORECASE) is not None
                    days_match = _re.search(r"last\s+(\d{1,3})\s+days", user_message, flags=_re.IGNORECASE)
                    wants_update = _re.search(r"\bupdate\b|\bwork note\b|\bset (it|state) to\b", user_message, flags=_re.IGNORECASE) is not None
                    mentions_incidents = _re.search(r"\bincidents?\b", user_message, flags=_re.IGNORECASE) is not None

                    if (name_match and mentions_incidents) or (keyword_present and mentions_incidents):
                        person = name_match.group(1) if name_match else "the specified user"
                        days = int(days_match.group(1)) if days_match else 90
                        kw = "VPN" if keyword_present else ""
                        username_guess = None
                        try:
                            if name_match:
                                parts = name_match.group(1).split()
                                if len(parts) == 2:
                                    username_guess = f"{parts[0]}.{parts[1]}"
                        except Exception:
                            pass

                        # Deterministic encoded query for incidents - use simple keyword search
                        # Let the MCP server handle date filtering properly
                        base_query_parts = []
                        if kw:
                            base_query_parts.append(f"short_descriptionLIKE{kw}")
                            base_query_parts.append(f"ORdescriptionLIKE{kw}")
                            base_query_parts.append(f"ORcaller_id.nameLIKE{kw}")
                            base_query_parts.append(f"ORopened_by.nameLIKE{kw}")
                            base_query_parts.append(f"ORassigned_to.nameLIKE{kw}")
                        
                        # Use simple keyword search without complex date filtering
                        full_query = "^".join(base_query_parts) if base_query_parts else ""

                        compound_hint = (
                            "SYSTEM TOOL HINT: This is a compound ServiceNow request. Before replying, you MUST execute these MCP tools: \n"
                            f"- sn_search_user with search_term='{person}'.\n"
                            f"- sn_get_user_incidents with name_or_username='{person}'.\n"
                            + (f"- sn_get_user_incidents with name_or_username='{username_guess}'.\n" if username_guess else "")
                            + f"- sn_search_incidents with query='{kw or 'VPN'}', limit=10.\n"
                            "Execute independent calls in parallel in the same step. Do not answer without executing these tools. "
                            "Only state 'no incidents' after BOTH user-based incident retrieval and keyword/timeframe search return no records, and after resolving the user profile."
                        )
                        if wants_update:
                            compound_hint += (
                                f"Then choose the most recent open incident that matches '{kw or 'the topic'}' and call sn_update_incident to add work_notes and set state to 'In Progress' if currently 'New'."
                            )
                        await self.send_message(thread_id, compound_hint, role="system")
                except Exception:
                    pass
        except Exception:
            pass

        # Removed URL-specific, low-level tool hint to avoid hardcoding server endpoints

        await self.send_message(thread_id, user_message)
        logger.info("   User message sent to thread")
        
        client = self._get_client()
        
        # According to official Microsoft documentation, MCP runs don't need custom tool_resources
        # Headers are handled via mcp_tool.update_headers() method
        # https://devblogs.microsoft.com/foundry/announcing-model-context-protocol-support-preview-in-azure-ai-foundry-agent-service/
        
        run = client.runs.create(
            thread_id=thread_id, 
            agent_id=self.agent.id
            # No tool_resources needed for MCP - handled automatically!
        )
        logger.info(f"   Run created successfully: {run.id}")
        logger.info("   MCP integration handled automatically by Azure AI Foundry")

        max_iterations = 25
        iterations = 0
        retry_count = 0
        max_retries = 3
        tool_calls_yielded = set()
        stuck_run_count = 0
        max_stuck_runs = 3

        while run.status in ["queued", "in_progress", "requires_action"] and iterations < max_iterations:
            iterations += 1
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

        # After run is complete, yield the assistant's response(s) with citation formatting
        messages = list(client.messages.list(thread_id=thread_id, order=ListSortOrder.ASCENDING))
        print(f"[DEBUG] Found {len(messages)} messages in thread")
        for msg in reversed(messages):
            print(f"[DEBUG] Processing message: role={msg.role}, content_count={len(msg.content) if msg.content else 0}")
            if msg.role == "assistant" and msg.content:
                for content_item in msg.content:
                    print(f"[DEBUG] Processing content item: type={type(content_item)}")
                    if hasattr(content_item, 'text'):
                        text_content = content_item.text.value
                        print(f"[DEBUG] Original text content: {text_content[:200]}...")
                        citations = []
                        # Extract citations as before
                        if hasattr(content_item.text, 'annotations') and content_item.text.annotations:
                            print(f"[DEBUG] Found {len(content_item.text.annotations)} annotations")
                            main_text = content_item.text.value if hasattr(content_item.text, 'value') else str(content_item.text)
                            for i, annotation in enumerate(content_item.text.annotations):
                                print(f"[DEBUG] Processing annotation {i}: {type(annotation)}")
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
                                    print(f"[DEBUG] Added file citation: {citation_text}")
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
                                    print(f"[DEBUG] Added file_path citation: {citation_text}")
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
                                    print(f"[DEBUG] Added URL citation: {title} -> {url}")
                        else:
                            print(f"[DEBUG] No annotations found in content item")
                        
                        print(f"[DEBUG] Total citations found: {len(citations)}")
                        if citations:
                            print(f"[DEBUG] Citations: {citations}")
                        else:
                            print(f"[DEBUG] No citations found - this is why sources are missing!")
                        formatted_response = self._format_response_with_citations(text_content, citations)
                        print(f"[DEBUG] Formatted response: {formatted_response[:200]}...")
                        print(f"[DEBUG] Full formatted response length: {len(formatted_response)}")
                        print(f"[DEBUG] Sources section in response: {'📚 Sources:' in formatted_response}")
                        if '📚 Sources:' in formatted_response:
                            sources_start = formatted_response.find('📚 Sources:')
                            print(f"[DEBUG] Sources section: {formatted_response[sources_start:sources_start+200]}...")
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
        import re
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
    

    
    def _extract_bing_citations(self, text_content: str) -> tuple[str, List[Dict]]:
        """Extract Bing search citations from the response text."""
        import re
        
        citations = []
        
        # Method 1: Look for citation patterns like [^1^], [^2^], etc.
        citation_pattern = r'\[\^(\d+)\^\]'
        citation_matches = re.findall(citation_pattern, text_content)
        
        # Method 2: Look for structured source sections
        # Bing often includes sources at the end like "Sources:\n1. Title - URL"
        source_section_pattern = r'(?:Sources?|References?):\s*\n((?:.*\n?)*)'
        source_matches = re.search(source_section_pattern, text_content, re.IGNORECASE | re.MULTILINE)
        
        if source_matches:
            source_text = source_matches.group(1)
            # Parse individual sources like "1. Title - URL"
            source_line_pattern = r'(\d+)\.\s*([^-\n]+?)\s*-\s*(https?://[^\s\n]+)'
            for match in re.finditer(source_line_pattern, source_text):
                source_num, title, url = match.groups()
                # Clean up the title by removing trailing whitespace
                clean_title = title.strip() if title else f"Source {source_num}"
                citations.append({
                    'type': 'web',
                    'text': clean_title,
                    'url': url.strip()
                })
        
        # Method 3: Look for URLs in the text (fallback)
        if not citations:
            url_pattern = r'https?://[^\s\)\]\>]+(?=[\s\)\]\>\n]|$)'
            urls = re.findall(url_pattern, text_content)
            
            # Try to find context around URLs for better link text
            for i, url in enumerate(urls[:5]):  # Limit to first 5 URLs
                # Look for text before the URL that might be a title
                url_context_pattern = rf'([^.\n]*?)\s*{re.escape(url)}'
                context_match = re.search(url_context_pattern, text_content)
                
                if context_match:
                    context = context_match.group(1).strip()
                    # Clean up the context to get a reasonable title
                    title = context[-50:] if len(context) > 50 else context
                    title = title.strip('.,;:')
                else:
                    title = f"Web Source {i+1}"
                
                citations.append({
                    'type': 'web',
                    'text': title or f"Web Source {i+1}",
                    'url': url
                })
        
        return text_content, citations
    
    def _extract_foundry_citations(self, text_content: str) -> List[Dict]:
        """Extract Azure AI Foundry style citations like 【4:4†source】."""
        import re
        
        citations = []
        
        # Look for Azure AI Foundry citation patterns with Japanese brackets 【4:4†source】
        foundry_pattern = r'【(\d+):(\d+)†source】'
        foundry_matches = re.findall(foundry_pattern, text_content)
        
        if foundry_matches:
            # These citations reference file search results
            for i, (doc_num, ref_num) in enumerate(foundry_matches):
                citations.append({
                    'type': 'file',
                    'text': f"Document {doc_num} (Reference {ref_num})",
                    'file_id': f"doc_{doc_num}_{ref_num}",  # Placeholder since we don't have the actual file ID
                    'quote': ''
                })
        
        return citations

    async def _handle_tool_calls(self, run: ThreadRun, thread_id: str):
        """Handle tool calls during agent execution, including MCP tool approval."""
        logger.info(f"Handling tool calls for run {run.id}")
        
        if not hasattr(run, 'required_action') or not run.required_action:
            logger.warning(f"No required action found in run {run.id}")
            return
            
        required_action = run.required_action
        logger.info(f"Required action type: {type(required_action)}")
        logger.info(f"Required action attributes: {dir(required_action)}")
        
        # Check if this is a SubmitToolApprovalAction (MCP tools)
        if hasattr(required_action, 'submit_tool_approval') and required_action.submit_tool_approval:
            logger.info("🔧 MCP TOOL APPROVAL REQUIRED - Implementing official Microsoft pattern")
            await self._handle_mcp_tool_approval(run, thread_id, required_action)
            return
            
        # Legacy tool output handling (for non-MCP tools)
        if hasattr(required_action, 'submit_tool_outputs') and required_action.submit_tool_outputs:
            logger.info("🔄 Legacy tool output handling (non-MCP tools)")
            await self._handle_legacy_tool_outputs(run, thread_id, required_action)
            return
            
        logger.warning(f"Unknown required action type: {type(required_action)}")

    async def _handle_mcp_tool_approval(self, run: ThreadRun, thread_id: str, required_action):
        """Handle MCP tool approval using the official Microsoft pattern."""
        logger.info("🚀 IMPLEMENTING MCP TOOL APPROVAL...")
        
        try:
            tool_calls = required_action.submit_tool_approval.tool_calls
            if not tool_calls:
                logger.warning("No tool calls provided - cancelling run")
                client = self._get_client()
                client.runs.cancel(thread_id=thread_id, run_id=run.id)
                return
            
            logger.info(f"Found {len(tool_calls)} MCP tool calls to approve")
            
            tool_approvals = []
            for tool_call in tool_calls:
                logger.info(f"🔧 Processing MCP tool call: {tool_call}")
                
                # Check if this is an MCP tool call
                if hasattr(tool_call, 'type') and tool_call.type == 'mcp':
                    logger.info(f"✅ MCP tool call detected: {tool_call.name}")
                    logger.info(f"   Arguments: {tool_call.arguments}")
                    logger.info(f"   Server label: {tool_call.server_label}")
                    
                    try:
                        # Create tool approval for MCP tools
                        tool_approval = ToolApproval(
                            tool_call_id=tool_call.id,
                            approve=True,
                            headers=self._mcp_tool.headers if hasattr(self, '_mcp_tool') else {},
                        )
                        tool_approvals.append(tool_approval)
                        logger.info(f"✅ Created tool approval for MCP tool: {tool_call.name}")
                        
                    except Exception as e:
                        logger.error(f"❌ Error creating tool approval for {tool_call.id}: {e}")
                        logger.error(f"   Tool call object: {tool_call}")
                        logger.error(f"   Tool call attributes: {dir(tool_call)}")
                else:
                    logger.warning(f"⚠️ Non-MCP tool call detected: {getattr(tool_call, 'type', 'unknown')}")
            
            # Submit all tool approvals
            if tool_approvals:
                logger.info(f"🚀 Submitting {len(tool_approvals)} MCP tool approvals...")
                client = self._get_client()
                
                try:
                    client.runs.submit_tool_outputs(
                        thread_id=thread_id,
                        run_id=run.id,
                        tool_approvals=tool_approvals
                    )
                    logger.info("✅ MCP tool approvals submitted successfully!")
                    logger.info("   Azure AI Foundry will now execute the MCP tools")
                    logger.info("   Check MCP server logs for incoming requests")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to submit MCP tool approvals: {e}")
                    logger.error(f"   Error type: {type(e)}")
                    import traceback
                    logger.error(f"   Full traceback: {traceback.format_exc()}")
                    
                    # Try to get more error details
                    if hasattr(e, 'response') and hasattr(e.response, 'text'):
                        logger.error(f"   Response text: {e.response.text}")
                    if hasattr(e, 'status_code'):
                        logger.error(f"   Status code: {e.status_code}")
            else:
                logger.warning("⚠️ No MCP tool approvals created - cancelling run")
                client = self._get_client()
                client.runs.cancel(thread_id=thread_id, run_id=run.id)
                
        except Exception as e:
            logger.error(f"❌ ERROR IN MCP TOOL APPROVAL: {e}")
            logger.error(f"   Error type: {type(e)}")
            import traceback
            logger.error(f"   Full traceback: {traceback.format_exc()}")
            
            # Try to cancel the run to prevent it from hanging
            try:
                client = self._get_client()
                client.runs.cancel(thread_id=thread_id, run_id=run.id)
                logger.info("✅ Run cancelled due to MCP tool approval error")
            except Exception as cancel_error:
                logger.error(f"❌ Failed to cancel run: {cancel_error}")

    async def _handle_legacy_tool_outputs(self, run: ThreadRun, thread_id: str, required_action):
        """Handle legacy tool output submission (for non-MCP tools)."""
        logger.info("🔄 Processing legacy tool outputs...")
        
        try:
            tool_calls = required_action.submit_tool_outputs.tool_calls
            if not tool_calls:
                logger.warning("No tool calls found in required action")
                return
            
            tool_outputs = []

            async def handle_single_tool_call(tool_call):
                function_name = tool_call.function.name
                arguments = tool_call.function.arguments
                logger.info(f"🔧 PROCESSING TOOL CALL: {function_name}")
                logger.info(f"   Arguments: {arguments}")
                logger.info(f"   Tool call ID: {tool_call.id}")
                logger.info(f"   Tool call type: {type(tool_call)}")
                
                # Enhanced logging for MCP tool calls
                if hasattr(tool_call, 'type'):
                    logger.info(f"   Tool call type attribute: {tool_call.type}")
                    if tool_call.type == 'mcp':
                        logger.info(f"🔧 MCP TOOL CALL BEING PROCESSED!")
                        logger.info(f"   This indicates Azure Foundry successfully connected to MCP server")
                        logger.info(f"   But the tool execution might fail due to protocol issues")
                
                # Log all available attributes for debugging
                logger.debug(f"🔍 ALL TOOL CALL ATTRIBUTES:")
                for attr in dir(tool_call):
                    if not attr.startswith('_'):
                        try:
                            value = getattr(tool_call, attr)
                            logger.debug(f"     {attr}: {value}")
                        except:
                            logger.debug(f"     {attr}: <could not access>")
                
                # Handle Salesforce tool responses - let LLM generate realistic data dynamically
                if function_name.startswith("sf_"):
                    import json
                    try:
                        args = json.loads(arguments) if isinstance(arguments, str) else arguments
                    except:
                        args = {}
                    
                    # Simple, dynamic approach - let LLM handle all the details
                    output = {
                        "status": "success",
                        "function": function_name,
                        "parameters": args,
                        "instruction": "Generate realistic ServiceNow data for this operation. Create appropriate ServiceNow records with realistic field values, proper formatting, and authentic-looking data."
                    }
                    
                    return {
                        "tool_call_id": tool_call.id,
                        "output": json.dumps(output)
                    }
                # --- Bank action simulation using LLM for dynamic responses ---
                elif function_name == "bank_action":
                    import json
                    from datetime import datetime
                    try:
                        args = json.loads(arguments) if isinstance(arguments, str) else arguments
                    except:
                        args = {}
                    action = args.get("action", "unknown_action")
                    params = args.get("parameters", {})
                    
                    # Let LLM generate realistic synthetic data dynamically
                    output = {
                        "status": "success",
                        "function": function_name,
                        "parameters": args,
                        "instruction": f"""Generate realistic Bank system data for the '{action}' operation. Create appropriate Bank records with realistic field values, proper formatting, and authentic-looking data. Include realistic IDs, timestamps, status messages, and processing times. Make the response look like it came from a real banking system.

IMPORTANT: After generating the technical response data, provide a detailed customer-friendly explanation that includes SPECIFIC DETAILS:

1. **Include specific account/card details**: Use the actual card numbers, account IDs, transaction IDs, amounts, merchant names, etc. from the parameters provided
2. **Personalize the response**: If a customer name is mentioned (like "David Miller"), include their name and any relevant account details
3. **Show exact amounts and dates**: Use the specific amounts, dates, and transaction details provided
4. **Include realistic account information**: Generate realistic account numbers, card numbers, routing numbers, etc.
5. **Provide specific next steps**: Give exact timelines, reference numbers, and contact details

Example: Instead of "Your card has been blocked", say "David Miller's credit card ending in 5678 (Account #1234567890) has been blocked. The card was issued on 03/15/2022 and had a credit limit of $10,000."

The response should include both the technical system response AND the customer-friendly explanation."""
                    }
                    
                    return {
                        "tool_call_id": tool_call.id,
                        "output": json.dumps(output)
                    }
                # --- Calendar action simulation using LLM for dynamic responses ---
                elif function_name == "calendar_action":
                    import json
                    from datetime import datetime, timedelta
                    try:
                        args = json.loads(arguments) if isinstance(arguments, str) else arguments
                    except:
                        args = {}
                    action = args.get("action", "unknown_action")
                    params = args.get("parameters", {})
                    
                    # Let LLM generate realistic synthetic data dynamically
                    output = {
                        "status": "success",
                        "function": function_name,
                        "parameters": args,
                        "instruction": f"""Generate realistic Calendar system data for the '{action}' operation. Create appropriate Calendar records with realistic field values, proper formatting, and authentic-looking data. Include realistic event IDs, timestamps, attendee lists, and calendar details. Make the response look like it came from a real calendar system.

IMPORTANT: After generating the technical response data, provide a detailed user-friendly explanation that includes SPECIFIC DETAILS:

1. **Include specific event details**: Use the actual event names, dates, times, locations, and attendee information from the parameters provided
2. **Personalize the response**: If a person's name is mentioned, include their name and any relevant calendar details
3. **Show exact dates and times**: Use the specific dates, times, and duration details provided
4. **Include realistic calendar information**: Generate realistic event IDs, calendar IDs, and meeting links
5. **Provide specific next steps**: Give exact confirmation details, reminder times, and follow-up actions

Example: Instead of "Meeting scheduled", say "Team Standup meeting scheduled for David Miller on Friday, March 15th, 2024 from 9:00 AM to 9:30 AM EST. Meeting ID: CAL-2024-0315-0900, Calendar: Work Calendar. Reminder set for 15 minutes before. Attendees: David Miller, Sarah Johnson, Mike Chen."

The response should include both the technical system response AND the user-friendly explanation."""
                    }
                    
                    return {
                        "tool_call_id": tool_call.id,
                        "output": json.dumps(output)
                    }
                # --- Web search simulation using LLM for dynamic responses ---
                elif function_name == "web_search":
                    import json
                    try:
                        args = json.loads(arguments) if isinstance(arguments, str) else arguments
                    except:
                        args = {}
                    query = args.get("query", "unknown query")
                    
                    # Let LLM generate realistic synthetic data dynamically
                    output = {
                        "status": "success",
                        "function": function_name,
                        "parameters": args,
                        "instruction": f"""Generate realistic web search results for the query: '{query}'. Create appropriate search results with realistic URLs, titles, snippets, and relevance scores. Make the response look like it came from a real web search engine.

IMPORTANT: After generating the technical response data, provide a detailed user-friendly explanation that includes SPECIFIC DETAILS:

1. **Include specific search details**: Use the actual query terms, search parameters, and filters from the parameters provided
2. **Personalize the response**: If specific terms or context are mentioned, include them in the search results
3. **Show exact search results**: Use the specific query, number of results, and search scope provided
4. **Include realistic search information**: Generate realistic URLs, titles, snippets, and relevance scores
5. **Provide specific next steps**: Give exact result counts, pagination details, and refinement suggestions

Example: Instead of "Search completed", say "Web search completed for 'Azure AI Foundry MCP integration' with 1,247 results found. Top result: 'Getting Started with MCP in Azure AI Foundry' from Microsoft Docs (https://docs.microsoft.com/azure/ai-foundry/mcp-integration) with 98% relevance. Search completed in 0.23 seconds. Showing results 1-10 of 1,247."

The response should include both the technical system response AND the user-friendly explanation."""
                    }
                    
                    return {
                        "tool_call_id": tool_call.id,
                        "output": json.dumps(output)
                    }
                else:
                    # For unknown functions, return a generic success response
                    return {
                        "tool_call_id": tool_call.id,
                        "output": json.dumps({
                            "status": "success",
                            "function": function_name,
                            "message": f"Function {function_name} executed successfully with arguments: {arguments}"
                        })
                    }

            # Process all tool calls concurrently
            tasks = [handle_single_tool_call(tool_call) for tool_call in tool_calls]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Filter out exceptions and collect valid outputs
            for result in results:
                if isinstance(result, dict) and "tool_call_id" in result and "output" in result:
                    tool_outputs.append(ToolOutput(**result))
                else:
                    logger.error(f"Invalid tool call result: {result}")

            # Submit tool outputs
            if tool_outputs:
                logger.info(f"Submitting {len(tool_outputs)} tool outputs")
                client = self._get_client()
                client.runs.submit_tool_outputs(
                    thread_id=thread_id,
                    run_id=run.id,
                    tool_outputs=tool_outputs
                )
                logger.info("Tool outputs submitted successfully")
            else:
                logger.warning("No valid tool outputs to submit")

        except Exception as e:
            logger.error(f"Error handling tool calls: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")

    async def cleanup_agent(self):
        """Clean up the agent resources (individual instance only)."""
        # DISABLED: Don't auto-delete the agent to allow reuse across multiple requests
        # if self.agent:
        #     client = self._get_client()
        #     client.delete_agent(self.agent.id)
        #     logger.info(f"Deleted agent: {self.agent.id}")
        #     self.agent = None
        
        # Clear cached clients but keep the agent alive
        # self._agents_client = None
        # self._project_client = None
        
        # Note: Agent is preserved for reuse, shared file search resources are left for other instances to use
        logger.info("Individual agent cleanup completed (agent preserved for reuse, shared resources preserved)")
    
    @classmethod
    async def cleanup_shared_resources(cls):
        """Clean up shared file search resources (call when shutting down completely)."""
        try:
            if cls._shared_vector_store or cls._shared_uploaded_files:
                # We need a project client to clean up, create a temporary one
                temp_agent = cls()
                project_client = temp_agent._get_project_client()
                
                # Delete vector store
                if cls._shared_vector_store:
                    project_client.agents.delete_vector_store(cls._shared_vector_store.id)
                    logger.info(f"Deleted shared vector store: {cls._shared_vector_store.id}")
                    cls._shared_vector_store = None
            
                # Delete uploaded files
                for file_id in cls._shared_uploaded_files:
                    try:
                        project_client.agents.delete_file(file_id=file_id)
                        logger.info(f"Deleted shared file: {file_id}")
                    except Exception as e:
                        logger.warning(f"Failed to delete shared file {file_id}: {e}")
                
                cls._shared_uploaded_files = []
                cls._shared_file_search_tool = None
                logger.info("Shared file search resources cleaned up")
                
        except Exception as e:
            logger.error(f"Error cleaning up shared file search resources: {e}")



    def _get_readable_file_name(self, citation: Dict) -> str:
        """Get meaningful citation text based on content, not just file names."""
        
        # Priority 1: Use actual quote/content if available and meaningful
        quote = citation.get('quote', '').strip()
        if quote and len(quote) > 20:  # Ensure substantial content
            # Clean and truncate the quote for readability
            clean_quote = quote.replace('\n', ' ').replace('\r', ' ')
            if len(clean_quote) > 100:
                clean_quote = clean_quote[:97] + "..."
            return f'"{clean_quote}"'
        
        # Priority 2: Extract meaningful content from the citation text itself
        citation_text = citation.get('text', '').strip()
        if citation_text and 'Document excerpt:' in citation_text:
            # Already formatted as an excerpt
            return citation_text
        
        # Priority 3: Try to create meaningful content from available text
        if citation_text and len(citation_text) > 20:
            clean_text = citation_text.replace('\n', ' ').replace('\r', ' ')
            if len(clean_text) > 100:
                clean_text = clean_text[:97] + "..."
            return f'Document excerpt: "{clean_text}"'
        
        # Priority 4: Use file information if available
        file_id = citation.get('file_id', '')
        if file_id:
            return f"Document (ID: {file_id[-8:]})"  # Use last 8 chars for brevity
        
        # Fallback: Generic but still informative
        source_type = citation.get('type', 'document')
        return f"Referenced {source_type}"

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
                        elif function_name.startswith("sf_"):
                            # Handle ServiceNow-like functions (legacy names retained in code paths)
                            if function_name == "sf_create_case":
                                subject = args.get('subject', '')[:50]
                                return f"Creating ServiceNow incident: '{subject}{'...' if len(subject) == 50 else ''}'"
                            elif function_name == "sf_search_cases":
                                query = args.get('query', args.get('category', ''))
                                return f"Searching ServiceNow incidents for: '{query[:50]}{'...' if len(query) > 50 else ''}'"
                            elif function_name == "sf_get_case":
                                case_id = args.get('case_id', '')
                                return f"Retrieving ServiceNow incident: {case_id}"
                            elif function_name == "sf_search_user":
                                search_term = args.get('search_term', '')
                                return f"Searching ServiceNow users for: '{search_term[:30]}{'...' if len(search_term) > 30 else ''}'"
                            elif function_name == "sf_get_user_cases":
                                username = args.get('username', '')
                                return f"Getting incidents for user: {username[:30]}{'...' if len(username) > 30 else ''}"
                            elif function_name == "sf_update_case":
                                case_id = args.get('case_id', '')
                                return f"Updating ServiceNow incident: {case_id}"
                            elif function_name == "sf_list_users":
                                dept = args.get('department', 'all departments')
                                return f"Listing ServiceNow users in: {dept}"
                            elif function_name == "sf_search_knowledge":
                                query = args.get('query', '')
                                return f"Searching ServiceNow knowledge base for: '{query[:50]}{'...' if len(query) > 50 else ''}'"
                            elif function_name == "bank_action":
                                action = args.get('action', 'unknown_action')
                                if action == "block_card":
                                    card_num = args.get('parameters', {}).get('card_number', 'XXXX')
                                    return f"Blocking credit card ending in {str(card_num)[-4:]}"
                                elif action == "unblock_card":
                                    card_num = args.get('parameters', {}).get('card_number', 'XXXX')
                                    return f"Unblocking credit card ending in {str(card_num)[-4:]}"
                                elif action == "create_dispute":
                                    amount = args.get('parameters', {}).get('amount', '$0.00')
                                    merchant = args.get('parameters', {}).get('merchant_name', 'Unknown')
                                    return f"Creating dispute for {amount} at {merchant}"
                                elif action == "issue_refund":
                                    amount = args.get('parameters', {}).get('amount', '$0.00')
                                    merchant = args.get('parameters', {}).get('merchant_name', 'Unknown')
                                    return f"Issuing refund of {amount} from {merchant}"
                                elif action == "check_balance":
                                    return f"Checking account balance"
                                elif action == "report_fraud":
                                    card_num = args.get('parameters', {}).get('card_number', 'XXXX')
                                    return f"Reporting fraud for card ending in {str(card_num)[-4:]}"
                                elif action == "check_transaction":
                                    tx_id = args.get('parameters', {}).get('transaction_id', 'Unknown')
                                    return f"Checking transaction {tx_id}"
                                else:
                                    return f"Simulating Bank action: {action}"
                            else:
                                return f"Executing Salesforce function: {function_name.replace('sf_', '').replace('_', ' ')}"
                        elif function_name.startswith("search_"):
                            search_term = args.get('search_term', args.get('query', ''))
                            if search_term:
                                return f"Searching ServiceNow for: '{search_term[:50]}{'...' if len(search_term) > 50 else ''}'"
                            else:
                                return f"Executing {function_name} in ServiceNow"
                        elif function_name.startswith("get_"):
                            return f"Retrieving {function_name.replace('get_', '').replace('_', ' ')} from ServiceNow"
                        elif function_name.startswith("create_"):
                            return f"Creating new {function_name.replace('create_', '').replace('_', ' ')} in ServiceNow"
                        elif function_name.startswith("list_"):
                            return f"Listing {function_name.replace('list_', '').replace('_', ' ')} from ServiceNow"
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




async def create_foundry_SN_agent() -> FoundrySNAgent:
    """Factory function to create and initialize a Foundry calendar and search agent."""
    agent = FoundrySNAgent()
    await agent.create_agent()
    return agent


# Example usage for testing
async def demo_agent_interaction():
    """Demo function showing how to use the Foundry calendar, web search, and file search agent."""
    agent = await create_foundry_SN_agent()
    
    try:
        # Create a conversation thread
        thread = await agent.create_thread()
        
        # Example interaction
        message = "Hello! Can you help me with my calendar, searching for information, finding content in documents, and managing ServiceNow incidents?"
        print(f"\nUser: {message}")
        async for response in agent.run_conversation(thread.id, message):
            print(f"Assistant: {response}")
                
    finally:
        # DISABLED: Don't auto-cleanup agent to allow reuse
        # await agent.cleanup_agent()
        # Only clean up shared resources on final shutdown if really needed
        # await FoundrySNAgent.cleanup_shared_resources()
        logger.info("Demo completed - agent preserved for reuse")


def test_citation_improvement():
    """Test function to demonstrate citation improvements."""
    agent = FoundrySNAgent()
    
    # Simulate the old problematic citation format
    old_citations = [
        {'type': 'file', 'text': 'Document Citation (【4:0†source】)', 'file_id': 'file123', 'quote': 'For Bank, the 24/7 number is 1-800-950-5114'},
        {'type': 'file', 'text': 'Document Citation (【4:0†source】)', 'file_id': 'file123', 'quote': 'For Bank, the 24/7 number is 1-800-950-5114'},
        {'type': 'file', 'text': 'Document Citation (【4:2†source】)', 'file_id': 'file123', 'quote': 'Federal laws limit consumer liability to $50'},
        {'type': 'file', 'text': 'Document 4 (Reference 0)', 'file_id': 'file123', 'quote': ''},
        {'type': 'file', 'text': 'Document 4 (Reference 0)', 'file_id': 'file123', 'quote': ''},
        {'type': 'file', 'text': 'Document 4 (Reference 2)', 'file_id': 'file123', 'quote': ''},
    ]
    
    test_response = """To handle a stolen credit card incident, follow the steps below:
Immediate Reporting:
Notify the bank immediately by calling their lost card hotline. For Bank, the 24/7 number is 1-800-950-5114 (for U.S. credit cards)【4:0†source】.
Alternatively, customers can use the bank's online account or mobile app to report the card as stolen and in some cases, lock or freeze the card temporarily【4:0†source】.
Card Deactivation and Replacement:
The bank will deactivate the stolen card to prevent unauthorized use.
A replacement card will be issued within 5-7 business days; expedited delivery may be available for a fee【4:0†source】.
Fraudulent Charges Check:
Review recent account transactions. Report any suspicious or unauthorized charges alongside lodging the stolen card report【4:0†source】.
The bank's fraud team will handle disputes and potentially provide refunds for fraudulent activities once the investigation confirms them【4:0†source】.
Update Recurring Payments:
Update any automatic payments or saved card details with the newly issued card information to prevent interruptions in payments【4:0†source】.
Legal and Security Actions:
Consider filing a fraud alert with major credit bureaus or even a police report if identity theft is suspected【4:2†source】.
Continue to monitor accounts for any further unauthorized transactions【4:2†source】.
Liability Protection:
Timely reporting ensures you are not held liable for unauthorized charges. Federal laws limit consumer liability to $50, but Citibank's policy is $0 for confirmed fraud cases【4:2†source】.
Following these actions promptly helps minimize losses and ensures a quick resolution."""
    
    # Test the improved citation formatting
    improved_response = agent._format_response_with_citations(test_response, old_citations)
    
    print("=== CITATION IMPROVEMENT DEMONSTRATION ===")
    print("\nOLD FORMAT (before improvement):")
    print("- Multiple identical 'Document Citation (【4:0†source】)' entries")
    print("- Generic 'Document 4 (Reference 0)' without context")
    print("- No actual file names or meaningful descriptions")
    print("- Repetitive and cluttered sources section")
    
    print("\nNEW FORMAT (after improvement):")
    print(improved_response)
    
    return improved_response


if __name__ == "__main__":
    asyncio.run(demo_agent_interaction())