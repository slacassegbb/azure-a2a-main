"""
AI Foundry Network Performance Agent for Contoso Customer Service.
Performs comprehensive network diagnostics including ping tests, device discovery, and network performance analysis.
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


class FoundryNetworkPerformanceAgent:
    """
    AI Foundry Agent for network performance diagnostics.
    Checks network health, device connectivity, and recommends actions.
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
        async with FoundryNetworkPerformanceAgent._file_search_setup_lock:
            if FoundryNetworkPerformanceAgent._shared_file_search_tool is not None:
                logger.info("Reusing existing shared file search tool")
                return FoundryNetworkPerformanceAgent._shared_file_search_tool
            
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
                        FoundryNetworkPerformanceAgent._shared_uploaded_files.append(file.id)
                        logger.info(f"Uploaded file: {os.path.basename(file_path)} (ID: {file.id})")
                    except Exception as e:
                        logger.warning(f"Failed to upload {file_path}: {e}")
                
                if not file_ids:
                    logger.warning("No files were successfully uploaded")
                    return None
                
                logger.info("Creating shared vector store with uploaded files...")
                FoundryNetworkPerformanceAgent._shared_vector_store = project_client.agents.vector_stores.create_and_poll(
                    file_ids=file_ids, 
                    name="network_performance_vectorstore"
                )
                logger.info(f"Created shared vector store: {FoundryNetworkPerformanceAgent._shared_vector_store.id}")
                
                file_search = FileSearchTool(vector_store_ids=[FoundryNetworkPerformanceAgent._shared_vector_store.id])
                logger.info(f"File search capability prepared")
                
                FoundryNetworkPerformanceAgent._shared_file_search_tool = file_search
                logger.info("Cached shared file search tool for future use")
                    
                return file_search
                    
            except Exception as e:
                logger.error(f"Error setting up file search: {e}")
                return None
        
    async def create_agent(self) -> Agent:
        """Create the AI Foundry agent with network diagnostic capabilities."""
        if self.agent:
            logger.info("Agent already exists, returning existing instance")
            return self.agent
        
        logger.info("🚀 Creating Contoso Network Performance Agent...")
        
        tools = []
        tool_resources = None
        
        # Setup file search for network database
        file_search_tool = await self._setup_file_search("documents")
        if file_search_tool:
            if hasattr(file_search_tool, 'definitions'):
                tools.extend(file_search_tool.definitions)
                logger.info("✅ File search tool definitions added")
            
            if hasattr(file_search_tool, 'resources'):
                tool_resources = file_search_tool.resources
                logger.info("✅ File search tool resources added")
        
        model_deployment_name = os.environ.get("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")
        
        instructions = """You are the Contoso Network Performance Check Agent. Your role is to perform comprehensive network diagnostics for Contoso internet customers experiencing connectivity issues.

**Your Capabilities:**
1. Device Discovery: Identify all connected devices (laptops, phones, tablets, smart TVs, IoT devices) with their IP addresses and MAC addresses
2. Ping Diagnostics: Perform ping tests to modem (192.168.1.1), network pods, and sample connected devices
3. Performance Analysis: Analyze latency, packet loss percentages, and overall network health
4. Network Reset: Trigger proactive network resets when performance issues are detected BUT network infrastructure is functional

**Diagnostic Protocol:**
1. **Retrieve customer network data** using customer_id from the network database
2. **Analyze modem status:**
   - Check if modem is responding to pings
   - Evaluate packet loss and latency to modem
   - Status levels: excellent (0% loss, <10ms), good (0% loss, 10-30ms), poor (>10% loss or >30ms), failed (100% loss)

3. **Check network pods** (if customer has them):
   - Ping each pod and evaluate response
   - Assess signal strength and connectivity
   - Identify degraded or offline pods

4. **Sample device connectivity:**
   - Review ping results from representative devices
   - Check for patterns of connectivity issues
   - Identify if issues are localized or network-wide

5. **List all connected devices:**
   - Provide complete inventory with device names, IPs, types, and current status
   - Highlight offline devices if customer should be online

6. **Determine network status:**
   - **EXCELLENT**: 0% packet loss, latency <10ms, all devices responsive → RECOMMEND PROACTIVE NETWORK RESET to optimize before declaring all clear
   - **GOOD**: 0% packet loss, latency 10-30ms → RECOMMEND PROACTIVE NETWORK RESET
   - **POOR**: 10-40% packet loss or latency >30ms → RECOMMEND IMMEDIATE NETWORK RESET to resolve issues
   - **CRITICAL**: >40% packet loss or modem offline → CANNOT RESET, requires technician dispatch

**CRITICAL: Proactive Network Reset Logic:**
- If network diagnostics show GOOD or EXCELLENT performance, you MUST recommend a proactive network reset BEFORE giving the all-clear
- Reason: "Your network performance appears normal, but I recommend a proactive network reset to clear any cached states and optimize your connection before we conclude everything is working properly."
- This is preventive maintenance to avoid false negatives where tests pass but customer still experiences issues

**Network Reset Action:**
When recommending a network reset, explain:
- What will happen: "I'll clear the ARP cache, reset DHCP leases, restart modem interface, restart network pods, clear DNS cache, and reset connection states"
- Expected downtime: "30-60 seconds of connectivity loss"
- Success indicators: "Pings return to normal (<10ms latency), packet loss drops to 0%, devices reconnect successfully"

**Response Format:**
Provide clear, structured reports:
1. Network topology (modem, pods, device count)
2. Ping test results with specific metrics
3. Device list with names and IPs
4. Overall network status assessment
5. Recommended action with clear reasoning

**Important Notes:**
- Always retrieve actual customer data from the network database using their customer_id
- Provide specific ping statistics (packet loss %, latency in ms)
- List device names and IPs for better troubleshooting
- If modem is completely offline or packet loss >40%, recommend technician dispatch instead of network reset
- Be proactive: even if network seems OK, recommend reset as preventive measure

Remember: You are helping customers who are already experiencing issues. Be thorough, specific, and actionable in your diagnostics."""
        
        project_client = self._get_project_client()
        
        logger.info(f"Creating agent with model: {model_deployment_name}")
        logger.info(f"Tools configured: {len(tools)}")
        
        self.agent = project_client.agents.create_agent(
            model=model_deployment_name,
            name="Contoso Network Performance Agent",
            instructions=instructions,
            tools=tools if tools else None,
            tool_resources=tool_resources,
        )
        
        logger.info(f"✅ Contoso Network Performance Agent created successfully (ID: {self.agent.id})")
        return self.agent

    async def create_thread(self) -> AgentThread:
        """Create a new conversation thread."""
        logger.info("🟢 [NETWORK AGENT] create_thread called")
        project_client = self._get_project_client()
        agents_client = project_client.agents
        thread = agents_client.threads.create()
        logger.info(f"🟢 [NETWORK AGENT] Created new thread: {thread.id}")
        return thread

    async def send_message(self, thread_id: str, message: str, role: str = "user") -> ThreadMessage:
        """Send a message to a thread."""
        logger.info(f"🟢 [NETWORK AGENT] send_message called for thread {thread_id}")
        project_client = self._get_project_client()
        agents_client = project_client.agents
        thread_message = agents_client.messages.create(
            thread_id=thread_id,
            role=role,
            content=message
        )
        logger.info(f"🟢 [NETWORK AGENT] Message sent to thread {thread_id}")
        return thread_message

    async def run_conversation_stream(self, thread_id: str, user_message: str):
        """Run the agent on a thread and stream responses."""
        logger.info(f"🟢 [NETWORK AGENT] run_conversation_stream called for thread {thread_id}")
        project_client = self._get_project_client()
        agents_client = project_client.agents
        
        await self.send_message(thread_id, user_message)
        
        yield "🤖 Analyzing network performance..."
        
        logger.info(f"🟢 [NETWORK AGENT] Creating and processing run for thread {thread_id}")
        run = agents_client.runs.create_and_process(
            thread_id=thread_id,
            agent_id=self.agent.id
        )
        
        logger.info(f"🟢 [NETWORK AGENT] Run created: {run.id}, status: {run.status}")
        
        # Get messages after run completes
        logger.info(f"🟢 [NETWORK AGENT] Listing messages for thread {thread_id}")
        messages = agents_client.messages.list(
            thread_id=thread_id,
            order=ListSortOrder.DESCENDING
        )
        
        logger.info(f"🟢 [NETWORK AGENT] Got messages, iterating through them")
        for msg in messages:
            if msg.role == "assistant":
                for content_item in msg.content:
                    if hasattr(content_item, 'text') and hasattr(content_item.text, 'value'):
                        yield content_item.text.value
                break
