"""End-to-end test: generate a test video via MCP, trim it, and get the artifact back."""
import asyncio
import json
import uuid
import httpx

A2A_URL = "http://localhost:9045"


async def test_e2e():
    # 1. Health check
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{A2A_URL}/health")
        print(f"Health: {r.status_code} - {r.text}")

    # 2. Send A2A message/send (non-streaming, synchronous)
    payload = {
        "jsonrpc": "2.0",
        "id": "test-e2e-1",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "messageId": str(uuid.uuid4()),
                "parts": [
                    {
                        "kind": "text",
                        "text": (
                            "Use the generate_test_media tool to create a 5-second test video "
                            "called test_input.mp4. Then trim that video to the first 2 seconds "
                            "and save it as trimmed_output.mp4. Finally, call download_file on "
                            "the trimmed output so I can download it."
                        ),
                    }
                ],
            },
        },
    }

    print(f"\nSending A2A message/send...")
    print("Waiting for response (this may take 30-90s)...\n")

    async with httpx.AsyncClient(timeout=180) as c:
        resp = await c.post(
            A2A_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        print(f"Response status: {resp.status_code}")
        body = resp.json()

        if "error" in body:
            err = body["error"]
            print(f"ERROR: JSON-RPC {err.get('code')}: {err.get('message', '')[:500]}")
            return

        result = body.get("result", {})
        state = result.get("state", "?")
        print(f"Task state: {state}")

        # Check for artifacts in the result
        artifacts = result.get("artifacts", [])
        if artifacts:
            print(f"\nArtifacts ({len(artifacts)}):")
            for i, art in enumerate(artifacts):
                parts = art.get("parts", [])
                for p in parts:
                    kind = p.get("kind") or p.get("type", "")
                    if kind == "file":
                        f = p.get("file", {})
                        uri = str(f.get("uri", ""))
                        name = f.get("name", "?")
                        mime = f.get("mimeType", "?")
                        print(f"  [{i}] FILE: {name} | mime={mime}")
                        print(f"       uri: {uri[:150]}...")
                    elif kind == "text":
                        print(f"  [{i}] TEXT: {p.get('text', '')[:200]}")

        # Check for message/status in history
        history = result.get("history", [])
        if history:
            print(f"\nHistory ({len(history)} messages):")
            for msg in history:
                role = msg.get("role", "?")
                parts = msg.get("parts", [])
                for p in parts:
                    kind = p.get("kind") or p.get("type", "")
                    if kind == "text":
                        text = p.get("text", "")[:300]
                        print(f"  [{role}] {text}")
                    elif kind == "file":
                        f = p.get("file", {})
                        uri = str(f.get("uri", ""))
                        name = f.get("name", "?")
                        mime = f.get("mimeType", "?")
                        print(f"  [{role}] FILE: {name} | mime={mime}")
                        print(f"           uri: {uri[:150]}...")
                    elif kind == "data":
                        d = p.get("data", {})
                        if d.get("type") == "token_usage":
                            print(
                                f"  [{role}] TOKENS: "
                                f"{d.get('prompt_tokens', 0)} prompt + "
                                f"{d.get('completion_tokens', 0)} completion = "
                                f"{d.get('total_tokens', 0)} total"
                            )

        # Also check direct status message
        status = result.get("status", {})
        status_msg = status.get("message", {})
        if status_msg:
            parts = status_msg.get("parts", [])
            print(f"\nFinal status message:")
            for p in parts:
                kind = p.get("kind") or p.get("type", "")
                if kind == "text":
                    print(f"  TEXT: {p.get('text', '')[:500]}")
                elif kind == "file":
                    f = p.get("file", {})
                    uri = str(f.get("uri", ""))
                    print(f"  FILE: {f.get('name', '?')} | mime={f.get('mimeType', '?')}")
                    print(f"        uri: {uri[:150]}...")
                elif kind == "data":
                    d = p.get("data", {})
                    if d.get("type") == "token_usage":
                        print(
                            f"  TOKENS: {d.get('prompt_tokens', 0)} prompt + "
                            f"{d.get('completion_tokens', 0)} completion = "
                            f"{d.get('total_tokens', 0)} total"
                        )

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(test_e2e())
