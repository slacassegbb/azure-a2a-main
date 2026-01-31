# HubSpot MCP Server (Flattened)

A flattened HubSpot MCP server designed for Azure AI Foundry compatibility.

## Why Flattened?

Azure AI Foundry has issues with deeply nested JSON schemas in MCP tool definitions. The official `@hubspot/mcp-server` uses complex nested schemas (e.g., `filterGroups[].filters[].propertyName`), which causes agent runs to fail.

This server provides the same HubSpot functionality but with **flat schemas** that Azure AI Foundry can process.

## Tools Available

| Tool | Description |
|------|-------------|
| `hubspot_get_user_details` | Get account info and owners |
| `hubspot_list_objects` | List CRM objects (contacts, companies, deals, etc.) |
| `hubspot_search_objects` | Search with flattened filter syntax |
| `hubspot_get_object` | Get a single object by ID |
| `hubspot_create_contact` | Create a new contact |
| `hubspot_create_company` | Create a new company |
| `hubspot_create_deal` | Create a new deal |
| `hubspot_update_object` | Update any object |
| `hubspot_list_associations` | List associations between objects |
| `hubspot_create_note` | Create a note/engagement |

## Flattened Filter Syntax

Instead of nested filter groups, use simple string filters:

```
filter1: "email EQ john@example.com"
filter2: "amount GT 1000"
filter3: "createdate GTE 2026-01-01"
```

Operators: `EQ`, `NEQ`, `LT`, `LTE`, `GT`, `GTE`, `CONTAINS_TOKEN`

## Deployment

### Deploy to Azure Container Apps

```bash
az containerapp up \
  --name mcp-hubspot-flat \
  --resource-group rg-a2a-prod \
  --source . \
  --ingress external \
  --target-port 8000 \
  --env-vars PRIVATE_APP_ACCESS_TOKEN="your-token-here"
```

### Local Testing

```bash
npm install
PRIVATE_APP_ACCESS_TOKEN="your-token" node index.js
```

## MCP SSE Endpoint

After deployment: `https://mcp-hubspot-flat.<your-env>.azurecontainerapps.io/sse`
