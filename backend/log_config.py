"""
Centralized logging configuration for the A2A backend.

Controls log verbosity across all backend services.
Set VERBOSE_LOGGING=true in environment to see detailed debug logs.
"""
import os
from typing import Any


def _is_verbose() -> bool:
    """
    Check if verbose logging is enabled.
    
    Lazy evaluation to avoid circular import with settings module.
    
    :return: True if verbose logging is enabled
    """
    # Try to get from settings first (if available)
    try:
        from config import settings
        if hasattr(settings, 'server') and hasattr(settings.server, 'verbose_logging'):
            return settings.server.verbose_logging
    except (ImportError, RuntimeError, AttributeError):
        pass
    
    # Fallback to environment variable during initialization
    return os.environ.get("VERBOSE_LOGGING", "false").lower() in (
        "true",
        "1",
        "yes",
    )


def log_info(message: str, *args: Any) -> None:
    """Log informational messages (always shown)."""
    print(f"[INFO] {message}", *args)


def log_success(message: str, *args: Any) -> None:
    """Log success messages (always shown)."""
    print(f"✅ {message}", *args)


def log_warning(message: str, *args: Any) -> None:
    """Log warning messages (always shown)."""
    print(f"[WARNING] {message}", *args)


def log_error(message: str, *args: Any) -> None:
    """Log error messages (always shown)."""
    print(f"[ERROR] {message}", *args)


def log_debug(message: str, *args: Any) -> None:
    """Log debug messages (only shown when VERBOSE_LOGGING=true)."""
    if _is_verbose():
        print(f"[DEBUG] {message}", *args)


def log_websocket_debug(message: str, *args: Any) -> None:
    """Log WebSocket debug messages (only shown when VERBOSE_LOGGING=true)."""
    if _is_verbose():
        print(f"[WEBSOCKET DEBUG] {message}", *args)


def log_memory_debug(message: str, *args: Any) -> None:
    """Log memory service debug messages (only shown when VERBOSE_LOGGING=true)."""
    if _is_verbose():
        print(f"[A2AMemoryService] {message}", *args)


def log_foundry_debug(message: str, *args: Any) -> None:
    """Log Foundry agent debug messages (only shown when VERBOSE_LOGGING=true)."""
    if _is_verbose():
        print(f"🔍 DEBUG: {message}", *args)


def log_auth(message: str, *args: Any) -> None:
    """Log auth messages (always shown for security visibility)."""
    print(f"[AuthService] {message}", *args)
