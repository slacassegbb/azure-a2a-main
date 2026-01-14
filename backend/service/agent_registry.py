"""Agent Registry Service

A local registry for storing and retrieving agent configurations.
Provides CRUD operations for managing agent cards with a standardized structure.
"""

import json
from typing import List, Dict, Any, Optional
from pathlib import Path


class AgentRegistry:
    """Local registry for managing agent configurations."""
    
    def __init__(self, registry_file: str | Path | None = None):
        """Initialize the registry with a JSON file for persistence.
        
        Args:
            registry_file: Path to the JSON file for storing agent data
        """
        if registry_file is None:
            self.registry_file = (
                Path(__file__).resolve().parent.parent / "data" / "agent_registry.json"
            )
        else:
            self.registry_file = Path(registry_file)
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_registry_file()
    
    def _ensure_registry_file(self):
        """Ensure the registry file exists, create with empty list if not."""
        if not self.registry_file.exists():
            self._save_registry([])
    
    def _load_registry(self) -> List[Dict[str, Any]]:
        """Load agent data from the registry file.
        
        Returns:
            List of agent configuration dictionaries
        """
        try:
            with open(self.registry_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []
    
    def _save_registry(self, agents: List[Dict[str, Any]]):
        """Save agent data to the registry file.
        
        Args:
            agents: List of agent configuration dictionaries
        """
        with open(self.registry_file, 'w', encoding='utf-8') as f:
            json.dump(agents, f, indent=2, ensure_ascii=False)
    
    def add_agent(self, agent: Dict[str, Any]) -> bool:
        """Add a new agent to the registry.
        
        Args:
            agent: Agent configuration dictionary
            
        Returns:
            True if agent was added, False if agent with same name or URL already exists
        """
        agents = self._load_registry()
        
        # Check if agent with same name already exists
        if any(a.get('name') == agent.get('name') for a in agents):
            return False
        
        # Check if agent with same URL already exists
        if any(a.get('url') == agent.get('url') for a in agents):
            return False
        
        # Validate required fields
        if not self._validate_agent(agent):
            raise ValueError("Invalid agent configuration")
        
        agents.append(agent)
        self._save_registry(agents)
        return True
    
    def get_agent(self, name: str) -> Optional[Dict[str, Any]]:
        """Get an agent by name.
        
        Args:
            name: Agent name
            
        Returns:
            Agent configuration or None if not found
        """
        agents = self._load_registry()
        return next((a for a in agents if a.get('name') == name), None)
    
    def get_all_agents(self) -> List[Dict[str, Any]]:
        """Get all agents from the registry.
        
        Returns:
            List of all agent configurations
        """
        return self._load_registry()
    
    def update_agent(self, name: str, agent: Dict[str, Any]) -> bool:
        """Update an existing agent in the registry.
        
        Args:
            name: Current agent name
            agent: Updated agent configuration
            
        Returns:
            True if agent was updated, False if not found
        """
        agents = self._load_registry()
        
        for i, a in enumerate(agents):
            if a.get('name') == name:
                if not self._validate_agent(agent):
                    raise ValueError("Invalid agent configuration")
                agents[i] = agent
                self._save_registry(agents)
                return True
        
        return False
    
    def update_or_add_agent(self, agent: Dict[str, Any]) -> bool:
        """Update an existing agent or add as new if it doesn't exist.
        
        Checks by name first, then by URL to find existing agent.
        
        Args:
            agent: Agent configuration dictionary
            
        Returns:
            True if operation succeeded, False otherwise
        """
        agents = self._load_registry()
        
        # Validate required fields
        if not self._validate_agent(agent):
            raise ValueError("Invalid agent configuration")
        
        existing_index = None
        agent_name = agent.get('name')
        agent_url = agent.get('url')
        
        # First, check by name (primary identifier)
        for i, a in enumerate(agents):
            if a.get('name') == agent_name:
                existing_index = i
                break
        
        # If not found by name, check by URL
        if existing_index is None:
            for i, a in enumerate(agents):
                if a.get('url') == agent_url:
                    existing_index = i
                    break
        
        if existing_index is not None:
            # Update existing agent
            agents[existing_index] = agent
        else:
            # Add new agent
            agents.append(agent)
        
        self._save_registry(agents)
        return True
    
    def remove_agent(self, name: str) -> bool:
        """Remove an agent from the registry.
        
        Args:
            name: Agent name to remove
            
        Returns:
            True if agent was removed, False if not found
        """
        agents = self._load_registry()
        original_length = len(agents)
        agents = [a for a in agents if a.get('name') != name]
        
        if len(agents) < original_length:
            self._save_registry(agents)
            return True
        
        return False
    
    def _validate_agent(self, agent: Dict[str, Any]) -> bool:
        """Validate agent configuration structure.
        
        Args:
            agent: Agent configuration to validate
            
        Returns:
            True if valid, False otherwise
        """
        required_fields = ['name', 'description', 'version', 'url']
        
        # Check required fields
        for field in required_fields:
            if field not in agent:
                return False
        
        # Validate skills structure if present
        if 'skills' in agent:
            if not isinstance(agent['skills'], list):
                return False
            
            for skill in agent['skills']:
                if not isinstance(skill, dict):
                    return False
                
                skill_required = ['id', 'name', 'description']
                for field in skill_required:
                    if field not in skill:
                        return False
        
        # Validate capabilities structure if present
        if 'capabilities' in agent:
            if not isinstance(agent['capabilities'], dict):
                return False
        
        # Validate input/output modes if present
        for mode_field in ['defaultInputModes', 'defaultOutputModes']:
            if mode_field in agent:
                if not isinstance(agent[mode_field], list):
                    return False
        
        return True
    
    def search_agents(self, query: str = None, tags: List[str] = None) -> List[Dict[str, Any]]:
        """Search agents by query or tags.
        
        Args:
            query: Text to search in name, description, or skills
            tags: List of tags to match in skills
            
        Returns:
            List of matching agent configurations
        """
        agents = self._load_registry()
        
        if not query and not tags:
            return agents
        
        filtered_agents = []
        
        for agent in agents:
            match = True
            
            # Text search
            if query:
                query_lower = query.lower()
                text_match = False
                
                # Search in name and description
                if (query_lower in agent.get('name', '').lower() or
                    query_lower in agent.get('description', '').lower()):
                    text_match = True
                
                # Search in skills
                for skill in agent.get('skills', []):
                    if (query_lower in skill.get('name', '').lower() or
                        query_lower in skill.get('description', '').lower()):
                        text_match = True
                        break
                
                if not text_match:
                    match = False
            
            # Tag search
            if tags and match:
                tag_match = False
                for skill in agent.get('skills', []):
                    skill_tags = skill.get('tags', [])
                    if any(tag in skill_tags for tag in tags):
                        tag_match = True
                        break
                
                if not tag_match:
                    match = False
            
            if match:
                filtered_agents.append(agent)
        
        return filtered_agents


class SessionAgentRegistry:
    """Per-session registry for tracking which agents a user has enabled.
    
    This is separate from the global AgentRegistry (catalog) which stores
    all discovered agents. Each session/tenant can enable a subset of
    agents from the catalog.
    """
    
    def __init__(self, base_dir: str | Path | None = None):
        """Initialize session registry storage.
        
        Args:
            base_dir: Base directory for storing session registrations
        """
        if base_dir is None:
            self.base_dir = (
                Path(__file__).resolve().parent.parent / "data" / "session_agents"
            )
        else:
            self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_session_file(self, session_id: str) -> Path:
        """Get the file path for a session's agent registrations."""
        # Sanitize session_id to prevent path traversal
        safe_id = "".join(c for c in session_id if c.isalnum() or c in '-_')
        return self.base_dir / f"{safe_id}.json"
    
    def _load_session(self, session_id: str) -> List[str]:
        """Load registered agent URLs for a session.
        
        Returns:
            List of registered agent URLs
        """
        session_file = self._get_session_file(session_id)
        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []
    
    def _save_session(self, session_id: str, agent_urls: List[str]):
        """Save registered agent URLs for a session."""
        session_file = self._get_session_file(session_id)
        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(agent_urls, f, indent=2)
    
    def register_agent(self, session_id: str, agent_url: str) -> bool:
        """Register an agent for a session.
        
        Args:
            session_id: The session/tenant ID
            agent_url: URL of the agent to register
            
        Returns:
            True if registered, False if already registered
        """
        agent_urls = self._load_session(session_id)
        
        # Normalize URL
        agent_url = agent_url.rstrip('/')
        
        if agent_url in agent_urls:
            return False
        
        agent_urls.append(agent_url)
        self._save_session(session_id, agent_urls)
        return True
    
    def unregister_agent(self, session_id: str, agent_url: str) -> bool:
        """Unregister an agent from a session.
        
        Args:
            session_id: The session/tenant ID
            agent_url: URL of the agent to unregister
            
        Returns:
            True if unregistered, False if not found
        """
        agent_urls = self._load_session(session_id)
        
        # Normalize URL
        agent_url = agent_url.rstrip('/')
        
        if agent_url not in agent_urls:
            return False
        
        agent_urls.remove(agent_url)
        self._save_session(session_id, agent_urls)
        return True
    
    def get_registered_urls(self, session_id: str) -> List[str]:
        """Get all registered agent URLs for a session.
        
        Args:
            session_id: The session/tenant ID
            
        Returns:
            List of registered agent URLs
        """
        return self._load_session(session_id)
    
    def is_registered(self, session_id: str, agent_url: str) -> bool:
        """Check if an agent is registered for a session.
        
        Args:
            session_id: The session/tenant ID
            agent_url: URL of the agent to check
            
        Returns:
            True if registered, False otherwise
        """
        agent_urls = self._load_session(session_id)
        return agent_url.rstrip('/') in agent_urls
    
    def get_registered_agents(self, session_id: str, catalog: 'AgentRegistry') -> List[Dict[str, Any]]:
        """Get full agent details for all registered agents in a session.
        
        Args:
            session_id: The session/tenant ID
            catalog: The global agent catalog to look up agent details
            
        Returns:
            List of agent configuration dictionaries
        """
        registered_urls = self._load_session(session_id)
        all_agents = catalog.get_all_agents()
        
        # Match by URL
        registered_agents = []
        for agent in all_agents:
            agent_url = agent.get('url', '').rstrip('/')
            if agent_url in registered_urls:
                registered_agents.append(agent)
        
        return registered_agents
    
    def clear_session(self, session_id: str):
        """Clear all registrations for a session.
        
        Args:
            session_id: The session/tenant ID
        """
        session_file = self._get_session_file(session_id)
        if session_file.exists():
            session_file.unlink()


# Global registry instances
_registry = None
_session_registry = None

def get_registry() -> AgentRegistry:
    """Get the global agent catalog instance.
    
    Returns:
        AgentRegistry instance (global catalog)
    """
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry


def get_session_registry() -> SessionAgentRegistry:
    """Get the session agent registry instance.
    
    Returns:
        SessionAgentRegistry instance (per-session registrations)
    """
    global _session_registry
    if _session_registry is None:
        _session_registry = SessionAgentRegistry()
    return _session_registry
