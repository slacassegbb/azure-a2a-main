import { z } from "zod";
import { ToolDefinition } from "../types/tool-definition.js";
import {
  searchQuickbooksAccounts,
  getQuickbooksAccount,
  createQuickbooksAccount,
  updateQuickbooksAccount,
} from "../handlers/account.handler.js";
import { summarizeAccount, summarizeAccountDetail, summarizeConfirmation } from "../utils/summarizers.js";

// Search Accounts Tool
const searchAccountsSchema = z.object({
  name: z.string().optional().describe("Filter by account name (partial match)"),
  accountType: z.enum([
    "Bank", "Accounts Receivable", "Other Current Asset", "Fixed Asset", "Other Asset",
    "Accounts Payable", "Credit Card", "Other Current Liability", "Long Term Liability",
    "Equity", "Income", "Cost of Goods Sold", "Expense", "Other Income", "Other Expense"
  ]).optional().describe("Filter by account type (e.g., 'Income', 'Expense', 'Bank')"),
  active: z.boolean().optional().describe("Filter by active status"),
});

export const SearchAccountsTool: ToolDefinition<typeof searchAccountsSchema> = {
  name: "qbo_search_accounts",
  description: "Search chart of accounts in QuickBooks Online. Use accountType filter to find specific account types (e.g., 'Income' for revenue accounts).",
  schema: searchAccountsSchema,
  handler: async (args: any) => {
    const params = (args.params ?? {}) as z.infer<typeof searchAccountsSchema>;
    // Convert to criteria format expected by handler
    const criteria: any = {};
    if (params.name) criteria.name = params.name;
    if (params.accountType) criteria.accountType = params.accountType;
    if (params.active !== undefined) criteria.active = params.active;
    
    const response = await searchQuickbooksAccounts(criteria);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error searching accounts: ${response.error}` }],
      };
    }
    const accounts = response.result;
    const summaries = accounts?.map((acc: any) => summarizeAccount(acc)) || [];
    return {
      content: [
        { type: "text" as const, text: `Found ${accounts?.length || 0} accounts: ${JSON.stringify(summaries)}` },
      ],
    };
  },
};

// Get Account Tool
const getAccountSchema = z.object({
  id: z.string().describe("The ID of the account to retrieve"),
});

export const GetAccountTool: ToolDefinition<typeof getAccountSchema> = {
  name: "qbo_get_account",
  description: "Get a single account by ID from QuickBooks Online.",
  schema: getAccountSchema,
  handler: async (args: any) => {
    const { id } = (args.params ?? {}) as z.infer<typeof getAccountSchema>;
    const response = await getQuickbooksAccount(id);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error getting account: ${response.error}` }],
      };
    }
    const detail = summarizeAccountDetail(response.result);
    return {
      content: [{ type: "text" as const, text: JSON.stringify(detail) }],
    };
  },
};

// Create Account Tool
const createAccountSchema = z.object({
  Name: z.string().describe("Name of the account (required)"),
  AccountType: z.enum([
    "Bank", "Accounts Receivable", "Other Current Asset", "Fixed Asset",
    "Other Asset", "Accounts Payable", "Credit Card", "Other Current Liability",
    "Long Term Liability", "Equity", "Income", "Cost of Goods Sold",
    "Expense", "Other Income", "Other Expense"
  ]).describe("Type of account (required)"),
  AccountSubType: z.string().optional().describe("Subtype of the account"),
  Description: z.string().optional().describe("Description of the account"),
  AcctNum: z.string().optional().describe("Account number"),
  CurrencyRef: z.object({
    value: z.string(),
    name: z.string().optional(),
  }).optional().describe("Currency reference"),
});

export const CreateAccountTool: ToolDefinition<typeof createAccountSchema> = {
  name: "qbo_create_account",
  description: "Create a new account in QuickBooks Online chart of accounts.",
  schema: createAccountSchema,
  handler: async (args: any) => {
    const accountData = (args.params ?? {}) as z.infer<typeof createAccountSchema>;
    const response = await createQuickbooksAccount(accountData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error creating account: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'Account');
    return {
      content: [
        { type: "text" as const, text: `Account created successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};

// Update Account Tool
const updateAccountSchema = z.object({
  Id: z.string().describe("The ID of the account to update"),
  SyncToken: z.string().describe("The sync token of the account"),
  Name: z.string().optional().describe("Name of the account"),
  Description: z.string().optional().describe("Description of the account"),
  AcctNum: z.string().optional().describe("Account number"),
  Active: z.boolean().optional().describe("Whether the account is active"),
});

export const UpdateAccountTool: ToolDefinition<typeof updateAccountSchema> = {
  name: "qbo_update_account",
  description: "Update an existing account in QuickBooks Online.",
  schema: updateAccountSchema,
  handler: async (args: any) => {
    const accountData = (args.params ?? {}) as z.infer<typeof updateAccountSchema>;
    const response = await updateQuickbooksAccount(accountData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error updating account: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'Account');
    return {
      content: [
        { type: "text" as const, text: `Account updated successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};
