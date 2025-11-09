# A2A Agent Network Visualizer - Setup Guide

## Overview

The Visualizer is now fully integrated with the A2A backend using WebSocket for real-time agent network visualization.

## What's Been Integrated

### 1. WebSocket Infrastructure
- ✅ `lib/websocket-client.ts` - WebSocket client matching main frontend
- ✅ `lib/a2a-event-types.ts` - TypeScript types for A2A events
- ✅ `lib/debug.ts` - Debug utilities
- ✅ `contexts/event-hub-context.tsx` - Singleton WebSocket context
- ✅ `hooks/use-event-hub.ts` - React hook for WebSocket access

### 2. Dashboard Integration
- ✅ Real-time agent registry sync from backend
- ✅ Live event handling (task_updated, message, conversation_created)
- ✅ Send Request button sends real messages to backend
- ✅ Thought bubbles populated from agent responses
- ✅ Activity log shows real A2A events
- ✅ Connection status indicator
- ✅ Live KPIs (agent count, event count, response time)

### 3. Event Handlers Implemented

| Event | Description | Action |
|-------|-------------|--------|
| `agent_registry_sync` | Backend sends agent list | Populates remote agents in network |
| `task_updated` | Agent processing update | Triggers glow, thought bubble, activity log |
| `message` | Agent message/response | Shows in activity, triggers animations |
| `conversation_created` | New conversation | Sets conversation ID for requests |
| `event` | General system events | Logged for debugging |

## Quick Start

### 1. Install Dependencies

```bash
cd Visualizer/voice-a2a-fabric
npm install
```

### 2. Configuration

The Visualizer inherits environment variables from the root `.env` file (no separate `.env.local` needed).

Ensure `azure-a2a-main/.env` contains:

```env
NEXT_PUBLIC_A2A_API_URL=http://localhost:12000
NEXT_PUBLIC_WEBSOCKET_URL=ws://localhost:8080/events
NEXT_PUBLIC_DEBUG_LOGS=true
NEXT_PUBLIC_WEBSOCKET_MAX_INITIAL_ATTEMPTS=3
```

These match the main frontend configuration.

### 3. Start Backend

Ensure the A2A backend is running:

```bash
# From project root
cd backend
python backend_production.py
```

Backend should be running on:
- HTTP: `http://localhost:12000`
- WebSocket: `ws://localhost:8080/events`

### 4. Start Visualizer

```bash
cd Visualizer/voice-a2a-fabric
npm run dev
```

The Visualizer will start on `http://localhost:3000` (or next available port).

## How It Works

### Connection Flow

1. **App Starts**: `EventHubProvider` in `layout.tsx` initializes WebSocket client
2. **Connection**: WebSocket connects to `ws://localhost:8080/events`
3. **Registry Sync**: Backend sends `agent_registry_sync` with all registered agents
4. **Dashboard Updates**: Agents populate in the network visualization
5. **Status Indicator**: Green dot shows successful connection

### Request Flow

1. **User Action**: Click "Send Request" button
2. **Message Sent**: WebSocket sends message to backend via `sendMessage()`
3. **Backend Processing**: Host agent receives request and routes to remote agents
4. **Events Stream**: Backend sends `task_updated` and `message` events
5. **Visualization Updates**: 
   - Agents glow when processing
   - Thought bubbles show agent outputs
   - Activity log displays events
   - KPIs update in real-time

### Message Format

When you click "Send Request", the Visualizer sends:

```json
{
  "type": "message",
  "conversationId": "viz-1730918400000",
  "content": [
    {
      "type": "text",
      "content": "Analyze the current network performance..."
    }
  ],
  "role": "user",
  "timestamp": "2025-11-07T12:00:00.000Z"
}
```

Backend responds with:
- `conversation_created` - New conversation initiated
- `task_updated` - Agent processing updates
- `message` - Agent responses and outputs

## Features

### Visual Elements

- **Host Agent (center)**: Indigo square, central orchestrator
- **Remote Agents (circle)**: Colored hexagons from registry
- **Connection Lines**: Gradient lines showing communication paths
- **Glow Effects**: Pulsing glow when agent is processing
- **Thought Bubbles**: Float up showing agent outputs

### UI Components

- **Top Left**: Title, subtitle, connection status (green/red dot)
- **Top Right**: Send Request button (disabled when disconnected)
- **Left Sidebar**: Activity log with real-time events
- **Right Sidebar**: Agent directory with expandable cards
- **Bottom Panel**: KPIs - Active Agents, Events Processed, Avg Response Time

### Connection Status

| Indicator | Meaning | Action |
|-----------|---------|--------|
| 🟢 Green | Connected to backend | Can send requests |
| 🔴 Red | Disconnected | Check backend is running |

## Testing the Integration

### Test 1: Connection

1. Start Visualizer: `npm run dev`
2. Check connection status indicator (should be green)
3. Open browser console (F12)
4. Look for: `[EventHubProvider] Successfully connected to WebSocket server`

### Test 2: Agent Registry

1. Ensure backend has registered agents
2. Visualizer should automatically populate agents
3. Check right sidebar - should show all registered agents
4. Check activity log - should show "Agent connected to network" messages

### Test 3: Send Request

1. Click "Send Request" button
2. Observe:
   - Host Agent glows immediately
   - Activity log shows "Processing request..."
   - Remote agents glow as they process
   - Thought bubbles appear with agent outputs
   - KPIs update (events count increases)

### Test 4: Debug Mode

1. Enable debug logging in root `.env` (set `NEXT_PUBLIC_DEBUG_LOGS=true`)
2. Open browser console
3. Send a request
4. Check console for detailed logs:
   - `[WebSocket] Message sent`
   - `[AgentDashboard] Task updated`
   - `[AgentDashboard] Message received`

## Troubleshooting

### Issue: Red Connection Indicator

**Cause**: Cannot connect to backend WebSocket

**Solutions**:
1. Check backend is running: `http://localhost:12000/health`
2. Check WebSocket server is running on port 8080
3. Verify root `.env` has `NEXT_PUBLIC_WEBSOCKET_URL=ws://localhost:8080/events`
4. Check browser console for WebSocket errors
5. Try restarting both backend and Visualizer

### Issue: No Agents Showing

**Cause**: Agent registry not syncing

**Solutions**:
1. Check backend has registered agents: `GET http://localhost:12000/agents`
2. Look for `agent_registry_sync` event in console
3. Verify backend is sending agent data in correct format
4. Restart Visualizer to retry connection

### Issue: Send Request Button Disabled

**Cause**: Not connected to backend

**Solutions**:
1. Check connection status indicator (must be green)
2. Ensure WebSocket connection is established
3. See "Red Connection Indicator" solutions above

### Issue: Events Not Showing

**Cause**: Event handlers not working

**Solutions**:
1. Enable debug mode: `NEXT_PUBLIC_DEBUG_LOGS=true`
2. Check console for event subscriptions
3. Verify backend is sending events in A2A format
4. Check for JavaScript errors in console

## Architecture Details

### Event Subscription

The dashboard subscribes to these events in `useEffect`:

```typescript
subscribe('agent_registry_sync', handleAgentRegistrySync)
subscribe('task_updated', handleTaskUpdated)
subscribe('message', handleMessage)
subscribe('conversation_created', handleConversationCreated)
subscribe('event', handleEvent)
```

### State Management

- **agents**: Array of Agent objects (host + remotes from registry)
- **messages**: Activity log entries
- **thoughtBubbles**: Floating text bubbles on agents
- **kpis**: Live metrics (active agents, events, response time)
- **currentConversationId**: Active conversation for requests
- **isConnected**: WebSocket connection status

### WebSocket Client

- **Connection**: Auto-connects on app start
- **Reconnection**: Auto-reconnects with exponential backoff
- **Event Parsing**: Parses A2A event envelope format
- **Type Safety**: Full TypeScript types for all events

## Comparison with Main Frontend

Both applications use the same WebSocket integration:

| Component | Main Frontend | Visualizer |
|-----------|---------------|------------|
| WebSocket Client | ✅ Same | ✅ Same |
| Event Hub Context | ✅ Same | ✅ Same |
| A2A Event Types | ✅ Same | ✅ Same |
| Backend URL | `ws://localhost:8080/events` | `ws://localhost:8080/events` |
| Agent Registry Sync | ✅ Yes | ✅ Yes |
| Send Messages | ✅ Chat input | ✅ Send Request button |
| Display | Chat UI | Network graph |

## Next Steps

### Enhancements You Can Make

1. **More Event Types**: Add handlers for file uploads, form submissions
2. **Agent Details**: Click agent to show detailed info panel
3. **Performance Metrics**: Track response times per agent
4. **Error Handling**: Show error states when agents fail
5. **Agent Status Colors**: Different colors for online/offline/error states
6. **Historical Data**: Store and replay past events
7. **Export**: Export network state or event logs

### Customization

You can customize the visualization by editing:

- `AGENT_COLORS` array - Change agent colors
- `addThoughtBubble()` - Modify thought bubble behavior
- `drawBotIcon()` / `drawHostIcon()` - Change agent icons
- KPI calculations - Add new metrics

## Support

If you encounter issues:

1. Check browser console for errors (F12)
2. Enable debug mode: `NEXT_PUBLIC_DEBUG_LOGS=true`
3. Verify backend is running and accessible
4. Check WebSocket connection in Network tab (F12)
5. Review this guide for troubleshooting steps

The Visualizer is now fully integrated and production-ready! 🎉
