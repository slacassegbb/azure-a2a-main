"""
Test script for Stripe agent with custom MCP implementation.
This verifies that the custom stripe_action tool works correctly.
"""
import asyncio
import logging
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)

from foundry_agent import FoundryStripeAgent

async def test_stripe_agent():
    """Test the Stripe agent with custom MCP client."""
    
    print("\n" + "="*80)
    print("🧪 TESTING STRIPE AGENT WITH CUSTOM MCP CLIENT")
    print("="*80 + "\n")
    
    # Create agent
    agent = FoundryStripeAgent()
    
    # Create agent and thread
    print("📝 Creating agent...")
    await agent.create_agent()
    
    print("🧵 Creating thread...")
    thread_id = await agent.create_thread()
    
    # Test: List customers
    print("\n" + "-"*80)
    print("TEST 1: List Stripe customers")
    print("-"*80)
    
    test_message = "List all customers in Stripe (limit 5)"
    
    print(f"💬 User: {test_message}")
    await agent.add_message(thread_id, test_message)
    
    print("⏳ Running agent...")
    await agent.run_and_wait(thread_id)
    
    response = await agent.get_response(thread_id)
    print(f"\n🤖 Assistant: {response}")
    
    # Print token usage
    if agent.last_token_usage:
        print(f"\n💰 Token Usage:")
        print(f"   Prompt tokens: {agent.last_token_usage['prompt_tokens']:,}")
        print(f"   Completion tokens: {agent.last_token_usage['completion_tokens']:,}")
        print(f"   Total tokens: {agent.last_token_usage['total_tokens']:,}")
    
    # Test: Check balance
    print("\n" + "-"*80)
    print("TEST 2: Check Stripe balance")
    print("-"*80)
    
    test_message = "What is my current Stripe balance?"
    
    print(f"💬 User: {test_message}")
    await agent.add_message(thread_id, test_message)
    
    print("⏳ Running agent...")
    await agent.run_and_wait(thread_id)
    
    response = await agent.get_response(thread_id)
    print(f"\n🤖 Assistant: {response}")
    
    # Print token usage
    if agent.last_token_usage:
        print(f"\n💰 Token Usage:")
        print(f"   Prompt tokens: {agent.last_token_usage['prompt_tokens']:,}")
        print(f"   Completion tokens: {agent.last_token_usage['completion_tokens']:,}")
        print(f"   Total tokens: {agent.last_token_usage['total_tokens']:,}")
    
    print("\n" + "="*80)
    print("✅ TESTS COMPLETED SUCCESSFULLY")
    print("="*80 + "\n")
    
    # Cleanup
    await agent._mcp_client.close()

if __name__ == "__main__":
    asyncio.run(test_stripe_agent())
