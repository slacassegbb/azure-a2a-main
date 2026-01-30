from typing import List, Optional, Dict, Any
import os
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    SearchFieldDataType,
    SearchField,
)
import time
from azure.core.exceptions import ResourceNotFoundError
import openai
import sys

ROOT_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(dotenv_path=ROOT_ENV_PATH, override=False)

# Add backend directory to path for log_config import
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from log_config import log_memory_debug, log_info, log_success, log_warning, log_error

# Azure Cognitive Search configuration
service_endpoint = os.getenv("AZURE_SEARCH_SERVICE_ENDPOINT")
admin_key = os.getenv("AZURE_SEARCH_ADMIN_KEY")
vector_dimension = int(os.getenv("AZURE_SEARCH_VECTOR_DIMENSION", "1536"))
index_name = os.getenv("AZURE_SEARCH_INDEX_NAME", "a2a-agent-interactions")
vector_profile_name = os.getenv("AZURE_SEARCH_VECTOR_PROFILE", "a2a-vector-profile")
vector_algorithm_name = os.getenv("AZURE_SEARCH_VECTOR_ALGORITHM", "a2a-hnsw-config")

# Azure OpenAI configuration
azure_openai_endpoint = os.getenv("AZURE_OPENAI_EMBEDDINGS_ENDPOINT")
azure_openai_key = os.getenv("AZURE_OPENAI_EMBEDDINGS_KEY")
azure_openai_deployment = os.getenv("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT")

class A2AMemoryService:
    def __init__(self):
        # Initialize the search clients only if environment variables are available
        if not admin_key or not service_endpoint:
            print(f"⚠️ Azure Search not configured (admin_key: {admin_key is not None}, service_endpoint: {service_endpoint is not None})")
            print(f"⚠️ Memory service will be disabled")
            self.credential = None
            self.index_client = None
            self.search_client = None
            self.azure_openai_client = None
            self._enabled = False
            return
            
        try:
            self.credential = AzureKeyCredential(admin_key)
            self.index_client = SearchIndexClient(
                endpoint=service_endpoint,
                credential=self.credential
            )
            
            # Initialize other clients only if Azure OpenAI config is available
            if azure_openai_endpoint and azure_openai_key and azure_openai_deployment:
                self.openai_client = openai.AzureOpenAI(
                    azure_endpoint=azure_openai_endpoint,
                    api_key=azure_openai_key,
                    api_version="2024-02-01"
                )
                print(f"✅ Azure OpenAI client initialized")
            else:
                print(f"⚠️ Azure OpenAI not configured - embeddings disabled")
                self.openai_client = None
            
            self.search_client = None
            self.index_name = index_name
            
            self._enabled = True
            print(f"✅ Azure Search initialized successfully")
            
            # Create index on initialization
            self._create_index_if_not_exists()
            
        except Exception as e:
            print(f"❌ Failed to initialize Azure Search: {e}")
            self.credential = None
            self.index_client = None
            self.search_client = None
            self.azure_openai_client = None
            self.openai_client = None
            self._enabled = False
            return

    def _create_index_if_not_exists(self):
        """Create index if it doesn't exist - wrapper for _ensure_index_exists"""
        return self._ensure_index_exists()
        self._ensure_index_exists()

    def _ensure_index_exists(self) -> bool:
        """Ensure the A2A interactions index exists"""
        log_memory_debug(f"Ensuring index {self.index_name} exists")
        
        # Check if index already exists
        try:
            existing_index = self.index_client.get_index(self.index_name)
            if self._is_index_compatible(existing_index):
                log_memory_debug(f"Index {self.index_name} already exists")
                self.search_client = SearchClient(
                    endpoint=service_endpoint,
                    index_name=self.index_name,
                    credential=self.credential
                )
                return True
            else:
                log_memory_debug(f"Existing index configuration does not match expected settings. Recreating index {self.index_name}.")
                self.index_client.delete_index(self.index_name)
        except ResourceNotFoundError:
            log_memory_debug(f"Index {self.index_name} does not exist, creating new index")
        except Exception as e:
            log_memory_debug(f"Unexpected error checking index existence: {str(e)}")
            return False

        # Create the index
        return self._create_interactions_index()

    def _create_interactions_index(self) -> bool:
        """Create the A2A interactions search index"""
        vector_search_config = {
            "algorithms": [
                {
                    "name": vector_algorithm_name,
                    "kind": "hnsw",
                    "hnswParameters": {
                        "m": 4,
                        "efConstruction": 400,
                        "efSearch": 500,
                        "metric": "cosine"
                    }
                }
            ],
            "profiles": [
                {
                    "name": vector_profile_name,
                    "algorithm": vector_algorithm_name
                }
            ]
        }

        # Define fields for A2A protocol data
        fields = [
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(name="session_id", type=SearchFieldDataType.String, filterable=True),  # Tenant isolation
            SimpleField(name="agent_name", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="processing_time_seconds", type=SearchFieldDataType.Double),
            SimpleField(name="timestamp", type=SearchFieldDataType.DateTimeOffset),
            
            # Complete A2A protocol payloads
            SearchableField(name="outbound_payload", type=SearchFieldDataType.String),
            SearchableField(name="inbound_payload", type=SearchFieldDataType.String),
            
            # Vector embedding for semantic search
            SearchField(
                name="interaction_vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=vector_dimension,
                vector_search_profile_name=vector_profile_name
            )
        ]

        # Create index
        index = SearchIndex(
            name=self.index_name,
            fields=fields,
            vector_search=vector_search_config
        )
        
        try:
            log_memory_debug(f"Creating index {self.index_name}")
            self.index_client.create_index(index)
            log_memory_debug(f"Successfully created index {self.index_name}")
            
            # Wait for index to be ready
            if self._wait_for_index(self.index_name):
                self.search_client = SearchClient(
                    endpoint=service_endpoint,
                    index_name=self.index_name,
                    credential=self.credential
                )
                return True
            return False
            
        except Exception as e:
            log_memory_debug(f"Error creating index: {str(e)}")
            return False

    def _is_index_compatible(self, index: SearchIndex) -> bool:
        """Validate that an existing index matches the configured settings including session_id field."""
        try:
            has_session_id = False
            has_valid_vector = False
            
            for field in index.fields:
                # Check for session_id field (required for multi-tenancy)
                if field.name == "session_id":
                    has_session_id = True
                
                # Check vector field configuration
                if field.name == "interaction_vector":
                    current_dim = getattr(field, "vector_search_dimensions", None)
                    current_profile = getattr(field, "vector_search_profile_name", None)
                    if current_dim != vector_dimension:
                        log_memory_debug(
                            f"Existing vector dimension {current_dim} != expected {vector_dimension}"
                        )
                        return False
                    if current_profile != vector_profile_name:
                        log_memory_debug(
                            f"Existing vector profile {current_profile} != expected {vector_profile_name}"
                        )
                        return False
                    has_valid_vector = True
            
            if not has_session_id:
                log_memory_debug("session_id field missing in index - recreating for multi-tenancy support")
                return False
            
            if not has_valid_vector:
                log_memory_debug("interaction_vector field missing in index definition.")
                return False
            
            return True
        except Exception as e:
            log_memory_debug(f"Failed to validate existing index: {e}")
            return False

    def _wait_for_index(self, index_name: str, max_retries: int = 5, delay: int = 5) -> bool:
        """Wait for index to be available and ready for operations"""
        for i in range(max_retries):
            try:
                self.index_client.get_index(index_name)
                
                # Test with a simple search operation
                search_client = SearchClient(
                    endpoint=service_endpoint,
                    index_name=index_name,
                    credential=self.credential
                )
                search_client.search(search_text="*", top=1)
                
                log_memory_debug(f"Index {index_name} is ready")
                return True
            except Exception as e:
                if i < max_retries - 1:
                    log_memory_debug(f"Waiting for index (attempt {i+1}/{max_retries})")
                    time.sleep(delay)
                continue
        
        log_memory_debug(f"Index failed to become ready after {max_retries} attempts")
        return False

    async def _create_embedding(self, text: str) -> List[float]:
        """Create embedding for text using Azure OpenAI"""
        log_memory_debug(f"_create_embedding called with text length: {len(text)}")
        try:
            log_memory_debug("Calling Azure OpenAI embeddings API...")
            response = self.openai_client.embeddings.create(
                model=azure_openai_deployment,
                input=text
            )
            log_memory_debug("Azure OpenAI embeddings API returned successfully")
            embedding = response.data[0].embedding
            log_memory_debug(f"Extracted embedding with {len(embedding)} dimensions")
            return embedding
        except Exception as e:
            log_memory_debug(f"Error creating embedding: {str(e)}")
            log_memory_debug(f"Exception type: {type(e).__name__}")
            import traceback
            log_memory_debug(f"Traceback: {traceback.format_exc()}")
            return []

    def _chunk_text(self, text: str, chunk_size: int = 6000, overlap: int = 500) -> List[Dict[str, Any]]:
        """Split text into overlapping chunks for embedding.
        
        Args:
            text: The text to chunk
            chunk_size: Maximum characters per chunk (~1500 tokens)
            overlap: Number of overlapping characters between chunks
            
        Returns:
            List of dicts with 'text', 'chunk_index', 'total_chunks', 'start_char', 'end_char'
        """
        if len(text) <= chunk_size:
            return [{
                'text': text,
                'chunk_index': 0,
                'total_chunks': 1,
                'start_char': 0,
                'end_char': len(text)
            }]
        
        chunks = []
        start = 0
        chunk_index = 0
        
        while start < len(text):
            end = start + chunk_size
            
            # Try to break at a natural boundary (paragraph, sentence, or word)
            if end < len(text):
                # Look for paragraph break
                para_break = text.rfind('\n\n', start + chunk_size // 2, end)
                if para_break > start:
                    end = para_break + 2
                else:
                    # Look for sentence break
                    sentence_break = max(
                        text.rfind('. ', start + chunk_size // 2, end),
                        text.rfind('.\n', start + chunk_size // 2, end),
                        text.rfind('? ', start + chunk_size // 2, end),
                        text.rfind('! ', start + chunk_size // 2, end)
                    )
                    if sentence_break > start:
                        end = sentence_break + 2
                    else:
                        # Look for word break
                        word_break = text.rfind(' ', start + chunk_size // 2, end)
                        if word_break > start:
                            end = word_break + 1
            
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append({
                    'text': chunk_text,
                    'chunk_index': chunk_index,
                    'start_char': start,
                    'end_char': min(end, len(text))
                })
                chunk_index += 1
            
            # Move start position with overlap
            start = end - overlap if end < len(text) else len(text)
        
        # Update total_chunks in all chunks
        total = len(chunks)
        for chunk in chunks:
            chunk['total_chunks'] = total
        
        return chunks

    async def store_interaction(self, interaction_data: Dict[str, Any], session_id: str = None) -> bool:
        """Store A2A protocol payloads in the search index with tenant isolation.
        
        For large documents, automatically chunks content into multiple search documents
        with overlapping text for better semantic search coverage.
        
        Args:
            interaction_data: Dict containing agent_name, outbound_payload, inbound_payload, etc.
            session_id: Required for multi-tenancy. The session/tenant identifier.
        """
        if not self._enabled:
            log_memory_debug("Memory service disabled - skipping store_interaction")
            return True  # Return success to avoid breaking the flow
        
        # Validate session_id for multi-tenancy
        if not session_id:
            log_memory_debug("⚠️ No session_id provided - memory will not be stored (multi-tenancy required)")
            return False
            
        log_memory_debug("store_interaction called")
        log_memory_debug(f"Session ID: {session_id}")
        log_memory_debug(f"Agent name: {interaction_data.get('agent_name', 'unknown')}")
        
        if not self.search_client:
            log_memory_debug("Search client not initialized")
            return False

        try:
            # Get the inbound payload content (this is where document text lives)
            inbound_payload = interaction_data.get('inbound_payload', {})
            outbound_payload = interaction_data.get('outbound_payload', {})
            
            # Extract content for chunking (usually in 'content' field for documents)
            content_to_chunk = ""
            if isinstance(inbound_payload, dict):
                content_to_chunk = inbound_payload.get('content', '')
            elif isinstance(inbound_payload, str):
                content_to_chunk = inbound_payload
            
            # Threshold for chunking: ~24K chars = ~6K tokens
            CHUNK_THRESHOLD = 24000
            
            if len(content_to_chunk) > CHUNK_THRESHOLD:
                # Large document - use chunking strategy
                log_memory_debug(f"Large document detected ({len(content_to_chunk)} chars), using chunking strategy")
                return await self._store_chunked_document(interaction_data, session_id, content_to_chunk)
            else:
                # Small document - store as single document (original behavior)
                return await self._store_single_document(interaction_data, session_id)

        except Exception as e:
            log_memory_debug(f"Error storing A2A payloads: {str(e)}")
            import traceback
            log_memory_debug(f"Traceback: {traceback.format_exc()}")
            return False

    async def _store_single_document(self, interaction_data: Dict[str, Any], session_id: str) -> bool:
        """Store a single (small) document without chunking."""
        try:
            outbound_str = str(interaction_data.get('outbound_payload', ''))
            inbound_str = str(interaction_data.get('inbound_payload', ''))
            
            log_memory_debug(f"Outbound payload length: {len(outbound_str)}")
            log_memory_debug(f"Inbound payload length: {len(inbound_str)}")
            
            # Truncate for embedding if needed (safety net)
            MAX_EMBEDDING_CHARS = 28000
            embed_inbound = inbound_str[:MAX_EMBEDDING_CHARS] if len(inbound_str) > MAX_EMBEDDING_CHARS else inbound_str
            embed_outbound = outbound_str[:MAX_EMBEDDING_CHARS] if len(outbound_str) > MAX_EMBEDDING_CHARS else outbound_str
            
            searchable_text = f"""
            Agent: {interaction_data.get('agent_name', '')}
            Outbound: {embed_outbound}
            Inbound: {embed_inbound}
            """
            
            embedding = await self._create_embedding(searchable_text.strip())
            if not embedding or len(embedding) != vector_dimension:
                log_memory_debug("Failed to create valid embedding")
                return False

            document = {
                "id": interaction_data.get('interaction_id', str(uuid.uuid4())),
                "session_id": session_id,
                "agent_name": interaction_data.get('agent_name', ''),
                "processing_time_seconds": interaction_data.get('processing_time_seconds', 0.0),
                "timestamp": interaction_data.get('timestamp', datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'),
                "outbound_payload": json.dumps(interaction_data.get('outbound_payload', {})),
                "inbound_payload": json.dumps(interaction_data.get('inbound_payload', {})),
                "interaction_vector": embedding
            }
            
            self.search_client.upload_documents([document])
            log_success(f"Successfully stored document {document['id']} for session {session_id}")
            return True

        except Exception as e:
            log_memory_debug(f"Error storing single document: {str(e)}")
            return False

    async def _store_chunked_document(self, interaction_data: Dict[str, Any], session_id: str, content: str) -> bool:
        """Store a large document as multiple chunks with overlapping text."""
        try:
            base_id = interaction_data.get('interaction_id', str(uuid.uuid4()))
            agent_name = interaction_data.get('agent_name', '')
            filename = interaction_data.get('filename', '')
            timestamp = interaction_data.get('timestamp', datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z')
            outbound_payload = interaction_data.get('outbound_payload', {})
            inbound_payload = interaction_data.get('inbound_payload', {})
            
            # Chunk the content with overlap
            chunks = self._chunk_text(content, chunk_size=6000, overlap=500)
            log_memory_debug(f"Document split into {len(chunks)} chunks")
            
            documents_to_upload = []
            
            for chunk in chunks:
                chunk_id = f"{base_id}_chunk_{chunk['chunk_index']}"
                
                # Create embedding for this chunk
                searchable_text = f"""
                Document: {filename}
                Agent: {agent_name}
                Chunk {chunk['chunk_index'] + 1} of {chunk['total_chunks']}:
                {chunk['text']}
                """
                
                embedding = await self._create_embedding(searchable_text.strip())
                if not embedding or len(embedding) != vector_dimension:
                    log_memory_debug(f"Failed to create embedding for chunk {chunk['chunk_index']}")
                    continue
                
                # Create chunk-specific inbound payload
                chunk_inbound = {
                    "type": inbound_payload.get("type", "document_chunk") if isinstance(inbound_payload, dict) else "document_chunk",
                    "content": chunk['text'],
                    "chunk_index": chunk['chunk_index'],
                    "total_chunks": chunk['total_chunks'],
                    "start_char": chunk['start_char'],
                    "end_char": chunk['end_char'],
                    "parent_document_id": base_id,
                    "filename": filename,
                    "processed_at": inbound_payload.get("processed_at") if isinstance(inbound_payload, dict) else timestamp
                }
                
                document = {
                    "id": chunk_id,
                    "session_id": session_id,
                    "agent_name": agent_name,
                    "processing_time_seconds": 0.0,
                    "timestamp": timestamp,
                    "outbound_payload": json.dumps(outbound_payload),
                    "inbound_payload": json.dumps(chunk_inbound),
                    "interaction_vector": embedding
                }
                
                documents_to_upload.append(document)
            
            if documents_to_upload:
                # Upload all chunks in batch
                self.search_client.upload_documents(documents_to_upload)
                log_success(f"Successfully stored {len(documents_to_upload)} chunks for document {base_id} (session: {session_id})")
                return True
            else:
                log_memory_debug("No chunks were successfully processed")
                return False

        except Exception as e:
            log_memory_debug(f"Error storing chunked document: {str(e)}")
            import traceback
            log_memory_debug(f"Traceback: {traceback.format_exc()}")
            return False

    async def search_similar_interactions(
        self, 
        query: str,
        session_id: str = None,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Search for similar interactions using semantic search with tenant isolation.
        
        Args:
            query: The search query text
            session_id: Required for multi-tenancy. Only returns results for this session.
            filters: Additional filters (e.g., agent_name)
            top_k: Number of results to return
        """
        if not self._enabled:
            log_memory_debug("Memory service disabled - returning empty results")
            return []
        
        # Validate session_id for multi-tenancy
        if not session_id:
            log_memory_debug("⚠️ No session_id provided - returning empty results (multi-tenancy required)")
            return []
            
        if not self.search_client:
            log_memory_debug("Search client not initialized")
            return []

        try:
            # Create embedding for query
            query_embedding = await self._create_embedding(query)
            if not query_embedding:
                log_memory_debug("Failed to create query embedding")
                return []
            if len(query_embedding) != vector_dimension:
                log_memory_debug(
                    f"Query embedding dimension {len(query_embedding)} does not match configured vector dimension {vector_dimension}."
                )
                return []

            # Build filter expression - ALWAYS include session_id for tenant isolation
            filter_parts = [f"session_id eq '{session_id}'"]
            
            # Add any additional filters
            if filters:
                for key, value in filters.items():
                    if isinstance(value, bool):
                        filter_parts.append(f"{key} eq {str(value).lower()}")
                    elif isinstance(value, str):
                        filter_parts.append(f"{key} eq '{value}'")
            
            filter_expr = " and ".join(filter_parts)
            log_memory_debug(f"Searching with filter: {filter_expr}")

            # Vector search
            vector_queries = [{
                "kind": "vector",
                "vector": query_embedding,
                "fields": "interaction_vector",
                "k": top_k
            }]

            results = self.search_client.search(
                search_text="*",
                select=[
                    "id", "session_id", "agent_name", "outbound_payload", "inbound_payload", 
                    "processing_time_seconds", "timestamp"
                ],
                vector_queries=vector_queries,
                filter=filter_expr,
                top=top_k
            )

            return [dict(result) for result in results]

        except Exception as e:
            log_memory_debug(f"Error searching interactions: {str(e)}")
            return []

    def get_agent_interactions(self, agent_name: str, session_id: str = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent interactions for a specific agent with tenant isolation.
        
        Args:
            agent_name: The agent to get interactions for
            session_id: Required for multi-tenancy. Only returns results for this session.
            limit: Maximum number of results to return
        """
        if not self.search_client:
            return []
        
        # Validate session_id for multi-tenancy
        if not session_id:
            log_memory_debug("⚠️ No session_id provided - returning empty results (multi-tenancy required)")
            return []

        try:
            # Build filter with both session_id and agent_name for tenant isolation
            filter_expr = f"session_id eq '{session_id}' and agent_name eq '{agent_name}'"
            
            results = self.search_client.search(
                search_text="*",
                filter=filter_expr,
                select=["session_id", "outbound_payload", "inbound_payload", "processing_time_seconds", "timestamp"],
                order_by=["timestamp desc"],
                top=limit
            )
            
            return [dict(result) for result in results]

        except Exception as e:
            log_memory_debug(f"Error getting agent interactions: {str(e)}")
            return []

    def clear_all_interactions(self, session_id: str = None) -> bool:
        """Clear interactions from the search index with optional tenant isolation.
        
        Args:
            session_id: If provided, only clears interactions for this session.
                       If None, clears ALL interactions (admin operation).
        """
        if not self._enabled:
            log_memory_debug("Memory service disabled - skipping clear_all_interactions")
            return True  # Return success to avoid breaking the flow
        
        scope = f"session {session_id}" if session_id else "ALL sessions (global)"
        log_memory_debug(f"Clearing interactions from index {self.index_name} for {scope}")
        
        if not self.search_client:
            log_memory_debug("Search client not initialized")
            return False
        
        try:
            # Build filter for session-scoped clearing
            filter_expr = f"session_id eq '{session_id}'" if session_id else None
            
            # Get documents (filtered by session if provided)
            results = self.search_client.search(
                search_text="*", 
                select=["id"],
                filter=filter_expr
            )
            
            # Collect document IDs
            doc_ids = []
            for result in results:
                doc_ids.append(result["id"])
            
            if not doc_ids:
                log_memory_debug(f"No documents found to delete for {scope}")
                return True
            
            # Delete documents
            log_memory_debug(f"Deleting {len(doc_ids)} documents from index for {scope}")
            delete_actions = [{"@search.action": "delete", "id": doc_id} for doc_id in doc_ids]
            
            upload_result = self.search_client.upload_documents(documents=delete_actions)
            
            # Check results
            success_count = sum(1 for result in upload_result if result.succeeded)
            log_success(f"Successfully deleted {success_count}/{len(doc_ids)} documents for {scope}")
            
            return success_count == len(doc_ids)
            
        except Exception as e:
            log_memory_debug(f"Error clearing interactions: {str(e)}")
            import traceback
            log_memory_debug(f"Traceback: {traceback.format_exc()}")
            return False

    def get_processed_filenames(self, session_id: str) -> set:
        """Get all filenames that have been processed and stored in memory for a session.
        
        This is much faster than querying blob metadata for each file.
        Returns a set of filenames that are "in memory" (analyzed).
        """
        if not self.search_client or not session_id:
            return set()
        
        try:
            # Query all documents for this session
            filter_expr = f"session_id eq '{session_id}'"
            
            results = self.search_client.search(
                search_text="*",
                select=["inbound_payload"],
                filter=filter_expr,
                top=1000  # Should be more than enough for file count
            )
            
            filenames = set()
            for result in results:
                try:
                    inbound = result.get("inbound_payload", "{}")
                    if isinstance(inbound, str):
                        inbound = json.loads(inbound)
                    
                    # Extract filename from inbound_payload
                    filename = inbound.get("filename", "")
                    if filename:
                        filenames.add(filename)
                except (json.JSONDecodeError, AttributeError):
                    continue
            
            log_memory_debug(f"Found {len(filenames)} processed files in memory for session {session_id}")
            return filenames
            
        except Exception as e:
            log_memory_debug(f"Error getting processed filenames: {str(e)}")
            return set()

# Create singleton instance
a2a_memory_service = A2AMemoryService()