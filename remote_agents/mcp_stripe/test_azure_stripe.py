#!/usr/bin/env python3
"""
Test the deployed Stripe MCP on Azure Container Apps.
"""

import asyncio
from mcp import ClientSession
from mcp.client.sse import sse_client


async def test_azure_stripe_mcp():
    """Test Stripe MCP running on Azure Container Apps."""
    print("="*60)
    print("Stripe MCP Azure Test")
    print("="*60)
    
    server_url = "https://mcp-stripe.ambitioussky-6c709152.westus2.azurecontainerapps.io/sse"
    
    print(f"\n🔌 Connecting to {server_url}...")
    
    try:
        async with sse_client(server_url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                print("✅ Connected to Stripe MCP on Azure!")
                
                # List tools
                tools_result = await session.list_tools()
                tools = tools_result.tools
                print(f"\n📦 Found {len(tools)} Stripe tools")
                
                # Test list_customers
                print("\n🧪 Testing: list_customers...")
                result = await session.call_tool("list_customers", {})
                print(f"✅ Result: {result.content}")
                
                # Test retrieve_balance
                print("\n🧪 Testing: retrieve_balance...")
                result = await session.call_tool("retrieve_balance", {})
                print(f"✅ Result: {result.content}")
                
                print("\n✅ All tests passed!")
                
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_azure_stripe_mcp())
