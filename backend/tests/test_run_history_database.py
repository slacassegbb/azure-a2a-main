#!/usr/bin/env python3
"""Test schedule run history database operations."""
import os
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Set DATABASE_URL before importing
os.environ["DATABASE_URL"] = "postgresql://pgadmin:Hip1hops!@a2adb.postgres.database.azure.com:5432/postgres"

from service.scheduler_service import WorkflowScheduler

def test_run_history_database():
    """Test run history with database operations."""
    print("\n🧪 Testing Schedule Run History Database Operations\n")
    print("=" * 60)
    
    scheduler = WorkflowScheduler()
    print(f"✓ Scheduler initialized (use_database={scheduler.use_database})")
    
    # Test 1: Get all run history
    print("\n📜 Test 1: Getting all run history...")
    history = scheduler.get_run_history(limit=5)
    print(f"✓ Retrieved {len(history)} history entries")
    if history:
        latest = history[0]
        print(f"  Latest run:")
        print(f"    - workflow: {latest['workflow_name']}")
        print(f"    - status: {latest['status']}")
        print(f"    - timestamp: {latest['timestamp']}")
        print(f"    - duration: {latest['duration_seconds']}s")
    
    # Test 2: Filter by schedule_id
    print("\n🔍 Test 2: Filtering by schedule_id...")
    if history:
        schedule_id = history[0]['schedule_id']
        filtered = scheduler.get_run_history(schedule_id=schedule_id, limit=3)
        print(f"✓ Found {len(filtered)} runs for schedule {schedule_id[:8]}...")
    
    # Test 3: Filter by session_id
    print("\n👤 Test 3: Filtering by session_id...")
    if history:
        session_id = history[0]['session_id']
        filtered = scheduler.get_run_history(session_id=session_id, limit=10)
        print(f"✓ Found {len(filtered)} runs for session {session_id}")
    
    # Test 4: Add a new run history entry
    print("\n➕ Test 4: Adding new run history entry...")
    import uuid
    entry = scheduler._add_run_history(
        schedule_id=str(uuid.uuid4()),  # Valid UUID
        workflow_id="test-workflow",
        workflow_name="Test Workflow",
        session_id="test-session",
        status="success",
        result="Test result",
        error=None,
        execution_time=1.5
    )
    print(f"✓ Added run history entry: {entry['run_id']}")
    
    # Test 5: Verify the entry was saved
    print("\n✅ Test 5: Verifying entry was saved to database...")
    all_history = scheduler.get_run_history(limit=100)
    found = any(h['run_id'] == entry['run_id'] for h in all_history)
    if found:
        print(f"✓ Entry {entry['run_id']} found in database")
    else:
        print(f"❌ Entry {entry['run_id']} NOT found in database")
    
    print("\n" + "=" * 60)
    print("✅ All run history database tests completed!\n")
    return True

if __name__ == "__main__":
    try:
        success = test_run_history_database()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
