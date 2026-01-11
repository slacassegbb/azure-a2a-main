#!/usr/bin/env python3
"""
Add MCP tunnel to existing ngrok session
"""

import requests
import json
import time
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_ngrok_api_url():
    """Get the ngrok API URL - try common ports"""
    common_ports = [4040, 4041, 4042, 4043]
    
    for port in common_ports:
        try:
            api_url = f"http://127.0.0.1:{port}/api"
            response = requests.get(f"{api_url}/tunnels", timeout=2)
            if response.status_code == 200:
                logger.info(f"✅ Found ngrok API at port {port}")
                return api_url
        except:
            continue
    
    return None

def list_existing_tunnels(api_url):
    """List existing tunnels in the ngrok session"""
    try:
        response = requests.get(f"{api_url}/tunnels")
        if response.status_code == 200:
            tunnels = response.json().get("tunnels", [])
            logger.info(f"📋 Found {len(tunnels)} existing tunnels:")
            for tunnel in tunnels:
                name = tunnel.get("name", "unknown")
                public_url = tunnel.get("public_url", "unknown")
                config = tunnel.get("config", {})
                addr = config.get("addr", "unknown")
                logger.info(f"   - {name}: {public_url} -> {addr}")
            return tunnels
        else:
            logger.error(f"Failed to list tunnels: {response.status_code}")
            return []
    except Exception as e:
        logger.error(f"Error listing tunnels: {e}")
        return []

def add_mcp_tunnel(api_url):
    """Add a new tunnel for the MCP server"""
    tunnel_config = {
        "addr": "8000",
        "proto": "http",
        "name": "mcp-servicenow",
        "bind_tls": True
    }
    
    try:
        logger.info("🚀 Adding MCP tunnel to existing ngrok session...")
        response = requests.post(f"{api_url}/tunnels", json=tunnel_config)
        
        if response.status_code == 201:
            tunnel_data = response.json()
            public_url = tunnel_data.get("public_url", "")
            name = tunnel_data.get("name", "")
            
            logger.info("✅ MCP tunnel created successfully!")
            logger.info(f"🌐 Public URL: {public_url}")
            logger.info(f"🔗 MCP Endpoint: {public_url}/mcp/")
            
            return public_url
        else:
            error_data = response.json() if response.content else {}
            error_msg = error_data.get("msg", f"HTTP {response.status_code}")
            logger.error(f"❌ Failed to create tunnel: {error_msg}")
            
            # Check if tunnel already exists
            if "already exists" in error_msg.lower() or response.status_code == 400:
                logger.info("🔍 Tunnel might already exist, checking existing tunnels...")
                tunnels = list_existing_tunnels(api_url)
                for tunnel in tunnels:
                    if tunnel.get("name") == "mcp-servicenow":
                        public_url = tunnel.get("public_url", "")
                        logger.info(f"✅ Found existing MCP tunnel: {public_url}")
                        return public_url
            
            return None
            
    except Exception as e:
        logger.error(f"❌ Error creating tunnel: {e}")
        return None

def main():
    """Main function to add MCP tunnel to existing ngrok session"""
    print("🔗 Adding MCP Tunnel to Existing ngrok Session")
    print("=" * 60)
    
    # Find ngrok API
    api_url = get_ngrok_api_url()
    if not api_url:
        print("❌ Could not find running ngrok API")
        print("💡 Make sure ngrok is running with a web interface")
        print("   Try: ngrok http 3000 (or any other tunnel)")
        return
    
    print(f"🔍 Using ngrok API: {api_url}")
    
    # List existing tunnels (if any)
    print("\n📋 Current tunnels:")
    for tunnel in list_existing_tunnels(api_url):
        print(f" - {tunnel.get('name','unknown')}: {tunnel.get('public_url','')}")
    
    # Add MCP tunnel
    print("\n🚀 Adding MCP tunnel...")
    public_url = add_mcp_tunnel(api_url)
    
    if public_url:
        print("\n" + "=" * 60)
        print("🎉 SUCCESS! MCP tunnel added to existing ngrok session!")
        print("=" * 60)
        print(f"🌐 Public URL: {public_url}")
        print(f"🔗 MCP Endpoint: {public_url}/mcp/")
        print(f"🏠 Local URL: http://127.0.0.1:8000/mcp/")
        print("=" * 60)
        print("\n📋 For Azure Foundry integration, use:")
        print(f'   server_url="{public_url}/mcp/"')
        print("\n✅ Your MCP server is now publicly accessible!")
        print("   The tunnel will remain active as long as your ngrok session runs")
        
        # Test the tunnel
        print("\n🧪 Testing the tunnel...")
        try:
            test_response = requests.get(public_url, timeout=5)
            if test_response.status_code in [200, 404]:  # 404 is expected for root path
                print("✅ Tunnel is accessible from the internet!")
            else:
                print(f"⚠️  Tunnel responds but with status: {test_response.status_code}")
        except Exception as e:
            print(f"⚠️  Could not test tunnel: {e}")
    else:
        print("❌ Failed to create MCP tunnel")
        print("💡 Check the ngrok dashboard for more details")

if __name__ == "__main__":
    main() 