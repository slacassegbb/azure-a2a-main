# AI Foundry Reporter Agent

A professional report creation agent powered by Azure AI Foundry. Creates executive summaries, technical analyses, project status reports, and custom reports using structured templates.

## Features

- 📋 **Executive Summary Reports** – High-level overviews for leadership with key findings and recommendations
- 🔧 **Technical Analysis Reports** – Detailed technical evaluations with metrics, data, and risk assessments
- 📊 **Project Status Reports** – Progress updates with milestones, blockers, and outlook
- 📄 **Custom Reports** – Flexible format for any topic or purpose
- 🌐 **Web Search Integration** – Research current information via Bing search
- 📂 **Document Search** – Reference uploaded documents for grounded responses
- 🤝 **Self-Registration** – Registers with the Host Agent (A2A protocol)

## Project Structure

```
├── foundry_agent.py            # Core Reporter agent logic and report templates
├── foundry_agent_executor.py   # A2A executor with streaming and rate limiting
├── __main__.py                 # CLI entry point (A2A server + optional Gradio UI)
├── utils/self_registration.py  # Host-agent self-registration helper
├── documents/                  # Reference documents (report guides)
├── static/                     # UI assets
└── pyproject.toml              # Dependencies
```

## Quick Start

### 1) Environment Setup

```bash
# Required Azure AI Foundry settings
export AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=your-project-endpoint
export AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=your-model-deployment

# Optional: A2A host for self-registration (host agent URL)
export A2A_HOST=http://localhost:12000

# Optional: override bind/advertised endpoint
export A2A_ENDPOINT=localhost    # hostname used in public URL
export A2A_PORT=9020             # A2A server port (defaults to 9020)
```

### 2) Install Dependencies

```bash
uv sync
```

### 3) Run the Agent

**A2A server only** (serves on `http://$A2A_ENDPOINT:$A2A_PORT/`):

```bash
uv run .
```

Health check: `http://$A2A_ENDPOINT:$A2A_PORT/health`

**Gradio UI + A2A server**:

```bash
uv run . --ui
```

- UI: `http://localhost:9120` (default)
- A2A API: `http://localhost:9020/`

**Custom ports**:

```bash
uv run . --ui --ui-port 9121 --port 9021
```

### 4) Verify Self-Registration (optional)

With the host agent running, start the Reporter agent and confirm it appears in the host's Remote Agents list.

## Example Requests

### Executive Summary
```
Create an executive summary report on our company's Q4 2024 performance, 
focusing on revenue growth, customer acquisition, and strategic initiatives.
```

### Technical Analysis
```
Create a technical analysis report evaluating our current microservices 
architecture, including performance metrics, scalability concerns, and 
recommendations for improvement.
```

### Project Status
```
Create a project status report for the cloud migration project. We're 
currently in Phase 2, 60% complete, with the main blocker being 
database schema compatibility.
```

### Custom Report
```
Create a competitive analysis report on the top 3 competitors in the 
enterprise SaaS space. Include sections on market positioning, pricing 
strategies, feature comparison, and recommendations.
```

## Report Templates

The agent uses predefined templates to ensure consistent, professional output:

### Executive Summary Template
- 📌 Title, Date, Audience
- 🎯 Executive Summary (2-3 paragraphs)
- 📊 Key Findings (bullet points)
- 💡 Recommendations (numbered)
- ⏭️ Next Steps (action items)

### Technical Analysis Template
- 📌 Subject, Date, Analysis Type
- 📋 Overview
- 🔍 Detailed Analysis (by component)
- 📈 Metrics & Data (tables)
- ⚠️ Risks & Considerations
- 🎯 Conclusions

### Project Status Template
- 📌 Project Name, Period, Status Indicator
- 📈 Progress Summary
- ✅ Accomplishments
- 🎯 Upcoming Milestones
- ⚠️ Issues & Blockers
- 📊 Key Metrics
- 🔮 Outlook

## Troubleshooting

- Ensure `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` and `AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME` are set
- If the UI doesn't load, verify port `9120` or set `--ui-port`
- If the A2A server fails to bind, verify port `9020` or set `A2A_PORT`/`--port`
- If self-registration fails, confirm the host URL in `A2A_HOST` and that the host is reachable
- For rate limiting issues, ensure your Azure AI Foundry model has at least 20,000 TPM quota

## Default Ports & Environment Overrides

| Component | Default | Environment Variable |
|-----------|---------|---------------------|
| A2A Server | `9020` | `A2A_PORT` |
| Gradio UI | `9120` | `--ui-port` flag |
| Host Agent | `http://localhost:12000` | `A2A_HOST` |

## Integration with Host Agent

The Reporter agent can be called by the Host Agent to generate reports as part of multi-agent workflows. When invoked:

1. The agent receives the report request via A2A protocol
2. Optionally searches the web for current information
3. References any uploaded documents
4. Generates the report using the appropriate template
5. Returns the formatted report to the Host Agent

This enables workflows like:
- "Research AI trends and create an executive summary" (combines web search + report)
- "Analyze the uploaded data and create a technical report" (combines document search + report)
