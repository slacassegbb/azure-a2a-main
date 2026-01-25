"""
Tool Context for Artifact Management.

Provides storage and retrieval for files and data artifacts that flow
through multi-agent conversations with hybrid local/Azure Blob storage.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from a2a.types import (
    Artifact,
    DataPart,
    FilePart,
    FileWithUri,
)

from log_config import log_debug, log_error

# Import the models we need
from .models import SessionContext


def _normalize_env_bool(raw_value: str | None, default: bool) -> bool:
    """Parse boolean environment variable with support for common true/false representations."""
    if raw_value is None:
        return default
    normalized = raw_value.strip().strip('"').strip("'").lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _normalize_env_int(raw_value: str | None, default: int) -> int:
    """Parse integer environment variable with support for quoted values."""
    if raw_value is None:
        return default
    try:
        return int(raw_value.strip().strip('"').strip("'"))
    except (TypeError, ValueError):
        return default


class DummyToolContext:
    """
    Tool context for artifact management during conversation processing.
    
    This class provides storage and retrieval for files and data artifacts that flow
    through multi-agent conversations. It implements a hybrid storage strategy:
    
    **Small files (<1MB)**: Stored locally for fast access
    **Large files (>1MB)**: Stored in Azure Blob Storage with SAS token URIs
    
    Artifacts are assigned unique IDs and made accessible to remote agents via:
    - HTTP URIs for local files (served by backend API)
    - Azure Blob SAS URIs with time-limited read access (24 hours)
    
    The context also tracks processing actions:
    - skip_summarization: Flag to bypass response summarization
    - escalate: Flag to indicate human intervention needed
    """
    
    def __init__(self, session_context: SessionContext, azure_blob_client=None):
        self.state = session_context
        self._artifacts: Dict[str, Dict[str, Any]] = {}  # Maps artifact_id -> {artifact, file_bytes, uri, etc.}
        self._azure_blob_client = azure_blob_client
        
        # Local filesystem storage for smaller artifacts
        self.storage_dir = os.path.join(os.getcwd(), "host_agent_files")
        os.makedirs(self.storage_dir, exist_ok=True)
        
        # Base URL for artifact retrieval (configurable per deployment)
        self.artifact_base_url = "http://localhost:8000/artifacts"
        
        # Action flags for conversation flow control
        class Actions:
            skip_summarization = False  # Skip host response if agent already provided full answer
            escalate = False  # Escalate to human if agent cannot complete task
        self.actions = Actions()
    
    async def save_artifact(self, file_id: str, file_part) -> DataPart:
        """
        Save a file artifact with intelligent storage selection and A2A protocol compliance.
        
        Storage Strategy (hybrid approach for optimal performance and cost):
        
        **Azure Blob Storage** (for files >1MB or when FORCE_AZURE_BLOB=true):
        - Scalable: Handle files up to 50MB
        - Accessible: Generate SAS tokens for secure agent access
        - Durable: Enterprise-grade reliability and backup
        - Cost-effective: Pay only for storage used
        
        **Local Filesystem** (for files <1MB):
        - Fast: No network latency for small files
        - Simple: Direct filesystem access
        - Development-friendly: Easy debugging
        
        Args:
            file_id: Original filename from user upload
            file_part: A2A file part or dict with file data
            
        Returns:
            DataPart with artifact-id, artifact-uri, and storage metadata
        """
        print(f"save_artifact called for file: {file_id}")
        
        # Generate unique artifact ID (A2A best practice)
        artifact_id = str(uuid.uuid4())
        print(f"Generated artifact ID: {artifact_id}")
        
        try:
            # Extract file data with robust error handling (A2A-native format)
            print(f"Extracting file data from file_part type: {type(file_part)}")
            file_role = None
            
            if isinstance(file_part, dict):
                # Handle A2A-native format
                if file_part.get('kind') == 'file' and 'file' in file_part:
                    file_info = file_part['file']
                    file_bytes = file_info['data']
                    mime_type = file_info.get('mimeType', 'application/octet-stream')
                    log_debug(f"Extracted {len(file_bytes)} bytes from A2A file part")
                    file_role = file_info.get('role')
                else:
                    print(f"Could not extract file bytes from A2A file part: {file_part.keys()}")
                    return DataPart(data={'error': 'Invalid A2A file format'})
            elif hasattr(file_part, 'inline_data') and hasattr(file_part.inline_data, 'data'):
                # Handle Google ADK format (fallback)
                file_bytes = file_part.inline_data.data
                mime_type = getattr(file_part.inline_data, 'mime_type', 'application/octet-stream')
                log_debug(f"Extracted {len(file_bytes)} bytes from inline_data")
                file_role = getattr(file_part.inline_data, 'role', None)
            elif hasattr(file_part, 'data'):
                file_bytes = file_part.data
                mime_type = 'application/octet-stream'
                log_debug(f"Extracted {len(file_bytes)} bytes from data attribute")
                file_role = getattr(file_part, 'role', None)
            else:
                print(f"Could not extract file bytes from artifact: {type(file_part)}")
                return DataPart(data={'error': 'Invalid file format'})
            
            print(f"File size: {len(file_bytes)} bytes, MIME type: {mime_type}")
            
            # Enhanced security: Validate file before processing
            if len(file_bytes) > 50 * 1024 * 1024:  # 50MB limit
                return DataPart(data={'error': 'File too large', 'max_size': '50MB'})
            
            # Determine storage strategy based on file size and configuration
            use_azure_blob = self._should_use_azure_blob(len(file_bytes))
            
            force_blob_flag = False
            if isinstance(file_part, dict) and file_part.get('kind') == 'file' and 'file' in file_part:
                force_blob_flag = file_part['file'].get('force_blob', False)

            file_uri: Optional[str] = None

            if (use_azure_blob or force_blob_flag) and hasattr(self, '_azure_blob_client'):
                # A2A URI mechanism with Azure Blob Storage
                print(f"Using Azure Blob Storage for large file")
                try:
                    file_uri = self._upload_to_azure_blob(artifact_id, file_id, file_bytes, mime_type)
                    print(f"✅ Azure Blob upload succeeded: {file_uri[:80]}...")
                except Exception as blob_err:
                    print(f"❌ Azure Blob upload exception caught:")
                    print(f"   Exception type: {type(blob_err).__name__}")
                    print(f"   Exception message: {str(blob_err)}")
                    import traceback
                    print(f"   Full traceback:")
                    for line in traceback.format_exc().split('\n'):
                        if line.strip():
                            print(f"   {line}")
                    # Fall back to local storage path below
                    file_uri = None
                
            normalized_role = str(file_role).lower() if file_role else None

            if file_uri:
                # Create A2A compliant Artifact with URI reference
                file_with_uri = FileWithUri(
                    name=file_id,
                    mimeType=mime_type,
                    uri=file_uri,
                    role=normalized_role,
                )
                file_part_obj = FilePart(kind="file", file=file_with_uri)

                artifact = Artifact(
                    artifactId=artifact_id,
                    name=file_id,
                    description=f"File uploaded via A2A protocol: {file_id}",
                    parts=[file_part_obj],
                    metadata={
                        "uploadTime": datetime.now(timezone.utc).isoformat(),
                        "fileSize": len(file_bytes),
                        "storageType": "azure_blob",
                        "contentType": mime_type,
                        "securityScan": "pending",
                        "accessMethod": "uri",
                        **({"role": normalized_role} if normalized_role else {}),
                    }
                )

                self._artifacts[artifact_id] = {
                    'artifact': artifact,
                    'storage_type': 'azure_blob',
                    'uri': file_uri,
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'role': normalized_role,
                }

                print(f"A2A Artifact stored in Azure Blob: {artifact_id} -> {file_uri}")

            else:
                # Local storage with inline bytes (current implementation)
                print(f"Using local storage for file")
                safe_filename = file_id.replace('/', '_').replace('\\', '_')
                file_path = os.path.join(self.storage_dir, f"host_received_{safe_filename}")
                
                with open(file_path, 'wb') as f:
                    f.write(file_bytes)
                
                # Create A2A compliant Artifact object with local reference
                file_with_uri = FileWithUri(
                    name=file_id,
                    mimeType=mime_type,
                    uri=f"{self.artifact_base_url}/{artifact_id}",
                    role=normalized_role,
                )
                file_part_obj = FilePart(kind="file", file=file_with_uri)
                
                artifact = Artifact(
                    artifactId=artifact_id,
                    name=file_id,
                    description=f"File uploaded via A2A protocol: {file_id}",
                    parts=[file_part_obj],
                    metadata={
                        "uploadTime": datetime.now(timezone.utc).isoformat(),
                        "fileSize": len(file_bytes),
                        "localPath": file_path,
                        "storageType": "local",
                        "contentType": mime_type,
                        "securityScan": "pending",
                        "accessMethod": "uri",
                        **({"role": normalized_role} if normalized_role else {}),
                    }
                )
                
                # Store in memory with full artifact metadata
                self._artifacts[artifact_id] = {
                    'artifact': artifact,
                    'file_bytes': file_bytes,
                    'local_path': file_path,
                    'storage_type': 'local',
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'role': normalized_role,
                }
                
                print(f"A2A Artifact stored locally: {artifact_id} for file: {file_id}")
                print(f"File saved to: {file_path} ({len(file_bytes)} bytes)")
            
            # Return A2A compliant DataPart with artifact reference
            artifact_uri = file_part_obj.file.uri
            
            response = DataPart(data={
                'artifact-id': artifact_id,
                'artifact-uri': artifact_uri,
                'file-name': file_id,
                'storage-type': 'azure_blob' if use_azure_blob else 'local',
                'status': 'stored',
                'message': f'File {file_id} successfully stored as A2A artifact {artifact_id}'
            })
            if file_role:
                response.data['role'] = str(file_role).lower()
                response.data['metadata'] = {**response.data.get('metadata', {}), 'role': str(file_role).lower()}
            
            return response
            
        except Exception as e:
            print(f"Error saving A2A artifact: {e}")
            import traceback
            log_error(f"Full traceback: {traceback.format_exc()}")
            return DataPart(data={
                'error': f'Failed to save artifact: {str(e)}',
                'file-name': file_id,
                'status': 'failed'
            })
    
    def _should_use_azure_blob(self, file_size_bytes: int) -> bool:
        """Determine whether to use Azure Blob based on file size and configuration."""
        raw_threshold = os.getenv('AZURE_BLOB_SIZE_THRESHOLD')
        size_threshold = _normalize_env_int(raw_threshold, 1024 * 1024)
        force_azure = _normalize_env_bool(os.getenv('FORCE_AZURE_BLOB'), False)
        has_azure_config = self._azure_blob_client is not None
 
        print(f"Azure Blob decision factors:")
        print(f"   - File size: {file_size_bytes:,} bytes")
        print(f"   - Size threshold: {size_threshold:,} bytes")
        print(f"   - Force Azure: {force_azure}")
        print(f"   - Has Azure client: {has_azure_config}")
        print(f"   - Size exceeds threshold: {file_size_bytes > size_threshold}")
 
        decision = has_azure_config and (force_azure or file_size_bytes > size_threshold)
        log_debug(f"🎯 Azure Blob decision: {'YES' if decision else 'NO'}")
 
        return decision
    
    def _upload_to_azure_blob(self, artifact_id: str, file_name: str, file_bytes: bytes, mime_type: str) -> str:
        """Upload file to Azure Blob Storage and return A2A-compliant URI with SAS token."""
        from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions, ContentSettings
        
        try:
            print(f"🔥 _upload_to_azure_blob ENTRY (SYNC)")
            print(f"   artifact_id: {artifact_id}")
            print(f"   file_name: {file_name}")
            print(f"   file_bytes size: {len(file_bytes)} bytes")
            print(f"   mime_type: {mime_type}")
            
            if not self._azure_blob_client:
                print(f"❌ _upload_to_azure_blob: Azure Blob client is None!")
                raise Exception("Azure Blob client not initialized")
            
            # Generate blob name with artifact ID for uniqueness
            safe_file_name = file_name.replace('/', '_').replace('\\', '_')
            blob_name = f"a2a-artifacts/{artifact_id}/{safe_file_name}"
            
            # Upload to Azure Blob
            container_name = os.getenv('AZURE_BLOB_CONTAINER', 'a2a-files')
            
            blob_client = self._azure_blob_client.get_blob_client(
                container=container_name,
                blob=blob_name
            )
            
            # Create proper ContentSettings object
            content_settings = ContentSettings(
                content_type=mime_type,
                content_disposition=f'attachment; filename="{file_name}"'
            )
            
            # Upload with metadata (synchronous call)
            print(f"   🔄 Starting blob upload...")
            blob_client.upload_blob(
                file_bytes,
                content_settings=content_settings,
                metadata={
                    'artifact_id': artifact_id,
                    'original_name': file_name,
                    'upload_time': datetime.now(timezone.utc).isoformat(),
                    'a2a_protocol': 'true'
                },
                overwrite=True
            )
            print(f"   ✅ Blob uploaded successfully!")
            
            # Extract account key from connection string for SAS token generation
            connection_string = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
            account_key = None
            if connection_string:
                for part in connection_string.split(';'):
                    if part.startswith('AccountKey='):
                        account_key = part.split('=', 1)[1]
                        break
            
            sas_token = None
            if account_key:
                print(f"   🔐 Generating SAS token with account key...")
                sas_token = generate_blob_sas(
                    account_name=blob_client.account_name,
                    container_name=blob_client.container_name,
                    blob_name=blob_name,
                    account_key=account_key,
                    permission=BlobSasPermissions(read=True),
                    expiry=datetime.now(timezone.utc) + timedelta(hours=24),
                    version="2023-11-03",
                )
            else:
                # Attempt user-delegation SAS when using Azure AD credentials
                try:
                    print(f"   🔐 Requesting user delegation key for SAS...")
                    delegation_key = self._azure_blob_client.get_user_delegation_key(
                        key_start_time=datetime.now(timezone.utc) - timedelta(minutes=5),
                        key_expiry_time=datetime.now(timezone.utc) + timedelta(hours=24),
                    )
                    sas_token = generate_blob_sas(
                        account_name=blob_client.account_name,
                        container_name=blob_client.container_name,
                        blob_name=blob_name,
                        user_delegation_key=delegation_key,
                        permission=BlobSasPermissions(read=True),
                        expiry=datetime.now(timezone.utc) + timedelta(hours=24),
                        version="2023-11-03",
                    )
                    print(f"   ✅ User delegation SAS generated")
                except Exception as ude_err:
                    print(f"   ⚠️ Failed to generate user delegation SAS: {ude_err}")

            if sas_token:
                blob_uri = f"{blob_client.url}?{sas_token}"
                print(f"   ✅ SAS token generated: {blob_uri[:80]}...")
            else:
                raise RuntimeError("Unable to generate SAS token for blob upload")
            
            print(f"🔥 _upload_to_azure_blob EXIT - returning URI")
            return blob_uri
            
        except Exception as e:
            print(f"❌ _upload_to_azure_blob ERROR: {e}")
            import traceback
            print(f"   Full traceback: {traceback.format_exc()}")
            raise Exception(f"Azure Blob upload failed: {str(e)}")
    
    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        """Retrieve saved artifact by ID (A2A compliant)."""
        artifact_data = self._artifacts.get(artifact_id)
        if artifact_data:
            return artifact_data['artifact']
        return None
    
    def get_artifact_data(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve full artifact data including file bytes (A2A compliant)."""
        return self._artifacts.get(artifact_id)
    
    def list_artifacts(self) -> list:
        """List all stored artifacts (A2A compliant)."""
        return [data['artifact'] for data in self._artifacts.values()]
