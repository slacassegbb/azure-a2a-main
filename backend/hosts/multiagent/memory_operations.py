"""
MemoryOperations - Memory search and artifact creation methods for FoundryHostAgent2.

This module contains methods related to:
- Searching relevant memory interactions
- Clearing memory index
- Creating memory artifacts for remote agents

These are extracted from foundry_agent_a2a.py to improve code organization.
The class is designed to be used as a mixin with FoundryHostAgent2.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Import logging utilities
import sys
from pathlib import Path
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from a2a.types import Artifact, DataPart

from .a2a_memory_service import a2a_memory_service
from utils.tenant import get_tenant_from_context


class MemoryOperations:
    """
    Mixin class providing memory service methods.
    
    This class is designed to be inherited by FoundryHostAgent2 along with
    other mixin classes. All methods use 'self' and expect the main class
    to have the required attributes.
    """

    async def _search_relevant_memory(self, query: str, context_id: str, agent_name: str = None, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search for relevant memory interactions to provide context to remote agents.
        
        Args:
            query: The search query
            context_id: The context ID for tenant-scoped search
            agent_name: Optional agent name to filter by
            top_k: Number of results to return
        """
        
        try:
            # Extract session_id for tenant isolation
            session_id = get_tenant_from_context(context_id)
            
            # Build filters if agent name is specified
            filters = {}
            if agent_name:
                filters["agent_name"] = agent_name
            
            # Search for similar interactions (tenant-scoped)
            memory_results = await a2a_memory_service.search_similar_interactions(
                query=query,
                session_id=session_id,
                filters=filters,
                top_k=top_k
            )
            
            return memory_results
            
        except Exception as e:
            return []

    def clear_memory_index(self, context_id: str = None) -> bool:
        """Clear stored interactions from the memory index.
        
        Args:
            context_id: If provided, only clear interactions for this session.
                       If None, clears ALL interactions (admin use only).
        """
        try:
            session_id = None
            if context_id:
                session_id = get_tenant_from_context(context_id)
            
            success = a2a_memory_service.clear_all_interactions(session_id=session_id)
            if success:
                return success
            else:
                return False
        except Exception as e:
            return False

    async def _create_memory_artifact(self, memory_results: List[Dict[str, Any]], query: str) -> Optional[Artifact]:
        """Create a memory artifact from search results to send to remote agents"""
        if not memory_results:
            return None
            
        try:
            print(f"Creating memory artifact from {len(memory_results)} interactions")
            
            # Process memory results into structured format
            session_timeline = []
            agent_patterns = {}
            file_references = []
            related_interactions = []
            
            for result in memory_results:
                try:
                    # Parse the stored JSON payloads
                    outbound_payload = json.loads(result.get('outbound_payload', '{}'))
                    inbound_payload = json.loads(result.get('inbound_payload', '{}'))
                    
                    agent_name = result.get('agent_name', 'unknown')
                    timestamp = result.get('timestamp', '')
                    processing_time = result.get('processing_time_seconds', 0)
                    
                    # Extract interaction summary
                    interaction_summary = {
                        "timestamp": timestamp,
                        "agent_name": agent_name,
                        "processing_time_seconds": processing_time,
                        "interaction_type": "host_to_remote" if agent_name != "host_agent" else "user_to_host"
                    }
                    
                    # Extract user request from outbound payload
                    if outbound_payload.get('message', {}).get('parts'):
                        parts = outbound_payload['message']['parts']
                        text_parts = [p.get('text', '') for p in parts if p.get('text')]
                        if text_parts:
                            interaction_summary["user_request"] = text_parts[0][:200] + "..." if len(text_parts[0]) > 200 else text_parts[0]
                    
                    # Extract agent response from inbound payload
                    if inbound_payload.get('artifacts'):
                        artifacts = inbound_payload['artifacts']
                        for artifact in artifacts:
                            if artifact.get('parts'):
                                text_parts = [p.get('text', '') for p in artifact['parts'] if p.get('text')]
                                if text_parts:
                                    interaction_summary["agent_response"] = text_parts[0][:200] + "..." if len(text_parts[0]) > 200 else text_parts[0]
                                    break
                    
                    session_timeline.append(interaction_summary)
                    
                    # Track agent patterns
                    if agent_name not in agent_patterns:
                        agent_patterns[agent_name] = {
                            "interaction_count": 0,
                            "avg_processing_time": 0,
                            "common_requests": []
                        }
                    
                    agent_patterns[agent_name]["interaction_count"] += 1
                    agent_patterns[agent_name]["avg_processing_time"] = (
                        agent_patterns[agent_name]["avg_processing_time"] + processing_time
                    ) / 2
                    
                    # Extract file references
                    if outbound_payload.get('message', {}).get('parts'):
                        for part in outbound_payload['message']['parts']:
                            if part.get('file') and 'artifact_uri' in str(part.get('file', {})):
                                file_ref = {
                                    "timestamp": timestamp,
                                    "agent_name": agent_name,
                                    "file_info": part['file']
                                }
                                file_references.append(file_ref)
                    
                    # Store complete interaction for reference
                    related_interactions.append({
                        "timestamp": timestamp,
                        "agent_name": agent_name,
                        "outbound_summary": str(outbound_payload)[:500] + "...",
                        "inbound_summary": str(inbound_payload)[:500] + "..."
                    })
                    
                except Exception as e:
                    continue
            
            # Create the memory artifact data
            memory_data = {
                "search_query": query,
                "search_timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                "total_results": len(memory_results),
                "session_timeline": sorted(session_timeline, key=lambda x: x.get('timestamp', '')),
                "agent_patterns": agent_patterns,
                "file_references": file_references,
                "related_interactions": related_interactions[:3]  # Limit to top 3 most relevant
            }
            
            # Create the artifact
            memory_artifact = Artifact(
                name="relevant_memory",
                description=f"Historical context and patterns relevant to: {query}",
                parts=[
                    DataPart(data=memory_data)
                ]
            )
            
            print(f"✅ Created memory artifact with {len(session_timeline)} timeline entries")
            print(f"✅ Memory artifact includes {len(agent_patterns)} agent patterns")
            print(f"✅ Memory artifact includes {len(file_references)} file references")
            
            return memory_artifact
            
        except Exception as e:
            import traceback
            print(f"❌ Error creating memory artifact: {e}")
            print(f"❌ Traceback: {traceback.format_exc()}")
            return None
