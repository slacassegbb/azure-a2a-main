# QuickBooks MCP Server - Docker Image
# Runs the MCP server in HTTP mode for Azure Container Apps

FROM node:20-slim

# Set working directory
WORKDIR /app

# Copy package files first for better caching
COPY package*.json ./

# Install production dependencies only (skip prepare script since we copy pre-built dist)
RUN npm ci --omit=dev --ignore-scripts

# Copy built TypeScript output
COPY dist/ ./dist/

# Set environment variables
ENV NODE_ENV=production
ENV TRANSPORT_MODE=http
ENV PORT=3001

# Expose the port
EXPOSE 3001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD node -e "fetch('http://localhost:3001/health').then(r => r.ok ? process.exit(0) : process.exit(1)).catch(() => process.exit(1))"

# Run the server
CMD ["node", "dist/index.js"]
