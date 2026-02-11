import { Tool } from "@modelcontextprotocol/sdk/types.js";
import { SalesforceObject } from "../types/salesforce";

export const SEARCH_OBJECTS: Tool = {
  name: "salesforce_search_objects",
  description: "Search for Salesforce standard and custom objects by name pattern. Examples: 'Account' will find Account, AccountHistory; 'Order' will find WorkOrder, ServiceOrder__c etc.",
  inputSchema: {
    type: "object",
    properties: {
      searchPattern: {
        type: "string",
        description: "Search pattern to find objects (e.g., 'Account Coverage' will find objects like 'AccountCoverage__c')"
      }
    },
    required: ["searchPattern"]
  }
};

export async function handleSearchObjects(conn: any, searchPattern: string) {
  // Get list of all objects
  const describeGlobal = await conn.describeGlobal();
  
  // Process search pattern to create a more flexible search
  const searchTerms = searchPattern.toLowerCase().split(' ').filter(term => term.length > 0);
  
  // Filter objects based on search pattern
  const matchingObjects = describeGlobal.sobjects.filter((obj: SalesforceObject) => {
    const objectName = obj.name.toLowerCase();
    const objectLabel = obj.label.toLowerCase();
    
    // Check if all search terms are present in either the API name or label
    return searchTerms.every(term => 
      objectName.includes(term) || objectLabel.includes(term)
    );
  });

  if (matchingObjects.length === 0) {
    return {
      content: [{
        type: "text",
        text: `No Salesforce objects found matching "${searchPattern}".`
      }],
      isError: false,
    };
  }

  // Format the output
  const formattedResults = matchingObjects.map((obj: SalesforceObject) => 
    `${obj.name}${obj.custom ? ' (Custom)' : ''}\n  Label: ${obj.label}`
  ).join('\n\n');

  return {
    content: [{
      type: "text",
      text: `Found ${matchingObjects.length} matching objects:\n\n${formattedResults}`
    }],
    isError: false,
  };
}