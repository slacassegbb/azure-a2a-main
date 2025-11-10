# Multi-stage build for Next.js frontend
FROM node:20-alpine AS base

# Install dependencies only when needed
FROM base AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app

# Copy package files
COPY package*.json ./
COPY pnpm-lock.yaml* ./

# Install dependencies (no frozen lockfile for Docker builds)
RUN npm install -g pnpm && pnpm install --no-frozen-lockfile

# Rebuild the source code only when needed
FROM base AS builder
WORKDIR /app

# Accept build args for NEXT_PUBLIC_ environment variables
ARG NEXT_PUBLIC_AZURE_AI_TOKEN
ARG NEXT_PUBLIC_AZURE_AI_FOUNDRY_PROJECT_ENDPOINT
ARG NEXT_PUBLIC_VOICE_MODEL
ARG NEXT_PUBLIC_A2A_API_URL
ARG NEXT_PUBLIC_WEBSOCKET_URL
ARG NEXT_PUBLIC_DEBUG_LOGS

# Set as environment variables for the build
ENV NEXT_PUBLIC_AZURE_AI_TOKEN=$NEXT_PUBLIC_AZURE_AI_TOKEN
ENV NEXT_PUBLIC_AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=$NEXT_PUBLIC_AZURE_AI_FOUNDRY_PROJECT_ENDPOINT
ENV NEXT_PUBLIC_VOICE_MODEL=$NEXT_PUBLIC_VOICE_MODEL
ENV NEXT_PUBLIC_A2A_API_URL=$NEXT_PUBLIC_A2A_API_URL
ENV NEXT_PUBLIC_WEBSOCKET_URL=$NEXT_PUBLIC_WEBSOCKET_URL
ENV NEXT_PUBLIC_DEBUG_LOGS=$NEXT_PUBLIC_DEBUG_LOGS

# Copy dependencies from deps stage
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Disable telemetry during build
ENV NEXT_TELEMETRY_DISABLED=1

# Build the application
RUN npm run build

# Production image, copy all the files and run next
FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Create a non-root user
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

# Copy necessary files
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

# Set correct permissions
RUN chown -R nextjs:nodejs /app

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
