# AI Foundry ServiceNow (SN) Agent

An Azure AI Foundry agent that simulates ServiceNow and banking workflows while integrating with the A2A protocol. It can run alongside other agents and self‑register with a host orchestrator.

## Features
- 🧰 **ServiceNow Management** – Create/search/update incidents; list users; search KB articles (simulated with realistic synthetic data).
- 🏦 **Bank Actions** – Simulate card block/unblock, balance checks, fraud reporting, disputes, and refunds.
- 🔎 **Web Search** – Query the web (e.g., Bing) for current information.
- 📂 **File & Knowledge Search** – Search uploaded files and knowledge bases for answers.
- 🙋 **Human Expert Escalation** – Request human‑in‑the‑loop assistance for complex issues.
- 🌐 **Dual Modes** – A2A API server (default `8000`) and optional Gradio UI (default `8085`).
- 🤝 **Self‑Registration** – Registers with the Host Agent (`A2A_HOST`, defaults to `http://localhost:12000`).

## Project Structure
```
├── foundry_agent.py            # Core ServiceNow/banking logic and response formatting
├── foundry_agent_executor.py   # A2A executor with streaming and shared-thread execution
├── __main__.py                 # CLI entry point (A2A server + optional Gradio UI)
├── MCP_SERVICENOW/             # MCP server for ServiceNow tool endpoints
├── utils/self_registration.py  # Host-agent self‑registration helper
├── documents/                  # Reference docs (optional)
├── static/                     # UI assets
└── pyproject.toml              # Dependencies
```

## ServiceNow MCP server integration
This agent is wired to use a ServiceNow MCP server (Model Context Protocol) via Azure Foundry’s `McpTool`. The MCP server exposes ServiceNow tools the agent can call, such as:
- `create_incident`, `update_incident`, `search_records`, `get_record`, `perform_query`
- `add_comment`, `add_work_notes`
- plus SN alias helpers expected by the agent

Run the MCP server locally (HTTP/SSE) or expose it publicly (e.g., ngrok) so the agent can reach it:

```bash
# Option A: HTTP transport on localhost:8005
python -m mcp_server_servicenow.cli --transport http --host 127.0.0.1 --port 8005

# Option B: SSE with direct ServiceNow credentials
python -m mcp_server_servicenow.cli \
  --url "https://your-instance.service-now.com/" \
  --username "your-username" \
  --password "your-password"
```

For convenience, see `MCP_SERVICENOW/servicenow-mcp/README.md` for full setup and the `add_mcp_tunnel.py` helper to expose an HTTP MCP on `/mcp/` via ngrok.

Configure the MCP endpoint used by the agent:
- Update the MCP server URL in `remote_agents/azurefoundry_SN/foundry_agent.py` (look for the `self._mcp_server_url` assignment) to point at your MCP endpoint (e.g., `https://<your-ngrok-domain>/mcp/`).
- The agent performs a basic connectivity test at startup; check logs if connectivity fails.

> Note: If the MCP server is unreachable, the agent will continue in simulated mode, but live ServiceNow actions will be unavailable.

## Quick Start
### 1) Environment Setup
```bash
# Required Azure AI Foundry settings
export AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=your-project-endpoint
export AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=your-model-deployment

# Optional: A2A host for self-registration (host agent URL)
export A2A_HOST=http://localhost:12000

# Optional: override bind/advertised endpoint
export A2A_ENDPOINT=localhost    # hostname used in public URL
export A2A_PORT=8000             # A2A server port (defaults to 8000)
```

### 2) Install Dependencies
```bash
uv sync
```

### 3) Run the Agent
- **A2A server only** (serves on `http://$A2A_ENDPOINT:$A2A_PORT/`):
  ```bash
  uv run .
  ```
  Health check: `http://$A2A_ENDPOINT:$A2A_PORT/health`

- **Gradio UI + A2A server**
  ```bash
  uv run . --ui
  ```
  UI: `http://localhost:8085` (default)  |  A2A API: `http://localhost:8000/`

- **Custom ports**
  ```bash
  uv run . --ui --ui-port 8091 --port 8003
  ```

### 4) Verify Self‑Registration (optional)
With the host agent running, start the SN agent and confirm it appears in the host’s Remote Agents list.

## Example Tasks
- "Create a new ServiceNow incident for a login outage."
- "List incidents assigned to John Doe."
- "Block a compromised credit card and report fraud."
- "Search the KB for password reset steps."

## Troubleshooting
- Ensure `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` and `AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME` are set.
- If the UI doesn’t load, verify port `8085` or set `--ui-port`.
- If the A2A server fails to bind, verify port `8000` or set `A2A_PORT`/`--port`.
- If self‑registration fails, confirm the host URL in `A2A_HOST` and that the host is reachable.
- If MCP calls fail, verify the MCP server is reachable at your configured URL and inspect its logs.

## Default Ports & Environment Overrides
- A2A Server: `A2A_ENDPOINT:A2A_PORT` (defaults to `localhost:8000`, override via env or `--port`)
- Gradio UI: `8085` (override with `--ui-port`)
- Host Agent URL: `A2A_HOST` (defaults to `http://localhost:12000`, accepts empty string to disable)
