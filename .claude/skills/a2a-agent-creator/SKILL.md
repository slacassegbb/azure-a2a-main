---
name: a2a-agent-creator
description: Scaffold new A2A remote agents with Responses API, MCP support, Dockerfile, and auto-testing. Use when creating, adding, or scaffolding a new agent.
---

# A2A Agent Creator

Scaffold new remote agents following this project's Responses API + A2A SDK patterns.

## Workflow

Creating a new agent involves these steps:

1. Gather requirements from the user
2. Derive naming and check port availability
3. Create directory and copy static assets
4. Generate domain-specific files from code patterns
5. Verify correctness across files
6. Configure credentials and test the agent

### Step 1: Gather Requirements

Collect from the user:

| Field | Example | Required |
|---|---|---|
| Domain name | "Jira", "GitHub" | Yes |
| What the agent does | "Manages issues and sprints" | Yes |
| Skills (capabilities) | Customer mgmt, reports, etc. | Yes |
| Agent instructions | System prompt for the LLM | Yes |
| MCP enabled? | true/false | Yes |
| MCP server URL | env var + default URL | If MCP |
| MCP allowed tools | List of tool names | If MCP |
| Returns file artifacts? | true/false | Yes |
| Artifact type | image/png, application/pdf, etc. | If artifacts |
| Blob storage needed? | true/false (upload to Azure Blob) | If artifacts |

### Step 2: Derive Naming and Port

From domain name (e.g., "Jira"), derive:
- **Directory**: `remote_agents/azurefoundry_Jira`
- **Class**: `FoundryJiraAgent`
- **Display name**: `AI Foundry Jira Agent`
- **Package**: `aifoundry-jira-agent`
- **Executor import**: `from foundry_agent import FoundryJiraAgent`

Check **references/port-allocation.md** for existing assignments. Pick an unused port from the available ranges.

### Step 3: Create Directory and Copy Assets

Create the directory structure:
```
remote_agents/azurefoundry_{Domain}/
├── __main__.py
├── foundry_agent.py
├── foundry_agent_executor.py
├── pyproject.toml
├── Dockerfile
├── .env.example
├── .dockerignore
└── utils/
    ├── __init__.py
    └── self_registration.py
```

Copy these static files verbatim from this skill's `assets/` directory:
- `assets/utils/__init__.py` -> `utils/__init__.py`
- `assets/utils/self_registration.py` -> `utils/self_registration.py`
- `assets/dockerignore` -> `.dockerignore`

### Step 4: Generate Files from Code Patterns

Read **references/code-patterns.md** for complete templates. Replace all `{{PLACEHOLDER}}` markers.

**MCP vs non-MCP**: The code-patterns reference provides both variants for `foundry_agent.py`. Choose based on user input.

**Artifacts vs no artifacts**: If the agent returns files (images, PDFs, etc.), use the artifact-enabled variants for `foundry_agent.py` and `foundry_agent_executor.py`. These add blob storage upload, SAS URL generation, `_latest_artifacts` list, and `pop_latest_artifacts()` to the agent, and `FilePart(FileWithUri(...))` artifact return to the executor.

Generate in this order:
1. `foundry_agent.py` — Core logic. **Most customization** needed here: class name, MCP config, agent instructions, tool descriptions. If artifacts enabled, include blob upload helpers and `_latest_artifacts` pattern.
2. `foundry_agent_executor.py` — A2A bridge. Change only: import, class references, log messages. If artifacts enabled, use the artifact-aware executor variant that calls `pop_latest_artifacts()` and converts to `FilePart(FileWithUri(...))`.
3. `__main__.py` — Server, CLI, agent card. Define skills here (must appear in 3 places: `create_a2a_server()`, `launch_ui()`, and `main_async()`).
4. `pyproject.toml` — Package name and description. Add `azure-storage-blob>=12.19.0` if artifacts/blob storage enabled.
5. `Dockerfile` — Port default and comment.
6. `.env.example` — Add MCP env vars if applicable. Add blob storage env vars if artifacts enabled.

### Step 5: Verify

- [ ] Imports resolve: `foundry_agent_executor.py` imports the correct class from `foundry_agent.py`
- [ ] Class names match across all three Python files
- [ ] Port doesn't conflict with existing agents
- [ ] Skills are defined identically in all 3 locations in `__main__.py`
- [ ] Agent instructions include NEEDS_INPUT/HITL documentation
- [ ] MCP config present only if MCP is enabled
- [ ] Artifact support: `_latest_artifacts` + `pop_latest_artifacts()` in agent, artifact handling in executor (if applicable)
- [ ] Blob storage env vars in `.env.example` and `azure-storage-blob` in `pyproject.toml` (if artifacts enabled)
- [ ] `human_interaction` skill is always included

### Step 6: Configure & Test

Run the automated test script to validate the scaffolded agent end-to-end:

```bash
python3 .claude/skills/a2a-agent-creator/scripts/test_agent.py remote_agents/azurefoundry_{Domain} --port {PORT}
```

The script performs 8 checks:
1. **File structure** — All 9 required files present
2. **Python syntax** — `ast.parse` on all `.py` files
3. **Credentials** — Discovers Azure AI + blob storage creds from sibling agent `.env` files, creates `.env`
4. **Dependencies** — Runs `uv sync` to install packages
5. **Imports** — Verifies `FoundryAgentExecutor` and A2A SDK imports resolve
6. **Server endpoints** — Starts the server, tests `/health` (200) and `/.well-known/agent.json` (200, validates skills)
7. **Live A2A query** — Sends a real `message/send` request using the agent's skill examples, validates response text, checks for model refusals, and verifies artifact URIs are accessible (if returned)

If any check fails, fix the issue and re-run. All result lines must show `PASS`.

## Key Conventions

- Python >=3.12, `uv` for package management
- Streaming always enabled via Responses API (`stream=True`)
- Auth: `DefaultAzureCredential` + `get_bearer_token_provider`
- Endpoint conversion: `services.ai.azure.com` -> `openai.azure.com/openai/v1/`
- HITL: `NEEDS_INPUT` / `END_NEEDS_INPUT` blocks in agent instructions
- Token usage: append `DataPart(data={'type': 'token_usage', ...})` to responses
- Rate limiting: `Semaphore(3)`, 30 calls/min, exponential backoff on 429
- Self-registration: background daemon thread, 2s delay after server start
- Gradio UI: optional via `--ui` CLI flag, `--ui-port` for port
- Multi-turn: chain via `previous_response_id` keyed by session ID
