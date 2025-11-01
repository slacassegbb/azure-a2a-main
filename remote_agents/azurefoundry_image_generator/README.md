# AI Foundry Image Generator Agent

An Azure AI Foundry–powered creative assistant that turns natural‑language prompts into polished image briefs and renders. It implements the A2A protocol so it can run alongside other agents and self‑register with a host orchestrator.

## Features
- 🎨 **Text‑to‑Image** – Generates images from prompts using OpenAI image models (e.g., `gpt-image-1`, `gpt-image-1-mini`).
- 🖼️ **Image‑to‑Image & Refinement** – Accepts prior artifacts or `image_url` to refine/iterate on an existing image.
- 🩹 **Masked Editing** – Applies edits within a supplied `mask_url`/mask attachment.
- 🧵 **Batch & Size Control** – Supports `n` (1‑4) images per call and `size` (e.g., `1024x1024`).
- 🎛️ **Style & Fidelity** – Optional `style` guidance and `input_fidelity` override for edit strength.
- 📎 **File Attachments** – Consumes A2A `FilePart` URIs (base image/mask) and normalizes them for edits.
- 🗂️ **Style Grounding via File Search** – Builds a shared vector store of brand/style documents for guided prompts.
- 🔗 **A2A Integration** – Streams progress/results, returns tool outputs, and self‑registers with the host agent.
- 🌐 **Dual Modes** – A2A API server (default `9010`) and optional Gradio UI (default `9166`).

## Project Structure
```
├── foundry_agent.py           # Core Azure AI Foundry image generation logic
├── foundry_agent_executor.py  # A2A executor with streaming and shared-thread execution
├── __main__.py                # CLI entry point (A2A server + optional Gradio UI)
├── utils/self_registration.py # Host-agent self-registration helper
├── documents/                 # Optional reference material
├── static/                    # UI assets (e.g., a2a.png)
└── pyproject.toml             # Dependencies
```

## Quick Start
### 1) Environment Setup
```bash
# Required Azure AI Foundry settings
export AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=your-project-endpoint
export AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=your-model-deployment

# Optional: A2A host for self-registration
export A2A_HOST=http://localhost:12000

# Optional: override bind/advertised endpoint
export A2A_ENDPOINT=localhost    # hostname used in public URL
export A2A_PORT=9066             # A2A server port (defaults to 9066)
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
  UI: `http://localhost:9166` (default)  |  A2A API: `http://localhost:9066/`

- **Custom ports**
  ```bash
  uv run . --ui --ui-port 9110 --port 9015
  ```

### 4) Verify Self‑Registration (optional)
With the host agent running, start the Image Generator and confirm it appears in the host’s Remote Agents list.

## Sample Prompts
- "Generate a cinematic cyberpunk skyline at dusk with neon reflections."
- "Create a watercolor illustration of a fox in a forest wearing a scarf."
- "Studio hero shot of a matte black smartwatch on marble, soft morning light."
- "Low‑poly desert landscape for a mobile game loading screen."

## Optional Storage
The agent can save artifacts to Azure Blob Storage (see `foundry_agent.py`). Configure via:
```bash
export AZURE_BLOB_CONTAINER=a2a-files
# plus any required storage credentials as used by your environment
```

## Troubleshooting
- Ensure `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` and `AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME` are set.
- If the UI doesn't load, verify port `9166` or set `--ui-port`.
- If the A2A server fails to bind, verify port `9066` or set `A2A_PORT`/`--port`.
- If self‑registration fails, confirm the host URL in `A2A_HOST` and that the host is reachable.

## Default Ports & Environment Overrides
- A2A Server: `A2A_ENDPOINT:A2A_PORT` (defaults to `localhost:9066`, override via env or `--port`)
- Gradio UI: `9166` (override with `--ui-port`)
- Host Agent URL: `A2A_HOST` (defaults to `http://localhost:12000`, accepts empty string to disable)

Happy generating! 🖼️
