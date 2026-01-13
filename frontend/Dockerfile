# Use Node.js 20 LTS Debian slim for Azure SDK compatibility
FROM node:20-bookworm-slim AS base
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies only when needed
FROM base AS deps
WORKDIR /app

# Copy package files
COPY package.json package-lock.json ./
RUN npm ci --only=production

# Build stage
FROM base AS builder
WORKDIR /app

# Copy package files and install all dependencies (including dev)
COPY package.json package-lock.json ./
RUN npm ci

# Copy source code
COPY . .

# Build-time environment variables (can be overridden with --build-arg)
ARG NEXT_PUBLIC_A2A_API_URL="http://localhost:12000"
ARG NEXT_PUBLIC_WEBSOCKET_URL="ws://localhost:8080/events"
ARG NEXT_PUBLIC_DEV_MODE="false"
ENV NEXT_PUBLIC_A2A_API_URL=$NEXT_PUBLIC_A2A_API_URL
ENV NEXT_PUBLIC_WEBSOCKET_URL=$NEXT_PUBLIC_WEBSOCKET_URL
ENV NEXT_PUBLIC_DEV_MODE=$NEXT_PUBLIC_DEV_MODE
ENV NEXT_TELEMETRY_DISABLED=1

# Build the application
RUN npm run build

# Production runtime
FROM base AS runner
WORKDIR /app

# Create nextjs user
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Set runtime environment variables
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Hardcoded runtime environment variables
ENV NEXT_PUBLIC_A2A_API_URL="http://localhost:12000"
ENV NEXT_PUBLIC_WEBSOCKET_URL="ws://localhost:8080/events"
ENV NEXT_PUBLIC_DEV_MODE="false"

# Copy production dependencies
COPY --from=deps --chown=nextjs:nodejs /app/node_modules ./node_modules

# Copy built application
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./ 
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
