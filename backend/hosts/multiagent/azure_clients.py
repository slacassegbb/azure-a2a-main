"""
AzureClients - Azure client initialization and authentication for FoundryHostAgent2.

This module contains methods related to:
- Azure AI Project Client and Agents Client initialization
- Azure Blob Storage client setup and verification
- Azure authentication with token caching and retry logic
- OpenAI endpoint conversion

These are extracted from foundry_agent_a2a.py to improve code organization.
The class is designed to be used as a mixin with FoundryHostAgent2.
"""

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Import logging utilities
import sys
from pathlib import Path
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from azure.ai.projects.aio import AIProjectClient

from log_config import (
    log_debug,
    log_error,
    log_foundry_debug,
)


class AzureClients:
    """
    Mixin providing Azure client initialization and authentication methods.
    
    This mixin handles:
    - Azure AI Project Client initialization with event loop awareness
    - Azure Blob Storage client setup
    - Authentication token management with caching
    - OpenAI endpoint conversion
    
    Expected instance attributes (set by main class __init__):
    - self.endpoint: str
    - self.credential: Any (Azure credential)
    - self.project_client: Optional[AIProjectClient]
    - self.agents_client: Any
    - self._cached_token: Optional[str]
    - self._token_expiry: Optional[datetime]
    - self._azure_blob_client: Any
    - self._azure_blob_container: Optional[str]
    """

    async def _ensure_project_client(self):
        """
        Initialize Azure AI Project Client and Agents Client if not already done.
        
        IMPORTANT: AIProjectClient must be created in the same event loop where it's used.
        If the event loop has changed, we need to recreate the client.
        """
        current_loop = asyncio.get_running_loop()
        
        # Check if we need to recreate the client for a new event loop
        if self.project_client is not None:
            # Check if the client's loop is still the current loop
            try:
                # If the client was created in a different loop, recreate it
                if hasattr(self, '_project_client_loop') and self._project_client_loop != current_loop:
                    log_foundry_debug("🔄 Event loop changed, recreating AIProjectClient...")
                    # Close the old client if possible
                    if hasattr(self.project_client, 'close'):
                        try:
                            await self.project_client.close()
                        except:
                            pass
                    self.project_client = None
                    self.agents_client = None
                    self.credential = None
            except:
                pass
        
        # Recreate credential if needed
        if self.credential is None:
            from azure.identity.aio import AzureCliCredential, DefaultAzureCredential
            
            # Detect if we're running in Azure Container Apps (managed identity)
            is_azure_container = os.environ.get('CONTAINER_APP_NAME') or os.environ.get('WEBSITE_INSTANCE_ID')
            
            if is_azure_container:
                # Use DefaultAzureCredential in Azure (will use managed identity)
                self.credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
                log_foundry_debug("Recreated DefaultAzureCredential (Managed Identity) for new event loop")
            else:
                # Use AzureCliCredential locally
                self.credential = AzureCliCredential(process_timeout=5)
                log_foundry_debug("Recreated AzureCliCredential for new event loop")
        
        if self.project_client is None:
            log_foundry_debug("🔧 Initializing AIProjectClient...")
            self.project_client = AIProjectClient(
                endpoint=self.endpoint,
                credential=self.credential,
            )
            self._project_client_loop = current_loop
            log_foundry_debug("✅ AIProjectClient initialized")
        
        if self.agents_client is None:
            log_foundry_debug("🔧 Getting AgentsClient from project...")
            self.agents_client = self.project_client.agents
            log_foundry_debug("✅ AgentsClient ready")

    def _init_azure_blob_client(self):
        """Initialize Azure Blob Storage client if environment variables are configured."""
        try:
            self._azure_blob_client = None
            self._azure_blob_container = os.getenv('AZURE_BLOB_CONTAINER', 'a2a-files')
            azure_storage_connection_string = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
            azure_storage_account_name = os.getenv('AZURE_STORAGE_ACCOUNT_NAME')
            
            if azure_storage_connection_string:
                from azure.storage.blob import BlobServiceClient
                self._azure_blob_client = BlobServiceClient.from_connection_string(
                    azure_storage_connection_string,
                    api_version="2023-11-03",
                )
                log_debug("Azure Blob Storage initialized with connection string")
            elif azure_storage_account_name:
                from azure.storage.blob import BlobServiceClient
                account_url = f"https://{azure_storage_account_name}.blob.core.windows.net"
                self._azure_blob_client = BlobServiceClient(
                    account_url,
                    credential=self.credential,
                    api_version="2023-11-03",
                )
                log_debug(f"Azure Blob Storage initialized with managed identity: {account_url}")
            else:
                log_debug("Azure Blob Storage not configured - using local storage")
                self._azure_blob_container = None
            
            if self._azure_blob_client:
                log_debug(f"Target Azure Blob container: {self._azure_blob_container}")
                loop = asyncio.get_running_loop()
                loop.create_task(self._verify_blob_connection())

        except ImportError as e:
            log_debug(f"Azure Storage SDK not installed - using local storage: {e}")
        except Exception as e:
            log_error(f"Failed to initialize Azure Blob Storage: {e}")
            self._azure_blob_client = None

    async def _verify_blob_connection(self):
        """Log diagnostics about the configured Azure Blob container."""
        if not self._azure_blob_client or not self._azure_blob_container:
            print("ℹ️ Azure Blob verification skipped: client or container not set")
            return

        try:
            print("🔍 Azure Blob check: resolving container client...")
            container_client = self._azure_blob_client.get_container_client(self._azure_blob_container)

            print("🔍 Azure Blob check: ensuring container exists...")
            try:
                await asyncio.to_thread(container_client.create_container)
                print(f"✅ Azure Blob container '{self._azure_blob_container}' created")
            except Exception as create_err:
                from azure.core.exceptions import ResourceExistsError
                if isinstance(create_err, ResourceExistsError):
                    print(f"ℹ️ Azure Blob container '{self._azure_blob_container}' already exists")
                else:
                    raise

            print("🔍 Azure Blob check: listing blobs (up to 5 entries)...")
            blob_count = 0
            for blob in container_client.list_blobs(name_starts_with="a2a-artifacts/"):
                print(f"   • Existing blob: {blob.name} (size={blob.size})")
                blob_count += 1
                if blob_count >= 5:
                    print("   • ... additional blobs omitted ...")
                    break
            if blob_count == 0:
                print("   • No blobs found yet in this container")

            print("🔍 Azure Blob check: uploading connectivity probe...")
            probe_blob_name = f"a2a-artifacts/_connectivity_probe_.txt"
            probe_client = container_client.get_blob_client(probe_blob_name)
            probe_payload = f"connection verified at {datetime.now(timezone.utc).isoformat()}"
            await asyncio.to_thread(probe_client.upload_blob, probe_payload, overwrite=True)
            print(f"✅ Azure Blob probe uploaded: {probe_blob_name}")

        except Exception as e:
            print(f"❌ Azure Blob verification failed: {e}")
            import traceback
            print(traceback.format_exc())

    async def _get_auth_headers(self) -> Dict[str, str]:
        """
        Obtain Azure authentication headers with token caching for performance.
        
        Implements:
        - Token caching with 5-minute expiry buffer to avoid auth failures
        - Automatic retry logic (3 attempts) with exponential backoff
        - Timeout protection (8 seconds) to prevent hanging
        - Helpful error messages for common authentication issues
        
        Returns:
            Dict containing Authorization and Content-Type headers
        """
        log_foundry_debug(f"Getting authentication token with timeout handling and caching")
        
        # Return cached token if still valid (with 5-minute safety buffer)
        if self._cached_token and self._token_expiry:
            from datetime import datetime as dt, timedelta
            # Add 5 minute buffer before expiry
            buffer_time = dt.now() + timedelta(minutes=5)
            if self._token_expiry > buffer_time:
                log_foundry_debug(f"✅ Using cached token (expires: {self._token_expiry})")
                return {
                    "Authorization": f"Bearer {self._cached_token}",
                    "Content-Type": "application/json"
                }
        
        # Token acquisition with retry logic for reliability
        max_retries = 3
        for attempt in range(max_retries):
            try:
                log_foundry_debug(f"Token attempt {attempt + 1}/{max_retries}...")
                
                # Get token with proper async handling
                import asyncio
                import inspect
                
                # Check if get_token is async or sync
                get_token_method = self.credential.get_token
                
                if inspect.iscoroutinefunction(get_token_method):
                    # Async credential - await directly with timeout
                    log_foundry_debug("Using async credential.get_token()")
                    token = await asyncio.wait_for(
                        self.credential.get_token("https://ai.azure.com/.default"),
                        timeout=8.0
                    )
                else:
                    # Sync credential - run in executor to avoid blocking
                    log_foundry_debug("Using sync credential.get_token() in executor")
                    async def get_token_async():
                        loop = asyncio.get_event_loop()
                        return await loop.run_in_executor(
                            None, 
                            lambda: self.credential.get_token("https://ai.azure.com/.default")
                        )
                    
                    token = await asyncio.wait_for(get_token_async(), timeout=8.0)
                
                # Cache the token
                self._cached_token = token.token
                from datetime import datetime as dt
                self._token_expiry = dt.fromtimestamp(token.expires_on)
                
                headers = {
                    "Authorization": f"Bearer {token.token}",
                    "Content-Type": "application/json"
                }
                log_foundry_debug(f"✅ Authentication headers obtained successfully (expires: {self._token_expiry})")
                return headers
                
            except asyncio.TimeoutError:
                error_name = "TimeoutError"
                error_msg = "Authentication request timed out after 8 seconds"
                log_foundry_debug(f"⚠️ Auth attempt {attempt + 1} timed out after 8 seconds")
                
            except Exception as e:
                error_name = type(e).__name__
                error_msg = str(e)
                
                if attempt < max_retries - 1:
                    log_foundry_debug(f"⚠️ Auth attempt {attempt + 1} failed ({error_name}), retrying in 3 seconds...")
                    log_foundry_debug(f"⚠️ Error details: {error_msg}")
                    await asyncio.sleep(3)  # Wait 3 seconds before retry
                    continue
                else:
                    log_foundry_debug(f"❌ Failed to get authentication token after {max_retries} attempts: {error_name}: {e}")
                    
                    # Provide specific help based on error type
                    if "CredentialUnavailableError" in error_name and "Azure CLI" in error_msg:
                        print("💡 DEBUG: Azure CLI authentication failed. Try:")
                        print("   1. az login --tenant <your-tenant-id>")
                        print("   2. az account set --subscription <your-subscription-id>")
                        print("   3. Set environment variables for service principal auth")
                    elif "TimeoutError" in error_name or "timed out" in error_msg.lower():
                        print("💡 DEBUG: Authentication timed out. Try:")
                        print("   1. Check your network connection")
                        print("   2. Run 'az login' to refresh your session")
                        print("   3. Consider using service principal authentication for better reliability")
                    elif "ChainedTokenCredential" in error_msg:
                        print("💡 DEBUG: All credential types failed. Options:")
                        print("   1. Set environment variables: AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET")
                        print("   2. Run 'az login' and try again")
                        print("   3. Run from Azure environment (VM, Container App, etc.)")
                    
                    raise

    def _clear_cached_token(self):
        """Clear cached authentication token to force refresh on next request"""
        log_foundry_debug(f"🔄 Clearing cached authentication token")
        self._cached_token = None
        self._token_expiry = None

    async def refresh_azure_cli_session(self):
        """Helper method to refresh Azure CLI session when authentication fails"""
        try:
            log_foundry_debug(f"🔄 Attempting to refresh Azure CLI session...")
            import subprocess
            import asyncio
            
            # Run az account get-access-token to refresh session
            process = await asyncio.create_subprocess_exec(
                'az', 'account', 'get-access-token', '--output', 'json',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10.0)
            
            if process.returncode == 0:
                log_foundry_debug(f"✅ Azure CLI session refreshed successfully")
                self._clear_cached_token()  # Clear cache to use fresh token
                return True
            else:
                log_foundry_debug(f"❌ Azure CLI refresh failed: {stderr.decode()}")
                return False
                
        except asyncio.TimeoutError:
            log_foundry_debug(f"❌ Azure CLI refresh timed out")
            return False
        except Exception as e:
            log_foundry_debug(f"❌ Error refreshing Azure CLI session: {e}")
            return False

    def _get_openai_endpoint(self) -> str:
        """
        Convert AI Foundry endpoint to OpenAI /v1/ endpoint format.
        
        Converts from: https://RESOURCE.services.ai.azure.com/subscriptions/.../
        To: https://RESOURCE.openai.azure.com/openai/v1/
        """
        endpoint = self.endpoint
        
        if "services.ai.azure.com" in endpoint:
            # Extract resource name from AI Foundry endpoint
            # Example: https://simonfoundry.services.ai.azure.com/...
            parts = endpoint.split("//")[1].split(".")[0]
            openai_endpoint = f"https://{parts}.openai.azure.com/openai/v1/"
            log_foundry_debug(f"Converted endpoint: {endpoint} -> {openai_endpoint}")
            return openai_endpoint
        else:
            # Already in OpenAI format or needs manual /openai/v1/ suffix
            openai_endpoint = endpoint if endpoint.endswith("/openai/v1/") else f"{endpoint.rstrip('/')}/openai/v1/"
            log_foundry_debug(f"Using endpoint as-is: {openai_endpoint}")
            return openai_endpoint

    def _get_openai_client(self):
        """
        Get client configured for Responses API via direct HTTP calls.
        
        Note: The Responses API is accessed via direct HTTP to /openai/v1/responses,
        not through the OpenAI SDK's standard client interface.
        
        This method is kept for compatibility but the actual HTTP calls
        are made directly in _create_response_with_streaming.
        """
        # This is now a placeholder - actual HTTP calls are made directly
        return None

    def _get_client(self):
        """Legacy method - now throws error to identify remaining SDK usage"""
        raise NotImplementedError(
            "❌ _get_client() is no longer supported! "
            "The foundry_agent_a2a.py now uses HTTP API calls instead of the azure.ai.agents SDK. "
            "This error indicates that some code is still trying to use the old SDK approach. "
            "Please update the calling code to use HTTP-based methods."
        )
