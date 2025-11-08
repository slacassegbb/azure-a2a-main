# PowerShell script to assign Storage Blob Data Contributor role for Azure managed identity authentication
# This is required when using AZURE_STORAGE_ACCOUNT_NAME without connection string

$ErrorActionPreference = "Stop"  # Exit on error

Write-Host "🔐 Setting up Azure Storage permissions for managed identity authentication" -ForegroundColor Cyan
Write-Host ""

# Get the current user's object ID
Write-Host "📋 Getting your Azure AD user object ID..." -ForegroundColor Yellow
$UserObjectId = az ad signed-in-user show --query id -o tsv
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to get user object ID. Make sure you're logged in with 'az login'" -ForegroundColor Red
    exit 1
}
Write-Host "✅ User Object ID: $UserObjectId" -ForegroundColor Green
Write-Host ""

# Get storage account name from environment or prompt
if ($env:AZURE_STORAGE_ACCOUNT_NAME) {
    $StorageAccountName = $env:AZURE_STORAGE_ACCOUNT_NAME
    Write-Host "📦 Using storage account: $StorageAccountName" -ForegroundColor Yellow
} else {
    Write-Host "⚠️  AZURE_STORAGE_ACCOUNT_NAME not set in environment" -ForegroundColor Yellow
    $StorageAccountName = Read-Host "Enter your storage account name (e.g., stsummit1000)"
}
Write-Host ""

# Get the resource group for the storage account
Write-Host "🔍 Finding resource group for storage account..." -ForegroundColor Yellow
$ResourceGroup = az storage account show --name $StorageAccountName --query resourceGroup -o tsv
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to find storage account. Check the name and your permissions." -ForegroundColor Red
    exit 1
}
Write-Host "✅ Resource Group: $ResourceGroup" -ForegroundColor Green
Write-Host ""

# Get subscription ID
$SubscriptionId = az account show --query id -o tsv
Write-Host "📍 Subscription ID: $SubscriptionId" -ForegroundColor Yellow
Write-Host ""

# Build the scope
$Scope = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Storage/storageAccounts/$StorageAccountName"

# Assign the role
Write-Host "🎯 Assigning 'Storage Blob Data Contributor' role..." -ForegroundColor Yellow
Write-Host "   Assignee: $UserObjectId"
Write-Host "   Scope: $Scope"
Write-Host ""

az role assignment create `
    --assignee $UserObjectId `
    --role "Storage Blob Data Contributor" `
    --scope $Scope

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "✅ Role assignment complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "📝 Next steps:" -ForegroundColor Cyan
    Write-Host "   1. Make sure .env has AZURE_STORAGE_ACCOUNT_NAME set (no connection string)"
    Write-Host "   2. Make sure AZURE_STORAGE_CONNECTION_STRING is commented out or removed"
    Write-Host "   3. Restart your backend server to use managed identity authentication"
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "❌ Role assignment failed. Check the error message above." -ForegroundColor Red
    exit 1
}
