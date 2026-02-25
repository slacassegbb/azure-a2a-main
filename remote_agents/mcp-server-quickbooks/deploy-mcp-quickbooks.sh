#!/bin/bash

# Deploy QuickBooks MCP Server to Azure Container Apps
# Usage: ./deploy-mcp-quickbooks.sh

# Default values (using same infrastructure as your A2A agents)
RESOURCE_GROUP="rg-a2a-prod"
ACR_NAME="a2awestuslab"
ENVIRONMENT="env-a2a-final"
MANAGED_IDENTITY="a2a-registry-uami"
CONTAINER_NAME="mcp-quickbooks"
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
        -p|--port)
            PORT="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: ./deploy-mcp-quickbooks.sh [options]"
            echo ""
            echo "Options:"
            echo "  -r, --resource-group     Resource group (default: rg-a2a-prod)"
            echo "  --acr                    ACR name (default: a2awestuslab)"
            echo "  -e, --environment        Environment name (default: env-a2a-final)"
            echo "  -p, --port               Port number (default: 3001)"
            echo "  -h, --help               Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}❌ Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${CYAN}🔌 Deploying QuickBooks MCP Server to Azure Container Apps${NC}"
echo -e "${CYAN}===========================================================${NC}"
echo -e "${WHITE}  Container Name: $CONTAINER_NAME${NC}"
echo -e "${WHITE}  Port: $PORT${NC}"
echo -e "${WHITE}  Resource Group: $RESOURCE_GROUP${NC}"
echo -e "${WHITE}  ACR: $ACR_NAME${NC}"
echo -e "${WHITE}  Environment: $ENVIRONMENT${NC}"
echo ""

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo -e "${RED}❌ .env file not found${NC}"
    echo -e "${YELLOW}Please create a .env file with QuickBooks credentials:${NC}"
    echo "  QUICKBOOKS_CLIENT_ID=your_client_id"
    echo "  QUICKBOOKS_CLIENT_SECRET=your_client_secret"
    echo "  QUICKBOOKS_ENVIRONMENT=sandbox"
    echo "  QUICKBOOKS_REFRESH_TOKEN=your_refresh_token"
    echo "  QUICKBOOKS_REALM_ID=your_realm_id"
    exit 1
fi

# Read QuickBooks credentials from .env
echo -e "${CYAN}🔑 Reading QuickBooks configuration from .env${NC}"
QUICKBOOKS_CLIENT_ID=$(grep "^QUICKBOOKS_CLIENT_ID" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
QUICKBOOKS_CLIENT_SECRET=$(grep "^QUICKBOOKS_CLIENT_SECRET" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
QUICKBOOKS_ENVIRONMENT=$(grep "^QUICKBOOKS_ENVIRONMENT" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
QUICKBOOKS_REFRESH_TOKEN=$(grep "^QUICKBOOKS_REFRESH_TOKEN" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
QUICKBOOKS_REALM_ID=$(grep "^QUICKBOOKS_REALM_ID" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')

# Validate required credentials
if [ -z "$QUICKBOOKS_CLIENT_ID" ] || [ -z "$QUICKBOOKS_CLIENT_SECRET" ] || [ -z "$QUICKBOOKS_REFRESH_TOKEN" ] || [ -z "$QUICKBOOKS_REALM_ID" ]; then
    echo -e "${RED}❌ Missing required QuickBooks credentials in .env${NC}"
    echo -e "${YELLOW}Required variables:${NC}"
    echo "  QUICKBOOKS_CLIENT_ID"
    echo "  QUICKBOOKS_CLIENT_SECRET"
    echo "  QUICKBOOKS_REFRESH_TOKEN"
    echo "  QUICKBOOKS_REALM_ID"
    exit 1
fi

echo -e "${GREEN}✅ QuickBooks credentials loaded${NC}"
echo -e "${WHITE}  Client ID: ****${QUICKBOOKS_CLIENT_ID: -4}${NC}"
echo -e "${WHITE}  Environment: ${QUICKBOOKS_ENVIRONMENT:-sandbox}${NC}"
echo -e "${WHITE}  Realm ID: $QUICKBOOKS_REALM_ID${NC}"
echo ""

# Build TypeScript first
echo -e "${CYAN}📦 Building TypeScript...${NC}"
npm run build
if [ $? -ne 0 ]; then
    echo -e "${RED}❌ TypeScript build failed${NC}"
    exit 1
fi
echo -e "${GREEN}✅ TypeScript build complete${NC}"
echo ""

# Login to ACR
echo -e "${CYAN}🔐 Logging in to ACR...${NC}"
az acr login --name "$ACR_NAME"
if [ $? -ne 0 ]; then
    echo -e "${RED}❌ ACR login failed. Make sure you're logged in to Azure CLI.${NC}"
    exit 1
fi
echo ""

# Generate timestamp for versioning
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

# Build the Docker image for linux/amd64
echo -e "${CYAN}🔨 Building Docker image for linux/amd64...${NC}"
IMAGE_NAME="$ACR_NAME.azurecr.io/$CONTAINER_NAME:$TIMESTAMP"
IMAGE_LATEST="$ACR_NAME.azurecr.io/$CONTAINER_NAME:latest"

docker buildx build --platform linux/amd64 \
    -t "$IMAGE_NAME" \
    -t "$IMAGE_LATEST" \
    --load .

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Docker build failed${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Docker image built${NC}"
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

# Get managed identity client ID (for potential future use)
echo -e "${CYAN}🔍 Getting managed identity info...${NC}"
MANAGED_IDENTITY_CLIENT_ID=$(az identity show \
    --name "$MANAGED_IDENTITY" \
    --resource-group "$RESOURCE_GROUP" \
    --query clientId -o tsv 2>/dev/null)

if [ -z "$MANAGED_IDENTITY_CLIENT_ID" ]; then
    echo -e "${YELLOW}⚠️  Managed identity not found, continuing without it${NC}"
fi
echo ""

# Check if container app exists
echo -e "${CYAN}🚀 Deploying to Azure Container Apps...${NC}"
CONTAINER_EXISTS=$(az containerapp show --name "$CONTAINER_NAME" --resource-group "$RESOURCE_GROUP" 2>/dev/null)

# Build environment variables
ENV_VARS=(
    "TRANSPORT_MODE=http"
    "PORT=$PORT"
    "QUICKBOOKS_CLIENT_ID=$QUICKBOOKS_CLIENT_ID"
    "QUICKBOOKS_CLIENT_SECRET=$QUICKBOOKS_CLIENT_SECRET"
    "QUICKBOOKS_ENVIRONMENT=${QUICKBOOKS_ENVIRONMENT:-sandbox}"
    "QUICKBOOKS_REFRESH_TOKEN=$QUICKBOOKS_REFRESH_TOKEN"
    "QUICKBOOKS_REALM_ID=$QUICKBOOKS_REALM_ID"
    "AZURE_SUBSCRIPTION_ID=4f134af7-23ad-4bc1-85a4-748d72a8b663"
    "AZURE_RESOURCE_GROUP=$RESOURCE_GROUP"
    "AZURE_CONTAINER_APP_NAME=$CONTAINER_NAME"
)

# Add managed identity client ID for Azure token auto-persistence
if [ -n "$MANAGED_IDENTITY_CLIENT_ID" ]; then
    ENV_VARS+=("AZURE_CLIENT_ID=$MANAGED_IDENTITY_CLIENT_ID")
fi

if [ -n "$CONTAINER_EXISTS" ]; then
    echo -e "${YELLOW}  Updating existing container app...${NC}"
    
    # Get container's public FQDN
    CONTAINER_FQDN=$(az containerapp show \
        --name "$CONTAINER_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query properties.configuration.ingress.fqdn -o tsv)
    
    # Add redirect URI based on container FQDN
    ENV_VARS+=("QUICKBOOKS_REDIRECT_URI=https://$CONTAINER_FQDN/oauth/callback")
    
    az containerapp update \
        --name "$CONTAINER_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --image "$IMAGE_NAME" \
        --set-env-vars "${ENV_VARS[@]}" \
        --output none
else
    echo -e "${YELLOW}  Creating new container app...${NC}"
    
    # Create without managed identity first if not available
    if [ -n "$MANAGED_IDENTITY_CLIENT_ID" ]; then
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
            --env-vars "${ENV_VARS[@]}" \
            --output none
    else
        # Create with system identity
        az containerapp create \
            --name "$CONTAINER_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --environment "$ENVIRONMENT" \
            --image "$IMAGE_NAME" \
            --registry-server "$ACR_NAME.azurecr.io" \
            --target-port "$PORT" \
            --ingress external \
            --min-replicas 1 \
            --max-replicas 3 \
            --cpu 0.5 \
            --memory 1.0Gi \
            --env-vars "${ENV_VARS[@]}" \
            --output none
    fi
    
    # Get the newly created container's FQDN and update redirect URI
    sleep 5
    CONTAINER_FQDN=$(az containerapp show \
        --name "$CONTAINER_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query properties.configuration.ingress.fqdn -o tsv)
    
    echo -e "${YELLOW}  Updating OAuth redirect URI...${NC}"
    az containerapp update \
        --name "$CONTAINER_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --set-env-vars "QUICKBOOKS_REDIRECT_URI=https://$CONTAINER_FQDN/oauth/callback" \
        --output none
fi

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Deployment failed${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Container app deployed${NC}"
echo ""

# Get final FQDN
CONTAINER_FQDN=$(az containerapp show \
    --name "$CONTAINER_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn -o tsv)

# Summary
echo -e "${CYAN}========================================${NC}"
echo -e "${GREEN}✅ QuickBooks MCP Server Deployed!${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""
echo -e "${WHITE}Server Details:${NC}"
echo -e "${CYAN}  URL: https://$CONTAINER_FQDN${NC}"
echo -e "${CYAN}  SSE Endpoint: https://$CONTAINER_FQDN/sse${NC}"
echo -e "${CYAN}  Health Check: https://$CONTAINER_FQDN/health${NC}"
echo -e "${CYAN}  Port: $PORT${NC}"
echo ""
echo -e "${WHITE}QuickBooks Configuration:${NC}"
echo -e "${CYAN}  Environment: ${QUICKBOOKS_ENVIRONMENT:-sandbox}${NC}"
echo -e "${CYAN}  Realm ID: $QUICKBOOKS_REALM_ID${NC}"
echo -e "${CYAN}  OAuth Redirect: https://$CONTAINER_FQDN/oauth/callback${NC}"
echo ""
echo -e "${YELLOW}⚠️  IMPORTANT: Update your QuickBooks App!${NC}"
echo -e "${WHITE}  Add this redirect URI to your QuickBooks Developer app:${NC}"
echo -e "${GREEN}  https://$CONTAINER_FQDN/oauth/callback${NC}"
echo ""
echo -e "${YELLOW}View logs:${NC}"
echo -e "${WHITE}  az containerapp logs show --name $CONTAINER_NAME --resource-group $RESOURCE_GROUP --follow${NC}"
echo ""
echo -e "${YELLOW}Test the MCP server:${NC}"
echo -e "${WHITE}  curl https://$CONTAINER_FQDN/health${NC}"
echo ""
echo -e "${YELLOW}Use with Azure AI Foundry:${NC}"
echo -e "${WHITE}  MCP Server URL: https://$CONTAINER_FQDN/sse${NC}"
echo ""
