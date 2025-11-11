"""
AI Foundry Authentication Agent for Contoso Customer Service.
Handles customer authentication by verifying first name, last name, postal code, and date of birth.
"""
import os
import datetime
import asyncio
import logging
import json
from typing import Optional, Dict, List

from azure.ai.agents.models import (
    Agent,
    ThreadMessage,
    ThreadRun,
    AgentThread,
    BingGroundingTool,
    ListSortOrder,
    FilePurpose,
    FileSearchTool,
)
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
import glob

logger = logging.getLogger(__name__)


class FoundryAuthenticationAgent:
    """
    AI Foundry Agent for customer authentication.
    Verifies customer identity using first name, last name, postal code, and date of birth.
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

    async def _setup_file_search(
        self, files_directory: str = "documents"
    ) -> Optional[FileSearchTool]:
        """Upload files from local directory and create vector store for file search - ONCE per class."""
        async with FoundryAuthenticationAgent._file_search_setup_lock:
            if FoundryAuthenticationAgent._shared_file_search_tool is not None:
                logger.info("Reusing existing shared file search tool")
                return FoundryAuthenticationAgent._shared_file_search_tool

            try:
                if not os.path.exists(files_directory):
                    logger.info(
                        f"No {files_directory} directory found, skipping file search setup"
                    )
                    return None

                supported_extensions = [
                    "*.txt",
                    "*.md",
                    "*.pdf",
                    "*.docx",
                    "*.json",
                    "*.csv",
                ]
                file_paths = set()
                for ext in supported_extensions:
                    file_paths.update(glob.glob(os.path.join(files_directory, ext)))
                    file_paths.update(
                        glob.glob(
                            os.path.join(files_directory, "**", ext), recursive=True
                        )
                    )

                file_paths = list(file_paths)

                if not file_paths:
                    logger.info(
                        f"No supported files found in {files_directory}, skipping file search setup"
                    )
                    return None

                logger.info(
                    f"Found {len(file_paths)} files to upload: {[os.path.basename(f) for f in file_paths]}"
                )

                file_ids = []
                project_client = self._get_project_client()
                for file_path in file_paths:
                    try:
                        logger.info(f"Uploading file: {os.path.basename(file_path)}")
                        file = project_client.agents.files.upload_and_poll(
                            file_path=file_path, purpose=FilePurpose.AGENTS
                        )
                        file_ids.append(file.id)
                        FoundryAuthenticationAgent._shared_uploaded_files.append(
                            file.id
                        )
                        logger.info(
                            f"Uploaded file: {os.path.basename(file_path)} (ID: {file.id})"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to upload {file_path}: {e}")

                if not file_ids:
                    logger.warning("No files were successfully uploaded")
                    return None

                logger.info("Creating shared vector store with uploaded files...")
                FoundryAuthenticationAgent._shared_vector_store = (
                    project_client.agents.vector_stores.create_and_poll(
                        file_ids=file_ids, name="authentication_vectorstore"
                    )
                )
                logger.info(
                    f"Created shared vector store: {FoundryAuthenticationAgent._shared_vector_store.id}"
                )

                file_search = FileSearchTool(
                    vector_store_ids=[
                        FoundryAuthenticationAgent._shared_vector_store.id
                    ]
                )
                logger.info(f"File search capability prepared")

                FoundryAuthenticationAgent._shared_file_search_tool = file_search
                logger.info("Cached shared file search tool for future use")

                return file_search

            except Exception as e:
                logger.error(f"Error setting up file search: {e}")
                return None

    async def create_agent(self) -> Agent:
        """Create the AI Foundry agent with customer authentication capabilities."""
        if self.agent:
            logger.info("Agent already exists, returning existing instance")
            return self.agent

        logger.info("🚀 Creating Contoso Authentication Agent...")

        tools = []
        tool_resources = None

        # Setup file search for customer database
        file_search_tool = await self._setup_file_search("documents")
        if file_search_tool:
            if hasattr(file_search_tool, "definitions"):
                tools.extend(file_search_tool.definitions)
                logger.info("✅ File search tool definitions added")

            if hasattr(file_search_tool, "resources"):
                tool_resources = file_search_tool.resources
                logger.info("✅ File search tool resources added")

        # Add web search capability
        # tools.append(BingGroundingTool())
        # logger.info("✅ Bing grounding tool added")

        model_deployment_name = os.environ.get(
            "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o"
        )

        instructions = """You are a Contoso customer authentication agent. Your role is to verify customer identity before they can proceed with support.

AUTHENTICATION REQUIREMENTS:
You must collect and verify the following information:
1. First Name
2. Last Name
3. Postal Code (Canadian format: A1A1A1)
4. Date of Birth (format: YYYY-MM-DD)

AUTHENTICATION PROCESS:
1. Greet the customer warmly and explain that you need to verify their identity
2. Ask for each piece of information one at a time (be conversational, not robotic)
3. Search the customer database file for a matching customer record
4. Verify that ALL provided information matches exactly:
   - first_name matches (case insensitive)
   - last_name matches (case insensitive)
   - postal_code matches (remove spaces, case insensitive)
   - date_of_birth matches exactly (YYYY-MM-DD format)

AUTHENTICATION OUTCOMES:
✅ SUCCESS: If all information matches, respond with:
   "Authentication successful! Welcome back [First Name] [Last Name]. Your account is verified."
   Then extract and provide: customer_id, address, phone, email, region

❌ FAILURE: If any information doesn't match or customer not found:
   "I'm sorry, but I couldn't verify your identity with the information provided. Please double-check your information and try again."

IMPORTANT RULES:
- Be polite and professional at all times
- Ask for information naturally in conversation
- Do not reveal partial matches or which field failed
- After 3 failed attempts, suggest contacting customer service directly
- Once authenticated, provide the customer_id for downstream agents to use

CUSTOMER DATABASE:
You have access to a customer database JSON file. Use file search to look up customer records.
"""

        project_client = self._get_project_client()

        logger.info(f"Creating agent with model: {model_deployment_name}")
        logger.info(f"Tools configured: {len(tools)}")

        self.agent = project_client.agents.create_agent(
            model=model_deployment_name,
            name="Contoso Authentication Agent",
            instructions=instructions,
            tools=tools if tools else None,
            tool_resources=tool_resources,
        )

        logger.info(
            f"✅ Contoso Authentication Agent created successfully (ID: {self.agent.id})"
        )
        return self.agent

    async def create_thread(self) -> AgentThread:
        """Create a new conversation thread."""
        logger.info("🟢 [AUTH AGENT] create_thread called")
        project_client = self._get_project_client()
        logger.info(f"🟢 [AUTH AGENT] Got project_client: {type(project_client)}")
        agents_client = project_client.agents
        logger.info(f"🟢 [AUTH AGENT] agents_client: {type(agents_client)}")
        thread = agents_client.threads.create()
        logger.info(f"🟢 [AUTH AGENT] Created new thread: {thread.id}")
        return thread

    async def send_message(
        self, thread_id: str, message: str, role: str = "user"
    ) -> ThreadMessage:
        """Send a message to a thread."""
        logger.info(f"🟢 [AUTH AGENT] send_message called for thread {thread_id}")
        project_client = self._get_project_client()
        agents_client = project_client.agents
        thread_message = agents_client.messages.create(
            thread_id=thread_id, role=role, content=message
        )
        logger.info(f"🟢 [AUTH AGENT] Message sent to thread {thread_id}")
        return thread_message

    async def run_conversation_stream(self, thread_id: str, user_message: str):
        """Run the agent on a thread and stream responses."""
        logger.info(
            f"🟢 [AUTH AGENT] run_conversation_stream called for thread {thread_id}"
        )
        project_client = self._get_project_client()
        agents_client = project_client.agents

        await self.send_message(thread_id, user_message)

        yield "🤖 Authenticating customer..."

        logger.info(
            f"🟢 [AUTH AGENT] Creating and processing run for thread {thread_id}"
        )
        run = agents_client.runs.create_and_process(
            thread_id=thread_id, agent_id=self.agent.id
        )

        logger.info(f"🟢 [AUTH AGENT] Run created: {run.id}, status: {run.status}")

        # Get messages after run completes
        logger.info(f"🟢 [AUTH AGENT] Listing messages for thread {thread_id}")
        messages = agents_client.messages.list(
            thread_id=thread_id, order=ListSortOrder.DESCENDING
        )

        logger.info(f"🟢 [AUTH AGENT] Got messages, iterating through them")
        for msg in messages:
            if msg.role == "assistant":
                for content_item in msg.content:
                    if hasattr(content_item, "text") and hasattr(
                        content_item.text, "value"
                    ):
                        yield content_item.text.value
                break
