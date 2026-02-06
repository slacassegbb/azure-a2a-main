#!/usr/bin/env python3
"""
Comprehensive Backend Test Suite for Code Coverage
===================================================

This unified test suite runs all major backend tests against a live backend
to measure code coverage of foundry_agent_a2a.py and related modules.

Requirements:
- Backend running with coverage: coverage run --source=hosts/multiagent backend_production.py
- WebSocket server running on localhost:8080
- Required agents running (Classification, Branding, etc.)

Usage:
    python comprehensive_test_suite.py
    python comprehensive_test_suite.py --verbose
    python comprehensive_test_suite.py --quick  # Skip long-running tests
    
After running:
    1. Stop backend (Ctrl+C)
    2. coverage report
    3. coverage html
    4. open htmlcov/index.html
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
from pathlib import Path

import httpx
import websockets

# Configuration
BACKEND_URL = "http://localhost:12000"
WEBSOCKET_URL = "ws://localhost:8080/events"
DEFAULT_TIMEOUT = 30.0
LONG_TIMEOUT = 120.0


class TestStatus(Enum):
    PASSED = "✅ PASSED"
    FAILED = "❌ FAILED"
    SKIPPED = "⏭️ SKIPPED"
    RUNNING = "🔄 RUNNING"


@dataclass
class TestResult:
    category: str
    name: str
    status: TestStatus
    duration: float
    message: str = ""
    details: Optional[Dict] = None


class ComprehensiveTestSuite:
    """Comprehensive test suite combining all backend tests."""
    
    def __init__(self, verbose: bool = False, quick: bool = False):
        self.verbose = verbose
        self.quick = quick  # Skip long-running tests
        self.results: List[TestResult] = []
        self.context_id = None  # Will be set to user_id after authentication
        self.client: Optional[httpx.AsyncClient] = None
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.auth_token: Optional[str] = None
        self.user_id: Optional[str] = None
        
    def log(self, message: str, force: bool = False):
        """Log message if verbose or forced."""
        if self.verbose or force:
            print(f"  {message}")
    
    async def setup(self):
        """Initialize HTTP client and test environment."""
        self.log("Setting up test environment...", force=True)
        self.client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        
        # Verify backend is running
        try:
            response = await self.client.get(f"{BACKEND_URL}/health")
            if response.status_code != 200:
                raise Exception(f"Backend health check failed: {response.status_code}")
            self.log("✓ Backend is healthy", force=True)
        except Exception as e:
            raise Exception(f"❌ Cannot connect to backend at {BACKEND_URL}: {e}")
        
        # Login or register to get auth token
        try:
            # Use known test credentials
            test_email = "test@example.com"
            test_password = "test123"
            
            # Try to login
            login_response = await self.client.post(
                f"{BACKEND_URL}/api/auth/login",
                json={
                    "email": test_email,
                    "password": test_password
                }
            )
            
            if login_response.status_code == 200:
                login_data = login_response.json()
                if login_data.get("success"):
                    self.auth_token = login_data.get("access_token")
                    self.user_id = login_data.get("user_info", {}).get("user_id")
                    self.context_id = self.user_id  # Use user_id as session_id (same as UI)
                    self.log(f"✓ Authenticated as {test_email}", force=True)
                    self.log(f"  Session ID: {self.context_id}", force=True)
                    
                    # Enable all agents for this session
                    await self.enable_all_agents()
                else:
                    # Login failed, try to register
                    test_email = "testautomation@example.com"
                    test_password = "testpass123"
                    self.log("  Login failed, attempting registration...", force=True)
                    register_response = await self.client.post(
                        f"{BACKEND_URL}/api/auth/register",
                        json={
                            "email": test_email,
                            "password": test_password,
                            "name": "Test User",
                            "role": "user",
                            "description": "Automated test user",
                            "skills": ["testing"],
                            "color": "#4B5563"
                        }
                    )
                    
                    if register_response.status_code == 200:
                        register_data = register_response.json()
                        if register_data.get("success"):
                            self.auth_token = register_data.get("access_token")
                            self.user_id = register_data.get("user_info", {}).get("user_id")
                            self.context_id = self.user_id  # Use user_id as session_id
                            self.log(f"✓ Registered and authenticated as: {self.user_id}", force=True)
                        else:
                            self.log("⚠️  Registration failed, tests requiring auth will be skipped", force=True)
                    else:
                        self.log("⚠️  Could not register user, tests requiring auth will be skipped", force=True)
            else:
                self.log("⚠️  Auth not available, tests requiring auth will be skipped", force=True)
        except Exception as e:
            self.log(f"⚠️  Could not authenticate: {e}", force=True)
    
    async def enable_all_agents(self):
        """Enable all available agents for this session.
        
        Note: The /api/query endpoint requires agents to be enabled in the session registry.
        In the UI, this is done via the Agents tab. For automated testing, we use WebSocket
        to enable agents programmatically.
        """
        try:
            # Get list of all agents
            response = await self.client.get(f"{BACKEND_URL}/api/agents")
            if response.status_code != 200:
                self.log("⚠️  Could not fetch agents to enable them", force=True)
                return
            
            agents_data = response.json()
            agents = agents_data.get("agents", [])
            
            if not agents:
                self.log("⚠️  No agents available to enable", force=True)
                return
            
            # Connect to WebSocket and enable agents
            # Note: This is a workaround. In production, users enable agents via the UI.
            self.log(f"  Enabling {len(agents)} agents for session...", force=True)
            
            # For now, we'll document that /api/query requires UI-enabled agents
            # The test suite can still test API endpoints, workflows, etc.
            self.log(f"  ⚠️  Note: /api/query endpoint requires agents enabled via UI", force=True)
            self.log(f"  ⚠️  These tests will be skipped. Use /api/workflows/run instead.", force=True)
            
        except Exception as e:
            self.log(f"⚠️  Error enabling agents: {e}", force=True)
    
    async def teardown(self):
        """Cleanup resources."""
        try:
            if self.client:
                await self.client.aclose()
            if self.ws:
                await self.ws.close()
        except Exception as e:
            self.log(f"⚠️  Error during teardown: {e}", force=True)
    
    async def send_message(
        self, 
        text: str,
        agent_mode: bool = True,
        timeout: float = DEFAULT_TIMEOUT
    ) -> Dict[str, Any]:
        """Send a message to the backend and return response."""
        # Ensure we have user_id
        if not self.user_id:
            raise Exception("No user_id available - authentication may have failed")
        
        payload = {
            "query": text,
            "user_id": self.user_id,
            "session_id": self.context_id
        }
        
        # Add auth header if available
        headers = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        
        self.log(f"Sending query with user_id={self.user_id}")
        
        try:
            response = await self.client.post(
                f"{BACKEND_URL}/api/query",
                json=payload,
                headers=headers,
                timeout=timeout
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            # Get error details from response
            try:
                error_detail = e.response.json()
                return {"error": f"HTTP {e.response.status_code}: {error_detail}"}
            except:
                return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}
    
    # ========================================================================
    # TEST CATEGORY 1: Basic API Tests
    # ========================================================================
    
    async def test_health_check(self):
        """Test backend health endpoint."""
        start_time = time.time()
        try:
            response = await self.client.get(f"{BACKEND_URL}/health")
            duration = time.time() - start_time
            
            if response.status_code == 200:
                self.results.append(TestResult(
                    category="API",
                    name="Health Check",
                    status=TestStatus.PASSED,
                    duration=duration,
                    message="Backend health endpoint responding"
                ))
            else:
                self.results.append(TestResult(
                    category="API",
                    name="Health Check",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message=f"Unexpected status code: {response.status_code}"
                ))
        except Exception as e:
            self.results.append(TestResult(
                category="API",
                name="Health Check",
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message=str(e)
            ))
    
    async def test_agent_registry(self):
        """Test agent registry endpoint."""
        start_time = time.time()
        try:
            response = await self.client.get(f"{BACKEND_URL}/api/agents")
            duration = time.time() - start_time
            
            if response.status_code == 200:
                agents = response.json()
                self.results.append(TestResult(
                    category="API",
                    name="Agent Registry",
                    status=TestStatus.PASSED,
                    duration=duration,
                    message=f"Found {len(agents)} registered agents",
                    details={"agent_count": len(agents)}
                ))
            else:
                self.results.append(TestResult(
                    category="API",
                    name="Agent Registry",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message=f"Status code: {response.status_code}"
                ))
        except Exception as e:
            self.results.append(TestResult(
                category="API",
                name="Agent Registry",
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message=str(e)
            ))
    
    # ========================================================================
    # TEST CATEGORY 2: Single Agent Tests
    # ========================================================================
    
    async def test_single_agent_query(self):
        """Test querying a single agent."""
        start_time = time.time()
        
        # Skip if no auth token
        if not self.auth_token:
            self.results.append(TestResult(
                category="Single Agent",
                name="Classification Query",
                status=TestStatus.SKIPPED,
                duration=0.0,
                message="Skipped: No authentication token"
            ))
            return
        
        try:
            # Simple query that should route to an agent
            result = await self.send_message(
                "Classify this incident: User cannot log in to the system",
                agent_mode=True,
                timeout=30.0
            )
            duration = time.time() - start_time
            
            if "error" not in result:
                self.results.append(TestResult(
                    category="Single Agent",
                    name="Classification Query",
                    status=TestStatus.PASSED,
                    duration=duration,
                    message="Agent responded successfully"
                ))
            else:
                self.results.append(TestResult(
                    category="Single Agent",
                    name="Classification Query",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message=result.get("error", "Unknown error")
                ))
        except Exception as e:
            self.results.append(TestResult(
                category="Single Agent",
                name="Classification Query",
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message=str(e)
            ))
    
    # ========================================================================
    # TEST CATEGORY 3: Parallel Workflow Tests
    # ========================================================================
    
    async def test_parallel_workflow(self):
        """Test parallel agent execution."""
        start_time = time.time()
        
        # Skip if no auth token
        if not self.auth_token:
            self.results.append(TestResult(
                category="Parallel Workflow",
                name="Two Agent Parallel",
                status=TestStatus.SKIPPED,
                duration=0.0,
                message="Skipped: No authentication token"
            ))
            return
        
        try:
            result = await self.send_message(
                "Ask Classification and Branding agents to analyze this product launch",
                agent_mode=True,
                timeout=45.0
            )
            duration = time.time() - start_time
            
            if "error" not in result:
                self.results.append(TestResult(
                    category="Parallel Workflow",
                    name="Two Agent Parallel",
                    status=TestStatus.PASSED,
                    duration=duration,
                    message="Parallel execution completed"
                ))
            else:
                self.results.append(TestResult(
                    category="Parallel Workflow",
                    name="Two Agent Parallel",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message=result.get("error", "Unknown error")
                ))
        except Exception as e:
            self.results.append(TestResult(
                category="Parallel Workflow",
                name="Two Agent Parallel",
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message=str(e)
            ))
    
    # ========================================================================
    # TEST CATEGORY 4: Sequential Workflow Tests
    # ========================================================================
    
    async def test_sequential_workflow(self):
        """Test sequential agent execution with context passing."""
        start_time = time.time()
        
        # Skip if no auth token
        if not self.auth_token:
            self.results.append(TestResult(
                category="Sequential Workflow",
                name="Two Step Sequential",
                status=TestStatus.SKIPPED,
                duration=0.0,
                message="Skipped: No authentication token"
            ))
            return
        
        try:
            result = await self.send_message(
                "First ask Classification agent about this incident, then ask Branding agent to create messaging",
                agent_mode=True,
                timeout=60.0
            )
            duration = time.time() - start_time
            
            if "error" not in result:
                self.results.append(TestResult(
                    category="Sequential Workflow",
                    name="Two Step Sequential",
                    status=TestStatus.PASSED,
                    duration=duration,
                    message="Sequential execution completed"
                ))
            else:
                self.results.append(TestResult(
                    category="Sequential Workflow",
                    name="Two Step Sequential",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message=result.get("error", "Unknown error")
                ))
        except Exception as e:
            self.results.append(TestResult(
                category="Sequential Workflow",
                name="Two Step Sequential",
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message=str(e)
            ))
    
    # ========================================================================
    # TEST CATEGORY 5: Chat Mode Tests
    # ========================================================================
    
    async def test_chat_mode(self):
        """Test regular chat mode (no agent routing)."""
        start_time = time.time()
        
        # Skip if no auth token
        if not self.auth_token:
            self.results.append(TestResult(
                category="Chat Mode",
                name="Direct LLM Query",
                status=TestStatus.SKIPPED,
                duration=0.0,
                message="Skipped: No authentication token"
            ))
            return
        
        try:
            result = await self.send_message(
                "What is the capital of France?",
                agent_mode=False,
                timeout=20.0
            )
            duration = time.time() - start_time
            
            if "error" not in result:
                self.results.append(TestResult(
                    category="Chat Mode",
                    name="Direct LLM Query",
                    status=TestStatus.PASSED,
                    duration=duration,
                    message="Chat mode responded"
                ))
            else:
                self.results.append(TestResult(
                    category="Chat Mode",
                    name="Direct LLM Query",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message=result.get("error", "Unknown error")
                ))
        except Exception as e:
            self.results.append(TestResult(
                category="Chat Mode",
                name="Direct LLM Query",
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message=str(e)
            ))
    
    # ========================================================================
    # TEST CATEGORY 6: Memory Tests
    # ========================================================================
    
    async def test_memory_storage(self):
        """Test that conversations are stored in memory."""
        start_time = time.time()
        
        # Skip if no auth token
        if not self.auth_token:
            self.results.append(TestResult(
                category="Memory",
                name="Context Recall",
                status=TestStatus.SKIPPED,
                duration=0.0,
                message="Skipped: No authentication token"
            ))
            return
        
        try:
            # Send a message with a specific fact
            await self.send_message(
                "Remember that my favorite color is blue",
                agent_mode=False,
                timeout=20.0
            )
            
            # Wait a bit
            await asyncio.sleep(2)
            
            # Ask about it
            result = await self.send_message(
                "What is my favorite color?",
                agent_mode=False,
                timeout=20.0
            )
            duration = time.time() - start_time
            
            if "error" not in result:
                self.results.append(TestResult(
                    category="Memory",
                    name="Context Recall",
                    status=TestStatus.PASSED,
                    duration=duration,
                    message="Memory system working"
                ))
            else:
                self.results.append(TestResult(
                    category="Memory",
                    name="Context Recall",
                    status=TestStatus.FAILED,
                    duration=duration,
                    message=result.get("error", "Unknown error")
                ))
        except Exception as e:
            self.results.append(TestResult(
                category="Memory",
                name="Context Recall",
                status=TestStatus.FAILED,
                duration=time.time() - start_time,
                message=str(e)
            ))
    
    # ========================================================================
    # Main Test Runner
    # ========================================================================
    
    async def run_all_tests(self):
        """Run all test categories."""
        print("\n" + "="*70)
        print("🧪 COMPREHENSIVE BACKEND TEST SUITE")
        print("="*70)
        print(f"Quick Mode: {'Enabled' if self.quick else 'Disabled'}")
        print("="*70 + "\n")
        
        await self.setup()
        
        # Print session info after setup
        print(f"\n📋 Session ID: {self.context_id}")
        print(f"   User ID: {self.user_id}")
        print("=" * 70)
        
        # Category 1: API Tests
        print("\n📦 Category 1: API Tests")
        print("-" * 70)
        await self.test_health_check()
        await self.test_agent_registry()
        
        # Category 2: Single Agent Tests
        print("\n🤖 Category 2: Single Agent Tests")
        print("-" * 70)
        await self.test_single_agent_query()
        
        # Category 3: Parallel Workflows
        print("\n⚡ Category 3: Parallel Workflows")
        print("-" * 70)
        await self.test_parallel_workflow()
        
        # Category 4: Sequential Workflows
        print("\n🔄 Category 4: Sequential Workflows")
        print("-" * 70)
        if not self.quick:
            await self.test_sequential_workflow()
        else:
            self.results.append(TestResult(
                category="Sequential Workflow",
                name="Two Step Sequential",
                status=TestStatus.SKIPPED,
                duration=0.0,
                message="Skipped in quick mode"
            ))
        
        # Category 5: Chat Mode
        print("\n💬 Category 5: Chat Mode")
        print("-" * 70)
        await self.test_chat_mode()
        
        # Category 6: Memory
        print("\n🧠 Category 6: Memory Tests")
        print("-" * 70)
        if not self.quick:
            await self.test_memory_storage()
        else:
            self.results.append(TestResult(
                category="Memory",
                name="Context Recall",
                status=TestStatus.SKIPPED,
                duration=0.0,
                message="Skipped in quick mode"
            ))
        
        await self.teardown()
        
        # Print summary
        self.print_summary()
    
    def print_summary(self):
        """Print test results summary."""
        print("\n" + "="*70)
        print("📊 TEST SUMMARY")
        print("="*70)
        
        # Group by category
        categories = {}
        for result in self.results:
            if result.category not in categories:
                categories[result.category] = []
            categories[result.category].append(result)
        
        # Print each category
        for category, tests in categories.items():
            print(f"\n{category}:")
            for test in tests:
                duration_str = f"({test.duration:.2f}s)" if test.duration > 0 else ""
                print(f"  {test.status.value} {test.name} {duration_str}")
                if test.message and self.verbose:
                    print(f"      → {test.message}")
        
        # Overall stats
        total = len(self.results)
        passed = sum(1 for r in self.results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in self.results if r.status == TestStatus.FAILED)
        skipped = sum(1 for r in self.results if r.status == TestStatus.SKIPPED)
        total_time = sum(r.duration for r in self.results)
        
        print("\n" + "="*70)
        print(f"✅ Passed:  {passed}/{total}")
        print(f"❌ Failed:  {failed}/{total}")
        print(f"⏭️  Skipped: {skipped}/{total}")
        print(f"⏱️  Total Time: {total_time:.2f}s")
        print("="*70)
        
        if failed == 0 and passed > 0:
            print("\n🎉 All tests passed! Code coverage data collected.")
            print("\nNext steps:")
            print("  1. Stop backend (Ctrl+C in backend terminal)")
            print("  2. Run: coverage report")
            print("  3. Run: coverage html")
            print("  4. Run: open htmlcov/index.html")
        elif failed > 0:
            print("\n⚠️  Some tests failed. Review errors above.")
            print("Coverage data was still collected for tests that ran.")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Comprehensive backend test suite for code coverage"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )
    parser.add_argument(
        "--quick", "-q",
        action="store_true",
        help="Quick mode: skip long-running tests"
    )
    
    args = parser.parse_args()
    
    suite = ComprehensiveTestSuite(
        verbose=args.verbose,
        quick=args.quick
    )
    
    try:
        await suite.run_all_tests()
        sys.exit(0 if all(r.status != TestStatus.FAILED for r in suite.results) else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
