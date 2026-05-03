#!/bin/bash

# Deploy Frontend Light (Voice UI) to Azure Container Apps
# Usage: ./deploy-frontend-light.sh [options]

# Default values
RESOURCE_GROUP="rg-a2a-prod"
ACR_NAME="a2awestuslab"
ENVIRONMENT="env-a2a-final"
CONTAINER_NAME="frontend-light"
PORT=3001

# Colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -r|--resource-group)
            RESOURCE_GROUP="$2"
            shift 2
            ;;
        --acr)
            ACR_NAME="$2"
            shift 2
            ;;
        -e|--environment)
            ENVIRONMENT="$2"
            shift 2
            ;;
        -n|--name)
            CONTAINER_NAME="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: ./deploy-frontend-light.sh [options]"
            echo ""
            echo "Optional:"
            echo "  -r, --resource-group     Resource group (default: rg-a2a-prod)"
            echo "  --acr                    ACR name (default: a2awestuslab)"
            echo "  -e, --environment        Environment name (default: env-a2a-final)"
            echo "  -n, --name               Container app name (default: frontend-light)"
            echo "  -h, --help               Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}❌ Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

FRONTEND_PATH="frontend_mobile"

echo -e "${CYAN}🎙️  Deploying Frontend Light (Voice UI)${NC}"
echo -e "${CYAN}=========================================${NC}"
echo -e "${WHITE}  Container Name: $CONTAINER_NAME${NC}"
echo -e "${WHITE}  Port: $PORT${NC}"
echo -e "${WHITE}  Resource Group: $RESOURCE_GROUP${NC}"
echo -e "${WHITE}  ACR: $ACR_NAME${NC}"
echo ""

# Check if frontend_light directory exists
if [ ! -d "$FRONTEND_PATH" ]; then
    echo -e "${RED}❌ Frontend Light not found at: $FRONTEND_PATH${NC}"
    exit 1
fi

# Check if Dockerfile exists
if [ ! -f "$FRONTEND_PATH/Dockerfile" ]; then
    echo -e "${RED}❌ Dockerfile not found in $FRONTEND_PATH${NC}"
    exit 1
fi

# Get backend FQDN
echo -e "${CYAN}🔍 Getting backend FQDN...${NC}"
BACKEND_FQDN=$(az containerapp show \
    --name backend-uami \
    --resource-group "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null)

if [ -z "$BACKEND_FQDN" ]; then
    echo -e "${RED}❌ Backend not found. Please deploy the backend first.${NC}"
    echo -e "${YELLOW}Run: ./deploy-azure.sh${NC}"
    exit 1
fi

BACKEND_URL="https://$BACKEND_FQDN"
echo -e "${GREEN}✅ Backend URL: $BACKEND_URL${NC}"

# Get WebSocket server FQDN
WEBSOCKET_FQDN=$(az containerapp show \
    --name websocket-uami \
    --resource-group "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null)

if [ -n "$WEBSOCKET_FQDN" ]; then
    WEBSOCKET_URL="wss://$WEBSOCKET_FQDN"
    echo -e "${GREEN}✅ WebSocket URL: $WEBSOCKET_URL${NC}"
else
    # Fallback: derive from backend URL
    WEBSOCKET_URL="${BACKEND_URL/https:/wss:}"
    echo -e "${YELLOW}⚠️  WebSocket container not found, using backend URL for WebSocket${NC}"
fi
echo ""

# Read Azure AI Foundry configuration
echo -e "${CYAN}🔑 Reading Azure AI Configuration${NC}"

# Try to read from frontend_mobile/.env.local first, then .env
if [ -f "$FRONTEND_PATH/.env.local" ]; then
    AZURE_AI_ENDPOINT=$(grep "NEXT_PUBLIC_AZURE_AI_FOUNDRY_PROJECT_ENDPOINT" "$FRONTEND_PATH/.env.local" | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    VOICE_MODEL=$(grep "NEXT_PUBLIC_VOICE_MODEL" "$FRONTEND_PATH/.env.local" | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    AZURE_OPENAI_GPT_API_KEY=$(grep "^AZURE_OPENAI_GPT_API_KEY" "$FRONTEND_PATH/.env.local" | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    AZURE_VOICE_API_KEY=$(grep "^AZURE_VOICE_API_KEY" "$FRONTEND_PATH/.env.local" | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    VOICE_HOST=$(grep "NEXT_PUBLIC_VOICE_HOST" "$FRONTEND_PATH/.env.local" | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    VOICE_DEPLOYMENT=$(grep "NEXT_PUBLIC_VOICE_DEPLOYMENT" "$FRONTEND_PATH/.env.local" | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
elif [ -f ".env" ]; then
    AZURE_AI_ENDPOINT=$(grep "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    VOICE_MODEL=${VOICE_MODEL:-"gpt-realtime"}
fi

# Set defaults
VOICE_MODEL=${VOICE_MODEL:-"gpt-realtime"}
VOICE_DEPLOYMENT=${VOICE_DEPLOYMENT:-"gpt-realtime"}

if [ -z "$AZURE_AI_ENDPOINT" ]; then
    echo -e "${YELLOW}⚠️  No Azure AI endpoint found in .env files${NC}"
    read -p "Azure AI Foundry Project Endpoint: " AZURE_AI_ENDPOINT
fi

if [ -z "$AZURE_OPENAI_GPT_API_KEY" ]; then
    echo -e "${YELLOW}⚠️  No Azure OpenAI API Key found in .env files${NC}"
    read -p "Azure OpenAI GPT API Key: " AZURE_OPENAI_GPT_API_KEY
fi

# Use AZURE_VOICE_API_KEY if set, otherwise fall back to GPT key
AZURE_VOICE_API_KEY=${AZURE_VOICE_API_KEY:-$AZURE_OPENAI_GPT_API_KEY}

if [ -z "$VOICE_HOST" ]; then
    echo -e "${YELLOW}⚠️  No Voice Host found in .env files${NC}"
    read -p "Azure Voice Host (e.g. yourname.openai.azure.com): " VOICE_HOST
fi

echo -e "${GREEN}✅ Using configuration:${NC}"
echo -e "${WHITE}  Backend API: $BACKEND_URL${NC}"
echo -e "${WHITE}  AI Endpoint: $AZURE_AI_ENDPOINT${NC}"
echo -e "${WHITE}  Voice Host:  $VOICE_HOST${NC}"
echo -e "${WHITE}  Voice Model: $VOICE_MODEL${NC}"
echo -e "${WHITE}  GPT Key:     ****${AZURE_OPENAI_GPT_API_KEY: -4}${NC}"
echo -e "${WHITE}  Voice Key:   ****${AZURE_VOICE_API_KEY: -4}${NC}"
echo ""

# Login to ACR
echo -e "${CYAN}🔐 Logging in to ACR...${NC}"
az acr login --name "$ACR_NAME"
echo ""

# Generate timestamp for versioning
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

# Build the image for linux/amd64
echo -e "${CYAN}🔨 Building Docker image for linux/amd64...${NC}"
IMAGE_NAME="$ACR_NAME.azurecr.io/$CONTAINER_NAME:$TIMESTAMP"
IMAGE_LATEST="$ACR_NAME.azurecr.io/$CONTAINER_NAME:latest"

docker buildx build --platform linux/amd64 \
    -f "$FRONTEND_PATH/Dockerfile" \
    --build-arg NEXT_PUBLIC_A2A_API_URL="$BACKEND_URL" \
    --build-arg NEXT_PUBLIC_API_BASE_URL="$BACKEND_URL" \
    --build-arg NEXT_PUBLIC_WEBSOCKET_URL="$WEBSOCKET_URL" \
    --build-arg NEXT_PUBLIC_VOICE_HOST="$VOICE_HOST" \
    --build-arg NEXT_PUBLIC_VOICE_DEPLOYMENT="$VOICE_DEPLOYMENT" \
    --build-arg NEXT_PUBLIC_DEV_MODE="false" \
    -t "$IMAGE_NAME" \
    -t "$IMAGE_LATEST" \
    --load "$FRONTEND_PATH"

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Docker build failed${NC}"
    exit 1
fi

echo ""

# Push to ACR
echo -e "${CYAN}📤 Pushing image to ACR...${NC}"
docker push "$IMAGE_NAME"
docker push "$IMAGE_LATEST"

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Docker push failed${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Image pushed: $IMAGE_NAME${NC}"
echo ""

# Deploy or update Container App
echo -e "${CYAN}🚀 Deploying to Azure Container Apps...${NC}"

# Check if app exists
APP_EXISTS=$(az containerapp show --name "$CONTAINER_NAME" --resource-group "$RESOURCE_GROUP" 2>/dev/null)

if [ -n "$APP_EXISTS" ]; then
    echo -e "${YELLOW}  Updating existing app...${NC}"
    
    az containerapp update \
        --name "$CONTAINER_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --image "$IMAGE_NAME" \
        --set-env-vars \
            "AZURE_OPENAI_GPT_API_KEY=$AZURE_OPENAI_GPT_API_KEY" \
            "AZURE_VOICE_API_KEY=$AZURE_VOICE_API_KEY" \
            "NEXT_PUBLIC_VOICE_HOST=$VOICE_HOST" \
            "NEXT_PUBLIC_VOICE_DEPLOYMENT=$VOICE_DEPLOYMENT" \
            "NEXT_PUBLIC_WEBSOCKET_URL=$WEBSOCKET_URL" \
        --output none
else
    echo -e "${YELLOW}  Creating new app...${NC}"
    
    # Get managed identity for ACR pull
    MANAGED_IDENTITY="a2a-registry-uami"
    
    az containerapp create \
        --name "$CONTAINER_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --environment "$ENVIRONMENT" \
        --image "$IMAGE_NAME" \
        --registry-server "$ACR_NAME.azurecr.io" \
        --user-assigned "$MANAGED_IDENTITY" \
        --target-port "$PORT" \
        --ingress external \
        --min-replicas 1 \
        --max-replicas 3 \
        --cpu 0.5 \
        --memory 1.0Gi \
        --env-vars \
            "AZURE_OPENAI_GPT_API_KEY=$AZURE_OPENAI_GPT_API_KEY" \
            "AZURE_VOICE_API_KEY=$AZURE_VOICE_API_KEY" \
            "NEXT_PUBLIC_VOICE_HOST=$VOICE_HOST" \
            "NEXT_PUBLIC_VOICE_DEPLOYMENT=$VOICE_DEPLOYMENT" \
            "NEXT_PUBLIC_WEBSOCKET_URL=$WEBSOCKET_URL" \
        --output none
fi

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Deployment failed${NC}"
    exit 1
fi

echo ""

# Get the app URL
APP_FQDN=$(az containerapp show \
    --name "$CONTAINER_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn -o tsv)

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ Frontend Light deployed successfully!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${WHITE}  🌐 URL: https://$APP_FQDN${NC}"
echo -e "${WHITE}  📦 Image: $IMAGE_NAME${NC}"
echo -e "${WHITE}  🔗 Backend: $BACKEND_URL${NC}"
echo ""
echo -e "${CYAN}Open in browser:${NC}"
echo -e "${WHITE}  open https://$APP_FQDN${NC}"
echo ""
