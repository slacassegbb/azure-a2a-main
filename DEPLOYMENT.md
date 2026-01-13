# A2A Multi-Agent System - Complete Deployment Guide

**Status:** ✅ **FULLY OPERATIONAL**  
**Last Updated:** January 13, 2026

This guide contains everything you need to deploy and manage your A2A multi-agent system on Azure Container Apps.

---

## 📋 Table of Contents

1. [Quick Start](#quick-start)
2. [Prerequisites](#prerequisites)
3. [Architecture Overview](#architecture-overview)
4. [Deployment Steps](#deployment-steps)
5. [Environment Variables](#environment-variables)
6. [Common Operations](#common-operations)
7. [Troubleshooting](#troubleshooting)
8. [Lessons Learned](#lessons-learned)

---

## 🚀 Quick Start

### Deploy Main System (Frontend + Backend + WebSocket)

```powershell
.\deploy-azure.ps1 `
    -ResourceGroup "rg-a2a-prod" `
    -Location "westus2" `
    -AcrName "a2awestuslab" `
    -Environment "env-a2a-final"
```

**Time:** ~15-20 minutes (first deployment)

### Deploy Remote Agent

```powershell
.\deploy-remote-agent.ps1 `
    -AgentName "azurefoundry_branding" `
    -Port 9000 `
    -ResourceGroup "rg-a2a-prod" `
    -AcrName "a2awestuslab" `
    -Environment "env-a2a-final"
```

**Time:** ~5-10 minutes per agent

---

## 📦 Prerequisites

### Required Tools

1. **Azure CLI**
   ```powershell
   # Check if installed
   az --version
   
   # Login
   az login
   ```

2. **Docker Desktop**
   ```powershell
   # Check if installed and running
   docker --version
   docker info
   ```

3. **PowerShell** (Windows) or **pwsh** (Mac/Linux)

### Azure Resources

- **Subscription:** Active Azure subscription
- **Resource Group:** Will be created if doesn't exist
- **ACR:** `a2awestuslab.azurecr.io` (correct ACR)
- **Managed Identity:** Created automatically for RBAC

### Required Information

Before deploying, have these ready:

1. **Azure AI Foundry Project Endpoint**
   - Example: `https://simonfoundry.services.ai.azure.com/api/projects/proj-default`

2. **Azure AI Model Deployment Name**
   - Example: `gpt-4o`

3. **Azure OpenAI Configuration**
   - API Base URL
   - API Key
   - Deployment Name
   - Embeddings Endpoint
   - Embeddings Key

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Azure Container Apps                    │
│                                                               │
│  ┌──────────────┐         ┌───────────────┐                │
│  │  Frontend    │◄───────►│  WebSocket    │                │
│  │  (Next.js)   │         │  Server       │                │
│  │  Port 3000   │         │  Port 8080    │                │
│  └──────────────┘         └───────────────┘                │
│         │                         │                          │
│         └──────────┬──────────────┘                          │
│                    │                                         │
│                    ▼                                         │
│          ┌──────────────────┐                               │
│          │  Backend API     │                               │
│          │  Port 12000      │                               │
│          └──────────────────┘                               │
│                    │                                         │
│                    ▼                                         │
│          ┌──────────────────┐                               │
│          │  Remote Agent    │                               │
│          │  Port 9000+      │                               │
│          └──────────────────┘                               │
└─────────────────────────────────────────────────────────────┘
```

### Communication Flow

1. **Frontend** ↔ **WebSocket** (real-time events via WebSocket)
2. **Frontend** → **Backend** (API calls via HTTPS)
3. **Backend** → **WebSocket** (trigger immediate sync via HTTP POST)
4. **Backend** ↔ **Remote Agent** (A2A protocol via HTTPS)
5. **Remote Agent** → **Backend** (self-registration on startup)
6. **WebSocket** → **Backend** (fetch agent registry every 15 seconds)

### Key Features

- ✅ **Instant Agent Registration:** 1-2 seconds (not 15!)
- ✅ **Real-time Updates:** WebSocket broadcasting to all clients
- ✅ **Managed Identity:** No keys/secrets for Azure authentication
- ✅ **Microservices:** Each component scales independently
- ✅ **Platform Optimized:** Built for linux/amd64 (Azure)

---

## 🚀 Deployment Steps

### Step 1: Deploy Main System

This deploys Frontend, Backend, and WebSocket servers.

```powershell
cd /path/to/sl-a2a-main2

.\deploy-azure.ps1 `
    -ResourceGroup "rg-a2a-prod" `
    -Location "westus2" `
    -AcrName "a2awestuslab" `
    -Environment "env-a2a-final"
```

**What it does:**
1. Creates resource group (if needed)
2. Creates ACR (if needed)
3. Creates Managed Identity with AcrPull role
4. Builds 3 Docker images for linux/amd64:
   - WebSocket server
   - Backend API
   - Frontend (rebuilt with correct URLs after getting FQDNs)
5. Pushes images to ACR
6. Creates Container Apps environment
7. Deploys WebSocket server (port 8080)
8. Deploys Backend API (port 12000)
9. Configures WebSocket with backend URL
10. Rebuilds and deploys Frontend with correct URLs

**Expected Output:**
```
✅ Deployment Complete!

Your services are available at:
  Frontend:   https://frontend-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io
  Backend:    https://backend-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io
  WebSocket:  wss://websocket-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io/events

Test login credentials:
  Email: test@example.com
  Password: password123
```

---

### Step 2: Deploy Remote Agents

Deploy individual agents that will self-register with the backend.

```powershell
.\deploy-remote-agent.ps1 `
    -AgentName "azurefoundry_branding" `
    -Port 9000 `
    -ResourceGroup "rg-a2a-prod" `
    -AcrName "a2awestuslab" `
    -Environment "env-a2a-final"
```

**Available Agents:**
- `azurefoundry_branding` (Port 9000)
- `azurefoundry_network` (Port 9001)
- `azurefoundry_auth` (Port 9002)
- Any other agent in `remote_agents/` folder

**What it does:**
1. Builds agent Docker image for linux/amd64
2. Pushes image to ACR
3. Gets backend FQDN for registration
4. Creates container app with:
   - `A2A_ENDPOINT` (agent's own public URL)
   - `BACKEND_SERVER_URL` (for self-registration)
   - `AZURE_CLIENT_ID` (Managed Identity)
5. Grants Cognitive Services User role automatically
6. Agent starts and self-registers with backend **instantly** (1-2 seconds)

**Expected Output:**
```
✅ Agent Deployment Complete!

Agent Details:
  Name: azurefoundry_branding
  URL: https://azurefoundry-branding.ambitioussky-6c709152.westus2.azurecontainerapps.io
  Backend: https://backend-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io

Next Steps:
  1. Wait 2-3 minutes for RBAC permissions to propagate
  2. Go to: https://frontend-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io
  3. Agent should appear in sidebar automatically!
```

---

## 🔑 Environment Variables

### Backend API (`backend-uami`)

| Variable | Example | Purpose |
|----------|---------|---------|
| `WEBSOCKET_SERVER_URL` | `https://websocket-uami...azurecontainerapps.io` | Backend → WebSocket communication |
| `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` | `https://simonfoundry.services.ai.azure.com/api/projects/proj-default` | Azure AI Foundry endpoint |
| `AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME` | `gpt-4o` | Model deployment name |
| `AZURE_OPENAI_GPT_API_BASE` | `https://simonfoundry.openai.azure.com/` | OpenAI API base URL |
| `AZURE_OPENAI_GPT_API_KEY` | `AmYAu...` | OpenAI API key |
| `AZURE_OPENAI_GPT_DEPLOYMENT` | `gpt-4o` | GPT deployment name |
| `AZURE_OPENAI_EMBEDDINGS_ENDPOINT` | `https://simonfoundry.cognitiveservices.azure.com/...` | Embeddings endpoint |
| `AZURE_OPENAI_EMBEDDINGS_KEY` | `AmYAu...` | Embeddings key |
| `A2A_HOST` | `FOUNDRY` | Agent type identifier |
| `VERBOSE_LOGGING` | `true` | Enable debug logging |

### WebSocket Server (`websocket-uami`)

| Variable | Example | Purpose |
|----------|---------|---------|
| `BACKEND_HOST` | `backend-uami...azurecontainerapps.io` | WebSocket → Backend communication |
| `BACKEND_PORT` | `443` | HTTPS port |

### Remote Agent (e.g., `azurefoundry-branding`)

| Variable | Example | Purpose |
|----------|---------|---------|
| `A2A_PORT` | `9000` | Agent listening port |
| `A2A_HOST` | `0.0.0.0` | Bind to all interfaces |
| `A2A_ENDPOINT` | `https://azurefoundry-branding...azurecontainerapps.io` | Agent's own public URL |
| `BACKEND_SERVER_URL` | `https://backend-uami...azurecontainerapps.io` | Backend URL for self-registration |
| `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` | `https://simonfoundry.services.ai.azure.com/...` | Azure AI Foundry endpoint |
| `AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME` | `gpt-4o` | Model deployment name |
| `AZURE_CLIENT_ID` | `<managed-identity-client-id>` | Managed Identity client ID |

### Frontend (Build-time variables)

| Variable | Example | Purpose |
|----------|---------|---------|
| `NEXT_PUBLIC_A2A_API_URL` | `https://backend-uami...azurecontainerapps.io` | Backend API URL (baked into build) |
| `NEXT_PUBLIC_WEBSOCKET_URL` | `wss://websocket-uami...azurecontainerapps.io/events` | WebSocket connection URL |
| `NEXT_PUBLIC_DEV_MODE` | `false` | Production mode |

> **Important:** Frontend variables are **build-time only**. Changing them requires rebuilding the Docker image.

---

## 🔧 Common Operations

### View Logs

```powershell
# Backend logs
az containerapp logs show `
    --name backend-uami `
    --resource-group rg-a2a-prod `
    --follow

# WebSocket logs
az containerapp logs show `
    --name websocket-uami `
    --resource-group rg-a2a-prod `
    --follow

# Remote agent logs
az containerapp logs show `
    --name azurefoundry-branding `
    --resource-group rg-a2a-prod `
    --follow
```

### Restart Services

```powershell
# Restart backend
az containerapp revision restart `
    --name backend-uami `
    --resource-group rg-a2a-prod

# Restart WebSocket
az containerapp revision restart `
    --name websocket-uami `
    --resource-group rg-a2a-prod

# Restart remote agent
az containerapp revision restart `
    --name azurefoundry-branding `
    --resource-group rg-a2a-prod
```

### Quick Update (after code changes)

**Backend only:**
```bash
# Rebuild and push
docker buildx build --platform linux/amd64 \
    -t a2awestuslab.azurecr.io/a2a-backend:latest \
    -f backend/Dockerfile . --push

# Update container
az containerapp update \
    --name backend-uami \
    --resource-group rg-a2a-prod \
    --image a2awestuslab.azurecr.io/a2a-backend:latest
```

**WebSocket only:**
```bash
# Rebuild and push
docker buildx build --platform linux/amd64 \
    -t a2awestuslab.azurecr.io/a2a-websocket:latest \
    -f backend/Dockerfile.websocket . --push

# Update container
az containerapp update \
    --name websocket-uami \
    --resource-group rg-a2a-prod \
    --image a2awestuslab.azurecr.io/a2a-websocket:latest
```

### Delete Agent

```powershell
az containerapp delete `
    --name azurefoundry-branding `
    --resource-group rg-a2a-prod `
    --yes
```

---

## 🐛 Troubleshooting

### Agent Not Appearing in Sidebar

**Symptoms:**
- Agent deployed successfully
- Agent shows in Agent Catalog
- Agent NOT in right sidebar

**Solutions:**

1. **Check agent self-registration:**
   ```powershell
   az containerapp logs show --name azurefoundry-branding --resource-group rg-a2a-prod --tail 50
   ```
   Look for: `"Self-registration successful"`

2. **Check backend received registration:**
   ```powershell
   az containerapp logs show --name backend-uami --resource-group rg-a2a-prod --tail 50
   ```
   Look for: `"Triggering immediate sync via HTTP POST"`

3. **Hard refresh browser:**
   - Press `Ctrl+Shift+R` (Windows/Linux)
   - Press `Cmd+Shift+R` (Mac)

4. **Check WebSocket connection:**
   - Open browser DevTools (F12) → Console
   - Should see: `[WebSocket] Connected successfully`

---

### Agent Shows "Offline" Status

**Symptoms:**
- Agent appears in sidebar
- Status shows red/offline

**Solutions:**

1. **Check agent health:**
   ```powershell
   curl https://azurefoundry-branding...azurecontainerapps.io/health
   ```
   Should return: `{"status": "healthy"}`

2. **Wait for RBAC propagation:**
   - RBAC roles can take 2-3 minutes to propagate
   - Wait and refresh

3. **Check Managed Identity permissions:**
   ```powershell
   # Get identity principal ID
   $principalId = az identity show `
       --name a2a-registry-uami `
       --resource-group rg-a2a-prod `
       --query principalId -o tsv
   
   # Check role assignments
   az role assignment list `
       --assignee $principalId `
       --all
   ```
   Should see: `Cognitive Services User` role

4. **Restart agent:**
   ```powershell
   az containerapp revision restart `
       --name azurefoundry-branding `
       --resource-group rg-a2a-prod
   ```

---

### Docker Build Failing

**Symptoms:**
- `docker build` command fails
- Image build errors

**Solutions:**

1. **Check Docker is running:**
   ```powershell
   docker info
   ```

2. **Login to ACR:**
   ```powershell
   az acr login --name a2awestuslab
   ```

3. **Ensure correct platform:**
   - Always use: `--platform linux/amd64`
   - Mac M1/M2/M3 (arm64) must explicitly specify this

4. **Clear Docker cache:**
   ```powershell
   docker system prune -a
   ```

---

### Frontend Shows Localhost URLs

**Symptoms:**
- Browser console shows: `POST http://localhost:12000/... net::ERR_CONNECTION_REFUSED`

**Cause:**
Frontend was built with wrong URLs (build-time variables)

**Solution:**
Rebuild frontend with correct URLs:
```bash
# Get backend FQDN
BACKEND_FQDN=$(az containerapp show \
    --name backend-uami \
    --resource-group rg-a2a-prod \
    --query properties.configuration.ingress.fqdn -o tsv)

# Get WebSocket FQDN
WS_FQDN=$(az containerapp show \
    --name websocket-uami \
    --resource-group rg-a2a-prod \
    --query properties.configuration.ingress.fqdn -o tsv)

# Rebuild with correct URLs
docker buildx build --platform linux/amd64 \
    --build-arg NEXT_PUBLIC_A2A_API_URL="https://$BACKEND_FQDN" \
    --build-arg NEXT_PUBLIC_WEBSOCKET_URL="wss://$WS_FQDN/events" \
    --build-arg NEXT_PUBLIC_DEV_MODE="false" \
    --build-arg BUILDCACHE_BUST="$(date +%s)" \
    -t a2awestuslab.azurecr.io/a2a-frontend:latest \
    --push ./frontend

# Update container
az containerapp update \
    --name frontend-uami \
    --resource-group rg-a2a-prod \
    --image a2awestuslab.azurecr.io/a2a-frontend:latest
```

---

### ImagePullUnauthorized Error

**Symptoms:**
- Container app shows: `ImagePullUnauthorized` or `ImagePullFailure`
- Container never starts

**Solutions:**

1. **Wrong ACR:**
   - Correct ACR: `a2awestuslab.azurecr.io`
   - NOT: `a2acay.azurecr.io`

2. **Wrong platform:**
   - Must use: `--platform linux/amd64`
   - Azure Container Apps runs on amd64, not arm64

3. **Check Managed Identity has AcrPull:**
   ```powershell
   # Get identity principal ID
   $principalId = az identity show `
       --name a2a-registry-uami `
       --resource-group rg-a2a-prod `
       --query principalId -o tsv
   
   # Get ACR ID
   $acrId = az acr show `
       --name a2awestuslab `
       --resource-group rg-a2a-prod `
       --query id -o tsv
   
   # Grant role
   az role assignment create `
       --assignee $principalId `
       --role AcrPull `
       --scope $acrId
   ```

---

## 📚 Lessons Learned

### Critical Best Practices

1. **Platform Architecture Matters**
   - Apple Silicon (M1/M2/M3) = arm64
   - Azure Container Apps = amd64
   - **Always build for linux/amd64:** `--platform linux/amd64`

2. **Build-time vs Runtime Environment Variables**
   - Next.js `NEXT_PUBLIC_*` variables are **baked into the build**
   - Changing them requires **rebuilding the Docker image**
   - Use `--build-arg` to set them during build

3. **Microservices Communication**
   - Use **public FQDNs**, not `localhost`
   - Each service needs to know how to reach others
   - Environment variables are crucial

4. **Docker Build Cache**
   - Can hide problems when rebuilding
   - Use unique tags (timestamps) or cache-busting args
   - Clear cache when debugging: `docker system prune`

5. **RBAC Propagation**
   - Role assignments take **2-3 minutes** to propagate
   - Don't panic if permissions fail immediately
   - Wait, then restart the service

6. **Multiple Code Paths**
   - Check **ALL** registration endpoints (we had 2!)
   - `/agent/register-by-address` AND `/agent/self-register`
   - Both needed the immediate sync fix

7. **Instant Feedback > Polling**
   - HTTP POST to trigger immediate sync (1-2 seconds)
   - vs. waiting for periodic sync (15 seconds)
   - User experience matters!

---

## 🎯 Success Criteria

Your deployment is working correctly when:

- ✅ Frontend loads at: `https://frontend-uami...azurecontainerapps.io`
- ✅ You can log in with `test@example.com` / `password123`
- ✅ Backend health: `https://backend-uami...azurecontainerapps.io/`
- ✅ WebSocket connection shown in browser console
- ✅ Remote agent appears in sidebar **within 1-2 seconds** of deployment
- ✅ You can send messages and get responses
- ✅ Agent status shows as "online" (green dot)

---

## 🎉 You're All Set!

Your A2A multi-agent system is now fully deployed on Azure Container Apps with:
- ✅ Instant agent registration (1-2 seconds)
- ✅ Real-time WebSocket updates
- ✅ Proper authentication and RBAC
- ✅ Correct platform architecture (linux/amd64)
- ✅ Production-ready configuration

**Ready to deploy more agents or scale your system!** 🚀

For questions or issues, refer to the [Troubleshooting](#troubleshooting) section above.
