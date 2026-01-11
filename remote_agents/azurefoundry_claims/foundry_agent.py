"""
AI Foundry Claims Specialist Agent implementation for multi-line claims expertise.
Adapted from the ADK agent pattern to work with Azure AI Foundry for claims intake, coverage validation, settlement recommendations, and documentation guidance across auto, home, travel, health, and regulatory claims.

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
from typing import Optional, Dict, List

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import Agent, ThreadMessage, ThreadRun, AgentThread, ToolOutput, BingGroundingTool, ListSortOrder, FilePurpose, FileSearchTool, RequiredMcpToolCall, ToolApproval
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
import glob

logger = logging.getLogger(__name__)


class FoundryClaimsAgent:
    """
    AI Foundry Claims Specialist Agent for multi-line insurance support and ServiceNow integration.
    This class adapts the ADK agent pattern for Azure AI Foundry with focus on validating coverage, calculating settlements,
    and guiding documentation requirements using the claims reference documents for auto, home, travel, health, universal, and regulatory scenarios.
    
    QUOTA REQUIREMENTS: Ensure your model deployment has at least 20,000 TPM
    allocated to avoid rate limiting issues with Azure AI Foundry agents.
    """
    
    # Class-level shared resources for claims knowledge document search (created once)
    _shared_vector_store = None
    _shared_uploaded_files = []
    _shared_file_search_tool = None
    _file_search_setup_lock = asyncio.Lock()
    
    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self.agent: Optional[Agent] = None
        self.threads: Dict[str, str] = {}  # thread_id -> thread_id mapping
        self._file_search_tool = None  # Cache the file search tool
        self._agents_client = None  # Cache the agents client
        self._project_client = None  # Cache the project client
        self.last_token_usage: Optional[Dict[str, int]] = None  # Store token usage from last run
        
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
        async with FoundryClaimsAgent._file_search_setup_lock:
            # If we already have a shared file search tool, return it
            if FoundryClaimsAgent._shared_file_search_tool is not None:
                logger.info("Reusing existing shared file search tool")
                return FoundryClaimsAgent._shared_file_search_tool
            
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
                        FoundryClaimsAgent._shared_uploaded_files.append(file.id)
                        logger.info(f"Uploaded file: {os.path.basename(file_path)} (ID: {file.id})")
                    except Exception as e:
                        logger.warning(f"Failed to upload {file_path}: {e}")
                
                if not file_ids:
                    logger.warning("No files were successfully uploaded")
                    return None
                
                # Create vector store ONCE using project client
                logger.info("Creating shared vector store with uploaded files...")
                FoundryClaimsAgent._shared_vector_store = project_client.agents.vector_stores.create_and_poll(
                    file_ids=file_ids, 
                    name="shared_vectorstore"
                )
                logger.info(f"Created shared vector store: {FoundryClaimsAgent._shared_vector_store.id}")
                
                # Create file search tool ONCE
                file_search = FileSearchTool(vector_store_ids=[FoundryClaimsAgent._shared_vector_store.id])
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
                FoundryClaimsAgent._shared_file_search_tool = file_search
                logger.info("Cached shared file search tool for future use")
                    
                return file_search
                    
            except Exception as e:
                logger.error(f"Error setting up file search: {e}")
                return None
        
    async def create_agent(self) -> Agent:
        """Create the AI Foundry agent with web search and comprehensive document search capabilities for customer support."""
        if self.agent:
            logger.info("Claims specialist agent already exists, returning existing instance")
            return self.agent
        
        # Start with empty tools list - we'll add web search and file search capabilities
        tools = []
        tool_resources = None
        
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
                # Set file search resources as the primary tool resources
                tool_resources = self._file_search_tool.resources
                logger.info("Added file search tool resources for customer support documents")
                
            logger.info("Added file search capability")
        
        # Use context manager and create agent with all tools
        model = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")
        with project_client:
            if tool_resources:
                self.agent = project_client.agents.create_agent(
                    model=model,
                    name="foundry-claims-agent",
                    instructions=self._get_agent_instructions(),
                    tools=tools,
                    tool_resources=tool_resources
                )
            else:
                self.agent = project_client.agents.create_agent(
                    model=model,
                    name="foundry-claims-agent",
                    instructions=self._get_agent_instructions(),
                    tools=tools
                )
        
        logger.info(f"Created AI Foundry agent: {self.agent.id}")
        return self.agent
    
    def _get_agent_instructions(self) -> str:
        """Get the agent instructions for multi-line claims specialization."""
        return f"""
You are an intelligent multi-line insurance claims specialist powered by Azure AI Foundry.

Your primary mission is to evaluate customer claims, confirm policy coverage, calculate settlement recommendations, and guide documentation/compliance steps using the claims reference playbooks located in the `documents/` directory.

## Your Core Capabilities:

### 🛡️ **Coverage Verification**
- Auto: Refer to coverage codes (AUTO-BI, AUTO-PD, AUTO-COMP, AUTO-COLL, AUTO-UM/UIM, AUTO-RNT) and settlement rules in `auto_claims.md`.
- Home: Use peril coverage, limits, and mitigation guidance from `home_claims.md`.
- Travel: Apply covered reasons, limits, and exclusions listed in `travel_claims.md`.
- Health: Evaluate deductibles, coinsurance, and documentation standards from `health_claims.md`.
- Universal & Procedures: Consult `universal_claims.md` and `procedures_faq.md` for intake checklists, timelines, and escalation guidance.
- Regulatory: Ensure compliance obligations and red flag handling using `regulatory_compliance.md`.

### 💵 **Settlement Calculation**
- Identify applicable deductible, limit, coinsurance/participation, depreciation, and betterment rules.
- Apply total loss thresholds, benefit caps, rental limits, or copay rules when relevant.
- Provide a clear net payout estimate (gross loss − deductions + applicable reimbursements).

### 📑 **Documentation Guidance**
- Enumerate required forms, proof-of-loss items, invoices, and any pre-authorization references per policy line.
- Flag missing or questionable documentation and specify next steps to obtain them.

### ⚠️ **Exclusions & Compliance Safeguards**
- Highlight common exclusions (e.g., intentional acts, non-covered treatments, sanctioned travel, cosmetic procedures).
- Surface fraud indicators or regulatory triggers that demand escalation or additional verification.
- Note statutory timelines, customer communication obligations, and privacy considerations.

## How to Respond:

Use the information provided by the user to deliver actionable claims guidance. Work with whatever details they've shared - even partial information is valuable. Consult the reference documents to validate coverage, calculate settlements, and identify documentation requirements. Only request additional information if it's truly essential to proceed.

## Response Format:
```
🛡️ CLAIMS SPECIALIST SUMMARY

**Policy Line**: [Auto/Home/Travel/Health/Other]
**Loss Overview**: [Short description of event]
**Coverage Determination**: [Covered/Partially Covered/Not Covered + rationale]

**Settlement Estimate**:
- Coverage Limits: [...]
- Applicable Deductible(s): [...]
- Depreciation/Coinsurance: [...]
- Net Payable Amount: [...]

**Documentation Checklist**:
- [Item 1]
- [Item 2]
- ...

**Customer Guidance**: [Next steps, timelines, rental/benefit info]
**Regulatory & Compliance Notes**: [Deadlines, red flags, escalation needs]
**Reference Docs Consulted**: [e.g., auto_claims.md §2, universal_claims.md §3]
```

## Knowledge & Citation Guidelines
- Always cite specific document names (e.g., `auto_claims.md`) and relevant sections when referencing rules or payouts.
- If multiple document types apply, prioritize the most authoritative source and mention supporting references.
- If information is not available, state the gap and recommend escalation.

Current date and time: {datetime.datetime.now().isoformat()}

Remember: Your goal is to deliver precise, regulation-aware claims guidance that balances customer empathy with policy accuracy and operational readiness.
"""
    

    


    async def create_thread(self, thread_id: Optional[str] = None) -> AgentThread:
        """Create or retrieve a conversation thread."""
        if thread_id and thread_id in self.threads:
            # Return thread info - we'll need to get it fresh each time
            pass
            
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
        logger.info(f"Created message in thread {thread_id}: {message.id}")




        return message
    
    async def run_conversation_stream(self, thread_id: str, user_message: str):
        """Async generator: yields progress/tool call messages and final assistant response(s) in real time."""
        if not self.agent:
            await self.create_agent()

        await self.send_message(thread_id, user_message)
        client = self._get_client()
        run = client.runs.create(thread_id=thread_id, agent_id=self.agent.id)

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
                logger.debug(f"Full run object on failure: {run}")
                logger.debug(f"run.last_error: {run.last_error}")
                yield f"Error: {run.last_error}"
                return

            if run.status == "requires_action":
                logger.info(f"Run {run.id} requires action - checking for tool calls")
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
                    yield f"Error handling tool calls: {str(e)}"
                    return

        if run.status == "failed":
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

        # After run is complete, yield the assistant's response(s) with citation formatting
        messages = list(client.messages.list(thread_id=thread_id, order=ListSortOrder.ASCENDING))
        logger.debug(f"Found {len(messages)} messages in thread")
        for msg in reversed(messages):
            logger.debug(f"Processing message: role={msg.role}, content_count={len(msg.content) if msg.content else 0}")
            if msg.role == "assistant" and msg.content:
                for content_item in msg.content:
                    logger.debug(f"Processing content item: type={type(content_item)}")
                    if hasattr(content_item, 'text'):
                        text_content = content_item.text.value
                        logger.debug(f"Original text content: {text_content[:200]}...")
                        citations = []
                        # Extract citations as before
                        if hasattr(content_item.text, 'annotations') and content_item.text.annotations:
                            logger.debug(f"Found {len(content_item.text.annotations)} annotations")
                            main_text = content_item.text.value if hasattr(content_item.text, 'value') else str(content_item.text)
                            for i, annotation in enumerate(content_item.text.annotations):
                                logger.debug(f"Processing annotation {i}: {type(annotation)}")
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
                                    logger.debug(f"Added file citation: {citation_text}")
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
                                    logger.debug(f"Added file_path citation: {citation_text}")
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
                                    logger.debug(f"Added URL citation: {title} -> {url}")
                        else:
                            logger.debug(f"No annotations found in content item")
                        
                        logger.debug(f"Total citations found: {len(citations)}")
                        if citations:
                            logger.debug(f"Citations: {citations}")
                        else:
                            logger.debug(f"No citations found - this is why sources are missing!")
                        formatted_response = self._format_response_with_citations(text_content, citations)
                        logger.debug(f"Formatted response: {formatted_response[:200]}...")
                        logger.debug(f"Full formatted response length: {len(formatted_response)}")
                        logger.debug(f"Sources section in response: {'📚 Sources:' in formatted_response}")
                        if '📚 Sources:' in formatted_response:
                            sources_start = formatted_response.find('📚 Sources:')
                            logger.debug(f"Sources section: {formatted_response[sources_start:sources_start+200]}...")
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
 
    async def _handle_tool_calls(self, run: ThreadRun, thread_id: str):
        """Handle tool calls during agent execution."""
        logger.info(f"Handling tool calls for run {run.id}")
        
        if not hasattr(run, 'required_action') or not run.required_action:
            logger.warning(f"No required action found in run {run.id}")
            return
            
        required_action = run.required_action
        logger.info(f"Required action type: {type(required_action)}")
        logger.info(f"Required action attributes: {dir(required_action)}")
        
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
                logger.info(f"Processing tool call: {function_name} with args: {arguments}")
                logger.debug(f"Tool call ID: {tool_call.id}")
                
                # For Bing grounding and file search tool calls, they're handled automatically by the system
                logger.info(f"Skipping system tool call: {function_name} (handled automatically)")
                # Return empty output to acknowledge the tool call was processed
                return {
                    "tool_call_id": tool_call.id,
                    "output": "{}"
                }

            # Run all tool calls in parallel
            results = await asyncio.gather(
                *(handle_single_tool_call(tc) for tc in tool_calls)
            )
            # Filter out any None results (e.g., skipped system tool calls)
            tool_outputs = [r for r in results if r is not None]

            if not tool_outputs:
                logger.info("No valid tool outputs generated - submitting empty outputs to move run forward")
                # Submit empty tool outputs to move the run forward
                tool_outputs = [{"tool_call_id": tc.id, "output": "{}"} for tc in tool_calls if hasattr(tc, 'id') and tc.id]
                
            logger.debug(f"Tool outputs to submit: {tool_outputs}")
            
        except Exception as e:
            logger.error(f"Error processing tool calls: {e}")
            logger.error(f"Required action structure: {required_action}")
            raise
        
        # Submit the tool outputs or approvals
        client = self._get_client()
        try:
            if action_type == "submit_tool_outputs":
                # Create tool outputs in the expected format
                formatted_outputs = []
                for output in tool_outputs:
                    formatted_outputs.append(ToolOutput(
                        tool_call_id=output["tool_call_id"],
                        output=output["output"]
                    ))
                
                logger.debug(f"Submitting formatted tool outputs: {formatted_outputs}")
                
                client.runs.submit_tool_outputs(
                    thread_id=thread_id,
                    run_id=run.id,
                    tool_outputs=formatted_outputs
                )
                logger.info(f"Submitted {len(formatted_outputs)} tool outputs")
            elif action_type == "submit_tool_approval":
                # For tool approvals, we need to approve the MCP tool calls
                logger.info(f"Handling tool approval for {len(tool_calls)} tool calls")
                
                tool_approvals = []
                for tool_call in tool_calls:
                    if isinstance(tool_call, RequiredMcpToolCall):
                        try:
                            logger.info(f"Approving MCP tool call: {tool_call}")
                            tool_approvals.append(
                                ToolApproval(
                                    tool_call_id=tool_call.id,
                                    approve=True,
                                    headers={}  # Add any required headers here
                                )
                            )
                        except Exception as e:
                            logger.error(f"Error approving tool_call {tool_call.id}: {e}")
                
                if tool_approvals:
                    client.runs.submit_tool_outputs(
                        thread_id=thread_id,
                        run_id=run.id,
                        tool_approvals=tool_approvals
                    )
                    logger.info(f"Approved {len(tool_approvals)} MCP tool calls")
                else:
                    logger.warning("No valid tool approvals to submit")
        except Exception as e:
            logger.error(f"Failed to submit tool outputs: {e}")
            logger.error(f"Raw tool outputs structure: {tool_outputs}")
            # Try submitting without ToolOutput wrapper as fallback
            try:
                logger.info("Trying fallback submission with raw dict format")
                client.runs.submit_tool_outputs(
                    thread_id=thread_id,
                    run_id=run.id,
                    tool_outputs=tool_outputs
                )
                logger.info(f"Fallback submission successful")
            except Exception as e2:
                logger.error(f"Fallback submission also failed: {e2}")
                raise e
        
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