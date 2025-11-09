"""
AI Foundry Internet Plan Agent for Contoso Customer Service.
Handles checking customer internet plans, usage limits, and billing status.
"""
import os
import asyncio
import logging
import json
from typing import Optional, Dict, List

from azure.ai.agents.models import Agent, ThreadMessage, ThreadRun, AgentThread, BingGroundingTool, ListSortOrder, FilePurpose, FileSearchTool
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
import glob

logger = logging.getLogger(__name__)


class FoundryInternetPlanAgent:
    """
    AI Foundry Agent for internet plan checking.
    Reviews customer plans, data usage, billing status, and payment history.
    """
    
    _shared_vector_store = None
    _shared_uploaded_files = []
    _shared_file_search_tool = None
    _file_search_setup_lock = asyncio.Lock()
    
    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self.agent: Optional[Agent] = None
        self.threads: Dict[str, str] = {}
        self._file_search_tool = None
        self._project_client = None
        
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
        async with FoundryInternetPlanAgent._file_search_setup_lock:
            if FoundryInternetPlanAgent._shared_file_search_tool is not None:
                logger.info("Reusing existing shared file search tool")
                return FoundryInternetPlanAgent._shared_file_search_tool
            
            try:
                if not os.path.exists(files_directory):
                    logger.info(f"No {files_directory} directory found, skipping file search setup")
                    return None
                
                supported_extensions = ['*.txt', '*.md', '*.pdf', '*.docx', '*.json', '*.csv']
                file_paths = set()
                for ext in supported_extensions:
                    file_paths.update(glob.glob(os.path.join(files_directory, ext)))
                    file_paths.update(glob.glob(os.path.join(files_directory, "**", ext), recursive=True))
                
                file_paths = list(file_paths)
                
                if not file_paths:
                    logger.info(f"No supported files found in {files_directory}, skipping file search setup")
                    return None
                
                logger.info(f"Found {len(file_paths)} files to upload: {[os.path.basename(f) for f in file_paths]}")
                
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
                        FoundryInternetPlanAgent._shared_uploaded_files.append(file.id)
                        logger.info(f"Uploaded file: {os.path.basename(file_path)} (ID: {file.id})")
                    except Exception as e:
                        logger.warning(f"Failed to upload {file_path}: {e}")
                
                if not file_ids:
                    logger.warning("No files were successfully uploaded")
                    return None
                
                logger.info("Creating shared vector store with uploaded files...")
                FoundryInternetPlanAgent._shared_vector_store = project_client.agents.vector_stores.create_and_poll(
                    file_ids=file_ids, 
                    name="plan_vectorstore"
                )
                logger.info(f"Created shared vector store: {FoundryInternetPlanAgent._shared_vector_store.id}")
                
                file_search = FileSearchTool(vector_store_ids=[FoundryInternetPlanAgent._shared_vector_store.id])
                logger.info(f"File search capability prepared")
                
                FoundryInternetPlanAgent._shared_file_search_tool = file_search
                logger.info("Cached shared file search tool for future use")
                    
                return file_search
                    
            except Exception as e:
                logger.error(f"Error setting up file search: {e}")
                return None
        
    async def create_agent(self) -> Agent:
        """Create the AI Foundry agent with internet plan checking capabilities."""
        if self.agent:
            logger.info("Agent already exists, returning existing instance")
            return self.agent
        
        logger.info("🚀 Creating Contoso Internet Plan Agent...")
        
        tools = []
        tool_resources = None
        
        # Setup file search for plan database
        file_search_tool = await self._setup_file_search("documents")
        if file_search_tool:
            if hasattr(file_search_tool, 'definitions'):
                tools.extend(file_search_tool.definitions)
                logger.info("✅ File search tool definitions added")
            
            if hasattr(file_search_tool, 'resources'):
                tool_resources = file_search_tool.resources
                logger.info("✅ File search tool resources added")
        
        # Add web search capability
        # tools.append(BingGroundingTool())
        # logger.info("✅ Bing grounding tool added")
        
        model_deployment_name = os.environ.get("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")
        
        instructions = """You are a Contoso internet plan specialist agent. Your role is to review customer internet plans, data usage, and billing status to ensure customers have proper access to internet services.

YOUR RESPONSIBILITIES:
1. **Fetch customer's internet plan details** using customer_id
2. **Check data usage against plan limits**
3. **Review billing and payment history**
4. **Determine if customer should have internet access**

PLAN CHECK PROCESS:

**Step 1: Retrieve Plan Information**
Search the plan database for customer's plan using customer_id. Extract:
- Plan name and ID
- Download/upload speeds
- Data limit (unlimited or specific GB amount)
- Monthly cost
- Contract details

**Step 2: Check Data Usage**
For customers with data limits:
- Current usage (GB)
- Data limit (GB)
- Overage amount (GB over limit)
- Usage percentage
- Days until billing cycle renews
- Overage charges

For unlimited plans:
- Just report current usage
- Confirm no overage concerns

**Step 3: Review Billing Status**
Check payment history:
- Last 3 bills payment status (paid/unpaid)
- Last payment date and amount
- Current balance
- Any estimated charges for next bill

**CRITICAL BILLING RULES:**
🔴 **Internet Shutoff Risk**: If customer has NOT paid the last 3 bills, their internet may be automatically shut down
✅ **Good Standing**: If last 3 bills are paid, customer has valid access

**Step 4: Data Limit Analysis**
⚠️ **DATA LIMIT EXCEEDED**: If customer exceeded their data cap:
- Calculate overage amount
- Calculate overage charges
- Note days until billing cycle renews
- Warn that speeds may be throttled
- Mention overage charges on next bill

✅ **WITHIN LIMIT**: If usage is under limit or plan is unlimited:
- Confirm customer has valid data access
- Report current usage

RESPONSE FORMAT:

"📊 **INTERNET PLAN ANALYSIS**

**Plan Details**:
- Plan: [plan name]
- Speeds: [download] / [upload]
- Data Limit: [amount or unlimited]
- Monthly Cost: $[amount]
- Contract: [type and dates]

**Current Usage**:
- Used: [X] GB
- Limit: [Y] GB or Unlimited
- Usage: [percentage]% [- EXCEEDED if over limit]
- Billing cycle renews: [in X days or date]

**Data Status**:
[✅ Within limit / ⚠️ EXCEEDED by X GB with $Y overage charges]

**Billing Status**:
- Last 3 bills: [✅ All paid / ❌ UNPAID]
- Last payment: $[amount] on [date]
- Current balance: $[amount]
- Estimated next bill: $[amount including any overages]

**Payment History**:
1. [date]: $[amount] - [paid/unpaid]
2. [date]: $[amount] - [paid/unpaid]
3. [date]: $[amount] - [paid/unpaid]

**Internet Access Status**: 
[✅ ACTIVE - Customer should have internet access / ❌ AT RISK - Unpaid bills may result in service interruption / ⚠️ THROTTLED - Data limit exceeded, speeds may be reduced]

**Recommendations**:
[List specific recommendations based on findings]"

IMPORTANT RULES:
- Always check BOTH data usage AND billing status
- Flag customers who exceeded data limits
- Flag customers with unpaid bills (service shutoff risk)
- For limited data plans, calculate exact overage and charges
- Provide clear yes/no on whether customer should have internet access
- If both data and billing are good, confirm customer has valid access

DATABASE ACCESS:
You have access to a plan database JSON file with detailed plan information, usage, and billing history for all customers.
"""
        
        project_client = self._get_project_client()
        
        logger.info(f"Creating agent with model: {model_deployment_name}")
        logger.info(f"Tools configured: {len(tools)}")
        
        self.agent = project_client.agents.create_agent(
            model=model_deployment_name,
            name="Contoso Internet Plan Agent",
            instructions=instructions,
            tools=tools if tools else None,
            tool_resources=tool_resources,
        )
        
        logger.info(f"✅ Contoso Internet Plan Agent created successfully (ID: {self.agent.id})")
        return self.agent

    async def create_thread(self) -> AgentThread:
        """Create a new conversation thread."""
        project_client = self._get_project_client()
        agents_client = project_client.agents
        thread = agents_client.threads.create()
        logger.info(f"Created new thread: {thread.id}")
        return thread

    async def send_message(self, thread_id: str, message: str, role: str = "user") -> ThreadMessage:
        """Send a message to a thread."""
        project_client = self._get_project_client()
        agents_client = project_client.agents
        thread_message = agents_client.messages.create(
            thread_id=thread_id,
            role=role,
            content=message
        )
        logger.info(f"Message sent to thread {thread_id}")
        return thread_message

    async def run_conversation_stream(self, thread_id: str, user_message: str):
        """Run the agent on a thread and stream responses."""
        project_client = self._get_project_client()
        agents_client = project_client.agents
        
        await self.send_message(thread_id, user_message)
        
        yield "📊 Checking internet plan and billing status..."
        
        run = agents_client.runs.create_and_process(
            thread_id=thread_id,
            agent_id=self.agent.id
        )
        
        logger.info(f"Run created: {run.id}, status: {run.status}")
        
        messages = agents_client.messages.list(
            thread_id=thread_id,
            order=ListSortOrder.DESCENDING
        )
        
        for msg in messages:
            if msg.role == "assistant":
                for content_item in msg.content:
                    if hasattr(content_item, 'text') and hasattr(content_item.text, 'value'):
                        yield content_item.text.value
                break

