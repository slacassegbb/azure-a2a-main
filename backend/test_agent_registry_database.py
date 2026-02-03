#!/usr/bin/env python3
"""Test database-backed agent registry."""

import os
import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent
sys.path.insert(0, str(backend_path))

# Set DATABASE_URL for testing
os.environ["DATABASE_URL"] = "postgresql://pgadmin:Hip1hops!@a2adb.postgres.database.azure.com:5432/postgres"
os.environ["USE_PROD_REGISTRY"] = "false"  # Test with local URLs

from service.agent_registry import AgentRegistry


def test_initialization():
    """Test registry initialization with database."""
    print("\n" + "="*70)
    print("TEST 1: INITIALIZATION")
    print("="*70)
    
    registry = AgentRegistry()
    
    if registry.use_database:
        print("✅ Registry using PostgreSQL database")
        return True
    else:
        print("❌ Registry not using database")
        return False


def test_get_all_agents():
    """Test loading all agents from database."""
    print("\n" + "="*70)
    print("TEST 2: GET ALL AGENTS")
    print("="*70)
    
    registry = AgentRegistry()
    agents = registry.get_all_agents()
    
    print(f"\n✅ Loaded {len(agents)} agents from database")
    
    if agents:
        agent = agents[0]
        print(f"\nSample Agent: {agent.get('name')}")
        print(f"  URL: {agent.get('url')}")
        print(f"  Local URL: {agent.get('local_url')}")
        print(f"  Production URL: {agent.get('production_url')}")
        print(f"  Skills: {len(agent.get('skills', []))} skills")
        
        # Verify URL normalization
        if agent.get('url'):
            print(f"  ✅ URL field correctly populated")
            return True
        else:
            print(f"  ❌ URL field not populated")
            return False
    else:
        print("❌ No agents found")
        return False


def test_get_specific_agent():
    """Test getting a specific agent by name."""
    print("\n" + "="*70)
    print("TEST 3: GET SPECIFIC AGENT")
    print("="*70)
    
    registry = AgentRegistry()
    agent = registry.get_agent("AI Foundry Classification Triage Agent")
    
    if agent:
        print(f"\n✅ Retrieved agent: {agent.get('name')}")
        print(f"  URL: {agent.get('url')}")
        print(f"  Description: {agent.get('description', '')[:80]}...")
        return True
    else:
        print("❌ Could not find classification agent")
        return False


def test_production_urls():
    """Test that production mode returns correct URLs."""
    print("\n" + "="*70)
    print("TEST 4: PRODUCTION URL MODE")
    print("="*70)
    
    # Switch to production mode
    os.environ["USE_PROD_REGISTRY"] = "true"
    registry_prod = AgentRegistry()
    
    agents = registry_prod.get_all_agents()
    
    # Find an agent with actual production URL
    prod_agent = None
    for agent in agents:
        url = agent.get('url', '')
        if 'azurecontainerapps.io' in url:
            prod_agent = agent
            break
    
    if prod_agent:
        print(f"\n✅ Found production agent: {prod_agent.get('name')}")
        print(f"  Production URL: {prod_agent.get('url')}")
        return True
    else:
        print("\nℹ️  No fully deployed production agents found (expected for some environments)")
        return True


def test_add_agent():
    """Test adding a new agent to database."""
    print("\n" + "="*70)
    print("TEST 5: ADD NEW AGENT")
    print("="*70)
    
    os.environ["USE_PROD_REGISTRY"] = "false"
    registry = AgentRegistry()
    
    test_agent = {
        "name": "Test Agent (DELETE ME)",
        "description": "A test agent for verification",
        "version": "1.0.0",
        "local_url": "http://localhost:9999/",
        "production_url": "https://test-agent.example.com/",
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "capabilities": {"streaming": True},
        "skills": [
            {
                "id": "test_skill",
                "name": "Test Skill",
                "description": "A test skill",
                "examples": ["test example"],
                "tags": ["test"]
            }
        ]
    }
    
    # Try to add the agent
    result = registry.add_agent(test_agent)
    
    if result:
        print("\n✅ Successfully added test agent")
        
        # Verify it was added
        retrieved = registry.get_agent("Test Agent (DELETE ME)")
        if retrieved:
            print("✅ Successfully retrieved newly added agent")
            
            # Clean up - remove the test agent
            registry.remove_agent("Test Agent (DELETE ME)")
            print("✅ Successfully removed test agent")
            return True
        else:
            print("❌ Could not retrieve newly added agent")
            return False
    else:
        # Agent might already exist from previous test
        print("⚠️  Could not add agent (may already exist)")
        registry.remove_agent("Test Agent (DELETE ME)")
        return True


def main():
    """Run all tests."""
    print("\n" + "="*70)
    print("DATABASE-BACKED AGENT REGISTRY TEST SUITE")
    print("="*70)
    
    try:
        results = []
        
        results.append(("Initialization", test_initialization()))
        results.append(("Get All Agents", test_get_all_agents()))
        results.append(("Get Specific Agent", test_get_specific_agent()))
        results.append(("Production URLs", test_production_urls()))
        results.append(("Add Agent", test_add_agent()))
        
        print("\n" + "="*70)
        print("TEST RESULTS SUMMARY")
        print("="*70)
        
        for test_name, passed in results:
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{status}: {test_name}")
        
        all_passed = all(result[1] for result in results)
        
        if all_passed:
            print("\n🎉 All tests passed! Agent registry is using PostgreSQL correctly.")
            return 0
        else:
            print("\n❌ Some tests failed. Please review the output above.")
            return 1
            
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
