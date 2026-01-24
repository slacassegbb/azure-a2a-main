#!/bin/bash

# Deploy Remote Agent to Azure Container Apps with Managed Identity
# Usage: ./deploy-remote-agent.sh -a azurefoundry_branding -p 9000

# Default values
RESOURCE_GROUP="rg-a2a-prod"
ACR_NAME="a2awestuslab"
ENVIRONMENT="env-a2a-final"
MANAGED_IDENTITY="a2a-registry-uami"
COGNITIVE_SERVICES_ACCOUNT="simonfoundry"

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
        -a|--agent-name)
            AGENT_NAME="$2"
            shift 2
            ;;
        -p|--port)
            PORT="$2"
            shift 2
            ;;
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
        -h|--help)
            echo "Usage: ./deploy-remote-agent.sh -a AGENT_NAME -p PORT [options]"
            echo ""
            echo "Required:"
            echo "  -a, --agent-name         Agent name (e.g., azurefoundry_branding)"
            echo "  -p, --port               Port number (e.g., 9000)"
            echo ""
            echo "Optional:"
            echo "  -r, --resource-group     Resource group (default: rg-a2a-prod)"
            echo "  --acr                    ACR name (default: a2awestuslab)"
            echo "  -e, --environment        Environment name (default: env-a2a-final)"
            echo "  -h, --help               Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}❌ Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Check required parameters
if [ -z "$AGENT_NAME" ] || [ -z "$PORT" ]; then
    echo -e "${RED}❌ Missing required parameters${NC}"
    echo ""
    echo "Usage: ./deploy-remote-agent.sh -a AGENT_NAME -p PORT"
    echo "Example: ./deploy-remote-agent.sh -a azurefoundry_branding -p 9000"
    echo ""
    echo "Run './deploy-remote-agent.sh --help' for more options"
    exit 1
fi

AGENT_PATH="remote_agents/$AGENT_NAME"

echo -e "${CYAN}🤖 Deploying Remote Agent with Managed Identity${NC}"
echo -e "${CYAN}===============================================${NC}"
echo -e "${WHITE}  Agent: $AGENT_NAME${NC}"
echo -e "${WHITE}  Port: $PORT${NC}"
echo -e "${WHITE}  Resource Group: $RESOURCE_GROUP${NC}"
echo -e "${WHITE}  ACR: $ACR_NAME${NC}"
echo -e "${WHITE}  Managed Identity: $MANAGED_IDENTITY${NC}"
echo ""

# Check if agent directory exists
if [ ! -d "$AGENT_PATH" ]; then
    echo -e "${RED}❌ Agent not found at: $AGENT_PATH${NC}"
    echo ""
    echo -e "${YELLOW}Available agents:${NC}"
    ls -1 remote_agents/ | grep -v "^\." | sed 's/^/  - /'
    exit 1
fi

# Check if Dockerfile exists
if [ ! -f "$AGENT_PATH/Dockerfile" ]; then
    echo -e "${RED}❌ Dockerfile not found in $AGENT_PATH${NC}"
    exit 1
fi

# Azure AI Foundry configuration (read from .env file or prompt if not available)
echo -e "${CYAN}🔑 Azure AI Foundry Configuration${NC}"

# Try to read from .env file as defaults (check agent directory first)
if [ -f "$AGENT_PATH/.env" ]; then
    DEFAULT_AI_ENDPOINT=$(grep "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT" "$AGENT_PATH/.env" | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    DEFAULT_AI_MODEL=$(grep "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME" "$AGENT_PATH/.env" | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    # Read optional OPENAI_API_KEY for agents that use OpenAI directly (e.g., image generator)
    OPENAI_API_KEY=$(grep "^OPENAI_API_KEY" "$AGENT_PATH/.env" | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    # Read AZURE_OPENAI_ENDPOINT for agents that use Azure OpenAI (e.g., video generator)
    AZURE_OPENAI_ENDPOINT=$(grep "^AZURE_OPENAI_ENDPOINT" "$AGENT_PATH/.env" | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    # Read blob storage configuration for image generator
    AZURE_STORAGE_CONNECTION_STRING=$(grep "^AZURE_STORAGE_CONNECTION_STRING" "$AGENT_PATH/.env" | cut -d '=' -f2- | tr -d '"')
elif [ -f ".env" ]; then
    DEFAULT_AI_ENDPOINT=$(grep "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    DEFAULT_AI_MODEL=$(grep "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    OPENAI_API_KEY=$(grep "^OPENAI_API_KEY" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    # Read AZURE_OPENAI_ENDPOINT from root .env
    AZURE_OPENAI_ENDPOINT=$(grep "^AZURE_OPENAI_ENDPOINT" .env | cut -d '=' -f2- | tr -d '"' | tr -d ' ')
    # Read blob storage configuration from root .env
    AZURE_STORAGE_CONNECTION_STRING=$(grep "^AZURE_STORAGE_CONNECTION_STRING" .env | cut -d '=' -f2- | tr -d '"')
fi

# If .env values exist, use them automatically; otherwise prompt
if [ -n "$DEFAULT_AI_ENDPOINT" ] && [ -n "$DEFAULT_AI_MODEL" ]; then
    AZURE_AI_ENDPOINT="$DEFAULT_AI_ENDPOINT"
    AZURE_AI_MODEL_DEPLOYMENT="$DEFAULT_AI_MODEL"
    echo -e "${GREEN}✅ Using configuration from .env file${NC}"
    echo -e "${WHITE}  Endpoint: $AZURE_AI_ENDPOINT${NC}"
    echo -e "${WHITE}  Model: $AZURE_AI_MODEL_DEPLOYMENT${NC}"
    if [ -n "$OPENAI_API_KEY" ]; then
        echo -e "${WHITE}  OpenAI API Key: ****${OPENAI_API_KEY: -4}${NC}"
    fi
    if [ -n "$AZURE_OPENAI_ENDPOINT" ]; then
        echo -e "${WHITE}  Azure OpenAI Endpoint: $AZURE_OPENAI_ENDPOINT${NC}"
    fi
else
    echo -e "${YELLOW}No .env file found, please enter configuration:${NC}"
    read -p "Azure AI Foundry Project Endpoint: " AZURE_AI_ENDPOINT
    read -p "Azure AI Agent Model Deployment Name: " AZURE_AI_MODEL_DEPLOYMENT
fi

echo ""

# Login to ACR
echo -e "${CYAN}🔐 Logging in to ACR...${NC}"
az acr login --name "$ACR_NAME"
echo ""

# Generate timestamp for versioning
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

# Convert agent name to lowercase for Docker image tag
AGENT_NAME_LOWER=$(echo "$AGENT_NAME" | tr '[:upper:]' '[:lower:]')

# Build the image for linux/amd64
echo -e "${CYAN}🔨 Building Docker image for linux/amd64...${NC}"
IMAGE_NAME="$ACR_NAME.azurecr.io/a2a-$AGENT_NAME_LOWER:$TIMESTAMP"
IMAGE_LATEST="$ACR_NAME.azurecr.io/a2a-$AGENT_NAME_LOWER:latest"

docker buildx build --platform linux/amd64 \
    -f "$AGENT_PATH/Dockerfile" \
    -t "$IMAGE_NAME" \
    -t "$IMAGE_LATEST" \
    --load "$AGENT_PATH"

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

# Get backend FQDN for registration
echo -e "${CYAN}🔍 Getting backend FQDN...${NC}"
BACKEND_FQDN=$(az containerapp show \
    --name backend-uami \
    --resource-group "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null)

if [ -z "$BACKEND_FQDN" ]; then
    echo -e "${YELLOW}⚠️  Backend not found. Agent will run but may not auto-register.${NC}"
    BACKEND_URL="http://localhost:12000"
else
    BACKEND_URL="https://$BACKEND_FQDN"
    echo -e "${GREEN}✅ Backend URL: $BACKEND_URL${NC}"
fi
echo ""

# Deploy or update to Container Apps
CONTAINER_NAME=$(echo "$AGENT_NAME" | tr '[:upper:]' '[:lower:]' | tr '_' '-')
echo -e "${CYAN}🚀 Deploying to Azure Container Apps as: $CONTAINER_NAME${NC}"

# Get managed identity client ID
MANAGED_IDENTITY_CLIENT_ID=$(az identity show \
    --name "$MANAGED_IDENTITY" \
    --resource-group "$RESOURCE_GROUP" \
    --query clientId -o tsv)

# Check if agent exists
AGENT_EXISTS=$(az containerapp show --name "$CONTAINER_NAME" --resource-group "$RESOURCE_GROUP" 2>/dev/null)

if [ -n "$AGENT_EXISTS" ]; then
    echo -e "${YELLOW}  Updating existing agent...${NC}"
    
    # Get agent's public FQDN for A2A_ENDPOINT
    AGENT_FQDN=$(az containerapp show \
        --name "$CONTAINER_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query properties.configuration.ingress.fqdn -o tsv)
    
    # Build env vars array
    ENV_VARS=(
        "A2A_PORT=$PORT"
        "A2A_HOST=0.0.0.0"
        "A2A_ENDPOINT=https://$AGENT_FQDN"
        "BACKEND_SERVER_URL=$BACKEND_URL"
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=$AZURE_AI_ENDPOINT"
        "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=$AZURE_AI_MODEL_DEPLOYMENT"
        "AZURE_CLIENT_ID=$MANAGED_IDENTITY_CLIENT_ID"
    )
    
    # Add OPENAI_API_KEY if set (for agents like image_generator that use OpenAI directly)
    if [ -n "$OPENAI_API_KEY" ]; then
        ENV_VARS+=("OPENAI_API_KEY=$OPENAI_API_KEY")
    fi
    
    # Add AZURE_OPENAI_ENDPOINT if set (for agents like video_generator that use Azure OpenAI Sora)
    if [ -n "$AZURE_OPENAI_ENDPOINT" ]; then
        ENV_VARS+=("AZURE_OPENAI_ENDPOINT=$AZURE_OPENAI_ENDPOINT")
    fi
    
    # Add blob storage env vars for image and video generator agents
    if ([[ "$AGENT_NAME" == *"image_generator"* ]] || [[ "$AGENT_NAME" == *"video"* ]]) && [ -n "$AZURE_STORAGE_CONNECTION_STRING" ]; then
        ENV_VARS+=("FORCE_AZURE_BLOB=true")
        ENV_VARS+=("AZURE_STORAGE_CONNECTION_STRING=$AZURE_STORAGE_CONNECTION_STRING")
        ENV_VARS+=("AZURE_BLOB_CONTAINER=a2a-files")
        echo -e "${GREEN}✅ Blob storage configuration added${NC}"
    fi
    
    az containerapp update \
        --name "$CONTAINER_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --image "$IMAGE_NAME" \
        --set-env-vars "${ENV_VARS[@]}" \
        --output none
else
    echo -e "${YELLOW}  Creating new agent...${NC}"
    
    # Build env vars string for create command
    ENV_VARS_CREATE="A2A_PORT=$PORT A2A_HOST=0.0.0.0 AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=$AZURE_AI_ENDPOINT AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=$AZURE_AI_MODEL_DEPLOYMENT AZURE_CLIENT_ID=$MANAGED_IDENTITY_CLIENT_ID"
    
    # Add OPENAI_API_KEY if set (for agents like image_generator that use OpenAI directly)
    if [ -n "$OPENAI_API_KEY" ]; then
        ENV_VARS_CREATE="$ENV_VARS_CREATE OPENAI_API_KEY=$OPENAI_API_KEY"
    fi
    
    # Add AZURE_OPENAI_ENDPOINT if set (for agents like video_generator that use Azure OpenAI Sora)
    if [ -n "$AZURE_OPENAI_ENDPOINT" ]; then
        ENV_VARS_CREATE="$ENV_VARS_CREATE AZURE_OPENAI_ENDPOINT=$AZURE_OPENAI_ENDPOINT"
    fi
    
    # Add blob storage env vars for image and video generator agents
    if ([[ "$AGENT_NAME" == *"image_generator"* ]] || [[ "$AGENT_NAME" == *"video"* ]]) && [ -n "$AZURE_STORAGE_CONNECTION_STRING" ]; then
        ENV_VARS_CREATE="$ENV_VARS_CREATE FORCE_AZURE_BLOB=true AZURE_STORAGE_CONNECTION_STRING=\"$AZURE_STORAGE_CONNECTION_STRING\" AZURE_BLOB_CONTAINER=a2a-files"
        echo -e "${GREEN}✅ Blob storage configuration added${NC}"
    fi
    
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
        --max-replicas 1 \
        --cpu 0.5 \
        --memory 1.0Gi \
        --env-vars $ENV_VARS_CREATE \
        --output none
    
    # Get the newly created agent's FQDN and update with A2A_ENDPOINT and BACKEND_SERVER_URL
    sleep 5
    AGENT_FQDN=$(az containerapp show \
        --name "$CONTAINER_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query properties.configuration.ingress.fqdn -o tsv)
    
    echo -e "${YELLOW}  Configuring agent URLs...${NC}"
    az containerapp update \
        --name "$CONTAINER_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --set-env-vars \
            "A2A_ENDPOINT=https://$AGENT_FQDN" \
            "BACKEND_SERVER_URL=$BACKEND_URL" \
        --output none
fi

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Deployment failed${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Agent deployed${NC}"
echo ""

# Get agent FQDN
AGENT_FQDN=$(az containerapp show \
    --name "$CONTAINER_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn -o tsv)

# Setup RBAC permissions
echo -e "${CYAN}🔐 Setting up RBAC permissions...${NC}"

# Get managed identity principal ID
PRINCIPAL_ID=$(az identity show \
    --name "$MANAGED_IDENTITY" \
    --resource-group "$RESOURCE_GROUP" \
    --query principalId -o tsv)

# Get Azure AI Foundry (Cognitive Services) account resource ID
# Try the same resource group first, then search all resource groups
COGNITIVE_SERVICES_ID=$(az cognitiveservices account show \
    --name "$COGNITIVE_SERVICES_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --query id -o tsv 2>/dev/null)

# If not found in the same resource group, search across all resource groups
if [ -z "$COGNITIVE_SERVICES_ID" ]; then
    echo -e "${YELLOW}  Searching for Cognitive Services account across all resource groups...${NC}"
    COGNITIVE_SERVICES_ID=$(az cognitiveservices account list \
        --query "[?name=='$COGNITIVE_SERVICES_ACCOUNT'].id | [0]" -o tsv 2>/dev/null)
fi

if [ -n "$COGNITIVE_SERVICES_ID" ]; then
    # Determine which role to assign based on agent type
    # Video agents (using Sora) need Contributor role for video generation
    # Other agents can use the basic User role
    if [[ "$AGENT_NAME" == *"video"* ]]; then
        ROLE_NAME="Cognitive Services OpenAI Contributor"
        echo -e "${YELLOW}  Granting '$ROLE_NAME' role (required for Sora video generation)...${NC}"
    else
        ROLE_NAME="Cognitive Services User"
        echo -e "${YELLOW}  Granting '$ROLE_NAME' role...${NC}"
    fi
    
    # Check if role assignment already exists
    EXISTING_ROLE=$(az role assignment list \
        --assignee "$PRINCIPAL_ID" \
        --role "$ROLE_NAME" \
        --scope "$COGNITIVE_SERVICES_ID" \
        --query "[0].id" -o tsv 2>/dev/null)
    
    if [ -z "$EXISTING_ROLE" ]; then
        az role assignment create \
            --assignee "$PRINCIPAL_ID" \
            --role "$ROLE_NAME" \
            --scope "$COGNITIVE_SERVICES_ID" \
            --output none
        echo -e "${GREEN}  ✅ Role assigned (may take 2-3 minutes to propagate)${NC}"
    else
        echo -e "${GREEN}  ✅ Role already assigned${NC}"
    fi
else
    echo -e "${YELLOW}  ⚠️  Could not find Cognitive Services account: $COGNITIVE_SERVICES_ACCOUNT${NC}"
    echo -e "${YELLOW}  You may need to manually grant permissions if the agent needs Azure AI Foundry access${NC}"
fi

echo ""

# Summary
echo -e "${CYAN}========================================${NC}"
echo -e "${GREEN}✅ Agent Deployment Complete!${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""
echo -e "${WHITE}Agent Details:${NC}"
echo -e "${CYAN}  Name: $AGENT_NAME${NC}"
echo -e "${CYAN}  URL: https://$AGENT_FQDN${NC}"
echo -e "${CYAN}  Port: $PORT${NC}"
echo -e "${CYAN}  Backend: $BACKEND_URL${NC}"
echo ""
echo -e "${WHITE}Configuration:${NC}"
echo -e "${CYAN}  Azure AI Foundry: $AZURE_AI_ENDPOINT${NC}"
echo -e "${CYAN}  Model Deployment: $AZURE_AI_MODEL_DEPLOYMENT${NC}"
echo -e "${CYAN}  Managed Identity: $MANAGED_IDENTITY (with Cognitive Services User role)${NC}"
echo ""
echo -e "${YELLOW}View logs:${NC}"
echo -e "${WHITE}  az containerapp logs show --name $CONTAINER_NAME --resource-group $RESOURCE_GROUP --follow${NC}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo -e "${WHITE}  1. Wait 2-3 minutes for RBAC permissions to propagate${NC}"
echo -e "${WHITE}  2. Go to: https://frontend-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io${NC}"
echo -e "${WHITE}  3. Agent should appear in sidebar automatically!${NC}"
echo -e "${WHITE}  4. Start chatting with the $AGENT_NAME agent!${NC}"
echo ""
echo -e "${YELLOW}If you see permission errors in logs:${NC}"
echo -e "${WHITE}  - Wait a few more minutes for RBAC to propagate${NC}"
echo -e "${WHITE}  - Restart the agent: az containerapp revision restart --name $CONTAINER_NAME --resource-group $RESOURCE_GROUP${NC}"
echo ""

