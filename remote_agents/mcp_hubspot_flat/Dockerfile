FROM node:20-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy source files
COPY index.js ./
COPY server.js ./

# Environment variables (set at runtime)
ENV PRIVATE_APP_ACCESS_TOKEN=""
ENV PORT=8000

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:${PORT}/health || exit 1

# Run the HTTP wrapper server (not supergateway)
CMD ["node", "server.js"]
