import { z } from "zod";
import { ToolDefinition } from "../types/tool-definition.js";
import {
  searchQuickbooksVendors,
  getQuickbooksVendor,
  createQuickbooksVendor,
  updateQuickbooksVendor,
  deleteQuickbooksVendor,
} from "../handlers/vendor.handler.js";
import { summarizeVendor, summarizeVendorDetail, summarizeConfirmation } from "../utils/summarizers.js";

// Search Vendors Tool
const searchVendorsSchema = z.object({
  displayName: z.string().optional().describe("Filter by vendor display name (partial match)"),
  companyName: z.string().optional().describe("Filter by company name"),
  active: z.boolean().optional().describe("Filter by active status"),
});

export const SearchVendorsTool: ToolDefinition<typeof searchVendorsSchema> = {
  name: "qbo_search_vendors",
  description: "Search vendors/suppliers in QuickBooks Online. Use filters to narrow results.",
  schema: searchVendorsSchema,
  handler: async (args: any) => {
    const params = (args.params ?? {}) as z.infer<typeof searchVendorsSchema>;
    const criteria: any = {};
    if (params.displayName) criteria.displayName = params.displayName;
    if (params.companyName) criteria.companyName = params.companyName;
    if (params.active !== undefined) criteria.active = params.active;
    
    const response = await searchQuickbooksVendors(criteria);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error searching vendors: ${response.error}` }],
      };
    }
    const vendors = response.result;
    const summaries = vendors?.map((v: any) => summarizeVendor(v)) || [];
    return {
      content: [
        { type: "text" as const, text: `Found ${vendors?.length || 0} vendors: ${JSON.stringify(summaries)}` },
      ],
    };
  },
};

// Get Vendor Tool
const getVendorSchema = z.object({
  id: z.string().describe("The ID of the vendor to retrieve"),
});

export const GetVendorTool: ToolDefinition<typeof getVendorSchema> = {
  name: "qbo_get_vendor",
  description: "Get a single vendor by ID from QuickBooks Online.",
  schema: getVendorSchema,
  handler: async (args: any) => {
    const { id } = (args.params ?? {}) as z.infer<typeof getVendorSchema>;
    const response = await getQuickbooksVendor(id);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error getting vendor: ${response.error}` }],
      };
    }
    const detail = summarizeVendorDetail(response.result);
    return {
      content: [{ type: "text" as const, text: JSON.stringify(detail) }],
    };
  },
};

// Create Vendor Tool
const createVendorSchema = z.object({
  displayName: z.string().describe("Display name of the vendor (required)"),
  givenName: z.string().optional().describe("First name"),
  familyName: z.string().optional().describe("Last name"),
  companyName: z.string().optional().describe("Company name"),
  email: z.string().optional().describe("Primary email address"),
  phone: z.string().optional().describe("Primary phone number"),
});

export const CreateVendorTool: ToolDefinition<typeof createVendorSchema> = {
  name: "qbo_create_vendor",
  description: `Create a new vendor in QuickBooks Online, or return existing vendor if one with the same name exists.

This tool is SAFE to call even if the vendor already exists - it will automatically:
1. Search for existing vendor with same displayName
2. If found, return the existing vendor ID
3. If not found, create new vendor and return the new ID

**Example:** { "displayName": "U1 Software LLC" }`,
  schema: createVendorSchema,
  handler: async (args: any) => {
    const vendorData = (args.params ?? {}) as z.infer<typeof createVendorSchema>;
    
    // First, search for existing vendor to avoid duplicates
    const searchResponse = await searchQuickbooksVendors({ displayName: vendorData.displayName });
    
    if (!searchResponse.isError && searchResponse.result && searchResponse.result.length > 0) {
      // Found existing vendor - return it
      const existingVendor = searchResponse.result[0];
      const confirmation = summarizeConfirmation(existingVendor, 'Vendor');
      return {
        content: [
          { type: "text" as const, text: `Vendor already exists: ${JSON.stringify(confirmation)}` },
        ],
      };
    }
    
    // No existing vendor found - create new one
    const response = await createQuickbooksVendor(vendorData);

    if (response.isError) {
      // Check if it's a duplicate error and try to fetch the existing vendor
      if (response.error && response.error.includes("Duplicate")) {
        // Extract vendor ID from error message if available (e.g., "Id=97")
        const idMatch = response.error.match(/Id=(\d+)/);
        if (idMatch) {
          // Fetch the vendor by ID directly
          const vendorById = await getQuickbooksVendor(idMatch[1]);
          if (!vendorById.isError && vendorById.result) {
            const existingVendor = vendorById.result;
            const confirmation = summarizeConfirmation(existingVendor, 'Vendor');
            return {
              content: [
                { type: "text" as const, text: `Found existing vendor with similar name (ID ${idMatch[1]}): ${JSON.stringify(confirmation)}. QuickBooks detected a name conflict. Please use this existing vendor or provide a different name.` },
              ],
            };
          }
        }
        
        // Fallback: Try partial match search
        const retrySearch = await searchQuickbooksVendors({ displayName: vendorData.displayName });
        if (!retrySearch.isError && retrySearch.result && retrySearch.result.length > 0) {
          const existingVendor = retrySearch.result[0];
          const confirmation = summarizeConfirmation(existingVendor, 'Vendor');
          return {
            content: [
              { type: "text" as const, text: `Vendor already exists: ${JSON.stringify(confirmation)}` },
            ],
          };
        }
      }
      return {
        content: [{ type: "text" as const, text: `Error creating vendor: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'Vendor');
    return {
      content: [
        { type: "text" as const, text: `Vendor created successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};

// Update Vendor Tool
const updateVendorSchema = z.object({
  Id: z.string().describe("The ID of the vendor to update"),
  SyncToken: z.string().describe("The sync token of the vendor"),
  DisplayName: z.string().optional(),
  GivenName: z.string().optional(),
  FamilyName: z.string().optional(),
  CompanyName: z.string().optional(),
  Active: z.boolean().optional(),
});

export const UpdateVendorTool: ToolDefinition<typeof updateVendorSchema> = {
  name: "qbo_update_vendor",
  description: "Update an existing vendor in QuickBooks Online.",
  schema: updateVendorSchema,
  handler: async (args: any) => {
    const vendorData = (args.params ?? {}) as z.infer<typeof updateVendorSchema>;
    const response = await updateQuickbooksVendor(vendorData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error updating vendor: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'Vendor');
    return {
      content: [
        { type: "text" as const, text: `Vendor updated successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};

// Delete Vendor Tool
const deleteVendorSchema = z.object({
  Id: z.string().describe("The ID of the vendor to delete"),
  SyncToken: z.string().describe("The sync token of the vendor"),
});

export const DeleteVendorTool: ToolDefinition<typeof deleteVendorSchema> = {
  name: "qbo_delete_vendor",
  description: "Delete (deactivate) a vendor in QuickBooks Online.",
  schema: deleteVendorSchema,
  handler: async (args: any) => {
    const { Id, SyncToken } = (args.params ?? {}) as z.infer<typeof deleteVendorSchema>;
    const response = await deleteQuickbooksVendor({ Id, SyncToken });

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error deleting vendor: ${response.error}` }],
      };
    }
    return {
      content: [{ type: "text" as const, text: "Vendor deactivated successfully." }],
    };
  },
};
