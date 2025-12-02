"""
Azure AI Foundry Email Agent
============================

An agent that can compose and send emails using Microsoft Graph API.
Based on the working template agent pattern.
"""
import os
import time
import datetime
import asyncio
import logging
import json
from typing import Optional, Dict, List

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import Agent, ThreadMessage, ThreadRun, AgentThread, ToolOutput, BingGroundingTool, ListSortOrder, FilePurpose, FileSearchTool, RequiredMcpToolCall, ToolApproval
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
import glob

logger = logging.getLogger(__name__)


class FoundryEmailAgent:
    """
    Azure AI Foundry Email Agent
    
    This agent can compose professional emails and send them via Microsoft Graph API.
    """

    # Class-level shared resources for document search (created once)
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
        self._agents_client = None
        self._project_client = None
        
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
        """Upload files from local directory and create vector store for file search."""
        async with FoundryEmailAgent._file_search_setup_lock:
            if FoundryEmailAgent._shared_file_search_tool is not None:
                logger.info("Reusing existing shared file search tool")
                return FoundryEmailAgent._shared_file_search_tool
            
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
                    logger.info(f"No supported files found in {files_directory}")
                    return None
                
                logger.info(f"Found {len(file_paths)} files to upload")
                
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
                        FoundryEmailAgent._shared_uploaded_files.append(file.id)
                        logger.info(f"Uploaded file: {os.path.basename(file_path)}")
                    except Exception as e:
                        logger.warning(f"Failed to upload {file_path}: {e}")
                
                if not file_ids:
                    return None
                
                logger.info("Creating shared vector store...")
                FoundryEmailAgent._shared_vector_store = project_client.agents.vector_stores.create_and_poll(
                    file_ids=file_ids, 
                    name="email_agent_vectorstore"
                )
                
                file_search = FileSearchTool(vector_store_ids=[FoundryEmailAgent._shared_vector_store.id])
                FoundryEmailAgent._shared_file_search_tool = file_search
                logger.info("File search capability ready")
                    
                return file_search
                    
            except Exception as e:
                logger.error(f"Error setting up file search: {e}")
                return None
        
    async def create_agent(self) -> Agent:
        """Create the AI Foundry agent."""
        if self.agent:
            logger.info("Agent already exists, returning existing instance")
            return self.agent
        
        tools = []
        tool_resources = None
        
        project_client = self._get_project_client()
        
        # Add Bing search if available
        try:
            bing_connection = project_client.connections.get(name="agentbing")
            bing = BingGroundingTool(connection_id=bing_connection.id)
            tools.extend(bing.definitions)
            logger.info("Added Bing search capability")
        except Exception as e:
            logger.warning(f"Could not add Bing search: {e}")
        
        # Add file search if available
        if self._file_search_tool is None:
            self._file_search_tool = await self._setup_file_search()
        
        if self._file_search_tool:
            if hasattr(self._file_search_tool, 'definitions'):
                tools.extend(self._file_search_tool.definitions)
            if hasattr(self._file_search_tool, 'resources'):
                tool_resources = self._file_search_tool.resources
            logger.info("Added file search capability")
        
        with project_client:
            if tool_resources:
                self.agent = project_client.agents.create_agent(
                    model="gpt-4o",
                    name="email-agent",
                    instructions=self._get_agent_instructions(),
                    tools=tools,
                    tool_resources=tool_resources
                )
            else:
                self.agent = project_client.agents.create_agent(
                    model="gpt-4o",
                    name="email-agent",
                    instructions=self._get_agent_instructions(),
                    tools=tools
                )
        
        logger.info(f"Created Email Agent: {self.agent.id}")
        return self.agent
    
    def _get_agent_instructions(self) -> str:
        """Get the agent instructions for email composition and sending."""
        return f"""
You are an Email Communications Specialist. Your job is to compose and send professional emails IMMEDIATELY without asking for confirmation.

## HOW THIS WORKS

When you receive information about an email to send, you must:

1. **Extract the Information**:
   - Recipient email address
   - Subject line (create one based on context if not provided)
   - The FULL content/report to include in the email body
   - Any CC recipients (optional)

2. **Compose and SEND IMMEDIATELY**: Create a professional email and output it in the EMAIL_TO_SEND format right away. DO NOT ask for confirmation or approval.

3. **Output Format**: ALWAYS output the email in this EXACT format:

```EMAIL_TO_SEND
TO: recipient@example.com
SUBJECT: Your Subject Here
CC: optional@example.com (or leave blank)
BODY:
<html>
<p>Your email content here...</p>
</html>
```END_EMAIL

The system will automatically detect this format and send the email.

## CRITICAL RULES

- **NEVER** ask "Would you like me to send this?" or "Do you want any changes?"
- **NEVER** show a draft and wait for approval
- **ALWAYS** output the EMAIL_TO_SEND block immediately when you have the required info
- If you have recipient + subject/topic + content, SEND IT immediately
- **INCLUDE THE FULL REPORT/CONTENT IN THE EMAIL BODY** - do NOT say "attached" or "see attachment" since we don't support attachments
- Use HTML formatting in the body for professional appearance (<p>, <h2>, <ul>, <li>, <strong>, etc.)
- Create professional, well-structured emails automatically

## EXAMPLE

User: "Send this report to simon@company.com: [Report Title] Executive Summary... Key Findings... Recommendations..."

You: "I'll send that email now.

```EMAIL_TO_SEND
TO: simon@company.com
SUBJECT: Your AI Consultation Report
CC: 
BODY:
<html>
<p>Dear Simon,</p>
<p>Thank you for your time during our AI consultation. Please find your personalized report below:</p>
<h2>Report Title</h2>
<h3>Executive Summary</h3>
<p>...</p>
<h3>Key Findings</h3>
<ul>
<li>Finding 1</li>
<li>Finding 2</li>
</ul>
<h3>Recommendations</h3>
<p>...</p>
<p>If you have any questions, please don't hesitate to reach out.</p>
<p>Best regards</p>
</html>
```END_EMAIL"

Current date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
"""
    
    async def create_thread(self, thread_id: Optional[str] = None) -> AgentThread:
        """Create or retrieve a conversation thread."""
        client = self._get_client()
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
        logger.info(f"Created message in thread {thread_id}")
        return message
    
    async def run_conversation_stream(self, thread_id: str, user_message: str):
        """Run the conversation and yield responses."""
        if not self.agent:
            await self.create_agent()

        await self.send_message(thread_id, user_message)
        client = self._get_client()
        run = client.runs.create(thread_id=thread_id, agent_id=self.agent.id)

        max_iterations = 25
        iterations = 0

        while run.status in ["queued", "in_progress", "requires_action"] and iterations < max_iterations:
            iterations += 1
            await asyncio.sleep(2)

            try:
                run = client.runs.get(thread_id=thread_id, run_id=run.id)
            except Exception as e:
                yield f"Error: {str(e)}"
                return

            if run.status == "failed":
                yield f"Error: {run.last_error}"
                return

            if run.status == "requires_action":
                if hasattr(run, 'required_action') and run.required_action:
                    await self._handle_tool_calls(run, thread_id)
                run = client.runs.get(thread_id=thread_id, run_id=run.id)

        if run.status == "failed":
            yield f"Error: {run.last_error}"
            return

        if iterations >= max_iterations:
            yield "Error: Request timed out"
            return

        # Get the response
        messages = list(client.messages.list(thread_id=thread_id, order=ListSortOrder.ASCENDING))
        for msg in reversed(messages):
            if msg.role == "assistant" and msg.content:
                for content_item in msg.content:
                    if hasattr(content_item, 'text'):
                        text_content = content_item.text.value
                        
                        # Check if there's an email to send
                        email_result, clean_content = self._try_send_email(text_content)
                        if email_result:
                            # Show clean summary instead of raw EMAIL_TO_SEND block
                            yield f"{clean_content}\n\n{email_result}"
                        else:
                            yield text_content
                break
    
    def _try_send_email(self, response_text: str) -> tuple[Optional[str], str]:
        """Check if the response contains an email to send and send it.
        Returns: (result_message, cleaned_content)
        """
        import re
        
        # Look for the EMAIL_TO_SEND block
        pattern = r'```EMAIL_TO_SEND\s*\n(.*?)\n```END_EMAIL'
        match = re.search(pattern, response_text, re.DOTALL)
        
        if not match:
            return None, response_text
        
        email_block = match.group(1)
        
        # Parse the email fields
        to_match = re.search(r'^TO:\s*(.+)$', email_block, re.MULTILINE)
        subject_match = re.search(r'^SUBJECT:\s*(.+)$', email_block, re.MULTILINE)
        cc_match = re.search(r'^CC:\s*(.*)$', email_block, re.MULTILINE)
        body_match = re.search(r'^BODY:\s*\n(.+)', email_block, re.DOTALL | re.MULTILINE)
        
        if not to_match or not subject_match or not body_match:
            return "⚠️ Could not parse email format", response_text
        
        to = to_match.group(1).strip()
        subject = subject_match.group(1).strip()
        cc = cc_match.group(1).strip() if cc_match else ""
        body = body_match.group(1).strip()
        
        # Create a clean summary - strip HTML tags for readable display
        import html
        body_clean = re.sub(r'<[^>]+>', ' ', body)  # Remove HTML tags
        body_clean = html.unescape(body_clean)  # Decode HTML entities
        body_clean = re.sub(r' +', ' ', body_clean)  # Normalize spaces
        body_clean = re.sub(r'\n\s*\n', '\n\n', body_clean.strip())  # Clean up newlines
        
        clean_summary = f"📧 **Email Sent**\n\n**To:** {to}\n**Subject:** {subject}\n\n{body_clean}"
        if cc and cc.lower() != "body:" and "@" in cc:
            clean_summary = f"📧 **Email Sent**\n\n**To:** {to}\n**CC:** {cc}\n**Subject:** {subject}\n\n{body_clean}"
        
        # Send the email
        try:
            from email_config import send_email, send_email_with_cc
            
            if cc and "@" in cc:
                cc_list = [e.strip() for e in cc.split(",") if "@" in e]
                result = send_email_with_cc(to=to, subject=subject, body=body, cc=cc_list)
            else:
                result = send_email(to=to, subject=subject, body=body)
            
            if result["success"]:
                return f"✅ {result['message']}", clean_summary
            else:
                return f"❌ {result['message']}", clean_summary
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return f"❌ Failed to send email: {str(e)}", clean_summary
    
    async def _handle_tool_calls(self, run: ThreadRun, thread_id: str):
        """Handle tool calls during agent execution."""
        if not hasattr(run, 'required_action') or not run.required_action:
            return
            
        required_action = run.required_action
        
        if not hasattr(required_action, 'submit_tool_outputs') or not required_action.submit_tool_outputs:
            return
            
        try:
            tool_calls = required_action.submit_tool_outputs.tool_calls
            if not tool_calls:
                return
            
            tool_outputs = []
            for tool_call in tool_calls:
                # For built-in tools (Bing, file search), return empty output
                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "output": "{}"
                })
            
            client = self._get_client()
            formatted_outputs = [
                ToolOutput(tool_call_id=o["tool_call_id"], output=o["output"])
                for o in tool_outputs
            ]
            
            client.runs.submit_tool_outputs(
                thread_id=thread_id,
                run_id=run.id,
                tool_outputs=formatted_outputs
            )
            
        except Exception as e:
            logger.error(f"Error handling tool calls: {e}")


# Aliases for compatibility
FoundryTemplateAgent = FoundryEmailAgent


async def create_foundry_email_agent() -> FoundryEmailAgent:
    """Factory function to create and initialize a Foundry email agent."""
    agent = FoundryEmailAgent()
    await agent.create_agent()
    return agent


create_foundry_template_agent = create_foundry_email_agent
