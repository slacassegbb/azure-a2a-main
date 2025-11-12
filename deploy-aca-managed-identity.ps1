# Complete Azure Container Apps Deployment with Managed Identity
# This script deploys the entire A2A system with proper managed identity configuration

param(
    [Parameter(Mandatory=$false)]
    [string]$SubscriptionId,
    
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroup = "rg-a2a-prod",
    
    [Parameter(Mandatory=$false)]
    [string]$Location = "eastus",
    
    [Parameter(Mandatory=$false)]
    [string]$AcrName = "acra2aprod",
    
    [Parameter(Mandatory=$false)]
    [string]$Environment = "env-a2a-prod",
    
    [Parameter(Mandatory=$false)]
    [string]$KeyVaultName = "kv-a2a-prod",
    
    [Parameter(Mandatory=$false)]
    [string]$StorageAccountName = "sta2aprod"
)

$ErrorActionPreference = "Stop"

Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "   Azure Container Apps Deployment with Managed Identity" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ============================================================================
# Interactive Component Selection
# ============================================================================
Write-Host "🎯 Component Selection" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""
Write-Host "Which components do you want to deploy?" -ForegroundColor Yellow
Write-Host "  1. Backend only" -ForegroundColor White
Write-Host "  2. Frontend only" -ForegroundColor White
Write-Host "  3. Visualizer only" -ForegroundColor White
Write-Host "  4. Remote agents only" -ForegroundColor White
Write-Host "  5. Backend + Frontend" -ForegroundColor White
Write-Host "  6. Backend + Frontend + Visualizer" -ForegroundColor White
Write-Host "  7. All components (Backend + Frontend + Visualizer + Remote Agents)" -ForegroundColor White
Write-Host ""

$componentChoice = Read-Host "Enter your choice (1-7)"

# Parse component selection
$deployBackend = $false
$deployFrontend = $false
$deployVisualizer = $false
$deployRemoteAgents = $false

switch ($componentChoice) {
    "1" { 
        $deployBackend = $true
        Write-Host "✅ Selected: Backend only" -ForegroundColor Green
    }
    "2" { 
        $deployFrontend = $true
        Write-Host "✅ Selected: Frontend only" -ForegroundColor Green
    }
    "3" { 
        $deployVisualizer = $true
        Write-Host "✅ Selected: Visualizer only" -ForegroundColor Green
    }
    "4" { 
        $deployRemoteAgents = $true
        Write-Host "✅ Selected: Remote agents only" -ForegroundColor Green
    }
    "5" { 
        $deployBackend = $true
        $deployFrontend = $true
        Write-Host "✅ Selected: Backend + Frontend" -ForegroundColor Green
    }
    "6" { 
        $deployBackend = $true
        $deployFrontend = $true
        $deployVisualizer = $true
        Write-Host "✅ Selected: Backend + Frontend + Visualizer" -ForegroundColor Green
    }
    "7" { 
        $deployBackend = $true
        $deployFrontend = $true
        $deployVisualizer = $true
        $deployRemoteAgents = $true
        Write-Host "✅ Selected: All components" -ForegroundColor Green
    }
    default {
        Write-Host "❌ Invalid choice. Exiting." -ForegroundColor Red
        exit 1
    }
}
Write-Host ""

# ============================================================================
# Configuration Options
# ============================================================================
Write-Host "⚙️  Configuration Options" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""

$updateSecrets = $false
$updateHealthChecks = $false

Write-Host "Do you need to update secrets in Key Vault? (y/n)" -ForegroundColor Yellow
$secretsResponse = Read-Host "Update secrets"
if ($secretsResponse -eq "y" -or $secretsResponse -eq "Y" -or $secretsResponse -eq "yes") {
    $updateSecrets = $true
    Write-Host "✅ Secrets will be updated" -ForegroundColor Green
} else {
    Write-Host "⏭️  Skipping secret updates" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "Do you need to configure health checks? (y/n)" -ForegroundColor Yellow
$healthCheckResponse = Read-Host "Configure health checks"
if ($healthCheckResponse -eq "y" -or $healthCheckResponse -eq "Y" -or $healthCheckResponse -eq "yes") {
    $updateHealthChecks = $true
    Write-Host "✅ Health checks will be configured" -ForegroundColor Green
} else {
    Write-Host "⏭️  Skipping health check configuration" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "📋 Deployment Configuration Summary:" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "  Backend:         $(if ($deployBackend) {'✅ Yes'} else {'❌ No'})" -ForegroundColor White
Write-Host "  Frontend:        $(if ($deployFrontend) {'✅ Yes'} else {'❌ No'})" -ForegroundColor White
Write-Host "  Visualizer:      $(if ($deployVisualizer) {'✅ Yes'} else {'❌ No'})" -ForegroundColor White
Write-Host "  Remote Agents:   $(if ($deployRemoteAgents) {'✅ Yes'} else {'❌ No'})" -ForegroundColor White
Write-Host "  Update Secrets:  $(if ($updateSecrets) {'✅ Yes'} else {'❌ No'})" -ForegroundColor White
Write-Host "  Health Checks:   $(if ($updateHealthChecks) {'✅ Yes'} else {'❌ No'})" -ForegroundColor White
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""

Write-Host "Press any key to continue or Ctrl+C to cancel..." -ForegroundColor Yellow
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
Write-Host ""

# Check Azure CLI
if (!(Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Azure CLI not found. Please install it first." -ForegroundColor Red
    exit 1
}

# Login check
Write-Host "🔐 Checking Azure login status..." -ForegroundColor Cyan
$account = az account show 2>$null | ConvertFrom-Json
if (!$account) {
    Write-Host "⚠️  Not logged in. Launching Azure login..." -ForegroundColor Yellow
    az login
    $account = az account show | ConvertFrom-Json
}

Write-Host "✅ Logged in as: $($account.user.name)" -ForegroundColor Green

# Set subscription if provided
if ($SubscriptionId) {
    Write-Host "📌 Setting subscription: $SubscriptionId" -ForegroundColor Cyan
    az account set --subscription $SubscriptionId
}

$currentSub = az account show | ConvertFrom-Json
Write-Host "✅ Using subscription: $($currentSub.name)" -ForegroundColor Green
Write-Host ""

# ============================================================================
# STEP 0: Load Environment Variables from .env
# ============================================================================
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "STEP 0: Load Environment Configuration" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan

$envVars = @{}
$envFilePath = Join-Path $PSScriptRoot ".env"

if (Test-Path $envFilePath) {
    Write-Host "📄 Loading environment variables from .env..." -ForegroundColor Cyan
    
    Get-Content $envFilePath | ForEach-Object {
        $line = $_.Trim()
        # Skip empty lines and comments
        if ($line -and !$line.StartsWith('#')) {
            if ($line -match '^([^=]+)=(.*)$') {
                $key = $matches[1].Trim()
                $value = $matches[2].Trim()
                # Remove surrounding quotes if present
                $value = $value.Trim('"').Trim("'")
                $envVars[$key] = $value
            }
        }
    }
    
    Write-Host "✅ Loaded $($envVars.Count) environment variables" -ForegroundColor Green
    
    # Extract Azure AI Foundry configuration
    $azureSubId = if ($SubscriptionId) { $SubscriptionId } else { $envVars["AZURE_SUBSCRIPTION_ID"] }
    if (!$azureSubId) {
        $azureSubId = $currentSub.id
    }
    $azureRgName = $envVars["AZURE_RESOURCE_GROUP"]
    $aiFoundryResourceName = $envVars["AZURE_AI_FOUNDRY_RESOURCE_NAME"]
    $aiFoundryProjectName = $envVars["AZURE_AI_FOUNDRY_PROJECT_NAME"]
    
    # Construct Azure AI Foundry resource ID if components are available
    if ($azureSubId -and $azureRgName -and $aiFoundryResourceName -and $aiFoundryProjectName) {
        $aiProjectResourceId = "/subscriptions/$azureSubId/resourceGroups/$azureRgName/providers/Microsoft.CognitiveServices/accounts/$aiFoundryResourceName/projects/$aiFoundryProjectName"
        Write-Host "✅ Constructed AI Foundry resource ID from .env:" -ForegroundColor Green
        Write-Host "   $aiProjectResourceId" -ForegroundColor Gray
    } else {
        Write-Host "⚠️  Azure AI Foundry components not fully configured in .env" -ForegroundColor Yellow
        Write-Host "   Required: AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, AZURE_AI_FOUNDRY_RESOURCE_NAME, AZURE_AI_FOUNDRY_PROJECT_NAME" -ForegroundColor Yellow
        $aiProjectResourceId = $null
    }
    
    # Validate required variables
    $requiredVars = @(
        'AZURE_SUBSCRIPTION_ID',
        'AZURE_RESOURCE_GROUP',
        'AZURE_AI_FOUNDRY_RESOURCE_NAME',
        'AZURE_AI_FOUNDRY_PROJECT_NAME',
        'AZURE_AI_FOUNDRY_PROJECT_ENDPOINT',
        'AZURE_OPENAI_GPT_API_BASE',
        'AZURE_OPENAI_GPT_API_VERSION',
        'AZURE_OPENAI_GPT_DEPLOYMENT',
        'AZURE_OPENAI_GPT_API_KEY',
        'AZURE_OPENAI_EMBEDDINGS_ENDPOINT',
        'AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT',
        'AZURE_OPENAI_EMBEDDINGS_KEY',
        'AZURE_SEARCH_SERVICE_ENDPOINT',
        'AZURE_SEARCH_ADMIN_KEY',
        'AZURE_STORAGE_ACCOUNT_NAME',
        'AZURE_BLOB_CONTAINER',
        'AZURE_TENANT_ID'
    )
    
    $missingVars = @()
    foreach ($var in $requiredVars) {
        if (!$envVars.ContainsKey($var) -or [string]::IsNullOrWhiteSpace($envVars[$var])) {
            $missingVars += $var
        }
    }
    
    if ($missingVars.Count -gt 0) {
        Write-Host "❌ Missing required environment variables in .env:" -ForegroundColor Red
        foreach ($var in $missingVars) {
            Write-Host "   - $var" -ForegroundColor Red
        }
        Write-Host ""
        Write-Host "Please add these variables to your .env file before continuing." -ForegroundColor Yellow
        exit 1
    }
    
    Write-Host "✅ All required environment variables present" -ForegroundColor Green
} else {
    Write-Host "❌ .env file not found at: $envFilePath" -ForegroundColor Red
    Write-Host "Please create a .env file with all required configuration." -ForegroundColor Yellow
    exit 1
}

Write-Host ""

# ============================================================================
# STEP 1: Create Resource Group
# ============================================================================
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "STEP 1: Resource Group" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan

$rgExists = az group exists --name $ResourceGroup
if ($rgExists -eq "true") {
    Write-Host "✅ Resource group '$ResourceGroup' already exists" -ForegroundColor Green
} else {
    Write-Host "📦 Creating resource group: $ResourceGroup" -ForegroundColor Yellow
    az group create --name $ResourceGroup --location $Location --output none
    Write-Host "✅ Resource group created" -ForegroundColor Green
}
Write-Host ""

# ============================================================================
# STEP 2: Create Azure Container Registry
# ============================================================================
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "STEP 2: Azure Container Registry" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan

$acrExists = az acr show --name $AcrName --resource-group $ResourceGroup 2>$null
if ($acrExists) {
    Write-Host "✅ ACR '$AcrName' already exists" -ForegroundColor Green
} else {
    Write-Host "🐳 Creating Azure Container Registry: $AcrName" -ForegroundColor Yellow
    az acr create `
        --resource-group $ResourceGroup `
        --name $AcrName `
        --sku Standard `
        --admin-enabled false `
        --output none
    Write-Host "✅ ACR created" -ForegroundColor Green
}

# Login to ACR
Write-Host "🔐 Logging in to ACR..." -ForegroundColor Cyan
az acr login --name $AcrName
Write-Host "✅ ACR login successful" -ForegroundColor Green
Write-Host ""

# ============================================================================
# STEP 3: Create Key Vault for Secrets
# ============================================================================
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "STEP 3: Azure Key Vault" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan

$kvExists = az keyvault show --name $KeyVaultName --resource-group $ResourceGroup 2>$null
if ($kvExists) {
    Write-Host "✅ Key Vault '$KeyVaultName' already exists" -ForegroundColor Green
} else {
    Write-Host "🔑 Creating Key Vault: $KeyVaultName" -ForegroundColor Yellow
    az keyvault create `
        --resource-group $ResourceGroup `
        --name $KeyVaultName `
        --location $Location `
        --enable-rbac-authorization true `
        --output none
    Write-Host "✅ Key Vault created" -ForegroundColor Green
}

# Get current user for Key Vault permissions
$currentUserId = $account.user.name
Write-Host "🔐 Setting up Key Vault permissions for current user..." -ForegroundColor Cyan
$kvId = az keyvault show --name $KeyVaultName --resource-group $ResourceGroup --query id -o tsv
$userId = az ad signed-in-user show --query id -o tsv

az role assignment create `
    --role "Key Vault Secrets Officer" `
    --assignee $userId `
    --scope $kvId `
    --output none 2>$null

Write-Host "✅ Key Vault permissions configured" -ForegroundColor Green
Write-Host ""

# ============================================================================
# STEP 4: Store Secrets in Key Vault
# ============================================================================
if ($updateSecrets) {
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "STEP 4: Configure Secrets" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan

    Write-Host "🔐 Storing secrets from .env file in Key Vault..." -ForegroundColor Cyan

    # Wait a bit for RBAC to propagate
    Start-Sleep -Seconds 5

    # Store secrets from .env file
    az keyvault secret set --vault-name $KeyVaultName --name "azure-ai-endpoint" --value $envVars['AZURE_AI_FOUNDRY_PROJECT_ENDPOINT'] --output none
    az keyvault secret set --vault-name $KeyVaultName --name "azure-openai-key" --value $envVars['AZURE_OPENAI_GPT_API_KEY'] --output none
    az keyvault secret set --vault-name $KeyVaultName --name "azure-openai-deployment" --value $envVars['AZURE_OPENAI_GPT_DEPLOYMENT'] --output none
    az keyvault secret set --vault-name $KeyVaultName --name "azure-openai-base" --value $envVars['AZURE_OPENAI_GPT_API_BASE'] --output none
    az keyvault secret set --vault-name $KeyVaultName --name "azure-openai-embeddings-key" --value $envVars['AZURE_OPENAI_EMBEDDINGS_KEY'] --output none
    az keyvault secret set --vault-name $KeyVaultName --name "azure-search-key" --value $envVars['AZURE_SEARCH_ADMIN_KEY'] --output none
    az keyvault secret set --vault-name $KeyVaultName --name "azure-ai-token" --value $envVars['VOICE_LIVE_API_KEY'] --output none

    Write-Host "✅ Secrets stored securely" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "STEP 4: Configure Secrets (SKIPPED)" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "⏭️  Skipping secret updates (using existing secrets)" -ForegroundColor Yellow
    Write-Host ""
}

# ============================================================================
# STEP 5: Create Storage Account for Backend Data
# ============================================================================
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "STEP 5: Azure Storage Account" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan

$storageExists = az storage account show --name $StorageAccountName --resource-group $ResourceGroup 2>$null
if ($storageExists) {
    Write-Host "✅ Storage account '$StorageAccountName' already exists" -ForegroundColor Green
} else {
    Write-Host "💾 Creating storage account: $StorageAccountName" -ForegroundColor Yellow
    az storage account create `
        --name $StorageAccountName `
        --resource-group $ResourceGroup `
        --location $Location `
        --sku Standard_LRS `
        --kind StorageV2 `
        --allow-blob-public-access false `
        --output none
    Write-Host "✅ Storage account created" -ForegroundColor Green
}

# Create file shares using Azure AD authentication
Write-Host "📁 Creating file shares..." -ForegroundColor Cyan
$shares = @("backend-data", "backend-uploads", "backend-voice")
foreach ($share in $shares) {
    $shareExists = az storage share exists --name $share --account-name $StorageAccountName --auth-mode login --query exists -o tsv 2>$null
    if ($shareExists -eq "true") {
        Write-Host "  ✅ Share '$share' already exists" -ForegroundColor Green
    } else {
        az storage share create --name $share --account-name $StorageAccountName --auth-mode login --output none 2>$null
        Write-Host "  ✅ Created share '$share'" -ForegroundColor Green
    }
}
Write-Host ""

# ============================================================================
# STEP 6: Create Container Apps Environment
# ============================================================================
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "STEP 6: Container Apps Environment" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan

$envExists = az containerapp env show --name $Environment --resource-group $ResourceGroup 2>$null
if ($envExists) {
    Write-Host "✅ Environment '$Environment' already exists" -ForegroundColor Green
} else {
    Write-Host "🌍 Creating Container Apps Environment: $Environment" -ForegroundColor Yellow
    az containerapp env create `
        --name $Environment `
        --resource-group $ResourceGroup `
        --location $Location `
        --output none
    Write-Host "✅ Environment created" -ForegroundColor Green
}
Write-Host ""

# ============================================================================
# STEP 7: Configure Storage Mounts
# ============================================================================
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "STEP 7: Configure Storage Mounts" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan

$storageKey = az storage account keys list `
    --resource-group $ResourceGroup `
    --account-name $StorageAccountName `
    --query "[0].value" -o tsv

Write-Host "💾 Configuring storage mounts for Container Apps Environment..." -ForegroundColor Cyan

foreach ($share in $shares) {
    $mountExists = az containerapp env storage show `
        --name $Environment `
        --resource-group $ResourceGroup `
        --storage-name $share 2>$null
    
    if ($mountExists) {
        Write-Host "  ✅ Mount '$share' already configured" -ForegroundColor Green
    } else {
        az containerapp env storage set `
            --name $Environment `
            --resource-group $ResourceGroup `
            --storage-name $share `
            --azure-file-account-name $StorageAccountName `
            --azure-file-account-key $storageKey `
            --azure-file-share-name $share `
            --access-mode ReadWrite `
            --output none
        Write-Host "  ✅ Configured mount '$share'" -ForegroundColor Green
    }
}
Write-Host ""

# ============================================================================
# STEP 8: Get Environment Default Domain for Internal FQDNs
# ============================================================================
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "STEP 8: Get Environment Default Domain" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan

Write-Host "🔗 Getting environment default domain..." -ForegroundColor Cyan
$envDefaultDomain = az containerapp env show `
    --name $Environment `
    --resource-group $ResourceGroup `
    --query properties.defaultDomain -o tsv

$backendInternalFqdn = "backend.internal.$envDefaultDomain"
$backendExternalFqdn = "backend.$envDefaultDomain"
Write-Host "✅ Backend FQDNs calculated:" -ForegroundColor Green
Write-Host "   External: $backendExternalFqdn" -ForegroundColor Cyan
Write-Host "   Internal: $backendInternalFqdn" -ForegroundColor Cyan
Write-Host ""

# Generate timestamp and tag for all image builds (used across multiple steps)
$timestamp = Get-Date -Format "yyyyMMddHHmmss"
$tag = "v$timestamp"

# ============================================================================
# STEP 8.5: Build and Push Container Images
# ============================================================================
if ($deployBackend) {
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "STEP 8.5: Build and Push Backend Container Image" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan

    Write-Host "🔨 Building backend image with tag: $tag" -ForegroundColor Cyan
    Write-Host ""

    # Backend only - frontend and visualizer will be built after backend deployment
    Write-Host "  📦 Building backend..." -ForegroundColor Yellow
    docker build -f backend/Dockerfile -t "$AcrName.azurecr.io/a2a-backend:$tag" -t "$AcrName.azurecr.io/a2a-backend:latest" .
    Write-Host "  ✅ Backend built" -ForegroundColor Green

    Write-Host ""
    Write-Host "📤 Pushing backend image to ACR..." -ForegroundColor Cyan

    docker push "$AcrName.azurecr.io/a2a-backend:$tag"
    docker push "$AcrName.azurecr.io/a2a-backend:latest"
    Write-Host "  ✅ Backend pushed" -ForegroundColor Green

    Write-Host ""

    # ============================================================================
    # STEP 9: Deploy Backend Container App with Managed Identity
    # ============================================================================
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "STEP 9: Deploy Backend Container App" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan

    # Generate unique revision suffix using timestamp (used for both create and update)
    $revisionSuffix = "v$(Get-Date -Format 'yyyyMMddHHmmss')"
    Write-Host "📝 Using revision suffix: $revisionSuffix" -ForegroundColor Cyan

    $backendExists = az containerapp show --name backend --resource-group $ResourceGroup 2>$null

if ($backendExists) {
    Write-Host "🔄 Updating existing backend container app..." -ForegroundColor Yellow
    
    $kvUri = az keyvault show --name $KeyVaultName --resource-group $ResourceGroup --query properties.vaultUri -o tsv
    
    # First update secrets (names must be ≤20 chars) - no revision suffix here
    Write-Host "⚙️  Updating secrets..." -ForegroundColor Cyan
    az containerapp secret set `
        --name backend `
        --resource-group $ResourceGroup `
        --secrets `
            "ai-endpoint=keyvaultref:${kvUri}secrets/azure-ai-endpoint,identityref:system" `
            "openai-key=keyvaultref:${kvUri}secrets/azure-openai-key,identityref:system" `
            "openai-deployment=keyvaultref:${kvUri}secrets/azure-openai-deployment,identityref:system" `
            "openai-base=keyvaultref:${kvUri}secrets/azure-openai-base,identityref:system" `
            "openai-embed-key=keyvaultref:${kvUri}secrets/azure-openai-embeddings-key,identityref:system" `
            "search-key=keyvaultref:${kvUri}secrets/azure-search-key,identityref:system" `
            "azure-ai-token=keyvaultref:${kvUri}secrets/azure-ai-token,identityref:system" `
        --output none
    
    # Enable external ingress (if not already enabled, will reuse revision)
    Write-Host "⚙️  Configuring external ingress..." -ForegroundColor Cyan
    az containerapp ingress enable `
        --name backend `
        --resource-group $ResourceGroup `
        --type external `
        --target-port 12000 `
        --allow-insecure `
        --output none 2>$null
    
    # Then update image and environment variables with same revision suffix
    Write-Host "⚙️  Updating image and environment variables..." -ForegroundColor Cyan
    az containerapp update `
        --name backend `
        --resource-group $ResourceGroup `
        --image "$AcrName.azurecr.io/a2a-backend:latest" `
        --revision-suffix $revisionSuffix `
        --set-env-vars `
            "A2A_UI_HOST=0.0.0.0" `
            "A2A_UI_PORT=12000" `
            "WEBSOCKET_PORT=12000" `
            "BACKEND_SERVER_URL=http://localhost:12000" `
            "WEBSOCKET_SERVER_URL=http://localhost:12000" `
            "LOG_LEVEL=$($envVars['LOG_LEVEL'])" `
            "AZURE_TENANT_ID=$($envVars['AZURE_TENANT_ID'])" `
            "AZURE_SUBSCRIPTION_ID=$($envVars['AZURE_SUBSCRIPTION_ID'])" `
            "AZURE_RESOURCE_GROUP=$($envVars['AZURE_RESOURCE_GROUP'])" `
            "AZURE_AI_FOUNDRY_RESOURCE_NAME=$($envVars['AZURE_AI_FOUNDRY_RESOURCE_NAME'])" `
            "AZURE_AI_FOUNDRY_PROJECT_NAME=$($envVars['AZURE_AI_FOUNDRY_PROJECT_NAME'])" `
            "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=$($envVars['AZURE_AI_FOUNDRY_PROJECT_ENDPOINT'])" `
            "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=$($envVars['AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME'])" `
            "AZURE_OPENAI_GPT_API_BASE=$($envVars['AZURE_OPENAI_GPT_API_BASE'])" `
            "AZURE_OPENAI_GPT_API_VERSION=$($envVars['AZURE_OPENAI_GPT_API_VERSION'])" `
            "AZURE_OPENAI_GPT_DEPLOYMENT=$($envVars['AZURE_OPENAI_GPT_DEPLOYMENT'])" `
            "AZURE_OPENAI_EMBEDDINGS_ENDPOINT=$($envVars['AZURE_OPENAI_EMBEDDINGS_ENDPOINT'])" `
            "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT=$($envVars['AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT'])" `
            "AZURE_SEARCH_SERVICE_ENDPOINT=$($envVars['AZURE_SEARCH_SERVICE_ENDPOINT'])" `
            "AZURE_SEARCH_SERVICE_NAME=$($envVars['AZURE_SEARCH_SERVICE_NAME'])" `
            "AZURE_SEARCH_INDEX_NAME=$($envVars['AZURE_SEARCH_INDEX_NAME'])" `
            "AZURE_SEARCH_VECTOR_DIMENSION=$($envVars['AZURE_SEARCH_VECTOR_DIMENSION'])" `
            "AZURE_STORAGE_ACCOUNT_NAME=$($envVars['AZURE_STORAGE_ACCOUNT_NAME'])" `
            "AZURE_BLOB_CONTAINER=$($envVars['AZURE_BLOB_CONTAINER'])" `
            "AZURE_BLOB_SIZE_THRESHOLD=$($envVars['AZURE_BLOB_SIZE_THRESHOLD'])" `
            "AZURE_CONTENT_UNDERSTANDING_ENDPOINT=$($envVars['AZURE_CONTENT_UNDERSTANDING_ENDPOINT'])" `
            "AZURE_CONTENT_UNDERSTANDING_API_VERSION=$($envVars['AZURE_CONTENT_UNDERSTANDING_API_VERSION'])" `
            "AZURE_OPENAI_GPT_API_KEY=secretref:openai-key" `
            "AZURE_OPENAI_EMBEDDINGS_KEY=secretref:openai-embed-key" `
            "AZURE_SEARCH_ADMIN_KEY=secretref:search-key" `
            "AZURE_CU_API_KEY=secretref:openai-key" `
            "VOICE_LIVE_API_KEY=secretref:azure-ai-token" `
        --output none
    
    Write-Host "✅ Backend updated with environment variables" -ForegroundColor Green
} else {
    Write-Host "🚀 Creating backend container app..." -ForegroundColor Yellow
    
    # Create with managed identity and external ingress for browser access
    # Port 12000 serves both HTTP API and WebSocket on the same FastAPI instance
    az containerapp create `
        --name backend `
        --resource-group $ResourceGroup `
        --environment $Environment `
        --image "$AcrName.azurecr.io/a2a-backend:latest" `
        --target-port 12000 `
        --ingress external `
        --min-replicas 1 `
        --max-replicas 5 `
        --cpu 1.0 `
        --memory 2.0Gi `
        --registry-server "$AcrName.azurecr.io" `
        --registry-identity system `
        --system-assigned `
        --output none
    
    Write-Host "✅ Backend created with system-assigned managed identity (HTTP + WebSocket on port 12000)" -ForegroundColor Green
}

# Get backend managed identity
$backendIdentity = az containerapp show `
    --name backend `
    --resource-group $ResourceGroup `
    --query identity.principalId -o tsv

Write-Host "🔑 Backend Managed Identity: $backendIdentity" -ForegroundColor Cyan

# Grant ACR pull permissions
Write-Host "🔐 Granting ACR pull permissions to backend..." -ForegroundColor Cyan
$acrId = az acr show --name $AcrName --resource-group $ResourceGroup --query id -o tsv
az role assignment create `
    --assignee $backendIdentity `
    --role "AcrPull" `
    --scope $acrId `
    --output none 2>$null
Write-Host "✅ ACR permissions granted" -ForegroundColor Green

# Grant Key Vault access
Write-Host "🔐 Granting Key Vault access to backend..." -ForegroundColor Cyan
az role assignment create `
    --role "Key Vault Secrets User" `
    --assignee $backendIdentity `
    --scope $kvId `
    --output none 2>$null
Write-Host "✅ Key Vault access granted" -ForegroundColor Green

Write-Host "🔐 Granting AI Foundry access to backend..." -ForegroundColor Cyan

# Use the constructed Azure AI Foundry resource ID from .env
    if (!$aiProjectResourceId) {
        Write-Host "⚠️  Skipping AI Foundry RBAC - resource ID not configured" -ForegroundColor Yellow
    } else {
        Write-Host "  📍 AI Foundry project resource ID: $aiProjectResourceId" -ForegroundColor Cyan

        Write-Host "  🔐 Granting Azure AI User role..." -ForegroundColor Cyan
    az role assignment create `
        --role "Azure AI User" `
        --assignee $backendIdentity `
        --scope $aiProjectResourceId `
        --output none 2>$null

    Write-Host "  🔐 Granting Azure AI Developer role..." -ForegroundColor Cyan
    az role assignment create `
        --role "Azure AI Developer" `
        --assignee $backendIdentity `
        --scope $aiProjectResourceId `
        --output none 2>$null

        Write-Host "  ✅ Azure AI User and Azure AI Developer roles assigned at project scope" -ForegroundColor Green

        Write-Host "  ⏳ Waiting 10 seconds for role propagation..." -ForegroundColor Cyan
        Start-Sleep -Seconds 10

        Write-Host "  🔄 Restarting backend to pick up new permissions..." -ForegroundColor Cyan
        az containerapp revision restart `
            --name backend `
            --resource-group $ResourceGroup `
            --output none 2>$null

        Write-Host "✅ Azure AI User role granted and backend restarted" -ForegroundColor Green
    }

    if ($updateHealthChecks) {
    # Configure health probes (applies to both new and existing backends)
    Write-Host "⚙️  Configuring health probes..." -ForegroundColor Cyan
    $healthProbeConfig = @"
properties:
  template:
    containers:
    - name: backend
      probes:
      - type: liveness
        httpGet:
          path: /health
          port: 12000
        initialDelaySeconds: 90
        periodSeconds: 30
        timeoutSeconds: 10
        failureThreshold: 3
"@

        $healthProbeConfig | az containerapp update --name backend --resource-group $ResourceGroup --yaml - --output none 2>$null
        Write-Host "✅ Health probes configured (90s initial delay, 30s checks, 3 failures = 90s grace)" -ForegroundColor Green
    } else {
        Write-Host "⏭️  Skipping health probe configuration" -ForegroundColor Yellow
    }

    # Configure environment variables for newly created backend (update path handles this inline)
    if (-not $backendExists) {
    Write-Host "⚙️  Configuring secrets for new backend..." -ForegroundColor Cyan
    
    $kvUri = az keyvault show --name $KeyVaultName --resource-group $ResourceGroup --query properties.vaultUri -o tsv
    
    # Set secrets first (separate command)
    az containerapp secret set `
        --name backend `
        --resource-group $ResourceGroup `
        --secrets `
            "ai-endpoint=keyvaultref:${kvUri}secrets/azure-ai-endpoint,identityref:system" `
            "openai-key=keyvaultref:${kvUri}secrets/azure-openai-key,identityref:system" `
            "openai-deployment=keyvaultref:${kvUri}secrets/azure-openai-deployment,identityref:system" `
            "openai-base=keyvaultref:${kvUri}secrets/azure-openai-base,identityref:system" `
            "openai-embed-key=keyvaultref:${kvUri}secrets/azure-openai-embeddings-key,identityref:system" `
            "search-key=keyvaultref:${kvUri}secrets/azure-search-key,identityref:system" `
            "azure-ai-token=keyvaultref:${kvUri}secrets/azure-ai-token,identityref:system" `
        --output none
    
    Write-Host "✅ Secrets configured" -ForegroundColor Green
    
    Write-Host "⚙️  Configuring environment variables for new backend..." -ForegroundColor Cyan
    
    # Get backend FQDN for WebSocket configuration
    $backendFqdn = az containerapp show `
        --name backend `
        --resource-group $ResourceGroup `
        --query properties.configuration.ingress.fqdn `
        -o tsv
    
    # Then update with environment variables
    az containerapp update `
        --name backend `
        --resource-group $ResourceGroup `
        --revision-suffix $revisionSuffix `
        --set-env-vars `
            "A2A_UI_HOST=0.0.0.0" `
            "A2A_UI_PORT=12000" `
            "WEBSOCKET_PORT=12000" `
            "BACKEND_SERVER_URL=http://localhost:12000" `
            "WEBSOCKET_SERVER_URL=http://localhost:12000" `
            "LOG_LEVEL=$($envVars['LOG_LEVEL'])" `
            "AZURE_TENANT_ID=$($envVars['AZURE_TENANT_ID'])" `
            "AZURE_SUBSCRIPTION_ID=$($envVars['AZURE_SUBSCRIPTION_ID'])" `
            "AZURE_RESOURCE_GROUP=$($envVars['AZURE_RESOURCE_GROUP'])" `
            "AZURE_AI_FOUNDRY_RESOURCE_NAME=$($envVars['AZURE_AI_FOUNDRY_RESOURCE_NAME'])" `
            "AZURE_AI_FOUNDRY_PROJECT_NAME=$($envVars['AZURE_AI_FOUNDRY_PROJECT_NAME'])" `
            "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=$($envVars['AZURE_AI_FOUNDRY_PROJECT_ENDPOINT'])" `
            "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=$($envVars['AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME'])" `
            "AZURE_OPENAI_GPT_API_BASE=$($envVars['AZURE_OPENAI_GPT_API_BASE'])" `
            "AZURE_OPENAI_GPT_API_VERSION=$($envVars['AZURE_OPENAI_GPT_API_VERSION'])" `
            "AZURE_OPENAI_GPT_DEPLOYMENT=$($envVars['AZURE_OPENAI_GPT_DEPLOYMENT'])" `
            "AZURE_OPENAI_EMBEDDINGS_ENDPOINT=$($envVars['AZURE_OPENAI_EMBEDDINGS_ENDPOINT'])" `
            "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT=$($envVars['AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT'])" `
            "AZURE_SEARCH_SERVICE_ENDPOINT=$($envVars['AZURE_SEARCH_SERVICE_ENDPOINT'])" `
            "AZURE_SEARCH_SERVICE_NAME=$($envVars['AZURE_SEARCH_SERVICE_NAME'])" `
            "AZURE_SEARCH_INDEX_NAME=$($envVars['AZURE_SEARCH_INDEX_NAME'])" `
            "AZURE_SEARCH_VECTOR_DIMENSION=$($envVars['AZURE_SEARCH_VECTOR_DIMENSION'])" `
            "AZURE_STORAGE_ACCOUNT_NAME=$($envVars['AZURE_STORAGE_ACCOUNT_NAME'])" `
            "AZURE_BLOB_CONTAINER=$($envVars['AZURE_BLOB_CONTAINER'])" `
            "AZURE_BLOB_SIZE_THRESHOLD=$($envVars['AZURE_BLOB_SIZE_THRESHOLD'])" `
            "AZURE_CONTENT_UNDERSTANDING_ENDPOINT=$($envVars['AZURE_CONTENT_UNDERSTANDING_ENDPOINT'])" `
            "AZURE_CONTENT_UNDERSTANDING_API_VERSION=$($envVars['AZURE_CONTENT_UNDERSTANDING_API_VERSION'])" `
            "AZURE_OPENAI_GPT_API_KEY=secretref:openai-key" `
            "AZURE_OPENAI_EMBEDDINGS_KEY=secretref:openai-embed-key" `
            "AZURE_SEARCH_ADMIN_KEY=secretref:search-key" `
            "AZURE_CU_API_KEY=secretref:openai-key" `
            "VOICE_LIVE_API_KEY=secretref:azure-ai-token" `
        --output none
    
    Write-Host "✅ Environment variables configured" -ForegroundColor Green
}

# Add storage mounts
Write-Host "💾 Attaching storage volumes..." -ForegroundColor Cyan

# Create YAML for storage mounts (az CLI doesn't support this directly in create command)
$backendConfig = @"
properties:
  template:
    containers:
    - name: backend
      volumeMounts:
      - volumeName: backend-data
        mountPath: /app/data
      - volumeName: backend-uploads
        mountPath: /app/uploads
      - volumeName: backend-voice
        mountPath: /app/voice_recordings
    volumes:
    - name: backend-data
      storageType: AzureFile
      storageName: backend-data
    - name: backend-uploads
      storageType: AzureFile
      storageName: backend-uploads
    - name: backend-voice
      storageType: AzureFile
      storageName: backend-voice
"@

$backendConfig | az containerapp update --name backend --resource-group $ResourceGroup --yaml - --output none 2>$null

Write-Host "✅ Storage volumes attached" -ForegroundColor Green

# Get backend FQDNs (both external and internal)
$backendFqdn = az containerapp show `
    --name backend `
    --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn -o tsv

# Get environment default domain for internal FQDN
$envDefaultDomain = az containerapp env show `
    --name $Environment `
    --resource-group $ResourceGroup `
    --query properties.defaultDomain -o tsv

$backendInternalFqdn = "backend.internal.$envDefaultDomain"

    Write-Host "✅ Backend deployed at:" -ForegroundColor Green
    Write-Host "   External: https://$backendFqdn" -ForegroundColor Cyan
    Write-Host "   Internal: https://$backendInternalFqdn" -ForegroundColor Cyan
    Write-Host ""
} else {
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "STEP 8.5 & 9: Deploy Backend (SKIPPED)" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "⏭️  Skipping backend deployment" -ForegroundColor Yellow
    
    # Still need to get backend FQDN for frontend/visualizer builds
    $backendExists = az containerapp show --name backend --resource-group $ResourceGroup 2>$null
    if ($backendExists) {
        $backendFqdn = az containerapp show `
            --name backend `
            --resource-group $ResourceGroup `
            --query properties.configuration.ingress.fqdn -o tsv
        Write-Host "✅ Using existing backend at: https://$backendFqdn" -ForegroundColor Green
    }
    Write-Host ""
}

# ============================================================================
# STEP 9.5: Build Frontend and Visualizer with Real Backend URL
# ============================================================================
if ($deployFrontend -or $deployVisualizer) {
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "STEP 9.5: Build Frontend and Visualizer Images" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan

    # Ensure we have the backend FQDN (needed for frontend/visualizer build-time variables)
    if ([string]::IsNullOrWhiteSpace($backendFqdn)) {
        Write-Host "� Backend FQDN not set, retrieving from existing backend..." -ForegroundColor Yellow
        $backendFqdn = az containerapp show `
            --name backend `
            --resource-group $ResourceGroup `
            --query properties.configuration.ingress.fqdn -o tsv 2>$null
        
        if ([string]::IsNullOrWhiteSpace($backendFqdn)) {
            Write-Host "❌ ERROR: Backend container app not found. Cannot build frontend/visualizer without backend URL." -ForegroundColor Red
            Write-Host "💡 Please deploy backend first, or ensure backend container app exists." -ForegroundColor Yellow
            exit 1
        }
        
        Write-Host "✅ Using existing backend at: https://$backendFqdn" -ForegroundColor Green
    }

    Write-Host "🔨 Building frontend and visualizer with backend URL: https://$backendFqdn" -ForegroundColor Cyan
    Write-Host ""

if ($deployFrontend) {
    # Frontend - Use actual backend FQDN for NEXT_PUBLIC_ build-time variables
    Write-Host "  📦 Building frontend..." -ForegroundColor Yellow
    docker build -f frontend/Dockerfile `
        --build-arg NEXT_PUBLIC_A2A_API_URL="https://$backendFqdn" `
        --build-arg NEXT_PUBLIC_WEBSOCKET_URL="wss://$backendFqdn/events" `
        --build-arg NEXT_PUBLIC_DEV_MODE="false" `
        --build-arg NEXT_PUBLIC_DEBUG_LOGS="$($envVars['NEXT_PUBLIC_DEBUG_LOGS'])" `
        -t "$AcrName.azurecr.io/a2a-frontend:$tag" -t "$AcrName.azurecr.io/a2a-frontend:latest" ./frontend
    Write-Host "  ✅ Frontend built with backend URL: https://$backendFqdn" -ForegroundColor Green
}

if ($deployVisualizer) {
    # Visualizer - Use actual backend FQDN for NEXT_PUBLIC_ build-time variables
    Write-Host "  📦 Building visualizer..." -ForegroundColor Yellow
    docker build -f Visualizer/voice-a2a-fabric/Dockerfile `
        --build-arg NEXT_PUBLIC_AZURE_AI_FOUNDRY_PROJECT_ENDPOINT="$($envVars['NEXT_PUBLIC_AZURE_AI_FOUNDRY_PROJECT_ENDPOINT'])" `
        --build-arg NEXT_PUBLIC_AZURE_AI_TOKEN="$($envVars['VOICE_LIVE_API_KEY'])" `
        --build-arg NEXT_PUBLIC_VOICE_MODEL="$($envVars['NEXT_PUBLIC_VOICE_MODEL'])" `
        --build-arg NEXT_PUBLIC_A2A_API_URL="https://$backendFqdn" `
        --build-arg NEXT_PUBLIC_WEBSOCKET_URL="wss://$backendFqdn/events" `
        --build-arg NEXT_PUBLIC_DEBUG_LOGS="$($envVars['NEXT_PUBLIC_DEBUG_LOGS'])" `
        -t "$AcrName.azurecr.io/a2a-visualizer:$tag" -t "$AcrName.azurecr.io/a2a-visualizer:latest" ./Visualizer/voice-a2a-fabric
    Write-Host "  ✅ Visualizer built with backend URL: https://$backendFqdn" -ForegroundColor Green
}

    Write-Host ""
    Write-Host "📤 Pushing images to ACR..." -ForegroundColor Cyan

if ($deployFrontend) {
    docker push "$AcrName.azurecr.io/a2a-frontend:$tag"
    docker push "$AcrName.azurecr.io/a2a-frontend:latest"
    Write-Host "  ✅ Frontend pushed" -ForegroundColor Green
}

if ($deployVisualizer) {
    docker push "$AcrName.azurecr.io/a2a-visualizer:$tag"
    docker push "$AcrName.azurecr.io/a2a-visualizer:latest"
    Write-Host "  ✅ Visualizer pushed" -ForegroundColor Green
}

    Write-Host ""
} else {
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "STEP 9.5: Build Frontend/Visualizer Images (SKIPPED)" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "⏭️  Skipping frontend/visualizer builds" -ForegroundColor Yellow
    Write-Host ""
}

# ============================================================================
# STEP 10: Deploy Frontend Container App with Managed Identity
# ============================================================================
if ($deployFrontend) {
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "STEP 10: Deploy Frontend Container App" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan

    # Ensure we have the backend FQDN for frontend runtime env vars
    if ([string]::IsNullOrWhiteSpace($backendFqdn)) {
        Write-Host "🔍 Retrieving backend FQDN for frontend configuration..." -ForegroundColor Yellow
        $backendFqdn = az containerapp show `
            --name backend `
            --resource-group $ResourceGroup `
            --query properties.configuration.ingress.fqdn -o tsv 2>$null
        
        if ([string]::IsNullOrWhiteSpace($backendFqdn)) {
            Write-Host "⚠️  WARNING: Backend FQDN not found. Frontend will use placeholder URL." -ForegroundColor Yellow
            $backendFqdn = "backend-not-deployed.placeholder.io"
        }
    }

    $frontendExists = az containerapp show --name frontend --resource-group $ResourceGroup 2>$null

    if ($frontendExists) {
        Write-Host "🔄 Updating existing frontend container app..." -ForegroundColor Yellow
        az containerapp update `
            --name frontend `
            --resource-group $ResourceGroup `
            --image "$AcrName.azurecr.io/a2a-frontend:latest" `
            --set-env-vars `
                "NODE_ENV=production" `
                "NEXT_PUBLIC_A2A_API_URL=https://$backendFqdn" `
                "NEXT_PUBLIC_WEBSOCKET_URL=wss://$backendFqdn/events" `
                "NEXT_PUBLIC_DEV_MODE=$($envVars['NEXT_PUBLIC_DEV_MODE'])" `
                "NEXT_PUBLIC_DEBUG_LOGS=$($envVars['NEXT_PUBLIC_DEBUG_LOGS'])" `
                "NEXT_PUBLIC_AZURE_EVENTHUB_CONNECTION_STRING=$($envVars['NEXT_PUBLIC_AZURE_EVENTHUB_CONNECTION_STRING'])" `
                "NEXT_PUBLIC_AZURE_EVENTHUB_NAME=$($envVars['NEXT_PUBLIC_AZURE_EVENTHUB_NAME'])" `
                "NEXT_PUBLIC_AZURE_STORAGE_CONNECTION_STRING=$($envVars['NEXT_PUBLIC_AZURE_STORAGE_CONNECTION_STRING'])" `
                "NEXT_PUBLIC_AZURE_STORAGE_CONTAINER_NAME=$($envVars['NEXT_PUBLIC_AZURE_STORAGE_CONTAINER_NAME'])" `
            --output none
        Write-Host "✅ Frontend updated with environment variables" -ForegroundColor Green
    } else {
        Write-Host "🚀 Creating frontend container app..." -ForegroundColor Yellow
        
        az containerapp create `
            --name frontend `
            --resource-group $ResourceGroup `
            --environment $Environment `
            --image "$AcrName.azurecr.io/a2a-frontend:latest" `
            --target-port 3000 `
            --ingress external `
            --min-replicas 1 `
            --max-replicas 5 `
            --cpu 0.5 `
            --memory 1.0Gi `
            --registry-server "$AcrName.azurecr.io" `
            --registry-identity system `
            --system-assigned `
            --env-vars `
                "NODE_ENV=production" `
                "NEXT_PUBLIC_A2A_API_URL=https://$backendFqdn" `
                "NEXT_PUBLIC_WEBSOCKET_URL=wss://$backendFqdn/events" `
                "NEXT_PUBLIC_DEV_MODE=$($envVars['NEXT_PUBLIC_DEV_MODE'])" `
                "NEXT_PUBLIC_DEBUG_LOGS=$($envVars['NEXT_PUBLIC_DEBUG_LOGS'])" `
                "NEXT_PUBLIC_AZURE_EVENTHUB_CONNECTION_STRING=$($envVars['NEXT_PUBLIC_AZURE_EVENTHUB_CONNECTION_STRING'])" `
                "NEXT_PUBLIC_AZURE_EVENTHUB_NAME=$($envVars['NEXT_PUBLIC_AZURE_EVENTHUB_NAME'])" `
                "NEXT_PUBLIC_AZURE_STORAGE_CONNECTION_STRING=$($envVars['NEXT_PUBLIC_AZURE_STORAGE_CONNECTION_STRING'])" `
                "NEXT_PUBLIC_AZURE_STORAGE_CONTAINER_NAME=$($envVars['NEXT_PUBLIC_AZURE_STORAGE_CONTAINER_NAME'])" `
                "NEXT_PUBLIC_USE_MOCK_EVENTHUB=$($envVars['NEXT_PUBLIC_USE_MOCK_EVENTHUB'])" `
            --output none
        
        Write-Host "✅ Frontend created with system-assigned managed identity" -ForegroundColor Green
    }

# Grant ACR pull permissions
$frontendIdentity = az containerapp show `
    --name frontend `
    --resource-group $ResourceGroup `
    --query identity.principalId -o tsv

Write-Host "🔐 Granting ACR pull permissions to frontend..." -ForegroundColor Cyan
az role assignment create `
    --assignee $frontendIdentity `
    --role "AcrPull" `
    --scope $acrId `
    --output none 2>$null
Write-Host "✅ ACR permissions granted" -ForegroundColor Green

$frontendFqdn = az containerapp show `
    --name frontend `
    --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn -o tsv

    Write-Host "✅ Frontend deployed at: https://$frontendFqdn" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "STEP 10: Deploy Frontend Container App (SKIPPED)" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "⏭️  Skipping frontend deployment" -ForegroundColor Yellow
    Write-Host ""
}

# ============================================================================
# STEP 11: Deploy Visualizer Container App with Managed Identity
# ============================================================================
if ($deployVisualizer) {
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "STEP 11: Deploy Visualizer Container App" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan

    $visualizerExists = az containerapp show --name visualizer --resource-group $ResourceGroup 2>$null

    # Ensure we have the backend FQDN for visualizer runtime env vars
    if ([string]::IsNullOrWhiteSpace($backendFqdn)) {
        Write-Host "🔍 Retrieving backend FQDN for visualizer configuration..." -ForegroundColor Yellow
        $backendFqdn = az containerapp show `
            --name backend `
            --resource-group $ResourceGroup `
            --query properties.configuration.ingress.fqdn -o tsv 2>$null
        
        if ([string]::IsNullOrWhiteSpace($backendFqdn)) {
            Write-Host "⚠️  WARNING: Backend FQDN not found. Visualizer will use placeholder URL." -ForegroundColor Yellow
            $backendFqdn = "backend-not-deployed.placeholder.io"
        }
    }

    if ($visualizerExists) {
        Write-Host "🔄 Updating existing visualizer container app..." -ForegroundColor Yellow
        
        $kvUri = az keyvault show --name $KeyVaultName --resource-group $ResourceGroup --query properties.vaultUri -o tsv
        
        # First update secrets
        Write-Host "⚙️  Updating secrets..." -ForegroundColor Cyan
        az containerapp secret set `
            --name visualizer `
            --resource-group $ResourceGroup `
            --secrets `
                "ai-token=keyvaultref:${kvUri}secrets/azure-ai-token,identityref:system" `
            --output none
        
        # Then update image and environment variables
        az containerapp update `
            --name visualizer `
            --resource-group $ResourceGroup `
            --image "$AcrName.azurecr.io/a2a-visualizer:latest" `
            --set-env-vars `
                "NODE_ENV=production" `
                "NEXT_PUBLIC_A2A_API_URL=https://$backendFqdn" `
                "NEXT_PUBLIC_WEBSOCKET_URL=wss://$backendFqdn/events" `
                "NEXT_PUBLIC_AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=$($envVars['NEXT_PUBLIC_AZURE_AI_FOUNDRY_PROJECT_ENDPOINT'])" `
                "NEXT_PUBLIC_VOICE_MODEL=$($envVars['NEXT_PUBLIC_VOICE_MODEL'])" `
                "NEXT_PUBLIC_DEV_MODE=$($envVars['NEXT_PUBLIC_DEV_MODE'])" `
                "NEXT_PUBLIC_DEBUG_LOGS=$($envVars['NEXT_PUBLIC_DEBUG_LOGS'])" `
                "NEXT_PUBLIC_AZURE_AI_TOKEN=secretref:ai-token" `
            --output none
    
    Write-Host "✅ Visualizer updated with environment variables" -ForegroundColor Green
} else {
    Write-Host "🚀 Creating visualizer container app..." -ForegroundColor Yellow
    
    az containerapp create `
        --name visualizer `
        --resource-group $ResourceGroup `
        --environment $Environment `
        --image "$AcrName.azurecr.io/a2a-visualizer:latest" `
        --target-port 3000 `
        --ingress external `
        --min-replicas 1 `
        --max-replicas 3 `
        --cpu 0.5 `
        --memory 1.0Gi `
        --registry-server "$AcrName.azurecr.io" `
        --registry-identity system `
        --system-assigned `
        --output none
    
    Write-Host "✅ Visualizer created with system-assigned managed identity" -ForegroundColor Green
}

# Grant permissions
$visualizerIdentity = az containerapp show `
    --name visualizer `
    --resource-group $ResourceGroup `
    --query identity.principalId -o tsv

Write-Host "🔐 Granting ACR pull permissions to visualizer..." -ForegroundColor Cyan
az role assignment create `
    --assignee $visualizerIdentity `
    --role "AcrPull" `
    --scope $acrId `
    --output none 2>$null

Write-Host "🔐 Granting Key Vault access to visualizer..." -ForegroundColor Cyan
az role assignment create `
    --role "Key Vault Secrets User" `
    --assignee $visualizerIdentity `
    --scope $kvId `
    --output none 2>$null

Write-Host "🔐 Granting Cognitive Services access to visualizer..." -ForegroundColor Cyan
az role assignment create `
    --role "Cognitive Services User" `
    --assignee $visualizerIdentity `
    --scope "/subscriptions/$subscriptionId" `
    --output none 2>$null

Write-Host "✅ Permissions granted" -ForegroundColor Green

    # Configure environment variables for newly created visualizer (update path handles this inline)
    if (-not $visualizerExists) {
        Write-Host "⚙️  Configuring environment variables for new visualizer..." -ForegroundColor Cyan
        
        $kvUri = az keyvault show --name $KeyVaultName --resource-group $ResourceGroup --query properties.vaultUri -o tsv
        
        az containerapp update `
            --name visualizer `
            --resource-group $ResourceGroup `
            --set-env-vars `
                "NODE_ENV=production" `
                "NEXT_PUBLIC_A2A_API_URL=https://$backendFqdn" `
                "NEXT_PUBLIC_WEBSOCKET_URL=wss://$backendFqdn/events" `
                "NEXT_PUBLIC_AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=$($envVars['NEXT_PUBLIC_AZURE_AI_FOUNDRY_PROJECT_ENDPOINT'])" `
                "NEXT_PUBLIC_VOICE_MODEL=$($envVars['NEXT_PUBLIC_VOICE_MODEL'])" `
                "NEXT_PUBLIC_DEV_MODE=$($envVars['NEXT_PUBLIC_DEV_MODE'])" `
                "NEXT_PUBLIC_DEBUG_LOGS=$($envVars['NEXT_PUBLIC_DEBUG_LOGS'])" `
                "NEXT_PUBLIC_AZURE_AI_TOKEN=secretref:ai-token" `
        --secrets `
            "ai-token=keyvaultref:${kvUri}secrets/azure-ai-token,identityref:system" `
        --output none
    
    Write-Host "✅ Environment variables configured" -ForegroundColor Green
}

$visualizerFqdn = az containerapp show `
    --name visualizer `
    --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn -o tsv

    Write-Host "✅ Visualizer deployed at: https://$visualizerFqdn" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "STEP 11: Deploy Visualizer Container App (SKIPPED)" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "⏭️  Skipping visualizer deployment" -ForegroundColor Yellow
    Write-Host ""
}

# ============================================================================
# STEP 12: Deploy Agent Container Apps with Managed Identity
# ============================================================================
if ($deployRemoteAgents) {
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "STEP 12: Deploy Agent Container Apps" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan

    $agents = @(
    @{Name="authentication-agent"; Port=8101; Path="contoso_agents/authentication_agent"},
    @{Name="outage-check-agent"; Port=8102; Path="contoso_agents/outage_check_agent"},
    @{Name="modem-check-agent"; Port=8103; Path="contoso_agents/modem_check_agent"},
    @{Name="internet-plan-agent"; Port=8104; Path="contoso_agents/internet_plan_agent"},
    @{Name="network-performance-agent"; Port=8105; Path="contoso_agents/network_performance_agent"},
    @{Name="technical-dispatch-agent"; Port=8106; Path="contoso_agents/technical_dispatch_agent"}
)

Write-Host "🔨 Building and pushing agent images..." -ForegroundColor Cyan
Write-Host ""

foreach ($agent in $agents) {
    $agentName = $agent.Name
    $agentPath = $agent.Path
    
    Write-Host "  📦 Building $agentName..." -ForegroundColor Yellow
    docker build -f "$agentPath/Dockerfile" -t "$AcrName.azurecr.io/${agentName}:${tag}" -t "$AcrName.azurecr.io/${agentName}:latest" $agentPath
    
    Write-Host "  📤 Pushing $agentName..." -ForegroundColor Yellow
    docker push "$AcrName.azurecr.io/${agentName}:${tag}"
    docker push "$AcrName.azurecr.io/${agentName}:latest"
    
    Write-Host "  ✅ $agentName image ready" -ForegroundColor Green
}

Write-Host ""
Write-Host "🚀 Deploying agent container apps..." -ForegroundColor Cyan
Write-Host ""

# Get Key Vault URI for secret references
$kvUri = az keyvault show --name $KeyVaultName --resource-group $ResourceGroup --query properties.vaultUri -o tsv

$agentFqdns = @{}

foreach ($agent in $agents) {
    $agentName = $agent.Name
    $agentPort = $agent.Port
    
    Write-Host "  🚀 Deploying $agentName..." -ForegroundColor Yellow
    
    $agentExists = az containerapp show --name $agentName --resource-group $ResourceGroup 2>$null
    
    if ($agentExists) {
        Write-Host "  ⚙️  Updating secrets for $agentName..." -ForegroundColor Cyan
        
        # First update secrets
        az containerapp secret set `
            --name $agentName `
            --resource-group $ResourceGroup `
            --secrets `
                "openai-key=keyvaultref:${kvUri}secrets/azure-openai-key,identityref:system" `
            --output none 2>&1 | Out-Null
        
        Write-Host "  ⚙️  Updating image and environment for $agentName..." -ForegroundColor Cyan
        
        # Then update image and environment variables
        az containerapp update `
            --name $agentName `
            --resource-group $ResourceGroup `
            --image "${AcrName}.azurecr.io/${agentName}:latest" `
            --set-env-vars `
                "A2A_ENDPOINT=https://$agentName.internal.$envDefaultDomain" `
                "A2A_HOST=https://$backendInternalFqdn" `
                "LOG_LEVEL=$($envVars['LOG_LEVEL'])" `
                "AZURE_TENANT_ID=$($envVars['AZURE_TENANT_ID'])" `
                "AZURE_SUBSCRIPTION_ID=$($envVars['AZURE_SUBSCRIPTION_ID'])" `
                "AZURE_RESOURCE_GROUP=$($envVars['AZURE_RESOURCE_GROUP'])" `
                "AZURE_AI_FOUNDRY_RESOURCE_NAME=$($envVars['AZURE_AI_FOUNDRY_RESOURCE_NAME'])" `
                "AZURE_AI_FOUNDRY_PROJECT_NAME=$($envVars['AZURE_AI_FOUNDRY_PROJECT_NAME'])" `
                "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=$($envVars['AZURE_AI_FOUNDRY_PROJECT_ENDPOINT'])" `
                "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=$($envVars['AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME'])" `
                "AZURE_OPENAI_GPT_API_BASE=$($envVars['AZURE_OPENAI_GPT_API_BASE'])" `
                "AZURE_OPENAI_GPT_API_VERSION=$($envVars['AZURE_OPENAI_GPT_API_VERSION'])" `
                "AZURE_OPENAI_GPT_DEPLOYMENT=$($envVars['AZURE_OPENAI_GPT_DEPLOYMENT'])" `
                "AZURE_OPENAI_GPT_API_KEY=secretref:openai-key" `
            --output none
    } else {
        # Create with env vars but without secrets
        az containerapp create `
            --name $agentName `
            --resource-group $ResourceGroup `
            --environment $Environment `
            --image "$AcrName.azurecr.io/$agentName:latest" `
            --target-port $agentPort `
            --ingress internal `
            --min-replicas 1 `
            --max-replicas 3 `
            --cpu 0.5 `
            --memory 1.0Gi `
            --registry-server "$AcrName.azurecr.io" `
            --registry-identity system `
            --system-assigned `
            --env-vars `
                "A2A_ENDPOINT=https://$agentName.internal.$envDefaultDomain" `
                "A2A_HOST=https://$backendInternalFqdn" `
                "LOG_LEVEL=$($envVars['LOG_LEVEL'])" `
                "AZURE_TENANT_ID=$($envVars['AZURE_TENANT_ID'])" `
                "AZURE_SUBSCRIPTION_ID=$($envVars['AZURE_SUBSCRIPTION_ID'])" `
                "AZURE_RESOURCE_GROUP=$($envVars['AZURE_RESOURCE_GROUP'])" `
                "AZURE_AI_FOUNDRY_RESOURCE_NAME=$($envVars['AZURE_AI_FOUNDRY_RESOURCE_NAME'])" `
                "AZURE_AI_FOUNDRY_PROJECT_NAME=$($envVars['AZURE_AI_FOUNDRY_PROJECT_NAME'])" `
                "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=$($envVars['AZURE_AI_FOUNDRY_PROJECT_ENDPOINT'])" `
                "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=$($envVars['AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME'])" `
                "AZURE_OPENAI_GPT_API_BASE=$($envVars['AZURE_OPENAI_GPT_API_BASE'])" `
                "AZURE_OPENAI_GPT_API_VERSION=$($envVars['AZURE_OPENAI_GPT_API_VERSION'])" `
                "AZURE_OPENAI_GPT_DEPLOYMENT=$($envVars['AZURE_OPENAI_GPT_DEPLOYMENT'])" `
            --output none
        
        # Set secrets after creation
        az containerapp secret set `
            --name $agentName `
            --resource-group $ResourceGroup `
            --secrets `
                "openai-key=keyvaultref:${kvUri}secrets/azure-openai-key,identityref:system" `
            --output none
        
        # Update to add secret reference
        az containerapp update `
            --name $agentName `
            --resource-group $ResourceGroup `
            --set-env-vars `
                "AZURE_OPENAI_GPT_API_KEY=secretref:openai-key" `
            --output none
    }
    
    # Grant ACR pull permissions
    $agentIdentity = az containerapp show `
        --name $agentName `
        --resource-group $ResourceGroup `
        --query identity.principalId -o tsv
    
    az role assignment create `
        --assignee $agentIdentity `
        --role AcrPull `
        --scope $acrId `
        --output none 2>$null
    
    # Grant Key Vault access
    az role assignment create `
        --assignee $agentIdentity `
        --role "Key Vault Secrets User" `
        --scope $kvId `
        --output none 2>$null
    
    # Grant Azure AI User and Developer roles for AI Foundry agent creation
    if ($aiProjectResourceId) {
        az role assignment create `
            --assignee $agentIdentity `
            --role "Azure AI User" `
            --scope $aiProjectResourceId `
            --output none 2>$null
        
        az role assignment create `
            --assignee $agentIdentity `
            --role "Azure AI Developer" `
            --scope $aiProjectResourceId `
            --output none 2>$null
    } else {
        Write-Host "⚠️  Skipping AI Foundry RBAC for $agentName - resource ID not configured" -ForegroundColor Yellow
    }
    
    # Get agent internal FQDN
    $agentInternalFqdn = "$agentName.internal.$envDefaultDomain"
    $agentFqdns[$agentName] = $agentInternalFqdn
    
    Write-Host "  ✅ $agentName deployed at https://$agentInternalFqdn" -ForegroundColor Green
}

    Write-Host ""
    Write-Host "✅ All agents deployed with internal ingress" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "STEP 12: Deploy Agent Container Apps (SKIPPED)" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "⏭️  Skipping remote agent deployment" -ForegroundColor Yellow
    Write-Host ""
}

# ============================================================================
# STEP 13: Configure Backend with Agent URLs
# ============================================================================
if ($deployRemoteAgents -and $deployBackend) {
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "STEP 13: Configure Backend with Agent URLs" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan

    Write-Host "⚙️  Updating backend environment variables with agent URLs..." -ForegroundColor Cyan

# Build agent URL environment variables
$agentEnvVars = @(
    "AUTHENTICATION_AGENT_URL=https://$($agentFqdns['authentication-agent'])",
    "OUTAGE_CHECK_AGENT_URL=https://$($agentFqdns['outage-check-agent'])",
    "MODEM_CHECK_AGENT_URL=https://$($agentFqdns['modem-check-agent'])",
    "INTERNET_PLAN_AGENT_URL=https://$($agentFqdns['internet-plan-agent'])",
    "NETWORK_PERFORMANCE_AGENT_URL=https://$($agentFqdns['network-performance-agent'])",
    "TECHNICAL_DISPATCH_AGENT_URL=https://$($agentFqdns['technical-dispatch-agent'])"
)

# Get existing environment variables (only the ones we're adding)
$existingEnvVars = az containerapp show --name backend --resource-group $ResourceGroup --query "properties.template.containers[0].env[?name!='AUTHENTICATION_AGENT_URL' && name!='OUTAGE_CHECK_AGENT_URL' && name!='MODEM_CHECK_AGENT_URL' && name!='INTERNET_PLAN_AGENT_URL' && name!='NETWORK_PERFORMANCE_AGENT_URL' && name!='TECHNICAL_DISPATCH_AGENT_URL'].{name:name,value:value,secretRef:secretRef}" -o json | ConvertFrom-Json

# Build env-vars parameter
$envVarsParam = @()
foreach ($var in $existingEnvVars) {
    if ($var.secretRef) {
        $envVarsParam += "$($var.name)=secretref:$($var.secretRef)"
    } else {
        $envVarsParam += "$($var.name)=$($var.value)"
    }
}
$envVarsParam += $agentEnvVars

az containerapp update `
    --name backend `
    --resource-group $ResourceGroup `
    --set-env-vars $envVarsParam `
    --output none

    Write-Host "✅ Backend configured with agent URLs" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "STEP 13: Configure Backend with Agent URLs (SKIPPED)" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "⏭️  Skipping backend agent URL configuration" -ForegroundColor Yellow
    Write-Host ""
}

# ============================================================================
# STEP 14: Configure Auto-Scaling
# ============================================================================
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "STEP 14: Configure Auto-Scaling" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan

Write-Host "⚙️  Configuring HTTP-based auto-scaling..." -ForegroundColor Cyan

if ($deployBackend) {
    # Backend scaling
    az containerapp update `
        --name backend `
        --resource-group $ResourceGroup `
        --min-replicas 1 `
        --max-replicas 10 `
        --scale-rule-name http-rule `
        --scale-rule-type http `
        --scale-rule-http-concurrency 50 `
        --output none

    Write-Host "  ✅ Backend auto-scaling configured (1-10 replicas, 50 concurrent requests)" -ForegroundColor Green
}

if ($deployFrontend) {
    # Frontend scaling
    az containerapp update `
        --name frontend `
        --resource-group $ResourceGroup `
        --min-replicas 1 `
        --max-replicas 10 `
        --scale-rule-name http-rule `
        --scale-rule-type http `
        --scale-rule-http-concurrency 100 `
        --output none

    Write-Host "  ✅ Frontend auto-scaling configured (1-10 replicas, 100 concurrent requests)" -ForegroundColor Green
}

if ($deployVisualizer) {
    # Visualizer scaling
    az containerapp update `
        --name visualizer `
        --resource-group $ResourceGroup `
        --min-replicas 1 `
        --max-replicas 5 `
        --scale-rule-name http-rule `
        --scale-rule-type http `
        --scale-rule-http-concurrency 50 `
        --output none

    Write-Host "  ✅ Visualizer auto-scaling configured (1-5 replicas, 50 concurrent requests)" -ForegroundColor Green
}

Write-Host ""

# ============================================================================
# DEPLOYMENT SUMMARY
# ============================================================================
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "   🎉 DEPLOYMENT COMPLETED SUCCESSFULLY! 🎉" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""

Write-Host "📋 Deployment Summary:" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""

Write-Host "🌐 Application URLs:" -ForegroundColor Yellow
if ($deployBackend) {
    Write-Host "  Backend:    https://$backendFqdn" -ForegroundColor White
}
if ($deployFrontend) {
    Write-Host "  Frontend:   https://$frontendFqdn" -ForegroundColor White
}
if ($deployVisualizer) {
    Write-Host "  Visualizer: https://$visualizerFqdn" -ForegroundColor White
}
Write-Host ""

Write-Host "🔐 Managed Identities:" -ForegroundColor Yellow
if ($deployBackend) {
    Write-Host "  Backend:    $backendIdentity" -ForegroundColor White
}
if ($deployFrontend) {
    Write-Host "  Frontend:   $frontendIdentity" -ForegroundColor White
}
if ($deployVisualizer) {
    Write-Host "  Visualizer: $visualizerIdentity" -ForegroundColor White
}
Write-Host ""

Write-Host "📦 Azure Resources:" -ForegroundColor Yellow
Write-Host "  Resource Group:    $ResourceGroup" -ForegroundColor White
Write-Host "  Container Registry: $AcrName" -ForegroundColor White
Write-Host "  Key Vault:         $KeyVaultName" -ForegroundColor White
Write-Host "  Storage Account:   $StorageAccountName" -ForegroundColor White
Write-Host "  ACA Environment:   $Environment" -ForegroundColor White
Write-Host ""

Write-Host "🔑 Security Features:" -ForegroundColor Yellow
Write-Host "  ✅ Managed Identities for all services" -ForegroundColor Green
Write-Host "  ✅ Key Vault for secret management" -ForegroundColor Green
Write-Host "  ✅ ACR with managed identity authentication" -ForegroundColor Green
Write-Host "  ✅ HTTPS-only ingress" -ForegroundColor Green
Write-Host "  ✅ Azure File Storage with managed access" -ForegroundColor Green
Write-Host ""

Write-Host "📊 Useful Commands:" -ForegroundColor Yellow
Write-Host ""
Write-Host "View logs:" -ForegroundColor Cyan
if ($deployBackend) {
    Write-Host "  az containerapp logs show --name backend --resource-group $ResourceGroup --follow" -ForegroundColor White
}
if ($deployFrontend) {
    Write-Host "  az containerapp logs show --name frontend --resource-group $ResourceGroup --follow" -ForegroundColor White
}
if ($deployVisualizer) {
    Write-Host "  az containerapp logs show --name visualizer --resource-group $ResourceGroup --follow" -ForegroundColor White
}
if ($deployRemoteAgents) {
    Write-Host "  az containerapp logs show --name authentication-agent --resource-group $ResourceGroup --follow" -ForegroundColor White
}
Write-Host ""

if ($deployBackend) {
    Write-Host "Update deployment:" -ForegroundColor Cyan
    Write-Host "  az containerapp update --name backend --resource-group $ResourceGroup --image $AcrName.azurecr.io/a2a-backend:latest" -ForegroundColor White
    Write-Host ""

    Write-Host "Scale manually:" -ForegroundColor Cyan
    Write-Host "  az containerapp update --name backend --resource-group $ResourceGroup --min-replicas 2 --max-replicas 20" -ForegroundColor White
    Write-Host ""
}

Write-Host "View in Azure Portal:" -ForegroundColor Cyan
Write-Host "  https://portal.azure.com/#@/resource/subscriptions/$($currentSub.id)/resourceGroups/$ResourceGroup/overview" -ForegroundColor White
Write-Host ""

Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "✨ Your A2A system is now running in Azure Container Apps! ✨" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
