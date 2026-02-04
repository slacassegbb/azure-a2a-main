"""
Script to list all files stored in memory for a specific session.
"""
import os
import sys
import json
from pathlib import Path

# Add the backend directory to the path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential

def list_session_files(session_id: str):
    """List all files stored in memory for a session."""
    
    # Get Azure Search credentials
    search_endpoint = os.getenv('AZURE_SEARCH_SERVICE_ENDPOINT')
    search_key = os.getenv('AZURE_SEARCH_ADMIN_KEY')
    index_name = os.getenv('AZURE_SEARCH_INDEX_NAME', 'a2a-agent-interactions')
    
    if not search_endpoint or not search_key:
        print("ERROR: Missing AZURE_SEARCH_SERVICE_ENDPOINT or AZURE_SEARCH_ADMIN_KEY")
        return
    
    print(f"\n=== Files in Memory for Session: {session_id} ===\n")
    
    # Create search client
    credential = AzureKeyCredential(search_key)
    search_client = SearchClient(
        endpoint=search_endpoint,
        index_name=index_name,
        credential=credential
    )
    
    # Query all documents for this session
    filter_expr = f"session_id eq '{session_id}'"
    
    results = search_client.search(
        search_text="*",
        select=["id", "agent_name", "inbound_payload", "timestamp"],
        filter=filter_expr,
        top=1000
    )
    
    # Group by filename
    files_found = {}
    total_docs = 0
    
    for result in results:
        total_docs += 1
        try:
            inbound = result.get("inbound_payload", "{}")
            if isinstance(inbound, str):
                inbound = json.loads(inbound)
            
            filename = inbound.get("filename", None)
            agent = result.get("agent_name", "unknown")
            timestamp = result.get("timestamp", "")
            
            if filename:
                if filename not in files_found:
                    files_found[filename] = {
                        "count": 0,
                        "agent": agent,
                        "first_seen": timestamp,
                        "doc_ids": []
                    }
                files_found[filename]["count"] += 1
                files_found[filename]["doc_ids"].append(result["id"])
        
        except Exception as e:
            pass
    
    print(f"Total documents in session: {total_docs}")
    print(f"Documents with filenames: {sum(f['count'] for f in files_found.values())}")
    print(f"Unique files: {len(files_found)}\n")
    
    if files_found:
        print("Files found in memory:\n")
        for filename, info in sorted(files_found.items()):
            print(f"  📄 {filename}")
            print(f"      Chunks: {info['count']}")
            print(f"      Agent: {info['agent']}")
            print(f"      First seen: {info['first_seen']}")
            if info['count'] <= 3:
                print(f"      Doc IDs:")
                for doc_id in info['doc_ids']:
                    print(f"        - {doc_id}")
            print()
    else:
        print("No files found in memory for this session.")
    
    print("="*80)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python list_session_files.py <session_id>")
        print("\nExample: python list_session_files.py user_3")
        sys.exit(1)
    
    session_id = sys.argv[1]
    list_session_files(session_id)
