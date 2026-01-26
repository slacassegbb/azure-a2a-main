"""
Azure AI Foundry A2A Agent Template
====================================

This is a template for creating custom Azure AI Foundry agents that work with the A2A protocol.
Use this as a starting point to build your own specialized agents.

IMPORTANT: QUOTA REQUIREMENTS FOR AZURE AI FOUNDRY AGENTS
=========================================================

Based on Microsoft support documentation and user reports, Azure AI Foundry
agents require a MINIMUM of 20,000 TPM (Tokens Per Minute) to function properly
without rate limiting issues.

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
from datetime import datetime as dt_datetime, timedelta
import asyncio
import logging
import json
import uuid
import httpx
import io
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any
from PIL import Image
from openai import OpenAI

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import Agent, ThreadMessage, ThreadRun, AgentThread, ToolOutput, BingGroundingTool, ListSortOrder, FilePurpose, FileSearchTool, RequiredMcpToolCall, ToolApproval
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.core.credentials import AzureNamedKeyCredential, AzureSasCredential
import glob

logger = logging.getLogger(__name__)


class FoundryTemplateAgent:
    """
    Sora 2 Video Generator Agent
    
    An Azure AI Foundry agent specialized in generating AI videos using 
    Azure OpenAI's Sora 2 model. Supports text-to-video and image-to-video
    generation with various resolutions and durations.
    
    Features:
    - Text-to-video generation from natural language prompts
    - Image-to-video transformation with reference images
    - Supports 1280x720 (landscape) and 720x1280 (portrait) resolutions
    - Video durations: 4, 8, or 12 seconds
    - Audio generation in output videos
    
    QUOTA REQUIREMENTS: Ensure your model deployment has at least 20,000 TPM
    allocated to avoid rate limiting issues with Azure AI Foundry agents.
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
        self.threads: Dict[str, str] = {}  # thread_id -> thread_id mapping
        self._file_search_tool = None  # Cache the file search tool
        self._agents_client = None  # Cache the agents client
        self._project_client = None  # Cache the project client
        self._blob_service_client: Optional[BlobServiceClient] = None
        self._latest_artifacts: List[Dict[str, Any]] = []  # Track generated artifacts for A2A
        
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

    def _get_blob_service_client(self) -> Optional[BlobServiceClient]:
        """Return a BlobServiceClient if Azure storage is configured and forced."""
        force_blob = os.getenv("FORCE_AZURE_BLOB", "false").lower() == "true"
        if not force_blob:
            return None
        if self._blob_service_client is not None:
            return self._blob_service_client

        conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not conn_str:
            raise RuntimeError("Missing AZURE_STORAGE_CONNECTION_STRING for blob uploads")

        try:
            self._blob_service_client = BlobServiceClient.from_connection_string(
                conn_str
            )
            logger.info("BlobServiceClient initialized successfully.")
            return self._blob_service_client
        except Exception as e:
            logger.error(f"Failed to initialize BlobServiceClient: {e}")
            return None

    def _upload_to_blob(self, file_path: Path) -> Optional[str]:
        """Upload the given file to Azure Blob Storage and return the blob URL with SAS token."""
        blob_client = self._get_blob_service_client()
        if not blob_client:
            return None

        container_name = os.getenv("AZURE_BLOB_CONTAINER", "a2a-files")
        blob_size_threshold = int(os.getenv("AZURE_BLOB_SIZE_THRESHOLD", "8048576"))
        force_blob = os.getenv("FORCE_AZURE_BLOB", "false").lower() == "true"

        try:
            file_size = file_path.stat().st_size
            if not force_blob and file_size < blob_size_threshold:
                logger.info(
                    "File %s below blob size threshold (%s); skipping upload",
                    file_path,
                    blob_size_threshold,
                )
                return None
        except FileNotFoundError:
            logger.error(f"File not found for blob upload: {file_path}")
            return None

        blob_name = f"video-generator/{uuid.uuid4().hex}/{file_path.name}"
        try:
            container_client = blob_client.get_container_client(container_name)
            if not container_client.exists():
                container_client.create_container()
            with open(file_path, "rb") as data:
                container_client.upload_blob(name=blob_name, data=data, overwrite=True)

            sas_duration_minutes = int(
                os.getenv("AZURE_BLOB_SAS_DURATION_MINUTES", str(24 * 60))
            )

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
                            expiry=dt_datetime.utcnow() + timedelta(minutes=sas_duration_minutes),
                            protocol="https",
                            version="2023-11-03",
                        )
                    except Exception as sas_error:
                        logger.error(f"Failed to generate SAS URL with shared key: {sas_error}")

            if sas_token is None and self._blob_service_client is not None:
                try:
                    delegation_key = self._blob_service_client.get_user_delegation_key(
                        key_start_time=dt_datetime.utcnow() - timedelta(minutes=5),
                        key_expiry_time=dt_datetime.utcnow() + timedelta(minutes=sas_duration_minutes),
                    )
                    sas_token = generate_blob_sas(
                        account_name=self._blob_service_client.account_name,
                        container_name=container_name,
                        blob_name=blob_name,
                        user_delegation_key=delegation_key,
                        permission=BlobSasPermissions(read=True),
                        expiry=dt_datetime.utcnow() + timedelta(minutes=sas_duration_minutes),
                        protocol="https",
                        version="2023-11-03",
                    )
                except Exception as delegation_error:
                    logger.warning(f"Failed to generate SAS URL with user delegation key: {delegation_error}")

            blob_url = f"https://{service_client.account_name}.blob.core.windows.net/{container_name}/{blob_name}"
            if sas_token:
                blob_url = f"{blob_url}?{sas_token}"

            logger.info(f"✅ Uploaded video to blob: {blob_url[:100]}...")
            return blob_url

        except Exception as e:
            logger.error(f"Blob upload failed: {e}")
            return None

    def pop_latest_artifacts(self) -> List[Dict[str, Any]]:
        """Pop and return the latest artifacts (for A2A integration)."""
        artifacts = self._latest_artifacts.copy()
        self._latest_artifacts.clear()
        return artifacts
    
    async def _setup_file_search(self, files_directory: str = "documents") -> Optional[FileSearchTool]:
        """Upload files from local directory and create vector store for file search - ONCE per class."""
        async with FoundryTemplateAgent._file_search_setup_lock:
            # If we already have a shared file search tool, return it
            if FoundryTemplateAgent._shared_file_search_tool is not None:
                logger.info("Reusing existing shared file search tool")
                return FoundryTemplateAgent._shared_file_search_tool
            
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
                        FoundryTemplateAgent._shared_uploaded_files.append(file.id)
                        logger.info(f"Uploaded file: {os.path.basename(file_path)} (ID: {file.id})")
                    except Exception as e:
                        logger.warning(f"Failed to upload {file_path}: {e}")
                
                if not file_ids:
                    logger.warning("No files were successfully uploaded")
                    return None
                
                # Create vector store ONCE using project client
                logger.info("Creating shared vector store with uploaded files...")
                FoundryTemplateAgent._shared_vector_store = project_client.agents.vector_stores.create_and_poll(
                    file_ids=file_ids, 
                    name="agent_template_vectorstore"
                )
                logger.info(f"Created shared vector store: {FoundryTemplateAgent._shared_vector_store.id}")
                
                # Create file search tool ONCE
                file_search = FileSearchTool(vector_store_ids=[FoundryTemplateAgent._shared_vector_store.id])
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
                FoundryTemplateAgent._shared_file_search_tool = file_search
                logger.info("Cached shared file search tool for future use")
                    
                return file_search
                    
            except Exception as e:
                logger.error(f"Error setting up file search: {e}")
                return None
        
    async def create_agent(self) -> Agent:
        """Create the AI Foundry agent with web search and document search capabilities."""
        if self.agent:
            logger.info("Agent already exists, returning existing instance")
            return self.agent
        
        # Start with empty tools list - we'll add web search and file search capabilities
        tools = []
        tool_resources = None
        
        project_client = self._get_project_client()
        
        # Add video generation function tool definition
        generate_video_tool = {
            "type": "function",
            "function": {
                "name": "generate_video",
                "description": """Generate AI videos using Azure OpenAI's Sora 2 model from text prompts.
                
Creates high-quality video content with cinematic quality, natural motion, and optional audio.

Key capabilities:
- Text-to-video generation from detailed prompts
- Supports landscape (1280x720) and portrait (720x1280) resolutions
- Video durations: 4, 8, or 12 seconds
- Includes audio generation in output videos

For best results, include in prompts:
- Shot type (close-up, wide shot, tracking, aerial)
- Subject details and actions
- Setting and atmosphere
- Lighting description
- Camera motion

IMPORTANT: Video generation can take 60-120 seconds. Be patient.""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "Detailed text description of the desired video. Include shot type, subject, actions, setting, lighting, and atmosphere for best results."
                        },
                        "size": {
                            "type": "string",
                            "enum": ["1280x720", "720x1280"],
                            "description": "Video resolution. 1280x720 for landscape (default), 720x1280 for portrait."
                        },
                        "duration": {
                            "type": "integer",
                            "enum": [4, 8, 12],
                            "description": "Video duration in seconds. Options: 4, 8, or 12 seconds. Default is 8."
                        }
                    },
                    "required": ["prompt"],
                    "additionalProperties": False
                }
            }
        }
        tools.append(generate_video_tool)
        
        # Add remix_video tool for modifying existing videos
        remix_video_tool = {
            "type": "function",
            "function": {
                "name": "remix_video",
                "description": """Remix an existing video by applying a new text prompt to modify its appearance.
                
Use this to transform previously generated videos by changing:
- Color palette and grading
- Lighting and atmosphere
- Visual style and effects
- Mood and tone
- Scene modifications while preserving the core content

The remix preserves the original video's structure, duration, and motion while applying the requested changes.

Examples of remix prompts:
- "Shift the color palette to teal, sand, and rust with warm backlight"
- "Convert to black and white noir style with high contrast"
- "Add golden hour lighting with warm sunset tones"
- "Apply a dreamy soft-focus effect with pastel colors"

IMPORTANT: You need the video_id from a previously generated video.""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "video_id": {
                            "type": "string",
                            "description": "The ID of the previously generated video to remix. This is returned from generate_video calls."
                        },
                        "prompt": {
                            "type": "string",
                            "description": "Text description of the modifications to apply. Focus on visual style, color palette, lighting, or atmospheric changes."
                        }
                    },
                    "required": ["video_id", "prompt"],
                    "additionalProperties": False
                }
            }
        }
        tools.append(remix_video_tool)
        
        # Add Bing search tool if available
        try:
            bing_connection = project_client.connections.get(name="aiagentworkshopbinggrounding")
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
                logger.info("Added file search tool resources for uploaded documents")
                
            logger.info("Added file search capability")
        
        # Use context manager and create agent with all tools
        with project_client:
            if tool_resources:
                self.agent = project_client.agents.create_agent(
                    model="gpt-4o",
                    name="sora-2-video-generator",
                    instructions=self._get_agent_instructions(),
                    tools=tools,
                    tool_resources=tool_resources
                )
            else:
                self.agent = project_client.agents.create_agent(
                    model="gpt-4o",
                    name="sora-2-video-generator",
                    instructions=self._get_agent_instructions(),
                    tools=tools
                )
        
        logger.info(f"Created AI Foundry agent: {self.agent.id}")
        return self.agent
    
    def _get_sora_auth(self) -> Tuple[str, str]:
        """
        Get the Sora 2 API base URL and authentication token.
        Uses the Azure Cognitive Services endpoint with Entra ID authentication.
        
        Returns:
            Tuple of (base_url, auth_token)
        """
        # Sora uses Azure Cognitive Services endpoint format (*.cognitiveservices.azure.com)
        # Set AZURE_OPENAI_ENDPOINT to your Sora endpoint
        # e.g., https://simon-miaxownu-eastus2.cognitiveservices.azure.com
        sora_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        
        if not sora_endpoint:
            raise ValueError(
                "AZURE_OPENAI_ENDPOINT environment variable is required for Sora video generation.\n"
                "Set it to your Azure Cognitive Services endpoint, e.g.:\n"
                "AZURE_OPENAI_ENDPOINT=https://your-resource.cognitiveservices.azure.com"
            )
        
        # Ensure endpoint ends without trailing slash
        if sora_endpoint.endswith('/'):
            sora_endpoint = sora_endpoint.rstrip('/')
        
        # Create token provider for Azure Cognitive Services authentication
        logger.info(f"Creating token provider for Sora with endpoint: {sora_endpoint}")
        token_provider = get_bearer_token_provider(
            self.credential, 
            "https://cognitiveservices.azure.com/.default"
        )
        
        # Get the token and log (partial) for debugging
        token = token_provider()
        logger.info(f"Token obtained, length: {len(token)}, starts with: {token[:20]}...")
        
        # Base URL for Sora API (api-version added in _sora_api_request)
        base_url = f"{sora_endpoint}/openai/v1"
        
        return base_url, token
    
    def _resize_image_for_video(self, image_path: str, target_size: str) -> bytes:
        """
        Resize an image to match the target video dimensions.
        Sora 2 requires the reference image to exactly match the output video size.
        
        Args:
            image_path: Path to the source image
            target_size: Target size string (e.g., "1280x720" or "720x1280")
            
        Returns:
            Resized image as bytes (PNG format)
        """
        # Parse target dimensions
        width, height = map(int, target_size.split("x"))
        
        # Open and resize the image
        with Image.open(image_path) as img:
            # Convert to RGB if necessary (handles RGBA, etc.)
            if img.mode in ('RGBA', 'LA', 'P'):
                # Create white background for transparency
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Resize to exact dimensions (may distort aspect ratio)
            # Use LANCZOS for high-quality downsampling
            resized = img.resize((width, height), Image.LANCZOS)
            
            # Save to bytes as PNG
            buffer = io.BytesIO()
            resized.save(buffer, format='PNG')
            buffer.seek(0)
            
            logger.info(f"Resized image from {img.size} to ({width}, {height})")
            return buffer.getvalue()
    
    async def _sora_api_request(
        self, 
        method: str, 
        path: str, 
        json_data: Optional[Dict] = None,
        files: Optional[Dict] = None,
        timeout: float = 120.0
    ) -> Dict[str, Any]:
        """
        Make a request to the Sora API.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (e.g., "/video/generations/jobs")
            json_data: JSON body for POST requests
            files: Files for multipart form upload
            timeout: Request timeout in seconds
            
        Returns:
            Parsed JSON response
        """
        base_url, token = self._get_sora_auth()
        
        # Construct full URL with api-version query parameter
        separator = "&" if "?" in path else "?"
        url = f"{base_url}{path}{separator}api-version=preview"
        
        headers = {
            "Authorization": f"Bearer {token}",
        }
        
        logger.info(f"Making {method} request to: {url}")
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            if files:
                # Multipart form upload
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    files=files,
                    data=json_data
                )
            else:
                # JSON request
                if json_data:
                    headers["Content-Type"] = "application/json"
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_data
                )
            
            logger.info(f"Response status: {response.status_code}")
            
            if response.status_code >= 400:
                logger.error(f"API error: {response.status_code} - {response.text}")
                response.raise_for_status()
            
            return response.json()
    
    async def _download_video_content(self, generation_id: str) -> bytes:
        """
        Download video content from Sora API using raw HTTP request.
        
        Args:
            generation_id: The generation ID (e.g., gen_xxx)
            
        Returns:
            Video content as bytes
        """
        sora_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        if not sora_endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT environment variable is required")
        
        if sora_endpoint.endswith('/'):
            sora_endpoint = sora_endpoint.rstrip('/')
        
        # Create token provider for authentication
        token_provider = get_bearer_token_provider(
            self.credential, 
            "https://cognitiveservices.azure.com/.default"
        )
        token = token_provider()
        
        # Correct Azure Sora download URL format from documentation:
        # /openai/v1/video/generations/{generation_id}/content/video?api-version=preview
        url = f"{sora_endpoint}/openai/v1/video/generations/{generation_id}/content/video?api-version=preview"
        
        headers = {
            "Authorization": f"Bearer {token}",
        }
        
        logger.info(f"Downloading from: {url}")
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code >= 400:
                logger.error(f"Download error: {response.status_code} - {response.text}")
                response.raise_for_status()
            
            logger.info(f"✅ Downloaded {len(response.content)} bytes")
            return response.content

    async def _download_from_url(self, url: str) -> bytes:
        """
        Download video content from a direct URL.
        
        Args:
            url: Direct download URL for the video
            
        Returns:
            Video content as bytes
        """
        logger.info(f"Downloading video from URL: {url}")
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.get(url)
            
            if response.status_code >= 400:
                logger.error(f"Download error: {response.status_code} - {response.text}")
                response.raise_for_status()
            
            return response.content

    async def generate_video(
        self,
        prompt: str,
        size: str = "1280x720",
        seconds: int = 4,
        output_dir: str = "generated_videos",
        input_reference_path: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Generate a video using Sora 2 model.
        
        Args:
            prompt: Natural-language description of the video to generate.
                   Include shot type, subject, action, setting, lighting, 
                   and any desired camera motion for best results.
            size: Output resolution - "720x1280" (portrait) or "1280x720" (landscape).
                  Default: "1280x720"
            seconds: Video duration - 4, 8, or 12 seconds. Default: 4
            output_dir: Directory to save the generated video. Default: "generated_videos"
            input_reference_path: Optional path to a reference image (must match size exactly).
                                 Supported formats: JPEG, PNG, WEBP.
        
        Returns:
            Tuple of (video_file_path, status_message)
        """
        logger.info(f"Starting Sora 2 video generation with prompt: {prompt[:100]}...")
        
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        try:
            # Get Sora endpoint and token
            base_url, token = self._get_sora_auth()
            
            # Create OpenAI client with token
            from openai import OpenAI
            client = OpenAI(
                base_url=base_url,
                api_key=token,
            )
            
            # Prepare parameters for video creation
            create_params = {
                "model": "sora-2",  # Use sora-2 as per documentation
                "prompt": prompt,
                "size": size,
                "seconds": str(seconds),  # Azure API expects string, not integer
            }
            
            # Check if we have a reference image
            if input_reference_path and os.path.exists(input_reference_path):
                logger.info(f"Using reference image: {input_reference_path}")
                # Resize image to match video dimensions (Sora 2 requirement)
                resized_image_data = self._resize_image_for_video(input_reference_path, size)
                create_params["input_reference"] = resized_image_data
            
            # Create the video using OpenAI SDK
            logger.info(f"Submitting video generation request via SDK...")
            logger.info(f"Parameters: model={create_params['model']}, size={size}, seconds={create_params['seconds']}")
            video = client.videos.create(**create_params)
            
            video_id = video.id
            video_status = video.status
            
            logger.info(f"Video creation started. ID: {video_id}")
            logger.info(f"Initial status: {video_status}")
            
            # Poll for completion using SDK
            poll_count = 0
            max_polls = 90  # Maximum 30 minutes (90 * 20 seconds)
            
            while video_status not in ["completed", "succeeded", "failed", "cancelled"]:
                poll_count += 1
                logger.info(f"Status: {video_status}. Waiting 20 seconds... (Poll {poll_count}/{max_polls})")
                
                if poll_count >= max_polls:
                    return "", f"Video generation timed out after {max_polls * 20} seconds"
                
                await asyncio.sleep(20)
                
                # Retrieve the latest status using SDK
                video = client.videos.retrieve(video_id)
                video_status = video.status
            
            # Check final status
            if video_status in ["completed", "succeeded"]:
                logger.info("="*60)
                logger.info("🎉 VIDEO GENERATION COMPLETED!")
                logger.info(f"📹 VIDEO ID: {video_id}")
                logger.info(f"📄 Video object: {video}")
                logger.info("="*60)
                
                # Generate filename with video_id for easy reference
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                # Extract short video id (last 8 chars) for filename - handle both video_ and task_ prefixes
                short_vid = video_id.replace('video_', '').replace('task_', '')[-8:] if video_id else str(uuid.uuid4())[:8]
                output_filename = f"sora_{timestamp}_{short_vid}.mp4"
                output_path = os.path.join(output_dir, output_filename)
                saved_path = Path(output_path)
                
                # Download using OpenAI SDK's download_content method
                logger.info(f"Downloading video to: {output_path}")
                video_content = client.videos.download_content(video_id, variant="video")
                video_content.write_to_file(str(saved_path))
                
                logger.info(f"✅ Video saved successfully: {output_path}")
                logger.info(f"💡 To remix this video, use Video ID: {video_id}")
                
                # Upload to blob storage and create artifact for A2A
                blob_url = self._upload_to_blob(saved_path)
                response_text = f"✅ Video generated successfully!\n\n**Video ID (for remix):** `{video_id}`\n**Duration:** {seconds} seconds\n**Resolution:** {size}"
                
                if blob_url:
                    file_size = saved_path.stat().st_size if saved_path.exists() else 0
                    artifact_record: Dict[str, Any] = {
                        "artifact-uri": blob_url,
                        "file-name": saved_path.name,
                        "mime": "video/mp4",
                        "storage-type": "azure_blob",
                        "status": "stored",
                        "provider": "sora",
                        "model": "sora-2",
                        "video_id": video_id,  # This is the ID to use for remix
                        "local-path": str(saved_path),
                        "file-size": file_size,
                    }
                    self._latest_artifacts.append(artifact_record)
                    logger.info(f"🎬 Created video artifact: {saved_path.name}, blob_url={blob_url[:80]}...")
                    response_text += f"\n**Video URL:** [View Video]({blob_url})"
                else:
                    response_text += f"\n**Saved to:** {str(output_path)}"
                
                response_text += "\n\n💡 *Copy the Video ID above to use with the Remix feature!*"
                return str(output_path), response_text
            
            elif video_status == "failed":
                error_info = getattr(video, 'error', 'Unknown error')
                logger.error(f"Video generation failed: {error_info}")
                return "", f"❌ Video generation failed: {error_info}"
            
            else:
                logger.warning(f"Video generation ended with status: {video_status}")
                return "", f"⚠️ Video generation ended with status: {video_status}"
                
        except Exception as e:
            logger.error(f"Error generating video: {e}")
            import traceback
            traceback.print_exc()
            return "", f"❌ Error generating video: {str(e)}"

    async def remix_video(
        self,
        video_id: str,
        prompt: str,
        output_dir: str = "generated_videos"
    ):
        """
        Remix an existing video with a new text prompt.
        
        Args:
            video_id: The ID of the previously generated video (format: video_xxx)
            prompt: Text description of modifications to apply (color, style, lighting, etc.)
            output_dir: Directory to save the remixed video
            
        Returns:
            Tuple of (output_path, response_text)
        """
        try:
            logger.info(f"🎨 Starting video remix with ID: {video_id}")
            logger.info(f"📝 Remix prompt: {prompt}")
            
            # Ensure output directory exists
            os.makedirs(output_dir, exist_ok=True)
            
            # Get Sora endpoint and token
            base_url, token = await self._get_sora_credentials()
            
            # Create OpenAI client with token
            from openai import OpenAI
            client = OpenAI(
                base_url=base_url,
                api_key=token,
            )
            
            # Call remix API
            logger.info("Calling Sora remix API...")
            video = client.videos.remix(
                video_id=video_id,
                prompt=prompt
            )
            
            logger.info(f"Remix initiated: {video}")
            
            # Extract the new video ID from the response
            if hasattr(video, 'id'):
                new_video_id = video.id
            elif isinstance(video, dict):
                new_video_id = video.get('id')
            else:
                new_video_id = str(video)
            
            logger.info(f"New remixed video ID: {new_video_id}")
            
            # Poll for completion (remix uses same polling as generation)
            max_wait = 180  # 3 minutes max
            poll_interval = 5
            elapsed = 0
            
            while elapsed < max_wait:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                
                # Check status using the new video ID
                video_response = await self._sora_api_request(
                    method="GET",
                    endpoint=f"/video/generations/{new_video_id}"
                )
                
                video_status = video_response.get("status", "unknown")
                logger.info(f"⏳ Remix status ({elapsed}s): {video_status}")
                
                if video_status == "succeeded":
                    logger.info("✅ Video remix completed successfully!")
                    
                    # Save the remixed video
                    timestamp = int(time.time())
                    short_vid = new_video_id.replace('video_', '')[-8:] if new_video_id else str(uuid.uuid4())[:8]
                    output_filename = f"sora_remix_{timestamp}_{short_vid}.mp4"
                    output_path = os.path.join(output_dir, output_filename)
                    
                    # Get generation ID for download
                    generations = video_response.get("generations", [])
                    if not generations:
                        raise ValueError("No generations found in remix response")
                    
                    generation_id = generations[0].get("id")
                    logger.info(f"📥 Remixed Video ID: {new_video_id}, Generation ID: {generation_id}")
                    
                    # Download the remixed video
                    logger.info(f"Downloading remixed video to: {output_path}")
                    video_content = await self._download_video_content(generation_id)
                    saved_path = Path(output_path)
                    with open(saved_path, "wb") as f:
                        f.write(video_content)
                    
                    logger.info(f"✅ Remixed video saved: {output_path}")
                    
                    # Upload to blob storage
                    blob_url = self._upload_to_blob(saved_path)
                    response_text = f"✅ Video remixed successfully!\n\n**Original Video ID:** `{video_id}`\n**New Video ID:** `{new_video_id}`\n**Remix Prompt:** {prompt}"
                    
                    if blob_url:
                        artifact_record: Dict[str, Any] = {
                            "artifact-uri": blob_url,
                            "file-name": saved_path.name,
                            "mime": "video/mp4",
                            "storage-type": "azure_blob",
                            "status": "stored",
                            "provider": "sora",
                            "model": "sora-remix",
                            "video_id": new_video_id,
                            "generation_id": generation_id,
                            "original_video_id": video_id,
                            "local-path": str(saved_path),
                            "file-size": len(video_content),
                        }
                        self._latest_artifacts.append(artifact_record)
                        logger.info(f"🎬 Created remix artifact: {saved_path.name}")
                        response_text += f"\n**Video URL:** [View Remixed Video]({blob_url})"
                    else:
                        response_text += f"\n**Saved to:** {output_path}"
                    
                    response_text += "\n\n💡 *You can remix this video again with a different prompt!*"
                    return output_path, response_text
                
                elif video_status == "failed":
                    error_msg = video_response.get('error', 'Unknown error')
                    logger.error(f"Video remix failed: {error_msg}")
                    return "", f"❌ Video remix failed: {error_msg}"
            
            # Timeout
            logger.warning(f"Video remix timed out after {max_wait}s")
            return "", f"⏱️ Video remix timed out. The video may still be processing. Video ID: {new_video_id}"
            
        except Exception as e:
            logger.error(f"Error remixing video: {e}")
            return "", f"❌ Error remixing video: {str(e)}"

    async def generate_video_stream(
        self,
        prompt: str,
        size: str = "1280x720",
        seconds: int = 4,
        output_dir: str = "generated_videos",
        input_reference_path: Optional[str] = None
    ):
        """
        Generate a video using Sora 2 model with streaming status updates.
        
        Yields status messages during generation, then yields the final result.
        
        Args:
            prompt: Natural-language description of the video to generate.
            size: Output resolution - "720x1280" (portrait) or "1280x720" (landscape).
            seconds: Video duration - 4, 8, or 12 seconds.
            output_dir: Directory to save the generated video.
            input_reference_path: Optional path to a reference image.
        
        Yields:
            Status messages and final result with video path
        """
        logger.info(f"Starting Sora 2 video generation (streaming) with prompt: {prompt[:100]}...")
        
        yield f"🎬 **Starting video generation...**\n\n**Prompt:** {prompt}\n**Size:** {size}\n**Duration:** {seconds} seconds"
        
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        try:
            # Check if we have a reference image - requires multipart form upload
            if input_reference_path and os.path.exists(input_reference_path):
                yield f"📷 Using reference image: {input_reference_path}"
                
                # Resize image to match video dimensions (Sora 2 requirement)
                yield f"🔄 Resizing image to match video dimensions ({size})..."
                resized_image_data = self._resize_image_for_video(input_reference_path, size)
                
                # Parse size string to width and height
                width, height = map(int, size.split("x"))
                
                # For image-to-video, use multipart form upload with resized image
                files = {
                    "input_reference": ("reference_image.png", resized_image_data, "image/png")
                }
                form_data = {
                    "model": "sora",
                    "prompt": prompt,
                    "width": str(width),
                    "height": str(height),
                    "n_seconds": str(seconds),
                }
                
                # Create the video generation job with multipart form
                yield "📤 Submitting video generation request to Sora (with reference image)..."
                video_response = await self._sora_api_request("POST", "/video/generations/jobs", json_data=form_data, files=files)
            else:
                # Parse size string to width and height
                width, height = map(int, size.split("x"))
                
                # Text-to-video: use JSON body
                create_body = {
                    "model": "sora",
                    "prompt": prompt,
                    "width": width,
                    "height": height,
                    "n_seconds": seconds,
                }
                
                # Create the video generation job
                yield "📤 Submitting video generation request to Sora..."
                video_response = await self._sora_api_request("POST", "/video/generations/jobs", json_data=create_body)
            
            video_id = video_response.get("id")
            video_status = video_response.get("status")
            
            yield f"✅ Video job created!\n**Video ID:** {video_id}\n**Initial Status:** {video_status}"
            
            # Poll for completion
            poll_count = 0
            max_polls = 90  # Maximum 30 minutes
            
            while video_status not in ["completed", "succeeded", "failed", "cancelled"]:
                poll_count += 1
                
                # Yield progress update every few polls
                if poll_count % 3 == 0:  # Every minute
                    elapsed = poll_count * 20
                    yield f"⏳ **Status:** {video_status} | **Elapsed:** {elapsed} seconds | Checking again in 20s..."
                
                if poll_count >= max_polls:
                    yield f"⚠️ Video generation timed out after {max_polls * 20} seconds"
                    return
                
                await asyncio.sleep(20)
                video_response = await self._sora_api_request("GET", f"/video/generations/jobs/{video_id}")
                video_status = video_response.get("status")
            
            # Check final status
            if video_status in ["completed", "succeeded"]:
                logger.info("="*60)
                logger.info("🎉 VIDEO GENERATION COMPLETED!")
                logger.info(f"📹 VIDEO ID: {video_id}")
                logger.info("="*60)
                
                yield "🎉 **Video generation completed!** Downloading..."
                
                # Get generation ID for download
                generations = video_response.get("generations", [])
                if not generations:
                    yield "❌ No generations found in response"
                    return
                generation_id = generations[0].get("id")
                logger.info(f"📥 Task ID: {video_id}, Generation ID: {generation_id}")
                
                # Generate filename with video_id for easy reference
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                # Extract short video id (last 8 chars) for filename
                short_vid = video_id.replace('video_', '')[-8:] if video_id else str(uuid.uuid4())[:8]
                output_filename = f"sora_{timestamp}_{short_vid}.mp4"
                output_path = os.path.join(output_dir, output_filename)
                
                # Download the video using generation_id
                video_content = await self._download_video_content(generation_id)
                saved_path = Path(output_path)
                with open(saved_path, "wb") as f:
                    f.write(video_content)
                
                logger.info(f"✅ Video saved successfully: {output_path}")
                logger.info(f"💡 To remix this video, use Video ID: {video_id}")
                
                # Upload to blob storage and create artifact for A2A
                blob_url = self._upload_to_blob(saved_path)
                response_text = f"✅ **Video saved successfully!**\n\n**Video ID (for remix):** `{video_id}`\n**Duration:** {seconds} seconds\n**Resolution:** {size}"
                
                if blob_url:
                    artifact_record: Dict[str, Any] = {
                        "artifact-uri": blob_url,
                        "file-name": saved_path.name,
                        "mime": "video/mp4",
                        "storage-type": "azure_blob",
                        "status": "stored",
                        "provider": "sora",
                        "model": "sora",
                        "video_id": video_id,
                        "generation_id": generation_id,
                        "local-path": str(saved_path),
                        "file-size": len(video_content),
                    }
                    self._latest_artifacts.append(artifact_record)
                    logger.info(f"🎬 Created video artifact: {saved_path.name}, blob_url={blob_url[:80]}...")
                    response_text += f"\n**Video URL:** [View Video]({blob_url})"
                else:
                    response_text += f"\n**File:** {output_path}"
                
                response_text += "\n\n💡 *Copy the Video ID above to use with the Remix feature!*"
                yield response_text
            
            elif video_status == "failed":
                error_msg = video_response.get('error', 'Unknown error')
                yield f"❌ **Video generation failed:** {error_msg}"
            
            else:
                yield f"⚠️ Video generation ended with status: {video_status}"
                
        except Exception as e:
            logger.error(f"Error generating video: {e}")
            yield f"❌ **Error generating video:** {str(e)}"

    async def remix_video(
        self,
        video_id: str,
        prompt: str,
        output_dir: str = "generated_videos"
    ) -> Tuple[str, str]:
        """
        Remix an existing video by making targeted adjustments while preserving core elements.
        
        The remix feature modifies specific aspects of an existing video while preserving
        its framework, scene transitions, and visual layout. For best results, limit 
        modifications to one clearly articulated adjustment.
        
        Args:
            video_id: ID of a previously completed video (e.g., "video_...")
            prompt: Description of the changes to make (e.g., "Shift the color palette to teal")
            output_dir: Directory to save the remixed video. Default: "generated_videos"
        
        Returns:
            Tuple of (video_file_path, status_message)
        """
        logger.info(f"Starting video remix for {video_id} with prompt: {prompt[:100]}...")
        
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        try:
            # Azure returns task_XXX format but OpenAI SDK expects video_XXX format
            # Check if we need to convert the format
            original_video_id = video_id
            if video_id.startswith("task_"):
                # Try with video_ prefix for OpenAI SDK compatibility
                sdk_video_id = video_id.replace("task_", "video_", 1)
                logger.info(f"Converting Azure task ID format: {video_id} -> {sdk_video_id} for SDK")
            else:
                sdk_video_id = video_id
            
            # Get Sora endpoint and token
            base_url, token = self._get_sora_auth()
            
            # Create OpenAI client with token
            from openai import OpenAI
            client = OpenAI(
                base_url=base_url,
                api_key=token,
            )
            
            # Use the OpenAI SDK's remix method (Sora 2 API)
            logger.info("Calling Sora 2 remix API via OpenAI SDK...")
            logger.info(f"Original Video ID: {original_video_id}")
            logger.info(f"SDK Video ID: {sdk_video_id}")
            logger.info(f"Remix prompt: {prompt}")
            
            try:
                video_response = client.videos.remix(
                    video_id=sdk_video_id,
                    prompt=prompt
                )
            except Exception as e:
                # If SDK format fails, try with original Azure task_ format via direct API
                logger.warning(f"SDK remix failed: {e}")
                logger.info(f"Retrying with direct API call using original task ID: {original_video_id}")
                
                remix_body = {"prompt": prompt}
                video_response = await self._sora_api_request(
                    "POST", 
                    f"/video/generations/jobs/{original_video_id}/remix", 
                    json_data=remix_body
                )
                # Convert dict response to object-like format for compatibility
                class VideoResponse:
                    def __init__(self, data):
                        self.id = data.get("id")
                        self.status = data.get("status")
                        self._data = data
                
                video_response = VideoResponse(video_response)
            
            # Extract video ID and status from OpenAI SDK response object
            new_video_id = video_response.id if hasattr(video_response, 'id') else video_response.get("id")
            video_status = video_response.status if hasattr(video_response, 'status') else video_response.get("status")
            
            logger.info(f"Remix job created. ID: {new_video_id}")
            logger.info(f"Initial status: {video_status}")
            
            # Determine if we should use SDK or direct API for polling
            use_sdk = not new_video_id.startswith("task_")
            
            # Poll for completion
            poll_count = 0
            max_polls = 90
            
            while video_status not in ["completed", "succeeded", "failed", "cancelled"]:
                poll_count += 1
                logger.info(f"Status: {video_status}. Waiting 20 seconds... (Poll {poll_count}/{max_polls})")
                
                if poll_count >= max_polls:
                    return "", f"Video remix timed out after {max_polls * 20} seconds"
                
                await asyncio.sleep(20)
                
                # Use SDK or direct API based on video ID format
                if use_sdk:
                    try:
                        video_response = client.videos.retrieve(new_video_id)
                        video_status = video_response.status if hasattr(video_response, 'status') else video_response.get("status")
                    except Exception as e:
                        logger.warning(f"SDK retrieve failed, falling back to direct API: {e}")
                        use_sdk = False
                
                if not use_sdk:
                    # Use direct API call for Azure task_ format
                    response_dict = await self._sora_api_request("GET", f"/video/generations/jobs/{new_video_id}")
                    video_status = response_dict.get("status")
                    # Update video_response for later use
                    video_response._data = response_dict if hasattr(video_response, '_data') else response_dict
                
                # Log full response when status changes from in_progress
                if video_status in ["completed", "succeeded", "failed", "cancelled"]:
                    logger.info(f"Final response: {video_response}")
            
            if video_status in ["completed", "succeeded"]:
                logger.info("="*60)
                logger.info("🎉 VIDEO REMIX COMPLETED!")
                logger.info(f"📹 ORIGINAL VIDEO ID: {original_video_id}")
                logger.info(f"📹 NEW REMIX VIDEO ID: {new_video_id}")
                logger.info("="*60)
                
                # Download the video
                logger.info(f"Downloading remixed video...")
                
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                # Extract short video id (last 8 chars) for filename
                short_vid = new_video_id.replace('video_', '').replace('task_', '')[-8:] if new_video_id else str(uuid.uuid4())[:8]
                output_filename = f"sora_remix_{timestamp}_{short_vid}.mp4"
                output_path = os.path.join(output_dir, output_filename)
                saved_path = Path(output_path)
                
                # Try SDK download first, fall back to direct API if needed
                try:
                    if use_sdk:
                        video_content = client.videos.download_content(new_video_id, variant="video")
                        video_content.write_to_file(str(saved_path))
                    else:
                        raise Exception("Using direct API download for task_ format")
                except Exception as e:
                    logger.info(f"SDK download not available, using direct API: {e}")
                    # For Azure task_ format, get generation_id and download directly
                    response_data = video_response._data if hasattr(video_response, '_data') else {}
                    generations = response_data.get("generations", [])
                    if not generations:
                        return "", "❌ No generations found in remix response"
                    generation_id = generations[0].get("id")
                    logger.info(f"Downloading using generation_id: {generation_id}")
                    video_content_bytes = await self._download_video_content(generation_id)
                    with open(saved_path, "wb") as f:
                        f.write(video_content_bytes)
                
                logger.info(f"✅ Remixed video saved: {output_path}")
                logger.info(f"💡 To remix again, use Video ID: {new_video_id}")
                
                # Upload to blob storage and create artifact for A2A
                blob_url = self._upload_to_blob(saved_path)
                response_text = f"✅ Video remixed successfully!\n\n**Original Video ID:** `{video_id}`\n**New Remix Video ID (for further remix):** `{new_video_id}`"
                
                if blob_url:
                    # Get file size for artifact
                    file_size = saved_path.stat().st_size if saved_path.exists() else 0
                    
                    artifact_record: Dict[str, Any] = {
                        "artifact-uri": blob_url,
                        "file-name": saved_path.name,
                        "mime": "video/mp4",
                        "storage-type": "azure_blob",
                        "status": "stored",
                        "provider": "sora",
                        "model": "sora",
                        "video_id": new_video_id,
                        "original_video_id": video_id,  # Store original video ID for tracking
                        "local-path": str(saved_path),
                        "file-size": file_size,
                    }
                    self._latest_artifacts.append(artifact_record)
                    logger.info(f"🎬 Created remix artifact: {saved_path.name}, blob_url={blob_url[:80]}...")
                    response_text += f"\n**Video URL:** [View Video]({blob_url})"
                else:
                    response_text += f"\n**Saved to:** {output_path}"
                
                response_text += "\n\n💡 *You can use the New Remix Video ID to create another remix!*"
                return str(output_path), response_text
            
            elif video_status == "failed":
                error_obj = video_response.get('error', {})
                if isinstance(error_obj, dict):
                    error_code = error_obj.get('code', 'unknown')
                    error_message = error_obj.get('message', 'Unknown error')
                    logger.error(f"Video remix failed - Code: {error_code}, Message: {error_message}")
                    logger.error(f"Full error object: {error_obj}")
                    return "", f"❌ Video remix failed: **{error_code}**\n\n{error_message}\n\n*This is an internal Sora 2 error. The prompt may be too complex or conflict with content policies. Try simplifying your remix request.*"
                else:
                    logger.error(f"Video remix failed with error: {error_obj}")
                    return "", f"❌ Video remix failed: {error_obj}"
            
            else:
                return "", f"⚠️ Video remix ended with status: {video_status}"
                
        except Exception as e:
            logger.error(f"Error remixing video: {e}")
            return "", f"❌ Error remixing video: {str(e)}"

    async def video_to_video(
        self,
        prompt: str,
        input_video_path: str,
        size: str = "1280x720",
        seconds: int = 4,
        output_dir: str = "generated_videos"
    ) -> Tuple[str, str]:
        """
        Generate a new video using an existing video as a reference.
        
        Args:
            prompt: Description of the desired output within the context of the reference video
            input_video_path: Path to the reference video file (MP4)
            size: Output resolution - "720x1280" (portrait) or "1280x720" (landscape)
            seconds: Video duration - 4, 8, or 12 seconds
            output_dir: Directory to save the generated video
        
        Returns:
            Tuple of (video_file_path, status_message)
        """
        logger.info(f"Starting video-to-video generation with prompt: {prompt[:100]}...")
        
        if not os.path.exists(input_video_path):
            return "", f"❌ Input video not found: {input_video_path}"
        
        os.makedirs(output_dir, exist_ok=True)
        
        try:
            # Read video file
            with open(input_video_path, "rb") as video_file:
                video_data = video_file.read()
            
            # Parse size string to width and height
            width, height = map(int, size.split("x"))
            
            # For video-to-video, use multipart form upload
            files = {
                "input_reference": (os.path.basename(input_video_path), video_data, "video/mp4")
            }
            form_data = {
                "model": "sora",
                "prompt": prompt,
                "width": str(width),
                "height": str(height),
                "n_seconds": str(seconds),
            }
            
            logger.info("Submitting video-to-video request to Sora...")
            video_response = await self._sora_api_request("POST", "/video/generations/jobs", json_data=form_data, files=files)
            
            video_id = video_response.get("id")
            video_status = video_response.get("status")
            
            logger.info(f"Video creation started. ID: {video_id}")
            logger.info(f"Initial status: {video_status}")
            
            # Poll for completion
            poll_count = 0
            max_polls = 90
            
            while video_status not in ["completed", "succeeded", "failed", "cancelled"]:
                poll_count += 1
                logger.info(f"Status: {video_status}. Waiting 20 seconds... (Poll {poll_count}/{max_polls})")
                
                if poll_count >= max_polls:
                    return "", f"Video generation timed out after {max_polls * 20} seconds"
                
                await asyncio.sleep(20)
                video_response = await self._sora_api_request("GET", f"/video/generations/jobs/{video_id}")
                video_status = video_response.get("status")
            
            if video_status in ["completed", "succeeded"]:
                logger.info("Video-to-video completed!")
                
                # Get generation ID for download
                generations = video_response.get("generations", [])
                if not generations:
                    return "", "❌ No generations found in v2v response"
                generation_id = generations[0].get("id")
                logger.info(f"📥 Task ID: {video_id}, Generation ID: {generation_id}")
                
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                unique_id = str(uuid.uuid4())[:8]
                output_filename = f"sora_v2v_{timestamp}_{unique_id}.mp4"
                output_path = os.path.join(output_dir, output_filename)
                
                logger.info(f"Downloading video to: {output_path}")
                video_content = await self._download_video_content(generation_id)
                saved_path = Path(output_path)
                with open(saved_path, "wb") as f:
                    f.write(video_content)
                
                logger.info(f"Video saved: {output_path}")
                
                # Upload to blob storage and create artifact for A2A
                blob_url = self._upload_to_blob(saved_path)
                response_text = f"✅ Video-to-video completed!\n\n**Video ID:** {video_id}\n**Duration:** {seconds} seconds\n**Resolution:** {size}"
                
                if blob_url:
                    artifact_record: Dict[str, Any] = {
                        "artifact-uri": blob_url,
                        "file-name": saved_path.name,
                        "mime": "video/mp4",
                        "storage-type": "azure_blob",
                        "status": "stored",
                        "provider": "sora",
                        "model": "sora",
                        "video_id": video_id,
                        "generation_id": generation_id,
                        "local-path": str(saved_path),
                        "file-size": len(video_content),
                    }
                    self._latest_artifacts.append(artifact_record)
                    logger.info(f"🎬 Created v2v artifact: {saved_path.name}, blob_url={blob_url[:80]}...")
                    response_text += f"\n**Video URL:** [View Video]({blob_url})"
                else:
                    response_text += f"\n**Saved to:** {output_path}"
                
                return output_path, response_text
            
            elif video_status == "failed":
                error_msg = video_response.get('error', 'Unknown error')
                return "", f"❌ Video generation failed: {error_msg}"
            
            else:
                return "", f"⚠️ Video generation ended with status: {video_status}"
                
        except Exception as e:
            logger.error(f"Error in video-to-video: {e}")
            return "", f"❌ Error in video-to-video: {str(e)}"

    def _get_agent_instructions(self) -> str:
        """
        Define the Sora 2 Video Generator agent's personality and behavior.
        This is the system prompt that determines how the agent responds.
        """
        return f"""
You are a **Sora 2 Video Generation Specialist** powered by Azure AI Foundry.

You create stunning AI-generated videos using Azure OpenAI's Sora 2 model through the generate_video and remix_video functions.

## Core Responsibilities

1. **Video Generation** – When users request a video, IMMEDIATELY call the generate_video function with their prompt
2. **Video Remixing** – Modify existing videos by calling remix_video with a video_id and transformation prompt
3. **Prompt Enhancement** – Improve basic prompts with cinematographic details before generating
4. **Creative Consultation** – Suggest improvements to make videos more cinematic and engaging
5. **Technical Guidance** – Explain Sora 2 capabilities and best practices

## CRITICAL: When to Call generate_video

**ALWAYS call generate_video immediately when:**
- User asks to "generate a video"
- User describes a scene they want as a video
- User requests "create", "make", or "produce" a video
- User provides any video description

**DO NOT just provide prompt suggestions - GENERATE THE VIDEO!**

## CRITICAL: When to Call remix_video

**ALWAYS call remix_video when:**
- User asks to "remix", "modify", "change", or "transform" an existing video
- User wants to adjust colors, lighting, mood, or visual style of a previous video
- User references a video_id and requests changes
- User says things like "make it darker", "change the colors", "add effects" to an existing video

**After generating a video, ALWAYS provide the video_id to the user so they can remix it!**

## Sora 2 Capabilities

- **Text-to-Video**: Generate videos from text descriptions  
- **Video Remixing**: Transform existing videos with new prompts (color, lighting, style, mood)
- **Resolutions**: 1280x720 (landscape, default) or 720x1280 (portrait)
- **Durations**: 4, 8, or 12 seconds (default: 8)
- **Audio**: Includes audio generation in output videos

## Prompt Enhancement

Before calling generate_video, enhance basic prompts with:

1. **Shot Type**: Close-up, wide shot, medium shot, tracking shot, aerial view
2. **Subject Details**: Describe the main focus in detail
3. **Action/Movement**: Specific movements and what's happening
4. **Setting**: Location, indoor/outdoor, time of day
5. **Lighting**: Natural, dramatic, soft, golden hour, cinematic
6. **Atmosphere/Mood**: Cinematic, dreamy, energetic, peaceful, mysterious
7. **Camera Motion**: Pan, zoom, dolly, static, smooth tracking

## Remix Examples

**Good remix prompts:**
- "Shift the color palette to teal, sand, and rust with warm backlight"
- "Convert to black and white noir style with high contrast"
- "Add golden hour lighting with warm sunset tones"
- "Apply a dreamy soft-focus effect with pastel colors"
- "Make it darker and more moody with blue tones"

## Example Flow - Generation

**User:** "Generate a video of a dog running"

**You should:**
1. Enhance the prompt internally
2. Immediately call generate_video with: "A cinematic tracking shot of a golden retriever joyfully running through a sunlit meadow at sunset. The camera follows alongside the dog at eye level. Golden hour lighting creates warm tones and long shadows on the grass, which sways gently in the breeze. The mood is energetic and peaceful. Smooth camera motion captures the dog's playful energy."
3. After generation completes, provide the video_id and explain what you created

## Example Flow - Remix

**User:** "Make that video darker and add blue tones"

**You should:**
1. Use the video_id from the previous generation
2. Call remix_video with video_id and prompt: "Shift to a darker atmosphere with deep blue and teal color grading. Add moody, twilight lighting with cooler tones throughout."
3. After remix completes, provide the new video_id

## Function Call Parameters

**generate_video:**
- **prompt** (required): Detailed, enhanced description
- **size** (optional): "1280x720" (landscape, default) or "720x1280" (portrait)  
- **duration** (optional): 4, 8 (default), or 12 seconds

**remix_video:**
- **video_id** (required): ID from a previously generated video (format: video_xxx)
- **prompt** (required): Description of visual modifications (color, lighting, style, mood)

## Limitations

- Video generation takes 60-120 seconds
- Remix takes 60-120 seconds
- Complex physics may not render perfectly
- Spatial reasoning (left/right) can be challenging
- Very specific text or logos are difficult

Current date and time: {datetime.datetime.now().isoformat()}
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
            action_type = getattr(required_action, 'type', 'submit_tool_outputs')
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
                
                # Handle generate_video function call
                if function_name == "generate_video":
                    try:
                        args_dict = json.loads(arguments) if isinstance(arguments, str) else arguments
                        logger.info(f"Calling generate_video with args: {args_dict}")
                        
                        # Call the generate_video method (map duration to seconds parameter)
                        video_artifacts = await self.generate_video(
                            prompt=args_dict.get("prompt"),
                            size=args_dict.get("size", "1280x720"),
                            seconds=args_dict.get("duration", 8)  # Map duration param to seconds arg
                        )
                        
                        # Return success with video info
                        result = {
                            "success": True,
                            "message": "Video generated successfully",
                            "artifacts": video_artifacts
                        }
                        
                        return {
                            "tool_call_id": tool_call.id,
                            "output": json.dumps(result)
                        }
                    except Exception as e:
                        logger.error(f"Error generating video: {e}")
                        return {
                            "tool_call_id": tool_call.id,
                            "output": json.dumps({
                                "success": False,
                                "error": str(e)
                            })
                        }
                
                # Handle remix_video function call
                if function_name == "remix_video":
                    try:
                        args_dict = json.loads(arguments) if isinstance(arguments, str) else arguments
                        logger.info(f"Calling remix_video with args: {args_dict}")
                        
                        # Call the remix_video method
                        output_path, response_text = await self.remix_video(
                            video_id=args_dict.get("video_id"),
                            prompt=args_dict.get("prompt")
                        )
                        
                        # Return success with remixed video info
                        result = {
                            "success": True,
                            "message": response_text,
                            "output_path": output_path
                        }
                        
                        return {
                            "tool_call_id": tool_call.id,
                            "output": json.dumps(result)
                        }
                    except Exception as e:
                        logger.error(f"Error remixing video: {e}")
                        return {
                            "tool_call_id": tool_call.id,
                            "output": json.dumps({
                                "success": False,
                                "error": str(e)
                            })
                        }
                
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




async def create_foundry_template_agent() -> FoundryTemplateAgent:
    """Factory function to create and initialize a Foundry template agent."""
    agent = FoundryTemplateAgent()
    await agent.create_agent()
    return agent


# Example usage for testing
async def demo_agent_interaction():
    """Demo function showing how to use the Foundry template agent."""
    agent = await create_foundry_template_agent()
    
    try:
        # Create a conversation thread
        thread = await agent.create_thread()
        
        # Example interaction - customize this for your agent's domain
        message = "Hello! What can you help me with?"
        print(f"\nUser: {message}")
        async for response in agent.run_conversation_stream(thread.id, message):
            print(f"Assistant: {response}")
                
    finally:
        # DISABLED: Don't auto-cleanup agent to allow reuse
        # await agent.cleanup_agent()
        # Only clean up shared resources on final shutdown if really needed
        # await FoundryTemplateAgent.cleanup_shared_resources()
        logger.info("Demo completed - agent preserved for reuse")


if __name__ == "__main__":
    asyncio.run(demo_agent_interaction())