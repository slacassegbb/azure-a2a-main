#!/usr/bin/env python3
"""
Test Image Generation + Analysis Flow
======================================

This test validates the complete image generation and analysis workflow:
1. Generate an image using the Image Generator agent
2. Host orchestrator receives the image as a FilePart
3. Send the image to Image Analysis agent for analysis
4. Receive analysis results from the vision agent

This ensures the A2A protocol correctly handles:
- Initial image generation
- FilePart return with blob storage URIs
- Image file exchange between agents
- Vision analysis of generated images
"""

import asyncio
import httpx
import websockets
import json
import uuid
from pathlib import Path

# Configuration
BACKEND_URL = "http://localhost:12000"
WEBSOCKET_URL = "ws://localhost:8080/events"
IMAGE_GENERATION_TIMEOUT = 180  # Increased for DALL-E 3
IMAGE_ANALYSIS_TIMEOUT = 120     # Increased for vision analysis

async def test_image_generation_and_analysis():
    """
    Test the complete image generation and analysis workflow.
    
    Phase 1: Generate an image with Image Generator agent
    Phase 2: Send the generated image to Image Analysis agent for analysis
    """
    
    print("\n" + "=" * 60)
    print("TESTING IMAGE GENERATION & ANALYSIS FLOW")
    print("=" * 60)
    print("\n")
    print("⚠️  Note: Image generation typically takes 30-60 seconds")
    print("⚠️  Image analysis typically takes 10-20 seconds")
    print("⚠️  Make sure both agents are running:")
    print("    - Image Generator agent on port 9010")
    print("    - Image Analysis agent on port 9066")
    print()
    
    # Use a unique context ID for this test
    context_id = f"gen_analysis_test_{uuid.uuid4().hex[:8]}"
    
    # Track test state
    initial_image_uri = None
    analysis_completed = False
    analysis_text = None
    
    async with websockets.connect(
        WEBSOCKET_URL,
        ping_interval=20,
        ping_timeout=60
    ) as ws:
        # Subscribe to events for this context
        await ws.send(json.dumps({
            "type": "subscribe",
            "contextId": context_id
        }))
        
        print("=" * 60)
        print("PHASE 1: IMAGE GENERATION")
        print("=" * 60)
        print()
        print("📡 WebSocket connected")
        
        # Phase 1: Generate an image
        message_id_1 = str(uuid.uuid4())
        generation_payload = {
            "params": {
                "messageId": message_id_1,
                "contextId": context_id,
                "role": "user",
                "parts": [
                    {
                        "root": {
                            "kind": "text",
                            "text": "Use the Image Generator agent to create a photorealistic image of a red sports car on a mountain road at sunset"
                        }
                    }
                ],
                "agentMode": True,
                "enableInterAgentMemory": True
            }
        }
        
        print("📤 Sending image generation request...")
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{BACKEND_URL}/message/send", json=generation_payload)
            
            if response.status_code != 200:
                print(f"❌ Generation request failed with status {response.status_code}")
                print(response.text)
                return False
        
        print(f"✅ Request sent, collecting events (timeout: {IMAGE_GENERATION_TIMEOUT}s)...")
        print("⏳ Image generation typically takes 30-60 seconds...\n")
        
        # Collect events for Phase 1
        start_time = asyncio.get_event_loop().time()
        completed = False
        image_generated = False
        
        while (asyncio.get_event_loop().time() - start_time) < IMAGE_GENERATION_TIMEOUT and not completed:
            try:
                event_str = await asyncio.wait_for(ws.recv(), timeout=5.0)
                event = json.loads(event_str)
                event_type = event.get('eventType') or event.get('type')
                
                # Check for image generator activity
                if event_type in ['outgoing_agent_message', 'remote_agent_activity', 'task_updated']:
                    event_str_lower = json.dumps(event).lower()
                    if 'image' in event_str_lower and 'generator' in event_str_lower:
                        image_generated = True
                        print(f"   🎨 Image Generator agent called")
                
                # Check for generated image
                if event_type == 'file_uploaded':
                    file_info = event
                    uri = file_info.get('uri', '')
                    mime = file_info.get('content_type', '')
                    
                    if 'image' in mime:
                        initial_image_uri = uri
                        print(f"\n   ✅ IMAGE GENERATED!")
                        print(f"      URI: {uri[:100]}...\n")
                
                # Check for message with image
                if event_type == 'message':
                    content_items = event.get('content', [])
                    for item in content_items:
                        if isinstance(item, dict) and item.get('type') == 'image':
                            uri = item.get('uri', '')
                            if uri and not initial_image_uri:
                                initial_image_uri = uri
                                print(f"\n   ✅ IMAGE GENERATED!")
                                print(f"      URI: {uri[:100]}...\n")
                
                # Check for host completion
                if event_type == 'task_updated':
                    agent_name = event.get('agentName', '')
                    state = event.get('state')
                    if state == 'completed' and 'host' in agent_name.lower():
                        print(f"   ✅ Host agent completed - finishing Phase 1")
                        await asyncio.sleep(1)
                        completed = True
                        break
                        
            except asyncio.TimeoutError:
                continue
        
        print()
        print("=" * 60)
        print("PHASE 1 RESULTS")
        print("=" * 60)
        print(f"{'✅' if image_generated else '❌'} Image generated: {image_generated}")
        print(f"{'✅' if initial_image_uri else '❌'} Image returned: {bool(initial_image_uri)}")
        if initial_image_uri:
            print(f"🖼️  Image URI: {initial_image_uri[:100]}...")
        print()
        
        if not initial_image_uri:
            print("❌ TEST FAILED: No image was generated in Phase 1")
            return False
        
        # Phase 2: Send image to Image Analysis agent
        print("=" * 60)
        print("PHASE 2: IMAGE ANALYSIS")
        print("=" * 60)
        print()
        
        message_id_2 = str(uuid.uuid4())
        analysis_payload = {
            "params": {
                "messageId": message_id_2,
                "contextId": context_id,
                "role": "user",
                "parts": [
                    {
                        "root": {
                            "kind": "text",
                            "text": "Use the Image Analysis agent to analyze this image and describe what you see in detail"
                        }
                    },
                    {
                        "root": {
                            "kind": "file",
                            "file": {
                                "uri": initial_image_uri,
                                "name": "generated_image.png",
                                "mimeType": "image/png"
                            }
                        }
                    }
                ],
                "agentMode": True,
                "enableInterAgentMemory": True
            }
        }
        
        print("📤 Sending image analysis request...")
        print(f"   Image URI: {initial_image_uri[:80]}...")
        print()
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{BACKEND_URL}/message/send", json=analysis_payload)
            
            if response.status_code != 200:
                print(f"❌ Analysis request failed with status {response.status_code}")
                print(response.text)
                return False
        
        print(f"✅ Analysis request sent, collecting events (timeout: {IMAGE_ANALYSIS_TIMEOUT}s)...")
        print("⏳ Image analysis typically takes 10-20 seconds...\n")
        
        # Collect events for Phase 2
        start_time = asyncio.get_event_loop().time()
        completed = False
        analysis_invoked = False
        
        while (asyncio.get_event_loop().time() - start_time) < IMAGE_ANALYSIS_TIMEOUT and not completed:
            try:
                event_str = await asyncio.wait_for(ws.recv(), timeout=5.0)
                event = json.loads(event_str)
                event_type = event.get('eventType') or event.get('type')
                
                # Check for analysis activity
                if event_type in ['outgoing_agent_message', 'remote_agent_activity', 'task_updated']:
                    event_str_lower = json.dumps(event).lower()
                    if 'image' in event_str_lower and ('analysis' in event_str_lower or 'vision' in event_str_lower):
                        analysis_invoked = True
                        print(f"   🔍 Image Analysis agent called")
                
                # Check for analysis results in multiple event formats
                if event_type == 'message':
                    # Check direct content array
                    content = event.get('content', [])
                    for item in content:
                        if isinstance(item, dict):
                            # Check both 'text' and 'content' fields (different event formats)
                            text = item.get('text', '') or item.get('content', '')
                            if text and len(text) > 100:
                                text_lower = text.lower()
                                # Look for analysis-related keywords
                                if any(kw in text_lower for kw in ['analysis', 'finding', 'key finding', 'primary object', 'environment', 'atmosphere']):
                                    analysis_text = text
                                    analysis_completed = True
                                    print(f"\n   ✅ ANALYSIS COMPLETED!")
                                    print(f"      Analysis preview: {text[:150]}...\n")
                    
                    # Also check message text directly
                    message_text = event.get('message', '')
                    if message_text and len(message_text) > 100 and not analysis_completed:
                        if 'analysis' in message_text.lower() or 'finding' in message_text.lower():
                            analysis_text = message_text
                            analysis_completed = True
                            print(f"\n   ✅ ANALYSIS COMPLETED!")
                            print(f"      Analysis preview: {message_text[:150]}...\n")
                
                # Check remote_agent_activity for analysis results
                if event_type == 'remote_agent_activity' and not analysis_completed:
                    activity_content = event.get('content', '')
                    if activity_content and len(activity_content) > 200:
                        if 'analysis' in activity_content.lower() or 'finding' in activity_content.lower():
                            analysis_text = activity_content
                            analysis_completed = True
                            print(f"\n   ✅ ANALYSIS COMPLETED!")
                            print(f"      Analysis preview: {activity_content[:150]}...\n")
                
                # Check for host completion - only exit if we have analysis
                if event_type == 'task_updated':
                    agent_name = event.get('agentName', '')
                    state = event.get('state')
                    if state == 'completed' and 'host' in agent_name.lower():
                        print(f"   ✅ Host agent completed")
                        # Only exit if we have analysis results
                        if analysis_completed:
                            print(f"   ✅ Have analysis results - finishing Phase 2")
                            await asyncio.sleep(1)
                            completed = True
                            break
                        else:
                            print(f"   ⏳ Waiting for analysis results...")
                        
            except asyncio.TimeoutError:
                continue
        
        print()
        print("=" * 60)
        print("PHASE 2 RESULTS")
        print("=" * 60)
        print(f"{'✅' if analysis_invoked else '❌'} Analysis invoked: {analysis_invoked}")
        print(f"{'✅' if analysis_completed else '❌'} Analysis completed: {analysis_completed}")
        if analysis_text:
            print(f"📝 Analysis preview: {analysis_text[:200]}...")
        print()
        
        # Final test results
        print("=" * 60)
        print("FINAL TEST RESULTS")
        print("=" * 60)
        print(f"✅ Phase 1 - Image generated: {bool(initial_image_uri)}")
        print(f"✅ Phase 2 - Image analyzed: {analysis_completed}")
        print()
        print(f"🖼️  Generated Image: {initial_image_uri}")
        if analysis_text:
            print(f"\n📝 Analysis Result:")
            print(f"   {analysis_text[:300]}{'...' if len(analysis_text) > 300 else ''}")
        print()
        
        if initial_image_uri and analysis_completed:
            print("✅ TEST PASSED: Complete image generation and analysis flow successful!")
            print("   - Image generated via Image Generator agent")
            print("   - Image sent to Image Analysis agent")
            print("   - Analysis results returned successfully")
            return True
        else:
            print("❌ TEST FAILED:")
            if not initial_image_uri:
                print("   - Image generation failed")
            if not analysis_completed:
                print("   - Image analysis failed")
            return False

if __name__ == "__main__":
    success = asyncio.run(test_image_generation_and_analysis())
    exit(0 if success else 1)
