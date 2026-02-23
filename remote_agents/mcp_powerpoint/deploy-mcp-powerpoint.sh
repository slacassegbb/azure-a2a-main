#!/bin/bash

# Deploy PowerPoint MCP Server to Azure Container Apps
# Usage: ./deploy-mcp-powerpoint.sh

# Default values (same infrastructure as other A2A agents)
RESOURCE_GROUP="rg-a2a-prod"
ACR_NAME="a2awestuslab"
ENVIRONMENT="env-a2a-final"
MANAGED_IDENTITY="a2a-registry-uami"
CONTAINER_NAME="mcp-powerpoint"
PORT=8000

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
            echo "Usage: ./deploy-mcp-powerpoint.sh [options]"
            echo ""
            echo "Options:"
            echo "  -r, --resource-group     Resource group (default: rg-a2a-prod)"
            echo "  --acr                    ACR name (default: a2awestuslab)"
            echo "  -e, --environment        Environment name (default: env-a2a-final)"
            echo "  -p, --port               Port number (default: 8000)"
            echo "  -h, --help               Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${CYAN}Deploying PowerPoint MCP Server to Azure Container Apps${NC}"
echo -e "${CYAN}========================================================${NC}"
echo -e "${WHITE}  Container Name: $CONTAINER_NAME${NC}"
echo -e "${WHITE}  Port: $PORT${NC}"
echo -e "${WHITE}  Resource Group: $RESOURCE_GROUP${NC}"
echo -e "${WHITE}  ACR: $ACR_NAME${NC}"
echo -e "${WHITE}  Environment: $ENVIRONMENT${NC}"
echo ""

# Login to ACR
echo -e "${CYAN}Logging in to ACR...${NC}"
az acr login --name "$ACR_NAME"
if [ $? -ne 0 ]; then
    echo -e "${RED}ACR login failed. Make sure you're logged in to Azure CLI.${NC}"
    exit 1
fi
echo ""

# Generate timestamp for versioning
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

# Build the Docker image for linux/amd64
echo -e "${CYAN}Building Docker image for linux/amd64...${NC}"
IMAGE_NAME="$ACR_NAME.azurecr.io/$CONTAINER_NAME:$TIMESTAMP"
IMAGE_LATEST="$ACR_NAME.azurecr.io/$CONTAINER_NAME:latest"

docker buildx build --platform linux/amd64 \
    -t "$IMAGE_NAME" \
    -t "$IMAGE_LATEST" \
    --load .

if [ $? -ne 0 ]; then
    echo -e "${RED}Docker build failed${NC}"
    exit 1
fi
echo -e "${GREEN}Docker image built${NC}"
echo ""

# Push to ACR
echo -e "${CYAN}Pushing image to ACR...${NC}"
docker push "$IMAGE_NAME"
docker push "$IMAGE_LATEST"

if [ $? -ne 0 ]; then
    echo -e "${RED}Docker push failed${NC}"
    exit 1
fi
echo -e "${GREEN}Image pushed: $IMAGE_NAME${NC}"
echo ""

# Get managed identity client ID
echo -e "${CYAN}Getting managed identity info...${NC}"
MANAGED_IDENTITY_CLIENT_ID=$(az identity show \
    --name "$MANAGED_IDENTITY" \
    --resource-group "$RESOURCE_GROUP" \
    --query clientId -o tsv 2>/dev/null)

if [ -z "$MANAGED_IDENTITY_CLIENT_ID" ]; then
    echo -e "${YELLOW}Managed identity not found, continuing without it${NC}"
fi
echo ""

# Check if container app exists
echo -e "${CYAN}Deploying to Azure Container Apps...${NC}"
CONTAINER_EXISTS=$(az containerapp show --name "$CONTAINER_NAME" --resource-group "$RESOURCE_GROUP" 2>/dev/null)

# Build environment variables
ENV_VARS=(
    "PORT=$PORT"
)

if [ -n "$CONTAINER_EXISTS" ]; then
    echo -e "${YELLOW}  Updating existing container app...${NC}"

    az containerapp update \
        --name "$CONTAINER_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --image "$IMAGE_NAME" \
        --set-env-vars "${ENV_VARS[@]}" \
        --output none
else
    echo -e "${YELLOW}  Creating new container app...${NC}"

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
fi

if [ $? -ne 0 ]; then
    echo -e "${RED}Deployment failed${NC}"
    exit 1
fi

echo -e "${GREEN}Container app deployed${NC}"
echo ""

# Get final FQDN
CONTAINER_FQDN=$(az containerapp show \
    --name "$CONTAINER_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn -o tsv)

# Summary
echo -e "${CYAN}========================================${NC}"
echo -e "${GREEN}PowerPoint MCP Server Deployed!${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""
echo -e "${WHITE}Server Details:${NC}"
echo -e "${CYAN}  URL: https://$CONTAINER_FQDN${NC}"
echo -e "${CYAN}  MCP Endpoint: https://$CONTAINER_FQDN/mcp${NC}"
echo -e "${CYAN}  Port: $PORT${NC}"
echo ""
echo -e "${YELLOW}View logs:${NC}"
echo -e "${WHITE}  az containerapp logs show --name $CONTAINER_NAME --resource-group $RESOURCE_GROUP --follow${NC}"
echo ""
echo -e "${YELLOW}Test the MCP server:${NC}"
echo -e "${WHITE}  curl -X POST https://$CONTAINER_FQDN/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"clientInfo\":{\"name\":\"test\",\"version\":\"1.0\"}}}'${NC}"
echo ""
