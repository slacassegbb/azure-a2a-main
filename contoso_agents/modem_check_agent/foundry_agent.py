"""
AI Foundry Modem Check Agent for Contoso Customer Service.
Handles modem LED video analysis and backend configuration checks.
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


class FoundryModemCheckAgent:
    """
    AI Foundry Agent for modem checking.
    Analyzes modem LED status from video/images and checks backend configurations.
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
        async with FoundryModemCheckAgent._file_search_setup_lock:
            if FoundryModemCheckAgent._shared_file_search_tool is not None:
                logger.info("Reusing existing shared file search tool")
                return FoundryModemCheckAgent._shared_file_search_tool
            
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
                        FoundryModemCheckAgent._shared_uploaded_files.append(file.id)
                        logger.info(f"Uploaded file: {os.path.basename(file_path)} (ID: {file.id})")
                    except Exception as e:
                        logger.warning(f"Failed to upload {file_path}: {e}")
                
                if not file_ids:
                    logger.warning("No files were successfully uploaded")
                    return None
                
                logger.info("Creating shared vector store with uploaded files...")
                FoundryModemCheckAgent._shared_vector_store = project_client.agents.vector_stores.create_and_poll(
                    file_ids=file_ids, 
                    name="modem_vectorstore"
                )
                logger.info(f"Created shared vector store: {FoundryModemCheckAgent._shared_vector_store.id}")
                
                file_search = FileSearchTool(vector_store_ids=[FoundryModemCheckAgent._shared_vector_store.id])
                logger.info(f"File search capability prepared")
                
                FoundryModemCheckAgent._shared_file_search_tool = file_search
                logger.info("Cached shared file search tool for future use")
                    
                return file_search
                    
            except Exception as e:
                logger.error(f"Error setting up file search: {e}")
                return None
        
    async def create_agent(self) -> Agent:
        """Create the AI Foundry agent with modem checking capabilities."""
        if self.agent:
            logger.info("Agent already exists, returning existing instance")
            return self.agent
        
        logger.info("🚀 Creating Contoso Modem Check Agent...")
        
        tools = []
        tool_resources = None
        
        # Setup file search for modem database
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
        
        instructions = """You are a Contoso modem diagnostics agent. Your role is to analyze modem status through LED indicators and backend system checks.

MODEM LED STATUS MEANINGS:
- **Solid White**: Live and functional ✅
- **Blinking White**: On and looking for internet connectivity 🔄
- **Blinking Yellow**: Turning on/booting 🟡
- **Solid Yellow**: On but connectivity issue ⚠️
- **Red**: Internal issue with modem ❌
- **No Light**: Modem is off or has no power ⚫

YOUR RESPONSIBILITIES:
1. **Analyze modem LED status** (when customer provides video/image or description)
2. **Check backend modem configuration** using customer_id
3. **Compare visual status with backend status**
4. **Provide diagnosis and recommendations**

MODEM CHECK PROCESS:

**Step 1: Request LED Status**
If not provided, ask customer to describe modem LED color/pattern or send a photo/video.

**Step 2: Backend Configuration Check**
Search modem database for customer's modem using customer_id. Extract:
- Modem model and ID
- Firmware version and update status
- Connection status (online/offline/degraded)
- Signal strength (downstream power, upstream power, SNR)
- Backend errors
- Expected LED status
- Connection quality

**Step 3: Compare and Diagnose**
Compare visual LED status with backend data:

✅ **NORMAL**: Solid white LED + backend shows online + good signal strength
   → "Modem is functioning normally"

⚠️ **MISMATCH DETECTED**: Visual status doesn't match backend status
   → Example: Backend shows online but LED is red/yellow/off
   → "Discrepancy detected - backend shows X but modem LED shows Y"

❌ **PROBLEM DETECTED**: Any red/yellow LED or backend errors
   → Provide specific diagnosis based on combination

**Step 4: Recommendations**
Based on findings, recommend:
- Power cycle if LED is off or blinking
- Signal strength investigation if degraded
- Firmware update if outdated
- Technician dispatch if hardware issue suspected
- Configuration check if backend errors present

RESPONSE FORMAT:
"📡 **MODEM ANALYSIS RESULTS**

**Visual LED Status**: [color/pattern]
**Backend Status**: [online/offline/degraded]
**Modem Model**: [model]
**Signal Strength**: [downstream/upstream/SNR]
**Firmware**: [version] ([up-to-date/needs update])
**Connection Quality**: [excellent/good/poor/offline]

**Diagnosis**: [your assessment]

**Backend Errors**: [list any errors or "None"]

**Recommendations**: 
1. [specific action]
2. [specific action]
..."

IMPORTANT:
- Always check backend configuration for complete diagnosis
- Visual LED status alone is not sufficient
- Identify mismatches between visual and backend status
- Be specific in recommendations
- Consider signal strength values for connection quality assessment
"""
        
        project_client = self._get_project_client()
        
        logger.info(f"Creating agent with model: {model_deployment_name}")
        logger.info(f"Tools configured: {len(tools)}")
        
        self.agent = project_client.agents.create_agent(
            model=model_deployment_name,
            name="Contoso Modem Check Agent",
            instructions=instructions,
            tools=tools if tools else None,
            tool_resources=tool_resources,
        )
        
        logger.info(f"✅ Contoso Modem Check Agent created successfully (ID: {self.agent.id})")
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
        
        yield "📡 Analyzing modem status..."
        
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
