#!/usr/bin/env python3
"""
Check the details of created incidents
"""

import asyncio
import json
from dotenv import load_dotenv
from fastmcp import Client

async def check_created_incident():
    """Create an incident and show the details for verification"""
    print("🔍 Creating Incident and Showing Details for ServiceNow Verification")
    print("=" * 70)
    
    try:
        async with Client("./mcp_server_servicenow/server.py") as client:
            print("✅ Connected to MCP server")
            
            # Create a new incident with specific details
            print("\n📝 Creating incident with specific details...")
            result = await client.call_tool(
                "create_incident",
                {
                    "short_description": "MCP Integration Test - Please Verify",
                    "description": "This incident was created via MCP server integration test. Created to verify the connection is working properly."
                }
            )
            
            if hasattr(result, 'content') and result.content:
                response_text = result.content[0].text
                print(f"\n✅ Incident Created Successfully!")
                print("=" * 50)
                
                try:
                    # Parse the JSON response
                    response_data = json.loads(response_text)
                    
                    if response_data.get("status") == "success":
                        incident_data = response_data.get("data", {})
                        metadata = response_data.get("metadata", {})
                        
                        print("🎫 INCIDENT DETAILS:")
                        print("-" * 30)
                        print(f"📋 Incident Number: {metadata.get('number', 'Not available')}")
                        print(f"🆔 System ID: {incident_data.get('sys_id', 'Not available')}")
                        print(f"📝 Short Description: {incident_data.get('short_description', 'Not available')}")
                        print(f"📄 Description: {incident_data.get('description', 'Not available')}")
                        print(f"⚠️  Priority: {incident_data.get('priority', 'Not available')}")
                        print(f"🔥 Urgency: {incident_data.get('urgency', 'Not available')}")
                        print(f"💥 Impact: {incident_data.get('impact', 'Not available')}")
                        print(f"📅 Created: {incident_data.get('sys_created_on', 'Not available')}")
                        print(f"👤 Created By: {incident_data.get('sys_created_by', 'Not available')}")
                        print(f"🔄 State: {incident_data.get('state', 'Not available')}")
                        
                        print("\n" + "=" * 50)
                        print("🌐 TO VERIFY IN SERVICENOW:")
                        print("-" * 30)
                        print(f"1. Go to: https://dev355156.service-now.com")
                        print(f"2. Navigate to: Incident > All")
                        print(f"3. Search for incident number: {metadata.get('number', 'N/A')}")
                        print(f"4. Or search by description: 'MCP Integration Test'")
                        
                        # Also search for the incident to confirm it exists
                        print(f"\n🔍 Verifying incident exists by searching...")
                        if metadata.get('number'):
                            search_result = await client.call_tool(
                                "search_records",
                                {
                                    "query": f"number={metadata.get('number')}",
                                    "table": "incident",
                                    "limit": 1
                                }
                            )
                            
                            if hasattr(search_result, 'content') and search_result.content:
                                search_text = search_result.content[0].text
                                if metadata.get('number') in search_text:
                                    print("✅ VERIFIED: Incident found in ServiceNow!")
                                else:
                                    print("⚠️  Could not verify incident in search results")
                            else:
                                print("⚠️  Search verification failed")
                    else:
                        print("❌ Incident creation failed")
                        print(f"Response: {response_text}")
                        
                except json.JSONDecodeError:
                    print("⚠️  Could not parse response as JSON")
                    print(f"Raw response: {response_text[:500]}...")
            else:
                print("❌ No response content received")
                
    except Exception as e:
        print(f"❌ Error: {str(e)}")

def main():
    load_dotenv()
    asyncio.run(check_created_incident())

if __name__ == "__main__":
    main() 