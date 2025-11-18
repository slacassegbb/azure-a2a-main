#!/bin/bash
# ============================================================
# Script: start_all_agents.sh
# Purpose: Start all Azure Foundry remote agents in background
# ============================================================

set -e

# Get the project root (parent of scripts directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENTS_DIR="$PROJECT_ROOT/remote_agents"

echo "🤖 Starting all Azure Foundry remote agents..."
echo "================================================"
echo ""

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "❌ Error: UV package manager is not installed"
    echo "Please install it with: pip install uv"
    exit 1
fi

# Array of all agents with their directories and ports
declare -A AGENTS
AGENTS[azurefoundry_template]="9020"
AGENTS[azurefoundry_assessment]="9002"
AGENTS[azurefoundry_branding]="9033"
AGENTS[azurefoundry_claims]="9001"
AGENTS[azurefoundry_classification]="8001"
AGENTS[azurefoundry_Deep_Search]="8002"
AGENTS[azurefoundry_fraud]="9004"
AGENTS[azurefoundry_image_analysis]="9066"
AGENTS[azurefoundry_image_generator]="9010"
AGENTS[azurefoundry_legal]="8006"
AGENTS[azurefoundry_SN]="8000"
AGENTS[google_adk]="8003"

# Start each agent in background
for agent in "${!AGENTS[@]}"; do
    port="${AGENTS[$agent]}"
    agent_dir="$AGENTS_DIR/$agent"
    
    if [[ ! -d "$agent_dir" ]]; then
        echo "⚠️  Warning: Agent directory not found: $agent_dir"
        continue
    fi
    
    echo "🚀 Starting $agent on port $port..."
    
    # Start agent in background
    cd "$agent_dir"
    if [[ "$agent" == "google_adk" ]]; then
        nohup python __main__.py > "/tmp/${agent}.log" 2>&1 &
    else
        nohup uv run . > "/tmp/${agent}.log" 2>&1 &
    fi
    
    echo "   ✅ Started (PID: $!, Logs: /tmp/${agent}.log)"
    sleep 1
done

echo ""
echo "✅ All agents started in background!"
echo ""
echo "📊 Agent Status:"
echo "   • Backend should be running at: http://localhost:12000"
echo "   • Frontend should be running at: http://localhost:3000"
echo "   • Agents will auto-register with the backend"
echo ""
echo "📋 To view logs:"
echo "   tail -f /tmp/azurefoundry_*.log"
echo ""
echo "🛑 To stop all agents:"
echo "   make stop-all"