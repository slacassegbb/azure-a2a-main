#!/usr/bin/env python3
"""
Debug the running MCP server to understand its configuration
"""

import requests
import json

def debug_server():
    """Debug the running server to understand its configuration"""
    base_url = "http://127.0.0.1:8000"
    
    print("🔍 Debugging Running MCP Server")
    print("=" * 50)
    
    # Test various possible endpoints
    endpoints_to_test = [
        "/",
        "/mcp/",
        "/mcp",
        "/sse/",
        "/sse",
        "/health",
        "/status",
        "/docs",
        "/openapi.json",
        "/api/",
        "/api/mcp/",
        "/servicenow/",
    ]
    
    print("📡 Testing different endpoints...")
    working_endpoints = []
    
    for endpoint in endpoints_to_test:
        url = f"{base_url}{endpoint}"
        try:
            response = requests.get(url, timeout=3)
            status = response.status_code
            content_type = response.headers.get('content-type', 'unknown')
            
            if status == 200:
                print(f"✅ {endpoint} - Status: {status} - Type: {content_type}")
                working_endpoints.append(endpoint)
                if response.text and len(response.text) < 500:
                    print(f"   Content: {response.text}")
            elif status == 404:
                print(f"❌ {endpoint} - 404 Not Found")
            else:
                print(f"⚠️  {endpoint} - Status: {status} - Type: {content_type}")
                if response.text and len(response.text) < 200:
                    print(f"   Content: {response.text}")
                    
        except requests.exceptions.ConnectionError:
            print(f"🔌 {endpoint} - Connection refused")
        except requests.exceptions.Timeout:
            print(f"⏱️  {endpoint} - Timeout")
        except Exception as e:
            print(f"❌ {endpoint} - Error: {str(e)[:50]}")
    
    print(f"\n📊 Summary:")
    print(f"   Working endpoints: {len(working_endpoints)}")
    if working_endpoints:
        print(f"   Available: {', '.join(working_endpoints)}")
    
    # Check server headers for more info
    print(f"\n🔧 Server Information:")
    try:
        response = requests.get(base_url, timeout=3)
        headers = response.headers
        print(f"   Server: {headers.get('server', 'Unknown')}")
        print(f"   Date: {headers.get('date', 'Unknown')}")
        print(f"   Content-Type: {headers.get('content-type', 'Unknown')}")
        
        # Check if this is our FastMCP server
        if 'uvicorn' in headers.get('server', '').lower():
            print("   ✅ This appears to be a Uvicorn server (likely our MCP server)")
        
    except Exception as e:
        print(f"   ❌ Could not get server info: {e}")
    
    # Test if we can identify the MCP server type
    print(f"\n🏷️  Identifying Server Type:")
    
    # Look for FastMCP indicators
    print("   Checking for FastMCP indicators...")
    test_urls = [
        f"{base_url}/mcp/",
        f"{base_url}/",
    ]
    
    for test_url in test_urls:
        try:
            # Try POST with MCP-like payload
            response = requests.post(
                test_url,
                json={"test": "probe"},
                headers={'Content-Type': 'application/json'},
                timeout=3
            )
            print(f"   POST {test_url}: {response.status_code}")
            
            if response.status_code != 404:
                print(f"      Response: {response.text[:100]}...")
                
        except Exception as e:
            print(f"   POST {test_url}: Error - {str(e)[:50]}")
    
    print("\n" + "=" * 50)
    print("🤔 Analysis:")
    
    if not working_endpoints:
        print("❌ No working endpoints found")
        print("   This suggests the server might be:")
        print("   1. Running on a different port")
        print("   2. Using a different transport (not HTTP)")
        print("   3. Configured differently than expected")
    else:
        print("✅ Server is responding to some requests")
        print("   The 404 errors suggest the server is running but")
        print("   the MCP endpoints might be configured differently")
    
    print("\n💡 Recommendations:")
    print("   1. Check the server logs for any error messages")
    print("   2. Verify the server startup command and configuration")
    print("   3. The server might be using stdio transport instead of SSE")

if __name__ == "__main__":
    debug_server() 