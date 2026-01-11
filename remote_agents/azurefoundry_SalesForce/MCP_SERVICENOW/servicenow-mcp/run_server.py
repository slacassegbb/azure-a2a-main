#!/usr/bin/env python3
"""
Run the ServiceNow MCP Server
This script starts the MCP server that agents can connect to for ServiceNow integration
"""

import os
import sys
import signal
import asyncio
import logging
from dotenv import load_dotenv

from mcp_server_servicenow.server import ServiceNowMCP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global server instance for cleanup
mcp_server = None

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info("Shutdown signal received, cleaning up...")
    if mcp_server:
        try:
            # Stop the server gracefully
            asyncio.run(mcp_server.close())
            logger.info("Server stopped gracefully")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
    sys.exit(0)

def main():
    """Run the MCP server."""
    global mcp_server
    
    # Load environment variables
    load_dotenv()
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Get server configuration from environment
        host = os.getenv("MCP_HOST", "127.0.0.1")
        port = int(os.getenv("MCP_PORT", "8000"))
        transport = os.getenv("MCP_TRANSPORT", "sse")
        
        # Get ServiceNow configuration
        username = os.getenv("SERVICENOW_USERNAME")
        password = os.getenv("SERVICENOW_PASSWORD")
        instance_url = os.getenv("SERVICENOW_INSTANCE_URL")
        
        if not all([username, password, instance_url]):
            logger.error("Missing required ServiceNow environment variables:")
            logger.error("   SERVICENOW_USERNAME")
            logger.error("   SERVICENOW_PASSWORD") 
            logger.error("   SERVICENOW_INSTANCE_URL")
            sys.exit(1)
        
        logger.info(f"Starting ServiceNow MCP server on {host}:{port} using {transport} transport")
        
        # Create and start the server
        from mcp_server_servicenow.server import create_basic_auth
        auth = create_basic_auth(username, password)
        mcp_server = ServiceNowMCP(instance_url, auth)
        mcp_server.run(transport=transport, host=host, port=port)
        
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 