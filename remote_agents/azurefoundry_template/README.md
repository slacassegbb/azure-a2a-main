# 🤖 Azure AI Foundry A2A Agent Template

**A ready-to-use template for creating custom A2A-compatible agents powered by Azure AI Foundry.**

This template provides all the boilerplate code needed to build your own specialized remote agent that integrates seamlessly with the Azure A2A multi-agent system. Simply customize the agent's personality, skills, and domain knowledge to create a production-ready agent in minutes.

---

## 📋 What's Included

- ✅ **Full A2A Protocol Support** – Works with the Azure A2A orchestrator out of the box
- ✅ **File Search Integration** – Automatically grounds responses in documents you upload
- ✅ **Optional Bing Search** – Web search capability if configured in Azure AI Foundry
- ✅ **Gradio UI** – Built-in chat interface for testing and demos
- ✅ **Self-Registration** – Automatically registers with the host agent on startup
- ✅ **Streaming Support** – Real-time response streaming for better UX
- ✅ **Clean Logging** – Production-ready logging with configurable verbosity
- ✅ **Centralized Configuration** – All agent identity settings in one file (`agent_config.py`)

---

## 🚀 Quick Start Guide

### Step 1: Set Up Your Environment

1. **Copy this template directory** to create your own agent:
   ```bash
   cp -r remote_agents/azurefoundry_template remote_agents/my_custom_agent
   cd remote_agents/my_custom_agent
   ```

2. **Customize your agent identity** in `agent_config.py`:
   ```python
   # Update these values to match your agent's purpose
   AGENT_NAME = "My Custom Agent"
   AGENT_ID = "my-custom-agent"
   AGENT_DESCRIPTION = "Description of what your agent does"
   # ... and more settings
   ```

3. **Create your `.env` file** from the template:
   ```bash
   cp .env.example .env
   ```

4. **Configure your Azure credentials** in `.env`:
   ```bash
   # Required: Azure AI Foundry
   AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=https://your-project.cognitiveservices.azure.com/
   AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=gpt-4o
   
   # Optional: Custom ports (defaults shown)
   A2A_PORT=9020
   A2A_ENDPOINT=localhost
   
   # Optional: Host agent auto-registration
   HOST_AGENT_URL=http://localhost:12000
   ```

5. **Install dependencies**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install uv
   uv pip install -r ../../backend/requirements.txt  # Install A2A SDK and dependencies
   ```

---

### Step 2: Add Your Domain Knowledge

1. **Upload your documents** to the `documents/` folder:
   ```bash
   # Add any combination of these file types:
   documents/
     ├── your_knowledge_base.md
     ├── domain_guide.pdf
     ├── reference_data.txt
     └── faq.csv
   ```

2. **Supported file formats**:
   - Markdown (`.md`)
   - PDF (`.pdf`)
   - Text files (`.txt`)
   - Word documents (`.docx`)
   - JSON (`.json`)
   - CSV (`.csv`)

Your agent will automatically index these documents and use them to ground its responses via Azure AI Foundry's file search capability.

---

### Step 3: Customize Your Agent

#### 3.1 Update Agent Identity (`agent_config.py`)

**All customization is now centralized in `agent_config.py`** - update this single file to configure your agent's entire identity and behavior:

```python
# ============================================================================
# Agent Identity
# ============================================================================

AGENT_NAME = "My Custom Agent"  # Human-readable name
AGENT_ID = "my-custom-agent"    # Technical ID (lowercase, no spaces)
AGENT_DESCRIPTION = "What your agent does"
AGENT_VERSION = "1.0.0"

# ============================================================================
# UI Customization
# ============================================================================

UI_TITLE = "My Custom Agent"
UI_HEADING = "🤖 My Custom Agent"
UI_LOGO_PATH = "static/a2a.png"  # Replace with your logo

# Chat interface description
UI_CHAT_DESCRIPTION = "Ask me about [your domain]"

# Main UI description (supports markdown)
UI_MARKDOWN_DESCRIPTION = """
**What I can help with:**
- [Capability 1]
- [Capability 2]
- [Capability 3]

### My Expertise
- [Domain 1]
- [Domain 2]
"""

# ============================================================================
# Model Configuration
# ============================================================================

MODEL_DEPLOYMENT_NAME = "gpt-4o"  # Azure OpenAI deployment name

# ============================================================================
# Network Configuration
# ============================================================================

DEFAULT_A2A_PORT = 9020  # A2A server port
DEFAULT_UI_PORT = 9120   # Gradio UI port

# ============================================================================
# Vector Store Configuration
# ============================================================================

VECTOR_STORE_NAME = "my_agent_vectorstore"

# ============================================================================
# Agent Skills Definition
# ============================================================================

AGENT_SKILLS = [
    {
        'id': 'troubleshooting',
        'name': 'Technical Troubleshooting',
        'description': "Diagnose and resolve technical issues",
        'tags': ['support', 'troubleshooting', 'technical'],
        'examples': [
            'Why is my account login failing?',
            'How do I reset my password?',
        ],
    },
    # Add more skills as needed
]

# ============================================================================
# Agent Card Configuration
# ============================================================================

AGENT_INPUT_MODES = ['text']
AGENT_OUTPUT_MODES = ['text']
AGENT_CAPABILITIES = {"streaming": True}
```

These settings automatically update:
- Agent registration card with all metadata
- Agent skills shown in catalog
- Gradio UI title, heading, and descriptions
- Azure AI Foundry agent name and model
- Default ports (can still be overridden by environment variables)
- Health check endpoints
- Startup messages
- All user-facing text

---

#### 3.2 Define Your Agent's Personality (`agent_instructions.prompty`)

The agent's behavior is defined in `agent_instructions.prompty`. Edit the system prompt section to customize your agent's role:

```
system:
You are a [YOUR ROLE] specialist powered by Azure AI Foundry.

## Core Responsibilities

1. **[Responsibility 1]** – [Description]
2. **[Responsibility 2]** – [Description]
3. **[Responsibility 3]** – [Description]

## Operating Guidelines

- Always consult documents in the `documents/` folder via file search
- [Add your specific guidelines]
- [Define your response style]

Current date and time: {{current_datetime}}
```

**Example**: For a customer support agent:
```
You are a Customer Support Specialist powered by Azure AI Foundry.

## Core Responsibilities

1. **Issue Resolution** – Help customers resolve technical and account issues
2. **Product Guidance** – Provide accurate information about features and usage
3. **Escalation Management** – Identify when issues need human intervention

## Operating Guidelines

- Always search the knowledge base before responding
- Be empathetic and professional
- Cite specific documentation when providing instructions
- If unsure, acknowledge limitations and offer to escalate

Current date and time: {{current_datetime}}
```

---

#### 3.3 Define Your Agent's Skills (`__main__.py`)

Open `__main__.py` and find the `_build_agent_skills()` function (line 94). Replace the example skill with your agent's actual capabilities:

---

#### 3.3 Define Your Agent's Skills (`agent_config.py`)

Agent skills are now defined in `agent_config.py` as the `AGENT_SKILLS` list. Each skill is a dictionary with the following fields:

```python
AGENT_SKILLS = [
    {
        'id': 'your_skill_id',
        'name': 'Your Skill Name',
        'description': "What this skill does and when to use it",
        'tags': ['tag1', 'tag2', 'tag3'],
        'examples': [
            'Example query 1',
            'Example query 2',
            'Example query 3',
        ],
    },
    # Add more skills as needed
]
```

**Example**: For a customer support agent:
```python
AGENT_SKILLS = [
    {
        'id': 'troubleshooting',
        'name': 'Technical Troubleshooting',
        'description': "Diagnose and resolve technical issues",
        'tags': ['support', 'troubleshooting', 'technical'],
        'examples': [
            'Why is my account login failing?',
            'How do I reset my password?',
        ],
    },
    {
        'id': 'product_information',
        'name': 'Product Information',
        'description': "Provide accurate product details",
        'tags': ['product', 'features', 'information'],
        'examples': [
            'What features are in the Pro plan?',
            'Does it integrate with Salesforce?',
        ],
    },
]
```

**Example**: For a customer support agent:
```python
def _build_agent_skills() -> List[AgentSkill]:
    return [
        AgentSkill(
            id='troubleshooting',
            name='Technical Troubleshooting',
            description="Diagnose and resolve technical issues",
            tags=['support', 'troubleshooting', 'technical'],
            examples=[
                'Why is my account login failing?',
                'How do I reset my password?',
            ],
        ),
    ]
```

---

### Step 4: Update Port Configuration (Optional)

If you're running multiple agents, ensure each uses a unique port.

**Option 1: In `agent_config.py` (Recommended)**:
```python
DEFAULT_A2A_PORT = 9025  # Choose an available port
DEFAULT_UI_PORT = 9125
```

**Option 2: In `.env` (Overrides config)**:
```bash
A2A_PORT=9025
```

---

## 🎬 Running Your Agent

### Option 1: A2A Server Only (Production)

Run your agent as an A2A server that can be discovered and used by the host orchestrator:

```bash
# Make sure you're in your agent directory
cd remote_agents/my_custom_agent

# Activate virtual environment
source .venv/bin/activate

# Run the agent
uv run .
```

Your agent will:
- Start on the configured A2A port (default: 9020)
- Auto-register with the host agent (if HOST_AGENT_URL is set)
- Be available at `http://localhost:9020` (or your configured port)

### Option 2: With Gradio UI (Development/Testing)

Run your agent with a chat interface for testing:

```bash
uv run . --ui
```

This will:
- Start the A2A server on port 9020 (or configured port)
- Start Gradio UI on port 9120 (or configured UI port)
- Open a browser with the chat interface

Access the UI at: `http://localhost:9120`

---

## 🔧 Advanced Customization

### Changing the Model

To use a different Azure OpenAI model, update in `agent_config.py`:

```python
MODEL_DEPLOYMENT_NAME = "gpt-4"  # or gpt-35-turbo, etc.
```

Or override via environment variable in `.env`:
```bash
AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=gpt-4
```

### Adding Custom File Handling

If you need to process uploaded files differently, modify the `execute()` method in `foundry_agent_executor.py`.

### Disabling Bing Search

If you don't want web search, the agent will work fine without it. The code already handles missing Bing connections gracefully.

---

## 📊 Testing Your Agent

### 1. Test with Gradio UI

```bash
uv run . --ui
```

Visit `http://localhost:9120` and ask questions related to your documents.

### 2. Test with Host Orchestrator

1. Start your backend (host orchestrator):
   ```bash
   cd backend
   python backend_production.py
   ```

2. Start your agent:
   ```bash
   cd remote_agents/my_custom_agent
   uv run .
   ```

3. Open the frontend at `http://localhost:3000` and look for your agent in the agent catalog.

### 3. Test A2A Endpoint Directly

```bash
# Check health
curl http://localhost:9020/health

# Get agent card
curl http://localhost:9020/card
```

---

## 🐛 Troubleshooting

### "Rate limit exceeded" errors

Your Azure AI Foundry deployment needs at least **20,000 TPM** (Tokens Per Minute). See the quota notes in `foundry_agent.py` for details.

### Agent not appearing in catalog

1. Check that `HOST_AGENT_URL` is set correctly in `.env`
2. Verify the backend is running
3. Check agent logs for registration errors

### File search not working

1. Ensure your documents are in the `documents/` folder
2. Check supported file formats (md, pdf, txt, docx, json, csv)
3. Look for upload errors in the startup logs

### Port conflicts

If you see "Address already in use", change your `A2A_PORT` in `.env` to an available port.

---

## 📝 Best Practices

1. **Define clear agent identity** – The AgentCard in `_create_agent_card()` is your agent's public face. Make the name and description clear and accurate.

2. **Write clear skills** – Skills appear in the agent catalog. Make them descriptive and include good examples.

3. **Test with real documents** – Add representative documents to the `documents/` folder for realistic testing.

4. **Version your agent** – Update the `version` field in AgentCard when you make significant changes.

5. **Keep descriptions clear** – The agent card description and Gradio UI description help users understand what your agent does.

---

## 🎯 Next Steps

- **Customize the agent logo**: Replace `static/a2a.png` with your own 100x100px image
- **Add more documents**: Upload comprehensive domain knowledge to `documents/`
- **Refine the prompt**: Iterate on the agent instructions based on test results
- **Deploy to production**: Use Azure Container Apps or App Service to host your agent

---

## 📚 Additional Resources

- [Azure AI Foundry Documentation](https://learn.microsoft.com/en-us/azure/ai-services/agents/)
- [A2A Protocol Specification](https://github.com/microsoft/a2a)
- [Main README](../../README.md) – Setup guide for the full multi-agent system

---

## ❓ Need Help?

If you encounter issues:
1. Check the logs (set `VERBOSE_LOGGING=true` in `.env` for detailed output)
2. Review the original branding agent (`azurefoundry_branding/`) as a working example
3. Ensure all environment variables are set correctly
4. Verify your Azure AI Foundry project is properly configured

---

**Happy Agent Building! 🚀**
