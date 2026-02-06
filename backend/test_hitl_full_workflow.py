#!/usr/bin/env python3
"""
HITL Test with Interactive Approval

This test will:
1. Send a Teams approval request
2. WAIT for you to approve in Teams
3. Show the plan resuming after approval
"""

import asyncio
import httpx
import uuid
from datetime import datetime

BACKEND_URL = "http://localhost:12000"

def log(msg: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}")


async def main():
    context_id = f"test-teams-{uuid.uuid4().hex[:8]}"
    
    print("\n" + "="*70)
    print("  HITL TEST: Teams Approval → QuickBooks Invoice")
    print("="*70)
    print(f"\n🆔 Context ID: {context_id}\n")
    
    # The full workflow test
    message = """
    I need your help with a $500 expense:
    1. First, send an approval request to the Teams channel for this $500 expense
    2. After I approve in Teams, create a QuickBooks invoice for $500 with description "Approved expense"
    
    Please complete both steps in order.
    """
    
    payload = {
        "params": {
            "contextId": context_id,
            "agentMode": True,
            "parts": [
                {"root": {"kind": "text", "text": message}}
            ]
        }
    }
    
    print("📤 STEP 1: Sending workflow request...")
    print("   This should trigger:")
    print("   • Orchestrator plans: Teams approval → QuickBooks invoice")
    print("   • Teams agent called")
    print("   • Teams returns 'input_required'")
    print("   • Plan saved with both tasks\n")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{BACKEND_URL}/message/send", json=payload)
        log(f"✅ Request sent! Status: {resp.status_code}")
    
    print("\n" + "="*70)
    print("  WAITING FOR TEAMS APPROVAL")
    print("="*70)
    print("\n⏸️  The workflow is now PAUSED waiting for your approval")
    print("\n📱 GO TO TEAMS NOW:")
    print("   1. Check the Teams channel for the approval request")
    print("   2. Reply with 'approved' or 'yes'")
    print("   3. The Teams webhook will forward your response to the backend")
    print("   4. The plan will resume and QuickBooks will be called")
    print()
    
    input("👉 Press Enter AFTER you've approved in Teams...")
    
    print("\n⏳ Waiting for workflow to resume (60 seconds)...")
    print("   The backend should:")
    print("   • Receive your approval from Teams webhook")
    print("   • Load the saved plan")
    print("   • Mark Teams task as 'completed'")
    print("   • Call QuickBooks agent")
    print("   • Create the invoice\n")
    
    # Give it time to process
    await asyncio.sleep(5)
    
    print("="*70)
    print("  CHECK BACKEND LOGS FOR:")
    print("="*70)
    print("  1. '📋 [Agent Mode] Resuming existing plan with X tasks'")
    print("  2. '📋 [Agent Mode] Restored workflow from plan'")
    print("  3. '✅ [Agent Mode] Marked task as completed with user response'")
    print("  4. '🤖 [Agent Mode] Calling agent: QuickBooks Online Agent'")
    print("  5. QuickBooks invoice creation")
    print()
    print("🎯 The key test: QuickBooks should get the ACTUAL task,")
    print("   NOT 'Proceed only after approval from Teams'!")
    print()

if __name__ == "__main__":
    asyncio.run(main())
