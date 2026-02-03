-- Workflows Schema for PostgreSQL
-- Stores workflow configurations with steps and connections

CREATE TABLE IF NOT EXISTS workflows (
    id VARCHAR(100) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100),
    user_id VARCHAR(100) NOT NULL,
    steps JSONB DEFAULT '[]'::jsonb,
    connections JSONB DEFAULT '[]'::jsonb,
    goal TEXT,
    is_custom BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index on user_id for fast user workflow lookups
CREATE INDEX IF NOT EXISTS idx_workflows_user_id ON workflows(user_id);

-- Index on category for filtering
CREATE INDEX IF NOT EXISTS idx_workflows_category ON workflows(category);

-- Index on name for searching
CREATE INDEX IF NOT EXISTS idx_workflows_name ON workflows(name);

-- Trigger to automatically update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_workflows_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_workflows_timestamp ON workflows;
CREATE TRIGGER trigger_update_workflows_timestamp
    BEFORE UPDATE ON workflows
    FOR EACH ROW
    EXECUTE FUNCTION update_workflows_updated_at();

-- Comments for documentation
COMMENT ON TABLE workflows IS 'Workflow configurations with steps and connections';
COMMENT ON COLUMN workflows.user_id IS 'User who owns this workflow';
COMMENT ON COLUMN workflows.steps IS 'JSONB array of workflow steps with agent info';
COMMENT ON COLUMN workflows.connections IS 'JSONB array of connections between steps';
