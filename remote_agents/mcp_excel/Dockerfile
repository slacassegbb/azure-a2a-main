# Excel MCP Server - HTTP Mode
# Builds the Go binary from source (with file-creation fix) and wraps it
# with a Node.js HTTP server for Azure Container Apps.

# --- Stage 1: Build Go binary ---
FROM golang:1.24-bookworm AS go-builder

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download

COPY cmd/ cmd/
COPY internal/ internal/
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /excel-mcp-server ./cmd/excel-mcp-server

# --- Stage 2: Runtime ---
FROM node:20-slim

WORKDIR /app

# Copy the Go binary built from source
COPY --from=go-builder /excel-mcp-server /usr/local/bin/excel-mcp-server

# Copy the HTTP wrapper
COPY server.js .

# Environment variables
ENV PORT=8000
ENV EXCEL_MCP_PAGING_CELLS_LIMIT=4000

# Expose the port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD node -e "fetch('http://localhost:${PORT}/health').then(r => r.ok ? process.exit(0) : process.exit(1)).catch(() => process.exit(1))"

# Run the HTTP wrapper
CMD ["node", "server.js"]
