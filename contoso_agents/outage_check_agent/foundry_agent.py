"""
AI Foundry Outage Check Agent for Contoso Customer Service.
Handles checking for local and regional internet outages.
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


class FoundryOutageCheckAgent:
    """
    AI Foundry Agent for checking internet outages.
    Checks both local (address-specific) and regional outages.
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
        async with FoundryOutageCheckAgent._file_search_setup_lock:
            if FoundryOutageCheckAgent._shared_file_search_tool is not None:
                logger.info("Reusing existing shared file search tool")
                return FoundryOutageCheckAgent._shared_file_search_tool
            
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
                        FoundryOutageCheckAgent._shared_uploaded_files.append(file.id)
                        logger.info(f"Uploaded file: {os.path.basename(file_path)} (ID: {file.id})")
                    except Exception as e:
                        logger.warning(f"Failed to upload {file_path}: {e}")
                
                if not file_ids:
                    logger.warning("No files were successfully uploaded")
                    return None
                
                logger.info("Creating shared vector store with uploaded files...")
                FoundryOutageCheckAgent._shared_vector_store = project_client.agents.vector_stores.create_and_poll(
                    file_ids=file_ids, 
                    name="outage_vectorstore"
                )
                logger.info(f"Created shared vector store: {FoundryOutageCheckAgent._shared_vector_store.id}")
                
                file_search = FileSearchTool(vector_store_ids=[FoundryOutageCheckAgent._shared_vector_store.id])
                logger.info(f"File search capability prepared")
                
                FoundryOutageCheckAgent._shared_file_search_tool = file_search
                logger.info("Cached shared file search tool for future use")
                    
                return file_search
                    
            except Exception as e:
                logger.error(f"Error setting up file search: {e}")
                return None
        
    async def create_agent(self) -> Agent:
        """Create the AI Foundry agent with outage checking capabilities."""
        if self.agent:
            logger.info("Agent already exists, returning existing instance")
            return self.agent
        
        logger.info("🚀 Creating Contoso Outage Check Agent...")
        
        tools = []
        tool_resources = None
        
        # Setup file search for outage database
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
        
        instructions = """You are a Contoso outage check agent. Your role is to check for internet outages affecting customers.

OUTAGE CHECK PROCESS:
When given a customer_id, address, postal code, or region, you must:

1. **Check for LOCAL outages first**:
   - Search the outage database for local outages matching the customer's address or postal code
   - Local outages are specific to a particular address or small area
   - Look in the "local_outages" section and "customer_outage_status" section

2. **If NO local outage found, check for REGIONAL outages**:
   - Search for regional outages affecting the customer's region
   - Regional outages affect a broader area (multiple postal codes)
   - Look in the "regional_outages" section

OUTAGE REPORTING:
When reporting outages, include:
- Outage ID
- Outage type (local or regional)
- Status (active, monitoring, resolved)
- Affected services (internet, tv, phone)
- Cause/reason for outage
- Reported time and estimated resolution time
- Number of affected customers
- Latest update message
- Whether technicians have been dispatched

RESPONSE FORMATS:
✅ **LOCAL OUTAGE FOUND**:
"🔴 Local outage detected for your address!
- Outage ID: [ID]
- Status: [status]
- Affected services: [services]
- Cause: [cause]
- Reported: [time]
- Estimated resolution: [time]
- Customers affected: [count]
- Latest update: [latest update message]
- Technicians dispatched: [yes/no]"

✅ **REGIONAL OUTAGE FOUND (no local)**:
"🟡 Regional outage detected in your area!
- Outage ID: [ID]
- Region: [region]
- Status: [status]
- Affected services: [services]
- Cause: [cause]
- Reported: [time]
- Estimated resolution: [time]
- Customers affected: [count]
- Latest update: [latest update message]"

✅ **NO OUTAGES FOUND**:
"✅ No outages detected for your address or region. Your connectivity issue may be specific to your equipment or configuration. Further diagnostics recommended."

IMPORTANT RULES:
- Always check local first, then regional
- Be clear about what type of outage was found
- Provide realistic estimated resolution times
- If both local AND regional outages exist, report the local one as it's more specific
- Use the customer_outage_status mapping to quickly determine if a customer has outages

DATABASE ACCESS:
You have access to an outage database JSON file with local_outages, regional_outages, and customer_outage_status mappings.
"""
        
        project_client = self._get_project_client()
        
        logger.info(f"Creating agent with model: {model_deployment_name}")
        logger.info(f"Tools configured: {len(tools)}")
        
        self.agent = project_client.agents.create_agent(
            model=model_deployment_name,
            name="Contoso Outage Check Agent",
            instructions=instructions,
            tools=tools if tools else None,
            tool_resources=tool_resources,
        )
        
        logger.info(f"✅ Contoso Outage Check Agent created successfully (ID: {self.agent.id})")
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
        
        yield "🔍 Checking for outages in your area..."
        
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
