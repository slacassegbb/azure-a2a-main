# ⚡ Azure A2A Multi-Agent System

This repository is an **experimental (and evolving)** implementation of an **Azure-based A2A multi-agent orchestration system**. 

It demonstrates how to design, host, and scale a distributed network of intelligent agents using open protocols (**A2A**, **MCP**), **Azure AI Foundry**, and Azure-native services for **memory** and **observability**. The goal is to create an interoperable, production-grade framework that allows agents to communicate, collaborate, and reason together across environments and organizations.

This repository contains the complete documentation and setup instructions including the **Host Orchestrator (backend)**, **Frontend UI (frontend)**, and a collection of **specialized remote agents (remote_agents)**. Each remote agent runs independently and can connect to the Host Orchestrator through open protocols like **A2A (Agent-to-Agent)**. 

You'll find detailed guides to install, configure, and run the full system, along with a **ready-to-use Agent Template** for building custom agents, plus sample agents that showcase realistic enterprise workflows including the **Claims, Fraud, Legal, Branding, Classification, Deep Search, Assessment & Estimation, Customer Support (MCP), Image Analysis, Image Generation, and Sentiment Analysis (Google ADK)** agents. Including an agent template for you to build your own remote agents quickly. 

Special thank you to Sergey Chernykh, Ryan Morgan, David Barkol and Owen Van Valkenburg for their peer review and contribution. 

---

## 🎥 Demonstration of Azure A2A Multi-Agent System

<table>
  <tr>
    <td align="center" width="33%">
      <a href="https://youtu.be/5t78x_9qUKM">
        <div style="width: 320px; height: 180px; overflow: hidden; margin: 0 auto; border-radius: 4px;">
          <img src="https://img.youtube.com/vi/5t78x_9qUKM/maxresdefault.jpg" style="width: 100%; height: 100%; object-fit: cover; transform: scale(1.4);" alt="Claims Workflow Demo" />
        </div>
        <br/><br/>
        <b>Claims Workflow</b><br/>
        <sub>Intro to Azure A2A + Multimodal + Memory</sub>
      </a>
    </td>
    <td align="center" width="33%">
      <a href="https://youtu.be/ziz7n7jLd7E">
        <img src="https://img.youtube.com/vi/ziz7n7jLd7E/maxresdefault.jpg" width="320" height="180" style="display: block; margin: 0 auto; object-fit: cover; border-radius: 4px;" alt="Content Creation Workflow Demo" />
        <br/><br/>
        <b>Content Creation Workflow</b><br/>
        <sub>Advanced Orchestration + Inter-Agent File Exchange + Human Collaboration</sub>
      </a>
    </td>
    <td align="center" width="33%">
      <a href="https://youtu.be/CenIL5zq79w">
        <img src="https://img.youtube.com/vi/CenIL5zq79w/maxresdefault.jpg" width="320" height="180" style="display: block; margin: 0 auto; object-fit: cover; border-radius: 4px;" alt="Customer Support Workflow Demo" />
        <br/><br/>
        <b>Customer Support Workflow</b><br/>
        <sub>MCP Remote Agents + Workflows + Human in the Loop</sub>
      </a>
    </td>
  </tr>
</table>

<br/>

> _Click any thumbnail to watch the Azure A2A multi-agent system in action — featuring dynamic orchestration, multimodal memory, and remote agents across environments._

## 📖 Architecture Whitepaper — *Scaling Agents for Enterprises*

A full companion paper is included with this repository, explaining the vision, architecture, protocols, and patterns behind this system.

<p align="center">
  <a href="https://github.com/slacassegbb/azure-a2a-main/raw/main/Scaling_Agents_Enterprise.pdf">
    <img src="./paper_thumbnail.png" alt="Scaling Agents for Enterprises Whitepaper" width="350"/>
  </a>
</p>

> _Click the thumbnail above to open **Scaling_Agents.pdf** — "Scaling Agents for Enterprises: Guide to designing and scaling enterprise multi-agent systems using open standard agent protocols."_

---

## 🛠️ Local & Cloud Deployment

This guide focuses on local development, but the architecture is cloud-ready and can be easily deployed to Azure using **Bicep** or **Terraform**, allowing you to host and run both host and remote agents in the cloud.

**Backend** – Runs the Host Orchestrator and core A2A services (registry, memory, orchestration logic).  
**Frontend** – Provides the multi-agent user interface for managing sessions and visualizing interactions.  
**Remote Agents** – Specialized agents deployed independently with **local** endpoints that connect to the host via the A2A protocol.

Instructions below explain how to set up each component and run the system locally before deploying it to the cloud.

---

## ✅ Prerequisites

Install the following locally:

- Git and VS Code *(recommended)*
- Python 3.13+
- Optional: Docker 

Provision the following services in your Microsoft Azure subscription:

- Azure AI Foundry (make sure you have a model and embeddings model created)
- Search Service *(optional but recommended)*
- Storage Account *(optional but recommended)*
- Application Insights *(optional)*

---

## 🛠️ Installation and Setup Guide (Backend, Frontend and Remote Agents)

### 📦 1. Clone the Repository

```bash
git clone https://github.com/slacassegbb/azure-a2a-main.git
cd azure-a2a-main
```

---

### 🔧 2. Configure the Root Environment Variables

There is **one `.env.example` file in the root** of this repo. 

Create a copy of the file and rename it to `.env`:

```bash
cp .env.example .env
```

Open `.env` and configure your keys and service endpoints. Instructions are provided in the example file for each key and setup. Please ensure that the required Microsoft Azure services are provisioned in your subscription.

---

### ⚙️ 3. Start the Host Orchestrator (Backend)

The **Host Orchestrator** acts as the core intelligence and coordination hub:

- Registers agents through local A2A handshake or through the agent catalog
- Manages memory and multimodal content processing
- Provides Azure AI Foundry agent orchestration to run distributed A2A multi-agent workflows 
- WebSocket for backend and frontend integration: `http://localhost:8080`
- A2A Backend API server: `http://localhost:12000`

```bash
cd backend
python3 -m venv .venv    # (Windows: python -m venv venv)
source venv/bin/activate # (Windows: .\venv\Scripts\Activate.ps1)
python -m pip install -r requirements.txt

# Optional for Multi-Modal Document Processing
brew install --cask LibreOffice    # (Windows: winget install TheDocumentFoundation.LibreOffice)

# Important: Make sure you are logged into Azure
# In Terminal or PowerShell, run:
az login

python backend_production.py
```

---

### 🖥️ 4. Start the Multi-Agent UI (Frontend)

The **Frontend** provides an interactive web interface for managing, orchestrating, and visualizing multi-agent sessions.

- Connects to the Host Orchestrator via WebSocket for real-time updates and event streaming
- Enables users to create, manage, and monitor multi-agent conversations and distributed task workflows
- Provides visualization of agent interactions, delegations, and tool execution traces
- Supports file uploads, multimodal content processing, and voice interaction
- Includes a local agent catalog for browsing and registering agents dynamically
- Runs locally at `http://localhost:3000` by default

First download 👉 https://nodejs.org/en/download/

```bash
cd frontend
npm install
npm run dev
```

Then open:

```
http://localhost:3000
```

---

<small><small>

## 🤖 Remote Agents Setup Guide

A set of sample specialized A2A remote agents is provided in the `remote_agents` folder. 

---

### 🎨 Azure AI Foundry (A2A) — **Template Agent** ⭐
**Directory:** `remote_agents\azurefoundry_template` · **A2A_PORT=9020** (customizable)

**A ready-to-use template for building your own custom A2A agents.** The Template Agent provides all the boilerplate code needed to create specialized remote agents that integrate seamlessly with the Azure A2A multi-agent system. Simply customize the agent's personality, skills, and domain knowledge by editing 3 key sections. Includes full A2A protocol support, file search integration for document grounding, optional Bing search, Gradio UI for testing, and production-ready logging. Perfect starting point for creating domain-specific agents in minutes.

📖 **[View Template Agent Documentation →](./remote_agents/azurefoundry_template/README.md)**

---

### 🟦 Azure AI Foundry (A2A) — **Assessment & Estimation Agent**
**Directory:** `remote_agents\azurefoundry_assessment` · **A2A_PORT=9002**

The AI Foundry Assessment & Estimation Agent is an Azure-based A2A-compatible agent grounded in synthetic data for multi-line insurance assessment and cost estimation. It covers auto, property, travel, and health domains, applying structured workflows and QA rules. The agent runs as both an API service and interactive Gradio UI, integrating seamlessly with a Host Orchestrator for multi-agent collaboration.

---

### 🟩 Azure AI Foundry (A2A) — **Branding Agent**
**Directory:** `remote_agents\azurefoundry_branding` · **A2A_PORT=9033`

The AI Foundry Branding & Content Agent is an Azure-based A2A-compatible agent grounded in synthetic branding data that enforces visual and tonal consistency. It provides guidance on brand colors, lighting, composition, and copy tone to ensure all creative outputs stay on-brand. The agent runs as both an API service and interactive Gradio UI, integrating with a Host Orchestrator for collaborative content creation.

---

### 🟧 Azure AI Foundry (A2A) — **Claims Agent**
**Directory:** `remote_agents\azurefoundry_claims` · **A2A_PORT=9001`

The AI Foundry Claims Specialist Agent is an Azure-based A2A-compatible agent grounded in synthetic insurance data for realistic multi-line claims processing. It provides intelligent coverage validation, settlement estimation, documentation guidance, and regulatory compliance across auto, property, travel, and health domains. The agent operates as both an API service and interactive Gradio UI, integrating with a Host Orchestrator for coordinated claims handling and escalation.

---

### 🟥 Azure AI Foundry (A2A) — **Classification Agent**
**Directory:** `remote_agents\azurefoundry_classification` · **A2A_PORT=8001`

The AI Foundry Classification Triage Agent is an Azure-based A2A-compatible agent grounded in synthetic customer support data for realistic incident handling. It classifies incoming issues into categories like fraud, payment, security, or technical problems, assesses their priority, and routes them to the right teams using ServiceNow standards. The agent runs as both an API service and interactive Gradio UI, integrating with a Host Orchestrator for automated triage and escalation workflows.

---

### 🟪 Azure AI Foundry (A2A) — **Deep Search Agent**
**Directory:** `remote_agents\azurefoundry_Deep_Search` · **A2A_PORT=8002`

The AI Foundry Deep Search Knowledge Agent is an Azure-based A2A-compatible agent grounded in synthetic customer support documentation. It performs deep semantic search across topics like account management, billing, fraud prevention, and technical support to deliver precise, context-aware answers. The agent operates as both an API service and interactive Gradio UI, integrating with a Host Orchestrator for enterprise knowledge retrieval and customer assistance workflows.

---

### 🟫 Azure AI Foundry (A2A) — **Fraud Agent**
**Directory:** `remote_agents\azurefoundry_fraud` · **A2A_PORT=9004`

The AI Foundry Fraud Intelligence Agent is an Azure-based A2A-compatible agent grounded in synthetic fraud investigation data for realistic multi-line insurance analysis. It detects red flags, evaluates claim patterns, and recommends SIU escalation across auto, property, travel, and health domains. The agent operates as both an API service and interactive Gradio UI, integrating with a Host Orchestrator for coordinated fraud detection and compliance workflows.

---

### ⬛ Azure AI Foundry (A2A) — **Image Analysis Agent** *(Experimental)*
**Directory:** `remote_agents\azurefoundry_image_analysis` · **A2A_PORT=9066`

The AI Foundry Image Analysis Agent is an Azure-based A2A-compatible vision agent that **analyzes and interprets visual content**. It performs **detailed image understanding, object detection, scene analysis, and visual quality assessment** to provide actionable insights. The agent operates as an API service, integrating with a Host Orchestrator for coordinated visual analysis and content validation workflows.

---

### ⬛ Azure AI Foundry (A2A) — **Image Generation Agent** *(Experimental)*
**Directory:** `remote_agents\azurefoundry_image_generator` · **A2A_PORT=9010`

The AI Foundry Image Generator Agent is an Azure-based A2A-compatible creative agent that **transforms text prompts into high-quality images** and performs **advanced image editing**. It supports **in-painting, masking, and prompt-based modifications** to refine or extend existing visuals. The agent operates as an API service, integrating with a Host Orchestrator for coordinated visual creation and editing workflows.

---

### 🟨 Azure AI Foundry (A2A) — **Legal Agent**
**Directory:** `remote_agents\azurefoundry_legal` · **A2A_PORT=8006`

The AI Foundry Legal Compliance & Regulatory Agent is an Azure-based A2A-compatible agent grounded in synthetic legal and compliance data. It analyzes regulatory frameworks like GDPR, SOX, and CCPA, performs risk assessments, and reviews contracts and compliance documents for legal integrity. The agent operates as both an API service and interactive Gradio dashboard, integrating with a Host Orchestrator for coordinated governance and audit workflows.

---

### 🟦 Azure AI Foundry (A2A + MCP) — **Customer Support Agent (MCP)** *(Experimental)*
**Directory:** `remote_agents\azurefoundry_SN` · **A2A_PORT=8000`

The AI Foundry Expert Agent is an Azure-based **A2A and MCP-compatible** agent grounded in synthetic enterprise and support data. It can execute **ServiceNow actions via MCP server** (create and update **incidents**, look up customers, etc.), execute banking actions, perform web (with Bing added to Foundry agent portal) and document searches, and manage **human-in-the-loop** escalations. The agent runs as both an API service and interactive Gradio UI, integrating with a Host Orchestrator to automate IT service management, banking workflows, and expert escalation scenarios.

---

### 🟩 Google ADK (A2A) — **Sentiment Agent (MCP)**
**Directory:** `remote_agents\google_adk` · **A2A_PORT=8003`

The Sentiment Analysis Agent is a Google ADK A2A-compatible agent grounded in synthetic customer interaction data. It detects emotional tone, classifies sentiment, and personalizes responses across customer feedback, chats, and service interactions. The agent operates as a lightweight API service that integrates with a Host Orchestrator to enhance customer understanding, improve satisfaction, and guide next-step decisions based on detected sentiment.

---

### 🚀 Building Your Own Agents

Want to create a custom agent? Start with the **Template Agent** (listed first above) — it provides a clean, documented foundation with step-by-step instructions for building domain-specific agents in minutes.

You can also use the sample agents as-is to test your scenarios, or customize them for your specific needs. Each agent can be easily modified, and the `documents` folder lets you add your own data for grounding and testing.

**Important:** Before running any remote agent, make sure to create your own `.env` file in each remote agent directory—use the included `.env.example` as your starting point.

</small></small>

</small>

### Running the agents

```bash
cd remote_agents/<agent-name>
python3 -m venv .venv    # (Windows: python -m venv venv)
source .venv/bin/activate # (Windows: .\venv\Scripts\Activate.ps11)
pip install uv
uv run .                  # use 'uv run . --ui' to run Gradio UI
```

Once started, these agents become available in the **Agent Catalog** and can be registered into an active session. You can also bring your own **A2A-compliant** agents by simply connecting them via their endpoint or IP address. If the backend is already running, any agent you start will automatically register itself to the current session.

---

## 🌐 Instructions for the Google ADK Sentiment Agent (Cross-Cloud Example)

To demonstrate cross-cloud remote agents outside Azure, you can use the specialized **Google ADK Sentiment Analysis Agent**. Just update its `.env` file with your own Google ADK key before starting it.

```bash
cd remote_agents/google-adk-agent   # or your path
python3 -m venv .venv    # (Windows: python -m venv venv)
source .venv/bin/activate # (Windows: .\venv\Scripts\Activate.ps1)
pip install a2a-sdk
python __main__.py
```

---

## 🌐 8. Customer Support MCP Agent (ServiceNow MCP integration)

This agent is experimental but fully functional.

To set up the MCP server, an MCP Server is also provided in the `MCP_SERVICENOW/servicenow-mcp` directory to demonstrate ServiceNow MCP integration. 

**To use it in your own ServiceNow environment, you’ll need to supply your own ServiceNow credentials in the `.env` file.**

**Important:** Azure AI Foundry agents require a **public MCP endpoint**, not `localhost` as currently configured. You can either:

- Deploy the MCP server in a container or host with a public URL, or
- Use **NGROK** to expose localhost. 

The Customer Support MCP Agent can run as a standalone agent and includes its own **Gradio UI**, which you can use to test it independently or demonstrate **human-in-the-loop** orchestration between the host and remote agent.

**Running the Customer Support MCP Agent**

```bash
cd /azurefoundry_SN/MCP_SERVICENOW/servicenow-mcp
python -m mcp_server_servicenow.cli --transport http --host 127.0.0.1 --port 8005   # change 127.0.0.1 to your public endpoint if not using NGROK

# Launch the Customer Support MCP Agent with UI
cd remote_agents/azurefoundry_SN
python3 -m venv .venv    # (Windows: python -m venv venv)
source .venv/bin/activate # (Windows: .\venv\Scripts\Activate.ps1)
uv run . --ui            # use --ui to also load the Gradio app on localhost
```

Then open:

```
http://localhost:8085
```

---

## 🎉 Local Multi-Agent Network Running

Start the backend, the frontend, and connect your agents or register them manually.
