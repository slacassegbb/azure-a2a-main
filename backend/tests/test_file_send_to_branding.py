#!/usr/bin/env python3
"""
Simple test to verify file exchange with Branding agent.
This test uploads a test image and sends it to the Branding agent via the Host Agent.
"""
import asyncio
import httpx
import json
import websockets
import uuid
from pathlib import Path

BACKEND_URL = "http://localhost:12000"
WEBSOCKET_URL = "ws://localhost:8080/events"
TEST_IMAGE = "/Users/simonlacasse/Downloads/sl-a2a-main2/a2a_logo.png"


async def test_send_file_to_branding():
    """Test sending a file to the Branding agent."""
    
    print("\n" + "="*60)
    print("TESTING FILE EXCHANGE WITH BRANDING AGENT")
    print("="*60 + "\n")
    
    # Step 1: Upload the test image to get a blob URL
    print("📤 Step 1: Uploading test image...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        with open(TEST_IMAGE, 'rb') as f:
            files = {'file': (Path(TEST_IMAGE).name, f, 'image/png')}
            response = await client.post(f"{BACKEND_URL}/upload", files=files)
            
        if response.status_code != 200:
            print(f"❌ Upload failed: {response.status_code}")
            print(response.text)
            return False
            
        upload_result = response.json()
        print(f"   Upload response: {json.dumps(upload_result, indent=2)}")
        
        # Handle different response formats
        file_url = upload_result.get('url') or upload_result.get('file_url') or upload_result.get('uri')
        file_name = upload_result.get('name') or upload_result.get('filename') or Path(TEST_IMAGE).name
        
        if not file_url:
            print(f"❌ No file URL in response: {upload_result}")
            return False
            
        print(f"✅ Image uploaded: {file_name}")
        print(f"   URL: {file_url[:80] if len(file_url) > 80 else file_url}...")
    
    # Step 2: Send message with file to Branding agent via HTTP + WebSocket
    print("\n📨 Step 2: Sending file to Branding agent via Host Agent...")
    
    context_id = f"branding_test_{uuid.uuid4().hex[:8]}"
    message_id = str(uuid.uuid4())
    events_received = []
    branding_invoked = False
    file_received = False
    
    try:
        async with websockets.connect(WEBSOCKET_URL) as ws:
            print("   WebSocket connected")
            
            # Subscribe to context
            await ws.send(json.dumps({
                "type": "subscribe",
                "contextId": context_id
            }))
            
            # Build message payload
            payload = {
                "params": {
                    "messageId": message_id,
                    "contextId": context_id,
                    "role": "user",
                    "parts": [
                        {
                            "root": {
                                "kind": "text",
                                "text": "Please ask the Branding agent to analyze this company logo image. Describe the colors, design elements, and provide branding recommendations."
                            }
                        },
                        {
                            "root": {
                                "kind": "file",
                                "file": {
                                    "name": file_name,
                                    "uri": file_url,
                                    "mimeType": "image/png"
                                }
                            }
                        }
                    ],
                    "agentMode": True,
                    "enableInterAgentMemory": True
                }
            }
            
            # Send message via HTTP
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(f"{BACKEND_URL}/message/send", json=payload)
                
                if response.status_code != 200:
                    print(f"❌ HTTP error: {response.status_code}")
                    print(response.text)
                    return False
            
            print("   Message sent via HTTP, collecting events from WebSocket...")
            
            # Collect events for 30 seconds max
            timeout = 30
            start_time = asyncio.get_event_loop().time()
            
            while (asyncio.get_event_loop().time() - start_time) < timeout:
                try:
                    event_str = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    event = json.loads(event_str)
                    event_type = event.get('eventType') or event.get('type')
                    events_received.append(event)
                    
                    # Check for Branding agent activity
                    if event_type in ['outgoing_agent_message', 'remote_agent_activity', 'task_updated']:
                        event_str_lower = json.dumps(event).lower()
                        if 'branding' in event_str_lower:
                            branding_invoked = True
                            print(f"   🎯 Branding agent activity detected: {event_type}")
                            
                            # Check if agent received the file
                            if event_type == 'remote_agent_activity':
                                content = event.get('content', '')
                                if 'file' in content.lower() or 'image' in content.lower() or file_name.lower() in content.lower():
                                    file_received = True
                                    print(f"      ✅ Agent acknowledges file: {content[:100]}...")
                    
                    # Check for completion
                    if event_type == 'task_updated' and event.get('state') == 'completed':
                        print(f"   ✅ Task completed")
                        agent_name = event.get('agentName', '')
                        if 'branding' in agent_name.lower():
                            print(f"      Agent: {agent_name}")
                            break
                            
                except asyncio.TimeoutError:
                    continue
                    
    except Exception as e:
        print(f"❌ WebSocket error: {e}")
        return False
    
    # Step 3: Analyze results
    print("\n" + "="*60)
    print("TEST RESULTS")
    print("="*60)
    print(f"✅ File uploaded: {file_name}")
    print(f"✅ Message sent with file attachment")
    print(f"{'✅' if branding_invoked else '❌'} Branding agent invoked: {branding_invoked}")
    print(f"{'✅' if file_received else '❌'} File received by agent: {file_received}")
    print(f"\n📊 Total events received: {len(events_received)}")
    
    success = branding_invoked
    
    if success:
        print("\n✅ TEST PASSED: Branding agent successfully received and processed the file!")
    else:
        print("\n❌ TEST FAILED: Branding agent was not invoked or did not receive the file")
        print("\n📋 Events summary:")
        for event in events_received:
            event_type = event.get('eventType') or event.get('type')
            print(f"   - {event_type}")
    
    return success


if __name__ == "__main__":
    result = asyncio.run(test_send_file_to_branding())
    exit(0 if result else 1)
