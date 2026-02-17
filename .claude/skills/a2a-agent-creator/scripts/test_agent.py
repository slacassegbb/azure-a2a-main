#!/usr/bin/env python3
"""
A2A Agent Test Runner

Tests a newly scaffolded agent by:
1. Finding Azure credentials from a sibling agent's .env
2. Creating .env for the new agent
3. Installing dependencies
4. Running syntax checks
5. Starting the server
6. Testing /health and /.well-known/agent.json endpoints
7. Sending a real A2A message/send query and verifying the response
8. Reporting results

Usage:
    test_agent.py <agent-directory> [--port PORT] [--skip-query]

Examples:
    test_agent.py remote_agents/azurefoundry_GitHub
    test_agent.py remote_agents/azurefoundry_GitHub --port 9035
    test_agent.py remote_agents/azurefoundry_GitHub --port 9035 --skip-query
"""

import sys
import os
import subprocess
import time
import json
import ast
import shutil
import signal
from pathlib import Path


def find_azure_credentials(agent_dir: Path) -> dict:
    """Find Azure credentials from sibling agents or project root."""
    creds = {}
    needed_keys = [
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME",
    ]

    # Search locations in priority order
    search_paths = []

    # 1. Sibling agent .env files
    remote_agents_dir = agent_dir.parent
    if remote_agents_dir.exists():
        for sibling in sorted(remote_agents_dir.iterdir()):
            if sibling.is_dir() and sibling != agent_dir:
                env_file = sibling / ".env"
                if env_file.exists():
                    search_paths.append(env_file)

    # 2. Project root .env
    project_root = remote_agents_dir.parent
    root_env = project_root / ".env"
    if root_env.exists():
        search_paths.append(root_env)

    for env_file in search_paths:
        try:
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key in needed_keys and value and key not in creds:
                            creds[key] = value
        except Exception:
            continue

        if all(k in creds for k in needed_keys):
            print(f"  Found credentials in: {env_file}")
            break

    return creds


def create_env_file(agent_dir: Path, port: int) -> bool:
    """Create .env file with discovered credentials."""
    env_file = agent_dir / ".env"

    if env_file.exists():
        print(f"  .env already exists, checking credentials...")
        creds = {}
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if value:
                        creds[key] = value

        if "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT" in creds:
            print(f"  Credentials present in existing .env")
            return True

    print(f"  Searching for Azure credentials in sibling agents...")
    creds = find_azure_credentials(agent_dir)

    if "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT" not in creds:
        print(f"  ERROR: Could not find AZURE_AI_FOUNDRY_PROJECT_ENDPOINT")
        print(f"  Searched sibling agents and project root .env files")
        return False

    if "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME" not in creds:
        creds["AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME"] = "gpt-4o"

    # Read .env.example for any extra keys
    extra_keys = {}
    env_example = agent_dir / ".env.example"
    if env_example.exists():
        with open(env_example) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key not in creds:
                        extra_keys[key] = value

    # Write .env
    with open(env_file, "w") as f:
        for key, value in creds.items():
            f.write(f'{key}="{value}"\n')
        f.write(f"A2A_ENDPOINT=localhost\n")
        f.write(f"A2A_PORT={port}\n")
        f.write(f"A2A_HOST=http://localhost:12000\n")
        f.write(f"LOG_LEVEL=INFO\n")
        for key, value in extra_keys.items():
            if key not in ("A2A_ENDPOINT", "A2A_PORT", "A2A_HOST", "LOG_LEVEL"):
                f.write(f"{key}={value}\n")

    print(f"  Created .env with Azure credentials")
    return True


def check_syntax(agent_dir: Path) -> bool:
    """Check Python syntax of all agent files."""
    py_files = ["__main__.py", "foundry_agent.py", "foundry_agent_executor.py"]
    all_ok = True

    for fname in py_files:
        fpath = agent_dir / fname
        if not fpath.exists():
            print(f"  MISSING: {fname}")
            all_ok = False
            continue
        try:
            with open(fpath) as f:
                ast.parse(f.read())
            print(f"  {fname}: OK")
        except SyntaxError as e:
            print(f"  {fname}: SYNTAX ERROR - {e}")
            all_ok = False

    return all_ok


def install_dependencies(agent_dir: Path) -> bool:
    """Install dependencies using uv."""
    pyproject = agent_dir / "pyproject.toml"
    if not pyproject.exists():
        print(f"  ERROR: pyproject.toml not found")
        return False

    venv = agent_dir / ".venv"
    if venv.exists():
        print(f"  .venv exists, skipping install")
        return True

    try:
        result = subprocess.run(
            ["uv", "sync"],
            cwd=str(agent_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            print(f"  Dependencies installed")
            return True
        else:
            # Try alternative install
            result = subprocess.run(
                ["uv", "pip", "install", "-e", "."],
                cwd=str(agent_dir),
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ, "VIRTUAL_ENV": str(venv)},
            )
            if result.returncode == 0:
                print(f"  Dependencies installed (pip fallback)")
                return True
            print(f"  ERROR: {result.stderr[:300]}")
            return False
    except FileNotFoundError:
        print(f"  ERROR: uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh")
        return False
    except subprocess.TimeoutExpired:
        print(f"  ERROR: Dependency install timed out")
        return False


def test_imports(agent_dir: Path) -> bool:
    """Test that all imports resolve."""
    result = subprocess.run(
        [
            "uv", "run", "python3", "-c",
            "from foundry_agent_executor import FoundryAgentExecutor, create_foundry_agent_executor; "
            "from a2a.types import AgentCard, AgentSkill; "
            "print('imports OK')"
        ],
        cwd=str(agent_dir),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode == 0 and "imports OK" in result.stdout:
        print(f"  All imports resolved")
        return True
    else:
        print(f"  Import error: {result.stderr[:300]}")
        return False


def test_server(agent_dir: Path, port: int, skip_query: bool = False) -> dict:
    """Start server, test endpoints, optionally send a real query, return results."""
    results = {"health": False, "agent_card": False, "card_data": None, "live_query": None}

    # Start server in background
    proc = subprocess.Popen(
        ["uv", "run", ".", "--port", str(port)],
        cwd=str(agent_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        # Wait for server to start
        print(f"  Waiting for server on port {port}...")
        import urllib.request
        import urllib.error

        started = False
        for i in range(20):
            time.sleep(1)
            try:
                req = urllib.request.urlopen(f"http://localhost:{port}/health", timeout=3)
                if req.status == 200:
                    health_text = req.read().decode()
                    print(f"  /health: 200 - {health_text}")
                    results["health"] = True
                    started = True
                    break
            except (urllib.error.URLError, ConnectionRefusedError, OSError):
                if i % 5 == 4:
                    print(f"  Still waiting... ({i+1}s)")
                continue

        if not started:
            print(f"  ERROR: Server did not start within 20s")
            # Capture output for debugging
            proc.terminate()
            try:
                out, _ = proc.communicate(timeout=5)
                if out:
                    print(f"  Server output:\n{out[-500:]}")
            except Exception:
                pass
            return results

        # Test agent card
        try:
            req = urllib.request.urlopen(
                f"http://localhost:{port}/.well-known/agent.json", timeout=5
            )
            if req.status == 200:
                card = json.loads(req.read().decode())
                results["agent_card"] = True
                results["card_data"] = card
                print(f"  /agent.json: 200")
                print(f"    Name: {card.get('name')}")
                print(f"    Skills: {len(card.get('skills', []))}")
                for s in card.get("skills", []):
                    print(f"      - {s.get('name')}")
                print(f"    Streaming: {card.get('capabilities', {}).get('streaming')}")
        except Exception as e:
            print(f"  /agent.json: ERROR - {e}")

        # Test live A2A query
        if skip_query:
            print(f"\n  Live query: SKIPPED (--skip-query)")
            results["live_query"] = None
        elif results["agent_card"] and results.get("card_data"):
            results["live_query"] = test_live_query(port, results["card_data"])
        else:
            print(f"\n  Live query: SKIPPED (no agent card)")
            results["live_query"] = None

    finally:
        # Shutdown server
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        print(f"  Server shut down")

    return results


def test_live_query(port: int, card_data: dict) -> bool:
    """Send a real message/send A2A request and verify the response.

    Picks the first example from the agent's first non-human-interaction skill
    as the test query. Falls back to a generic greeting if no examples found.
    """
    import urllib.request
    import urllib.error

    # Pick test query from agent's skill examples, making it self-contained
    # so the agent can respond without asking for more info.
    SAMPLE_TEXT = (
        "The product quality is outstanding and the delivery was fast. "
        "However, the packaging was slightly damaged. Overall a great experience."
    )
    test_query = f"Hello, what can you help me with? Here is some sample text: {SAMPLE_TEXT}"
    skill_used = None
    for skill in card_data.get("skills", []):
        # Skip the human_interaction skill — it won't produce a useful response
        if skill.get("id") == "human_interaction":
            continue
        examples = skill.get("examples", [])
        if examples:
            example = examples[0]
            # Make the query self-contained: if the example looks like it
            # references external data (e.g., "this review", "these responses"),
            # append sample text so the agent has something to work with.
            test_query = f"{example}\n\nHere is the text to analyze: {SAMPLE_TEXT}"
            skill_used = skill.get("name", skill.get("id"))
            break

    print(f"\n  Live query test:")
    if skill_used:
        print(f"    Skill: {skill_used}")
    print(f"    Query: {test_query[:80]}{'...' if len(test_query) > 80 else ''}")

    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": "test-live-1",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "messageId": "msg-live-001",
                "parts": [
                    {"kind": "text", "text": test_query}
                ],
            }
        },
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"http://localhost:{port}/",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # Allow up to 90s for the LLM to respond
        resp = urllib.request.urlopen(req, timeout=90)
        body = json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        print(f"    ERROR: Request failed - {e}")
        return False
    except json.JSONDecodeError as e:
        print(f"    ERROR: Invalid JSON response - {e}")
        return False
    except Exception as e:
        print(f"    ERROR: {e}")
        return False

    # Check for JSON-RPC error
    if "error" in body:
        err = body["error"]
        print(f"    ERROR: JSON-RPC {err.get('code')}: {err.get('message', '')[:200]}")
        return False

    # Validate result structure
    result = body.get("result", {})
    status = result.get("status", {})
    state = status.get("state")
    message = status.get("message", {})
    parts = message.get("parts", [])

    # Extract text from response
    text_parts = [p.get("text", "") for p in parts if p.get("kind") == "text"]
    response_text = " ".join(text_parts).strip()

    # Check for token usage data
    token_data = None
    for p in parts:
        if p.get("kind") == "data" and isinstance(p.get("data"), dict):
            if p["data"].get("type") == "token_usage":
                token_data = p["data"]

    # Normalize state: A2A SDK may return hyphenated (input-required) or
    # underscored (input_required) depending on version
    normalized_state = state.replace("-", "_") if state else state
    print(f"    State: {state}")

    if normalized_state == "completed":
        if response_text:
            # Truncate for display
            preview = response_text[:150].replace("\n", " ")
            print(f"    Response: {preview}{'...' if len(response_text) > 150 else ''}")
            print(f"    Response length: {len(response_text)} chars")
        else:
            print(f"    WARNING: Completed but no text in response")

        if token_data:
            prompt_t = token_data.get("prompt_tokens", 0)
            completion_t = token_data.get("completion_tokens", 0)
            total_t = token_data.get("total_tokens", 0)
            print(f"    Tokens: {prompt_t} prompt + {completion_t} completion = {total_t} total")

        return bool(response_text)

    elif normalized_state == "input_required":
        # Agent asked for clarification — this is valid behavior
        print(f"    Agent requested input (HITL): {response_text[:100]}")
        print(f"    (This is valid — agent needs more context)")
        return True

    elif normalized_state == "failed":
        print(f"    FAILED: {response_text[:200]}")
        return False

    else:
        print(f"    Unexpected state: {state}")
        print(f"    Response: {response_text[:200] if response_text else '(empty)'}")
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: test_agent.py <agent-directory> [--port PORT] [--skip-query]")
        sys.exit(1)

    agent_dir = Path(sys.argv[1]).resolve()
    port = 9035  # default
    skip_query = "--skip-query" in sys.argv

    # Parse --port
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    print(f"Testing agent: {agent_dir.name}")
    print(f"Port: {port}")
    if skip_query:
        print(f"Live query: SKIPPED")
    print()

    # Step 1: Check files exist
    print("[1/7] Checking file structure...")
    required = [
        "__main__.py", "foundry_agent.py", "foundry_agent_executor.py",
        "pyproject.toml", "Dockerfile", ".env.example", ".dockerignore",
        "utils/__init__.py", "utils/self_registration.py",
    ]
    missing = [f for f in required if not (agent_dir / f).exists()]
    if missing:
        print(f"  MISSING FILES: {missing}")
        sys.exit(1)
    print(f"  All {len(required)} required files present")

    # Step 2: Syntax check
    print("\n[2/7] Checking Python syntax...")
    if not check_syntax(agent_dir):
        sys.exit(1)

    # Step 3: Create .env
    print("\n[3/7] Configuring credentials...")
    if not create_env_file(agent_dir, port):
        sys.exit(1)

    # Step 4: Install dependencies
    print("\n[4/7] Installing dependencies...")
    if not install_dependencies(agent_dir):
        sys.exit(1)

    # Step 5: Test imports
    print("\n[5/7] Testing imports...")
    if not test_imports(agent_dir):
        sys.exit(1)

    # Step 6: Test server endpoints
    print(f"\n[6/7] Testing server endpoints...")
    results = test_server(agent_dir, port, skip_query=True)

    # Step 7: Test live A2A query (separate step for clarity)
    if skip_query:
        print(f"\n[7/7] Live A2A query... SKIPPED (--skip-query)")
        results["live_query"] = None
    elif results["health"] and results["agent_card"]:
        print(f"\n[7/7] Testing live A2A query...")
        # Re-start server for the live query test
        results["live_query"] = _run_live_query_test(agent_dir, port, results.get("card_data"))
    else:
        print(f"\n[7/7] Live A2A query... SKIPPED (server not healthy)")
        results["live_query"] = None

    # Summary
    print("\n" + "=" * 50)
    print("TEST RESULTS")
    print("=" * 50)

    checks = [
        ("File structure", True),
        ("Python syntax", True),
        ("Credentials configured", True),
        ("Dependencies installed", True),
        ("Imports resolved", True),
        ("Health endpoint", results["health"]),
        ("Agent card endpoint", results["agent_card"]),
    ]

    # Only include live query in pass/fail if it was actually run
    if results["live_query"] is not None:
        checks.append(("Live A2A query", results["live_query"]))

    all_passed = True
    for name, passed in checks:
        status = "PASS" if passed else "FAIL"
        print(f"  {status}: {name}")
        if not passed:
            all_passed = False

    if results["live_query"] is None and not skip_query:
        print(f"  SKIP: Live A2A query (prerequisite failed)")

    if results.get("card_data"):
        card = results["card_data"]
        print(f"\n  Agent: {card.get('name')}")
        print(f"  Skills: {len(card.get('skills', []))}")
        print(f"  URL: {card.get('url')}")

    print()
    if all_passed:
        print("ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)


def _run_live_query_test(agent_dir: Path, port: int, card_data: dict) -> bool:
    """Start the server, send a live A2A query, shut down, and return pass/fail."""
    proc = subprocess.Popen(
        ["uv", "run", ".", "--port", str(port)],
        cwd=str(agent_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        import urllib.request
        import urllib.error

        # Wait for server
        print(f"  Starting server for live query...")
        started = False
        for i in range(20):
            time.sleep(1)
            try:
                req = urllib.request.urlopen(f"http://localhost:{port}/health", timeout=3)
                if req.status == 200:
                    started = True
                    break
            except (urllib.error.URLError, ConnectionRefusedError, OSError):
                continue

        if not started:
            print(f"  ERROR: Server did not start for live query test")
            return False

        return test_live_query(port, card_data)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


if __name__ == "__main__":
    main()
