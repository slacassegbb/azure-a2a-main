-- Chat History Schema for PostgreSQL
-- Stores conversations and messages with full fidelity for replay

-- Conversations table (chat sessions in the sidebar)
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,  -- user/session who owns this conversation
    name TEXT DEFAULT '',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast lookup by session
CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC);

-- Messages table (individual messages in a conversation)
-- Stores the full message structure as JSONB for flexibility
CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    message_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    role TEXT NOT NULL,  -- 'user', 'agent', 'system'
    parts JSONB NOT NULL,  -- Array of TextPart, FilePart, DataPart objects
    context_id TEXT,
    task_id TEXT,
    metadata JSONB,  -- Additional metadata (agent name, workflow info, etc.)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(conversation_id, message_id)
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_messages_task ON messages(task_id) WHERE task_id IS NOT NULL;

-- Task IDs associated with conversations (for tracking workflow executions)
CREATE TABLE IF NOT EXISTS conversation_tasks (
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (conversation_id, task_id)
);

CREATE INDEX IF NOT EXISTS idx_conversation_tasks_task ON conversation_tasks(task_id);
