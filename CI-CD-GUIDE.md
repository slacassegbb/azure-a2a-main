# 🚀 Automated CI/CD Deployment Guide

## ⚡ Quick Start

### One-Time Setup (Do This Once)

```bash
# Install GitHub CLI (if not already installed)
brew install gh

# Login to GitHub
gh auth login

# Run the setup script
./setup-github-cicd.sh
```

That's it! Now every push to `main` automatically deploys to Azure! 🎉

---

## 🔄 Daily Workflow

### 1. Make Your Changes
Edit any files in `frontend/` or `backend/`:
```bash
# Example: Edit a frontend component
code frontend/app/page.tsx

# Example: Edit a backend endpoint
code backend/backend_production.py
```

### 2. Commit & Push
```bash
git add .
git commit -m "Add new feature"
git push
```

### 3. Watch It Deploy
- Go to: https://github.com/slacassegbb/azure-a2a-main/actions
- Your deployment will start automatically
- Takes ~3-5 minutes per service

### 4. Test on Production URLs
- **Frontend**: https://frontend-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io
- **Backend**: https://backend-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io
- **WebSocket**: https://websocket-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io

---

## 🎯 Smart Deployment Features

### Only Changed Services Deploy
The workflow is smart:
- Change **only** `frontend/` → Only frontend deploys ⚡
- Change **only** `backend/` → Backend + WebSocket deploy ⚡
- Change **both** → All three deploy

This saves time and costs!

### Manual Deployment
Don't want to commit? Run deployment manually:
1. Go to: https://github.com/slacassegbb/azure-a2a-main/actions
2. Click "Deploy to Azure Container Apps"
3. Click "Run workflow" → "Run workflow"
4. Deploys everything (frontend, backend, websocket)

---

## 📊 Monitoring Deployments

### View Workflow Progress
```bash
# In terminal
gh run list

# Watch latest run
gh run watch
```

### View Logs
In GitHub Actions UI:
1. Click on your workflow run
2. Click on a job (e.g., "deploy-frontend")
3. View real-time logs

### View Container App Logs
```bash
# Backend logs
az containerapp logs show --name backend-uami --resource-group rg-a2a-prod --follow

# Frontend logs
az containerapp logs show --name frontend-uami --resource-group rg-a2a-prod --follow

# WebSocket logs
az containerapp logs show --name websocket-uami --resource-group rg-a2a-prod --follow
```

---

## 🛠️ Advanced Usage

### Deploy Specific Service Only
Want to deploy just one service? Push changes to only that folder:

```bash
# Only deploy frontend
git add frontend/
git commit -m "Update frontend"
git push

# Only deploy backend
git add backend/
git commit -m "Update backend"
git push
```

### Rollback
Made a mistake? Roll back to previous image:

```bash
# Get previous image SHA from GitHub Actions
PREVIOUS_SHA="abc123def456"

# Rollback frontend
az containerapp update \
  --name frontend-uami \
  --resource-group rg-a2a-prod \
  --image a2awestuslab.azurecr.io/frontend:$PREVIOUS_SHA
```

### Disable Auto-Deployment
Don't want auto-deployment temporarily?

1. Go to: https://github.com/slacassegbb/azure-a2a-main/actions
2. Click "Deploy to Azure Container Apps"
3. Click "..." → "Disable workflow"

Re-enable when ready!

---

## 🔒 Security

### GitHub Secret: AZURE_CREDENTIALS
This secret contains Azure service principal credentials that allow GitHub to deploy to your Azure resources.

**To rotate/update:**
```bash
./setup-github-cicd.sh
```

**To view current secrets:**
```bash
gh secret list
```

---

## 💡 Tips & Tricks

### Test Locally First
Before pushing, test locally:
```bash
# Start backend
cd backend && python backend_production.py

# Start frontend (in new terminal)
cd frontend && npm run dev
```

### Use Feature Branches
For big changes, use feature branches:
```bash
git checkout -b feature/my-new-feature
# Make changes...
git push -u origin feature/my-new-feature
# Create PR on GitHub
# Merge to main when ready → Auto-deploys!
```

### Check Deployment Status
```bash
# Quick status check
gh run list --limit 5

# Watch current deployment
gh run watch
```

---

## 📦 What Gets Deployed

### Frontend Container
- **Base**: Next.js production build
- **Port**: 3000 → 443 (HTTPS)
- **Features**: React app, Tailwind CSS
- **Build time**: ~2-3 minutes

### Backend Container
- **Base**: Python FastAPI
- **Port**: 12000 → 443 (HTTPS)
- **Features**: Agent orchestration, API endpoints
- **Build time**: ~2-3 minutes

### WebSocket Container
- **Base**: Python WebSocket server
- **Port**: 8080 → 443 (HTTPS)
- **Features**: Real-time agent updates
- **Build time**: ~2 minutes

---

## ❓ Troubleshooting

### Deployment Failed
1. Check GitHub Actions logs
2. Look for error messages
3. Common issues:
   - Docker build errors → Check Dockerfile
   - Azure auth errors → Re-run `./setup-github-cicd.sh`
   - Image push errors → Check ACR permissions

### Service Not Responding
```bash
# Check if container is running
az containerapp show --name backend-uami --resource-group rg-a2a-prod --query "properties.runningStatus"

# Restart container
az containerapp revision restart --name backend-uami --resource-group rg-a2a-prod
```

### Logs Not Showing
```bash
# Enable logging
az containerapp logs show --name backend-uami --resource-group rg-a2a-prod --follow --type console
```

---

## 🎉 Success!

You now have:
- ✅ Automated deployments on every push
- ✅ Smart deployment (only changed services)
- ✅ Production URLs ready to test
- ✅ Manual deployment option
- ✅ Full deployment visibility

**Your new workflow:**
```
Edit code → Commit → Push → ☕ Wait 5 mins → Test on production URLs
```

That's it! No manual Docker commands, no Azure CLI commands needed! 🚀
