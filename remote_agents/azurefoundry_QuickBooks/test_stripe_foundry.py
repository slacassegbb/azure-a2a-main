#!/usr/bin/env python3
"""
Test Stripe MCP integration with Azure AI Foundry.
Uses the official Stripe MCP server to verify Foundry can call Stripe tools.
"""

import os
from dotenv import load_dotenv

load_dotenv()

from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import McpTool, ToolSet
from azure.identity import DefaultAzureCredential

# Your Stripe test API key - set via environment variable STRIPE_API_KEY
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY", "")
if not STRIPE_API_KEY:
    raise ValueError("STRIPE_API_KEY environment variable is required")


def test_stripe_hosted_mcp():
    """Test with Stripe MCP deployed on Azure Container Apps."""
    print("\n" + "="*60)
    print("TEST 1: Stripe MCP via Azure Container Apps")
    print("="*60)
    
    project_client = AIProjectClient(
        credential=DefaultAzureCredential(),
        endpoint=os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"],
    )
    
    # Azure Container Apps deployed Stripe MCP
    mcp_url = "https://mcp-stripe.ambitioussky-6c709152.westus2.azurecontainerapps.io/sse"
    
    mcp_tool = McpTool(
        server_label="Stripe",
        server_url=mcp_url,
        # Stripe MCP tools
        allowed_tools=[
            "list_customers",
            "create_customer",
            "list_products",
            "list_invoices",
            "list_payment_intents",
            "retrieve_balance",
        ]
    )
    mcp_tool.set_approval_mode("never")
    # Add Stripe API key as Bearer token
    mcp_tool.update_headers("Authorization", f"Bearer {STRIPE_API_KEY}")
    mcp_tool.update_headers("Accept", "application/json, text/event-stream")
    
    toolset = ToolSet()
    toolset.add(mcp_tool)
    
    print(f"MCP Tool created: {mcp_tool.server_label}")
    print(f"MCP URL: {mcp_url}")
    print(f"API Key: {STRIPE_API_KEY[:20]}...{STRIPE_API_KEY[-4:]}")
    
    with project_client:
        agent = project_client.agents.create_agent(
            model="gpt-4o",
            name="test-stripe-agent",
            instructions="You are a Stripe payment assistant. Use the Stripe tools to help users manage payments, customers, and invoices.",
            toolset=toolset
        )
        print(f"✅ Agent created: {agent.id}")
        
        thread = project_client.agents.threads.create()
        print(f"✅ Thread created: {thread.id}")
        
        project_client.agents.messages.create(
            thread_id=thread.id,
            role="user",
            content="List all customers in my Stripe account"
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
        max_wait = 60
        waited = 0
        while run.status in ["queued", "in_progress"] and waited < max_wait:
            time.sleep(2)
            waited += 2
            run = project_client.agents.runs.get(thread_id=thread.id, run_id=run.id)
            print(f"  Status: {run.status} ({waited}s)")
        
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
        else:
            print(f"⚠️ Run ended with status: {run.status}")
        
        # Cleanup
        project_client.agents.delete_agent(agent.id)
        print("✅ Cleanup done")


def test_stripe_balance():
    """Test simple balance retrieval to verify connection."""
    print("\n" + "="*60)
    print("TEST 2: Stripe Balance Check (Simple Test)")
    print("="*60)
    
    project_client = AIProjectClient(
        credential=DefaultAzureCredential(),
        endpoint=os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"],
    )
    
    # Use our Azure Container Apps deployment (not Stripe's OAuth-only hosted MCP)
    mcp_url = "https://mcp-stripe.ambitioussky-6c709152.westus2.azurecontainerapps.io/sse"
    
    mcp_tool = McpTool(
        server_label="Stripe",
        server_url=mcp_url,
        allowed_tools=["retrieve_balance"]
    )
    mcp_tool.set_approval_mode("never")
    mcp_tool.update_headers("Authorization", f"Bearer {STRIPE_API_KEY}")
    mcp_tool.update_headers("Accept", "application/json, text/event-stream")
    
    toolset = ToolSet()
    toolset.add(mcp_tool)
    
    with project_client:
        agent = project_client.agents.create_agent(
            model="gpt-4o",
            name="test-stripe-balance",
            instructions="You are a Stripe assistant. When asked about balance, use retrieve_balance tool.",
            toolset=toolset
        )
        print(f"✅ Agent created: {agent.id}")
        
        thread = project_client.agents.threads.create()
        print(f"✅ Thread created: {thread.id}")
        
        project_client.agents.messages.create(
            thread_id=thread.id,
            role="user",
            content="What is my current Stripe balance?"
        )
        print("✅ Message sent")
        
        run = project_client.agents.runs.create(
            thread_id=thread.id,
            agent_id=agent.id,
            tool_resources=mcp_tool.resources
        )
        print(f"Run created: {run.id}, status: {run.status}")
        
        import time
        max_wait = 60
        waited = 0
        while run.status in ["queued", "in_progress"] and waited < max_wait:
            time.sleep(2)
            waited += 2
            run = project_client.agents.runs.get(thread_id=thread.id, run_id=run.id)
            print(f"  Status: {run.status} ({waited}s)")
        
        if run.status == "failed":
            print(f"❌ FAILED: {run.last_error}")
        elif run.status == "completed":
            print("✅ RUN COMPLETED!")
            messages = project_client.agents.messages.list(thread_id=thread.id)
            for msg in messages:
                if msg.role == "assistant":
                    for content in msg.content:
                        if hasattr(content, 'text'):
                            print(f"Response: {content.text.value}")
        else:
            print(f"⚠️ Run ended with status: {run.status}")
        
        project_client.agents.delete_agent(agent.id)
        print("✅ Cleanup done")


if __name__ == "__main__":
    print("Azure AI Foundry + Stripe MCP Integration Test")
    print("="*60)
    print(f"Testing with Stripe API key: {STRIPE_API_KEY[:20]}...")
    
    # Test 1: List customers
    try:
        test_stripe_hosted_mcp()
    except Exception as e:
        print(f"❌ Test 1 failed with exception: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 2: Check balance
    try:
        test_stripe_balance()
    except Exception as e:
        print(f"❌ Test 2 failed with exception: {e}")
        import traceback
        traceback.print_exc()
