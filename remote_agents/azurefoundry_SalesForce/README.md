# AI Foundry Salesforce CRM Agent

An Azure AI Foundry agent that integrates with Salesforce CRM via MCP (Model Context Protocol) providing full access to data queries, data management, metadata operations, and Apex development tools.

## Features

### 📊 Data Query & Search (5 tools)
- **SEARCH_OBJECTS** - Search for Salesforce object names by pattern
- **DESCRIBE_OBJECT** - Get detailed metadata about a Salesforce object (fields, relationships, etc.)
- **QUERY_RECORDS** - Execute SOQL queries to retrieve records
- **AGGREGATE_QUERY** - Run aggregate queries (COUNT, SUM, AVG, etc.)
- **SEARCH_ALL** - Search across multiple objects using SOSL

### 📝 Data Management (1 tool)
- **DML_RECORDS** - Create, update, or delete Salesforce records

### 🏗️ Metadata Management (3 tools)
- **MANAGE_OBJECT** - Create or manage custom Salesforce objects
- **MANAGE_FIELD** - Create or manage custom fields on objects
- **MANAGE_FIELD_PERMISSIONS** - Manage field-level security permissions

### 💻 Apex Code Management (4 tools)
- **READ_APEX** - Read Apex class code
- **WRITE_APEX** - Create or update Apex classes
- **READ_APEX_TRIGGER** - Read Apex trigger code
- **WRITE_APEX_TRIGGER** - Create or update Apex triggers

### 🐛 Development & Debugging (2 tools)
- **EXECUTE_ANONYMOUS** - Execute anonymous Apex code for testing
- **MANAGE_DEBUG_LOGS** - Enable/disable debug logs and retrieve log data

### Additional Capabilities
- 🔎 **Web Search** – Query the web (e.g., Bing) for current information
- 🙋 **Human Expert Escalation** – Request human-in-the-loop assistance
- 🌐 **Dual Modes** – A2A API server and optional Gradio UI
- 🤝 **Self-Registration** – Registers with the Host Agent

## Example Use Cases

### Data Queries
```
"Show me all accounts in the technology industry"
"How many opportunities are in the pipeline?"
"What's the average deal size this quarter?"
"Find all contacts at companies starting with 'Tech'"
"List all open cases assigned to John"
```

### Data Management
```
"Create a new contact named John Smith at Acme Corp"
"Update the status of opportunity X to Closed Won"
"Delete the duplicate lead record"
"Create a new account for TechCorp Inc"
```

### Metadata Operations
```
"What fields does the Account object have?"
"Create a new custom field on the Lead object"
"Show me the picklist values for the Status field"
"What objects are available that contain 'Order'?"
```

### Development & Code
```
"Show me the code for the AccountTrigger"
"Read the AccountService Apex class"
"Run this Apex code to test the logic"
"Enable debug logs for user admin@example.com"
"Create a new Apex class for handling lead conversion"
```

## Project Structure
```
├── foundry_agent.py            # Core Salesforce CRM logic with MCP integration
├── foundry_agent_executor.py   # A2A executor with streaming execution
├── __main__.py                 # CLI entry point (A2A server + optional Gradio UI)
├── utils/self_registration.py  # Host-agent self-registration helper
├── documents/                  # Reference docs (optional)
├── static/                     # UI assets
└── pyproject.toml              # Dependencies
```

## Quick Start

### 1) Environment Setup
```bash
# Required Azure AI Foundry settings
export AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=your-project-endpoint
export AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=your-model-deployment

# Optional: A2A host for self-registration
export A2A_HOST=http://localhost:12000

# Optional: override bind/advertised endpoint
export A2A_ENDPOINT=localhost
export A2A_PORT=8000
```

### 2) Install Dependencies
```bash
uv sync
```

### 3) Run the Agent
- **A2A server only**:
  ```bash
  uv run .
  ```

- **Gradio UI + A2A server**:
  ```bash
  uv run . --ui
  ```

- **Custom ports**:
  ```bash
  uv run . --ui --ui-port 8091 --port 8003
  ```

## MCP Server Configuration

The agent connects to a Salesforce MCP server. Update the MCP endpoint in `foundry_agent.py`:
```python
self._mcp_server_url = "https://your-mcp-server-url/sse"
```

## Default Ports
- A2A Server: `localhost:8000` (override with `A2A_PORT` or `--port`)
- Gradio UI: `8085` (override with `--ui-port`)
- Host Agent: `http://localhost:12000` (override with `A2A_HOST`)
