# Azure Container Apps Deployment Script - Separate Servers Architecture
# This script automates the deployment of A2A system with proper microservices architecture
#
# Architecture:
# - WebSocket Server (port 8080) - Handles real-time event streaming
# - Backend API (port 12000) - Main orchestration and business logic
# - Frontend (port 3000) - User interface
#
# Usage:
#   .\deploy-azure.ps1 -ResourceGroup "rg-a2a-prod" -Location "westus2" -AcrName "a2awestuslab" -Environment "env-a2a-final"

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,
    
    [Parameter(Mandatory=$true)]
    [string]$Location,
    
    [Parameter(Mandatory=$true)]
    [string]$AcrName,
    
    [Parameter(Mandatory=$true)]
    [string]$Environment,

    [Parameter(Mandatory=$false)]
    [string]$ManagedIdentity = "a2a-registry-uami"
)

Write-Host "🚀 A2A System - Separate Servers Deployment" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "📋 Configuration:" -ForegroundColor Yellow
Write-Host "  Resource Group: $ResourceGroup" -ForegroundColor White
Write-Host "  Location: $Location" -ForegroundColor White
Write-Host "  ACR Name: $AcrName" -ForegroundColor White
Write-Host "  Environment: $Environment" -ForegroundColor White
Write-Host "  Managed Identity: $ManagedIdentity" -ForegroundColor White
Write-Host ""

# Check if Azure CLI is installed
if (!(Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Azure CLI not found. Please install it first." -ForegroundColor Red
    exit 1
}

# Check if Docker is installed
if (!(Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Docker not found. Please install Docker Desktop first." -ForegroundColor Red
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

# Step 1: Create Resource Group (if it doesn't exist)
Write-Host "📦 Ensuring resource group exists: $ResourceGroup" -ForegroundColor Cyan
az group create --name $ResourceGroup --location $Location --output none
Write-Host "✅ Resource group ready" -ForegroundColor Green
Write-Host ""

# Step 2: Create Azure Container Registry (if it doesn't exist)
Write-Host "🐳 Ensuring Azure Container Registry exists: $AcrName" -ForegroundColor Cyan
$acrExists = az acr show --name $AcrName --resource-group $ResourceGroup 2>$null
if (!$acrExists) {
    az acr create `
        --resource-group $ResourceGroup `
        --name $AcrName `
        --sku Basic `
        --admin-enabled true `
        --output none
    Write-Host "✅ ACR created" -ForegroundColor Green
} else {
    Write-Host "✅ ACR already exists" -ForegroundColor Green
}
Write-Host ""

# Step 3: Create User-Assigned Managed Identity (if it doesn't exist)
Write-Host "🔐 Ensuring Managed Identity exists: $ManagedIdentity" -ForegroundColor Cyan
$identityExists = az identity show --name $ManagedIdentity --resource-group $ResourceGroup 2>$null
if (!$identityExists) {
    az identity create `
        --name $ManagedIdentity `
        --resource-group $ResourceGroup `
        --location $Location `
        --output none
    Write-Host "✅ Managed Identity created" -ForegroundColor Green
    
    # Grant AcrPull role to managed identity
    $identityPrincipalId = az identity show --name $ManagedIdentity --resource-group $ResourceGroup --query principalId -o tsv
    $acrId = az acr show --name $AcrName --resource-group $ResourceGroup --query id -o tsv
    
    Write-Host "  Granting AcrPull permissions..." -ForegroundColor Yellow
    az role assignment create `
        --assignee $identityPrincipalId `
        --role AcrPull `
        --scope $acrId `
        --output none
    
    Write-Host "  ⚠️  Waiting 30 seconds for permissions to propagate..." -ForegroundColor Yellow
    Start-Sleep -Seconds 30
} else {
    Write-Host "✅ Managed Identity already exists" -ForegroundColor Green
}
Write-Host ""

# Step 4: Login to ACR
Write-Host "🔐 Logging in to ACR..." -ForegroundColor Cyan
az acr login --name $AcrName
Write-Host "✅ Logged in to ACR" -ForegroundColor Green
Write-Host ""

# Step 5: Prompt for Azure configuration
Write-Host "🔑 Azure Configuration" -ForegroundColor Cyan
Write-Host "Enter the following values (press Enter to keep existing if updating):" -ForegroundColor Yellow
Write-Host ""

$azureAiEndpoint = Read-Host "Azure AI Foundry Project Endpoint"
$azureAiModelDeployment = Read-Host "Azure AI Agent Model Deployment Name (e.g., gpt-4o)"
$azureOpenAiBase = Read-Host "Azure OpenAI API Base URL"
$azureOpenAiKey = Read-Host "Azure OpenAI API Key"
$azureOpenAiDeployment = Read-Host "Azure OpenAI Deployment Name"
$azureEmbeddingsEndpoint = Read-Host "Azure OpenAI Embeddings Endpoint"
$azureEmbeddingsDeployment = Read-Host "Azure Embeddings Deployment Name"
$azureEmbeddingsKey = Read-Host "Azure Embeddings Key"

Write-Host ""
Write-Host "🔍 Azure Search (Memory Service) Configuration" -ForegroundColor Cyan
$azureSearchEndpoint = Read-Host "Azure Search Service Endpoint"
$azureSearchKey = Read-Host "Azure Search Admin Key"
$azureSearchIndex = Read-Host "Azure Search Index Name (e.g., microsoft-results)"

Write-Host ""
Write-Host "🌐 Bing Grounding (Web Search) Configuration" -ForegroundColor Cyan
Write-Host "  (Optional - leave blank to disable web search capability)" -ForegroundColor Yellow
$bingConnectionId = Read-Host "Bing Connection ID"

Write-Host ""

# Generate timestamp for image tags
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

# Step 6: Build and push images
Write-Host "🔨 Building Docker images for linux/amd64 platform..." -ForegroundColor Cyan
Write-Host ""

Write-Host "  [1/3] Building WebSocket server..." -ForegroundColor Yellow
docker buildx build --platform linux/amd64 `
    -f backend/Dockerfile.websocket `
    -t "$AcrName.azurecr.io/a2a-websocket:$timestamp" `
    -t "$AcrName.azurecr.io/a2a-websocket:latest" `
    --load .

Write-Host "  [2/3] Building backend API..." -ForegroundColor Yellow
docker buildx build --platform linux/amd64 `
    -f backend/Dockerfile `
    -t "$AcrName.azurecr.io/a2a-backend:$timestamp" `
    -t "$AcrName.azurecr.io/a2a-backend:latest" `
    --load .

Write-Host "  [3/3] Building frontend..." -ForegroundColor Yellow
# Frontend will be built again with proper URLs after we get the FQDNs
docker buildx build --platform linux/amd64 `
    -t "$AcrName.azurecr.io/a2a-frontend:temp" `
    --load ./frontend

Write-Host ""
Write-Host "📤 Pushing images to ACR..." -ForegroundColor Cyan
docker push "$AcrName.azurecr.io/a2a-websocket:$timestamp"
docker push "$AcrName.azurecr.io/a2a-websocket:latest"
docker push "$AcrName.azurecr.io/a2a-backend:$timestamp"
docker push "$AcrName.azurecr.io/a2a-backend:latest"
Write-Host "✅ Images pushed" -ForegroundColor Green
Write-Host ""

# Step 7: Create Container Apps Environment (if it doesn't exist)
Write-Host "🌍 Ensuring Container Apps Environment exists: $Environment" -ForegroundColor Cyan
$envExists = az containerapp env show --name $Environment --resource-group $ResourceGroup 2>$null
if (!$envExists) {
    az containerapp env create `
        --name $Environment `
        --resource-group $ResourceGroup `
        --location $Location `
        --output none
    Write-Host "✅ Environment created" -ForegroundColor Green
} else {
    Write-Host "✅ Environment already exists" -ForegroundColor Green
}
Write-Host ""

# Step 8: Deploy WebSocket Server
Write-Host "🔌 Deploying WebSocket Server..." -ForegroundColor Cyan

# Note: WebSocket needs to know backend URL, but backend doesn't exist yet on first deploy
# We'll deploy it first, then update with env vars after backend is deployed
$wsExists = az containerapp show --name websocket-uami --resource-group $ResourceGroup 2>$null
if ($wsExists) {
    # Get backend FQDN for WebSocket configuration
    $backendFqdn = az containerapp show `
        --name backend-uami `
        --resource-group $ResourceGroup `
        --query properties.configuration.ingress.fqdn -o tsv 2>$null
    
    if ($backendFqdn) {
        az containerapp update `
            --name websocket-uami `
            --resource-group $ResourceGroup `
            --image "$AcrName.azurecr.io/a2a-websocket:$timestamp" `
            --set-env-vars `
                "BACKEND_HOST=$backendFqdn" `
                "BACKEND_PORT=443" `
            --output none
        Write-Host "✅ WebSocket server updated with backend URL" -ForegroundColor Green
    } else {
        az containerapp update `
            --name websocket-uami `
            --resource-group $ResourceGroup `
            --image "$AcrName.azurecr.io/a2a-websocket:$timestamp" `
            --output none
        Write-Host "⚠️  WebSocket server updated (backend URL will be set later)" -ForegroundColor Yellow
    }
} else {
    az containerapp create `
        --name websocket-uami `
        --resource-group $ResourceGroup `
        --environment $Environment `
        --image "$AcrName.azurecr.io/a2a-websocket:$timestamp" `
        --registry-server "$AcrName.azurecr.io" `
        --user-assigned $ManagedIdentity `
        --target-port 8080 `
        --ingress external `
        --min-replicas 1 `
        --max-replicas 1 `
        --cpu 0.5 `
        --memory 1.0Gi `
        --output none
    Write-Host "✅ WebSocket server deployed (will configure backend URL after backend deployment)" -ForegroundColor Green
}

$wsFqdn = az containerapp show `
    --name websocket-uami `
    --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn -o tsv

Write-Host "  📍 WebSocket FQDN: $wsFqdn" -ForegroundColor White
Write-Host ""

# Step 9: Deploy Backend API
Write-Host "🚀 Deploying Backend API..." -ForegroundColor Cyan
$backendExists = az containerapp show --name backend-uami --resource-group $ResourceGroup 2>$null
if ($backendExists) {
    az containerapp update `
        --name backend-uami `
        --resource-group $ResourceGroup `
        --image "$AcrName.azurecr.io/a2a-backend:$timestamp" `
        --set-env-vars `
            "WEBSOCKET_SERVER_URL=https://$wsFqdn" `
            "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=$azureAiEndpoint" `
            "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=$azureAiModelDeployment" `
            "AZURE_OPENAI_GPT_API_BASE=$azureOpenAiBase" `
            "AZURE_OPENAI_GPT_API_KEY=$azureOpenAiKey" `
            "AZURE_OPENAI_GPT_DEPLOYMENT=$azureOpenAiDeployment" `
            "AZURE_OPENAI_EMBEDDINGS_ENDPOINT=$azureEmbeddingsEndpoint" `
            "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT=$azureEmbeddingsDeployment" `
            "AZURE_OPENAI_EMBEDDINGS_KEY=$azureEmbeddingsKey" `
            "AZURE_SEARCH_SERVICE_ENDPOINT=$azureSearchEndpoint" `
            "AZURE_SEARCH_ADMIN_KEY=$azureSearchKey" `
            "AZURE_SEARCH_INDEX_NAME=$azureSearchIndex" `
            "BING_CONNECTION_ID=$bingConnectionId" `
            "A2A_HOST=FOUNDRY" `
            "VERBOSE_LOGGING=true" `
        --output none
    Write-Host "✅ Backend updated" -ForegroundColor Green
} else {
    az containerapp create `
        --name backend-uami `
        --resource-group $ResourceGroup `
        --environment $Environment `
        --image "$AcrName.azurecr.io/a2a-backend:$timestamp" `
        --registry-server "$AcrName.azurecr.io" `
        --user-assigned $ManagedIdentity `
        --target-port 12000 `
        --ingress external `
        --min-replicas 1 `
        --max-replicas 1 `
        --cpu 1.0 `
        --memory 2.0Gi `
        --env-vars `
            "WEBSOCKET_SERVER_URL=https://$wsFqdn" `
            "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=$azureAiEndpoint" `
            "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=$azureAiModelDeployment" `
            "AZURE_OPENAI_GPT_API_BASE=$azureOpenAiBase" `
            "AZURE_OPENAI_GPT_API_KEY=$azureOpenAiKey" `
            "AZURE_OPENAI_GPT_DEPLOYMENT=$azureOpenAiDeployment" `
            "AZURE_OPENAI_EMBEDDINGS_ENDPOINT=$azureEmbeddingsEndpoint" `
            "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT=$azureEmbeddingsDeployment" `
            "AZURE_OPENAI_EMBEDDINGS_KEY=$azureEmbeddingsKey" `
            "AZURE_SEARCH_SERVICE_ENDPOINT=$azureSearchEndpoint" `
            "AZURE_SEARCH_ADMIN_KEY=$azureSearchKey" `
            "AZURE_SEARCH_INDEX_NAME=$azureSearchIndex" `
            "BING_CONNECTION_ID=$bingConnectionId" `
            "A2A_HOST=FOUNDRY" `
            "VERBOSE_LOGGING=true" `
        --output none
    Write-Host "✅ Backend deployed" -ForegroundColor Green
}

$backendFqdn = az containerapp show `
    --name backend-uami `
    --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn -o tsv

Write-Host "  📍 Backend FQDN: $backendFqdn" -ForegroundColor White
Write-Host ""

# Step 9.5: Update WebSocket Server with Backend URL
Write-Host "🔧 Configuring WebSocket server with backend URL..." -ForegroundColor Cyan
az containerapp update `
    --name websocket-uami `
    --resource-group $ResourceGroup `
    --set-env-vars `
        "BACKEND_HOST=$backendFqdn" `
        "BACKEND_PORT=443" `
    --output none
Write-Host "✅ WebSocket server configured with backend URL" -ForegroundColor Green
Write-Host ""

# Step 10: Build and Deploy Frontend with correct URLs
Write-Host "🎨 Building frontend with correct URLs..." -ForegroundColor Cyan
docker buildx build --platform linux/amd64 `
    --build-arg NEXT_PUBLIC_A2A_API_URL="https://$backendFqdn" `
    --build-arg NEXT_PUBLIC_WEBSOCKET_URL="wss://$wsFqdn/events" `
    --build-arg NEXT_PUBLIC_DEV_MODE="false" `
    --build-arg BUILDCACHE_BUST="$timestamp" `
    -t "$AcrName.azurecr.io/a2a-frontend:$timestamp" `
    -t "$AcrName.azurecr.io/a2a-frontend:latest" `
    --load ./frontend

Write-Host "📤 Pushing frontend image..." -ForegroundColor Cyan
docker push "$AcrName.azurecr.io/a2a-frontend:$timestamp"
docker push "$AcrName.azurecr.io/a2a-frontend:latest"

Write-Host "🚀 Deploying Frontend..." -ForegroundColor Cyan
$frontendExists = az containerapp show --name frontend-uami --resource-group $ResourceGroup 2>$null
if ($frontendExists) {
    az containerapp update `
        --name frontend-uami `
        --resource-group $ResourceGroup `
        --image "$AcrName.azurecr.io/a2a-frontend:$timestamp" `
        --output none
    Write-Host "✅ Frontend updated" -ForegroundColor Green
} else {
    az containerapp create `
        --name frontend-uami `
        --resource-group $ResourceGroup `
        --environment $Environment `
        --image "$AcrName.azurecr.io/a2a-frontend:$timestamp" `
        --registry-server "$AcrName.azurecr.io" `
        --user-assigned $ManagedIdentity `
        --target-port 3000 `
        --ingress external `
        --min-replicas 1 `
        --max-replicas 1 `
        --cpu 0.5 `
        --memory 1.0Gi `
        --output none
    Write-Host "✅ Frontend deployed" -ForegroundColor Green
}

$frontendFqdn = az containerapp show `
    --name frontend-uami `
    --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn -o tsv

Write-Host "  📍 Frontend FQDN: $frontendFqdn" -ForegroundColor White
Write-Host ""

# Summary
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "🎉 Deployment Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Your services are available at:" -ForegroundColor White
Write-Host "  Frontend:   https://$frontendFqdn" -ForegroundColor Cyan
Write-Host "  Backend:    https://$backendFqdn" -ForegroundColor Cyan
Write-Host "  WebSocket:  wss://$wsFqdn/events" -ForegroundColor Cyan
Write-Host ""
Write-Host "Architecture:" -ForegroundColor Yellow
Write-Host "  ✓ Separate WebSocket server (port 8080)" -ForegroundColor White
Write-Host "  ✓ Backend API server (port 12000)" -ForegroundColor White
Write-Host "  ✓ Frontend (port 3000)" -ForegroundColor White
Write-Host "  ✓ All images built for linux/amd64" -ForegroundColor White
Write-Host "  ✓ Managed Identity authentication" -ForegroundColor White
Write-Host ""
Write-Host "View logs with:" -ForegroundColor Yellow
Write-Host "  az containerapp logs show --name websocket-uami --resource-group $ResourceGroup --follow" -ForegroundColor White
Write-Host "  az containerapp logs show --name backend-uami --resource-group $ResourceGroup --follow" -ForegroundColor White
Write-Host "  az containerapp logs show --name frontend-uami --resource-group $ResourceGroup --follow" -ForegroundColor White
Write-Host ""
Write-Host "Test login credentials:" -ForegroundColor Yellow
Write-Host "  Email: test@example.com" -ForegroundColor White
Write-Host "  Password: password123" -ForegroundColor White
Write-Host ""
Write-Host "To clean up resources:" -ForegroundColor Yellow
Write-Host "  az group delete --name $ResourceGroup --yes --no-wait" -ForegroundColor White
Write-Host ""
