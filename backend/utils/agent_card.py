import requests

from a2a.types import AgentCard


def get_agent_card(remote_agent_address: str) -> AgentCard:
    """Get the agent card with a reasonable timeout."""
    if not remote_agent_address.startswith(('http://', 'https://')):
        remote_agent_address = 'http://' + remote_agent_address
    agent_card = requests.get(
        f'{remote_agent_address}/.well-known/agent.json',
        timeout=15.0  # 15 second timeout to prevent hanging
    )
    return AgentCard(**agent_card.json())
