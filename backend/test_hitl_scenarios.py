#!/usr/bin/env python3
"""
HITL Test - Scenario 1: Simple single-agent call (no HITL)
"""

import asyncio
import httpx
import uuid
from datetime import datetime

BACKEND_URL = "http://localhost:12000"

def log(msg: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}")


async def send_message(context_id: str, message: str) -> dict:
    """Send a message to the backend."""
    payload = {
        "params": {
            "contextId": context_id,
            "agentMode": True,
            "parts": [
                {"root": {"kind": "text", "text": message}}
            ]
        }
    }
    
    log(f"📤 Sending: '{message}'")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{BACKEND_URL}/message/send", json=payload)
        log(f"📥 Response status: {resp.status_code}")
        return resp.json()


async def poll_events(context_id: str, timeout: int = 30) -> list:
    """Poll for events."""
    events = []
    start = asyncio.get_event_loop().time()
    last_event_time = start
    
    log(f"⏳ Polling events (max {timeout}s)...")
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        while asyncio.get_event_loop().time() - start < timeout:
            try:
                resp = await client.post(
                    f"{BACKEND_URL}/events/get",
                    json={"params": context_id}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("result"):
                        last_event_time = asyncio.get_event_loop().time()
                        for event in data["result"]:
                            # Check this event is for our context
                            event_context = event.get("content", {}).get("contextId", "")
                            if event_context != context_id:
                                continue
                                
                            events.append(event)
                            
                            content = event.get("content", {})
                            event_kind = content.get("kind", "unknown")
                            actor = event.get("actor", "unknown")
                            
                            if event_kind == "message":
                                parts = content.get("parts", [])
                                for part in parts:
                                    # Handle different part formats
                                    text = None
                                    if isinstance(part, dict):
                                        text = part.get("text") or part.get("root", {}).get("text")
                                    if text:
                                        preview = text[:150] + "..." if len(text) > 150 else text
                                        log(f"💬 [{actor}]: {preview}")
                                        
                            elif event_kind == "status":
                                status = content.get("status", {})
                                state = status.get("state", "")
                                msg = status.get("message", "")
                                log(f"📊 Status [{state}]: {msg}")
                                
                                if state == "completed":
                                    log("✅ Completed!")
                                    return events
                                elif state == "input-required":
                                    log("⏸️ HITL: Input required!")
                                    return events
                    else:
                        # No new events - check if we've been idle for 5s (likely done)
                        if asyncio.get_event_loop().time() - last_event_time > 5 and len(events) > 0:
                            log("✅ No new events for 5s - likely done")
                            return events
                                    
            except Exception as e:
                log(f"❌ Error: {e}")
                
            await asyncio.sleep(0.5)
    
    log(f"⏰ Timeout after {timeout}s")
    return events


async def main():
    print("\n" + "="*60)
    print("  HITL TEST: Teams Approval Request")
    print("="*60 + "\n")
    
    context_id = f"test-teams-{uuid.uuid4().hex[:8]}"
    log(f"🆔 Context ID: {context_id}")
    
    print("\n📋 This test will:")
    print("1. Call Teams agent to request approval")
    print("2. Teams agent should return 'input_required'")
    print("3. Plan should be saved with the Teams task")
    print("4. You approve in Teams")
    print("5. Workflow should resume\n")
    
    # Request that should trigger Teams HITL
    message = "Send an approval request to the Teams channel for a $500 expense."
    
    await send_message(context_id, message)
    events = await poll_events(context_id, timeout=60)
    
    print("\n" + "-"*60)
    log(f"📊 Total events received: {len(events)}")
    
    # Check if HITL was detected
    hitl_found = False
    for event in events:
        content = event.get("content", {})
        parts = content.get("parts", [])
        for part in parts:
            text_content = ""
            if isinstance(part, dict):
                text_content = str(part.get("text", "")) + str(part.get("root", {}).get("text", ""))
            if "input_required" in text_content.lower():
                hitl_found = True
                log("⏸️ HITL DETECTED! Plan should be saved now.")
                break
    
    if hitl_found:
        print("\n" + "="*60)
        print("  GO TO TEAMS AND APPROVE THE REQUEST")
        print("  (Type 'approved' or 'yes' in the channel)")
        print("="*60 + "\n")
        input("Press Enter after you've approved in Teams...")
        
        log("Waiting for workflow to resume...")
        more_events = await poll_events(context_id, timeout=60)
        
        print(f"\n📊 Events after approval: {len(more_events)}")
        log("✅ Test completed!")
    else:
        log("⚠️ No HITL detected - check backend logs")
    
    print("-"*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
