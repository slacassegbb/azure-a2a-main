# AI Foundry A2A Demo

A demonstration project showcasing the integration of Azure AI Foundry with the Agent-to-Agent (A2A) framework. This project implements an intelligent calendar management agent with the following capabilities:

## Features

- 🤖 **AI Foundry Integration**: Build intelligent agents using Azure AI Foundry
- 📅 **Calendar Management**: Check schedule availability, get upcoming events
- 🔄 **A2A Framework**: Support agent-to-agent communication and collaboration
- 💬 **Conversation Capabilities**: Natural language processing and multi-turn conversations
- 🛠️ **Tool Integration**: Simulated calendar API tool integration
- 🎨 **Gradio Web UI**: Beautiful web interface for direct agent interaction
- 🌐 **Dual Mode Operation**: Run as A2A server or with web UI
- 🤝 **Self-Registration**: Automatically registers with host agent on startup

## Project Structure

```
├── foundry_agent.py           # AI Foundry calendar agent 
├── foundry_agent_executor.py  # A2A framework executor
├── __main__.py                # Main application
├── pyproject.toml             # Project dependencies 
├── test_client.toml           # Test 
└── .env.template              # Environment variables template
```

## Quick Start

### 1. Environment Setup

```bash

# Copy environment variables template
cp .env.template .env

# Edit the .env file and fill in your Azure configuration
```

### 2. Install Dependencies

```bash
# Using uv (recommended)
uv sync
```

### 3. Configure Azure AI Foundry

Set the following required environment variables in the `.env` file:

```env
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=Your Azure AI Foundry Project Endpoint
AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=Your Azure AI Foundry Deployment Model Name
```

### 3a. Configure A2A Server

```env
# Hostname or base domain the agent binds to (defaults to localhost)
A2A_ENDPOINT=localhost

# Port for the agent's A2A API
A2A_PORT=8002

# Host agent URL for self-registration (empty string disables)
A2A_HOST=http://localhost:12000
```

### 4. Run the Demo

#### Option A: A2A Server Mode (Default)

```bash
# Start Your Azure AI Foundry Agent A2A server
uv run .

# The server will be available at: http://$A2A_ENDPOINT:$A2A_PORT
# Health check at: http://$A2A_ENDPOINT:$A2A_PORT/health
```

#### Option B: Web UI Mode (Gradio Interface)

```bash
# Start with Gradio Web UI + A2A server
uv run . --ui

# Web UI will be available at: http://localhost:8087
# A2A server will be available at: http://$A2A_ENDPOINT:$A2A_PORT
```

#### Option C: Custom Ports

```bash
# Customize ports
uv run . --ui --ui-port 8089 --port 8010

# Or just A2A server on custom port
uv run . --port 8010
```

#### Testing the A2A Server

Open another terminal tab:

```bash
# Test the A2A server
uv run test_client.py
```

## 🤝 Self-Registration

This agent supports **automatic self-registration** with a host agent, eliminating the need for manual agent setup in multi-agent environments.

### How Self-Registration Works

When the agent starts, it automatically:
1. Waits 2 seconds for the server to fully initialize
2. Attempts to register with the host agent using the A2A protocol
3. Sends its agent card (capabilities, skills, URL) to the host agent
4. Logs the registration status

### Configuration

Self-registration is controlled by the `A2A_HOST` environment variable (falls back to `A2A_HOST_AGENT_URL` for legacy setups):

```bash
# Default (tries to register with host agent on localhost:12000)
uv run .

# Custom host agent URL
A2A_HOST=http://your-host-agent:8080 uv run .

# Disable self-registration (empty URL)
A2A_HOST="" uv run .
```

### Environment Variables

```env
# Host agent URL for self-registration (optional)
A2A_HOST=http://localhost:12000  # Default
# Legacy fallback (still supported)
A2A_HOST_AGENT_URL=http://localhost:12000

# A2A binding configuration
A2A_ENDPOINT=localhost
A2A_PORT=8002
```

### Complete Multi-Agent Setup

1. **Start the Host Agent** (in terminal 1):
   ```bash
   cd demo/ui
   uv run main.py
   ```

2. **Start this Azure Foundry Agent** (in terminal 2):
   ```bash
   cd samples/python/agents/azureaifoundry_sdk/azurefoundryagent
   uv run .
   ```

3. **Verify Registration**:
   - Open the host agent UI: value of `A2A_HOST` (default http://localhost:12000)
   - Go to "Remote Agents" tab
   - Look for "AI Foundry Expert Agent" in the list

### Testing Self-Registration

Test the self-registration functionality independently:

```bash
# Test registration without starting the full agent
python test_self_registration.py
```

This will:
- Create a test agent card
- Attempt registration with the host agent
- Report success/failure with detailed diagnostics
- Provide troubleshooting guidance

### Registration Status Logs

When starting the agent, look for these log messages:

```
✅ Self-registration utility loaded
🚀 'AI Foundry Expert Agent' starting with background registration enabled
🤝 Attempting to register 'AI Foundry Expert Agent' with host agent...
```

**Successful registration:**
```
🎉 'AI Foundry Expert Agent' successfully registered with host agent!
```

**Failed registration (expected if host agent not running):**
```
📡 'AI Foundry Expert Agent' registration failed - host agent may be unavailable
```

### Benefits of Self-Registration

- ✅ **Zero Configuration**: No manual agent setup required
- ✅ **Dynamic Discovery**: Agents appear automatically in host agent UI
- ✅ **Fault Tolerant**: Graceful handling when host agent is unavailable
- ✅ **Development Friendly**: Easy testing and iteration
- ✅ **Production Ready**: Reliable registration with retry logic


## Agent Capabilities

### Calendar Management Skills

1. **Check Availability** (`check_availability`)
   - Check schedule arrangements for specific time periods
   - Example: "Am I free tomorrow from 2 PM to 3 PM?"

2. **Get Upcoming Events** (`get_upcoming_events`)
   - Get future calendar events
   - Example: "What meetings do I have today?"

3. **Calendar Management** (`calendar_management`)
   - General calendar management and scheduling assistant
   - Example: "Help me optimize tomorrow's schedule"

### Conversation Examples

```
User: Hello, can you help me manage my calendar?
Agent: Of course! I'm the AI Foundry calendar agent, and I can help you check schedule availability, view upcoming events, and optimize your schedule. What do you need help with?

User: Am I free tomorrow from 2 PM to 3 PM?
Agent: Let me check your availability for tomorrow from 2 PM to 3 PM...
```

## Gradio Web UI

The project includes a beautiful Gradio web interface that provides:

### Features
- 🎨 **Modern UI**: Ocean-themed interface with A2A branding
- 💬 **Chat Interface**: Interactive chat with the calendar agent
- 📝 **Example Prompts**: Pre-built examples to get started quickly
- 🔄 **Real-time Processing**: Live responses with status updates
- 🚀 **Dual Operation**: Runs both web UI and A2A server simultaneously

### Example Prompts Available in UI
- "Am I free from 10am to 11am tomorrow?"
- "What meetings do I have today?"
- "Check my availability for next Tuesday afternoon"
- "Show me my schedule for this week"
- "Do I have any conflicts on Friday morning?"
- "When is the best time for a meeting this week?"
- "What's coming up in the next few hours?"
- "Help me optimize my schedule for tomorrow"

### Access Points
- **Web UI**: http://localhost:8087 (default)
- **A2A API**: http://$A2A_ENDPOINT:$A2A_PORT (default http://localhost:8002)
- **Health Check**: http://$A2A_ENDPOINT:$A2A_PORT/health

## Technical Architecture

### Core Components

1. **FoundryCalendarAgent**: 
   - Core implementation of Azure AI Foundry agent
   - Handles conversation logic and tool calls

2. **FoundryAgentExecutor**:
   - A2A framework executor
   - Handles request routing and state management

3. **A2A Integration**:
   - Agent card definitions
   - Skills and capabilities declarations
   - Message transformation and processing

### Key Features

- **Asynchronous Processing**: Full support for Python asynchronous programming
- **Error Handling**: Complete exception handling and logging
- **State Management**: Session and thread state management
- **Extensibility**: Easy to add new tools and skills
