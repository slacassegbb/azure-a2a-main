import { z } from "zod";
import { ToolDefinition } from "../types/tool-definition.js";
import {
  searchQuickbooksItems,
  getQuickbooksItem,
  createQuickbooksItem,
  updateQuickbooksItem,
} from "../handlers/item.handler.js";
import { summarizeItem, summarizeItemDetail, summarizeConfirmation } from "../utils/summarizers.js";

// Search Items Tool
const searchItemsSchema = z.object({
  name: z.string().optional().describe("Filter by item name (partial match supported)"),
  type: z.enum(["Inventory", "Service", "NonInventory"]).optional().describe("Filter by item type"),
  active: z.boolean().optional().describe("Filter by active status (true/false)"),
});

export const SearchItemsTool: ToolDefinition<typeof searchItemsSchema> = {
  name: "qbo_search_items",
  description: "Search products/services (items) in QuickBooks Online. Use filters to narrow results. To find all service items, use type='Service'.",
  schema: searchItemsSchema,
  handler: async (args: any) => {
    const params = (args.params ?? {}) as z.infer<typeof searchItemsSchema>;
    // Convert to criteria format expected by handler
    const criteria: any = {};
    if (params.name) criteria.name = params.name;
    if (params.type) criteria.type = params.type;
    if (params.active !== undefined) criteria.active = params.active;
    
    const response = await searchQuickbooksItems(criteria);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error searching items: ${response.error}` }],
      };
    }
    const items = response.result;
    const summaries = items?.map((item: any) => summarizeItem(item)) || [];
    return {
      content: [
        { type: "text" as const, text: `Found ${items?.length || 0} items: ${JSON.stringify(summaries)}` },
      ],
    };
  },
};

// Get Item Tool
const getItemSchema = z.object({
  id: z.string().describe("The ID of the item to retrieve"),
});

export const GetItemTool: ToolDefinition<typeof getItemSchema> = {
  name: "qbo_get_item",
  description: "Get a single item (product/service) by ID from QuickBooks Online.",
  schema: getItemSchema,
  handler: async (args: any) => {
    const { id } = (args.params ?? {}) as z.infer<typeof getItemSchema>;
    const response = await getQuickbooksItem(id);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error getting item: ${response.error}` }],
      };
    }
    const detail = summarizeItemDetail(response.result);
    return {
      content: [{ type: "text" as const, text: JSON.stringify(detail) }],
    };
  },
};

// Create Item Tool
const createItemSchema = z.object({
  Name: z.string().describe("Name of the item (required)"),
  Type: z.enum(["Inventory", "Service", "NonInventory"]).describe("Type of item"),
  IncomeAccountRef: z.object({
    value: z.string().describe("Income account ID"),
    name: z.string().optional(),
  }).optional().describe("Income account reference"),
  ExpenseAccountRef: z.object({
    value: z.string().describe("Expense account ID"),
    name: z.string().optional(),
  }).optional().describe("Expense account reference (for inventory items)"),
  AssetAccountRef: z.object({
    value: z.string().describe("Asset account ID"),
    name: z.string().optional(),
  }).optional().describe("Asset account reference (for inventory items)"),
  UnitPrice: z.number().optional().describe("Unit price"),
  PurchaseCost: z.number().optional().describe("Purchase cost"),
  QtyOnHand: z.number().optional().describe("Quantity on hand (for inventory items)"),
  InvStartDate: z.string().optional().describe("Inventory start date (YYYY-MM-DD)"),
  Description: z.string().optional().describe("Description"),
  PurchaseDesc: z.string().optional().describe("Purchase description"),
  Taxable: z.boolean().optional().describe("Whether the item is taxable"),
  Sku: z.string().optional().describe("SKU"),
});

export const CreateItemTool: ToolDefinition<typeof createItemSchema> = {
  name: "qbo_create_item",
  description: "Create a new item (product/service) in QuickBooks Online.",
  schema: createItemSchema,
  handler: async (args: any) => {
    const itemData = (args.params ?? {}) as z.infer<typeof createItemSchema>;
    const response = await createQuickbooksItem(itemData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error creating item: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'Item');
    return {
      content: [
        { type: "text" as const, text: `Item created successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};

// Update Item Tool
const updateItemSchema = z.object({
  Id: z.string().describe("The ID of the item to update"),
  SyncToken: z.string().describe("The sync token of the item"),
  Name: z.string().optional().describe("Name of the item"),
  UnitPrice: z.number().optional().describe("Unit price"),
  PurchaseCost: z.number().optional().describe("Purchase cost"),
  Description: z.string().optional().describe("Description"),
  Active: z.boolean().optional().describe("Whether the item is active"),
});

export const UpdateItemTool: ToolDefinition<typeof updateItemSchema> = {
  name: "qbo_update_item",
  description: "Update an existing item in QuickBooks Online.",
  schema: updateItemSchema,
  handler: async (args: any) => {
    const itemData = (args.params ?? {}) as z.infer<typeof updateItemSchema>;
    const response = await updateQuickbooksItem(itemData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error updating item: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'Item');
    return {
      content: [
        { type: "text" as const, text: `Item updated successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};
