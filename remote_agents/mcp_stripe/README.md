# Stripe MCP Server

This is a containerized Stripe MCP server that exposes Stripe's MCP tools via HTTP/SSE for Azure AI Foundry integration.

## How it works

1. **Stripe MCP** (`@stripe/mcp`) runs in stdio mode with your API key
2. **Supergateway** proxies stdio to HTTP/SSE on port 8080
3. Azure AI Foundry connects to the `/sse` endpoint

## Available Tools (22 total)

| Category | Tools |
|----------|-------|
| **Customers** | `create_customer`, `list_customers` |
| **Products** | `create_product`, `list_products` |
| **Pricing** | `create_price`, `list_prices`, `create_payment_link` |
| **Invoicing** | `create_invoice`, `list_invoices`, `create_invoice_item`, `finalize_invoice` |
| **Payments** | `list_payment_intents`, `retrieve_balance`, `create_refund` |
| **Subscriptions** | `list_subscriptions`, `cancel_subscription`, `update_subscription` |
| **Coupons** | `list_coupons`, `create_coupon` |
| **Disputes** | `list_disputes`, `update_dispute` |
| **Documentation** | `search_stripe_documentation` |

## Local Testing

```bash
# Run locally with Docker
docker build -t mcp-stripe .
docker run -p 8080:8080 -e STRIPE_API_KEY=sk_test_... mcp-stripe

# Test the SSE endpoint
curl http://localhost:8080/sse
```

## Deploy to Azure Container Apps

```bash
# From the repo root
./deploy-remote-agent.sh -a mcp_stripe -p 8080

# Or manually:
cd remote_agents/mcp_stripe
az containerapp up \
    --name mcp-stripe \
    --resource-group rg-a2a-prod \
    --source . \
    --ingress external \
    --target-port 8080 \
    --env-vars STRIPE_API_KEY=sk_test_...
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `STRIPE_API_KEY` | Your Stripe secret key (test or live) | Yes |
| `PORT` | Server port (default: 8080) | No |

## Usage with Azure AI Foundry

Once deployed, use the MCP endpoint in your Foundry agent:

```python
from azure.ai.agents.models import McpTool, ToolSet

mcp_tool = McpTool(
    server_label="Stripe",
    server_url="https://mcp-stripe.your-app.azurecontainerapps.io/sse",
    allowed_tools=[
        "list_customers",
        "create_customer", 
        "list_invoices",
        "retrieve_balance",
        # ... add more as needed
    ]
)
mcp_tool.set_approval_mode("never")

toolset = ToolSet()
toolset.add(mcp_tool)
```

## Security Notes

⚠️ **Use test keys for development!** Never commit live API keys.

- Use restricted API keys in production
- Consider using Azure Key Vault for secrets
- Enable Stripe webhook signatures for verification
