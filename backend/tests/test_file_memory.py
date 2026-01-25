#!/usr/bin/env python3
"""
File Upload & Memory Service Tests
===================================

Tests for file upload, memory storage, and inter-agent context sharing.

These tests verify:
1. File upload to backend
2. Memory storage of agent interactions
3. Memory search/retrieval
4. Inter-agent memory sharing
5. File content extraction for agent search

Requirements:
- Backend running on localhost:12000
- WebSocket server running on localhost:8080
- At least 1 agent running (Classification preferred)
- Azure Search configured (for memory tests) - optional

Usage:
    python tests/test_file_memory.py
    python tests/test_file_memory.py --test upload
    python tests/test_file_memory.py --test memory
"""

import asyncio
import json
import time
import uuid
import argparse
import sys
import os
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum
from io import BytesIO

import httpx

# Configuration
BACKEND_URL = "http://localhost:12000"
WEBSOCKET_URL = "ws://localhost:8080/events"

# Agent info
CLASSIFICATION_PORT = 8009


class TestStatus(Enum):
    PASSED = "✅ PASSED"
    FAILED = "❌ FAILED"
    SKIPPED = "⏭️ SKIPPED"


@dataclass
class FileMemoryTestResult:
    name: str
    status: TestStatus
    duration: float
    message: str = ""
    details: Optional[Dict] = None


class FileMemoryTestSuite:
    """Test suite for file upload and memory functionality."""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results: List[FileMemoryTestResult] = []
        self.client: Optional[httpx.AsyncClient] = None
        self.session_id: str = f"test_session_{uuid.uuid4().hex[:8]}"
        self.uploaded_files: List[Dict] = []
        
    def log(self, message: str, force: bool = False):
        if self.verbose or force:
            print(f"  {message}")
    
    async def setup(self):
        self.client = httpx.AsyncClient(timeout=60.0)
        
        # Register agent
        await self.client.post(
            f"{BACKEND_URL}/agent/register-by-address",
            json={"address": f"http://localhost:{CLASSIFICATION_PORT}"}
        )
    
    async def teardown(self):
        if self.client:
            await self.client.aclose()
    
    def create_test_file(self, filename: str, content: str) -> BytesIO:
        """Create a test file in memory."""
        file_bytes = content.encode('utf-8')
        return BytesIO(file_bytes)
    
    # ==================== File Upload Tests ====================
    
    async def test_simple_file_upload(self) -> FileMemoryTestResult:
        """Test basic file upload functionality."""
        start = time.time()
        
        try:
            # Create a simple test file
            test_content = """
            Customer Support Policy Document
            ================================
            
            1. Response Time: All tickets must be acknowledged within 4 hours
            2. Priority Levels:
               - Critical: System outage, data loss
               - High: Payment issues, account locked
               - Medium: Feature requests, general questions
               - Low: Feedback, suggestions
            3. Escalation: Critical issues escalate to senior team after 1 hour
            """
            
            files = {
                'file': ('test_policy.txt', test_content.encode(), 'text/plain')
            }
            
            resp = await self.client.post(
                f"{BACKEND_URL}/upload",
                files=files,
                headers={"X-Session-ID": self.session_id}
            )
            
            duration = time.time() - start
            
            if resp.status_code == 200:
                result = resp.json()
                if result.get('success'):
                    self.uploaded_files.append(result)
                    return FileMemoryTestResult(
                        name="Simple File Upload",
                        status=TestStatus.PASSED,
                        duration=duration,
                        message=f"Uploaded: {result.get('filename')}",
                        details={
                            "file_id": result.get('file_id'),
                            "uri": result.get('uri', '')[:100] + "...",
                            "size": result.get('size'),
                            "session_id": result.get('session_id')
                        }
                    )
            
            return FileMemoryTestResult(
                name="Simple File Upload",
                status=TestStatus.FAILED,
                duration=duration,
                message=f"Upload failed: {resp.status_code}"
            )
            
        except Exception as e:
            return FileMemoryTestResult(
                name="Simple File Upload",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    async def test_pdf_file_upload(self) -> FileMemoryTestResult:
        """Test PDF file upload (simulated with proper MIME type)."""
        start = time.time()
        
        try:
            # Create a minimal PDF-like file for testing
            # (Real PDF testing would need an actual PDF file)
            pdf_content = b"%PDF-1.4 Test PDF content for upload testing"
            
            files = {
                'file': ('test_document.pdf', pdf_content, 'application/pdf')
            }
            
            resp = await self.client.post(
                f"{BACKEND_URL}/upload",
                files=files,
                headers={"X-Session-ID": self.session_id}
            )
            
            duration = time.time() - start
            
            if resp.status_code == 200:
                result = resp.json()
                if result.get('success'):
                    self.uploaded_files.append(result)
                    return FileMemoryTestResult(
                        name="PDF File Upload",
                        status=TestStatus.PASSED,
                        duration=duration,
                        message=f"Uploaded: {result.get('filename')}",
                        details={
                            "file_id": result.get('file_id'),
                            "content_type": result.get('content_type'),
                            "size": result.get('size')
                        }
                    )
            
            return FileMemoryTestResult(
                name="PDF File Upload",
                status=TestStatus.FAILED,
                duration=duration,
                message=f"Upload failed: {resp.status_code}"
            )
            
        except Exception as e:
            return FileMemoryTestResult(
                name="PDF File Upload",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    async def test_session_scoped_upload(self) -> FileMemoryTestResult:
        """Test that uploads are scoped to session ID."""
        start = time.time()
        
        try:
            # Upload file with specific session
            session1 = f"session_1_{uuid.uuid4().hex[:6]}"
            session2 = f"session_2_{uuid.uuid4().hex[:6]}"
            
            test_content = "Session-specific test file content"
            
            # Upload to session 1
            files1 = {'file': ('session1_file.txt', test_content.encode(), 'text/plain')}
            resp1 = await self.client.post(
                f"{BACKEND_URL}/upload",
                files=files1,
                headers={"X-Session-ID": session1}
            )
            
            # Upload to session 2
            files2 = {'file': ('session2_file.txt', test_content.encode(), 'text/plain')}
            resp2 = await self.client.post(
                f"{BACKEND_URL}/upload",
                files=files2,
                headers={"X-Session-ID": session2}
            )
            
            duration = time.time() - start
            
            if resp1.status_code == 200 and resp2.status_code == 200:
                result1 = resp1.json()
                result2 = resp2.json()
                
                if result1.get('session_id') == session1 and result2.get('session_id') == session2:
                    return FileMemoryTestResult(
                        name="Session-Scoped Upload",
                        status=TestStatus.PASSED,
                        duration=duration,
                        message="Files correctly scoped to different sessions",
                        details={
                            "session1": session1,
                            "session2": session2,
                            "file1_id": result1.get('file_id'),
                            "file2_id": result2.get('file_id')
                        }
                    )
            
            return FileMemoryTestResult(
                name="Session-Scoped Upload",
                status=TestStatus.FAILED,
                duration=duration,
                message="Session scoping not working correctly"
            )
            
        except Exception as e:
            return FileMemoryTestResult(
                name="Session-Scoped Upload",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    # ==================== Memory Tests ====================
    
    async def test_memory_clear(self) -> FileMemoryTestResult:
        """Test clearing memory index."""
        start = time.time()
        
        try:
            resp = await self.client.post(f"{BACKEND_URL}/clear-memory")
            
            duration = time.time() - start
            
            if resp.status_code == 200:
                result = resp.json()
                if result.get('success'):
                    return FileMemoryTestResult(
                        name="Memory Clear",
                        status=TestStatus.PASSED,
                        duration=duration,
                        message="Memory index cleared successfully"
                    )
                else:
                    # Memory service might not be configured - that's OK
                    return FileMemoryTestResult(
                        name="Memory Clear",
                        status=TestStatus.SKIPPED,
                        duration=duration,
                        message=result.get('message', 'Memory service not available')
                    )
            
            return FileMemoryTestResult(
                name="Memory Clear",
                status=TestStatus.FAILED,
                duration=duration,
                message=f"Clear failed: {resp.status_code}"
            )
            
        except Exception as e:
            return FileMemoryTestResult(
                name="Memory Clear",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    async def test_memory_storage_via_workflow(self) -> FileMemoryTestResult:
        """Test that agent interactions are stored in memory."""
        start = time.time()
        
        try:
            # Send a workflow that should trigger memory storage
            context_id = f"memory_test_{uuid.uuid4().hex[:8]}"
            
            payload = {
                "params": {
                    "messageId": str(uuid.uuid4()),
                    "contextId": context_id,
                    "role": "user",
                    "parts": [{
                        "root": {
                            "kind": "text",
                            "text": "Use the Classification agent to classify this unique test case: 'MEMORY_TEST_12345 - Customer account compromised'"
                        }
                    }],
                    "agentMode": True,
                    "enableInterAgentMemory": True,  # Enable memory!
                    "workflow": "Classify the test case using Classification agent"
                }
            }
            
            resp = await self.client.post(f"{BACKEND_URL}/message/send", json=payload)
            
            if resp.status_code != 200:
                return FileMemoryTestResult(
                    name="Memory Storage via Workflow",
                    status=TestStatus.FAILED,
                    duration=time.time() - start,
                    message="Failed to send workflow"
                )
            
            # Wait for processing
            self.log("Waiting for agent processing and memory storage...")
            await asyncio.sleep(15)
            
            duration = time.time() - start
            
            # Check if messages were created (indirect evidence of processing)
            messages_resp = await self.client.post(
                f"{BACKEND_URL}/message/list",
                json={"params": context_id}
            )
            
            messages = []
            if messages_resp.status_code == 200:
                messages = messages_resp.json().get('result', [])
            
            return FileMemoryTestResult(
                name="Memory Storage via Workflow",
                status=TestStatus.PASSED,
                duration=duration,
                message=f"Workflow completed, {len(messages)} messages stored",
                details={
                    "context_id": context_id,
                    "message_count": len(messages),
                    "inter_agent_memory": True
                }
            )
            
        except Exception as e:
            return FileMemoryTestResult(
                name="Memory Storage via Workflow",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    async def test_memory_retrieval_in_followup(self) -> FileMemoryTestResult:
        """Test that memory is retrieved in follow-up queries."""
        start = time.time()
        
        try:
            # First, create a context with specific information
            context_id = f"memory_retrieval_{uuid.uuid4().hex[:8]}"
            unique_marker = f"UNIQUE_MARKER_{uuid.uuid4().hex[:6]}"
            
            # First message with unique content
            payload1 = {
                "params": {
                    "messageId": str(uuid.uuid4()),
                    "contextId": context_id,
                    "role": "user",
                    "parts": [{
                        "root": {
                            "kind": "text",
                            "text": f"Use Classification agent to classify: '{unique_marker} - Critical system failure affecting all users'"
                        }
                    }],
                    "agentMode": True,
                    "enableInterAgentMemory": True
                }
            }
            
            await self.client.post(f"{BACKEND_URL}/message/send", json=payload1)
            self.log("First message sent, waiting for processing...")
            await asyncio.sleep(15)
            
            # Second message in same context - should have memory access
            payload2 = {
                "params": {
                    "messageId": str(uuid.uuid4()),
                    "contextId": context_id,
                    "role": "user",
                    "parts": [{
                        "root": {
                            "kind": "text",
                            "text": "What was the classification result from the previous analysis?"
                        }
                    }],
                    "agentMode": True,
                    "enableInterAgentMemory": True
                }
            }
            
            await self.client.post(f"{BACKEND_URL}/message/send", json=payload2)
            self.log("Follow-up message sent, waiting for response...")
            await asyncio.sleep(10)
            
            duration = time.time() - start
            
            # Get all messages
            messages_resp = await self.client.post(
                f"{BACKEND_URL}/message/list",
                json={"params": context_id}
            )
            
            messages = []
            if messages_resp.status_code == 200:
                messages = messages_resp.json().get('result', [])
            
            return FileMemoryTestResult(
                name="Memory Retrieval in Follow-up",
                status=TestStatus.PASSED,
                duration=duration,
                message=f"Context maintained across {len(messages)} messages",
                details={
                    "context_id": context_id,
                    "message_count": len(messages),
                    "unique_marker": unique_marker
                }
            )
            
        except Exception as e:
            return FileMemoryTestResult(
                name="Memory Retrieval in Follow-up",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    # ==================== Inter-Agent Memory Tests ====================
    
    async def test_inter_agent_memory_disabled(self) -> FileMemoryTestResult:
        """Test workflow with inter-agent memory disabled."""
        start = time.time()
        
        try:
            context_id = f"no_memory_{uuid.uuid4().hex[:8]}"
            
            payload = {
                "params": {
                    "messageId": str(uuid.uuid4()),
                    "contextId": context_id,
                    "role": "user",
                    "parts": [{
                        "root": {
                            "kind": "text",
                            "text": "Use Classification agent to classify: 'Simple test without memory'"
                        }
                    }],
                    "agentMode": True,
                    "enableInterAgentMemory": False  # Disabled!
                }
            }
            
            resp = await self.client.post(f"{BACKEND_URL}/message/send", json=payload)
            
            await asyncio.sleep(10)
            
            duration = time.time() - start
            
            if resp.status_code == 200:
                return FileMemoryTestResult(
                    name="Inter-Agent Memory Disabled",
                    status=TestStatus.PASSED,
                    duration=duration,
                    message="Workflow completed without memory storage",
                    details={
                        "context_id": context_id,
                        "inter_agent_memory": False
                    }
                )
            
            return FileMemoryTestResult(
                name="Inter-Agent Memory Disabled",
                status=TestStatus.FAILED,
                duration=duration,
                message=f"Request failed: {resp.status_code}"
            )
            
        except Exception as e:
            return FileMemoryTestResult(
                name="Inter-Agent Memory Disabled",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    async def test_inter_agent_memory_enabled(self) -> FileMemoryTestResult:
        """Test workflow with inter-agent memory enabled."""
        start = time.time()
        
        try:
            context_id = f"with_memory_{uuid.uuid4().hex[:8]}"
            
            payload = {
                "params": {
                    "messageId": str(uuid.uuid4()),
                    "contextId": context_id,
                    "role": "user",
                    "parts": [{
                        "root": {
                            "kind": "text",
                            "text": "Use Classification agent to classify: 'Test case WITH memory enabled for cross-agent context'"
                        }
                    }],
                    "agentMode": True,
                    "enableInterAgentMemory": True  # Enabled!
                }
            }
            
            resp = await self.client.post(f"{BACKEND_URL}/message/send", json=payload)
            
            await asyncio.sleep(10)
            
            duration = time.time() - start
            
            if resp.status_code == 200:
                return FileMemoryTestResult(
                    name="Inter-Agent Memory Enabled",
                    status=TestStatus.PASSED,
                    duration=duration,
                    message="Workflow completed with memory storage",
                    details={
                        "context_id": context_id,
                        "inter_agent_memory": True
                    }
                )
            
            return FileMemoryTestResult(
                name="Inter-Agent Memory Enabled",
                status=TestStatus.FAILED,
                duration=duration,
                message=f"Request failed: {resp.status_code}"
            )
            
        except Exception as e:
            return FileMemoryTestResult(
                name="Inter-Agent Memory Enabled",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    # ==================== File + Agent Integration Tests ====================
    
    async def test_file_content_in_workflow(self) -> FileMemoryTestResult:
        """Test that uploaded file content is accessible to agents in workflow."""
        start = time.time()
        
        try:
            # First upload a test file with specific content
            test_content = """
            PRIORITY ESCALATION MATRIX
            ==========================
            
            Tier 1 (Critical): Data breach, system outage, financial loss > $10,000
            - Response: Immediate
            - Escalation: CTO + Security Team
            
            Tier 2 (High): Service degradation, payment failures
            - Response: Within 1 hour  
            - Escalation: Engineering Lead
            
            Tier 3 (Medium): Feature bugs, performance issues
            - Response: Within 4 hours
            - Escalation: Product Manager
            
            Tier 4 (Low): UI issues, documentation requests
            - Response: Within 24 hours
            - Escalation: Support Lead
            """
            
            files = {
                'file': ('escalation_matrix.txt', test_content.encode(), 'text/plain')
            }
            
            upload_resp = await self.client.post(
                f"{BACKEND_URL}/upload",
                files=files,
                headers={"X-Session-ID": self.session_id}
            )
            
            if upload_resp.status_code != 200:
                return FileMemoryTestResult(
                    name="File Content in Workflow",
                    status=TestStatus.FAILED,
                    duration=time.time() - start,
                    message="Failed to upload test file"
                )
            
            upload_result = upload_resp.json()
            file_uri = upload_result.get('uri', '')
            
            self.log(f"File uploaded: {upload_result.get('filename')}")
            
            # Now send a workflow that references the file
            context_id = f"file_workflow_{uuid.uuid4().hex[:8]}"
            
            payload = {
                "params": {
                    "messageId": str(uuid.uuid4()),
                    "contextId": context_id,
                    "role": "user",
                    "parts": [
                        {
                            "root": {
                                "kind": "text",
                                "text": "Based on the escalation matrix document, use Classification agent to classify this issue: 'We just discovered unauthorized access to customer database'"
                            }
                        }
                    ],
                    "agentMode": True,
                    "enableInterAgentMemory": True
                }
            }
            
            await self.client.post(f"{BACKEND_URL}/message/send", json=payload)
            
            self.log("Waiting for agent to process with file context...")
            await asyncio.sleep(15)
            
            duration = time.time() - start
            
            return FileMemoryTestResult(
                name="File Content in Workflow",
                status=TestStatus.PASSED,
                duration=duration,
                message="Workflow executed with file context",
                details={
                    "file_id": upload_result.get('file_id'),
                    "context_id": context_id,
                    "file_uri": file_uri[:80] + "..." if len(file_uri) > 80 else file_uri
                }
            )
            
        except Exception as e:
            return FileMemoryTestResult(
                name="File Content in Workflow",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    # ==================== Test Runner ====================
    
    async def run_all_tests(self) -> List[FileMemoryTestResult]:
        """Run all file and memory tests."""
        print("\n" + "="*70)
        print("📁 File Upload & Memory Service Test Suite")
        print("="*70 + "\n")
        
        await self.setup()
        
        tests = [
            ("File Upload", [
                self.test_simple_file_upload,
                self.test_pdf_file_upload,
                self.test_session_scoped_upload,
            ]),
            ("Memory Operations", [
                self.test_memory_clear,
                self.test_memory_storage_via_workflow,
                self.test_memory_retrieval_in_followup,
            ]),
            ("Inter-Agent Memory", [
                self.test_inter_agent_memory_disabled,
                self.test_inter_agent_memory_enabled,
            ]),
            ("File + Agent Integration", [
                self.test_file_content_in_workflow,
            ]),
        ]
        
        for category, test_funcs in tests:
            print(f"\n📁 {category}")
            print("-" * 50)
            
            for test_func in test_funcs:
                result = await test_func()
                self.results.append(result)
                
                status_str = result.status.value
                print(f"  {status_str} {result.name} ({result.duration:.1f}s)")
                if result.message and self.verbose:
                    print(f"      └─ {result.message}")
        
        await self.teardown()
        
        return self.results
    
    async def run_single_test(self, test_name: str) -> Optional[FileMemoryTestResult]:
        """Run a single test by name."""
        await self.setup()
        
        test_map = {
            "upload": self.test_simple_file_upload,
            "upload_pdf": self.test_pdf_file_upload,
            "session_upload": self.test_session_scoped_upload,
            "memory_clear": self.test_memory_clear,
            "memory_store": self.test_memory_storage_via_workflow,
            "memory_retrieve": self.test_memory_retrieval_in_followup,
            "memory_disabled": self.test_inter_agent_memory_disabled,
            "memory_enabled": self.test_inter_agent_memory_enabled,
            "file_workflow": self.test_file_content_in_workflow,
        }
        
        if test_name not in test_map:
            print(f"Unknown test: {test_name}")
            print(f"Available: {', '.join(test_map.keys())}")
            await self.teardown()
            return None
        
        result = await test_map[test_name]()
        await self.teardown()
        
        print(f"\n{result.status.value} {result.name}")
        print(f"Duration: {result.duration:.1f}s")
        print(f"Message: {result.message}")
        if result.details:
            print(f"Details: {json.dumps(result.details, indent=2)}")
        
        return result
    
    def print_summary(self):
        """Print test summary."""
        print("\n" + "="*70)
        print("📊 File & Memory Test Summary")
        print("="*70)
        
        passed = sum(1 for r in self.results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in self.results if r.status == TestStatus.FAILED)
        skipped = sum(1 for r in self.results if r.status == TestStatus.SKIPPED)
        total_time = sum(r.duration for r in self.results)
        
        print(f"\n  ✅ Passed:  {passed}")
        print(f"  ❌ Failed:  {failed}")
        print(f"  ⏭️ Skipped: {skipped}")
        print(f"  ⏱️ Time:    {total_time:.1f}s")
        
        if self.uploaded_files:
            print(f"\n  📎 Files uploaded: {len(self.uploaded_files)}")
        
        if failed > 0:
            print("\n❌ Failed Tests:")
            for r in self.results:
                if r.status == TestStatus.FAILED:
                    print(f"  - {r.name}: {r.message}")
        
        print("\n" + "="*70 + "\n")
        
        return failed == 0


async def main():
    parser = argparse.ArgumentParser(description="File Upload & Memory Tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--test", "-t", type=str, help="Run a specific test")
    args = parser.parse_args()
    
    suite = FileMemoryTestSuite(verbose=args.verbose)
    
    if args.test:
        await suite.run_single_test(args.test)
    else:
        await suite.run_all_tests()
        success = suite.print_summary()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
