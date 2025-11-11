#!/bin/bash

# ============================================================
# Script: start_backend.sh
# Purpose: Start the Host Orchestrator (Backend)
# ============================================================

set -e

# Get the project root (parent of scripts directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
VENV_DIR="$BACKEND_DIR/.venv"

echo "⚙️  Starting Host Orchestrator (Backend)"
echo "=========================================="

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed"
    echo "Please install Python 3.8 or higher"
    exit 1
fi

echo "✅ Python version: $(python3 --version)"

# Check if backend directory exists
if [[ ! -d "$BACKEND_DIR" ]]; then
    echo "❌ Error: Backend directory not found at $BACKEND_DIR"
    exit 1
fi

# Navigate to backend directory
cd "$BACKEND_DIR"

# Create virtual environment if it doesn't exist
if [[ ! -d "$VENV_DIR" ]]; then
    echo ""
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
    echo "✅ Virtual environment created"
fi

# Activate virtual environment
echo ""
echo "🔧 Activating virtual environment..."
source .venv/bin/activate

# Install/upgrade pip
echo ""
echo "📦 Upgrading pip..."
python -m pip install --upgrade pip

# Install dependencies
echo ""
echo "📦 Installing backend dependencies..."
python -m pip install -r "$PROJECT_ROOT/requirements.txt"

# Check Azure CLI login
echo ""
echo "🔐 Checking Azure login..."
if ! command -v az &> /dev/null; then
    echo "⚠️  Warning: Azure CLI is not installed"
    echo "   Install from: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
    echo ""
    read -p "Continue without Azure login check? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    if ! az account show &> /dev/null; then
        echo "⚠️  Warning: Not logged into Azure"
        echo "   Please run: az login"
        echo ""
        read -p "Continue without Azure login? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        echo "✅ Azure login verified"
    fi
fi

# Start the backend
echo ""
echo "🚀 Starting backend server..."
echo "   WebSocket server: http://localhost:8080"
echo "   A2A Backend API: http://localhost:12000"
echo ""

python backend_production.py
