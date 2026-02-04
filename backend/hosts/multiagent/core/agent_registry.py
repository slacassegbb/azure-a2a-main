"""
Agent Registry - Agent registration and management methods for FoundryHostAgent2.

This module contains methods related to:
- Remote agent registration and discovery
- Agent card management (load, save, convert)
- Session agent management
- Agent listing and lookup

These are extracted from foundry_agent_a2a.py to improve code organization.
The class is designed to be used as a mixin with FoundryHostAgent2.
"""

import asyncio
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from a2a.client import A2ACardResolver
from a2a.types import AgentCard

# Import logging utilities
import sys
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from log_config import log_debug, log_info, log_error

from ..remote_agent_connection import RemoteAgentConnections


class AgentRegistry:
    """
    Mixin class providing agent registration and management methods.
    
    This class is designed to be inherited by FoundryHostAgent2 along with
    other mixin classes. All methods use 'self' and expect the main class
    to have the required attributes (cards, remote_agent_connections, etc).
    """

    async def set_session_agents(self, session_agents: List[Dict[str, Any]]):
        """Set the available agents for this session/request.
        
        This clears existing agents and sets only the provided session agents.
        Called before processing each request to ensure session isolation.
        
        OPTIMIZATION: We now construct AgentCard objects directly from the session
        data (which came from the catalog) instead of making HTTP calls to fetch
        agent cards on every request. This eliminates N HTTP calls per message.
        
        Args:
            session_agents: List of agent dicts with url, name, description, skills, etc.
        """
        import asyncio
        from a2a.types import AgentCard, AgentSkill, AgentCapabilities, AgentProvider
        
        # Clear existing agents
        self.cards.clear()
        self.remote_agent_connections.clear()
        self.agents = ''
        
        print(f"🔷 [SET_SESSION_AGENTS] Received {len(session_agents)} agents to register")
        
        # Track successful and failed registrations
        successful_agents = []
        failed_agents = []
        
        # Register each session agent
        for agent_data in session_agents:
            agent_url = agent_data.get('url')
            agent_name = agent_data.get('name', 'Unknown')
            print(f"🔷 [SET_SESSION_AGENTS]   - Registering: {agent_name} @ {agent_url}")
            
            if not agent_url:
                failed_agents.append(f"{agent_name} (no URL)")
                continue
                
            try:
                # OPTIMIZATION: Try to construct AgentCard directly from session data
                # This avoids HTTP calls on every request
                if self._can_construct_card_from_data(agent_data):
                    card = self._construct_agent_card(agent_data)
                    self.register_agent_card(card)
                    successful_agents.append(agent_name)
                    log_debug(f"Session agent registered (from cache): {agent_name}")
                else:
                    # Fallback: Fetch card via HTTP (only if data is incomplete)
                    print(f"🔷 [SET_SESSION_AGENTS]   ⚠️ Incomplete data for {agent_name}, fetching via HTTP...")
                    await asyncio.wait_for(self.retrieve_card(agent_url), timeout=15.0)
                    successful_agents.append(agent_name)
                    log_debug(f"Session agent registered (via HTTP): {agent_name}")
                    
            except asyncio.TimeoutError:
                failed_agents.append(f"{agent_name} (TIMEOUT)")
                log_error(f"⚠️ TIMEOUT registering agent {agent_name} @ {agent_url}")
                print(f"⚠️ [SET_SESSION_AGENTS] TIMEOUT: {agent_name} @ {agent_url}")
            except Exception as e:
                failed_agents.append(f"{agent_name} ({type(e).__name__})")
                log_error(f"⚠️ Failed to register session agent {agent_url}: {e}")
                print(f"⚠️ [SET_SESSION_AGENTS] FAILED: {agent_name} - {e}")
        
        # Log summary
        print(f"🔷 [SET_SESSION_AGENTS] Final self.cards has {len(self.cards)} agents: {list(self.cards.keys())}")
        if failed_agents:
            print(f"⚠️ [SET_SESSION_AGENTS] WARNING: {len(failed_agents)} agents failed to register: {failed_agents}")
        print(f"🔷 [SET_SESSION_AGENTS] self.agents string length: {len(self.agents)} chars")
        log_debug(f"Session has {len(self.cards)} agents: {list(self.cards.keys())}")
        
        # Return summary for debugging
        return {
            "registered": len(successful_agents),
            "failed": len(failed_agents),
            "successful_agents": successful_agents,
            "failed_agents": failed_agents
        }
    
    def _can_construct_card_from_data(self, agent_data: Dict[str, Any]) -> bool:
        """Check if we have enough data to construct an AgentCard without HTTP fetch."""
        # Minimum required: name, url, description
        return bool(
            agent_data.get('name') and 
            agent_data.get('url') and 
            agent_data.get('description')
        )
    
    def _construct_agent_card(self, agent_data: Dict[str, Any]) -> 'AgentCard':
        """Construct an AgentCard object from session data dict.
        
        This avoids HTTP calls by using cached data from the catalog.
        """
        from a2a.types import AgentCard, AgentSkill, AgentCapabilities, AgentProvider
        
        # Build skills list
        skills = []
        if agent_data.get('skills'):
            for skill in agent_data['skills']:
                if isinstance(skill, dict):
                    skills.append(AgentSkill(
                        id=skill.get('id', skill.get('name', '')),
                        name=skill.get('name', ''),
                        description=skill.get('description', ''),
                        tags=skill.get('tags', [])  # Required field, default to empty list
                    ))
        
        # Build capabilities
        caps_data = agent_data.get('capabilities', {})
        if isinstance(caps_data, dict):
            capabilities = AgentCapabilities(
                streaming=caps_data.get('streaming', False),
                pushNotifications=caps_data.get('pushNotifications', False)
            )
        else:
            capabilities = AgentCapabilities(streaming=False, pushNotifications=False)
        
        # Build provider (optional)
        provider = None
        if agent_data.get('provider'):
            prov_data = agent_data['provider']
            if isinstance(prov_data, dict):
                provider = AgentProvider(organization=prov_data.get('organization', ''))
        
        # Get input/output modes with defaults
        default_input_modes = agent_data.get('defaultInputModes', ['text'])
        default_output_modes = agent_data.get('defaultOutputModes', ['text'])
        
        # Construct the card
        card = AgentCard(
            name=agent_data['name'],
            url=agent_data['url'],
            description=agent_data.get('description', ''),
            version=agent_data.get('version', '1.0.0'),
            skills=skills if skills else None,
            capabilities=capabilities,
            provider=provider,
            defaultInputModes=default_input_modes,
            defaultOutputModes=default_output_modes
        )
        
        return card

    def _find_agent_registry_path(self) -> Path:
        """Resolve the agent registry path within the backend/data directory."""
        backend_root = Path(__file__).resolve().parents[2]
        registry_path = backend_root / "data" / "agent_registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        if registry_path.exists():
            log_debug(f"📋 Found agent registry at: {registry_path}")
        else:
            log_debug(f"📋 Agent registry will be created at: {registry_path}")
        return registry_path

    def _load_agent_registry(self) -> List[Dict[str, Any]]:
        """Load agent registry from JSON file."""
        try:
            if self._agent_registry_path.exists():
                with open(self._agent_registry_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                log_debug(f"📋 Agent registry file not found at {self._agent_registry_path}, returning empty list")
                return []
        except Exception as e:
            log_error(f"Error loading agent registry: {e}")
            return []

    def _save_agent_registry(self, agents: List[Dict[str, Any]]):
        """Save agent registry to JSON file."""
        try:
            # Ensure directory exists
            self._agent_registry_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self._agent_registry_path, 'w', encoding='utf-8') as f:
                json.dump(agents, f, indent=2, ensure_ascii=False)
            log_debug(f"📋 Saved agent registry with {len(agents)} agents to {self._agent_registry_path}")
        except Exception as e:
            log_error(f"Error saving agent registry: {e}")

    def _agent_card_to_dict(self, card: AgentCard) -> Dict[str, Any]:
        """Convert AgentCard object to dictionary for JSON serialization in the agent registry."""
        try:
            card_dict = {
                "name": card.name,
                "description": card.description,
                "version": getattr(card, 'version', '1.0.0'),
                "url": card.url,
                "defaultInputModes": getattr(card, 'defaultInputModes', ["text"]),
                "defaultOutputModes": getattr(card, 'defaultOutputModes', ["text"]),
            }
            
            if hasattr(card, 'capabilities') and card.capabilities:
                capabilities_dict = {}
                if hasattr(card.capabilities, 'streaming'):
                    capabilities_dict["streaming"] = card.capabilities.streaming
                card_dict["capabilities"] = capabilities_dict
            
            if hasattr(card, 'skills') and card.skills:
                skills_list = []
                for skill in card.skills:
                    skill_dict = {
                        "id": getattr(skill, 'id', ''),
                        "name": getattr(skill, 'name', ''),
                        "description": getattr(skill, 'description', ''),
                        "examples": getattr(skill, 'examples', []),
                        "tags": getattr(skill, 'tags', [])
                    }
                    skills_list.append(skill_dict)
                card_dict["skills"] = skills_list
            
            return card_dict
        except Exception as e:
            log_error(f"Error converting agent card to dict: {e}")
            return {
                "name": getattr(card, 'name', 'Unknown'),
                "description": getattr(card, 'description', ''),
                "version": "1.0.0",
                "url": getattr(card, 'url', ''),
                "defaultInputModes": ["text"],
                "defaultOutputModes": ["text"]
            }

    def _update_agent_registry(self, card: AgentCard):
        """Persist agent card to registry file, updating existing entries or adding new ones."""
        try:
            registry = self._load_agent_registry()
            card_dict = self._agent_card_to_dict(card)
            
            existing_index = None
            # First, check by name (primary identifier)
            for i, existing_agent in enumerate(registry):
                if existing_agent.get("name") == card.name:
                    existing_index = i
                    break
            
            # If not found by name, check by URL (for backward compatibility)
            if existing_index is None:
                for i, existing_agent in enumerate(registry):
                    if existing_agent.get("url") == card.url:
                        existing_index = i
                        break
            
            if existing_index is not None:
                registry[existing_index] = card_dict
                log_debug(f"📋 Updated existing agent in registry: {card.name} at {card.url}")
            else:
                registry.append(card_dict)
                log_debug(f"📋 Added new agent to registry: {card.name} at {card.url}")
            
            self._save_agent_registry(registry)
            
        except Exception as e:
            log_error(f"Error updating agent registry: {e}")

    async def init_remote_agent_addresses(self, remote_agent_addresses: List[str]):
        """Initialize remote agent connections from a list of addresses."""
        async with asyncio.TaskGroup() as task_group:
            for address in remote_agent_addresses:
                task_group.create_task(self.retrieve_card(address))

    async def retrieve_card(self, address: str):
        """Retrieve and register an agent card from the given address."""
        card_resolver = A2ACardResolver(self.httpx_client, address, '/.well-known/agent.json')
        card = await card_resolver.get_agent_card()
        self.register_agent_card(card)

    def register_agent_card(self, card: AgentCard):
        """
        Register a remote agent by its card, establishing connection and updating UI state.
        Handles both new registrations and updates to existing agents.
        """
        if hasattr(card, 'capabilities') and card.capabilities:
            streaming_flag = getattr(card.capabilities, 'streaming', None)
            if streaming_flag is True:
                log_debug(f"🔄 [STREAMING] {card.name} supports streaming; enabling granular UI visibility")
            elif streaming_flag is False:
                log_debug(f"ℹ️ [STREAMING] {card.name} does not support streaming; using non-streaming mode")
            else:
                log_debug(f"ℹ️ [STREAMING] {card.name} did not specify streaming capability; defaulting to non-streaming mode")
                try:
                    card.capabilities.streaming = False
                except Exception:
                    pass
        
        self._update_agent_registry(card)
        
        log_debug(f"🔗 [CALLBACK] Registering {card.name} with callback: {self.task_callback.__name__ if hasattr(self.task_callback, '__name__') else type(self.task_callback)}")
        remote_connection = RemoteAgentConnections(self.httpx_client, card, self.task_callback)
        self.remote_agent_connections[card.name] = remote_connection
        self.cards[card.name] = card
        
        agent_info = []
        for ra in self.list_remote_agents():
            agent_info.append(json.dumps(ra))
        self.agents = '\n'.join(agent_info)
        
        if hasattr(self, '_host_manager') and self._host_manager:
            existing_index = next((i for i, a in enumerate(self._host_manager._agents) if a.name == card.name), None)
            
            if existing_index is not None:
                self._host_manager._agents[existing_index] = card
                log_debug(f"🔄 Updated {card.name} in host manager agent list")
            else:
                self._host_manager._agents.append(card)
                log_debug(f"✅ Added {card.name} to host manager agent list")
        
        # Emit registration event (inherited from EventEmitters mixin)
        self._emit_agent_registration_event(card)
        
        if self.agent:
            asyncio.create_task(self._update_agent_instructions())

    def list_remote_agents(self) -> List[Dict[str, Any]]:
        """
        List available remote agents for the current session.
        Note: self.cards is already session-specific, set via set_session_agents() before each request.
        """
        agents = []
        for card in self.cards.values():
            agent_info = {
                'name': card.name,
                'description': card.description
            }
            
            # Add skills if present
            if hasattr(card, 'skills') and card.skills:
                skills_list = []
                for skill in card.skills:
                    skill_dict = {
                        "id": getattr(skill, 'id', ''),
                        "name": getattr(skill, 'name', ''),
                        "description": getattr(skill, 'description', ''),
                    }
                    skills_list.append(skill_dict)
                agent_info['skills'] = skills_list
            
            agents.append(agent_info)
        
        # Log what agents are being returned (helps debug delegation issues)
        if agents:
            print(f"🔶 [LIST_REMOTE_AGENTS] Returning {len(agents)} agents: {[a['name'] for a in agents]}")
        else:
            print(f"🔶 [LIST_REMOTE_AGENTS] Returning EMPTY list - no agents available for this session!")
        
        return agents

    def list_remote_agents_sync(self) -> List[Dict[str, Any]]:
        """
        Synchronous wrapper for list_remote_agents - for use with AsyncFunctionTool.
        
        The underlying list_remote_agents() method is synchronous, so this wrapper
        can also be synchronous. AsyncFunctionTool will handle it appropriately.
        """
        log_debug("🔧 [TOOL] list_remote_agents_sync called by SDK!")
        result = self.list_remote_agents()
        
        # If no agents are registered, return a helpful message instead of empty list
        # This prevents Azure AI Agents API from choking on empty responses
        if not result or len(result) == 0:
            log_debug("🔧 [TOOL] list_remote_agents_sync returning: [] (no agents registered)")
            return [{
                "name": "No Agents Available",
                "description": "No specialized remote agents are currently registered. The host agent can still respond to general queries.",
                "status": "info"
            }]
        
        log_debug(f"🔧 [TOOL] list_remote_agents_sync returning: {result}")
        return result
