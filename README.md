# ⚡ Azure A2A Multi-Agent System

This repository is an **experimental (and evolving)** implementation of an **Azure-based A2A multi-agent orchestration system**.

It demonstrates how to design, host, and scale a distributed network of intelligent agents using open protocols (**A2A**, **MCP**), **Azure AI Foundry**, and Azure-native services for **memory** and **observability**.  
The goal is to create an **interoperable, production-grade framework** that allows agents to communicate, collaborate, and reason together across environments and organizations.

This repository includes the **Host Orchestrator (backend)**, **Frontend UI (frontend)**, and a **collection of specialized remote agents (remote_agents)**.  
Each remote agent runs independently and connects to the Host Orchestrator through open protocols such as **A2A (Agent-to-Agent)** and **MCP (Model Context Protocol)**.

You’ll find detailed guides to install, configure, and run the full system — along with sample agents that showcase realistic enterprise workflows including:

**Claims**, **Fraud**, **Legal**, **Branding**, **Classification**, **Deep Search**, **Assessment & Estimation**, **Customer Support (MCP)**, **Image Generation**, and **Sentiment Analysis (Google ADK)**.

---

## 🎥 Demonstration of Azure A2A Multi-Agent System

| Claims Workflow *(Intro to Azure A2A + Multimodal + Memory)* | Customer Support Workflow *(MCP Remote Agents + Workflows + Human in the Loop)* |
|---------------------------------------------------------------|--------------------------------------------------------------------------------|
| [![Demo 1](https://img.youtube.com/vi/5t78x_9qUKM/hqdefault.jpg)](https://youtu.be/5t78x_9qUKM) | [![Demo 2](https://img.youtube.com/vi/CenIL5zq79w/hqdefault.jpg)](https://youtu.be/CenIL5zq79w) |

> _Click to watch the Azure A2A multi-agent system in action — featuring live orchestration, memory, and cross-cloud connected agents._

---

## 📖 Architecture Whitepaper — *Scaling Agents for Enterprises*

A full companion paper is included with this repository, explaining the vision, architecture, protocols, and design patterns behind this system.

<a href="./Scaling_Agents.pdf">
  <img src="./paper_thumbnail.png" alt="Scaling Agents Whitepaper" width="350"/>
</a>

> _Click the thumbnail above to open **Scaling_Agents.pdf** — “Scaling Agents for Enterprises: Guide to designing and scaling enterprise multi-agent systems using open standard agent protocols.”_

---

## 🛠️ Local & Cloud Deployment

While this guide focuses on **local development**, the architecture is **cloud-ready** and easily deployable to Azure using **Bicep** or **Terraform**, allowing you to host and run both the Host Orchestrator and Remote Agents in the cloud.

**Components**

- **Backend** – Runs the Host Orchestrator and core A2A services (registry, memory, orchestration logic).  
- **Frontend** – Provides the multi-agent UI for managing sessions and visualizing interactions.  
- **Remote Agents** – Specialized agents deployed independently with local endpoints that connect to the host via the A2A protocol.

---

## ✅ Prerequisites

Install locally:

- **Git** and **VS Code** *(recommended)*  
- **Python 3.13+**  
- **Docker** *(optional)*  

Provision these services in your **Microsoft Azure** subscription:

- **Azure AI Foundry**  
- **Azure Search Service** *(optional but recommended)*  
- **Azure Storage Account** *(optional but recommended)*  
- **Azure Application Insights** *(optional)*  

---

## 🧩 Installation and Setup Guide  
*(Backend · Frontend · Remote Agents)*

### 📦 1. Clone the Repository

```bash
git clone https://github.com/slacassegbb/azure-a2a-main.git
cd azure-a2a-main
```

---

### 🔧 2. Configure Root Environment Variables

There is **one `.env.example`** file in the root directory.

```bash
cp .env.example .env
```

Open `.env` and configure your keys and service endpoints.  
Ensure required Azure services are provisioned before continuing.

---

### ⚙️ 3. Start the Host Orchestrator (Backend)

The **Host Orchestrator** acts as the core intelligence and coordination hub:

- Registers agents via local A2A handshake or agent catalog  
- Manages memory and multimodal content processing  
- Provides Azure AI Foundry orchestration for distributed A2A workflows  
- WebSocket for frontend integration → `http://localhost:8080`  
- Backend API server → `http://localhost:12000`

```bash
cd backend
python3 -m venv .venv      # Windows: python -m venv venv
source venv/bin/activate   # Windows: .\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# Optional for multi-modal document processing
brew install --cask LibreOffice   # Windows: winget install TheDocumentFoundation.LibreOffice

# Make sure you are logged into Azure
az login

python backend_production.py
```

---

### 🖥️ 4. Start the Multi-Agent UI (Frontend)

The **Frontend** provides an interactive web interface for managing, orchestrating, and visualizing multi-agent sessions.

**Key Features**

- Real-time WebSocket updates  
- Multi-agent conversation and workflow management  
- Visualization of delegations and tool traces  
- File upload · multimodal content · voice input  
- Local agent catalog for dynamic registration  
- Runs at [`http://localhost:3000`](http://localhost:3000)

**Setup**

1. Install Node.js → [https://nodejs.org/en/download/](https://nodejs.org/en/download/)  
2. Run the frontend:

```bash
cd frontend
npm install
npm run dev
```

Then open your browser to:

```
http://localhost:3000
```

---

## 🤖 Remote Agents Setup Guide

A set of sample specialized **A2A remote agents** is included under `/remote_agents`.  
Each runs independently and connects to the Host Orchestrator using A2A or MCP protocols.

---

### 🧠 Assessment & Estimation Agent  
**Directory:** `remote_agents/azurefoundry_assessment` · **Port:** `9002`

The AI Foundry Assessment & Estimation Agent is grounded in synthetic data for multi-line insurance assessment and cost estimation across auto, property, travel, and health domains.  
It operates as both an API service and Gradio UI, integrating with the Host Orchestrator for collaborative estimation workflows.

---

### 🎨 Branding Agent  
**Directory:** `remote_agents/azurefoundry_branding` · **Port:** `9033`

Ensures visual and tonal brand consistency across creative outputs.  
Provides guidance on brand colors, lighting, composition, and copy tone.  
Operates as both an API and Gradio UI for collaborative content generation.

---

### 🧾 Claims Agent  
**Directory:** `remote_agents/azurefoundry_claims` · **Port:** `9001`

Handles realistic, multi-line claims processing (auto, property, travel, health).  
Performs coverage validation, settlement estimation, and compliance checks.

---

### 🗂️ Classification Agent  
**Directory:** `remote_agents/azurefoundry_classification` · **Port:** `8001`

Performs intelligent triage of incidents such as fraud, payment, or technical issues.  
Integrates with ServiceNow-style workflows for automated routing and escalation.

---

### 🔍 Deep Search Agent  
**Directory:** `remote_agents/azurefoundry_deep_search` · **Port:** `8002`

Provides deep semantic search across enterprise documentation (billing, fraud, support).  
Integrates with the Host Orchestrator for knowledge retrieval workflows.

---

### 🕵️‍♂️ Fraud Agent  
**Directory:** `remote_agents/azurefoundry_fraud` · **Port:** `9004`

Performs fraud pattern detection, anomaly evaluation, and SIU escalation logic.  
Integrates with compliance and investigative workflows.

---

### 🖼️ Image Generation Agent *(Experimental)*  
**Directory:** `remote_agents/azurefoundry_image_generator` · **Port:** `9010`

Transforms text prompts into high-quality images and performs advanced image editing.  
Supports in-painting, masking, and prompt-based refinement workflows.

---

### ⚖️ Legal Compliance Agent  
**Directory:** `remote_agents/azurefoundry_legal` · **Port:** `8006`

Analyzes compliance frameworks (GDPR, SOX, CCPA) and contract integrity.  
Operates as an API service and Gradio dashboard for governance workflows.

---

### 💬 Customer Support Agent *(MCP Experimental)*  
**Directory:** `remote_agents/azurefoundry_SN` · **Port:** `8000`

Executes ServiceNow actions via MCP server (create/update incidents, customer lookups).  
Supports document and web search, banking actions, and human-in-the-loop workflows.

---

### 🌤️ Sentiment Agent *(Google ADK Cross-Cloud)*  
**Directory:** `remote_agents/google_adk` · **Port:** `8003`

Detects emotional tone and classifies sentiment across customer interactions.  
Integrates as a lightweight cross-cloud agent for customer understanding and escalation.

---

## ⚙️ Running Remote Agents

Before running any remote agent, create your own `.env` file in its directory using the included `.env.example` as a template.

```bash
cd remote_agents/<agent-name>
python3 -m venv .venv      # Windows: python -m venv venv
source .venv/bin/activate   # Windows: .\venv\Scripts\Activate.ps1
pip install uv
uv run .                   # or 'uv run . --ui' to launch Gradio UI
```

Once started, these agents become available in the **Agent Catalog** and can be registered into an active session.  
If the backend is already running, new agents will automatically register to the current session.

---

## 🌐 Google ADK Sentiment Agent (Cross-Cloud Example)

To demonstrate cross-cloud remote agents outside Azure, you can use the **Google ADK Sentiment Analysis Agent**.  
Update its `.env` file with your Google ADK key before starting.

```bash
cd remote_agents/google-adk-agent
python3 -m venv .venv
source .venv/bin/activate
pip install a2a-sdk
python __main__.py
```

---

## 🧭 Customer Support MCP Agent (ServiceNow MCP Integration)

This agent is experimental but fully functional.

To set up the **MCP Server**, use the implementation under:  
`MCP_SERVICENOW/servicenow-mcp`

**Setup**

- Supply your own ServiceNow credentials in the `.env` file.  
- Azure AI Foundry agents require a public MCP endpoint (not localhost).  
  - Deploy the MCP server to a public host or  
  - Use **NGROK** to tunnel your localhost.  

```bash
cd /azurefoundry_SN/MCP_SERVICENOW/servicenow-mcp
python -m mcp_server_servicenow.cli --transport http --host 127.0.0.1 --port 8005
```

Then launch the Customer Support MCP Agent with UI:

```bash
cd remote_agents/azurefoundry_SN
python3 -m venv .venv
source .venv/bin/activate
uv run . --ui
```

Then open:

```
http://localhost:8085
```

---

## 🎉 Local Multi-Agent Network Running

Once all components (backend, frontend, and remote agents) are running, you’ll have a **fully functional local A2A multi-agent ecosystem**.  
Agents can discover, communicate, and collaborate across services — all orchestrated via the **Host Orchestrator** and visualized in the **Frontend UI**.

---

> _You can use the included agents as-is to test scenarios or adapt them as templates for your own use cases. Each agent supports customization and grounding with your own data stored in the `documents` folder._
