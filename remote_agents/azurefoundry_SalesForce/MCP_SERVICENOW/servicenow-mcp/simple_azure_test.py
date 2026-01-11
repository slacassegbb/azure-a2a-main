#!/usr/bin/env python3
"""
Simple test to check if Azure MCP server is responding
"""

import requests
import json

def test_azure_mcp_server():
    """Simple HTTP test of the Azure MCP server"""
    
    url = "https://servicenowmcp.purplebeach-9bf4f526.eastus2.azurecontainerapps.io/mcp/"
    
    print(f"Testing Azure MCP server at: {url}")
    
    try:
        # Test 1: Basic GET request
        print("\n1. Testing basic GET request...")
        response = requests.get(url, timeout=10)
        print(f"   Status Code: {response.status_code}")
        print(f"   Content-Type: {response.headers.get('content-type', 'Not set')}")
        print(f"   Response Length: {len(response.text)} characters")
        print(f"   First 200 chars: {response.text[:200]}")
        
        # Test 2: POST request to messages endpoint
        print("\n2. Testing POST to messages endpoint...")
        messages_url = url.replace("/mcp/", "/messages/")
        post_data = {
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
        
        response = requests.post(messages_url, json=post_data, timeout=10)
        print(f"   Status Code: {response.status_code}")
        print(f"   Response: {response.text[:500]}")
        
    except requests.exceptions.Timeout:
        print("❌ Timeout - server not responding")
    except requests.exceptions.ConnectionError:
        print("❌ Connection Error - cannot reach server")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_azure_mcp_server() 