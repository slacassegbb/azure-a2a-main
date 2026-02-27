-- User Agent Configuration Schema for PostgreSQL
-- Stores per-user agent credentials/settings with encryption at rest

-- Enable pgcrypto for symmetric encryption
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS user_agent_configs (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    agent_name VARCHAR(255) NOT NULL REFERENCES agents(name) ON DELETE CASCADE,
    config_data BYTEA NOT NULL,  -- pgp_sym_encrypt(json_text, key)
    is_configured BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, agent_name)
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_user_agent_configs_user_id ON user_agent_configs(user_id);
CREATE INDEX IF NOT EXISTS idx_user_agent_configs_agent_name ON user_agent_configs(agent_name);

-- Trigger to automatically update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_user_agent_configs_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_user_agent_configs_timestamp ON user_agent_configs;
CREATE TRIGGER trigger_update_user_agent_configs_timestamp
    BEFORE UPDATE ON user_agent_configs
    FOR EACH ROW
    EXECUTE FUNCTION update_user_agent_configs_updated_at();

-- Comments for documentation
COMMENT ON TABLE user_agent_configs IS 'Per-user agent configuration storing encrypted credentials';
COMMENT ON COLUMN user_agent_configs.config_data IS 'PGP-encrypted JSONB containing user-specific agent credentials';
COMMENT ON COLUMN user_agent_configs.is_configured IS 'True when all required fields per agent config_schema are present';
