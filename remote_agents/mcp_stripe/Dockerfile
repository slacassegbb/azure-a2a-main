# Stripe MCP Server - HTTP Mode
# Wraps @stripe/mcp to work like QuickBooks MCP server
# Supports direct POST to /sse for Azure AI Foundry compatibility

FROM node:20-alpine

WORKDIR /app

# Install stripe mcp globally
RUN npm install -g @stripe/mcp

# Copy server script
COPY server.js .

# Environment variables (set at runtime)
ENV STRIPE_API_KEY=""
ENV PORT=8080

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:${PORT}/health || exit 1

# Start the server
CMD ["node", "server.js"]
