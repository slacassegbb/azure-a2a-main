#!/usr/bin/env python3
"""
Minimal test to verify Azure AI Foundry MCP integration works.
Uses Microsoft's public fetch MCP server to isolate any issues.
"""

import os
from dotenv import load_dotenv

load_dotenv()

from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import McpTool, ToolSet
from azure.identity import DefaultAzureCredential


def test_with_microsoft_public_server():
    """Test with Microsoft's public fetch MCP server."""
    print("\n" + "="*60)
    print("TEST 1: Microsoft's Public Fetch MCP Server")
    print("="*60)
    
    project_client = AIProjectClient(
        credential=DefaultAzureCredential(),
        endpoint=os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"],
    )
    
    # Use Microsoft's public fetch server
    mcp_tool = McpTool(
        server_label="fetch",
        server_url="https://mcp.azure-api.net/fetch",
        allowed_tools=["fetch"]
    )
    mcp_tool.set_approval_mode("never")
    
    toolset = ToolSet()
    toolset.add(mcp_tool)
    
    print(f"MCP Tool created: {mcp_tool.server_label}")
    print(f"MCP Tool resources: {mcp_tool.resources}")
    
    with project_client:
        agent = project_client.agents.create_agent(
            model="gpt-4o",
            name="test-fetch-agent",
            instructions="You are a helpful assistant that can fetch web pages.",
            toolset=toolset
        )
        print(f"✅ Agent created: {agent.id}")
        
        thread = project_client.agents.threads.create()
        print(f"✅ Thread created: {thread.id}")
        
        project_client.agents.messages.create(
            thread_id=thread.id,
            role="user",
            content="Fetch https://example.com and tell me what it says"
        )
        print("✅ Message sent")
        
        run = project_client.agents.runs.create(
            thread_id=thread.id,
            agent_id=agent.id,
            tool_resources=mcp_tool.resources
        )
        print(f"Run created: {run.id}, status: {run.status}")
        
        # Poll for completion
        import time
        while run.status in ["queued", "in_progress"]:
            time.sleep(1)
            run = project_client.agents.runs.get(thread_id=thread.id, run_id=run.id)
            print(f"  Status: {run.status}")
        
        if run.status == "failed":
            print(f"❌ FAILED: {run.last_error}")
        elif run.status == "completed":
            print("✅ RUN COMPLETED!")
            messages = project_client.agents.messages.list(thread_id=thread.id)
            for msg in messages:
                if msg.role == "assistant":
                    for content in msg.content:
                        if hasattr(content, 'text'):
                            print(f"Response: {content.text.value[:200]}...")
        
        # Cleanup
        project_client.agents.delete_agent(agent.id)
        print("✅ Cleanup done")


def test_with_quickbooks_server():
    """Test with QuickBooks MCP server via ngrok."""
    print("\n" + "="*60)
    print("TEST 2: QuickBooks MCP Server via ngrok")
    print("="*60)
    
    project_client = AIProjectClient(
        credential=DefaultAzureCredential(),
        endpoint=os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"],
    )
    
    mcp_url = "https://b216cb9d1f7a.ngrok-free.app/sse"
    
    mcp_tool = McpTool(
        server_label="QuickBooks",
        server_url=mcp_url,
        # ALL 15 tools - testing with simplified flat schemas!
        allowed_tools=[
            # Query & Reports
            "qbo_query",            # SQL-like queries
            "qbo_report",           # Financial reports
            "qbo_company_info",     # Company info
            # Customer Tools
            "qbo_search_customers", # Search customers
            "qbo_get_customer",     # Get customer by ID
            "qbo_create_customer",  # Create customers  
            "qbo_update_customer",  # Update customer
            "qbo_delete_customer",  # Deactivate customer
            # Invoice Tools
            "qbo_search_invoices",  # Search invoices
            "qbo_get_invoice",      # Get invoice by ID
            "qbo_create_invoice",   # Create invoices
            # Other Entity Tools
            "qbo_search_accounts",  # Search chart of accounts
            "qbo_search_items",     # Search products/services
            "qbo_search_vendors",   # Search vendors/suppliers
            "qbo_search_bills"      # Search bills/payables
        ]
    )
    mcp_tool.set_approval_mode("never")
    mcp_tool.update_headers("ngrok-skip-browser-warning", "true")
    mcp_tool.update_headers("Accept", "application/json, text/event-stream")
    
    toolset = ToolSet()
    toolset.add(mcp_tool)
    
    print(f"MCP Tool created: {mcp_tool.server_label}")
    print(f"MCP Tool resources: {mcp_tool.resources}")
    
    with project_client:
        agent = project_client.agents.create_agent(
            model="gpt-4o",
            name="test-qb-agent",
            instructions="You are a QuickBooks assistant. Use qbo_query with SQL-like syntax to search QuickBooks data. Example: SELECT * FROM Customer",
            toolset=toolset
        )
        print(f"✅ Agent created: {agent.id}")
        
        thread = project_client.agents.threads.create()
        print(f"✅ Thread created: {thread.id}")
        
        project_client.agents.messages.create(
            thread_id=thread.id,
            role="user",
            content="Run qbo_company_info to get company details"
        )
        print("✅ Message sent")
        
        run = project_client.agents.runs.create(
            thread_id=thread.id,
            agent_id=agent.id,
            tool_resources=mcp_tool.resources
        )
        print(f"Run created: {run.id}, status: {run.status}")
        
        # Poll for completion
        import time
        while run.status in ["queued", "in_progress"]:
            time.sleep(1)
            run = project_client.agents.runs.get(thread_id=thread.id, run_id=run.id)
            print(f"  Status: {run.status}")
        
        if run.status == "failed":
            print(f"❌ FAILED: {run.last_error}")
        elif run.status == "completed":
            print("✅ RUN COMPLETED!")
            messages = project_client.agents.messages.list(thread_id=thread.id)
            for msg in messages:
                if msg.role == "assistant":
                    for content in msg.content:
                        if hasattr(content, 'text'):
                            print(f"Response: {content.text.value[:500]}...")
        
        # Cleanup
        project_client.agents.delete_agent(agent.id)
        print("✅ Cleanup done")


if __name__ == "__main__":
    print("Azure AI Foundry MCP Integration Test")
    print("="*60)
    
    # Test 1: Microsoft's public server (to verify MCP works at all)
    try:
        test_with_microsoft_public_server()
    except Exception as e:
        print(f"❌ Test 1 failed with exception: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 2: Your QuickBooks server
    try:
        test_with_quickbooks_server()
    except Exception as e:
        print(f"❌ Test 2 failed with exception: {e}")
        import traceback
        traceback.print_exc()
