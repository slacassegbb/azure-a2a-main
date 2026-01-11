#!/usr/bin/env python3
"""
Start ServiceNow MCP Server with ngrok tunnel for public access
"""

import asyncio
import os
import sys
import threading
import time
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

try:
    from pyngrok import ngrok, conf
    NGROK_AVAILABLE = True
except ImportError:
    NGROK_AVAILABLE = False
    print("❌ pyngrok not available. Install with: pip install pyngrok")

from mcp_server_servicenow.server import ServiceNowMCP, create_basic_auth

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def start_mcp_server():
    """Start the MCP server in a separate thread"""
    try:
        # Get credentials from environment
        username = os.getenv("SERVICENOW_USERNAME")
        password = os.getenv("SERVICENOW_PASSWORD") 
        instance_url = os.getenv("SERVICENOW_INSTANCE_URL")
        
        if not all([username, password, instance_url]):
            logger.error("Missing required environment variables: SERVICENOW_USERNAME, SERVICENOW_PASSWORD, SERVICENOW_INSTANCE_URL")
            return
        
        logger.info("Starting ServiceNow MCP server...")
        logger.info(f"Instance URL: {instance_url}")
        logger.info(f"Username: {username}")
        
        # Create authentication
        auth = create_basic_auth(username, password)
        
        # Create server
        server = ServiceNowMCP(instance_url=instance_url, auth=auth)
        
        # Configure SSE transport
        transport_options = {
            "host": "127.0.0.1",
            "port": 8000,
            "path": "/mcp/",
        }
        
        logger.info("Starting MCP server on localhost:8000...")
        server.run(transport="sse", **transport_options)
        
    except Exception as e:
        logger.error(f"MCP Server error: {e}")

def setup_ngrok_tunnel():
    """Setup ngrok tunnel to expose the MCP server"""
    if not NGROK_AVAILABLE:
        logger.error("pyngrok not available")
        return None
    
    try:
        # Set ngrok config (optional)
        # You can set your auth token here if you have one
        # conf.get_default().auth_token = "your_auth_token_here"
        
        logger.info("Creating ngrok tunnel...")
        
        # Create HTTP tunnel to localhost:8000
        public_tunnel = ngrok.connect(8000, "http")
        public_url = public_tunnel.public_url
        
        logger.info(f"✅ ngrok tunnel created!")
        logger.info(f"🌐 Public URL: {public_url}")
        logger.info(f"🔗 MCP Endpoint: {public_url}/mcp/")
        
        return public_url
        
    except Exception as e:
        logger.error(f"Failed to create ngrok tunnel: {e}")
        logger.error("Make sure ngrok is properly installed and you have internet connection")
        return None

def main():
    """Main function to start both MCP server and ngrok tunnel"""
    print("🚀 Starting ServiceNow MCP Server with ngrok tunnel")
    print("=" * 60)
    
    if not NGROK_AVAILABLE:
        print("❌ pyngrok not available. Installing...")
        os.system("pip install pyngrok")
        print("✅ Please restart this script after installation")
        return
    
    # Start MCP server in background thread
    print("1️⃣ Starting MCP server...")
    server_thread = threading.Thread(target=start_mcp_server, daemon=True)
    server_thread.start()
    
    # Wait a moment for server to start
    print("⏳ Waiting for MCP server to start...")
    time.sleep(3)
    
    # Create ngrok tunnel
    print("2️⃣ Creating ngrok tunnel...")
    public_url = setup_ngrok_tunnel()
    
    if public_url:
        print("\n" + "=" * 60)
        print("🎉 SUCCESS! Your ServiceNow MCP server is now publicly accessible!")
        print("=" * 60)
        print(f"🌐 Public URL: {public_url}")
        print(f"🔗 MCP Endpoint: {public_url}/mcp/")
        print(f"🏠 Local URL: http://127.0.0.1:8000/mcp/")
        print("=" * 60)
        print("\n📋 For Azure Foundry integration, use:")
        print(f'   server_url="{public_url}/mcp/"')
        print("\n⚠️  Keep this script running to maintain the tunnel!")
        print("   Press Ctrl+C to stop both server and tunnel")
        
        try:
            # Keep the main thread alive
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Stopping server and tunnel...")
            ngrok.kill()
            print("✅ Stopped successfully")
    else:
        print("❌ Failed to create ngrok tunnel")
        print("💡 You can still use the local URL: http://127.0.0.1:8000/mcp/")

if __name__ == "__main__":
    main() 