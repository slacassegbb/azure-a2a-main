#!/usr/bin/env python3
"""
Test video generation and file exchange with Video agent.
Verifies that:
1. Video generation requests work via A2A protocol
2. Generated videos are returned as FilePart with proper URI
3. Video metadata (video_id) is included for remix capability
4. Blob storage integration works for video files
"""
import asyncio
import httpx
import json
import websockets
import uuid
from pathlib import Path

BACKEND_URL = "http://localhost:12000"
WEBSOCKET_URL = "ws://localhost:8080/events"
VIDEO_GENERATION_TIMEOUT = 180  # Videos take longer than images


async def test_video_generation():
    """Test video generation and file exchange."""
    
    print("\n" + "="*60)
    print("TESTING VIDEO GENERATION & FILE EXCHANGE")
    print("="*60 + "\n")
    
    context_id = f"video_test_{uuid.uuid4().hex[:8]}"
    message_id = str(uuid.uuid4())
    events_received = []
    video_agent_invoked = False
    video_file_returned = False
    video_id_found = None
    video_uri = None
    
    try:
        async with websockets.connect(WEBSOCKET_URL) as ws:
            print("📡 WebSocket connected")
            
            # Subscribe to context
            await ws.send(json.dumps({
                "type": "subscribe",
                "contextId": context_id
            }))
            
            # Build video generation request
            payload = {
                "params": {
                    "messageId": message_id,
                    "contextId": context_id,
                    "role": "user",
                    "parts": [
                        {
                            "root": {
                                "kind": "text",
                                "text": "Use the Sora 2 Video Generator agent to generate a 5-second video of a golden retriever puppy playing in a sunny garden with colorful flowers."
                            }
                        }
                    ],
                    "agentMode": True,
                    "enableInterAgentMemory": True
                }
            }
            
            # Send message via HTTP
            print("📤 Sending video generation request...")
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(f"{BACKEND_URL}/message/send", json=payload)
                
                if response.status_code != 200:
                    print(f"❌ HTTP error: {response.status_code}")
                    print(response.text)
                    return False
            
            print(f"✅ Request sent, collecting events (timeout: {VIDEO_GENERATION_TIMEOUT}s)...")
            print("⏳ Video generation typically takes 1-3 minutes...\n")
            
            # Collect events
            start_time = asyncio.get_event_loop().time()
            completed = False
            
            while (asyncio.get_event_loop().time() - start_time) < VIDEO_GENERATION_TIMEOUT and not completed:
                try:
                    event_str = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    event = json.loads(event_str)
                    event_type = event.get('eventType') or event.get('type')
                    events_received.append(event)
                    
                    # Check for Video agent activity
                    if event_type in ['outgoing_agent_message', 'remote_agent_activity', 'task_updated']:
                        event_str_lower = json.dumps(event).lower()
                        if 'video' in event_str_lower and ('generator' in event_str_lower or 'sora' in event_str_lower):
                            video_agent_invoked = True
                            if event_type == 'outgoing_agent_message':
                                print(f"   🎬 Video agent called: {event.get('message', '')[:80]}...")
                            elif event_type == 'remote_agent_activity':
                                content = event.get('content', '')
                                if content:
                                    print(f"   📹 {content[:100]}...")
                    
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
                        
                        # Check if it's a video file
                        if 'video' in mime or '.mp4' in filename.lower():
                            video_file_returned = True
                            video_uri = uri
                            print(f"\n   ✅ VIDEO FILE RETURNED VIA FILE_UPLOADED EVENT!")
                    
                    # Check for message with FilePart (video returned)
                    if event_type == 'message':
                        # message events have 'content' array, not 'data.parts'
                        content_items = event.get('content', [])
                        
                        if content_items:
                            print(f"   📨 Received message event with {len(content_items)} content items")
                        
                        for idx, item in enumerate(content_items):
                            # Check for video/image content
                            if isinstance(item, dict):
                                item_type = item.get('type', '')
                                print(f"      Content {idx}: type={item_type}")
                                
                                # Check for video type content
                                if item_type == 'video':
                                    uri = item.get('uri', '')
                                    video_file_returned = True
                                    video_uri = uri
                                    print(f"\n   ✅ VIDEO FILE RETURNED!")
                                    print(f"      Type: {item_type}")
                                    print(f"      URI: {uri[:80]}..." if len(uri) > 80 else f"      URI: {uri}")
                                    
                                    # Check for video_id metadata
                                    if item.get('videoId'):
                                        video_id_found = item.get('videoId')
                                        print(f"      Video ID: {video_id_found}")
                                
                                # Check for image type (in case videos are sent as image type)
                                elif item_type == 'image':
                                    uri = item.get('uri', '')
                                    if '.mp4' in uri.lower() or 'video' in uri.lower():
                                        video_file_returned = True
                                        video_uri = uri
                                        print(f"\n   ✅ VIDEO FILE RETURNED (as image type)!")
                                        print(f"      URI: {uri[:80]}..." if len(uri) > 80 else f"      URI: {uri}")
                                
                                # Also check for FilePart format (legacy)
                                file_info = item.get('file')
                                if file_info and isinstance(file_info, dict):
                                    uri = file_info.get('uri', '')
                                    mime = file_info.get('mimeType', '')
                                    name = file_info.get('name', '')
                                    
                                    print(f"         FilePart: name={name}, mime={mime}")
                                    
                                    if 'video' in mime or '.mp4' in name:
                                        video_file_returned = True
                                        video_uri = uri
                                        print(f"\n   ✅ VIDEO FILE RETURNED!")
                                        print(f"      Name: {name}")
                                        print(f"      MIME: {mime}")
                                        print(f"      URI: {uri[:80]}...")
                                
                                # Check for DataPart with video_id
                                data_info = item.get('data')
                                if data_info and isinstance(data_info, dict):
                                    if data_info.get('type') == 'video_metadata':
                                        video_id_found = data_info.get('video_id')
                                        print(f"   📎 Video metadata found:")
                                        print(f"      video_id: {video_id_found}")
                                        print(f"      generation_id: {data_info.get('generation_id')}")
                    
                    # Check for completion with artifacts in task_updated
                    if event_type == 'task_updated':
                        state = event.get('state')
                        artifacts_count = event.get('artifactsCount', 0)
                        content = event.get('content')
                        
                        if artifacts_count > 0:
                            print(f"   📦 Task has {artifacts_count} artifacts")
                        
                        # Check for video URL in content
                        if content and isinstance(content, str):
                            if 'blob.core.windows.net' in content and ('.mp4' in content or 'video' in content.lower()):
                                video_file_returned = True
                                # Extract URL from content
                                import re
                                urls = re.findall(r'https://[^\s\)]+\.mp4[^\s\)]*', content)
                                if urls:
                                    video_uri = urls[0]
                                    print(f"\n   ✅ VIDEO URL FOUND IN CONTENT!")
                                    print(f"      URI: {video_uri[:80]}...")
                            
                            # Check for video_id in content
                            if 'task_' in content:
                                match = re.search(r'task_[a-z0-9]+', content)
                                if match:
                                    video_id_found = match.group(0)
                                    print(f"   🆔 Video ID found: {video_id_found}")
                        
                        if state == 'completed':
                            agent_name = event.get('agentName', '')
                            if 'video' in agent_name.lower() or 'sora' in agent_name.lower():
                                print(f"\n   ✅ Video generation completed!")
                                # Don't break immediately - wait for message events with FileParts
                                # The final message with FilePart comes AFTER the task_updated
                                print(f"   ⏳ Waiting for final message with FilePart...")
                                # Continue collecting events for a few more seconds
                        elif state == 'failed':
                            print(f"\n   ❌ Task failed: {event.get('error', 'Unknown error')}")
                            completed = True
                            break
                    
                    # Check for host-agent completion (this is AFTER video agent finishes)
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
            
            if not completed and (asyncio.get_event_loop().time() - start_time) >= VIDEO_GENERATION_TIMEOUT:
                print(f"\n   ⏱️ Timeout reached ({VIDEO_GENERATION_TIMEOUT}s)")
                    
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
    print(f"{'✅' if video_agent_invoked else '❌'} Video agent invoked: {video_agent_invoked}")
    print(f"{'✅' if video_file_returned else '❌'} Video FilePart returned: {video_file_returned}")
    print(f"{'✅' if video_id_found else '❌'} Video ID metadata included: {'Yes' if video_id_found else 'No'}")
    
    if video_uri:
        print(f"\n📹 Video URI: {video_uri}")
    if video_id_found:
        print(f"🆔 Video ID: {video_id_found}")
    
    print(f"\n📊 Total events received: {len(events_received)}")
    
    # Test passes if video agent was invoked and returned a file
    success = video_agent_invoked and video_file_returned and video_id_found
    
    if success:
        print("\n✅ TEST PASSED: Video agent successfully generated and returned video with metadata!")
    else:
        print("\n❌ TEST FAILED")
        if not video_agent_invoked:
            print("   - Video agent was not invoked")
        if not video_file_returned:
            print("   - Video FilePart was not returned")
        if not video_id_found:
            print("   - Video ID metadata was not included")
        
        print("\n📋 Event types received:")
        event_types = {}
        for event in events_received:
            et = event.get('eventType') or event.get('type', 'unknown')
            event_types[et] = event_types.get(et, 0) + 1
        for et, count in sorted(event_types.items()):
            print(f"   - {et}: {count}")
    
    return success


if __name__ == "__main__":
    print("\n⚠️  Note: Video generation can take 1-3 minutes")
    print("⚠️  Make sure the Video Generator agent is running on port 9028\n")
    
    result = asyncio.run(test_video_generation())
    exit(0 if result else 1)
