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
    case 'create_full_invoice': {
      // BATCHED invoice creation: customer lookup/create + invoice + N line items + finalize
      // Reduces 10+ MCP tool calls to 1 for multi-line invoices
      const results = { steps: [] };

      try {
        // Step 1: Find or create customer
        let customerId;
        if (args.customer_id) {
          customerId = args.customer_id;
          results.steps.push({ step: 'customer', action: 'provided', id: customerId });
        } else {
          // Search by email first
          const email = args.customer_email;
          const name = args.customer_name || '';

          if (email) {
            const searchResult = await callStripeAPI(`customers?email=${encodeURIComponent(email)}&limit=1`, 'GET', {});
            if (searchResult.data && searchResult.data.length > 0) {
              customerId = searchResult.data[0].id;
              results.steps.push({ step: 'customer', action: 'found', id: customerId, email });
            }
          }

          if (!customerId) {
            const customerData = {};
            if (email) customerData.email = email;
            if (name) customerData.name = name;
            const customer = await callStripeAPI('customers', 'POST', customerData);
            customerId = customer.id;
            results.steps.push({ step: 'customer', action: 'created', id: customerId, email, name });
          }
        }

        // Step 2: Create draft invoice
        const invoiceData = {
          customer: customerId,
          auto_advance: false,
          currency: args.currency || 'usd'
        };
        if (args.description) invoiceData.description = args.description;
        if (args.days_until_due) {
          invoiceData.collection_method = 'send_invoice';
          invoiceData.days_until_due = args.days_until_due;
        }

        const invoice = await callStripeAPI('invoices', 'POST', invoiceData);
        results.invoice_id = invoice.id;
        results.steps.push({ step: 'invoice', action: 'created', id: invoice.id });

        // Step 3: Add all line items
        const lineItems = args.line_items || [];
        let totalAmount = 0;
        for (let i = 0; i < lineItems.length; i++) {
          const item = lineItems[i];
          const itemData = {
            invoice: invoice.id,
            customer: customerId,
            amount: item.amount,
            description: item.description || `Line item ${i + 1}`
          };
          const invoiceItem = await callStripeAPI('invoiceitems', 'POST', itemData);
          totalAmount += item.amount;
          results.steps.push({ step: 'line_item', index: i + 1, id: invoiceItem.id, amount: item.amount, description: item.description });
        }

        // Step 4: Finalize if requested (default: true)
        const shouldFinalize = args.finalize !== false;
        if (shouldFinalize) {
          const finalized = await callStripeAPI(`invoices/${invoice.id}/finalize`, 'POST', {});
          results.status = finalized.status;
          results.hosted_invoice_url = finalized.hosted_invoice_url;
          results.steps.push({ step: 'finalize', status: finalized.status, url: finalized.hosted_invoice_url });
        } else {
          results.status = 'draft';
        }

        results.total_amount_cents = totalAmount;
        results.total_amount_dollars = (totalAmount / 100).toFixed(2);
        results.line_item_count = lineItems.length;
        results.customer_id = customerId;

        console.error(`create_full_invoice completed: ${invoice.id}, ${lineItems.length} items, $${results.total_amount_dollars}`);

        return {
          content: [{
            type: 'text',
            text: JSON.stringify(results)
          }]
        };
      } catch (err) {
        console.error(`create_full_invoice error at step: ${results.steps.length}`, err.message);
        results.error = err.message;
        return {
          content: [{
            type: 'text',
            text: JSON.stringify(results)
          }]
        };
      }
    }

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
// Response Summarizer — reduce @stripe/mcp token bloat
// ========================================

/**
 * Summarize a Stripe API object to essential fields only.
 * Full Stripe objects can be 3-8KB each. This reduces to ~200-400 bytes.
 */
function summarizeStripeObject(obj) {
  if (!obj || !obj.object) return obj;
  
  switch (obj.object) {
    case 'invoice':
      return {
        id: obj.id,
        object: 'invoice',
        status: obj.status,
        number: obj.number,
        customer: obj.customer,
        customer_name: obj.customer_name,
        customer_email: obj.customer_email,
        currency: obj.currency,
        amount_due: obj.amount_due,
        amount_paid: obj.amount_paid,
        amount_remaining: obj.amount_remaining,
        total: obj.total,
        subtotal: obj.subtotal,
        description: obj.description,
        due_date: obj.due_date,
        created: obj.created,
        hosted_invoice_url: obj.hosted_invoice_url,
        line_item_count: obj.lines?.data?.length || obj.lines?.total_count || 0,
        line_items: obj.lines?.data?.map(li => ({
          id: li.id,
          amount: li.amount,
          description: li.description,
          quantity: li.quantity,
        })) || [],
      };
    
    case 'customer':
      return {
        id: obj.id,
        object: 'customer',
        name: obj.name,
        email: obj.email,
        phone: obj.phone,
        created: obj.created,
        balance: obj.balance,
        currency: obj.currency,
        default_source: obj.default_source,
      };
    
    case 'payment_intent':
      return {
        id: obj.id,
        object: 'payment_intent',
        status: obj.status,
        amount: obj.amount,
        amount_received: obj.amount_received,
        currency: obj.currency,
        customer: obj.customer,
        description: obj.description,
        created: obj.created,
        payment_method: obj.payment_method,
      };
    
    case 'subscription':
      return {
        id: obj.id,
        object: 'subscription',
        status: obj.status,
        customer: obj.customer,
        current_period_start: obj.current_period_start,
        current_period_end: obj.current_period_end,
        cancel_at_period_end: obj.cancel_at_period_end,
        created: obj.created,
        items: obj.items?.data?.map(si => ({
          id: si.id,
          price_id: si.price?.id,
          quantity: si.quantity,
          amount: si.price?.unit_amount,
        })) || [],
      };
    
    case 'dispute':
      return {
        id: obj.id,
        object: 'dispute',
        status: obj.status,
        amount: obj.amount,
        currency: obj.currency,
        reason: obj.reason,
        charge: obj.charge,
        payment_intent: obj.payment_intent,
        created: obj.created,
      };
    
    case 'charge':
      return {
        id: obj.id,
        object: 'charge',
        status: obj.status,
        amount: obj.amount,
        currency: obj.currency,
        customer: obj.customer,
        description: obj.description,
        created: obj.created,
        refunded: obj.refunded,
        paid: obj.paid,
      };
    
    case 'refund':
      return {
        id: obj.id,
        object: 'refund',
        status: obj.status,
        amount: obj.amount,
        currency: obj.currency,
        charge: obj.charge,
        payment_intent: obj.payment_intent,
        created: obj.created,
        reason: obj.reason,
      };
    
    case 'balance':
      return {
        object: 'balance',
        available: obj.available?.map(b => ({ amount: b.amount, currency: b.currency })) || [],
        pending: obj.pending?.map(b => ({ amount: b.amount, currency: b.currency })) || [],
      };
    
    default:
      // Unknown object type — return id + top-level scalar fields only
      const slim = { id: obj.id, object: obj.object };
      for (const [key, value] of Object.entries(obj)) {
        if (typeof value !== 'object' && typeof value !== 'function') {
          slim[key] = value;
        }
      }
      return slim;
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

// MINIMAL tool definitions — trimmed to ~12 high-value tools
// Removed: create_product, list_products, create_price, list_prices (not needed for invoices)
// Removed: create_invoice, create_invoice_item, finalize_invoice (superseded by create_full_invoice)
// Removed: create_payment_link (needs products/prices which we removed)
// Removed: create_coupon, list_coupons (niche)
// Removed: search_stripe_documentation (wastes a tool call)
// The full @stripe/mcp tools are still available via passthrough for other clients.
const MINIMAL_TOOLS = [
  // Customer management
  mcpTool("create_customer", "Create a customer", 
    { name: { type: "string" }, email: { type: "string" } }, ["name"]),
  mcpTool("list_customers", "List customers", 
    { email: { type: "string" }, limit: { type: "integer" } }),
  
  // Invoices — BATCHED (primary tool for all invoice creation)
  mcpTool("create_full_invoice", "Create a complete invoice in one call: finds/creates customer, creates invoice, adds ALL line items, and finalizes. Use this instead of individual invoice tools.",
    {
      customer_email: { type: "string", description: "Customer email to find or create" },
      customer_name: { type: "string", description: "Customer name (for creation)" },
      customer_id: { type: "string", description: "Customer ID if already known (skips lookup)" },
      line_items: { type: "array", description: "Array of line items", items: { type: "object", properties: { amount: { type: "integer", description: "Amount in cents (e.g. 32000 = $320.00)" }, description: { type: "string" } }, required: ["amount", "description"] } },
      description: { type: "string", description: "Invoice description" },
      currency: { type: "string", description: "Currency code (default: usd)" },
      days_until_due: { type: "integer", description: "Days until due (enables send_invoice)" },
      finalize: { type: "boolean", description: "Finalize invoice (default: true)" }
    }, ["line_items"]),
  // Invoice queries
  mcpTool("list_invoices", "List invoices",
    { customer: { type: "string" }, status: { type: "string" }, limit: { type: "integer" } }),
  
  // Payments
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
  
  // Disputes
  mcpTool("list_disputes", "List disputes", 
    { limit: { type: "integer" } }),
  mcpTool("update_dispute", "Update a dispute with evidence", 
    { dispute: { type: "string" }, evidence: { type: "object" }, submit: { type: "boolean" } }, ["dispute"]),
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
          
          // SECURITY: Block tools not in MINIMAL_TOOLS list
          const allowedToolNames = MINIMAL_TOOLS.map(t => t.name);
          if (!allowedToolNames.includes(toolName)) {
            console.error(`🚫 BLOCKED tool call: ${toolName} (not in MINIMAL_TOOLS)`);
            response = {
              jsonrpc: '2.0',
              id: jsonRpcRequest.id,
              result: {
                content: [{
                  type: 'text',
                  text: JSON.stringify({ error: `Tool '${toolName}' is not available. Available tools: ${allowedToolNames.join(', ')}` })
                }],
                isError: true
              }
            };
          }
          
          // List of tools we handle directly (bypassing @stripe/mcp)
          const directTools = ['create_full_invoice', 'list_customers', 'create_invoice', 'create_invoice_item', 'finalize_invoice'];
          
          if (!response && directTools.includes(toolName)) {
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
          
          // SUMMARIZE @stripe/mcp responses to reduce token usage
          // The SDK returns full Stripe objects (25KB+ for list_invoices with 3 items!)
          // We strip them to essential fields only.
          if (jsonRpcRequest.method === 'tools/call' && response?.result?.content) {
            const toolName = jsonRpcRequest.params?.name;
            try {
              const content = response.result.content;
              if (content.length > 0 && content[0].type === 'text') {
                const rawText = content[0].text;
                const rawSize = rawText.length;
                
                // Only summarize if response is large (>2KB)
                if (rawSize > 2000) {
                  const parsed = JSON.parse(rawText);
                  let summarized = null;
                  
                  // Handle different response shapes from @stripe/mcp:
                  // 1. {object: "list", data: [{...}, ...]} — standard Stripe list
                  // 2. [{...}, {...}] — raw array (some @stripe/mcp tools)
                  // 3. {object: "invoice", ...} — single object
                  if (Array.isArray(parsed)) {
                    summarized = parsed.map(item => summarizeStripeObject(item));
                  } else if (Array.isArray(parsed.data)) {
                    summarized = parsed.data.map(item => summarizeStripeObject(item));
                  } else if (parsed.object) {
                    summarized = summarizeStripeObject(parsed);
                  }
                  
                  if (summarized) {
                    const wrappedResult = Array.isArray(summarized)
                      ? { results: summarized, count: summarized.length, has_more: parsed.has_more ?? parsed?.data?.has_more ?? false }
                      : summarized;
                    const summarizedText = JSON.stringify(wrappedResult);
                    content[0].text = summarizedText;
                    const reduction = Math.round((1 - summarizedText.length / rawSize) * 100);
                    console.error(`📉 SUMMARIZED ${toolName}: ${rawSize} → ${summarizedText.length} bytes (${reduction}% reduction)`);
                  }
                }
              }
            } catch (e) {
              // If summarization fails, send original response — never break the flow
              console.error(`Summarization failed for ${toolName}, sending raw response:`, e.message);
            }
          }
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
