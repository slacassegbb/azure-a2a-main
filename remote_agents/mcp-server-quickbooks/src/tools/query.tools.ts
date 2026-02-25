import { z } from "zod";
import { ToolDefinition } from "../types/tool-definition.js";
import {
  executeQuickbooksQuery,
  getQuickbooksCompanyInfo,
  runQuickbooksReport,
} from "../handlers/query.handler.js";

// Query Tool - Execute raw QBO queries
const querySchema = z.object({
  query: z.string().describe("QuickBooks Query Language (QQL) query. Use WHERE clauses to filter. Examples: 'SELECT * FROM Item WHERE Type = \\'Service\\'', 'SELECT * FROM Customer WHERE DisplayName LIKE \\'%Corp%\\''"),
});

export const QueryTool: ToolDefinition<typeof querySchema> = {
  name: "qbo_query",
  description: "Execute a QuickBooks Query Language (QQL) query. Use this for flexible queries when search tools don't have the filter you need. Supports WHERE, ORDER BY. Entities: Customer, Invoice, Item, Account, Vendor, Bill, Payment, etc.",
  schema: querySchema,
  handler: async (args: any) => {
    const { query } = (args.params ?? {}) as z.infer<typeof querySchema>;
    const response = await executeQuickbooksQuery(query);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error executing query: ${response.error}` }],
      };
    }
    const results = response.result;
    // Limit response size - return first 50 results summarized
    const maxResults = 50;
    const truncated = results?.slice(0, maxResults) || [];
    const summaryResults = truncated.map((r: any) => ({
      Id: r.Id,
      ...(r.DisplayName && { DisplayName: r.DisplayName }),
      ...(r.Name && { Name: r.Name }),
      ...(r.DocNumber && { DocNumber: r.DocNumber }),
      ...(r.TotalAmt !== undefined && { TotalAmt: r.TotalAmt }),
      ...(r.Balance !== undefined && { Balance: r.Balance }),
      ...(r.TxnDate && { TxnDate: r.TxnDate }),
      ...(r.Active !== undefined && { Active: r.Active }),
    }));
    const truncMsg = (results?.length || 0) > maxResults ? ` (showing first ${maxResults})` : '';
    return {
      content: [
        { type: "text" as const, text: `Query returned ${results?.length || 0} results${truncMsg}: ${JSON.stringify(summaryResults)}` },
      ],
    };
  },
};

// Company Info Tool
const companyInfoSchema = z.object({});

export const CompanyInfoTool: ToolDefinition<typeof companyInfoSchema> = {
  name: "qbo_company_info",
  description: "Get company information from QuickBooks Online, including company name, address, fiscal year, etc.",
  schema: companyInfoSchema,
  handler: async () => {
    const response = await getQuickbooksCompanyInfo();

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error getting company info: ${response.error}` }],
      };
    }
    // Summarize company info to reduce token usage
    const info = response.result;
    const summary = {
      CompanyName: info.CompanyName,
      LegalName: info.LegalName,
      CompanyAddr: info.CompanyAddr,
      Country: info.Country,
      Email: info.Email?.Address,
      Phone: info.PrimaryPhone?.FreeFormNumber,
      FiscalYearStartMonth: info.FiscalYearStartMonth,
    };
    return {
      content: [{ type: "text" as const, text: JSON.stringify(summary) }],
    };
  },
};

// Report Tool
const reportSchema = z.object({
  reportType: z.enum([
    "ProfitAndLoss",
    "BalanceSheet",
    "CashFlow",
    "GeneralLedger",
    "TrialBalance",
    "AccountList",
    "CustomerBalance",
    "VendorBalance",
    "AgedReceivables",
    "AgedPayables",
  ]).describe("Type of report to run"),
  start_date: z.string().optional().describe("Start date for the report (YYYY-MM-DD)"),
  end_date: z.string().optional().describe("End date for the report (YYYY-MM-DD)"),
  accounting_method: z.enum(["Cash", "Accrual"]).optional().describe("Accounting method"),
  summarize_column_by: z.string().optional().describe("How to summarize columns (e.g., 'Month', 'Quarter', 'Year')"),
});

export const ReportTool: ToolDefinition<typeof reportSchema> = {
  name: "qbo_report",
  description: "Run a financial report from QuickBooks Online. Supports Profit & Loss, Balance Sheet, Cash Flow, and more.",
  schema: reportSchema,
  handler: async (args: any) => {
    const { reportType, ...options } = (args.params ?? {}) as z.infer<typeof reportSchema>;
    const response = await runQuickbooksReport(reportType, options);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error running report: ${response.error}` }],
      };
    }
    // Flatten the QuickBooks report into a readable table for the LLM
    const report = response.result;
    const columns = report.Columns?.Column?.map((c: any) => c.ColTitle) || [];

    // Recursively extract all rows (QuickBooks nests sections)
    const flatRows: string[] = [];
    function extractRows(rows: any[], indent = 0) {
      if (!rows) return;
      for (const row of rows) {
        if (row.Header?.ColData) {
          const vals = row.Header.ColData.map((c: any) => c.value || '');
          flatRows.push('  '.repeat(indent) + vals.join(' | '));
        }
        if (row.ColData) {
          const vals = row.ColData.map((c: any) => c.value || '');
          flatRows.push('  '.repeat(indent) + vals.join(' | '));
        }
        if (row.Rows?.Row) {
          extractRows(row.Rows.Row, indent + 1);
        }
        if (row.Summary?.ColData) {
          const vals = row.Summary.ColData.map((c: any) => c.value || '');
          flatRows.push('  '.repeat(indent) + '**' + vals.join(' | ') + '**');
        }
      }
    }
    extractRows(report.Rows?.Row);

    const header = `${report.Header?.ReportName || reportType} (${report.Header?.StartPeriod || ''} to ${report.Header?.EndPeriod || ''}, ${report.Header?.Currency || 'USD'})`;
    const table = `${columns.join(' | ')}\n${flatRows.join('\n')}`;

    return {
      content: [
        { type: "text" as const, text: `${header}\n\n${table}` },
      ],
    };
  },
};
