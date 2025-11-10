# Docker Build and Run Script for A2A System
# This script builds and runs both backend and visualizer services

Write-Host "🐳 A2A System - Docker Build & Run Script" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check if .env exists
if (-not (Test-Path ".env")) {
    Write-Host "❌ Error: .env file not found in root directory!" -ForegroundColor Red
    Write-Host "Please create .env from .env.example" -ForegroundColor Yellow
    exit 1
}

# Check if visualizer .env.local exists
if (-not (Test-Path "Visualizer/voice-a2a-fabric/.env.local")) {
    Write-Host "⚠️  Warning: .env.local not found in Visualizer/voice-a2a-fabric/" -ForegroundColor Yellow
    Write-Host "The visualizer may not work properly without environment variables" -ForegroundColor Yellow
    Write-Host ""
}

# Ask user what to do
Write-Host "What would you like to do?" -ForegroundColor Green
Write-Host "1. Build and start all services (docker-compose up --build)" -ForegroundColor White
Write-Host "2. Start existing containers (docker-compose up)" -ForegroundColor White
Write-Host "3. Stop all services (docker-compose down)" -ForegroundColor White
Write-Host "4. View logs (docker-compose logs -f)" -ForegroundColor White
Write-Host "5. Rebuild backend only" -ForegroundColor White
Write-Host "6. Rebuild visualizer only" -ForegroundColor White
Write-Host "7. Clean everything (down + remove volumes)" -ForegroundColor White
Write-Host ""

$choice = Read-Host "Enter your choice (1-7)"

switch ($choice) {
    "1" {
        Write-Host "🔨 Building and starting all services..." -ForegroundColor Cyan
        docker-compose up --build
    }
    "2" {
        Write-Host "▶️  Starting services..." -ForegroundColor Cyan
        docker-compose up
    }
    "3" {
        Write-Host "⏹️  Stopping services..." -ForegroundColor Cyan
        docker-compose down
    }
    "4" {
        Write-Host "📋 Viewing logs (Ctrl+C to exit)..." -ForegroundColor Cyan
        docker-compose logs -f
    }
    "5" {
        Write-Host "🔨 Rebuilding backend..." -ForegroundColor Cyan
        docker-compose build backend
        docker-compose up -d backend
    }
    "6" {
        Write-Host "🔨 Rebuilding visualizer..." -ForegroundColor Cyan
        docker-compose build visualizer
        docker-compose up -d visualizer
    }
    "7" {
        Write-Host "🧹 Cleaning everything..." -ForegroundColor Cyan
        docker-compose down -v
        Write-Host "✅ All containers and volumes removed" -ForegroundColor Green
    }
    default {
        Write-Host "❌ Invalid choice" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "✅ Done!" -ForegroundColor Green
Write-Host ""
Write-Host "Access your services at:" -ForegroundColor Cyan
Write-Host "  - Backend API:  http://localhost:12000" -ForegroundColor White
Write-Host "  - Frontend:     http://localhost:3000" -ForegroundColor White
Write-Host "  - Visualizer:   http://localhost:3001" -ForegroundColor White
Write-Host "  - WebSocket:    ws://localhost:8080" -ForegroundColor White
