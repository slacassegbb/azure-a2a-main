"""
WebSocket Server Startup Script
Starts the WebSocket server with periodic agent registry sync enabled.
"""
import signal
import sys
import time
import logging
from service.websocket_server import start_websocket_server, set_auth_service

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
    logger.info("🚀 Starting WebSocket server with periodic sync...")
    print("🚀 Starting WebSocket server with periodic sync...", flush=True)
    
    try:
        # Initialize AuthService for WebSocket authentication
        # Use the lightweight auth_service module to avoid slow Azure SDK imports
        logger.info("📝 Initializing AuthService for WebSocket authentication...")
        from service.auth_service import AuthService
        auth_service_instance = AuthService()
        set_auth_service(auth_service_instance)
        logger.info("✅ AuthService initialized successfully")
        
        # Start server (includes 15-second periodic sync)
        server = start_websocket_server(host='0.0.0.0', port=8080)
        logger.info("✅ WebSocket server started successfully")
        
        # Handle graceful shutdown
        def shutdown_handler(signum, frame):
            logger.info("📴 Shutting down WebSocket server...")
            print("📴 Shutting down WebSocket server...", flush=True)
            server.stop()
            sys.exit(0)
        
        signal.signal(signal.SIGTERM, shutdown_handler)
        signal.signal(signal.SIGINT, shutdown_handler)
        
        logger.info("✅ WebSocket server running with periodic agent sync enabled")
        logger.info("   Sync interval: 15 seconds")
        print("✅ WebSocket server running. Sync interval: 15 seconds", flush=True)
        
        # Keep the main thread alive and log status every minute
        counter = 0
        try:
            while True:
                time.sleep(10)
                counter += 10
                if counter % 60 == 0:
                    logger.info(f"WebSocket server still running (uptime: {counter}s)")
                    print(f"✅ WebSocket server alive (uptime: {counter}s)", flush=True)
        except KeyboardInterrupt:
            shutdown_handler(None, None)
            
    except Exception as e:
        logger.error(f"❌ CRITICAL ERROR starting WebSocket server: {e}", exc_info=True)
        print(f"❌ CRITICAL ERROR: {e}", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()

