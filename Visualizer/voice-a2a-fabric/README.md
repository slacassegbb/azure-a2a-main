# A2A Agent Network Visualizer

Real-time visualization dashboard for the Azure A2A Multi-Agent System.

## 🚀 Quick Start

### Prerequisites
- Backend running on `http://localhost:12000`
- WebSocket server on `ws://localhost:8080/events`
- Root `.env` file configured (see below)

### Environment Configuration

**The Visualizer inherits environment variables from the root `azure-a2a-main/.env` file.**

Ensure the root `.env` contains:
```bash
NEXT_PUBLIC_A2A_API_URL=http://localhost:12000
NEXT_PUBLIC_WEBSOCKET_URL=ws://localhost:8080/events
NEXT_PUBLIC_DEBUG_LOGS=true
NEXT_PUBLIC_WEBSOCKET_MAX_INITIAL_ATTEMPTS=3
```

These match the main frontend configuration.

### Running the Visualizer

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

Open [http://localhost:3000](http://localhost:3000) with your browser to see the live agent network visualization.

## 📚 Documentation

- **[SETUP_GUIDE.md](./SETUP_GUIDE.md)** - Complete setup and integration guide
- **[INTEGRATION_SUMMARY.md](./INTEGRATION_SUMMARY.md)** - Quick reference for the WebSocket integration
- **[TESTING.md](./TESTING.md)** - Test suite and troubleshooting
- **[AGENTS.MD](./AGENTS.MD)** - Technical documentation and architecture

## ✨ Features

- Real-time agent network visualization with D3.js
- WebSocket integration with A2A backend
- Live agent registry sync
- Agent glow effects and thought bubbles
- Activity log and KPI dashboard
- Automatic reconnection with exponential backoff

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
