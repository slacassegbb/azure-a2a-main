# 🔧 Fixes Applied - Deployment Issues Resolved

## Problem Summary

The system was initially deployed with a **combined server architecture** where the backend tried to handle both API requests and WebSocket connections on the same port (12000). This caused:
- ❌ Slow performance due to CPU contention
- ❌ Timeouts when sending messages
- ❌ Complex troubleshooting

## Solution Implemented

Switched to **proper microservices architecture** with **3 separate servers**:

### 1. WebSocket Server (Port 8080)
- **Purpose:** Dedicated real-time event streaming
- **Dockerfile:** `backend/Dockerfile.websocket`
- **Container:** `websocket-uami`
- **Handles:** WebSocket connections from frontend, broadcasts events

### 2. Backend API (Port 12000)
- **Purpose:** Main business logic and Azure AI Foundry integration
- **Dockerfile:** `backend/Dockerfile`
- **Container:** `backend-uami`
- **Handles:** API requests, posts events to WebSocket server via HTTP

### 3. Frontend (Port 3000)
- **Purpose:** User interface
- **Dockerfile:** `frontend/Dockerfile`
- **Container:** `frontend-uami`
- **Connects to:** Backend for API, WebSocket server for real-time updates

## Files Modified

### 1. `deploy-azure.ps1` ✅ FIXED
**Changes:**
- Added WebSocket server deployment
- Builds 3 separate Docker images
- Configures backend with `WEBSOCKET_SERVER_URL` pointing to WebSocket server
- Configures frontend with both backend and WebSocket URLs
- Added managed identity setup
- All images built with `--platform linux/amd64`

### 2. `backend/Dockerfile.websocket` ✅ CREATED
**New file:**
- Dockerfile for WebSocket server
- Copies all backend code (needed for imports)
- Runs `create_websocket_app()` from `websocket_server.py`
- Exposes port 8080

### 3. `backend/backend_production.py` ✅ FIXED
**Changes:**
- Removed combined WebSocket endpoint (`@app.websocket("/events")`)
- Removed HTTP POST `/events` endpoint
- Removed `websocket_manager` import
- Backend now only handles API requests
- WebSocket functionality delegated to separate server

### 4. `DEPLOYMENT.md` ✅ UPDATED
**Changes:**
- Added architecture diagram showing 3 servers
- Updated deployment instructions
- Added troubleshooting for common issues:
  - Architecture mismatch errors
  - localhost URL problems
  - Permission denied errors
  - Image platform issues
- Updated all commands to reference correct container names

### 5. `DEPLOYMENT-CHECKLIST.md` ✅ CREATED
**New file:**
- Step-by-step deployment verification
- Common issues with quick fixes
- Post-deployment checklist
- Success criteria

## Key Configuration Changes

### Backend Environment Variables
```bash
WEBSOCKET_SERVER_URL=https://websocket-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=<your-endpoint>
AZURE_OPENAI_GPT_API_KEY=<your-key>
AZURE_OPENAI_EMBEDDINGS_KEY=<your-key>
A2A_HOST=FOUNDRY
VERBOSE_LOGGING=true
```

### Frontend Build Args
```bash
NEXT_PUBLIC_A2A_API_URL=https://backend-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io
NEXT_PUBLIC_WEBSOCKET_URL=wss://websocket-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io/events
NEXT_PUBLIC_DEV_MODE=false
```

## Docker Build Changes

### CRITICAL: Platform Specification
All Docker builds now use `--platform linux/amd64`:

```bash
docker buildx build --platform linux/amd64 -t image:tag . --load
```

This is **required** because:
- Azure Container Apps runs on amd64 nodes
- Mac M1/M2/M3 users build arm64 by default
- Wrong platform = `ImagePullUnauthorized` errors

## Architecture Flow

```
User Browser
    │
    ├──> [HTTPS] Backend API (12000)
    │    - Create conversation
    │    - Send message
    │    - Business logic
    │    │
    │    └──> [HTTP POST] WebSocket Server (8080)
    │         - Broadcast events
    │
    └──> [WSS] WebSocket Server (8080)
         - Real-time updates
         - Message streaming
```

## Testing Verification

✅ **Verified Working:**
1. Frontend loads and connects to WebSocket
2. Login works (test@example.com / password123)
3. Chat messages get responses
4. Real-time updates stream correctly
5. Backend creates Azure AI Foundry agents successfully
6. All 3 services show "Running" status

## Future Deployments

Use the updated `deploy-azure.ps1` script:

```powershell
./deploy-azure.ps1 `
    -ResourceGroup "rg-a2a-prod" `
    -Location "westus2" `
    -AcrName "a2awestuslab" `
    -Environment "env-a2a-final"
```

This will correctly deploy all 3 services with proper configuration.

## Lessons Learned

1. **Separate Concerns:** Don't combine API and WebSocket servers
2. **Platform Matters:** Always specify `--platform linux/amd64` for Azure
3. **Build-time vs Runtime:** Next.js env vars are baked in at build time
4. **Cache Busting:** Use timestamps or cache-bust args when rebuilding
5. **RBAC Propagation:** Wait 2-3 minutes after role assignments

## Status

✅ **DEPLOYMENT WORKING**
- All services deployed and running
- Chat functionality operational
- Real-time updates functioning
- Proper microservices architecture implemented

---

**Next Steps:** Use `DEPLOYMENT-CHECKLIST.md` for future deployments to avoid these issues.
