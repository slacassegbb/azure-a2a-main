# Project: Azure A2A Multi-Agent Platform

## Overview
A multi-agent orchestration platform using the A2A (Agent-to-Agent) protocol. A Next.js frontend connects to a Python/FastAPI backend that orchestrates remote agents via Azure AI Foundry. Agents communicate through A2A protocol with SSE streaming and WebSocket real-time updates.

## Architecture

### Services (Azure Container Apps)
- **Frontend** (`frontend-uami`): Next.js 14, React, Tailwind, shadcn/ui
- **Backend** (`backend-uami`): Python FastAPI, orchestrates agents via Azure AI Foundry
- **WebSocket** (`websocket-uami`): Real-time event streaming to frontend
- **Remote Agents**: Individual containers per agent (Email, Teams, QuickBooks, etc.)

### Production URLs
- Frontend: `https://frontend-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io`
- Backend: `https://backend-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io`
- WebSocket: `wss://websocket-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io/events`

### Key Infrastructure
- **Registry**: `a2awestuslab.azurecr.io`
- **Resource Group**: `rg-a2a-prod`
- **Region**: `westus2`
- **Database**: PostgreSQL (via `DATABASE_URL` env var), fallback to local JSON
- **Memory/Search**: Azure AI Search for document indexing and agent memory
- **LLM**: Azure OpenAI gpt-4o (East US)

## Project Structure

```
backend/
  backend_production.py          # Main FastAPI app entry point
  hosts/multiagent/
    core/
      workflow_orchestration.py   # Core orchestration engine (step execution, planning, branching)
      agent_registry.py          # Agent discovery and registration
      azure_clients.py           # Azure OpenAI/AI Foundry client setup
      event_emitters.py          # WebSocket event emission helpers
      memory_operations.py       # Azure Search memory operations
      streaming_handlers.py      # SSE stream processing from agents
  database/                      # PostgreSQL schemas and migrations

frontend/
  app/                           # Next.js app router pages
  components/
    chat-panel.tsx               # Main chat interface (large file, ~4000 lines)
    visual-workflow-designer.tsx  # Drag-and-drop workflow builder (canvas-based)
    inference-steps.tsx           # Workflow step rendering in chat
    agent-network.tsx             # Agent sidebar and availability checks
    workflow-catalog.tsx          # Saved workflow management
  lib/
    workflow-api.ts              # Backend API calls for workflows
    agent-colors.ts              # Agent color theming

remote_agents/
  azurefoundry_*/                # Individual agent implementations
  deploy-remote-agent.sh         # Agent deployment script
```

## Debugging

### Backend Logs (Azure Container Apps)
```bash
# Recent console logs
az containerapp logs show --name backend-uami --resource-group rg-a2a-prod --type console --tail 100

# Filter for errors
az containerapp logs show --name backend-uami --resource-group rg-a2a-prod --type console --tail 300 | grep -i -E "error|exception|traceback|fail"

# Filter for specific agent/feature
az containerapp logs show --name backend-uami --resource-group rg-a2a-prod --type console --tail 300 | grep -i "EVALUATE"

# System logs (container startup, probes, crashes)
az containerapp logs show --name backend-uami --resource-group rg-a2a-prod --type system --tail 30

# Check revision health
az containerapp revision list --name backend-uami --resource-group rg-a2a-prod -o table
```

### WebSocket Server Logs
```bash
az containerapp logs show --name websocket-uami --resource-group rg-a2a-prod --type console --tail 100
```

### Remote Agent Logs
```bash
# Replace AGENT_NAME with the container app name (e.g., email-agent-uami)
az containerapp logs show --name AGENT_NAME --resource-group rg-a2a-prod --type console --tail 100
```

### Database (PostgreSQL)
```bash
# Connect via psql (get DATABASE_URL from Azure secrets)
# Tables: users, workflows, agents, agent_files, chat_history, scheduled_workflows, schedule_run_history
# Workflows stored with JSONB columns for steps and connections
```

### GitHub Actions Deployment
```bash
# Check deployment status
gh run list --workflow=deploy-azure.yml --limit 5

# View specific run logs
gh run view <run-id> --log
```

## Deployment

### CI/CD
- GitHub Actions: `.github/workflows/deploy-azure.yml`
- Auto-deploys on push to: `main`, `feature/multi-tenancy`, `feature/postgresql-migration`, `feature/evaluation-step`
- Builds Docker images, pushes to ACR, updates Container Apps
- Frontend, backend, and websocket deploy independently based on changed paths

### Manual Deploy
```bash
# Restart a container app (no rebuild)
az containerapp restart --name backend-uami --resource-group rg-a2a-prod
```

### Remote Agent Deploy
```bash
# Deploy a remote agent from remote_agents/ directory
./deploy-remote-agent.sh azurefoundry_email
```

## Key Patterns

### Workflow Orchestration Flow
1. Frontend visual designer creates workflow steps and connections
2. `generateWorkflowTextFromRefs()` converts to text format for the LLM
3. Backend orchestrator uses structured output (gpt-4o) to plan next steps
4. Tasks dispatched to remote agents via A2A protocol with SSE streaming
5. Results emitted via WebSocket events to frontend for real-time rendering

### Evaluation Steps (Branching)
- `[EVALUATE]` steps are handled by the host orchestrator LLM, not remote agents
- Returns TRUE/FALSE with reasoning for conditional branching
- Frontend renders as "Evaluate" agent card with step number and results
- Searches Azure Search memory for extracted document content before evaluating

### Event Flow (Backend to Frontend)
- Backend emits `remote_agent_activity` events via WebSocket
- Events have `eventType`: `agent_start`, `agent_output`, `agent_complete`, `agent_error`, `phase`, `reasoning`
- `foundry-host-agent` events go to orchestrator section in UI
- Named agent events render as agent cards with step numbers extracted from `[Step X]` in content

### Document Extraction
- When agents return files, orchestrator extracts content (PDF, images)
- Extracted content stored in Azure Search memory as `DocumentProcessor` entries
- Subsequent steps can search memory for this content

## Common Issues
- **Rate limiting**: Azure OpenAI S0 tier has token-per-minute limits. Wait 20s between runs or increase quota at https://aka.ms/oai/quotaincrease
- **Startup probe failures**: Backend takes ~30-40s to start. Probe failures during startup are normal and resolve automatically.
- **Agent "not found"**: Check agent registry sync. EVALUATE is not a remote agent and should be excluded from availability checks.
- **Missing document content**: Document extraction stores in Azure Search memory, not in `previous_task_outputs`. Steps needing document content must search memory.
