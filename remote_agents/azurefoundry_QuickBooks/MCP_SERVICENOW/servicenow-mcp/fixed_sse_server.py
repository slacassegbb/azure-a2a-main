#!/usr/bin/env python3
"""
Fixed SSE Server for ServiceNow MCP

This version ensures that SSE transport is properly configured with accessible HTTP endpoints.
"""

import asyncio
import os
import sys
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from mcp_server_servicenow.server import ServiceNowMCP, create_basic_auth

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def run_fixed_sse_server():
    """Run the ServiceNow MCP server with properly configured SSE transport"""
    
    # Get credentials from environment
    username = os.getenv("SERVICENOW_USERNAME")
    password = os.getenv("SERVICENOW_PASSWORD") 
    instance_url = os.getenv("SERVICENOW_INSTANCE_URL")
    
    if not all([username, password, instance_url]):
        logger.error("Missing required environment variables: SERVICENOW_USERNAME, SERVICENOW_PASSWORD, SERVICENOW_INSTANCE_URL")
        sys.exit(1)
    
    logger.info("Creating ServiceNow MCP server with fixed SSE transport...")
    logger.info(f"Instance URL: {instance_url}")
    logger.info(f"Username: {username}")
    
    # Create authentication
    auth = create_basic_auth(username, password)
    
    # Create server
    server = ServiceNowMCP(instance_url=instance_url, auth=auth)
    
    # Configure SSE transport with explicit options
    transport_options = {
        "host": "127.0.0.1",
        "port": 8000,
        "path": "/mcp/",
        # Add explicit SSE configuration
        "cors_origins": ["*"],
        "debug": True
    }
    
    logger.info("Starting ServiceNow MCP server with SSE transport...")
    logger.info(f"Server will be available at: http://127.0.0.1:8000/mcp/")
    logger.info("Transport options: %s", transport_options)
    
    try:
        # Run with explicit SSE transport
        await server.run_async(transport="sse", **transport_options)
    except Exception as e:
        logger.error(f"Server failed to start: {e}")
        raise

def main():
    """Main entry point"""
    try:
        asyncio.run(run_fixed_sse_server())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 