# AI Foundry Assessment & Estimation Agent

An Azure AI Foundry agent tailored for damage inspections, cost estimation, and report preparation. The agent reads estimation playbooks to produce defensible cost ranges, severity ratings, and QA-ready summaries for auto, property, travel, and health losses.

## Features
- 📏 **Multi-Line Assessment** – Uses `documents/` knowledge (auto, property, travel, health, universal, procedures) to ground estimates.
- 💰 **Cost & Severity Modeling** – Applies labor/material tables, depreciation rules, and severity matrices to deliver low/high estimates and escalation triggers.
- ✅ **Workflow & QA Guidance** – Recommends documentation, reinspection steps, and QA checklists to ensure accurate submissions.
- 🌐 **Dual Operation Modes** – Run as A2A server on port `9002` or launch the Gradio UI on port `9102` for interactive assessments.
- 🤝 **Self-Registration** – Automatically registers with the host agent configured via `A2A_HOST` (defaults to `http://localhost:12000`).

## Project Structure
```
├── foundry_agent.py           # Azure AI Foundry assessment/estimation implementation
├── foundry_agent_executor.py  # A2A executor with streaming result handling
├── __main__.py                # CLI entry (A2A server + optional Gradio UI)
├── documents/                 # Estimation reference guides
├── utils/self_registration.py # Host-agent registration helper
├── test_client.py             # Assessment-focused A2A client smoke test
├── test_bing_search.py        # Bing/web search integration test
├── test_self_registration.py  # Self-registration diagnostics
└── pyproject.toml             # Dependencies
```

## Quick Start
### 1. Environment Setup
```bash
cp .env.template .env  # if template provided
```

### 2. Install Dependencies
```bash
uv sync
```

### 3. Configure Azure AI Foundry
```env
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=your-endpoint
AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=your-model
```

### 3a. Configure A2A Server
```env
# Hostname the agent binds to (leave blank to fall back to localhost)
A2A_ENDPOINT=localhost

# Port for the agent's A2A API
A2A_PORT=9002

# Host agent URL for self-registration (empty string disables)
A2A_HOST=http://localhost:12000
```

### 4. Run the Agent
- **A2A server** (defaults to `A2A_ENDPOINT:A2A_PORT`, e.g. `http://localhost:9002`):
  ```bash
  uv run .
  ```
  Health check: `http://$A2A_ENDPOINT:$A2A_PORT/health`

- **Gradio UI + A2A server**:
  ```bash
  uv run . --ui
  ```
  UI: `http://localhost:9102`

- **Custom ports**:
  ```bash
  uv run . --ui --ui-port 9110 --port 9010
  ```

### 5. Self-Registration Check (optional)
Start the host agent (`demo/ui`) and run `python test_self_registration.py` to confirm registration.

## Sample Prompts
- "Provide an estimate for front-end collision repairs with bumper, headlight, and paint work."
- "Basement flood soaked drywall and flooring—calculate material/labor costs and severity."
- "Trip cancellation due to illness: itinerary cost $3,800—estimate reimbursable amount."
- "Hospital stay (3 days) plus CT scan—give typical cost range for comparison."
- "Before submitting the estimate, list the QA checklist items I should verify."

## Testing Utilities
- `python test_client.py` – runs health check, card retrieval, and sample conversations.
- `python test_bing_search.py` – validates Bing search integration for market data.
- `python test_self_registration.py` – verifies registration to the host agent endpoint.

## Troubleshooting
- Ensure Azure AI Foundry TPM quota (≥20k TPM) is available for uninterrupted runs.
- Confirm environment variables are loaded in the working shell.
- Check `documents/` for expected estimation references; missing files reduce accuracy.
- Use the Gradio console output for streaming tool-call diagnostics.

## Defaults & Overrides
- A2A Server: `A2A_ENDPOINT:A2A_PORT` (defaults to `localhost:9002`, override via env or `--port`)
- Gradio UI: `9102` (override with `--ui-port`)
- Host Agent URL: `A2A_HOST` (defaults to `http://localhost:12000`, accepts empty string to disable)

Accurate estimates start with solid data—happy assessing! 🧮
