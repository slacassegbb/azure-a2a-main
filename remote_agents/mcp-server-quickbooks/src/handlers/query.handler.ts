import { quickbooksClient } from "../clients/quickbooks-client.js";
import { ToolResponse } from "../types/tool-response.js";
import { formatError } from "../helpers/format-error.js";

// Map of entity names to their find method names
const entityFindMethods: { [key: string]: string } = {
  customer: "findCustomers",
  invoice: "findInvoices",
  account: "findAccounts",
  item: "findItems",
  vendor: "findVendors",
  bill: "findBills",
  billpayment: "findBillPayments",
  employee: "findEmployees",
  estimate: "findEstimates",
  purchase: "findPurchases",
  journalentry: "findJournalEntries",
  payment: "findPayments",
  deposit: "findDeposits",
  transfer: "findTransfers",
  creditmemo: "findCreditMemos",
  salesreceipt: "findSalesReceipts",
  refundreceipt: "findRefundReceipts",
  purchaseorder: "findPurchaseOrders",
  class: "findClasses",
  department: "findDepartments",
  taxcode: "findTaxCodes",
  taxrate: "findTaxRates",
  term: "findTerms",
  paymentmethod: "findPaymentMethods",
  companyinfo: "findCompanyInfos",
};

/**
 * Execute a raw QuickBooks query (QBO Query Language).
 * Parses the SQL-like query and routes to the appropriate find* method.
 */
export async function executeQuickbooksQuery(
  query: string
): Promise<ToolResponse<any[]>> {
  try {
    await quickbooksClient.authenticate();
    const quickbooks = quickbooksClient.getQuickbooks();

    // Parse the entity from the query (e.g., "SELECT * FROM Customer" -> "customer")
    const match = query.match(/from\s+(\w+)/i);
    if (!match) {
      return {
        result: null,
        isError: true,
        error: `Could not parse entity from query: ${query}. Expected format: SELECT * FROM EntityName`,
      };
    }

    const entity = match[1].toLowerCase();
    const findMethod = entityFindMethods[entity];
    
    if (!findMethod) {
      return {
        result: null,
        isError: true,
        error: `Unknown entity: ${match[1]}. Supported entities: ${Object.keys(entityFindMethods).join(", ")}`,
      };
    }

    // Parse WHERE clause for criteria
    const criteria: any[] = [];
    const whereMatch = query.match(/where\s+(.+?)(?:order\s+by|limit|offset|$)/i);
    
    if (whereMatch) {
      // Parse simple conditions like "Active = true" or "DisplayName LIKE '%test%'"
      const conditions = whereMatch[1].split(/\s+and\s+/i);
      for (const condition of conditions) {
        const condMatch = condition.match(/(\w+)\s*(=|!=|<|>|<=|>=|like)\s*['"]*([^'"]+)['"]*\s*/i);
        if (condMatch) {
          const [, field, operator, value] = condMatch;
          criteria.push({
            field: field,
            value: value.trim(),
            operator: operator.toUpperCase() === "LIKE" ? "LIKE" : operator,
          });
        }
      }
    }

    // Check for LIMIT
    const limitMatch = query.match(/limit\s+(\d+)/i);
    if (limitMatch) {
      criteria.push({ field: "limit", value: parseInt(limitMatch[1]) });
    }

    return new Promise((resolve) => {
      const method = (quickbooks as any)[findMethod];
      if (!method) {
        resolve({
          result: null,
          isError: true,
          error: `Method ${findMethod} not found on QuickBooks client`,
        });
        return;
      }

      method.call(quickbooks, criteria.length > 0 ? criteria : null, (err: any, result: any) => {
        if (err) {
          resolve({
            result: null,
            isError: true,
            error: formatError(err),
          });
        } else {
          // Extract the query response - it will be under whatever entity was queried
          const queryResponse = result?.QueryResponse || result || {};
          // Get the first key that's not startPosition, maxResults, totalCount
          const entityKey = Object.keys(queryResponse).find(
            (k) => !["startPosition", "maxResults", "totalCount"].includes(k)
          );
          resolve({
            result: entityKey ? queryResponse[entityKey] : (Array.isArray(result) ? result : []),
            isError: false,
            error: null,
          });
        }
      });
    });
  } catch (error) {
    return {
      result: null,
      isError: true,
      error: formatError(error),
    };
  }
}

/**
 * Get company info from QuickBooks Online.
 */
export async function getQuickbooksCompanyInfo(): Promise<ToolResponse<any>> {
  try {
    await quickbooksClient.authenticate();
    const quickbooks = quickbooksClient.getQuickbooks();
    const realmId = quickbooksClient.getRealmId();

    if (!realmId) {
      return {
        result: null,
        isError: true,
        error: "Realm ID not available. Please authenticate first.",
      };
    }

    return new Promise((resolve) => {
      (quickbooks as any).getCompanyInfo(realmId, (err: any, companyInfo: any) => {
        if (err) {
          resolve({
            result: null,
            isError: true,
            error: formatError(err),
          });
        } else {
          resolve({
            result: companyInfo,
            isError: false,
            error: null,
          });
        }
      });
    });
  } catch (error) {
    return {
      result: null,
      isError: true,
      error: formatError(error),
    };
  }
}

/**
 * Run a report from QuickBooks Online.
 * Supported reports: ProfitAndLoss, BalanceSheet, CashFlow, GeneralLedger, etc.
 */
export async function runQuickbooksReport(
  reportType: string,
  options: Record<string, any> = {}
): Promise<ToolResponse<any>> {
  try {
    await quickbooksClient.authenticate();
    const quickbooks = quickbooksClient.getQuickbooks();

    // Build the report method name (e.g., reportProfitAndLoss, reportBalanceSheet)
    const methodName = `report${reportType}`;

    return new Promise((resolve) => {
      if (typeof (quickbooks as any)[methodName] !== "function") {
        resolve({
          result: null,
          isError: true,
          error: `Report type '${reportType}' is not supported. Try: ProfitAndLoss, BalanceSheet, CashFlow, GeneralLedger`,
        });
        return;
      }

      (quickbooks as any)[methodName](options, (err: any, report: any) => {
        if (err) {
          resolve({
            result: null,
            isError: true,
            error: formatError(err),
          });
        } else {
          resolve({
            result: report,
            isError: false,
            error: null,
          });
        }
      });
    });
  } catch (error) {
    return {
      result: null,
      isError: true,
      error: formatError(error),
    };
  }
}
