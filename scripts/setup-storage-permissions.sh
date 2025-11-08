#!/bin/bash
# Script to assign Storage Blob Data Contributor role for Azure managed identity authentication
# This is required when using AZURE_STORAGE_ACCOUNT_NAME without connection string

set -e  # Exit on error

echo "🔐 Setting up Azure Storage permissions for managed identity authentication"
echo ""

# Get the current user's object ID
echo "📋 Getting your Azure AD user object ID..."
USER_OBJECT_ID=$(az ad signed-in-user show --query id -o tsv)
echo "✅ User Object ID: $USER_OBJECT_ID"
echo ""

# Get storage account name from environment or prompt
if [ -z "$AZURE_STORAGE_ACCOUNT_NAME" ]; then
    echo "⚠️  AZURE_STORAGE_ACCOUNT_NAME not set in environment"
    read -p "Enter your storage account name (e.g., stsummit1000): " STORAGE_ACCOUNT_NAME
else
    STORAGE_ACCOUNT_NAME=$AZURE_STORAGE_ACCOUNT_NAME
    echo "📦 Using storage account: $STORAGE_ACCOUNT_NAME"
fi
echo ""

# Get the resource group for the storage account
echo "🔍 Finding resource group for storage account..."
RESOURCE_GROUP=$(az storage account show --name "$STORAGE_ACCOUNT_NAME" --query resourceGroup -o tsv)
echo "✅ Resource Group: $RESOURCE_GROUP"
echo ""

# Get subscription ID
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
echo "📍 Subscription ID: $SUBSCRIPTION_ID"
echo ""

# Build the scope
SCOPE="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$STORAGE_ACCOUNT_NAME"

# Assign the role
echo "🎯 Assigning 'Storage Blob Data Contributor' role..."
echo "   Assignee: $USER_OBJECT_ID"
echo "   Scope: $SCOPE"
echo ""

az role assignment create \
    --assignee "$USER_OBJECT_ID" \
    --role "Storage Blob Data Contributor" \
    --scope "$SCOPE"

echo ""
echo "✅ Role assignment complete!"
echo ""
echo "📝 Next steps:"
echo "   1. Make sure .env has AZURE_STORAGE_ACCOUNT_NAME set (no connection string)"
echo "   2. Make sure AZURE_STORAGE_CONNECTION_STRING is commented out or removed"
echo "   3. Restart your backend server to use managed identity authentication"
echo ""
