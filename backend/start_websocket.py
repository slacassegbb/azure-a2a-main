"""
WebSocket Server Startup Script

Runs the WebSocket server directly with uvicorn in a single event loop.
Periodic agent registry sync runs as an asyncio background task via the
FastAPI lifespan — no background threads, no cross-loop issues.
"""
import sys
import logging
import uvicorn
from service.websocket_server import create_websocket_app, set_auth_service

# Suppress noisy third-party loggers
for _name in ["azure", "azure.core", "azure.identity", "httpx", "httpcore",
              "openai", "aiohttp", "urllib3", "msal", "opentelemetry"]:
    logging.getLogger(_name).setLevel(logging.WARNING)
for _name in ["azure.monitor.opentelemetry", "opentelemetry"]:
    logging.getLogger(_name).setLevel(logging.ERROR)

# Configure logging to output to stdout with immediate flushing
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ],
    force=True  # Override any existing configuration
)

# Disable buffering for immediate log output
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

logger = logging.getLogger(__name__)


def main():
    """Start WebSocket server — single process, single event loop."""
    logger.info("Starting WebSocket server...")

    # Initialize AuthService for WebSocket authentication
    logger.info("Initializing AuthService for WebSocket authentication...")
    from service.auth_service import AuthService
    auth_service_instance = AuthService()
    set_auth_service(auth_service_instance)
    logger.info("AuthService initialized successfully")

    # Create the FastAPI app (lifespan handles periodic sync)
    app = create_websocket_app()

    # Run uvicorn directly — everything in one event loop
    # Ctrl+C / SIGTERM handled by uvicorn's built-in signal handling
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
