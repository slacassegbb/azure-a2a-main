#!/usr/bin/env python3
"""
Test script for Azure Foundry Claims Specialist Agent self-registration

This script tests the self-registration functionality for the Azure AI Foundry
claims specialist agent to ensure it can automatically register with the host agent.

Usage:
    python test_self_registration.py
"""

import asyncio
import logging
import os
import sys
from utils.self_registration import register_with_host_agent
from a2a.types import AgentCard, AgentCapabilities, AgentSkill

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_HOST = 'localhost'
DEFAULT_PORT = 9001


def create_test_agent_card(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> AgentCard:
    """Create a test agent card for registration testing."""
    skills = [
        AgentSkill(
            id='auto_claims_assessment',
            name='Auto Claims Assessment',
            description="Evaluate auto coverage, deductibles, and rental benefits using auto_claims.md guidance.",
            tags=['auto', 'claims', 'settlement'],
            examples=[
                'Vehicle collision with $5,000 in damage',
                'Rental reimbursement question during repairs',
                'Total loss evaluation after theft'
            ],
        ),
        AgentSkill(
            id='claims_documentation_compliance',
            name='Documentation & Compliance',
            description="Provide required forms, regulatory timelines, and fraud indicators using claims reference guides.",
            tags=['documentation', 'compliance', 'fraud'],
            examples=[
                'Checklist for water damage claim',
                'Escalation steps for suspected fraud',
                'Regulatory timeline for claim denials'
            ],
        )
    ]

    return AgentCard(
        name='AI Foundry Claims Specialist Agent',
        description="An intelligent multi-line claims specialist powered by Azure AI Foundry for coverage validation, settlement estimates, and compliance guidance.",
        url=f'http://{host}:{port}/',
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities=AgentCapabilities(streaming=True),
        skills=skills,
    )

async def test_self_registration():
    """Test the self-registration functionality."""
    print("🧪 Testing Azure Foundry Claims Specialist Agent Self-Registration")
    print("=" * 60)
    
    # Test configuration
    host_agent_url = os.getenv('A2A_HOST_AGENT_URL', 'http://localhost:12000')
    agent_host = os.getenv('AGENT_HOST', DEFAULT_HOST)
    agent_port = int(os.getenv('AGENT_PORT', DEFAULT_PORT))
    
    print(f"📊 Test Configuration:")
    print(f"  • Host Agent URL: {host_agent_url}")
    print(f"  • Agent URL: http://{agent_host}:{agent_port}/")
    print()
    
    # Create test agent card
    print("🔧 Creating test agent card...")
    agent_card = create_test_agent_card(agent_host, agent_port)
    print(f"  ✅ Agent card created: {agent_card.name}")
    print(f"  📋 Skills: {', '.join(skill.name for skill in agent_card.skills)}")
    print()
    
    # Test registration
    print("🤝 Testing registration with host agent...")
    try:
        success = await register_with_host_agent(agent_card, host_agent_url)
        
        if success:
            print("  🎉 SUCCESS: Agent registered successfully!")
            print(f"  📡 The agent '{agent_card.name}' should now appear in the host agent's UI")
            print(f"  🌐 Check the host agent UI at: {host_agent_url.replace('/agent/self-register', '')}")
        else:
            print("  ❌ FAILED: Registration was not successful")
            print("  🔍 Possible causes:")
            print(f"    - Host agent is not running at {host_agent_url}")
            print(f"    - Network connectivity issues")
            print(f"    - Host agent is not accepting registrations")
            
    except Exception as e:
        print(f"  ❌ ERROR: Registration failed with exception: {e}")
        print("  🔍 This could indicate:")
        print(f"    - Host agent is not running at {host_agent_url}")
        print(f"    - Network or connection issues")
        print(f"    - Invalid agent card format")
    
    print()
    print("🏁 Test completed!")
    
    # Additional diagnostics
    print("\n📋 Troubleshooting Guide:")
    print("  1. Ensure host agent is running:")
    print(f"     cd demo/ui && uv run main.py")
    print("  2. Verify host agent URL is accessible:")
    print(f"     curl {host_agent_url.replace('/agent/self-register', '/health')}")
    print("  3. Check environment variables:")
    print("     A2A_HOST_AGENT_URL (current: {})".format(host_agent_url))
    print("  4. Ensure agent will run on the specified URL:")
    print(f"     Agent URL: http://{agent_host}:{agent_port}/")
    print("\n🎯 Next Steps:")
    print("  • Start this agent with: uv run .")
    print("  • Check the host agent UI for the new agent registration")
    print("  • Test agent-to-agent communication through the host")

if __name__ == "__main__":
    print("🚀 Azure Foundry Claims Specialist Agent Self-Registration Test")
    print()
    
    # Check for required environment variables for the agent itself
    required_env_vars = [
        'AZURE_AI_FOUNDRY_PROJECT_ENDPOINT',
        'AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME'
    ]
    
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        print("⚠️  Warning: Missing required environment variables for agent operation:")
        for var in missing_vars:
            print(f"  • {var}")
        print("\nNote: These are needed for the actual agent to run, but not for registration testing.")
        print()
    
    asyncio.run(test_self_registration()) 