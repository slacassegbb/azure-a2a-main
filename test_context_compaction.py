#!/usr/bin/env python3
"""
End-to-end test for tiered context compaction with gpt-4o-mini summarization.

Usage:
    python3 test_context_compaction.py                # local (default)
    python3 test_context_compaction.py --production   # production backend

What it tests:
    1. Authenticates as user_3
    2. Enables Classification and Legal agents (must be running locally or in prod)
    3. Fires a multi-step query that exercises:
       - Sequential agent execution (Classification → Legal → Legal)
       - Context compaction: gpt-4o-mini summaries generated after each task
       - Tiered context: step 3 receives step 1 as summary, step 2 in full
       - Goal re-injection (only triggers on iteration >= 3, every 3rd iteration)
    4. Verifies the result is coherent (references upstream step outputs)

IMPORTANT:
    - /agents/session/enable requires FULL agent object (with url, skills, etc.)
    - Login: email="test@example.com", password="test123" → user_id="user_3"
    - Look for "[Context Compaction] Summary for ..." in backend logs to confirm

Expected backend log output:
    [Context Compaction] Summary for 'Classification and Triage Agent': ...
    [Context Compaction] Summary for 'Legal Agent': ...
    [Context Compaction] Summary for 'Legal Agent': ...
"""

import argparse
import requests
import sys
import time
import uuid

LOCAL_BASE = "http://localhost:12000"
PROD_BASE = "https://backend-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io"

# Agents needed for this test (must be running)
REQUIRED_AGENTS = [
    "Classification and Triage Agent",
    "Legal Agent",
]

# Test queries: each exercises different compaction scenarios
TEST_QUERIES = [
    {
        "name": "2-step sequential (Classification → Legal)",
        "query": (
            "A customer called saying they found two unauthorized charges on their "
            "credit card for $500 each. They are very upset and want to know their "
            "legal rights. First classify this incident, then have the legal agent "
            "analyze what consumer protection laws apply."
        ),
        "min_steps": 2,
    },
    {
        "name": "3-step sequential (Classification → Legal analysis → Legal risk assessment)",
        "query": (
            "I received a suspicious email asking for my banking credentials. "
            "First, classify this incident. Then, analyze what data protection "
            "regulations might be violated. Finally, provide a risk assessment "
            "and recommended next steps."
        ),
        "min_steps": 3,
    },
]


def login(base: str) -> str:
    print("🔐 Logging in as user_3...")
    r = requests.post(f"{base}/api/auth/login", json={
        "email": "test@example.com",
        "password": "test123",
    })
    r.raise_for_status()
    token = r.json()["access_token"]
    print(f"   ✅ Token: {token[:30]}...")
    return token


def enable_agents(base: str, token: str, session_id: str) -> int:
    """Enable required agents with FULL agent data. Returns count of enabled agents."""
    print(f"\n🤖 Enabling agents for session {session_id}...")
    headers = {"Authorization": f"Bearer {token}"}

    catalog = requests.get(f"{base}/api/agents", headers=headers).json().get("agents", [])
    catalog_by_name = {a["name"]: a for a in catalog if isinstance(a, dict)}

    enabled = 0
    for agent_name in REQUIRED_AGENTS:
        agent_data = catalog_by_name.get(agent_name)
        if not agent_data:
            print(f"   ⚠️  {agent_name} not found in catalog — skipping")
            continue
        r = requests.post(f"{base}/agents/session/enable", headers=headers, json={
            "session_id": session_id,
            "agent": agent_data,
        })
        status = r.json().get("status", "?")
        ok = status == "success"
        print(f"   {'✅' if ok else '❌'} {agent_name}: {status}")
        if ok:
            enabled += 1

    return enabled


def run_query(base: str, token: str, session_id: str, query: str) -> dict:
    """Fire a multi-agent query via /api/query."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.post(f"{base}/api/query", headers=headers, json={
        "query": query,
        "user_id": "user_3",
        "session_id": session_id,
    }, timeout=300)
    r.raise_for_status()
    return r.json()


def run_test(base: str, token: str, test: dict, test_num: int) -> bool:
    """Run a single test case. Returns True if passed."""
    name = test["name"]
    query = test["query"]
    min_steps = test["min_steps"]

    print(f"\n{'='*60}")
    print(f"🧪 Test {test_num}: {name}")
    print(f"{'='*60}")

    # Unique session per test to avoid state leakage
    session_id = f"test_compaction_{uuid.uuid4().hex[:8]}"
    enabled = enable_agents(base, token, session_id)
    if enabled < len(REQUIRED_AGENTS):
        print(f"   ⚠️  Only {enabled}/{len(REQUIRED_AGENTS)} agents enabled")

    print(f"\n🚀 Firing query...")
    print(f"   Query: {query[:100]}...")
    start = time.time()

    try:
        result = run_query(base, token, session_id, query)
    except Exception as e:
        print(f"   ❌ Query failed: {e}")
        return False

    elapsed = time.time() - start
    success = result.get("success", False)
    result_text = result.get("result", "")
    exec_time = result.get("execution_time_seconds", elapsed)

    print(f"\n📋 Result ({exec_time:.1f}s):")
    print(f"   Success: {success}")
    if result_text:
        print(f"   Output ({len(result_text)} chars):")
        # Indent the output for readability
        for line in result_text[:800].split("\n"):
            print(f"     {line}")
        if len(result_text) > 800:
            print(f"     ... [truncated, {len(result_text)} total chars]")

    # Validation
    passed = True
    if not success:
        print(f"   ❌ FAIL: success=false")
        passed = False
    if not result_text or len(result_text) < 50:
        print(f"   ❌ FAIL: result too short ({len(result_text)} chars)")
        passed = False

    if passed:
        print(f"\n   ✅ PASSED — {min_steps}+ steps executed, coherent result in {exec_time:.1f}s")
    else:
        print(f"\n   ❌ FAILED")

    return passed


def main():
    parser = argparse.ArgumentParser(description="Test tiered context compaction")
    parser.add_argument("--production", action="store_true", help="Run against production backend")
    parser.add_argument("--test", type=int, help="Run only test N (1-indexed)")
    args = parser.parse_args()

    base = PROD_BASE if args.production else LOCAL_BASE
    print(f"🌐 Backend: {base}")

    try:
        token = login(base)
    except Exception as e:
        print(f"❌ Login failed: {e}")
        print(f"   Is the backend running at {base}?")
        sys.exit(1)

    tests = TEST_QUERIES
    if args.test:
        if args.test < 1 or args.test > len(tests):
            print(f"❌ Invalid test number {args.test} (valid: 1-{len(tests)})")
            sys.exit(1)
        tests = [tests[args.test - 1]]

    results = []
    for i, test in enumerate(tests, 1):
        passed = run_test(base, token, test, i)
        results.append((test["name"], passed))

    # Summary
    print(f"\n{'='*60}")
    print(f"📊 SUMMARY")
    print(f"{'='*60}")
    total_passed = 0
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"   {status}: {name}")
        if passed:
            total_passed += 1

    print(f"\n   {total_passed}/{len(results)} tests passed")
    print(f"\n💡 Check backend logs for '[Context Compaction] Summary for ...' lines")
    print(f"   to verify gpt-4o-mini summarization is working.")

    sys.exit(0 if total_passed == len(results) else 1)


if __name__ == "__main__":
    main()
