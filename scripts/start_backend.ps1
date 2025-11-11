# ============================================================
# Script: start_backend.ps1
# Purpose: Start the Host Orchestrator (Backend)
# ============================================================

$ErrorActionPreference = "Stop"

# Get the project root (parent of scripts directory)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$BackendDir = Join-Path $ProjectRoot "backend"
$VenvDir = Join-Path $BackendDir ".venv"

Write-Host ""
Write-Host "⚙️  Starting Host Orchestrator (Backend)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check if Python is installed
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✅ Python version: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Error: Python is not installed" -ForegroundColor Red
    Write-Host "Please install Python 3.8 or higher from: https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

# Check if backend directory exists
if (-not (Test-Path $BackendDir)) {
    Write-Host "❌ Error: Backend directory not found at $BackendDir" -ForegroundColor Red
    exit 1
}

# Navigate to backend directory
Set-Location $BackendDir

# Create virtual environment if it doesn't exist
if (-not (Test-Path $VenvDir)) {
    Write-Host ""
    Write-Host "📦 Creating virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
    Write-Host "✅ Virtual environment created" -ForegroundColor Green
}

# Activate virtual environment
Write-Host ""
Write-Host "🔧 Activating virtual environment..." -ForegroundColor Yellow
& "$VenvDir\Scripts\Activate.ps1"

# Install/upgrade pip
Write-Host ""
Write-Host "📦 Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip | Out-Null

# Install dependencies
Write-Host ""
Write-Host "📦 Installing backend dependencies..." -ForegroundColor Yellow
$RequirementsFile = Join-Path $ProjectRoot "requirements.txt"
python -m pip install -r $RequirementsFile

# Check Azure CLI login
Write-Host ""
Write-Host "🔐 Checking Azure login..." -ForegroundColor Yellow
try {
    $azVersion = az --version 2>&1 | Select-Object -First 1
    try {
        az account show 2>&1 | Out-Null
        Write-Host "✅ Azure login verified" -ForegroundColor Green
    } catch {
        Write-Host "⚠️  Warning: Not logged into Azure" -ForegroundColor Yellow
        Write-Host "   Please run: az login" -ForegroundColor Yellow
        Write-Host ""
        $response = Read-Host "Continue without Azure login? (y/n)"
        if ($response -ne "y" -and $response -ne "Y") {
            exit 1
        }
    }
} catch {
    Write-Host "⚠️  Warning: Azure CLI is not installed" -ForegroundColor Yellow
    Write-Host "   Install from: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli" -ForegroundColor Yellow
    Write-Host ""
    $response = Read-Host "Continue without Azure login check? (y/n)"
    if ($response -ne "y" -and $response -ne "Y") {
        exit 1
    }
}

# Start the backend
Write-Host ""
Write-Host "🚀 Starting backend server..." -ForegroundColor Green
Write-Host "   WebSocket server: http://localhost:8080" -ForegroundColor Cyan
Write-Host "   A2A Backend API: http://localhost:12000" -ForegroundColor Cyan
Write-Host ""

python backend_production.py
