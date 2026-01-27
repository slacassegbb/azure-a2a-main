#!/usr/bin/env python3
"""
Test Image Generation + Refinement Flow
========================================

This test validates the complete image refinement workflow:
1. Generate an initial image from a text prompt
2. Host orchestrator receives the image as a FilePart
3. Send a refinement request with the original image
4. Receive the refined image from the generator agent

This ensures the A2A protocol correctly handles:
- Initial image generation
- FilePart return with blob storage URIs
- Image-to-image refinement with text modifications
- Proper payload construction for refinement requests
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
IMAGE_GENERATION_TIMEOUT = 120  # Increased for DALL-E 3 generation time
IMAGE_REFINEMENT_TIMEOUT = 180  # Significantly increased for image editing (can take 90-120s)

async def test_image_refinement_flow():
    """Test the complete image generation and refinement workflow"""
    
    print("\n⚠️  Note: Image generation typically takes 30-60 seconds")
    print("⚠️  Image refinement also takes 30-60 seconds")
    print("⚠️  Make sure the Image Generator agent is running on port 9010")
    print()
    
    # Phase 1: Generate initial image
    print("=" * 60)
    print("PHASE 1: INITIAL IMAGE GENERATION")
    print("=" * 60)
    print()
    
    context_id = f"refine_test_{uuid.uuid4().hex[:8]}"
    message_id_1 = str(uuid.uuid4())
    initial_image_uri = None
    
    try:
        async with websockets.connect(
            WEBSOCKET_URL,
            ping_interval=20,
            ping_timeout=60,
            close_timeout=10
        ) as ws:
            print("📡 WebSocket connected")
            
            # Subscribe to context
            await ws.send(json.dumps({
                "type": "subscribe",
                "contextId": context_id
            }))
            
            # Phase 1: Generate initial image
            payload = {
                "params": {
                    "messageId": message_id_1,
                    "contextId": context_id,
                    "role": "user",
                    "parts": [
                        {
                            "root": {
                                "kind": "text",
                                "text": "Use the Image Generator agent to create a serene mountain landscape with a lake at sunset"
                            }
                        }
                    ],
                    "agentMode": True,
                    "enableInterAgentMemory": True
                }
            }
            
            print("📤 Sending initial image generation request...")
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(f"{BACKEND_URL}/message/send", json=payload)
                
                if response.status_code != 200:
                    print(f"❌ HTTP error: {response.status_code}")
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
                    
                    # Check for Image Generator agent activity
                    if event_type in ['outgoing_agent_message', 'remote_agent_activity', 'task_updated']:
                        event_str_lower = json.dumps(event).lower()
                        if 'image' in event_str_lower and ('generator' in event_str_lower or 'dall' in event_str_lower):
                            image_generated = True
                            print(f"   🎨 Image Generator agent called")
                    
                    # Check for file_uploaded event
                    if event_type == 'file_uploaded':
                        file_info = event
                        uri = file_info.get('uri', '')
                        mime = file_info.get('content_type', '')
                        
                        if 'image' in mime:
                            initial_image_uri = uri
                            print(f"\n   ✅ INITIAL IMAGE RETURNED!")
                            print(f"      URI: {uri[:100]}...\n")
                    
                    # Check for message with image
                    if event_type == 'message':
                        content_items = event.get('content', [])
                        for item in content_items:
                            if isinstance(item, dict) and item.get('type') == 'image':
                                initial_image_uri = item.get('uri', '')
                                print(f"\n   ✅ INITIAL IMAGE RETURNED!")
                                print(f"      URI: {initial_image_uri[:100]}...\n")
                    
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
            print(f"{'✅' if image_generated else '❌'} Initial image generated: {image_generated}")
            print(f"{'✅' if initial_image_uri else '❌'} Initial image returned: {bool(initial_image_uri)}")
            if initial_image_uri:
                print(f"🖼️  Image URI: {initial_image_uri[:100]}...")
            print()
            
            if not initial_image_uri:
                print("❌ PHASE 1 FAILED: No image URI received")
                return False
            
            # Phase 2: Refine the image
            print("=" * 60)
            print("PHASE 2: IMAGE REFINEMENT")
            print("=" * 60)
            print()
            
            await asyncio.sleep(2)
            
            message_id_2 = str(uuid.uuid4())
            refined_image_uri = None
            
            refinement_payload = {
                "params": {
                    "messageId": message_id_2,
                    "contextId": context_id,
                    "role": "user",
                    "parts": [
                        {
                            "root": {
                                "kind": "text",
                                "text": "Use the Image Generator agent to refine this image: make it more dramatic with darker clouds and golden sunset lighting"
                            }
                        },
                        {
                            "root": {
                                "kind": "file",
                                "file": {
                                    "uri": initial_image_uri,
                                    "name": "original_image.png",
                                    "mimeType": "image/png"
                                }
                            }
                        }
                    ],
                    "agentMode": True,
                    "enableInterAgentMemory": True
                }
            }
            
            print("📤 Sending image refinement request...")
            print(f"   Original image URI: {initial_image_uri[:80]}...")
            print()
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(f"{BACKEND_URL}/message/send", json=refinement_payload)
                
                if response.status_code != 200:
                    print(f"❌ Refinement request failed with status {response.status_code}")
                    print(response.text)
                    return False
            
            print(f"✅ Refinement request sent, collecting events (timeout: {IMAGE_REFINEMENT_TIMEOUT}s)...")
            print("⏳ Image refinement typically takes 30-60 seconds...\n")
            
            # Collect events for Phase 2
            start_time = asyncio.get_event_loop().time()
            completed = False
            refinement_invoked = False
            
            while (asyncio.get_event_loop().time() - start_time) < IMAGE_REFINEMENT_TIMEOUT and not completed:
                try:
                    event_str = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    event = json.loads(event_str)
                    event_type = event.get('eventType') or event.get('type')
                    
                    # Check for refinement activity
                    if event_type in ['outgoing_agent_message', 'remote_agent_activity', 'task_updated']:
                        event_str_lower = json.dumps(event).lower()
                        if 'image' in event_str_lower and ('generator' in event_str_lower or 'dall' in event_str_lower or 'refin' in event_str_lower):
                            refinement_invoked = True
                            print(f"   🎨 Image refinement invoked")
                    
                    # Check for refined image
                    if event_type == 'file_uploaded':
                        file_info = event
                        uri = file_info.get('uri', '')
                        mime = file_info.get('content_type', '')
                        
                        if 'image' in mime and uri != initial_image_uri:
                            refined_image_uri = uri
                            print(f"\n   ✅ REFINED IMAGE RETURNED!")
                            print(f"      URI: {uri[:100]}...\n")
                    
                    # Check for message with image
                    if event_type == 'message':
                        content_items = event.get('content', [])
                        for item in content_items:
                            if isinstance(item, dict) and item.get('type') == 'image':
                                uri = item.get('uri', '')
                                if uri != initial_image_uri:
                                    refined_image_uri = uri
                                    print(f"\n   ✅ REFINED IMAGE RETURNED!")
                                    print(f"      URI: {refined_image_uri[:100]}...\n")
                    
                    # Check for host completion - but only exit if we also have a refined image
                    if event_type == 'task_updated':
                        agent_name = event.get('agentName', '')
                        state = event.get('state')
                        if state == 'completed' and 'host' in agent_name.lower():
                            print(f"   ✅ Host agent completed")
                            # Only exit if we have a refined image, otherwise keep waiting
                            if refined_image_uri:
                                print(f"   ✅ Have refined image - finishing Phase 2")
                                await asyncio.sleep(1)
                                completed = True
                                break
                            else:
                                print(f"   ⏳ Waiting for refined image...")                            
                except asyncio.TimeoutError:
                    continue
            
            print()
            print("=" * 60)
            print("PHASE 2 RESULTS")
            print("=" * 60)
            print(f"{'✅' if refinement_invoked else '❌'} Refinement invoked: {refinement_invoked}")
            print(f"{'✅' if refined_image_uri else '❌'} Refined image returned: {bool(refined_image_uri)}")
            if refined_image_uri:
                print(f"🖼️  Refined Image URI: {refined_image_uri[:100]}...")
            print()
            
            # Final test results
            print("=" * 60)
            print("FINAL TEST RESULTS")
            print("=" * 60)
            print(f"✅ Phase 1 - Initial image generated: {bool(initial_image_uri)}")
            print(f"✅ Phase 2 - Image refinement completed: {bool(refined_image_uri)}")
            print()
            
            if initial_image_uri:
                print(f"🖼️  Original Image: {initial_image_uri}")
            if refined_image_uri:
                print(f"🖼️  Refined Image: {refined_image_uri}")
            print()
            
            # Determine overall success
            if initial_image_uri and refined_image_uri:
                print("✅ TEST PASSED: Complete image refinement flow successful!")
                print("   - Initial image generated and returned via FilePart")
                print("   - Image sent back to agent for refinement")
                print("   - Refined image returned via FilePart")
                return True
            else:
                print("❌ TEST FAILED:")
                if not initial_image_uri:
                    print("   - Initial image generation failed")
                if not refined_image_uri:
                    print("   - Image refinement failed")
                return False
    
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
    """Test the complete image generation and refinement workflow"""
    
    print("\n⚠️  Note: Image generation typically takes 30-60 seconds")
    print("⚠️  Image refinement also takes 30-60 seconds")
    print("⚠️  Make sure the Image Generator agent is running on port 9010")
    print()
    
    # Phase 1: Generate initial image
    print("=" * 60)
    print("PHASE 1: INITIAL IMAGE GENERATION")
    print("=" * 60)
    print()
    
    initial_image_uri = None
    generation_task_id = None
    
    try:
        # Configure WebSocket with ping settings
        async with websockets.connect(
            WEBSOCKET_URL,
            ping_interval=20,
            ping_timeout=60,
            close_timeout=10
        ) as websocket:
            print("📡 WebSocket connected")
            
            # Subscribe to context updates
            context_id = "test_refinement_context"
            subscribe_msg = {
                "type": "subscribe",
                "contextId": context_id
            }
            await websocket.send(json.dumps(subscribe_msg))
            
            # Phase 1: Generate initial image
            async with httpx.AsyncClient(timeout=IMAGE_GENERATION_TIMEOUT) as client:
                message_id = str(asyncio.get_event_loop().time())
                context_id = "test_refinement_context"
                
                payload = {
                    "params": {
                        "messageId": message_id,
                        "contextId": context_id,
                        "role": "user",
                        "parts": [
                            {
                                "root": {
                                    "kind": "text",
                                    "text": "Use the Image Generator agent to generate an image of a serene mountain landscape with a lake at sunset"
                                }
                            }
                        ],
                        "agentMode": True,
                        "enableInterAgentMemory": False
                    }
                }
                
                print("📤 Sending initial image generation request...")
                response = await client.post(f"{BACKEND_URL}/message/send", json=payload)
                
                if response.status_code != 200:
                    print(f"❌ Request failed with status {response.status_code}")
                    print(f"Response: {response.text}")
                    return False
                
                print("✅ Request sent, collecting events (timeout: 90s)...")
                print("⏳ Image generation typically takes 30-60 seconds...")
                print()
                
                # Collect events for Phase 1
                image_generated = False
                image_returned = False
                start_time = asyncio.get_event_loop().time()
                completed = False
                
                while (asyncio.get_event_loop().time() - start_time) < IMAGE_GENERATION_TIMEOUT and not completed:
                    try:
                        event_str = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                        event = json.loads(event_str)
                        event_type = event.get('eventType') or event.get('type')
                        
                        # Check for Image Generator agent activity
                        event_str_lower = json.dumps(event).lower()
                        if 'image' in event_str_lower and ('generator' in event_str_lower or 'dall' in event_str_lower):
                            print(f"   🎨 Image Generator agent called")
                            image_generated = True
                        
                        # Check for image FilePart return
                        if event_type == 'message':
                            data = event.get('data', {})
                            content = data.get('content', [])
                            
                            for part in content:
                                if part.get('type') == 'image' and part.get('uri'):
                                    initial_image_uri = part.get('uri')
                                    print()
                                    print(f"   ✅ INITIAL IMAGE RETURNED!")
                                    print(f"      URI: {initial_image_uri[:100]}...")
                                    print()
                                    image_returned = True
                                    completed = True
                                    break
                    
                    except asyncio.TimeoutError:
                        # Just continue waiting
                        continue
                    except Exception as e:
                        print(f"⚠️  Error: {e}")
                        break
            
            print()
            print("=" * 60)
            print("PHASE 1 RESULTS")
            print("=" * 60)
            print(f"✅ Initial image generated: {image_generated}")
            print(f"✅ Initial image returned: {image_returned}")
            if initial_image_uri:
                print(f"🖼️  Image URI: {initial_image_uri[:100]}...")
            print()
            
            if not initial_image_uri:
                print("❌ PHASE 1 FAILED: No image URI received")
                return False
            
            # Phase 2: Refine the image
            print("=" * 60)
            print("PHASE 2: IMAGE REFINEMENT")
            print("=" * 60)
            print()
            
            # Wait a moment before starting refinement
            await asyncio.sleep(2)
            
            async with httpx.AsyncClient(timeout=IMAGE_REFINEMENT_TIMEOUT) as client:
                # Construct refinement payload with image attached as FilePart
                message_id_2 = str(asyncio.get_event_loop().time() + 1000)
                
                refinement_payload = {
                    "params": {
                        "messageId": message_id_2,
                        "contextId": context_id,
                        "role": "user",
                        "parts": [
                            {
                                "root": {
                                    "kind": "text",
                                    "text": "Use the Image Generator agent to refine this image: make it more dramatic with darker clouds and golden sunset lighting"
                                }
                            },
                            {
                                "root": {
                                    "kind": "file",
                                    "uri": initial_image_uri,
                                    "name": "original_image.png",
                                    "mimeType": "image/png"
                                }
                            }
                        ],
                        "agentMode": True,
                        "enableInterAgentMemory": False
                    }
                }
                
                print("📤 Sending image refinement request...")
                print(f"   Original image URI: {initial_image_uri[:80]}...")
                print(f"   Refinement prompt: Refine with darker clouds and golden sunset lighting")
                print()
                
                response = await client.post(f"{BACKEND_URL}/message/send", json=refinement_payload)
                
                if response.status_code != 200:
                    print(f"❌ Refinement request failed with status {response.status_code}")
                    print(f"Response: {response.text}")
                    return False
                
                print("✅ Refinement request sent, collecting events (timeout: 90s)...")
                print("⏳ Image refinement typically takes 30-60 seconds...")
                print()
                
                # Collect events for Phase 2
                refined_image_uri = None
                refinement_invoked = False
                refinement_returned = False
                start_time = asyncio.get_event_loop().time()
                
                while True:
                    try:
                        message = await asyncio.wait_for(
                            websocket.recv(),
                            timeout=IMAGE_REFINEMENT_TIMEOUT
                        )
                        event_data = json.loads(message)
                        
                        # Check for timeout
                        elapsed = asyncio.get_event_loop().time() - start_time
                        if elapsed > IMAGE_REFINEMENT_TIMEOUT:
                            print(f"⏱️  Timeout reached ({IMAGE_REFINEMENT_TIMEOUT}s)")
                            break
                        
                        event_type = event_data.get("type", "")
                        event_name = event_data.get("event", "")
                        data = event_data.get("data", {})
                        
                        # Look for image refinement events
                        if event_type == "agent_event":
                            agent_name = data.get("agent_name", "").lower()
                            message_text = data.get("message", "").lower()
                            
                            if "image" in agent_name or "image" in message_text:
                                if any(word in message_text for word in ["refine", "edit", "modify", "generator", "dall"]):
                                    print(f"   🎨 Image refinement invoked: {data.get('message', '')[:100]}...")
                                    refinement_invoked = True
                        
                        # Look for status updates
                        if event_type == "status_update":
                            status = data.get("status", "")
                            message_text = data.get("message", "")
                            if "image" in message_text.lower() or "refin" in message_text.lower():
                                print(f"   🖼️  {message_text[:100]}...")
                        
                        # Look for message events with refined image FilePart
                        if event_name == "message":
                            content = data.get("content", [])
                            print(f"   📨 Received message event with {len(content)} content items")
                            
                            for idx, part in enumerate(content):
                                part_type = part.get("type", "")
                                print(f"      Content {idx}: type={part_type}")
                                
                                if part_type == "image":
                                    image_uri = part.get("uri", "")
                                    # Make sure it's a different image than the original
                                    if image_uri and image_uri != initial_image_uri:
                                        print()
                                        print(f"   ✅ REFINED IMAGE RETURNED!")
                                        print(f"      Type: {part_type}")
                                        print(f"      URI: {image_uri[:100]}...")
                                        print()
                                        refined_image_uri = image_uri
                                        refinement_returned = True
                        
                        # Check if host agent completed
                        if event_type == "agent_completed":
                            agent_name = data.get("agent_name", "")
                            if agent_name.lower() == "host":
                                print("   ✅ Host agent completed - finishing Phase 2")
                                break
                    
                    except asyncio.TimeoutError:
                        print("⏱️  WebSocket timeout")
                        break
                    except Exception as e:
                        print(f"⚠️  Error receiving event: {e}")
                        break
            
            print()
            print("=" * 60)
            print("PHASE 2 RESULTS")
            print("=" * 60)
            print(f"✅ Refinement invoked: {refinement_invoked}")
            print(f"✅ Refined image returned: {refinement_returned}")
            if refined_image_uri:
                print(f"🖼️  Refined Image URI: {refined_image_uri[:100]}...")
            print()
            
            # Final test results
            print("=" * 60)
            print("FINAL TEST RESULTS")
            print("=" * 60)
            print(f"✅ Phase 1 - Initial image generated: {image_returned}")
            print(f"✅ Phase 2 - Image refinement completed: {refinement_returned}")
            print()
            
            if initial_image_uri:
                print(f"🖼️  Original Image: {initial_image_uri}")
            if refined_image_uri:
                print(f"🖼️  Refined Image: {refined_image_uri}")
            print()
            
            # Determine overall success
            if image_returned and refinement_returned:
                print("✅ TEST PASSED: Complete image refinement flow successful!")
                print("   - Initial image generated and returned via FilePart")
                print("   - Image sent back to agent for refinement")
                print("   - Refined image returned via FilePart")
                return True
            else:
                print("❌ TEST FAILED:")
                if not image_returned:
                    print("   - Initial image generation failed")
                if not refinement_returned:
                    print("   - Image refinement failed")
                return False
    
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print()
    print("=" * 60)
    print("TESTING IMAGE GENERATION & REFINEMENT FLOW")
    print("=" * 60)
    print()
    
    success = asyncio.run(test_image_refinement_flow())
    exit(0 if success else 1)

