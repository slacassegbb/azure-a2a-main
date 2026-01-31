# Azure AI Foundry QuickBooks Online A2A Agent Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies and Azure CLI
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        apt-transport-https \
        lsb-release \
        gnupg \
    && curl -sL https://aka.ms/InstallAzureCLIDeb | bash \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
RUN pip install --no-cache-dir uv

# Copy pyproject.toml and lock file
COPY pyproject.toml uv.lock* ./

# Install dependencies using uv
RUN uv pip install --system -e .

# Copy agent code
COPY . .

# Default port for QuickBooks agent (override with -e A2A_PORT=XXXX)
ENV A2A_PORT=8020
ENV A2A_HOST=0.0.0.0

EXPOSE ${A2A_PORT}

# Run the agent
CMD ["sh", "-c", "uv run . --host ${A2A_HOST} --port ${A2A_PORT}"]

