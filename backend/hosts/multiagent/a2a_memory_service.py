from typing import List, Optional, Dict, Any
import os
import json
import uuid
from datetime import datetime
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
            SimpleField(name="agent_name", type=SearchFieldDataType.String),
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
        """Validate that an existing index matches the configured vector settings."""
        try:
            for field in index.fields:
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
                    return True
            log_memory_debug("interaction_vector field missing in index definition.")
            return False
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

    async def store_interaction(self, interaction_data: Dict[str, Any]) -> bool:
        """Store A2A protocol payloads in the search index"""
        if not self._enabled:
            log_memory_debug("Memory service disabled - skipping store_interaction")
            return True  # Return success to avoid breaking the flow
            
        log_memory_debug("store_interaction called")
        log_memory_debug(f"Agent name: {interaction_data.get('agent_name', 'unknown')}")
        
        if not self.search_client:
            log_memory_debug("Search client not initialized")
            return False

        try:
            log_memory_debug("Creating searchable text...")
            # Create searchable text for embedding from A2A payloads
            outbound_str = str(interaction_data.get('outbound_payload', ''))
            inbound_str = str(interaction_data.get('inbound_payload', ''))
            
            log_memory_debug(f"Outbound payload length: {len(outbound_str)}")
            log_memory_debug(f"Inbound payload length: {len(inbound_str)}")
            
            searchable_text = f"""
            Outbound A2A payload: {outbound_str}
            Inbound A2A payload: {inbound_str}
            Agent: {interaction_data.get('agent_name', '')}
            """
            
            log_memory_debug(f"Searchable text length: {len(searchable_text)}")
            log_memory_debug("About to create embedding...")

            # Create embedding
            embedding = await self._create_embedding(searchable_text.strip())
            log_memory_debug(f"Embedding created, length: {len(embedding)}")
            if not embedding:
                log_memory_debug("Failed to create embedding")
                return False
            if len(embedding) != vector_dimension:
                log_memory_debug(
                    f"Embedding dimension {len(embedding)} does not match configured vector dimension {vector_dimension}."
                )
                log_memory_debug("To resolve, set AZURE_SEARCH_VECTOR_DIMENSION to the embedding size and restart the service.")
                return False

            log_memory_debug("Preparing document for indexing...")
            # Prepare document for indexing
            document = {
                "id": interaction_data.get('interaction_id', str(uuid.uuid4())),
                "agent_name": interaction_data.get('agent_name', ''),
                "processing_time_seconds": interaction_data.get('processing_time_seconds', 0.0),
                "timestamp": interaction_data.get('timestamp', datetime.utcnow().isoformat() + 'Z'),
                
                "outbound_payload": json.dumps(interaction_data.get('outbound_payload', {})),
                "inbound_payload": json.dumps(interaction_data.get('inbound_payload', {})),
                
                "interaction_vector": embedding
            }
            
            log_memory_debug(f"Document prepared with ID: {document['id']}")
            log_memory_debug("About to upload to search index...")

            # Upload to search index
            self.search_client.upload_documents([document])
            log_success(f"Successfully stored A2A payloads {document['id']}")
            return True

        except Exception as e:
            log_memory_debug(f"Error storing A2A payloads: {str(e)}")
            return False

    async def search_similar_interactions(
        self, 
        query: str, 
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Search for similar interactions using semantic search"""
        if not self._enabled:
            log_memory_debug("Memory service disabled - returning empty results")
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

            # Build filter expression
            filter_expr = None
            if filters:
                filter_parts = []
                for key, value in filters.items():
                    if isinstance(value, bool):
                        filter_parts.append(f"{key} eq {str(value).lower()}")
                    elif isinstance(value, str):
                        filter_parts.append(f"{key} eq '{value}'")
                
                if filter_parts:
                    filter_expr = " and ".join(filter_parts)

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
                    "id", "agent_name", "outbound_payload", "inbound_payload", 
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

    def get_agent_interactions(self, agent_name: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent interactions for a specific agent"""
        if not self.search_client:
            return []

        try:
            results = self.search_client.search(
                search_text="*",
                filter=f"agent_name eq '{agent_name}'",
                select=["outbound_payload", "inbound_payload", "processing_time_seconds", "timestamp"],
                order_by=["timestamp desc"],
                top=limit
            )
            
            return [dict(result) for result in results]

        except Exception as e:
            log_memory_debug(f"Error getting agent interactions: {str(e)}")
            return []

    def clear_all_interactions(self) -> bool:
        """Clear all interactions from the search index"""
        if not self._enabled:
            log_memory_debug("Memory service disabled - skipping clear_all_interactions")
            return True  # Return success to avoid breaking the flow
            
        log_memory_debug(f"Clearing all interactions from index {self.index_name}")
        
        if not self.search_client:
            log_memory_debug("Search client not initialized")
            return False
        
        try:
            # Get all documents
            results = self.search_client.search(search_text="*", select=["id"])
            
            # Collect all document IDs
            doc_ids = []
            for result in results:
                doc_ids.append(result["id"])
            
            if not doc_ids:
                log_memory_debug("No documents found to delete")
                return True
            
            # Delete all documents
            log_memory_debug(f"Deleting {len(doc_ids)} documents from index")
            delete_actions = [{"@search.action": "delete", "id": doc_id} for doc_id in doc_ids]
            
            upload_result = self.search_client.upload_documents(documents=delete_actions)
            
            # Check results
            success_count = sum(1 for result in upload_result if result.succeeded)
            log_success(f"Successfully deleted {success_count}/{len(doc_ids)} documents")
            
            return success_count == len(doc_ids)
            
        except Exception as e:
            log_memory_debug(f"Error clearing interactions: {str(e)}")
            import traceback
            log_memory_debug(f"Traceback: {traceback.format_exc()}")
            return False

# Create singleton instance
a2a_memory_service = A2AMemoryService() 