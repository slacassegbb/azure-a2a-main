#!/usr/bin/env python3
"""
Test connectivity to Stripe and Twilio Azure agent endpoints.
"""

import asyncio
import httpx

async def check_agent_health(name: str, url: str):
    """Check if an agent is healthy and responsive."""
    print(f"\n🔍 Testing {name}")
    print(f"   URL: {url}")
    
    # First attempt with longer timeout (30s to allow for cold start)
    try:
        print(f"   ⏳ Attempting health check (30s timeout for cold start)...")
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Try health endpoint
            response = await client.get(f"{url.rstrip('/')}/health")
            print(f"   ✅ Health check: {response.status_code}")
            if response.text:
                print(f"   📄 Response: {response.text[:200]}")
            return True
    except httpx.ConnectError as e:
        print(f"   ❌ Connection error: {e}")
        print(f"   💡 Agent may be stopped or URL is incorrect")
        return False
    except httpx.TimeoutException:
        print(f"   ⏰ Timeout after 30s - agent is not responding")
        print(f"   💡 Try checking Azure Portal to see if container is running")
        return False
    except Exception as e:
        print(f"   ❌ Error: {type(e).__name__}: {e}")
        return False

async def main():
    print("="*60)
    print("Testing Azure Agent Connectivity")
    print("="*60)
    
    agents = [
        ("AI Foundry Stripe Agent", "https://azurefoundry-stripe.ambitioussky-6c709152.westus2.azurecontainerapps.io/"),
        ("Twilio SMS Agent", "https://azurefoundry-twilio2.ambitioussky-6c709152.westus2.azurecontainerapps.io/"),
    ]
    
    results = []
    for name, url in agents:
        is_healthy = await check_agent_health(name, url)
        results.append((name, is_healthy))
    
    print("\n" + "="*60)
    print("Summary:")
    print("="*60)
    for name, is_healthy in results:
        status = "✅ HEALTHY" if is_healthy else "❌ UNAVAILABLE"
        print(f"{status}: {name}")
    
    if all(is_healthy for _, is_healthy in results):
        print("\n✅ All agents are healthy! Scheduled workflows should work.")
    else:
        print("\n⚠️  Some agents are unavailable.")
        print("💡 If agents are on Azure Container Apps with scale-to-zero,")
        print("   they may need to be woken up with a first request.")

if __name__ == "__main__":
    asyncio.run(main())
