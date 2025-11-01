"""
Centralized logging configuration for the A2A backend.

Controls log verbosity across all backend services.
Set VERBOSE_LOGGING=true in environment to see detailed debug logs.
"""
import os
from typing import Any

# Read verbose flag from environment (defaults to False for clean logs)
VERBOSE_LOGGING = os.environ.get("VERBOSE_LOGGING", "false").lower() in ("true", "1", "yes")


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
    if VERBOSE_LOGGING:
        print(f"[DEBUG] {message}", *args)


def log_websocket_debug(message: str, *args: Any) -> None:
    """Log WebSocket debug messages (only shown when VERBOSE_LOGGING=true)."""
    if VERBOSE_LOGGING:
        print(f"[WEBSOCKET DEBUG] {message}", *args)


def log_memory_debug(message: str, *args: Any) -> None:
    """Log memory service debug messages (only shown when VERBOSE_LOGGING=true)."""
    if VERBOSE_LOGGING:
        print(f"[A2AMemoryService] {message}", *args)


def log_foundry_debug(message: str, *args: Any) -> None:
    """Log Foundry agent debug messages (only shown when VERBOSE_LOGGING=true)."""
    if VERBOSE_LOGGING:
        print(f"🔍 DEBUG: {message}", *args)


def log_auth(message: str, *args: Any) -> None:
    """Log auth messages (always shown for security visibility)."""
    print(f"[AuthService] {message}", *args)

