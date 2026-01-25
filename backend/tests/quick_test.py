#!/usr/bin/env python3
"""
Quick Test Script - Simple connectivity and message test
=========================================================

A lightweight test to quickly verify the system is working.

Usage:
    python tests/quick_test.py
"""

import asyncio
import json
import uuid
import httpx

BACKEND_URL = "http://localhost:12000"


async def quick_test():
    print("\n🔍 Quick System Test\n" + "="*40)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        
        # 1. Health check
        print("\n1️⃣ Backend Health Check...")
        try:
            resp = await client.get(f"{BACKEND_URL}/health")
            if resp.status_code == 200:
                print("   ✅ Backend is healthy")
            else:
                print(f"   ❌ Backend returned {resp.status_code}")
                return
        except Exception as e:
            print(f"   ❌ Cannot connect to backend: {e}")
            return
        
        # 2. List agents
        print("\n2️⃣ Checking Registered Agents...")
        try:
            resp = await client.get(f"{BACKEND_URL}/agents")
            data = resp.json()
            # Handle both list and dict formats
            if isinstance(data, list):
                agents = data
            elif isinstance(data, dict):
                agents = data.get('agents', data.get('result', []))
            else:
                agents = []
            
            print(f"   ✅ Found {len(agents)} agents:")
            for agent in agents:
                if isinstance(agent, dict):
                    name = agent.get('name', 'Unknown')
                    url = agent.get('url', 'N/A')
                    print(f"      • {name} ({url})")
                else:
                    print(f"      • {agent}")
        except Exception as e:
            print(f"   ⚠️ Could not list agents: {e}")
        
        # 3. Send a test message
        print("\n3️⃣ Sending Test Message...")
        try:
            message_id = str(uuid.uuid4())
            context_id = f"quicktest_{uuid.uuid4().hex[:8]}"
            
            payload = {
                "params": {
                    "messageId": message_id,
                    "contextId": context_id,
                    "role": "user",
                    "parts": [{
                        "root": {
                            "kind": "text",
                            "text": "Hello, this is a quick test message"
                        }
                    }],
                    "agentMode": False
                }
            }
            
            resp = await client.post(f"{BACKEND_URL}/message/send", json=payload)
            if resp.status_code == 200:
                result = resp.json()
                print(f"   ✅ Message sent successfully")
                print(f"      Message ID: {result.get('result', {}).get('message_id', 'N/A')}")
            else:
                print(f"   ❌ Failed to send: {resp.status_code}")
        except Exception as e:
            print(f"   ❌ Error sending message: {e}")
        
        # 4. Test agent mode with Classification agent
        print("\n4️⃣ Testing Agent Mode (Classification)...")
        try:
            # First register the agent if not already
            await client.post(
                f"{BACKEND_URL}/agent/register-by-address",
                json={"address": "http://localhost:8009"}
            )
            
            message_id = str(uuid.uuid4())
            context_id = f"agenttest_{uuid.uuid4().hex[:8]}"
            
            workflow = "Use the Classification agent to classify this: 'I was charged incorrectly'"
            
            payload = {
                "params": {
                    "messageId": message_id,
                    "contextId": context_id,
                    "role": "user",
                    "parts": [{
                        "root": {
                            "kind": "text",
                            "text": workflow
                        }
                    }],
                    "agentMode": True,
                    "workflow": workflow
                }
            }
            
            resp = await client.post(f"{BACKEND_URL}/message/send", json=payload)
            if resp.status_code == 200:
                print(f"   ✅ Agent workflow initiated")
                print(f"      Context ID: {context_id}")
                print(f"      (Check backend logs for agent processing)")
            else:
                print(f"   ❌ Failed: {resp.status_code}")
        except Exception as e:
            print(f"   ⚠️ Agent test error: {e}")
    
    print("\n" + "="*40)
    print("✨ Quick test complete!\n")


if __name__ == "__main__":
    asyncio.run(quick_test())
