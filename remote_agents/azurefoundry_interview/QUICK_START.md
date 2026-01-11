# 🚀 Quick Start - Interview Agent

Get your AI consulting interview agent running in 10 minutes!

## Prerequisites

- Python 3.10+
- Azure AI Foundry project with model deployment
- Azure authentication configured (CLI, credentials, or environment variables)

---

## Step 1: Configure Azure (2 minutes)

1. **Copy the environment template**:
   ```bash
   cd remote_agents/azurefoundry_interview
   ```

2. **Create `.env` file** with your Azure details:
   ```bash
   # Required
   AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=https://your-project.cognitiveservices.azure.com/
   AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=gpt-4o
   
   # Optional - for auto-registration with host
   HOST_AGENT_URL=http://localhost:12000
   
   # Optional - custom ports if needed
   A2A_PORT=9020
   UI_PORT=9120
   ```

3. **Ensure Azure authentication** is set up:
   ```bash
   # Option 1: Use Azure CLI (easiest for local dev)
   az login
   
   # Option 2: Set environment variables
   # export AZURE_TENANT_ID=your-tenant-id
   # export AZURE_CLIENT_ID=your-client-id
   # export AZURE_CLIENT_SECRET=your-client-secret
   ```

---

## Step 2: Install Dependencies (2 minutes)

```bash
# Create virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install uv (fast package installer)
pip install uv

# Install dependencies
uv pip install -r ../../backend/requirements.txt
```

---

## Step 3: Customize for Your Company (5 minutes)

### Edit `interview_config.py`:

```python
# Line 12-13: Update company info
COMPANY_NAME = "Your AI Consulting Company"
COMPANY_DESCRIPTION = "Your company description"

# Lines 22-68: Customize interview questions (optional)
# Lines 75-100: Adjust agent personality (optional)
```

### Edit `documents/INTERVIEW_GUIDE.md`:

Replace the placeholder content with:
- Your actual services
- Real case studies
- Your pricing models
- Your company values

**Tip**: You can update these anytime and just restart the agent!

---

## Step 4: Run the Agent (1 minute)

### Option A: A2A Server Only (Production Mode)

```bash
uv run .
```

Your agent will:
- ✅ Start on port 9020 (or your configured port)
- ✅ Auto-register with host agent (if HOST_AGENT_URL is set)
- ✅ Be available at `http://localhost:9020`

### Option B: With Gradio UI (Testing Mode)

```bash
uv run . --ui
```

This adds a chat interface at `http://localhost:9120` for easy testing.

---

## Step 5: Test It! (2 minutes)

### Test with Gradio UI:

1. Open `http://localhost:9120` in your browser
2. Start a conversation: "I'm interested in AI for my business"
3. Observe how the agent asks follow-up questions
4. Notice the `input_required` behavior when the agent probes for details

### Test with Host Orchestrator:

1. Start your backend (in another terminal):
   ```bash
   cd backend
   python backend_production.py
   ```

2. Open frontend at `http://localhost:3000`

3. Look for "AI Consulting Interview Agent" in the agent catalog

4. Start a conversation through the multi-agent system

---

## What to Expect

### First Message

The agent will greet you and ask an opening question:

> "Hello! I'm here to learn about your AI and automation needs. To start, could you tell me about your company and what brings you here today?"

### During the Interview

- Agent asks 1-2 questions at a time
- Probes deeper based on your responses
- References your documents when discussing capabilities
- Uses `input_required` to ensure it gets important information

### Conversation Topics

The agent will typically explore:

1. **Company Information** - Who you are, industry, size
2. **AI Needs** - Challenges, goals, expected outcomes
3. **Technical Context** - Tech stack, data, team capabilities
4. **Timeline & Budget** - When and what you can invest
5. **Contact & Next Steps** - Who's involved, how to follow up

### End of Interview

The agent will:
- Summarize what it learned
- Suggest appropriate next steps
- Offer to schedule consultation or provide resources

---

## Troubleshooting

### "Rate limit exceeded" errors

**Cause**: Azure AI Foundry deployment needs at least 20,000 TPM

**Fix**: Request quota increase in Azure portal (Management > Quota)

### Agent not appearing in catalog

**Cause**: HOST_AGENT_URL not set or backend not running

**Fix**: 
1. Check `.env` has `HOST_AGENT_URL=http://localhost:12000`
2. Verify backend is running: `curl http://localhost:12000/health`
3. Check agent logs for registration errors

### Agent not using my documents

**Cause**: Documents not in correct folder or unsupported format

**Fix**:
1. Ensure documents are in `documents/` folder
2. Use supported formats: `.md`, `.pdf`, `.txt`, `.docx`, `.json`, `.csv`
3. Check agent startup logs for upload confirmation

### Port already in use

**Cause**: Another agent or process using the port

**Fix**: Change port in `.env`:
```bash
A2A_PORT=9025  # Use different port
UI_PORT=9125   # Use different UI port
```

### Changes not taking effect

**Cause**: Agent needs restart to pick up config changes

**Fix**: Stop agent (Ctrl+C) and restart: `uv run .`

---

## Next Steps

Now that your agent is running:

1. **Test thoroughly**: Have several test conversations
2. **Refine questions**: Update `interview_config.py` based on what works
3. **Add documents**: Upload more company materials to `documents/`
4. **Customize further**: See `CUSTOMIZATION_GUIDE.md` for advanced options
5. **Deploy**: Once satisfied, deploy to production (Azure Container Apps, App Service, etc.)

---

## Quick Reference

### Files to Customize

| File | Purpose | Edit Frequency |
|------|---------|----------------|
| `interview_config.py` | Questions, personality, behavior | Often |
| `documents/INTERVIEW_GUIDE.md` | Company info, services, cases | Often |
| `documents/WELCOME.md` | Interview introduction | Rarely |
| `.env` | Azure config, ports | Once |
| `foundry_agent.py` | Agent logic | Rarely |
| `__main__.py` | Skills, agent card | Rarely |

### Common Commands

```bash
# Run A2A server only
uv run .

# Run with UI for testing
uv run . --ui

# Check health
curl http://localhost:9020/health

# Get agent card
curl http://localhost:9020/card

# View logs (verbose)
# Set VERBOSE_LOGGING=true in .env first
uv run .
```

### Ports

- **9020**: A2A server (customize with `A2A_PORT`)
- **9120**: Gradio UI (customize with `UI_PORT`)
- **12000**: Host agent (backend)
- **3000**: Frontend

---

## Getting Help

- **Customization**: See `CUSTOMIZATION_GUIDE.md`
- **Full Documentation**: See `README.md`
- **Azure AI Foundry**: [Microsoft Docs](https://learn.microsoft.com/azure/ai-services/agents/)
- **A2A Protocol**: [GitHub](https://github.com/microsoft/a2a)

---

**You're all set! Start interviewing leads! 🎤**

Remember: The agent learns from your documents, so the better your documents, the better your interviews!


