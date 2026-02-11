import { z } from "zod";
import { ToolDefinition } from "../types/tool-definition.js";
import {
  searchQuickbooksBillPayments,
  getQuickbooksBillPayment,
  createQuickbooksBillPayment,
  updateQuickbooksBillPayment,
  deleteQuickbooksBillPayment,
} from "../handlers/bill-payment.handler.js";
import { summarizeBillPayment, summarizeConfirmation } from "../utils/summarizers.js";

// Search Bill Payments Tool
const searchBillPaymentsSchema = z.object({
  vendorId: z.string().optional().describe("Filter by vendor ID"),
  txnDateFrom: z.string().optional().describe("Filter by transaction date (from) - format YYYY-MM-DD"),
  txnDateTo: z.string().optional().describe("Filter by transaction date (to) - format YYYY-MM-DD"),
});

export const SearchBillPaymentsTool: ToolDefinition<typeof searchBillPaymentsSchema> = {
  name: "qbo_search_bill_payments",
  description: "Search bill payments in QuickBooks Online. Use vendorId to find payments to a specific vendor.",
  schema: searchBillPaymentsSchema,
  handler: async (args: any) => {
    const params = (args.params ?? {}) as z.infer<typeof searchBillPaymentsSchema>;
    const criteria: any = {};
    if (params.vendorId) criteria.vendorId = params.vendorId;
    if (params.txnDateFrom) criteria.txnDateFrom = params.txnDateFrom;
    if (params.txnDateTo) criteria.txnDateTo = params.txnDateTo;
    
    const response = await searchQuickbooksBillPayments(criteria);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error searching bill payments: ${response.error}` }],
      };
    }
    const payments = response.result;
    const summaries = payments?.map((p: any) => summarizeBillPayment(p)) || [];
    return {
      content: [
        { type: "text" as const, text: `Found ${payments?.length || 0} bill payments: ${JSON.stringify(summaries)}` },
      ],
    };
  },
};

// Get Bill Payment Tool
const getBillPaymentSchema = z.object({
  id: z.string().describe("The ID of the bill payment to retrieve"),
});

export const GetBillPaymentTool: ToolDefinition<typeof getBillPaymentSchema> = {
  name: "qbo_get_bill_payment",
  description: "Get a single bill payment by ID from QuickBooks Online.",
  schema: getBillPaymentSchema,
  handler: async (args: any) => {
    const { id } = (args.params ?? {}) as z.infer<typeof getBillPaymentSchema>;
    const response = await getQuickbooksBillPayment(id);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error getting bill payment: ${response.error}` }],
      };
    }
    const summary = summarizeBillPayment(response.result);
    return {
      content: [{ type: "text" as const, text: JSON.stringify(summary) }],
    };
  },
};

// Create Bill Payment Tool
const createBillPaymentSchema = z.object({
  VendorRef: z.object({
    value: z.string().describe("Vendor ID"),
    name: z.string().optional(),
  }).describe("Reference to the vendor"),
  PayType: z.enum(["Check", "CreditCard"]).describe("Type of payment"),
  TotalAmt: z.number().describe("Total payment amount"),
  Line: z.array(z.object({
    Amount: z.number().describe("Amount to apply to this bill"),
    LinkedTxn: z.array(z.object({
      TxnId: z.string().describe("Bill ID"),
      TxnType: z.literal("Bill"),
    })),
  })).describe("Bills to pay"),
  CheckPayment: z.object({
    BankAccountRef: z.object({
      value: z.string(),
      name: z.string().optional(),
    }),
  }).optional().describe("Check payment details (required if PayType is Check)"),
  CreditCardPayment: z.object({
    CCAccountRef: z.object({
      value: z.string(),
      name: z.string().optional(),
    }),
  }).optional().describe("Credit card payment details (required if PayType is CreditCard)"),
  TxnDate: z.string().optional().describe("Transaction date (YYYY-MM-DD)"),
  DocNumber: z.string().optional().describe("Payment reference number"),
});

export const CreateBillPaymentTool: ToolDefinition<typeof createBillPaymentSchema> = {
  name: "qbo_create_bill_payment",
  description: "Create a new bill payment in QuickBooks Online to pay vendor bills.",
  schema: createBillPaymentSchema,
  handler: async (args: any) => {
    const billPaymentData = (args.params ?? {}) as z.infer<typeof createBillPaymentSchema>;
    const response = await createQuickbooksBillPayment(billPaymentData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error creating bill payment: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'BillPayment');
    return {
      content: [
        { type: "text" as const, text: `Bill payment created successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};

// Update Bill Payment Tool
const updateBillPaymentSchema = z.object({
  Id: z.string().describe("The ID of the bill payment to update"),
  SyncToken: z.string().describe("The sync token of the bill payment"),
  TotalAmt: z.number().optional(),
  Line: z.array(z.any()).optional(),
  TxnDate: z.string().optional(),
});

export const UpdateBillPaymentTool: ToolDefinition<typeof updateBillPaymentSchema> = {
  name: "qbo_update_bill_payment",
  description: "Update an existing bill payment in QuickBooks Online.",
  schema: updateBillPaymentSchema,
  handler: async (args: any) => {
    const billPaymentData = (args.params ?? {}) as z.infer<typeof updateBillPaymentSchema>;
    const response = await updateQuickbooksBillPayment(billPaymentData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error updating bill payment: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'BillPayment');
    return {
      content: [
        { type: "text" as const, text: `Bill payment updated successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};

// Delete Bill Payment Tool
const deleteBillPaymentSchema = z.object({
  Id: z.string().describe("The ID of the bill payment to delete"),
  SyncToken: z.string().describe("The sync token of the bill payment"),
});

export const DeleteBillPaymentTool: ToolDefinition<typeof deleteBillPaymentSchema> = {
  name: "qbo_delete_bill_payment",
  description: "Delete a bill payment from QuickBooks Online.",
  schema: deleteBillPaymentSchema,
  handler: async (args: any) => {
    const { Id, SyncToken } = (args.params ?? {}) as z.infer<typeof deleteBillPaymentSchema>;
    const response = await deleteQuickbooksBillPayment({ Id, SyncToken });

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error deleting bill payment: ${response.error}` }],
      };
    }
    return {
      content: [{ type: "text" as const, text: "Bill payment deleted successfully." }],
    };
  },
};
