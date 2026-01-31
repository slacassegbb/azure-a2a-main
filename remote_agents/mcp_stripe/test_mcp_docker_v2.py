#!/usr/bin/env python3
"""
Test the Stripe MCP Docker container - keeps SSE connection alive.
"""

import asyncio
import httpx
import json


async def test_stripe_mcp():
    """Test Stripe MCP with persistent SSE connection."""
    print("="*60)
    print("Stripe MCP Docker Test (with persistent SSE)")
    print("="*60)
    
    base_url = "http://localhost:8031"
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Connect to SSE and keep it open
        print("\n1️⃣ Connecting to SSE endpoint...")
        
        async with client.stream("GET", f"{base_url}/sse") as sse_response:
            print(f"   SSE Status: {sse_response.status_code}")
            
            # Get the session URL from first event
            session_url = None
            line_count = 0
            async for line in sse_response.aiter_lines():
                line_count += 1
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data and "/message" in data:
                        session_url = f"{base_url}{data}"
                        print(f"   ✅ Session URL: {session_url}")
                        break
                if line_count > 5:
                    break
            
            if not session_url:
                print("   ❌ Failed to get session URL")
                return
            
            # Now send MCP requests while SSE is still connected
            print("\n2️⃣ Sending initialize request...")
            
            init_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0.0"}
                }
            }
            
            # Use a separate client for POST requests (same session)
            async with httpx.AsyncClient(timeout=30.0) as post_client:
                resp = await post_client.post(
                    session_url,
                    json=init_request,
                    headers={"Content-Type": "application/json"}
                )
                print(f"   Status: {resp.status_code}")
                if resp.status_code == 200 or resp.status_code == 202:
                    print(f"   ✅ Initialize successful!")
                    try:
                        data = resp.json()
                        if "result" in data:
                            server_info = data["result"].get("serverInfo", {})
                            print(f"   Server: {server_info.get('name', 'unknown')} v{server_info.get('version', '?')}")
                    except:
                        pass
                else:
                    print(f"   Response: {resp.text[:200]}")
                    return
                
                # Wait a moment for SSE to process
                await asyncio.sleep(0.5)
                
                # Read any SSE events that came back
                print("\n3️⃣ Listing available tools...")
                
                list_tools_request = {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {}
                }
                
                resp = await post_client.post(
                    session_url,
                    json=list_tools_request,
                    headers={"Content-Type": "application/json"}
                )
                print(f"   Status: {resp.status_code}")
                
                if resp.status_code == 200:
                    print(f"   ✅ Tools list request sent!")
                else:
                    print(f"   Response: {resp.text[:200]}")
                
                # Wait for SSE response
                await asyncio.sleep(0.5)
                
                # Read SSE events for tools response
                tools_found = False
                event_count = 0
                async for line in sse_response.aiter_lines():
                    event_count += 1
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if data:
                            try:
                                parsed = json.loads(data)
                                if "result" in parsed and "tools" in parsed["result"]:
                                    tools = parsed["result"]["tools"]
                                    print(f"   ✅ Found {len(tools)} tools:")
                                    for tool in tools[:8]:
                                        print(f"      • {tool.get('name', 'unknown')}")
                                    if len(tools) > 8:
                                        print(f"      ... and {len(tools) - 8} more")
                                    tools_found = True
                                    break
                            except json.JSONDecodeError:
                                pass
                    if event_count > 20:
                        break
                
                if not tools_found:
                    print("   ⚠️ Tools response not received via SSE")
                
                # Test calling list_customers
                print("\n4️⃣ Calling list_customers tool...")
                
                call_request = {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "list_customers",
                        "arguments": {}
                    }
                }
                
                resp = await post_client.post(
                    session_url,
                    json=call_request,
                    headers={"Content-Type": "application/json"}
                )
                print(f"   Status: {resp.status_code}")
                
                if resp.status_code == 200 or resp.status_code == 202:
                    print(f"   ✅ Tool call request sent!")
                
                # Read SSE for result
                await asyncio.sleep(1.0)
                result_found = False
                event_count = 0
                async for line in sse_response.aiter_lines():
                    event_count += 1
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if data:
                            try:
                                parsed = json.loads(data)
                                if parsed.get("id") == 3:  # Our call request
                                    if "result" in parsed:
                                        result = parsed["result"]
                                        print(f"   ✅ Tool executed successfully!")
                                        if "content" in result:
                                            for item in result["content"]:
                                                if item.get("type") == "text":
                                                    text = item.get("text", "")
                                                    print(f"   Result: {text[:200]}...")
                                        result_found = True
                                        break
                                    elif "error" in parsed:
                                        print(f"   ❌ Error: {parsed['error']}")
                                        result_found = True
                                        break
                            except json.JSONDecodeError:
                                pass
                    if event_count > 30:
                        break
                
                if not result_found:
                    print("   ⚠️ Result not received via SSE (may still be processing)")


if __name__ == "__main__":
    print("Stripe MCP Docker Container Test")
    print("="*60)
    asyncio.run(test_stripe_mcp())
    print("\n" + "="*60)
    print("✅ Test complete!")
    print("="*60)
