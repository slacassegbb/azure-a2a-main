## A2A Frontend (Next.js)

A modern Next.js app that provides the UI for the A2A platform. It connects to the backend Host Agent to:
- Browse and manage the agent registry
- Start and follow conversations and tasks
- Authenticate users and show connected/active users
- Stream real‑time events over WebSocket (status, messages, registry updates)

### Tech
- Next.js App Router, TypeScript, Tailwind
- WebSocket client for real‑time updates
- REST calls to the backend API for data and actions

---

## Quick start (local)
```bash
cd frontend
npm install

# Configure environment
cp .env.local .env.local.backup 2>/dev/null || true
echo "# see README for all options" > .env.local
echo "NEXT_PUBLIC_A2A_API_URL=http://localhost:12000" >> .env.local
echo "NEXT_PUBLIC_WEBSOCKET_URL=ws://localhost:8080/events" >> .env.local

# Run the dev server
npm run dev
# Open http://localhost:3000
```

Make sure the backend is running at `http://localhost:12000` and its WebSocket server at `ws://localhost:8080/events` (default from the backend).

---

## Environment variables (.env.local)
The app reads public variables at build/runtime:

```bash
# Backend API base URL (FastAPI Host Agent)
NEXT_PUBLIC_A2A_API_URL=http://localhost:12000

# WebSocket endpoint for real‑time events
NEXT_PUBLIC_WEBSOCKET_URL=ws://localhost:8080/events

# Optional flags
NEXT_PUBLIC_DEV_MODE=false                 # feature flags / UI hints
NEXT_PUBLIC_DEBUG_LOGS=false               # verbose console logs
NEXT_PUBLIC_WEBSOCKET_MAX_INITIAL_ATTEMPTS=10  # reconnect attempts
```

Tips:
- Use `wss://...` for `NEXT_PUBLIC_WEBSOCKET_URL` when the site is served over HTTPS.
- These vars may also be provided via Docker build/run args (see `DOCKER.md`).

---

## Scripts
```bash
npm run dev       # start dev server (http://localhost:3000)
npm run build     # production build
npm run start     # start production server (PORT=3000 by default)
```

Docker and Compose usage are covered in `DOCKER.md` and the `docker-compose*.yml` files.

---

## Notable features & routes
- UI components: `components/*` (chat panel, agent catalog, agent network graph, connected users, etc.)
- Client libs: `lib/conversation-api.ts`, `lib/websocket-client.ts`, `lib/a2a-event-types.ts`
- Server routes (API proxies/utilities):
  - `app/api/health/route.ts` – exposes runtime/frontend health (uses env)
  - `app/api/upload-voice/route.ts` – proxies voice uploads to backend
  - `app/api/register-agent/route.ts` – proxies agent registration to backend

---

## Troubleshooting
- WebSocket not connecting: confirm `NEXT_PUBLIC_WEBSOCKET_URL` matches the backend (`ws://localhost:8080/events` locally) and switch to `wss://` under HTTPS.
- 401/403 on actions: login via the UI; ensure the backend `SECRET_KEY` is set and reachable.
- Backend not found: verify `NEXT_PUBLIC_A2A_API_URL` and that the backend is listening on the expected host/port.
- CORS: the backend is permissive by default; if tightened, allow the frontend origin.

---

## Project layout
- `app/` – Next.js App Router pages and API routes
- `components/` – UI components
- `hooks/` – React hooks (event hub, media, websocket)
- `lib/` – API client, event types, utilities
- `public/` – static assets

This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
