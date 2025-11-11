# ============================================================
# Script: start_frontend.ps1
# Purpose: Start the Multi-Agent UI Frontend (Next.js)
# ============================================================

$ErrorActionPreference = "Stop"

# Get the project root (parent of scripts directory)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$FrontendDir = Join-Path $ProjectRoot "frontend"

Write-Host ""
Write-Host "🖥️  Starting Multi-Agent UI (Frontend)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check if Node.js is installed
try {
    $nodeVersion = node --version 2>&1
    $npmVersion = npm --version 2>&1
    Write-Host "✅ Node.js version: $nodeVersion" -ForegroundColor Green
    Write-Host "✅ npm version: $npmVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Error: Node.js is not installed" -ForegroundColor Red
    Write-Host "Please download and install Node.js from: https://nodejs.org/en/download/" -ForegroundColor Yellow
    exit 1
}

# Check if frontend directory exists
if (-not (Test-Path $FrontendDir)) {
    Write-Host "❌ Error: Frontend directory not found at $FrontendDir" -ForegroundColor Red
    exit 1
}

# Navigate to frontend directory
Set-Location $FrontendDir

# Install dependencies
Write-Host ""
Write-Host "📦 Installing frontend dependencies..." -ForegroundColor Yellow
npm install

# Start the development server
Write-Host ""
Write-Host "🚀 Starting frontend dev server..." -ForegroundColor Green
Write-Host "   Frontend will be available at: http://localhost:3000" -ForegroundColor Cyan
Write-Host "   WebSocket backend should be running at: http://localhost:8080" -ForegroundColor Cyan
Write-Host ""

npm run dev
