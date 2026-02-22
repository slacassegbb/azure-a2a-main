"""
Centralized logging configuration for the A2A backend.

Controls log verbosity across all backend services.
Set VERBOSE_LOGGING=true in environment to see detailed debug logs.
"""
import os
import logging
import sys
from typing import Any

# Read verbose flag from environment (defaults to False for clean logs)
VERBOSE_LOGGING = os.environ.get("VERBOSE_LOGGING", "false").lower() in ("true", "1", "yes")


def suppress_noisy_libraries() -> None:
    """Suppress verbose logging from third-party libraries."""
    noisy_loggers = [
        "azure",
        "azure.core",
        "azure.identity",
        "azure.storage",
        "azure.search",
        "azure.ai",
        "azure.eventhub",
        "azure.monitor",
        "azure.monitor.opentelemetry",
        "openai",
        "httpx",
        "httpcore",
        "aiohttp",
        "urllib3",
        "opentelemetry",
        "msal",
        "uamqp",
        "a2a",
        "a2a.utils",
        "a2a.utils.telemetry",
    ]
    for name in noisy_loggers:
        logging.getLogger(name).setLevel(logging.WARNING)

    # These are extra noisy — silence completely (they spam even at ERROR level)
    for name in [
        "azure.monitor",
        "azure.monitor.opentelemetry",
        "azure.monitor.opentelemetry.exporter",
        "azure.monitor.opentelemetry.exporter.export._base",
        "opentelemetry",
    ]:
        logging.getLogger(name).setLevel(logging.CRITICAL)


# Apply suppression at import time
suppress_noisy_libraries()

# Configure root logger level based on verbosity
logging.basicConfig(
    level=logging.DEBUG if VERBOSE_LOGGING else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)


def log_info(message: str, *args: Any) -> None:
    """Log informational messages (always shown)."""
    print(f"[INFO] {message}", *args, flush=True)


def log_success(message: str, *args: Any) -> None:
    """Log success messages (always shown)."""
    print(f"[INFO] {message}", *args, flush=True)


def log_warning(message: str, *args: Any) -> None:
    """Log warning messages (always shown)."""
    print(f"[WARNING] {message}", *args, flush=True)


def log_error(message: str, *args: Any) -> None:
    """Log error messages (always shown)."""
    print(f"[ERROR] {message}", *args, flush=True)


def log_debug(message: str, *args: Any) -> None:
    """Log debug messages (only shown when VERBOSE_LOGGING=true)."""
    if VERBOSE_LOGGING:
        print(f"[DEBUG] {message}", *args, flush=True)


def log_websocket_debug(message: str, *args: Any) -> None:
    """Log WebSocket debug messages (only shown when VERBOSE_LOGGING=true)."""
    if VERBOSE_LOGGING:
        print(f"[DEBUG] [WS] {message}", *args, flush=True)


def log_memory_debug(message: str, *args: Any) -> None:
    """Log memory service debug messages (only shown when VERBOSE_LOGGING=true)."""
    if VERBOSE_LOGGING:
        print(f"[DEBUG] [MEMORY] {message}", *args, flush=True)


def log_foundry_debug(message: str, *args: Any) -> None:
    """Log Foundry agent debug messages (only shown when VERBOSE_LOGGING=true)."""
    if VERBOSE_LOGGING:
        print(f"[DEBUG] [FOUNDRY] {message}", *args, flush=True)


def log_auth(message: str, *args: Any) -> None:
    """Log auth messages (always shown for security visibility)."""
    print(f"[INFO] [AUTH] {message}", *args, flush=True)
