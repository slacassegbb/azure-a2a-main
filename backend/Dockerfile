FROM python:3.12-slim-bookworm

WORKDIR /app

# Install system dependencies required by document processing utilities and Azure CLI
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        poppler-utils \
        libreoffice \
        curl \
        ca-certificates \
        apt-transport-https \
        lsb-release \
        gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -sLS https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg \
    && chmod go+r /etc/apt/keyrings/microsoft.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ bookworm main" > /etc/apt/sources.list.d/azure-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends azure-cli \
    && rm -rf /var/lib/apt/lists/*

# Create empty .env file (CI/CD uses Azure Container Apps env vars instead)
RUN touch .env

# Copy requirements file from backend directory
COPY backend/requirements.txt ./

# Install Python dependencies
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Copy backend source code
COPY backend/ ./

# Create necessary directories
RUN mkdir -p data uploads hosts voice_recordings

# Set environment variables
ENV PYTHONPATH=/app
ENV A2A_UI_HOST=0.0.0.0
ENV A2A_UI_PORT=12000

EXPOSE 12000

# Run the backend production server
CMD ["python", "backend_production.py"]
