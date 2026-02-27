#!/usr/bin/env node

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { randomUUID } from "crypto";
import * as dotenv from "dotenv";
import http from "http";
import { quickbooksClient } from "./clients/quickbooks-client.js";

// Customer tools
import {
  SearchCustomersTool,
  GetCustomerTool,
  CreateCustomerTool,
  UpdateCustomerTool,
  DeleteCustomerTool,
} from "./tools/customer.tools.js";

// Invoice tools
import {
  SearchInvoicesTool,
  GetInvoiceTool,
  CreateInvoiceTool,
  UpdateInvoiceTool,
  DeleteInvoiceTool,
} from "./tools/invoice.tools.js";

// Account tools
import {
  SearchAccountsTool,
  GetAccountTool,
  CreateAccountTool,
  UpdateAccountTool,
} from "./tools/account.tools.js";

// Item tools
import {
  SearchItemsTool,
  GetItemTool,
  CreateItemTool,
  UpdateItemTool,
} from "./tools/item.tools.js";

// Vendor tools
import {
  SearchVendorsTool,
  GetVendorTool,
  CreateVendorTool,
  UpdateVendorTool,
  DeleteVendorTool,
} from "./tools/vendor.tools.js";

// Bill tools
import {
  SearchBillsTool,
  GetBillTool,
  CreateBillTool,
  UpdateBillTool,
  DeleteBillTool,
} from "./tools/bill.tools.js";

// Employee tools
import {
  SearchEmployeesTool,
  GetEmployeeTool,
  CreateEmployeeTool,
  UpdateEmployeeTool,
} from "./tools/employee.tools.js";

// Estimate tools
import {
  SearchEstimatesTool,
  GetEstimateTool,
  CreateEstimateTool,
  UpdateEstimateTool,
  DeleteEstimateTool,
} from "./tools/estimate.tools.js";

// Purchase tools
import {
  SearchPurchasesTool,
  GetPurchaseTool,
  CreatePurchaseTool,
  UpdatePurchaseTool,
  DeletePurchaseTool,
} from "./tools/purchase.tools.js";

// Journal Entry tools
import {
  SearchJournalEntriesTool,
  GetJournalEntryTool,
  CreateJournalEntryTool,
  UpdateJournalEntryTool,
  DeleteJournalEntryTool,
} from "./tools/journal-entry.tools.js";

// Bill Payment tools
import {
  SearchBillPaymentsTool,
  GetBillPaymentTool,
  CreateBillPaymentTool,
  UpdateBillPaymentTool,
  DeleteBillPaymentTool,
} from "./tools/bill-payment.tools.js";

// Query and Report tools
import {
  QueryTool,
  CompanyInfoTool,
  ReportTool,
} from "./tools/query.tools.js";

// Import summarizers for response optimization
import {
  summarizeInvoice,
  summarizeInvoiceDetail,
  summarizeCustomer,
  summarizeCustomerDetail,
  summarizeVendor,
  summarizeVendorDetail,
  summarizeBill,
  summarizeBillDetail,
  summarizeItem,
  summarizeItemDetail,
  summarizeAccount,
  summarizeAccountDetail,
  summarizeEmployee,
  summarizeEstimate,
  summarizePurchase,
  summarizeJournalEntry,
  summarizeBillPayment,
  summarizeConfirmation,
} from "./utils/summarizers.js";

import { registerTool } from "./helpers/register-tool.js";

// Load environment variables
dotenv.config();

// Create the MCP server
const server = new McpServer({
  name: "QuickBooks Online MCP Server",
  version: "1.0.0",
});

// Register essential tools only (20 tools instead of 55)
// This reduces token overhead from ~10K to ~3K tokens
function registerAllTools() {
  // === INVOICES (AR) - Core workflow ===
  registerTool(server, SearchInvoicesTool);
  registerTool(server, GetInvoiceTool);
  registerTool(server, CreateInvoiceTool);

  // === CUSTOMERS - Required for invoices ===
  registerTool(server, SearchCustomersTool);
  registerTool(server, GetCustomerTool);
  registerTool(server, CreateCustomerTool);

  // === ITEMS - Products/services for line items ===
  registerTool(server, SearchItemsTool);
  registerTool(server, GetItemTool);

  // === BILLS (AP) - Core workflow ===
  registerTool(server, SearchBillsTool);
  registerTool(server, GetBillTool);
  registerTool(server, CreateBillTool);

  // === VENDORS - Required for bills ===
  registerTool(server, SearchVendorsTool);
  registerTool(server, GetVendorTool);
  registerTool(server, CreateVendorTool);

  // === BILL PAYMENTS - Pay vendors ===
  registerTool(server, SearchBillPaymentsTool);
  registerTool(server, GetBillPaymentTool);
  registerTool(server, CreateBillPaymentTool);

  // === ACCOUNTS - Chart of accounts lookup ===
  registerTool(server, SearchAccountsTool);
  registerTool(server, GetAccountTool);

  // === REPORTS & QUERIES - Flexible access ===
  registerTool(server, QueryTool);        // Generic query for anything
  registerTool(server, CompanyInfoTool);  // Company details
  registerTool(server, ReportTool);       // Financial reports

  // === DISABLED TOOLS (uncomment if needed) ===
  // Update/Delete tools - enable for full CRUD:
  // registerTool(server, UpdateInvoiceTool);
  // registerTool(server, DeleteInvoiceTool);
  // registerTool(server, UpdateCustomerTool);
  // registerTool(server, DeleteCustomerTool);
  // registerTool(server, UpdateBillTool);
  // registerTool(server, DeleteBillTool);
  // registerTool(server, UpdateVendorTool);
  // registerTool(server, DeleteVendorTool);
  // registerTool(server, CreateItemTool);
  // registerTool(server, UpdateItemTool);
  // registerTool(server, CreateAccountTool);
  // registerTool(server, UpdateAccountTool);
  // registerTool(server, UpdateBillPaymentTool);
  // registerTool(server, DeleteBillPaymentTool);
  
  // Employee tools:
  // registerTool(server, SearchEmployeesTool);
  // registerTool(server, GetEmployeeTool);
  // registerTool(server, CreateEmployeeTool);
  // registerTool(server, UpdateEmployeeTool);

  // Estimate tools:
  // registerTool(server, SearchEstimatesTool);
  // registerTool(server, GetEstimateTool);
  // registerTool(server, CreateEstimateTool);
  // registerTool(server, UpdateEstimateTool);
  // registerTool(server, DeleteEstimateTool);

  // Purchase tools:
  // registerTool(server, SearchPurchasesTool);
  // registerTool(server, GetPurchaseTool);
  // registerTool(server, CreatePurchaseTool);
  // registerTool(server, UpdatePurchaseTool);
  // registerTool(server, DeletePurchaseTool);

  // Journal Entry tools:
  // registerTool(server, SearchJournalEntriesTool);
  // registerTool(server, GetJournalEntryTool);
  // registerTool(server, CreateJournalEntryTool);
  // registerTool(server, UpdateJournalEntryTool);
  // registerTool(server, DeleteJournalEntryTool);
}

// OAuth callback handler - will be set by quickbooks-client
let oauthCallbackResolver: ((url: string) => void) | null = null;

export function setOAuthCallbackResolver(resolver: (url: string) => void) {
  oauthCallbackResolver = resolver;
}

async function runServer() {
  // Register all tools
  registerAllTools();

  const transportMode = process.env.TRANSPORT_MODE || "stdio";

  if (transportMode === "http") {
    // HTTP/SSE mode for ngrok and remote testing
    const PORT = parseInt(process.env.PORT || "3000");

    // Store active SSE transports by session ID (legacy pattern)
    const sseTransports = new Map<string, SSEServerTransport>();
    
    // Store active StreamableHTTP transports by session ID (Azure AI Foundry pattern)
    const streamableTransports = new Map<string, StreamableHTTPServerTransport>();

    const httpServer = http.createServer(async (req, res) => {
      console.error(`Received ${req.method} request to: ${req.url}`);

      // Enable CORS for all requests
      res.setHeader("Access-Control-Allow-Origin", "*");
      res.setHeader("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS");
      res.setHeader("Access-Control-Allow-Headers", "Content-Type, Accept, Authorization, Mcp-Session-Id");
      res.setHeader("Access-Control-Expose-Headers", "Mcp-Session-Id");

      if (req.method === "OPTIONS") {
        res.writeHead(200);
        res.end();
        return;
      }

      // Root endpoint - return server info
      if (req.url === "/" && req.method === "GET") {
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({
          name: "QuickBooks MCP Server",
          version: "1.0.0",
          protocol: "MCP",
          endpoints: {
            mcp: "/mcp",
            sse: "/sse",
            message: "/message",
            health: "/health"
          }
        }));
        return;
      }

      if (req.url === "/health") {
        // Health check endpoint
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ status: "healthy", server: "QuickBooks MCP" }));
        return;
      }

      // OAuth start endpoint - initiates QuickBooks OAuth flow
      if (req.url === "/oauth/start") {
        try {
          console.error("Starting OAuth flow...");
          const authUri = quickbooksClient["oauthClient"].authorizeUri({
            scope: [
              "com.intuit.quickbooks.accounting",
              "com.intuit.quickbooks.payment"
            ],
            state: "oauth-state-" + Date.now()
          });

          res.writeHead(302, { "Location": authUri });
          res.end();
        } catch (error: any) {
          console.error("Error starting OAuth:", error);
          res.writeHead(500, { "Content-Type": "text/html" });
          res.end(`
            <html>
              <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h2 style="color: #d32f2f;">Error starting OAuth flow</h2>
                <p>${error.message}</p>
              </body>
            </html>
          `);
        }
        return;
      }

      // OAuth callback endpoint
      if (req.url?.startsWith("/oauth/callback")) {
        console.error("Received OAuth callback");
        
        if (oauthCallbackResolver) {
          // Pass the full URL to the resolver
          const fullUrl = `http://localhost:${PORT}${req.url}`;
          oauthCallbackResolver(fullUrl);
          
          res.writeHead(200, { "Content-Type": "text/html" });
          res.end(`
            <html>
              <body style="
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                font-family: Arial, sans-serif;
                background-color: #f5f5f5;
              ">
                <h2 style="color: #2E8B57;">✓ Successfully connected to QuickBooks!</h2>
                <p>You can close this window and return to the terminal.</p>
              </body>
            </html>
          `);
        } else {
          res.writeHead(400, { "Content-Type": "text/html" });
          res.end(`
            <html>
              <body style="
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                font-family: Arial, sans-serif;
                background-color: #fff0f0;
              ">
                <h2 style="color: #d32f2f;">No OAuth flow in progress</h2>
                <p>Please try authenticating again.</p>
              </body>
            </html>
          `);
        }
        return;
      }

      // Streamable HTTP endpoint - Azure AI Foundry pattern
      // Handles POST /mcp for direct JSON-RPC requests
      if (req.url?.startsWith("/mcp") && (req.method === "POST" || req.method === "GET" || req.method === "DELETE")) {
        console.error(`Streamable HTTP request: ${req.method} /mcp`);
        
        // Get or create transport based on session ID header
        const sessionId = req.headers["mcp-session-id"] as string | undefined;
        
        let transport = sessionId ? streamableTransports.get(sessionId) : undefined;
        
        if (!transport && req.method === "POST") {
          // Create new transport for this session
          transport = new StreamableHTTPServerTransport({
            sessionIdGenerator: () => randomUUID(),
            onsessioninitialized: (newSessionId) => {
              console.error(`New Streamable HTTP session: ${newSessionId}`);
              streamableTransports.set(newSessionId, transport!);
            }
          });
          
          // Connect to server (this also starts the transport)
          await server.connect(transport);
        }
        
        if (transport) {
          try {
            await transport.handleRequest(req, res);
          } catch (error) {
            console.error("Error handling Streamable HTTP request:", error);
            if (!res.headersSent) {
              res.writeHead(500, { "Content-Type": "application/json" });
              res.end(JSON.stringify({ error: "Internal server error" }));
            }
          }
        } else {
          res.writeHead(400, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: "Session not found. Send initialize request first." }));
        }
        return;
      }

      // Handle POST to /sse - Direct JSON-RPC handling for Azure AI Foundry compatibility
      if (req.url?.startsWith("/sse") && req.method === "POST") {
        console.error("Received POST to /sse - direct JSON-RPC handling");
        
        // Check if client wants SSE format
        const acceptHeader = req.headers.accept || "";
        const wantsSSE = acceptHeader.includes("text/event-stream");
        console.error(`Accept header: ${acceptHeader}, wants SSE: ${wantsSSE}`);
        
        // Helper to send response in correct format (SSE or JSON)
        const sendResponse = (responseObj: any) => {
          const jsonStr = JSON.stringify(responseObj);
          if (wantsSSE) {
            res.writeHead(200, { 
              "Content-Type": "text/event-stream",
              "Cache-Control": "no-cache",
              "Connection": "keep-alive"
            });
            // Include event: message before data: for proper SSE format
            res.write(`event: message\ndata: ${jsonStr}\n\n`);
            res.end();
          } else {
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(jsonStr);
          }
        };
        
        // Read the request body
        let body = "";
        req.on("data", (chunk) => {
          body += chunk.toString();
        });
        
        req.on("end", async () => {
          try {
            const jsonRpcRequest = JSON.parse(body);
            console.error("JSON-RPC request:", JSON.stringify(jsonRpcRequest, null, 2));
            
            // Handle initialize request
            if (jsonRpcRequest.method === "initialize") {
              // Negotiate protocol version - use client's version if we support it
              const clientVersion = jsonRpcRequest.params?.protocolVersion || "2024-11-05";
              const supportedVersions = ["2025-03-26", "2025-11-25", "2024-11-05"];
              const negotiatedVersion = supportedVersions.includes(clientVersion) 
                ? clientVersion 
                : "2025-03-26"; // Default to latest
              
              console.error(`Client requested protocol version: ${clientVersion}, responding with: ${negotiatedVersion}`);
              
              const response = {
                jsonrpc: "2.0",
                id: jsonRpcRequest.id,
                result: {
                  protocolVersion: negotiatedVersion,
                  capabilities: {
                    tools: {}
                  },
                  serverInfo: {
                    name: "QuickBooks MCP Server",
                    version: "1.0.0"
                  }
                }
              };
              sendResponse(response);
              return;
            }
            
            // Handle tools/list request
            if (jsonRpcRequest.method === "tools/list") {
              // REDUCED TOOL SET: Only 22 essential tools to minimize token usage
              const tools = [
                // Customer tools (3)
                { 
                  name: "qbo_search_customers", 
                  description: "Search customers in QuickBooks Online",
                  inputSchema: {
                    type: "object",
                    properties: {
                      displayName: { type: "string", description: "Filter by customer display name" },
                      active: { type: "boolean", description: "Filter by active status" },
                      limit: { type: "number", description: "Max results (default 100)" }
                    }
                  }
                },
                { 
                  name: "qbo_get_customer", 
                  description: "Get a customer by ID",
                  inputSchema: {
                    type: "object",
                    properties: {
                      customerId: { type: "string", description: "Customer ID" }
                    },
                    required: ["customerId"]
                  }
                },
                { 
                  name: "qbo_create_customer", 
                  description: "Create a new customer",
                  inputSchema: {
                    type: "object",
                    properties: {
                      displayName: { type: "string", description: "Customer name (required, unique)" },
                      email: { type: "string", description: "Email address" },
                      phone: { type: "string", description: "Phone number" },
                      companyName: { type: "string", description: "Company name" }
                    },
                    required: ["displayName"]
                  }
                },
                
                // Invoice tools
                { 
                  name: "qbo_search_invoices", 
                  description: "Search invoices in QuickBooks Online",
                  inputSchema: {
                    type: "object",
                    properties: {
                      customerId: { type: "string", description: "Filter by customer ID" },
                      docNumber: { type: "string", description: "Filter by invoice number" },
                      limit: { type: "number", description: "Maximum number of results" }
                    },
                    required: []
                  }
                },
                { 
                  name: "qbo_get_invoice", 
                  description: "Get a single invoice by ID",
                  inputSchema: {
                    type: "object",
                    properties: {
                      invoiceId: { type: "string", description: "The QuickBooks invoice ID" }
                    },
                    required: ["invoiceId"]
                  }
                },
                { 
                  name: "qbo_create_invoice", 
                  description: "Create a new invoice in QuickBooks Online",
                  inputSchema: {
                    type: "object",
                    properties: {
                      customerId: { type: "string", description: "Customer ID for the invoice (required)" },
                      lineItems: { type: "string", description: "JSON string of line items array, e.g., [{\"Description\": \"Service\", \"Amount\": 100}]" },
                      dueDate: { type: "string", description: "Due date in YYYY-MM-DD format" }
                    },
                    required: ["customerId"]
                  }
                },
                
                // Account tools
                { 
                  name: "qbo_search_accounts", 
                  description: "Search chart of accounts in QuickBooks Online",
                  inputSchema: {
                    type: "object",
                    properties: {
                      name: { type: "string", description: "Filter by account name" },
                      accountType: { type: "string", description: "Filter by type: Bank, Expense, Income, etc." },
                      limit: { type: "number", description: "Maximum results" }
                    },
                    required: []
                  }
                },
                
                // Item tools
                { 
                  name: "qbo_search_items", 
                  description: "Search products/services in QuickBooks Online",
                  inputSchema: {
                    type: "object",
                    properties: {
                      name: { type: "string", description: "Filter by item name" },
                      type: { type: "string", description: "Filter by type: Service, Inventory, NonInventory" },
                      limit: { type: "number", description: "Maximum results" }
                    },
                    required: []
                  }
                },
                
                // Vendor tools
                { 
                  name: "qbo_search_vendors", 
                  description: "Search vendors/suppliers in QuickBooks Online",
                  inputSchema: {
                    type: "object",
                    properties: {
                      displayName: { type: "string", description: "Filter by vendor name" },
                      active: { type: "boolean", description: "Filter by active status" },
                      limit: { type: "number", description: "Maximum results" }
                    },
                    required: []
                  }
                },
                
                // Bill tools
                { 
                  name: "qbo_search_bills", 
                  description: "Search bills/payables in QuickBooks Online",
                  inputSchema: {
                    type: "object",
                    properties: {
                      vendorId: { type: "string", description: "Filter by vendor ID" },
                      docNumber: { type: "string", description: "Filter by bill number" },
                      limit: { type: "number", description: "Maximum results" }
                    },
                    required: []
                  }
                },
                
                // Query tool
                { 
                  name: "qbo_query", 
                  description: "Run a SQL-like query against QuickBooks. Example: SELECT * FROM Customer WHERE Active = true",
                  inputSchema: {
                    type: "object",
                    properties: {
                      query: { type: "string", description: "SQL-like query string" }
                    },
                    required: ["query"]
                  }
                },
                
                // Company info tool
                { 
                  name: "qbo_company_info", 
                  description: "Get company information and settings from QuickBooks Online",
                  inputSchema: {
                    type: "object",
                    properties: {},
                    required: []
                  }
                },
                
                // Report tool
                { 
                  name: "qbo_report", 
                  description: "Run a financial report in QuickBooks Online",
                  inputSchema: {
                    type: "object",
                    properties: {
                      reportType: { type: "string", description: "Report type: ProfitAndLoss, BalanceSheet, CashFlow, CustomerSales, etc." },
                      startDate: { type: "string", description: "Start date (YYYY-MM-DD)" },
                      endDate: { type: "string", description: "End date (YYYY-MM-DD)" }
                    },
                    required: ["reportType"]
                  }
                },
                
                // Additional Invoice tools
                { 
                  name: "qbo_update_invoice", 
                  description: "Update an existing invoice",
                  inputSchema: {
                    type: "object",
                    properties: {
                      invoiceId: { type: "string", description: "Invoice ID to update" },
                      dueDate: { type: "string", description: "New due date (YYYY-MM-DD)" },
                      privateNote: { type: "string", description: "Private note/memo" }
                    },
                    required: ["invoiceId"]
                  }
                },
                { 
                  name: "qbo_delete_invoice", 
                  description: "Delete/void an invoice",
                  inputSchema: {
                    type: "object",
                    properties: {
                      invoiceId: { type: "string", description: "Invoice ID to delete" }
                    },
                    required: ["invoiceId"]
                  }
                },
                
                // Account CRUD tools
                { 
                  name: "qbo_get_account", 
                  description: "Get an account by ID",
                  inputSchema: {
                    type: "object",
                    properties: {
                      accountId: { type: "string", description: "Account ID" }
                    },
                    required: ["accountId"]
                  }
                },
                { 
                  name: "qbo_create_account", 
                  description: "Create a new account in the chart of accounts",
                  inputSchema: {
                    type: "object",
                    properties: {
                      name: { type: "string", description: "Account name (required)" },
                      accountType: { type: "string", description: "Account type: Bank, Expense, Income, Other Current Asset, etc." },
                      accountSubType: { type: "string", description: "Account sub-type" }
                    },
                    required: ["name", "accountType"]
                  }
                },
                
                // Item CRUD tools
                { 
                  name: "qbo_get_item", 
                  description: "Get an item/product by ID",
                  inputSchema: {
                    type: "object",
                    properties: {
                      itemId: { type: "string", description: "Item ID" }
                    },
                    required: ["itemId"]
                  }
                },
                { 
                  name: "qbo_create_item", 
                  description: "Create a new product or service",
                  inputSchema: {
                    type: "object",
                    properties: {
                      name: { type: "string", description: "Item name (required)" },
                      type: { type: "string", description: "Type: Service, Inventory, NonInventory" },
                      unitPrice: { type: "number", description: "Unit price" },
                      description: { type: "string", description: "Item description" }
                    },
                    required: ["name"]
                  }
                },
                
                // Vendor CRUD tools
                { 
                  name: "qbo_get_vendor", 
                  description: "Get a vendor by ID",
                  inputSchema: {
                    type: "object",
                    properties: {
                      vendorId: { type: "string", description: "Vendor ID" }
                    },
                    required: ["vendorId"]
                  }
                },
                { 
                  name: "qbo_create_vendor", 
                  description: "Create a new vendor/supplier",
                  inputSchema: {
                    type: "object",
                    properties: {
                      displayName: { type: "string", description: "Vendor display name (required)" },
                      email: { type: "string", description: "Vendor email" },
                      phone: { type: "string", description: "Vendor phone" },
                      companyName: { type: "string", description: "Company name" }
                    },
                    required: ["displayName"]
                  }
                },
                { 
                  name: "qbo_update_vendor", 
                  description: "Update an existing vendor",
                  inputSchema: {
                    type: "object",
                    properties: {
                      vendorId: { type: "string", description: "Vendor ID to update" },
                      displayName: { type: "string", description: "New display name" },
                      email: { type: "string", description: "New email" },
                      phone: { type: "string", description: "New phone" }
                    },
                    required: ["vendorId"]
                  }
                },
                { 
                  name: "qbo_delete_vendor", 
                  description: "Deactivate a vendor",
                  inputSchema: {
                    type: "object",
                    properties: {
                      vendorId: { type: "string", description: "Vendor ID to delete" }
                    },
                    required: ["vendorId"]
                  }
                },
                
                // Bill CRUD tools
                { 
                  name: "qbo_get_bill", 
                  description: "Get a bill by ID",
                  inputSchema: {
                    type: "object",
                    properties: {
                      billId: { type: "string", description: "Bill ID" }
                    },
                    required: ["billId"]
                  }
                },
                { 
                  name: "qbo_create_bill", 
                  description: "Create a new bill/payable",
                  inputSchema: {
                    type: "object",
                    properties: {
                      vendorId: { type: "string", description: "Vendor ID (required)" },
                      lineItems: { type: "string", description: "JSON array of line items" },
                      dueDate: { type: "string", description: "Due date (YYYY-MM-DD)" }
                    },
                    required: ["vendorId"]
                  }
                },
                { 
                  name: "qbo_delete_bill", 
                  description: "Delete a bill",
                  inputSchema: {
                    type: "object",
                    properties: {
                      billId: { type: "string", description: "Bill ID to delete" }
                    },
                    required: ["billId"]
                  }
                },
                
                // Employee tools
                { 
                  name: "qbo_search_employees", 
                  description: "Search employees",
                  inputSchema: {
                    type: "object",
                    properties: {
                      displayName: { type: "string", description: "Filter by name" },
                      active: { type: "boolean", description: "Filter by active status" },
                      limit: { type: "number", description: "Maximum results" }
                    },
                    required: []
                  }
                },
                { 
                  name: "qbo_get_employee", 
                  description: "Get an employee by ID",
                  inputSchema: {
                    type: "object",
                    properties: {
                      employeeId: { type: "string", description: "Employee ID" }
                    },
                    required: ["employeeId"]
                  }
                },
                { 
                  name: "qbo_create_employee", 
                  description: "Create a new employee",
                  inputSchema: {
                    type: "object",
                    properties: {
                      givenName: { type: "string", description: "First name (required)" },
                      familyName: { type: "string", description: "Last name (required)" },
                      email: { type: "string", description: "Email address" },
                      phone: { type: "string", description: "Phone number" }
                    },
                    required: ["givenName", "familyName"]
                  }
                },
                // Estimate tools
                { 
                  name: "qbo_search_estimates", 
                  description: "Search for estimates",
                  inputSchema: {
                    type: "object",
                    properties: {
                      customerId: { type: "string", description: "Filter by customer ID" },
                      limit: { type: "number", description: "Max results" }
                    }
                  }
                },
                { 
                  name: "qbo_get_estimate", 
                  description: "Get a specific estimate by ID",
                  inputSchema: {
                    type: "object",
                    properties: {
                      estimateId: { type: "string", description: "Estimate ID" }
                    },
                    required: ["estimateId"]
                  }
                },
                { 
                  name: "qbo_create_estimate", 
                  description: "Create a new estimate",
                  inputSchema: {
                    type: "object",
                    properties: {
                      customerId: { type: "string", description: "Customer ID (required)" },
                      lineItems: { type: "string", description: "JSON array of line items" },
                      expirationDate: { type: "string", description: "Expiration date (YYYY-MM-DD)" }
                    },
                    required: ["customerId"]
                  }
                },
                { 
                  name: "qbo_update_estimate", 
                  description: "Update an existing estimate",
                  inputSchema: {
                    type: "object",
                    properties: {
                      estimateId: { type: "string", description: "Estimate ID (required)" },
                      customerId: { type: "string", description: "Customer ID" },
                      lineItems: { type: "string", description: "JSON array of line items" },
                      expirationDate: { type: "string", description: "Expiration date (YYYY-MM-DD)" }
                    },
                    required: ["estimateId"]
                  }
                },
                { 
                  name: "qbo_delete_estimate", 
                  description: "Delete an estimate",
                  inputSchema: {
                    type: "object",
                    properties: {
                      estimateId: { type: "string", description: "Estimate ID" }
                    },
                    required: ["estimateId"]
                  }
                },
                // Purchase tools
                { 
                  name: "qbo_search_purchases", 
                  description: "Search for purchases",
                  inputSchema: {
                    type: "object",
                    properties: {
                      paymentType: { type: "string", description: "Filter by payment type (Cash, Check, CreditCard)" },
                      limit: { type: "number", description: "Max results" }
                    }
                  }
                },
                { 
                  name: "qbo_get_purchase", 
                  description: "Get a specific purchase by ID",
                  inputSchema: {
                    type: "object",
                    properties: {
                      purchaseId: { type: "string", description: "Purchase ID" }
                    },
                    required: ["purchaseId"]
                  }
                },
                { 
                  name: "qbo_create_purchase", 
                  description: "Create a new purchase",
                  inputSchema: {
                    type: "object",
                    properties: {
                      paymentType: { type: "string", description: "Payment type: Cash, Check, CreditCard (required)" },
                      accountId: { type: "string", description: "Account ID for the purchase" },
                      lineItems: { type: "string", description: "JSON array of line items" }
                    },
                    required: ["paymentType"]
                  }
                },
                { 
                  name: "qbo_update_purchase", 
                  description: "Update an existing purchase",
                  inputSchema: {
                    type: "object",
                    properties: {
                      purchaseId: { type: "string", description: "Purchase ID (required)" },
                      paymentType: { type: "string", description: "Payment type: Cash, Check, CreditCard" },
                      accountId: { type: "string", description: "Account ID" },
                      lineItems: { type: "string", description: "JSON array of line items" }
                    },
                    required: ["purchaseId"]
                  }
                },
                { 
                  name: "qbo_delete_purchase", 
                  description: "Delete a purchase",
                  inputSchema: {
                    type: "object",
                    properties: {
                      purchaseId: { type: "string", description: "Purchase ID" }
                    },
                    required: ["purchaseId"]
                  }
                },
                // Journal Entry tools
                { 
                  name: "qbo_search_journal_entries", 
                  description: "Search for journal entries",
                  inputSchema: {
                    type: "object",
                    properties: {
                      limit: { type: "number", description: "Max results" }
                    }
                  }
                },
                { 
                  name: "qbo_get_journal_entry", 
                  description: "Get a specific journal entry by ID",
                  inputSchema: {
                    type: "object",
                    properties: {
                      journalEntryId: { type: "string", description: "Journal entry ID" }
                    },
                    required: ["journalEntryId"]
                  }
                },
                { 
                  name: "qbo_create_journal_entry", 
                  description: "Create a new journal entry",
                  inputSchema: {
                    type: "object",
                    properties: {
                      lineItems: { type: "string", description: "JSON array of line items with AccountRef, Amount, Description, PostingType (Debit/Credit)" },
                      privateNote: { type: "string", description: "Private note" },
                      txnDate: { type: "string", description: "Transaction date (YYYY-MM-DD)" }
                    },
                    required: ["lineItems"]
                  }
                },
                { 
                  name: "qbo_update_journal_entry", 
                  description: "Update an existing journal entry",
                  inputSchema: {
                    type: "object",
                    properties: {
                      journalEntryId: { type: "string", description: "Journal entry ID (required)" },
                      lineItems: { type: "string", description: "JSON array of line items" },
                      privateNote: { type: "string", description: "Private note" },
                      txnDate: { type: "string", description: "Transaction date (YYYY-MM-DD)" }
                    },
                    required: ["journalEntryId"]
                  }
                },
                { 
                  name: "qbo_delete_journal_entry", 
                  description: "Delete a journal entry",
                  inputSchema: {
                    type: "object",
                    properties: {
                      journalEntryId: { type: "string", description: "Journal entry ID" }
                    },
                    required: ["journalEntryId"]
                  }
                },
                // Bill Payment tools
                { 
                  name: "qbo_search_bill_payments", 
                  description: "Search for bill payments",
                  inputSchema: {
                    type: "object",
                    properties: {
                      vendorId: { type: "string", description: "Filter by vendor ID" },
                      limit: { type: "number", description: "Max results" }
                    }
                  }
                },
                { 
                  name: "qbo_get_bill_payment", 
                  description: "Get a specific bill payment by ID",
                  inputSchema: {
                    type: "object",
                    properties: {
                      billPaymentId: { type: "string", description: "Bill payment ID" }
                    },
                    required: ["billPaymentId"]
                  }
                },
                { 
                  name: "qbo_create_bill_payment", 
                  description: "Create a new bill payment",
                  inputSchema: {
                    type: "object",
                    properties: {
                      vendorId: { type: "string", description: "Vendor ID (required)" },
                      payType: { type: "string", description: "Payment type: Check or CreditCard (required)" },
                      totalAmt: { type: "number", description: "Total amount (required)" },
                      checkPayment: { type: "string", description: "JSON object with BankAccountRef for check payments" },
                      lineItems: { type: "string", description: "JSON array of line items linking to bills" }
                    },
                    required: ["vendorId", "payType", "totalAmt"]
                  }
                },
                { 
                  name: "qbo_update_bill_payment", 
                  description: "Update an existing bill payment",
                  inputSchema: {
                    type: "object",
                    properties: {
                      billPaymentId: { type: "string", description: "Bill payment ID (required)" },
                      vendorId: { type: "string", description: "Vendor ID" },
                      payType: { type: "string", description: "Payment type: Check or CreditCard" },
                      totalAmt: { type: "number", description: "Total amount" },
                      checkPayment: { type: "string", description: "JSON object with BankAccountRef" },
                      lineItems: { type: "string", description: "JSON array of line items" }
                    },
                    required: ["billPaymentId"]
                  }
                },
                { 
                  name: "qbo_delete_bill_payment", 
                  description: "Delete a bill payment",
                  inputSchema: {
                    type: "object",
                    properties: {
                      billPaymentId: { type: "string", description: "Bill payment ID" }
                    },
                    required: ["billPaymentId"]
                  }
                },
                // Query and Report tools
                { 
                  name: "qbo_query", 
                  description: "Execute a query (e.g., 'SELECT * FROM Customer')",
                  inputSchema: {
                    type: "object",
                    properties: {
                      query: { type: "string", description: "Query string in QuickBooks query format" }
                    },
                    required: ["query"]
                  }
                },
                { 
                  name: "qbo_company_info", 
                  description: "Get company information",
                  inputSchema: {
                    type: "object",
                    properties: {}
                  }
                },
                { 
                  name: "qbo_report", 
                  description: "Run a financial report (ProfitAndLoss, BalanceSheet, etc.)",
                  inputSchema: {
                    type: "object",
                    properties: {
                      reportType: { type: "string", description: "Report type (ProfitAndLoss, BalanceSheet, CashFlow, etc.)" },
                      startDate: { type: "string", description: "Start date (YYYY-MM-DD)" },
                      endDate: { type: "string", description: "End date (YYYY-MM-DD)" }
                    },
                    required: ["reportType"]
                  }
                }
              ];
              
              // ESSENTIAL TOOL SET: Matches QUICKBOOKS_ALLOWED_TOOLS in agent (16 tools)
              const essentialToolNames = [
                // Reports & Company
                'qbo_report', 'qbo_company_info',
                // Invoices (AR)
                'qbo_search_invoices', 'qbo_get_invoice', 'qbo_create_invoice',
                // Customers
                'qbo_search_customers', 'qbo_get_customer', 'qbo_create_customer',
                // Bills (AP)
                'qbo_search_bills', 'qbo_get_bill', 'qbo_create_bill',
                // Vendors
                'qbo_get_vendor', 'qbo_create_vendor',
                // Bill Payments
                'qbo_search_bill_payments', 'qbo_get_bill_payment',
                // Utility
                'qbo_query',
              ];
              // Deduplicate: take first occurrence of each tool name
              const seen = new Set<string>();
              const filteredTools = tools.filter(t => {
                if (!essentialToolNames.includes(t.name) || seen.has(t.name)) return false;
                seen.add(t.name);
                return true;
              });
              
              const response = {
                jsonrpc: "2.0",
                id: jsonRpcRequest.id,
                result: { tools: filteredTools }
              };
              sendResponse(response);
              return;
            }
            
            // Handle tools/call - route to actual tool handlers
            if (jsonRpcRequest.method === "tools/call") {
              const toolName = jsonRpcRequest.params?.name;
              const toolArgs = jsonRpcRequest.params?.arguments || {};
              
              console.error(`\n${"=".repeat(60)}`);
              console.error(`📞 TOOL CALL: ${toolName}`);
              console.error(`📥 Arguments: ${JSON.stringify(toolArgs)}`);
              console.error(`${"=".repeat(60)}`);
              
              // Import and call the appropriate handler
              try {
                let result;
                
                // Customer handlers
                if (toolName === "qbo_search_customers") {
                  const { searchQuickbooksCustomers } = await import("./handlers/customer.handler.js");
                  // Convert flat params to criteria array format
                  const criteria: any[] = [];
                  if (toolArgs.displayName) criteria.push({ field: "DisplayName", value: toolArgs.displayName, operator: "LIKE" });
                  if (toolArgs.active !== undefined) criteria.push({ field: "Active", value: toolArgs.active });
                  if (toolArgs.limit) criteria.push({ field: "limit", value: toolArgs.limit });
                  result = await searchQuickbooksCustomers(criteria);
                } else if (toolName === "qbo_get_customer") {
                  const { getQuickbooksCustomer } = await import("./handlers/customer.handler.js");
                  result = await getQuickbooksCustomer(toolArgs.customerId);
                } else if (toolName === "qbo_create_customer") {
                  const { createQuickbooksCustomer } = await import("./handlers/customer.handler.js");
                  // Convert flat params to QuickBooks format
                  const customerData: any = { DisplayName: toolArgs.displayName };
                  if (toolArgs.email) customerData.PrimaryEmailAddr = { Address: toolArgs.email };
                  if (toolArgs.phone) customerData.PrimaryPhone = { FreeFormNumber: toolArgs.phone };
                  if (toolArgs.companyName) customerData.CompanyName = toolArgs.companyName;
                  result = await createQuickbooksCustomer(customerData);
                } else if (toolName === "qbo_update_customer") {
                  const { updateQuickbooksCustomer } = await import("./handlers/customer.handler.js");
                  const customerData: any = { Id: toolArgs.customerId };
                  if (toolArgs.displayName) customerData.DisplayName = toolArgs.displayName;
                  if (toolArgs.email) customerData.PrimaryEmailAddr = { Address: toolArgs.email };
                  if (toolArgs.phone) customerData.PrimaryPhone = { FreeFormNumber: toolArgs.phone };
                  result = await updateQuickbooksCustomer(customerData);
                } else if (toolName === "qbo_delete_customer") {
                  const { deleteQuickbooksCustomer } = await import("./handlers/customer.handler.js");
                  result = await deleteQuickbooksCustomer(toolArgs.customerId);
                
                // Invoice handlers
                } else if (toolName === "qbo_search_invoices") {
                  const { searchQuickbooksInvoices } = await import("./handlers/invoice.handler.js");
                  const criteria: any[] = [];
                  if (toolArgs.customerId) criteria.push({ field: "CustomerRef", value: toolArgs.customerId });
                  if (toolArgs.docNumber) criteria.push({ field: "DocNumber", value: toolArgs.docNumber });
                  if (toolArgs.limit) criteria.push({ field: "limit", value: toolArgs.limit });
                  result = await searchQuickbooksInvoices(criteria);
                } else if (toolName === "qbo_get_invoice") {
                  const { getQuickbooksInvoice } = await import("./handlers/invoice.handler.js");
                  result = await getQuickbooksInvoice(toolArgs.invoiceId);
                } else if (toolName === "qbo_create_invoice") {
                  const { createQuickbooksInvoice } = await import("./handlers/invoice.handler.js");
                  const invoiceData: any = {
                    CustomerRef: { value: toolArgs.customerId }
                  };
                  if (toolArgs.lineItems) {
                    let rawLineItems: any[];
                    // Handle lineItems as string, array, or object
                    if (typeof toolArgs.lineItems === "string") {
                      try {
                        rawLineItems = JSON.parse(toolArgs.lineItems);
                        console.log("Parsed lineItems from JSON string");
                      } catch {
                        rawLineItems = [{ amount: 0, description: toolArgs.lineItems }];
                      }
                    } else if (Array.isArray(toolArgs.lineItems)) {
                      rawLineItems = toolArgs.lineItems;
                    } else {
                      rawLineItems = [toolArgs.lineItems];
                    }
                    // Transform simplified format to QuickBooks API format
                    // FIXED: Don't include empty Description (causes QuickBooks API error)
                    invoiceData.Line = rawLineItems.map((item: any) => {
                      const line: any = {
                        Amount: item.amount || item.Amount || 0,
                        DetailType: "SalesItemLineDetail",
                        SalesItemLineDetail: {
                          ItemRef: { value: item.itemId || "1" },  // Default to first item
                          Qty: item.qty || item.Qty || 1,
                          UnitPrice: item.unitPrice || item.UnitPrice || item.amount || item.Amount || 0
                        }
                      };
                      // Only add Description if it has a non-empty value
                      const desc = item.description || item.Description;
                      if (desc && desc.trim()) {
                        line.Description = desc;
                      }
                      return line;
                    });
                  } else {
                    // Default line item if none provided
                    invoiceData.Line = [{
                      DetailType: "SalesItemLineDetail",
                      Amount: 0,
                      SalesItemLineDetail: { ItemRef: { value: "1" }, Qty: 1, UnitPrice: 0 }
                    }];
                  }
                  if (toolArgs.dueDate) invoiceData.DueDate = toolArgs.dueDate;
                  if (toolArgs.docNumber) invoiceData.DocNumber = toolArgs.docNumber;
                  if (toolArgs.txnDate) invoiceData.TxnDate = toolArgs.txnDate;
                  console.error("Creating invoice with data:", JSON.stringify(invoiceData, null, 2));
                  result = await createQuickbooksInvoice(invoiceData);
                } else if (toolName === "qbo_update_invoice") {
                  const { updateQuickbooksInvoice } = await import("./handlers/invoice.handler.js");
                  const invoiceData: any = { Id: toolArgs.invoiceId };
                  if (toolArgs.dueDate) invoiceData.DueDate = toolArgs.dueDate;
                  if (toolArgs.privateNote) invoiceData.PrivateNote = toolArgs.privateNote;
                  result = await updateQuickbooksInvoice(invoiceData);
                } else if (toolName === "qbo_delete_invoice") {
                  const { deleteQuickbooksInvoice } = await import("./handlers/invoice.handler.js");
                  result = await deleteQuickbooksInvoice(toolArgs.invoiceId);
                
                // Account handlers
                } else if (toolName === "qbo_search_accounts") {
                  const { searchQuickbooksAccounts } = await import("./handlers/account.handler.js");
                  const criteria: any[] = [];
                  if (toolArgs.name) criteria.push({ field: "Name", value: toolArgs.name, operator: "LIKE" });
                  if (toolArgs.accountType) criteria.push({ field: "AccountType", value: toolArgs.accountType });
                  if (toolArgs.limit) criteria.push({ field: "limit", value: toolArgs.limit });
                  result = await searchQuickbooksAccounts(criteria);
                } else if (toolName === "qbo_get_account") {
                  const { getQuickbooksAccount } = await import("./handlers/account.handler.js");
                  result = await getQuickbooksAccount(toolArgs.accountId);
                } else if (toolName === "qbo_create_account") {
                  const { createQuickbooksAccount } = await import("./handlers/account.handler.js");
                  const accountData: any = { 
                    Name: toolArgs.name,
                    AccountType: toolArgs.accountType
                  };
                  if (toolArgs.accountSubType) accountData.AccountSubType = toolArgs.accountSubType;
                  result = await createQuickbooksAccount(accountData);
                } else if (toolName === "qbo_update_account") {
                  const { updateQuickbooksAccount } = await import("./handlers/account.handler.js");
                  result = await updateQuickbooksAccount({ Id: toolArgs.accountId, ...toolArgs.accountData });
                
                // Item handlers
                } else if (toolName === "qbo_search_items") {
                  const { searchQuickbooksItems } = await import("./handlers/item.handler.js");
                  const criteria: any[] = [];
                  if (toolArgs.name) criteria.push({ field: "Name", value: toolArgs.name, operator: "LIKE" });
                  if (toolArgs.type) criteria.push({ field: "Type", value: toolArgs.type });
                  if (toolArgs.limit) criteria.push({ field: "limit", value: toolArgs.limit });
                  result = await searchQuickbooksItems(criteria);
                } else if (toolName === "qbo_get_item") {
                  const { getQuickbooksItem } = await import("./handlers/item.handler.js");
                  result = await getQuickbooksItem(toolArgs.itemId);
                } else if (toolName === "qbo_create_item") {
                  const { createQuickbooksItem } = await import("./handlers/item.handler.js");
                  const itemData: any = { Name: toolArgs.name };
                  if (toolArgs.type) itemData.Type = toolArgs.type;
                  if (toolArgs.unitPrice) itemData.UnitPrice = toolArgs.unitPrice;
                  if (toolArgs.description) itemData.Description = toolArgs.description;
                  result = await createQuickbooksItem(itemData);
                } else if (toolName === "qbo_update_item") {
                  const { updateQuickbooksItem } = await import("./handlers/item.handler.js");
                  result = await updateQuickbooksItem({ Id: toolArgs.itemId, ...toolArgs.itemData });
                
                // Vendor handlers
                } else if (toolName === "qbo_search_vendors") {
                  const { searchQuickbooksVendors } = await import("./handlers/vendor.handler.js");
                  const criteria: any[] = [];
                  if (toolArgs.displayName) criteria.push({ field: "DisplayName", value: toolArgs.displayName, operator: "LIKE" });
                  if (toolArgs.active !== undefined) criteria.push({ field: "Active", value: toolArgs.active });
                  if (toolArgs.limit) criteria.push({ field: "limit", value: toolArgs.limit });
                  result = await searchQuickbooksVendors(criteria);
                } else if (toolName === "qbo_get_vendor") {
                  const { getQuickbooksVendor } = await import("./handlers/vendor.handler.js");
                  result = await getQuickbooksVendor(toolArgs.vendorId);
                } else if (toolName === "qbo_create_vendor") {
                  const { createQuickbooksVendor, getQuickbooksVendor } = await import("./handlers/vendor.handler.js");
                  const { executeQuickbooksQuery } = await import("./handlers/query.handler.js");
                  const originalDisplayName = toolArgs.displayName;
                  const vendorData: any = { DisplayName: originalDisplayName };
                  if (toolArgs.email) vendorData.PrimaryEmailAddr = { Address: toolArgs.email };
                  if (toolArgs.phone) vendorData.PrimaryPhone = { FreeFormNumber: toolArgs.phone };
                  if (toolArgs.companyName) vendorData.CompanyName = toolArgs.companyName;
                  result = await createQuickbooksVendor(vendorData);
                  
                  // Handle duplicate vendor error - try to fetch existing vendor or search by name
                  if (result.isError && result.error && result.error.includes("Duplicate Name Exists Error")) {
                    const idMatch = result.error.match(/Id=(\d+)/);
                    if (idMatch) {
                      const existingId = idMatch[1];
                      console.log(`[MCP] Vendor already exists with Id=${existingId}, attempting to fetch...`);
                      
                      // Try to get vendor directly by ID from the error
                      let existingVendor = await getQuickbooksVendor(existingId);
                      
                      if (!existingVendor.isError) {
                        // Vendor is active, return it
                        result = {
                          result: existingVendor.result,
                          isError: false,
                          error: null,
                          message: `Vendor already exists (Id=${existingId}), returning existing vendor`
                        };
                        console.log(`[MCP] Returning existing active vendor ${existingId}`);
                      } else {
                        // Vendor ID from error is deleted/inaccessible — the name is reserved by a deleted vendor.
                        // Use raw SQL query to find active vendors with matching DisplayName prefix (most reliable).
                        console.log(`[MCP] Vendor ${existingId} is deleted/inaccessible. Querying for active vendor with similar name...`);
                        
                        const escapedName = originalDisplayName.replace(/'/g, "\\'");
                        const queryResult = await executeQuickbooksQuery(
                          `SELECT * FROM Vendor WHERE DisplayName LIKE '${escapedName}%'`
                        );
                        
                        console.log(`[MCP] Query result: isError=${queryResult.isError}, count=${queryResult.result?.length || 0}`);
                        
                        if (!queryResult.isError && queryResult.result && queryResult.result.length > 0) {
                          // Found active vendor(s) with similar name — return the most recent one (highest Id)
                          const vendors = queryResult.result;
                          const bestMatch = vendors.reduce((a: any, b: any) => 
                            parseInt(a.Id) > parseInt(b.Id) ? a : b
                          );
                          result = {
                            result: bestMatch,
                            isError: false,
                            error: null,
                            message: `Original name "${originalDisplayName}" is reserved by deleted vendor. Returning most recent active vendor "${bestMatch.DisplayName}" (Id=${bestMatch.Id})`
                          };
                          console.log(`[MCP] Found active vendor match: ${bestMatch.DisplayName} (Id=${bestMatch.Id})`);
                        } else {
                          // No active vendor found — create with unique timestamp suffix
                          const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19); // YYYY-MM-DDTHH-MM-SS
                          const newDisplayName = `${originalDisplayName} (${timestamp})`;
                          vendorData.DisplayName = newDisplayName;
                          
                          const retryResult = await createQuickbooksVendor(vendorData);
                          if (!retryResult.isError) {
                            result = {
                              result: retryResult.result,
                              isError: false,
                              error: null,
                              message: `Original vendor name was deleted. Created new vendor as "${newDisplayName}"`
                            };
                            console.log(`[MCP] Created vendor with alternate name: ${newDisplayName}`);
                          } else {
                            result = retryResult;
                          }
                        }
                      }
                    }
                  }
                } else if (toolName === "qbo_update_vendor") {
                  const { updateQuickbooksVendor } = await import("./handlers/vendor.handler.js");
                  const vendorData: any = { Id: toolArgs.vendorId || toolArgs.Id };
                  if (toolArgs.displayName || toolArgs.DisplayName) vendorData.DisplayName = toolArgs.displayName || toolArgs.DisplayName;
                  if (toolArgs.email) vendorData.PrimaryEmailAddr = { Address: toolArgs.email };
                  if (toolArgs.phone) vendorData.PrimaryPhone = { FreeFormNumber: toolArgs.phone };
                  if (toolArgs.Active !== undefined) vendorData.Active = toolArgs.Active;
                  if (toolArgs.SyncToken) vendorData.SyncToken = toolArgs.SyncToken;
                  result = await updateQuickbooksVendor(vendorData);
                } else if (toolName === "qbo_delete_vendor") {
                  const { deleteQuickbooksVendor } = await import("./handlers/vendor.handler.js");
                  result = await deleteQuickbooksVendor(toolArgs.vendorId);
                
                // Bill handlers
                } else if (toolName === "qbo_search_bills") {
                  const { searchQuickbooksBills } = await import("./handlers/bill.handler.js");
                  const criteria: any[] = [];
                  if (toolArgs.vendorId) criteria.push({ field: "VendorRef", value: toolArgs.vendorId });
                  if (toolArgs.docNumber) criteria.push({ field: "DocNumber", value: toolArgs.docNumber });
                  if (toolArgs.limit) criteria.push({ field: "limit", value: toolArgs.limit });
                  result = await searchQuickbooksBills(criteria);
                } else if (toolName === "qbo_get_bill") {
                  const { getQuickbooksBill } = await import("./handlers/bill.handler.js");
                  result = await getQuickbooksBill(toolArgs.billId);
                } else if (toolName === "qbo_create_bill") {
                  const { createQuickbooksBill } = await import("./handlers/bill.handler.js");
                  const billData: any = { VendorRef: { value: toolArgs.vendorId } };
                  if (toolArgs.lineItems) {
                    let rawLineItems: any[];
                    if (typeof toolArgs.lineItems === "string") {
                      try {
                        rawLineItems = JSON.parse(toolArgs.lineItems);
                      } catch {
                        rawLineItems = [{ amount: 0, description: toolArgs.lineItems }];
                      }
                    } else if (Array.isArray(toolArgs.lineItems)) {
                      rawLineItems = toolArgs.lineItems;
                    } else {
                      rawLineItems = [toolArgs.lineItems];
                    }
                    // Transform simplified format to QuickBooks API format
                    billData.Line = rawLineItems.map((item: any) => {
                      const desc = item.description || item.Description;
                      return {
                        Amount: item.amount || item.Amount || 0,
                        DetailType: "AccountBasedExpenseLineDetail",
                        AccountBasedExpenseLineDetail: {
                          AccountRef: { value: item.accountId || "7" }  // Default to Expenses account
                        },
                        ...(desc ? { Description: desc } : {})  // Only add if truthy
                      };
                    });
                  }
                  if (toolArgs.dueDate) billData.DueDate = toolArgs.dueDate;
                  if (toolArgs.docNumber) billData.DocNumber = toolArgs.docNumber;
                  if (toolArgs.txnDate) billData.TxnDate = toolArgs.txnDate;
                  result = await createQuickbooksBill(billData);
                } else if (toolName === "qbo_update_bill") {
                  const { updateQuickbooksBill } = await import("./handlers/bill.handler.js");
                  const updateBillData: any = { Id: toolArgs.billId };
                  if (toolArgs.vendorId) updateBillData.VendorRef = { value: toolArgs.vendorId };
                  if (toolArgs.dueDate) updateBillData.DueDate = toolArgs.dueDate;
                  if (toolArgs.lineItems) {
                    if (typeof toolArgs.lineItems === "string") {
                      try {
                        updateBillData.Line = JSON.parse(toolArgs.lineItems);
                      } catch {
                        updateBillData.Line = [{ Description: toolArgs.lineItems, Amount: 0, DetailType: "AccountBasedExpenseLineDetail" }];
                      }
                    } else if (Array.isArray(toolArgs.lineItems)) {
                      updateBillData.Line = toolArgs.lineItems;
                    } else {
                      updateBillData.Line = [toolArgs.lineItems];
                    }
                  }
                  result = await updateQuickbooksBill(updateBillData);
                } else if (toolName === "qbo_delete_bill") {
                  const { deleteQuickbooksBill } = await import("./handlers/bill.handler.js");
                  result = await deleteQuickbooksBill(toolArgs.billId);
                
                // Employee handlers
                } else if (toolName === "qbo_search_employees") {
                  const { searchQuickbooksEmployees } = await import("./handlers/employee.handler.js");
                  result = await searchQuickbooksEmployees(toolArgs.criteria || {});
                } else if (toolName === "qbo_get_employee") {
                  const { getQuickbooksEmployee } = await import("./handlers/employee.handler.js");
                  result = await getQuickbooksEmployee(toolArgs.employeeId);
                } else if (toolName === "qbo_create_employee") {
                  const { createQuickbooksEmployee } = await import("./handlers/employee.handler.js");
                  const employeeData: any = {};
                  if (toolArgs.givenName) employeeData.GivenName = toolArgs.givenName;
                  if (toolArgs.familyName) employeeData.FamilyName = toolArgs.familyName;
                  if (toolArgs.displayName) employeeData.DisplayName = toolArgs.displayName;
                  if (toolArgs.email) employeeData.PrimaryEmailAddr = { Address: toolArgs.email };
                  if (toolArgs.phone) employeeData.PrimaryPhone = { FreeFormNumber: toolArgs.phone };
                  result = await createQuickbooksEmployee(employeeData);
                } else if (toolName === "qbo_update_employee") {
                  const { updateQuickbooksEmployee } = await import("./handlers/employee.handler.js");
                  const updateEmployeeData: any = { Id: toolArgs.employeeId };
                  if (toolArgs.givenName) updateEmployeeData.GivenName = toolArgs.givenName;
                  if (toolArgs.familyName) updateEmployeeData.FamilyName = toolArgs.familyName;
                  if (toolArgs.displayName) updateEmployeeData.DisplayName = toolArgs.displayName;
                  if (toolArgs.email) updateEmployeeData.PrimaryEmailAddr = { Address: toolArgs.email };
                  if (toolArgs.phone) updateEmployeeData.PrimaryPhone = { FreeFormNumber: toolArgs.phone };
                  result = await updateQuickbooksEmployee(updateEmployeeData);
                
                // Estimate handlers
                } else if (toolName === "qbo_search_estimates") {
                  const { searchQuickbooksEstimates } = await import("./handlers/estimate.handler.js");
                  result = await searchQuickbooksEstimates(toolArgs.criteria || {});
                } else if (toolName === "qbo_get_estimate") {
                  const { getQuickbooksEstimate } = await import("./handlers/estimate.handler.js");
                  result = await getQuickbooksEstimate(toolArgs.estimateId);
                } else if (toolName === "qbo_create_estimate") {
                  const { createQuickbooksEstimate } = await import("./handlers/estimate.handler.js");
                  const estimateData: any = { CustomerRef: { value: toolArgs.customerId } };
                  if (toolArgs.lineItems) {
                    if (typeof toolArgs.lineItems === "string") {
                      try {
                        estimateData.Line = JSON.parse(toolArgs.lineItems);
                      } catch {
                        estimateData.Line = [{ Description: toolArgs.lineItems, Amount: 0, DetailType: "SalesItemLineDetail" }];
                      }
                    } else if (Array.isArray(toolArgs.lineItems)) {
                      estimateData.Line = toolArgs.lineItems;
                    } else {
                      estimateData.Line = [toolArgs.lineItems];
                    }
                  }
                  if (toolArgs.expirationDate) estimateData.ExpirationDate = toolArgs.expirationDate;
                  result = await createQuickbooksEstimate(estimateData);
                } else if (toolName === "qbo_update_estimate") {
                  const { updateQuickbooksEstimate } = await import("./handlers/estimate.handler.js");
                  const updateEstimateData: any = { Id: toolArgs.estimateId };
                  if (toolArgs.customerId) updateEstimateData.CustomerRef = { value: toolArgs.customerId };
                  if (toolArgs.expirationDate) updateEstimateData.ExpirationDate = toolArgs.expirationDate;
                  if (toolArgs.lineItems) {
                    if (typeof toolArgs.lineItems === "string") {
                      try {
                        updateEstimateData.Line = JSON.parse(toolArgs.lineItems);
                      } catch {
                        updateEstimateData.Line = [{ Description: toolArgs.lineItems, Amount: 0, DetailType: "SalesItemLineDetail" }];
                      }
                    } else if (Array.isArray(toolArgs.lineItems)) {
                      updateEstimateData.Line = toolArgs.lineItems;
                    } else {
                      updateEstimateData.Line = [toolArgs.lineItems];
                    }
                  }
                  result = await updateQuickbooksEstimate(updateEstimateData);
                } else if (toolName === "qbo_delete_estimate") {
                  const { deleteQuickbooksEstimate } = await import("./handlers/estimate.handler.js");
                  result = await deleteQuickbooksEstimate(toolArgs.estimateId);
                
                // Purchase handlers
                } else if (toolName === "qbo_search_purchases") {
                  const { searchQuickbooksPurchases } = await import("./handlers/purchase.handler.js");
                  result = await searchQuickbooksPurchases(toolArgs.criteria || {});
                } else if (toolName === "qbo_get_purchase") {
                  const { getQuickbooksPurchase } = await import("./handlers/purchase.handler.js");
                  result = await getQuickbooksPurchase(toolArgs.purchaseId);
                } else if (toolName === "qbo_create_purchase") {
                  const { createQuickbooksPurchase } = await import("./handlers/purchase.handler.js");
                  const purchaseData: any = { PaymentType: toolArgs.paymentType || "Cash" };
                  if (toolArgs.accountId) purchaseData.AccountRef = { value: toolArgs.accountId };
                  if (toolArgs.lineItems) {
                    if (typeof toolArgs.lineItems === "string") {
                      try {
                        purchaseData.Line = JSON.parse(toolArgs.lineItems);
                      } catch {
                        purchaseData.Line = [{ Description: toolArgs.lineItems, Amount: 0, DetailType: "AccountBasedExpenseLineDetail" }];
                      }
                    } else if (Array.isArray(toolArgs.lineItems)) {
                      purchaseData.Line = toolArgs.lineItems;
                    } else {
                      purchaseData.Line = [toolArgs.lineItems];
                    }
                  }
                  result = await createQuickbooksPurchase(purchaseData);
                } else if (toolName === "qbo_update_purchase") {
                  const { updateQuickbooksPurchase } = await import("./handlers/purchase.handler.js");
                  const updatePurchaseData: any = { Id: toolArgs.purchaseId };
                  if (toolArgs.paymentType) updatePurchaseData.PaymentType = toolArgs.paymentType;
                  if (toolArgs.accountId) updatePurchaseData.AccountRef = { value: toolArgs.accountId };
                  if (toolArgs.lineItems) {
                    if (typeof toolArgs.lineItems === "string") {
                      try {
                        updatePurchaseData.Line = JSON.parse(toolArgs.lineItems);
                      } catch {
                        updatePurchaseData.Line = [{ Description: toolArgs.lineItems, Amount: 0, DetailType: "AccountBasedExpenseLineDetail" }];
                      }
                    } else if (Array.isArray(toolArgs.lineItems)) {
                      updatePurchaseData.Line = toolArgs.lineItems;
                    } else {
                      updatePurchaseData.Line = [toolArgs.lineItems];
                    }
                  }
                  result = await updateQuickbooksPurchase(updatePurchaseData);
                } else if (toolName === "qbo_delete_purchase") {
                  const { deleteQuickbooksPurchase } = await import("./handlers/purchase.handler.js");
                  result = await deleteQuickbooksPurchase(toolArgs.purchaseId);
                
                // Journal Entry handlers
                } else if (toolName === "qbo_search_journal_entries") {
                  const { searchQuickbooksJournalEntries } = await import("./handlers/journal-entry.handler.js");
                  result = await searchQuickbooksJournalEntries(toolArgs.criteria || {});
                } else if (toolName === "qbo_get_journal_entry") {
                  const { getQuickbooksJournalEntry } = await import("./handlers/journal-entry.handler.js");
                  result = await getQuickbooksJournalEntry(toolArgs.journalEntryId);
                } else if (toolName === "qbo_create_journal_entry") {
                  const { createQuickbooksJournalEntry } = await import("./handlers/journal-entry.handler.js");
                  const journalEntryData: any = {};
                  if (toolArgs.lineItems) {
                    if (typeof toolArgs.lineItems === "string") {
                      try {
                        journalEntryData.Line = JSON.parse(toolArgs.lineItems);
                      } catch {
                        journalEntryData.Line = [];
                      }
                    } else if (Array.isArray(toolArgs.lineItems)) {
                      journalEntryData.Line = toolArgs.lineItems;
                    } else {
                      journalEntryData.Line = [toolArgs.lineItems];
                    }
                  }
                  if (toolArgs.privateNote) journalEntryData.PrivateNote = toolArgs.privateNote;
                  if (toolArgs.txnDate) journalEntryData.TxnDate = toolArgs.txnDate;
                  result = await createQuickbooksJournalEntry(journalEntryData);
                } else if (toolName === "qbo_update_journal_entry") {
                  const { updateQuickbooksJournalEntry } = await import("./handlers/journal-entry.handler.js");
                  const updateJournalEntryData: any = { Id: toolArgs.journalEntryId };
                  if (toolArgs.lineItems) {
                    if (typeof toolArgs.lineItems === "string") {
                      try {
                        updateJournalEntryData.Line = JSON.parse(toolArgs.lineItems);
                      } catch {
                        updateJournalEntryData.Line = [];
                      }
                    } else if (Array.isArray(toolArgs.lineItems)) {
                      updateJournalEntryData.Line = toolArgs.lineItems;
                    } else {
                      updateJournalEntryData.Line = [toolArgs.lineItems];
                    }
                  }
                  if (toolArgs.privateNote) updateJournalEntryData.PrivateNote = toolArgs.privateNote;
                  if (toolArgs.txnDate) updateJournalEntryData.TxnDate = toolArgs.txnDate;
                  result = await updateQuickbooksJournalEntry(updateJournalEntryData);
                } else if (toolName === "qbo_delete_journal_entry") {
                  const { deleteQuickbooksJournalEntry } = await import("./handlers/journal-entry.handler.js");
                  result = await deleteQuickbooksJournalEntry(toolArgs.journalEntryId);
                
                // Bill Payment handlers
                } else if (toolName === "qbo_search_bill_payments") {
                  const { searchQuickbooksBillPayments } = await import("./handlers/bill-payment.handler.js");
                  result = await searchQuickbooksBillPayments(toolArgs.criteria || {});
                } else if (toolName === "qbo_get_bill_payment") {
                  const { getQuickbooksBillPayment } = await import("./handlers/bill-payment.handler.js");
                  result = await getQuickbooksBillPayment(toolArgs.billPaymentId);
                } else if (toolName === "qbo_create_bill_payment") {
                  const { createQuickbooksBillPayment } = await import("./handlers/bill-payment.handler.js");
                  const billPaymentData: any = { 
                    VendorRef: { value: toolArgs.vendorId },
                    PayType: toolArgs.payType || "Check",
                    TotalAmt: toolArgs.totalAmt
                  };
                  if (toolArgs.checkPayment) {
                    billPaymentData.CheckPayment = typeof toolArgs.checkPayment === "string" 
                      ? JSON.parse(toolArgs.checkPayment) 
                      : toolArgs.checkPayment;
                  }
                  if (toolArgs.lineItems) {
                    if (typeof toolArgs.lineItems === "string") {
                      try {
                        billPaymentData.Line = JSON.parse(toolArgs.lineItems);
                      } catch {
                        billPaymentData.Line = [];
                      }
                    } else if (Array.isArray(toolArgs.lineItems)) {
                      billPaymentData.Line = toolArgs.lineItems;
                    } else {
                      billPaymentData.Line = [toolArgs.lineItems];
                    }
                  }
                  result = await createQuickbooksBillPayment(billPaymentData);
                } else if (toolName === "qbo_update_bill_payment") {
                  const { updateQuickbooksBillPayment } = await import("./handlers/bill-payment.handler.js");
                  const updateBillPaymentData: any = { Id: toolArgs.billPaymentId };
                  if (toolArgs.vendorId) updateBillPaymentData.VendorRef = { value: toolArgs.vendorId };
                  if (toolArgs.payType) updateBillPaymentData.PayType = toolArgs.payType;
                  if (toolArgs.totalAmt) updateBillPaymentData.TotalAmt = toolArgs.totalAmt;
                  if (toolArgs.checkPayment) {
                    updateBillPaymentData.CheckPayment = typeof toolArgs.checkPayment === "string" 
                      ? JSON.parse(toolArgs.checkPayment) 
                      : toolArgs.checkPayment;
                  }
                  if (toolArgs.lineItems) {
                    if (typeof toolArgs.lineItems === "string") {
                      try {
                        updateBillPaymentData.Line = JSON.parse(toolArgs.lineItems);
                      } catch {
                        updateBillPaymentData.Line = [];
                      }
                    } else if (Array.isArray(toolArgs.lineItems)) {
                      updateBillPaymentData.Line = toolArgs.lineItems;
                    } else {
                      updateBillPaymentData.Line = [toolArgs.lineItems];
                    }
                  }
                  result = await updateQuickbooksBillPayment(updateBillPaymentData);
                } else if (toolName === "qbo_delete_bill_payment") {
                  const { deleteQuickbooksBillPayment } = await import("./handlers/bill-payment.handler.js");
                  result = await deleteQuickbooksBillPayment(toolArgs.billPaymentId);
                
                // Query and Report handlers
                } else if (toolName === "qbo_query") {
                  const { executeQuickbooksQuery } = await import("./handlers/query.handler.js");
                  result = await executeQuickbooksQuery(toolArgs.query);
                } else if (toolName === "qbo_company_info") {
                  const { getQuickbooksCompanyInfo } = await import("./handlers/query.handler.js");
                  result = await getQuickbooksCompanyInfo();
                } else if (toolName === "qbo_report") {
                  const { runQuickbooksReport } = await import("./handlers/query.handler.js");
                  // Convert flat params to options object
                  const options: any = {};
                  if (toolArgs.startDate) options.start_date = toolArgs.startDate;
                  if (toolArgs.endDate) options.end_date = toolArgs.endDate;
                  result = await runQuickbooksReport(toolArgs.reportType, options);
                } else {
                  throw new Error(`Unknown tool: ${toolName}`);
                }
                
                // === APPLY SUMMARIZATION TO REDUCE TOKEN USAGE ===
                let summarizedResult: any;
                const rawData = result?.result;
                
                // Summarize based on tool type
                if (toolName === "qbo_search_invoices" && Array.isArray(rawData)) {
                  summarizedResult = rawData.map((inv: any) => summarizeInvoice(inv));
                } else if (toolName === "qbo_get_invoice" && rawData) {
                  summarizedResult = summarizeInvoiceDetail(rawData);
                } else if (toolName === "qbo_create_invoice" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'Invoice');
                } else if (toolName === "qbo_update_invoice" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'Invoice');
                } else if (toolName === "qbo_search_customers" && Array.isArray(rawData)) {
                  summarizedResult = rawData.map((c: any) => summarizeCustomer(c));
                } else if (toolName === "qbo_get_customer" && rawData) {
                  summarizedResult = summarizeCustomerDetail(rawData);
                } else if (toolName === "qbo_create_customer" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'Customer');
                } else if (toolName === "qbo_update_customer" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'Customer');
                } else if (toolName === "qbo_search_vendors" && Array.isArray(rawData)) {
                  summarizedResult = rawData.map((v: any) => summarizeVendor(v));
                } else if (toolName === "qbo_get_vendor" && rawData) {
                  summarizedResult = summarizeVendorDetail(rawData);
                } else if (toolName === "qbo_create_vendor" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'Vendor');
                } else if (toolName === "qbo_update_vendor" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'Vendor');
                } else if (toolName === "qbo_search_bills" && Array.isArray(rawData)) {
                  summarizedResult = rawData.map((b: any) => summarizeBill(b));
                } else if (toolName === "qbo_get_bill" && rawData) {
                  summarizedResult = summarizeBillDetail(rawData);
                } else if (toolName === "qbo_create_bill" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'Bill');
                } else if (toolName === "qbo_update_bill" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'Bill');
                } else if (toolName === "qbo_search_items" && Array.isArray(rawData)) {
                  summarizedResult = rawData.map((item: any) => summarizeItem(item));
                } else if (toolName === "qbo_get_item" && rawData) {
                  summarizedResult = summarizeItemDetail(rawData);
                } else if (toolName === "qbo_create_item" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'Item');
                } else if (toolName === "qbo_update_item" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'Item');
                } else if (toolName === "qbo_search_accounts" && Array.isArray(rawData)) {
                  summarizedResult = rawData.map((acc: any) => summarizeAccount(acc));
                } else if (toolName === "qbo_get_account" && rawData) {
                  summarizedResult = summarizeAccountDetail(rawData);
                } else if (toolName === "qbo_create_account" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'Account');
                } else if (toolName === "qbo_update_account" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'Account');
                } else if (toolName === "qbo_search_employees" && Array.isArray(rawData)) {
                  summarizedResult = rawData.map((emp: any) => summarizeEmployee(emp));
                } else if (toolName === "qbo_get_employee" && rawData) {
                  summarizedResult = summarizeEmployee(rawData);
                } else if (toolName === "qbo_create_employee" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'Employee');
                } else if (toolName === "qbo_update_employee" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'Employee');
                } else if (toolName === "qbo_search_estimates" && Array.isArray(rawData)) {
                  summarizedResult = rawData.map((est: any) => summarizeEstimate(est));
                } else if (toolName === "qbo_get_estimate" && rawData) {
                  summarizedResult = summarizeEstimate(rawData);
                } else if (toolName === "qbo_create_estimate" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'Estimate');
                } else if (toolName === "qbo_update_estimate" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'Estimate');
                } else if (toolName === "qbo_search_purchases" && Array.isArray(rawData)) {
                  summarizedResult = rawData.map((p: any) => summarizePurchase(p));
                } else if (toolName === "qbo_get_purchase" && rawData) {
                  summarizedResult = summarizePurchase(rawData);
                } else if (toolName === "qbo_create_purchase" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'Purchase');
                } else if (toolName === "qbo_update_purchase" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'Purchase');
                } else if (toolName === "qbo_search_journal_entries" && Array.isArray(rawData)) {
                  summarizedResult = rawData.map((je: any) => summarizeJournalEntry(je));
                } else if (toolName === "qbo_get_journal_entry" && rawData) {
                  summarizedResult = summarizeJournalEntry(rawData);
                } else if (toolName === "qbo_create_journal_entry" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'JournalEntry');
                } else if (toolName === "qbo_update_journal_entry" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'JournalEntry');
                } else if (toolName === "qbo_search_bill_payments" && Array.isArray(rawData)) {
                  summarizedResult = rawData.map((bp: any) => summarizeBillPayment(bp));
                } else if (toolName === "qbo_get_bill_payment" && rawData) {
                  summarizedResult = summarizeBillPayment(rawData);
                } else if (toolName === "qbo_create_bill_payment" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'BillPayment');
                } else if (toolName === "qbo_update_bill_payment" && rawData) {
                  summarizedResult = summarizeConfirmation(rawData, 'BillPayment');
                } else if (toolName === "qbo_query" && Array.isArray(rawData)) {
                  // For raw queries, limit results and extract key fields
                  const maxResults = 50;
                  const truncated = rawData.slice(0, maxResults);
                  summarizedResult = truncated.map((r: any) => ({
                    Id: r.Id,
                    ...(r.DisplayName && { DisplayName: r.DisplayName }),
                    ...(r.Name && { Name: r.Name }),
                    ...(r.DocNumber && { DocNumber: r.DocNumber }),
                    ...(r.TotalAmt !== undefined && { TotalAmt: r.TotalAmt }),
                    ...(r.Balance !== undefined && { Balance: r.Balance }),
                    ...(r.TxnDate && { TxnDate: r.TxnDate }),
                    ...(r.Active !== undefined && { Active: r.Active }),
                  }));
                  if (rawData.length > maxResults) {
                    summarizedResult._note = `Showing first ${maxResults} of ${rawData.length} results`;
                  }
                } else if (toolName === "qbo_company_info" && rawData) {
                  summarizedResult = {
                    CompanyName: rawData.CompanyName,
                    LegalName: rawData.LegalName,
                    CompanyAddr: rawData.CompanyAddr,
                    Country: rawData.Country,
                    Email: rawData.Email?.Address,
                    Phone: rawData.PrimaryPhone?.FreeFormNumber,
                    FiscalYearStartMonth: rawData.FiscalYearStartMonth,
                  };
                } else if (toolName === "qbo_report" && rawData) {
                  // Flatten the QuickBooks report into a readable table
                  const columns = rawData.Columns?.Column?.map((c: any) => c.ColTitle) || [];
                  const flatRows: string[] = [];
                  function extractRows(rows: any[], indent = 0) {
                    if (!rows) return;
                    for (const row of rows) {
                      if (row.Header?.ColData) {
                        const vals = row.Header.ColData.map((c: any) => c.value || '');
                        flatRows.push('  '.repeat(indent) + vals.join(' | '));
                      }
                      if (row.ColData) {
                        const vals = row.ColData.map((c: any) => c.value || '');
                        flatRows.push('  '.repeat(indent) + vals.join(' | '));
                      }
                      if (row.Rows?.Row) {
                        extractRows(row.Rows.Row, indent + 1);
                      }
                      if (row.Summary?.ColData) {
                        const vals = row.Summary.ColData.map((c: any) => c.value || '');
                        flatRows.push('  '.repeat(indent) + '**' + vals.join(' | ') + '**');
                      }
                    }
                  }
                  extractRows(rawData.Rows?.Row);
                  const header = `${rawData.Header?.ReportName || 'Report'} (${rawData.Header?.StartPeriod || ''} to ${rawData.Header?.EndPeriod || ''}, ${rawData.Header?.Currency || 'USD'})`;
                  const table = `${columns.join(' | ')}\n${flatRows.join('\n')}`;
                  summarizedResult = `${header}\n\n${table}`;
                } else if (toolName?.includes("delete")) {
                  // Delete operations return simple confirmations
                  summarizedResult = { success: true, message: `${toolName.replace('qbo_delete_', '')} deleted successfully` };
                } else {
                  // Fallback: use raw result but warn if large
                  summarizedResult = result;
                }
                
                // Build response text
                let responseText: string;
                if (result?.isError) {
                  responseText = `Error: ${result.error}`;
                } else if (Array.isArray(summarizedResult)) {
                  // CAP search results to prevent token bloat (25KB+ for broad queries)
                  const MAX_SEARCH_RESULTS = 25;
                  const totalCount = summarizedResult.length;
                  if (totalCount > MAX_SEARCH_RESULTS) {
                    summarizedResult = summarizedResult.slice(0, MAX_SEARCH_RESULTS);
                    responseText = `Found ${totalCount} results (showing first ${MAX_SEARCH_RESULTS}): ${JSON.stringify(summarizedResult)}`;
                  } else {
                    responseText = `Found ${totalCount} results: ${JSON.stringify(summarizedResult)}`;
                  }
                } else if (typeof summarizedResult === 'string') {
                  responseText = summarizedResult;
                } else {
                  responseText = JSON.stringify(summarizedResult);
                }
                
                // Log the result size for debugging token usage
                const resultSize = responseText.length;
                const estimatedTokens = Math.ceil(resultSize / 4);
                const resultCount = Array.isArray(summarizedResult) ? summarizedResult.length : 'N/A';
                
                console.error(`\n📤 TOOL RESPONSE: ${toolName}`);
                console.error(`   Result count: ${resultCount}`);
                console.error(`   Response size: ${resultSize} bytes (~${estimatedTokens} tokens)`);
                console.error(`   Preview: ${responseText.substring(0, 200)}...`);
                console.error(`${"=".repeat(60)}\n`);
                
                const response = {
                  jsonrpc: "2.0",
                  id: jsonRpcRequest.id,
                  result: {
                    content: [
                      { type: "text", text: responseText }
                    ]
                  }
                };
                sendResponse(response);
              } catch (toolError: any) {
                console.error(`\n❌ TOOL ERROR: ${toolName}`);
                console.error(`   Error: ${toolError.message}`);
                console.error(`${"=".repeat(60)}\n`);
                
                const response = {
                  jsonrpc: "2.0",
                  id: jsonRpcRequest.id,
                  result: {
                    content: [
                      { type: "text", text: `Error: ${toolError.message}` }
                    ],
                    isError: true
                  }
                };
                sendResponse(response);
              }
              return;
            }
            
            // Handle notifications/initialized (just acknowledge)
            if (jsonRpcRequest.method === "notifications/initialized") {
              // This is a notification - return 202 Accepted
              res.writeHead(202);
              res.end();
              return;
            }
            
            // Unknown method
            const errorResponse = {
              jsonrpc: "2.0",
              id: jsonRpcRequest.id,
              error: {
                code: -32601,
                message: `Method not found: ${jsonRpcRequest.method}`
              }
            };
            sendResponse(errorResponse);
            
          } catch (parseError: any) {
            console.error("Error parsing JSON-RPC request:", parseError);
            res.writeHead(400, { "Content-Type": "application/json" });
            res.end(JSON.stringify({
              jsonrpc: "2.0",
              id: null,
              error: {
                code: -32700,
                message: "Parse error: " + parseError.message
              }
            }));
          }
        });
        return;
      }

      if (req.url?.startsWith("/sse") && req.method === "GET") {
        // Handle GET /sse - return tool list for Azure AI Foundry compatibility
        console.error("Received GET request to /sse - returning tool list");
        
        // Build the tools array (same as in tools/list handler)
        const tools = [
          // Customer tools
          { 
            name: "qbo_search_customers", 
            description: "Search customers in QuickBooks Online. Returns a list of customers matching the search criteria.",
            inputSchema: {
              type: "object",
              properties: {
                displayName: { type: "string", description: "Filter by customer display name (partial match)" },
                active: { type: "boolean", description: "Filter by active status (true/false)" },
                limit: { type: "number", description: "Maximum number of results to return (default 100)" }
              }
            }
          },
          { 
            name: "qbo_get_customer", 
            description: "Get a specific customer by ID from QuickBooks Online",
            inputSchema: {
              type: "object",
              properties: {
                customerId: { type: "string", description: "Customer ID (required)" }
              },
              required: ["customerId"]
            }
          },
          { 
            name: "qbo_create_customer", 
            description: "Create a new customer in QuickBooks Online",
            inputSchema: {
              type: "object",
              properties: {
                displayName: { type: "string", description: "Customer display name (required)" },
                email: { type: "string", description: "Email address" },
                phone: { type: "string", description: "Phone number" },
                companyName: { type: "string", description: "Company name" }
              },
              required: ["displayName"]
            }
          },
          { 
            name: "qbo_update_customer", 
            description: "Update an existing customer in QuickBooks Online",
            inputSchema: {
              type: "object",
              properties: {
                customerId: { type: "string", description: "Customer ID (required)" },
                displayName: { type: "string", description: "Customer display name" },
                email: { type: "string", description: "Email address" },
                phone: { type: "string", description: "Phone number" },
                companyName: { type: "string", description: "Company name" }
              },
              required: ["customerId"]
            }
          },
          // Invoice tools
          { 
            name: "qbo_search_invoices", 
            description: "Search invoices in QuickBooks Online",
            inputSchema: {
              type: "object",
              properties: {
                customerId: { type: "string", description: "Filter by customer ID" },
                docNumber: { type: "string", description: "Filter by invoice number" },
                limit: { type: "number", description: "Max results" }
              }
            }
          },
          { 
            name: "qbo_get_invoice", 
            description: "Get a specific invoice by ID",
            inputSchema: {
              type: "object",
              properties: {
                invoiceId: { type: "string", description: "Invoice ID" }
              },
              required: ["invoiceId"]
            }
          },
          { 
            name: "qbo_create_invoice", 
            description: "Create a new invoice",
            inputSchema: {
              type: "object",
              properties: {
                customerId: { type: "string", description: "Customer ID (required)" },
                lineItems: { type: "string", description: "JSON array of line items with Amount, Description, DetailType, SalesItemLineDetail" },
                dueDate: { type: "string", description: "Due date (YYYY-MM-DD)" }
              },
              required: ["customerId"]
            }
          },
          { 
            name: "qbo_update_invoice", 
            description: "Update an existing invoice",
            inputSchema: {
              type: "object",
              properties: {
                invoiceId: { type: "string", description: "Invoice ID (required)" },
                customerId: { type: "string", description: "Customer ID" },
                dueDate: { type: "string", description: "Due date (YYYY-MM-DD)" },
                lineItems: { type: "string", description: "JSON array of line items" }
              },
              required: ["invoiceId"]
            }
          },
          // Account tools
          { 
            name: "qbo_search_accounts", 
            description: "Search chart of accounts",
            inputSchema: {
              type: "object",
              properties: {
                name: { type: "string", description: "Filter by account name" },
                accountType: { type: "string", description: "Filter by type (Bank, Other Current Asset, Fixed Asset, etc.)" },
                limit: { type: "number", description: "Max results" }
              }
            }
          },
          { 
            name: "qbo_get_account", 
            description: "Get a specific account by ID",
            inputSchema: {
              type: "object",
              properties: {
                accountId: { type: "string", description: "Account ID" }
              },
              required: ["accountId"]
            }
          },
          { 
            name: "qbo_create_account", 
            description: "Create a new account",
            inputSchema: {
              type: "object",
              properties: {
                name: { type: "string", description: "Account name (required)" },
                accountType: { type: "string", description: "Type: Bank, Other Current Asset, Fixed Asset, etc. (required)" },
                accountSubType: { type: "string", description: "Sub-type (required)" }
              },
              required: ["name", "accountType", "accountSubType"]
            }
          },
          // Item tools
          { 
            name: "qbo_search_items", 
            description: "Search items (products/services)",
            inputSchema: {
              type: "object",
              properties: {
                name: { type: "string", description: "Filter by item name" },
                type: { type: "string", description: "Filter by type (Inventory, Service, NonInventory)" },
                limit: { type: "number", description: "Max results" }
              }
            }
          },
          { 
            name: "qbo_get_item", 
            description: "Get a specific item by ID",
            inputSchema: {
              type: "object",
              properties: {
                itemId: { type: "string", description: "Item ID" }
              },
              required: ["itemId"]
            }
          },
          { 
            name: "qbo_create_item", 
            description: "Create a new item",
            inputSchema: {
              type: "object",
              properties: {
                name: { type: "string", description: "Item name (required)" },
                type: { type: "string", description: "Type: Inventory, Service, or NonInventory (required)" },
                description: { type: "string", description: "Item description" },
                unitPrice: { type: "number", description: "Unit price" },
                incomeAccountId: { type: "string", description: "Income account reference ID" }
              },
              required: ["name", "type"]
            }
          },
          // Vendor tools
          { 
            name: "qbo_search_vendors", 
            description: "Search vendors",
            inputSchema: {
              type: "object",
              properties: {
                displayName: { type: "string", description: "Filter by display name" },
                limit: { type: "number", description: "Max results" }
              }
            }
          },
          { 
            name: "qbo_get_vendor", 
            description: "Get a specific vendor by ID",
            inputSchema: {
              type: "object",
              properties: {
                vendorId: { type: "string", description: "Vendor ID" }
              },
              required: ["vendorId"]
            }
          },
          { 
            name: "qbo_create_vendor", 
            description: "Create a new vendor",
            inputSchema: {
              type: "object",
              properties: {
                displayName: { type: "string", description: "Vendor display name (required)" },
                email: { type: "string", description: "Email address" },
                phone: { type: "string", description: "Phone number" },
                companyName: { type: "string", description: "Company name" }
              },
              required: ["displayName"]
            }
          },
          { 
            name: "qbo_update_vendor", 
            description: "Update an existing vendor",
            inputSchema: {
              type: "object",
              properties: {
                vendorId: { type: "string", description: "Vendor ID (required)" },
                displayName: { type: "string", description: "Display name" },
                email: { type: "string", description: "Email address" },
                phone: { type: "string", description: "Phone number" }
              },
              required: ["vendorId"]
            }
          },
          // Bill tools
          { 
            name: "qbo_search_bills", 
            description: "Search bills",
            inputSchema: {
              type: "object",
              properties: {
                vendorId: { type: "string", description: "Filter by vendor ID" },
                limit: { type: "number", description: "Max results" }
              }
            }
          },
          { 
            name: "qbo_get_bill", 
            description: "Get a specific bill by ID",
            inputSchema: {
              type: "object",
              properties: {
                billId: { type: "string", description: "Bill ID" }
              },
              required: ["billId"]
            }
          },
          { 
            name: "qbo_create_bill", 
            description: "Create a new bill",
            inputSchema: {
              type: "object",
              properties: {
                vendorId: { type: "string", description: "Vendor ID (required)" },
                lineItems: { type: "string", description: "JSON array of line items" },
                dueDate: { type: "string", description: "Due date (YYYY-MM-DD)" }
              },
              required: ["vendorId"]
            }
          },
          { 
            name: "qbo_update_bill", 
            description: "Update an existing bill",
            inputSchema: {
              type: "object",
              properties: {
                billId: { type: "string", description: "Bill ID (required)" },
                vendorId: { type: "string", description: "Vendor ID" },
                dueDate: { type: "string", description: "Due date (YYYY-MM-DD)" },
                lineItems: { type: "string", description: "JSON array of line items" }
              },
              required: ["billId"]
            }
          },
          // Employee tools
          { 
            name: "qbo_search_employees", 
            description: "Search employees",
            inputSchema: {
              type: "object",
              properties: {
                displayName: { type: "string", description: "Filter by display name" },
                limit: { type: "number", description: "Max results" }
              }
            }
          },
          { 
            name: "qbo_get_employee", 
            description: "Get a specific employee by ID",
            inputSchema: {
              type: "object",
              properties: {
                employeeId: { type: "string", description: "Employee ID" }
              },
              required: ["employeeId"]
            }
          },
          { 
            name: "qbo_create_employee", 
            description: "Create a new employee",
            inputSchema: {
              type: "object",
              properties: {
                givenName: { type: "string", description: "First name (required)" },
                familyName: { type: "string", description: "Last name (required)" },
                email: { type: "string", description: "Email address" },
                phone: { type: "string", description: "Phone number" }
              },
              required: ["givenName", "familyName"]
            }
          },
          // Query and Report tools
          { 
            name: "qbo_query", 
            description: "Execute a query (e.g., 'SELECT * FROM Customer')",
            inputSchema: {
              type: "object",
              properties: {
                query: { type: "string", description: "Query string in QuickBooks query format" }
              },
              required: ["query"]
            }
          },
          { 
            name: "qbo_company_info", 
            description: "Get company information",
            inputSchema: {
              type: "object",
              properties: {}
            }
          },
          { 
            name: "qbo_report", 
            description: "Run a financial report (ProfitAndLoss, BalanceSheet, etc.)",
            inputSchema: {
              type: "object",
              properties: {
                reportType: { type: "string", description: "Report type (ProfitAndLoss, BalanceSheet, CashFlow, etc.)" },
                startDate: { type: "string", description: "Start date (YYYY-MM-DD)" },
                endDate: { type: "string", description: "End date (YYYY-MM-DD)" }
              },
              required: ["reportType"]
            }
          }
        ];
        
        // MINIMAL TOOL SET: Only 10 tools for invoice creation to stay under rate limits
        const essentialToolNames = [
          'qbo_search_customers', 'qbo_get_customer', 'qbo_create_customer',
          'qbo_search_invoices', 'qbo_get_invoice', 'qbo_create_invoice',
          'qbo_search_items', 'qbo_get_item',
          'qbo_query', 'qbo_company_info'
        ];
        const filteredTools = tools.filter(t => essentialToolNames.includes(t.name));
        
        res.writeHead(200, { 
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*"
        });
        res.end(JSON.stringify({ tools: filteredTools }));
        return;
      }

      if (req.url?.startsWith("/message") && req.method === "POST") {
        // Legacy message endpoint - not used with Streamable HTTP
        const url = new URL(req.url, `http://${req.headers.host}`);
        const sessionId = url.searchParams.get("sessionId");

        if (!sessionId) {
          console.error("No session ID provided in request URL");
          res.writeHead(400).end("Missing sessionId parameter");
          return;
        }

        const transport = sseTransports.get(sessionId);
        if (!transport) {
          console.error(`No active transport found for session ID: ${sessionId}`);
          res.writeHead(404).end("Session not found");
          return;
        }

        try {
          await transport.handlePostMessage(req, res);
        } catch (error) {
          console.error("Error handling POST message:", error);
          if (!res.headersSent) {
            res.writeHead(500).end("Error handling request");
          }
        }
        return;
      }

      res.writeHead(404);
      res.end("Not Found");
    });

    httpServer.listen(PORT, () => {
      console.error(`QuickBooks MCP Server running on http://localhost:${PORT}`);
      console.error(`SSE endpoint: http://localhost:${PORT}/sse`);
      console.error(`Health check: http://localhost:${PORT}/health`);
      console.error("");
      console.error("To test with ngrok, run:");
      console.error(`  ngrok http ${PORT}`);
    });
  } else {
    // Stdio mode for Claude Desktop (default)
    const transport = new StdioServerTransport();
    await server.connect(transport);
    console.error("QuickBooks MCP Server running on stdio");
  }
}

runServer().catch((error) => {
  console.error("Fatal error running server:", error);
  process.exit(1);
});