# Use official Python image
FROM python:3.11-slim

# Set work directory
WORKDIR /app

# Install pip, uv, and build tools
RUN pip install --upgrade pip uv build

# Copy project files
COPY . .

# Install dependencies (pyproject.toml and requirements.txt)
RUN uv pip install --system . && \
    if [ -f requirements.txt ]; then uv pip install --system -r requirements.txt; fi

# Expose default port
EXPOSE 80

# Run the CLI with hardcoded credentials and server options
ENTRYPOINT ["python", "-m", "mcp_server_servicenow.cli"]
CMD ["--url", "https://dev222136.service-now.com/", "--username", "admin", "--password", "^JqW,bS,L:lLvQ0{NE$#Iw{y4)XN:ycVP)MwBls0xz+.gN3jId?jicM_Jk?tWw0!$", "--transport", "sse", "--host", "0.0.0.0", "--port", "80"] 