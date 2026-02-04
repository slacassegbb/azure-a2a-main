-- Active Workflows Schema
-- Stores active workflow context per session (persists across backend restarts)

-- Single active workflow per session (legacy format)
CREATE TABLE IF NOT EXISTS active_workflow_sessions (
    session_id VARCHAR(255) PRIMARY KEY,
    workflow TEXT DEFAULT '',
    name VARCHAR(500) DEFAULT '',
    goal TEXT DEFAULT '',
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Multiple active workflows per session (new format)
CREATE TABLE IF NOT EXISTS active_workflows_multi (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    workflow_id VARCHAR(255) NOT NULL,
    workflow_data JSONB NOT NULL,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, workflow_id)
);

-- Index for fast session lookups
CREATE INDEX IF NOT EXISTS idx_active_workflows_multi_session 
ON active_workflows_multi(session_id);

-- Index for cleanup of old sessions (optional)
CREATE INDEX IF NOT EXISTS idx_active_workflow_sessions_updated 
ON active_workflow_sessions(updated_at);
