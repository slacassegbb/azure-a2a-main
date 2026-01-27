#!/usr/bin/env python3
"""
Test image generation and file exchange with Image Generator agent.
Verifies that:
1. Image generation requests work via A2A protocol
2. Generated images are returned as FilePart with proper URI
3. Blob storage integration works for image files
4. Multiple images can be generated and returned
"""
import asyncio
import httpx
import json
import websockets
import uuid
from pathlib import Path

# Local development URLs
BACKEND_URL = "http://localhost:12000"
WEBSOCKET_URL = "ws://localhost:8080/events"
IMAGE_GENERATION_TIMEOUT = 180  # 3 minutes - Images can take longer with DALL-E 3


async def test_image_generation():
    """Test image generation and file exchange."""
    
    print("\n" + "="*60)
    print("TESTING IMAGE GENERATION & FILE EXCHANGE")
    print("="*60 + "\n")
    
    context_id = f"image_test_{uuid.uuid4().hex[:8]}"
    message_id = str(uuid.uuid4())
    events_received = []
    image_agent_invoked = False
    image_file_returned = False
    image_uri = None
    image_count = 0
    
    try:
        # Configure WebSocket with longer ping interval for cloud deployment
        async with websockets.connect(
            WEBSOCKET_URL,
            ping_interval=20,  # Send ping every 20 seconds
            ping_timeout=60,   # Wait 60 seconds for pong
            close_timeout=10
        ) as ws:
            print("📡 WebSocket connected")
            
            # Subscribe to context
            await ws.send(json.dumps({
                "type": "subscribe",
                "contextId": context_id
            }))
            
            # Build image generation request
            payload = {
                "params": {
                    "messageId": message_id,
                    "contextId": context_id,
                    "role": "user",
                    "parts": [
                        {
                            "root": {
                                "kind": "text",
                                "text": "Use the Image Generator agent to create a beautiful landscape image of a serene mountain lake at sunset with vibrant orange and pink skies reflecting on the water."
                            }
                        }
                    ],
                    "agentMode": True,
                    "enableInterAgentMemory": True
                }
            }
            
            # Send message via HTTP
            print("📤 Sending image generation request...")
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(f"{BACKEND_URL}/message/send", json=payload)
                
                if response.status_code != 200:
                    print(f"❌ HTTP error: {response.status_code}")
                    print(response.text)
                    return False
            
            print(f"✅ Request sent, collecting events (timeout: {IMAGE_GENERATION_TIMEOUT}s)...")
            print("⏳ Image generation typically takes 30-60 seconds...\n")
            
            # Collect events
            start_time = asyncio.get_event_loop().time()
            completed = False
            
            while (asyncio.get_event_loop().time() - start_time) < IMAGE_GENERATION_TIMEOUT and not completed:
                try:
                    event_str = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    event = json.loads(event_str)
                    event_type = event.get('eventType') or event.get('type')
                    events_received.append(event)
                    
                    # Check for Image Generator agent activity
                    if event_type in ['outgoing_agent_message', 'remote_agent_activity', 'task_updated']:
                        event_str_lower = json.dumps(event).lower()
                        if 'image' in event_str_lower and ('generator' in event_str_lower or 'dall' in event_str_lower or 'dalle' in event_str_lower):
                            image_agent_invoked = True
                            if event_type == 'outgoing_agent_message':
                                print(f"   🎨 Image Generator agent called: {event.get('message', '')[:80]}...")
                            elif event_type == 'remote_agent_activity':
                                content = event.get('content', '')
                                if content:
                                    print(f"   🖼️  {content[:100]}...")
                    
                    # Check for file_uploaded event (this is how FileParts are sent to WebSocket)
                    if event_type == 'file_uploaded':
                        print(f"\n   📤 FILE UPLOADED EVENT RECEIVED!")
                        file_info = event
                        uri = file_info.get('uri', '')
                        filename = file_info.get('filename', '')
                        mime = file_info.get('content_type', '')
                        source_agent = file_info.get('source_agent', '')
                        
                        print(f"      Filename: {filename}")
                        print(f"      MIME: {mime}")
                        print(f"      Source: {source_agent}")
                        print(f"      URI: {uri[:80]}..." if len(uri) > 80 else f"      URI: {uri}")
                        
                        # Check if it's an image file
                        if 'image' in mime or any(ext in filename.lower() for ext in ['.png', '.jpg', '.jpeg', '.webp']):
                            image_file_returned = True
                            image_uri = uri
                            image_count += 1
                            print(f"\n   ✅ IMAGE FILE #{image_count} RETURNED VIA FILE_UPLOADED EVENT!")
                    
                    # Check for message with FilePart (image returned)
                    if event_type == 'message':
                        # message events have 'content' array, not 'data.parts'
                        content_items = event.get('content', [])
                        
                        if content_items:
                            print(f"   📨 Received message event with {len(content_items)} content items")
                        
                        for idx, item in enumerate(content_items):
                            # Check for image content
                            if isinstance(item, dict):
                                item_type = item.get('type', '')
                                print(f"      Content {idx}: type={item_type}")
                                
                                # Check for image type content
                                if item_type == 'image':
                                    uri = item.get('uri', '')
                                    image_file_returned = True
                                    image_uri = uri
                                    image_count += 1
                                    print(f"\n   ✅ IMAGE FILE #{image_count} RETURNED!")
                                    print(f"      Type: {item_type}")
                                    print(f"      URI: {uri[:80]}..." if len(uri) > 80 else f"      URI: {uri}")
                                
                                # Also check for FilePart format (standard A2A format)
                                file_info = item.get('file')
                                if file_info and isinstance(file_info, dict):
                                    uri = file_info.get('uri', '')
                                    mime = file_info.get('mimeType', '')
                                    name = file_info.get('name', '')
                                    
                                    print(f"         FilePart: name={name}, mime={mime}")
                                    
                                    if 'image' in mime or any(ext in name.lower() for ext in ['.png', '.jpg', '.jpeg', '.webp']):
                                        image_file_returned = True
                                        image_uri = uri
                                        image_count += 1
                                        print(f"\n   ✅ IMAGE FILE #{image_count} RETURNED!")
                                        print(f"      Name: {name}")
                                        print(f"      MIME: {mime}")
                                        print(f"      URI: {uri[:80]}...")
                    
                    # Check for completion with artifacts in task_updated
                    if event_type == 'task_updated':
                        state = event.get('state')
                        artifacts_count = event.get('artifactsCount', 0)
                        content = event.get('content')
                        
                        if artifacts_count > 0:
                            print(f"   📦 Task has {artifacts_count} artifacts")
                        
                        # Check for image URL in content
                        if content and isinstance(content, str):
                            if 'blob.core.windows.net' in content:
                                import re
                                # Look for image URLs (png, jpg, jpeg, webp)
                                urls = re.findall(r'https://[^\s\)]+\.(png|jpg|jpeg|webp)[^\s\)]*', content, re.IGNORECASE)
                                if urls:
                                    image_file_returned = True
                                    image_uri = urls[0][0]  # urls is list of tuples (url, extension)
                                    image_count = len(urls)
                                    print(f"\n   ✅ {image_count} IMAGE URL(S) FOUND IN CONTENT!")
                                    print(f"      First URI: {image_uri[:80]}...")
                        
                        if state == 'completed':
                            agent_name = event.get('agentName', '')
                            if 'image' in agent_name.lower() and 'generator' in agent_name.lower():
                                print(f"\n   ✅ Image generation completed!")
                                # Don't break immediately - wait for message events with FileParts
                                print(f"   ⏳ Waiting for final message with FilePart...")
                        elif state == 'failed':
                            print(f"\n   ❌ Task failed: {event.get('error', 'Unknown error')}")
                            completed = True
                            break
                    
                    # Check for host-agent completion (this is AFTER image agent finishes)
                    if event_type == 'task_updated':
                        agent_name = event.get('agentName', '')
                        state = event.get('state')
                        if state == 'completed' and 'host' in agent_name.lower():
                            print(f"\n   ✅ Host agent completed - finishing collection")
                            # Wait a bit more to collect any final events
                            await asyncio.sleep(2)
                            completed = True
                            break
                            
                except asyncio.TimeoutError:
                    continue
            
            if not completed and (asyncio.get_event_loop().time() - start_time) >= IMAGE_GENERATION_TIMEOUT:
                print(f"\n   ⏱️ Timeout reached ({IMAGE_GENERATION_TIMEOUT}s)")
                    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Analyze results
    print("\n" + "="*60)
    print("TEST RESULTS")
    print("="*60)
    print(f"✅ Request sent successfully")
    print(f"{'✅' if image_agent_invoked else '❌'} Image Generator agent invoked: {image_agent_invoked}")
    print(f"{'✅' if image_file_returned else '❌'} Image FilePart returned: {image_file_returned}")
    print(f"📊 Number of images returned: {image_count}")
    
    if image_uri:
        print(f"\n🖼️  Image URI: {image_uri}")
    
    print(f"\n📊 Total events received: {len(events_received)}")
    
    # Test passes if image agent was invoked and returned at least one file
    success = image_agent_invoked and image_file_returned and image_count > 0
    
    if success:
        print(f"\n✅ TEST PASSED: Image Generator agent successfully generated and returned {image_count} image(s)!")
    else:
        print("\n❌ TEST FAILED")
        if not image_agent_invoked:
            print("   - Image Generator agent was not invoked")
        if not image_file_returned:
            print("   - Image FilePart was not returned")
        if image_count == 0:
            print("   - No images were generated")
        
        print("\n📋 Event types received:")
        event_types = {}
        for event in events_received:
            et = event.get('eventType') or event.get('type', 'unknown')
            event_types[et] = event_types.get(et, 0) + 1
        for et, count in sorted(event_types.items()):
            print(f"   - {et}: {count}")
    
    return success


if __name__ == "__main__":
    print("\n⚠️  Note: Image generation typically takes 30-60 seconds")
    print("⚠️  Make sure the Image Generator agent is running on port 9010\n")
    
    result = asyncio.run(test_image_generation())
    exit(0 if result else 1)
