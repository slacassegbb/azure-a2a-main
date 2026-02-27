"""Shared credential helper for remote agents.

Call the platform's credential service to get per-user credentials at request time.
Falls back gracefully — agents can use env vars as default if no user config exists.

Usage in an agent:
    from shared.credential_helper import get_user_credentials

    user_creds = await get_user_credentials(context_id, "Twilio SMS Agent")
    phone = (user_creds or {}).get("to_phone_number") or os.environ.get("TWILIO_DEFAULT_TO_NUMBER")
"""

import os
import logging
from typing import Optional, Dict

import httpx

logger = logging.getLogger(__name__)


async def get_user_credentials(context_id: str, agent_name: str) -> Optional[Dict[str, str]]:
    """Call platform credential service to get user-specific credentials.

    Args:
        context_id: The A2A context ID (sessionId::conversationId).
        agent_name: The agent's registered name (must match agents table).

    Returns:
        Dict of credential key-value pairs, or None if no user config exists.
    """
    host_url = os.environ.get("A2A_HOST", "http://localhost:12000")
    # Normalize — A2A_HOST may be set to "FOUNDRY" or a URL
    if host_url == "FOUNDRY" or not host_url.startswith("http"):
        host_url = os.environ.get("BACKEND_SERVER_URL") or os.environ.get("BACKEND_URL", "http://localhost:12000")

    api_key = os.environ.get("CREDENTIAL_SERVICE_API_KEY", "dev-internal-key")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{host_url}/api/credentials/resolve",
                json={"context_id": context_id, "agent_name": agent_name},
                headers={"X-Internal-API-Key": api_key},
            )
            if resp.status_code == 200:
                data = resp.json()
                creds = data.get("credentials")
                if creds:
                    logger.info(f"Resolved user credentials for agent={agent_name} (keys: {list(creds.keys())})")
                return creds
            else:
                logger.warning(f"Credential resolve returned {resp.status_code}: {resp.text}")
                return None
    except Exception as e:
        logger.warning(f"Failed to resolve user credentials: {e}")
        return None
