# AI Foundry Image Analysis Agent

An Azure AI Foundry–powered vision assistant that analyzes images to identify damage, detect objects, understand scenes, assess quality, and extract text using Azure OpenAI GPT-4o vision capabilities. It implements the A2A protocol so it can run alongside other agents and self‑register with a host orchestrator.

## Features
- 🚗 **Damage Assessment** – Identifies and describes visible damage in vehicles, properties, or objects with severity analysis.
- 🔍 **Object Detection** – Recognizes and catalogs all significant objects, vehicles, structures, or items in images.
- 🌄 **Scene Understanding** – Provides comprehensive descriptions of scenes, environments, contexts, and atmospheric conditions.
- ✅ **Quality Inspection** – Evaluates condition, maintenance state, and wear/tear of items or structures.
- 📝 **Text Extraction** – Reads and extracts visible text, labels, signs, license plates, VINs, and documents.
- 🤖 **Azure OpenAI GPT-4o Vision** – Powered by advanced computer vision AI for accurate, detailed analysis.
- 📎 **File Ingestion** – Accepts images via base64 encoding or URLs through A2A `FilePart` messages.
- 🗂️ **Reference Documents** – Can leverage documents for assessment guidelines and standards.
- 🔗 **A2A Integration** – Streams analysis results, returns structured insights, and self‑registers with the host agent.
- 🌐 **Dual Modes** – A2A API server (default `9066`) and optional Gradio UI (default `9110`).

## Project Structure
```
├── foundry_agent.py           # Core Azure AI Foundry image analysis logic with GPT-4o vision
├── foundry_agent_executor.py  # A2A executor with streaming and shared-thread execution
├── __main__.py                # CLI entry point (A2A server + optional Gradio UI)
├── utils/self_registration.py # Host-agent self-registration helper
├── documents/                 # Optional reference guidelines and assessment criteria
├── static/                    # UI assets (e.g., a2a.png)
└── pyproject.toml             # Dependencies
```

## Quick Start
### 1) Environment Setup
```bash
# Required Azure AI Foundry settings
export AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=your-project-endpoint
export AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=gpt-4o  # Must be a vision-capable model

# Optional: A2A host for self-registration
export A2A_HOST=http://localhost:12000

# Optional: override bind/advertised endpoint
export A2A_ENDPOINT=localhost    # hostname used in public URL
export A2A_PORT=9010             # A2A server port (defaults to 9010)
```

**Important**: Your `AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME` must be a vision-capable model like:
- `gpt-4o` (recommended)
- `gpt-4-turbo` with vision preview
- `gpt-4-vision-preview`

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
  UI: `http://localhost:9110` (default)  |  A2A API: `http://localhost:9010/`

- **Custom ports**
  ```bash
  uv run . --ui --ui-port 9140 --port 9035
  ```

### 4) Verify Self‑Registration (optional)
With the host agent running, start the Image Analysis Agent and confirm it appears in the host's Remote Agents list.

## Sample Analysis Requests
- "Analyze this vehicle damage photo and identify all visible issues."
- "What type of damage is visible in this property image?"
- "Identify all objects and safety hazards in this scene."
- "Extract and read the text visible on this license plate."
- "Assess the overall condition and maintenance state of this equipment."
- "Describe the environment, lighting, and context of this scene."

## Image Input Methods
The agent accepts images in multiple formats:
- **Base64-encoded images** via the A2A payload
- **Image URLs** (publicly accessible or with SAS tokens)
- **File attachments** through A2A `FilePart` messages

Images are automatically processed and analyzed using Azure OpenAI GPT-4o vision.

## Troubleshooting
- Ensure all required environment variables are set:
  - `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT`
  - `AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME` (must be a vision-capable model like `gpt-4o`)
- If the UI doesn't load, verify port `9110` or set `--ui-port`.
- If the A2A server fails to bind, verify port `9010` or set `A2A_PORT`/`--port`.
- If self‑registration fails, confirm the host URL in `A2A_HOST` and that the host is reachable.
- If image analysis fails, check that your model deployment supports vision:
  - In Azure AI Foundry, verify your model is `gpt-4o`, `gpt-4-turbo`, or `gpt-4-vision-preview`
  - Images must be attached to messages via the A2A protocol (as FilePart with URI or base64)

## Default Ports & Environment Overrides
- A2A Server: `A2A_ENDPOINT:A2A_PORT` (defaults to `localhost:9010`, override via env or `--port`)
- Gradio UI: `9110` (override with `--ui-port`)
- Host Agent URL: `A2A_HOST` (defaults to `http://localhost:12000`, accepts empty string to disable)

Happy analyzing! 🔍
