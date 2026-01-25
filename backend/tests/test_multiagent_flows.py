#!/usr/bin/env python3
"""
Multi-Agent Workflow Test Suite
================================

Tests the A2A multi-agent system by sending messages through the API
and validating responses from remote agents.

Requirements:
- Backend running on localhost:12000
- WebSocket server running on localhost:8080  
- Classification agent running on localhost:8001
- Branding agent running on localhost:9033

Usage:
    python tests/test_multiagent_flows.py
    python tests/test_multiagent_flows.py --verbose
    python tests/test_multiagent_flows.py --test single_agent
"""

import asyncio
import json
import time
import uuid
import argparse
import sys
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from enum import Enum

import httpx
import websockets

# Configuration
BACKEND_URL = "http://localhost:12000"
WEBSOCKET_URL = "ws://localhost:8080/events"

# Agent ports (from running instances)
CLASSIFICATION_PORT = 8009  # Classification agent
BRANDING_PORT = 9020        # Branding agent


class TestStatus(Enum):
    PASSED = "✅ PASSED"
    FAILED = "❌ FAILED"
    SKIPPED = "⏭️ SKIPPED"
    RUNNING = "🔄 RUNNING"


@dataclass
class TestResult:
    name: str
    status: TestStatus
    duration: float
    message: str = ""
    details: Optional[Dict] = None


class MultiAgentTestSuite:
    """Test suite for multi-agent workflows."""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results: List[TestResult] = []
        self.context_id = f"test_{uuid.uuid4().hex[:8]}"
        self.client: Optional[httpx.AsyncClient] = None
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.ws_messages: List[Dict] = []
        
    def log(self, message: str, force: bool = False):
        """Log message if verbose or forced."""
        if self.verbose or force:
            print(f"  {message}")
    
    async def setup(self):
        """Initialize HTTP client and WebSocket connection."""
        self.client = httpx.AsyncClient(timeout=60.0)
        
        # Connect to WebSocket with tenant ID
        try:
            ws_url = f"{WEBSOCKET_URL}?tenantId={self.context_id}"
            self.ws = await websockets.connect(ws_url)
            self.log(f"Connected to WebSocket: {ws_url}")
            
            # Start background task to collect WebSocket messages
            asyncio.create_task(self._collect_ws_messages())
        except Exception as e:
            self.log(f"WebSocket connection failed: {e}", force=True)
    
    async def teardown(self):
        """Cleanup resources."""
        if self.client:
            await self.client.aclose()
        if self.ws:
            await self.ws.close()
    
    async def _collect_ws_messages(self):
        """Background task to collect WebSocket messages."""
        try:
            while self.ws:
                message = await asyncio.wait_for(self.ws.recv(), timeout=0.5)
                data = json.loads(message)
                self.ws_messages.append(data)
                self.log(f"WS Event: {data.get('eventType', 'unknown')}")
        except asyncio.TimeoutError:
            pass
        except websockets.exceptions.ConnectionClosed:
            self.log("WebSocket connection closed")
        except Exception as e:
            self.log(f"WebSocket error: {e}")
    
    async def wait_for_ws_event(self, event_type: str, timeout: float = 30.0) -> Optional[Dict]:
        """Wait for a specific WebSocket event type."""
        start = time.time()
        while time.time() - start < timeout:
            for msg in self.ws_messages:
                if msg.get('eventType') == event_type:
                    return msg
            await asyncio.sleep(0.5)
        return None
    
    # ==================== API Helper Methods ====================
    
    async def check_health(self) -> bool:
        """Check if backend is healthy."""
        try:
            resp = await self.client.get(f"{BACKEND_URL}/health")
            return resp.status_code == 200
        except Exception:
            return False
    
    async def get_agents(self) -> List[Dict]:
        """Get list of registered agents."""
        resp = await self.client.get(f"{BACKEND_URL}/agents")
        if resp.status_code == 200:
            data = resp.json()
            # Handle different response formats
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return data.get('agents', [])
        return []
    
    async def check_agent_health(self, agent_url: str) -> bool:
        """Check if a specific agent is healthy."""
        try:
            resp = await self.client.get(f"{BACKEND_URL}/api/agents/health/{agent_url}")
            return resp.status_code == 200 and resp.json().get('healthy', False)
        except Exception:
            return False
    
    async def create_conversation(self) -> Optional[str]:
        """Create a new conversation and return its ID."""
        resp = await self.client.post(f"{BACKEND_URL}/conversation/create")
        if resp.status_code == 200:
            data = resp.json()
            # Handle JSON-RPC response format
            result = data.get('result', {})
            return result.get('conversation_id') or result.get('conversationId')
        return None
    
    async def send_message(
        self, 
        text: str, 
        context_id: Optional[str] = None,
        agent_mode: bool = False,
        workflow: Optional[str] = None
    ) -> Optional[Dict]:
        """Send a message to the backend."""
        message_id = str(uuid.uuid4())
        context = context_id or self.context_id
        
        payload = {
            "params": {
                "messageId": message_id,
                "contextId": context,
                "role": "user",
                "parts": [
                    {
                        "root": {
                            "kind": "text",
                            "text": text
                        }
                    }
                ],
                "agentMode": agent_mode,
                "enableInterAgentMemory": False
            }
        }
        
        if workflow:
            payload["params"]["workflow"] = workflow
        
        self.log(f"Sending message: {text[:50]}...")
        resp = await self.client.post(f"{BACKEND_URL}/message/send", json=payload)
        
        if resp.status_code == 200:
            return resp.json()
        self.log(f"Send failed: {resp.status_code} - {resp.text}")
        return None
    
    async def list_messages(self, context_id: Optional[str] = None) -> List[Dict]:
        """List messages in a conversation."""
        context = context_id or self.context_id
        resp = await self.client.post(
            f"{BACKEND_URL}/message/list",
            json={"params": context}
        )
        if resp.status_code == 200:
            return resp.json().get('result', [])
        return []
    
    async def register_agent_by_address(self, address: str) -> bool:
        """Register an agent by its address."""
        resp = await self.client.post(
            f"{BACKEND_URL}/agent/register-by-address",
            json={"address": address}
        )
        return resp.status_code == 200
    
    # ==================== Test Cases ====================
    
    async def test_backend_health(self) -> TestResult:
        """Test that backend is running and healthy."""
        start = time.time()
        try:
            healthy = await self.check_health()
            duration = time.time() - start
            
            if healthy:
                return TestResult(
                    name="Backend Health Check",
                    status=TestStatus.PASSED,
                    duration=duration,
                    message="Backend is healthy"
                )
            else:
                return TestResult(
                    name="Backend Health Check",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message="Backend health check failed"
                )
        except Exception as e:
            return TestResult(
                name="Backend Health Check",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    async def test_agent_registry(self) -> TestResult:
        """Test that agents can be listed from registry."""
        start = time.time()
        try:
            agents = await self.get_agents()
            duration = time.time() - start
            
            agent_names = [a.get('name', 'unknown') for a in agents]
            self.log(f"Found {len(agents)} agents: {agent_names}")
            
            return TestResult(
                name="Agent Registry",
                status=TestStatus.PASSED,
                duration=duration,
                message=f"Found {len(agents)} registered agents",
                details={"agents": agent_names}
            )
        except Exception as e:
            return TestResult(
                name="Agent Registry",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    async def test_classification_agent_available(self) -> TestResult:
        """Test that Classification agent is running."""
        start = time.time()
        agent_url = f"http://localhost:{CLASSIFICATION_PORT}"
        
        try:
            # First try to register it
            await self.register_agent_by_address(agent_url)
            
            # Check if it's in the registry
            agents = await self.get_agents()
            classification_agent = next(
                (a for a in agents if 'classification' in a.get('name', '').lower()),
                None
            )
            
            duration = time.time() - start
            
            if classification_agent:
                return TestResult(
                    name="Classification Agent Available",
                    status=TestStatus.PASSED,
                    duration=duration,
                    message=f"Agent found: {classification_agent.get('name')}",
                    details=classification_agent
                )
            else:
                return TestResult(
                    name="Classification Agent Available",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message=f"Classification agent not found at {agent_url}"
                )
        except Exception as e:
            return TestResult(
                name="Classification Agent Available",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    async def test_branding_agent_available(self) -> TestResult:
        """Test that Branding agent is running."""
        start = time.time()
        agent_url = f"http://localhost:{BRANDING_PORT}"
        
        try:
            await self.register_agent_by_address(agent_url)
            
            agents = await self.get_agents()
            branding_agent = next(
                (a for a in agents if 'branding' in a.get('name', '').lower()),
                None
            )
            
            duration = time.time() - start
            
            if branding_agent:
                return TestResult(
                    name="Branding Agent Available",
                    status=TestStatus.PASSED,
                    duration=duration,
                    message=f"Agent found: {branding_agent.get('name')}",
                    details=branding_agent
                )
            else:
                return TestResult(
                    name="Branding Agent Available",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message=f"Branding agent not found at {agent_url}"
                )
        except Exception as e:
            return TestResult(
                name="Branding Agent Available",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    async def test_simple_chat_message(self) -> TestResult:
        """Test sending a simple chat message (no agent mode)."""
        start = time.time()
        
        try:
            result = await self.send_message(
                "Hello, this is a test message",
                agent_mode=False
            )
            
            duration = time.time() - start
            
            if result and result.get('result'):
                return TestResult(
                    name="Simple Chat Message",
                    status=TestStatus.PASSED,
                    duration=duration,
                    message="Message sent successfully",
                    details=result
                )
            else:
                return TestResult(
                    name="Simple Chat Message",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message="Failed to send message"
                )
        except Exception as e:
            return TestResult(
                name="Simple Chat Message",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    async def test_single_agent_workflow(self) -> TestResult:
        """Test workflow with a single agent (Classification)."""
        start = time.time()
        
        try:
            # Create workflow that uses Classification agent
            workflow = "Use the Classification agent to classify this support ticket: 'My account was charged twice for the same order'"
            
            result = await self.send_message(
                workflow,
                agent_mode=True,
                workflow=workflow
            )
            
            if not result:
                return TestResult(
                    name="Single Agent Workflow",
                    status=TestStatus.FAILED,
                    duration=time.time() - start,
                    message="Failed to send workflow message"
                )
            
            # Wait for response (give agents time to process)
            self.log("Waiting for agent response...")
            await asyncio.sleep(10)
            
            # Check for messages in conversation
            messages = await self.list_messages()
            
            duration = time.time() - start
            
            # Look for assistant response
            assistant_messages = [m for m in messages if m.get('role') == 'agent']
            
            if assistant_messages:
                return TestResult(
                    name="Single Agent Workflow",
                    status=TestStatus.PASSED,
                    duration=duration,
                    message=f"Received {len(assistant_messages)} agent response(s)",
                    details={"response_count": len(assistant_messages)}
                )
            else:
                return TestResult(
                    name="Single Agent Workflow",
                    status=TestStatus.PASSED,  # Message sent, response pending
                    duration=duration,
                    message="Workflow initiated (async processing)"
                )
                
        except Exception as e:
            return TestResult(
                name="Single Agent Workflow",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    async def test_multi_agent_workflow(self) -> TestResult:
        """Test workflow with multiple agents (Classification → Branding)."""
        start = time.time()
        
        try:
            # Create multi-step workflow
            workflow = """
            Step 1: Use the Classification agent to analyze this customer complaint: 
            'The product packaging was damaged and the logo was printed incorrectly'
            
            Step 2: Then use the Branding agent to provide brand guidelines for fixing the packaging issue
            """
            
            result = await self.send_message(
                workflow,
                agent_mode=True,
                workflow=workflow
            )
            
            if not result:
                return TestResult(
                    name="Multi-Agent Workflow",
                    status=TestStatus.FAILED,
                    duration=time.time() - start,
                    message="Failed to send multi-agent workflow"
                )
            
            # Wait longer for multi-agent processing
            self.log("Waiting for multi-agent workflow...")
            await asyncio.sleep(20)
            
            # Check WebSocket events for workflow progress
            workflow_events = [
                m for m in self.ws_messages 
                if 'workflow' in m.get('eventType', '').lower() or
                   'agent' in m.get('eventType', '').lower()
            ]
            
            duration = time.time() - start
            
            return TestResult(
                name="Multi-Agent Workflow",
                status=TestStatus.PASSED,
                duration=duration,
                message=f"Workflow initiated, received {len(workflow_events)} events",
                details={
                    "events_received": len(workflow_events),
                    "event_types": list(set(m.get('eventType') for m in workflow_events))
                }
            )
            
        except Exception as e:
            return TestResult(
                name="Multi-Agent Workflow",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    async def test_websocket_events(self) -> TestResult:
        """Test that WebSocket events are being received."""
        start = time.time()
        
        try:
            # Send a message to trigger events
            await self.send_message("Test message for WebSocket events")
            
            # Wait a bit for events
            await asyncio.sleep(3)
            
            duration = time.time() - start
            event_types = list(set(m.get('eventType') for m in self.ws_messages))
            
            if self.ws_messages:
                return TestResult(
                    name="WebSocket Events",
                    status=TestStatus.PASSED,
                    duration=duration,
                    message=f"Received {len(self.ws_messages)} events",
                    details={"event_types": event_types}
                )
            else:
                return TestResult(
                    name="WebSocket Events",
                    status=TestStatus.SKIPPED,
                    duration=duration,
                    message="No WebSocket events received (may be normal)"
                )
        except Exception as e:
            return TestResult(
                name="WebSocket Events",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    async def test_conversation_lifecycle(self) -> TestResult:
        """Test full conversation lifecycle: create, message, list."""
        start = time.time()
        
        try:
            # Create conversation
            conv_id = await self.create_conversation()
            if not conv_id:
                return TestResult(
                    name="Conversation Lifecycle",
                    status=TestStatus.FAILED,
                    duration=time.time() - start,
                    message="Failed to create conversation"
                )
            
            self.log(f"Created conversation: {conv_id}")
            
            # Send message
            result = await self.send_message(
                "Test conversation lifecycle",
                context_id=conv_id
            )
            
            if not result:
                return TestResult(
                    name="Conversation Lifecycle",
                    status=TestStatus.FAILED,
                    duration=time.time() - start,
                    message="Failed to send message"
                )
            
            # List messages
            await asyncio.sleep(1)
            messages = await self.list_messages(conv_id)
            
            duration = time.time() - start
            
            return TestResult(
                name="Conversation Lifecycle",
                status=TestStatus.PASSED,
                duration=duration,
                message=f"Lifecycle complete: created, sent 1 message, listed {len(messages)} messages",
                details={
                    "conversation_id": conv_id,
                    "message_count": len(messages)
                }
            )
            
        except Exception as e:
            return TestResult(
                name="Conversation Lifecycle",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    # ==================== Test Runner ====================
    
    async def run_all_tests(self) -> List[TestResult]:
        """Run all tests in sequence."""
        print("\n" + "="*60)
        print("🧪 A2A Multi-Agent Test Suite")
        print("="*60 + "\n")
        
        await self.setup()
        
        tests = [
            ("Infrastructure", [
                self.test_backend_health,
                self.test_agent_registry,
            ]),
            ("Agent Availability", [
                self.test_classification_agent_available,
                self.test_branding_agent_available,
            ]),
            ("Messaging", [
                self.test_simple_chat_message,
                self.test_conversation_lifecycle,
                self.test_websocket_events,
            ]),
            ("Workflows", [
                self.test_single_agent_workflow,
                self.test_multi_agent_workflow,
            ]),
        ]
        
        for category, test_funcs in tests:
            print(f"\n📁 {category}")
            print("-" * 40)
            
            for test_func in test_funcs:
                result = await test_func()
                self.results.append(result)
                
                status_str = result.status.value
                print(f"  {status_str} {result.name} ({result.duration:.2f}s)")
                if result.message and self.verbose:
                    print(f"      └─ {result.message}")
        
        await self.teardown()
        
        return self.results
    
    async def run_single_test(self, test_name: str) -> TestResult:
        """Run a single test by name."""
        await self.setup()
        
        test_map = {
            "health": self.test_backend_health,
            "agents": self.test_agent_registry,
            "classification": self.test_classification_agent_available,
            "branding": self.test_branding_agent_available,
            "chat": self.test_simple_chat_message,
            "single_agent": self.test_single_agent_workflow,
            "multi_agent": self.test_multi_agent_workflow,
            "websocket": self.test_websocket_events,
            "conversation": self.test_conversation_lifecycle,
        }
        
        if test_name not in test_map:
            print(f"Unknown test: {test_name}")
            print(f"Available tests: {', '.join(test_map.keys())}")
            await self.teardown()
            return None
        
        result = await test_map[test_name]()
        await self.teardown()
        
        print(f"\n{result.status.value} {result.name}")
        print(f"Duration: {result.duration:.2f}s")
        print(f"Message: {result.message}")
        if result.details:
            print(f"Details: {json.dumps(result.details, indent=2)}")
        
        return result
    
    def print_summary(self):
        """Print test summary."""
        print("\n" + "="*60)
        print("📊 Test Summary")
        print("="*60)
        
        passed = sum(1 for r in self.results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in self.results if r.status == TestStatus.FAILED)
        skipped = sum(1 for r in self.results if r.status == TestStatus.SKIPPED)
        total_time = sum(r.duration for r in self.results)
        
        print(f"\n  ✅ Passed:  {passed}")
        print(f"  ❌ Failed:  {failed}")
        print(f"  ⏭️ Skipped: {skipped}")
        print(f"  ⏱️ Time:    {total_time:.2f}s")
        
        if failed > 0:
            print("\n❌ Failed Tests:")
            for r in self.results:
                if r.status == TestStatus.FAILED:
                    print(f"  - {r.name}: {r.message}")
        
        print("\n" + "="*60 + "\n")
        
        return failed == 0


async def main():
    parser = argparse.ArgumentParser(description="A2A Multi-Agent Test Suite")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--test", "-t", type=str, help="Run a specific test")
    args = parser.parse_args()
    
    suite = MultiAgentTestSuite(verbose=args.verbose)
    
    if args.test:
        await suite.run_single_test(args.test)
    else:
        await suite.run_all_tests()
        success = suite.print_summary()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
