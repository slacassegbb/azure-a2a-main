# AI Foundry Branding & Content Agent

An Azure AI Foundry agent built to keep every asset on-brand. The agent reads the Company Branding Guide (`documents/company_branding.md`) and turns briefs, drafts, and prompts into polished recommendations that respect color palette, tone, composition, and typography rules.

## Features
- 🎨 **Brand-Grounded Guidance** – Automatically uploads the branding guide and uses file search to cite palette, lighting, composition, and voice rules.
- 🗣️ **Voice & Messaging Support** – Generates copy, slogans, CTA variants, and channel adaptations that maintain the confident, forward-looking tone.
- 🖼️ **Visual Direction & Prompts** – Produces art direction notes and positive/negative prompts for generative tools aligned to brand colors and mood.
- ✅ **Compliance Reviews** – Audits supplied copy or concepts, flags off-brand elements, and provides corrective next steps.
- 🌐 **Dual Operation Modes** – Run as an A2A server on port `9033` or launch the optional Gradio UI on port `9120` for interactive reviews.
- 🤝 **Self-Registration** – Supports auto-registration with the host agent configured via `A2A_HOST` (defaults to `http://localhost:12000`).

## Project Structure
```
├── foundry_agent.py           # Azure AI Foundry branding agent implementation
├── foundry_agent_executor.py  # A2A executor with streaming result handling
├── __main__.py                # CLI entry (A2A server + optional Gradio UI)
├── documents/
│   └── company_branding.md    # Primary branding guideline for grounding
├── static/                    # UI assets
├── utils/self_registration.py # Host-agent registration helper (optional)
├── pyproject.toml             # Dependencies
└── uv.lock                    # Locked dependency graph
```

## Quick Start
### 1. Environment Setup
```bash
cp .env.template .env  # if a template is provided
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
A2A_PORT=9033

# Host agent URL for self-registration (empty string disables)
A2A_HOST=http://localhost:12000
```

### 4. Run the Agent
- **A2A server** (defaults to `A2A_ENDPOINT:A2A_PORT`, e.g. `http://localhost:9033`):
  ```bash
  uv run .
  ```
  Health check: `http://$A2A_ENDPOINT:$A2A_PORT/health`

- **Gradio UI + A2A server**:
  ```bash
  uv run . --ui
  ```
  UI: `http://localhost:9120`

- **Custom ports**:
  ```bash
  uv run . --ui --ui-port 9130 --port 9030
  ```

### 5. Self-Registration Check (optional)
Start the host agent (`demo/ui`) and run `python utils/self_registration.py` helpers or build your own check to confirm registration.

## Sample Prompts
- "Create LinkedIn carousel copy and image prompts for the innovation launch while citing the brand guide."
- "Review this webinar invite and adjust tone/CTA so it matches our branding."
- "Generate a Midjourney prompt (with negatives) for a futuristic workspace hero image in brand colors."
- "Summarize the key typography and composition rules we must follow for a product brochure."
- "Audit this video script for off-brand language and recommend fixes."

## Troubleshooting
- Ensure Azure AI Foundry TPM quota (≥20k TPM) is available for uninterrupted runs.
- Confirm environment variables are loaded in the working shell.
- Verify `documents/company_branding.md` is present; missing references reduce accuracy.
- Use the Gradio console output to view streaming tool-call diagnostics when debugging.

## Defaults & Overrides
- A2A Server: `A2A_ENDPOINT:A2A_PORT` (defaults to `localhost:9033`, override via env or `--port`)
- Gradio UI: `9120` (override with `--ui-port`)
- Host Agent URL: `A2A_HOST` (defaults to `http://localhost:12000`, accepts empty string to disable)

Consistent branding builds trust—ship confidently. ✨
