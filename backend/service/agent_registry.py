"""Agent Registry Service

A database-backed registry for storing and retrieving agent configurations.
Provides CRUD operations for managing agent cards with a standardized structure.

Agents are persisted to PostgreSQL and survive backend restarts.
Falls back to JSON file storage if database is not available.
"""

import json
import os
from typing import List, Dict, Any, Optional
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
from service.agent_colors import assign_color_for_agent
from log_config import log_debug, log_info, log_warning, log_error


class AgentRegistry:
    """Database-backed registry for managing agent configurations."""
    
    def __init__(self, registry_file: str | Path | None = None):
        """Initialize the registry with PostgreSQL database.
        
        Args:
            registry_file: Deprecated - kept for backward compatibility, not used when database is available
        """
        # Check if we should use production URLs (for Azure deployment)
        self.use_prod = os.environ.get("USE_PROD_REGISTRY", "false").lower() == "true"
        
        # Try to connect to database
        self.database_url = os.environ.get('DATABASE_URL')
        self.use_database = False
        self.db_conn = None
        
        if self.database_url:
            try:
                self.db_conn = psycopg2.connect(self.database_url)
                self.db_conn.autocommit = True
                self.use_database = True
                env_type = "PRODUCTION" if self.use_prod else "LOCAL"
                log_info(f"[AgentRegistry] Using PostgreSQL database ({env_type} URLs)")
                self._run_migrations()
            except Exception as e:
                log_warning(f"[AgentRegistry] Database connection failed: {e}")
                log_warning("[AgentRegistry] Falling back to JSON file storage")
        
        # Fallback to JSON file if database not available
        if not self.use_database:
            if registry_file is None:
                registry_filename = "agent_registry_unified.json"
                self.registry_file = (
                    Path(__file__).resolve().parent.parent / "data" / registry_filename
                )
            else:
                self.registry_file = Path(registry_file)
            
            env_type = "PRODUCTION" if self.use_prod else "LOCAL"
            log_info(f"[AgentRegistry] Using JSON file storage ({env_type} URLs)")
            self.registry_file.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_registry_file()
    
    def _run_migrations(self):
        """Ensure database schema is up to date. Safe to run repeatedly (idempotent).

        Note: ALTER TABLE ADD COLUMN color was removed — the column already exists
        in production and the ALTER TABLE takes an ACCESS EXCLUSIVE lock that blocks
        when other container revisions hold open transactions.
        """
        # One-time migration: assign curated distinct colors to known agents.
        # Uses a flag row check so it only runs once.
        try:
            cur = self.db_conn.cursor()
            # Check if we already ran this migration (Email Agent should be blue, not emerald)
            cur.execute("SELECT color FROM agents WHERE name = 'Email Agent'")
            row = cur.fetchone()
            if row and row[0] == '#3b82f6':
                cur.close()
                return  # Already migrated

            curated_colors = {
                'Email Agent': '#3b82f6',
                'Teams Agent': '#f97316',
                'AI Foundry Stripe Agent': '#8b5cf6',
                'AI Foundry QuickBooks Agent': '#10b981',
                'AI Foundry Deep Search Knowledge Agent': '#06b6d4',
                'AI Foundry HubSpot Agent': '#f59e0b',
                'AI Foundry Image Generator Agent': '#ec4899',
                'AI Foundry Image Analysis Agent': '#a855f7',
                'Salesforce CRM Agent': '#ef4444',
                'AI Foundry Reporter Agent': '#14b8a6',
                'AI Foundry Branding & Content Agent': '#ec4899',
                'AI Foundry Claims Specialist Agent': '#06b6d4',
                'AI Foundry Classification Triage Agent': '#f59e0b',
                'AI Foundry Assessment & Estimation Agent': '#8b5cf6',
                'AI Foundry Fraud Intelligence Agent': '#ef4444',
                'Legal Compliance & Regulatory Agent': '#14b8a6',
                'Sentiment Analysis Agent': '#a855f7',
                'Twilio SMS Agent': '#3b82f6',
                'Sora 2 Video Generator': '#f97316',
                'SportsResultAgent': '#06b6d4',
                'Benjamin School AP-Calculus Study Buddy': '#ef4444',
                'Benjamin School AP Environmental Science Study Buddy': '#10b981',
                'Benjamin School Biology Teacher': '#14b8a6',
                'Benjamin School English Teacher': '#3b82f6',
            }
            for name, color in curated_colors.items():
                cur.execute("UPDATE agents SET color = %s WHERE name = %s", (color, name))
            self.db_conn.commit()
            cur.close()
            log_info(f"[AgentRegistry] Migrated {len(curated_colors)} agents to curated colors")
        except Exception as e:
            log_warning(f"[AgentRegistry] Color migration warning: {e}")
            self.db_conn.rollback()

    def _ensure_registry_file(self):
        """Ensure the registry file exists, create with empty list if not."""
        if not hasattr(self, 'registry_file'):
            return
        if not self.registry_file.exists():
            self._save_registry([])
    
    def _load_agents_from_database(self) -> List[Dict[str, Any]]:
        """Load agent data from PostgreSQL database.
        
        Returns:
            List of agent configuration dictionaries
        """
        try:
            cur = self.db_conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT
                    id, name, description, version,
                    local_url, production_url,
                    default_input_modes, default_output_modes,
                    capabilities, skills, color,
                    created_at, updated_at
                FROM agents
                ORDER BY name
            """)

            agents = []
            for row in cur.fetchall():
                agent = dict(row)
                # Normalize to match JSON format
                agent['defaultInputModes'] = agent.pop('default_input_modes', [])
                agent['defaultOutputModes'] = agent.pop('default_output_modes', [])
                # Auto-assign color if missing in DB
                if not agent.get('color'):
                    color = assign_color_for_agent(agent.get('name', ''))
                    try:
                        update_cur = self.db_conn.cursor()
                        update_cur.execute(
                            "UPDATE agents SET color = %s WHERE name = %s AND color IS NULL",
                            (color, agent['name'])
                        )
                        self.db_conn.commit()
                        update_cur.close()
                    except Exception:
                        pass
                    agent['color'] = color
                agents.append(agent)

            cur.close()
            
            # Normalize agents to have 'url' field based on environment
            return [self._normalize_agent_url(agent) for agent in agents]
        except Exception as e:
            log_error(f"[AgentRegistry] Error loading from database: {e}")
            return []
    
    def _load_registry(self) -> List[Dict[str, Any]]:
        """Load agent data from database or fallback to file.
        
        Returns:
            List of agent configuration dictionaries
        """
        # Use database if available
        if self.use_database:
            return self._load_agents_from_database()
        
        # Fallback to JSON file
        try:
            with open(self.registry_file, 'r', encoding='utf-8') as f:
                agents = json.load(f)
                # Normalize agents to have 'url' field based on environment
                return [self._normalize_agent_url(agent) for agent in agents]
        except (FileNotFoundError, json.JSONDecodeError):
            return []
    
    def _normalize_agent_url(self, agent: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize agent to have 'url' field based on environment.
        
        Sets 'url' to production_url or local_url based on USE_PROD_REGISTRY.
        Maintains backward compatibility with old format.
        
        Args:
            agent: Agent configuration dictionary
            
        Returns:
            Agent with normalized 'url' field
        """
        agent_copy = agent.copy()
        
        # If agent has both local_url and production_url, set url based on environment
        if 'local_url' in agent_copy and 'production_url' in agent_copy:
            agent_copy['url'] = agent_copy['production_url'] if self.use_prod else agent_copy['local_url']
        # Backward compatibility: if only 'url' exists, keep it as is
        elif 'url' not in agent_copy:
            # Fallback if neither format exists
            agent_copy['url'] = None
            
        return agent_copy
    
    def _save_registry(self, agents: List[Dict[str, Any]]):
        """Save agent data to the registry file (JSON fallback only).
        
        Args:
            agents: List of agent configuration dictionaries
        """
        if not hasattr(self, 'registry_file'):
            return
        with open(self.registry_file, 'w', encoding='utf-8') as f:
            json.dump(agents, f, indent=2, ensure_ascii=False)
    
    def _save_agent_to_database(self, agent: Dict[str, Any]) -> bool:
        """Save a single agent to PostgreSQL database using UPSERT.
        
        Args:
            agent: Agent configuration dictionary
            
        Returns:
            True if saved successfully, False otherwise
        """
        try:
            # Handle both old format (url) and new format (local_url/production_url)
            # If agent has 'url' but not 'local_url', use 'url' as local_url
            local_url = agent.get('local_url') or agent.get('url')
            production_url = agent.get('production_url') or agent.get('url')
            
            # Both must be non-null for database constraint
            if not local_url:
                local_url = production_url
            if not production_url:
                production_url = local_url
            
            # Auto-assign color if not provided
            color = agent.get('color')
            if not color:
                color = assign_color_for_agent(agent.get('name', ''))

            log_debug(f"[AgentRegistry] _save_agent_to_database: {agent.get('name')}")
            log_debug(f"[AgentRegistry]   local_url: {local_url}")
            log_debug(f"[AgentRegistry]   production_url: {production_url}")
            log_debug(f"[AgentRegistry]   color: {color}")
            log_debug(f"[AgentRegistry]   skills: {[s.get('id') for s in agent.get('skills', [])]}")

            cur = self.db_conn.cursor()
            cur.execute("""
                INSERT INTO agents (
                    name, description, version,
                    local_url, production_url,
                    default_input_modes, default_output_modes,
                    capabilities, skills, color
                ) VALUES (
                    %s, %s, %s,
                    %s, %s,
                    %s::jsonb, %s::jsonb,
                    %s::jsonb, %s::jsonb, %s
                )
                ON CONFLICT (name) DO UPDATE SET
                    description = EXCLUDED.description,
                    version = EXCLUDED.version,
                    local_url = COALESCE(EXCLUDED.local_url, agents.local_url),
                    production_url = COALESCE(EXCLUDED.production_url, agents.production_url),
                    default_input_modes = EXCLUDED.default_input_modes,
                    default_output_modes = EXCLUDED.default_output_modes,
                    capabilities = EXCLUDED.capabilities,
                    skills = EXCLUDED.skills,
                    color = COALESCE(EXCLUDED.color, agents.color),
                    updated_at = CURRENT_TIMESTAMP
            """, (
                agent.get('name'),
                agent.get('description'),
                agent.get('version'),
                local_url,
                production_url,
                json.dumps(agent.get('defaultInputModes', [])),
                json.dumps(agent.get('defaultOutputModes', [])),
                json.dumps(agent.get('capabilities', {})),
                json.dumps(agent.get('skills', [])),
                color
            ))
            self.db_conn.commit()
            cur.close()
            return True
        except Exception as e:
            log_error(f"[AgentRegistry] Error saving agent to database: {e}")
            self.db_conn.rollback()
            return False
    
    def add_agent(self, agent: Dict[str, Any]) -> bool:
        """Add a new agent to the registry.
        
        Args:
            agent: Agent configuration dictionary
            
        Returns:
            True if agent was added, False if agent with same name or URL already exists
        """
        # Validate required fields
        if not self._validate_agent(agent):
            raise ValueError("Invalid agent configuration")
        
        if self.use_database:
            # Check if agent with same name already exists in database
            existing = self.get_agent(agent.get('name'))
            if existing:
                return False
            
            # Save to database
            return self._save_agent_to_database(agent)
        else:
            # Fallback to JSON
            agents = self._load_registry()
            
            # Check if agent with same name already exists
            if any(a.get('name') == agent.get('name') for a in agents):
                return False
            
            # Check if agent with same URL already exists
            if any(a.get('url') == agent.get('url') for a in agents):
                return False
            
            if 'color' not in agent:
                agent['color'] = assign_color_for_agent(agent.get('name', ''))
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
        log_debug(f"[AgentRegistry] update_agent called for: {name}")
        log_debug(f"[AgentRegistry] Agent data keys: {list(agent.keys())}")
        log_debug(f"[AgentRegistry] Skills count: {len(agent.get('skills', []))}")

        # Validate required fields
        if not self._validate_agent(agent):
            log_debug(f"[AgentRegistry] Validation FAILED for {name}")
            raise ValueError("Invalid agent configuration")

        log_debug(f"[AgentRegistry] Validation passed for {name}")
        
        if self.use_database:
            # Check if agent exists
            existing = self.get_agent(name)
            if not existing:
                log_debug(f"[AgentRegistry] Agent {name} not found in database")
                return False

            log_debug(f"[AgentRegistry] Updating {name} in database...")
            # Update in database
            return self._save_agent_to_database(agent)
        else:
            # Fallback to JSON
            agents = self._load_registry()
            
            for i, a in enumerate(agents):
                if a.get('name') == name:
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
        # Validate required fields
        if not self._validate_agent(agent):
            raise ValueError("Invalid agent configuration")
        
        if self.use_database:
            # Database UPSERT handles this automatically
            return self._save_agent_to_database(agent)
        else:
            # Fallback to JSON
            agents = self._load_registry()
            
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
            
            if 'color' not in agent:
                agent['color'] = assign_color_for_agent(agent.get('name', ''))

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
        if self.use_database:
            try:
                cur = self.db_conn.cursor()
                cur.execute("DELETE FROM agents WHERE name = %s", (name,))
                rows_deleted = cur.rowcount
                self.db_conn.commit()
                cur.close()
                return rows_deleted > 0
            except Exception as e:
                log_error(f"[AgentRegistry] Error removing agent from database: {e}")
                self.db_conn.rollback()
                return False
        else:
            # Fallback to JSON
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
        # Required fields - support both unified format (local_url + production_url) and old format (url)
        basic_required = ['name', 'description', 'version']
        
        # Check basic required fields
        for field in basic_required:
            if field not in agent:
                return False
        
        # Check URL fields - must have either 'url' OR both 'local_url' and 'production_url'
        has_url = 'url' in agent
        has_unified_urls = 'local_url' in agent and 'production_url' in agent
        
        if not (has_url or has_unified_urls):
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


# Global registry instance
_registry = None

def get_registry() -> AgentRegistry:
    """Get the global agent registry instance.
    
    Returns:
        AgentRegistry instance
    """
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry


class SessionAgentRegistry:
    """In-memory registry for session-enabled agents.
    
    This registry is intentionally NOT persisted - session agents are cleared
    on backend restart. Users must re-enable agents from the catalog each session.
    """
    
    def __init__(self):
        self._sessions: Dict[str, List[Dict[str, Any]]] = {}
        log_debug("[SessionAgentRegistry] Initialized with empty session agents (cleared on restart)")
    
    def enable_agent(self, session_id: str, agent: Dict[str, Any]) -> bool:
        """Enable an agent for a session."""
        log_debug(f"[SessionRegistry.enable_agent] session_id='{session_id}', agent={agent.get('name')}")
        if session_id not in self._sessions:
            self._sessions[session_id] = []

        # Check if already enabled (by URL)
        if any(a.get('url') == agent.get('url') for a in self._sessions[session_id]):
            log_debug("[SessionRegistry.enable_agent] Agent already enabled, skipping")
            return False

        self._sessions[session_id].append(agent)
        log_debug(f"[SessionRegistry.enable_agent] Now {len(self._sessions[session_id])} agents in session")
        log_debug(f"[SessionRegistry.enable_agent] All sessions: {list(self._sessions.keys())}")
        return True
    
    def disable_agent(self, session_id: str, agent_url: str) -> bool:
        """Disable an agent for a session."""
        if session_id not in self._sessions:
            return False
        
        original_len = len(self._sessions[session_id])
        self._sessions[session_id] = [
            a for a in self._sessions[session_id] if a.get('url') != agent_url
        ]
        return len(self._sessions[session_id]) < original_len
    
    def get_session_agents(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all enabled agents for a session."""
        agents = self._sessions.get(session_id, [])
        log_debug(f"[SessionRegistry.get_session_agents] session_id='{session_id}' -> {len(agents)} agents")
        log_debug(f"[SessionRegistry.get_session_agents] All sessions: {list(self._sessions.keys())}")
        return agents
    
    def is_enabled(self, session_id: str, agent_url: str) -> bool:
        """Check if an agent is enabled for a session."""
        return any(
            a.get('url') == agent_url 
            for a in self._sessions.get(session_id, [])
        )
    
    def clear_all(self):
        """Clear all session agents. Called on server restart."""
        count = sum(len(agents) for agents in self._sessions.values())
        session_count = len(self._sessions)
        self._sessions = {}
        log_info(f"[SessionAgentRegistry] Cleared {count} agents from {session_count} sessions")


_session_registry = None

def get_session_registry() -> SessionAgentRegistry:
    """Get the global session agent registry instance."""
    global _session_registry
    if _session_registry is None:
        _session_registry = SessionAgentRegistry()
    return _session_registry
