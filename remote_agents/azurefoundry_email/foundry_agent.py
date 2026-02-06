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
import uuid
import tempfile
from pathlib import Path
from typing import Optional, Dict, List, Any

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import Agent, ThreadMessage, ThreadRun, AgentThread, ToolOutput, BingGroundingTool, ListSortOrder, FilePurpose, FileSearchTool, RequiredMcpToolCall, ToolApproval
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
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
        self._blob_service_client: Optional[BlobServiceClient] = None
        self._latest_artifacts: List[Dict[str, Any]] = []  # Store file artifacts for A2A
        self.last_token_usage: Optional[Dict[str, int]] = None  # Store token usage from last run

    def _get_blob_service_client(self) -> Optional[BlobServiceClient]:
        """Return a BlobServiceClient if Azure storage is configured and forced."""
        force_blob = os.getenv("FORCE_AZURE_BLOB", "false").lower() == "true"
        if not force_blob:
            return None
        if self._blob_service_client is not None:
            return self._blob_service_client

        connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            logger.error("AZURE_STORAGE_CONNECTION_STRING must be set when FORCE_AZURE_BLOB=true")
            raise RuntimeError("Missing AZURE_STORAGE_CONNECTION_STRING for blob uploads")

        try:
            self._blob_service_client = BlobServiceClient.from_connection_string(
                connection_string,
                api_version="2023-11-03",
            )
            return self._blob_service_client
        except Exception as e:
            logger.error(f"Failed to create BlobServiceClient: {e}")
            raise
        
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
        """Get the agent instructions for email composition, sending, and reading."""
        return f"""
You are an Email Communications Specialist. You can both READ incoming emails and SEND emails via Microsoft Graph API.

## CAPABILITIES

### 1. READ EMAILS (Inbox Retrieval)
When users ask to check, read, show, or retrieve emails, output a request in this format:

```EMAIL_FETCH
COUNT: 50
UNREAD_ONLY: false
FROM_ADDRESS: 
SUBJECT_CONTAINS: 
SINCE_DATE: 
INCLUDE_ATTACHMENTS: false
```END_EMAIL_FETCH

Parameters:
- COUNT: Number of emails to fetch (1-100, default: 50)
  * Use 50-100 when searching for specific emails (by sender, subject, or attachments)
  * Use 10-20 only when user explicitly asks for "recent" or "last few" emails
- UNREAD_ONLY: true/false - only get unread emails
- FROM_ADDRESS: Filter by sender email (partial match)
- SUBJECT_CONTAINS: Filter by subject text (partial match)  
- SINCE_DATE: Get emails after this date (format: 2026-02-04)
- INCLUDE_ATTACHMENTS: true/false - download and extract file attachments

**IMPORTANT for INCLUDE_ATTACHMENTS:**
- Set to `true` when user explicitly asks for attachments, files, or documents from emails
- Set to `true` for: "get emails with attachments", "download files from my emails", "attachments from invoices"
- Set to `false` for: "show my emails", "any new messages?", "what emails do I have?"
- When `true`, all email attachments will be downloaded and made available

Examples:
- "Show my last 5 emails" → COUNT: 5, INCLUDE_ATTACHMENTS: false
- "Any unread emails?" → COUNT: 20, UNREAD_ONLY: true, INCLUDE_ATTACHMENTS: false
- "Find email from Ryan about invoice" → COUNT: 100, FROM_ADDRESS: Ryan, SUBJECT_CONTAINS: invoice, INCLUDE_ATTACHMENTS: true
- "Get my emails with attachments" → COUNT: 50, INCLUDE_ATTACHMENTS: true
- "Download attachments from invoice emails" → COUNT: 100, SUBJECT_CONTAINS: invoice, INCLUDE_ATTACHMENTS: true
- "Emails about invoices with files" → COUNT: 100, SUBJECT_CONTAINS: invoice, INCLUDE_ATTACHMENTS: true
- "Emails from john@company.com" → COUNT: 50, FROM_ADDRESS: john@company.com, INCLUDE_ATTACHMENTS: false

### 2. SEND EMAILS
When you have information to send an email, output it in this format:

```EMAIL_TO_SEND
TO: recipient@example.com
SUBJECT: Your Subject Here
CC: optional@example.com (or leave blank)
BODY:
<html>
<p>Your email content here...</p>
</html>
```END_EMAIL

## CRITICAL RULES

**For Reading Emails:**
- When user asks to "check emails", "show my inbox", "any new emails?", etc. → Use EMAIL_FETCH format
- When user mentions "attachments", "files", "documents" → Set INCLUDE_ATTACHMENTS: true
- After fetching, summarize the emails in a readable format
- If attachments were downloaded, mention them in your response
- You can suggest actions like "Would you like me to reply to any of these?"

**For Sending Emails:**
- **NEVER** ask "Would you like me to send this?" or wait for confirmation
- **ALWAYS** output the EMAIL_TO_SEND block immediately when you have recipient + subject + content
- Include the FULL report content in the BODY - the system will generate a PDF if appropriate
- Use HTML formatting for professional appearance

## RESPONSE EXAMPLES

**User: "Check my emails"**
You: "I'll check your inbox now.

```EMAIL_FETCH
COUNT: 50
UNREAD_ONLY: false
FROM_ADDRESS: 
SUBJECT_CONTAINS: 
SINCE_DATE: 
INCLUDE_ATTACHMENTS: false
```END_EMAIL_FETCH"

**User: "Get my last 5 emails with attachments"**
You: "I'll retrieve your emails and download any attachments.

```EMAIL_FETCH
COUNT: 5
UNREAD_ONLY: false
FROM_ADDRESS: 
SUBJECT_CONTAINS: 
SINCE_DATE: 
INCLUDE_ATTACHMENTS: true
```END_EMAIL_FETCH"

**User: "Download invoice attachments from today"**
You: "I'll get invoices from today and download their attachments.

```EMAIL_FETCH
COUNT: 100
UNREAD_ONLY: false
FROM_ADDRESS: 
SUBJECT_CONTAINS: invoice
SINCE_DATE: {datetime.datetime.now().strftime('%Y-%m-%d')}
INCLUDE_ATTACHMENTS: true
```END_EMAIL_FETCH"

**User: "Send this report to simon@company.com: [Report content...]"**
You: "I'll send that email now.

```EMAIL_TO_SEND
TO: simon@company.com
SUBJECT: Your AI Consultation Report
CC: 
BODY:
<html>
<p>Dear Simon,</p>
[Full report content in HTML...]
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
    
    async def run_conversation_stream(self, thread_id: str, user_message: str, context_id: str = None):
        """Run the conversation and yield responses.
        
        Args:
            thread_id: The conversation thread ID
            user_message: The user's message
            context_id: The A2A context ID (format: {session_id}::{conversation_id})
                       Used for uploading files to the user's session blob storage path
        """
        # Store context_id for use in file upload methods
        self._current_context_id = context_id
        
        if not self.agent:
            await self.create_agent()

        await self.send_message(thread_id, user_message)
        client = self._get_client()
        # Reduced to 3 messages to prevent token accumulation in workflow execution
        run = client.runs.create(
            thread_id=thread_id,
            agent_id=self.agent.id,
            truncation_strategy={"type": "last_messages", "last_messages": 3}
        )
        
        logger.info(f"Created run {run.id} with status {run.status}")

        max_iterations = 25
        iterations = 0

        while run.status in ["queued", "in_progress", "requires_action"] and iterations < max_iterations:
            iterations += 1
            await asyncio.sleep(2)

            try:
                run = client.runs.get(thread_id=thread_id, run_id=run.id)
                logger.info(f"Run status: {run.status} (iteration {iterations})")
            except Exception as e:
                yield f"Error: {str(e)}"
                return

            if run.status == "failed":
                logger.error(f"Run failed: {run.last_error}")
                yield f"Error: {run.last_error}"
                return

            if run.status == "requires_action":
                if hasattr(run, 'required_action') and run.required_action:
                    await self._handle_tool_calls(run, thread_id)
                run = client.runs.get(thread_id=thread_id, run_id=run.id)

        if run.status == "failed":
            logger.error(f"Run failed after loop: {run.last_error}")
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

        # Get the response
        messages = list(client.messages.list(thread_id=thread_id, order=ListSortOrder.ASCENDING))
        for msg in reversed(messages):
            if msg.role == "assistant" and msg.content:
                for content_item in msg.content:
                    if hasattr(content_item, 'text'):
                        text_content = content_item.text.value
                        
                        # Check if there's an email fetch request
                        fetch_result, fetch_clean = self._try_fetch_emails(text_content)
                        if fetch_result:
                            yield f"{fetch_clean}\n\n{fetch_result}"
                            break
                        
                        # Check if there's an email to send
                        email_result, clean_content = self._try_send_email(text_content)
                        if email_result:
                            # Show clean summary instead of raw EMAIL_TO_SEND block
                            yield f"{clean_content}\n\n{email_result}"
                        else:
                            yield text_content
                break
    
    def _try_fetch_emails(self, response_text: str) -> tuple[Optional[str], str]:
        """Check if the response contains an email fetch request and retrieve emails.
        Returns: (formatted_emails, cleaned_content)
        """
        import re
        from datetime import datetime, timedelta
        
        # Look for the EMAIL_FETCH block
        pattern = r'```EMAIL_FETCH\s*\n(.*?)\n```END_EMAIL_FETCH'
        match = re.search(pattern, response_text, re.DOTALL)
        
        if not match:
            return None, response_text
        
        fetch_block = match.group(1)
        logger.info(f"📧 EMAIL_FETCH block content:\n{fetch_block}")
        
        # Parse the fetch parameters line by line
        # Each line is "FIELD: value" or "FIELD:" (empty value)
        count = 10
        unread_only = False
        from_address = None
        subject_contains = None
        since_date = None
        include_attachments = False
        
        for line in fetch_block.strip().split('\n'):
            line = line.strip()
            if ':' in line:
                field, _, value = line.partition(':')
                field = field.strip().upper()
                value = value.strip()
                
                if field == 'COUNT' and value.isdigit():
                    count = int(value)
                elif field == 'UNREAD_ONLY':
                    unread_only = value.lower() == 'true'
                elif field == 'FROM_ADDRESS' and value:
                    from_address = value
                elif field == 'SUBJECT_CONTAINS' and value:
                    subject_contains = value
                elif field == 'SINCE_DATE' and value:
                    since_date = value
                elif field == 'INCLUDE_ATTACHMENTS':
                    include_attachments = value.lower() == 'true'
        
        logger.info(f"📧 Parsed EMAIL_FETCH: count={count}, unread={unread_only}, from={from_address}, subject={subject_contains}, since={since_date}, include_attachments={include_attachments}")
        
        # Remove the EMAIL_FETCH block from response for clean display
        clean_content = re.sub(pattern, '', response_text, flags=re.DOTALL).strip()
        if not clean_content:
            clean_content = "📬 Checking your inbox..."
        
        # Clear any previous artifacts
        self._latest_artifacts = []
        
        # Fetch the emails
        try:
            from email_config import get_emails, get_email_attachments, download_attachment
            
            result = get_emails(
                count=count,
                unread_only=unread_only,
                from_address=from_address,
                subject_contains=subject_contains,
                since_date=since_date
            )
            
            if not result["success"]:
                return f"❌ {result['message']}", clean_content
            
            emails = result["emails"]
            
            if not emails:
                filters_desc = []
                if unread_only:
                    filters_desc.append("unread")
                if from_address:
                    filters_desc.append(f"from '{from_address}'")
                if subject_contains:
                    filters_desc.append(f"about '{subject_contains}'")
                if since_date:
                    filters_desc.append(f"since {since_date}")
                
                filter_text = " ".join(filters_desc) if filters_desc else ""
                return f"📭 No {filter_text} emails found.", clean_content
            
            # If attachments requested, process them
            downloaded_attachments = []
            if include_attachments:
                logger.info(f"� Processing attachments for {len(emails)} emails...")
                for email in emails:
                    if email.get("has_attachments"):
                        email_id = email.get("id")
                        email_subject = email.get("subject", "Unknown")
                        
                        # Get attachment list for this email
                        att_result = get_email_attachments(email_id)
                        if att_result["success"] and att_result["attachments"]:
                            for att in att_result["attachments"]:
                                # Skip inline attachments (usually images in signature)
                                if att.get("is_inline"):
                                    continue
                                
                                # Download the attachment
                                dl_result = download_attachment(email_id, att["id"])
                                if dl_result["success"] and dl_result["content"]:
                                    # Upload to blob storage
                                    blob_url = self._upload_attachment_to_blob(
                                        content=dl_result["content"],
                                        filename=dl_result["name"],
                                        content_type=dl_result["content_type"]
                                    )
                                    
                                    if blob_url:
                                        attachment_info = {
                                            "name": dl_result["name"],
                                            "url": blob_url,
                                            "content_type": dl_result["content_type"],
                                            "size": dl_result["size"],
                                            "from_email": email_subject,
                                        }
                                        downloaded_attachments.append(attachment_info)
                                        
                                        # Add to artifacts for A2A payload
                                        self._latest_artifacts.append({
                                            "artifact-uri": blob_url,
                                            "file-name": dl_result["name"],
                                            "mime": dl_result["content_type"],
                                            "file-size": dl_result["size"],
                                            "storage-type": "azure-blob",
                                        })
                                        logger.info(f"✅ Uploaded attachment: {dl_result['name']} -> {blob_url[:80]}...")
                                    else:
                                        logger.warning(f"⚠️ Failed to upload attachment: {dl_result['name']}")
            
            # Format emails for display
            formatted = f"📬 **Found {len(emails)} email(s):**\n\n"
            
            for i, email in enumerate(emails, 1):
                # Format received time
                received = email.get("received_at", "")
                if received:
                    try:
                        dt = datetime.fromisoformat(received.replace("Z", "+00:00"))
                        received = dt.strftime("%b %d, %Y at %I:%M %p")
                    except:
                        pass
                
                read_status = "" if email.get("is_read") else "🔵 "
                attachment_icon = "📎 " if email.get("has_attachments") else ""
                
                formatted += f"---\n"
                formatted += f"**{i}. {read_status}{attachment_icon}{email.get('subject', '(No Subject)')}**\n"
                formatted += f"   From: {email.get('from_name', 'Unknown')} <{email.get('from_email', '')}>\n"
                formatted += f"   Received: {received}\n"
                
                # Show preview
                preview = email.get("preview", "")
                if preview:
                    # Truncate preview if too long
                    if len(preview) > 150:
                        preview = preview[:150] + "..."
                    formatted += f"   Preview: {preview}\n"
                formatted += "\n"
            
            # Add attachment summary if any were downloaded
            if downloaded_attachments:
                formatted += f"\n---\n📎 **Downloaded {len(downloaded_attachments)} attachment(s):**\n\n"
                for att in downloaded_attachments:
                    size_kb = att["size"] / 1024
                    formatted += f"• **{att['name']}** ({size_kb:.1f} KB) - from: {att['from_email']}\n"
            
            return formatted, clean_content
            
        except Exception as e:
            logger.error(f"Failed to fetch emails: {e}")
            return f"❌ Failed to fetch emails: {str(e)}", clean_content
    
    def _upload_attachment_to_blob(self, content: bytes, filename: str, content_type: str) -> Optional[str]:
        """Upload an email attachment to Azure Blob Storage and return the URL with SAS token.
        
        Uses the unified blob path: uploads/{session_id}/{file_id}/{filename}
        This allows the file to appear in the user's file history automatically.
        """
        from datetime import datetime, timedelta
        from azure.core.credentials import AzureNamedKeyCredential, AzureSasCredential
        
        blob_client = self._get_blob_service_client()
        if not blob_client:
            logger.warning("Blob storage not configured, skipping upload")
            return None

        container_name = os.getenv("AZURE_BLOB_CONTAINER", "a2a-files")
        
        # Extract session_id from context_id (format: {session_id}::{conversation_id})
        # This allows files to be stored in the user's session path
        context_id = getattr(self, '_current_context_id', None)
        if context_id and '::' in context_id:
            session_id = context_id.split('::')[0]
        else:
            # Fallback to legacy path if no context_id available
            session_id = None
            logger.warning(f"No context_id available, using legacy path for {filename}")
        
        # Generate unique file_id
        file_id = uuid.uuid4().hex
        
        # Use unified path: uploads/{session_id}/{file_id}/{filename}
        # This matches the path used by user uploads, so files appear in file history
        if session_id:
            blob_name = f"uploads/{session_id}/{file_id}/{filename}"
            logger.info(f"📁 Uploading to unified path: {blob_name}")
        else:
            # Legacy fallback path (for backwards compatibility)
            blob_name = f"email-attachments/{file_id}/{filename}"
            logger.warning(f"📁 Using legacy path: {blob_name}")
        
        try:
            container_client = blob_client.get_container_client(container_name)
            if not container_client.exists():
                container_client.create_container()
            
            # Upload the content with proper content type
            from azure.storage.blob import ContentSettings
            content_settings = ContentSettings(content_type=content_type)
            container_client.upload_blob(
                name=blob_name, 
                data=content, 
                overwrite=True,
                content_settings=content_settings
            )
            
            # Generate SAS token
            sas_duration_minutes = int(os.getenv("AZURE_BLOB_SAS_DURATION_MINUTES", str(24 * 60)))
            sas_token: Optional[str] = None
            
            service_client = self._blob_service_client
            
            if service_client is not None:
                credential = getattr(service_client, "credential", None)
                account_key_value: Optional[str] = None
                
                if isinstance(credential, AzureNamedKeyCredential):
                    account_key_value = credential.key
                elif isinstance(credential, AzureSasCredential):
                    sas_token = credential.signature.lstrip("?")
                elif hasattr(credential, "account_key"):
                    account_key_value = getattr(credential, "account_key")
                elif hasattr(credential, "key"):
                    account_key_value = getattr(credential, "key")
                
                if callable(account_key_value):
                    account_key_value = account_key_value()
                if isinstance(account_key_value, bytes):
                    account_key_value = account_key_value.decode()
                
                if account_key_value:
                    try:
                        sas_token = generate_blob_sas(
                            account_name=service_client.account_name,
                            container_name=container_name,
                            blob_name=blob_name,
                            account_key=account_key_value,
                            permission=BlobSasPermissions(read=True),
                            expiry=datetime.utcnow() + timedelta(minutes=sas_duration_minutes),
                            protocol="https",
                            version="2023-11-03",
                        )
                    except Exception as sas_error:
                        logger.error(f"Failed to generate SAS URL: {sas_error}")
            
            # Try user delegation key if shared key didn't work
            if sas_token is None and self._blob_service_client is not None:
                try:
                    delegation_key = self._blob_service_client.get_user_delegation_key(
                        key_start_time=datetime.utcnow() - timedelta(minutes=5),
                        key_expiry_time=datetime.utcnow() + timedelta(minutes=sas_duration_minutes),
                    )
                    sas_token = generate_blob_sas(
                        account_name=self._blob_service_client.account_name,
                        container_name=container_name,
                        blob_name=blob_name,
                        user_delegation_key=delegation_key,
                        permission=BlobSasPermissions(read=True),
                        expiry=datetime.utcnow() + timedelta(minutes=sas_duration_minutes),
                        version="2023-11-03",
                    )
                except Exception as ude_err:
                    logger.warning(f"Failed to generate user delegation SAS: {ude_err}")
            
            if sas_token:
                base_url = blob_client.get_blob_client(container=container_name, blob=blob_name).url
                token = sas_token.lstrip("?")
                separator = '&' if '?' in base_url else '?'
                return f"{base_url}{separator}{token}"
            
            raise RuntimeError("Unable to generate SAS token for blob upload")
            
        except Exception as e:
            logger.error(f"Failed to upload attachment to blob storage: {e}")
            return None
    
    def pop_latest_artifacts(self) -> List[Dict[str, Any]]:
        """Return and clear any file artifacts (downloaded attachments)."""
        artifacts = self._latest_artifacts
        self._latest_artifacts = []
        return artifacts
    
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
        
        # Check if this looks like a report (for PDF generation)
        is_report = any(keyword in body.lower() or keyword in subject.lower() 
                       for keyword in ['report', 'summary', 'analysis', 'findings', 'recommendations'])
        
        # Try to generate PDF if it's a report
        pdf_path = None
        pdf_generated = False
        email_body = body  # Default to full body
        
        if is_report:
            try:
                from pdf_generator import generate_report_pdf, is_pdf_available
                if is_pdf_available():
                    # Extract recipient name from email or body
                    recipient_name = ""
                    name_match = re.search(r'Dear\s+(\w+)', body, re.IGNORECASE)
                    if name_match:
                        recipient_name = name_match.group(1)
                    
                    # Generate PDF from FULL body content
                    pdf_path = generate_report_pdf(
                        report_content=body,
                        recipient_name=recipient_name,
                        recipient_email=to,
                    )
                    pdf_generated = True
                    logger.info(f"Generated PDF report: {pdf_path}")
                    
                    # Create a SHORT email body since full report is in PDF
                    greeting = f"Dear {recipient_name}," if recipient_name else "Hello,"
                    email_body = f"""<html>
<p>{greeting}</p>
<p>Thank you for your time during our consultation.</p>
<p><strong>Please find your personalized report attached as a PDF.</strong></p>
<p>The attached document contains our detailed analysis and recommendations tailored to your needs.</p>
<p>If you have any questions, please don't hesitate to reach out.</p>
<p>Best regards,<br><strong>Cay Digital Team</strong></p>
</html>"""
            except ImportError as e:
                logger.warning(f"PDF generation not available: {e}")
            except Exception as e:
                logger.warning(f"Failed to generate PDF: {e}")
        
        # Build clean summary
        clean_summary = f"📧 **Email Sent**\n\n**To:** {to}\n**Subject:** {subject}"
        if cc and cc.lower() != "body:" and "@" in cc:
            clean_summary += f"\n**CC:** {cc}"
        if pdf_generated:
            clean_summary += f"\n**📎 Attachment:** Cay Digital Report (PDF)"
        clean_summary += f"\n\n{body_clean}"
        
        # Send the email
        try:
            from email_config import send_email, send_email_with_cc
            
            # Prepare attachments if PDF was generated
            attachments = None
            if pdf_path:
                attachments = [{"path": pdf_path, "name": f"Cay_Digital_Report_{subject[:30].replace(' ', '_')}.pdf"}]
            
            if cc and "@" in cc:
                cc_list = [e.strip() for e in cc.split(",") if "@" in e]
                result = send_email_with_cc(to=to, subject=subject, body=email_body, cc=cc_list, attachments=attachments)
            else:
                result = send_email(to=to, subject=subject, body=email_body, attachments=attachments)
            
            # Clean up temp PDF file
            if pdf_path:
                try:
                    import os
                    os.remove(pdf_path)
                except:
                    pass
            
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
