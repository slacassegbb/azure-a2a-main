"""
Active Workflow Service - Manages active workflow state per session.

Provides database persistence with in-memory caching for performance.
Pattern: Memory is primary for reads, database is synced on writes.
"""

import os
import json
import sys
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path

# Add backend directory to path for log_config import
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from log_config import log_debug, log_info, log_error, log_warning

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL')
_db_conn = None
_use_database = False

# In-memory stores (primary for reads)
_single_workflows: Dict[str, Dict[str, str]] = {}  # session_id -> {workflow, name, goal}
_multi_workflows: Dict[str, List[Dict[str, Any]]] = {}  # session_id -> [workflow_data, ...]


def _init_database():
    """Initialize database connection and load existing data."""
    global _db_conn, _use_database
    
    if DATABASE_URL:
        try:
            import psycopg2
            _db_conn = psycopg2.connect(DATABASE_URL)
            _use_database = True
            log_info("[ActiveWorkflowService] Using PostgreSQL database")
            _load_from_database()
        except Exception as e:
            log_error(f"[ActiveWorkflowService] Failed to connect to database: {e}")
            _use_database = False
    else:
        log_warning("[ActiveWorkflowService] DATABASE_URL not set, using in-memory only")


def _load_from_database():
    """Load existing active workflows from database into memory."""
    global _single_workflows, _multi_workflows
    
    if not _db_conn:
        return
    
    try:
        cur = _db_conn.cursor()
        
        # Load single workflows
        cur.execute("SELECT session_id, workflow, name, goal FROM active_workflow_sessions")
        for row in cur.fetchall():
            _single_workflows[row[0]] = {
                "workflow": row[1] or "",
                "name": row[2] or "",
                "goal": row[3] or ""
            }
        
        # Load multi workflows
        cur.execute("SELECT session_id, workflow_id, workflow_data FROM active_workflows_multi ORDER BY added_at")
        for row in cur.fetchall():
            session_id = row[0]
            workflow_data = row[2] if isinstance(row[2], dict) else json.loads(row[2])
            
            if session_id not in _multi_workflows:
                _multi_workflows[session_id] = []
            _multi_workflows[session_id].append(workflow_data)
        
        cur.close()
        log_debug(f"[ActiveWorkflowService] Loaded {len(_single_workflows)} single workflows, {len(_multi_workflows)} multi-workflow sessions")
        
    except Exception as e:
        log_error(f"[ActiveWorkflowService] Error loading from database: {e}")


# ==================== Single Workflow API ====================

def get_active_workflow(session_id: str) -> Dict[str, str]:
    """Get the active workflow for a session."""
    if session_id in _single_workflows:
        return _single_workflows[session_id]
    return {"workflow": "", "name": "", "goal": ""}


def set_active_workflow(session_id: str, workflow: str, name: str, goal: str) -> bool:
    """Set the active workflow for a session."""
    # Update memory
    _single_workflows[session_id] = {
        "workflow": workflow,
        "name": name,
        "goal": goal
    }
    
    # Persist to database
    if _use_database and _db_conn:
        try:
            cur = _db_conn.cursor()
            cur.execute("""
                INSERT INTO active_workflow_sessions (session_id, workflow, name, goal, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (session_id) DO UPDATE SET
                    workflow = EXCLUDED.workflow,
                    name = EXCLUDED.name,
                    goal = EXCLUDED.goal,
                    updated_at = EXCLUDED.updated_at
            """, (session_id, workflow, name, goal, datetime.utcnow()))
            _db_conn.commit()
            cur.close()
        except Exception as e:
            log_error(f"[ActiveWorkflowService] Error saving to database: {e}")
            _db_conn.rollback()
            return False
    
    return True


def clear_active_workflow(session_id: str) -> bool:
    """Clear the active workflow for a session."""
    # Update memory
    if session_id in _single_workflows:
        del _single_workflows[session_id]
    
    # Delete from database
    if _use_database and _db_conn:
        try:
            cur = _db_conn.cursor()
            cur.execute("DELETE FROM active_workflow_sessions WHERE session_id = %s", (session_id,))
            _db_conn.commit()
            cur.close()
        except Exception as e:
            log_error(f"[ActiveWorkflowService] Error deleting from database: {e}")
            _db_conn.rollback()
            return False
    
    return True


# ==================== Multi-Workflow API ====================

def get_active_workflows(session_id: str) -> List[Dict[str, Any]]:
    """Get all active workflows for a session."""
    return _multi_workflows.get(session_id, [])


def set_active_workflows(session_id: str, workflows: List[Dict[str, Any]]) -> bool:
    """Set all active workflows for a session (replaces existing)."""
    # Update memory
    _multi_workflows[session_id] = workflows
    
    # Persist to database
    if _use_database and _db_conn:
        try:
            cur = _db_conn.cursor()
            
            # Clear existing workflows for this session
            cur.execute("DELETE FROM active_workflows_multi WHERE session_id = %s", (session_id,))
            
            # Insert new workflows
            for workflow in workflows:
                workflow_id = workflow.get("id", "")
                cur.execute("""
                    INSERT INTO active_workflows_multi (session_id, workflow_id, workflow_data, added_at)
                    VALUES (%s, %s, %s, %s)
                """, (session_id, workflow_id, json.dumps(workflow), datetime.utcnow()))
            
            _db_conn.commit()
            cur.close()
        except Exception as e:
            log_error(f"[ActiveWorkflowService] Error saving multi-workflows to database: {e}")
            _db_conn.rollback()
            return False
    
    return True


def add_active_workflow(session_id: str, workflow: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Add a single workflow to the active workflows list."""
    if session_id not in _multi_workflows:
        _multi_workflows[session_id] = []
    
    # Avoid duplicates by ID
    existing_ids = {w.get("id") for w in _multi_workflows[session_id]}
    workflow_id = workflow.get("id", "")
    
    if workflow_id not in existing_ids:
        _multi_workflows[session_id].append(workflow)
        
        # Persist to database
        if _use_database and _db_conn:
            try:
                cur = _db_conn.cursor()
                cur.execute("""
                    INSERT INTO active_workflows_multi (session_id, workflow_id, workflow_data, added_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (session_id, workflow_id) DO UPDATE SET
                        workflow_data = EXCLUDED.workflow_data,
                        added_at = EXCLUDED.added_at
                """, (session_id, workflow_id, json.dumps(workflow), datetime.utcnow()))
                _db_conn.commit()
                cur.close()
            except Exception as e:
                log_error(f"[ActiveWorkflowService] Error adding workflow to database: {e}")
                _db_conn.rollback()
    
    return _multi_workflows[session_id]


def remove_active_workflow(session_id: str, workflow_id: str) -> List[Dict[str, Any]]:
    """Remove a specific workflow from the active workflows list."""
    if session_id in _multi_workflows:
        _multi_workflows[session_id] = [
            w for w in _multi_workflows[session_id] 
            if w.get("id") != workflow_id
        ]
    
    # Delete from database
    if _use_database and _db_conn:
        try:
            cur = _db_conn.cursor()
            cur.execute("""
                DELETE FROM active_workflows_multi 
                WHERE session_id = %s AND workflow_id = %s
            """, (session_id, workflow_id))
            _db_conn.commit()
            cur.close()
        except Exception as e:
            log_error(f"[ActiveWorkflowService] Error removing workflow from database: {e}")
            _db_conn.rollback()
    
    return _multi_workflows.get(session_id, [])


def clear_active_workflows(session_id: str) -> bool:
    """Clear all active workflows for a session."""
    if session_id in _multi_workflows:
        del _multi_workflows[session_id]
    
    # Delete from database
    if _use_database and _db_conn:
        try:
            cur = _db_conn.cursor()
            cur.execute("DELETE FROM active_workflows_multi WHERE session_id = %s", (session_id,))
            _db_conn.commit()
            cur.close()
        except Exception as e:
            log_error(f"[ActiveWorkflowService] Error clearing workflows from database: {e}")
            _db_conn.rollback()
            return False
    
    return True


# Initialize on module import
_init_database()
