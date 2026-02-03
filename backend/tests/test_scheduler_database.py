"""Test scheduler database operations."""
import os
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from service.scheduler_service import WorkflowScheduler, ScheduleType

def test_scheduler_database():
    """Test scheduler with database operations."""
    print("\n🧪 Testing Scheduler Database Operations\n")
    print("=" * 50)
    
    # Initialize scheduler with database
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("❌ DATABASE_URL not set")
        return False
    
    print(f"✓ Using database: {database_url.split('@')[1] if '@' in database_url else 'local'}")
    
    scheduler = WorkflowScheduler()
    print(f"✓ Scheduler initialized (use_database={scheduler.use_database})")
    
    # Test 1: Load schedules from database
    print("\n📥 Test 1: Loading schedules from database...")
    initial_count = len(scheduler.schedules)
    print(f"✓ Loaded {initial_count} schedules")
    
    # Test 2: List schedules
    print("\n📋 Test 2: Listing schedules...")
    schedules = scheduler.get_schedules()
    for schedule in schedules[:3]:  # Show first 3
        print(f"  - {schedule.id}: {schedule.workflow_name} ({schedule.schedule_type.value})")
    
    # Test 3: Create a test schedule
    print("\n➕ Test 3: Creating a test schedule...")
    test_schedule = scheduler.create_schedule(
        workflow_id="test-workflow",
        workflow_name="Database Test Workflow",
        session_id="test-session",
        schedule_type=ScheduleType.INTERVAL,
        enabled=False,  # Disabled so it doesn't actually run
        interval_value=60,
        interval_unit="minutes"
    )
    
    if test_schedule:
        print(f"✓ Created schedule: {test_schedule.id}")
        
        # Test 4: Update the schedule
        print("\n✏️ Test 4: Updating schedule...")
        updated = scheduler.update_schedule(
            test_schedule.id,
            enabled=True,
            interval_value=30
        )
        if updated:
            print(f"✓ Updated schedule: interval_value={updated.interval_value}")
        else:
            print("❌ Failed to update schedule")
        
        # Test 5: Get schedule by ID
        print("\n🔍 Test 5: Getting schedule by ID...")
        fetched = scheduler.get_schedule(test_schedule.id)
        if fetched:
            print(f"✓ Retrieved schedule: {fetched.id}")
            print(f"  - workflow_name: {fetched.workflow_name}")
            print(f"  - enabled: {fetched.enabled}")
            print(f"  - interval_value: {fetched.interval_value}")
        else:
            print("❌ Failed to retrieve schedule")
        
        # Test 6: Delete the schedule
        print("\n🗑️ Test 6: Deleting test schedule...")
        deleted = scheduler.delete_schedule(test_schedule.id)
        if deleted:
            print(f"✓ Deleted schedule: {test_schedule.id}")
            
            # Verify deletion
            fetched_after = scheduler.get_schedule(test_schedule.id)
            if not fetched_after:
                print("✓ Verified schedule was deleted")
            else:
                print("❌ Schedule still exists after deletion")
        else:
            print("❌ Failed to delete schedule")
    else:
        print("❌ Failed to create test schedule")
    
    print("\n" + "=" * 50)
    print("✅ All scheduler database tests completed!\n")
    return True

if __name__ == "__main__":
    try:
        success = test_scheduler_database()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
