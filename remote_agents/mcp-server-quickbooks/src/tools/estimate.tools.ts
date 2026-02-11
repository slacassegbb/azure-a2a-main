import { z } from "zod";
import { ToolDefinition } from "../types/tool-definition.js";
import {
  searchQuickbooksEstimates,
  getQuickbooksEstimate,
  createQuickbooksEstimate,
  updateQuickbooksEstimate,
  deleteQuickbooksEstimate,
} from "../handlers/estimate.handler.js";
import { summarizeEstimate, summarizeConfirmation } from "../utils/summarizers.js";

// Search Estimates Tool
const searchEstimatesSchema = z.object({
  customerId: z.string().optional().describe("Filter by customer ID"),
  docNumber: z.string().optional().describe("Filter by estimate/document number"),
  txnDateFrom: z.string().optional().describe("Filter by transaction date (from) - format YYYY-MM-DD"),
  txnDateTo: z.string().optional().describe("Filter by transaction date (to) - format YYYY-MM-DD"),
});

export const SearchEstimatesTool: ToolDefinition<typeof searchEstimatesSchema> = {
  name: "qbo_search_estimates",
  description: "Search estimates/quotes in QuickBooks Online. Use customerId to find estimates for a specific customer.",
  schema: searchEstimatesSchema,
  handler: async (args: any) => {
    const params = (args.params ?? {}) as z.infer<typeof searchEstimatesSchema>;
    const criteria: any = {};
    if (params.customerId) criteria.customerId = params.customerId;
    if (params.docNumber) criteria.docNumber = params.docNumber;
    if (params.txnDateFrom) criteria.txnDateFrom = params.txnDateFrom;
    if (params.txnDateTo) criteria.txnDateTo = params.txnDateTo;
    
    const response = await searchQuickbooksEstimates(criteria);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error searching estimates: ${response.error}` }],
      };
    }
    const estimates = response.result;
    const summaries = estimates?.map((e: any) => summarizeEstimate(e)) || [];
    return {
      content: [
        { type: "text" as const, text: `Found ${estimates?.length || 0} estimates: ${JSON.stringify(summaries)}` },
      ],
    };
  },
};

// Get Estimate Tool
const getEstimateSchema = z.object({
  id: z.string().describe("The ID of the estimate to retrieve"),
});

export const GetEstimateTool: ToolDefinition<typeof getEstimateSchema> = {
  name: "qbo_get_estimate",
  description: "Get a single estimate by ID from QuickBooks Online.",
  schema: getEstimateSchema,
  handler: async (args: any) => {
    const { id } = (args.params ?? {}) as z.infer<typeof getEstimateSchema>;
    const response = await getQuickbooksEstimate(id);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error getting estimate: ${response.error}` }],
      };
    }
    const summary = summarizeEstimate(response.result);
    return {
      content: [{ type: "text" as const, text: JSON.stringify(summary) }],
    };
  },
};

// Create Estimate Tool
const createEstimateSchema = z.object({
  CustomerRef: z.object({
    value: z.string().describe("Customer ID"),
    name: z.string().optional(),
  }).describe("Reference to the customer"),
  Line: z.array(z.object({
    Amount: z.number().describe("Line amount"),
    DetailType: z.string().describe("Type of line detail"),
    SalesItemLineDetail: z.object({
      ItemRef: z.object({
        value: z.string(),
        name: z.string().optional(),
      }),
      Qty: z.number().optional(),
      UnitPrice: z.number().optional(),
    }).optional(),
    Description: z.string().optional(),
  })).describe("Estimate line items"),
  TxnDate: z.string().optional().describe("Transaction date (YYYY-MM-DD)"),
  ExpirationDate: z.string().optional().describe("Expiration date (YYYY-MM-DD)"),
  DocNumber: z.string().optional().describe("Estimate number"),
});

export const CreateEstimateTool: ToolDefinition<typeof createEstimateSchema> = {
  name: "qbo_create_estimate",
  description: "Create a new estimate/quote in QuickBooks Online.",
  schema: createEstimateSchema,
  handler: async (args: any) => {
    const estimateData = (args.params ?? {}) as z.infer<typeof createEstimateSchema>;
    const response = await createQuickbooksEstimate(estimateData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error creating estimate: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'Estimate');
    return {
      content: [
        { type: "text" as const, text: `Estimate created successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};

// Update Estimate Tool
const updateEstimateSchema = z.object({
  Id: z.string().describe("The ID of the estimate to update"),
  SyncToken: z.string().describe("The sync token of the estimate"),
  CustomerRef: z.object({
    value: z.string(),
    name: z.string().optional(),
  }).optional(),
  Line: z.array(z.any()).optional(),
  TxnDate: z.string().optional(),
  ExpirationDate: z.string().optional(),
});

export const UpdateEstimateTool: ToolDefinition<typeof updateEstimateSchema> = {
  name: "qbo_update_estimate",
  description: "Update an existing estimate in QuickBooks Online.",
  schema: updateEstimateSchema,
  handler: async (args: any) => {
    const estimateData = (args.params ?? {}) as z.infer<typeof updateEstimateSchema>;
    const response = await updateQuickbooksEstimate(estimateData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error updating estimate: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'Estimate');
    return {
      content: [
        { type: "text" as const, text: `Estimate updated successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};

// Delete Estimate Tool
const deleteEstimateSchema = z.object({
  Id: z.string().describe("The ID of the estimate to delete"),
  SyncToken: z.string().describe("The sync token of the estimate"),
});

export const DeleteEstimateTool: ToolDefinition<typeof deleteEstimateSchema> = {
  name: "qbo_delete_estimate",
  description: "Delete an estimate from QuickBooks Online.",
  schema: deleteEstimateSchema,
  handler: async (args: any) => {
    const { Id, SyncToken } = (args.params ?? {}) as z.infer<typeof deleteEstimateSchema>;
    const response = await deleteQuickbooksEstimate({ Id, SyncToken });

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error deleting estimate: ${response.error}` }],
      };
    }
    return {
      content: [{ type: "text" as const, text: "Estimate deleted successfully." }],
    };
  },
};
