#!/bin/bash
#
# Complete Coverage Testing Session
# ==================================
#
# This script guides you through a complete coverage testing session
#

set -e

BACKEND_DIR="backend"
COVERAGE_FILE=".coverage"

echo "================================================================="
echo "  🧪 COVERAGE TESTING SESSION"
echo "================================================================="
echo ""

# Check if backend is already running
if lsof -Pi :12000 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo "⚠️  Backend is already running on port 12000"
    echo "   Please stop it first (Ctrl+C in the backend terminal)"
    exit 1
fi

echo "📋 This script will help you:"
echo "   1. Start backend with coverage tracking"
echo "   2. Run automated tests"
echo "   3. Remind you to test the UI"
echo "   4. Generate coverage reports"
echo ""
read -p "Press Enter to continue..."

cd "$BACKEND_DIR"

# Activate venv
echo ""
echo "🔧 Activating virtual environment..."
source .venv/bin/activate

# Clean old coverage data
if [ -f "$COVERAGE_FILE" ]; then
    echo "🗑️  Removing old coverage data..."
    rm -f "$COVERAGE_FILE"
    rm -rf htmlcov
fi

echo ""
echo "================================================================="
echo "  STEP 1: Starting Backend with Coverage"
echo "================================================================="
echo ""
echo "⚠️  IMPORTANT: Keep this terminal open!"
echo "   The backend will run in the FOREGROUND"
echo "   When you're done testing, press Ctrl+C to stop it"
echo ""
echo "Starting backend with coverage tracking..."
echo "Coverage source: hosts/multiagent"
echo ""
read -p "Press Enter to start backend..."

# Start backend with coverage
# This will block until Ctrl+C
coverage run --source=hosts/multiagent backend_production.py

# When backend stops (after Ctrl+C), continue with coverage report
echo ""
echo "================================================================="
echo "  Backend stopped. Generating coverage reports..."
echo "================================================================="
echo ""

# Generate text report
echo "📊 Coverage Summary:"
echo ""
coverage report

# Generate HTML report
echo ""
echo "📈 Generating detailed HTML report..."
coverage html

echo ""
echo "================================================================="
echo "  ✅ Coverage Testing Complete!"
echo "================================================================="
echo ""
echo "📁 Coverage report generated in: htmlcov/"
echo ""
echo "To view the report:"
echo "   open htmlcov/index.html"
echo ""
echo "Or in browser:"
echo "   file://$(pwd)/htmlcov/index.html"
echo ""

read -p "Open report now? (y/n): " open_report
if [[ "$open_report" =~ ^[Yy]$ ]]; then
    open htmlcov/index.html
    echo "✅ Report opened in browser"
fi

echo ""
echo "🎉 Done!"
