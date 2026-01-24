#!/bin/bash

# ====================================================================
# Azure OpenAI Sora 2 Model Deployment Script
# ====================================================================
# This script provisions a Sora 2 model deployment in your Azure OpenAI
# resource for use with the Video Agent.
#
# Prerequisites:
# - Azure CLI installed and logged in (az login)
# - Sora 2 access granted to your subscription
# - Existing Azure OpenAI resource in East US 2
# ====================================================================

set -e  # Exit on error

echo "🎬 Azure OpenAI Sora 2 Deployment Script"
echo "========================================"
echo ""

# Configuration - UPDATE THESE VALUES
SUBSCRIPTION_ID="4f134af7-23ad-4bc1-85a4-748d72a8b663"
RESOURCE_GROUP="simon_rc"
AZURE_OPENAI_NAME="simon-miaxownu-eastus2"  # From your .env file
LOCATION="eastus2"
DEPLOYMENT_NAME="sora-2"
MODEL_NAME="sora-2"
MODEL_VERSION="2025-10-06"  # Latest version available in your subscription
CAPACITY=10  # TPM capacity - adjust as needed

echo "Configuration:"
echo "  Subscription: $SUBSCRIPTION_ID"
echo "  Resource Group: $RESOURCE_GROUP"
echo "  Azure OpenAI: $AZURE_OPENAI_NAME"
echo "  Location: $LOCATION"
echo "  Deployment Name: $DEPLOYMENT_NAME"
echo ""

# Confirm before proceeding
read -p "Continue with deployment? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    echo "❌ Deployment cancelled"
    exit 1
fi

# Set the subscription
echo "📋 Setting active subscription..."
az account set --subscription "$SUBSCRIPTION_ID"

# Check if Azure OpenAI resource exists
echo "🔍 Checking Azure OpenAI resource..."
if ! az cognitiveservices account show \
    --name "$AZURE_OPENAI_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --subscription "$SUBSCRIPTION_ID" > /dev/null 2>&1; then
    echo "❌ Error: Azure OpenAI resource '$AZURE_OPENAI_NAME' not found in resource group '$RESOURCE_GROUP'"
    echo "Please update RESOURCE_GROUP and AZURE_OPENAI_NAME variables in this script"
    exit 1
fi

echo "✅ Azure OpenAI resource found"

# Check if deployment already exists
echo "🔍 Checking for existing deployment..."
if az cognitiveservices account deployment show \
    --name "$AZURE_OPENAI_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --deployment-name "$DEPLOYMENT_NAME" \
    --subscription "$SUBSCRIPTION_ID" > /dev/null 2>&1; then
    echo "⚠️  Deployment '$DEPLOYMENT_NAME' already exists"
    read -p "Delete and recreate? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "🗑️  Deleting existing deployment..."
        az cognitiveservices account deployment delete \
            --name "$AZURE_OPENAI_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --deployment-name "$DEPLOYMENT_NAME" \
            --subscription "$SUBSCRIPTION_ID"
        echo "✅ Existing deployment deleted"
    else
        echo "❌ Deployment cancelled"
        exit 1
    fi
fi

# Create the Sora 2 deployment
echo "🚀 Creating Sora 2 deployment..."
echo "   This may take several minutes..."

az cognitiveservices account deployment create \
    --name "$AZURE_OPENAI_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --deployment-name "$DEPLOYMENT_NAME" \
    --model-name "$MODEL_NAME" \
    --model-version "$MODEL_VERSION" \
    --model-format OpenAI \
    --sku-capacity "$CAPACITY" \
    --sku-name "GlobalStandard" \
    --subscription "$SUBSCRIPTION_ID"

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Sora 2 deployment successful!"
    echo ""
    echo "📝 Deployment Details:"
    echo "   Deployment Name: $DEPLOYMENT_NAME"
    echo "   Model: $MODEL_NAME"
    echo "   Version: $MODEL_VERSION"
    echo "   Capacity: $CAPACITY TPM"
    echo ""
    echo "🎯 Next Steps:"
    echo "   1. The video agent is already configured to use this endpoint"
    echo "   2. Start the video agent with:"
    echo "      cd remote_agents/azurefoundry_video"
    echo "      source .venv/bin/activate"
    echo "      uv run ."
    echo ""
else
    echo ""
    echo "❌ Deployment failed!"
    echo ""
    echo "Common issues:"
    echo "  1. Sora 2 may not be available yet in your subscription despite access approval"
    echo "  2. Model version may be incorrect - check Azure docs for latest version"
    echo "  3. Region may not support Sora 2 yet - try different regions"
    echo "  4. Resource group or resource name may be incorrect"
    echo ""
    echo "📚 For more information:"
    echo "   https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/create-resource"
    echo ""
    exit 1
fi
