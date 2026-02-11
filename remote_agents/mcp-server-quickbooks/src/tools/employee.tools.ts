import { z } from "zod";
import { ToolDefinition } from "../types/tool-definition.js";
import {
  searchQuickbooksEmployees,
  getQuickbooksEmployee,
  createQuickbooksEmployee,
  updateQuickbooksEmployee,
} from "../handlers/employee.handler.js";
import { summarizeEmployee, summarizeConfirmation } from "../utils/summarizers.js";

// Search Employees Tool
const searchEmployeesSchema = z.object({
  displayName: z.string().optional().describe("Filter by employee display name (partial match)"),
  givenName: z.string().optional().describe("Filter by first name"),
  familyName: z.string().optional().describe("Filter by last name"),
  active: z.boolean().optional().describe("Filter by active status"),
});

export const SearchEmployeesTool: ToolDefinition<typeof searchEmployeesSchema> = {
  name: "qbo_search_employees",
  description: "Search employees in QuickBooks Online. Use name filters to find specific employees.",
  schema: searchEmployeesSchema,
  handler: async (args: any) => {
    const params = (args.params ?? {}) as z.infer<typeof searchEmployeesSchema>;
    const criteria: any = {};
    if (params.displayName) criteria.displayName = params.displayName;
    if (params.givenName) criteria.givenName = params.givenName;
    if (params.familyName) criteria.familyName = params.familyName;
    if (params.active !== undefined) criteria.active = params.active;
    
    const response = await searchQuickbooksEmployees(criteria);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error searching employees: ${response.error}` }],
      };
    }
    const employees = response.result;
    const summaries = employees?.map((e: any) => summarizeEmployee(e)) || [];
    return {
      content: [
        { type: "text" as const, text: `Found ${employees?.length || 0} employees: ${JSON.stringify(summaries)}` },
      ],
    };
  },
};

// Get Employee Tool
const getEmployeeSchema = z.object({
  id: z.string().describe("The ID of the employee to retrieve"),
});

export const GetEmployeeTool: ToolDefinition<typeof getEmployeeSchema> = {
  name: "qbo_get_employee",
  description: "Get a single employee by ID from QuickBooks Online.",
  schema: getEmployeeSchema,
  handler: async (args: any) => {
    const { id } = (args.params ?? {}) as z.infer<typeof getEmployeeSchema>;
    const response = await getQuickbooksEmployee(id);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error getting employee: ${response.error}` }],
      };
    }
    const summary = summarizeEmployee(response.result);
    return {
      content: [{ type: "text" as const, text: JSON.stringify(summary) }],
    };
  },
};

// Create Employee Tool
const createEmployeeSchema = z.object({
  GivenName: z.string().describe("First name of the employee (required)"),
  FamilyName: z.string().describe("Last name of the employee (required)"),
  DisplayName: z.string().optional().describe("Display name"),
  PrimaryEmailAddr: z.object({ Address: z.string() }).optional(),
  PrimaryPhone: z.object({ FreeFormNumber: z.string() }).optional(),
  PrimaryAddr: z.object({
    Line1: z.string().optional(),
    City: z.string().optional(),
    CountrySubDivisionCode: z.string().optional(),
    PostalCode: z.string().optional(),
  }).optional(),
  SSN: z.string().optional().describe("Social Security Number (last 4 digits)"),
  BirthDate: z.string().optional().describe("Birth date (YYYY-MM-DD)"),
  HiredDate: z.string().optional().describe("Hire date (YYYY-MM-DD)"),
});

export const CreateEmployeeTool: ToolDefinition<typeof createEmployeeSchema> = {
  name: "qbo_create_employee",
  description: "Create a new employee in QuickBooks Online.",
  schema: createEmployeeSchema,
  handler: async (args: any) => {
    const employeeData = (args.params ?? {}) as z.infer<typeof createEmployeeSchema>;
    const response = await createQuickbooksEmployee(employeeData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error creating employee: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'Employee');
    return {
      content: [
        { type: "text" as const, text: `Employee created successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};

// Update Employee Tool
const updateEmployeeSchema = z.object({
  Id: z.string().describe("The ID of the employee to update"),
  SyncToken: z.string().describe("The sync token of the employee"),
  GivenName: z.string().optional(),
  FamilyName: z.string().optional(),
  DisplayName: z.string().optional(),
  Active: z.boolean().optional(),
});

export const UpdateEmployeeTool: ToolDefinition<typeof updateEmployeeSchema> = {
  name: "qbo_update_employee",
  description: "Update an existing employee in QuickBooks Online.",
  schema: updateEmployeeSchema,
  handler: async (args: any) => {
    const employeeData = (args.params ?? {}) as z.infer<typeof updateEmployeeSchema>;
    const response = await updateQuickbooksEmployee(employeeData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error updating employee: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'Employee');
    return {
      content: [
        { type: "text" as const, text: `Employee updated successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};
