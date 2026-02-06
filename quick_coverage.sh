#!/bin/bash
# Quick Coverage Analysis for foundry_agent_a2a.py

echo "🎯 Quick Coverage Check for foundry_agent_a2a.py"
echo "=================================================="

# Clear previous coverage data
coverage erase

# Option 1: Just import the module and check basic coverage
echo ""
echo "📊 Measuring import-level coverage..."
coverage run --source=backend/hosts/multiagent -m py_compile backend/hosts/multiagent/foundry_agent_a2a.py

# Option 2: If you have pytest tests
# coverage run -m pytest backend/tests/ -v

# Generate report
echo ""
echo "📈 Coverage Report:"
echo "==================="
coverage report --include="backend/hosts/multiagent/foundry_agent_a2a.py"

# Generate HTML report
coverage html --include="backend/hosts/multiagent/foundry_agent_a2a.py"

echo ""
echo "✅ Done! View HTML report at: htmlcov/index.html"
echo "Run: open htmlcov/index.html"
