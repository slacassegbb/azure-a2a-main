#!/usr/bin/env python3
"""
Quick test to verify Azure MCP server connection
"""

import requests
import json

def test_azure_mcp():
    url = "https://servicenowmcp.purplebeach-9bf4f526.eastus2.azurecontainerapps.io/mcp/"
    
    print(f"Testing Azure MCP server at: {url}")
    
    try:
        # Test basic GET request
        print("\n1. Testing basic GET request...")
        response = requests.get(url, timeout=10)
        print(f"   Status Code: {response.status_code}")
        print(f"   Content-Type: {response.headers.get('content-type', 'Not set')}")
        
        if response.status_code == 200:
            print("   ✅ Server is responding!")
            
            # Test MCP initialization
            print("\n2. Testing MCP initialization...")
            init_data = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "test-client",
                        "version": "1.0.0"
                    }
                }
            }
            
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream'
            }
            
            response = requests.post(url, json=init_data, headers=headers, timeout=10)
            print(f"   Status Code: {response.status_code}")
            print(f"   Content-Type: {response.headers.get('content-type', 'Not set')}")
            
            if response.status_code == 200:
                print("   ✅ MCP initialization successful!")
                print(f"   Response preview: {response.text[:200]}...")
            else:
                print(f"   ❌ MCP initialization failed: {response.text}")
        else:
            print(f"   ❌ Server returned status {response.status_code}")
            
    except requests.exceptions.Timeout:
        print("❌ Timeout - server not responding")
    except requests.exceptions.ConnectionError:
        print("❌ Connection Error - cannot reach server")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_azure_mcp() 