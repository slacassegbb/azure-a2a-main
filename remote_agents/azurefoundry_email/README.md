# 📧 Email Agent

**An AI agent that sends emails using Microsoft Graph API.**

This agent can compose and send professional emails on behalf of users. It uses the A2A protocol to integrate with other agents and supports HTML formatting, CC recipients, and email templates.

---

## 📋 What's Included

- ✅ **Full A2A Protocol Support** – Works with the Azure A2A orchestrator out of the box
- ✅ **Microsoft Graph Integration** – Sends emails via Microsoft 365
- ✅ **HTML Formatting** – Professional email formatting with HTML
- ✅ **CC Support** – Send to multiple recipients
- ✅ **Confirmation Flow** – Preview emails before sending
- ✅ **Gradio UI** – Built-in chat interface for testing
- ✅ **Self-Registration** – Automatically registers with the host agent on startup
- ✅ **Streaming Support** – Real-time response streaming for better UX

---

## 🎯 What This Agent Does

This email agent is designed to:

1. **Send Emails** – Send emails to any recipient via Microsoft Graph API
2. **Compose Professional Content** – Create well-formatted, professional emails
3. **Support CC Recipients** – Copy additional recipients on emails
4. **Preview Before Sending** – Show email content for confirmation before sending
5. **Use HTML Formatting** – Format emails with headers, lists, and styling

---

## 🚀 Quick Start Guide

### Step 1: Set Up Your Environment

1. **Navigate to the agent directory**:
   ```bash
   cd remote_agents/azurefoundry_email
   ```

2. **Create your `.env` file** with the required credentials:
   ```bash
   # Required: Azure AI Foundry
   AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=https://your-project.cognitiveservices.azure.com/
   AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=gpt-4o
   
   # Required: Microsoft Graph Email Credentials
   EMAIL_TENANT_ID=your-azure-tenant-id
   EMAIL_CLIENT_ID=your-app-client-id
   EMAIL_CLIENT_SECRET=your-app-client-secret
   EMAIL_SENDER_ADDRESS=sender@yourdomain.com
   
   # Optional: Custom ports (defaults shown)
   A2A_PORT=9020
   A2A_ENDPOINT=localhost
   
   # Optional: Host agent auto-registration
   HOST_AGENT_URL=http://localhost:12000
   ```

3. **Install dependencies**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install uv
   uv pip install -r ../../backend/requirements.txt
   ```

---

### Step 2: Configure Microsoft Graph Permissions

Your Azure AD application needs the following Microsoft Graph permissions:

1. **Mail.Send** - Application permission to send emails
2. **User.Read** - Delegated permission (optional)

To set up:

1. Go to Azure Portal > Azure Active Directory > App registrations
2. Create a new app or use an existing one
3. Under API permissions, add:
   - Microsoft Graph > Application permissions > Mail.Send
4. Grant admin consent for the permissions
5. Create a client secret under Certificates & secrets
6. Copy the Tenant ID, Client ID, and Client Secret to your `.env` file

---

## 🎬 Running Your Agent

### Option 1: A2A Server Only (Production)

Run the agent as an A2A server:

```bash
cd remote_agents/azurefoundry_email
source .venv/bin/activate
uv run .
```

Your agent will:
- Start on the configured A2A port (default: 9020)
- Auto-register with the host agent (if HOST_AGENT_URL is set)
- Be available at `http://localhost:9020`

### Option 2: With Gradio UI (Development/Testing)

Run the agent with a chat interface for testing:

```bash
uv run . --ui
```

This will:
- Start the A2A server on port 9020 (or configured port)
- Start Gradio UI on port 9120 (or configured UI port)
- Open a browser with the chat interface

Access the UI at: `http://localhost:9120`

---

## 💡 Usage Examples

### Send a Simple Email
```
Send an email to john@example.com saying the meeting is at 3pm
```

### Email with Specific Subject
```
Email sarah@company.com with subject "Project Update" about the completed milestones
```

### Email with CC
```
Send an email to team-lead@company.com and CC manager@company.com about the quarterly review
```

### Professional Thank You
```
Send a thank you email to client@business.com for the great meeting today
```

---

## 📊 Testing Your Agent

### 1. Test with Gradio UI

```bash
uv run . --ui
```

Visit `http://localhost:9120` and try sending test emails.

### 2. Test with Host Orchestrator

1. Start your backend (host orchestrator):
   ```bash
   cd backend
   python backend_production.py
   ```

2. Start the email agent:
   ```bash
   cd remote_agents/azurefoundry_email
   uv run .
   ```

3. Open the frontend at `http://localhost:3000` and look for the Email Agent in the agent catalog.

### 3. Test A2A Endpoint Directly

```bash
# Check health
curl http://localhost:9020/health

# Get agent card
curl http://localhost:9020/card
```

---

## 🔧 Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` | Yes | Azure AI Foundry project endpoint |
| `AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME` | Yes | Model deployment name (e.g., gpt-4o) |
| `EMAIL_TENANT_ID` | Yes | Azure AD tenant ID |
| `EMAIL_CLIENT_ID` | Yes | Azure AD app client ID |
| `EMAIL_CLIENT_SECRET` | Yes | Azure AD app client secret |
| `EMAIL_SENDER_ADDRESS` | Yes | Sender email address |
| `A2A_PORT` | No | Port for A2A server (default: 9020) |
| `A2A_ENDPOINT` | No | Host for A2A server (default: localhost) |
| `HOST_AGENT_URL` | No | URL of host agent for registration |

---

## 🐛 Troubleshooting

### "Rate limit exceeded" errors

Your Azure AI Foundry deployment needs at least **20,000 TPM** (Tokens Per Minute).

### Email not sending

1. Check that all email credentials are set in `.env`
2. Verify the Azure AD app has Mail.Send permission
3. Ensure admin consent has been granted
4. Check that the sender email address is valid

### Agent not appearing in catalog

1. Check that `HOST_AGENT_URL` is set correctly in `.env`
2. Verify the backend is running
3. Check agent logs for registration errors

### Port conflicts

If you see "Address already in use", change your `A2A_PORT` in `.env` to an available port.

---

## 📝 Best Practices

1. **Preview Before Sending** – The agent will show email content before sending. Always review.

2. **Validate Email Addresses** – Ensure recipient addresses are correct before sending.

3. **Use Clear Instructions** – Be specific about the email content and tone you want.

4. **Test First** – Use the Gradio UI to test emails before production use.

---

## 📚 Additional Resources

- [Azure AI Foundry Documentation](https://learn.microsoft.com/en-us/azure/ai-services/agents/)
- [Microsoft Graph API - Send Mail](https://learn.microsoft.com/en-us/graph/api/user-sendmail)
- [A2A Protocol Specification](https://github.com/microsoft/a2a)
- [Main README](../../README.md) – Setup guide for the full multi-agent system

---

**Happy Emailing! 📧**
