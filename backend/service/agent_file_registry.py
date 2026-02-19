"""
Agent File Registry - Minimal file deletion support.

Files are stored in unified blob storage at uploads/{session_id}/{file_id}/{filename}.
The /api/files endpoint queries blob storage directly. This module only provides
the delete_agent_file() function used by the DELETE /api/files/{file_id} endpoint.
"""

import os
import threading
import psycopg2

# Thread lock for safe concurrent access
_lock = threading.Lock()

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL')
_db_conn = None
_use_database = False


def _get_db_connection():
    """Get a working database connection, reconnecting if needed."""
    global _db_conn, _use_database

    if not DATABASE_URL:
        return None

    try:
        if _db_conn:
            try:
                _db_conn.cursor().execute("SELECT 1")
            except:
                try:
                    _db_conn.close()
                except:
                    pass
                _db_conn = None

        if not _db_conn:
            _db_conn = psycopg2.connect(DATABASE_URL)
            _db_conn.autocommit = False
            _use_database = True

        return _db_conn
    except Exception as e:
        print(f"[AgentFileRegistry] Database connection failed: {e}")
        _use_database = False
        return None


def delete_agent_file(session_id: str, file_id: str) -> bool:
    """
    Delete a specific file from the agent_files table.

    Args:
        session_id: The user's session ID
        file_id: The ID of the file to delete

    Returns:
        True if file was deleted, False otherwise
    """
    with _lock:
        db_conn = _get_db_connection()
        if _use_database and db_conn:
            try:
                cur = db_conn.cursor()
                cur.execute("DELETE FROM agent_files WHERE session_id = %s AND id = %s", (session_id, file_id))
                deleted = cur.rowcount > 0
                db_conn.commit()
                cur.close()
                if deleted:
                    print(f"[AgentFileRegistry] Deleted file {file_id} from database")
                return deleted
            except Exception as e:
                print(f"[AgentFileRegistry] Error deleting file from database: {e}")
                db_conn.rollback()
                return False
        return False
