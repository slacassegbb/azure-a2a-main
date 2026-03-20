# Build stage
FROM node:20-alpine AS builder
WORKDIR /app

# Install dependencies
COPY package.json ./
RUN npm install

# Copy source and build
COPY . .

# Build-time env vars (must be passed as --build-arg)
ARG NEXT_PUBLIC_A2A_API_URL
ARG NEXT_PUBLIC_WEBSOCKET_URL
ARG NEXT_PUBLIC_VOICE_HOST
ARG NEXT_PUBLIC_VOICE_DEPLOYMENT=gpt-realtime
ARG NEXT_PUBLIC_DEV_MODE=false

ENV NEXT_PUBLIC_A2A_API_URL=$NEXT_PUBLIC_A2A_API_URL
ENV NEXT_PUBLIC_WEBSOCKET_URL=$NEXT_PUBLIC_WEBSOCKET_URL
ENV NEXT_PUBLIC_VOICE_HOST=$NEXT_PUBLIC_VOICE_HOST
ENV NEXT_PUBLIC_VOICE_DEPLOYMENT=$NEXT_PUBLIC_VOICE_DEPLOYMENT
ENV NEXT_PUBLIC_DEV_MODE=$NEXT_PUBLIC_DEV_MODE

RUN npm run build

# Production stage
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3001

# Copy standalone build
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3001

CMD ["node", "server.js"]
