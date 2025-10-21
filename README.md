# ⚡ Azure A2A Multi-Agent System

> _“If you’ve made it this far, you’re either deeply passionate about multi-agent systems… or an extremely committed nerd.”_

Either way — welcome, you're in the right place.

This repository is an **experimental (and evolving)** implementation of an **Azure-based A2A multi-agent orchestration system**. It works, it’s real, and yes — there are **bugs**, **rough edges**, and a **backlog long enough to qualify as its own roadmap (see backlog below**.

I’ve poured an unreasonable number of late nights and coffee-fueled weekends into this, and while I absolutely love building it, one thing has become clear:

> **No single person should build an entire multi-agent system alone.**  
> _(For both technical reasons and for my social life to survive.)_

That’s why this project is **open-sourced — not as a finished product, but as a foundation**. A **blueprint** we can all push forward together.

---

### 🚀 Call to Action

If this sparks something in you — **jump in**:

- Open an issue  
- Fork it and break things  
- Improve it, challenge it, extend it  
- Propose wild ideas — seriously

Let’s turn this into the **multi-agent framework we all wish existed.**

### 🎥 Live Demos

| Claims Workflow (Intro to Azure A2A + Multimodal + Memory) | Customer Support Workflow (MCP Remote Agents + Workflows + Human in the Loop) |
|-------------------------------------|--------------------------------------------------------|
| [![Demo 1](https://img.youtube.com/vi/5t78x_9qUKM/hqdefault.jpg)](https://youtu.be/5t78x_9qUKM) | [![Demo 2](https://img.youtube.com/vi/CenIL5zq79w/hqdefault.jpg)](https://youtu.be/CenIL5zq79w) |

> _Click to watch the Azure A2A multi-agent system in action — with live agent orchestration, memory, and cross-cloud connected agents._

---

### 📖 Architecture Whitepaper — *Scaling Agents for Enterprises*

A full companion paper is included with this repository, explaining the vision, architecture, protocols, and patterns behind this system.

<a href="./Scaling_Agents.pdf">
  <img src="./paper_thumbnail.png" alt="Scaling Agents Whitepaper" width="350"/>
</a>

> _Click the thumbnail above to open **Scaling_Agents.pdf** — “Scaling Agents for Enterprises: Guide to designing and scaling enterprise multi-agent systems using open standard agent protocols.”_

---

## 🛠️ Local Setup & Installation Guide

This guide covers **local development only**.  
The architecture is cloud-ready, but **Azure deployment (Bicep/Terraform, public MCP endpoints, cross-cloud remote agents)** will be documented separately.

---

### ✅ Prerequisites (Local Environment)

Install the following locally:

- Python 3.10+
- Node.js & npm *(required for the full multi-agent UI)*
- Git and VS Code *(recommended)*
- Optional: Docker *(if you prefer containerized local agents)*

---

### 📦 1. Clone the Repository

```bash
git clone https://github.com/slacassegbb/azure-a2a-main.git
cd azure-a2a-main
```

---

### 🔧 2. Configure Environment Variables

There is **one `.env.example` file in the root** of this repo.

```bash
cp .env.example .env
```

Open `.env` and configure your keys and service endpoints.

---

### ⚙️ 3. Start the Host Orchestrator (Backend)

```bash
cd backend
source venv/bin/activate
python -m pip install -r requirements.txt
python backend_production.py
```

The **Host Orchestrator** acts as the core intelligence and coordination hub:

- Can Registers agents through local A2A handshake or through agent catalog
- Manages memory aand multimodal content processing
- Provides Azure AI Fondry agent orchestration to run distributed A2A multi-agent workflows 
- Websocket for backend and frontend integration: http://localhost:8080
- A2A Backend API server on http://localhost:12000
---

### 🖥️ 4. Start the Multi-Agent UI (Frontend)

```bash
cd frontend
npm install
npm run dev
```

Then open:

```
http://localhost:3000
```

> This is the **full orchestration UI** — visualizing agent connections, capability discovery, delegation chains, memory activity, and MCP routing in real time.

---

### 📎 5. Enable Host Multimodal Document Processing

The **Host Orchestrator** supports multimodal file processing (PDF, DOCX, etc.) for ingestion into memory.

Install **LibreOffice** locally:

```bash
brew install --cask libreoffice
```

---

### 🤖 6. Start Any Remote Agent Locally

A set of sample remote agents is provided in the remote_agents folder. You can use them as-is to test your scenarios or treat them as templates to adapt and build agents for your own use cases. Before running any remote agent, make sure to configure its .env file—use the included .env.example as your starting point.

```bash
cd remote_agents/<agent-name>
python3 -m venv .venv
source .venv/bin/activate
pip install uv
uv run .
```

Once started, these agents become available in the Agent Catalog and can be registered into an active session. You can also bring your own A2A-compliant agents by simply connecting them via their endpoint or IP address. If the backend is already running, any agent you start will automatically register itself to the current session.

---

### 🌐 7. (Optional) Google ADK Remote Agent (Cross-Cloud Example)

To demonstrate cross-cloud remote agents outside Azure, you can use the specialized Google ADK Sentiment Analysis Agent. Just update its .env file with your own Google ADK key before starting it.

```bash
cd remote_agents/google-adk-agent   # or your path
python3 -m venv .venv
source .venv/bin/activate
pip install a2a-sdk
python __main__.py
```

---

### 🌐 8. (Optional) Customer Support MCP Agent (ServiceNow MCP integration, Knowledge Grounding, Bing Search, Human in the Loop)  

For a more advanced example, a Customer Support MCP Agent with extensive capabilities is available in the azurefoundry_sn directory. This agent is experimental but fully functional.

An MCP Server is also provided in the MCP_SERVICENOW directory to demonstrate ServiceNow MCP integration. To use it in your own ServiceNow environment, you’ll need to supply your own ServiceNow credentials in the .env file.

Important: Azure AI Foundry agents require a public MCP endpoint, not localhost as currently configured. You can either:

- Deploy the MCP server in a container or host with a public URL, or
- Use NGROK to expose localhost.
  
Make sure to replace all instances of https://agent1.ngrok.app/mcp/ in foundry_agent.py with your own public endpoint.

Additionally, the Customer Support MCP Agent can run as a standalone agent and includes its own Gradio UI, which you can use to test it independently or demonstrate human-in-the-loop orchestration between the host and remote agent.

```bash
MCP Server Setup: (make sure you have a Service Now instance and set your. .env variables in the root directory of the MCP server folder)
cd /azurefoundry_SN/MCP_SERVICENOW/servicenow-mcp
python -m mcp_server_servicenow.cli --transport http --host 127.0.0.1 --port 8005 (change 127.0.0.1 to your public endpoint if not using NGROK)

Launch the Customer Support MCP Agent with UI

cd remote_agents/azurefoundry_SN
python3 -m venv .venv
source .venv/bin/activate
uv run . --ui (use the --ui to also load the gradio app on localhost, this agent has it's own UI interface)
```
Then open:

```
http://localhost:8085
```

---

### 🎉 Local Multi-Agent Network Running

Once the host, UI, and at least one agent are live, you have a **fully local A2A driven multi-agent system**.

---

> ☁️ **Cloud Deployment Note:**  
> This system is architected for **Azure hosting with public MCP endpoints, Bicep/Terraform provisioning, and distributed remote agents across clouds** — that deployment guide will be published next.  





