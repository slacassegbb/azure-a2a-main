#!/usr/bin/env python3
"""
Test Environment Validator
===========================

This script checks which test scenarios in comprehensive_test_suite.py will work
by validating:
1. Backend API is accessible
2. WebSocket server is running
3. Required agents are registered and online
4. Database connectivity
5. Required workflows exist

Run this BEFORE comprehensive_test_suite.py to know what will work.

Usage:
    python validate_test_environment.py
"""

import asyncio
import httpx
import websockets
import json
from typing import Dict, List, Tuple

BACKEND_URL = "http://localhost:12000"
WEBSOCKET_URL = "ws://localhost:8080/events"

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_header(text: str):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text.center(60)}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}\n")

def print_result(name: str, status: bool, details: str = ""):
    icon = f"{Colors.GREEN}✅{Colors.END}" if status else f"{Colors.RED}❌{Colors.END}"
    print(f"{icon} {name}")
    if details:
        print(f"   {Colors.YELLOW}{details}{Colors.END}")

async def check_backend_api() -> Tuple[bool, Dict]:
    """Check if backend API is accessible."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{BACKEND_URL}/health")
            data = response.json()
            return response.status_code == 200, data
    except Exception as e:
        return False, {"error": str(e)}

async def check_websocket_server() -> Tuple[bool, str]:
    """Check if WebSocket server is accessible."""
    try:
        async with websockets.connect(WEBSOCKET_URL) as ws:
            # Try to send a ping
            await asyncio.wait_for(ws.ping(), timeout=2.0)
            return True, "Connected successfully"
    except Exception as e:
        return False, str(e)

async def check_agent_registry() -> Tuple[bool, List[Dict]]:
    """Check available agents in registry."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{BACKEND_URL}/api/agents")
            if response.status_code == 200:
                data = response.json()
                # Response format: {"success": true, "agents": [...]}
                agents = data.get("agents", [])
                return True, agents
            return False, []
    except Exception as e:
        return False, []

async def check_agent_health(agent_name: str, agent_url: str) -> Tuple[bool, str]:
    """Check if specific agent is online."""
    try:
        # Clean up URL - remove /sse if present
        if agent_url.endswith('/sse'):
            base_url = agent_url[:-4]
        else:
            base_url = agent_url
        health_url = base_url.rstrip('/') + '/health'
        
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(health_url)
            return response.status_code == 200, health_url
    except Exception as e:
        return False, str(e)

async def check_workflows() -> Tuple[bool, List[Dict]]:
    """Check available workflows."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{BACKEND_URL}/api/workflows/all")
            if response.status_code == 200:
                data = response.json()
                workflows = data.get("workflows", [])
                return True, workflows
            return False, []
    except Exception as e:
        return False, []

async def main():
    print_header("TEST ENVIRONMENT VALIDATION")
    
    results = {
        "backend": False,
        "websocket": False,
        "registry": False,
        "agents_online": [],
        "workflows": False,
        "test_scenarios": {}
    }
    
    # 1. Check Backend API
    print(f"{Colors.BOLD}1. Backend API{Colors.END}")
    backend_ok, backend_data = await check_backend_api()
    results["backend"] = backend_ok
    
    if backend_ok:
        print_result("Backend API", True, f"Status: {backend_data.get('status')}")
        print(f"   Host: {backend_data.get('host', 'N/A')}")
        print(f"   WebSocket URL: {backend_data.get('websocket_url', 'N/A')}")
    else:
        print_result("Backend API", False, f"Error: {backend_data.get('error', 'Unknown')}")
        print(f"\n{Colors.RED}❌ Backend is not running! Start it with:{Colors.END}")
        print(f"   cd backend && coverage run --source=hosts/multiagent backend_production.py")
        return
    
    # 2. Check WebSocket Server
    print(f"\n{Colors.BOLD}2. WebSocket Server{Colors.END}")
    ws_ok, ws_msg = await check_websocket_server()
    results["websocket"] = ws_ok
    print_result("WebSocket Server", ws_ok, ws_msg if not ws_ok else "")
    
    if not ws_ok:
        print(f"   {Colors.YELLOW}Note: Some tests require WebSocket (chat mode, streaming){Colors.END}")
    
    # 3. Check Agent Registry
    print(f"\n{Colors.BOLD}3. Agent Registry{Colors.END}")
    registry_ok, agents = await check_agent_registry()
    results["registry"] = registry_ok
    
    if registry_ok:
        print_result("Agent Registry", True, f"Found {len(agents)} agents")
        
        # Check each agent's health
        print(f"\n{Colors.BOLD}4. Agent Health Checks{Colors.END}")
        online_agents = []
        offline_agents = []
        
        for agent in agents:
            name = agent.get("name", "Unknown")
            url = agent.get("url", "")
            
            if not url:
                print_result(name, False, "No URL configured")
                offline_agents.append(name)
                continue
            
            is_online, detail = await check_agent_health(name, url)
            
            if is_online:
                print_result(name, True, f"{url}")
                online_agents.append(name)
            else:
                print_result(name, False, f"Cannot reach {url}")
                offline_agents.append(name)
        
        results["agents_online"] = online_agents
        
        print(f"\n   {Colors.GREEN}Online:{Colors.END} {len(online_agents)}")
        print(f"   {Colors.RED}Offline:{Colors.END} {len(offline_agents)}")
        
    else:
        print_result("Agent Registry", False, "Cannot fetch agents")
    
    # 4. Check Workflows
    print(f"\n{Colors.BOLD}5. Available Workflows{Colors.END}")
    workflows_ok, workflows = await check_workflows()
    results["workflows"] = workflows_ok
    
    if workflows_ok:
        print_result("Workflow Database", True, f"Found {len(workflows)} workflows")
        if workflows:
            print("\n   Workflows:")
            for wf in workflows[:10]:  # Show first 10
                print(f"   - {wf.get('name', 'Unnamed')} (ID: {wf.get('id', 'N/A')})")
            if len(workflows) > 10:
                print(f"   ... and {len(workflows) - 10} more")
    else:
        print_result("Workflow Database", False, "Cannot fetch workflows")
    
    # 6. Test Scenario Predictions
    print_header("TEST SCENARIO PREDICTIONS")
    
    # Determine which test categories will work
    scenarios = {
        "API Tests": {
            "will_work": results["backend"],
            "reason": "Backend API accessible" if results["backend"] else "Backend not running"
        },
        "Single Agent Tests": {
            "will_work": results["backend"] and len(results["agents_online"]) > 0,
            "reason": f"{len(results['agents_online'])} agents online" if results["agents_online"] 
                     else "No agents online"
        },
        "Parallel Workflow Tests": {
            "will_work": results["backend"] and len(results["agents_online"]) >= 2,
            "reason": f"Need 2+ agents, have {len(results['agents_online'])}"
        },
        "Sequential Workflow Tests": {
            "will_work": results["backend"] and len(results["agents_online"]) >= 2,
            "reason": f"Need 2+ agents, have {len(results['agents_online'])}"
        },
        "Chat Mode Tests": {
            "will_work": results["backend"] and results["websocket"],
            "reason": "Backend + WebSocket available" if results["backend"] and results["websocket"]
                     else "WebSocket not available" if results["backend"] else "Backend not running"
        },
        "Memory Tests": {
            "will_work": results["backend"],
            "reason": "Depends on memory configuration" if results["backend"] else "Backend not running"
        }
    }
    
    for scenario, info in scenarios.items():
        status_icon = f"{Colors.GREEN}✅" if info["will_work"] else f"{Colors.YELLOW}⚠️"
        print(f"{status_icon} {scenario}{Colors.END}")
        print(f"   {info['reason']}")
    
    # 7. Summary and Recommendations
    print_header("SUMMARY & RECOMMENDATIONS")
    
    total_scenarios = len(scenarios)
    working_scenarios = sum(1 for s in scenarios.values() if s["will_work"])
    
    print(f"Test Coverage: {working_scenarios}/{total_scenarios} scenario categories will work")
    print(f"Agents Online: {len(results['agents_online'])}")
    
    if working_scenarios == total_scenarios:
        print(f"\n{Colors.GREEN}✅ All test scenarios should work!{Colors.END}")
        print(f"\nReady to run comprehensive tests:")
        print(f"   python comprehensive_test_suite.py --verbose")
    elif working_scenarios > 0:
        print(f"\n{Colors.YELLOW}⚠️  Some test scenarios will be skipped{Colors.END}")
        print(f"\nYou can still run tests, but some will be skipped:")
        print(f"   python comprehensive_test_suite.py --verbose")
    else:
        print(f"\n{Colors.RED}❌ No test scenarios will work!{Colors.END}")
        print(f"\nPlease fix the issues above before running tests.")
    
    # Specific recommendations
    print(f"\n{Colors.BOLD}Recommendations:{Colors.END}")
    
    if not results["backend"]:
        print(f"{Colors.RED}• Start backend with coverage tracking{Colors.END}")
        print(f"  cd backend && coverage run --source=hosts/multiagent backend_production.py")
    
    if not results["websocket"]:
        print(f"{Colors.YELLOW}• Start WebSocket server for chat/streaming tests{Colors.END}")
        print(f"  cd backend && python start_websocket.py")
    
    if len(results["agents_online"]) < 2:
        print(f"{Colors.YELLOW}• Start more remote agents for workflow tests{Colors.END}")
        print(f"  (e.g., Classification, Branding, QuickBooks agents)")
    
    if not results["workflows"]:
        print(f"{Colors.YELLOW}• Create some workflows through the UI first{Colors.END}")
    
    print()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Validation interrupted{Colors.END}")
    except Exception as e:
        print(f"\n{Colors.RED}Error: {e}{Colors.END}")
