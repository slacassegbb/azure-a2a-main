############################################################
# Makefile for art-voice-agent-accelerator
# Purpose: Manage code quality, environment, and app tasks
# Each target is documented for clarity and maintainability
############################################################

.PHONY: create_conda_env activate_conda_env remove_conda_env start_backend start_frontend start_tunnel

# Python interpreter to use
PYTHON_INTERPRETER = python
# Conda environment name (default: audioagent)
CONDA_ENV ?= a2a-environment
# Ensure current directory is in PYTHONPATH
export PYTHONPATH=$(PWD):$PYTHONPATH;
SCRIPTS_DIR = scripts/

create_conda_env:
	@echo "Creating conda environment"
	conda env create -f environment.yaml

activate_conda_env:
	@echo "Creating conda environment"
	conda activate $(CONDA_ENV)

remove_conda_env:
	@echo "Removing conda environment"
	conda env remove --name $(CONDA_ENV)

start_backend:
	$(PYTHON_INTERPRETER) $(SCRIPTS_DIR)/start_backend.py

start_frontend:
	bash $(SCRIPTS_DIR)/start_frontend.sh

start_tunnel:
	bash $(SCRIPTS_DIR)/start_devtunnel_host.sh