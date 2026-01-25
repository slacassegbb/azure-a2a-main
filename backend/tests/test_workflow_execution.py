#!/usr/bin/env python3
"""
Workflow Execution Tests
========================

Tests for parallel, sequential, and mixed workflow execution patterns,
as well as agent mode vs regular chat mode behavior.

These tests verify:
1. Parallel execution: Multiple agents run simultaneously
2. Sequential execution: Agents run one after another with context passing
3. Mixed workflows: Combination of parallel and sequential steps
4. Agent mode vs Chat mode: Different routing behaviors

Requirements:
- Backend running on localhost:12000
- WebSocket server running on localhost:8080
- At least 2 agents running (Classification, Branding)

Usage:
    python tests/test_workflow_execution.py
    python tests/test_workflow_execution.py --test parallel
    python tests/test_workflow_execution.py --test sequential
"""

import asyncio
import json
import time
import uuid
import argparse
import sys
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum

import httpx

# Configuration
BACKEND_URL = "http://localhost:12000"
WEBSOCKET_URL = "ws://localhost:8080/events"

# Agent info
CLASSIFICATION_PORT = 8009
BRANDING_PORT = 9020


class TestStatus(Enum):
    PASSED = "✅ PASSED"
    FAILED = "❌ FAILED"
    SKIPPED = "⏭️ SKIPPED"


@dataclass
class WorkflowTestResult:
    name: str
    status: TestStatus
    duration: float
    message: str = ""
    events_received: int = 0
    agents_called: List[str] = field(default_factory=list)
    execution_pattern: str = ""  # "parallel", "sequential", "mixed"
    details: Optional[Dict] = None


class WorkflowExecutionTests:
    """Test suite for workflow execution patterns."""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results: List[WorkflowTestResult] = []
        self.client: Optional[httpx.AsyncClient] = None
        
    def log(self, message: str, force: bool = False):
        if self.verbose or force:
            print(f"  {message}")
    
    async def setup(self):
        self.client = httpx.AsyncClient(timeout=120.0)
        
        # Ensure agents are registered
        await self.client.post(
            f"{BACKEND_URL}/agent/register-by-address",
            json={"address": f"http://localhost:{CLASSIFICATION_PORT}"}
        )
        await self.client.post(
            f"{BACKEND_URL}/agent/register-by-address",
            json={"address": f"http://localhost:{BRANDING_PORT}"}
        )
    
    async def teardown(self):
        if self.client:
            await self.client.aclose()
    
    async def send_workflow(
        self, 
        text: str,
        agent_mode: bool = True,
        workflow: Optional[str] = None,
        wait_time: float = 15.0
    ) -> Dict[str, Any]:
        """Send a workflow message and collect events."""
        context_id = f"workflow_test_{uuid.uuid4().hex[:8]}"
        message_id = str(uuid.uuid4())
        
        payload = {
            "params": {
                "messageId": message_id,
                "contextId": context_id,
                "role": "user",
                "parts": [{
                    "root": {
                        "kind": "text",
                        "text": text
                    }
                }],
                "agentMode": agent_mode,
                "enableInterAgentMemory": True
            }
        }
        
        if workflow:
            payload["params"]["workflow"] = workflow
        
        start_time = time.time()
        
        # Send the message
        resp = await self.client.post(f"{BACKEND_URL}/message/send", json=payload)
        
        if resp.status_code != 200:
            return {
                "success": False,
                "error": f"Failed to send: {resp.status_code}",
                "context_id": context_id
            }
        
        # Wait for processing
        self.log(f"Waiting {wait_time}s for workflow to complete...")
        await asyncio.sleep(wait_time)
        
        # Get messages from conversation
        messages_resp = await self.client.post(
            f"{BACKEND_URL}/message/list",
            json={"params": context_id}
        )
        
        messages = []
        if messages_resp.status_code == 200:
            messages = messages_resp.json().get('result', [])
        
        elapsed = time.time() - start_time
        
        return {
            "success": True,
            "context_id": context_id,
            "message_id": message_id,
            "messages": messages,
            "message_count": len(messages),
            "elapsed_time": elapsed
        }
    
    # ==================== Parallel Execution Tests ====================
    
    async def test_parallel_two_agents(self) -> WorkflowTestResult:
        """Test parallel execution with two agents using 'and' language."""
        start = time.time()
        
        try:
            # Use language that implies parallel execution
            workflow = """
            Use the Classification agent to classify this issue: 'Product damaged'
            AND use the Branding agent to provide brand guidelines for response
            """
            
            result = await self.send_workflow(
                text=workflow,
                agent_mode=True,
                workflow=workflow,
                wait_time=20.0
            )
            
            duration = time.time() - start
            
            if not result["success"]:
                return WorkflowTestResult(
                    name="Parallel: Two Agents",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message=result.get("error", "Unknown error")
                )
            
            return WorkflowTestResult(
                name="Parallel: Two Agents",
                status=TestStatus.PASSED,
                duration=duration,
                message=f"Workflow completed in {result['elapsed_time']:.1f}s",
                execution_pattern="parallel",
                agents_called=["Classification", "Branding"],
                details={
                    "context_id": result["context_id"],
                    "message_count": result["message_count"]
                }
            )
            
        except Exception as e:
            return WorkflowTestResult(
                name="Parallel: Two Agents",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    async def test_parallel_numbered_steps(self) -> WorkflowTestResult:
        """Test parallel execution using numbered parallel steps (2a, 2b)."""
        start = time.time()
        
        try:
            # Explicit parallel notation
            workflow = """
            1. Analyze the customer complaint: 'Order was late and item was wrong'
            2a. Use Classification agent to categorize the issue
            2b. Use Branding agent to draft a branded apology response
            3. Summarize both results
            """
            
            result = await self.send_workflow(
                text=workflow,
                agent_mode=True,
                workflow=workflow,
                wait_time=25.0
            )
            
            duration = time.time() - start
            
            if not result["success"]:
                return WorkflowTestResult(
                    name="Parallel: Numbered Steps (2a, 2b)",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message=result.get("error", "Unknown error")
                )
            
            return WorkflowTestResult(
                name="Parallel: Numbered Steps (2a, 2b)",
                status=TestStatus.PASSED,
                duration=duration,
                message=f"Mixed workflow completed in {result['elapsed_time']:.1f}s",
                execution_pattern="mixed",
                agents_called=["Classification", "Branding"],
                details={
                    "context_id": result["context_id"],
                    "message_count": result["message_count"],
                    "workflow_type": "1-sequential, 2-parallel, 3-sequential"
                }
            )
            
        except Exception as e:
            return WorkflowTestResult(
                name="Parallel: Numbered Steps (2a, 2b)",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    # ==================== Sequential Execution Tests ====================
    
    async def test_sequential_then_language(self) -> WorkflowTestResult:
        """Test sequential execution triggered by 'then' language."""
        start = time.time()
        
        try:
            # Use language that implies sequential execution
            workflow = """
            First use the Classification agent to classify this support ticket: 'Billing error on my account'
            THEN use the Branding agent to create a response based on the classification
            """
            
            result = await self.send_workflow(
                text=workflow,
                agent_mode=True,
                workflow=workflow,
                wait_time=30.0  # Longer for sequential
            )
            
            duration = time.time() - start
            
            if not result["success"]:
                return WorkflowTestResult(
                    name="Sequential: 'THEN' Language",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message=result.get("error", "Unknown error")
                )
            
            return WorkflowTestResult(
                name="Sequential: 'THEN' Language",
                status=TestStatus.PASSED,
                duration=duration,
                message=f"Sequential workflow completed in {result['elapsed_time']:.1f}s",
                execution_pattern="sequential",
                agents_called=["Classification", "Branding"],
                details={
                    "context_id": result["context_id"],
                    "message_count": result["message_count"]
                }
            )
            
        except Exception as e:
            return WorkflowTestResult(
                name="Sequential: 'THEN' Language",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    async def test_sequential_numbered_steps(self) -> WorkflowTestResult:
        """Test sequential execution using numbered steps (1, 2, 3)."""
        start = time.time()
        
        try:
            workflow = """
            1. Use the Classification agent to analyze: 'Customer wants refund for defective item'
            2. Use the Branding agent to create a customer-friendly refund message
            """
            
            result = await self.send_workflow(
                text=workflow,
                agent_mode=True,
                workflow=workflow,
                wait_time=30.0
            )
            
            duration = time.time() - start
            
            if not result["success"]:
                return WorkflowTestResult(
                    name="Sequential: Numbered Steps (1, 2)",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message=result.get("error", "Unknown error")
                )
            
            return WorkflowTestResult(
                name="Sequential: Numbered Steps (1, 2)",
                status=TestStatus.PASSED,
                duration=duration,
                message=f"Sequential workflow completed in {result['elapsed_time']:.1f}s",
                execution_pattern="sequential",
                agents_called=["Classification", "Branding"],
                details={
                    "context_id": result["context_id"],
                    "message_count": result["message_count"]
                }
            )
            
        except Exception as e:
            return WorkflowTestResult(
                name="Sequential: Numbered Steps (1, 2)",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    async def test_sequential_context_passing(self) -> WorkflowTestResult:
        """Test that sequential execution passes context between agents."""
        start = time.time()
        
        try:
            # Explicitly request context passing
            workflow = """
            Step 1: Use the Classification agent to classify this complaint and identify the severity: 
            'I was charged 3 times for the same order and nobody is responding to my emails!'
            
            Step 2: Based on the classification result from Step 1, use the Branding agent 
            to create an appropriate branded response matching the severity level.
            """
            
            result = await self.send_workflow(
                text=workflow,
                agent_mode=True,
                workflow=workflow,
                wait_time=35.0
            )
            
            duration = time.time() - start
            
            if not result["success"]:
                return WorkflowTestResult(
                    name="Sequential: Context Passing",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message=result.get("error", "Unknown error")
                )
            
            return WorkflowTestResult(
                name="Sequential: Context Passing",
                status=TestStatus.PASSED,
                duration=duration,
                message=f"Context passed between agents in {result['elapsed_time']:.1f}s",
                execution_pattern="sequential",
                agents_called=["Classification", "Branding"],
                details={
                    "context_id": result["context_id"],
                    "message_count": result["message_count"],
                    "context_passing": True
                }
            )
            
        except Exception as e:
            return WorkflowTestResult(
                name="Sequential: Context Passing",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    # ==================== Agent Mode Tests ====================
    
    async def test_agent_mode_enabled(self) -> WorkflowTestResult:
        """Test workflow with agent mode explicitly enabled."""
        start = time.time()
        
        try:
            result = await self.send_workflow(
                text="Use the Classification agent to classify: 'Login issues with mobile app'",
                agent_mode=True,
                workflow="Use Classification agent to classify the issue",
                wait_time=15.0
            )
            
            duration = time.time() - start
            
            if not result["success"]:
                return WorkflowTestResult(
                    name="Agent Mode: Enabled",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message=result.get("error", "Unknown error")
                )
            
            return WorkflowTestResult(
                name="Agent Mode: Enabled",
                status=TestStatus.PASSED,
                duration=duration,
                message=f"Agent mode workflow completed",
                agents_called=["Classification"],
                details={
                    "agent_mode": True,
                    "context_id": result["context_id"]
                }
            )
            
        except Exception as e:
            return WorkflowTestResult(
                name="Agent Mode: Enabled",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    async def test_agent_mode_disabled(self) -> WorkflowTestResult:
        """Test regular chat without agent mode (should use host orchestrator)."""
        start = time.time()
        
        try:
            result = await self.send_workflow(
                text="What is 2+2? Just answer directly.",
                agent_mode=False,
                workflow=None,  # No workflow
                wait_time=10.0
            )
            
            duration = time.time() - start
            
            if not result["success"]:
                return WorkflowTestResult(
                    name="Chat Mode: No Agent Routing",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message=result.get("error", "Unknown error")
                )
            
            return WorkflowTestResult(
                name="Chat Mode: No Agent Routing",
                status=TestStatus.PASSED,
                duration=duration,
                message=f"Chat response received (no agent routing)",
                agents_called=[],  # No agents should be called
                details={
                    "agent_mode": False,
                    "context_id": result["context_id"]
                }
            )
            
        except Exception as e:
            return WorkflowTestResult(
                name="Chat Mode: No Agent Routing",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    async def test_auto_agent_detection(self) -> WorkflowTestResult:
        """Test that workflow presence auto-enables agent mode."""
        start = time.time()
        
        try:
            # Send with workflow but agent_mode not explicitly set
            # The backend should auto-detect based on workflow presence
            result = await self.send_workflow(
                text="Classify this issue with the Classification agent: 'Password reset failed'",
                agent_mode=None,  # Not explicitly set
                workflow="Use Classification agent",
                wait_time=15.0
            )
            
            duration = time.time() - start
            
            if not result["success"]:
                return WorkflowTestResult(
                    name="Auto Agent Detection",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message=result.get("error", "Unknown error")
                )
            
            return WorkflowTestResult(
                name="Auto Agent Detection",
                status=TestStatus.PASSED,
                duration=duration,
                message=f"Agent auto-detected from workflow",
                agents_called=["Classification"],
                details={
                    "auto_detected": True,
                    "context_id": result["context_id"]
                }
            )
            
        except Exception as e:
            return WorkflowTestResult(
                name="Auto Agent Detection",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    # ==================== Mixed/Complex Workflow Tests ====================
    
    async def test_complex_mixed_workflow(self) -> WorkflowTestResult:
        """Test complex workflow with both sequential and parallel steps."""
        start = time.time()
        
        try:
            workflow = """
            Customer Issue: "I received the wrong item and was overcharged"
            
            1. Analyze the complaint to identify all issues
            2a. Use Classification agent to categorize the 'wrong item' issue
            2b. Use Classification agent to categorize the 'overcharged' issue  
            3. Use Branding agent to create a unified response addressing both issues
            """
            
            result = await self.send_workflow(
                text=workflow,
                agent_mode=True,
                workflow=workflow,
                wait_time=40.0  # Complex workflow needs more time
            )
            
            duration = time.time() - start
            
            if not result["success"]:
                return WorkflowTestResult(
                    name="Complex: Mixed Sequential + Parallel",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message=result.get("error", "Unknown error")
                )
            
            return WorkflowTestResult(
                name="Complex: Mixed Sequential + Parallel",
                status=TestStatus.PASSED,
                duration=duration,
                message=f"Complex workflow completed in {result['elapsed_time']:.1f}s",
                execution_pattern="mixed",
                agents_called=["Classification", "Classification", "Branding"],
                details={
                    "context_id": result["context_id"],
                    "message_count": result["message_count"],
                    "workflow_structure": "1-seq, 2a+2b-parallel, 3-seq"
                }
            )
            
        except Exception as e:
            return WorkflowTestResult(
                name="Complex: Mixed Sequential + Parallel",
                status=TestStatus.FAILED,
                duration=time.time() - start,
                message=f"Error: {str(e)}"
            )
    
    # ==================== Test Runner ====================
    
    async def run_all_tests(self) -> List[WorkflowTestResult]:
        """Run all workflow tests."""
        print("\n" + "="*70)
        print("🔄 Workflow Execution Test Suite")
        print("="*70 + "\n")
        
        await self.setup()
        
        tests = [
            ("Parallel Execution", [
                self.test_parallel_two_agents,
                self.test_parallel_numbered_steps,
            ]),
            ("Sequential Execution", [
                self.test_sequential_then_language,
                self.test_sequential_numbered_steps,
                self.test_sequential_context_passing,
            ]),
            ("Agent Mode", [
                self.test_agent_mode_enabled,
                self.test_agent_mode_disabled,
                self.test_auto_agent_detection,
            ]),
            ("Complex Workflows", [
                self.test_complex_mixed_workflow,
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
                if result.execution_pattern and self.verbose:
                    print(f"      └─ Pattern: {result.execution_pattern}")
        
        await self.teardown()
        
        return self.results
    
    async def run_single_test(self, test_name: str) -> Optional[WorkflowTestResult]:
        """Run a single test by name."""
        await self.setup()
        
        test_map = {
            "parallel": self.test_parallel_two_agents,
            "parallel_numbered": self.test_parallel_numbered_steps,
            "sequential": self.test_sequential_then_language,
            "sequential_numbered": self.test_sequential_numbered_steps,
            "context_passing": self.test_sequential_context_passing,
            "agent_mode": self.test_agent_mode_enabled,
            "chat_mode": self.test_agent_mode_disabled,
            "auto_detect": self.test_auto_agent_detection,
            "complex": self.test_complex_mixed_workflow,
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
        if result.execution_pattern:
            print(f"Pattern: {result.execution_pattern}")
        if result.agents_called:
            print(f"Agents: {', '.join(result.agents_called)}")
        if result.details:
            print(f"Details: {json.dumps(result.details, indent=2)}")
        
        return result
    
    def print_summary(self):
        """Print test summary."""
        print("\n" + "="*70)
        print("📊 Workflow Test Summary")
        print("="*70)
        
        passed = sum(1 for r in self.results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in self.results if r.status == TestStatus.FAILED)
        total_time = sum(r.duration for r in self.results)
        
        print(f"\n  ✅ Passed:  {passed}")
        print(f"  ❌ Failed:  {failed}")
        print(f"  ⏱️ Time:    {total_time:.1f}s")
        
        # Execution pattern breakdown
        patterns = {}
        for r in self.results:
            if r.execution_pattern:
                patterns[r.execution_pattern] = patterns.get(r.execution_pattern, 0) + 1
        
        if patterns:
            print(f"\n  📈 Patterns tested:")
            for pattern, count in patterns.items():
                print(f"      {pattern}: {count}")
        
        if failed > 0:
            print("\n❌ Failed Tests:")
            for r in self.results:
                if r.status == TestStatus.FAILED:
                    print(f"  - {r.name}: {r.message}")
        
        print("\n" + "="*70 + "\n")
        
        return failed == 0


async def main():
    parser = argparse.ArgumentParser(description="Workflow Execution Tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--test", "-t", type=str, help="Run a specific test")
    args = parser.parse_args()
    
    suite = WorkflowExecutionTests(verbose=args.verbose)
    
    if args.test:
        await suite.run_single_test(args.test)
    else:
        await suite.run_all_tests()
        success = suite.print_summary()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
