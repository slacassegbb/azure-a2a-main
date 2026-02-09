# Twilio SMS Agent

A2A Remote Agent for **two-way SMS communication** via Twilio, powered by Azure AI Foundry.

## Overview

This agent uses **Azure AI Foundry** with **function calling** to send and receive SMS messages via the Twilio API. It can be used for:
- **Sending** SMS notifications and alerts to users
- **Receiving** SMS replies from users  
- **Two-way SMS conversations** with users
- **Monitoring** incoming messages

## Architecture

```
User Request → Host Orchestrator → Previous Agents → Twilio SMS Agent → SMS to User
                                                     ↑
                                              User SMS Reply
```

The agent:
1. **Send**: Receives a message from the orchestrator and delivers it via Twilio SMS
2. **Receive**: Retrieves recent incoming SMS messages from Twilio's message log
3. Returns confirmation and message details

## Skills

| Skill | Description |
|-------|-------------|
| **Send SMS Message** | Send an SMS text message to a phone number via Twilio |
| **Receive SMS Messages** | Retrieve and read recent incoming SMS messages |
| **User Notification** | Notify a user via SMS with workflow results or updates |

## Configuration

Create a `.env` file with the following variables:

```env
# Azure AI Foundry Configuration
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT="https://your-project.services.ai.azure.com/api/projects/proj-default"
AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME="gpt-4o"

# Twilio Credentials (from https://console.twilio.com/)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here

# Phone Numbers
TWILIO_FROM_NUMBER=+1234567890          # Your Twilio number
TWILIO_DEFAULT_TO_NUMBER=+1234567890    # Default recipient

# A2A Configuration
A2A_ENDPOINT=localhost
A2A_PORT=8016
A2A_HOST=http://localhost:12000         # Host agent for registration
```

## Running the Agent

### Using uv (recommended)

```bash
cd remote_agents/azurefoundry_twilio2
uv sync
uv run python -m __main__
```

### Using pip

```bash
cd remote_agents/azurefoundry_twilio2
pip install -e .
python -m __main__
```

### Options

```bash
python -m __main__ --help

Options:
  --host TEXT     Host to bind to (default: localhost)
  --port INTEGER  Port for A2A server (default: 8016)
```

## Function Tools

The agent has two function tools available:

### `send_sms`

Sends an SMS message via Twilio.

**Parameters:**
- `message` (required): The SMS message content (max ~1600 characters)
- `to_number` (optional): Recipient phone number in E.164 format (e.g., +15147715943)

**Example:**
```python
send_sms(
    message="Your account balance is $1,234.56",
    to_number="+15147715943"
)
```

### `receive_sms`

Retrieves recent incoming SMS messages from Twilio.

**Parameters:**
- `from_number` (optional): Filter messages from a specific phone number
- `limit` (optional): Maximum number of messages to retrieve (default: 10, max: 50)

**Example:**
```python
# Get last 10 messages from any sender
receive_sms()

# Get last 5 messages from specific number
receive_sms(from_number="+15147715943", limit=5)
```

**Output:** Messages will be printed to the terminal with details including sender, timestamp, and content.

## Example Workflow Usage

### Example 1: Send SMS Notification

In a multi-agent workflow:

```yaml
workflow:
  name: "Balance Check with SMS Notification"
  agents:
    - name: stripe
      task: "Get current account balance"
    - name: twilio
      task: "Send the balance summary via SMS to +15147715943"
```

### Example 2: Two-Way SMS Conversation

```yaml
workflow:
  name: "SMS Conversation"
  agents:
    - name: twilio
      task: "Check if any users have replied to our SMS"
    - name: processor
      task: "Process the user's reply and determine next action"
    - name: twilio
      task: "Send a follow-up SMS based on the user's response"
```

### Example 3: Monitor Specific User Replies

```
User: "Check if John (+15147715943) has replied to my text"
Twilio Agent: Uses receive_sms(from_number="+15147715943") to check for replies
```

The orchestrator will:
1. Call the Stripe agent to get the balance
2. Call the Twilio agent with: "Send SMS: Your Stripe balance is $1,234.56"
3. The Twilio agent sends the SMS and confirms delivery

## API Endpoints

- `GET /health` - Health check
- `POST /` - A2A task endpoint
- `GET /.well-known/agent.json` - Agent card

## Trial Account Limitations

If using a Twilio trial account:
- Can only send SMS to **verified phone numbers**
- Messages are prefixed with "Sent from your Twilio trial account"
- Verify numbers at: https://console.twilio.com/us1/develop/phone-numbers/manage/verified

## Troubleshooting

### "Missing required environment variables"
Ensure all required variables are set in your `.env` file.

### "Twilio credentials not configured"
Check that `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` are correct.

### "Cannot send to unverified number" (Trial accounts)
Verify the recipient number in the Twilio console.

### "Rate limit exceeded"
Your Azure AI Foundry deployment needs at least 20,000 TPM allocated.
