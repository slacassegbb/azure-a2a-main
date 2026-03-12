#!/usr/bin/env python3
"""
End-to-end test for the FCT Mortgage Closing Review workflow.

Usage:
    python3 test_fct_workflow.py

What it does:
    1. Authenticates as user_3 (test@example.com / test123)
    2. Enables the 4 required agents with FULL agent data (including URLs)
    3. Uploads the 3 demo documents
    4. Fires the FCT Mortgage Closing Review workflow via /api/query with enable_routing=True
    5. Prints the result (workflow pauses at Teams HITL — respond in Teams to continue)

IMPORTANT LESSONS (don't change these without understanding why):
    - Login: email="test@example.com", password="test123" → user_id="user_3"
    - /agents/session/enable requires FULL agent object (with url, skills, etc.) — not just {"name": "..."}
    - Upload endpoint is /upload (not /api/upload), needs session_id form field
    - Use enable_routing=True + activated_workflow_ids — do NOT pass workflow= trigger phrase
    - Query field is "query" (not "message")
    - Workflow "FCT Mortgage Closing Review" belongs to user_3 (created directly in DB)
"""

import requests
import os
import sys

BASE = "https://backend-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io"
DOCS_DIR = os.path.join(os.path.dirname(__file__), "demo_documents")
FCT_WORKFLOW_ID = "demo-fct-mortgage-closing-2026"
SESSION_ID = "user_3"
DEMO_DOCS = [
    "rbc_mortgage_commitment.pdf",
    "oakville_property_tax_statement.pdf",
    "sarah_mitchell_id.jpg",
]
REQUIRED_AGENTS = [
    "Legal Agent",
    "Microsoft Teams Agent",
    "Microsoft Word Agent",
    "Microsoft Outlook Agent",
]


def login() -> str:
    print("🔐 Logging in as user_3...")
    r = requests.post(f"{BASE}/api/auth/login", json={
        "email": "test@example.com",
        "password": "test123"
    })
    r.raise_for_status()
    token = r.json()["access_token"]
    print(f"   ✅ Token: {token[:30]}...")
    return token


def enable_agents(token: str) -> None:
    """Enable required agents with FULL agent data (including URL and skills)."""
    print("\n🤖 Enabling agents for session user_3...")
    headers = {"Authorization": f"Bearer {token}"}

    # Fetch full agent catalog (includes URLs, skills, etc.)
    catalog = requests.get(f"{BASE}/api/agents", headers=headers).json().get("agents", [])
    catalog_by_name = {a["name"]: a for a in catalog if isinstance(a, dict)}

    for agent_name in REQUIRED_AGENTS:
        agent_data = catalog_by_name.get(agent_name)
        if not agent_data:
            print(f"   ⚠️  {agent_name} not found in catalog — skipping")
            continue
        r = requests.post(f"{BASE}/agents/session/enable", headers=headers, json={
            "session_id": SESSION_ID,
            "agent": agent_data,   # MUST be full object with url/skills, not just {"name": ...}
        })
        status = r.json().get("status", "?")
        print(f"   {'✅' if status == 'success' else '❌'} {agent_name}: {status}")


def upload_documents(token: str) -> list:
    """Upload all demo documents and return their file IDs."""
    print("\n📄 Uploading demo documents...")
    headers = {"Authorization": f"Bearer {token}"}
    file_ids = []

    for fname in DEMO_DOCS:
        fpath = os.path.join(DOCS_DIR, fname)
        if not os.path.exists(fpath):
            print(f"   ⚠️  {fname} not found at {fpath} — skipping")
            continue
        with open(fpath, "rb") as f:
            r = requests.post(
                f"{BASE}/upload",          # Note: /upload NOT /api/upload
                headers=headers,
                files={"file": (fname, f)},
                data={"session_id": SESSION_ID},
            )
        fid = r.json().get("file_id")
        file_ids.append(fid)
        print(f"   ✅ {fname}: {fid}")

    return file_ids


def run_workflow(token: str, file_ids: list) -> dict:
    """Fire the FCT workflow via /api/query with routing enabled."""
    print(f"\n🚀 Firing FCT Mortgage Closing Review workflow...")
    print(f"   Files: {file_ids}")

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.post(f"{BASE}/api/query", headers=headers, json={
        "query": 'Execute the "FCT Mortgage Closing Review" workflow for the uploaded documents.',
        "user_id": SESSION_ID,
        "session_id": SESSION_ID,
        "file_ids": file_ids,
        "activated_workflow_ids": [FCT_WORKFLOW_ID],
        "enable_routing": True,   # Generates proper step-by-step workflow text from DB
        # DO NOT pass "workflow": "..." trigger phrase — use enable_routing instead
        "timeout": 300,
    }, timeout=320)

    return r.json()


def main():
    try:
        token = login()
        enable_agents(token)
        file_ids = upload_documents(token)

        if not file_ids:
            print("❌ No files uploaded — aborting")
            sys.exit(1)

        result = run_workflow(token, file_ids)

        print("\n" + "=" * 60)
        print("📋 WORKFLOW RESULT")
        print("=" * 60)
        result_text = result.get("result", str(result))
        print(result_text[:1500])
        if len(result_text) > 1500:
            print(f"... [truncated, {len(result_text)} total chars]")

        print("\n⏸️  If workflow paused at Teams HITL: respond in Microsoft Teams to continue.")
        print("   After responding, the workflow resumes → Word Agent → Email Agent.")

    except KeyboardInterrupt:
        print("\n⚠️  Interrupted")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
