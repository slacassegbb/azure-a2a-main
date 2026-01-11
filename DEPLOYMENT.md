# 🚀 Deployment Guide

This guide covers all deployment options for the A2A Multi-Agent Platform.

---

## 📋 Table of Contents

- [Prerequisites](#prerequisites)
- [Local Development](#local-development)
- [Local Docker](#local-docker)
- [Azure Container Apps Deployment](#azure-container-apps-deployment)
- [Deploying Remote Agents](#deploying-remote-agents)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### For Local Development
- Python 3.12+
- Node.js 20+
- Azure CLI (`az login`)
- Your `.env` files configured

### For Docker Deployment
- Docker Desktop installed
- Docker Compose

### For Azure Deployment
- Azure subscription
- Azure CLI installed and logged in (`az login`)
- Docker installed (to build images locally)

---

## Local Development

The simplest way to run the platform for development.

### Option 1: Using Make (Recommended)

```bash
# Terminal 1 - Start Backend
make start_backend

# Terminal 2 - Start Frontend
make start_frontend

# Terminal 3 - Start a Remote Agent (optional)
make start_agent AGENT=azurefoundry_fraud
```

### Option 2: Manual Commands

```bash
# Terminal 1 - Backend
cd backend
source venv/bin/activate  # Windows: .\venv\Scripts\Activate.ps1
python backend_production.py

# Terminal 2 - Frontend
cd frontend
npm install
npm run dev

# Terminal 3 - Remote Agent
cd remote_agents/azurefoundry_fraud
source .venv/bin/activate
uv run .
```

### Access Points
| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:12000 |
| WebSocket | ws://localhost:8080/events |

---

## Local Docker

Run everything in Docker containers on your local machine.

### Quick Start

```bash
# Build and start all services
docker-compose up --build

# Or start in background
docker-compose up -d --build

# View logs
docker-compose logs -f

# Stop all services
docker-compose down
```

### Individual Services

```bash
# Build and run just backend
docker-compose up backend --build

# Build and run just frontend
docker-compose up frontend --build
```

### Access Points (Docker)
| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:12000 |
| WebSocket | ws://localhost:8080/events |

---

## Azure Container Apps Deployment

Deploy the platform to Azure Container Apps for production use.

### Step 1: Configure Azure CLI

```bash
# Login to Azure
az login

# Set your subscription (if you have multiple)
az account set --subscription "Your Subscription Name"
```

### Step 2: Run the Deployment Script

```powershell
# PowerShell (Windows/macOS/Linux)
./deploy-azure.ps1 `
    -ResourceGroup "rg-a2a-prod" `
    -Location "eastus" `
    -AcrName "youruniquename123" `
    -Environment "env-a2a-prod"
```

**Note:** The ACR name must be globally unique (letters and numbers only).

### What the Script Does

1. ✅ Creates Azure Resource Group
2. ✅ Creates Azure Container Registry (ACR)
3. ✅ Builds Docker images locally
4. ✅ Pushes images to ACR
5. ✅ Creates Container Apps Environment
6. ✅ Deploys Backend container
7. ✅ Deploys Frontend container
8. ✅ Configures networking and environment variables
9. ✅ Outputs your live URLs

### During Deployment

The script will prompt you for:
- **Azure AI Foundry Project Endpoint** - from your `.env` file
- **Azure OpenAI API Key** - from your `.env` file
- **Azure OpenAI Deployment Name** - e.g., "gpt-4o"

### After Deployment

You'll receive URLs like:
```
Backend:  https://backend.redocean-xxxxx.eastus.azurecontainerapps.io
Frontend: https://frontend.redocean-xxxxx.eastus.azurecontainerapps.io
```

### View Logs

```bash
az containerapp logs show --name backend --resource-group rg-a2a-prod --follow
az containerapp logs show --name frontend --resource-group rg-a2a-prod --follow
```

### Clean Up Resources

```bash
# Delete everything (BE CAREFUL!)
az group delete --name rg-a2a-prod --yes --no-wait
```

---

## Deploying Remote Agents

Deploy individual remote agents to Azure Container Apps.

### Deploy a Single Agent

```powershell
./deploy-remote-agent.ps1 `
    -AgentName "azurefoundry_fraud" `
    -Port 9004 `
    -ResourceGroup "rg-a2a-prod" `
    -AcrName "youruniquename123"
```

### Common Agent Ports

| Agent | Port |
|-------|------|
| azurefoundry_template | 9000 |
| azurefoundry_SN | 8000 |
| azurefoundry_classification | 8001 |
| azurefoundry_Deep_Search | 8002 |
| azurefoundry_fraud | 9004 |
| azurefoundry_legal | 8006 |
| azurefoundry_image_generator | 9010 |
| azurefoundry_image_analysis | 9066 |

### Deploy Multiple Agents

```powershell
# Deploy several agents
./deploy-remote-agent.ps1 -AgentName azurefoundry_fraud -Port 9004
./deploy-remote-agent.ps1 -AgentName azurefoundry_classification -Port 8001
./deploy-remote-agent.ps1 -AgentName azurefoundry_legal -Port 8006
```

---

## Advanced Deployment

For more control, use the advanced deployment script with Managed Identity:

```powershell
./deploy-aca-managed-identity.ps1
```

This interactive script offers:
- Component selection (deploy just backend, or all components)
- Managed Identity configuration
- Key Vault integration
- Storage account setup

---

## Troubleshooting

### Docker Build Fails

```bash
# Clear Docker cache and rebuild
docker-compose build --no-cache
```

### ACR Login Issues

```bash
# Re-authenticate to ACR
az acr login --name youracrname
```

### Container App Not Starting

```bash
# Check logs
az containerapp logs show --name backend --resource-group rg-a2a-prod --follow

# Check container app status
az containerapp show --name backend --resource-group rg-a2a-prod
```

### Frontend Can't Connect to Backend

Make sure environment variables are set correctly:
```
NEXT_PUBLIC_A2A_API_URL=https://your-backend-url
NEXT_PUBLIC_WEBSOCKET_URL=wss://your-backend-url/events
```

### Azure Quota Issues

If you hit quota limits:
```bash
# Try a different region
./deploy-azure.ps1 -Location "westus2" ...
```

---

## Environment Variables Reference

### Backend (.env)
```
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=https://your-project.azure.com
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
```

### Frontend
```
NEXT_PUBLIC_A2A_API_URL=http://localhost:12000
NEXT_PUBLIC_WEBSOCKET_URL=ws://localhost:8080/events
```

### Remote Agents
Each agent has its own `.env` file in `remote_agents/<agent_name>/.env`

---

## Support

For issues with deployment:
1. Check the [Troubleshooting](#troubleshooting) section
2. Review Azure Container Apps logs
3. Verify your `.env` files have all required values

