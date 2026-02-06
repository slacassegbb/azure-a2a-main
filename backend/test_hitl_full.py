#!/usr/bin/env python3
"""
HITL Test - Shows the query and plan information

Run this and watch the backend terminal for the orchestration logs.
"""

import asyncio
import httpx
import uuid

BACKEND_URL = "http://localhost:12000"

async def main():
    print("\n" + "="*70)
    print("  HITL TEST: Teams + QuickBooks Workflow")
    print("="*70)
    
    context_id = f"test-hitl-workflow-{uuid.uuid4().hex[:8]}"
    
    print(f"\n🆔 Context ID: {context_id}")
    print(f"\n📋 Test Scenario:")
    print(f"   1. Request Teams approval")
    print(f"   2. After approval, create QuickBooks invoice")
    print(f"   This tests that the plan is saved and resumed correctly.")
    
    message = """
I need to process a transaction:

1. First, send an approval request to Teams asking: "Please approve this $500 transaction for office supplies"
2. Wait for human approval
3. After receiving approval, create a QuickBooks invoice for $500 with description "Office supplies - Approved"

Complete both steps in order.
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
    
    print(f"\n{'='*70}")
    print(f"📤 SENDING REQUEST")
    print(f"{'='*70}")
    print(f"\nQuery:")
    print(message)
    print(f"\n{'='*70}")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{BACKEND_URL}/message/send", json=payload)
        print(f"\n✅ Request sent! Status: {resp.status_code}")
    
    print(f"\n{'='*70}")
    print(f"  WATCH THE BACKEND LOGS")
    print(f"{'='*70}")
    print(f"\nYou should see:")
    print(f"")
    print(f"1️⃣  PLANNING PHASE:")
    print(f"   📋 'Initial plan created with X tasks'")
    print(f"   🎯 Goal: {message[:50]}...")
    print(f"   📝 Task 1: Teams approval (state: pending)")
    print(f"   📝 Task 2: QuickBooks invoice (state: pending)")
    print(f"")
    print(f"2️⃣  TEAMS AGENT CALLED:")
    print(f"   🤖 'Calling agent: Teams Agent'")
    print(f"   ⏸️  'Agent returned input_required'")
    print(f"   💾 'Saved plan for HITL resume' <-- KEY LOG!")
    print(f"   📊 'Task state: input_required'")
    print(f"")
    print(f"3️⃣  PLAN SAVED (check this in logs):")
    print(f"   • session_context.current_plan is set")
    print(f"   • Plan includes:")
    print(f"     - goal: (original query)")
    print(f"     - tasks: [Teams: input_required, QuickBooks: pending]")
    print(f"     - workflow: None (if not Visual Designer)")
    print(f"")
    print(f"4️⃣  GO TO TEAMS:")
    print(f"   📱 You should see the approval request")
    print(f"   ✍️  Reply with 'approved' or 'yes'")
    print(f"")
    print(f"5️⃣  AFTER YOU APPROVE (webhook triggers):")
    print(f"   📥 Webhook forwards to /message/send")
    print(f"   📋 'Resuming existing plan with X tasks'")
    print(f"   ♻️  'Restored workflow from plan' (if applicable)")
    print(f"   ✅ 'Marked task as completed with user response'")
    print(f"   🤖 'Calling agent: QuickBooks Online Agent'")
    print(f"   💰 QuickBooks creates invoice")
    print(f"   ✅ 'Goal completed'")
    print(f"")
    print(f"{'='*70}")
    print(f"\nContext ID for tracking: {context_id}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    asyncio.run(main())
