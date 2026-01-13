############################################################
# Makefile for Azure A2A Multi-Agent Platform
# Purpose: Manage environment, deployment, and app tasks
############################################################

.PHONY: help create_conda_env activate_conda_env remove_conda_env \
        start_backend start_frontend start_tunnel \
        list_agents start_agent \
        docker_backend docker_frontend docker_agent \
        docker_build_all docker_up docker_down

# Python interpreter to use
PYTHON_INTERPRETER = python
# Conda environment name
CONDA_ENV ?= a2a-environment
# Ensure current directory is in PYTHONPATH
export PYTHONPATH=$(PWD):$PYTHONPATH;
SCRIPTS_DIR = scripts/

# Default target - show help
help:
	@echo "Azure A2A Multi-Agent Platform"
	@echo "==============================="
	@echo ""
	@echo "Environment Setup:"
	@echo "  make create_conda_env    Create conda environment"
	@echo "  make remove_conda_env    Remove conda environment"
	@echo ""
	@echo "Local Development:"
	@echo "  make start_backend       Start the backend server"
	@echo "  make start_frontend      Start the frontend dev server"
	@echo "  make start_tunnel        Start dev tunnel for public access"
	@echo ""
	@echo "Remote Agents:"
	@echo "  make list_agents         List available remote agents"
	@echo "  make start_agent AGENT=<name>  Start a specific agent"
	@echo ""
	@echo "Docker Deployment:"
	@echo "  make docker_backend      Build & run backend in Docker"
	@echo "  make docker_frontend     Build & run frontend in Docker"
	@echo "  make docker_agent AGENT=<name> PORT=<port>  Run agent in Docker"
	@echo ""
	@echo "Examples:"
	@echo "  make start_agent AGENT=azurefoundry_template"
	@echo "  make docker_agent AGENT=azurefoundry_fraud PORT=9004"

# ============================================================
# Environment Management
# ============================================================

create_conda_env:
	@echo "Creating conda environment from environment.yaml..."
	conda env create -f environment.yaml

activate_conda_env:
	@echo "To activate: conda activate $(CONDA_ENV)"

remove_conda_env:
	@echo "Removing conda environment..."
	conda env remove --name $(CONDA_ENV)

# ============================================================
# Local Development
# ============================================================

start_backend:
	$(PYTHON_INTERPRETER) $(SCRIPTS_DIR)/start_backend.py

start_frontend:
	bash $(SCRIPTS_DIR)/start_frontend.sh

start_tunnel:
	bash $(SCRIPTS_DIR)/start_devtunnel_host.sh

# ============================================================
# Remote Agents
# ============================================================

list_agents:
	@bash $(SCRIPTS_DIR)/start_remote_agents.sh list

start_agent:
ifndef AGENT
	@echo "❌ Please specify AGENT=<agent_name>"
	@echo "   Example: make start_agent AGENT=azurefoundry_template"
	@exit 1
endif
	@bash $(SCRIPTS_DIR)/start_remote_agents.sh start $(AGENT)

# ============================================================
# Docker Deployment
# ============================================================

docker_backend:
	@echo "🐳 Building and running backend for linux/amd64..."
	docker buildx build --platform linux/amd64 -t a2a-backend -f backend/Dockerfile --load .
	docker run -d --name a2a-backend -p 12000:12000 -p 8080:8080 --env-file backend/.env a2a-backend

docker_frontend:
	@echo "🐳 Building and running frontend for linux/amd64..."
	docker buildx build --platform linux/amd64 -t a2a-frontend -f frontend/Dockerfile --load ./frontend
	docker run -d --name a2a-frontend -p 3000:3000 a2a-frontend

docker_agent:
ifndef AGENT
	@echo "❌ Please specify AGENT=<agent_name> and PORT=<port>"
	@exit 1
endif
ifndef PORT
	@echo "❌ Please specify PORT=<port>"
	@exit 1
endif
	@bash $(SCRIPTS_DIR)/start_remote_agents.sh docker $(AGENT) $(PORT)

# Build all Docker images
docker_build_all:
	@echo "🐳 Building all Docker images for linux/amd64..."
	docker buildx build --platform linux/amd64 -t a2a-backend -f backend/Dockerfile --load .
	docker buildx build --platform linux/amd64 -t a2a-frontend -f frontend/Dockerfile --load ./frontend
	@echo "✅ All images built"

# Start with docker-compose (frontend)
docker_up:
	cd frontend && docker-compose up -d

docker_down:
	cd frontend && docker-compose down
