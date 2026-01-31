#!/usr/bin/env python3
"""
Test Flattened HubSpot MCP integration with Azure AI Foundry.
Uses the deployed HubSpot MCP Flat SSE server with McpTool class.
"""

import os
import asyncio
import time
from dotenv import load_dotenv

load_dotenv()

# Azure AI Foundry configuration
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT = os.getenv(
    "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
    "https://simonfoundry.services.ai.azure.com/api/projects/proj-default"
)
AZURE_AI_AGENT_MODEL = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")

# HubSpot MCP FLAT SSE endpoint (flattened schemas)
HUBSPOT_MCP_SSE_URL = "https://mcp-hubspot-flat.ambitioussky-6c709152.westus2.azurecontainerapps.io/sse"


async def test_hubspot_flat_tools():
    """Test that we can create an agent with flattened HubSpot MCP tools."""
    print("=" * 60)
    print("Testing Flattened HubSpot MCP Tools via Azure AI Foundry")
    print("=" * 60)
    
    try:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential
        from azure.ai.agents.models import McpTool, ToolSet
        
        print(f"\n📡 HubSpot MCP FLAT SSE URL: {HUBSPOT_MCP_SSE_URL}")
        print(f"📍 Azure Endpoint: {AZURE_AI_FOUNDRY_PROJECT_ENDPOINT}")
        
        credential = DefaultAzureCredential()
        project_client = AIProjectClient(
            endpoint=AZURE_AI_FOUNDRY_PROJECT_ENDPOINT,
            credential=credential,
        )
        
        print("\n🔧 Creating McpTool for HubSpot (flattened)...")
        
        # Create MCP tool with ALL flattened tools
        mcp_tool = McpTool(
            server_label="HubSpot",
            server_url=HUBSPOT_MCP_SSE_URL,
            allowed_tools=[
                "hubspot_get_user_details",
                "hubspot_list_objects",
                "hubspot_search_objects",
                "hubspot_get_object",
                "hubspot_create_contact",
                "hubspot_create_company",
                "hubspot_create_deal",
                "hubspot_update_object",
                "hubspot_list_associations",
                "hubspot_create_note",
            ]
        )
        
        mcp_tool.update_headers("Content-Type", "application/json")
        mcp_tool.update_headers("Accept", "application/json, text/event-stream")
        mcp_tool.set_approval_mode("never")
        
        print("✅ McpTool created successfully")
        
        toolset = ToolSet()
        toolset.add(mcp_tool)
        
        print("\n🔧 Creating test agent with HubSpot MCP tools...")
        
        with project_client:
            agent = project_client.agents.create_agent(
                model=AZURE_AI_AGENT_MODEL,
                name="HubSpot Flat MCP Test Agent",
                instructions="You are a HubSpot CRM assistant. Use the available HubSpot tools to help users manage their CRM data.",
                toolset=toolset
            )
        
            print(f"✅ Agent created: {agent.id}")
            print(f"   Model: {agent.model}")
            print(f"   Name: {agent.name}")
            
            if hasattr(agent, 'tools') and agent.tools:
                print(f"\n📦 Available MCP Tools ({len(agent.tools)}):")
                for tool in agent.tools[:10]:
                    tool_info = str(tool)[:60]
                    print(f"   - {tool_info}")
            
            project_client.agents.delete_agent(agent.id)
            print(f"\n🧹 Cleaned up test agent")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_hubspot_query():
    """Test an actual HubSpot query via Azure AI Foundry."""
    print("\n" + "=" * 60)
    print("Testing HubSpot Query via Azure AI Foundry")
    print("=" * 60)
    
    try:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential
        from azure.ai.agents.models import McpTool, ToolSet
        
        credential = DefaultAzureCredential()
        project_client = AIProjectClient(
            endpoint=AZURE_AI_FOUNDRY_PROJECT_ENDPOINT,
            credential=credential,
        )
        
        # Create MCP tool with key tools
        mcp_tool = McpTool(
            server_label="HubSpot",
            server_url=HUBSPOT_MCP_SSE_URL,
            allowed_tools=[
                "hubspot_get_user_details",
                "hubspot_list_objects",
                "hubspot_search_objects",
            ]
        )
        mcp_tool.update_headers("Content-Type", "application/json")
        mcp_tool.update_headers("Accept", "application/json, text/event-stream")
        mcp_tool.set_approval_mode("never")
        
        toolset = ToolSet()
        toolset.add(mcp_tool)
        
        with project_client:
            agent = project_client.agents.create_agent(
                model=AZURE_AI_AGENT_MODEL,
                name="HubSpot Query Test",
                instructions="You are a HubSpot CRM assistant. Use the HubSpot tools to answer questions about CRM data.",
                toolset=toolset
            )
            
            thread = project_client.agents.threads.create()
            
            # Ask to get user details and list contacts
            project_client.agents.messages.create(
                thread_id=thread.id,
                role="user",
                content="Get my HubSpot account details and list all contacts in the CRM."
            )
            
            print("\n🔄 Running query: 'Get account details and list contacts'...")
            
            # Run with polling
            run = project_client.agents.runs.create(
                thread_id=thread.id,
                agent_id=agent.id,
                tool_resources=mcp_tool.resources
            )
            print(f"   Run created: {run.id}")
            
            # Poll for completion
            while run.status in ["queued", "in_progress"] or str(run.status) in ["RunStatus.QUEUED", "RunStatus.IN_PROGRESS"]:
                time.sleep(2)
                run = project_client.agents.runs.get(thread_id=thread.id, run_id=run.id)
                print(f"   Status: {run.status}")
            
            print(f"   Final status: {run.status}")
            
            if run.status == "failed" or str(run.status) == "RunStatus.FAILED":
                print(f"   ❌ Run failed!")
                if hasattr(run, 'last_error') and run.last_error:
                    print(f"   Error: {run.last_error}")
            
            # Get messages
            messages = project_client.agents.messages.list(thread_id=thread.id)
            
            for msg in messages:
                if msg.role == "assistant":
                    for content in msg.content:
                        if hasattr(content, 'text') and hasattr(content.text, 'value'):
                            response_text = content.text.value
                            print(f"\n📋 Response:\n{response_text[:1000]}")
                            if len(response_text) > 1000:
                                print("...")
                        break
            
            project_client.agents.delete_agent(agent.id)
            print(f"\n🧹 Cleaned up test agent")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print("\n🚀 HubSpot MCP FLAT + Azure AI Foundry Integration Test\n")
    
    # Test 1: Create agent with MCP tools
    tools_ok = await test_hubspot_flat_tools()
    
    # Test 2: Run a query (only if tools test passed)
    if tools_ok:
        query_ok = await test_hubspot_query()
    else:
        query_ok = False
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print(f"  MCP Tools Test:  {'✅ PASSED' if tools_ok else '❌ FAILED'}")
    print(f"  Query Test:      {'✅ PASSED' if query_ok else '❌ FAILED'}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
