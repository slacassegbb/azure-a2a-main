#!/bin/bash

# ============================================================
# Script: start_frontend.sh
# Purpose: Start the Multi-Agent UI Frontend (Next.js)
# ============================================================

set -e

# Get the project root (parent of scripts directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

echo "🖥️  Starting Multi-Agent UI (Frontend)"
echo "=========================================="

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "❌ Error: Node.js is not installed"
    echo "Please download and install Node.js from: https://nodejs.org/en/download/"
    exit 1
fi

echo "✅ Node.js version: $(node --version)"
echo "✅ npm version: $(npm --version)"

# Check if frontend directory exists
if [[ ! -d "$FRONTEND_DIR" ]]; then
    echo "❌ Error: Frontend directory not found at $FRONTEND_DIR"
    exit 1
fi

# Navigate to frontend directory
cd "$FRONTEND_DIR"

# Install dependencies
echo ""
echo "📦 Installing frontend dependencies..."
npm install

# Start the development server
echo ""
echo "🚀 Starting frontend dev server..."
echo "   Frontend will be available at: http://localhost:3000"
echo "   WebSocket backend should be running at: http://localhost:8080"
echo ""

npm run dev
