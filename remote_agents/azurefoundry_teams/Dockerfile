# A2A Teams Agent Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
RUN pip install --no-cache-dir uv

# Copy pyproject.toml
COPY pyproject.toml ./

# Install dependencies using uv
RUN uv pip install --system -e .

# Copy agent code
COPY . .

# Default port for Teams agent
ENV A2A_PORT=8021
ENV A2A_HOST=0.0.0.0

EXPOSE ${A2A_PORT}

# Run the agent
CMD ["sh", "-c", "uv run . --host ${A2A_HOST} --port ${A2A_PORT}"]

