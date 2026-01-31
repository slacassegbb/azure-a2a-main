# Azure AI Foundry HubSpot CRM Agent

An A2A-compatible agent that provides HubSpot CRM capabilities using Azure AI Foundry with MCP (Model Context Protocol) integration.

## Features

- **Contact Management** - Create, search, list, and update contacts
- **Company Management** - Create, search, list, and update companies
- **Deal Management** - Create, search, list, and update deals/opportunities
- **Associations** - View relationships between CRM objects
- **Notes & Engagements** - Create notes on CRM records
- **Account Info** - View account details and owners

## Architecture

```
┌─────────────────────────┐
│   A2A Frontend          │
└───────────┬─────────────┘
            │ A2A Protocol
            ▼
┌─────────────────────────┐
│  HubSpot A2A Agent      │  ← Port 9040
│  (this agent)           │
└───────────┬─────────────┘
            │ AgentsClient
            ▼
┌─────────────────────────┐
│  Azure AI Foundry       │
│  (gpt-4o + MCP)         │
└───────────┬─────────────┘
            │ MCP/SSE
            ▼
┌─────────────────────────┐
│  HubSpot MCP (Flat)     │  ← Flattened schemas
│  mcp-hubspot-flat       │
└───────────┬─────────────┘
            │ REST API
            ▼
┌─────────────────────────┐
│  HubSpot API            │
└─────────────────────────┘
```

## Why Flattened MCP?

Azure AI Foundry has issues with deeply nested JSON schemas in MCP tool definitions. The official `@hubspot/mcp-server` uses complex nested schemas (e.g., `filterGroups[].filters[].propertyName`), which causes agent runs to fail.

This agent uses a custom flattened HubSpot MCP server (`mcp-hubspot-flat`) that provides the same functionality with flat schemas that Azure AI Foundry can process.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` | Azure AI Foundry project endpoint | Required |
| `AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME` | Model deployment name | `gpt-4o` |
| `HUBSPOT_MCP_URL` | HubSpot MCP SSE URL | `https://mcp-hubspot-flat.ambitioussky-6c709152.westus2.azurecontainerapps.io/sse` |
| `A2A_PORT` | Port to run the agent | `9040` |

## Running Locally

```bash
# Install dependencies
uv sync

# Run the agent
uv run .
```

## Deploy to Azure

```bash
az containerapp up \
  --name azurefoundry-hubspot \
  --resource-group rg-a2a-prod \
  --source . \
  --ingress external \
  --target-port 9040 \
  --env-vars \
    AZURE_AI_FOUNDRY_PROJECT_ENDPOINT="your-endpoint" \
    AZURE_OPENAI_API_KEY="your-key" \
    A2A_ENDPOINT="https://azurefoundry-hubspot.your-env.azurecontainerapps.io"
```

## Available HubSpot Tools

| Tool | Description |
|------|-------------|
| `hubspot_get_user_details` | Get account info and owners |
| `hubspot_list_objects` | List CRM objects (contacts, companies, deals) |
| `hubspot_search_objects` | Search with flattened filter syntax |
| `hubspot_get_object` | Get a single object by ID |
| `hubspot_create_contact` | Create a new contact |
| `hubspot_create_company` | Create a new company |
| `hubspot_create_deal` | Create a new deal |
| `hubspot_update_object` | Update any object |
| `hubspot_list_associations` | List associations between objects |
| `hubspot_create_note` | Create a note/engagement |

## Search Filter Syntax

When searching, use simple string filters:

```
filter1: "email EQ john@example.com"
filter2: "amount GT 1000"
filter3: "createdate GTE 2026-01-01"
```

Operators: `EQ`, `NEQ`, `LT`, `LTE`, `GT`, `GTE`, `CONTAINS_TOKEN`
