#!/bin/bash

# Azure Container Apps Deployment Script (Bash version for Mac/Linux)
# This script automates the deployment of A2A system to Azure Container Apps

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Default values (can be overridden)
RESOURCE_GROUP="${1:-rg-a2a-prod}"
LOCATION="${2:-eastus}"
ACR_NAME="${3:-}"
ENVIRONMENT="${4:-env-a2a-prod}"

echo -e "${CYAN}🚀 A2A System - Azure Container Apps Deployment${NC}"
echo "================================================"
echo ""

# Check if Azure CLI is installed
if ! command -v az &> /dev/null; then
    echo -e "${RED}❌ Azure CLI not found. Please install it first.${NC}"
    exit 1
fi

# Check if Docker is running
if ! docker info &> /dev/null; then
    echo -e "${RED}❌ Docker is not running. Please start Docker Desktop.${NC}"
    exit 1
fi

# Check if logged in
if ! az account show &> /dev/null; then
    echo -e "${YELLOW}❌ Not logged in to Azure. Running 'az login'...${NC}"
    az login
fi

echo -e "${GREEN}✅ Logged in to Azure${NC}"
SUBSCRIPTION=$(az account show --query name -o tsv)
echo "   Subscription: $SUBSCRIPTION"
echo ""

# Get ACR name if not provided
if [ -z "$ACR_NAME" ]; then
    echo -e "${YELLOW}Enter a unique name for Azure Container Registry (letters and numbers only):${NC}"
    read -p "ACR Name: " ACR_NAME
fi

echo ""
echo "Deployment Configuration:"
echo "  Resource Group: $RESOURCE_GROUP"
echo "  Location: $LOCATION"
echo "  ACR Name: $ACR_NAME"
echo "  Environment: $ENVIRONMENT"
echo ""
read -p "Continue with deployment? (y/n): " CONFIRM
if [ "$CONFIRM" != "y" ]; then
    echo "Deployment cancelled."
    exit 0
fi

# Step 1: Create Resource Group
echo ""
echo -e "${CYAN}📦 Creating resource group: $RESOURCE_GROUP${NC}"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none
echo -e "${GREEN}✅ Resource group created${NC}"

# Step 2: Create Azure Container Registry
echo ""
echo -e "${CYAN}🐳 Creating Azure Container Registry: $ACR_NAME${NC}"
az acr create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$ACR_NAME" \
    --sku Basic \
    --admin-enabled true \
    --output none
echo -e "${GREEN}✅ ACR created${NC}"

# Step 3: Login to ACR
echo ""
echo -e "${CYAN}🔐 Logging in to ACR...${NC}"
az acr login --name "$ACR_NAME"

# Step 4: Build and push images
echo ""
echo -e "${CYAN}🔨 Building Docker images...${NC}"

cd /Users/simonlacasse/Downloads/sl-a2a-main2

echo "  Building backend..."
docker build -f backend/Dockerfile -t "$ACR_NAME.azurecr.io/a2a-backend:latest" .

echo "  Building frontend..."
docker build -f frontend/Dockerfile -t "$ACR_NAME.azurecr.io/a2a-frontend:latest" ./frontend

echo ""
echo -e "${CYAN}📤 Pushing images to ACR...${NC}"
docker push "$ACR_NAME.azurecr.io/a2a-backend:latest"
docker push "$ACR_NAME.azurecr.io/a2a-frontend:latest"
echo -e "${GREEN}✅ Images pushed${NC}"

# Step 5: Create Container Apps Environment
echo ""
echo -e "${CYAN}🌍 Creating Container Apps Environment: $ENVIRONMENT${NC}"
az containerapp env create \
    --name "$ENVIRONMENT" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --output none
echo -e "${GREEN}✅ Environment created${NC}"

# Step 6: Get Azure credentials
echo ""
echo -e "${YELLOW}Enter Azure configuration values (from your .env file):${NC}"
read -p "Azure AI Foundry Project Endpoint: " AZURE_AI_ENDPOINT
read -s -p "Azure OpenAI API Key: " AZURE_OPENAI_KEY
echo ""
read -p "Azure OpenAI Deployment Name (e.g., gpt-4o): " AZURE_OPENAI_DEPLOYMENT

# Step 7: Deploy Backend
echo ""
echo -e "${CYAN}🚀 Deploying Backend...${NC}"
az containerapp create \
    --name backend \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$ENVIRONMENT" \
    --image "$ACR_NAME.azurecr.io/a2a-backend:latest" \
    --target-port 12000 \
    --ingress external \
    --min-replicas 1 \
    --max-replicas 3 \
    --cpu 1.0 \
    --memory 2.0Gi \
    --registry-server "$ACR_NAME.azurecr.io" \
    --env-vars \
        "A2A_UI_HOST=0.0.0.0" \
        "A2A_UI_PORT=12000" \
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=$AZURE_AI_ENDPOINT" \
        "AZURE_OPENAI_API_KEY=$AZURE_OPENAI_KEY" \
        "AZURE_OPENAI_DEPLOYMENT_NAME=$AZURE_OPENAI_DEPLOYMENT" \
    --output none

# Get backend FQDN
BACKEND_FQDN=$(az containerapp show \
    --name backend \
    --resource-group "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn -o tsv)

echo -e "${GREEN}✅ Backend deployed at: https://$BACKEND_FQDN${NC}"

# Step 8: Deploy Frontend
echo ""
echo -e "${CYAN}🚀 Deploying Frontend...${NC}"
az containerapp create \
    --name frontend \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$ENVIRONMENT" \
    --image "$ACR_NAME.azurecr.io/a2a-frontend:latest" \
    --target-port 3000 \
    --ingress external \
    --min-replicas 1 \
    --max-replicas 3 \
    --cpu 0.5 \
    --memory 1.0Gi \
    --registry-server "$ACR_NAME.azurecr.io" \
    --env-vars \
        "NODE_ENV=production" \
        "NEXT_PUBLIC_A2A_API_URL=https://$BACKEND_FQDN" \
        "NEXT_PUBLIC_WEBSOCKET_URL=wss://$BACKEND_FQDN/events" \
        "NEXT_PUBLIC_DEV_MODE=false" \
    --output none

FRONTEND_FQDN=$(az containerapp show \
    --name frontend \
    --resource-group "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn -o tsv)

echo -e "${GREEN}✅ Frontend deployed at: https://$FRONTEND_FQDN${NC}"

# Summary
echo ""
echo "========================================"
echo -e "${GREEN}🎉 Deployment Complete!${NC}"
echo "========================================"
echo ""
echo "Your services are available at:"
echo -e "  ${CYAN}Backend:  https://$BACKEND_FQDN${NC}"
echo -e "  ${CYAN}Frontend: https://$FRONTEND_FQDN${NC}"
echo ""
echo "View logs with:"
echo "  az containerapp logs show --name backend --resource-group $RESOURCE_GROUP --follow"
echo "  az containerapp logs show --name frontend --resource-group $RESOURCE_GROUP --follow"
echo ""
echo "To clean up resources:"
echo "  az group delete --name $RESOURCE_GROUP --yes --no-wait"

