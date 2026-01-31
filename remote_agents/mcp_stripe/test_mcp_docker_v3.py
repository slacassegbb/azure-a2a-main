#!/usr/bin/env python3
"""
Test Stripe MCP Docker container using the mcp library.
This is the most reliable way to test MCP servers.
"""

import asyncio
from mcp import ClientSession
from mcp.client.sse import sse_client


async def test_stripe_mcp_docker():
    """Test Stripe MCP running in Docker container."""
    print("="*60)
    print("Stripe MCP Docker Test (using mcp library)")
    print("="*60)
    
    # Docker container is running on port 8031
    server_url = "http://localhost:8031/sse"
    
    print(f"\n🔌 Connecting to {server_url}...")
    
    try:
        async with sse_client(server_url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                # Initialize the connection
                await session.initialize()
                print("✅ Connected to Stripe MCP!")
                
                # List available tools
                tools_result = await session.list_tools()
                tools = tools_result.tools
                print(f"\n📦 Found {len(tools)} Stripe tools:\n")
                
                for tool in tools:
                    desc = (tool.description or "")[:60].replace('\n', ' ')
                    print(f"  • {tool.name}")
                    print(f"    {desc}...")
                    print()
                
                # Test: Call list_customers
                print("\n🧪 Testing: List Stripe customers...")
                result = await session.call_tool("list_customers", {})
                print(f"✅ Result: {result.content}")
                
                # Test: Get balance
                print("\n🧪 Testing: Retrieve balance...")
                try:
                    result = await session.call_tool("retrieve_balance", {})
                    print(f"✅ Result: {result.content}")
                except Exception as e:
                    print(f"⚠️ Balance error: {e}")
                
                # Test: List products
                print("\n🧪 Testing: List products...")
                try:
                    result = await session.call_tool("list_products", {})
                    print(f"✅ Result: {result.content}")
                except Exception as e:
                    print(f"⚠️ Products error: {e}")
                
    except Exception as e:
        print(f"❌ Connection error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("Stripe MCP Docker Container Test")
    print("="*60)
    asyncio.run(test_stripe_mcp_docker())
    print("\n" + "="*60)
    print("✅ Test complete!")
