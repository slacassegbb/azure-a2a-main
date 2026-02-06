#!/usr/bin/env python3
"""
Simple HITL Test - Teams Approval

This script sends a request that should trigger Teams HITL.
Watch the backend logs to see the plan persistence in action.
"""

import asyncio
import httpx
import uuid

BACKEND_URL = "http://localhost:12000"

async def main():
    context_id = f"test-teams-hitl-{uuid.uuid4().hex[:8]}"
    
    print("\n" + "="*70)
    print("  HITL TEST: Teams Approval with Plan Persistence")
    print("="*70)
    print(f"\n🆔 Context ID: {context_id}\n")
    
    print("📋 What to watch for in backend logs:")
    print("   1. Orchestrator plans: Teams approval → (next task)")
    print("   2. Teams agent called and returns input_required")
    print("   3. '💾 [Agent Mode] Saved plan for HITL resume' message")
    print("   4. Plan saved with workflow info preserved")
    print()
    
    message = "Send an approval request to the Teams channel for a $500 expense, then wait for my approval."
    
    payload = {
        "params": {
            "contextId": context_id,
            "agentMode": True,
            "parts": [
                {"root": {"kind": "text", "text": message}}
            ]
        }
    }
    
    print(f"📤 Sending request...")
    print(f"   Message: {message}")
    print()
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{BACKEND_URL}/message/send", json=payload)
        print(f"✅ Request sent! Status: {resp.status_code}\n")
    
    print("="*70)
    print("  NOW CHECK THE BACKEND LOGS")
    print("="*70)
    print()
    print("Look for these log messages:")
    print("  • '📋 [Agent Mode] Initial plan created...'")
    print("  • '🤖 [Agent Mode] Calling agent: Teams Agent'")
    print("  • '⏸️ [Agent Mode] Agent returned input_required'")
    print("  • '💾 [Agent Mode] Saved plan for HITL resume'")
    print()
    print("Then check Teams for the approval request.")
    print("After you approve in Teams, the plan should resume automatically!")
    print()

if __name__ == "__main__":
    asyncio.run(main())
