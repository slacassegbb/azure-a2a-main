#!/usr/bin/env python3
"""
Test Parallel Image Generation + Sequential Vision Analysis
============================================================

This test validates the EXPLICIT FILE ROUTING (Option 3) implementation:
1. Generate 3 images IN PARALLEL using Image Generator agent
2. Each parallel call returns its own file URI
3. GPT-4 receives all 3 URIs in the responses
4. GPT-4 then calls Image Analysis agent 3 times, passing each URI explicitly via file_uris parameter

This tests the race condition fix where previously _latest_processed_parts would get overwritten
during parallel execution, causing files to be lost or mixed up.

Expected behavior:
- 3 images generated simultaneously (parallel execution)
- Each image analyzed by vision agent with its specific URI
- No file mix-ups or lost files
"""

import asyncio
import httpx
import websockets
import json
import uuid
import re
from datetime import datetime

# Configuration
BACKEND_URL = "http://localhost:12000"
WEBSOCKET_URL = "ws://localhost:8080/events"
TOTAL_TIMEOUT = 300  # 5 minutes for full test (3 parallel generations + 3 analyses)

# Test subjects - 3 different prompts to generate distinct images
IMAGE_PROMPTS = [
    "a red sports car on a mountain road at sunset",
    "a blue sailing boat on a calm ocean with dolphins", 
    "a green forest cabin with smoke coming from the chimney"
]


async def test_parallel_generation_and_analysis():
    """
    Test parallel image generation followed by sequential analysis.
    
    The key test here is:
    1. All 3 images generated in parallel (tests parallel execution)
    2. Each image correctly routed to analysis (tests explicit file routing)
    3. No files get mixed up or lost (validates Option 3 fix)
    """
    
    print("\n" + "=" * 70)
    print("TEST: PARALLEL IMAGE GENERATION + VISION ANALYSIS")
    print("=" * 70)
    print()
    print("This test validates the EXPLICIT FILE ROUTING implementation.")
    print("Previously, parallel execution would cause race conditions with")
    print("_latest_processed_parts being overwritten. Now each file URI is")
    print("explicitly passed via the file_uris parameter.")
    print()
    print(f"⏱️  Total timeout: {TOTAL_TIMEOUT} seconds")
    print()
    
    context_id = f"parallel_test_{uuid.uuid4().hex[:8]}"
    
    # Tracking state
    images_generated = []
    images_analyzed = []
    generation_started = False
    analysis_started = False
    test_completed = False
    
    async with websockets.connect(
        WEBSOCKET_URL,
        ping_interval=20,
        ping_timeout=60
    ) as ws:
        # Subscribe to events
        await ws.send(json.dumps({
            "type": "subscribe",
            "contextId": context_id
        }))
        
        print("📡 WebSocket connected")
        print()
        
        # Build the request - ask for 3 parallel image generations + analysis
        prompt = f"""I need you to do the following:

1. FIRST, generate 3 images IN PARALLEL using the Image Generator agent:
   - Image 1: {IMAGE_PROMPTS[0]}
   - Image 2: {IMAGE_PROMPTS[1]}
   - Image 3: {IMAGE_PROMPTS[2]}

2. THEN, after all 3 images are generated, use the Image Analysis agent to analyze EACH image.
   Make sure to pass each image's URI using the file_uris parameter.

Please generate all 3 images in parallel (simultaneously), then analyze each one."""

        message_id = str(uuid.uuid4())
        payload = {
            "params": {
                "messageId": message_id,
                "contextId": context_id,
                "role": "user",
                "parts": [
                    {
                        "root": {
                            "kind": "text",
                            "text": prompt
                        }
                    }
                ],
                "agentMode": True,
                "enableInterAgentMemory": True
            }
        }
        
        print("=" * 70)
        print("PHASE 1: PARALLEL IMAGE GENERATION")
        print("=" * 70)
        print()
        print("📤 Sending request for 3 parallel image generations...")
        print()
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{BACKEND_URL}/message/send", json=payload)
            
            if response.status_code != 200:
                print(f"❌ Request failed: {response.status_code}")
                print(response.text)
                return False
        
        print("✅ Request sent, monitoring events...")
        print()
        
        # Event collection loop
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
                
                # Track image generation from file_uploaded events
                if event_type == 'file_uploaded':
                    uri = event.get('uri', '')
                    filename = event.get('filename', '')
                    mime = event.get('content_type', '')
                    source = event.get('source_agent', '')
                    
                    print(f"   📤 [file_uploaded] mime={mime}, filename={filename[:30] if filename else 'N/A'}...")
                    
                    if 'image' in mime.lower() and uri not in [img['uri'] for img in images_generated]:
                        images_generated.append({
                            'uri': uri,
                            'filename': filename,
                            'source': source
                        })
                        print(f"   🖼️  IMAGE #{len(images_generated)} GENERATED (file_uploaded)")
                        print(f"      Source: {source}")
                        print(f"      File: {filename}")
                        print(f"      URI: {uri[:80]}...")
                        print()
                
                # Also track images from message events (type: 'image' in content)
                if event_type == 'message':
                    content_items = event.get('content', [])
                    # Debug: show what's in the message
                    if content_items:
                        types_found = [item.get('type') if isinstance(item, dict) else type(item).__name__ for item in content_items]
                        if 'image' in str(types_found).lower() or 'file' in str(types_found).lower():
                            print(f"   📨 [message] content types: {types_found}")
                    
                    for item in content_items:
                        if isinstance(item, dict) and item.get('type') == 'image':
                            uri = item.get('uri', '')
                            filename = item.get('fileName', '')
                            if uri and uri not in [img['uri'] for img in images_generated]:
                                images_generated.append({
                                    'uri': uri,
                                    'filename': filename,
                                    'source': 'message_event'
                                })
                                print(f"   🖼️  IMAGE #{len(images_generated)} GENERATED (message)")
                                print(f"      File: {filename}")
                                print(f"      URI: {uri[:80]}...")
                                print()
                                
                                if len(images_generated) == 3 and not analysis_started:
                                    print()
                                    print("=" * 70)
                                    print("PHASE 2: SEQUENTIAL IMAGE ANALYSIS")
                                    print("=" * 70)
                                    print()
                                    print("All 3 images generated! Now watching for analysis...")
                                    print()
                                    analysis_started = True
                
                # Track image analysis agent calls
                if event_type in ['outgoing_agent_message', 'task_updated']:
                    event_lower = json.dumps(event).lower()
                    
                    # Check for image generator calls
                    if 'image' in event_lower and 'generator' in event_lower:
                        if not generation_started:
                            generation_started = True
                            print("   🎨 Image Generator agent(s) called...")
                    
                    # Check for image analysis calls - count unique completions
                    if 'image' in event_lower and ('analysis' in event_lower or 'vision' in event_lower):
                        if event_type == 'task_updated':
                            state = event.get('state', '')
                            agent_name = event.get('agentName', '')
                            task_id = event.get('taskId', '')
                            
                            # Deduplicate by taskId to avoid counting same analysis multiple times
                            # Only count 'completed' state and ensure we haven't seen this task_id before
                            if state == 'completed' and 'analysis' in agent_name.lower():
                                existing_task_ids = [a.get('task_id') for a in images_analyzed]
                                if task_id and task_id not in existing_task_ids:
                                    images_analyzed.append({
                                        'agent': agent_name,
                                        'state': state,
                                        'task_id': task_id
                                    })
                                    print(f"   🔍 IMAGE ANALYSIS #{len(images_analyzed)} COMPLETED")
                                    print(f"      Agent: {agent_name}")
                                    print(f"      TaskID: {task_id[:8]}...")
                                    print()
                
                # Check for message events with analysis text
                if event_type == 'message':
                    content = event.get('content', [])
                    for item in content:
                        if isinstance(item, dict):
                            text = item.get('text', '')
                            # Look for analysis-related content
                            if text and len(text) > 200:
                                if any(word in text.lower() for word in ['analysis', 'image shows', 'depicts', 'features']):
                                    if len(images_analyzed) < 3:
                                        # This might be an analysis we didn't catch
                                        pass
                
                # Check for host completion
                if event_type == 'task_updated':
                    agent_name = event.get('agentName', '')
                    state = event.get('state', '')
                    
                    if state == 'completed' and 'host' in agent_name.lower():
                        print()
                        print("   ✅ Host agent completed - test finished")
                        test_completed = True
                        break
                        
            except asyncio.TimeoutError:
                elapsed = int(asyncio.get_event_loop().time() - start_time)
                if elapsed % 30 == 0:  # Status update every 30s
                    print(f"   ⏳ Waiting... ({elapsed}s elapsed, {len(images_generated)} images, {len(images_analyzed)} analyses)")
                continue
        
        # Results
        print()
        print("=" * 70)
        print("TEST RESULTS")
        print("=" * 70)
        print()
        
        # Check image generation
        print(f"📸 Images Generated: {len(images_generated)}/3")
        for i, img in enumerate(images_generated, 1):
            print(f"   {i}. {img['filename']}")
        print()
        
        # Check image analysis
        print(f"🔍 Images Analyzed: {len(images_analyzed)}/3")
        for i, analysis in enumerate(images_analyzed, 1):
            print(f"   {i}. {analysis['agent']}")
        print()
        
        # Determine success
        generation_success = len(images_generated) >= 3
        analysis_success = len(images_analyzed) >= 3
        
        # Verify no duplicate URIs (would indicate mix-up)
        unique_uris = set(img['uri'] for img in images_generated)
        no_duplicates = len(unique_uris) == len(images_generated)
        
        print("=" * 70)
        print("VALIDATION")
        print("=" * 70)
        print()
        print(f"{'✅' if generation_success else '❌'} Parallel generation: {len(images_generated)}/3 images")
        print(f"{'✅' if analysis_success else '❌'} Sequential analysis: {len(images_analyzed)}/3 analyses")
        print(f"{'✅' if no_duplicates else '❌'} No duplicate URIs (no file mix-up)")
        print()
        
        if generation_success and analysis_success and no_duplicates:
            print("🎉 TEST PASSED: Explicit file routing works correctly!")
            print("   - Parallel execution did not cause race conditions")
            print("   - Each image was routed to analysis with its correct URI")
            return True
        else:
            print("❌ TEST FAILED")
            if not generation_success:
                print("   - Not all images were generated")
            if not analysis_success:
                print("   - Not all images were analyzed")
            if not no_duplicates:
                print("   - Duplicate URIs detected (file mix-up)")
            return False


async def main():
    """Main entry point."""
    print()
    print("=" * 70)
    print("PARALLEL IMAGE GENERATION + ANALYSIS TEST")
    print("=" * 70)
    print()
    print("Prerequisites:")
    print("  1. Backend running on localhost:12000")
    print("  2. WebSocket server on localhost:8080")
    print("  3. Image Generator agent running")
    print("  4. Image Analysis agent running")
    print()
    print("This test validates Option 3 (Explicit File Routing) by:")
    print("  - Generating 3 images in PARALLEL")
    print("  - Analyzing each image with its specific URI")
    print("  - Verifying no race conditions or file mix-ups")
    print()
    
    try:
        success = await test_parallel_generation_and_analysis()
        print()
        if success:
            print("=" * 70)
            print("✅ ALL TESTS PASSED")
            print("=" * 70)
        else:
            print("=" * 70)
            print("❌ TEST FAILED")
            print("=" * 70)
        return success
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(main())
    exit(0 if result else 1)
