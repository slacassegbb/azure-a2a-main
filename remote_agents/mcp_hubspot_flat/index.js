#!/usr/bin/env node
/**
 * Flattened HubSpot MCP Server
 * 
 * This wraps the HubSpot API with simplified/flat schemas that work with Azure AI Foundry.
 * Azure AI Foundry has issues with deeply nested JSON schemas, so we flatten them.
 * 
 * Tools provided:
 * - hubspot_get_user_details - Get current user/account details
 * - hubspot_list_objects - List objects of a type
 * - hubspot_search_objects - Search with flattened filter syntax
 * - hubspot_get_object - Get a single object by ID
 * - hubspot_create_object - Create an object
 * - hubspot_update_object - Update an object
 * - hubspot_list_contacts - Convenience method for contacts
 * - hubspot_list_companies - Convenience method for companies
 * - hubspot_list_deals - Convenience method for deals
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const HUBSPOT_ACCESS_TOKEN = process.env.PRIVATE_APP_ACCESS_TOKEN;

if (!HUBSPOT_ACCESS_TOKEN) {
  console.error("ERROR: PRIVATE_APP_ACCESS_TOKEN environment variable is required");
  process.exit(1);
}

// HubSpot API base URL
const HUBSPOT_API_BASE = "https://api.hubapi.com";

// Helper function to make HubSpot API calls
async function hubspotRequest(method, endpoint, body = null) {
  const url = `${HUBSPOT_API_BASE}${endpoint}`;
  const options = {
    method,
    headers: {
      "Authorization": `Bearer ${HUBSPOT_ACCESS_TOKEN}`,
      "Content-Type": "application/json",
    },
  };
  
  if (body) {
    options.body = JSON.stringify(body);
  }
  
  const response = await fetch(url, options);
  
  if (!response.ok) {
    const error = await response.text();
    throw new Error(`HubSpot API error (${response.status}): ${error}`);
  }
  
  return response.json();
}

// Tool definitions with FLAT schemas (no nested objects)
const TOOLS = [
  {
    name: "hubspot_get_user_details",
    description: "Get details about the current HubSpot user and account. Returns user ID, hub ID, permissions, and account info. Use this first to understand the connected account.",
    inputSchema: {
      type: "object",
      properties: {},
      required: [],
    },
  },
  {
    name: "hubspot_list_objects",
    description: "List HubSpot CRM objects of a specific type. Valid object types: contacts, companies, deals, tickets, products, line_items, quotes.",
    inputSchema: {
      type: "object",
      properties: {
        objectType: {
          type: "string",
          description: "The object type to list: contacts, companies, deals, tickets, products, line_items, quotes",
        },
        limit: {
          type: "integer",
          description: "Maximum number of results (1-100, default 10)",
        },
        properties: {
          type: "string",
          description: "Comma-separated list of properties to return (e.g., 'firstname,lastname,email')",
        },
        after: {
          type: "string",
          description: "Pagination cursor from previous response",
        },
      },
      required: ["objectType"],
    },
  },
  {
    name: "hubspot_search_objects",
    description: "Search HubSpot CRM objects with filters. Use simple filter syntax: 'propertyName=value' or 'propertyName>value'. Multiple filters are ANDed together.",
    inputSchema: {
      type: "object",
      properties: {
        objectType: {
          type: "string",
          description: "The object type to search: contacts, companies, deals, tickets, products",
        },
        query: {
          type: "string",
          description: "Text search query (searches default searchable properties)",
        },
        filter1: {
          type: "string",
          description: "Filter 1: 'property operator value' e.g., 'email EQ john@example.com' or 'amount GT 1000'. Operators: EQ, NEQ, LT, LTE, GT, GTE, CONTAINS_TOKEN",
        },
        filter2: {
          type: "string",
          description: "Filter 2: Same format as filter1 (optional, ANDed with filter1)",
        },
        filter3: {
          type: "string",
          description: "Filter 3: Same format as filter1 (optional, ANDed with others)",
        },
        limit: {
          type: "integer",
          description: "Maximum number of results (1-100, default 10)",
        },
        properties: {
          type: "string",
          description: "Comma-separated list of properties to return",
        },
        sortBy: {
          type: "string",
          description: "Property name to sort by",
        },
        sortDirection: {
          type: "string",
          description: "Sort direction: ASCENDING or DESCENDING",
        },
      },
      required: ["objectType"],
    },
  },
  {
    name: "hubspot_get_object",
    description: "Get a single HubSpot object by its ID.",
    inputSchema: {
      type: "object",
      properties: {
        objectType: {
          type: "string",
          description: "The object type: contacts, companies, deals, tickets, products",
        },
        objectId: {
          type: "string",
          description: "The ID of the object to retrieve",
        },
        properties: {
          type: "string",
          description: "Comma-separated list of properties to return",
        },
      },
      required: ["objectType", "objectId"],
    },
  },
  {
    name: "hubspot_create_contact",
    description: "Create a new contact in HubSpot.",
    inputSchema: {
      type: "object",
      properties: {
        email: {
          type: "string",
          description: "Contact email address (required)",
        },
        firstname: {
          type: "string",
          description: "First name",
        },
        lastname: {
          type: "string",
          description: "Last name",
        },
        phone: {
          type: "string",
          description: "Phone number",
        },
        company: {
          type: "string",
          description: "Company name",
        },
        jobtitle: {
          type: "string",
          description: "Job title",
        },
        lifecyclestage: {
          type: "string",
          description: "Lifecycle stage: subscriber, lead, marketingqualifiedlead, salesqualifiedlead, opportunity, customer, evangelist, other",
        },
      },
      required: ["email"],
    },
  },
  {
    name: "hubspot_create_company",
    description: "Create a new company in HubSpot.",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Company name (required)",
        },
        domain: {
          type: "string",
          description: "Company website domain",
        },
        phone: {
          type: "string",
          description: "Phone number",
        },
        industry: {
          type: "string",
          description: "Industry",
        },
        city: {
          type: "string",
          description: "City",
        },
        state: {
          type: "string",
          description: "State/Region",
        },
        country: {
          type: "string",
          description: "Country",
        },
        description: {
          type: "string",
          description: "Company description",
        },
      },
      required: ["name"],
    },
  },
  {
    name: "hubspot_create_deal",
    description: "Create a new deal in HubSpot.",
    inputSchema: {
      type: "object",
      properties: {
        dealname: {
          type: "string",
          description: "Deal name (required)",
        },
        amount: {
          type: "string",
          description: "Deal amount",
        },
        dealstage: {
          type: "string",
          description: "Deal stage ID",
        },
        pipeline: {
          type: "string",
          description: "Pipeline ID",
        },
        closedate: {
          type: "string",
          description: "Expected close date (YYYY-MM-DD)",
        },
        hubspot_owner_id: {
          type: "string",
          description: "Owner ID",
        },
      },
      required: ["dealname"],
    },
  },
  {
    name: "hubspot_update_object",
    description: "Update an existing HubSpot object.",
    inputSchema: {
      type: "object",
      properties: {
        objectType: {
          type: "string",
          description: "The object type: contacts, companies, deals, tickets",
        },
        objectId: {
          type: "string",
          description: "The ID of the object to update",
        },
        properties: {
          type: "string",
          description: "Properties to update as 'key=value' pairs separated by semicolons. Example: 'firstname=John;lastname=Doe;phone=555-1234'",
        },
      },
      required: ["objectType", "objectId", "properties"],
    },
  },
  {
    name: "hubspot_list_associations",
    description: "List associations between a HubSpot object and objects of another type.",
    inputSchema: {
      type: "object",
      properties: {
        objectType: {
          type: "string",
          description: "The source object type: contacts, companies, deals, tickets",
        },
        objectId: {
          type: "string",
          description: "The ID of the source object",
        },
        toObjectType: {
          type: "string",
          description: "The target object type to find associations with",
        },
      },
      required: ["objectType", "objectId", "toObjectType"],
    },
  },
  {
    name: "hubspot_create_note",
    description: "Create a note/engagement on a HubSpot record.",
    inputSchema: {
      type: "object",
      properties: {
        body: {
          type: "string",
          description: "The note content (HTML supported)",
        },
        contactId: {
          type: "string",
          description: "Contact ID to attach the note to",
        },
        companyId: {
          type: "string",
          description: "Company ID to attach the note to",
        },
        dealId: {
          type: "string",
          description: "Deal ID to attach the note to",
        },
      },
      required: ["body"],
    },
  },
];

// Parse filter string like "email EQ john@example.com"
function parseFilter(filterStr) {
  if (!filterStr) return null;
  
  const parts = filterStr.trim().split(/\s+/);
  if (parts.length < 3) return null;
  
  const propertyName = parts[0];
  const operator = parts[1].toUpperCase();
  const value = parts.slice(2).join(" ");
  
  return { propertyName, operator, value };
}

// Parse properties string like "key=value;key2=value2"
function parseProperties(propsStr) {
  if (!propsStr) return {};
  
  const result = {};
  const pairs = propsStr.split(";");
  
  for (const pair of pairs) {
    const [key, ...valueParts] = pair.split("=");
    if (key && valueParts.length > 0) {
      result[key.trim()] = valueParts.join("=").trim();
    }
  }
  
  return result;
}

// Tool handlers
async function handleTool(name, args) {
  switch (name) {
    case "hubspot_get_user_details": {
      // For Private App tokens, we can't use the OAuth endpoint
      // Instead, get account info via the account-info API and owners
      const accountInfo = await hubspotRequest("GET", "/account-info/v3/details");
      
      // Get owners to understand who can be assigned
      let ownerInfo = null;
      try {
        const owners = await hubspotRequest("GET", "/crm/v3/owners?limit=100");
        ownerInfo = owners.results;
      } catch (e) {
        // Ignore if we can't get owners
      }
      
      return {
        portal_id: accountInfo.portalId,
        account_type: accountInfo.accountType,
        time_zone: accountInfo.timeZone,
        currency: accountInfo.currency,
        utc_offset: accountInfo.utcOffset,
        ui_domain: accountInfo.uiDomain,
        data_hosting_location: accountInfo.dataHostingLocation,
        owners: ownerInfo,
      };
    }
    
    case "hubspot_list_objects": {
      const { objectType, limit = 10, properties, after } = args;
      
      let url = `/crm/v3/objects/${objectType}?limit=${limit}`;
      if (properties) {
        url += `&properties=${properties}`;
      }
      if (after) {
        url += `&after=${after}`;
      }
      
      return await hubspotRequest("GET", url);
    }
    
    case "hubspot_search_objects": {
      const { objectType, query, filter1, filter2, filter3, limit = 10, properties, sortBy, sortDirection } = args;
      
      const filters = [];
      for (const f of [filter1, filter2, filter3]) {
        const parsed = parseFilter(f);
        if (parsed) filters.push(parsed);
      }
      
      const body = {
        limit,
      };
      
      if (query) {
        body.query = query;
      }
      
      if (filters.length > 0) {
        body.filterGroups = [{
          filters: filters,
        }];
      }
      
      if (properties) {
        body.properties = properties.split(",").map(p => p.trim());
      }
      
      if (sortBy) {
        body.sorts = [{
          propertyName: sortBy,
          direction: sortDirection || "ASCENDING",
        }];
      }
      
      return await hubspotRequest("POST", `/crm/v3/objects/${objectType}/search`, body);
    }
    
    case "hubspot_get_object": {
      const { objectType, objectId, properties } = args;
      
      let url = `/crm/v3/objects/${objectType}/${objectId}`;
      if (properties) {
        url += `?properties=${properties}`;
      }
      
      return await hubspotRequest("GET", url);
    }
    
    case "hubspot_create_contact": {
      const properties = {};
      for (const key of ["email", "firstname", "lastname", "phone", "company", "jobtitle", "lifecyclestage"]) {
        if (args[key]) properties[key] = args[key];
      }
      
      return await hubspotRequest("POST", "/crm/v3/objects/contacts", { properties });
    }
    
    case "hubspot_create_company": {
      const properties = {};
      for (const key of ["name", "domain", "phone", "industry", "city", "state", "country", "description"]) {
        if (args[key]) properties[key] = args[key];
      }
      
      return await hubspotRequest("POST", "/crm/v3/objects/companies", { properties });
    }
    
    case "hubspot_create_deal": {
      const properties = {};
      for (const key of ["dealname", "amount", "dealstage", "pipeline", "closedate", "hubspot_owner_id"]) {
        if (args[key]) properties[key] = args[key];
      }
      
      return await hubspotRequest("POST", "/crm/v3/objects/deals", { properties });
    }
    
    case "hubspot_update_object": {
      const { objectType, objectId, properties: propsStr } = args;
      const properties = parseProperties(propsStr);
      
      return await hubspotRequest("PATCH", `/crm/v3/objects/${objectType}/${objectId}`, { properties });
    }
    
    case "hubspot_list_associations": {
      const { objectType, objectId, toObjectType } = args;
      
      return await hubspotRequest("GET", `/crm/v4/objects/${objectType}/${objectId}/associations/${toObjectType}`);
    }
    
    case "hubspot_create_note": {
      const { body, contactId, companyId, dealId } = args;
      
      const associations = [];
      if (contactId) {
        associations.push({ types: [{ associationCategory: "HUBSPOT_DEFINED", associationTypeId: 10 }], to: { id: contactId } });
      }
      if (companyId) {
        associations.push({ types: [{ associationCategory: "HUBSPOT_DEFINED", associationTypeId: 8 }], to: { id: companyId } });
      }
      if (dealId) {
        associations.push({ types: [{ associationCategory: "HUBSPOT_DEFINED", associationTypeId: 12 }], to: { id: dealId } });
      }
      
      const requestBody = {
        properties: {
          hs_note_body: body,
          hs_timestamp: new Date().toISOString(),
        },
      };
      
      if (associations.length > 0) {
        requestBody.associations = associations;
      }
      
      return await hubspotRequest("POST", "/crm/v3/objects/notes", requestBody);
    }
    
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

// Create MCP server
const server = new Server(
  {
    name: "hubspot-mcp-flat",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// List tools handler
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return { tools: TOOLS };
});

// Call tool handler
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  
  try {
    const result = await handleTool(name, args || {});
    
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  } catch (error) {
    return {
      content: [
        {
          type: "text",
          text: `Error: ${error.message}`,
        },
      ],
      isError: true,
    };
  }
});

// Start server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("HubSpot MCP Flat server started");
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
