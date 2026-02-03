-- Scheduled Workflows Schema for PostgreSQL
-- Stores scheduled workflow job configurations

CREATE TABLE IF NOT EXISTS scheduled_workflows (
    id VARCHAR(100) PRIMARY KEY,
    workflow_id VARCHAR(100) NOT NULL,
    workflow_name VARCHAR(255) NOT NULL,
    session_id VARCHAR(100) NOT NULL,
    schedule_type VARCHAR(50) NOT NULL,
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_run TIMESTAMP WITH TIME ZONE,
    next_run TIMESTAMP WITH TIME ZONE,
    run_count INTEGER DEFAULT 0,
    
    -- Execution status tracking
    last_status VARCHAR(50),
    last_error TEXT,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    
    -- Schedule parameters
    run_at TIMESTAMP WITH TIME ZONE,
    interval_minutes INTEGER,
    time_of_day VARCHAR(10),
    days_of_week JSONB,
    day_of_month INTEGER,
    cron_expression VARCHAR(255),
    timezone VARCHAR(50) DEFAULT 'UTC',
    
    -- Execution settings
    timeout INTEGER DEFAULT 300,
    retry_on_failure BOOLEAN DEFAULT false,
    max_retries INTEGER DEFAULT 3,
    max_runs INTEGER,
    
    -- Metadata
    description TEXT,
    tags JSONB DEFAULT '[]'::jsonb,
    workflow_goal TEXT
);

-- Index on workflow_id for fast workflow schedule lookups
CREATE INDEX IF NOT EXISTS idx_scheduled_workflows_workflow_id ON scheduled_workflows(workflow_id);

-- Index on session_id
CREATE INDEX IF NOT EXISTS idx_scheduled_workflows_session_id ON scheduled_workflows(session_id);

-- Index on enabled for fast active schedule queries
CREATE INDEX IF NOT EXISTS idx_scheduled_workflows_enabled ON scheduled_workflows(enabled);

-- Index on next_run for scheduler queries
CREATE INDEX IF NOT EXISTS idx_scheduled_workflows_next_run ON scheduled_workflows(next_run) WHERE enabled = true;

-- Trigger to automatically update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_scheduled_workflows_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_scheduled_workflows_timestamp ON scheduled_workflows;
CREATE TRIGGER trigger_update_scheduled_workflows_timestamp
    BEFORE UPDATE ON scheduled_workflows
    FOR EACH ROW
    EXECUTE FUNCTION update_scheduled_workflows_updated_at();

-- Comments for documentation
COMMENT ON TABLE scheduled_workflows IS 'Scheduled workflow job configurations';
COMMENT ON COLUMN scheduled_workflows.workflow_id IS 'Reference to the workflow to execute';
COMMENT ON COLUMN scheduled_workflows.schedule_type IS 'Type of schedule: once, interval, daily, weekly, monthly, cron';
COMMENT ON COLUMN scheduled_workflows.enabled IS 'Whether the schedule is active';
