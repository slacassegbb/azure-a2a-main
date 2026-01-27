#!/usr/bin/env python3
"""
Simple Parallel Image Generation Test
======================================

Tests that the host agent correctly splits "generate 3 images" into
3 parallel tasks that execute simultaneously.

Usage:
    python tests/test_parallel_3_images.py
"""

import asyncio
import json
import uuid
from datetime import datetime

import httpx
import websockets

# Configuration
BACKEND_URL = "http://localhost:12000"
WEBSOCKET_URL = "ws://localhost:8080/events"

# Simple prompt that should trigger parallel execution
PROMPT = """Generate 3 product images IN PARALLEL:
1. A red sports car
2. A blue bicycle
3. A green backpack

Execute all 3 image generations simultaneously, not one at a time."""


async def run_test():
    context_id = str(uuid.uuid4())
    image_uris = []
    start_time = None
    end_times = []
    
    print("\n" + "="*80)
    print("PARALLEL IMAGE GENERATION TEST")
    print("="*80)
    print(f"\nContext ID: {context_id}")
    print(f"Prompt: {PROMPT[:60]}...")
    print("="*80)
    
    # Connect to WebSocket
    print(f"\n📡 Connecting to WebSocket...")
    
    async with websockets.connect(WEBSOCKET_URL) as ws:
        print(f"✅ Connected")
        
        # Send request
        print(f"\n🚀 Sending request...")
        start_time = datetime.now()
        
        async with httpx.AsyncClient(timeout=600.0) as client:
            payload = {
                "params": {
                    "messageId": str(uuid.uuid4()),
                    "contextId": context_id,
                    "role": "user",
                    "parts": [{"root": {"kind": "text", "text": PROMPT}}],
                    "agentMode": True,
                    "enableInterAgentMemory": True
                }
            }
            
            response = await client.post(f"{BACKEND_URL}/message/send", json=payload)
            if response.status_code != 200:
                print(f"❌ Request failed: {response.status_code}")
                return False
        
        print(f"✅ Request sent")
        
        # Monitor events
        print(f"\n⏳ Monitoring for image generations (max 5 minutes)...")
        
        timeout = 300  # 5 minutes
        elapsed = 0
        
        while elapsed < timeout:
            try:
                event_str = await asyncio.wait_for(ws.recv(), timeout=5.0)
                event = json.loads(event_str)
                
                # Filter by context
                if event.get('contextId') != context_id:
                    continue
                
                event_type = event.get('eventType') or event.get('type')
                
                # Track file uploads - check multiple event types
                if event_type in ['file_uploaded', 'file']:
                    uri = event.get('uri') or event.get('data', {}).get('uri') or event.get('file', {}).get('uri')
                    if uri and uri not in image_uris:
                        image_uris.append(uri)
                        end_times.append(datetime.now())
                        elapsed_sec = (end_times[-1] - start_time).total_seconds()
                        print(f"  📦 Image {len(image_uris)}/3 generated at {elapsed_sec:.1f}s: {uri[:60]}...")
                
                # Track images from message events
                if event_type == 'message':
                    content = event.get('content', [])
                    for item in content:
                        if isinstance(item, dict) and item.get('type') == 'image':
                            uri = item.get('uri')
                            if uri and uri not in image_uris:
                                image_uris.append(uri)
                                end_times.append(datetime.now())
                                elapsed_sec = (end_times[-1] - start_time).total_seconds()
                                print(f"  📦 Image {len(image_uris)}/3 generated at {elapsed_sec:.1f}s: {uri[:60]}...")
                
                # Also check remote_agent_activity for image URLs
                if event_type == 'remote_agent_activity':
                    content = event.get('content', '')
                    if 'blob.core.windows.net' in content and 'image-generator' in content:
                        # Extract URL from markdown or text
                        import re
                        urls = re.findall(r'https://[^\s\)]+blob\.core\.windows\.net[^\s\)]+\.png[^\s\)]*', content)
                        for uri in urls:
                            if uri not in image_uris:
                                image_uris.append(uri)
                                end_times.append(datetime.now())
                                elapsed_sec = (end_times[-1] - start_time).total_seconds()
                                print(f"  📦 Image {len(image_uris)}/3 generated at {elapsed_sec:.1f}s: {uri[:60]}...")
                
                # Check if done
                if len(image_uris) >= 3:
                    print(f"\n✅ All 3 images generated!")
                    break
                    
            except asyncio.TimeoutError:
                elapsed += 5
                if elapsed % 30 == 0:
                    print(f"   ... {elapsed}s elapsed, {len(image_uris)}/3 images")
    
    # Analyze timing
    print("\n" + "="*80)
    print("RESULTS")
    print("="*80)
    
    if len(image_uris) >= 3:
        total_time = (end_times[-1] - start_time).total_seconds()
        
        # Check if images were generated in parallel
        # If parallel, all 3 should complete within ~30 seconds of each other
        # If sequential, they'd be ~30-60 seconds apart each
        
        if len(end_times) >= 2:
            time_between_first_and_last = (end_times[-1] - end_times[0]).total_seconds()
            
            print(f"\n📊 Timing Analysis:")
            print(f"   Total time: {total_time:.1f}s")
            print(f"   Time between first and last image: {time_between_first_and_last:.1f}s")
            
            if time_between_first_and_last < 30:
                print(f"\n✅ PARALLEL EXECUTION CONFIRMED!")
                print(f"   All 3 images completed within {time_between_first_and_last:.1f}s of each other")
                return True
            else:
                print(f"\n⚠️ SEQUENTIAL EXECUTION DETECTED")
                print(f"   Images were generated {time_between_first_and_last:.1f}s apart")
                print(f"   Expected: < 30s for parallel execution")
                return False
        
        print(f"\n✅ Generated {len(image_uris)} images")
        for i, uri in enumerate(image_uris):
            print(f"   {i+1}. {uri[:80]}...")
        return True
    else:
        print(f"\n❌ Only {len(image_uris)}/3 images generated")
        return False


if __name__ == "__main__":
    import sys
    success = asyncio.run(run_test())
    sys.exit(0 if success else 1)
