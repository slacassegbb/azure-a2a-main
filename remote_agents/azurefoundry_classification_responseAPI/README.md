# AI Foundry Classification Triage Agent

An Azure AI Foundry agent that classifies customer incidents and recommends routing/priority based on ServiceNow standards. It reuses the A2A framework so it can run locally alongside other agents and self-register with a host agent.

## Features
- 🧭 **Incident Classification** – Categorizes messages into Fraud, Technical Issues, Payment Issues, Card Issues, Account Services, Security, and Inquiries.
- ⚡ **Priority Assessment** – Determines urgency/impact/priority using a ServiceNow-style matrix.
- 🚦 **Routing & Triage** – Recommends team assignment and escalation paths.
- 🧩 **Field Mapping** – Maps details to ServiceNow fields (category, subcategory, short description, metadata).
- 🔎 **Keyword Analysis** – Extracts signals and context cues to improve classification.
- 🌐 **Dual Operation Modes** – Run as an A2A server (default `8001`) or launch the Gradio UI (default `8089`) alongside it.
- 🤝 **Self-Registration** – Automatically registers with the Host Agent (`A2A_HOST`, defaults to `http://localhost:12000`).

## Project Structure
```
├── foundry_agent.py           # Core Azure AI Foundry agent logic (classification/triage)
├── foundry_agent_executor.py  # A2A executor with streaming and shared-thread execution
├── __main__.py                # CLI entry point (A2A server + optional Gradio UI)
├── utils/self_registration.py # Host-agent self-registration helper
├── documents/                 # (optional) reference docs used by skills
├── static/                    # UI assets (e.g., a2a.png)
└── pyproject.toml             # Dependencies
```

## Quick Start
### 1) Environment Setup
```bash
# Set required Azure AI Foundry variables (in shell or a local .env)
export AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=your-project-endpoint
export AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=your-model-deployment

# Optional: A2A host for self-registration (host agent URL)
export A2A_HOST=http://localhost:12000

# Optional: override bind/advertised endpoint
export A2A_ENDPOINT=localhost    # hostname used in public URL
export A2A_PORT=8001             # A2A server port (defaults to 8001)
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
  UI: `http://localhost:8089` (default)  |  A2A API: `http://localhost:8001/`

- **Custom ports**
  ```bash
  uv run . --ui --ui-port 8095 --port 8005
  ```

### 4) Verify Self-Registration (optional)
With the host agent running, start the classification agent and check for the new agent in the host’s Remote Agents list. You can also run a self-registration diagnostic from similar agents’ test utilities if needed.

## Sample Prompts
- "There’s an unauthorized $500 charge on my account."
- "I can’t log into the mobile banking app; it says invalid credentials."
- "ATM dispensed no cash but charged my account $200."
- "Please close my account and explain any fees."

## Troubleshooting
- Ensure `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` and `AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME` are set.
- Confirm the host agent is reachable at `A2A_HOST` for self-registration.
- If the UI doesn’t load, check that port `8089` is free (or set `--ui-port`).
- If the A2A server fails to bind, ensure port `8001` is free (or set `A2A_PORT` / `--port`).

## Default Ports & Environment Overrides
- A2A Server: `A2A_ENDPOINT:A2A_PORT` (defaults to `localhost:8001`, override via env or `--port`)
- Gradio UI: `8089` (override with `--ui-port`)
- Host Agent URL: `A2A_HOST` (defaults to `http://localhost:12000`, accepts empty string to disable)

Happy triaging! 🗂️
