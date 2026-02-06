import asyncio
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hosts.multiagent.core.a2a_memory_service import a2a_memory_service

async def main():
    print("✅ Initializing Azure Search...")
    
    # Initialize the memory service
    await a2a_memory_service.initialize()
    
    # Search for ALL entries (no query filter)
    session_id = "user_3"
    
    print(f"\n🔍 Searching for ALL memory entries for session {session_id}...")
    
    # Get the search client
    search_client = a2a_memory_service.search_client
    
    # Search with session filter only
    filter_expr = f"session_id eq '{session_id}'"
    results = search_client.search(
        search_text="*",
        filter=filter_expr,
        select=["agent_name", "timestamp", "outbound_payload", "inbound_payload"],
        top=50
    )
    
    entries = list(results)
    print(f"\n📊 Found {len(entries)} total memory entries\n")
    print("=" * 80)
    
    for i, entry in enumerate(entries, 1):
        agent_name = entry.get('agent_name', 'Unknown')
        timestamp = entry.get('timestamp', 'Unknown')
        
        # Check what type of entry this is
        inbound = entry.get('inbound_payload', '')
        outbound = entry.get('outbound_payload', '')
        
        # Determine entry type
        entry_type = "Unknown"
        preview = ""
        
        if isinstance(inbound, str):
            if '"content":' in inbound and 'DocumentProcessor' in agent_name:
                entry_type = "Document Content"
                # Extract preview
                import json
                try:
                    data = json.loads(inbound)
                    if 'content' in data:
                        preview = data['content'][:200] + "..."
                except:
                    preview = inbound[:200]
            else:
                entry_type = "Agent Conversation"
                preview = inbound[:200]
        
        print(f"�� Entry {i}: {agent_name}")
        print(f"   Type: {entry_type}")
        print(f"   Timestamp: {timestamp}")
        print(f"   Preview: {preview[:150]}...")
        print("-" * 80)

if __name__ == "__main__":
    asyncio.run(main())
