#!/usr/bin/env python3
"""
Test PURE Parallel Image Generation (No Analysis)
==================================================

This test validates parallel image generation ONLY:
1. Generate 3 images IN PARALLEL using Image Generator agent
2. Verify all 3 images are returned with unique URIs
3. No analysis - just generation

This isolates the parallel generation test from analysis.
"""

import asyncio
import httpx
import websockets
import json
import uuid

# Configuration
BACKEND_URL = "http://localhost:12000"
WEBSOCKET_URL = "ws://localhost:8080/events"
TOTAL_TIMEOUT = 300  # 5 minutes

# 3 different prompts
IMAGE_PROMPTS = [
    "a red sports car on a mountain road at sunset",
    "a blue sailing boat on a calm ocean with dolphins", 
    "a green forest cabin with smoke coming from the chimney"
]


async def test_parallel_generation():
    """Test pure parallel image generation."""
    
    print("\n" + "=" * 70)
    print("TEST: PURE PARALLEL IMAGE GENERATION")
    print("=" * 70)
    print()
    print("This test generates 3 images IN PARALLEL.")
    print("No analysis - just testing parallel generation.")
    print()
    print(f"⏱️  Total timeout: {TOTAL_TIMEOUT} seconds")
    print()
    
    context_id = f"parallel_gen_{uuid.uuid4().hex[:8]}"
    
    images_generated = []
    generation_started = False
    test_completed = False
    
    async with websockets.connect(
        WEBSOCKET_URL,
        ping_interval=20,
        ping_timeout=60
    ) as ws:
        await ws.send(json.dumps({
            "type": "subscribe",
            "contextId": context_id
        }))
        
        print("📡 WebSocket connected")
        print()
        
        # Simple prompt - ONLY generation, no analysis
        prompt = f"""Generate 3 images IN PARALLEL using the Image Generator agent. 
DO NOT analyze them, just generate these 3 images simultaneously:

1. {IMAGE_PROMPTS[0]}
2. {IMAGE_PROMPTS[1]}
3. {IMAGE_PROMPTS[2]}

Generate all 3 at the same time (in parallel). Do not analyze them."""

        message_id = str(uuid.uuid4())
        payload = {
            "params": {
                "messageId": message_id,
                "contextId": context_id,
                "role": "user",
                "parts": [{"root": {"kind": "text", "text": prompt}}],
                "agentMode": True,
                "enableInterAgentMemory": True
            }
        }
        
        print("📤 Sending request for 3 parallel image generations...")
        print()
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{BACKEND_URL}/message/send", json=payload)
            if response.status_code != 200:
                print(f"❌ Request failed: {response.status_code}")
                return False
        
        print("✅ Request sent, monitoring events...")
        print()
        
        start_time = asyncio.get_event_loop().time()
        
        while (asyncio.get_event_loop().time() - start_time) < TOTAL_TIMEOUT and not test_completed:
            try:
                event_str = await asyncio.wait_for(ws.recv(), timeout=5.0)
                event = json.loads(event_str)
                event_type = event.get('eventType') or event.get('type')
                
                # IMPORTANT: Filter events by context_id to ignore stale events from other tests
                event_context = event.get('contextId') or event.get('context_id')
                if event_context and event_context != context_id:
                    continue  # Skip events from other contexts
                
                # Track generation start
                if event_type in ['outgoing_agent_message', 'remote_agent_activity', 'task_updated']:
                    event_lower = json.dumps(event).lower()
                    if 'image' in event_lower and 'generator' in event_lower:
                        if not generation_started:
                            generation_started = True
                            print("   🎨 Image Generator agent(s) called...")
                
                # Track images from file_uploaded events
                if event_type == 'file_uploaded':
                    uri = event.get('uri', '')
                    filename = event.get('filename', '')
                    mime = event.get('content_type', '')
                    
                    if 'image' in mime.lower() and uri not in [img['uri'] for img in images_generated]:
                        images_generated.append({'uri': uri, 'filename': filename})
                        print(f"   🖼️  IMAGE #{len(images_generated)} GENERATED (file_uploaded)")
                        print(f"      File: {filename}")
                        print(f"      URI: {uri[:80]}...")
                        print()
                
                # Track images from message events
                if event_type == 'message':
                    content_items = event.get('content', [])
                    for item in content_items:
                        if isinstance(item, dict) and item.get('type') == 'image':
                            uri = item.get('uri', '')
                            filename = item.get('fileName', '')
                            if uri and uri not in [img['uri'] for img in images_generated]:
                                images_generated.append({'uri': uri, 'filename': filename})
                                print(f"   🖼️  IMAGE #{len(images_generated)} GENERATED (message)")
                                print(f"      File: {filename}")
                                print(f"      URI: {uri[:80]}...")
                                print()
                
                # Check for host completion
                if event_type == 'task_updated':
                    agent_name = event.get('agentName', '')
                    state = event.get('state', '')
                    if state == 'completed' and 'host' in agent_name.lower():
                        print("   ✅ Host agent completed")
                        await asyncio.sleep(2)  # Wait for any final events
                        test_completed = True
                        break
                        
            except asyncio.TimeoutError:
                elapsed = int(asyncio.get_event_loop().time() - start_time)
                if elapsed % 60 == 0 and elapsed > 0:
                    print(f"   ⏳ Still waiting... ({elapsed}s, {len(images_generated)} images so far)")
                continue
        
        # Results
        print()
        print("=" * 70)
        print("TEST RESULTS")
        print("=" * 70)
        print()
        print(f"📸 Images Generated: {len(images_generated)}/3")
        for i, img in enumerate(images_generated, 1):
            print(f"   {i}. {img['filename']}")
            print(f"      URI: {img['uri'][:80]}...")
        print()
        
        # Validation
        unique_uris = set(img['uri'] for img in images_generated)
        success = len(images_generated) >= 3 and len(unique_uris) == len(images_generated)
        
        print("=" * 70)
        print("VALIDATION")
        print("=" * 70)
        print()
        print(f"{'✅' if len(images_generated) >= 3 else '❌'} Generated {len(images_generated)}/3 images")
        print(f"{'✅' if len(unique_uris) == len(images_generated) else '❌'} All URIs unique (no duplicates)")
        print()
        
        if success:
            print("🎉 TEST PASSED: Parallel image generation works!")
        else:
            print("❌ TEST FAILED")
        
        return success


if __name__ == "__main__":
    result = asyncio.run(test_parallel_generation())
    exit(0 if result else 1)
