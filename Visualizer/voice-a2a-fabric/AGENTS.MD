# A2A Multiagent Network Visualization - Technical Documentation

## Overview

This application provides a real-time visualization dashboard for Agent-to-Agent (A2A) multiagent systems. It displays a network topology with a central host agent connected to multiple remote agents, tracks events and communications, and provides detailed insights into agent capabilities and activities.

---

## Current Implementation (Simulation Mode)

The application currently runs in **simulation mode** with hardcoded agent data and simulated events. This mode is useful for:
- Demonstrations and presentations
- UI/UX testing
- Understanding the visualization capabilities
- Prototyping agent behaviors

### Simulated Components:
1. **Static agent registry** - Agents are defined in the component state
2. **Random event generation** - Connection events fire on mount
3. **Manual simulation** - "Simulate Request" button triggers sequential processing
4. **Mock data** - Thought bubbles show pre-written agent outputs

---

## Architecture

### Component Structure

\`\`\`
AgentNetworkDashboard
├── Canvas Panel (Center) - D3.js visualization
│   ├── Host Agent Node (center)
│   ├── Remote Agent Nodes (circular layout)
│   ├── Human Operator Nodes (outer ring, connected to parent agents)
│   ├── Connection Lines (with gradient effects)
│   ├── Glow Effects (pulsing animations on events)
│   └── Thought Bubbles (floating output snippets)
│
├── Left Sidebar - Activity Log
│   └── Real-time event feed with timestamps
│
├── Right Sidebar - Agent Directory
│   └── Accordion with agent cards, descriptions, and skills
│
└── Bottom Panel - KPI Dashboard
    ├── Active Agents count
    ├── Events Processed count
    └── Avg Response Time
\`\`\`

### Agent Data Model

\`\`\`typescript
interface Agent {
  id: string;              // Unique identifier (e.g., "host-001", "remote-analytics")
  name: string;            // Display name (e.g., "Host Agent", "Analytics Agent")
  type: 'host' | 'remote' | 'human'; // Agent classification
  status: 'active' | 'idle' | 'processing'; // Current state
  description?: string;    // Agent purpose and capabilities description
  skills?: string[];       // Array of capabilities (e.g., ["NLP", "Data Processing"])
  color?: string;          // Hex color for visualization (assigned automatically)
  glowColor?: string;      // Glow effect color (assigned automatically)
  x?: number;              // Canvas X position (calculated automatically)
  y?: number;              // Canvas Y position (calculated automatically)
  glowing?: boolean;       // Active glow state
  glowIntensity?: number;  // Glow animation intensity (0-1)
  parentAgent?: string;    // For human operators - ID of connected agent
}
\`\`\`

### Event Data Model

\`\`\`typescript
interface AgentEvent {
  timestamp: Date;         // When the event occurred
  agentId: string;         // Which agent generated the event
  type: 'connection' | 'processing' | 'output' | 'error' | 'input_required';
  message: string;         // Human-readable event description
  output?: string;         // Agent output text (for thought bubbles)
}
\`\`\`

---

## Converting to Real Implementation

### 1. WebSocket Integration

Replace the simulation logic with a WebSocket client that connects to your A2A orchestration backend.

#### Required WebSocket Events (Inbound)

**Agent Registration**
\`\`\`json
{
  "event": "agent_connected",
  "data": {
    "id": "remote-analytics-001",
    "name": "Analytics Agent",
    "type": "remote",
    "description": "Processes data analytics and generates insights",
    "skills": ["Data Analysis", "Statistical Modeling", "Visualization"]
  }
}
\`\`\`

**Agent Disconnection**
\`\`\`json
{
  "event": "agent_disconnected",
  "data": {
    "id": "remote-analytics-001"
  }
}
\`\`\`

**Agent Status Update**
\`\`\`json
{
  "event": "agent_status",
  "data": {
    "id": "remote-analytics-001",
    "status": "processing" // or "idle", "active", "error"
  }
}
\`\`\`

**Agent Processing Event**
\`\`\`json
{
  "event": "agent_processing",
  "data": {
    "id": "remote-analytics-001",
    "message": "Processing request from host agent"
  }
}
\`\`\`

**Agent Output**
\`\`\`json
{
  "event": "agent_output",
  "data": {
    "id": "remote-analytics-001",
    "output": "Analyzed 15,000 records and identified 3 key patterns in customer behavior trends",
    "message": "Analysis complete"
  }
}
\`\`\`

**Human Input Required**
\`\`\`json
{
  "event": "input_required",
  "data": {
    "agentId": "remote-analytics-001",
    "operatorId": "human-operator-001",
    "operatorName": "Sarah Chen",
    "prompt": "Review analysis results for accuracy"
  }
}
\`\`\`

**Error Event**
\`\`\`json
{
  "event": "agent_error",
  "data": {
    "id": "remote-analytics-001",
    "message": "Failed to process request: timeout",
    "error": "Connection timeout after 30s"
  }
}
\`\`\`

#### WebSocket Client Implementation

\`\`\`typescript
// Add to component
const wsRef = useRef<WebSocket | null>(null);

useEffect(() => {
  // Connect to your A2A backend
  const ws = new WebSocket('wss://your-backend.com/agents');
  wsRef.current = ws;

  ws.onopen = () => {
    console.log('[v0] WebSocket connected');
  };

  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    handleWebSocketMessage(message);
  };

  ws.onerror = (error) => {
    console.error('[v0] WebSocket error:', error);
  };

  ws.onclose = () => {
    console.log('[v0] WebSocket disconnected');
    // Implement reconnection logic here
  };

  return () => {
    ws.close();
  };
}, []);

const handleWebSocketMessage = (message: any) => {
  switch (message.event) {
    case 'agent_connected':
      addAgent(message.data);
      break;
    case 'agent_disconnected':
      removeAgent(message.data.id);
      break;
    case 'agent_status':
      updateAgentStatus(message.data.id, message.data.status);
      break;
    case 'agent_processing':
      triggerGlow(message.data.id);
      addActivityLog(message.data);
      break;
    case 'agent_output':
      showThoughtBubble(message.data.id, message.data.output);
      addActivityLog(message.data);
      break;
    case 'input_required':
      addHumanOperator(message.data);
      break;
    case 'agent_error':
      handleAgentError(message.data);
      break;
  }
};
\`\`\`

### 2. Backend Requirements

Your A2A orchestration backend must provide:

#### Agent Registry API
\`\`\`
GET /api/agents
Response: Array of all currently connected agents
\`\`\`

#### WebSocket Server
- Maintains persistent connections with all agents
- Broadcasts agent connection/disconnection events
- Forwards agent events to visualization clients
- Handles authentication and authorization

#### Event Stream
- Real-time event broadcasting
- Event history/replay capability (optional)
- Event filtering by agent or type (optional)

### 3. Environment Configuration

The Visualizer inherits environment variables from the root `azure-a2a-main/.env` file.

Ensure the root `.env` contains:

\`\`\`bash
# WebSocket connection URL
NEXT_PUBLIC_WEBSOCKET_URL=ws://localhost:8080/events

# API base URL
NEXT_PUBLIC_A2A_API_URL=http://localhost:12000

# Debug logging
NEXT_PUBLIC_DEBUG_LOGS=true

# WebSocket retry settings
NEXT_PUBLIC_WEBSOCKET_MAX_INITIAL_ATTEMPTS=3
```

**Note:** No separate `.env.local` needed - configuration is shared with the main frontend.

### 4. Replace Simulation Code

#### Remove these sections:
1. **Hardcoded agents array** (lines with `initialAgents`)
2. **Connection simulation** (useEffect that adds connection events)
3. **`simulateRequest` function** (or convert to trigger backend request)
4. **Random event generation**

#### Add these functions:

\`\`\`typescript
// Add new agent from WebSocket
const addAgent = (agentData: any) => {
  const newAgent: Agent = {
    ...agentData,
    status: 'active',
    color: getUniqueColor(),
    glowColor: getUniqueColor(),
    glowing: false,
    glowIntensity: 0,
  };
  
  setAgents(prev => [...prev, newAgent]);
  addActivityLog({
    timestamp: new Date(),
    agentId: newAgent.id,
    type: 'connection',
    message: `${newAgent.name} connected to network`,
  });
};

// Remove disconnected agent
const removeAgent = (agentId: string) => {
  const agent = agents.find(a => a.id === agentId);
  if (agent) {
    addActivityLog({
      timestamp: new Date(),
      agentId,
      type: 'connection',
      message: `${agent.name} disconnected from network`,
    });
  }
  setAgents(prev => prev.filter(a => a.id !== agentId));
};

// Update agent status
const updateAgentStatus = (agentId: string, status: Agent['status']) => {
  setAgents(prev => prev.map(agent => 
    agent.id === agentId ? { ...agent, status } : agent
  ));
};

// Show thought bubble with agent output
const showThoughtBubble = (agentId: string, output: string) => {
  const agent = agents.find(a => a.id === agentId);
  if (!agent) return;

  // Take first 10 words
  const snippet = output.split(' ').slice(0, 10).join(' ') + '...';
  
  setThoughtBubbles(prev => [...prev, {
    id: Date.now(),
    agentId,
    text: snippet,
    x: agent.x || 0,
    y: agent.y || 0,
    opacity: 1,
    offset: 0,
  }]);
};

// Add human operator when input required
const addHumanOperator = (data: any) => {
  const humanAgent: Agent = {
    id: data.operatorId,
    name: data.operatorName,
    type: 'human',
    status: 'active',
    parentAgent: data.agentId,
    description: 'Human operator reviewing agent outputs',
    skills: ['Review', 'Decision Making'],
  };
  
  setAgents(prev => [...prev, humanAgent]);
  addActivityLog({
    timestamp: new Date(),
    agentId: data.agentId,
    type: 'input_required',
    message: `Human operator ${data.operatorName} requested for review`,
  });
};
\`\`\`

### 5. Agent Marketplace Integration

To make the Agent Catalog functional:

#### API Endpoints Needed:
\`\`\`
GET /api/marketplace/agents
Response: Array of available agents to connect

POST /api/agents/connect
Body: { agentId: string, config: object }
Response: Connection status and agent details
\`\`\`

#### Update `connectAgent` function:
\`\`\`typescript
const connectAgent = async (catalogAgent: any) => {
  try {
    const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/agents/connect`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${process.env.NEXT_PUBLIC_AUTH_TOKEN}`,
      },
      body: JSON.stringify({
        agentId: catalogAgent.id,
        config: {}, // Optional configuration
      }),
    });
    
    if (response.ok) {
      // Agent will appear via WebSocket 'agent_connected' event
      setShowCatalog(false);
    }
  } catch (error) {
    console.error('Failed to connect agent:', error);
  }
};
\`\`\`

---

## Testing Checklist

### Simulation Mode (Current)
- [x] Host agent renders in center
- [x] Remote agents render in circular layout
- [x] Human operator connects to agent with HITL skill
- [x] Glow effects trigger on simulation
- [x] Thought bubbles float up and fade
- [x] Activity log shows connection events
- [x] Agent accordion displays all agents
- [x] KPI cards update during simulation
- [x] Agent catalog modal opens and displays agents

### Real Implementation
- [ ] WebSocket connects to backend on mount
- [ ] New agents appear when connected
- [ ] Agents disappear when disconnected
- [ ] Glow effects trigger on agent events
- [ ] Thought bubbles show real agent outputs (first 10 words)
- [ ] Activity log shows all events with timestamps
- [ ] Agent status updates reflect real state
- [ ] Human operators appear on input_required events
- [ ] KPI metrics calculate from real data
- [ ] Agent catalog connects to marketplace API
- [ ] Error handling for disconnections and failures
- [ ] Reconnection logic for dropped WebSocket connections

---

## Performance Considerations

1. **Agent Limit**: The circular layout works best with 15-20 agents. Consider pagination or filtering for larger networks.

2. **Event Throttling**: If receiving high-frequency events, implement debouncing:
\`\`\`typescript
const throttledGlow = useCallback(
  debounce((agentId: string) => triggerGlow(agentId), 100),
  []
);
\`\`\`

3. **Canvas Rendering**: The animation loop runs at 60fps. For 50+ agents, consider reducing frame rate or using requestIdleCallback.

4. **Activity Log**: Limit log entries to last 100 events to prevent memory bloat:
\`\`\`typescript
setActivityLog(prev => [...prev.slice(-99), newEvent]);
\`\`\`

---

## Customization Options

### Visual Customization
- **Colors**: Modify `VIBRANT_COLORS` array for different color schemes
- **Layout**: Adjust `CIRCLE_RADIUS` to change agent spacing
- **Animations**: Modify `THOUGHT_BUBBLE_DURATION` and glow pulse speed
- **Icons**: Replace `renderHostIcon` and `renderRemoteIcon` functions

### Functional Customization
- **KPI Calculations**: Update formulas in bottom panel cards
- **Event Filtering**: Add filters to activity log
- **Agent Grouping**: Organize agents by capability or team
- **Custom Skills**: Add skill-specific icons or badges

---

## Support

For questions or issues:
1. Check WebSocket connection in browser DevTools
2. Verify event payload structure matches schemas above
3. Review console logs for [v0] debugging messages
4. Ensure backend is broadcasting events to all connected clients

---

**Version**: 1.0  
**Last Updated**: January 2025  
**Framework**: Next.js 16 + React 19 + D3.js
