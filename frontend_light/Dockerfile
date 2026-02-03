FROM node:20-alpine AS base

# Install dependencies only when needed
FROM base AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app

# Install dependencies
COPY package.json package-lock.json* ./
RUN npm ci

# Rebuild the source code only when needed
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Build arguments for Next.js public env vars (baked into the build)
ARG NEXT_PUBLIC_A2A_API_URL
ARG NEXT_PUBLIC_WEBSOCKET_URL
ARG NEXT_PUBLIC_AZURE_AI_FOUNDRY_PROJECT_ENDPOINT
ARG NEXT_PUBLIC_VOICE_MODEL=gpt-realtime
ARG AZURE_OPENAI_GPT_API_KEY

ENV NEXT_PUBLIC_A2A_API_URL=$NEXT_PUBLIC_A2A_API_URL
ENV NEXT_PUBLIC_WEBSOCKET_URL=$NEXT_PUBLIC_WEBSOCKET_URL
ENV NEXT_PUBLIC_AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=$NEXT_PUBLIC_AZURE_AI_FOUNDRY_PROJECT_ENDPOINT
ENV NEXT_PUBLIC_VOICE_MODEL=$NEXT_PUBLIC_VOICE_MODEL
ENV AZURE_OPENAI_GPT_API_KEY=$AZURE_OPENAI_GPT_API_KEY

# Build the application
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# Production image, copy all the files and run next
FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Runtime env vars (can be overridden at container runtime)
ARG AZURE_OPENAI_GPT_API_KEY
ENV AZURE_OPENAI_GPT_API_KEY=$AZURE_OPENAI_GPT_API_KEY

RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public

# Set the correct permission for prerender cache
RUN mkdir .next
RUN chown nextjs:nodejs .next

# Automatically leverage output traces to reduce image size
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3001

ENV PORT=3001
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
