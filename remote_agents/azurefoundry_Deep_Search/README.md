# AI Foundry Deep Search Knowledge Agent

An Azure AI Foundry agent that performs deep search across customer support knowledge and procedures. It speaks A2A so it can run alongside other agents and self‑register with a host orchestrator.

## Features
- 🔎 **Document & Knowledge Search** – Answers questions from account, billing/payments, fraud/security, and technical support guides.
- 🧭 **Guided Procedures** – Surfaces steps, requirements, and best practices pulled from reference docs.
- 🧩 **A2A Integration** – Exposes an A2A API server and streams results to the host; supports self‑registration.
- 🌐 **Dual Operation Modes** – Run as an A2A server (default `8002`) or launch the Gradio UI (default `8087`) alongside it.

## Project Structure
```
├── foundry_agent.py           # Core Azure AI Foundry deep search logic
├── foundry_agent_executor.py  # A2A executor with streaming and shared-thread execution
├── __main__.py                # CLI entry point (A2A server + optional Gradio UI)
├── utils/self_registration.py # Host-agent self-registration helper
├── documents/                 # Knowledge base documents used for answers
├── static/                    # UI assets (e.g., a2a.png)
└── pyproject.toml             # Dependencies
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
export A2A_PORT=8002             # A2A server port (defaults to 8002)
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
  UI: `http://localhost:8087` (default)  |  A2A API: `http://localhost:8002/`

- **Custom ports**
  ```bash
  uv run . --ui --ui-port 8097 --port 8007
  ```

### 4) Verify Self-Registration (optional)
With the host agent running, start the Deep Search agent and check for the new agent in the host’s Remote Agents list. You can also use similar self‑registration diagnostics from sibling agents as a reference.

## Sample Prompts
- "How do I close my account and what documents are required?"
- "What fees apply to international wire transfers?"
- "What should I do if I suspect fraud on my card?"
- "How can I reset my online banking password?"

## Troubleshooting
- Ensure `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` and `AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME` are set.
- Confirm the host agent is reachable at `A2A_HOST` for self-registration.
- If the UI doesn’t load, verify port `8087` or set `--ui-port`.
- If the A2A server fails to bind, verify port `8002` or set `A2A_PORT`/`--port`.

## Default Ports & Environment Overrides
- A2A Server: `A2A_ENDPOINT:A2A_PORT` (defaults to `localhost:8002`, override via env or `--port`)
- Gradio UI: `8087` (override with `--ui-port`)
- Host Agent URL: `A2A_HOST` (defaults to `http://localhost:12000`, accepts empty string to disable)

Happy searching! 🔍
