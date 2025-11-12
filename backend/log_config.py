"""
Centralized structured logging configuration for the A2A backend.

Provides context-aware logging with categories and better formatting.
Set VERBOSE_LOGGING=true in environment to see detailed debug logs.
"""
import os
import json
from typing import Any, Optional
from datetime import datetime
from enum import Enum


class LogLevel(Enum):
    """Log level enumeration."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"


class LogCategory(Enum):
    """Log category for better filtering and context."""

    SYSTEM = "SYSTEM"
    WEBSOCKET = "WEBSOCKET"
    VOICE = "VOICE"
    A2A = "A2A"
    AUTH = "AUTH"
    STORAGE = "STORAGE"
    AGENT = "AGENT"
    MEMORY = "MEMORY"


# Read verbose flag from environment (defaults to False for clean logs)
VERBOSE_LOGGING = os.environ.get("VERBOSE_LOGGING", "false").lower() in (
    "true",
    "1",
    "yes",
)


def _format_log(
    level: LogLevel,
    message: str,
    category: Optional[LogCategory] = None,
    context: Optional[dict[str, Any]] = None,
    *args: Any,
) -> str:
    """
    Format a structured log message.

    Args:
        level: Log level
        message: Main log message
        category: Optional category for context
        context: Optional dict of contextual information
        *args: Additional arguments to print

    Returns:
        Formatted log string
    """
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

    # Build prefix
    if level == LogLevel.SUCCESS:
        prefix = "✅"
    elif level == LogLevel.WARNING:
        prefix = "⚠️"
    elif level == LogLevel.ERROR:
        prefix = "❌"
    else:
        prefix = f"[{level.value}]"

    # Add category if provided
    if category:
        prefix = f"{prefix} [{category.value}]"

    # Build message
    parts = [f"{timestamp} {prefix} {message}"]

    # Add args
    if args:
        parts.extend(str(arg) for arg in args)

    # Add context if provided and in verbose mode
    if context and VERBOSE_LOGGING:
        context_str = json.dumps(context, indent=2)
        parts.append(f"\n  Context: {context_str}")

    return " ".join(parts)


def log_info(
    message: str,
    category: Optional[LogCategory] = None,
    context: Optional[dict[str, Any]] = None,
    *args: Any,
) -> None:
    """Log informational messages (always shown)."""
    print(_format_log(LogLevel.INFO, message, category, context, *args))


def log_success(
    message: str,
    category: Optional[LogCategory] = None,
    context: Optional[dict[str, Any]] = None,
    *args: Any,
) -> None:
    """Log success messages (always shown)."""
    print(_format_log(LogLevel.SUCCESS, message, category, context, *args))


def log_warning(
    message: str,
    category: Optional[LogCategory] = None,
    context: Optional[dict[str, Any]] = None,
    *args: Any,
) -> None:
    """Log warning messages (always shown)."""
    print(_format_log(LogLevel.WARNING, message, category, context, *args))


def log_error(
    message: str,
    category: Optional[LogCategory] = None,
    context: Optional[dict[str, Any]] = None,
    *args: Any,
) -> None:
    """Log error messages (always shown)."""
    print(_format_log(LogLevel.ERROR, message, category, context, *args))


def log_debug(
    message: str,
    category: Optional[LogCategory] = None,
    context: Optional[dict[str, Any]] = None,
    *args: Any,
) -> None:
    """Log debug messages (only shown when VERBOSE_LOGGING=true)."""
    if VERBOSE_LOGGING:
        print(_format_log(LogLevel.DEBUG, message, category, context, *args))


def log_websocket_debug(
    message: str, context: Optional[dict[str, Any]] = None, *args: Any
) -> None:
    """Log WebSocket debug messages (only shown when VERBOSE_LOGGING=true)."""
    log_debug(message, LogCategory.WEBSOCKET, context, *args)


def log_memory_debug(
    message: str, context: Optional[dict[str, Any]] = None, *args: Any
) -> None:
    """Log memory debug messages (only shown when VERBOSE_LOGGING=true)."""
    log_debug(message, LogCategory.MEMORY, context, *args)


def log_voice_debug(
    message: str, context: Optional[dict[str, Any]] = None, *args: Any
) -> None:
    """Log voice-related debug messages (only shown when VERBOSE_LOGGING=true)."""
    log_debug(message, LogCategory.VOICE, context, *args)


def log_a2a_debug(
    message: str, context: Optional[dict[str, Any]] = None, *args: Any
) -> None:
    """Log A2A communication debug messages (only shown when VERBOSE_LOGGING=true)."""
    log_debug(message, LogCategory.A2A, context, *args)


def log_auth_debug(
    message: str, context: Optional[dict[str, Any]] = None, *args: Any
) -> None:
    """Log authentication debug messages (only shown when VERBOSE_LOGGING=true)."""
    log_debug(message, LogCategory.AUTH, context, *args)
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
