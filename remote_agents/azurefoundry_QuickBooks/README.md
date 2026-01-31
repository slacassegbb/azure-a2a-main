# AI Foundry QuickBooks Online Agent

An Azure AI Foundry agent that integrates with QuickBooks Online via MCP (Model Context Protocol) providing full access to accounting data, customer management, invoicing, bills, vendors, and financial reporting.

## Features

### � Customers (5 tools)
- **qbo_search_customers** - Search for customers by name or other criteria
- **qbo_get_customer** - Get detailed information about a specific customer
- **qbo_create_customer** - Create a new customer record
- **qbo_update_customer** - Update an existing customer's information
- **qbo_delete_customer** - Delete a customer record

### 🧾 Invoices (5 tools)
- **qbo_search_invoices** - Search for invoices by various criteria
- **qbo_get_invoice** - Get detailed information about a specific invoice
- **qbo_create_invoice** - Create a new invoice
- **qbo_update_invoice** - Update an existing invoice
- **qbo_delete_invoice** - Delete an invoice

### 📊 Accounts (4 tools)
- **qbo_search_accounts** - Search for chart of accounts entries
- **qbo_get_account** - Get detailed account information
- **qbo_create_account** - Create a new account in the chart of accounts
- **qbo_update_account** - Update an existing account

### 📦 Items (4 tools)
- **qbo_search_items** - Search for products and services
- **qbo_get_item** - Get detailed item information
- **qbo_create_item** - Create a new product or service item
- **qbo_update_item** - Update an existing item

### 🏢 Vendors (5 tools)
- **qbo_search_vendors** - Search for vendors/suppliers
- **qbo_get_vendor** - Get detailed vendor information
- **qbo_create_vendor** - Create a new vendor record
- **qbo_update_vendor** - Update an existing vendor
- **qbo_delete_vendor** - Delete a vendor record

### 💳 Bills (5 tools)
- **qbo_search_bills** - Search for bills/payables
- **qbo_get_bill** - Get detailed bill information
- **qbo_create_bill** - Create a new bill
- **qbo_update_bill** - Update an existing bill
- **qbo_delete_bill** - Delete a bill

### 👷 Employees (4 tools)
- **qbo_search_employees** - Search for employees
- **qbo_get_employee** - Get detailed employee information
- **qbo_create_employee** - Create a new employee record
- **qbo_update_employee** - Update an existing employee

### 📝 Estimates (5 tools)
- **qbo_search_estimates** - Search for estimates/quotes
- **qbo_get_estimate** - Get detailed estimate information
- **qbo_create_estimate** - Create a new estimate
- **qbo_update_estimate** - Update an existing estimate
- **qbo_delete_estimate** - Delete an estimate

### � Purchases (5 tools)
- **qbo_search_purchases** - Search for purchase transactions
- **qbo_get_purchase** - Get detailed purchase information
- **qbo_create_purchase** - Create a new purchase
- **qbo_update_purchase** - Update an existing purchase
- **qbo_delete_purchase** - Delete a purchase

### 📒 Journal Entries (5 tools)
- **qbo_search_journal_entries** - Search for journal entries
- **qbo_get_journal_entry** - Get detailed journal entry information
- **qbo_create_journal_entry** - Create a new journal entry
- **qbo_update_journal_entry** - Update an existing journal entry
- **qbo_delete_journal_entry** - Delete a journal entry

### 💰 Bill Payments (5 tools)
- **qbo_search_bill_payments** - Search for bill payments
- **qbo_get_bill_payment** - Get detailed bill payment information
- **qbo_create_bill_payment** - Create a new bill payment
- **qbo_update_bill_payment** - Update an existing bill payment
- **qbo_delete_bill_payment** - Delete a bill payment

### 📈 Query & Reports (3 tools)
- **qbo_query** - Execute custom queries against QuickBooks data
- **qbo_company_info** - Get company information and settings
- **qbo_report** - Generate financial reports (P&L, Balance Sheet, etc.)

### Additional Capabilities
- 🔎 **Web Search** – Query the web (e.g., Bing) for current information
- 🙋 **Human Expert Escalation** – Request human-in-the-loop assistance
- 🌐 **Dual Modes** – A2A API server and optional Gradio UI
- 🤝 **Self-Registration** – Registers with the Host Agent

## Example Use Cases

### Customer Management
```
"Show me all customers with 'Tech' in their name"
"Get details for customer ABC Corp"
"Create a new customer for XYZ Inc"
"Update the email for customer John Smith"
"List all active customers"
```

### Invoice Management
```
"Show me all unpaid invoices"
"Create an invoice for customer ABC Corp for $500"
"Get details for invoice #1001"
"What invoices are overdue?"
"List invoices from this month"
```

### Bills & Expenses
```
"Show me all bills due this week"
"Create a bill from vendor Office Supplies Inc"
"Record a payment for bill #2001"
"List all purchases this month"
"What bills are overdue?"
```

### Financial Reporting
```
"Show me the Profit and Loss report"
"Get the Balance Sheet"
"What's our company information?"
"Query all accounts receivable over $1000"
"Generate a sales report"
```

### Vendor Management
```
"List all our vendors"
"Create a new vendor for our supplier"
"Update vendor contact information"
"Get details for vendor ABC Supplies"
```

## Project Structure
```
├── foundry_agent.py            # Core QuickBooks logic with MCP integration
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
export A2A_PORT=8020
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
  uv run . ui
  ```

- **Custom ports**:
  ```bash
  uv run . ui --ui-port 8095 --a2a-port 8020
  ```

## MCP Server Configuration

The agent connects to a QuickBooks MCP server. Update the MCP endpoint in `foundry_agent.py`:
```python
self._mcp_server_url = "https://b216cb9d1f7a.ngrok-free.app/sse"
```

## Default Ports
- A2A Server: `localhost:8020` (override with `A2A_PORT` or `--port`)
- Gradio UI: `8085` (override with `--ui-port`)
- Host Agent: `http://localhost:12000` (override with `A2A_HOST`)
