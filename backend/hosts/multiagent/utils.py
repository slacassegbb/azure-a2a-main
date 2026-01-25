"""
Utility functions for the multiagent host.

Contains common helper functions used across the multiagent module.
"""

import uuid
from typing import Any


def get_context_id(obj: Any, default: str = None) -> str:
    """
    Extract contextId from an object with fallback support for both camelCase and snake_case naming conventions.
    Returns a new UUID if no context ID is found.
    """
    try:
        if hasattr(obj, 'contextId') and obj.contextId is not None:
            return obj.contextId
        if hasattr(obj, 'context_id') and obj.context_id is not None:
            return obj.context_id
        return getattr(obj, 'contextId', getattr(obj, 'context_id', default or str(uuid.uuid4())))
    except Exception:
        return default or str(uuid.uuid4())


def get_message_id(obj: Any, default: str = None) -> str:
    """
    Extract messageId from an object with fallback support for both camelCase and snake_case naming conventions.
    Returns a new UUID if no message ID is found.
    """
    try:
        if hasattr(obj, 'messageId') and obj.messageId is not None:
            return obj.messageId
        if hasattr(obj, 'message_id') and obj.message_id is not None:
            return obj.message_id
        return getattr(obj, 'messageId', getattr(obj, 'message_id', default or str(uuid.uuid4())))
    except Exception:
        return default or str(uuid.uuid4())


def get_task_id(obj: Any, default: str = None) -> str:
    """
    Extract taskId from an object with fallback support for multiple naming conventions (taskId, task_id, or id).
    Returns a new UUID if no task ID is found.
    """
    try:
        if hasattr(obj, 'taskId') and obj.taskId is not None:
            return obj.taskId
        if hasattr(obj, 'task_id') and obj.task_id is not None:
            return obj.task_id
        if hasattr(obj, 'id') and obj.id is not None:
            return obj.id
        return getattr(obj, 'taskId', getattr(obj, 'task_id', getattr(obj, 'id', default or str(uuid.uuid4()))))
    except Exception:
        return default or str(uuid.uuid4())


def normalize_env_bool(raw_value: str | None, default: bool = False) -> bool:
    """Parse boolean environment variable with support for common true/false representations."""
    if raw_value is None:
        return default
    normalized = raw_value.strip().strip('"').strip("'").lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def normalize_env_int(raw_value: str | None, default: int) -> int:
    """Parse integer environment variable with support for quoted values."""
    if raw_value is None:
        return default
    try:
        return int(raw_value.strip().strip('"').strip("'"))
    except (TypeError, ValueError):
        return default
