#!/bin/bash

# ============================================================
# Script: start_remote_agents.sh
# Purpose: Start one or more A2A remote agents
# ============================================================

set -e

# Get the project root (parent of scripts directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REMOTE_AGENTS_DIR="$PROJECT_ROOT/remote_agents"

echo "🤖 A2A Remote Agents Launcher"
echo "=============================="
echo ""

# List available agents
list_agents() {
    echo "Available agents:"
    echo ""
    for agent_dir in "$REMOTE_AGENTS_DIR"/azurefoundry_*/; do
        if [ -d "$agent_dir" ]; then
            agent_name=$(basename "$agent_dir")
            echo "  - $agent_name"
        fi
    done
    if [ -d "$REMOTE_AGENTS_DIR/google_adk" ]; then
        echo "  - google_adk"
    fi
    echo ""
}

# Start a single agent
start_agent() {
    local agent_name=$1
    local agent_dir="$REMOTE_AGENTS_DIR/$agent_name"
    
    if [ ! -d "$agent_dir" ]; then
        echo "❌ Agent not found: $agent_name"
        return 1
    fi
    
    echo "🚀 Starting $agent_name..."
    cd "$agent_dir"
    
    # Check if .venv exists, if not create it
    if [ ! -d ".venv" ]; then
        echo "   Creating virtual environment..."
        python3 -m venv .venv
    fi
    
    # Activate and run
    source .venv/bin/activate
    
    # Install uv if not present
    if ! command -v uv &> /dev/null; then
        pip install uv
    fi
    
    # Run the agent
    uv run .
}

# Start agent with Docker
start_agent_docker() {
    local agent_name=$1
    local port=$2
    local agent_dir="$REMOTE_AGENTS_DIR/$agent_name"
    
    if [ ! -d "$agent_dir" ]; then
        echo "❌ Agent not found: $agent_name"
        return 1
    fi
    
    echo "🐳 Starting $agent_name in Docker on port $port (linux/amd64)..."
    cd "$agent_dir"
    
    docker buildx build --platform linux/amd64 -t "a2a-$agent_name" --load .
    docker run -d \
        --name "a2a-$agent_name" \
        -p "$port:$port" \
        -e "A2A_PORT=$port" \
        --env-file .env \
        "a2a-$agent_name"
    
    echo "✅ $agent_name running on port $port"
}

# Show usage
usage() {
    echo "Usage: $0 [command] [agent_name] [options]"
    echo ""
    echo "Commands:"
    echo "  list              List available agents"
    echo "  start <agent>     Start an agent locally"
    echo "  docker <agent> <port>  Start an agent in Docker"
    echo ""
    echo "Examples:"
    echo "  $0 list"
    echo "  $0 start azurefoundry_template"
    echo "  $0 docker azurefoundry_fraud 9004"
    echo ""
}

# Main
case "$1" in
    list)
        list_agents
        ;;
    start)
        if [ -z "$2" ]; then
            echo "❌ Please specify an agent name"
            usage
            exit 1
        fi
        start_agent "$2"
        ;;
    docker)
        if [ -z "$2" ] || [ -z "$3" ]; then
            echo "❌ Please specify agent name and port"
            usage
            exit 1
        fi
        start_agent_docker "$2" "$3"
        ;;
    *)
        usage
        ;;
esac

