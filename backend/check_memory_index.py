"""
Script to check what files are stored in the Azure Search memory index.
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

def check_memory_index(session_id: str = None):
    """Check what documents are in the memory index."""
    
    # Get Azure Search credentials
    search_endpoint = os.getenv('AZURE_SEARCH_SERVICE_ENDPOINT')
    search_key = os.getenv('AZURE_SEARCH_ADMIN_KEY')
    index_name = os.getenv('AZURE_SEARCH_INDEX_NAME', 'a2a-agent-interactions')
    
    if not search_endpoint or not search_key:
        print("ERROR: Missing AZURE_SEARCH_SERVICE_ENDPOINT or AZURE_SEARCH_ADMIN_KEY")
        return
    
    print(f"\n=== Checking Azure Search Index: {index_name} ===")
    print(f"Endpoint: {search_endpoint}")
    
    # Create search client
    credential = AzureKeyCredential(search_key)
    search_client = SearchClient(
        endpoint=search_endpoint,
        index_name=index_name,
        credential=credential
    )
    
    # Query parameters
    if session_id:
        filter_expr = f"session_id eq '{session_id}'"
        print(f"Filtering by session_id: {session_id}")
    else:
        filter_expr = None
        print("Showing all documents (no session filter)")
    
    # Search for all documents
    results = search_client.search(
        search_text="*",
        select=["id", "session_id", "inbound_payload", "timestamp"],
        filter=filter_expr,
        top=1000,
        include_total_count=True
    )
    
    # Group documents by filename
    files_by_session = {}
    total_count = 0
    
    for result in results:
        total_count += 1
        sess_id = result.get("session_id", "unknown")
        
        if sess_id not in files_by_session:
            files_by_session[sess_id] = {}
        
        try:
            inbound = result.get("inbound_payload", "{}")
            if isinstance(inbound, str):
                inbound = json.loads(inbound)
            
            filename = inbound.get("filename", "unknown")
            
            if filename not in files_by_session[sess_id]:
                files_by_session[sess_id][filename] = {
                    "chunks": 0,
                    "doc_ids": []
                }
            
            files_by_session[sess_id][filename]["chunks"] += 1
            files_by_session[sess_id][filename]["doc_ids"].append(result["id"])
            
        except (json.JSONDecodeError, AttributeError) as e:
            print(f"Warning: Could not parse document {result.get('id')}: {e}")
    
    # Print results
    print(f"\n=== Total Documents: {total_count} ===\n")
    
    for sess_id, files in files_by_session.items():
        print(f"\nSession: {sess_id[:16]}...")
        print(f"Files: {len(files)}")
        
        for filename, info in files.items():
            print(f"  - {filename}: {info['chunks']} chunks")
            if info['chunks'] <= 5:  # Show doc IDs if there are few chunks
                for doc_id in info['doc_ids']:
                    print(f"      ID: {doc_id}")
    
    print("\n" + "="*60)
    
    # Search for invoice specifically
    print("\n=== Searching for 'invoice' ===")
    invoice_results = search_client.search(
        search_text="invoice",
        select=["id", "session_id", "inbound_payload", "outbound_payload"],
        filter=filter_expr,
        top=10
    )
    
    invoice_count = 0
    for result in invoice_results:
        invoice_count += 1
        try:
            inbound = result.get("inbound_payload", "{}")
            if isinstance(inbound, str):
                inbound = json.loads(inbound)
            
            filename = inbound.get("filename", "unknown")
            outbound = result.get("outbound_payload", "")
            if isinstance(outbound, str) and outbound:
                try:
                    outbound = json.loads(outbound)
                    content_preview = outbound.get("message_payload", {}).get("content", "")[:100]
                except:
                    content_preview = outbound[:100]
            else:
                content_preview = ""
            
            print(f"\n  Match #{invoice_count}:")
            print(f"    Session: {result.get('session_id', 'unknown')[:16]}...")
            print(f"    File: {filename}")
            print(f"    Content: {content_preview}...")
            
        except Exception as e:
            print(f"    Error parsing result: {e}")
    
    if invoice_count == 0:
        print("  No documents found containing 'invoice'")
    
    print("\n" + "="*60)

if __name__ == "__main__":
    # Get session ID from command line or use None for all sessions
    session_id = sys.argv[1] if len(sys.argv) > 1 else None
    check_memory_index(session_id)
