import { z } from "zod";
import { ToolDefinition } from "../types/tool-definition.js";
import {
  searchQuickbooksCustomers,
  getQuickbooksCustomer,
  createQuickbooksCustomer,
  updateQuickbooksCustomer,
  deleteQuickbooksCustomer,
} from "../handlers/customer.handler.js";
import { summarizeCustomer, summarizeCustomerDetail, summarizeConfirmation } from "../utils/summarizers.js";

// Search Customers Tool
const searchCustomersSchema = z.object({
  criteria: z
    .array(
      z.object({
        field: z.string().describe("Field to filter on (e.g., DisplayName, GivenName, FamilyName, CompanyName, Balance, Active)"),
        value: z.union([z.string(), z.boolean(), z.number()]),
        operator: z.enum(["=", "<", ">", "<=", ">=", "LIKE", "IN"]).optional(),
      })
    )
    .optional()
    .describe("Filters to apply to the search"),
  limit: z.number().optional().describe("Maximum number of results to return"),
  offset: z.number().optional().describe("Number of results to skip"),
  asc: z.string().optional().describe("Field to sort ascending by"),
  desc: z.string().optional().describe("Field to sort descending by"),
});

export const SearchCustomersTool: ToolDefinition<typeof searchCustomersSchema> = {
  name: "qbo_search_customers",
  description: "Search customers in QuickBooks Online. Returns a list of customers matching the specified criteria.",
  schema: searchCustomersSchema,
  handler: async (args: any) => {
    const { criteria = [], ...options } = (args.params ?? {}) as z.infer<typeof searchCustomersSchema>;
    
    let criteriaToSend: any;
    if (Array.isArray(criteria) && criteria.length > 0) {
      criteriaToSend = [...criteria, ...Object.entries(options).map(([key, value]) => ({ field: key, value }))];
    } else {
      criteriaToSend = { ...options };
    }

    const response = await searchQuickbooksCustomers(criteriaToSend);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error searching customers: ${response.error}` }],
      };
    }
    
    // Return summarized data to reduce token usage
    const customers = Array.isArray(response.result) ? response.result : [];
    const summaries = customers.map((c: any) => summarizeCustomer(c));
    
    return {
      content: [
        { type: "text" as const, text: `Found ${customers.length} customers: ${JSON.stringify(summaries)}` },
      ],
    };
  },
};

// Get Customer Tool
const getCustomerSchema = z.object({
  id: z.string().describe("The ID of the customer to retrieve"),
});

export const GetCustomerTool: ToolDefinition<typeof getCustomerSchema> = {
  name: "qbo_get_customer",
  description: "Get a single customer by ID from QuickBooks Online.",
  schema: getCustomerSchema,
  handler: async (args: any) => {
    const { id } = (args.params ?? {}) as z.infer<typeof getCustomerSchema>;
    const response = await getQuickbooksCustomer(id);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error getting customer: ${response.error}` }],
      };
    }
    const detail = summarizeCustomerDetail(response.result);
    return {
      content: [{ type: "text" as const, text: JSON.stringify(detail) }],
    };
  },
};

// Create Customer Tool
const createCustomerSchema = z.object({
  displayName: z.string().describe("Display name of the customer (required)"),
  email: z.string().optional().describe("Primary email address"),
  phone: z.string().optional().describe("Primary phone number"),
  companyName: z.string().optional().describe("Company name"),
});

export const CreateCustomerTool: ToolDefinition<typeof createCustomerSchema> = {
  name: "qbo_create_customer",
  description: `Create a new customer in QuickBooks Online, or return existing customer if one with the same name exists.

This tool is SAFE to call even if the customer already exists - it will automatically:
1. Search for existing customer with same displayName
2. If found, return the existing customer ID
3. If not found, create new customer and return the new ID

**Example:** { "displayName": "Cay Digital LLC", "email": "info@caydigital.com" }`,
  schema: createCustomerSchema,
  handler: async (args: any) => {
    const input = (args.params ?? {}) as z.infer<typeof createCustomerSchema>;
    
    // First, search for existing customer to avoid duplicates
    const searchResponse = await searchQuickbooksCustomers({ displayName: input.displayName });
    
    if (!searchResponse.isError && searchResponse.result && searchResponse.result.length > 0) {
      // Found existing customer - return it
      const existingCustomer = searchResponse.result[0];
      const confirmation = summarizeConfirmation(existingCustomer, 'Customer');
      return {
        content: [
          { type: "text" as const, text: `Customer already exists: ${JSON.stringify(confirmation)}` },
        ],
      };
    }
    
    // Transform to QuickBooks API format
    const customerData: Record<string, any> = {
      DisplayName: input.displayName,
    };
    if (input.email) customerData.PrimaryEmailAddr = { Address: input.email };
    if (input.phone) customerData.PrimaryPhone = { FreeFormNumber: input.phone };
    if (input.companyName) customerData.CompanyName = input.companyName;
    
    // No existing customer found - create new one
    const response = await createQuickbooksCustomer(customerData);

    if (response.isError) {
      // Check if it's a duplicate error and try to fetch the existing customer
      if (response.error && response.error.includes("Duplicate")) {
        const retrySearch = await searchQuickbooksCustomers({ displayName: input.displayName });
        if (!retrySearch.isError && retrySearch.result && retrySearch.result.length > 0) {
          const existingCustomer = retrySearch.result[0];
          const confirmation = summarizeConfirmation(existingCustomer, 'Customer');
          return {
            content: [
              { type: "text" as const, text: `Customer already exists: ${JSON.stringify(confirmation)}` },
            ],
          };
        }
      }
      return {
        content: [{ type: "text" as const, text: `Error creating customer: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'Customer');
    return {
      content: [
        { type: "text" as const, text: `Customer created successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};

// Update Customer Tool
const updateCustomerSchema = z.object({
  Id: z.string().describe("The ID of the customer to update (required)"),
  SyncToken: z.string().describe("The sync token of the customer (required for updates)"),
  DisplayName: z.string().optional().describe("Display name of the customer"),
  GivenName: z.string().optional().describe("First name of the customer"),
  FamilyName: z.string().optional().describe("Last name of the customer"),
  CompanyName: z.string().optional().describe("Company name"),
  PrimaryEmailAddr: z.object({ Address: z.string() }).optional().describe("Primary email address"),
  PrimaryPhone: z.object({ FreeFormNumber: z.string() }).optional().describe("Primary phone number"),
  Active: z.boolean().optional().describe("Whether the customer is active"),
});

export const UpdateCustomerTool: ToolDefinition<typeof updateCustomerSchema> = {
  name: "qbo_update_customer",
  description: "Update an existing customer in QuickBooks Online. Requires the Id and SyncToken.",
  schema: updateCustomerSchema,
  handler: async (args: any) => {
    const customerData = (args.params ?? {}) as z.infer<typeof updateCustomerSchema>;
    const response = await updateQuickbooksCustomer(customerData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error updating customer: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'Customer');
    return {
      content: [
        { type: "text" as const, text: `Customer updated successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};

// Delete Customer Tool
const deleteCustomerSchema = z.object({
  Id: z.string().describe("The ID of the customer to delete (required)"),
  SyncToken: z.string().describe("The sync token of the customer (required)"),
});

export const DeleteCustomerTool: ToolDefinition<typeof deleteCustomerSchema> = {
  name: "qbo_delete_customer",
  description: "Delete (deactivate) a customer in QuickBooks Online. This sets the customer to inactive.",
  schema: deleteCustomerSchema,
  handler: async (args: any) => {
    const { Id, SyncToken } = (args.params ?? {}) as z.infer<typeof deleteCustomerSchema>;
    const response = await deleteQuickbooksCustomer({ Id, SyncToken });

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error deleting customer: ${response.error}` }],
      };
    }
    return {
      content: [{ type: "text" as const, text: "Customer deactivated successfully." }],
    };
  },
};
