# PowerPoint MCP Server - Docker Image
# Runs the MCP server in HTTP mode for Azure Container Apps

FROM python:3.10-alpine

# Install system dependencies (required for Pillow, lxml, fonttools)
RUN apk add --no-cache gcc musl-dev libffi-dev jpeg-dev zlib-dev

# Set work directory
WORKDIR /app

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV PORT=8000

# Expose the port
EXPOSE 8000

# Health check - use wget since curl isn't on alpine by default
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:${PORT}/mcp || exit 1

# Run the server in HTTP mode
CMD ["python", "ppt_mcp_server.py", "--transport", "http", "--port", "8000"]
