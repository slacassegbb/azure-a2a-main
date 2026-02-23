FROM python:3.11-slim

# Install build dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project files
COPY . /app

# Install Python dependencies (uses pyproject.toml)
RUN pip install --no-cache-dir .

# Configure for streamable-http transport
ENV MCP_TRANSPORT=streamable-http
ENV PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:${PORT}/health || exit 1

CMD ["python", "-m", "word_document_server.main"]
