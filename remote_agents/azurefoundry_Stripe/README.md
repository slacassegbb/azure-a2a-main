# 💳 AI Foundry Stripe Agent

An intelligent Azure AI Foundry agent specialized in **Stripe payment processing**. This agent can manage customers, payments, subscriptions, invoices, products, and check account balance using the Stripe API.

## 🚀 Features

### 💳 Payment Processing
- Create and manage payment intents
- Process charges and refunds
- Track payment status

### 👥 Customer Management
- List, create, search customers
- Update customer information
- Delete customers

### 🔄 Subscription Management
- Create and manage recurring subscriptions
- Update subscription plans
- Cancel subscriptions

### 📄 Invoice Management
- Create and send invoices
- Track invoice status
- List unpaid/overdue invoices

### 📦 Products & Pricing
- Manage product catalog
- Create and update prices
- List products and prices

### 💰 Balance & Payouts
- Check available balance
- View pending funds
- Track payouts

## 📋 Prerequisites

- Python 3.12+
- Azure AI Foundry project with:
  - GPT-4o model deployment
  - (Optional) Bing Search connection for web search
- Stripe MCP Server deployed (see `mcp_stripe` folder)

## 🛠️ Installation

1. **Clone and navigate to the agent folder:**
   ```bash
   cd remote_agents/azurefoundry_Stripe
   ```

2. **Create your environment file:**
   ```bash
   cp .env.example .env
   ```

3. **Configure your `.env` file:**
   ```bash
   # Required
   AZURE_AI_FOUNDRY_PROJECT_ENDPOINT="your-foundry-endpoint"
   AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME="gpt-4o"
   
   # Stripe MCP Server (already deployed)
   STRIPE_MCP_URL="https://mcp-stripe.ambitioussky-6c709152.westus2.azurecontainerapps.io/sse"
   
   # A2A Configuration
   A2A_PORT=9030
   A2A_HOST=http://localhost:12000
   ```

4. **Install dependencies and run:**
   ```bash
   pip install uv  # if not already installed
   uv run .
   ```

   Or with the Gradio UI:
   ```bash
   uv run . --ui
   ```

## 🎯 Usage Examples

### List Customers
```
"List all my Stripe customers"
"Show me customers with email containing @example.com"
```

### Check Balance
```
"What is my current Stripe balance?"
"Show me available and pending funds"
```

### Create Customer
```
"Create a new customer with email john@example.com and name John Doe"
```

### Manage Subscriptions
```
"List all active subscriptions"
"Show me subscriptions expiring this month"
```

### Payment Intents
```
"Create a payment intent for $100 USD"
"List recent payment intents"
```

## 🔧 Stripe MCP Tools (22 Available)

| Category | Tools |
|----------|-------|
| **Customers** | `list_customers`, `create_customer`, `retrieve_customer`, `update_customer`, `delete_customer`, `search_customers` |
| **Payments** | `list_payment_intents`, `create_payment_intent`, `retrieve_payment_intent`, `confirm_payment_intent`, `cancel_payment_intent` |
| **Subscriptions** | `list_subscriptions`, `create_subscription`, `retrieve_subscription`, `update_subscription`, `cancel_subscription` |
| **Products** | `list_products`, `create_product`, `list_prices`, `create_price` |
| **Invoices** | `list_invoices`, `create_invoice` |
| **Balance** | `retrieve_balance` |

## 🌐 A2A Integration

This agent registers with the host agent at startup and is available for multi-agent workflows.

**Agent Card:**
- **Name:** AI Foundry Stripe Agent
- **Port:** 9030 (default)
- **Capabilities:** Streaming, Text I/O

## 📁 Project Structure

```
azurefoundry_Stripe/
├── __main__.py              # Entry point with CLI and Gradio UI
├── foundry_agent.py         # Stripe agent implementation
├── foundry_agent_executor.py # A2A executor
├── pyproject.toml           # Dependencies
├── .env.example             # Environment template
├── README.md                # This file
├── utils/                   # Self-registration utility
│   └── self_registration.py
└── documents/               # Optional documents for file search
```

## 🔗 Related

- **Stripe MCP Server:** `../mcp_stripe/` - The underlying MCP server
- **QuickBooks Agent:** `../azurefoundry_QuickBooks/` - Similar pattern for QuickBooks
- **Host Agent:** `../../backend/` - The A2A host orchestrator
