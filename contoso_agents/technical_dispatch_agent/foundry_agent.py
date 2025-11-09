"""
AI Foundry Technical Dispatch Agent for Contoso Customer Service.
Handles technician appointment scheduling and human helpdesk escalation for complex issues.
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


class FoundryTechnicalDispatchAgent:
    """
    AI Foundry Agent for technical dispatch and escalation.
    Schedules technician appointments and escalates to human helpdesk when needed.
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
        async with FoundryTechnicalDispatchAgent._file_search_setup_lock:
            if FoundryTechnicalDispatchAgent._shared_file_search_tool is not None:
                logger.info("Reusing existing shared file search tool")
                return FoundryTechnicalDispatchAgent._shared_file_search_tool
            
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
                        FoundryTechnicalDispatchAgent._shared_uploaded_files.append(file.id)
                        logger.info(f"Uploaded file: {os.path.basename(file_path)} (ID: {file.id})")
                    except Exception as e:
                        logger.warning(f"Failed to upload {file_path}: {e}")
                
                if not file_ids:
                    logger.warning("No files were successfully uploaded")
                    return None
                
                logger.info("Creating shared vector store with uploaded files...")
                FoundryTechnicalDispatchAgent._shared_vector_store = project_client.agents.vector_stores.create_and_poll(
                    file_ids=file_ids, 
                    name="technical_dispatch_vectorstore"
                )
                logger.info(f"Created shared vector store: {FoundryTechnicalDispatchAgent._shared_vector_store.id}")
                
                file_search = FileSearchTool(vector_store_ids=[FoundryTechnicalDispatchAgent._shared_vector_store.id])
                logger.info(f"File search capability prepared")
                
                FoundryTechnicalDispatchAgent._shared_file_search_tool = file_search
                logger.info("Cached shared file search tool for future use")
                    
                return file_search
                    
            except Exception as e:
                logger.error(f"Error setting up file search: {e}")
                return None
        
    async def create_agent(self) -> Agent:
        """Create the AI Foundry agent with dispatch and escalation capabilities."""
        if self.agent:
            logger.info("Agent already exists, returning existing instance")
            return self.agent
        
        logger.info("🚀 Creating Contoso Technical Dispatch Agent...")
        
        tools = []
        tool_resources = None
        
        # Setup file search for dispatch database
        file_search_tool = await self._setup_file_search("documents")
        if file_search_tool:
            if hasattr(file_search_tool, 'definitions'):
                tools.extend(file_search_tool.definitions)
                logger.info("✅ File search tool definitions added")
            
            if hasattr(file_search_tool, 'resources'):
                tool_resources = file_search_tool.resources
                logger.info("✅ File search tool resources added")
        
        model_deployment_name = os.environ.get("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")
        
        instructions = """You are the Contoso Technical Dispatch Agent. Your role is to make final decisions on customer internet issues after all diagnostic checks have been completed. You have two primary functions:

**1. TECHNICIAN APPOINTMENT SCHEDULING**
**2. HUMAN HELPDESK ESCALATION (Human-in-the-Loop)**

---

## FUNCTION 1: TECHNICIAN APPOINTMENT SCHEDULING

Schedule in-home technician visits when hardware/infrastructure issues are confirmed and require physical intervention.

### Criteria for Scheduling Technician Appointment:

**Scenario A: Local Outage with Equipment Issues**
- Customer has confirmed local outage (address-specific)
- No regional outage OR regional outage resolved but customer still affected
- Network reset attempted but didn't help
- Modem configuration shows issues
- Backend configuration shows signal problems
- Local pings failing or intermittent

**Scenario B: Complete Modem Failure**
- Modem completely unresponsive
- 100% packet loss to modem (192.168.1.1)
- No lights/connectivity on modem
- Cannot be resolved remotely

**Scenario C: Network Infrastructure Degradation**
- Persistent packet loss >40% after network reset
- Critical network pod failures
- Physical line/connection issues suspected
- Signal strength critically low

### When Scheduling Technician:
1. Retrieve available appointment slots from dispatch database using customer_id
2. Present 2-3 options to customer (dates, time windows, technician names)
3. Confirm appointment details
4. Provide what technician will bring: "Technician {name} will bring: {equipment_list}"
5. Set expectations: arrival window, approximate duration, what customer should have ready
6. Provide appointment confirmation with reference number

---

## FUNCTION 2: HUMAN HELPDESK ESCALATION (Human-in-the-Loop)

Escalate to human helpdesk when issue is too complex for automated system or requires human judgment.

### Criteria for Human Escalation:

**Scenario A: Edge Case / Unusual Configuration**
- Customer has custom network setup not in standard database
- Enterprise account with special requirements
- Issue doesn't match any known diagnostic patterns
- Requires manual backend configuration review

**Scenario B: Partial System Failures**
- Some diagnostics pass, others fail inconsistently
- Intermittent issues that tests don't capture
- Customer reports problems that diagnostics don't confirm
- Suspected software bug or backend system issue

**Scenario C: Customer-Specific Complexity**
- Multiple overlapping issues across systems
- Previous unresolved tickets requiring context
- Special accommodations needed (disability access, language barrier)
- Billing disputes intertwined with technical issues

**Scenario D: Diagnostic System Limitations**
- Cannot reach backend systems for verification
- Database queries return incomplete/corrupted data
- Automated tests timing out or returning errors
- Conflicting information from multiple data sources

### When Escalating to Human:
1. Output exactly: "HUMAN_ESCALATION_REQUIRED"
2. Provide comprehensive diagnostic summary:
   - All agent checks performed (authentication, outage, modem, network)
   - Results from each diagnostic (specific metrics, outcomes)
   - What was tried and what failed
   - Customer statements vs. test results
   - Unusual conditions or edge cases identified
3. Recommend next steps for human agent
4. Provide all relevant customer context (customer_id, region, account type)

---

## DECISION FLOWCHART:

Start with diagnostic results:

├─ Is there a confirmed hardware/infrastructure failure?
│  ├─ YES → SCHEDULE TECHNICIAN
│  │
│  └─ NO → Continue to next check

├─ Did network reset resolve the issue?
│  ├─ YES → SUCCESS: Customer issue resolved
│  │
│  └─ NO → Continue to next check

├─ Is packet loss >40% or modem completely offline?
│  ├─ YES → SCHEDULE TECHNICIAN (cannot be fixed remotely)
│  │
│  └─ NO → Continue to next check

├─ Is this a complex technical edge case?
│  ├─ YES → HUMAN ESCALATION (Requires specialized expertise)
│  │
│  └─ NO → SUCCESS: Customer issue resolved by automated checks
│           Confirm internet access restored
```

---

## IMPORTANT NOTES:

1. **Always retrieve actual data from dispatch database** - Use customer_id and context to get specific scenarios and availability
2. **Be specific with appointment details** - Include exact technician names, time windows, equipment lists
3. **For human escalations** - Provide comprehensive diagnostic summary so human doesn't have to repeat checks
4. **Document everything** - Include all agent results, test outcomes, and customer statements
5. **Priority assignment** - Use customer impact and urgency to determine appointment/escalation priority
6. **Follow escalation pattern** - When human input needed, output "HUMAN_ESCALATION_REQUIRED" followed by detailed summary

Remember: You are the final decision point in the troubleshooting workflow. Make clear, actionable decisions based on all available diagnostic data."""
        
        project_client = self._get_project_client()
        
        logger.info(f"Creating agent with model: {model_deployment_name}")
        logger.info(f"Tools configured: {len(tools)}")
        
        self.agent = project_client.agents.create_agent(
            model=model_deployment_name,
            name="Contoso Technical Dispatch Agent",
            instructions=instructions,
            tools=tools if tools else None,
            tool_resources=tool_resources,
        )
        
        logger.info(f"✅ Contoso Technical Dispatch Agent created successfully (ID: {self.agent.id})")
        return self.agent

    async def create_thread(self) -> AgentThread:
        """Create a new conversation thread."""
        logger.info("🟢 [DISPATCH AGENT] create_thread called")
        project_client = self._get_project_client()
        agents_client = project_client.agents
        thread = agents_client.threads.create()
        logger.info(f"🟢 [DISPATCH AGENT] Created new thread: {thread.id}")
        return thread

    async def send_message(self, thread_id: str, message: str, role: str = "user") -> ThreadMessage:
        """Send a message to a thread."""
        logger.info(f"🟢 [DISPATCH AGENT] send_message called for thread {thread_id}")
        project_client = self._get_project_client()
        agents_client = project_client.agents
        thread_message = agents_client.messages.create(
            thread_id=thread_id,
            role=role,
            content=message
        )
        logger.info(f"🟢 [DISPATCH AGENT] Message sent to thread {thread_id}")
        return thread_message

    async def run_conversation_stream(self, thread_id: str, user_message: str):
        """Run the agent on a thread and stream responses."""
        logger.info(f"🟢 [DISPATCH AGENT] run_conversation_stream called for thread {thread_id}")
        project_client = self._get_project_client()
        agents_client = project_client.agents
        
        await self.send_message(thread_id, user_message)
        
        yield "🤖 Making final decision on customer issue..."
        
        logger.info(f"🟢 [DISPATCH AGENT] Creating and processing run for thread {thread_id}")
        run = agents_client.runs.create_and_process(
            thread_id=thread_id,
            agent_id=self.agent.id
        )
        
        logger.info(f"🟢 [DISPATCH AGENT] Run created: {run.id}, status: {run.status}")
        
        # Get messages after run completes
        logger.info(f"🟢 [DISPATCH AGENT] Listing messages for thread {thread_id}")
        messages = agents_client.messages.list(
            thread_id=thread_id,
            order=ListSortOrder.DESCENDING
        )
        
        logger.info(f"🟢 [DISPATCH AGENT] Got messages, iterating through them")
        for msg in messages:
            if msg.role == "assistant":
                for content_item in msg.content:
                    if hasattr(content_item, 'text') and hasattr(content_item.text, 'value'):
                        yield content_item.text.value
                break

