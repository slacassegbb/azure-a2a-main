import { z } from "zod";
import { ToolDefinition } from "../types/tool-definition.js";
import {
  searchQuickbooksPurchases,
  getQuickbooksPurchase,
  createQuickbooksPurchase,
  updateQuickbooksPurchase,
  deleteQuickbooksPurchase,
} from "../handlers/purchase.handler.js";
import { summarizePurchase, summarizeConfirmation } from "../utils/summarizers.js";

// Search Purchases Tool
const searchPurchasesSchema = z.object({
  accountId: z.string().optional().describe("Filter by account ID (bank/credit card)"),
  vendorId: z.string().optional().describe("Filter by vendor ID"),
  txnDateFrom: z.string().optional().describe("Filter by transaction date (from) - format YYYY-MM-DD"),
  txnDateTo: z.string().optional().describe("Filter by transaction date (to) - format YYYY-MM-DD"),
  paymentType: z.enum(["Cash", "Check", "CreditCard"]).optional().describe("Filter by payment type"),
});

export const SearchPurchasesTool: ToolDefinition<typeof searchPurchasesSchema> = {
  name: "qbo_search_purchases",
  description: "Search purchases (checks, credit card charges, cash purchases) in QuickBooks Online.",
  schema: searchPurchasesSchema,
  handler: async (args: any) => {
    const params = (args.params ?? {}) as z.infer<typeof searchPurchasesSchema>;
    const criteria: any = {};
    if (params.accountId) criteria.accountId = params.accountId;
    if (params.vendorId) criteria.vendorId = params.vendorId;
    if (params.txnDateFrom) criteria.txnDateFrom = params.txnDateFrom;
    if (params.txnDateTo) criteria.txnDateTo = params.txnDateTo;
    if (params.paymentType) criteria.paymentType = params.paymentType;
    
    const response = await searchQuickbooksPurchases(criteria);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error searching purchases: ${response.error}` }],
      };
    }
    const purchases = response.result;
    const summaries = purchases?.map((p: any) => summarizePurchase(p)) || [];
    return {
      content: [
        { type: "text" as const, text: `Found ${purchases?.length || 0} purchases: ${JSON.stringify(summaries)}` },
      ],
    };
  },
};

// Get Purchase Tool
const getPurchaseSchema = z.object({
  id: z.string().describe("The ID of the purchase to retrieve"),
});

export const GetPurchaseTool: ToolDefinition<typeof getPurchaseSchema> = {
  name: "qbo_get_purchase",
  description: "Get a single purchase by ID from QuickBooks Online.",
  schema: getPurchaseSchema,
  handler: async (args: any) => {
    const { id } = (args.params ?? {}) as z.infer<typeof getPurchaseSchema>;
    const response = await getQuickbooksPurchase(id);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error getting purchase: ${response.error}` }],
      };
    }
    const summary = summarizePurchase(response.result);
    return {
      content: [{ type: "text" as const, text: JSON.stringify(summary) }],
    };
  },
};

// Create Purchase Tool
const createPurchaseSchema = z.object({
  PaymentType: z.enum(["Cash", "Check", "CreditCard"]).describe("Type of payment"),
  AccountRef: z.object({
    value: z.string().describe("Account ID (bank or credit card account)"),
    name: z.string().optional(),
  }).describe("Account to pay from"),
  Line: z.array(z.object({
    Amount: z.number().describe("Line amount"),
    DetailType: z.enum(["AccountBasedExpenseLineDetail", "ItemBasedExpenseLineDetail"]).describe("Type of line detail"),
    AccountBasedExpenseLineDetail: z.object({
      AccountRef: z.object({
        value: z.string(),
        name: z.string().optional(),
      }),
    }).optional(),
    ItemBasedExpenseLineDetail: z.object({
      ItemRef: z.object({
        value: z.string(),
        name: z.string().optional(),
      }),
      Qty: z.number().optional(),
      UnitPrice: z.number().optional(),
    }).optional(),
    Description: z.string().optional(),
  })).describe("Purchase line items"),
  EntityRef: z.object({
    value: z.string(),
    name: z.string().optional(),
    type: z.enum(["Vendor", "Customer", "Employee"]).optional(),
  }).optional().describe("Reference to vendor, customer, or employee"),
  TxnDate: z.string().optional().describe("Transaction date (YYYY-MM-DD)"),
  DocNumber: z.string().optional().describe("Check/reference number"),
});

export const CreatePurchaseTool: ToolDefinition<typeof createPurchaseSchema> = {
  name: "qbo_create_purchase",
  description: "Create a new purchase (check, cash purchase, credit card charge) in QuickBooks Online.",
  schema: createPurchaseSchema,
  handler: async (args: any) => {
    const purchaseData = (args.params ?? {}) as z.infer<typeof createPurchaseSchema>;
    const response = await createQuickbooksPurchase(purchaseData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error creating purchase: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'Purchase');
    return {
      content: [
        { type: "text" as const, text: `Purchase created successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};

// Update Purchase Tool
const updatePurchaseSchema = z.object({
  Id: z.string().describe("The ID of the purchase to update"),
  SyncToken: z.string().describe("The sync token of the purchase"),
  Line: z.array(z.any()).optional(),
  TxnDate: z.string().optional(),
  DocNumber: z.string().optional(),
});

export const UpdatePurchaseTool: ToolDefinition<typeof updatePurchaseSchema> = {
  name: "qbo_update_purchase",
  description: "Update an existing purchase in QuickBooks Online.",
  schema: updatePurchaseSchema,
  handler: async (args: any) => {
    const purchaseData = (args.params ?? {}) as z.infer<typeof updatePurchaseSchema>;
    const response = await updateQuickbooksPurchase(purchaseData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error updating purchase: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'Purchase');
    return {
      content: [
        { type: "text" as const, text: `Purchase updated successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};

// Delete Purchase Tool
const deletePurchaseSchema = z.object({
  Id: z.string().describe("The ID of the purchase to delete"),
  SyncToken: z.string().describe("The sync token of the purchase"),
});

export const DeletePurchaseTool: ToolDefinition<typeof deletePurchaseSchema> = {
  name: "qbo_delete_purchase",
  description: "Delete a purchase from QuickBooks Online.",
  schema: deletePurchaseSchema,
  handler: async (args: any) => {
    const { Id, SyncToken } = (args.params ?? {}) as z.infer<typeof deletePurchaseSchema>;
    const response = await deleteQuickbooksPurchase({ Id, SyncToken });

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error deleting purchase: ${response.error}` }],
      };
    }
    return {
      content: [{ type: "text" as const, text: "Purchase deleted successfully." }],
    };
  },
};
