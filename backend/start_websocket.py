"""
WebSocket Server Startup Script
Starts the WebSocket server with periodic agent registry sync enabled.
"""
import signal
import sys
import time
import logging
from service.websocket_server import start_websocket_server, set_auth_service

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
    """Start WebSocket server with proper periodic sync."""
    logger.info("Starting WebSocket server with periodic sync...")

    try:
        # Initialize AuthService for WebSocket authentication
        logger.info("Initializing AuthService for WebSocket authentication...")
        from service.auth_service import AuthService
        auth_service_instance = AuthService()
        set_auth_service(auth_service_instance)
        logger.info("AuthService initialized successfully")

        # Start server (includes 15-second periodic sync)
        server = start_websocket_server(host='0.0.0.0', port=8080)
        logger.info("WebSocket server started successfully")

        # Handle graceful shutdown
        def shutdown_handler(signum, frame):
            logger.info("Shutting down WebSocket server...")
            server.stop()
            sys.exit(0)

        signal.signal(signal.SIGTERM, shutdown_handler)
        signal.signal(signal.SIGINT, shutdown_handler)

        logger.info("WebSocket server running with periodic agent sync (interval: 15s)")

        # Keep the main thread alive
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            shutdown_handler(None, None)

    except Exception as e:
        logger.error(f"CRITICAL ERROR starting WebSocket server: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
