-- Agent Registry Schema for PostgreSQL
-- Stores agent configurations with local and production URLs

CREATE TABLE IF NOT EXISTS agents (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    version VARCHAR(50),
    local_url VARCHAR(500) NOT NULL,
    production_url VARCHAR(500) NOT NULL,
    default_input_modes JSONB DEFAULT '[]'::jsonb,
    default_output_modes JSONB DEFAULT '[]'::jsonb,
    capabilities JSONB DEFAULT '{}'::jsonb,
    skills JSONB DEFAULT '[]'::jsonb,
    color VARCHAR(7),
    config_schema JSONB DEFAULT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index on name for fast lookups
CREATE INDEX IF NOT EXISTS idx_agents_name ON agents(name);

-- Index on local_url for duplicate checking
CREATE INDEX IF NOT EXISTS idx_agents_local_url ON agents(local_url);

-- Index on production_url for duplicate checking
CREATE INDEX IF NOT EXISTS idx_agents_production_url ON agents(production_url);

-- Trigger to automatically update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_agents_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_agents_timestamp ON agents;
CREATE TRIGGER trigger_update_agents_timestamp
    BEFORE UPDATE ON agents
    FOR EACH ROW
    EXECUTE FUNCTION update_agents_updated_at();

-- Comments for documentation
COMMENT ON TABLE agents IS 'Agent registry storing agent configurations with local and production URLs';
COMMENT ON COLUMN agents.name IS 'Unique agent name identifier';
COMMENT ON COLUMN agents.local_url IS 'URL for local development (localhost)';
COMMENT ON COLUMN agents.production_url IS 'URL for production deployment (Azure)';
COMMENT ON COLUMN agents.skills IS 'JSONB array of agent skills and capabilities';
COMMENT ON COLUMN agents.capabilities IS 'JSONB object of agent capabilities (e.g., streaming)';
COMMENT ON COLUMN agents.color IS 'Hex color code for agent display (e.g., #ec4899). Auto-assigned if not provided.';
COMMENT ON COLUMN agents.config_schema IS 'JSONB array of user-configurable fields. NULL means no user config needed.';
