-- PostgreSQL Database Schema for A2A System
-- This schema replaces JSON file storage with proper database tables

-- Users Table
-- Replaces: backend/data/users.json
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(50) PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(64) NOT NULL,
    name VARCHAR(100) NOT NULL,
    role VARCHAR(100),
    description TEXT,
    skills JSONB DEFAULT '[]'::jsonb,
    color VARCHAR(7) DEFAULT '#3B82F6',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create index on email for fast lookups
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- Create index on created_at for sorting
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at);

-- Function to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger to call update_updated_at_column on user updates
DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Comments for documentation
COMMENT ON TABLE users IS 'Stores user accounts and authentication data';
COMMENT ON COLUMN users.user_id IS 'Unique user identifier (e.g., user_1, user_abc123def)';
COMMENT ON COLUMN users.email IS 'User email address - unique across system';
COMMENT ON COLUMN users.password_hash IS 'SHA256 hash of user password';
COMMENT ON COLUMN users.skills IS 'JSONB array of user skills/expertise';
COMMENT ON COLUMN users.color IS 'Hex color code for user avatar/UI';
