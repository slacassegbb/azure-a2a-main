import os
import json
from pathlib import Path
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

ROOT_ENV_PATH = Path('.').resolve().parent / '.env'
load_dotenv(dotenv_path=ROOT_ENV_PATH, override=False)

service_endpoint = os.getenv('AZURE_SEARCH_SERVICE_ENDPOINT')
admin_key = os.getenv('AZURE_SEARCH_ADMIN_KEY')
index_name = os.getenv('AZURE_SEARCH_INDEX_NAME', 'a2a-agent-interactions')

client = SearchClient(
    endpoint=service_endpoint,
    index_name=index_name,
    credential=AzureKeyCredential(admin_key)
)

# Search for invoice specifically
results = client.search(
    search_text='invoice OR Net Price USD OR VAT',
    filter="agent_name eq 'DocumentProcessor'",
    top=5
)

output = []
output.append(f"Searching for invoice documents")
output.append("")

count = 0
for doc in results:
    count += 1
    output.append(f'=== Document {count} ===')
    output.append(f"ID: {doc.get('id', 'N/A')}")
    output.append(f"Session: {doc.get('session_id', 'N/A')}")
    output.append(f"Timestamp: {doc.get('timestamp', 'N/A')}")
    
    outbound = doc.get('outbound_payload', '')
    try:
        outbound_json = json.loads(outbound)
        filename = outbound_json.get('filename', 'N/A')
        output.append(f"Filename: {filename}")
    except:
        output.append(f"Outbound ({len(outbound)} chars): {outbound[:200]}")
    
    inbound = doc.get('inbound_payload', '')
    output.append(f"Inbound length: {len(inbound)} chars")
    output.append("")
    
    # Parse the inbound JSON to get the actual content
    try:
        inbound_json = json.loads(inbound)
        content = inbound_json.get('content', '')
        output.append(f"=== EXTRACTED CONTENT ({len(content)} chars) ===")
        output.append(content)
    except:
        output.append("=== RAW INBOUND ===")
        output.append(inbound)
    
    output.append('')
    output.append('=' * 100)
    output.append('')

if count == 0:
    output.append("No invoice documents found")

# Write to file
with open('doc_output.txt', 'w') as f:
    f.write('\n'.join(output))

print(f"Output written to doc_output.txt ({count} documents found)")
print(f"Run: cat doc_output.txt | grep -A 50 'Net Price USD' to see invoice table")
