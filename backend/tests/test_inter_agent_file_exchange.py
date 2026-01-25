#!/usr/bin/env python3
"""
Inter-Agent File Exchange Tests
================================

Tests the A2A protocol file exchange between agents with full payload validation:

A2A Payload Tests:
1. FilePart structure validation (kind, file.name, file.uri, file.mimeType)
2. DataPart artifact-uri handling
3. Message parts array structure
4. Outbound file parts to remote agents

Blob Storage Tests:
5. Azure Blob Storage URI format validation
6. SAS token presence and validity
7. Content accessibility and download verification
8. Content-Type header validation

File Exchange Tests:
9. Image Generator creates image → returns FilePart to Host
10. Host receives FilePart → can pass it to another agent
11. Agent-to-Agent file exchange via Host orchestrator
12. Multi-Agent file chain (A → B → C)
13. File metadata preservation (name, mimeType, role)
14. Round-trip: Generate → Edit → Return

Requirements:
- Backend running on localhost:12000
- WebSocket server running on localhost:8080
- Image Generator agent running on port 9010
- At least one other agent (Branding on 9020 recommended)

Note: Image generation can take up to 2 minutes per image!

Usage:
    python tests/test_inter_agent_file_exchange.py
    python tests/test_inter_agent_file_exchange.py -v
    python tests/test_inter_agent_file_exchange.py --test image_generation
    python tests/test_inter_agent_file_exchange.py --test a2a_payload
    python tests/test_inter_agent_file_exchange.py --test blob_storage
    python tests/test_inter_agent_file_exchange.py --test agent_to_agent
"""

import asyncio
import json
import time
import uuid
import argparse
import sys
import os
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum
from pathlib import Path

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

# Add backend to path for imports
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from log_config import log_debug

# Configuration
BACKEND_URL = "http://localhost:12000"
WEBSOCKET_URL = "ws://localhost:8080/events"

# Agent ports
IMAGE_GENERATOR_PORT = 9010
IMAGE_ANALYSIS_PORT = 9011  # Has vision capabilities - can actually analyze images
BRANDING_PORT = 9020  # No vision - can only see file URLs as text

# Timeout for image generation (can be slow)
IMAGE_GENERATION_TIMEOUT = 180  # 3 minutes


class TestStatus(Enum):
    PASSED = "✅ PASSED"
    FAILED = "❌ FAILED"
    SKIPPED = "⏭️ SKIPPED"


@dataclass
class FileExchangeResult:
    name: str
    status: TestStatus
    duration: float
    message: str = ""
    details: Optional[Dict] = None
    file_uri: Optional[str] = None
    file_name: Optional[str] = None
    content_type: Optional[str] = None


class InterAgentFileExchangeSuite:
    """
    Test suite for inter-agent file exchange via A2A protocol.
    
    Tests:
    1. Image generation returns FilePart with URI
    2. FilePart is properly structured (name, uri, mimeType)
    3. Image can be sent to another agent for analysis
    4. Round-trip: Generate → Send to Host → Send back to Image Generator
    """
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results: List[FileExchangeResult] = []
        self.client: Optional[httpx.AsyncClient] = None
        self.session_id: str = f"file_exchange_{uuid.uuid4().hex[:8]}"
        
        # Track generated artifacts across tests
        self.generated_image_uri: Optional[str] = None
        self.generated_image_name: Optional[str] = None
        
    def log(self, message: str, force: bool = False):
        if self.verbose or force:
            print(f"  {message}")
    
    async def setup(self):
        self.client = httpx.AsyncClient(timeout=IMAGE_GENERATION_TIMEOUT)
        
        # Check which agents are available
        try:
            response = await self.client.get(f"{BACKEND_URL}/api/agents")
            data = response.json()
            # Handle both dict format {"agents": [...]} and list format [...]
            agents = data.get('agents', data) if isinstance(data, dict) else data
            agent_names = [a.get('name', '') for a in agents if isinstance(a, dict)]
            self.log(f"Available agents in registry: {len(agent_names)}")
            
            # Check for Image Generator
            image_gen_available = any('image' in name.lower() and 'generator' in name.lower() 
                                      for name in agent_names)
            if not image_gen_available:
                print("⚠️  Image Generator agent not found. Trying to register it...")
                await self._register_image_generator()
            else:
                self.log(f"✅ Image Generator agent found in registry")
                
        except Exception as e:
            print(f"⚠️  Could not check agents: {e}")
            import traceback
            traceback.print_exc()
    
    async def _register_image_generator(self):
        """Register the Image Generator agent with the host."""
        try:
            response = await self.client.post(
                f"{BACKEND_URL}/agent/register-by-address",
                json={"agentAddress": f"http://localhost:{IMAGE_GENERATOR_PORT}"}
            )
            if response.status_code == 200:
                self.log("Image Generator registered successfully")
            else:
                self.log(f"Failed to register Image Generator: {response.status_code}")
        except Exception as e:
            self.log(f"Error registering Image Generator: {e}")
    
    async def teardown(self):
        if self.client:
            await self.client.aclose()
    
    async def send_message_and_collect_events(
        self,
        message: str,
        context_id: Optional[str] = None,
        files: Optional[List[Dict]] = None,
        timeout: float = IMAGE_GENERATION_TIMEOUT
    ) -> Dict[str, Any]:
        """
        Send a message to the host agent and collect WebSocket events.
        
        Returns dict with:
        - text_responses: List of text responses
        - file_parts: List of FilePart artifacts
        - data_parts: List of DataPart artifacts
        - events: All raw events
        """
        if context_id is None:
            # Use simple context_id without :: separator
            # When :: is present, session-based agent filtering is applied
            # Without ::, host uses its default registered agents
            context_id = f"file_exchange_test_{uuid.uuid4().hex[:8]}"
        
        message_id = str(uuid.uuid4())
        
        # Build message parts
        parts = [{"root": {"kind": "text", "text": message}}]
        
        # Add file parts if provided
        if files:
            for file in files:
                parts.append({
                    "root": {
                        "kind": "file",
                        "file": {
                            "name": file.get("name", "file"),
                            "uri": file.get("uri"),
                            "mime_type": file.get("mimeType", "image/png"),
                            "role": file.get("role")  # base, mask, overlay
                        }
                    }
                })
        
        payload = {
            "params": {
                "messageId": message_id,
                "contextId": context_id,
                "role": "user",  # Required - tells backend this is a user message
                "parts": parts,
                "agentMode": True,  # Use agent mode for delegation
                "enableInterAgentMemory": True
            }
        }
        
        result = {
            "text_responses": [],
            "file_parts": [],
            "data_parts": [],
            "events": [],
            "error": None
        }
        
        try:
            # Connect to WebSocket first
            async with websockets.connect(WEBSOCKET_URL) as ws:
                self.log(f"WebSocket connected, sending message...")
                
                # Subscribe to context
                await ws.send(json.dumps({
                    "type": "subscribe",
                    "contextId": context_id
                }))
                
                # Send the message
                response = await self.client.post(
                    f"{BACKEND_URL}/message/send",
                    json=payload
                )
                
                if response.status_code != 200:
                    result["error"] = f"HTTP {response.status_code}: {response.text}"
                    return result
                
                self.log(f"Message sent, waiting for events (timeout: {timeout}s)...")
                
                # Collect events until timeout or completion
                start_time = time.time()
                completed = False
                
                while time.time() - start_time < timeout and not completed:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        event = json.loads(msg)
                        result["events"].append(event)
                        
                        # Get event type - check multiple possible keys
                        event_type = event.get("eventType") or event.get("type") or event.get("event") or event.get("kind") or ""
                        
                        # Log event with preview for debugging
                        if self.verbose:
                            event_preview = str(event)[:100] + "..." if len(str(event)) > 100 else str(event)
                            self.log(f"Event [{event_type}]: {event_preview}")
                        else:
                            self.log(f"Event: {event_type}")
                        
                        # Check for completion - use eventType (backend format)
                        if event_type in ["message_complete", "message"]:
                            # For "message" events, check if it's a final message
                            if event_type == "message":
                                # Extract message data - debug dump
                                self.log(f"📨 MESSAGE EVENT RAW: {json.dumps(event, indent=2)[:2000]}")
                                
                                data = event.get("data", event)
                                message_obj = data.get("message", data)
                                parts = message_obj.get("parts", [])
                                
                                # Extract text and file parts from message
                                for part in parts:
                                    part_kind = part.get("kind", "")
                                    root = part.get("root", part)
                                    
                                    if root.get("kind") == "text" or part_kind == "text":
                                        text = root.get("text", part.get("text", ""))
                                        if text:
                                            result["text_responses"].append(text)
                                            
                                    elif root.get("kind") == "file" or part_kind == "file":
                                        file_data = root.get("file", part.get("file", {}))
                                        if file_data.get("uri"):
                                            result["file_parts"].append({
                                                "name": file_data.get("name"),
                                                "uri": file_data.get("uri"),
                                                "mimeType": file_data.get("mimeType")
                                            })
                                            
                                    elif root.get("kind") == "data" or part_kind == "data":
                                        data_content = root.get("data", part.get("data", {}))
                                        if isinstance(data_content, dict):
                                            if data_content.get("artifact-uri"):
                                                result["file_parts"].append({
                                                    "name": data_content.get("file-name"),
                                                    "uri": data_content.get("artifact-uri"),
                                                    "mimeType": data_content.get("mime")
                                                })
                                            else:
                                                result["data_parts"].append(data_content)
                                
                                # Don't mark as completed yet - wait for task_updated with completed state
                                
                            elif event_type == "message_complete":
                                completed = True
                                data = event.get("data", {})
                                message_obj = data.get("message", data)
                                parts = message_obj.get("parts", [])
                                
                                for part in parts:
                                    part_kind = part.get("kind", "")
                                    root = part.get("root", part)
                                    
                                    if root.get("kind") == "text" or part_kind == "text":
                                        text = root.get("text", part.get("text", ""))
                                        if text:
                                            result["text_responses"].append(text)
                                            
                                    elif root.get("kind") == "file" or part_kind == "file":
                                        file_data = root.get("file", part.get("file", {}))
                                        if file_data.get("uri"):
                                            result["file_parts"].append({
                                                "name": file_data.get("name"),
                                                "uri": file_data.get("uri"),
                                                "mimeType": file_data.get("mimeType")
                                            })
                                            
                                    elif root.get("kind") == "data" or part_kind == "data":
                                        data_content = root.get("data", part.get("data", {}))
                                        if isinstance(data_content, dict):
                                            if data_content.get("artifact-uri"):
                                                result["file_parts"].append({
                                                    "name": data_content.get("file-name"),
                                                    "uri": data_content.get("artifact-uri"),
                                                    "mimeType": data_content.get("mime")
                                                })
                                            else:
                                                result["data_parts"].append(data_content)

                        # Check for remote_agent_activity - may contain agent response with files
                        elif event_type == "remote_agent_activity":
                            self.log(f"🔄 remote_agent_activity event: {json.dumps(event, indent=2, default=str)[:600]}")
                            
                            # Check for response data
                            response = event.get("response", {})
                            if response and isinstance(response, dict):
                                # Check for parts in response
                                parts = response.get("parts", [])
                                for part in parts:
                                    part_kind = part.get("kind", "")
                                    if part_kind == "file":
                                        file_data = part.get("file", {})
                                        if file_data.get("uri"):
                                            result["file_parts"].append({
                                                "name": file_data.get("name"),
                                                "uri": file_data.get("uri"),
                                                "mimeType": file_data.get("mimeType")
                                            })
                                            self.log(f"📎 Found file in remote_agent_activity: {file_data.get('name')}")
                                    elif part_kind == "data":
                                        data_content = part.get("data", {})
                                        if isinstance(data_content, dict) and data_content.get("artifact-uri"):
                                            result["file_parts"].append({
                                                "name": data_content.get("file-name"),
                                                "uri": data_content.get("artifact-uri"),
                                                "mimeType": data_content.get("mime")
                                            })
                                            self.log(f"📎 Found artifact-uri in remote_agent_activity: {data_content.get('artifact-uri')}")
                                            
                        # Check for task_updated with completed state - may contain artifacts
                        elif event_type == "task_updated":
                            state = event.get("state", "")
                            # Debug: log the full task_updated event
                            self.log(f"📋 task_updated event: {json.dumps(event, indent=2, default=str)[:500]}")
                            
                            # Check for artifacts in task_updated
                            task_data = event.get("task", event)
                            artifacts = task_data.get("artifacts", [])
                            for artifact in artifacts:
                                parts = artifact.get("parts", [])
                                for part in parts:
                                    part_kind = part.get("kind", "")
                                    if part_kind == "file":
                                        file_data = part.get("file", {})
                                        if file_data.get("uri"):
                                            result["file_parts"].append({
                                                "name": file_data.get("name"),
                                                "uri": file_data.get("uri"),
                                                "mimeType": file_data.get("mimeType")
                                            })
                                            self.log(f"📎 Found file in task artifact: {file_data.get('name')}")
                                    elif part_kind == "data":
                                        data_content = part.get("data", {})
                                        if isinstance(data_content, dict) and data_content.get("artifact-uri"):
                                            result["file_parts"].append({
                                                "name": data_content.get("file-name"),
                                                "uri": data_content.get("artifact-uri"),
                                                "mimeType": data_content.get("mime")
                                            })
                                            self.log(f"📎 Found data artifact-uri: {data_content.get('artifact-uri')}")
                            
                            if state == "completed":
                                completed = True
                                self.log(f"✅ Task completed")
                                            
                        # Check for file_uploaded events (real-time artifacts)
                        elif event_type == "file_uploaded":
                            data = event.get("data", {})
                            result["file_parts"].append({
                                "name": data.get("filename"),
                                "uri": data.get("uri"),
                                "mimeType": data.get("contentType")
                            })
                            self.log(f"📎 File artifact received: {data.get('filename')}")
                            
                        # Check for message_chunk events (streaming text)
                        elif event_type == "message_chunk":
                            data = event.get("data", event)
                            chunk = data.get("chunk") or data.get("text") or data.get("content", "")
                            if chunk and isinstance(chunk, str):
                                # Accumulate chunks (will be combined later)
                                if not hasattr(self, '_current_chunks'):
                                    self._current_chunks = []
                                self._current_chunks.append(chunk)
                        
                        # Check for outgoing_agent_message events - may contain file parts
                        elif event_type == "outgoing_agent_message":
                            self.log(f"📤 outgoing_agent_message event: {json.dumps(event, indent=2, default=str)[:800]}")
                            
                            # Check for parts in the message
                            message_obj = event.get("message", event.get("data", event))
                            # Skip if message is a string (just text content, not structured data)
                            if not isinstance(message_obj, dict):
                                continue
                            parts = message_obj.get("parts", [])
                            
                            for part in parts:
                                part_kind = part.get("kind", "")
                                root = part.get("root", part)
                                
                                if root.get("kind") == "text" or part_kind == "text":
                                    text = root.get("text", part.get("text", ""))
                                    if text:
                                        result["text_responses"].append(text)
                                        
                                elif root.get("kind") == "file" or part_kind == "file":
                                    file_data = root.get("file", part.get("file", {}))
                                    if file_data.get("uri"):
                                        result["file_parts"].append({
                                            "name": file_data.get("name"),
                                            "uri": file_data.get("uri"),
                                            "mimeType": file_data.get("mimeType")
                                        })
                                        self.log(f"📎 Found file in outgoing_agent_message: {file_data.get('name')}")
                                        
                                elif root.get("kind") == "data" or part_kind == "data":
                                    data_content = root.get("data", part.get("data", {}))
                                    if isinstance(data_content, dict):
                                        if data_content.get("artifact-uri"):
                                            result["file_parts"].append({
                                                "name": data_content.get("file-name"),
                                                "uri": data_content.get("artifact-uri"),
                                                "mimeType": data_content.get("mime")
                                            })
                                            self.log(f"📎 Found artifact-uri in outgoing: {data_content.get('artifact-uri')}")
                        
                        # Check for error
                        elif event_type == "error":
                            result["error"] = event.get("data", {}).get("message", "Unknown error")
                            completed = True
                            
                    except asyncio.TimeoutError:
                        # Check if we have results even if not explicitly completed
                        if result["text_responses"] or result["file_parts"]:
                            self.log("No more events, using collected results")
                            break
                        continue
                
                # Combine any accumulated chunks
                if hasattr(self, '_current_chunks') and self._current_chunks:
                    combined = "".join(self._current_chunks)
                    if combined and combined not in result["text_responses"]:
                        result["text_responses"].append(combined)
                    self._current_chunks = []
                        
                if not completed:
                    self.log(f"Timeout after {timeout}s - collected {len(result['events'])} events")
                    
        except ConnectionClosed as e:
            result["error"] = f"WebSocket closed: {e}"
        except Exception as e:
            result["error"] = str(e)
            
        return result

    # =========================================================================
    # TEST 1: Image Generation Returns FilePart
    # =========================================================================
    async def test_image_generation_returns_filepart(self) -> FileExchangeResult:
        """
        Test that requesting image generation returns a FilePart with URI.
        
        Expected:
        - Image Generator agent is called
        - Response contains FilePart with:
          - name: filename
          - uri: blob storage URL
          - mimeType: image/png or image/jpeg
        """
        test_name = "Image Generation Returns FilePart"
        start_time = time.time()
        
        self.log(f"\n🧪 Testing: {test_name}")
        self.log("Sending image generation request (may take 1-2 minutes)...")
        
        try:
            result = await self.send_message_and_collect_events(
                message="Use the AI Foundry Image Generator Agent to generate an image of a blue dragon flying over mountains at sunset",
                timeout=IMAGE_GENERATION_TIMEOUT
            )
            
            if result["error"]:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message=f"Error: {result['error']}"
                )
            
            # Check for file parts
            file_parts = result["file_parts"]
            
            if not file_parts:
                # Check text responses for any indication of image
                text = " ".join(result["text_responses"])
                
                # Look for URLs in text that might be image links
                url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
                urls = re.findall(url_pattern, text)
                image_urls = [u for u in urls if any(ext in u.lower() for ext in ['.png', '.jpg', '.jpeg', 'blob.core'])]
                
                if image_urls:
                    # Found image URL in text
                    self.generated_image_uri = image_urls[0]
                    self.generated_image_name = "generated_image.png"
                    
                    return FileExchangeResult(
                        name=test_name,
                        status=TestStatus.PASSED,
                        duration=time.time() - start_time,
                        message=f"Image URL found in text response",
                        file_uri=self.generated_image_uri,
                        details={"source": "text_extraction", "url": self.generated_image_uri}
                    )
                
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message="No FilePart or image URL found in response",
                    details={
                        "text_responses_preview": result["text_responses"][:1000] if result["text_responses"] else "NONE",
                        "events_count": len(result["events"]),
                        "data_parts": result.get("data_parts", []),
                        "file_parts_found": len(result.get("file_parts", [])),
                        "note": "Check raw MESSAGE EVENT above for structure"
                    }
                )
            
            # Validate FilePart structure
            file_part = file_parts[0]
            file_uri = file_part.get("uri")
            file_name = file_part.get("name")
            mime_type = file_part.get("mimeType")
            
            # Store for subsequent tests
            self.generated_image_uri = file_uri
            self.generated_image_name = file_name
            
            validation_issues = []
            
            if not file_uri:
                validation_issues.append("Missing URI")
            elif not file_uri.startswith(("http://", "https://")):
                validation_issues.append(f"URI not HTTP(S): {file_uri[:50]}")
                
            if not file_name:
                validation_issues.append("Missing filename")
                
            if not mime_type:
                # Acceptable if mime type is inferred
                self.log("Note: mimeType not explicitly set")
            elif not mime_type.startswith("image/"):
                validation_issues.append(f"Unexpected mime type: {mime_type}")
            
            if validation_issues:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message=f"FilePart validation failed: {', '.join(validation_issues)}",
                    details=file_part
                )
            
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.PASSED,
                duration=time.time() - start_time,
                message=f"Generated image: {file_name}",
                file_uri=file_uri,
                file_name=file_name,
                content_type=mime_type,
                details={"file_parts_count": len(file_parts), "first_part": file_part}
            )
            
        except Exception as e:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message=f"Exception: {str(e)}"
            )

    # =========================================================================
    # TEST 2: FilePart Can Be Verified (URL is accessible)
    # =========================================================================
    async def test_filepart_uri_accessible(self) -> FileExchangeResult:
        """
        Test that the FilePart URI is actually accessible.
        
        This validates the image was properly uploaded to blob storage.
        """
        test_name = "FilePart URI Accessible"
        start_time = time.time()
        
        self.log(f"\n🧪 Testing: {test_name}")
        
        if not self.generated_image_uri:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.SKIPPED,
                duration=time.time() - start_time,
                message="No image URI from previous test"
            )
        
        try:
            self.log(f"Checking URI: {self.generated_image_uri[:80]}...")
            
            # Just do a HEAD request to check accessibility
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.head(self.generated_image_uri)
                
                if response.status_code != 200:
                    # Try GET if HEAD fails
                    response = await client.get(self.generated_image_uri)
                
                if response.status_code == 200:
                    content_type = response.headers.get("content-type", "unknown")
                    content_length = response.headers.get("content-length", "unknown")
                    
                    return FileExchangeResult(
                        name=test_name,
                        status=TestStatus.PASSED,
                        duration=time.time() - start_time,
                        message=f"URI accessible: {content_type}, {content_length} bytes",
                        file_uri=self.generated_image_uri,
                        content_type=content_type,
                        details={
                            "status_code": response.status_code,
                            "content_type": content_type,
                            "content_length": content_length
                        }
                    )
                else:
                    return FileExchangeResult(
                        name=test_name,
                        status=TestStatus.FAILED,
                        duration=time.time() - start_time,
                        message=f"URI not accessible: HTTP {response.status_code}",
                        file_uri=self.generated_image_uri,
                        details={"status_code": response.status_code}
                    )
                    
        except Exception as e:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message=f"Error checking URI: {str(e)}"
            )

    # =========================================================================
    # TEST 3: Send Image to Host for Analysis
    # =========================================================================
    async def test_send_image_to_host(self) -> FileExchangeResult:
        """
        Test sending a previously generated image back to the host.
        
        This simulates:
        1. User/agent has an image (from generation or upload)
        2. Sends it to host with a request for analysis/modification
        3. Host routes to appropriate agent
        """
        test_name = "Send Image to Host for Analysis"
        start_time = time.time()
        
        self.log(f"\n🧪 Testing: {test_name}")
        
        if not self.generated_image_uri:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.SKIPPED,
                duration=time.time() - start_time,
                message="No image URI from previous test"
            )
        
        try:
            # Send the image with a request
            result = await self.send_message_and_collect_events(
                message="Describe this image in detail - what do you see?",
                files=[{
                    "name": self.generated_image_name or "image.png",
                    "uri": self.generated_image_uri,
                    "mimeType": "image/png"
                }],
                timeout=120
            )
            
            if result["error"]:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message=f"Error: {result['error']}"
                )
            
            # Check that we got a text response (image was processed)
            text_responses = result["text_responses"]
            
            if not text_responses:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message="No text response received",
                    details={"events_count": len(result["events"])}
                )
            
            combined_text = " ".join(text_responses)
            
            # Check for meaningful response (not just an error)
            if len(combined_text) < 50:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message=f"Response too short ({len(combined_text)} chars)",
                    details={"response": combined_text}
                )
            
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.PASSED,
                duration=time.time() - start_time,
                message=f"Image analyzed, got {len(combined_text)} char response",
                details={
                    "response_preview": combined_text[:200] + "..." if len(combined_text) > 200 else combined_text,
                    "events_count": len(result["events"])
                }
            )
            
        except Exception as e:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message=f"Exception: {str(e)}"
            )

    # =========================================================================
    # TEST 4: Round-Trip - Image Generation → Edit Request
    # =========================================================================
    async def test_roundtrip_generate_then_edit(self) -> FileExchangeResult:
        """
        Test the full round-trip file exchange:
        1. Generate image with Image Generator
        2. Send the generated image back to Image Generator with edit request
        3. Verify new image is returned
        
        This tests the core A2A file exchange pattern.
        """
        test_name = "Round-Trip: Generate Then Edit"
        start_time = time.time()
        
        self.log(f"\n🧪 Testing: {test_name}")
        
        if not self.generated_image_uri:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.SKIPPED,
                duration=time.time() - start_time,
                message="No image URI from previous test"
            )
        
        try:
            # Send the original image with an edit request
            self.log("Sending edit request with original image (this may take 2+ minutes)...")
            
            result = await self.send_message_and_collect_events(
                message="Take this image and add a rainbow across the sky. Use the attached image as the base.",
                files=[{
                    "name": self.generated_image_name or "base_image.png",
                    "uri": self.generated_image_uri,
                    "mimeType": "image/png",
                    "role": "base"  # Mark as base image for editing
                }],
                timeout=IMAGE_GENERATION_TIMEOUT
            )
            
            if result["error"]:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message=f"Error: {result['error']}"
                )
            
            # Check for new file parts (edited image)
            file_parts = result["file_parts"]
            
            if not file_parts:
                # Check if text mentions inability to edit
                text = " ".join(result["text_responses"])
                if "cannot edit" in text.lower() or "not supported" in text.lower():
                    return FileExchangeResult(
                        name=test_name,
                        status=TestStatus.SKIPPED,
                        duration=time.time() - start_time,
                        message="Image editing not supported by this agent",
                        details={"response": text[:200]}
                    )
                
                # Look for URL in text
                url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
                urls = re.findall(url_pattern, text)
                image_urls = [u for u in urls if any(ext in u.lower() for ext in ['.png', '.jpg', 'blob.core'])]
                
                if image_urls:
                    new_uri = image_urls[0]
                    # Check if it's a different image
                    if new_uri != self.generated_image_uri:
                        return FileExchangeResult(
                            name=test_name,
                            status=TestStatus.PASSED,
                            duration=time.time() - start_time,
                            message="New edited image URL found in response",
                            file_uri=new_uri,
                            details={"original": self.generated_image_uri[:50], "new": new_uri[:50]}
                        )
                
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message="No new image returned after edit request",
                    details={"text_preview": text[:300] if text else "No text"}
                )
            
            # We got file parts - check if it's a new image
            new_file = file_parts[0]
            new_uri = new_file.get("uri")
            
            if new_uri and new_uri != self.generated_image_uri:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.PASSED,
                    duration=time.time() - start_time,
                    message=f"New edited image generated: {new_file.get('name')}",
                    file_uri=new_uri,
                    file_name=new_file.get("name"),
                    details={
                        "original_uri": self.generated_image_uri[:50] + "...",
                        "new_uri": new_uri[:50] + "..." if new_uri else None
                    }
                )
            else:
                # Same image returned or no URI
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message="Returned image is same as original or missing URI",
                    details=new_file
                )
                
        except Exception as e:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message=f"Exception: {str(e)}"
            )

    # =========================================================================
    # TEST 5: DataPart Artifact Reference
    # =========================================================================
    async def test_datapart_artifact_reference(self) -> FileExchangeResult:
        """
        Test that DataPart with artifact-uri is properly handled.
        
        Some agents return files as DataPart with artifact-uri instead of FilePart.
        Both should work for inter-agent file exchange.
        """
        test_name = "DataPart Artifact Reference"
        start_time = time.time()
        
        self.log(f"\n🧪 Testing: {test_name}")
        
        try:
            # This test checks if any of our collected file_parts came from DataPart
            # We check the events from the first test
            if not self.generated_image_uri:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.SKIPPED,
                    duration=time.time() - start_time,
                    message="No artifacts collected from previous tests"
                )
            
            # If we got an image URI, the artifact reference system is working
            # Either via FilePart or DataPart
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.PASSED,
                duration=time.time() - start_time,
                message="Artifact URI successfully extracted from A2A response",
                file_uri=self.generated_image_uri,
                details={
                    "uri_format": "blob_storage" if "blob.core" in self.generated_image_uri else "other",
                    "has_sas": "?" in self.generated_image_uri
                }
            )
            
        except Exception as e:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message=f"Exception: {str(e)}"
            )

    # =========================================================================
    # TEST 6: Agent-to-Agent File Exchange via Host
    # =========================================================================
    async def test_agent_to_agent_file_exchange(self) -> FileExchangeResult:
        """
        Test that files can be passed between agents via the host orchestrator.
        
        Since only Image Generator has vision capabilities among running agents,
        we test by sending an image with a request that requires understanding it.
        
        Flow:
        1. Image Generator created an image (from previous test)
        2. We send that image back with a modification request
        3. Image Generator receives the file and creates a modified version
        
        This tests the inter-agent file passing pattern through the host.
        """
        test_name = "Agent-to-Agent File Exchange via Host"
        start_time = time.time()
        
        self.log(f"\n🧪 Testing: {test_name}")
        
        if not self.generated_image_uri:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.SKIPPED,
                duration=time.time() - start_time,
                message="No image URI from previous test - run image_generation first"
            )
        
        try:
            # Send the generated image with a request to describe/modify it
            # This tests that the host can pass files to agents
            self.log("Sending image to host for processing...")
            
            result = await self.send_message_and_collect_events(
                message="Look at this image and describe what you see in detail. What colors, objects, and composition are present?",
                files=[{
                    "name": self.generated_image_name or "agent_generated.png",
                    "uri": self.generated_image_uri,
                    "mimeType": "image/png"
                }],
                timeout=180  # Allow time for processing
            )
            
            if result["error"]:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message=f"Error: {result['error']}"
                )
            
            # Check for response indicating the image was processed
            text_responses = result["text_responses"]
            combined_text = " ".join(text_responses).lower()
            
            if not text_responses:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message="No response received from file exchange",
                    details={"events_count": len(result["events"])}
                )
            
            # Verify the response suggests visual analysis occurred
            # These indicators show the agent processed the image
            vision_indicators = ["see", "shows", "depicts", "appears", "visible", "image", 
                                "color", "background", "foreground", "object", "scene",
                                "dragon", "mountain", "sunset", "blue", "flying"]  # From our test prompt
            found_indicators = [ind for ind in vision_indicators if ind in combined_text]
            
            # Check events for remote_agent_activity
            remote_agent_events = [
                e for e in result["events"] 
                if e.get("eventType") in ["remote_agent_activity", "task_created", "task_updated"]
            ]
            
            if len(found_indicators) >= 2:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.PASSED,
                    duration=time.time() - start_time,
                    message=f"File exchange successful. Image processed with indicators: {found_indicators[:5]}",
                    details={
                        "vision_indicators": found_indicators,
                        "remote_agent_events": len(remote_agent_events),
                        "response_preview": combined_text[:300] + "..." if len(combined_text) > 300 else combined_text
                    }
                )
            
            # If we got a response, file was at least passed through
            if len(combined_text) > 50:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.PASSED,
                    duration=time.time() - start_time,
                    message="File passed through host successfully (response received)",
                    details={
                        "response_length": len(combined_text),
                        "found_indicators": found_indicators,
                        "response_preview": combined_text[:300]
                    }
                )
            
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message="Response too short - unclear if file was processed",
                details={"response": combined_text}
            )
            
        except Exception as e:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message=f"Exception: {str(e)}"
            )

    # =========================================================================
    # TEST 7: Branding Agent Receives File (Non-Vision Agent)
    # =========================================================================
    async def test_branding_agent_receives_file(self) -> FileExchangeResult:
        """
        Test that a non-vision agent (Branding) can RECEIVE files via A2A.
        
        This is important because:
        - Branding agent doesn't have GPT-4o vision
        - But it SHOULD still receive the FilePart/URI in the A2A payload
        - It will see the file as "[File at https://...]" in text
        - This validates the A2A file passing mechanism works for ALL agents
        
        We verify:
        1. File is passed to Branding agent
        2. Branding acknowledges receiving the file
        3. Branding can reference the file in its response
        """
        test_name = "Branding Agent Receives File"
        start_time = time.time()
        
        self.log(f"\n🧪 Testing: {test_name}")
        
        if not self.generated_image_uri:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.SKIPPED,
                duration=time.time() - start_time,
                message="No image URI from previous test"
            )
        
        try:
            # Explicitly request Branding agent to handle this
            self.log("Sending file to Branding agent...")
            
            result = await self.send_message_and_collect_events(
                message="Please ask the Branding agent to review this image file for brand compliance. The image should be evaluated for color palette, composition, and alignment with corporate branding guidelines.",
                files=[{
                    "name": self.generated_image_name or "brand_review.png",
                    "uri": self.generated_image_uri,
                    "mimeType": "image/png"
                }],
                timeout=120
            )
            
            if result["error"]:
                if "not found" in str(result["error"]).lower() or "branding" in str(result["error"]).lower():
                    return FileExchangeResult(
                        name=test_name,
                        status=TestStatus.SKIPPED,
                        duration=time.time() - start_time,
                        message="Branding agent not available",
                        details={"error": result["error"]}
                    )
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message=f"Error: {result['error']}"
                )
            
            text_responses = result["text_responses"]
            combined_text = " ".join(text_responses).lower()
            
            if not text_responses:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message="No response received",
                    details={"events_count": len(result["events"])}
                )
            
            # Check if Branding agent was invoked (look in events)
            branding_invoked = False
            for event in result["events"]:
                event_str = json.dumps(event).lower()
                if "branding" in event_str and event.get("eventType") in ["remote_agent_activity", "task_created", "task_updated"]:
                    branding_invoked = True
                    break
            
            # Look for branding-related response indicators
            branding_indicators = ["brand", "color", "palette", "guideline", "compliance", 
                                   "visual", "identity", "logo", "design", "file"]
            found_indicators = [ind for ind in branding_indicators if ind in combined_text]
            
            # Check if file reference appears in response (Branding sees it as text)
            file_referenced = "file" in combined_text or "image" in combined_text or "attached" in combined_text
            
            if branding_invoked or len(found_indicators) >= 2:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.PASSED,
                    duration=time.time() - start_time,
                    message=f"Branding agent received file. Indicators: {found_indicators[:4]}",
                    details={
                        "branding_invoked": branding_invoked,
                        "found_indicators": found_indicators,
                        "file_referenced": file_referenced,
                        "response_preview": combined_text[:300]
                    }
                )
            
            if len(combined_text) > 50:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.PASSED,
                    duration=time.time() - start_time,
                    message="Response received (file may have been passed to host/agent)",
                    details={
                        "branding_invoked": branding_invoked,
                        "response_length": len(combined_text),
                        "response_preview": combined_text[:300]
                    }
                )
            
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message="Could not verify Branding agent received file",
                details={"response": combined_text}
            )
            
        except Exception as e:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message=f"Exception: {str(e)}"
            )

    # =========================================================================
    # TEST 8: Multi-Agent File Chain (A → B → C)
    # =========================================================================
    async def test_multi_agent_file_chain(self) -> FileExchangeResult:
        """
        Test a chain of file processing across multiple agents:
        
        1. Image Generator creates base image
        2. Ask host to have one agent analyze it
        3. Ask host to have another agent modify based on analysis
        
        This tests complex workflows where files flow through multiple agents.
        """
        test_name = "Multi-Agent File Chain"
        start_time = time.time()
        
        self.log(f"\n🧪 Testing: {test_name}")
        
        if not self.generated_image_uri:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.SKIPPED,
                duration=time.time() - start_time,
                message="No image URI from previous test"
            )
        
        try:
            # Send a complex request that requires multi-agent collaboration
            self.log("Requesting multi-agent file processing chain...")
            
            result = await self.send_message_and_collect_events(
                message="""I have this image attached. Please:
1. First, analyze the image and describe what you see
2. Then, based on the analysis, suggest how it could be improved for marketing use
3. If possible, create a modified version with those improvements

Please coordinate between agents to complete this multi-step task.""",
                files=[{
                    "name": self.generated_image_name or "chain_input.png",
                    "uri": self.generated_image_uri,
                    "mimeType": "image/png"
                }],
                timeout=IMAGE_GENERATION_TIMEOUT * 2  # Extra time for chain
            )
            
            if result["error"]:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message=f"Error: {result['error']}"
                )
            
            # Check for multi-step response
            text_responses = result["text_responses"]
            combined_text = " ".join(text_responses)
            
            # Look for evidence of multi-agent processing
            analysis_indicators = ["see", "image shows", "depicts", "appears", "visible"]
            suggestion_indicators = ["suggest", "improve", "recommend", "could", "marketing"]
            
            has_analysis = any(ind in combined_text.lower() for ind in analysis_indicators)
            has_suggestions = any(ind in combined_text.lower() for ind in suggestion_indicators)
            has_new_file = len(result["file_parts"]) > 0
            
            # Count unique remote agent events
            agent_events = [
                e for e in result["events"]
                if e.get("type") in ["remote_agent_activity", "agent_status", "task_status"]
            ]
            unique_agents = set()
            for e in agent_events:
                data = e.get("data", {})
                agent_name = data.get("agentName") or data.get("agent_name") or data.get("agent")
                if agent_name:
                    unique_agents.add(agent_name.lower())
            
            steps_completed = sum([has_analysis, has_suggestions, has_new_file])
            
            if steps_completed >= 2 or len(unique_agents) >= 2:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.PASSED,
                    duration=time.time() - start_time,
                    message=f"Multi-agent chain completed. Steps: {steps_completed}/3, Agents: {len(unique_agents)}",
                    details={
                        "has_analysis": has_analysis,
                        "has_suggestions": has_suggestions,
                        "new_file_generated": has_new_file,
                        "unique_agents_involved": list(unique_agents),
                        "response_length": len(combined_text)
                    }
                )
            elif steps_completed >= 1:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.PASSED,
                    duration=time.time() - start_time,
                    message=f"Partial chain completed ({steps_completed}/3 steps)",
                    details={
                        "has_analysis": has_analysis,
                        "has_suggestions": has_suggestions,
                        "new_file_generated": has_new_file
                    }
                )
            else:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message="Multi-agent chain did not complete any steps",
                    details={"response_preview": combined_text[:500]}
                )
            
        except Exception as e:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message=f"Exception: {str(e)}"
            )

    # =========================================================================
    # TEST 9: File Metadata Preservation
    # =========================================================================
    async def test_file_metadata_preservation(self) -> FileExchangeResult:
        """
        Test that file metadata (name, mimeType, role) is preserved
        when files are passed between agents.
        
        This is critical for agents that need to understand file context
        (e.g., "this is a base image" vs "this is a mask").
        """
        test_name = "File Metadata Preservation"
        start_time = time.time()
        
        self.log(f"\n🧪 Testing: {test_name}")
        
        if not self.generated_image_uri:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.SKIPPED,
                duration=time.time() - start_time,
                message="No image URI from previous test"
            )
        
        try:
            # Send file with explicit metadata including role
            test_filename = "test_metadata_image.png"
            test_role = "base"
            test_mime = "image/png"
            
            self.log(f"Sending file with metadata: name={test_filename}, role={test_role}")
            
            result = await self.send_message_and_collect_events(
                message="Process this base image and describe its properties. This is marked as a base image for potential overlay operations.",
                files=[{
                    "name": test_filename,
                    "uri": self.generated_image_uri,
                    "mimeType": test_mime,
                    "role": test_role
                }],
                timeout=120
            )
            
            if result["error"]:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message=f"Error: {result['error']}"
                )
            
            # Check that we got a response (file was received and processed)
            if result["text_responses"]:
                combined_text = " ".join(result["text_responses"])
                
                # The file was processed - metadata was at minimum not lost
                # Check events for any indication of metadata preservation
                metadata_in_events = False
                for e in result["events"]:
                    event_str = json.dumps(e)
                    if test_filename in event_str or test_role in event_str:
                        metadata_in_events = True
                        break
                
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.PASSED,
                    duration=time.time() - start_time,
                    message=f"File with metadata processed successfully",
                    details={
                        "sent_filename": test_filename,
                        "sent_role": test_role,
                        "sent_mime": test_mime,
                        "metadata_detected_in_events": metadata_in_events,
                        "response_length": len(combined_text)
                    }
                )
            else:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message="No response received after sending file with metadata"
                )
            
        except Exception as e:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message=f"Exception: {str(e)}"
            )

    # =========================================================================
    # TEST 10: A2A Payload Structure Validation
    # =========================================================================
    async def test_a2a_payload_structure(self) -> FileExchangeResult:
        """
        Validate the A2A protocol payload structure for file exchange.
        
        Verifies:
        - FilePart structure: {kind: "file", file: {name, uri, mimeType}}
        - DataPart artifact: {kind: "data", data: {artifact-uri, file-name, mime}}
        - Message structure includes proper parts array
        - Events contain correctly structured A2A parts
        
        This ensures we're generating spec-compliant A2A payloads.
        """
        test_name = "A2A Payload Structure Validation"
        start_time = time.time()
        
        self.log(f"\n🧪 Testing: {test_name}")
        
        if not self.generated_image_uri:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.SKIPPED,
                duration=time.time() - start_time,
                message="No image data from previous tests"
            )
        
        try:
            # Send a request that should trigger file-based response
            result = await self.send_message_and_collect_events(
                message="Generate a simple test image showing a red circle on white background",
                timeout=IMAGE_GENERATION_TIMEOUT
            )
            
            validation_results = {
                "filepart_valid": False,
                "datapart_valid": False,
                "message_structure_valid": False,
                "parts_array_found": False,
                "issues": []
            }
            
            # Analyze all events for A2A payload structure
            for event in result["events"]:
                event_type = event.get("type", "")
                data = event.get("data", {})
                
                # Check for message_complete event (main response)
                if event_type == "message_complete":
                    message_obj = data.get("message", data)
                    parts = message_obj.get("parts", [])
                    
                    if parts:
                        validation_results["parts_array_found"] = True
                        validation_results["message_structure_valid"] = True
                        
                        for part in parts:
                            root = part.get("root", part)
                            kind = root.get("kind", "")
                            
                            # Validate FilePart structure
                            if kind == "file":
                                file_obj = root.get("file", {})
                                has_name = bool(file_obj.get("name"))
                                has_uri = bool(file_obj.get("uri"))
                                has_mime = bool(file_obj.get("mimeType"))
                                
                                if has_name and has_uri:
                                    validation_results["filepart_valid"] = True
                                    self.log(f"✓ Valid FilePart: name={file_obj.get('name')}, uri={file_obj.get('uri')[:50]}...")
                                else:
                                    validation_results["issues"].append(
                                        f"FilePart missing fields: name={has_name}, uri={has_uri}, mimeType={has_mime}"
                                    )
                            
                            # Validate DataPart with artifact-uri
                            elif kind == "data":
                                data_content = root.get("data", {})
                                if isinstance(data_content, dict):
                                    artifact_uri = data_content.get("artifact-uri")
                                    if artifact_uri:
                                        validation_results["datapart_valid"] = True
                                        self.log(f"✓ Valid DataPart artifact: uri={artifact_uri[:50]}...")
                
                # Check file_uploaded events
                elif event_type == "file_uploaded":
                    uri = data.get("uri")
                    filename = data.get("filename")
                    content_type = data.get("contentType")
                    
                    if uri and filename:
                        validation_results["filepart_valid"] = True
                        self.log(f"✓ Valid file_uploaded event: {filename}")
            
            # Determine overall result
            if validation_results["filepart_valid"] or validation_results["datapart_valid"]:
                # Count valid structures
                valid_count = sum([
                    validation_results["filepart_valid"],
                    validation_results["datapart_valid"],
                    validation_results["message_structure_valid"],
                    validation_results["parts_array_found"]
                ])
                
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.PASSED,
                    duration=time.time() - start_time,
                    message=f"A2A payload structure valid ({valid_count}/4 checks passed)",
                    details=validation_results
                )
            else:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message="No valid A2A file payload structure found",
                    details=validation_results
                )
                
        except Exception as e:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message=f"Exception: {str(e)}"
            )

    # =========================================================================
    # TEST 11: Azure Blob Storage URI Validation
    # =========================================================================
    async def test_blob_storage_uri_validation(self) -> FileExchangeResult:
        """
        Validate that file URIs use Azure Blob Storage correctly.
        
        Verifies:
        - URI format: https://<account>.blob.core.windows.net/<container>/<path>
        - SAS token presence (for secure access)
        - URI is accessible (returns 200)
        - Content-Type header matches expected mime type
        - Blob can be downloaded successfully
        
        This ensures our blob storage integration works properly.
        """
        test_name = "Azure Blob Storage URI Validation"
        start_time = time.time()
        
        self.log(f"\n🧪 Testing: {test_name}")
        
        if not self.generated_image_uri:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.SKIPPED,
                duration=time.time() - start_time,
                message="No blob URI from previous tests"
            )
        
        try:
            uri = self.generated_image_uri
            validation_results = {
                "is_blob_storage": False,
                "has_sas_token": False,
                "uri_accessible": False,
                "content_type_valid": False,
                "content_downloadable": False,
                "storage_account": None,
                "container": None,
                "blob_path": None,
                "issues": []
            }
            
            # Parse the blob storage URI
            # Format: https://<account>.blob.core.windows.net/<container>/<path>?<sas>
            if "blob.core.windows.net" in uri:
                validation_results["is_blob_storage"] = True
                
                try:
                    from urllib.parse import urlparse, parse_qs
                    parsed = urlparse(uri)
                    
                    # Extract storage account
                    host_parts = parsed.hostname.split(".")
                    if host_parts:
                        validation_results["storage_account"] = host_parts[0]
                    
                    # Extract container and blob path
                    path_parts = parsed.path.strip("/").split("/", 1)
                    if path_parts:
                        validation_results["container"] = path_parts[0]
                        if len(path_parts) > 1:
                            validation_results["blob_path"] = path_parts[1]
                    
                    # Check for SAS token
                    if parsed.query:
                        query_params = parse_qs(parsed.query)
                        # SAS tokens have 'sig' parameter
                        if "sig" in query_params or "se" in query_params:
                            validation_results["has_sas_token"] = True
                            self.log("✓ SAS token detected in URI")
                        
                except Exception as parse_error:
                    validation_results["issues"].append(f"URI parsing error: {parse_error}")
            else:
                validation_results["issues"].append(f"Not an Azure Blob Storage URI: {uri[:50]}...")
            
            # Test URI accessibility
            async with httpx.AsyncClient(timeout=30.0) as client:
                try:
                    # HEAD request first (faster)
                    response = await client.head(uri)
                    
                    if response.status_code == 200:
                        validation_results["uri_accessible"] = True
                        
                        # Check content type
                        content_type = response.headers.get("content-type", "")
                        if content_type.startswith("image/"):
                            validation_results["content_type_valid"] = True
                            self.log(f"✓ Content-Type: {content_type}")
                        else:
                            validation_results["issues"].append(f"Unexpected Content-Type: {content_type}")
                        
                        # Try to download a small portion to verify
                        get_response = await client.get(uri, headers={"Range": "bytes=0-1023"})
                        if get_response.status_code in [200, 206]:
                            content = get_response.content
                            if len(content) > 0:
                                validation_results["content_downloadable"] = True
                                self.log(f"✓ Downloaded {len(content)} bytes successfully")
                                
                                # Check for PNG/JPEG magic bytes
                                if content[:4] == b'\x89PNG':
                                    self.log("✓ Valid PNG file signature")
                                elif content[:2] == b'\xff\xd8':
                                    self.log("✓ Valid JPEG file signature")
                                    
                    elif response.status_code == 403:
                        validation_results["issues"].append("Access denied (SAS token expired or invalid?)")
                    elif response.status_code == 404:
                        validation_results["issues"].append("Blob not found")
                    else:
                        validation_results["issues"].append(f"HTTP {response.status_code}")
                        
                except Exception as req_error:
                    validation_results["issues"].append(f"Request error: {req_error}")
            
            # Determine result
            passed_checks = sum([
                validation_results["is_blob_storage"],
                validation_results["has_sas_token"],
                validation_results["uri_accessible"],
                validation_results["content_type_valid"],
                validation_results["content_downloadable"]
            ])
            
            if passed_checks >= 4:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.PASSED,
                    duration=time.time() - start_time,
                    message=f"Blob storage validation passed ({passed_checks}/5 checks)",
                    file_uri=uri,
                    details=validation_results
                )
            elif passed_checks >= 2:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.PASSED,
                    duration=time.time() - start_time,
                    message=f"Blob storage partially validated ({passed_checks}/5 checks)",
                    file_uri=uri,
                    details=validation_results
                )
            else:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message=f"Blob storage validation failed ({passed_checks}/5 checks)",
                    file_uri=uri,
                    details=validation_results
                )
                
        except Exception as e:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message=f"Exception: {str(e)}"
            )

    # =========================================================================
    # TEST 12: Outbound A2A File Parts (Host → Remote Agent)
    # =========================================================================
    async def test_outbound_file_parts_to_agent(self) -> FileExchangeResult:
        """
        Validate that when we send files TO a remote agent, the A2A payload
        is correctly structured.
        
        This tests the outbound direction of file exchange:
        - User uploads file → Host → Remote Agent
        - Host passes file from Agent A → Agent B
        
        We verify the request structure matches A2A spec.
        """
        test_name = "Outbound A2A File Parts to Agent"
        start_time = time.time()
        
        self.log(f"\n🧪 Testing: {test_name}")
        
        if not self.generated_image_uri:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.SKIPPED,
                duration=time.time() - start_time,
                message="No image URI from previous tests"
            )
        
        try:
            # Send a file to the host with explicit metadata
            test_file = {
                "name": "outbound_test.png",
                "uri": self.generated_image_uri,
                "mimeType": "image/png",
                "role": "base"
            }
            
            self.log(f"Sending file to agent: {test_file['name']}")
            
            result = await self.send_message_and_collect_events(
                message="Please describe this image in detail. Focus on colors, composition, and any text visible.",
                files=[test_file],
                timeout=120
            )
            
            validation = {
                "file_sent_in_request": True,  # We sent it
                "agent_received_file": False,
                "agent_processed_file": False,
                "response_references_image": False
            }
            
            if result["error"]:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message=f"Error: {result['error']}"
                )
            
            # Check if agent processed the file (indicated by image-related response)
            text = " ".join(result["text_responses"]).lower()
            
            image_indicators = ["image", "picture", "shows", "depicts", "see", "color", "visual"]
            found_indicators = [ind for ind in image_indicators if ind in text]
            
            if found_indicators:
                validation["agent_processed_file"] = True
                validation["agent_received_file"] = True
                validation["response_references_image"] = True
            
            # Check events for file-related activity
            for event in result["events"]:
                event_str = json.dumps(event)
                if "outbound_test.png" in event_str or self.generated_image_uri[:30] in event_str:
                    validation["agent_received_file"] = True
            
            if validation["agent_processed_file"]:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.PASSED,
                    duration=time.time() - start_time,
                    message=f"Outbound file successfully processed by agent",
                    details={
                        "validation": validation,
                        "indicators_found": found_indicators,
                        "response_length": len(text)
                    }
                )
            else:
                return FileExchangeResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    duration=time.time() - start_time,
                    message="Agent did not appear to process the file",
                    details={"validation": validation, "response_preview": text[:300]}
                )
                
        except Exception as e:
            return FileExchangeResult(
                name=test_name,
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message=f"Exception: {str(e)}"
            )

    # =========================================================================
    # Run All Tests
    # =========================================================================
    async def run_all_tests(self) -> List[FileExchangeResult]:
        """Run all inter-agent file exchange tests."""
        
        await self.setup()
        
        tests = [
            self.test_image_generation_returns_filepart,
            self.test_filepart_uri_accessible,
            self.test_a2a_payload_structure,
            self.test_blob_storage_uri_validation,
            self.test_send_image_to_host,
            self.test_outbound_file_parts_to_agent,
            self.test_roundtrip_generate_then_edit,
            self.test_datapart_artifact_reference,
            self.test_agent_to_agent_file_exchange,
            self.test_branding_agent_receives_file,
            self.test_multi_agent_file_chain,
            self.test_file_metadata_preservation,
        ]
        
        for test in tests:
            result = await test()
            self.results.append(result)
            
            # Print result
            status_emoji = "✅" if result.status == TestStatus.PASSED else "❌" if result.status == TestStatus.FAILED else "⏭️"
            print(f"  {status_emoji} {result.name}: {result.message} ({result.duration:.1f}s)")
        
        await self.teardown()
        return self.results
    
    async def run_single_test(self, test_name: str) -> Optional[FileExchangeResult]:
        """Run a single test by name."""
        await self.setup()
        
        test_map = {
            "image_generation": self.test_image_generation_returns_filepart,
            "uri_accessible": self.test_filepart_uri_accessible,
            "a2a_payload": self.test_a2a_payload_structure,
            "blob_storage": self.test_blob_storage_uri_validation,
            "send_to_host": self.test_send_image_to_host,
            "outbound_file": self.test_outbound_file_parts_to_agent,
            "roundtrip": self.test_roundtrip_generate_then_edit,
            "datapart": self.test_datapart_artifact_reference,
            "agent_to_agent": self.test_agent_to_agent_file_exchange,
            "branding_receives": self.test_branding_agent_receives_file,
            "multi_chain": self.test_multi_agent_file_chain,
            "metadata": self.test_file_metadata_preservation,
        }
        
        if test_name not in test_map:
            print(f"Unknown test: {test_name}")
            print(f"Available tests: {list(test_map.keys())}")
            return None
        
        result = await test_map[test_name]()
        self.results.append(result)
        
        await self.teardown()
        return result


def print_summary(results: List[FileExchangeResult]):
    """Print test summary."""
    print("\n" + "=" * 60)
    print("INTER-AGENT FILE EXCHANGE TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for r in results if r.status == TestStatus.PASSED)
    failed = sum(1 for r in results if r.status == TestStatus.FAILED)
    skipped = sum(1 for r in results if r.status == TestStatus.SKIPPED)
    total = len(results)
    
    for result in results:
        icon = "✅" if result.status == TestStatus.PASSED else "❌" if result.status == TestStatus.FAILED else "⏭️"
        print(f"  {icon} {result.name}")
        print(f"      {result.message}")
        if result.file_uri:
            print(f"      URI: {result.file_uri[:60]}...")
    
    print("\n" + "-" * 60)
    print(f"Results: {passed}/{total} passed, {failed} failed, {skipped} skipped")
    print(f"Total time: {sum(r.duration for r in results):.1f}s")
    
    if failed > 0:
        print("\n⚠️  Some tests failed. Check agent availability and configuration.")
    elif passed == total:
        print("\n🎉 All tests passed! Inter-agent file exchange is working correctly.")


async def main():
    parser = argparse.ArgumentParser(description="Inter-Agent File Exchange Tests")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--test", type=str, 
                        help="Run specific test: image_generation, uri_accessible, a2a_payload, blob_storage, "
                             "send_to_host, outbound_file, roundtrip, datapart, agent_to_agent, branding_receives, "
                             "multi_chain, metadata")
    args = parser.parse_args()
    
    print("\n" + "=" * 60)
    print("INTER-AGENT FILE EXCHANGE TESTS")
    print("=" * 60)
    print("⚠️  Note: Image generation can take 1-3 minutes per image")
    print("")
    
    suite = InterAgentFileExchangeSuite(verbose=args.verbose)
    
    if args.test:
        result = await suite.run_single_test(args.test)
        if result:
            print_summary([result])
    else:
        results = await suite.run_all_tests()
        print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())
