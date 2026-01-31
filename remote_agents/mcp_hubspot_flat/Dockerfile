FROM node:20-alpine

WORKDIR /app

# Install supergateway globally
RUN npm install -g supergateway

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy source
COPY index.js ./

# Expose SSE port
EXPOSE 8000

# Run with supergateway to provide SSE endpoint
# PRIVATE_APP_ACCESS_TOKEN will be passed as env var
CMD ["supergateway", "--stdio", "node index.js", "--port", "8000"]
