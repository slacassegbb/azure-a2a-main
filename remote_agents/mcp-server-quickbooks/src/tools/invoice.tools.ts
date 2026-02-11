import { z } from "zod";
import { ToolDefinition } from "../types/tool-definition.js";
import {
  searchQuickbooksInvoices,
  getQuickbooksInvoice,
  createQuickbooksInvoice,
  updateQuickbooksInvoice,
  deleteQuickbooksInvoice,
} from "../handlers/invoice.handler.js";
import { summarizeInvoice, summarizeInvoiceDetail, summarizeConfirmation } from "../utils/summarizers.js";

// Search Invoices Tool
const searchInvoicesSchema = z.object({
  customerId: z.string().optional().describe("Filter by customer ID"),
  docNumber: z.string().optional().describe("Filter by invoice/document number"),
  txnDateFrom: z.string().optional().describe("Filter by transaction date (from) - format YYYY-MM-DD"),
  txnDateTo: z.string().optional().describe("Filter by transaction date (to) - format YYYY-MM-DD"),
  unpaidOnly: z.boolean().optional().describe("Set to true to only return invoices with Balance > 0"),
});

export const SearchInvoicesTool: ToolDefinition<typeof searchInvoicesSchema> = {
  name: "qbo_search_invoices",
  description: "Search invoices in QuickBooks Online. Use customerId to find invoices for a specific customer, or unpaidOnly=true to find outstanding invoices.",
  schema: searchInvoicesSchema,
  handler: async (args: any) => {
    const params = (args.params ?? {}) as z.infer<typeof searchInvoicesSchema>;
    const criteria: any = {};
    if (params.customerId) criteria.customerId = params.customerId;
    if (params.docNumber) criteria.docNumber = params.docNumber;
    if (params.txnDateFrom) criteria.txnDateFrom = params.txnDateFrom;
    if (params.txnDateTo) criteria.txnDateTo = params.txnDateTo;
    if (params.unpaidOnly) criteria.unpaidOnly = params.unpaidOnly;
    
    const response = await searchQuickbooksInvoices(criteria);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error searching invoices: ${response.error}` }],
      };
    }
    const invoices = response.result || [];
    // Summarize to reduce token usage (~96% reduction)
    const summary = invoices.map((inv: any) => summarizeInvoice(inv));
    return {
      content: [
        { type: "text" as const, text: `Found ${invoices.length} invoices:\n${JSON.stringify(summary)}` },
      ],
    };
  },
};

// Get Invoice Tool
const getInvoiceSchema = z.object({
  id: z.string().describe("The ID of the invoice to retrieve"),
});

export const GetInvoiceTool: ToolDefinition<typeof getInvoiceSchema> = {
  name: "qbo_get_invoice",
  description: "Get a single invoice by ID from QuickBooks Online. Returns detailed invoice including line items.",
  schema: getInvoiceSchema,
  handler: async (args: any) => {
    const { id } = (args.params ?? {}) as z.infer<typeof getInvoiceSchema>;
    const response = await getQuickbooksInvoice(id);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error getting invoice: ${response.error}` }],
      };
    }
    // Return detailed summary with line items for single invoice
    const detail = summarizeInvoiceDetail(response.result);
    return {
      content: [{ type: "text" as const, text: JSON.stringify(detail) }],
    };
  },
};

// Create Invoice Tool
const createInvoiceSchema = z.object({
  customerId: z.string().describe("The ID of the customer to invoice (required). Get this from qbo_search_customers or qbo_create_customer."),
  lineItems: z.array(z.object({
    amount: z.number().describe("Line amount in dollars (e.g., 500.00)"),
    description: z.string().optional().describe("Line item description (e.g., 'Consulting services - 10 hours')"),
    quantity: z.number().optional().describe("Quantity (optional, defaults to 1)"),
    unitPrice: z.number().optional().describe("Unit price (optional, calculated from amount if not provided)"),
  })).describe("Array of line items. Each item needs: amount (required), description (optional), quantity (optional), unitPrice (optional)"),
  dueDate: z.string().optional().describe("Due date in YYYY-MM-DD format (e.g., '2025-02-15')"),
  docNumber: z.string().optional().describe("Invoice number for reference (e.g., 'INV-2025-001')"),
  txnDate: z.string().optional().describe("Transaction date in YYYY-MM-DD format. Defaults to today."),
  customerEmail: z.string().optional().describe("Email address to send the invoice to"),
});

export const CreateInvoiceTool: ToolDefinition<typeof createInvoiceSchema> = {
  name: "qbo_create_invoice",
  description: `Create a new INVOICE (customer receivable) in QuickBooks Online.

Use this when billing a CUSTOMER for goods/services. NOT for vendor bills you need to pay.

**Example call:**
{
  "customerId": "77",
  "lineItems": [
    { "amount": 3200.00, "description": "Software development - 160 hours @ $20/hr" },
    { "amount": 1500.00, "description": "Cloud hosting services" }
  ],
  "dueDate": "2025-02-15",
  "docNumber": "INV-2025-001"
}

The tool automatically:
- Sets DetailType to "SalesItemLineDetail"
- Uses a default service item for line items
- Formats CustomerRef correctly`,
  schema: createInvoiceSchema,
  handler: async (args: any) => {
    const input = (args.params ?? {}) as z.infer<typeof createInvoiceSchema>;
    
    // CRITICAL: Handle lineItems coming as JSON string (Azure AI Foundry sends it this way)
    let lineItems = input.lineItems;
    if (typeof lineItems === 'string') {
      try {
        lineItems = JSON.parse(lineItems);
        console.log('Parsed lineItems from JSON string:', lineItems);
      } catch (e) {
        return {
          content: [{ type: "text" as const, text: `Error: lineItems must be a valid JSON array. Received: ${typeof lineItems}` }],
        };
      }
    }
    
    // Normalize field names (Amount/amount, Description/description)
    const normalizedLineItems = lineItems.map((item: any) => ({
      amount: item.amount ?? item.Amount,
      description: item.description ?? item.Description,
      quantity: item.quantity ?? item.Quantity ?? 1,
      unitPrice: item.unitPrice ?? item.UnitPrice ?? (item.amount ?? item.Amount),
    }));
    
    // Transform to QuickBooks API format
    const invoiceData: Record<string, any> = {
      CustomerRef: { value: input.customerId },
      Line: normalizedLineItems.map((item: any) => ({
        Amount: item.amount,
        DetailType: "SalesItemLineDetail",
        SalesItemLineDetail: {
          ItemRef: { value: "1" },  // Default to Services item (ID=1), no name field
          Qty: item.quantity || 1,
          UnitPrice: item.unitPrice || item.amount,
        },
        // Description is valid at Line level for SalesItemLineDetail
        ...(item.description ? { Description: item.description } : {})
      }))
    };
    
    if (input.dueDate) invoiceData.DueDate = input.dueDate;
    if (input.docNumber) invoiceData.DocNumber = input.docNumber;
    if (input.txnDate) invoiceData.TxnDate = input.txnDate;
    if (input.customerEmail) invoiceData.BillEmail = { Address: input.customerEmail };
    
    const response = await createQuickbooksInvoice(invoiceData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error creating invoice: ${response.error}` }],
      };
    }
    // Return confirmation with essential fields only
    const confirmation = summarizeConfirmation(response.result, 'Invoice');
    return {
      content: [
        { type: "text" as const, text: `Invoice created successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};

// Update Invoice Tool
const updateInvoiceSchema = z.object({
  Id: z.string().describe("The ID of the invoice to update"),
  SyncToken: z.string().describe("The sync token of the invoice"),
  CustomerRef: z.object({
    value: z.string(),
    name: z.string().optional(),
  }).optional(),
  Line: z.array(z.any()).optional(),
  TxnDate: z.string().optional(),
  DueDate: z.string().optional(),
  DocNumber: z.string().optional(),
});

export const UpdateInvoiceTool: ToolDefinition<typeof updateInvoiceSchema> = {
  name: "qbo_update_invoice",
  description: "Update an existing invoice in QuickBooks Online.",
  schema: updateInvoiceSchema,
  handler: async (args: any) => {
    const invoiceData = (args.params ?? {}) as z.infer<typeof updateInvoiceSchema>;
    const response = await updateQuickbooksInvoice(invoiceData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error updating invoice: ${response.error}` }],
      };
    }
    // Return confirmation with essential fields only
    const confirmation = summarizeConfirmation(response.result, 'Invoice');
    return {
      content: [
        { type: "text" as const, text: `Invoice updated successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};

// Delete Invoice Tool
const deleteInvoiceSchema = z.object({
  Id: z.string().describe("The ID of the invoice to delete"),
  SyncToken: z.string().describe("The sync token of the invoice"),
});

export const DeleteInvoiceTool: ToolDefinition<typeof deleteInvoiceSchema> = {
  name: "qbo_delete_invoice",
  description: "Delete an invoice from QuickBooks Online.",
  schema: deleteInvoiceSchema,
  handler: async (args: any) => {
    const { Id, SyncToken } = (args.params ?? {}) as z.infer<typeof deleteInvoiceSchema>;
    const response = await deleteQuickbooksInvoice({ Id, SyncToken });

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error deleting invoice: ${response.error}` }],
      };
    }
    return {
      content: [{ type: "text" as const, text: "Invoice deleted successfully." }],
    };
  },
};
