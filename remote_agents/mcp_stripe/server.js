#!/usr/bin/env node

/**
 * Stripe MCP Server - HTTP Mode
 * Wraps @stripe/mcp to work like QuickBooks MCP server
 * Supports direct POST to /sse for Azure AI Foundry compatibility
 * 
 * Includes direct Stripe API fallbacks for tools that don't work in @stripe/mcp
 */

import { spawn } from 'child_process';
import http from 'http';
import https from 'https';
import { randomUUID } from 'crypto';

const PORT = parseInt(process.env.PORT || '8080');
const STRIPE_API_KEY = process.env.STRIPE_API_KEY;

if (!STRIPE_API_KEY) {
  console.error('ERROR: STRIPE_API_KEY environment variable is required');
  process.exit(1);
}

console.error('Starting Stripe MCP Server in HTTP mode...');
console.error(`  Port: ${PORT}`);
console.error(`  API Key: ${STRIPE_API_KEY.substring(0, 20)}...`);

// ========================================
// Direct Stripe API Helpers (fallback for broken @stripe/mcp tools)
// ========================================

async function callStripeAPI(endpoint, method = 'POST', data = {}) {
  return new Promise((resolve, reject) => {
    let postData = '';
    
    // Only build form data for non-GET requests
    if (method !== 'GET') {
      const formData = new URLSearchParams();
      
      // Flatten nested objects for Stripe's form-encoded API
      function addToForm(obj, prefix = '') {
        for (const [key, value] of Object.entries(obj)) {
          const fullKey = prefix ? `${prefix}[${key}]` : key;
          if (value !== null && value !== undefined) {
            if (typeof value === 'object' && !Array.isArray(value)) {
              addToForm(value, fullKey);
            } else if (Array.isArray(value)) {
              value.forEach((item, idx) => {
                if (typeof item === 'object') {
                  addToForm(item, `${fullKey}[${idx}]`);
                } else {
                  formData.append(`${fullKey}[${idx}]`, String(item));
                }
              });
            } else {
              formData.append(fullKey, String(value));
            }
          }
        }
      }
      addToForm(data);
      postData = formData.toString();
    }
    
    const headers = {
      'Authorization': `Bearer ${STRIPE_API_KEY}`
    };
    
    if (method !== 'GET') {
      headers['Content-Type'] = 'application/x-www-form-urlencoded';
      headers['Content-Length'] = Buffer.byteLength(postData);
    }
    
    const options = {
      hostname: 'api.stripe.com',
      port: 443,
      path: `/v1/${endpoint}`,
      method: method,
      headers: headers
    };
    
    const req = https.request(options, (res) => {
      let body = '';
      res.on('data', chunk => body += chunk);
      res.on('end', () => {
        try {
          const json = JSON.parse(body);
          if (res.statusCode >= 400) {
            reject(new Error(json.error?.message || `Stripe API error: ${res.statusCode}`));
          } else {
            resolve(json);
          }
        } catch (e) {
          reject(new Error(`Failed to parse Stripe response: ${body}`));
        }
      });
    });
    
    req.on('error', reject);
    if (method !== 'GET' && postData) {
      req.write(postData);
    }
    req.end();
  });
}

// Handle tools that don't work in @stripe/mcp directly
async function handleDirectStripeTool(toolName, args) {
  console.error(`Direct Stripe API call for: ${toolName}`, JSON.stringify(args));
  
  switch (toolName) {
    case 'list_customers': {
      // List customers directly via Stripe API - returns compact response
      let endpoint = 'customers?limit=' + (args.limit || 10);
      if (args.email) {
        endpoint += '&email=' + encodeURIComponent(args.email);
      }
      const result = await callStripeAPI(endpoint, 'GET', {});
      // Return compact customer list
      const customers = (result.data || []).map(c => ({
        id: c.id,
        email: c.email,
        name: c.name
      }));
      return {
        content: [{
          type: 'text',
          text: JSON.stringify(customers)
        }]
      };
    }
    
    case 'create_invoice': {
      // Create invoice directly via Stripe API
      const invoiceData = {
        customer: args.customer,
        auto_advance: false,  // Keep as draft
        currency: args.currency || 'usd'  // Default to USD
      };
      if (args.description) invoiceData.description = args.description;
      // If days_until_due is provided, must use send_invoice collection method
      if (args.days_until_due) {
        invoiceData.collection_method = 'send_invoice';
        invoiceData.days_until_due = args.days_until_due;
      } else if (args.collection_method) {
        invoiceData.collection_method = args.collection_method;
      }
      
      const invoice = await callStripeAPI('invoices', 'POST', invoiceData);
      return {
        content: [{
          type: 'text',
          text: `{"invoice_id":"${invoice.id}","status":"${invoice.status}","customer":"${invoice.customer}"}`
        }]
      };
    }
    
    case 'create_invoice_item': {
      // Create invoice item directly via Stripe API
      // Stripe now REQUIRES customer even when invoice is specified
      const itemData = {
        invoice: args.invoice,
        description: args.description || ''
      };
      
      // Customer is REQUIRED - get from args or fetch from invoice
      if (args.customer) {
        itemData.customer = args.customer;
      } else if (args.invoice) {
        // Fetch the invoice to get the customer ID
        try {
          const invoice = await callStripeAPI(`invoices/${args.invoice}`, 'GET', {});
          itemData.customer = invoice.customer;
          console.error(`Fetched customer ${invoice.customer} from invoice ${args.invoice}`);
        } catch (err) {
          console.error(`Warning: Could not fetch invoice to get customer: ${err.message}`);
        }
      }
      
      // Handle different pricing methods
      // Stripe API now uses "pricing" object, not "price" directly
      if (args.amount) {
        // Direct amount in cents - this still works
        itemData.amount = args.amount;
      } else if (args.price) {
        // Price ID reference - Stripe now expects pricing.price
        itemData.pricing = { price: args.price };
      } else if (args.pricing) {
        // Already formatted correctly
        itemData.pricing = args.pricing;
      } else if (args.unit_amount) {
        // Unit amount with quantity
        itemData.unit_amount = args.unit_amount;
        itemData.quantity = args.quantity || 1;
      }
      
      // Only add currency if explicitly passed AND no invoice specified
      if (!args.invoice && args.currency) {
        itemData.currency = args.currency;
      }
      
      const item = await callStripeAPI('invoiceitems', 'POST', itemData);
      return {
        content: [{
          type: 'text',
          text: `{"item_id":"${item.id}","invoice":"${item.invoice}","amount":${item.amount}}`
        }]
      };
    }
    
    case 'finalize_invoice': {
      // Finalize invoice directly via Stripe API
      const invoiceId = args.invoice;
      const invoice = await callStripeAPI(`invoices/${invoiceId}/finalize`, 'POST', {});
      return {
        content: [{
          type: 'text',
          text: `{"invoice_id":"${invoice.id}","status":"${invoice.status}","url":"${invoice.hosted_invoice_url}"}`
        }]
      };
    }
    
    default:
      return null;  // Not a direct-handled tool
  }
}

// ========================================
// End Direct Stripe API Helpers
// ========================================

// Start @stripe/mcp as a child process in stdio mode
const stripeMcp = spawn('npx', ['@stripe/mcp', '--tools=all', `--api-key=${STRIPE_API_KEY}`], {
  stdio: ['pipe', 'pipe', 'inherit'] // stdin, stdout, stderr
});

stripeMcp.on('error', (err) => {
  console.error('Failed to start Stripe MCP:', err);
  process.exit(1);
});

stripeMcp.on('exit', (code) => {
  console.error(`Stripe MCP process exited with code ${code}`);
  process.exit(code || 0);
});

// Track pending requests waiting for responses
const pendingRequests = new Map();

// Minimal initialize response to reduce token usage
// Azure Foundry re-initializes for every tool call, so this saves ~2K tokens per call
const MINIMAL_INIT_RESPONSE = {
  protocolVersion: "2025-03-26",
  capabilities: {
    tools: { listChanged: false }
  },
  serverInfo: {
    name: "Stripe",
    version: "1.0.0"
  }
};

// Helper to create a properly formatted MCP tool definition
// Azure AI Foundry requires specific fields in the schema
function mcpTool(name, description, properties, required = []) {
  return {
    name,
    description,
    inputSchema: {
      type: "object",
      properties,
      required,
      additionalProperties: false,
      "$schema": "http://json-schema.org/draft-07/schema#"
    },
    annotations: {
      title: name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
    }
  };
}

// MINIMAL tool definitions to reduce token usage
// The full @stripe/mcp tools/list is 21KB+ (~15K tokens)
// These compact schemas are ~4KB (~3K tokens) - 80% reduction!
const MINIMAL_TOOLS = [
  // Customer management
  mcpTool("create_customer", "Create a customer", 
    { name: { type: "string" }, email: { type: "string" } }, ["name"]),
  mcpTool("list_customers", "List customers", 
    { email: { type: "string" }, limit: { type: "integer" } }),
  
  // Products & Prices
  mcpTool("create_product", "Create a product", 
    { name: { type: "string" }, description: { type: "string" } }, ["name"]),
  mcpTool("list_products", "List products", 
    { limit: { type: "integer" } }),
  mcpTool("create_price", "Create a price for a product", 
    { product: { type: "string" }, unit_amount: { type: "integer", description: "cents" }, currency: { type: "string" } }, ["product", "unit_amount", "currency"]),
  mcpTool("list_prices", "List prices", 
    { product: { type: "string" }, limit: { type: "integer" } }),
  
  // Invoices - MOST IMPORTANT for workflows
  mcpTool("create_invoice", "Create a draft invoice for a customer", 
    { customer: { type: "string", description: "Customer ID (cus_xxx)" }, description: { type: "string" }, currency: { type: "string" } }, ["customer"]),
  mcpTool("list_invoices", "List invoices", 
    { customer: { type: "string" }, status: { type: "string" }, limit: { type: "integer" } }),
  mcpTool("create_invoice_item", "Add a line item to an invoice", 
    { invoice: { type: "string", description: "Invoice ID (in_xxx)" }, amount: { type: "integer", description: "Amount in cents" }, description: { type: "string" } }, ["invoice", "amount"]),
  mcpTool("finalize_invoice", "Finalize a draft invoice to send it", 
    { invoice: { type: "string", description: "Invoice ID (in_xxx)" } }, ["invoice"]),
  
  // Payments
  mcpTool("create_payment_link", "Create a payment link", 
    { price: { type: "string" }, quantity: { type: "integer" } }, ["price"]),
  mcpTool("list_payment_intents", "List payment intents", 
    { customer: { type: "string" }, limit: { type: "integer" } }),
  mcpTool("create_refund", "Create a refund", 
    { payment_intent: { type: "string" }, amount: { type: "integer" }, reason: { type: "string" } }, ["payment_intent"]),
  
  // Balance
  mcpTool("retrieve_balance", "Get Stripe account balance", {}),
  
  // Subscriptions
  mcpTool("list_subscriptions", "List subscriptions", 
    { customer: { type: "string" }, status: { type: "string" }, limit: { type: "integer" } }),
  mcpTool("update_subscription", "Update a subscription", 
    { subscription: { type: "string" }, cancel_at_period_end: { type: "boolean" } }, ["subscription"]),
  mcpTool("cancel_subscription", "Cancel a subscription", 
    { subscription: { type: "string" } }, ["subscription"]),
  
  // Coupons
  mcpTool("create_coupon", "Create a discount coupon", 
    { percent_off: { type: "number" }, duration: { type: "string" }, name: { type: "string" } }),
  mcpTool("list_coupons", "List coupons", 
    { limit: { type: "integer" } }),
  
  // Disputes
  mcpTool("list_disputes", "List disputes", 
    { limit: { type: "integer" } }),
  mcpTool("update_dispute", "Update a dispute with evidence", 
    { dispute: { type: "string" }, evidence: { type: "object" }, submit: { type: "boolean" } }, ["dispute"]),
  
  // Documentation
  mcpTool("search_stripe_documentation", "Search Stripe docs", 
    { query: { type: "string" } }, ["query"])
];

// Read responses from Stripe MCP stdout
let buffer = '';
stripeMcp.stdout.on('data', (data) => {
  buffer += data.toString();
  
  // Process complete JSON-RPC messages (one per line)
  let newlineIndex;
  while ((newlineIndex = buffer.indexOf('\n')) !== -1) {
    const line = buffer.substring(0, newlineIndex).trim();
    buffer = buffer.substring(newlineIndex + 1);
    
    if (!line) continue;
    
    try {
      const response = JSON.parse(line);
      console.error('Received from Stripe MCP:', JSON.stringify(response).substring(0, 200));
      
      // Find the pending request with this ID
      if (response.id !== undefined && pendingRequests.has(response.id)) {
        const { resolve } = pendingRequests.get(response.id);
        pendingRequests.delete(response.id);
        resolve(response);
      }
    } catch (err) {
      console.error('Failed to parse Stripe MCP response:', line.substring(0, 200), err);
    }
  }
});

// Function to send a JSON-RPC request to Stripe MCP and get the response
async function callStripeMcp(request) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      pendingRequests.delete(request.id);
      reject(new Error('Request timeout'));
    }, 30000); // 30 second timeout
    
    pendingRequests.set(request.id, {
      resolve: (response) => {
        clearTimeout(timeout);
        resolve(response);
      },
      reject
    });
    
    const requestLine = JSON.stringify(request) + '\n';
    console.error('Sending to Stripe MCP:', requestLine.trim().substring(0, 200));
    stripeMcp.stdin.write(requestLine);
  });
}

// HTTP server
const server = http.createServer(async (req, res) => {
  console.error(`Received ${req.method} request to: ${req.url}`);

  // Enable CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Accept, Authorization');

  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    res.end();
    return;
  }

  // Root endpoint
  if (req.url === '/' && req.method === 'GET') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      name: 'Stripe MCP Server',
      version: '1.0.0',
      protocol: 'MCP',
      endpoints: {
        sse: '/sse',
        health: '/health'
      }
    }));
    return;
  }

  // Health check
  if (req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'healthy', server: 'Stripe MCP' }));
    return;
  }

  // Handle POST to /sse - Direct JSON-RPC handling (like QuickBooks)
  if (req.url?.startsWith('/sse') && req.method === 'POST') {
    console.error('Received POST to /sse - direct JSON-RPC handling');
    
    // Check if client wants SSE format
    const acceptHeader = req.headers.accept || '';
    const wantsSSE = acceptHeader.includes('text/event-stream');
    console.error(`Accept header: ${acceptHeader}, wants SSE: ${wantsSSE}`);
    
    // Read request body
    let body = '';
    req.on('data', (chunk) => {
      body += chunk.toString();
    });
    
    req.on('end', async () => {
      try {
        const jsonRpcRequest = JSON.parse(body);
        console.error('JSON-RPC request:', JSON.stringify(jsonRpcRequest, null, 2));
        
        // Check if this is a notification (no id = no response expected)
        const isNotification = jsonRpcRequest.id === undefined || jsonRpcRequest.method?.startsWith('notifications/');
        
        if (isNotification) {
          // For notifications, just forward and don't wait for response
          const requestLine = JSON.stringify(jsonRpcRequest) + '\n';
          console.error('Sending notification to Stripe MCP:', requestLine.trim().substring(0, 200));
          stripeMcp.stdin.write(requestLine);
          
          // Send empty success response
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ jsonrpc: '2.0', result: {} }));
          return;
        }
        
        let response;
        
        // OPTIMIZATION: Return minimal initialize response to reduce token usage
        // Azure Foundry re-initializes MCP for every tool call, which wastes ~2K tokens each time
        if (jsonRpcRequest.method === 'initialize') {
          console.error('Returning MINIMAL initialize response (token optimization)');
          // Use the protocol version from the request if provided
          const protocolVersion = jsonRpcRequest.params?.protocolVersion || '2025-03-26';
          response = {
            jsonrpc: '2.0',
            id: jsonRpcRequest.id,
            result: {
              protocolVersion: protocolVersion,
              capabilities: { tools: { listChanged: false } },
              serverInfo: { name: 'Stripe', version: '1.0.0' }
            }
          };
        }
        
        // Return our MINIMAL_TOOLS instead of the verbose @stripe/mcp tools
        // This reduces token usage from ~21KB to ~4KB (80% reduction!)
        if (jsonRpcRequest.method === 'tools/list' && !response) {
          console.error('Returning MINIMAL tools/list response (token optimization)');
          response = {
            jsonrpc: '2.0',
            id: jsonRpcRequest.id,
            result: { tools: MINIMAL_TOOLS }
          };
        }
        
        // Check if this is a tools/call for a tool we handle directly
        if (jsonRpcRequest.method === 'tools/call' && !response) {
          const toolName = jsonRpcRequest.params?.name;
          const toolArgs = jsonRpcRequest.params?.arguments || {};
          
          // List of tools we handle directly (bypassing @stripe/mcp)
          const directTools = ['list_customers', 'create_invoice', 'create_invoice_item', 'finalize_invoice'];
          
          if (directTools.includes(toolName)) {
            console.error(`Handling ${toolName} directly via Stripe API`);
            try {
              const result = await handleDirectStripeTool(toolName, toolArgs);
              response = {
                jsonrpc: '2.0',
                id: jsonRpcRequest.id,
                result: result
              };
            } catch (err) {
              console.error(`Direct Stripe API error for ${toolName}:`, err.message);
              response = {
                jsonrpc: '2.0',
                id: jsonRpcRequest.id,
                result: {
                  content: [{
                    type: 'text',
                    text: JSON.stringify({ error: err.message })
                  }]
                }
              };
            }
          }
        }
        
        // If not handled directly, forward to Stripe MCP
        if (!response) {
          response = await callStripeMcp(jsonRpcRequest);
        }
        
        console.error('JSON-RPC response:', JSON.stringify(response).substring(0, 200));
        
        // Send response in correct format
        const jsonStr = JSON.stringify(response);
        if (wantsSSE) {
          res.writeHead(200, {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive'
          });
          res.write(`event: message\ndata: ${jsonStr}\n\n`);
          res.end();
        } else {
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(jsonStr);
        }
        
      } catch (err) {
        console.error('Error handling request:', err);
        const errorResponse = {
          jsonrpc: '2.0',
          id: null,
          error: {
            code: -32603,
            message: err.message || 'Internal error'
          }
        };
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(errorResponse));
      }
    });
    return;
  }

  // Unknown endpoint
  res.writeHead(404, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ error: 'Not found' }));
});

server.listen(PORT, () => {
  console.error(`Stripe MCP Server listening on port ${PORT}`);
  console.error(`POST messages: http://localhost:${PORT}/sse`);
});

// Graceful shutdown
process.on('SIGTERM', () => {
  console.error('Received SIGTERM, shutting down...');
  stripeMcp.kill();
  server.close(() => {
    process.exit(0);
  });
});

process.on('SIGINT', () => {
  console.error('Received SIGINT, shutting down...');
  stripeMcp.kill();
  server.close(() => {
    process.exit(0);
  });
});
