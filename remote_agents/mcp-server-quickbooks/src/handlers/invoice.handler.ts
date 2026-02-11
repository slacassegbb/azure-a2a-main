import { quickbooksClient } from "../clients/quickbooks-client.js";
import { ToolResponse } from "../types/tool-response.js";
import { formatError } from "../helpers/format-error.js";
import { buildQuickbooksSearchCriteria, QuickbooksSearchCriteriaInput } from "../helpers/build-search-criteria.js";

/**
 * Search invoices from QuickBooks Online.
 */
export async function searchQuickbooksInvoices(
  criteria: QuickbooksSearchCriteriaInput = {}
): Promise<ToolResponse<any[]>> {
  try {
    await quickbooksClient.authenticate();
    const quickbooks = quickbooksClient.getQuickbooks();
    const normalizedCriteria = buildQuickbooksSearchCriteria(criteria);

    return new Promise((resolve) => {
      (quickbooks as any).findInvoices(normalizedCriteria, (err: any, invoices: any) => {
        if (err) {
          resolve({
            result: null,
            isError: true,
            error: formatError(err),
          });
        } else {
          resolve({
            result: invoices?.QueryResponse?.Invoice || [],
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
 * Get a single invoice by ID from QuickBooks Online.
 */
export async function getQuickbooksInvoice(
  invoiceId: string
): Promise<ToolResponse<any>> {
  try {
    await quickbooksClient.authenticate();
    const quickbooks = quickbooksClient.getQuickbooks();

    return new Promise((resolve) => {
      (quickbooks as any).getInvoice(invoiceId, (err: any, invoice: any) => {
        if (err) {
          resolve({
            result: null,
            isError: true,
            error: formatError(err),
          });
        } else {
          resolve({
            result: invoice,
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
 * Create an invoice in QuickBooks Online.
 */
export async function createQuickbooksInvoice(
  invoiceData: Record<string, any>
): Promise<ToolResponse<any>> {
  try {
    // DEBUG: Log the exact payload being sent
    console.log('=== INVOICE PAYLOAD DEBUG ===');
    console.log(JSON.stringify(invoiceData, null, 2));
    console.log('=== END PAYLOAD ===');
    
    await quickbooksClient.authenticate();
    const quickbooks = quickbooksClient.getQuickbooks();

    return new Promise((resolve) => {
      (quickbooks as any).createInvoice(invoiceData, (err: any, invoice: any) => {
        if (err) {
          console.log('=== QUICKBOOKS ERROR ===');
          console.log(JSON.stringify(err, null, 2));
          console.log('=== END ERROR ===');
          resolve({
            result: null,
            isError: true,
            error: formatError(err),
          });
        } else {
          resolve({
            result: invoice,
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
 * Update an invoice in QuickBooks Online.
 */
export async function updateQuickbooksInvoice(
  invoiceData: Record<string, any>
): Promise<ToolResponse<any>> {
  try {
    await quickbooksClient.authenticate();
    const quickbooks = quickbooksClient.getQuickbooks();

    return new Promise((resolve) => {
      (quickbooks as any).updateInvoice(invoiceData, (err: any, invoice: any) => {
        if (err) {
          resolve({
            result: null,
            isError: true,
            error: formatError(err),
          });
        } else {
          resolve({
            result: invoice,
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
 * Delete an invoice in QuickBooks Online.
 */
export async function deleteQuickbooksInvoice(
  invoiceData: { Id: string; SyncToken: string }
): Promise<ToolResponse<any>> {
  try {
    await quickbooksClient.authenticate();
    const quickbooks = quickbooksClient.getQuickbooks();

    return new Promise((resolve) => {
      (quickbooks as any).deleteInvoice(invoiceData, (err: any, result: any) => {
        if (err) {
          resolve({
            result: null,
            isError: true,
            error: formatError(err),
          });
        } else {
          resolve({
            result: result,
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
