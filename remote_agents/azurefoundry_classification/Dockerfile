# Azure Foundry Classification Agent Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install UV package manager
RUN pip install --no-cache-dir uv

# Copy pyproject.toml and related files
COPY pyproject.toml ./
COPY uv.lock* ./

# Install dependencies using UV
RUN uv sync --frozen

# Copy agent code
COPY . .

# Expose port
EXPOSE 8001

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=100s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8001/health', timeout=5)" || exit 1

# Run the agent
CMD ["uv", "run", "."]
