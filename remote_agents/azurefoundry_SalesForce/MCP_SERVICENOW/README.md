# ServiceNow MCP Server (for A2A ServiceNow Agent)

This folder hosts a vendored MCP server that exposes ServiceNow tools via the Model Context Protocol. The A2A ServiceNow agent consumes it through Azure Foundry’s `McpTool` to perform incident/user/KB operations.

## What it provides
- Tool endpoints for ServiceNow operations (create/update/search incidents, get records, comments, work notes, generic queries)
- Transports: `stdio`, `http`, or `sse`
- HTTP/SSE deployment suitable for agents connecting over a URL (e.g., `http://localhost:8005/mcp/` or `https://<domain>/mcp/`)

## Quick start
Choose one of the transports:

- HTTP (local, easy for ngrok):
```bash
python -m mcp_server_servicenow.cli --transport http --host 127.0.0.1 --port 8005 --path /mcp/
```

- SSE (direct to ServiceNow with credentials):
```bash
python -m mcp_server_servicenow.cli \
  --transport sse \
  --host 0.0.0.0 --port 8005 --path /mcp/ \
  --url "https://your-instance.service-now.com/" \
  --username "your-username" \
  --password "your-password"
```

- STDIO (local development, for compatible clients):
```bash
python -m mcp_server_servicenow.cli --transport stdio --url "https://your-instance.service-now.com/" --username "user" --password "pass"
```

Environment variables (optional instead of flags):
```bash
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com/
SERVICENOW_USERNAME=...
SERVICENOW_PASSWORD=...
# or token/OAuth:
SERVICENOW_TOKEN=...
SERVICENOW_CLIENT_ID=...
SERVICENOW_CLIENT_SECRET=...
```

## How the A2A SN agent uses it
- The agent connects to the MCP URL (e.g., `https://<domain>/mcp/`) via Azure Foundry `McpTool`.
- Update the endpoint in `remote_agents/azurefoundry_SN/foundry_agent.py` (search for `self._mcp_server_url`).
- On startup the agent performs a basic connectivity check (including SSE headers) and logs results.
- If the MCP is unavailable, the agent continues in simulated mode (no live ServiceNow actions).

## Tips
- Expose local HTTP with ngrok. The helper `servicenow-mcp/add_mcp_tunnel.py` can register an `/mcp/` tunnel against an existing ngrok session.
- The CLI also supports `--token` or OAuth (`--client-id/--client-secret`) if your instance is configured.
- Default HTTP URL printed at startup: `http://<host>:<port><path>` (defaults: host `127.0.0.1`, port `8000`, path `/mcp/`).

## Source
Core CLI and server:
- `servicenow-mcp/mcp_server_servicenow/cli.py`
- `servicenow-mcp/mcp_server_servicenow/server.py`
