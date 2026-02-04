"""
Script to inspect a specific document from Azure Search to see invoice data.
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

def inspect_invoice_documents():
    """Inspect documents containing 'invoice' keyword."""
    
    # Get Azure Search credentials
    search_endpoint = os.getenv('AZURE_SEARCH_SERVICE_ENDPOINT')
    search_key = os.getenv('AZURE_SEARCH_ADMIN_KEY')
    index_name = os.getenv('AZURE_SEARCH_INDEX_NAME', 'a2a-agent-interactions')
    
    if not search_endpoint or not search_key:
        print("ERROR: Missing AZURE_SEARCH_SERVICE_ENDPOINT or AZURE_SEARCH_ADMIN_KEY")
        return
    
    print(f"\n=== Inspecting Invoice Documents ===")
    print(f"Index: {index_name}")
    print(f"Endpoint: {search_endpoint}\n")
    
    # Create search client
    credential = AzureKeyCredential(search_key)
    search_client = SearchClient(
        endpoint=search_endpoint,
        index_name=index_name,
        credential=credential
    )
    
    # Search for documents containing "invoice"
    results = search_client.search(
        search_text="invoice",
        select=["id", "session_id", "agent_name", "inbound_payload", "outbound_payload", "timestamp"],
        top=5
    )
    
    count = 0
    for result in results:
        count += 1
        print(f"\n{'='*80}")
        print(f"Document #{count}")
        print(f"{'='*80}")
        print(f"ID: {result.get('id')}")
        print(f"Session: {result.get('session_id')}")
        print(f"Agent: {result.get('agent_name')}")
        print(f"Timestamp: {result.get('timestamp')}")
        
        # Parse inbound payload
        print(f"\n--- INBOUND PAYLOAD ---")
        inbound = result.get('inbound_payload', '{}')
        if isinstance(inbound, str):
            try:
                inbound_dict = json.loads(inbound)
                print(json.dumps(inbound_dict, indent=2))
            except:
                print(inbound[:500])
        else:
            print(inbound)
        
        # Parse outbound payload
        print(f"\n--- OUTBOUND PAYLOAD ---")
        outbound = result.get('outbound_payload', '{}')
        if isinstance(outbound, str):
            try:
                outbound_dict = json.loads(outbound)
                print(json.dumps(outbound_dict, indent=2))
            except:
                print(outbound[:500])
        else:
            print(outbound)
    
    if count == 0:
        print("No documents found containing 'invoice'")
    else:
        print(f"\n{'='*80}")
        print(f"Total documents inspected: {count}")
        print(f"{'='*80}")

if __name__ == "__main__":
    inspect_invoice_documents()
