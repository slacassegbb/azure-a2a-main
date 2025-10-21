# Docker Deployment Guide

This guide covers how to build and deploy the CitiChat frontend using Docker.

## Prerequisites

- Docker Engine 20.10+ 
- Docker Compose 2.0+
- Environment variables configured (see `.env` file)

## Quick Start

### Development Build

```bash
# Build and run with Docker Compose
docker-compose up --build

# Or run in detached mode
docker-compose up -d --build
```

### Production Build

```bash
# Build and run with production settings
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up --build
```

## Manual Docker Commands

### Build Image

```bash
# Basic build
docker build -t citichat-frontend .

# Build with environment variables
docker build \
  --build-arg NEXT_PUBLIC_A2A_API_URL="http://localhost:12000" \
  --build-arg NEXT_PUBLIC_WEBSOCKET_URL="ws://localhost:8080/events" \
  --build-arg NEXT_PUBLIC_DEV_MODE="false" \
  -t citichat-frontend .
```

### Run Container

```bash
# Basic run
docker run -p 3000:3000 citichat-frontend

# Run with environment variables
docker run -p 3000:3000 \
  -e NEXT_PUBLIC_A2A_API_URL="http://localhost:12000" \
  -e NEXT_PUBLIC_WEBSOCKET_URL="ws://localhost:8080/events" \
  citichat-frontend
```

## Environment Variables

The following environment variables can be set at build time and/or runtime:

### Required
- `NEXT_PUBLIC_A2A_API_URL` - A2A backend API URL

### Optional
- `NEXT_PUBLIC_WEBSOCKET_URL` - Override WebSocket relay endpoint (default: `ws://localhost:8080/events`)
- `NEXT_PUBLIC_DEV_MODE` - Development mode flag

## Health Check

The container includes a health check endpoint at `/api/health`:

```bash
# Check container health
curl http://localhost:3000/api/health
```

Response example:
```json
{
  "status": "healthy",
  "timestamp": "2025-07-21T16:30:00.000Z",
  "uptime": 125.234,
  "environment": "production",
  "version": "0.1.0",
  "websocket": {
    "url": "ws://localhost:8080/events",
    "usingDefaultUrl": true
  }
}
```

## Multi-Stage Build Optimization

The Dockerfile uses a multi-stage build for optimization:

1. **deps**: Installs dependencies
2. **builder**: Builds the application 
3. **runner**: Production runtime image

Benefits:
- Smaller production image size
- No development dependencies in production
- Optimized for Next.js standalone output

## Production Deployment

### Azure Container Instances

```bash
# Build for Azure Container Registry
docker build -t your-registry.azurecr.io/citichat-frontend:latest .

# Push to registry
docker push your-registry.azurecr.io/citichat-frontend:latest

# Deploy to ACI (example)
az container create \
  --resource-group your-rg \
  --name citichat-frontend \
  --image your-registry.azurecr.io/citichat-frontend:latest \
  --ports 3000 \
  --environment-variables \
    NEXT_PUBLIC_A2A_API_URL=https://your-backend.example.com \
    NEXT_PUBLIC_WEBSOCKET_URL=wss://your-backend.example.com/events
```

### Azure Container Apps

Use the production docker-compose configuration as a reference for Container Apps deployment.

## Troubleshooting

### Build Issues

1. **Node version**: Ensure using Node 20+ for Azure SDK compatibility
2. **Memory**: Increase Docker memory limit if build fails
3. **Dependencies**: Clear node_modules and rebuild if needed

### Runtime Issues

1. **WebSocket connection**: Verify the relay URL and ensure the backend WebSocket server is running
2. **Port conflicts**: Ensure port 3000 is available
3. **Health check**: Monitor `/api/health` endpoint

### Logs

```bash
# View container logs
docker-compose logs -f citichat-frontend

# View specific container logs
docker logs <container-id>
```

## Performance Tips

1. **Layer caching**: Dependencies are installed in separate layer for faster rebuilds
2. **Standalone output**: Next.js standalone mode reduces image size
3. **Multi-stage**: Only production files in final image
4. **Health checks**: Monitor application health automatically

## Security Considerations

1. **Non-root user**: Container runs as non-root user `nextjs`
2. **Secret management**: Use Azure Key Vault or container secrets for production
3. **Network isolation**: Use Docker networks for service communication
4. **Image scanning**: Scan images for vulnerabilities before deployment
