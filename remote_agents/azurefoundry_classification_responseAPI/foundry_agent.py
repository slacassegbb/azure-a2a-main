"""
AI Foundry Classification Triage Agent implementation using Responses API.
Migrated from Assistants API to Responses API for compatibility with newer models.

NOTE: This version uses Responses API which does NOT have built-in knowledge grounding.
The file upload works but is for vision-based PDF analysis, NOT for RAG/knowledge base.
To add knowledge grounding, you would need to integrate with Azure AI Search (Foundry IQ).

IMPORTANT: QUOTA REQUIREMENTS FOR AZURE AI FOUNDRY AGENTS
=========================================================
Ensure your model deployment has at least 20,000 TPM allocated to avoid rate limiting.
"""
import os
import time
import datetime
import asyncio
import logging
import json
from typing import Optional, Dict, List

from openai import AzureOpenAI, AsyncAzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
import glob

logger = logging.getLogger(__name__)


class FoundryClassificationAgent:
    """
    AI Foundry Classification Triage Agent using Responses API.
    
    IMPORTANT: This version uploads PDFs but they are used for vision analysis,
    NOT for knowledge base grounding like Assistants API vector stores did.
    """
    
    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self.agent: Optional[str] = None  # Agent instructions
        self.threads: Dict[str, str] = {}  # thread_id -> session mapping
        self._client = None  # Sync client for file uploads
        self._async_client = None  # Async client for responses
        self._uploaded_file_ids: List[str] = []
        self.last_token_usage: Optional[Dict[str, int]] = None
        
    def _get_client(self) -> AzureOpenAI:
        """Get OpenAI client with Azure authentication."""
        if self._client is None:
            # Convert AI Foundry endpoint to Azure OpenAI endpoint with /openai/v1/
            # From: https://RESOURCE.services.ai.azure.com/subscriptions/.../providers/Microsoft.MachineLearningServices/workspaces/...
            # To: https://RESOURCE.openai.azure.com/openai/v1/
            
            if "services.ai.azure.com" in self.endpoint:
                # Extract resource name from AI Foundry endpoint
                # Example: https://simonfoundry.services.ai.azure.com/...
                parts = self.endpoint.split("//")[1].split(".")[0]
                openai_endpoint = f"https://{parts}.openai.azure.com/openai/v1/"
            else:
                # Already in OpenAI format
                openai_endpoint = self.endpoint if self.endpoint.endswith("/openai/v1/") else f"{self.endpoint.rstrip('/')}/openai/v1/"
            
            token_provider = get_bearer_token_provider(
                self.credential,
                "https://cognitiveservices.azure.com/.default"
            )
            
            # Responses API requires BOTH api_version parameter AND the /openai/v1/ path
            # Use "preview" as the api_version for Responses API features
            self._client = AzureOpenAI(
                base_url=openai_endpoint,
                azure_ad_token_provider=token_provider,
                api_version="preview"
            )
            
        return self._client
    
    def _get_async_client(self) -> AsyncAzureOpenAI:
        """Get async OpenAI client for streaming responses (non-blocking)."""
        if self._async_client is None:
            if "services.ai.azure.com" in self.endpoint:
                parts = self.endpoint.split("//")[1].split(".")[0]
                openai_endpoint = f"https://{parts}.openai.azure.com/openai/v1/"
            else:
                openai_endpoint = self.endpoint if self.endpoint.endswith("/openai/v1/") else f"{self.endpoint.rstrip('/')}/openai/v1/"
            
            token_provider = get_bearer_token_provider(
                self.credential,
                "https://cognitiveservices.azure.com/.default"
            )
            
            self._async_client = AsyncAzureOpenAI(
                base_url=openai_endpoint,
                azure_ad_token_provider=token_provider,
                api_version="preview"
            )
            
        return self._async_client
    
    async def _setup_file_search(self, files_directory: str = "documents") -> List[str]:
        """
        Upload PDF files for vision-based analysis (NOT knowledge base grounding).
        Returns list of file IDs.
        """
        if self._uploaded_file_ids:
            logger.info(f"Using cached uploaded files: {self._uploaded_file_ids}")
            return self._uploaded_file_ids
            
        client = self._get_client()
        
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            docs_path = os.path.join(script_dir, files_directory)
            
            if not os.path.exists(docs_path):
                logger.warning(f"Documents directory not found: {docs_path}")
                return []
            
            # Upload PDF files
            pdf_files = glob.glob(os.path.join(docs_path, "*.pdf"))
            
            if not pdf_files:
                logger.warning(f"No PDF files found in {docs_path}")
                return []
            
            file_ids = []
            for pdf_path in pdf_files:
                logger.info(f"Uploading file: {pdf_path}")
                with open(pdf_path, "rb") as f:
                    file = client.files.create(
                        file=f,
                        purpose="assistants"  # Required even for Responses API
                    )
                    file_ids.append(file.id)
                    logger.info(f"Uploaded file: {os.path.basename(pdf_path)}, ID: {file.id}")
            
            self._uploaded_file_ids = file_ids
            return file_ids
            
        except Exception as e:
            logger.error(f"Error setting up file search: {str(e)}")
            return []
    
    def _get_agent_instructions(self) -> str:
        """Get agent instructions with explicit reference to uploaded PDF."""
        return """You are a Classification and Triage Agent for incident management using ServiceNow standards.

CRITICAL: Use the uploaded Classification_Triage.pdf document as your primary knowledge base for all classifications.

Your responsibilities:
1. Classify incidents into proper ServiceNow categories
2. Assign appropriate priority levels (P1-P5)
3. Route to the correct assignment group
4. Follow ServiceNow best practices from the uploaded document

Always reference the Classification_Triage.pdf for:
- Category definitions
- Priority criteria
- Assignment group mappings
- Escalation procedures

Be concise and specific in your classifications."""

    async def initialize_agent(self):
        """Initialize the agent with uploaded files."""
        logger.info("Initializing Classification Agent with Responses API")
        
        # Upload files for vision analysis (not knowledge grounding)
        await self._setup_file_search()
        
        # Store agent instructions
        self.agent = self._get_agent_instructions()
        
        logger.info("Agent initialized successfully")

    def create_thread(self, thread_id: str = None) -> str:
        """
        Create or return a thread ID (session identifier).
        Responses API is stateless, so we just track session IDs.
        """
        if thread_id and thread_id in self.threads:
            return self.threads[thread_id]
        
        new_thread_id = f"session_{int(time.time())}_{os.urandom(4).hex()}"
        self.threads[thread_id or new_thread_id] = new_thread_id
        logger.info(f"Created new session: {new_thread_id}")
        return new_thread_id

    def get_thread(self, thread_id: str) -> Optional[str]:
        """Get existing thread/session ID."""
        return self.threads.get(thread_id)

    def delete_thread(self, thread_id: str):
        """Remove thread/session from tracking."""
        if thread_id in self.threads:
            del self.threads[thread_id]
            logger.info(f"Deleted session: {thread_id}")

    async def run_conversation_stream(
        self,
        user_message: str,
        thread_id: str,
        additional_instructions: Optional[str] = None
    ):
        """
        Run a streaming conversation using Responses API with async client.
        
        NOTE: The PDF is included in the request but is used for vision analysis,
        NOT for knowledge base grounding. This is a limitation of Responses API.
        """
        # Build input content with PDF and text
        input_content = []
        
        # Add uploaded PDFs as input files (for vision, not grounding)
        if self._uploaded_file_ids:
            for file_id in self._uploaded_file_ids:
                input_content.append({
                    "type": "input_file",
                    "file_id": file_id
                })
        
        # Add user message
        input_content.append({
            "type": "input_text",
            "text": user_message
        })
        
        # Combine instructions
        full_instructions = self.agent
        if additional_instructions:
            full_instructions += f"\n\n{additional_instructions}"
        
        # Create response with streaming using async client for parallel execution
        try:
            client = self._get_async_client()
            response = await client.responses.create(
                model=os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-4o"),
                input=[{
                    "role": "user",
                    "content": input_content
                }],
                instructions=full_instructions,
                stream=True,
                max_output_tokens=4000
            )
            
            # Stream the response using async iteration
            full_response = ""
            event_count = 0
            async for event in response:
                event_count += 1
                logger.debug(f"Event {event_count}: type={event.type}")
                
                if event.type == 'response.output_text.delta':
                    chunk = event.delta
                    full_response += chunk
                    yield chunk
                elif event.type == 'response.done':
                    logger.info(f"Response done event received")
                else:
                    logger.debug(f"Unhandled event type: {event.type}")
            
            # Log completion
            logger.info(f"Response completed, length: {len(full_response)}, events: {event_count}")
            
        except Exception as e:
            logger.error(f"Error in run_conversation_stream: {str(e)}")
            yield f"Error: {str(e)}"

    async def process_user_message(
        self, 
        thread_id: str, 
        user_message: str,
        stream_callback=None
    ) -> str:
        """
        Process a user message and return the assistant's response.
        """
        if not self.agent:
            await self.initialize_agent()
        
        # Ensure thread exists
        if not self.get_thread(thread_id):
            self.create_thread(thread_id)
        
        full_response = ""
        
        async for chunk in self.run_conversation_stream(user_message, thread_id):
            full_response += chunk
            if stream_callback:
                await stream_callback(chunk)
        
        return full_response

    async def cleanup(self):
        """Cleanup resources."""
        logger.info("Cleaning up Classification Agent")
        if self._async_client:
            await self._async_client.close()
        self._client = None
        self._async_client = None
        self._uploaded_file_ids = []
        self.threads = {}
