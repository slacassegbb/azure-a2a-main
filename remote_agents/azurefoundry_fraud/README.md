# AI Foundry Fraud Intelligence Agent

An Azure AI Foundry agent specialized in detecting fraud across auto, property, travel, and health claims. The agent reads fraud playbooks to highlight red flags, organize evidence, and recommend escalation steps for investigators.

## Features
- 🕵️ **Multi-Line Fraud Insight** – Leverages `documents/` references (fraud_auto, fraud_property, fraud_travel, fraud_health, fraud_universal, fraud_procedures_faq) to ground findings.
- 🚨 **Red Flag Detection** – Maps claim facts to known schemes, anomaly patterns, and escalation triggers.
- 📚 **Evidence Documentation** – Summarizes supporting documents, data discrepancies, and follow-up actions.
- 🌐 **Dual Operation Modes** – Run as an A2A server on port `9004` or launch the Gradio UI on port `9104` for interactive investigations.
- 🤝 **Self-Registration** – Automatically registers with a host agent configured via `A2A_HOST` (defaults to `http://localhost:12000`).

## Project Structure
```
├── foundry_agent.py           # Azure AI Foundry fraud specialist implementation
├── foundry_agent_executor.py  # A2A executor with streaming support
├── __main__.py                # CLI entry point (A2A server + optional Gradio UI)
├── documents/                 # Fraud reference guides per domain
├── utils/self_registration.py # Host-agent registration helper
├── test_client.py             # Fraud-focused A2A client smoke test
├── test_bing_search.py        # Bing/web search integration test
├── test_self_registration.py  # Self-registration diagnostics
└── pyproject.toml             # Dependencies
```

## Quick Start
### 1. Environment Setup
```bash
cp .env.template .env  # if template available
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
# Hostname or base domain the agent binds to (defaults to localhost)
A2A_ENDPOINT=localhost

# Port for the agent's A2A API
A2A_PORT=9004

# Host agent URL for self-registration (empty string disables)
A2A_HOST=http://localhost:12000
```

### 4. Run the Agent
- **A2A server** (defaults to `A2A_ENDPOINT:A2A_PORT`, e.g. `http://localhost:9004`):
  ```bash
  uv run .
  ```
  Health check: `http://$A2A_ENDPOINT:$A2A_PORT/health`

- **Gradio UI + A2A server**:
  ```bash
  uv run . --ui
  ```
  UI: `http://localhost:9104`

- **Custom ports**:
  ```bash
  uv run . --ui --ui-port 9110 --port 9010
  ```

### 5. Self-Registration Check (optional)
With the host agent running (`demo/ui`), start the fraud agent and run `python test_self_registration.py` to confirm registration.

## Sample Prompts
- "Low-speed collision with high injury bills—what fraud indicators should I note?"
- "Home fire two months after coverage increase—summarize red flags and next steps."
- "Travel cancellation with questionable medical note—assess authenticity and evidence needs."
- "Provider billed 15 MRIs in one day—what actions should we take?"
- "Cluster of water backup claims using the same contractor—outline potential fraud ring signals."

## Testing Utilities
- `python test_client.py` – runs health check, card retrieval, and sample fraud conversations.
- `python test_bing_search.py` – validates Bing search integration for market data or risk research.
- `python test_self_registration.py` – confirms the agent can register with the host agent URL.

## Troubleshooting
- Verify Azure AI Foundry quotas (≥20k TPM) for uninterrupted streaming.
- Ensure environment variables are loaded before starting the agent.
- Check that all fraud reference documents exist in `documents/`; missing guides reduce accuracy.
- Use the Gradio console output to observe real-time fraud reasoning and tool calls.

## Defaults & Overrides
- A2A Server: `A2A_ENDPOINT:A2A_PORT` (defaults to `localhost:9004`, override via env or `--port`)
- Gradio UI: `9104` (override with `--ui-port`)
- Host Agent URL: `A2A_HOST` (defaults to `http://localhost:12000`, accepts empty string to disable)

Keep investigators ahead of fraud rings with timely, evidence-backed insights. 🕵️‍♂️
