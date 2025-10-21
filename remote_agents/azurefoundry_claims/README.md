# AI Foundry Claims Specialist Agent

An Azure AI Foundry agent tailored for multi-line insurance claims support. This agent validates coverage, estimates settlements, outlines documentation requirements, and surfaces compliance considerations across auto, property, travel, and health lines. It reuses the A2A framework so it can run locally alongside other agents and self-register with a host agent.

## Features
- 🛡️ **Multi-Line Expertise** – Draws on `documents/` playbooks (auto, home, travel, health, universal, regulatory) to answer claims questions.
- 💵 **Settlement Guidance** – Calculates deductibles, limits, depreciation, coinsurance, and net payable amounts for each claim scenario.
- 📑 **Documentation Checklists** – Lists required proof-of-loss items, forms, and follow-up steps to keep adjusters productive.
- ⚖️ **Compliance & Fraud Signals** – Highlights regulatory timelines, escalation triggers, and fraud indicators from the reference guides.
- 🌐 **Dual Operation Modes** – Run as an A2A server (port `9001`) or launch the Gradio UI (port `9101`) for direct conversations.
- 🤝 **Self-Registration** – Automatically registers with the host agent configured via `A2A_HOST` (defaults to `http://localhost:12000`).

## Project Structure
```
├── foundry_agent.py           # Azure AI Foundry claims specialist implementation
├── foundry_agent_executor.py  # A2A executor with rate limiting and streaming support
├── __main__.py                # CLI entry point (A2A server + optional Gradio UI)
├── documents/                 # Claims reference guides used for file search
├── utils/self_registration.py # Host-agent self-registration helper
├── test_client.py             # Claims-focused A2A client smoke test
├── test_bing_search.py        # Bing/web search integration test
├── test_self_registration.py  # Self-registration diagnostics
└── pyproject.toml             # Dependencies
```

## Quick Start
### 1. Environment Setup
```bash
# Copy and edit the environment template if needed
cp .env.template .env  # if the template exists in the repo root
```

### 2. Install Dependencies
```bash
uv sync
```

### 3. Configure Azure AI Foundry
Set the required variables (in `.env` or your shell):
```env
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=your-project-endpoint
AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=your-model-deployment
```

### 3a. Configure A2A Server
```env
# Hostname or base domain the agent binds to (defaults to localhost)
A2A_ENDPOINT=localhost

# Port for the agent's A2A API
A2A_PORT=9001

# Host agent URL for self-registration (empty string disables)
A2A_HOST=http://localhost:12000
```

### 4. Run the Agent
- **A2A server only** (defaults to `A2A_ENDPOINT:A2A_PORT`, e.g. `http://localhost:9001`)
  ```bash
  uv run .
  ```
  Health check: `http://$A2A_ENDPOINT:$A2A_PORT/health`

- **Gradio UI + A2A server**
  ```bash
  uv run . --ui
  ```
  UI: `http://localhost:9101`

- **Custom ports**
  ```bash
  uv run . --ui --ui-port 9105 --port 9005
  ```

### 5. Verify Self-Registration (optional)
With the host agent running (`demo/ui`), start the claims agent and check the Remote Agents tab. Use `python test_self_registration.py` to validate registration independently.

## Sample Questions to Try
- "My car was declared a total loss after a collision—how much will the payout be after deductible and salvage?"
- "A pipe burst in my basement. What documentation and mitigation steps do you need?"
- "Can travel insurance reimburse a $3,000 trip canceled due to hospitalization?"
- "What will I owe for a $12,000 inpatient surgery with a $1,500 deductible and 20% coinsurance?"
- "We suspect fraud on a homeowners claim—what compliance steps should we follow?"

## Testing Utilities
- `python test_client.py` – exercises health check, card retrieval, and messaging workflows against the running agent.
- `python test_bing_search.py` – quick check that web/Bing search is available when environment quotas allow it.
- `python test_self_registration.py` – confirms the agent can register with the host agent endpoint specified by `A2A_HOST` (falls back to `A2A_HOST_AGENT_URL`).

## Troubleshooting
- Ensure Azure AI Foundry quotas (TPM) are sufficient; agents typically require ≥20k TPM for smooth operation.
- Confirm environment variables are loaded in the shell running the agent.
- If Bing search or file search fails, verify the relevant services are enabled and the supporting docs exist in `documents/`.
- Use the Gradio UI console output for detailed streaming and tool-call diagnostics.

## Default Ports & Environment Overrides
- A2A Server: `A2A_ENDPOINT:A2A_PORT` (defaults to `localhost:9001`, override via env or `--port`)
- Gradio UI: `9101` (override with `--ui-port`)
- Host Agent URL: `A2A_HOST` (defaults to `http://localhost:12000`, accepts empty string to disable)

Happy adjusting! 🧾
