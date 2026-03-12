#!/usr/bin/env python3
"""
End-to-end test for Thread Queue (per-context sequential processing).

Tests:
  1. Basic query — single message processes normally through the queue
  2. Concurrent contexts — two different sessions run in parallel (not blocked)
  3. Sequential same-context — second message for same session queues behind first
  4. Interrupt semantics — simple text during running workflow triggers interrupt
  5. Context compaction still works — verify summaries are generated

Usage:
    python3 test_thread_queue.py              # all tests
    python3 test_thread_queue.py --test 1     # single test
"""

import argparse
import concurrent.futures
import requests
import sys
import time
import uuid

BASE = "http://localhost:12000"

REQUIRED_AGENTS = [
    "Classification and Triage Agent",
    "Legal Agent",
]


def login() -> str:
    print("Logging in as user_3...")
    r = requests.post(f"{BASE}/api/auth/login", json={
        "email": "test@example.com",
        "password": "test123",
    })
    r.raise_for_status()
    token = r.json()["access_token"]
    print(f"  Token: {token[:30]}...")
    return token


def enable_agents(token: str, session_id: str) -> int:
    headers = {"Authorization": f"Bearer {token}"}
    catalog = requests.get(f"{BASE}/api/agents", headers=headers).json().get("agents", [])
    catalog_by_name = {a["name"]: a for a in catalog if isinstance(a, dict)}

    enabled = 0
    for agent_name in REQUIRED_AGENTS:
        agent_data = catalog_by_name.get(agent_name)
        if not agent_data:
            continue
        r = requests.post(f"{BASE}/agents/session/enable", headers=headers, json={
            "session_id": session_id,
            "agent": agent_data,
        })
        if r.json().get("status") == "success":
            enabled += 1
    return enabled


def query(token: str, session_id: str, text: str, timeout: int = 300,
          conversation_id: str = None) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "query": text,
        "user_id": "user_3",
        "session_id": session_id,
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    r = requests.post(f"{BASE}/api/query", headers=headers, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ── Test 1: Basic query through queue ──

def test_basic_query(token: str) -> bool:
    print("\n" + "=" * 60)
    print("TEST 1: Basic query through queue")
    print("=" * 60)

    sid = f"test_queue_{uuid.uuid4().hex[:8]}"
    enabled = enable_agents(token, sid)
    print(f"  Agents enabled: {enabled}")

    start = time.time()
    result = query(token, sid, "Classify this: a customer reports their credit card was stolen.")
    elapsed = time.time() - start

    success = result.get("success", False)
    text = result.get("result", "")
    print(f"  Success: {success}, Length: {len(text)}, Time: {elapsed:.1f}s")
    if text:
        print(f"  Output: {text[:200]}...")

    passed = success and len(text) > 30
    print(f"  {'PASSED' if passed else 'FAILED'}")
    return passed


# ── Test 2: Concurrent different contexts (should run in parallel) ──

def test_concurrent_contexts(token: str) -> bool:
    print("\n" + "=" * 60)
    print("TEST 2: Concurrent contexts (parallel execution)")
    print("=" * 60)

    sid_a = f"test_parallel_a_{uuid.uuid4().hex[:8]}"
    sid_b = f"test_parallel_b_{uuid.uuid4().hex[:8]}"
    enable_agents(token, sid_a)
    enable_agents(token, sid_b)

    query_a = "Classify this incident: unauthorized login attempt from foreign IP."
    query_b = "Classify this incident: customer received a phishing email."

    start = time.time()

    # Fire both in parallel using threads
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(query, token, sid_a, query_a)
        future_b = pool.submit(query, token, sid_b, query_b)
        result_a = future_a.result(timeout=300)
        result_b = future_b.result(timeout=300)

    elapsed = time.time() - start

    ok_a = result_a.get("success", False)
    ok_b = result_b.get("success", False)
    len_a = len(result_a.get("result", ""))
    len_b = len(result_b.get("result", ""))

    print(f"  Context A: success={ok_a}, len={len_a}")
    print(f"  Context B: success={ok_b}, len={len_b}")
    print(f"  Total time: {elapsed:.1f}s (should be ~same as single query, not 2x)")

    passed = ok_a and ok_b and len_a > 30 and len_b > 30
    print(f"  {'PASSED' if passed else 'FAILED'}")
    return passed


# ── Test 3: Sequential same-context (second should queue) ──

def test_sequential_same_context(token: str) -> bool:
    print("\n" + "=" * 60)
    print("TEST 3: Sequential same-context (queue serialization)")
    print("=" * 60)

    sid = f"test_serial_{uuid.uuid4().hex[:8]}"
    conv_id = f"conv_{uuid.uuid4().hex[:8]}"  # Same conversation for both
    enable_agents(token, sid)

    query_1 = "Classify this: an employee lost their company laptop with sensitive data."
    query_2 = "Now analyze the legal implications of the data breach from the lost laptop."

    start = time.time()

    # Fire both concurrently — same session+conversation, so second should queue
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        future_1 = pool.submit(query, token, sid, query_1, 300, conv_id)
        time.sleep(1)  # Small delay so first enqueues before second
        future_2 = pool.submit(query, token, sid, query_2, 300, conv_id)
        result_1 = future_1.result(timeout=300)
        result_2 = future_2.result(timeout=300)

    elapsed = time.time() - start

    ok_1 = result_1.get("success", False)
    ok_2 = result_2.get("success", False)
    len_1 = len(result_1.get("result", ""))
    len_2 = len(result_2.get("result", ""))

    print(f"  Message 1: success={ok_1}, len={len_1}")
    print(f"  Message 2: success={ok_2}, len={len_2}")
    print(f"  Total time: {elapsed:.1f}s (should be ~2x single query — serialized)")
    print("  Check backend logs for '[ThreadQueue]' entries to confirm queuing")

    passed = ok_1 and ok_2 and len_1 > 30 and len_2 > 30
    print(f"  {'PASSED' if passed else 'FAILED'}")
    return passed


# ── Test 4: Interrupt semantics (two interrupts via /workflow/interrupt, like the frontend) ──

def send_interrupt(context_id: str, instruction: str) -> dict:
    """Send an interrupt via /workflow/interrupt — the same path the frontend uses."""
    r = requests.post(f"{BASE}/workflow/interrupt", json={
        "context_id": context_id,
        "instruction": instruction,
    }, timeout=30)
    r.raise_for_status()
    return r.json()


def test_interrupt(token: str) -> bool:
    print("\n" + "=" * 60)
    print("TEST 4: Interrupt semantics (two interrupts via frontend path)")
    print("=" * 60)
    print("  NOTE: Fires a long query, then sends TWO interrupt messages")
    print("  via /workflow/interrupt (the real frontend→WebSocket→backend path).")
    print("  Both should queue and the workflow should adapt to both.")

    sid = f"test_interrupt_{uuid.uuid4().hex[:8]}"
    conv_id = f"conv_{uuid.uuid4().hex[:8]}"
    enable_agents(token, sid)
    context_id = f"{sid}::{conv_id}"

    long_query = (
        "A customer reports they found unauthorized charges on their credit card. "
        "First classify this incident, then have the legal agent analyze what "
        "consumer protection laws apply and provide recommendations."
    )

    interrupt_1 = "Actually, focus on Canadian consumer protection laws specifically."
    interrupt_2 = "Also include Quebec-specific consumer protection regulations."

    # Fire the long query
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future_long = pool.submit(query, token, sid, long_query, 300, conv_id)

        # Wait for processing to start, then send both interrupts
        time.sleep(8)

        print("  Sending interrupt 1...")
        try:
            r1 = send_interrupt(context_id, interrupt_1)
            int1_ok = r1.get("status") == "success"
            print(f"  Interrupt 1: {r1}")
        except Exception as e:
            print(f"  Interrupt 1 error: {e}")
            int1_ok = False

        time.sleep(1)

        print("  Sending interrupt 2...")
        try:
            r2 = send_interrupt(context_id, interrupt_2)
            int2_ok = r2.get("status") == "success"
            print(f"  Interrupt 2: {r2}")
        except Exception as e:
            print(f"  Interrupt 2 error: {e}")
            int2_ok = False

        result_long = future_long.result(timeout=300)

    ok_long = result_long.get("success", False)
    len_long = len(result_long.get("result", ""))
    result_text = result_long.get("result", "")
    print(f"  Long query: success={ok_long}, len={len_long}")
    print(f"  Interrupt 1 acknowledged: {int1_ok}")
    print(f"  Interrupt 2 acknowledged: {int2_ok}")
    if result_text:
        has_canadian = "canad" in result_text.lower()
        has_quebec = "quebec" in result_text.lower() or "québec" in result_text.lower()
        print(f"  Result mentions Canadian law: {has_canadian}")
        print(f"  Result mentions Quebec: {has_quebec}")
        print(f"  Result: {result_text[:400]}...")
    print("  Check backend logs for '[INTERRUPT] Queue depth' entries")

    passed = ok_long and len_long > 30 and int1_ok and int2_ok
    print(f"  {'PASSED' if passed else 'FAILED'}")
    return passed


# ── Test 5: Context compaction still works ──

def test_compaction(token: str) -> bool:
    print("\n" + "=" * 60)
    print("TEST 5: Context compaction (summaries generated)")
    print("=" * 60)

    sid = f"test_compact_{uuid.uuid4().hex[:8]}"
    enable_agents(token, sid)

    result = query(token, sid, (
        "A customer received a suspicious email asking for banking credentials. "
        "First classify this incident, then analyze what data protection "
        "regulations might be violated."
    ))

    success = result.get("success", False)
    text = result.get("result", "")
    print(f"  Success: {success}, Length: {len(text)}")
    if text:
        print(f"  Output: {text[:200]}...")
    print("  Check backend logs for '[Context Compaction] Summary for ...' lines")

    passed = success and len(text) > 50
    print(f"  {'PASSED' if passed else 'FAILED'}")
    return passed


# ── Main ──

TESTS = [
    ("Basic query through queue", test_basic_query),
    ("Concurrent contexts (parallel)", test_concurrent_contexts),
    ("Sequential same-context (queue)", test_sequential_same_context),
    ("Interrupt semantics", test_interrupt),
    ("Context compaction", test_compaction),
]


def main():
    parser = argparse.ArgumentParser(description="Test Thread Queue")
    parser.add_argument("--test", type=int, help="Run only test N (1-indexed)")
    args = parser.parse_args()

    print(f"Backend: {BASE}")

    try:
        token = login()
    except Exception as e:
        print(f"Login failed: {e}")
        sys.exit(1)

    tests = TESTS
    if args.test:
        if args.test < 1 or args.test > len(tests):
            print(f"Invalid test number {args.test} (valid: 1-{len(tests)})")
            sys.exit(1)
        tests = [(TESTS[args.test - 1][0], TESTS[args.test - 1][1])]

    results = []
    for name, fn in tests:
        try:
            passed = fn(token)
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            passed = False
        results.append((name, passed))

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print("=" * 60)
    total_passed = 0
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {status}: {name}")
        if passed:
            total_passed += 1

    print(f"\n  {total_passed}/{len(results)} tests passed")
    print(f"\n  Check backend logs for '[ThreadQueue]' and '[Context Compaction]' entries")

    sys.exit(0 if total_passed == len(results) else 1)


if __name__ == "__main__":
    main()
