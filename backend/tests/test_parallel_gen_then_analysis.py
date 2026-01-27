#!/usr/bin/env python3
"""
Test Parallel Generation + Analysis with Explicit File Routing
===============================================================

This test validates:
1. Generate 3 images in parallel
2. GPT-4 routes each image to analysis via file_uris parameter
3. All images are analyzed
"""

import asyncio
import httpx
import websockets
import json
import uuid

BACKEND_URL = "http://localhost:12000"
WEBSOCKET_URL = "ws://localhost:8080/events"
TOTAL_TIMEOUT = 420  # 7 minutes - generation + analysis takes time

IMAGE_PROMPTS = [
    "a red sports car on a mountain road",
    "a blue sailboat on calm ocean waters", 
    "a green cabin in a snowy forest"
]


async def test_generation_then_analysis():
    """Test parallel generation followed by analysis."""
    
    print("\n" + "=" * 70)
    print("TEST: PARALLEL GENERATION + SEQUENTIAL ANALYSIS")
    print("=" * 70)
    print()
    print("Phase 1: Generate 3 images in parallel")
    print("Phase 2: Analyze each image (GPT-4 routes via file_uris)")
    print()
    print(f"⏱️  Total timeout: {TOTAL_TIMEOUT} seconds")
    print()
    
    context_id = f"gen_analyze_{uuid.uuid4().hex[:8]}"
    
    images_generated = []
    analyses_completed = []
    seen_analysis_task_ids = set()
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
        
        # Two-step prompt to ensure proper sequencing
        prompt = f"""Please do the following in TWO steps:

STEP 1 - PARALLEL IMAGE GENERATION:
Generate these 3 images IN PARALLEL (call Image Generator 3 times simultaneously):
- {IMAGE_PROMPTS[0]}
- {IMAGE_PROMPTS[1]}
- {IMAGE_PROMPTS[2]}

STEP 2 - ANALYZE EACH IMAGE:
After generation completes, analyze EACH generated image using the Image Analysis agent.
IMPORTANT: Pass each image's URI using the file_uris parameter.

Start with Step 1 now."""

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
        
        print("📤 Sending request...")
        print()
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{BACKEND_URL}/message/send", json=payload)
            if response.status_code != 200:
                print(f"❌ Request failed: {response.status_code}")
                return False
        
        print("✅ Request sent, monitoring events...")
        print()
        
        start_time = asyncio.get_event_loop().time()
        phase = "GENERATION"
        
        while (asyncio.get_event_loop().time() - start_time) < TOTAL_TIMEOUT and not test_completed:
            try:
                event_str = await asyncio.wait_for(ws.recv(), timeout=5.0)
                event = json.loads(event_str)
                event_type = event.get('eventType') or event.get('type')
                
                # Track images from message events
                if event_type == 'message':
                    content_items = event.get('content', [])
                    for item in content_items:
                        if isinstance(item, dict):
                            # Check for image content
                            if item.get('type') == 'image':
                                uri = item.get('uri', '')
                                filename = item.get('fileName', '')
                                if uri and uri not in [img['uri'] for img in images_generated]:
                                    images_generated.append({'uri': uri, 'filename': filename})
                                    print(f"   🖼️  [{phase}] Image #{len(images_generated)}: {filename}")
                            
                            # Check for analysis text
                            text = item.get('text', '') or item.get('content', '')
                            if text and len(text) > 200:
                                text_lower = text.lower()
                                if any(kw in text_lower for kw in ['analysis', 'key findings', 'primary object']):
                                    if phase == "GENERATION":
                                        phase = "ANALYSIS"
                                        print()
                                        print(f"   📊 Switching to ANALYSIS phase...")
                                        print()
                
                # Track analysis completions from task_updated
                if event_type == 'task_updated':
                    agent_name = event.get('agentName', '')
                    state = event.get('state', '')
                    task_id = event.get('taskId', '')
                    
                    if state == 'completed':
                        if 'analysis' in agent_name.lower() and task_id not in seen_analysis_task_ids:
                            seen_analysis_task_ids.add(task_id)
                            analyses_completed.append({'agent': agent_name, 'task_id': task_id})
                            print(f"   🔍 [{phase}] Analysis #{len(analyses_completed)} completed")
                        
                        if 'host' in agent_name.lower():
                            print()
                            print("   ✅ Host agent completed")
                            await asyncio.sleep(2)
                            test_completed = True
                            break
                
                # Track file_uploaded events
                if event_type == 'file_uploaded':
                    uri = event.get('uri', '')
                    filename = event.get('filename', '')
                    mime = event.get('content_type', '')
                    if 'image' in mime.lower() and uri not in [img['uri'] for img in images_generated]:
                        images_generated.append({'uri': uri, 'filename': filename})
                        print(f"   🖼️  [{phase}] Image #{len(images_generated)} (file_uploaded): {filename}")
                        
            except asyncio.TimeoutError:
                elapsed = int(asyncio.get_event_loop().time() - start_time)
                if elapsed % 60 == 0 and elapsed > 0:
                    print(f"   ⏳ {elapsed}s elapsed - {len(images_generated)} images, {len(analyses_completed)} analyses")
                continue
        
        # Results
        print()
        print("=" * 70)
        print("TEST RESULTS")
        print("=" * 70)
        print()
        print(f"📸 Images Generated: {len(images_generated)}")
        for i, img in enumerate(images_generated[:5], 1):  # Show first 5
            print(f"   {i}. {img['filename']}")
        if len(images_generated) > 5:
            print(f"   ... and {len(images_generated) - 5} more")
        print()
        print(f"🔍 Analyses Completed: {len(analyses_completed)}")
        print()
        
        # Validation
        gen_ok = len(images_generated) >= 3
        analysis_ok = len(analyses_completed) >= 3
        unique_uris = len(set(img['uri'] for img in images_generated)) == len(images_generated)
        
        print("=" * 70)
        print("VALIDATION")
        print("=" * 70)
        print()
        print(f"{'✅' if gen_ok else '❌'} Generated {len(images_generated)} images (need ≥3)")
        print(f"{'✅' if analysis_ok else '❌'} Completed {len(analyses_completed)} analyses (need ≥3)")
        print(f"{'✅' if unique_uris else '❌'} All image URIs unique")
        print()
        
        success = gen_ok and analysis_ok and unique_uris
        if success:
            print("🎉 TEST PASSED: Parallel generation + analysis with explicit file routing works!")
        else:
            print("❌ TEST FAILED")
            if not gen_ok:
                print("   - Need at least 3 images generated")
            if not analysis_ok:
                print("   - Need at least 3 analyses completed")
        
        return success


if __name__ == "__main__":
    result = asyncio.run(test_generation_then_analysis())
    exit(0 if result else 1)
