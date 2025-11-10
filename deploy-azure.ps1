# Azure Container Apps Deployment Script
# This script automates the deployment of A2A system to Azure Container Apps

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup = "rg-a2a-prod",
    
    [Parameter(Mandatory=$true)]
    [string]$Location = "eastus",
    
    [Parameter(Mandatory=$true)]
    [string]$AcrName = "acra2aprod",
    
    [Parameter(Mandatory=$true)]
    [string]$Environment = "env-a2a-prod"
)

Write-Host "🚀 A2A System - Azure Container Apps Deployment" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# Check if Azure CLI is installed
if (!(Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Azure CLI not found. Please install it first." -ForegroundColor Red
    exit 1
}

# Check if logged in
$account = az account show 2>$null
if (!$account) {
    Write-Host "❌ Not logged in to Azure. Running 'az login'..." -ForegroundColor Yellow
    az login
}

Write-Host "✅ Logged in to Azure" -ForegroundColor Green
Write-Host ""

# Step 1: Create Resource Group
Write-Host "📦 Creating resource group: $ResourceGroup" -ForegroundColor Cyan
az group create --name $ResourceGroup --location $Location
Write-Host ""

# Step 2: Create Azure Container Registry
Write-Host "🐳 Creating Azure Container Registry: $AcrName" -ForegroundColor Cyan
az acr create `
    --resource-group $ResourceGroup `
    --name $AcrName `
    --sku Basic `
    --admin-enabled true
Write-Host ""

# Step 3: Login to ACR
Write-Host "🔐 Logging in to ACR..." -ForegroundColor Cyan
az acr login --name $AcrName
Write-Host ""

# Step 4: Build and push images
Write-Host "🔨 Building Docker images..." -ForegroundColor Cyan

Write-Host "  Building backend..." -ForegroundColor Yellow
docker build -f backend/Dockerfile -t "$AcrName.azurecr.io/a2a-backend:latest" .

Write-Host "  Building frontend..." -ForegroundColor Yellow
docker build -f frontend/Dockerfile -t "$AcrName.azurecr.io/a2a-frontend:latest" ./frontend

Write-Host "  Building visualizer..." -ForegroundColor Yellow
docker build -f Visualizer/voice-a2a-fabric/Dockerfile -t "$AcrName.azurecr.io/a2a-visualizer:latest" ./Visualizer/voice-a2a-fabric

Write-Host ""
Write-Host "📤 Pushing images to ACR..." -ForegroundColor Cyan
docker push "$AcrName.azurecr.io/a2a-backend:latest"
docker push "$AcrName.azurecr.io/a2a-frontend:latest"
docker push "$AcrName.azurecr.io/a2a-visualizer:latest"
Write-Host ""

# Step 5: Create Container Apps Environment
Write-Host "🌍 Creating Container Apps Environment: $Environment" -ForegroundColor Cyan
az containerapp env create `
    --name $Environment `
    --resource-group $ResourceGroup `
    --location $Location
Write-Host ""

# Step 6: Deploy Backend
Write-Host "🚀 Deploying Backend..." -ForegroundColor Cyan

# Prompt for secrets
Write-Host "Enter Azure configuration values:" -ForegroundColor Yellow
$azureAiEndpoint = Read-Host "Azure AI Foundry Project Endpoint"
$azureOpenAiKey = Read-Host "Azure OpenAI API Key" -AsSecureString
$azureOpenAiKeyPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($azureOpenAiKey))
$azureOpenAiDeployment = Read-Host "Azure OpenAI Deployment Name (e.g., gpt-4o)"

az containerapp create `
    --name backend `
    --resource-group $ResourceGroup `
    --environment $Environment `
    --image "$AcrName.azurecr.io/a2a-backend:latest" `
    --target-port 12000 `
    --ingress external `
    --min-replicas 1 `
    --max-replicas 3 `
    --cpu 1.0 `
    --memory 2.0Gi `
    --registry-server "$AcrName.azurecr.io" `
    --env-vars `
        "A2A_UI_HOST=0.0.0.0" `
        "A2A_UI_PORT=12000" `
    --secrets `
        "azure-ai-endpoint=$azureAiEndpoint" `
        "azure-openai-key=$azureOpenAiKeyPlain" `
        "azure-openai-deployment=$azureOpenAiDeployment"

# Get backend FQDN
$backendFqdn = az containerapp show `
    --name backend `
    --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn -o tsv

Write-Host "✅ Backend deployed at: https://$backendFqdn" -ForegroundColor Green
Write-Host ""

# Step 7: Deploy Frontend
Write-Host "🚀 Deploying Frontend..." -ForegroundColor Cyan
az containerapp create `
    --name frontend `
    --resource-group $ResourceGroup `
    --environment $Environment `
    --image "$AcrName.azurecr.io/a2a-frontend:latest" `
    --target-port 3000 `
    --ingress external `
    --min-replicas 1 `
    --max-replicas 3 `
    --cpu 0.5 `
    --memory 1.0Gi `
    --registry-server "$AcrName.azurecr.io" `
    --env-vars `
        "NODE_ENV=production" `
        "NEXT_PUBLIC_A2A_API_URL=https://$backendFqdn" `
        "NEXT_PUBLIC_WEBSOCKET_URL=wss://$backendFqdn/events" `
        "NEXT_PUBLIC_DEV_MODE=false"

$frontendFqdn = az containerapp show `
    --name frontend `
    --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn -o tsv

Write-Host "✅ Frontend deployed at: https://$frontendFqdn" -ForegroundColor Green
Write-Host ""

# Step 8: Deploy Visualizer
Write-Host "🚀 Deploying Visualizer..." -ForegroundColor Cyan

$azureAiToken = Read-Host "Azure AI Token (for voice features)" -AsSecureString
$azureAiTokenPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($azureAiToken))

az containerapp create `
    --name visualizer `
    --resource-group $ResourceGroup `
    --environment $Environment `
    --image "$AcrName.azurecr.io/a2a-visualizer:latest" `
    --target-port 3000 `
    --ingress external `
    --min-replicas 1 `
    --max-replicas 2 `
    --cpu 0.5 `
    --memory 1.0Gi `
    --registry-server "$AcrName.azurecr.io" `
    --env-vars `
        "NODE_ENV=production" `
        "NEXT_PUBLIC_A2A_API_URL=https://$backendFqdn" `
        "NEXT_PUBLIC_WEBSOCKET_URL=wss://$backendFqdn/events" `
    --secrets `
        "azure-ai-token=$azureAiTokenPlain"

$visualizerFqdn = az containerapp show `
    --name visualizer `
    --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn -o tsv

Write-Host "✅ Visualizer deployed at: https://$visualizerFqdn" -ForegroundColor Green
Write-Host ""

# Summary
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "🎉 Deployment Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Your services are available at:" -ForegroundColor White
Write-Host "  Backend:    https://$backendFqdn" -ForegroundColor Cyan
Write-Host "  Frontend:   https://$frontendFqdn" -ForegroundColor Cyan
Write-Host "  Visualizer: https://$visualizerFqdn" -ForegroundColor Cyan
Write-Host ""
Write-Host "View logs with:" -ForegroundColor Yellow
Write-Host "  az containerapp logs show --name backend --resource-group $ResourceGroup --follow" -ForegroundColor White
Write-Host "  az containerapp logs show --name frontend --resource-group $ResourceGroup --follow" -ForegroundColor White
Write-Host "  az containerapp logs show --name visualizer --resource-group $ResourceGroup --follow" -ForegroundColor White
Write-Host ""
Write-Host "To clean up resources:" -ForegroundColor Yellow
Write-Host "  az group delete --name $ResourceGroup --yes --no-wait" -ForegroundColor White
