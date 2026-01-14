#!/bin/bash

# Setup GitHub Actions CI/CD for Azure Container Apps
# This script will help you configure the required GitHub secrets

set -e

echo "╔══════════════════════════════════════════════════════════════════════════╗"
echo "║           🔧 GitHub Actions CI/CD Setup for Azure                        ║"
echo "╚══════════════════════════════════════════════════════════════════════════╝"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if Azure CLI is installed
if ! command -v az &> /dev/null; then
    echo -e "${RED}❌ Azure CLI is not installed. Please install it first.${NC}"
    exit 1
fi

# Check if GitHub CLI is installed
if ! command -v gh &> /dev/null; then
    echo -e "${YELLOW}⚠️  GitHub CLI is not installed. You'll need to add secrets manually.${NC}"
    MANUAL_MODE=true
else
    MANUAL_MODE=false
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 1: Creating Azure Service Principal for GitHub Actions"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

SUBSCRIPTION_ID=$(az account show --query id -o tsv)
RESOURCE_GROUP="rg-a2a-prod"

echo "📋 Subscription ID: $SUBSCRIPTION_ID"
echo "📋 Resource Group: $RESOURCE_GROUP"
echo ""

# Create service principal with contributor access to the resource group
echo "Creating service principal..."
SP_OUTPUT=$(az ad sp create-for-rbac \
  --name "github-actions-a2a-cicd" \
  --role contributor \
  --scopes /subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP \
  --sdk-auth)

echo -e "${GREEN}✅ Service Principal created!${NC}"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 2: GitHub Secret Configuration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ "$MANUAL_MODE" = false ]; then
    echo "Adding secret to GitHub repository..."
    echo "$SP_OUTPUT" | gh secret set AZURE_CREDENTIALS
    echo -e "${GREEN}✅ GitHub secret AZURE_CREDENTIALS configured!${NC}"
    echo ""
else
    echo -e "${YELLOW}📋 Add this secret to your GitHub repository:${NC}"
    echo ""
    echo "Secret Name: AZURE_CREDENTIALS"
    echo "Secret Value:"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "$SP_OUTPUT"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "📖 To add this secret:"
    echo "   1. Go to: https://github.com/slacassegbb/azure-a2a-main/settings/secrets/actions"
    echo "   2. Click 'New repository secret'"
    echo "   3. Name: AZURE_CREDENTIALS"
    echo "   4. Value: Paste the JSON above"
    echo "   5. Click 'Add secret'"
    echo ""
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Setup Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🚀 How to use:"
echo ""
echo "1. Make changes to your code:"
echo "   - Edit files in frontend/ or backend/"
echo ""
echo "2. Commit and push:"
echo "   git add ."
echo "   git commit -m 'Your change description'"
echo "   git push"
echo ""
echo "3. Watch the deployment:"
echo "   - Go to: https://github.com/slacassegbb/azure-a2a-main/actions"
echo "   - The workflow will automatically deploy only the changed services"
echo ""
echo "4. Test your changes:"
echo "   - Frontend:  https://frontend-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io"
echo "   - Backend:   https://backend-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io"
echo "   - WebSocket: https://websocket-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io"
echo ""
echo "🎯 Smart Deployment:"
echo "   - Only frontend/ changes → Only frontend deploys"
echo "   - Only backend/ changes → Backend + WebSocket deploy"
echo "   - Both changed → All three deploy"
echo ""
echo "💡 Manual trigger:"
echo "   - Go to Actions tab → 'Deploy to Azure Container Apps' → 'Run workflow'"
echo ""
