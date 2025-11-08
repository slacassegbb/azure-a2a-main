# Scripts

This folder contains utility scripts for setting up and managing the Azure A2A system.

## Available Scripts

### `setup-storage-permissions.sh` (Bash/macOS/Linux)

Assigns the "Storage Blob Data Contributor" role to your Azure AD user for the specified storage account. This is required when using managed identity authentication instead of connection strings.

**Prerequisites:**

- Azure CLI installed and authenticated (`az login`)
- Permission to assign roles on the storage account

**Usage:**

```bash
# Option 1: Set AZURE_STORAGE_ACCOUNT_NAME in your environment
export AZURE_STORAGE_ACCOUNT_NAME="yourstorageaccount"
./scripts/setup-storage-permissions.sh

# Option 2: Run directly and enter the storage account name when prompted
./scripts/setup-storage-permissions.sh
```

### `setup-storage-permissions.ps1` (PowerShell/Windows)

PowerShell version of the storage permissions setup script.

**Prerequisites:**

- Azure CLI installed and authenticated (`az login`)
- Permission to assign roles on the storage account

**Usage:**

```powershell
# Option 1: Set AZURE_STORAGE_ACCOUNT_NAME in your environment
$env:AZURE_STORAGE_ACCOUNT_NAME = "yourstorageaccount"
.\scripts\setup-storage-permissions.ps1

# Option 2: Run directly and enter the storage account name when prompted
.\scripts\setup-storage-permissions.ps1
```

**What it does:**

1. Gets your Azure AD user object ID
2. Finds the resource group for your storage account
3. Assigns "Storage Blob Data Contributor" role at the storage account scope
4. Displays confirmation and next steps

**When to use:**

- Setting up a new development environment
- Switching from connection string to managed identity authentication
- When you get "Key based authentication is not permitted" errors

## Additional Notes

- These scripts are for development/setup purposes
- For production deployments, use managed identities assigned to your Azure resources (App Service, Container Apps, etc.)
- Always follow the principle of least privilege when assigning roles
