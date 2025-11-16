############################################################
# Azure A2A Multi-Agent System - Makefile
# Purpose: Manage backend, frontend, and remote agent lifecycle
# Usage: make <target>
############################################################

.PHONY: help install-backend install-frontend install-all start-backend start-frontend \
        start-websocket start-all-agents stop-all check-deps clean test lint format \
        docker-build docker-build-backend docker-build-frontend docker-build-agents \
        docker-up docker-down docker-logs docker-clean \
        create-conda-env activate-conda-env remove-conda-env install-conda-deps

# Configuration
PYTHON := python3
PIP := pip
BACKEND_DIR := backend
FRONTEND_DIR := frontend
REMOTE_AGENTS_DIR := remote_agents
SCRIPTS_DIR := scripts

# Colors for output
GREEN := \033[0;32m
YELLOW := \033[1;33m
RED := \033[0;31m
NC := \033[0m # No Color

##@ Help
help: ## Display this help message
	@echo "$(GREEN)Azure A2A Multi-Agent System - Available Commands$(NC)"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make $(YELLOW)<target>$(NC)\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2 } /^##@/ { printf "\n$(YELLOW)%s$(NC)\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Installation
create-conda-env: ## Create Conda environment from environemnt.yaml
	@echo "$(GREEN)🐍 Creating Conda environment 'a2a-environment'...$(NC)"
	conda env create -f environemnt.yaml
	@echo "$(GREEN)✅ Conda environment created$(NC)"
	@echo "$(YELLOW)💡 Activate with: conda activate a2a-environment$(NC)"

activate-conda-env: ## Instructions to activate Conda environment
	@echo "$(YELLOW)To activate the Conda environment, run:$(NC)"
	@echo "  conda activate a2a-environment"

remove-conda-env: ## Remove Conda environment
	@echo "$(YELLOW)⚠️  Removing Conda environment 'a2a-environment'...$(NC)"
	conda env remove --name a2a-environment
	@echo "$(GREEN)✅ Conda environment removed$(NC)"

install-conda-deps: ## Install/update dependencies in active Conda environment
	@echo "$(GREEN)📦 Installing dependencies in Conda environment...$(NC)"
	@if [ -z "$$CONDA_DEFAULT_ENV" ]; then \
		echo "$(RED)❌ No Conda environment active. Run: conda activate a2a-environment$(NC)"; \
		exit 1; \
	fi
	conda env update -f environemnt.yaml
	@echo "$(GREEN)✅ Dependencies installed$(NC)"

install-backend: ## Install backend dependencies
	@echo "$(GREEN)📦 Installing backend dependencies...$(NC)"
	cd $(BACKEND_DIR) && \
		$(PYTHON) -m venv .venv && \
		. .venv/bin/activate && \
		$(PIP) install --upgrade pip && \
		$(PIP) install -r requirements.txt
	@echo "$(GREEN)✅ Backend dependencies installed$(NC)"

install-frontend: ## Install frontend dependencies
	@echo "$(GREEN)📦 Installing frontend dependencies...$(NC)"
	cd $(FRONTEND_DIR) && npm install
	@echo "$(GREEN)✅ Frontend dependencies installed$(NC)"

install-all: install-backend install-frontend ## Install all dependencies (backend + frontend)
	@echo "$(GREEN)✅ All dependencies installed$(NC)"

##@ Development - Start Services
start_backend: ## Stbackendtart backend using script (handles setup + dependencies)
	@echo "$(GREEN)🚀 Starting Backend via script...$(NC)"
	bash $(SCRIPTS_DIR)/start_backend.sh

start_frontend: ## Start frontend using script (handles setup + dependencies)
	@echo "$(GREEN)🚀 Starting Frontend via script...$(NC)"
	bash $(SCRIPTS_DIR)/start_frontend.sh

start-all-agents-script: ## Start all agents using script (all 12 agents in background)
	@echo "$(GREEN)🤖 Starting all agents via script...$(NC)"
	bash $(SCRIPTS_DIR)/start_all_agents.sh

start-backend: ## Start the backend server (Host Orchestrator)
	@echo "$(GREEN)🚀 Starting Backend Host Orchestrator on http://localhost:12000$(NC)"
	cd $(BACKEND_DIR) && \
		. .venv/bin/activate && \
		$(PYTHON) backend_production.py

start-websocket: ## Start the WebSocket server
	@echo "$(GREEN)🚀 Starting WebSocket server on ws://localhost:8080$(NC)"
	@echo "$(YELLOW)Note: WebSocket is automatically started with backend$(NC)"

##@ Remote Agents - Individual
start-agent-template: ## Start the template agent (port 9020)
	@echo "$(GREEN)🤖 Starting Template Agent on port 9020$(NC)"
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_template && uv run .

start-agent-assessment: ## Start the assessment agent (port 9002)
	@echo "$(GREEN)🤖 Starting Assessment & Estimation Agent on port 9002$(NC)"
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_assessment && uv run .

start-agent-branding: ## Start the branding agent (port 9033)
	@echo "$(GREEN)🤖 Starting Branding Agent on port 9033$(NC)"
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_branding && uv run .

start-agent-claims: ## Start the claims agent (port 9001)
	@echo "$(GREEN)🤖 Starting Claims Agent on port 9001$(NC)"
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_claims && uv run .

start-agent-classification: ## Start the classification agent (port 8001)
	@echo "$(GREEN)🤖 Starting Classification Agent on port 8001$(NC)"
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_classification && uv run .

start-agent-deep-search: ## Start the deep search agent (port 8002)
	@echo "$(GREEN)🤖 Starting Deep Search Agent on port 8002$(NC)"
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_Deep_Search && uv run .

start-agent-fraud: ## Start the fraud agent (port 9004)
	@echo "$(GREEN)🤖 Starting Fraud Intelligence Agent on port 9004$(NC)"
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_fraud && uv run .

start-agent-image-analysis: ## Start the image analysis agent (port 9066)
	@echo "$(GREEN)🤖 Starting Image Analysis Agent on port 9066$(NC)"
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_image_analysis && uv run .

start-agent-image-generator: ## Start the image generator agent (port 9010)
	@echo "$(GREEN)🤖 Starting Image Generator Agent on port 9010$(NC)"
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_image_generator && uv run .

start-agent-legal: ## Start the legal agent (port 8006)
	@echo "$(GREEN)🤖 Starting Legal Compliance Agent on port 8006$(NC)"
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_legal && uv run .

start-agent-sn: ## Start the ServiceNow MCP agent (port 8000)
	@echo "$(GREEN)🤖 Starting Customer Support (ServiceNow MCP) Agent on port 8000$(NC)"
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_SN && uv run .

start-agent-google: ## Start the Google ADK sentiment agent (port 8003)
	@echo "$(GREEN)🤖 Starting Google ADK Sentiment Agent on port 8003$(NC)"
	cd $(REMOTE_AGENTS_DIR)/google_adk && $(PYTHON) __main__.py

##@ Remote Agents - Bulk
start-all-agents: ## Start all Azure Foundry agents (without UI)
	@echo "$(GREEN)🚀 Starting all Azure Foundry remote agents...$(NC)"
	@echo "$(YELLOW)Note: Agents will start in background. Use 'make stop-all' to stop them.$(NC)"
	@echo ""
	@cd $(REMOTE_AGENTS_DIR)/azurefoundry_template && uv run . & \
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_assessment && uv run . & \
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_branding && uv run . & \
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_claims && uv run . & \
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_classification && uv run . & \
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_Deep_Search && uv run . & \
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_fraud && uv run . & \
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_image_analysis && uv run . & \
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_image_generator && uv run . & \
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_legal && uv run . & \
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_SN && uv run . &
	@echo "$(GREEN)✅ All agents started in background$(NC)"
	@echo "$(YELLOW)💡 TIP: Agents auto-register with backend at http://localhost:12000$(NC)"

start-core-agents: ## Start only core agents (claims, fraud, classification)
	@echo "$(GREEN)🚀 Starting core agents...$(NC)"
	@cd $(REMOTE_AGENTS_DIR)/azurefoundry_claims && uv run . & \
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_fraud && uv run . & \
	cd $(REMOTE_AGENTS_DIR)/azurefoundry_classification && uv run . &
	@echo "$(GREEN)✅ Core agents started$(NC)"

##@ Full System
dev: ## Start full development environment (backend + frontend)
	@echo "$(GREEN)🚀 Starting full development environment...$(NC)"
	@echo "$(YELLOW)Opening backend and frontend in separate terminals...$(NC)"
	@make -j2 start-backend start-frontend

start-all: ## Start backend, frontend, and all agents
	@echo "$(GREEN)🚀 Starting complete A2A Multi-Agent System...$(NC)"
	@echo ""
	@echo "$(YELLOW)1. Starting Backend...$(NC)"
	@make start-backend &
	@sleep 5
	@echo ""
	@echo "$(YELLOW)2. Starting all remote agents...$(NC)"
	@make start-all-agents
	@sleep 2
	@echo ""
	@echo "$(YELLOW)3. Starting Frontend...$(NC)"
	@make start-frontend

##@ Utilities
stop-all: ## Stop all running agents and services
	@echo "$(YELLOW)⚠️  Stopping all services...$(NC)"
	@pkill -f "backend_production.py" || true
	@pkill -f "uv run" || true
	@pkill -f "npm run dev" || true
	@pkill -f "__main__.py" || true
	@echo "$(GREEN)✅ All services stopped$(NC)"

check-deps: ## Check if required dependencies are installed
	@echo "$(GREEN)🔍 Checking dependencies...$(NC)"
	@command -v python3 >/dev/null 2>&1 || { echo "$(RED)❌ Python3 not found$(NC)"; exit 1; }
	@command -v node >/dev/null 2>&1 || { echo "$(RED)❌ Node.js not found$(NC)"; exit 1; }
	@command -v npm >/dev/null 2>&1 || { echo "$(RED)❌ npm not found$(NC)"; exit 1; }
	@command -v uv >/dev/null 2>&1 || { echo "$(YELLOW)⚠️  uv not found (install with: pip install uv)$(NC)"; }
	@command -v az >/dev/null 2>&1 || { echo "$(YELLOW)⚠️  Azure CLI not found (optional)$(NC)"; }
	@echo "$(GREEN)✅ All required dependencies found$(NC)"

status: ## Show status of running services
	@echo "$(GREEN)📊 Service Status$(NC)"
	@echo ""
	@echo "Backend (port 12000):"
	@pgrep -f "backend_production.py" > /dev/null && echo "  $(GREEN)✅ Running$(NC)" || echo "  $(RED)❌ Not running$(NC)"
	@echo ""
	@echo "Frontend (port 3000):"
	@pgrep -f "npm run dev" > /dev/null && echo "  $(GREEN)✅ Running$(NC)" || echo "  $(RED)❌ Not running$(NC)"
	@echo ""
	@echo "Remote Agents:"
	@pgrep -f "uv run" > /dev/null && echo "  $(GREEN)✅ Running$(NC)" || echo "  $(RED)❌ Not running$(NC)"

##@ Code Quality
lint: ## Run linting on backend code
	@echo "$(GREEN)🔍 Running linters...$(NC)"
	cd $(BACKEND_DIR) && \
		. .venv/bin/activate && \
		flake8 . --max-line-length=100 --exclude=.venv || true
	@echo "$(GREEN)✅ Linting complete$(NC)"

format: ## Format backend code with black and isort
	@echo "$(GREEN)✨ Formatting code...$(NC)"
	cd $(BACKEND_DIR) && \
		. .venv/bin/activate && \
		isort . && \
		black . --line-length=100
	@echo "$(GREEN)✅ Formatting complete$(NC)"

test: ## Run backend tests
	@echo "$(GREEN)🧪 Running tests...$(NC)"
	cd $(BACKEND_DIR) && \
		. .venv/bin/activate && \
		pytest tests/ -v
	@echo "$(GREEN)✅ Tests complete$(NC)"

##@ Cleanup
clean: ## Remove build artifacts and caches
	@echo "$(YELLOW)🧹 Cleaning up...$(NC)"
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	cd $(FRONTEND_DIR) && rm -rf .next node_modules/.cache 2>/dev/null || true
	@echo "$(GREEN)✅ Cleanup complete$(NC)"

clean-all: clean ## Remove all generated files including venvs and node_modules
	@echo "$(YELLOW)⚠️  This will remove all virtual environments and node_modules$(NC)"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		rm -rf $(BACKEND_DIR)/.venv; \
		rm -rf $(FRONTEND_DIR)/node_modules; \
		echo "$(GREEN)✅ Deep clean complete$(NC)"; \
	else \
		echo "$(YELLOW)Cancelled$(NC)"; \
	fi

##@ Docker
docker-build: docker-build-backend docker-build-frontend docker-build-agents ## Build all Docker images

docker-build-backend: ## Build backend Docker image
	@echo "$(GREEN)🐳 Building backend Docker image...$(NC)"
	docker build -t a2a-backend:latest -f $(BACKEND_DIR)/Dockerfile .
	@echo "$(GREEN)✅ Backend image built$(NC)"

docker-build-frontend: ## Build frontend Docker image
	@echo "$(GREEN)🐳 Building frontend Docker image...$(NC)"
	docker build -t a2a-frontend:latest -f $(FRONTEND_DIR)/Dockerfile $(FRONTEND_DIR)
	@echo "$(GREEN)✅ Frontend image built$(NC)"

docker-build-agents: ## Build all remote agent Docker images
	@echo "$(GREEN)🐳 Building all agent Docker images...$(NC)"
	@docker build -t a2a-agent-template:latest $(REMOTE_AGENTS_DIR)/azurefoundry_template
	@docker build -t a2a-agent-assessment:latest $(REMOTE_AGENTS_DIR)/azurefoundry_assessment
	@docker build -t a2a-agent-branding:latest $(REMOTE_AGENTS_DIR)/azurefoundry_branding
	@docker build -t a2a-agent-claims:latest $(REMOTE_AGENTS_DIR)/azurefoundry_claims
	@docker build -t a2a-agent-classification:latest $(REMOTE_AGENTS_DIR)/azurefoundry_classification
	@docker build -t a2a-agent-deep-search:latest $(REMOTE_AGENTS_DIR)/azurefoundry_Deep_Search
	@docker build -t a2a-agent-fraud:latest $(REMOTE_AGENTS_DIR)/azurefoundry_fraud
	@docker build -t a2a-agent-image-analysis:latest $(REMOTE_AGENTS_DIR)/azurefoundry_image_analysis
	@docker build -t a2a-agent-image-generator:latest $(REMOTE_AGENTS_DIR)/azurefoundry_image_generator
	@docker build -t a2a-agent-legal:latest $(REMOTE_AGENTS_DIR)/azurefoundry_legal
	@docker build -t a2a-agent-servicenow:latest $(REMOTE_AGENTS_DIR)/azurefoundry_SN
	@docker build -t a2a-agent-google-adk:latest $(REMOTE_AGENTS_DIR)/google_adk
	@echo "$(GREEN)✅ All agent images built$(NC)"

docker-up: ## Start all services with Docker Compose
	@echo "$(GREEN)🐳 Starting services with Docker Compose...$(NC)"
	docker-compose up -d
	@echo "$(GREEN)✅ All services started$(NC)"
	@echo "$(YELLOW)📊 View logs: make docker-logs$(NC)"
	@echo "$(YELLOW)🔍 Check status: docker-compose ps$(NC)"

docker-up-backend: ## Start only backend and frontend with Docker Compose
	@echo "$(GREEN)🐳 Starting backend and frontend...$(NC)"
	docker-compose up -d backend frontend
	@echo "$(GREEN)✅ Backend and frontend started$(NC)"

docker-up-agents: ## Start only remote agents with Docker Compose
	@echo "$(GREEN)🐳 Starting all remote agents...$(NC)"
	docker-compose up -d agent-template agent-assessment agent-branding agent-claims \
		agent-classification agent-deep-search agent-fraud agent-image-analysis \
		agent-image-generator agent-legal agent-servicenow agent-google-adk
	@echo "$(GREEN)✅ All agents started$(NC)"

docker-down: ## Stop and remove all Docker containers
	@echo "$(YELLOW)🛑 Stopping Docker services...$(NC)"
	docker-compose down
	@echo "$(GREEN)✅ All services stopped$(NC)"

docker-logs: ## Show Docker Compose logs (all services)
	@echo "$(GREEN)📋 Showing Docker Compose logs...$(NC)"
	docker-compose logs -f

docker-logs-backend: ## Show backend logs
	@docker-compose logs -f backend

docker-logs-frontend: ## Show frontend logs
	@docker-compose logs -f frontend

docker-logs-agents: ## Show all agent logs
	@docker-compose logs -f agent-template agent-assessment agent-branding agent-claims \
		agent-classification agent-deep-search agent-fraud agent-image-analysis \
		agent-image-generator agent-legal agent-servicenow agent-google-adk

docker-ps: ## Show running Docker containers
	@echo "$(GREEN)📊 Docker Container Status:$(NC)"
	@docker-compose ps

docker-restart: ## Restart all Docker services
	@echo "$(YELLOW)🔄 Restarting all services...$(NC)"
	docker-compose restart
	@echo "$(GREEN)✅ All services restarted$(NC)"

docker-clean: docker-down ## Stop containers and remove images
	@echo "$(YELLOW)🧹 Cleaning up Docker images...$(NC)"
	docker-compose down --rmi local --volumes --remove-orphans
	@echo "$(GREEN)✅ Docker cleanup complete$(NC)"

