"""
Central configuration for Azure AI Foundry A2A Agent Template

⚠️ CUSTOMIZATION REQUIRED ⚠️
Update these values to match your agent's identity and purpose.

This single file controls all agent naming, branding, skills, and configuration.
Changes here automatically propagate to:
- agent_instructions.prompty (agent title, model)
- foundry_agent.py (agent ID, model, vector store name)
- __main__.py (all UI text, descriptions, ports, agent card, skills)
- Health check endpoints
- All startup/logging messages
- Agent catalog registration

Simply update the values below and restart your agent - no need to hunt
through multiple files to change agent names, skills, or configuration!
"""

# ============================================================================
# Agent Identity
# ============================================================================

# Human-readable name displayed in UI and registration
AGENT_NAME = "AI Foundry Template Agent"

# Technical identifier used in Azure AI Foundry (no spaces, lowercase recommended)
AGENT_ID = "foundry-template-agent"

# Short description of what the agent does
AGENT_DESCRIPTION = (
    "A template agent powered by Azure AI Foundry. "
    "Customize this description to explain what your agent does "
    "and what domain knowledge it has access to."
)

# Longer description for prompty and documentation
AGENT_FULL_TITLE = "Foundry Template Agent Instructions"

# Version number (semantic versioning recommended)
AGENT_VERSION = "1.0.0"

# ============================================================================
# UI Customization
# ============================================================================

# Gradio UI window title
UI_TITLE = "AI Foundry Template Agent"

# Markdown heading in Gradio UI
UI_HEADING = "🤖 AI Foundry Template Agent"

# Path to agent logo (relative to agent directory)
UI_LOGO_PATH = "static/a2a.png"

# Chat interface description/tagline
UI_CHAT_DESCRIPTION = (
    "Ask me questions related to my domain knowledge. "
    "Replace this with your agent's description."
)

# Markdown description shown in the UI (supports markdown formatting)
UI_MARKDOWN_DESCRIPTION = """
**⚠️ CUSTOMIZATION REQUIRED:**  
Replace this description with your agent's actual capabilities and purpose.

**What it does:**
- [Describe your agent's primary function]
- [What domain knowledge does it have?]
- [What documents ground its responses?]

### Core Capabilities
- [List your agent's skills here - see _build_agent_skills() above]
- [Add more capabilities as needed]
"""

# ============================================================================
# Model Configuration
# ============================================================================

# Azure OpenAI model deployment name to use
# This is the model used when creating the agent in Azure AI Foundry
# Common values: "gpt-4o", "gpt-4", "gpt-35-turbo"
MODEL_DEPLOYMENT_NAME = "gpt-4o"

# ============================================================================
# Network Configuration
# ============================================================================

# Default A2A server port (can be overridden by A2A_PORT environment variable)
DEFAULT_A2A_PORT = 9020

# Default Gradio UI port (can be overridden by UI_PORT environment variable)
DEFAULT_UI_PORT = 9120

# ============================================================================
# Vector Store Configuration
# ============================================================================

# Name for the vector store in Azure AI Foundry
VECTOR_STORE_NAME = "agent_template_vectorstore"

# ============================================================================
# Agent Skills Definition
# ============================================================================

# Define your agent's skills/capabilities here. These appear in the agent catalog
# and help users understand what your agent can do.
#
# Each skill should have:
# - id: unique identifier (snake_case)
# - name: display name
# - description: what the skill does
# - tags: searchable keywords
# - examples: sample queries that demonstrate the skill

AGENT_SKILLS = [
    # EXAMPLE SKILL - Replace with your own skills
    {
        'id': 'example_skill_1',
        'name': 'Example Skill',
        'description': "This is a template skill. Replace this with your agent's actual capabilities based on your domain knowledge and uploaded documents.",
        'tags': ['example', 'template', 'customize'],
        'examples': [
            'Example query 1 - replace with real use case',
            'Example query 2 - replace with real use case',
            'Example query 3 - replace with real use case',
        ],
    },
    # ADD MORE SKILLS HERE
    # Copy the dict block above and customize for each capability
    # {
    #     'id': 'your_skill_id',
    #     'name': 'Your Skill Name',
    #     'description': "What this skill does",
    #     'tags': ['tag1', 'tag2'],
    #     'examples': ['Example 1', 'Example 2'],
    # },
]

# ============================================================================
# Agent Card Configuration
# ============================================================================

# Input/output modes supported by the agent
AGENT_INPUT_MODES = ['text']
AGENT_OUTPUT_MODES = ['text']

# Agent capabilities
AGENT_CAPABILITIES = {"streaming": True}
