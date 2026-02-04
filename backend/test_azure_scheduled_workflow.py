#!/usr/bin/env python3
"""
Test scheduled workflow against Azure Container Apps backend.
No local backend needed!
"""

import asyncio
import httpx
import sys
from datetime import datetime, timedelta

# Azure backend URL - try both possibilities
AZURE_BACKEND_URLS = [
    "https://a2a-backend.ambitioussky-6c709152.westus2.azurecontainerapps.io",
    "https://a2abackend.ambitioussky-6c709152.westus2.azurecontainerapps.io",
]

async def find_working_backend_url():
    """Find which backend URL is working."""
    for url in AZURE_BACKEND_URLS:
        print(f"   Trying: {url}")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Try health endpoint
                response = await client.get(f"{url}/health")
                if response.status_code == 200:
                    print(f"   ✅ Found working backend!")
                    return url
                
                # Try root endpoint
                response = await client.get(url)
                if response.status_code in [200, 404, 405]:  # Some response
                    print(f"   ✅ Backend responding at {url}")
                    return url
        except Exception as e:
            print(f"   ❌ Not accessible: {str(e)[:60]}...")
            continue
    
    return None

async def test_scheduled_workflow_on_azure():
    """Test scheduled workflow execution on Azure backend."""
    
    print("="*70)
    print("🌐 TESTING SCHEDULED WORKFLOW ON AZURE")
    print("="*70)
    
    # Step 1: Find working backend URL
    print(f"📋 Step 1: Finding accessible Azure backend...")
    AZURE_BACKEND_URL = await find_working_backend_url()
    
    if not AZURE_BACKEND_URL:
        print("❌ No accessible Azure backend found!")
        print("\n💡 Tried:")
        for url in AZURE_BACKEND_URLS:
            print(f"   - {url}")
        print("\n💡 Possible reasons:")
        print("   - Backend is scaled to zero (takes 30-60s to wake up)")
        print("   - Backend not deployed")
        print("   - Different URL than expected")
        return None
    
    print(f"✅ Using backend: {AZURE_BACKEND_URL}\n")
    
    # Step 2: Get list of workflows
    print(f"\n📋 Step 2: Getting list of workflows...")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{AZURE_BACKEND_URL}/workflows")
            
            if response.status_code != 200:
                print(f"❌ Failed to get workflows: {response.status_code}")
                print(f"   Response: {response.text[:200]}")
                return None
                
            workflows = response.json()
            
            if not workflows:
                print("❌ No workflows found")
                return None
                
            print(f"✅ Found {len(workflows)} workflow(s):")
            for i, wf in enumerate(workflows, 1):
                desc = wf.get('description', 'No description')
                if len(desc) > 60:
                    desc = desc[:60] + "..."
                print(f"   {i}. {wf.get('name')} - {desc}")
            
            # Find Stripe/Twilio workflow
            test_workflow = None
            for wf in workflows:
                if 'stripe' in wf.get('name', '').lower() or 'twilio' in wf.get('name', '').lower():
                    test_workflow = wf
                    break
            
            if not test_workflow:
                test_workflow = workflows[0]
            
            print(f"\n   ✅ Selected: {test_workflow.get('name')}")
            print(f"      ID: {test_workflow.get('id')}")
            
    except Exception as e:
        print(f"❌ Failed to get workflows: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    # Step 3: Create a test schedule (run immediately)
    print(f"\n📋 Step 3: Creating test schedule (one-time immediate execution)...")
    schedule_time = (datetime.now() + timedelta(seconds=10)).isoformat()
    
    schedule_data = {
        "workflow_id": test_workflow.get('id'),
        "workflow_name": test_workflow.get('name'),
        "schedule_type": "once",
        "schedule_time": schedule_time,
        "enabled": True,
        "session_id": "azure_test_user"
    }
    
    print(f"   Schedule data: {schedule_data}")
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{AZURE_BACKEND_URL}/api/schedules",
                json=schedule_data
            )
            
            if response.status_code == 200:
                schedule = response.json()
                schedule_id = schedule.get('id')
                print(f"✅ Schedule created with ID: {schedule_id}")
                print(f"   Will run at: {schedule_time}")
            else:
                print(f"❌ Failed to create schedule: {response.status_code}")
                print(f"   Response: {response.text[:500]}")
                return None
                
    except Exception as e:
        print(f"❌ Failed to create schedule: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    # Step 4: Wait for execution
    print(f"\n📋 Step 4: Waiting for workflow to execute...")
    print(f"   ⏳ This may take 30-90 seconds for cold starts...")
    print(f"   🌐 Azure agents will wake up if scaled to zero")
    print(f"   💡 First execution is always slower due to cold starts")
    
    # Wait a bit longer than the schedule time
    print(f"\n   Waiting 15 seconds for schedule to trigger...")
    await asyncio.sleep(15)
    
    # Step 5: Check run history
    print(f"\n📋 Step 5: Checking run history...")
    max_attempts = 60  # 60 attempts = 60 seconds (enough for cold starts)
    attempt = 0
    last_status = None
    
    while attempt < max_attempts:
        attempt += 1
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{AZURE_BACKEND_URL}/api/schedules/history",
                    params={"schedule_id": schedule_id, "limit": 1}
                )
                
                if response.status_code == 200:
                    history = response.json()
                    
                    if history:
                        run = history[0]
                        status = run.get('status')
                        
                        # Only print if status changed
                        if status != last_status:
                            print(f"   📊 Attempt {attempt}/{max_attempts}: Status = {status}")
                            last_status = status
                        
                        if status == 'running':
                            await asyncio.sleep(2)
                            continue
                        
                        # Execution completed!
                        print("\n" + "="*70)
                        print("📊 WORKFLOW EXECUTION RESULT")
                        print("="*70)
                        
                        success = status == 'success'
                        print(f"{'✅' if success else '❌'} Status: {status.upper()}")
                        print(f"⏱️  Started: {run.get('started_at')}")
                        print(f"⏱️  Completed: {run.get('completed_at')}")
                        
                        if run.get('execution_time'):
                            print(f"⏱️  Duration: {run.get('execution_time')}s")
                        
                        if run.get('error'):
                            print(f"\n❌ Error: {run.get('error')}")
                        
                        if run.get('result'):
                            result = run.get('result')
                            print(f"\n📄 Result:")
                            if len(result) > 800:
                                print(result[:800] + "...")
                                print(f"\n(Truncated - full result is {len(result)} characters)")
                            else:
                                print(result)
                        
                        print("\n" + "="*70)
                        
                        # Cleanup: delete the test schedule
                        print(f"\n📋 Cleaning up: Deleting test schedule...")
                        try:
                            del_response = await client.delete(f"{AZURE_BACKEND_URL}/api/schedules/{schedule_id}")
                            if del_response.status_code == 200:
                                print("✅ Test schedule deleted")
                            else:
                                print(f"⚠️  Failed to delete schedule: {del_response.status_code}")
                        except Exception as cleanup_err:
                            print(f"⚠️  Cleanup error (non-critical): {cleanup_err}")
                        
                        return run
                    else:
                        if attempt % 5 == 0:  # Print every 5 attempts
                            print(f"   ⏳ Attempt {attempt}/{max_attempts}: No run history yet, waiting...")
                        await asyncio.sleep(2)
                else:
                    print(f"   ⚠️  API returned {response.status_code}: {response.text[:100]}")
                    await asyncio.sleep(2)
                        
        except Exception as e:
            if attempt % 10 == 0:  # Print error every 10 attempts
                print(f"   ⚠️  Error checking history (attempt {attempt}): {e}")
            await asyncio.sleep(2)
    
    print("\n⏰ Timeout waiting for execution to complete (60 seconds)")
    print("💡 The workflow may still be running. Check Azure backend logs or UI.")
    
    # Try to cleanup
    print(f"\n📋 Attempting cleanup...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.delete(f"{AZURE_BACKEND_URL}/api/schedules/{schedule_id}")
            print("✅ Cleanup done")
    except Exception as e:
        print(f"⚠️  Cleanup failed (non-critical): {e}")
    
    return None

async def main():
    """Main entry point."""
    print("\n" + "="*70)
    print("🧪 Azure Scheduled Workflow Test")
    print("="*70)
    print("This test will:")
    print("  1. Connect to Azure backend")
    print("  2. Create a one-time schedule")
    print("  3. Wait for it to execute")
    print("  4. Show the results")
    print("  5. Clean up")
    print("="*70 + "\n")
    
    try:
        result = await test_scheduled_workflow_on_azure()
        
        if result and result.get('status') == 'success':
            print("\n✅ Test completed successfully!")
            print("🎉 Scheduled workflows are working on Azure with cold-start support!")
            sys.exit(0)
        elif result:
            print(f"\n⚠️  Test completed but workflow status was: {result.get('status')}")
            sys.exit(1)
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
