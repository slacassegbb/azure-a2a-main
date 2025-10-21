## A2A Backend (FastAPI + WebSocket)

The backend is a FastAPI service that powers the Agent‑to‑Agent (A2A) platform. It runs the Host Agent/orchestrator that adapts Azure AI Foundry/ADK agents to the open A2A protocol—brokering conversations, routing messages, maintaining the agent registry, and streaming real‑time events over WebSocket. As the central coordinator, the Host Agent can delegate tasks to remote A2A‑capable agents and aggregate their results. It also provides authentication, file/voice ingestion with a document processor, optional vector memory, and telemetry hooks for operations.

This service is intended to run locally for development and can be deployed to container environments. It automatically reads environment variables from the project root `.env` file.

### Key components
- **FastAPI API**: Main HTTP service (default `:12000`).
- **WebSocket server**: Background service streaming events to the UI (default `ws://localhost:8080`).
- **Conversation server**: Implements A2A protocol endpoints and routes messages to host managers (Foundry/ADK).
- **Agent registry**: CRUD API backed by `backend/data/agent_registry.json`.
- **Auth service**: Simple JWT auth with users stored in `backend/data/users.json` (auto‑created with sample users).
- **Uploads**: File uploads saved under `backend/uploads/`; voice uploads saved to `backend/voice_recordings/` and optionally transcribed.
- **Document processor**: Converts images/PDF/Office/text to markdown; audio/video analyzed via Azure Content Understanding using templates in `hosts/multiagent/analyzer_templates/`.
- **Memory service**: Optional Azure AI Search vector memory storing interactions with embeddings (`AZURE_SEARCH_*`, `AZURE_OPENAI_EMBEDDINGS_*`).
- **Telemetry**: OpenTelemetry integration with Azure Monitor/Application Insights (enable via `APPLICATIONINSIGHTS_CONNECTION_STRING`).

---

## Prerequisites
- Python 3.10+
- macOS/Linux/WSL (Windows supported; some paths differ)

If you prefer using the provided virtual environment, the top‑level README shows:

```bash
cd backend
source venv/bin/activate
python -m pip install -r requirements.txt
```

Alternatively, create your own venv:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Environment configuration (.env at repo root)
The backend loads environment variables from the project root `.env`:

```text
<repo-root>/.env
```

Minimal local setup (safe defaults exist if omitted):

```bash
# Core service
SECRET_KEY=change-me                # Set a strong key for JWTs
A2A_HOST=FOUNDRY                   # FOUNDRY (default) or ADK
A2A_UI_HOST=0.0.0.0                # Bind address for FastAPI
A2A_UI_PORT=12000                  # FastAPI port
WEBSOCKET_SERVER_URL=http://localhost:8080  # UI connects here; server starts on :8080

# Azure Content Understanding (used for voice transcription)
AZURE_CONTENT_UNDERSTANDING_ENDPOINT=<your-endpoint>
AZURE_CONTENT_UNDERSTANDING_API_VERSION=2024-12-01-preview

# If using Azure AI Foundry Host (FOUNDRY)
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=<your-project-endpoint>
AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=<your-deployment-name>

# Optional: Vector memory (Azure AI Search + embeddings)
AZURE_SEARCH_SERVICE_ENDPOINT=<your-search-endpoint>
AZURE_SEARCH_ADMIN_KEY=<your-search-admin-key>
AZURE_SEARCH_VECTOR_DIMENSION=1536
AZURE_SEARCH_INDEX_NAME=a2a-agent-interactions
AZURE_SEARCH_VECTOR_PROFILE=a2a-vector-profile
AZURE_SEARCH_VECTOR_ALGORITHM=a2a-hnsw-config
AZURE_OPENAI_EMBEDDINGS_ENDPOINT=<your-aoai-endpoint>
AZURE_OPENAI_EMBEDDINGS_KEY=<your-aoai-key>
AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT=<your-embedding-deployment>

# Document processor (images/docs to markdown; audio/video via Content Understanding)
# For image/PDF/doc processing to markdown using Azure OpenAI (see doc2md_utils)
AZURE_OPENAI_GPT_API_BASE=<your-foundry-project-base>   # e.g. https://<host>/api/projects/<project>
AZURE_OPENAI_GPT_API_KEY=<your-foundry-api-key>
AZURE_OPENAI_GPT_API_VERSION=2024-02-01-preview        # or your deployment version
AZURE_OPENAI_GPT_DEPLOYMENT=<your-gpt-deployment-name>  # e.g. gpt-4o

# Optional: Azure Blob Storage for file handling
AZURE_STORAGE_CONNECTION_STRING=<connection-string>
AZURE_STORAGE_ACCOUNT_NAME=<account-name>
AZURE_BLOB_CONTAINER=a2a-files

# Telemetry (Azure Monitor / Application Insights)
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=...;IngestionEndpoint=...

# If using Google ADK instead of Foundry
GOOGLE_API_KEY=<your-google-genai-key>
GOOGLE_GENAI_USE_VERTEXAI=FALSE   # or TRUE if using Vertex AI
```

Notes:
- The code will fall back to sensible defaults if a variable is not set.
- The WebSocket server is started on `localhost:8080` by the backend; ensure that port is free.
- For production, set a strong `SECRET_KEY` and restrict CORS as needed.

---

## Install dependencies
```bash
cd backend
pip install -r requirements.txt
```

Requirements include `fastapi`, `uvicorn`, `httpx`, `pydantic`, Azure SDKs, `a2a-sdk`, and optional `google-adk`.

---

## Run the backend
```bash
cd backend
python backend_production.py
```

On start, the service will:
- Load `.env` from the repo root
- Ensure `backend/data/` and `backend/uploads/` exist
- Start the internal WebSocket server on `ws://localhost:8080/events`
- Register conversation and agent routes

You should see logs like:
- API: `http://0.0.0.0:12000` (configurable via `A2A_UI_HOST`/`A2A_UI_PORT`)
- Docs: `http://<host>:12000/docs`
- Health: `http://<host>:12000/health`

---

## Endpoints overview

### Health & root
- `GET /` — service info and pointers
- `GET /health` — health probe
- `GET /docs` — OpenAPI UI

### Authentication (file‑backed JWT)
- `POST /api/auth/login` — returns JWT
- `POST /api/auth/register` — create a new user
- `GET /api/auth/me` — user from token
- `GET /api/auth/users` — all users
- `GET /api/auth/active-users` — currently connected users (via WebSocket auth)

User storage lives in `backend/data/users.json`. If missing, it is auto‑created with sample users (`simon@example.com / simon123`, etc.). Change `SECRET_KEY` and replace users for real deployments.

### Agent registry
- `GET /api/agents` — list
- `POST /api/agents` — add
- `GET /api/agents/{agent_name}` — get
- `PUT /api/agents/{agent_name}` — update
- `DELETE /api/agents/{agent_name}` — remove
- `GET /api/agents/search?query=&tags=` — search
- `GET /api/agents/health/{agent_url}` — probe remote agent

### Conversations & messages (A2A)
Registered by the conversation server (examples):
- `POST /conversation/create`
- `POST /message/send`
- `POST /message/list`
- `POST /events/get`
- `POST /task/list`
- `POST /agent/register`
- `POST /agent/register-by-address`
- `POST /agent/self-register`
- `GET  /agent/list`

### File & voice uploads
- `POST /upload` — store file in `backend/uploads/`
- `POST /upload-voice` — save WAV in `backend/voice_recordings/` and attempt transcription via Azure Content Understanding

### Local agent start (locked down)
- `POST /start-agent` — executes a whitelisted local agent (currently `classification-triage`) with provided command/args; validates working directory.

### WebSocket events
- Server binds to `ws://localhost:8080/events`
- Broadcasts agent registry, chat events, inference events, and auth/user updates to connected clients

---

## Document processor
The document processor ingests files and produces markdown/text suitable for A2A. It supports:
- Images (extracts text and chart/diagram content to markdown)
- PDF/Office docs (converts to PDF, extracts pages to images, then to markdown)
- Text/JSON (reads and normalizes)
- Audio/Video (via Azure Content Understanding analyzers)

Implementation:
- Module: `backend/hosts/multiagent/a2a_document_processor.py`
- Analyzer templates: `backend/hosts/multiagent/analyzer_templates/*.json`
- Utilities: `backend/hosts/multiagent/doc2md_utils.py`
- Outputs go under `backend/images/`, `backend/markdown/`, `backend/pdf/`

Configure for image/doc → markdown:
- Set `AZURE_OPENAI_GPT_API_BASE`, `AZURE_OPENAI_GPT_API_KEY`, `AZURE_OPENAI_GPT_API_VERSION`, `AZURE_OPENAI_GPT_DEPLOYMENT` in `.env`.
- For Office file conversion, install LibreOffice (macOS default path: `/Applications/LibreOffice.app/Contents/MacOS/soffice`).

Configure for audio/video transcription/summarization:
- Set `AZURE_CONTENT_UNDERSTANDING_ENDPOINT` (or `AZURE_AI_SERVICE_ENDPOINT`) and optionally `AZURE_CONTENT_UNDERSTANDING_API_VERSION`.
- Endpoint used by `AzureContentUnderstandingClient` with managed identity by default.

How it’s used by the API:
- `POST /upload-voice` saves a WAV and calls `process_audio(...)` to produce a transcript.
- Foundry host also calls the processor when handling file parts in conversations.

---

## Memory service (Vector memory on Azure AI Search)
The A2A memory service stores and retrieves interaction data to support similarity search and context carry‑over.

Implementation:
- Module: `backend/hosts/multiagent/a2a_memory_service.py`
- Index name: `AZURE_SEARCH_INDEX_NAME` (default `a2a-agent-interactions`)
- Vector dimension: `AZURE_SEARCH_VECTOR_DIMENSION` (must match your embedding model)
- Embeddings: `AZURE_OPENAI_EMBEDDINGS_*` (endpoint, key, deployment)

Enable by setting:
- `AZURE_SEARCH_SERVICE_ENDPOINT`, `AZURE_SEARCH_ADMIN_KEY`
- Optionally `AZURE_OPENAI_EMBEDDINGS_*` for vector embeddings

Operations:
- On first run, creates/validates the index (profiles/algorithms configurable via env).
- Conversations store interactions automatically when enabled.
- `POST /clear-memory` clears the index via the Foundry host manager for fresh testing.
- If Azure Search env is missing, the memory service is disabled gracefully.

---

## Telemetry (Azure Monitor / OpenTelemetry)
Tracing is wired in the Foundry host using OpenTelemetry. If `APPLICATIONINSIGHTS_CONNECTION_STRING` is set, traces/metrics/logs are sent to Azure Monitor.

Implementation:
- `backend/hosts/multiagent/foundry_agent_a2a.py` initializes telemetry via `configure_azure_monitor(...)` and uses `opentelemetry.trace`.
- Python logging is used throughout modules; logs can be collected by your runtime as needed.

To enable:
- Set `APPLICATIONINSIGHTS_CONNECTION_STRING` in `.env`.
- Ensure outbound access to Azure Monitor ingestion endpoints.

What you get:
- Request/processing spans around message handling and agent operations
- Useful debug logging around agent registry sync, health checks, and message flow

---

## Host managers
The conversation server selects a host manager via `A2A_HOST`:
- **FOUNDRY** (default): integrates with Azure AI Foundry project (`AZURE_AI_FOUNDRY_PROJECT_ENDPOINT`, `AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME`).
- **ADK**: Google GenAI ADK (`GOOGLE_API_KEY`, optionally `GOOGLE_GENAI_USE_VERTEXAI=TRUE`).

When using memory/indexing, configure Azure AI Search and embeddings (see `.env` section).

---

## Troubleshooting
- Port 8080 already in use: stop the conflicting service. The WebSocket server currently binds to `localhost:8080`.
- Cannot access docs/health: verify `A2A_UI_HOST`/`A2A_UI_PORT` and firewall rules.
- Voice transcription errors: ensure `AZURE_CONTENT_UNDERSTANDING_ENDPOINT` is set and audio is valid WAV.
- Auth issues: set a strong `SECRET_KEY`; delete `backend/data/users.json` to regenerate sample users in dev.
- Agent health appears offline: endpoints must expose `/health`; network timeouts are limited.

---

## Useful paths
- `backend/backend_production.py` — entrypoint
- `backend/service/server/server.py` — conversation and A2A routes
- `backend/service/websocket_server.py` — WebSocket server
- `backend/service/websocket_streamer.py` — WebSocket streaming client
- `backend/data/agent_registry.json` — agent registry storage
- `backend/data/users.json` — user store (auto‑created)
- `backend/uploads/` — uploaded files

