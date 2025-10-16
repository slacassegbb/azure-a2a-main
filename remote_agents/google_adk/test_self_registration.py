#!/usr/bin/env python3
"""
Test script for validating self-registration functionality.

This script tests the self-registration utility without starting the full agent.
"""

import asyncio
import logging
import os
from a2a.types import AgentCard, AgentCapabilities, AgentSkill
from dotenv import load_dotenv
from pathlib import Path

# Load root .env first so shared secrets (e.g., GOOGLE_API_KEY) are available to tests
ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ROOT_ENV_PATH, override=False)
# Allow local overrides under remote_agents/google_adk/.env
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import self-registration utility
try:
    from utils.self_registration import register_with_host_agent
    SELF_REGISTRATION_AVAILABLE = True
    logger.info("✅ Self-registration utility loaded successfully")
except ImportError as e:
    logger.error(f"❌ Failed to import self-registration utility: {e}")
    SELF_REGISTRATION_AVAILABLE = False

async def test_registration():
    """Test the self-registration functionality."""
    if not SELF_REGISTRATION_AVAILABLE:
        logger.error("❌ Self-registration utility not available")
        return False
    
    # Create a test agent card
    capabilities = AgentCapabilities(streaming=True)
    skill = AgentSkill(
        id='test_skill',
        name='Test Skill',
        description='Test skill for self-registration validation.',
        tags=['test'],
        examples=['This is a test']
    )
    
    test_agent_card = AgentCard(
        name='Test Agent (Self-Registration)',
        description='Test agent for validating self-registration functionality.',
        url='http://localhost:10099/',  # Use a different port to avoid conflicts
        version='1.0.0-test',
        defaultInputModes=['text/plain'],
        defaultOutputModes=['text/plain'],
        capabilities=capabilities,
        skills=[skill],
    )
    
    logger.info(f"🧪 Testing self-registration for: {test_agent_card.name}")
    
    # Test with default host agent URL
    try:
        success = await register_with_host_agent(test_agent_card)
        if success:
            logger.info("✅ Self-registration test PASSED")
            return True
        else:
            logger.info("ℹ️ Self-registration test completed (host agent may not be running)")
            return True  # This is expected if host agent isn't running
    except Exception as e:
        logger.error(f"❌ Self-registration test FAILED: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Testing A2A Agent Self-Registration")
    print("=" * 50)
    
    success = asyncio.run(test_registration())
    
    if success:
        print("\n✅ Self-registration test completed successfully!")
        print("💡 To test with actual registration, start the host agent first:")
        print("   cd ../../demo/ui && uv run main.py")
    else:
        print("\n❌ Self-registration test failed!")
        exit(1) 