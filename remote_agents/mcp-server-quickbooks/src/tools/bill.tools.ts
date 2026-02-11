import { z } from "zod";
import { ToolDefinition } from "../types/tool-definition.js";
import {
  searchQuickbooksBills,
  getQuickbooksBill,
  createQuickbooksBill,
  updateQuickbooksBill,
  deleteQuickbooksBill,
} from "../handlers/bill.handler.js";
import { summarizeBill, summarizeBillDetail, summarizeConfirmation } from "../utils/summarizers.js";

// Search Bills Tool
const searchBillsSchema = z.object({
  vendorId: z.string().optional().describe("Filter by vendor ID"),
  docNumber: z.string().optional().describe("Filter by document/bill number"),
  txnDateFrom: z.string().optional().describe("Filter by transaction date (from) - format YYYY-MM-DD"),
  txnDateTo: z.string().optional().describe("Filter by transaction date (to) - format YYYY-MM-DD"),
});

export const SearchBillsTool: ToolDefinition<typeof searchBillsSchema> = {
  name: "qbo_search_bills",
  description: "Search bills/payables in QuickBooks Online. Use vendorId to find bills from a specific vendor.",
  schema: searchBillsSchema,
  handler: async (args: any) => {
    const params = (args.params ?? {}) as z.infer<typeof searchBillsSchema>;
    const criteria: any = {};
    if (params.vendorId) criteria.vendorId = params.vendorId;
    if (params.docNumber) criteria.docNumber = params.docNumber;
    if (params.txnDateFrom) criteria.txnDateFrom = params.txnDateFrom;
    if (params.txnDateTo) criteria.txnDateTo = params.txnDateTo;
    
    const response = await searchQuickbooksBills(criteria);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error searching bills: ${response.error}` }],
      };
    }
    const bills = response.result || [];
    // Summarize to reduce token usage
    const summary = bills.map((b: any) => summarizeBill(b));
    return {
      content: [
        { type: "text" as const, text: `Found ${bills.length} bills:\n${JSON.stringify(summary)}` },
      ],
    };
  },
};

// Get Bill Tool
const getBillSchema = z.object({
  id: z.string().describe("The ID of the bill to retrieve"),
});

export const GetBillTool: ToolDefinition<typeof getBillSchema> = {
  name: "qbo_get_bill",
  description: "Get a single bill by ID from QuickBooks Online.",
  schema: getBillSchema,
  handler: async (args: any) => {
    const { id } = (args.params ?? {}) as z.infer<typeof getBillSchema>;
    const response = await getQuickbooksBill(id);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error getting bill: ${response.error}` }],
      };
    }
    // Return detailed summary with line items
    const detail = summarizeBillDetail(response.result);
    return {
      content: [{ type: "text" as const, text: JSON.stringify(detail) }],
    };
  },
};

// Create Bill Tool
const createBillSchema = z.object({
  vendorId: z.string().describe("The ID of the vendor for this bill (required). Get this from qbo_search_vendors or qbo_create_vendor."),
  lineItems: z.array(z.object({
    amount: z.number().describe("Line amount in dollars (e.g., 500.00)"),
    description: z.string().optional().describe("Line item description (e.g., 'Software development services')"),
    accountId: z.string().optional().describe("Expense account ID. If not provided, defaults to '7' (Expenses)."),
  })).describe("Array of line items. Each item needs: amount (required), description (optional), accountId (optional, defaults to '7')"),
  dueDate: z.string().optional().describe("Due date in YYYY-MM-DD format (e.g., '2025-02-15')"),
  docNumber: z.string().optional().describe("Bill/invoice number for reference (e.g., 'INV-2025-001')"),
  txnDate: z.string().optional().describe("Transaction date in YYYY-MM-DD format. Defaults to today."),
});

export const CreateBillTool: ToolDefinition<typeof createBillSchema> = {
  name: "qbo_create_bill",
  description: `Create a new BILL (vendor payable) in QuickBooks Online.

Use this when recording a vendor invoice/bill that you need to pay. NOT for billing customers.

**Example call:**
{
  "vendorId": "123",
  "lineItems": [
    { "amount": 3200.00, "description": "Software development - 160 hours @ $20/hr" },
    { "amount": 1500.00, "description": "Cloud hosting services" }
  ],
  "dueDate": "2025-02-15",
  "docNumber": "INV-2512-036"
}

The tool automatically:
- Uses expense account "7" (Expenses) by default
- Sets DetailType to "AccountBasedExpenseLineDetail"
- Formats VendorRef correctly`,
  schema: createBillSchema,
  handler: async (args: any) => {
    const input = (args.params ?? {}) as z.infer<typeof createBillSchema>;
    
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
      accountId: item.accountId ?? item.AccountId ?? "7",
    }));
    
    // Transform to QuickBooks API format
    const billData: Record<string, any> = {
      VendorRef: { value: input.vendorId },
      Line: normalizedLineItems.map((item: any) => ({
        Amount: item.amount,
        DetailType: "AccountBasedExpenseLineDetail",
        AccountBasedExpenseLineDetail: {
          AccountRef: { value: item.accountId || "7" }  // Default to Expenses account
        },
        Description: item.description || ""
      }))
    };
    
    if (input.dueDate) billData.DueDate = input.dueDate;
    if (input.docNumber) billData.DocNumber = input.docNumber;
    if (input.txnDate) billData.TxnDate = input.txnDate;
    
    const response = await createQuickbooksBill(billData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error creating bill: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'Bill');
    return {
      content: [
        { type: "text" as const, text: `Bill created successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};

// Update Bill Tool
const updateBillSchema = z.object({
  Id: z.string().describe("The ID of the bill to update"),
  SyncToken: z.string().describe("The sync token of the bill"),
  VendorRef: z.object({
    value: z.string(),
    name: z.string().optional(),
  }).optional(),
  Line: z.array(z.any()).optional(),
  TxnDate: z.string().optional(),
  DueDate: z.string().optional(),
});

export const UpdateBillTool: ToolDefinition<typeof updateBillSchema> = {
  name: "qbo_update_bill",
  description: "Update an existing bill in QuickBooks Online.",
  schema: updateBillSchema,
  handler: async (args: any) => {
    const billData = (args.params ?? {}) as z.infer<typeof updateBillSchema>;
    const response = await updateQuickbooksBill(billData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error updating bill: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'Bill');
    return {
      content: [
        { type: "text" as const, text: `Bill updated successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};

// Delete Bill Tool
const deleteBillSchema = z.object({
  Id: z.string().describe("The ID of the bill to delete"),
  SyncToken: z.string().describe("The sync token of the bill"),
});

export const DeleteBillTool: ToolDefinition<typeof deleteBillSchema> = {
  name: "qbo_delete_bill",
  description: "Delete a bill from QuickBooks Online.",
  schema: deleteBillSchema,
  handler: async (args: any) => {
    const { Id, SyncToken } = (args.params ?? {}) as z.infer<typeof deleteBillSchema>;
    const response = await deleteQuickbooksBill({ Id, SyncToken });

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error deleting bill: ${response.error}` }],
      };
    }
    return {
      content: [{ type: "text" as const, text: "Bill deleted successfully." }],
    };
  },
};
