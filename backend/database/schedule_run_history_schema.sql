-- Schedule Run History Table
-- Stores execution audit logs for scheduled workflow runs

CREATE TABLE IF NOT EXISTS schedule_run_history (
    -- Primary key
    run_id UUID PRIMARY KEY,
    
    -- Schedule reference
    schedule_id UUID NOT NULL,
    workflow_id VARCHAR(255) NOT NULL,
    workflow_name VARCHAR(500) NOT NULL,
    session_id VARCHAR(255) NOT NULL,
    
    -- Timing information
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP NOT NULL,
    duration_seconds FLOAT NOT NULL DEFAULT 0,
    
    -- Execution status
    status VARCHAR(50) NOT NULL, -- 'success' or 'failed'
    result TEXT, -- Workflow output (truncated to 5000 chars)
    error TEXT, -- Error message if failed
    
    -- Indexes for common queries
    CONSTRAINT schedule_run_history_status_check CHECK (status IN ('success', 'failed'))
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_schedule_run_history_schedule_id ON schedule_run_history(schedule_id);
CREATE INDEX IF NOT EXISTS idx_schedule_run_history_session_id ON schedule_run_history(session_id);
CREATE INDEX IF NOT EXISTS idx_schedule_run_history_timestamp ON schedule_run_history(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_schedule_run_history_status ON schedule_run_history(status);
CREATE INDEX IF NOT EXISTS idx_schedule_run_history_workflow_id ON schedule_run_history(workflow_id);

-- Composite index for filtering by schedule and time
CREATE INDEX IF NOT EXISTS idx_schedule_run_history_schedule_time ON schedule_run_history(schedule_id, timestamp DESC);

-- Composite index for filtering by session and time
CREATE INDEX IF NOT EXISTS idx_schedule_run_history_session_time ON schedule_run_history(session_id, timestamp DESC);

COMMENT ON TABLE schedule_run_history IS 'Audit log of scheduled workflow executions';
COMMENT ON COLUMN schedule_run_history.run_id IS 'Unique identifier for this execution';
COMMENT ON COLUMN schedule_run_history.schedule_id IS 'ID of the schedule that triggered this run';
COMMENT ON COLUMN schedule_run_history.workflow_id IS 'ID of the workflow that was executed';
COMMENT ON COLUMN schedule_run_history.session_id IS 'Session ID of the schedule owner';
COMMENT ON COLUMN schedule_run_history.timestamp IS 'When the run history entry was created';
COMMENT ON COLUMN schedule_run_history.started_at IS 'When the workflow execution started';
COMMENT ON COLUMN schedule_run_history.completed_at IS 'When the workflow execution completed';
COMMENT ON COLUMN schedule_run_history.duration_seconds IS 'Total execution time in seconds';
COMMENT ON COLUMN schedule_run_history.status IS 'Execution status: success or failed';
COMMENT ON COLUMN schedule_run_history.result IS 'Workflow output text (truncated to 5000 chars)';
COMMENT ON COLUMN schedule_run_history.error IS 'Error message if execution failed';
