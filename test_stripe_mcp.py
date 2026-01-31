#!/usr/bin/env python3
"""Test Stripe MCP connection and list available tools."""

import asyncio
import json
import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

STRIPE_API_KEY = os.getenv("STRIPE_API_KEY", "")
if not STRIPE_API_KEY:
    raise ValueError("STRIPE_API_KEY environment variable is required")

async def test_stripe_mcp():
    """Connect to Stripe MCP and list tools."""
    
    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@stripe/mcp", "--tools=all", f"--api-key={STRIPE_API_KEY}"],
    )
    
    print("🔌 Connecting to Stripe MCP server...")
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the session
            await session.initialize()
            print("✅ Connected to Stripe MCP!\n")
            
            # List available tools
            tools = await session.list_tools()
            
            print(f"📦 Found {len(tools.tools)} Stripe tools:\n")
            for tool in tools.tools:
                print(f"  • {tool.name}")
                if tool.description:
                    # Truncate long descriptions
                    desc = tool.description[:80] + "..." if len(tool.description) > 80 else tool.description
                    print(f"    {desc}")
                print()
            
            # Try a simple read operation - list customers
            print("\n🧪 Testing: List Stripe customers...")
            try:
                result = await session.call_tool("list_customers", {"limit": 3})
                print(f"✅ Result: {result.content}")
            except Exception as e:
                print(f"⚠️ Test call result: {e}")

if __name__ == "__main__":
    asyncio.run(test_stripe_mcp())
