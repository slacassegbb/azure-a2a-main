#!/usr/bin/env python3
"""
HITL Test - Clean output showing plan state
"""

import asyncio
import httpx
import uuid
import json

BACKEND_URL = "http://localhost:12000"

async def send_and_show_plan(context_id: str, message: str):
    """Send a message and show what we sent."""
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
    print(f"Context ID: {context_id}")
    print(f"Message: {message}")
    print(f"{'='*70}\n")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{BACKEND_URL}/message/send", json=payload)
        print(f"✅ Response: {resp.status_code}")
        
        if resp.status_code == 200:
            result = resp.json()
            print(f"📋 Message ID: {result.get('result', {}).get('message_id', 'N/A')}")
        
    return resp.status_code == 200


async def get_final_messages(context_id: str, wait_time: int = 5):
    """Wait a bit then get the final messages."""
    print(f"\n⏳ Waiting {wait_time}s for processing...")
    await asyncio.sleep(wait_time)
    
    print(f"\n{'='*70}")
    print(f"📥 CHECKING MESSAGES")
    print(f"{'='*70}\n")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Get messages
        resp = await client.post(
            f"{BACKEND_URL}/message/list",
            json={"params": context_id}
        )
        
        if resp.status_code == 200:
            data = resp.json()
            messages = data.get("result", [])
            
            print(f"Found {len(messages)} messages:")
            
            for i, msg in enumerate(messages[-5:], 1):  # Show last 5
                actor = msg.get("actor", "unknown")
                parts = msg.get("parts", [])
                
                print(f"\n{i}. [{actor}]")
                
                for part in parts:
                    if isinstance(part, dict):
                        text = part.get("text") or part.get("root", {}).get("text", "")
                        if text:
                            # Show preview
                            preview = text[:200] + "..." if len(text) > 200 else text
                            print(f"   {preview}")
                            
                            # Check for HITL indicators
                            if "input_required" in text.lower():
                                print(f"\n   ⏸️  HITL DETECTED!")
                            elif "approval request" in text.lower():
                                print(f"   📨 Approval request sent!")
            
            return messages
        else:
            print(f"❌ Error: {resp.status_code}")
            return []


async def main():
    print("\n" + "="*70)
    print("  HITL TEST: Teams Approval Request")
    print("="*70)
    
    context_id = f"test-teams-{uuid.uuid4().hex[:8]}"
    
    # Test 1: Simple Teams approval
    message = """
    Send an approval request to the Teams channel asking:
    "Please approve this $500 expense for office supplies."
    
    Wait for the human to respond with approval.
    """
    
    success = await send_and_show_plan(context_id, message)
    
    if success:
        # Check what happened
        messages = await get_final_messages(context_id, wait_time=8)
        
        # Check if HITL was triggered
        hitl_detected = False
        for msg in messages:
            parts = msg.get("parts", [])
            for part in parts:
                if isinstance(part, dict):
                    text = str(part.get("text", "")) + str(part.get("root", {}).get("text", ""))
                    if "input_required" in text.lower():
                        hitl_detected = True
                        break
        
        print(f"\n{'='*70}")
        if hitl_detected:
            print(f"✅ HITL TRIGGERED - Plan should be saved!")
            print(f"{'='*70}")
            print(f"\n📋 What should have happened:")
            print(f"   1. Orchestrator planned the workflow")
            print(f"   2. Teams agent was called")
            print(f"   3. Teams returned 'input_required'")
            print(f"   4. Plan was saved to session_context.current_plan")
            print(f"   5. Workflow paused")
            print(f"\n📱 Check Teams for the approval message")
            print(f"   When you approve, the webhook will:")
            print(f"   1. Call /message/send with same context_id")
            print(f"   2. Orchestrator resumes from saved plan")
            print(f"   3. Teams task marked 'completed'")
            print(f"   4. Workflow continues")
        else:
            print(f"⚠️  NO HITL DETECTED")
            print(f"{'='*70}")
            print(f"\nCheck backend logs for:")
            print(f"   • Was Teams agent called?")
            print(f"   • Did it return input_required?")
            print(f"   • Was plan saved?")
        
        print(f"\n{'='*70}\n")


if __name__ == "__main__":
    asyncio.run(main())
