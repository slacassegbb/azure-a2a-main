# AI Foundry Legal Compliance & Regulatory Agent

An Azure AI Foundry agent specializing in legal/compliance analysis and guidance. It speaks A2A so it can run alongside other agents and self‑register with a host orchestrator.

## Features
- ⚖️ **Regulatory Analysis** – Guidance for GDPR, SOX, CCPA and related frameworks.
- 🛡️ **Risk Assessment** – Evaluates legal/compliance risk and proposes mitigation steps.
- 📚 **Regulatory Research** – Looks up requirements using integrated search and reference docs.
- 📄 **Document Analysis** – Reviews policies/contracts/compliance docs for required clauses and gaps.
- 🚨 **Incident Reporting** – Drafts breach/violation reports and escalation guidance.
- 🔎 **Web & File Search** – Searches the web and uploaded knowledge bases for current legal info.
- 🌐 **Dual Modes** – A2A API server (default `8006`) and optional Gradio UI (default `8095`).
- 🤝 **Self‑Registration** – Registers with the Host Agent (`A2A_HOST`, defaults to `http://localhost:12000`).

## Project Structure
```
├── foundry_agent.py            # Core legal/compliance logic and response formatting
├── foundry_agent_executor.py   # A2A executor with streaming and shared-thread execution
├── __main__.py                 # CLI entry point (A2A server + optional Gradio UI)
├── utils/self_registration.py  # Host-agent self‑registration helper
├── documents/                  # Legal/compliance reference materials
├── static/                     # UI assets (e.g., a2a.png)
└── pyproject.toml              # Dependencies
```

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
export A2A_PORT=8006             # A2A server port (defaults to 8006)
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
  UI: `http://localhost:8095` (default)  |  A2A API: `http://localhost:8006/`

- **Custom ports**
  ```bash
  uv run . --ui --ui-port 8101 --port 8010
  ```

### 4) Verify Self‑Registration (optional)
With the host agent running, start the Legal agent and confirm it appears in the host’s Remote Agents list.

## Example Tasks
- "Assess GDPR compliance for new data processing activity."
- "Conduct a SOX Section 404 controls review."
- "Analyze this privacy policy for gaps vs GDPR."
- "Draft an incident report for a suspected data breach."

## Troubleshooting
- Ensure `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` and `AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME` are set.
- If the UI doesn’t load, verify port `8095` or set `--ui-port`.
- If the A2A server fails to bind, verify port `8006` or set `A2A_PORT`/`--port`.
- If self‑registration fails, confirm the host URL in `A2A_HOST` and that the host is reachable.

## Default Ports & Environment Overrides
- A2A Server: `A2A_ENDPOINT:A2A_PORT` (defaults to `localhost:8006`, override via env or `--port`)
- Gradio UI: `8095` (override with `--ui-port`)
- Host Agent URL: `A2A_HOST` (defaults to `http://localhost:12000`, accepts empty string to disable)
