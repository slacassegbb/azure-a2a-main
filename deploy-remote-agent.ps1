# Deploy Remote Agent to Azure Container Apps with Managed Identity
# Usage: ./deploy-remote-agent.ps1 -AgentName azurefoundry_branding -Port 9000

param(
    [Parameter(Mandatory=$true)]
    [string]$AgentName,
    
    [Parameter(Mandatory=$true)]
    [int]$Port,
    
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroup = "rg-a2a-prod",
    
    [Parameter(Mandatory=$false)]
    [string]$AcrName = "a2awestuslab",
    
    [Parameter(Mandatory=$false)]
    [string]$Environment = "env-a2a-final",

    [Parameter(Mandatory=$false)]
    [string]$ManagedIdentity = "a2a-registry-uami",

    [Parameter(Mandatory=$false)]
    [string]$CognitiveServicesAccount = "simonfoundry"
)

$AgentPath = "remote_agents/$AgentName"

Write-Host "🤖 Deploying Remote Agent with Managed Identity" -ForegroundColor Cyan
Write-Host "===============================================" -ForegroundColor Cyan
Write-Host "  Agent: $AgentName" -ForegroundColor White
Write-Host "  Port: $Port" -ForegroundColor White
Write-Host "  Resource Group: $ResourceGroup" -ForegroundColor White
Write-Host "  ACR: $AcrName" -ForegroundColor White
Write-Host "  Managed Identity: $ManagedIdentity" -ForegroundColor White
Write-Host ""

# Check if agent directory exists
if (!(Test-Path $AgentPath)) {
    Write-Host "❌ Agent not found at: $AgentPath" -ForegroundColor Red
    Write-Host ""
    Write-Host "Available agents:" -ForegroundColor Yellow
    Get-ChildItem -Path "remote_agents" -Directory | ForEach-Object { Write-Host "  - $($_.Name)" }
    exit 1
}

# Check if Dockerfile exists
if (!(Test-Path "$AgentPath/Dockerfile")) {
    Write-Host "❌ Dockerfile not found in $AgentPath" -ForegroundColor Red
    exit 1
}

# Prompt for Azure AI Foundry configuration
Write-Host "🔑 Azure AI Foundry Configuration" -ForegroundColor Cyan
Write-Host "Enter the following values:" -ForegroundColor Yellow
Write-Host ""

$azureAiEndpoint = Read-Host "Azure AI Foundry Project Endpoint"
$azureAiModelDeployment = Read-Host "Azure AI Agent Model Deployment Name (e.g., gpt-4o)"

Write-Host ""

# Login to ACR
Write-Host "🔐 Logging in to ACR..." -ForegroundColor Cyan
az acr login --name $AcrName
Write-Host ""

# Generate timestamp for versioning
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

# Build the image for linux/amd64
Write-Host "🔨 Building Docker image for linux/amd64..." -ForegroundColor Cyan
$imageName = "$AcrName.azurecr.io/a2a-$AgentName`:$timestamp"
$imageLatest = "$AcrName.azurecr.io/a2a-$AgentName`:latest"

docker buildx build --platform linux/amd64 `
    -f "$AgentPath/Dockerfile" `
    -t $imageName `
    -t $imageLatest `
    --load $AgentPath

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Docker build failed" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Push to ACR
Write-Host "📤 Pushing image to ACR..." -ForegroundColor Cyan
docker push $imageName
docker push $imageLatest

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Docker push failed" -ForegroundColor Red
    exit 1
}

Write-Host "✅ Image pushed: $imageName" -ForegroundColor Green
Write-Host ""

# Get backend FQDN for registration
Write-Host "🔍 Getting backend FQDN..." -ForegroundColor Cyan
$backendFqdn = az containerapp show `
    --name backend-uami `
    --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn -o tsv 2>$null

if (!$backendFqdn) {
    Write-Host "⚠️  Backend not found. Agent will run but may not auto-register." -ForegroundColor Yellow
    $backendUrl = "http://localhost:12000"
} else {
    $backendUrl = "https://$backendFqdn"
    Write-Host "✅ Backend URL: $backendUrl" -ForegroundColor Green
}
Write-Host ""

# Deploy or update to Container Apps
$containerName = $AgentName.ToLower().Replace("_", "-")
Write-Host "🚀 Deploying to Azure Container Apps as: $containerName" -ForegroundColor Cyan

# Get managed identity client ID
$ManagedIdentityClientId = az identity show `
    --name $ManagedIdentity `
    --resource-group $ResourceGroup `
    --query clientId -o tsv

$agentExists = az containerapp show --name $containerName --resource-group $ResourceGroup 2>$null

if ($agentExists) {
    Write-Host "  Updating existing agent..." -ForegroundColor Yellow
    
    # Get agent's public FQDN for A2A_ENDPOINT
    $agentFqdn = az containerapp show `
        --name $containerName `
        --resource-group $ResourceGroup `
        --query properties.configuration.ingress.fqdn -o tsv
    
    az containerapp update `
        --name $containerName `
        --resource-group $ResourceGroup `
        --image $imageName `
        --set-env-vars `
            "A2A_PORT=$Port" `
            "A2A_HOST=0.0.0.0" `
            "A2A_ENDPOINT=https://$agentFqdn" `
            "BACKEND_SERVER_URL=$backendUrl" `
            "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=$azureAiEndpoint" `
            "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=$azureAiModelDeployment" `
            "AZURE_CLIENT_ID=$ManagedIdentityClientId" `
        --output none
} else {
    Write-Host "  Creating new agent..." -ForegroundColor Yellow
    az containerapp create `
        --name $containerName `
        --resource-group $ResourceGroup `
        --environment $Environment `
        --image $imageName `
        --registry-server "$AcrName.azurecr.io" `
        --user-assigned $ManagedIdentity `
        --target-port $Port `
        --ingress external `
        --min-replicas 1 `
        --max-replicas 1 `
        --cpu 0.5 `
        --memory 1.0Gi `
        --env-vars `
            "A2A_PORT=$Port" `
            "A2A_HOST=0.0.0.0" `
            "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=$azureAiEndpoint" `
            "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=$azureAiModelDeployment" `
            "AZURE_CLIENT_ID=$ManagedIdentityClientId" `
        --output none
    
    # Get the newly created agent's FQDN and update with A2A_ENDPOINT and BACKEND_SERVER_URL
    Start-Sleep -Seconds 5
    $agentFqdn = az containerapp show `
        --name $containerName `
        --resource-group $ResourceGroup `
        --query properties.configuration.ingress.fqdn -o tsv
    
    Write-Host "  Configuring agent URLs..." -ForegroundColor Yellow
    az containerapp update `
        --name $containerName `
        --resource-group $ResourceGroup `
        --set-env-vars `
            "A2A_ENDPOINT=https://$agentFqdn" `
            "BACKEND_SERVER_URL=$backendUrl" `
        --output none
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Deployment failed" -ForegroundColor Red
    exit 1
}

Write-Host "✅ Agent deployed" -ForegroundColor Green
Write-Host ""

# Get agent FQDN
$agentFqdn = az containerapp show `
    --name $containerName `
    --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn -o tsv

# Setup RBAC permissions
Write-Host "🔐 Setting up RBAC permissions..." -ForegroundColor Cyan

# Get managed identity principal ID
$principalId = az identity show `
    --name $ManagedIdentity `
    --resource-group $ResourceGroup `
    --query principalId -o tsv

# Get Azure AI Foundry (Cognitive Services) account resource ID
$cognitiveServicesId = az cognitiveservices account show `
    --name $CognitiveServicesAccount `
    --resource-group $ResourceGroup `
    --query id -o tsv 2>$null

if ($cognitiveServicesId) {
    Write-Host "  Granting 'Cognitive Services User' role..." -ForegroundColor Yellow
    
    # Check if role assignment already exists
    $existingRole = az role assignment list `
        --assignee $principalId `
        --role "Cognitive Services User" `
        --scope $cognitiveServicesId `
        --query "[0].id" -o tsv 2>$null
    
    if (!$existingRole) {
        az role assignment create `
            --assignee $principalId `
            --role "Cognitive Services User" `
            --scope $cognitiveServicesId `
            --output none
        Write-Host "  ✅ Role assigned (may take 2-3 minutes to propagate)" -ForegroundColor Green
    } else {
        Write-Host "  ✅ Role already assigned" -ForegroundColor Green
    }
} else {
    Write-Host "  ⚠️  Could not find Cognitive Services account: $CognitiveServicesAccount" -ForegroundColor Yellow
    Write-Host "  You may need to manually grant permissions if the agent needs Azure AI Foundry access" -ForegroundColor Yellow
}

Write-Host ""

# Summary
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "✅ Agent Deployment Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Agent Details:" -ForegroundColor White
Write-Host "  Name: $AgentName" -ForegroundColor Cyan
Write-Host "  URL: https://$agentFqdn" -ForegroundColor Cyan
Write-Host "  Port: $Port" -ForegroundColor Cyan
Write-Host "  Backend: $backendUrl" -ForegroundColor Cyan
Write-Host ""
Write-Host "Configuration:" -ForegroundColor White
Write-Host "  Azure AI Foundry: $azureAiEndpoint" -ForegroundColor Cyan
Write-Host "  Model Deployment: $azureAiModelDeployment" -ForegroundColor Cyan
Write-Host "  Managed Identity: $ManagedIdentity (with Cognitive Services User role)" -ForegroundColor Cyan
Write-Host ""
Write-Host "View logs:" -ForegroundColor Yellow
Write-Host "  az containerapp logs show --name $containerName --resource-group $ResourceGroup --follow" -ForegroundColor White
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "  1. Wait 2-3 minutes for RBAC permissions to propagate" -ForegroundColor White
Write-Host "  2. Go to: https://frontend-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io" -ForegroundColor White
Write-Host "  3. Register agent: https://$agentFqdn" -ForegroundColor White
Write-Host "  4. Start chatting with the $AgentName agent!" -ForegroundColor White
Write-Host ""
Write-Host "If you see permission errors in logs:" -ForegroundColor Yellow
Write-Host "  - Wait a few more minutes for RBAC to propagate" -ForegroundColor White
Write-Host "  - Restart the agent: az containerapp revision restart --name $containerName --resource-group $ResourceGroup" -ForegroundColor White
Write-Host ""
