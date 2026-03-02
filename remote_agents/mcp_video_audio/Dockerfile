# Video & Audio MCP Server - Docker Image
# Runs the MCP server in HTTP mode for Azure Container Apps

FROM python:3.11-slim

# Install system dependencies (FFmpeg for video/audio processing)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg wget && \
    rm -rf /var/lib/apt/lists/*

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

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:${PORT}/health || exit 1

# Run the server in HTTP mode
CMD ["python", "video_audio_server.py", "--transport", "http", "--port", "8000"]
