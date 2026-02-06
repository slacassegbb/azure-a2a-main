import asyncio
import os
import sys
import json

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hosts.multiagent.a2a_memory_service import a2a_memory_service

async def main():
    print("✅ Initializing Azure Search...")
    
    # Initialize the memory service
    await a2a_memory_service.initialize()
    
    session_id = "user_3"
    
    print(f"\n🔍 Searching Azure Cognitive Search for session: {session_id}\n")
    print("=" * 80)
    
    # Get the search client
    search_client = a2a_memory_service.search_client
    
    # Search with session filter only - get ALL entries
    filter_expr = f"session_id eq '{session_id}'"
    results = search_client.search(
        search_text="*",
        filter=filter_expr,
        select=["agent_name", "timestamp", "interaction_id", "outbound_payload", "inbound_payload"],
        top=100
    )
    
    entries = list(results)
    print(f"\n📊 TOTAL ENTRIES FOUND: {len(entries)}\n")
    print("=" * 80)
    
    if len(entries) == 0:
        print("\n✅ Memory is CLEAN - no entries found!")
        print("This means the 'Relevant context from previous interactions' is coming from")
        print("somewhere else (not Azure Cognitive Search memory)")
        return
    
    for i, entry in enumerate(entries, 1):
        agent_name = entry.get('agent_name', 'Unknown')
        timestamp = entry.get('timestamp', 'Unknown')
        interaction_id = entry.get('interaction_id', 'Unknown')
        
        print(f"\n📄 Entry {i}:")
        print(f"   Agent: {agent_name}")
        print(f"   Timestamp: {timestamp}")
        print(f"   ID: {interaction_id}")
        
        # Check what type of entry this is
        inbound = entry.get('inbound_payload', '')
        outbound = entry.get('outbound_payload', '')
        
        # Determine entry type
        if isinstance(inbound, str):
            try:
                inbound_data = json.loads(inbound)
            except:
                inbound_data = {}
        else:
            inbound_data = inbound
        
        # Check if it's a document or conversation
        if 'DocumentProcessor' in agent_name:
            entry_type = "📄 DOCUMENT CONTENT"
            if isinstance(inbound_data, dict) and 'content' in inbound_data:
                content_preview = inbound_data['content'][:200]
                print(f"   Type: {entry_type}")
                print(f"   Content Preview: {content_preview}...")
        else:
            entry_type = "💬 AGENT CONVERSATION"
            print(f"   Type: {entry_type}")
            print(f"   ⚠️  THIS SHOULD NOT BE HERE IF MEMORY IS DISABLED!")
            
            # Show what the conversation contains
            if isinstance(inbound_data, dict):
                if 'status' in inbound_data and 'message' in inbound_data['status']:
                    msg = inbound_data['status']['message']
                    if isinstance(msg, dict) and 'parts' in msg:
                        for part in msg['parts'][:1]:  # Just first part
                            if isinstance(part, dict) and 'text' in part:
                                print(f"   Preview: {part['text'][:150]}...")
        
        print("-" * 80)
    
    print(f"\n📊 SUMMARY:")
    print(f"   Total entries: {len(entries)}")
    doc_count = sum(1 for e in entries if 'DocumentProcessor' in e.get('agent_name', ''))
    conv_count = len(entries) - doc_count
    print(f"   Document entries: {doc_count}")
    print(f"   Conversation entries: {conv_count}")
    
    if conv_count > 0:
        print(f"\n⚠️  WARNING: {conv_count} conversation entries found in memory!")
        print("   These should NOT exist if conversation memory is disabled.")
        print("   This is the source of the 'Relevant context from previous interactions' text.")

if __name__ == "__main__":
    asyncio.run(main())
