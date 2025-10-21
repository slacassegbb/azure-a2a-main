# ADK Sentiment Analysis Agent

This sample uses the Agent Development Kit (ADK) to create a simple **Sentiment Analysis Agent** that is hosted as an A2A server.

✨ **Now with automatic self-registration!** This agent automatically registers itself with the host agent on startup.

This agent takes text requests from the client, analyzes the sentiment (positive, negative, or neutral), and personalizes the experience for the customer based on sentiment and context.

## Prerequisites

- Python 3.9 or higher
- [UV](https://docs.astral.sh/uv/)
- Access to an LLM and API Key

## Self-Registration Feature

This agent automatically registers itself with the host agent on startup:

🎯 **Zero Configuration**: Just start the agent and it appears in the host agent's registry  
🔄 **Resilient**: Handles host agent unavailability gracefully  
📡 **Background**: Registration happens without blocking agent startup  
⚙️ **Configurable**: Set `A2A_HOST` (or legacy `A2A_HOST_AGENT_URL`) to point to your host agent  

### Startup Flow
```
1. 🚀 Agent starts up
2. 🤝 Attempts registration with host agent (background)
3. ✅ Appears automatically in host agent UI
4. 📡 Ready to receive tasks from host agent
```

## Running the Sample

1. Navigate to the samples directory:
    ```bash
    cd samples/python/agents/google_adk
    ```

2. Create an environment file with your configuration:
   ```bash
   cat <<'EOF' > .env
   GOOGLE_API_KEY=your_api_key_here
   A2A_ENDPOINT=localhost
   A2A_PORT=8003
   A2A_HOST=http://localhost:12000
   EOF
   ```

4. Run the agent:
    ```bash
    uv run .
    ```
    
    The agent will:
    - Start on `http://localhost:8003` 
    - Automatically attempt registration with host agent
    - Show registration status in logs

## Testing Self-Registration

### With Host Agent (Recommended)

1. **Start the host agent** (demo UI):
   ```bash
   cd ../../demo/ui
   uv run main.py  # Runs on localhost:12000
   ```

2. **Start this agent**:
   ```bash
   uv run .  # Should auto-register with host agent
   ```

3. **Check the UI**: Go to http://localhost:12000 and check "Remote Agents" tab - the agent should appear automatically!

4. **Test interaction**: Ask the host agent "How does the customer feel about our service?" or "Analyze the sentiment of this feedback: 'I love the new features!'" and it should delegate to this agent.

### Standalone Testing (Manual)

If you want to test without the host agent:

```bash
# Connect to the agent directly (specify the agent URL with correct port)
cd samples/python/hosts/cli
uv run . --agent http://localhost:8003

# If you changed the port when starting the agent, use that port instead
# uv run . --agent http://localhost:YOUR_PORT
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_API_KEY` | *Required* | Your Google AI API key |
| `A2A_ENDPOINT` | `localhost` | Hostname/interface to bind the agent server |
| `A2A_PORT` | `8003` | Port for the agent's A2A API |
| `A2A_HOST` | `http://localhost:12000` | Host agent URL (empty string disables registration) |
| `A2A_HOST_AGENT_URL` | `http://localhost:12000` | Legacy fallback for host agent URL |

## Features

- 🧠 Analyzes sentiment (positive, negative, neutral) from customer messages
- 🤗 Personalizes the experience and response based on detected sentiment
- 💬 Provides concise, friendly, and context-aware feedback
- 🤝 **Automatic self-registration with host agent**
- 🔄 Graceful fallback if host agent unavailable

The agent follows the A2A protocol and can be integrated with any A2A-compatible host agent.
