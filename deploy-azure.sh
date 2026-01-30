#!/bin/bash

# Azure Container Apps Deployment Script - Separate Servers Architecture
# This script automates the deployment of A2A system with proper microservices architecture
#
# Architecture:
# - WebSocket Server (port 8080) - Handles real-time event streaming
# - Backend API (port 12000) - Main orchestration and business logic
# - Frontend (port 3000) - User interface
#
# Usage:
#   ./deploy-azure.sh -r RESOURCE_GROUP -l LOCATION -a ACR_NAME -e ENVIRONMENT

# Colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# Default values
MANAGED_IDENTITY="a2a-registry-uami"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -r|--resource-group)
            RESOURCE_GROUP="$2"
            shift 2
            ;;
        -l|--location)
            LOCATION="$2"
            shift 2
            ;;
        -a|--acr-name)
            ACR_NAME="$2"
            shift 2
            ;;
        -e|--environment)
            ENVIRONMENT="$2"
            shift 2
            ;;
        -i|--managed-identity)
            MANAGED_IDENTITY="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: ./deploy-azure.sh -r RESOURCE_GROUP -l LOCATION -a ACR_NAME -e ENVIRONMENT [options]"
            echo ""
            echo "Required:"
            echo "  -r, --resource-group     Resource group name"
            echo "  -l, --location           Azure location (e.g., westus2)"
            echo "  -a, --acr-name           Azure Container Registry name"
            echo "  -e, --environment        Container Apps Environment name"
            echo ""
            echo "Optional:"
            echo "  -i, --managed-identity   Managed Identity name (default: a2a-registry-uami)"
            echo "  -h, --help               Show this help message"
            echo ""
            echo "Example:"
            echo "  ./deploy-azure.sh -r rg-a2a-prod -l westus2 -a a2awestuslab -e env-a2a-final"
            exit 0
            ;;
        *)
            echo -e "${RED}❌ Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Check required parameters
if [ -z "$RESOURCE_GROUP" ] || [ -z "$LOCATION" ] || [ -z "$ACR_NAME" ] || [ -z "$ENVIRONMENT" ]; then
    echo -e "${RED}❌ Missing required parameters${NC}"
    echo ""
    echo "Usage: ./deploy-azure.sh -r RESOURCE_GROUP -l LOCATION -a ACR_NAME -e ENVIRONMENT"
    echo "Run './deploy-azure.sh --help' for more information"
    exit 1
fi

echo -e "${CYAN}🚀 A2A System - Separate Servers Deployment${NC}"
echo -e "${CYAN}=============================================${NC}"
echo ""
echo -e "${YELLOW}📋 Configuration:${NC}"
echo -e "${WHITE}  Resource Group: $RESOURCE_GROUP${NC}"
echo -e "${WHITE}  Location: $LOCATION${NC}"
echo -e "${WHITE}  ACR Name: $ACR_NAME${NC}"
echo -e "${WHITE}  Environment: $ENVIRONMENT${NC}"
echo -e "${WHITE}  Managed Identity: $MANAGED_IDENTITY${NC}"
echo ""

# Check if Azure CLI is installed
if ! command -v az &> /dev/null; then
    echo -e "${RED}❌ Azure CLI not found. Please install it first.${NC}"
    exit 1
fi

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker not found. Please install Docker Desktop first.${NC}"
    exit 1
fi

# Check if logged in
ACCOUNT=$(az account show 2>/dev/null)
if [ -z "$ACCOUNT" ]; then
    echo -e "${YELLOW}❌ Not logged in to Azure. Running 'az login'...${NC}"
    az login
fi

echo -e "${GREEN}✅ Logged in to Azure${NC}"
echo ""

# Step 1: Create Resource Group (if it doesn't exist)
echo -e "${CYAN}📦 Ensuring resource group exists: $RESOURCE_GROUP${NC}"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none
echo -e "${GREEN}✅ Resource group ready${NC}"
echo ""

# Step 2: Create Azure Container Registry (if it doesn't exist)
echo -e "${CYAN}🐳 Ensuring Azure Container Registry exists: $ACR_NAME${NC}"
ACR_EXISTS=$(az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" 2>/dev/null)
if [ -z "$ACR_EXISTS" ]; then
    az acr create \
        --resource-group "$RESOURCE_GROUP" \
        --name "$ACR_NAME" \
        --sku Basic \
        --admin-enabled true \
        --output none
    echo -e "${GREEN}✅ ACR created${NC}"
else
    echo -e "${GREEN}✅ ACR already exists${NC}"
fi
echo ""

# Step 3: Create User-Assigned Managed Identity (if it doesn't exist)
echo -e "${CYAN}🔐 Ensuring Managed Identity exists: $MANAGED_IDENTITY${NC}"
IDENTITY_EXISTS=$(az identity show --name "$MANAGED_IDENTITY" --resource-group "$RESOURCE_GROUP" 2>/dev/null)
if [ -z "$IDENTITY_EXISTS" ]; then
    az identity create \
        --name "$MANAGED_IDENTITY" \
        --resource-group "$RESOURCE_GROUP" \
        --location "$LOCATION" \
        --output none
    echo -e "${GREEN}✅ Managed Identity created${NC}"
    
    # Grant AcrPull role to managed identity
    IDENTITY_PRINCIPAL_ID=$(az identity show --name "$MANAGED_IDENTITY" --resource-group "$RESOURCE_GROUP" --query principalId -o tsv)
    ACR_ID=$(az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --query id -o tsv)
    
    echo -e "${YELLOW}  Granting AcrPull permissions...${NC}"
    az role assignment create \
        --assignee "$IDENTITY_PRINCIPAL_ID" \
        --role AcrPull \
        --scope "$ACR_ID" \
        --output none
    
    echo -e "${YELLOW}  ⚠️  Waiting 30 seconds for permissions to propagate...${NC}"
    sleep 30
else
    echo -e "${GREEN}✅ Managed Identity already exists${NC}"
fi
echo ""

# Step 4: Login to ACR
echo -e "${CYAN}🔐 Logging in to ACR...${NC}"
az acr login --name "$ACR_NAME"
echo -e "${GREEN}✅ Logged in to ACR${NC}"
echo ""

# Step 5: Prompt for Azure configuration (with .env file fallback)
echo -e "${CYAN}🔑 Azure Configuration${NC}"
echo -e "${YELLOW}Enter the following values (press Enter to use .env file defaults):${NC}"
echo ""

# Try to read from .env file as defaults
if [ -f ".env" ]; then
    DEFAULT_AI_ENDPOINT=$(grep "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    DEFAULT_AI_MODEL=$(grep "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    DEFAULT_OPENAI_BASE=$(grep "AZURE_OPENAI_GPT_API_BASE" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    DEFAULT_OPENAI_KEY=$(grep "AZURE_OPENAI_GPT_API_KEY" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    DEFAULT_OPENAI_DEPLOYMENT=$(grep "AZURE_OPENAI_GPT_DEPLOYMENT" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    DEFAULT_EMBEDDINGS_ENDPOINT=$(grep "AZURE_OPENAI_EMBEDDINGS_ENDPOINT" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    DEFAULT_EMBEDDINGS_DEPLOYMENT=$(grep "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    DEFAULT_EMBEDDINGS_KEY=$(grep "AZURE_OPENAI_EMBEDDINGS_KEY" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    # Azure Search (Memory Service) configuration
    DEFAULT_SEARCH_ENDPOINT=$(grep "AZURE_SEARCH_SERVICE_ENDPOINT" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    DEFAULT_SEARCH_ADMIN_KEY=$(grep "AZURE_SEARCH_ADMIN_KEY" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    DEFAULT_SEARCH_INDEX_NAME=$(grep "AZURE_SEARCH_INDEX_NAME" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    # Bing Grounding configuration
    DEFAULT_BING_CONNECTION_ID=$(grep "BING_CONNECTION_ID" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
fi

read -p "Azure AI Foundry Project Endpoint [$DEFAULT_AI_ENDPOINT]: " AZURE_AI_ENDPOINT
AZURE_AI_ENDPOINT=${AZURE_AI_ENDPOINT:-$DEFAULT_AI_ENDPOINT}

read -p "Azure AI Agent Model Deployment Name [$DEFAULT_AI_MODEL]: " AZURE_AI_MODEL_DEPLOYMENT
AZURE_AI_MODEL_DEPLOYMENT=${AZURE_AI_MODEL_DEPLOYMENT:-$DEFAULT_AI_MODEL}

read -p "Azure OpenAI API Base URL [$DEFAULT_OPENAI_BASE]: " AZURE_OPENAI_BASE
AZURE_OPENAI_BASE=${AZURE_OPENAI_BASE:-$DEFAULT_OPENAI_BASE}

read -s -p "Azure OpenAI API Key: " AZURE_OPENAI_KEY
AZURE_OPENAI_KEY=${AZURE_OPENAI_KEY:-$DEFAULT_OPENAI_KEY}
echo ""

read -p "Azure OpenAI Deployment Name [$DEFAULT_OPENAI_DEPLOYMENT]: " AZURE_OPENAI_DEPLOYMENT
AZURE_OPENAI_DEPLOYMENT=${AZURE_OPENAI_DEPLOYMENT:-$DEFAULT_OPENAI_DEPLOYMENT}

read -p "Azure OpenAI Embeddings Endpoint [$DEFAULT_EMBEDDINGS_ENDPOINT]: " AZURE_EMBEDDINGS_ENDPOINT
AZURE_EMBEDDINGS_ENDPOINT=${AZURE_EMBEDDINGS_ENDPOINT:-$DEFAULT_EMBEDDINGS_ENDPOINT}

read -p "Azure Embeddings Deployment Name [$DEFAULT_EMBEDDINGS_DEPLOYMENT]: " AZURE_EMBEDDINGS_DEPLOYMENT
AZURE_EMBEDDINGS_DEPLOYMENT=${AZURE_EMBEDDINGS_DEPLOYMENT:-$DEFAULT_EMBEDDINGS_DEPLOYMENT}

read -s -p "Azure Embeddings Key: " AZURE_EMBEDDINGS_KEY
AZURE_EMBEDDINGS_KEY=${AZURE_EMBEDDINGS_KEY:-$DEFAULT_EMBEDDINGS_KEY}
echo ""

# Azure Search (Memory Service) configuration
echo ""
echo -e "${CYAN}🔍 Azure Search (Memory Service) Configuration${NC}"
read -p "Azure Search Service Endpoint [$DEFAULT_SEARCH_ENDPOINT]: " AZURE_SEARCH_ENDPOINT
AZURE_SEARCH_ENDPOINT=${AZURE_SEARCH_ENDPOINT:-$DEFAULT_SEARCH_ENDPOINT}

read -s -p "Azure Search Admin Key: " AZURE_SEARCH_KEY
AZURE_SEARCH_KEY=${AZURE_SEARCH_KEY:-$DEFAULT_SEARCH_ADMIN_KEY}
echo ""

read -p "Azure Search Index Name [$DEFAULT_SEARCH_INDEX_NAME]: " AZURE_SEARCH_INDEX
AZURE_SEARCH_INDEX=${AZURE_SEARCH_INDEX:-$DEFAULT_SEARCH_INDEX_NAME}

# Bing Grounding (Web Search) configuration
echo ""
echo -e "${CYAN}🌐 Bing Grounding (Web Search) Configuration${NC}"
echo -e "${YELLOW}  (Optional - leave blank to disable web search capability)${NC}"
read -p "Bing Connection ID [$DEFAULT_BING_CONNECTION_ID]: " BING_CONNECTION_ID
BING_CONNECTION_ID=${BING_CONNECTION_ID:-$DEFAULT_BING_CONNECTION_ID}

echo ""

# Generate timestamp for image tags
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

# Step 6: Build and push images
echo -e "${CYAN}🔨 Building Docker images for linux/amd64 platform...${NC}"
echo ""

echo -e "${YELLOW}  [1/3] Building WebSocket server...${NC}"
docker buildx build --platform linux/amd64 \
    -f backend/Dockerfile.websocket \
    -t "$ACR_NAME.azurecr.io/a2a-websocket:$TIMESTAMP" \
    -t "$ACR_NAME.azurecr.io/a2a-websocket:latest" \
    --load .

echo -e "${YELLOW}  [2/3] Building backend API...${NC}"
docker buildx build --platform linux/amd64 \
    -f backend/Dockerfile \
    -t "$ACR_NAME.azurecr.io/a2a-backend:$TIMESTAMP" \
    -t "$ACR_NAME.azurecr.io/a2a-backend:latest" \
    --load .

echo -e "${YELLOW}  [3/3] Building frontend (temp)...${NC}"
# Frontend will be built again with proper URLs after we get the FQDNs
docker buildx build --platform linux/amd64 \
    -t "$ACR_NAME.azurecr.io/a2a-frontend:temp" \
    --load ./frontend

echo ""
echo -e "${CYAN}📤 Pushing images to ACR...${NC}"
docker push "$ACR_NAME.azurecr.io/a2a-websocket:$TIMESTAMP"
docker push "$ACR_NAME.azurecr.io/a2a-websocket:latest"
docker push "$ACR_NAME.azurecr.io/a2a-backend:$TIMESTAMP"
docker push "$ACR_NAME.azurecr.io/a2a-backend:latest"
echo -e "${GREEN}✅ Images pushed${NC}"
echo ""

# Step 7: Create Container Apps Environment (if it doesn't exist)
echo -e "${CYAN}🌍 Ensuring Container Apps Environment exists: $ENVIRONMENT${NC}"
ENV_EXISTS=$(az containerapp env show --name "$ENVIRONMENT" --resource-group "$RESOURCE_GROUP" 2>/dev/null)
if [ -z "$ENV_EXISTS" ]; then
    az containerapp env create \
        --name "$ENVIRONMENT" \
        --resource-group "$RESOURCE_GROUP" \
        --location "$LOCATION" \
        --output none
    echo -e "${GREEN}✅ Environment created${NC}"
else
    echo -e "${GREEN}✅ Environment already exists${NC}"
fi
echo ""

# Step 8: Deploy WebSocket Server
echo -e "${CYAN}🔌 Deploying WebSocket Server...${NC}"

# Note: WebSocket needs to know backend URL, but backend doesn't exist yet on first deploy
# We'll deploy it first, then update with env vars after backend is deployed
WS_EXISTS=$(az containerapp show --name websocket-uami --resource-group "$RESOURCE_GROUP" 2>/dev/null)
if [ -n "$WS_EXISTS" ]; then
    # Get backend FQDN for WebSocket configuration
    BACKEND_FQDN=$(az containerapp show \
        --name backend-uami \
        --resource-group "$RESOURCE_GROUP" \
        --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null)
    
    if [ -n "$BACKEND_FQDN" ]; then
        az containerapp update \
            --name websocket-uami \
            --resource-group "$RESOURCE_GROUP" \
            --image "$ACR_NAME.azurecr.io/a2a-websocket:$TIMESTAMP" \
            --set-env-vars \
                "BACKEND_HOST=$BACKEND_FQDN" \
                "BACKEND_PORT=443" \
            --output none
        echo -e "${GREEN}✅ WebSocket server updated with backend URL${NC}"
    else
        az containerapp update \
            --name websocket-uami \
            --resource-group "$RESOURCE_GROUP" \
            --image "$ACR_NAME.azurecr.io/a2a-websocket:$TIMESTAMP" \
            --output none
        echo -e "${YELLOW}⚠️  WebSocket server updated (backend URL will be set later)${NC}"
    fi
else
    az containerapp create \
        --name websocket-uami \
        --resource-group "$RESOURCE_GROUP" \
        --environment "$ENVIRONMENT" \
        --image "$ACR_NAME.azurecr.io/a2a-websocket:$TIMESTAMP" \
        --registry-server "$ACR_NAME.azurecr.io" \
        --user-assigned "$MANAGED_IDENTITY" \
        --target-port 8080 \
        --ingress external \
        --min-replicas 1 \
        --max-replicas 1 \
        --cpu 0.5 \
        --memory 1.0Gi \
        --output none
    echo -e "${GREEN}✅ WebSocket server deployed (will configure backend URL after backend deployment)${NC}"
fi

WS_FQDN=$(az containerapp show \
    --name websocket-uami \
    --resource-group "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn -o tsv)

echo -e "${WHITE}  📍 WebSocket FQDN: $WS_FQDN${NC}"
echo ""

# Step 9: Deploy Backend API
echo -e "${CYAN}🚀 Deploying Backend API...${NC}"
BACKEND_EXISTS=$(az containerapp show --name backend-uami --resource-group "$RESOURCE_GROUP" 2>/dev/null)
if [ -n "$BACKEND_EXISTS" ]; then
    az containerapp update \
        --name backend-uami \
        --resource-group "$RESOURCE_GROUP" \
        --image "$ACR_NAME.azurecr.io/a2a-backend:$TIMESTAMP" \
        --set-env-vars \
            "WEBSOCKET_SERVER_URL=https://$WS_FQDN" \
            "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=$AZURE_AI_ENDPOINT" \
            "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=$AZURE_AI_MODEL_DEPLOYMENT" \
            "AZURE_OPENAI_GPT_API_BASE=$AZURE_OPENAI_BASE" \
            "AZURE_OPENAI_GPT_API_KEY=$AZURE_OPENAI_KEY" \
            "AZURE_OPENAI_GPT_DEPLOYMENT=$AZURE_OPENAI_DEPLOYMENT" \
            "AZURE_OPENAI_EMBEDDINGS_ENDPOINT=$AZURE_EMBEDDINGS_ENDPOINT" \
            "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT=$AZURE_EMBEDDINGS_DEPLOYMENT" \
            "AZURE_OPENAI_EMBEDDINGS_KEY=$AZURE_EMBEDDINGS_KEY" \
            "AZURE_SEARCH_SERVICE_ENDPOINT=$AZURE_SEARCH_ENDPOINT" \
            "AZURE_SEARCH_ADMIN_KEY=$AZURE_SEARCH_KEY" \
            "AZURE_SEARCH_INDEX_NAME=$AZURE_SEARCH_INDEX" \
            "BING_CONNECTION_ID=$BING_CONNECTION_ID" \
            "A2A_HOST=FOUNDRY" \
            "VERBOSE_LOGGING=true" \
        --output none
    echo -e "${GREEN}✅ Backend updated${NC}"
else
    az containerapp create \
        --name backend-uami \
        --resource-group "$RESOURCE_GROUP" \
        --environment "$ENVIRONMENT" \
        --image "$ACR_NAME.azurecr.io/a2a-backend:$TIMESTAMP" \
        --registry-server "$ACR_NAME.azurecr.io" \
        --user-assigned "$MANAGED_IDENTITY" \
        --target-port 12000 \
        --ingress external \
        --min-replicas 1 \
        --max-replicas 1 \
        --cpu 1.0 \
        --memory 2.0Gi \
        --env-vars \
            "WEBSOCKET_SERVER_URL=https://$WS_FQDN" \
            "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=$AZURE_AI_ENDPOINT" \
            "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=$AZURE_AI_MODEL_DEPLOYMENT" \
            "AZURE_OPENAI_GPT_API_BASE=$AZURE_OPENAI_BASE" \
            "AZURE_OPENAI_GPT_API_KEY=$AZURE_OPENAI_KEY" \
            "AZURE_OPENAI_GPT_DEPLOYMENT=$AZURE_OPENAI_DEPLOYMENT" \
            "AZURE_OPENAI_EMBEDDINGS_ENDPOINT=$AZURE_EMBEDDINGS_ENDPOINT" \
            "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT=$AZURE_EMBEDDINGS_DEPLOYMENT" \
            "AZURE_OPENAI_EMBEDDINGS_KEY=$AZURE_EMBEDDINGS_KEY" \
            "AZURE_SEARCH_SERVICE_ENDPOINT=$AZURE_SEARCH_ENDPOINT" \
            "AZURE_SEARCH_ADMIN_KEY=$AZURE_SEARCH_KEY" \
            "AZURE_SEARCH_INDEX_NAME=$AZURE_SEARCH_INDEX" \
            "BING_CONNECTION_ID=$BING_CONNECTION_ID" \
            "A2A_HOST=FOUNDRY" \
            "VERBOSE_LOGGING=true" \
        --output none
    echo -e "${GREEN}✅ Backend deployed${NC}"
fi

BACKEND_FQDN=$(az containerapp show \
    --name backend-uami \
    --resource-group "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn -o tsv)

echo -e "${WHITE}  📍 Backend FQDN: $BACKEND_FQDN${NC}"
echo ""

# Step 9.5: Update WebSocket Server with Backend URL
echo -e "${CYAN}🔧 Configuring WebSocket server with backend URL...${NC}"
az containerapp update \
    --name websocket-uami \
    --resource-group "$RESOURCE_GROUP" \
    --set-env-vars \
        "BACKEND_HOST=$BACKEND_FQDN" \
        "BACKEND_PORT=443" \
    --output none
echo -e "${GREEN}✅ WebSocket server configured with backend URL${NC}"
echo ""

# Step 10: Build and Deploy Frontend with correct URLs
echo -e "${CYAN}🎨 Building frontend with correct URLs...${NC}"
docker buildx build --platform linux/amd64 \
    --build-arg NEXT_PUBLIC_A2A_API_URL="https://$BACKEND_FQDN" \
    --build-arg NEXT_PUBLIC_WEBSOCKET_URL="wss://$WS_FQDN/events" \
    --build-arg NEXT_PUBLIC_DEV_MODE="false" \
    --build-arg BUILDCACHE_BUST="$TIMESTAMP" \
    -t "$ACR_NAME.azurecr.io/a2a-frontend:$TIMESTAMP" \
    -t "$ACR_NAME.azurecr.io/a2a-frontend:latest" \
    --load ./frontend

echo -e "${CYAN}📤 Pushing frontend image...${NC}"
docker push "$ACR_NAME.azurecr.io/a2a-frontend:$TIMESTAMP"
docker push "$ACR_NAME.azurecr.io/a2a-frontend:latest"

echo -e "${CYAN}🚀 Deploying Frontend...${NC}"
FRONTEND_EXISTS=$(az containerapp show --name frontend-uami --resource-group "$RESOURCE_GROUP" 2>/dev/null)
if [ -n "$FRONTEND_EXISTS" ]; then
    az containerapp update \
        --name frontend-uami \
        --resource-group "$RESOURCE_GROUP" \
        --image "$ACR_NAME.azurecr.io/a2a-frontend:$TIMESTAMP" \
        --output none
    echo -e "${GREEN}✅ Frontend updated${NC}"
else
    az containerapp create \
        --name frontend-uami \
        --resource-group "$RESOURCE_GROUP" \
        --environment "$ENVIRONMENT" \
        --image "$ACR_NAME.azurecr.io/a2a-frontend:$TIMESTAMP" \
        --registry-server "$ACR_NAME.azurecr.io" \
        --user-assigned "$MANAGED_IDENTITY" \
        --target-port 3000 \
        --ingress external \
        --min-replicas 1 \
        --max-replicas 1 \
        --cpu 0.5 \
        --memory 1.0Gi \
        --output none
    echo -e "${GREEN}✅ Frontend deployed${NC}"
fi

FRONTEND_FQDN=$(az containerapp show \
    --name frontend-uami \
    --resource-group "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn -o tsv)

echo -e "${WHITE}  📍 Frontend FQDN: $FRONTEND_FQDN${NC}"
echo ""

# Summary
echo -e "${CYAN}========================================${NC}"
echo -e "${GREEN}🎉 Deployment Complete!${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""
echo -e "${WHITE}Your services are available at:${NC}"
echo -e "${CYAN}  Frontend:   https://$FRONTEND_FQDN${NC}"
echo -e "${CYAN}  Backend:    https://$BACKEND_FQDN${NC}"
echo -e "${CYAN}  WebSocket:  wss://$WS_FQDN/events${NC}"
echo ""
echo -e "${YELLOW}Architecture:${NC}"
echo -e "${WHITE}  ✓ Separate WebSocket server (port 8080)${NC}"
echo -e "${WHITE}  ✓ Backend API server (port 12000)${NC}"
echo -e "${WHITE}  ✓ Frontend (port 3000)${NC}"
echo -e "${WHITE}  ✓ All images built for linux/amd64${NC}"
echo -e "${WHITE}  ✓ Managed Identity authentication${NC}"
echo ""
echo -e "${YELLOW}View logs with:${NC}"
echo -e "${WHITE}  az containerapp logs show --name websocket-uami --resource-group $RESOURCE_GROUP --follow${NC}"
echo -e "${WHITE}  az containerapp logs show --name backend-uami --resource-group $RESOURCE_GROUP --follow${NC}"
echo -e "${WHITE}  az containerapp logs show --name frontend-uami --resource-group $RESOURCE_GROUP --follow${NC}"
echo ""
echo -e "${YELLOW}Test login credentials:${NC}"
echo -e "${WHITE}  Email: test@example.com${NC}"
echo -e "${WHITE}  Password: password123${NC}"
echo ""
echo -e "${YELLOW}To clean up resources:${NC}"
echo -e "${WHITE}  az group delete --name $RESOURCE_GROUP --yes --no-wait${NC}"
echo ""
