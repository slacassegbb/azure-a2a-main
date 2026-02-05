# A2A Teams Agent

Human-in-the-loop agent that enables real-time communication with users via Microsoft Teams. Use this agent when you need human input, approval, or escalation within A2A workflows.

## Features

- **Human-in-the-Loop**: Send questions to users in Teams and wait for their response
- **A2A Protocol**: Fully compatible with the A2A agent protocol using Azure AI Foundry
- **Input Required State**: Uses A2A's `input_required` state to properly signal when waiting for human input
- **Proactive Messaging**: Send notifications to Teams users from any A2A workflow
- **Multi-User Support**: Track and message multiple connected Teams users
- **Function Calling Pattern**: Uses Azure AI Foundry function calling (like the email agent)

## Skills

### 📱 Send Teams Message
Send a message to a user via Microsoft Teams. Use this to communicate with humans, ask questions, or provide updates.

### ⏳ Wait for Human Response
Wait for a human to respond via Microsoft Teams. The workflow will pause (using `input_required` state) until the human responds.

### 🚨 Human Escalation
Escalate a task to a human via Teams when the AI cannot proceed autonomously.

## Prerequisites

1. **Azure AI Foundry**: You need an Azure AI Foundry project with a deployed model (e.g., gpt-4o)

2. **Azure Bot Registration**: You need a Microsoft Bot Framework registration with:
   - App ID and Password
   - Tenant ID (for Single Tenant apps)
   - Messaging endpoint configured to your public URL

3. **Teams App**: The bot must be installed in your Teams environment

4. **ngrok or Public URL**: For local development, expose the `/api/messages` endpoint

## Quick Start

1. **Configure environment variables** (copy from `.env.example`):
   ```bash
   AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=your-foundry-endpoint
   AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=gpt-4o
   MICROSOFT_APP_ID=your-app-id
   MICROSOFT_APP_PASSWORD=your-app-password
   MICROSOFT_APP_TENANT_ID=your-tenant-id
   A2A_PORT=8021
   ```

2. **Start ngrok** (in a separate terminal):
   ```bash
   ngrok http 8021
   ```

3. **Update Bot Messaging Endpoint** in Azure Portal:
   - Set it to: `https://your-ngrok-url.ngrok-free.app/api/messages`

4. **Run the agent**:
   ```bash
   cd remote_agents/azurefoundry_teams
   uv run .
   ```

5. **Initialize the bot**: Message your bot in Teams with "hi" to establish the connection

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `http://localhost:8021/` | A2A API endpoint |
| `http://localhost:8021/api/messages` | Teams Bot webhook |
| `http://localhost:8021/health` | Health check |

## Human-in-the-Loop Workflow

1. Agent receives task via A2A protocol
2. Agent determines human input needed (uses TEAMS_WAIT_RESPONSE block)
3. Agent sends message to Teams and sets task state to `input_required`
4. Human responds in Teams
5. Webhook receives response and resumes the waiting task
6. Agent continues with the human input and completes the task

## Docker

```bash
docker build -t teams-agent .
docker run -p 8021:8021 --env-file .env teams-agent
```

## License

MIT License
