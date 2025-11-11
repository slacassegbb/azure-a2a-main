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
    
    async def _setup_file_search(self, files_directory: str = "documents", vector_store_name: str = "network_performance_vectorstore") -> Optional[FileSearchTool]:
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
                    name=vector_store_name
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
        
        # Load configuration from conf.yaml
        import yaml
        conf_path = os.path.join(os.path.dirname(__file__), "conf.yaml")
        try:
            with open(conf_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info("✅ Loaded configuration from conf.yaml")
        except Exception as e:
            logger.warning(f"⚠️  Could not load conf.yaml: {e}")
            config = {
                'agent': {
                    'name': 'Contoso Network Performance Agent',
                    'model': 'gpt-4o',
                    'vector_store_name': 'network_performance_vectorstore',
                    'documents_directory': 'documents',
                    'max_run_iterations': 10,
                    'poll_interval_seconds': 2
                },
                'fabric_endpoints': {}
            }
        
        # Extract agent configuration with defaults
        agent_config = config.get('agent', {})
        agent_name = agent_config.get('name', 'Contoso Network Performance Agent')
        model_deployment_name = agent_config.get('model', os.environ.get("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o"))
        vector_store_name = agent_config.get('vector_store_name', 'network_performance_vectorstore')
        documents_directory = agent_config.get('documents_directory', 'documents')
        instructions = agent_config.get('instructions', 'You are a network performance diagnostic agent.')
        
        logger.info(f"📋 Agent Configuration:")
        logger.info(f"   Name: {agent_name}")
        logger.info(f"   Model: {model_deployment_name}")
        logger.info(f"   Vector Store: {vector_store_name}")
        logger.info(f"   Documents Dir: {documents_directory}")
        logger.info(f"   Instructions Length: {len(instructions)} characters")
        
        # Import and configure tools
        try:
            from tools import (
                retrieve_operational_context, 
                set_network_performance_endpoint,
                set_azure_credential
            )
            
            # Set Fabric endpoint and credential
            if 'network_performance' in config.get('fabric_endpoints', {}):
                network_endpoint = config['fabric_endpoints']['network_performance']
                set_network_performance_endpoint(network_endpoint)
                logger.info("✅ Network performance endpoint configured")
            else:
                logger.warning("⚠️  No network_performance endpoint in conf.yaml")
            
            set_azure_credential(self.credential)
            logger.info("✅ Azure credential configured for tools")
            
        except Exception as e:
            logger.warning(f"⚠️  Could not configure Fabric tools: {e}")
        
        tools = []
        tool_resources = None
        
        # Add Fabric data retrieval function tool
        fabric_tool = {
            "type": "function",
            "function": {
                "name": "retrieve_operational_context",
                "description": "Retrieve historical network operational data from Microsoft Fabric including customer network history, device status, ping metrics, connectivity patterns, and performance baselines",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Query about customer network performance, device status, ping history, or historical metrics. Include customer_id when relevant. Examples: 'Get network performance data for customer CUST005 from last 7 days', 'Retrieve device connectivity history for customer CUST005'"
                        }
                    },
                    "required": ["query"]
                }
            }
        }
        tools.append(fabric_tool)
        logger.info("✅ Fabric retrieve_operational_context tool added")
        
        # Setup file search for network database
        file_search_tool = await self._setup_file_search(documents_directory, vector_store_name)
        if file_search_tool:
            if hasattr(file_search_tool, 'definitions'):
                tools.extend(file_search_tool.definitions)
                logger.info("✅ File search tool definitions added")
            
            if hasattr(file_search_tool, 'resources'):
                tool_resources = file_search_tool.resources
                logger.info("✅ File search tool resources added")
        
        project_client = self._get_project_client()
        
        logger.info(f"Creating agent with model: {model_deployment_name}")
        logger.info(f"Tools configured: {len(tools)}")
        
        self.agent = project_client.agents.create_agent(
            model=model_deployment_name,
            name=agent_name,
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

    async def _handle_tool_calls(self, run: ThreadRun, thread_id: str):
        """Handle tool calls during agent execution."""
        if not run.required_action:
            logger.info(f"No required action for run {run.id}")
            return
            
        required_action = run.required_action
        logger.info(f"Required action type: {type(required_action)}")
        
        if not hasattr(required_action, 'submit_tool_outputs') or not required_action.submit_tool_outputs:
            logger.warning(f"No tool outputs required in run {run.id}")
            return
            
        try:
            tool_calls = required_action.submit_tool_outputs.tool_calls
            if not tool_calls:
                logger.warning("No tool calls found in required action")
                return
            
            tool_outputs = []

            async def handle_single_tool_call(tool_call):
                function_name = tool_call.function.name
                arguments = tool_call.function.arguments
                logger.info(f"🔧 Processing tool call: {function_name} with args: {arguments}")
                logger.debug(f"Tool call ID: {tool_call.id}")
                
                # Handle retrieve_operational_context tool
                if function_name == "retrieve_operational_context":
                    import json
                    from tools import retrieve_operational_context
                    
                    try:
                        args = json.loads(arguments) if isinstance(arguments, str) else arguments
                        query = args.get("query", "")
                        
                        logger.info(f"📊 Executing retrieve_operational_context with query: {query}")
                        
                        # Call the actual Fabric tool
                        result = retrieve_operational_context(query)
                        
                        logger.info(f"✅ Fabric tool returned {len(result)} characters of data")
                        
                        return {
                            "tool_call_id": tool_call.id,
                            "output": result
                        }
                    except Exception as e:
                        logger.error(f"❌ Error executing retrieve_operational_context: {e}")
                        error_output = json.dumps({
                            "status": "error",
                            "message": f"Failed to retrieve operational context: {str(e)}"
                        })
                        return {
                            "tool_call_id": tool_call.id,
                            "output": error_output
                        }
                else:
                    # For file_search and other system tools, they're handled automatically
                    logger.info(f"Skipping system tool call: {function_name} (handled automatically)")
                    return {
                        "tool_call_id": tool_call.id,
                        "output": "{}"
                    }

            # Process all tool calls
            results = []
            for tool_call in tool_calls:
                result = await handle_single_tool_call(tool_call)
                if result:
                    results.append(result)
                await asyncio.sleep(0.5)
            
            tool_outputs = [r for r in results if r is not None]

            if not tool_outputs:
                logger.info("No valid tool outputs generated - submitting empty outputs")
                tool_outputs = [{"tool_call_id": tc.id, "output": "{}"} for tc in tool_calls if hasattr(tc, 'id') and tc.id]
                
            logger.debug(f"Tool outputs to submit: {tool_outputs}")
            
            # Submit tool outputs
            project_client = self._get_project_client()
            agents_client = project_client.agents
            agents_client.runs.submit_tool_outputs(
                thread_id=thread_id,
                run_id=run.id,
                tool_outputs=tool_outputs
            )
            logger.info(f"✅ Submitted {len(tool_outputs)} tool outputs")
            
        except Exception as e:
            logger.error(f"Error processing tool calls: {e}")
            raise

    async def run_conversation_stream(self, thread_id: str, user_message: str):
        """Run the agent on a thread and stream responses with tool call handling."""
        logger.info(f"🟢 [NETWORK AGENT] run_conversation_stream called for thread {thread_id}")
        project_client = self._get_project_client()
        agents_client = project_client.agents
        
        # Load config for run parameters
        import yaml
        conf_path = os.path.join(os.path.dirname(__file__), "conf.yaml")
        try:
            with open(conf_path, 'r') as f:
                config = yaml.safe_load(f)
            agent_config = config.get('agent', {})
            max_iterations = agent_config.get('max_run_iterations', 10)
            poll_interval = agent_config.get('poll_interval_seconds', 2)
        except:
            max_iterations = 10
            poll_interval = 2
        
        await self.send_message(thread_id, user_message)
        
        yield "🤖 Analyzing network performance..."
        
        logger.info(f"🟢 [NETWORK AGENT] Creating run for thread {thread_id}")
        run = agents_client.runs.create(
            thread_id=thread_id,
            agent_id=self.agent.id
        )
        
        # Poll the run and handle tool calls
        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            run = agents_client.runs.retrieve(thread_id=thread_id, run_id=run.id)
            logger.info(f"🟢 [NETWORK AGENT] Run status ({iteration}): {run.status}")
            
            if run.status == "requires_action":
                logger.info("🔧 Run requires action - handling tool calls")
                yield "🛠️ Retrieving data from Fabric..."
                await self._handle_tool_calls(run, thread_id)
                await asyncio.sleep(1)
                continue
            elif run.status in ["completed", "failed", "cancelled", "expired"]:
                logger.info(f"🟢 [NETWORK AGENT] Run reached terminal state: {run.status}")
                break
            else:
                await asyncio.sleep(poll_interval)
        
        if run.status != "completed":
            logger.error(f"❌ Run did not complete successfully: {run.status}")
            yield f"Error: Run ended with status {run.status}"
            return
        
        if run.status != "completed":
            logger.error(f"❌ Run did not complete successfully: {run.status}")
            yield f"Error: Run ended with status {run.status}"
            return
        
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
