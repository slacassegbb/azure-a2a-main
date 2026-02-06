#!/usr/bin/env python3
"""
Simple coverage test for foundry_agent_a2a.py

This script imports the module and exercises basic functionality
to measure code coverage.
"""

import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

def test_import():
    """Test that we can import the module"""
    print("Testing import of foundry_agent_a2a...")
    try:
        from hosts.multiagent import foundry_agent_a2a
        print("✅ Successfully imported foundry_agent_a2a")
        return True
    except Exception as e:
        print(f"❌ Failed to import: {e}")
        return False

def test_basic_classes():
    """Test basic class instantiation"""
    print("\nTesting basic classes...")
    try:
        from hosts.multiagent.foundry_agent_a2a import (
            TaskState,
            AgentTask,
            SessionContext
        )
        
        # Test TaskState enum
        state = TaskState.pending
        print(f"  ✓ TaskState: {state}")
        
        # Test AgentTask creation
        task = AgentTask(
            task_id="test-123",
            agent_name="test-agent",
            state=TaskState.pending,
            description="Test task",
            session_id="test-session",
            conversation_id="test-conv"
        )
        print(f"  ✓ AgentTask created: {task.task_id}")
        
        print("✅ Basic classes work correctly")
        return True
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_helper_functions():
    """Test utility functions"""
    print("\nTesting helper functions...")
    try:
        from hosts.multiagent.foundry_agent_a2a import (
            determine_task_status,
            extract_agent_name_variations
        )
        
        # Test status determination
        status = determine_task_status("completed")
        print(f"  ✓ determine_task_status('completed'): {status}")
        
        # Test agent name extraction
        agent_names = extract_agent_name_variations("test agent")
        print(f"  ✓ extract_agent_name_variations: {agent_names}")
        
        print("✅ Helper functions work correctly")
        return True
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("="*70)
    print("🧪 Coverage Test for foundry_agent_a2a.py")
    print("="*70)
    
    results = []
    results.append(test_import())
    results.append(test_basic_classes())
    results.append(test_helper_functions())
    
    print("\n" + "="*70)
    if all(results):
        print("✅ All tests passed!")
        sys.exit(0)
    else:
        print("❌ Some tests failed")
        sys.exit(1)
