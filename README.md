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
