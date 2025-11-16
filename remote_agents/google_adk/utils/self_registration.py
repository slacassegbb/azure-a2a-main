"""
A2A Agent Self-Registration Utility

This utility allows remote agents to automatically register themselves with the host agent
on startup, eliminating the need for manual registration through the UI.

Usage:
    from utils.self_registration import register_with_host_agent
    
    # In your agent's startup code:
    await register_with_host_agent(agent_card)
"""

import asyncio
import logging
import os
from typing import Optional

import httpx
from a2a.types import AgentCard

logger = logging.getLogger(__name__)


async def register_with_host_agent(
    agent_card: AgentCard,
    host_url: Optional[str] = None,
    max_retries: int = 3,
    retry_delay: float = 2.0,
) -> bool:
    print("[DEBUG] Entered register_with_host_agent function")
    print(
        f"[DEBUG] os.environ.get('A2A_HOST_AGENT_URL') = {os.environ.get('A2A_HOST_AGENT_URL')}"
    )
    """Register this agent with the host agent for automatic discovery.
    
    Args:
        agent_card: The agent card to register
        host_url: URL of the host agent (defaults to localhost:12000)
        max_retries: Maximum number of registration attempts
        retry_delay: Delay between retry attempts in seconds
        
    Returns:
        bool: True if registration successful, False otherwise
    """
    if not host_url:
        host_url = get_host_agent_url()

    if not host_url:
        logger.info("ℹ️ Host agent URL not provided; skipping self-registration")
        return False

    registration_url = f"{host_url.rstrip('/')}/agent/self-register"

    logger.info(f"[DEBUG] host_url resolved to: {host_url}")
    logger.info(f"[DEBUG] registration_url resolved to: {registration_url}")

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                logger.info(f"🔄 Self-registration attempt {attempt + 1}/{max_retries}")
                await asyncio.sleep(retry_delay)
            else:
                logger.info(
                    f"🤝 Attempting self-registration with host agent at: {registration_url}"
                )

            async with httpx.AsyncClient(timeout=10.0) as client:
                # Prepare registration payload
                payload = {
                    "agent_address": agent_card.url,
                    "agent_card": agent_card.model_dump(),
                }
                logger.info(f"[DEBUG] Registration payload: {payload}")

                response = await client.post(registration_url, json=payload)

                if response.status_code == 200:
                    result = response.json()
                    if result.get("success"):
                        logger.info(
                            f"✅ Successfully registered with host agent: {result.get('message')}"
                        )
                        return True
                    else:
                        logger.warning(
                            f"⚠️ Host agent rejected registration: {result.get('error')}"
                        )
                        if attempt == max_retries - 1:
                            return False
                        continue
                else:
                    logger.warning(
                        f"⚠️ Host agent returned status {response.status_code}: {response.text}"
                    )
                    if attempt == max_retries - 1:
                        return False
                    continue

        except httpx.ConnectError:
            if attempt == 0:
                logger.info(f"ℹ️ Host agent not available at {registration_url}")
            if attempt == max_retries - 1:
                logger.info(
                    f"ℹ️ Host agent still not available after {max_retries} attempts - continuing without registration"
                )
                return False
            continue
        except Exception as e:
            logger.warning(f"⚠️ Self-registration attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                return False
            continue

    return False


def get_host_agent_url() -> str:
    """Get the host agent URL from environment variables or default."""
    if "BACKEND_SERVER_URL" in os.environ:
        host_url = os.getenv("BACKEND_SERVER_URL", "")
    elif "A2A_HOST" in os.environ:
        host_url = os.getenv("A2A_HOST", "")
    elif "A2A_HOST_AGENT_URL" in os.environ:
        host_url = os.getenv("A2A_HOST_AGENT_URL", "")
    else:
        return "http://localhost:12000"

    return host_url.strip()


async def register_with_host_agent_async_startup(agent_card: AgentCard) -> None:
    """
    Async startup variant that runs registration in the background.

    This is useful for agents that need to start their server immediately
    and handle registration as a background task.
    """
    try:
        success = await register_with_host_agent(agent_card)
        if success:
            logger.info(f"🎉 Background registration successful for '{agent_card.name}'")
        else:
            logger.info(
                f"📡 Background registration failed for '{agent_card.name}' - agent still functional"
            )
    except Exception as e:
        logger.warning(f"⚠️ Background registration error for '{agent_card.name}': {e}")


def register_with_host_agent_background(agent_card: AgentCard) -> None:
    """
    Fire-and-forget background registration.

    Starts registration as a background task without blocking agent startup.
    """

    async def _register():
        await register_with_host_agent_async_startup(agent_card)

    # Start registration as background task
    asyncio.create_task(_register())
    logger.info(f"🚀 Started background registration task for '{agent_card.name}'")
