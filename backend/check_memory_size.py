#!/usr/bin/env python3
"""Check the size of content stored in memory index."""
import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(__file__))

from hosts.multiagent.a2a_memory_service import a2a_memory_service

async def check_memory():
    """Check memory entries for a session."""
    # Search for invoice-related content
    results = await a2a_memory_service.search_similar_interactions(
        query='invoice',
        session_id='user_3',
        top_k=10
    )
    
    print(f'\n🔍 Found {len(results)} memory entries for session user_3')
    print('='*80)
    
    total_chars = 0
    
    for i, result in enumerate(results, 1):
        agent_name = result.get('agent_name', 'Unknown')
        timestamp = result.get('timestamp', 'Unknown')
        
        # Get content from inbound payload
        inbound = result.get('inbound_payload', '')
        if isinstance(inbound, str):
            import json
            try:
                inbound = json.loads(inbound)
            except:
                pass
        
        if isinstance(inbound, dict) and 'content' in inbound:
            content = inbound['content']
            char_count = len(content)
            total_chars += char_count
            
            print(f'\n📄 Entry {i}: {agent_name}')
            print(f'   Timestamp: {timestamp}')
            print(f'   Size: {char_count:,} characters')
            print(f'   First 300 chars:')
            print(f'   {content[:300]}...')
            print('-'*80)
    
    print(f'\n📊 TOTAL: {total_chars:,} characters across {len(results)} entries')
    print(f'   Estimated tokens: ~{total_chars // 4:,} tokens (rough estimate)')

if __name__ == '__main__':
    asyncio.run(check_memory())
