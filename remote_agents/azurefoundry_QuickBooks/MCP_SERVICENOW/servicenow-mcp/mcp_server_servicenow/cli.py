"""
ServiceNow MCP Server CLI

This module provides the command-line interface for the ServiceNow MCP server.
"""

import argparse
import os
import sys
from dotenv import load_dotenv

from mcp_server_servicenow.server import ServiceNowMCP, create_basic_auth

def main():
    """Run the ServiceNow MCP server from the command line"""
    # Load environment variables from .env file if it exists
    load_dotenv()
    
    parser = argparse.ArgumentParser(description="ServiceNow MCP Server")
    parser.add_argument("--url", help="ServiceNow instance URL", default=os.environ.get("SERVICENOW_INSTANCE_URL"))
    parser.add_argument("--transport", help="Transport protocol (stdio, http, or sse)", default="stdio", choices=["stdio", "http", "sse"])
    parser.add_argument("--host", help="Host for HTTP/SSE transport", default="127.0.0.1")
    parser.add_argument("--port", help="Port for HTTP/SSE transport", type=int, default=8000)
    parser.add_argument("--path", help="Path for HTTP/SSE transport", default="/mcp/")
    
    # Authentication options
    auth_group = parser.add_argument_group("Authentication")
    auth_group.add_argument("--username", help="ServiceNow username", default=os.environ.get("SERVICENOW_USERNAME"))
    auth_group.add_argument("--password", help="ServiceNow password", default=os.environ.get("SERVICENOW_PASSWORD"))
    auth_group.add_argument("--token", help="ServiceNow token", default=os.environ.get("SERVICENOW_TOKEN"))
    auth_group.add_argument("--client-id", help="OAuth client ID", default=os.environ.get("SERVICENOW_CLIENT_ID"))
    auth_group.add_argument("--client-secret", help="OAuth client secret", default=os.environ.get("SERVICENOW_CLIENT_SECRET"))
    
    args = parser.parse_args()
    
    # Check required parameters
    if not args.url:
        print("Error: ServiceNow instance URL is required")
        print("Set SERVICENOW_INSTANCE_URL environment variable or use --url")
        sys.exit(1)
    
    # Determine authentication method
    auth = None
    if args.token:
        from mcp_server_servicenow.server import create_token_auth
        auth = create_token_auth(args.token)
    elif args.client_id and args.client_secret and args.username and args.password:
        from mcp_server_servicenow.server import create_oauth_auth
        auth = create_oauth_auth(args.client_id, args.client_secret, args.username, args.password, args.url)
    elif args.username and args.password:
        auth = create_basic_auth(args.username, args.password)
    else:
        print("Error: Authentication credentials required")
        print("Either provide username/password, token, or OAuth credentials")
        sys.exit(1)
    
    # Create and run the server
    server = ServiceNowMCP(instance_url=args.url, auth=auth)
    
    # Configure transport-specific options
    transport_options = {}
    if args.transport in ["http", "sse"]:
        transport_options.update({
            "host": args.host,
            "port": args.port,
            "path": args.path
        })
    
    print(f"Starting ServiceNow MCP server with {args.transport.upper()} transport")
    if args.transport in ["http", "sse"]:
        print(f"Server will be available at: http://{args.host}:{args.port}{args.path}")
    
    server.run(transport=args.transport, **transport_options)

if __name__ == "__main__":
    main()
