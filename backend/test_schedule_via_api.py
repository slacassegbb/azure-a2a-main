#!/usr/bin/env python3
"""
Test scheduled workflow by making an HTTP request to the running backend.
This is simpler than trying to initialize all the backend components.

PREREQUISITE: Backend must be running (python backend_production.py)
"""

import asyncio
import httpx
import sys
from datetime import datetime, timedelta

async def test_scheduled_workflow_via_api():
    """Test scheduled workflow execution via API."""
    
    print("="*70)
    print("🧪 TESTING SCHEDULED WORKFLOW VIA API")
    print("="*70)
    
    backend_url = "http://localhost:12000"
    
    # Step 1: Check if backend is running
    print(f"\n📋 Step 1: Checking if backend is running at {backend_url}...")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{backend_url}/health")
            if response.status_code == 200:
                print("✅ Backend is running!")
            else:
                print(f"⚠️  Backend responded with status {response.status_code}")
    except Exception as e:
        print(f"❌ Backend is not running or not accessible!")
        print(f"   Error: {e}")
        print(f"\n💡 Please start the backend first:")
        print(f"   cd backend && python backend_production.py")
        return None
    
    # Step 2: Get list of workflows
    print(f"\n📋 Step 2: Getting list of workflows...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{backend_url}/workflows")
            workflows = response.json()
            
            if not workflows:
                print("❌ No workflows found")
                return None
                
            print(f"✅ Found {len(workflows)} workflow(s):")
            for i, wf in enumerate(workflows, 1):
                print(f"   {i}. {wf.get('name')} - {wf.get('description', 'No description')[:60]}...")
            
            # Find Stripe/Twilio workflow
            test_workflow = None
            for wf in workflows:
                if 'stripe' in wf.get('name', '').lower() or 'twilio' in wf.get('name', '').lower():
                    test_workflow = wf
                    break
            
            if not test_workflow:
                test_workflow = workflows[0]
            
            print(f"\n   Selected: {test_workflow.get('name')}")
            
    except Exception as e:
        print(f"❌ Failed to get workflows: {e}")
        return None
    
    # Step 3: Create a test schedule (run immediately)
    print(f"\n📋 Step 3: Creating test schedule (one-time immediate execution)...")
    schedule_time = (datetime.now() + timedelta(seconds=5)).isoformat()
    
    schedule_data = {
        "workflow_id": test_workflow.get('id'),
        "workflow_name": test_workflow.get('name'),
        "schedule_type": "once",
        "schedule_time": schedule_time,
        "enabled": True,
        "session_id": "test_user"
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{backend_url}/api/schedules",
                json=schedule_data
            )
            
            if response.status_code == 200:
                schedule = response.json()
                schedule_id = schedule.get('id')
                print(f"✅ Schedule created with ID: {schedule_id}")
                print(f"   Will run at: {schedule_time}")
            else:
                print(f"❌ Failed to create schedule: {response.status_code}")
                print(f"   Response: {response.text}")
                return None
                
    except Exception as e:
        print(f"❌ Failed to create schedule: {e}")
        return None
    
    # Step 4: Wait for execution
    print(f"\n📋 Step 4: Waiting for workflow to execute...")
    print(f"   ⏳ This may take 30-90s for cold starts...")
    print(f"   💡 Check your backend terminal for [SCHEDULER] logs")
    
    # Wait a bit longer than the schedule time
    await asyncio.sleep(10)
    
    # Step 5: Check run history
    print(f"\n📋 Step 5: Checking run history...")
    max_attempts = 30  # 30 attempts = 30 seconds
    attempt = 0
    
    while attempt < max_attempts:
        attempt += 1
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{backend_url}/api/schedules/history",
                    params={"schedule_id": schedule_id, "limit": 1}
                )
                
                if response.status_code == 200:
                    history = response.json()
                    
                    if history:
                        run = history[0]
                        status = run.get('status')
                        
                        if status == 'running':
                            print(f"   ⏳ Attempt {attempt}/{max_attempts}: Still running...")
                            await asyncio.sleep(1)
                            continue
                        
                        # Execution completed!
                        print("\n" + "="*70)
                        print("📊 WORKFLOW EXECUTION RESULT")
                        print("="*70)
                        
                        print(f"✅ Status: {status.upper()}")
                        print(f"⏱️  Started: {run.get('started_at')}")
                        print(f"⏱️  Completed: {run.get('completed_at')}")
                        
                        if run.get('execution_time'):
                            print(f"⏱️  Duration: {run.get('execution_time')}s")
                        
                        if run.get('error'):
                            print(f"\n❌ Error: {run.get('error')}")
                        
                        if run.get('result'):
                            result = run.get('result')
                            print(f"\n📄 Result:")
                            if len(result) > 500:
                                print(result[:500] + "...")
                                print(f"\n(Truncated - full result is {len(result)} characters)")
                            else:
                                print(result)
                        
                        print("\n" + "="*70)
                        
                        # Cleanup: delete the test schedule
                        print(f"\n📋 Cleaning up: Deleting test schedule...")
                        try:
                            del_response = await client.delete(f"{backend_url}/api/schedules/{schedule_id}")
                            if del_response.status_code == 200:
                                print("✅ Test schedule deleted")
                        except:
                            pass
                        
                        return run
                    else:
                        print(f"   ⏳ Attempt {attempt}/{max_attempts}: No run history yet...")
                        await asyncio.sleep(1)
                        
        except Exception as e:
            print(f"   ⚠️  Error checking history: {e}")
            await asyncio.sleep(1)
    
    print("\n⏰ Timeout waiting for execution to complete")
    print("💡 Check backend logs for details")
    
    # Try to cleanup
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.delete(f"{backend_url}/api/schedules/{schedule_id}")
    except:
        pass
    
    return None

async def main():
    """Main entry point."""
    try:
        result = await test_scheduled_workflow_via_api()
        
        if result and result.get('status') == 'success':
            print("\n✅ Test completed successfully!")
            sys.exit(0)
        else:
            print("\n❌ Test failed or did not complete!")
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
    asyncio.run(main())
