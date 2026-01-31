# Stripe MCP Server via Supergateway
# Exposes Stripe MCP (stdio) as HTTP/SSE for Azure AI Foundry

FROM node:20-alpine

WORKDIR /app

# Install supergateway and stripe mcp globally
RUN npm install -g supergateway @stripe/mcp

# Environment variables (set at runtime)
ENV STRIPE_API_KEY=""
ENV PORT=8080

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:${PORT}/sse || exit 1

# Start supergateway proxying Stripe MCP
CMD supergateway \
    --stdio "npx @stripe/mcp --tools=all --api-key=${STRIPE_API_KEY}" \
    --port ${PORT} \
    --cors \
    --healthEndpoint /health
