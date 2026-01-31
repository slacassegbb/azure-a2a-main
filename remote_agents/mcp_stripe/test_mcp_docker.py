#!/usr/bin/env python3
"""
Test the Stripe MCP Docker container directly via SSE.
This verifies the MCP server is working before deploying to Azure.
"""

import asyncio
import httpx
import json


async def test_stripe_mcp_docker():
    """Test the Stripe MCP server running in Docker via SSE."""
    print("="*60)
    print("Testing Stripe MCP Docker Container (localhost:8031)")
    print("="*60)
    
    base_url = "http://localhost:8031"
    
    # Step 1: Connect to SSE and get session info
    print("\n1️⃣ Connecting to SSE endpoint...")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # First, connect to SSE to get session endpoint
        async with client.stream("GET", f"{base_url}/sse") as response:
            print(f"   SSE Status: {response.status_code}")
            
            # Read the first event which should give us the session URL
            session_url = None
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data:
                        print(f"   SSE Data: {data[:100]}...")
                        # Parse the endpoint URL
                        if "/message" in data or "endpoint" in data.lower():
                            session_url = data
                            break
                elif line.startswith("event:"):
                    event_type = line[6:].strip()
                    print(f"   Event: {event_type}")
                    if event_type == "endpoint":
                        continue  # Next line will be the data
                
                # Don't wait forever
                if session_url:
                    break
            
            if session_url:
                print(f"   ✅ Got session URL: {session_url}")
            else:
                print("   ⚠️ No session URL received yet, continuing...")


async def test_stripe_mcp_simple():
    """Simple test - just verify SSE connection works."""
    print("\n" + "="*60)
    print("Simple SSE Connection Test")
    print("="*60)
    
    import subprocess
    import time
    
    # Use curl to test SSE - it should show events
    print("\n📡 Testing SSE stream (5 seconds)...")
    try:
        result = subprocess.run(
            ["curl", "-s", "-N", "--max-time", "5", "http://localhost:8031/sse"],
            capture_output=True,
            text=True,
            timeout=10
        )
        output = result.stdout
        if output:
            print("   SSE Output:")
            for line in output.split('\n')[:10]:
                print(f"   {line}")
            print("   ✅ SSE stream is working!")
        else:
            print("   ⚠️ No output from SSE stream")
            print(f"   stderr: {result.stderr}")
    except subprocess.TimeoutExpired:
        print("   ⚠️ Timeout (expected for SSE streams)")
    except Exception as e:
        print(f"   ❌ Error: {e}")


async def test_mcp_initialize():
    """Test MCP initialize request via message endpoint."""
    print("\n" + "="*60)
    print("MCP Initialize Test")
    print("="*60)
    
    base_url = "http://localhost:8031"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Connect to SSE first to get session
        print("\n1️⃣ Connecting to SSE...")
        session_path = None
        
        try:
            async with client.stream("GET", f"{base_url}/sse") as response:
                async for line in response.aiter_lines():
                    if line.startswith("event: endpoint"):
                        continue
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if data and "/message" in data:
                            session_path = data
                            print(f"   ✅ Session path: {session_path}")
                            break
                    # Timeout after first few lines
                    if session_path:
                        break
        except Exception as e:
            print(f"   SSE connection: {e}")
        
        # Build full URL
        if session_path:
            session_url = f"{base_url}{session_path}"
        else:
            session_url = f"{base_url}/message"
        print(f"   Full URL: {session_url}")
        
        # Step 2: Send initialize request
        print("\n2️⃣ Sending MCP initialize request...")
        
        init_request = {
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
        
        try:
            resp = await client.post(
                session_url,
                json=init_request,
                headers={"Content-Type": "application/json"}
            )
            print(f"   Status: {resp.status_code}")
            if resp.status_code == 200 or resp.status_code == 202:
                print(f"   ✅ Initialize accepted!")
                print(f"   Response: {resp.text[:200]}...")
            else:
                print(f"   Response: {resp.text[:500]}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Step 3: List tools
        print("\n3️⃣ Listing available tools...")
        
        list_tools_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {}
        }
        
        try:
            resp = await client.post(
                session_url,
                json=list_tools_request,
                headers={"Content-Type": "application/json"}
            )
            print(f"   Status: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                if "result" in data and "tools" in data["result"]:
                    tools = data["result"]["tools"]
                    print(f"   ✅ Found {len(tools)} tools:")
                    for tool in tools[:5]:
                        print(f"      • {tool.get('name', 'unknown')}")
                    if len(tools) > 5:
                        print(f"      ... and {len(tools) - 5} more")
                else:
                    print(f"   Response: {resp.text[:300]}")
            else:
                print(f"   Response: {resp.text[:300]}")
        except Exception as e:
            print(f"   ❌ Error: {e}")


async def test_call_stripe_tool():
    """Actually call a Stripe tool via MCP."""
    print("\n" + "="*60)
    print("Call Stripe Tool Test (list_customers)")
    print("="*60)
    
    base_url = "http://localhost:8031"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Get session URL
        session_path = None
        try:
            async with client.stream("GET", f"{base_url}/sse") as response:
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if data and "/message" in data:
                            session_path = data
                            break
        except:
            pass
        
        # Build full URL
        if session_path:
            session_url = f"{base_url}{session_path}"
        else:
            session_url = f"{base_url}/message"
        
        print(f"   Using endpoint: {session_url}")
        
        # Initialize first
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"}
            }
        }
        await client.post(session_url, json=init_req)
        
        # Call list_customers
        print("\n📞 Calling list_customers tool...")
        
        call_req = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "list_customers",
                "arguments": {}
            }
        }
        
        try:
            resp = await client.post(session_url, json=call_req)
            print(f"   Status: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                if "result" in data:
                    result = data["result"]
                    print(f"   ✅ Tool executed successfully!")
                    # Pretty print the result
                    if isinstance(result, dict) and "content" in result:
                        for item in result.get("content", []):
                            if item.get("type") == "text":
                                text = item.get("text", "")
                                print(f"   Result: {text[:300]}...")
                    else:
                        print(f"   Result: {json.dumps(result, indent=2)[:300]}...")
                elif "error" in data:
                    print(f"   ❌ Error: {data['error']}")
                else:
                    print(f"   Response: {resp.text[:300]}")
            else:
                print(f"   Response: {resp.text[:300]}")
        except Exception as e:
            print(f"   ❌ Error: {e}")


if __name__ == "__main__":
    print("Stripe MCP Docker Container Test Suite")
    print("="*60)
    
    asyncio.run(test_stripe_mcp_simple())
    asyncio.run(test_mcp_initialize())
    asyncio.run(test_call_stripe_tool())
    
    print("\n" + "="*60)
    print("✅ Tests complete!")
    print("="*60)
