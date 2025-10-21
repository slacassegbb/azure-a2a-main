# Remote Agents (Overview)

This directory contains standalone agents that speak the A2A protocol and can self‑register with the Host Agent (backend). Each agent exposes an HTTP API (A2A server) and most optionally offer a Gradio UI for direct use.

## Connecting to the Host Agent
- Set `A2A_HOST` to the Host Agent URL (backend default: `http://localhost:12000`).
- On startup, agents attempt self‑registration; they’ll appear in the Host Agent’s Remote Agents list if reachable.
- Agents bind to `A2A_ENDPOINT:A2A_PORT`; override via env or CLI flags (see each agent’s README).

Common run commands (inside an agent folder):
```bash
uv sync
uv run .                 # start A2A server
uv run . --ui            # start A2A server + Gradio UI (if supported)
```

## Agents at a glance
| Agent | Purpose | Default A2A Port | Default UI Port | Notes |
|---|---|---:|---:|---|
| `azurefoundry_SN` | ServiceNow + Banking simulator: incidents, users, KB search, human escalation | 8000 | 8085 | Integrates with ServiceNow MCP (`MCP_SERVICENOW/`); update MCP URL in `foundry_agent.py` |
| `azurefoundry_legal` | Legal/compliance guidance: GDPR, SOX, CCPA; risk analysis; doc review; incidents | 8006 | 8095 | Web/file search for regulatory info |
| `azurefoundry_image_generator` | Text‑to‑image, edits, masked refinement, style grounding | 9010 | 9102 | Consumes file attachments; uses OpenAI image models |
| `azurefoundry_Deep_Search` | Deep search across knowledge docs (account, billing, fraud, tech support) | 8002 | 8087 | Knowledge search and guided procedures |
| `azurefoundry_classification` | Incident classification & triage; priority assessment; ServiceNow field mapping | 8001 | 8089 | Routes/triages incidents; UI for interactive runs |
| `azurefoundry_claims` | Insurance claims specialist; coverage, settlement, documentation | 9001 | 9101 | Multi‑line claims (auto, property, travel, health) |
| `azurefoundry_fraud` | Fraud analysis and response workflows | 9004 | 9104 | Detection, investigation, and reporting utilities |
| `azurefoundry_assessment` | Assessment workflows (evals, scoring, summaries) | 9002 | 9102 | Launch with `--ui` for the demo UI |
| `azurefoundry_branding` | Branding & content governance for copy, prompts, and visual direction | 9020 | 9120 | Grounds responses in `documents/company_branding.md` |
| `google_adk` | Google GenAI ADK example A2A agent | 8003 | — | Configure Google API key; no UI by default |

## Environment (common)
Set these in the agent shell or a `.env` file within the agent folder:
```bash
# A2A host (backend) for self‑registration
A2A_HOST=http://localhost:12000

# Where the agent binds and how it advertises itself
A2A_ENDPOINT=localhost
A2A_PORT=<port>
```

See each agent’s README for provider‑specific variables (e.g., Azure AI Foundry, ServiceNow MCP, Google ADK).
