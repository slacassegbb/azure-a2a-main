#!/usr/bin/env python3
"""
Test script for Bing search functionality in the foundry agent.
"""
import asyncio
import os
from foundry_agent import create_foundry_calendar_agent

async def test_bing_search():
    """Test the Bing search functionality."""
    print("🚀 Testing Bing Search Integration...")
    
    # Check required environment variables
    required_env_vars = [
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME"
    ]
    
    for var in required_env_vars:
        if not os.getenv(var):
            print(f"❌ Missing required environment variable: {var}")
            return
        print(f"✅ {var} is set")
    
    try:
        # Create the agent
        print("\n📝 Creating agent...")
        agent = await create_foundry_calendar_agent()
        print(f"✅ Agent created: {agent.agent.id}")
        
        # Create a conversation thread
        print("\n🧵 Creating conversation thread...")
        thread = await agent.create_thread()
        print(f"✅ Thread created: {thread.id}")
        
        # Test messages
        test_messages = [
            "Hello! Can you help me?",
            "What's the weather like today?",  # This should trigger web search
            "Search for the latest news about Microsoft Azure AI",  # Direct search request
            "Am I free tomorrow at 2pm?",  # Calendar function
        ]
        
        for i, message in enumerate(test_messages, 1):
            print(f"\n📤 Test {i}: {message}")
            try:
                responses = await agent.run_conversation(thread.id, message)
                for response in responses:
                    print(f"🤖 Response: {response[:200]}...")
                    if len(response) > 200:
                        print("   (truncated)")
            except Exception as e:
                print(f"❌ Error in conversation: {e}")
                
    except Exception as e:
        print(f"❌ Error: {e}")
        
    finally:
        try:
            await agent.cleanup_agent()
            print("\n🧹 Agent cleaned up successfully")
        except Exception as e:
            print(f"⚠️ Warning: Error cleaning up agent: {e}")

if __name__ == "__main__":
    asyncio.run(test_bing_search()) 