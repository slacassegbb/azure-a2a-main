"""
Chat History Service - Persists conversations and messages to PostgreSQL.

Provides database persistence for chat history with in-memory caching.
Pattern: Memory is primary for reads, database is synced on writes.

This enables:
- Chat history sidebar to show previous conversations
- Messages to persist across backend restarts
- Full conversation replay with images, files, workflow steps
"""

import os
import json
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass, field

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL')
_db_conn = None
_use_database = False

# In-memory cache
_conversations_cache: Dict[str, Dict[str, Any]] = {}  # conversation_id -> conversation data
_messages_cache: Dict[str, List[Dict[str, Any]]] = {}  # conversation_id -> [messages]


def _get_connection():
    """Get or create database connection."""
    global _db_conn, _use_database
    
    if _db_conn is not None:
        try:
            # Test connection is still alive
            cur = _db_conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            return _db_conn
        except Exception as e:
            print(f"[ChatHistoryService] ⚠️ Connection test failed: {e}, reconnecting...")
            try:
                _db_conn.close()
            except:
                pass
            _db_conn = None
    
    if DATABASE_URL:
        try:
            import psycopg2
            _db_conn = psycopg2.connect(DATABASE_URL)
            _use_database = True
            print("[ChatHistoryService] ✅ Connected to PostgreSQL")
            return _db_conn
        except Exception as e:
            print(f"[ChatHistoryService] ❌ Failed to connect: {e}")
            _use_database = False
            return None
    else:
        print("[ChatHistoryService] ⚠️ DATABASE_URL not set, using in-memory only")
        return None


def _init_database():
    """Initialize database connection and load data."""
    conn = _get_connection()
    if conn:
        _load_conversations_from_database()


def _load_conversations_from_database(session_id: str = None):
    """Load conversations from database into memory cache."""
    global _conversations_cache, _messages_cache
    
    conn = _get_connection()
    if not conn:
        return
    
    try:
        cur = conn.cursor()
        
        if session_id:
            cur.execute("""
                SELECT conversation_id, session_id, name, is_active, created_at, updated_at
                FROM conversations WHERE session_id = %s ORDER BY updated_at DESC
            """, (session_id,))
        else:
            cur.execute("""
                SELECT conversation_id, session_id, name, is_active, created_at, updated_at
                FROM conversations ORDER BY updated_at DESC LIMIT 1000
            """)
        
        for row in cur.fetchall():
            conv_id = row[0]
            _conversations_cache[conv_id] = {
                "conversation_id": conv_id,
                "session_id": row[1],
                "name": row[2] or "",
                "is_active": row[3],
                "created_at": row[4].isoformat() if row[4] else None,
                "updated_at": row[5].isoformat() if row[5] else None,
                "task_ids": [],
                "messages": []
            }
        
        # Load task_ids for each conversation
        if _conversations_cache:
            conv_ids = list(_conversations_cache.keys())
            cur.execute("""
                SELECT conversation_id, task_id FROM conversation_tasks
                WHERE conversation_id = ANY(%s)
            """, (conv_ids,))
            for row in cur.fetchall():
                if row[0] in _conversations_cache:
                    _conversations_cache[row[0]]["task_ids"].append(row[1])
        
        cur.close()
        print(f"[ChatHistoryService] Loaded {len(_conversations_cache)} conversations from database")
        
    except Exception as e:
        print(f"[ChatHistoryService] Error loading conversations: {e}")


def _load_messages_for_conversation(conversation_id: str) -> List[Dict[str, Any]]:
    """Load messages for a specific conversation from database."""
    global _messages_cache
    
    # Check cache first
    if conversation_id in _messages_cache:
        return _messages_cache[conversation_id]
    
    conn = _get_connection()
    if not conn:
        return []
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT message_id, role, parts, context_id, task_id, metadata, created_at
            FROM messages WHERE conversation_id = %s ORDER BY created_at
        """, (conversation_id,))
        
        messages = []
        for row in cur.fetchall():
            msg = {
                "messageId": row[0],
                "role": row[1],
                "parts": row[2] if isinstance(row[2], list) else json.loads(row[2]) if row[2] else [],
                "contextId": row[3],
                "taskId": row[4],
                "metadata": row[5] if isinstance(row[5], dict) else json.loads(row[5]) if row[5] else {},
                "created_at": row[6].isoformat() if row[6] else None
            }
            messages.append(msg)
        
        cur.close()
        
        # Cache the messages
        _messages_cache[conversation_id] = messages
        print(f"[ChatHistoryService] Loaded {len(messages)} messages for conversation {conversation_id[:8]}...")
        
        return messages
        
    except Exception as e:
        print(f"[ChatHistoryService] Error loading messages: {e}")
        return []


# ==================== Conversation API ====================

def create_conversation(conversation_id: str, session_id: str, name: str = "") -> Dict[str, Any]:
    """Create a new conversation."""
    now = datetime.utcnow()
    
    conversation = {
        "conversation_id": conversation_id,
        "session_id": session_id,
        "name": name,
        "is_active": True,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "task_ids": [],
        "messages": []
    }
    
    # Update cache
    _conversations_cache[conversation_id] = conversation
    _messages_cache[conversation_id] = []
    
    # Persist to database
    conn = _get_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO conversations (conversation_id, session_id, name, is_active, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (conversation_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    is_active = EXCLUDED.is_active,
                    updated_at = EXCLUDED.updated_at
            """, (conversation_id, session_id, name, True, now, now))
            conn.commit()
            cur.close()
            print(f"[ChatHistoryService] Created conversation {conversation_id[:8]}...")
        except Exception as e:
            print(f"[ChatHistoryService] Error creating conversation: {e}")
            conn.rollback()
    
    return conversation


def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """Get a conversation by ID, with messages loaded."""
    # Check cache first
    if conversation_id in _conversations_cache:
        conv = _conversations_cache[conversation_id].copy()
        conv["messages"] = _load_messages_for_conversation(conversation_id)
        return conv
    
    # Try loading from database
    conn = _get_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT conversation_id, session_id, name, is_active, created_at, updated_at
                FROM conversations WHERE conversation_id = %s
            """, (conversation_id,))
            row = cur.fetchone()
            cur.close()
            
            if row:
                conv = {
                    "conversation_id": row[0],
                    "session_id": row[1],
                    "name": row[2] or "",
                    "is_active": row[3],
                    "created_at": row[4].isoformat() if row[4] else None,
                    "updated_at": row[5].isoformat() if row[5] else None,
                    "task_ids": [],
                    "messages": _load_messages_for_conversation(conversation_id)
                }
                _conversations_cache[conversation_id] = conv
                return conv
        except Exception as e:
            print(f"[ChatHistoryService] Error getting conversation: {e}")
    
    return None


def list_conversations(session_id: str) -> List[Dict[str, Any]]:
    """List all conversations for a session."""
    # Ensure we have data for this session
    _load_conversations_from_database(session_id)
    
    # Filter and return
    conversations = [
        conv for conv in _conversations_cache.values()
        if conv.get("session_id") == session_id
    ]
    
    # Sort by updated_at descending
    conversations.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
    
    return conversations


def delete_conversation(conversation_id: str) -> bool:
    """Delete a conversation and its messages."""
    # Remove from cache
    if conversation_id in _conversations_cache:
        del _conversations_cache[conversation_id]
    if conversation_id in _messages_cache:
        del _messages_cache[conversation_id]
    
    # Delete from database
    conn = _get_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM conversations WHERE conversation_id = %s", (conversation_id,))
            conn.commit()
            cur.close()
            print(f"[ChatHistoryService] Deleted conversation {conversation_id[:8]}...")
            return True
        except Exception as e:
            print(f"[ChatHistoryService] Error deleting conversation: {e}")
            conn.rollback()
    
    return True  # Return true even if only cache was cleared


def delete_all_conversations(session_id: str) -> bool:
    """Delete all conversations and messages for a session.
    
    Args:
        session_id: The session ID to delete all conversations for
        
    Returns:
        True if successful, False otherwise
    """
    global _conversations_cache, _messages_cache
    
    # Find and remove all conversations for this session from cache
    conv_ids_to_delete = [
        conv_id for conv_id, conv in _conversations_cache.items()
        if conv.get("session_id") == session_id or conv_id.startswith(f"{session_id}::")
    ]
    
    for conv_id in conv_ids_to_delete:
        if conv_id in _conversations_cache:
            del _conversations_cache[conv_id]
        if conv_id in _messages_cache:
            del _messages_cache[conv_id]
    
    print(f"[ChatHistoryService] Cleared {len(conv_ids_to_delete)} conversations from cache for session {session_id[:8]}...")
    
    # Delete from database
    conn = _get_connection()
    if conn:
        try:
            cur = conn.cursor()
            # Delete by session_id column OR by conversation_id prefix (for legacy format)
            cur.execute("""
                DELETE FROM conversations 
                WHERE session_id = %s OR conversation_id LIKE %s
            """, (session_id, f"{session_id}::%"))
            deleted_count = cur.rowcount
            conn.commit()
            cur.close()
            print(f"[ChatHistoryService] Deleted {deleted_count} conversations from database for session {session_id[:8]}...")
            return True
        except Exception as e:
            print(f"[ChatHistoryService] Error deleting all conversations: {e}")
            conn.rollback()
    
    return True  # Return true even if only cache was cleared


def update_conversation_name(conversation_id: str, name: str) -> bool:
    """Update conversation name.
    
    Handles both short IDs (abc123) and full IDs (session::abc123).
    Will try to match on either the exact ID or IDs ending with ::conversation_id.
    """
    # Update cache if present
    if conversation_id in _conversations_cache:
        _conversations_cache[conversation_id]["name"] = name
        _conversations_cache[conversation_id]["updated_at"] = datetime.utcnow().isoformat()
    
    # Also check for full ID format in cache
    for cached_id in list(_conversations_cache.keys()):
        if cached_id.endswith(f"::{conversation_id}"):
            _conversations_cache[cached_id]["name"] = name
            _conversations_cache[cached_id]["updated_at"] = datetime.utcnow().isoformat()
    
    conn = _get_connection()
    if conn:
        try:
            cur = conn.cursor()
            # Try updating by exact match OR by suffix match (for session::convId format)
            cur.execute("""
                UPDATE conversations SET name = %s, updated_at = %s 
                WHERE conversation_id = %s OR conversation_id LIKE %s
            """, (name, datetime.utcnow(), conversation_id, f"%::{conversation_id}"))
            rows_updated = cur.rowcount
            conn.commit()
            cur.close()
            print(f"[ChatHistoryService] Updated name for {rows_updated} conversation(s) matching {conversation_id}")
            return rows_updated > 0
        except Exception as e:
            print(f"[ChatHistoryService] Error updating conversation name: {e}")
            conn.rollback()
    
    return False


# ==================== Message API ====================

def add_message(conversation_id: str, message: Dict[str, Any]) -> bool:
    """Add a message to a conversation."""
    message_id = message.get("messageId") or message.get("message_id", "")
    role = message.get("role", "user")
    parts = message.get("parts", [])
    context_id = message.get("contextId") or message.get("context_id")
    task_id = message.get("taskId") or message.get("task_id")
    metadata = message.get("metadata", {})
    
    # Auto-create conversation if it doesn't exist
    if conversation_id not in _conversations_cache:
        # Extract session_id from context_id (format: "user_3::uuid")
        session_id = conversation_id.split("::")[0] if "::" in conversation_id else "default"
        # Get first message text for conversation name
        name = ""
        if parts and isinstance(parts, list) and len(parts) > 0:
            first_part = parts[0]
            if isinstance(first_part, dict):
                if 'root' in first_part and isinstance(first_part['root'], dict):
                    name = first_part['root'].get('text', '')[:50]
                elif 'text' in first_part:
                    name = first_part.get('text', '')[:50]
        create_conversation(conversation_id, session_id, name or f"Chat {conversation_id[-8:]}")
    
    # Serialize parts if needed
    if isinstance(parts, list):
        # Convert Pydantic models to dicts if needed
        serialized_parts = []
        for part in parts:
            if hasattr(part, 'model_dump'):
                serialized_parts.append(part.model_dump())
            elif hasattr(part, 'dict'):
                serialized_parts.append(part.dict())
            elif isinstance(part, dict):
                serialized_parts.append(part)
            else:
                serialized_parts.append(str(part))
        parts = serialized_parts
    
    msg_data = {
        "messageId": message_id,
        "role": role,
        "parts": parts,
        "contextId": context_id,
        "taskId": task_id,
        "metadata": metadata,
        "created_at": datetime.utcnow().isoformat()
    }
    
    # Update cache
    if conversation_id not in _messages_cache:
        _messages_cache[conversation_id] = []
    
    # Avoid duplicates
    existing_ids = {m.get("messageId") for m in _messages_cache[conversation_id]}
    if message_id not in existing_ids:
        _messages_cache[conversation_id].append(msg_data)
    
    # Update conversation timestamp
    if conversation_id in _conversations_cache:
        _conversations_cache[conversation_id]["updated_at"] = datetime.utcnow().isoformat()
    
    # Persist to database
    conn = _get_connection()
    if not conn:
        print(f"[ChatHistoryService] ❌ No database connection - message NOT persisted: {message_id[:16]}...")
        return False
    
    try:
        cur = conn.cursor()
        
        # Insert message
        cur.execute("""
            INSERT INTO messages (message_id, conversation_id, role, parts, context_id, task_id, metadata, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (conversation_id, message_id) DO UPDATE SET
                parts = EXCLUDED.parts,
                metadata = EXCLUDED.metadata
        """, (message_id, conversation_id, role, json.dumps(parts), context_id, task_id, 
              json.dumps(metadata) if metadata else None, datetime.utcnow()))
        
        # Update conversation timestamp
        cur.execute("""
            UPDATE conversations SET updated_at = %s WHERE conversation_id = %s
        """, (datetime.utcnow(), conversation_id))
        
        conn.commit()
        cur.close()
        return True
        
    except Exception as e:
        print(f"[ChatHistoryService] ❌ Error adding message: {e}")
        try:
            conn.rollback()
        except:
            pass
        return False


def get_messages(conversation_id: str) -> List[Dict[str, Any]]:
    """Get all messages for a conversation."""
    return _load_messages_for_conversation(conversation_id)


def add_task_to_conversation(conversation_id: str, task_id: str) -> bool:
    """Associate a task with a conversation."""
    # Update cache
    if conversation_id in _conversations_cache:
        if task_id not in _conversations_cache[conversation_id].get("task_ids", []):
            _conversations_cache[conversation_id].setdefault("task_ids", []).append(task_id)
    
    # Persist to database
    conn = _get_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO conversation_tasks (conversation_id, task_id) VALUES (%s, %s)
                ON CONFLICT DO NOTHING
            """, (conversation_id, task_id))
            conn.commit()
            cur.close()
            return True
        except Exception as e:
            print(f"[ChatHistoryService] Error adding task: {e}")
            conn.rollback()
    
    return False


# ==================== Sync Utilities ====================

def sync_conversation_from_memory(conversation_id: str, messages: List[Any], session_id: str = None) -> bool:
    """
    Sync an in-memory conversation to the database.
    Called when the manager creates/updates conversations.
    """
    if not conversation_id:
        return False
    
    # Ensure conversation exists
    if conversation_id not in _conversations_cache:
        create_conversation(conversation_id, session_id or "default", "")
    
    # Sync messages
    for msg in messages:
        msg_dict = msg if isinstance(msg, dict) else (msg.model_dump() if hasattr(msg, 'model_dump') else msg.dict() if hasattr(msg, 'dict') else {})
        if msg_dict:
            add_message(conversation_id, msg_dict)
    
    return True


def clear_cache():
    """Clear in-memory caches. Useful for testing or forced refresh."""
    global _conversations_cache, _messages_cache
    _conversations_cache = {}
    _messages_cache = {}


# Initialize on module load
_init_database()
