"""User Agent Configuration Service

Per-user agent credential storage with pgcrypto encryption at rest.
Agents declare what config they need via config_schema on the agents table.
Users provide their credentials via the frontend, stored encrypted here.
At request time, agents call /api/credentials/resolve to get user-specific creds.
"""

import os
import json
from typing import Dict, Any, Optional, List

import psycopg2
from psycopg2.extras import RealDictCursor

from log_config import log_debug, log_info, log_warning, log_error

# Encryption key for pgcrypto — set in Azure Key Vault / env var
CREDENTIAL_ENCRYPTION_KEY = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "dev-only-change-me")

# Context ID separator (same as foundry_host_manager.py)
TENANT_SEPARATOR = "::"


class UserAgentConfigService:
    """Manages per-user agent configurations with encrypted storage."""

    def __init__(self):
        self.database_url = os.environ.get("DATABASE_URL")
        self.db_conn = None

        if self.database_url:
            try:
                self.db_conn = psycopg2.connect(self.database_url)
                self.db_conn.autocommit = True
                self._ensure_table()
                log_info("[UserAgentConfigService] Initialized with PostgreSQL")
            except Exception as e:
                log_error(f"[UserAgentConfigService] Database connection failed: {e}")
                self.db_conn = None
        else:
            log_warning("[UserAgentConfigService] No DATABASE_URL — service unavailable")

    def _ensure_table(self):
        """Verify the user_agent_configs table exists."""
        try:
            cur = self.db_conn.cursor()
            cur.execute("""
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'user_agent_configs'
            """)
            if cur.fetchone():
                log_info("[UserAgentConfigService] Table user_agent_configs ready")
            else:
                log_warning("[UserAgentConfigService] Table user_agent_configs not found — run the migration SQL")
            cur.close()
        except Exception as e:
            log_warning(f"[UserAgentConfigService] Table check warning: {e}")

    def _get_agent_config_schema(self, agent_name: str) -> Optional[List[Dict]]:
        """Get the config_schema for an agent from the agents table."""
        try:
            cur = self.db_conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT config_schema FROM agents WHERE name = %s", (agent_name,))
            row = cur.fetchone()
            cur.close()
            if row and row.get("config_schema"):
                return row["config_schema"]
            return None
        except Exception as e:
            log_error(f"[UserAgentConfigService] Error getting config_schema for {agent_name}: {e}")
            return None

    def _compute_is_configured(self, config_data: Dict, config_schema: Optional[List[Dict]]) -> bool:
        """Check if all required fields in the schema are present and non-empty."""
        if not config_schema:
            return True  # No schema means no config needed
        for field in config_schema:
            if field.get("required", False):
                value = config_data.get(field["key"], "")
                if not value or not str(value).strip():
                    return False
        return True

    def save_config(self, user_id: str, agent_name: str, config_data: Dict[str, str]) -> bool:
        """Save or update user config for an agent (encrypted)."""
        if not self.db_conn:
            log_error("[UserAgentConfigService] No database connection")
            return False

        try:
            config_schema = self._get_agent_config_schema(agent_name)
            is_configured = self._compute_is_configured(config_data, config_schema)
            config_json = json.dumps(config_data)

            cur = self.db_conn.cursor()
            cur.execute("""
                INSERT INTO user_agent_configs (user_id, agent_name, config_data, is_configured)
                VALUES (%s, %s, pgp_sym_encrypt(%s, %s), %s)
                ON CONFLICT (user_id, agent_name) DO UPDATE SET
                    config_data = pgp_sym_encrypt(%s, %s),
                    is_configured = %s,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                user_id, agent_name, config_json, CREDENTIAL_ENCRYPTION_KEY, is_configured,
                config_json, CREDENTIAL_ENCRYPTION_KEY, is_configured
            ))
            self.db_conn.commit()
            cur.close()
            log_info(f"[UserAgentConfigService] Saved config for user={user_id}, agent={agent_name}, configured={is_configured}")
            return True
        except Exception as e:
            log_error(f"[UserAgentConfigService] Error saving config: {e}")
            self.db_conn.rollback()
            return False

    def get_config(self, user_id: str, agent_name: str) -> Optional[Dict[str, str]]:
        """Get decrypted config for a specific agent (for form pre-fill)."""
        if not self.db_conn:
            return None

        try:
            cur = self.db_conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT pgp_sym_decrypt(config_data, %s) as config_json, is_configured
                FROM user_agent_configs
                WHERE user_id = %s AND agent_name = %s
            """, (CREDENTIAL_ENCRYPTION_KEY, user_id, agent_name))
            row = cur.fetchone()
            cur.close()

            if row:
                return {
                    "config_data": json.loads(row["config_json"]),
                    "is_configured": row["is_configured"]
                }
            return None
        except Exception as e:
            log_error(f"[UserAgentConfigService] Error getting config: {e}")
            return None

    def get_all_configs(self, user_id: str) -> List[Dict[str, Any]]:
        """Get config status for all agents for a user (no secrets returned)."""
        if not self.db_conn:
            return []

        try:
            cur = self.db_conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT agent_name, is_configured, created_at, updated_at
                FROM user_agent_configs
                WHERE user_id = %s
                ORDER BY agent_name
            """, (user_id,))
            rows = cur.fetchall()
            cur.close()
            return [dict(row) for row in rows]
        except Exception as e:
            log_error(f"[UserAgentConfigService] Error getting all configs: {e}")
            return []

    def delete_config(self, user_id: str, agent_name: str) -> bool:
        """Delete user config for an agent."""
        if not self.db_conn:
            return False

        try:
            cur = self.db_conn.cursor()
            cur.execute(
                "DELETE FROM user_agent_configs WHERE user_id = %s AND agent_name = %s",
                (user_id, agent_name)
            )
            deleted = cur.rowcount > 0
            self.db_conn.commit()
            cur.close()
            if deleted:
                log_info(f"[UserAgentConfigService] Deleted config for user={user_id}, agent={agent_name}")
            return deleted
        except Exception as e:
            log_error(f"[UserAgentConfigService] Error deleting config: {e}")
            self.db_conn.rollback()
            return False

    def resolve_credentials(self, context_id: str, agent_name: str) -> Optional[Dict[str, str]]:
        """Resolve user credentials from a context_id.

        context_id format: sessionId::conversationId
        For logged-in users, sessionId IS user_id (e.g., "user_abc123").
        """
        if not self.db_conn:
            return None

        # Extract session_id (which is user_id for logged-in users)
        session_id = context_id.split(TENANT_SEPARATOR, 1)[0] if TENANT_SEPARATOR in context_id else context_id
        user_id = session_id  # For logged-in users, session_id == user_id

        log_debug(f"[UserAgentConfigService] Resolving credentials: context_id={context_id}, user_id={user_id}, agent={agent_name}")

        result = self.get_config(user_id, agent_name)
        if result and result.get("is_configured"):
            return result["config_data"]
        return None

    def check_agents_configured(self, user_id: str, agent_names: List[str]) -> Dict[str, Dict[str, bool]]:
        """Bulk check which agents need config and whether user has provided it.

        Returns: {agent_name: {"needs_config": bool, "is_configured": bool}}
        """
        if not self.db_conn:
            # No DB = no config required (graceful fallback)
            return {name: {"needs_config": False, "is_configured": True} for name in agent_names}

        result = {}
        try:
            cur = self.db_conn.cursor(cursor_factory=RealDictCursor)

            for agent_name in agent_names:
                # Check if agent has a config_schema
                config_schema = self._get_agent_config_schema(agent_name)
                needs_config = config_schema is not None and len(config_schema) > 0

                if not needs_config:
                    result[agent_name] = {"needs_config": False, "is_configured": True}
                    continue

                # Check if user has configured this agent
                cur.execute("""
                    SELECT is_configured FROM user_agent_configs
                    WHERE user_id = %s AND agent_name = %s
                """, (user_id, agent_name))
                row = cur.fetchone()
                is_configured = row["is_configured"] if row else False

                result[agent_name] = {"needs_config": True, "is_configured": is_configured}

            cur.close()
        except Exception as e:
            log_error(f"[UserAgentConfigService] Error checking configs: {e}")
            # On error, don't block — assume configured
            for name in agent_names:
                if name not in result:
                    result[name] = {"needs_config": False, "is_configured": True}

        return result


# Singleton instance
_config_service = None


def get_user_agent_config_service() -> UserAgentConfigService:
    """Get the global UserAgentConfigService instance."""
    global _config_service
    if _config_service is None:
        _config_service = UserAgentConfigService()
    return _config_service
