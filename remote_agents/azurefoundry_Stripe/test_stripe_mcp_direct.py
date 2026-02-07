"""
Direct test of Stripe MCP server to understand its protocol.
Testing both direct POST and session-based approaches.
"""
import asyncio
import httpx
import json

STRIPE_MCP_URL = "https://mcp-stripe.ambitioussky-6c709152.westus2.azurecontainerapps.io"

async def test_direct_post():
    """Test direct POST to /sse endpoint (QuickBooks style)."""
    print("\n" + "="*80)
    print("TEST 1: Direct POST to /sse (QuickBooks pattern)")
    print("="*80)
    
    request_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "retrieve_balance",
            "arguments": {}
        }
    }
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "Test-Client"
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{STRIPE_MCP_URL}/sse",
                json=request_payload,
                headers=headers
            )
            print(f"Status: {response.status_code}")
            print(f"Response: {response.text[:500]}")
    except Exception as e:
        print(f"❌ Error: {e}")

async def test_session_based():
    """Test session-based approach (connect to /sse, then POST to /message)."""
    print("\n" + "="*80)
    print("TEST 2: Session-based (GET /sse for session, POST /message)")
    print("="*80)
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1: Connect to /sse to establish session
            print("\n📡 Step 1: Connecting to /sse to get session ID...")
            
            headers = {"Accept": "text/event-stream"}
            
            async with client.stream("GET", f"{STRIPE_MCP_URL}/sse", headers=headers) as response:
                print(f"   Status: {response.status_code}")
                
                # Read initial SSE events to get session info
                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    print(f"   Received chunk: {chunk[:200]}")
                    
                    # Look for session ID in the stream
                    if "session" in buffer.lower() or len(buffer) > 500:
                        break
                
                print(f"   Buffer content: {buffer[:500]}")
                
    except Exception as e:
        print(f"❌ Error: {e}")

async def test_message_endpoint():
    """Test POST to /message endpoint directly."""
    print("\n" + "="*80)
    print("TEST 3: Direct POST to /message endpoint")
    print("="*80)
    
    request_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "retrieve_balance",
            "arguments": {}
        }
    }
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{STRIPE_MCP_URL}/message",
                json=request_payload,
                headers=headers
            )
            print(f"Status: {response.status_code}")
            print(f"Response: {response.text[:500]}")
    except Exception as e:
        print(f"❌ Error: {e}")

async def test_list_tools():
    """Test if we can list available tools."""
    print("\n" + "="*80)
    print("TEST 4: List available tools")
    print("="*80)
    
    request_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {}
    }
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try POST to /sse
            response = await client.post(
                f"{STRIPE_MCP_URL}/sse",
                json=request_payload,
                headers=headers
            )
            print(f"📡 POST /sse - Status: {response.status_code}")
            print(f"   Response: {response.text[:500]}")
    except Exception as e:
        print(f"❌ Error: {e}")

async def test_initialize():
    """Test initialization handshake."""
    print("\n" + "="*80)
    print("TEST 5: MCP Initialize handshake")
    print("="*80)
    
    request_payload = {
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
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{STRIPE_MCP_URL}/sse",
                json=request_payload,
                headers=headers
            )
            print(f"Status: {response.status_code}")
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")

async def main():
    """Run all tests."""
    print("\n🧪 TESTING STRIPE MCP SERVER PROTOCOL")
    print("Server URL:", STRIPE_MCP_URL)
    
    await test_direct_post()
    await test_session_based()
    await test_message_endpoint()
    await test_list_tools()
    await test_initialize()
    
    print("\n" + "="*80)
    print("✅ ALL TESTS COMPLETED")
    print("="*80)

if __name__ == "__main__":
    asyncio.run(main())
