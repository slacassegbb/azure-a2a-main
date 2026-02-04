#!/usr/bin/env python3
"""
Test scheduled workflow execution from the command line.
This simulates what happens when a scheduled workflow triggers.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path so we can import backend modules
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

# Load environment variables
ROOT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ROOT_ENV_PATH, override=False)

# Set required environment variables
os.environ.setdefault("A2A_HOST", "FOUNDRY")
os.environ.setdefault("DEBUG_MODE", "false")

async def test_scheduled_workflow():
    """Test execution of a scheduled workflow."""
    
    print("="*70)
    print("🧪 TESTING SCHEDULED WORKFLOW EXECUTION")
    print("="*70)
    
    # Import after environment is set up
    from service.workflow_service import WorkflowService
    
    # Get available workflows
    print("\n📋 Step 1: Loading workflows from database...")
    workflow_service = WorkflowService()
    workflows = workflow_service.get_all_workflows()
    
    if not workflows:
        print("❌ No workflows found in the database")
        return
    
    print(f"✅ Found {len(workflows)} workflow(s):")
    for i, wf in enumerate(workflows, 1):
        print(f"   {i}. {wf.name} - {wf.description or 'No description'}")
    
    # Find the test workflow (or use first one)
    test_workflow = None
    for wf in workflows:
        if 'stripe' in wf.name.lower() or 'twilio' in wf.name.lower():
            test_workflow = wf
            break
    
    if not test_workflow:
        test_workflow = workflows[0]
    
    print(f"\n📋 Step 2: Selected workflow: '{test_workflow.name}'")
    print(f"   Description: {test_workflow.description or 'N/A'}")
    print(f"   Steps: {len(test_workflow.steps or [])}")
    for i, step in enumerate(test_workflow.steps or [], 1):
        agent_name = step.get('agentName', 'Unknown')
        desc = step.get('description', 'No description')
        print(f"      {i}. {agent_name}: {desc}")
    
    # Check agent availability
    print(f"\n📋 Step 3: Checking required agents...")
    from service.agent_registry import get_registry
    
    global_registry = get_registry()
    agent_names_needed = []
    for step in (test_workflow.steps or []):
        name = step.get('agentName') or step.get('agent')
        if name and name not in agent_names_needed:
            agent_names_needed.append(name)
    
    print(f"   Required agents: {agent_names_needed}")
    
    for agent_name in agent_names_needed:
        agent_config = global_registry.get_agent(agent_name)
        if agent_config:
            # Check for production URL
            prod_url = agent_config.get('production_url')
            local_url = agent_config.get('local_url')
            url = agent_config.get('url')
            
            print(f"   ✅ {agent_name}:")
            print(f"      Production URL: {prod_url or '(not set)'}")
            print(f"      Local URL: {local_url or '(not set)'}")
            print(f"      Current URL: {url or '(not set)'}")
            
            # For scheduled workflows, we'll use production URL
            if prod_url:
                print(f"      🌐 Will use production URL for scheduled execution")
        else:
            print(f"   ❌ {agent_name}: NOT FOUND in registry!")
    
    print(f"\n📋 Step 4: Triggering scheduled workflow execution...")
    print("   ⏳ This may take 30-90s for cold starts from scale-to-zero...")
    print("   💡 Watch for [SCHEDULER] logs below")
    print("")
    
    # Import and call the execute function directly
    import backend_production
    
    try:
        # Execute the workflow
        result = await backend_production.execute_scheduled_workflow(
            workflow_name=test_workflow.name,
            session_id="test_user",
            timeout=300  # 5 minute timeout
        )
        
        print("\n" + "="*70)
        print("📊 WORKFLOW EXECUTION RESULT")
        print("="*70)
        
        if result.get('success'):
            print("✅ Status: SUCCESS")
            print(f"⏱️  Execution Time: {result.get('execution_time_seconds', 0)}s")
            print(f"\n📄 Result:")
            result_text = result.get('result', 'No result text')
            if len(result_text) > 500:
                print(result_text[:500] + "...")
                print(f"\n(Truncated - full result is {len(result_text)} characters)")
            else:
                print(result_text)
        else:
            print("❌ Status: FAILED")
            print(f"❗ Error: {result.get('error', 'Unknown error')}")
        
        print("\n" + "="*70)
        
        return result
        
    except Exception as e:
        print("\n" + "="*70)
        print("❌ EXCEPTION DURING EXECUTION")
        print("="*70)
        print(f"Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None

async def main():
    """Main entry point."""
    try:
        result = await test_scheduled_workflow()
        
        # Exit with appropriate code
        if result and result.get('success'):
            print("\n✅ Test completed successfully!")
            sys.exit(0)
        else:
            print("\n❌ Test failed!")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())
