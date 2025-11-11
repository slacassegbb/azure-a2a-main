# Network Performance Agent Dockerfile
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

# Install dependencies
RUN uv pip install --system -r pyproject.toml

# Copy agent code
COPY . .

# Expose port (network performance agent port)
EXPOSE 8105

# Run the agent using uv
CMD ["uv", "run", ".", "--host", "0.0.0.0", "--port", "8105"]
