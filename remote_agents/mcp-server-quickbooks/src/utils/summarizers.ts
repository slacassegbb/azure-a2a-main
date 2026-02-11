/**
 * Response summarizers to reduce token usage in MCP tool responses.
 * These extract only essential fields that the agent needs for decision-making.
 */

// Invoice summary - for search/list operations
export function summarizeInvoice(inv: any) {
  return {
    Id: inv.Id,
    DocNumber: inv.DocNumber,
    CustomerRef: inv.CustomerRef ? {
      value: inv.CustomerRef.value,
      name: inv.CustomerRef.name
    } : null,
    TxnDate: inv.TxnDate,
    DueDate: inv.DueDate,
    TotalAmt: inv.TotalAmt,
    Balance: inv.Balance,
    EmailStatus: inv.EmailStatus,
    // Include line count for context
    LineCount: inv.Line?.filter((l: any) => l.DetailType === 'SalesItemLineDetail')?.length || 0
  };
}

// Invoice detail - for get single invoice (includes line items)
export function summarizeInvoiceDetail(inv: any) {
  return {
    Id: inv.Id,
    SyncToken: inv.SyncToken, // Needed for updates
    DocNumber: inv.DocNumber,
    CustomerRef: inv.CustomerRef,
    TxnDate: inv.TxnDate,
    DueDate: inv.DueDate,
    TotalAmt: inv.TotalAmt,
    Balance: inv.Balance,
    EmailStatus: inv.EmailStatus,
    BillEmail: inv.BillEmail,
    // Summarize line items
    Line: inv.Line?.filter((l: any) => l.DetailType === 'SalesItemLineDetail')?.map((line: any) => ({
      Id: line.Id,
      Description: line.Description,
      Amount: line.Amount,
      Qty: line.SalesItemLineDetail?.Qty,
      UnitPrice: line.SalesItemLineDetail?.UnitPrice,
      ItemRef: line.SalesItemLineDetail?.ItemRef
    })) || []
  };
}

// Customer summary - for search/list operations
export function summarizeCustomer(c: any) {
  return {
    Id: c.Id,
    DisplayName: c.DisplayName,
    CompanyName: c.CompanyName,
    PrimaryEmailAddr: c.PrimaryEmailAddr?.Address,
    PrimaryPhone: c.PrimaryPhone?.FreeFormNumber,
    Balance: c.Balance,
    Active: c.Active
  };
}

// Customer detail - for get single customer
export function summarizeCustomerDetail(c: any) {
  return {
    Id: c.Id,
    SyncToken: c.SyncToken,
    DisplayName: c.DisplayName,
    CompanyName: c.CompanyName,
    GivenName: c.GivenName,
    FamilyName: c.FamilyName,
    PrimaryEmailAddr: c.PrimaryEmailAddr,
    PrimaryPhone: c.PrimaryPhone,
    BillAddr: c.BillAddr,
    Balance: c.Balance,
    Active: c.Active
  };
}

// Vendor summary
export function summarizeVendor(v: any) {
  return {
    Id: v.Id,
    DisplayName: v.DisplayName,
    CompanyName: v.CompanyName,
    PrimaryEmailAddr: v.PrimaryEmailAddr?.Address,
    PrimaryPhone: v.PrimaryPhone?.FreeFormNumber,
    Balance: v.Balance,
    Active: v.Active
  };
}

// Vendor detail
export function summarizeVendorDetail(v: any) {
  return {
    Id: v.Id,
    SyncToken: v.SyncToken,
    DisplayName: v.DisplayName,
    CompanyName: v.CompanyName,
    GivenName: v.GivenName,
    FamilyName: v.FamilyName,
    PrimaryEmailAddr: v.PrimaryEmailAddr,
    PrimaryPhone: v.PrimaryPhone,
    BillAddr: v.BillAddr,
    Balance: v.Balance,
    Active: v.Active
  };
}

// Bill summary
export function summarizeBill(bill: any) {
  return {
    Id: bill.Id,
    DocNumber: bill.DocNumber,
    VendorRef: bill.VendorRef ? {
      value: bill.VendorRef.value,
      name: bill.VendorRef.name
    } : null,
    TxnDate: bill.TxnDate,
    DueDate: bill.DueDate,
    TotalAmt: bill.TotalAmt,
    Balance: bill.Balance,
    LineCount: bill.Line?.filter((l: any) => l.DetailType === 'AccountBasedExpenseLineDetail' || l.DetailType === 'ItemBasedExpenseLineDetail')?.length || 0
  };
}

// Bill detail
export function summarizeBillDetail(bill: any) {
  return {
    Id: bill.Id,
    SyncToken: bill.SyncToken,
    DocNumber: bill.DocNumber,
    VendorRef: bill.VendorRef,
    TxnDate: bill.TxnDate,
    DueDate: bill.DueDate,
    TotalAmt: bill.TotalAmt,
    Balance: bill.Balance,
    Line: bill.Line?.map((line: any) => ({
      Id: line.Id,
      Description: line.Description,
      Amount: line.Amount,
      DetailType: line.DetailType,
      AccountRef: line.AccountBasedExpenseLineDetail?.AccountRef || line.ItemBasedExpenseLineDetail?.ItemRef
    })) || []
  };
}

// Item summary
export function summarizeItem(item: any) {
  return {
    Id: item.Id,
    Name: item.Name,
    Type: item.Type,
    UnitPrice: item.UnitPrice,
    Active: item.Active,
    Taxable: item.Taxable
  };
}

// Item detail
export function summarizeItemDetail(item: any) {
  return {
    Id: item.Id,
    SyncToken: item.SyncToken,
    Name: item.Name,
    Type: item.Type,
    Description: item.Description,
    UnitPrice: item.UnitPrice,
    PurchaseCost: item.PurchaseCost,
    IncomeAccountRef: item.IncomeAccountRef,
    ExpenseAccountRef: item.ExpenseAccountRef,
    Active: item.Active,
    Taxable: item.Taxable
  };
}

// Account summary
export function summarizeAccount(acct: any) {
  return {
    Id: acct.Id,
    Name: acct.Name,
    AccountType: acct.AccountType,
    AccountSubType: acct.AccountSubType,
    CurrentBalance: acct.CurrentBalance,
    Active: acct.Active
  };
}

// Account detail
export function summarizeAccountDetail(acct: any) {
  return {
    Id: acct.Id,
    SyncToken: acct.SyncToken,
    Name: acct.Name,
    FullyQualifiedName: acct.FullyQualifiedName,
    AccountType: acct.AccountType,
    AccountSubType: acct.AccountSubType,
    CurrentBalance: acct.CurrentBalance,
    Active: acct.Active,
    Classification: acct.Classification
  };
}

// Employee summary
export function summarizeEmployee(emp: any) {
  return {
    Id: emp.Id,
    DisplayName: emp.DisplayName,
    GivenName: emp.GivenName,
    FamilyName: emp.FamilyName,
    PrimaryPhone: emp.PrimaryPhone?.FreeFormNumber,
    Active: emp.Active
  };
}

// Payment summary
export function summarizePayment(pmt: any) {
  return {
    Id: pmt.Id,
    TxnDate: pmt.TxnDate,
    CustomerRef: pmt.CustomerRef ? {
      value: pmt.CustomerRef.value,
      name: pmt.CustomerRef.name
    } : null,
    TotalAmt: pmt.TotalAmt,
    PaymentMethodRef: pmt.PaymentMethodRef,
    DepositToAccountRef: pmt.DepositToAccountRef
  };
}

// Estimate summary
export function summarizeEstimate(est: any) {
  return {
    Id: est.Id,
    DocNumber: est.DocNumber,
    CustomerRef: est.CustomerRef ? {
      value: est.CustomerRef.value,
      name: est.CustomerRef.name
    } : null,
    TxnDate: est.TxnDate,
    ExpirationDate: est.ExpirationDate,
    TotalAmt: est.TotalAmt,
    TxnStatus: est.TxnStatus
  };
}

// Purchase summary
export function summarizePurchase(purch: any) {
  return {
    Id: purch.Id,
    DocNumber: purch.DocNumber,
    TxnDate: purch.TxnDate,
    TotalAmt: purch.TotalAmt,
    PaymentType: purch.PaymentType,
    EntityRef: purch.EntityRef ? {
      value: purch.EntityRef.value,
      name: purch.EntityRef.name
    } : null,
    AccountRef: purch.AccountRef
  };
}

// Journal Entry summary
export function summarizeJournalEntry(je: any) {
  return {
    Id: je.Id,
    DocNumber: je.DocNumber,
    TxnDate: je.TxnDate,
    TotalAmt: je.TotalAmt,
    Adjustment: je.Adjustment,
    LineCount: je.Line?.length || 0
  };
}

// Bill Payment summary
export function summarizeBillPayment(bp: any) {
  return {
    Id: bp.Id,
    DocNumber: bp.DocNumber,
    TxnDate: bp.TxnDate,
    TotalAmt: bp.TotalAmt,
    VendorRef: bp.VendorRef ? {
      value: bp.VendorRef.value,
      name: bp.VendorRef.name
    } : null,
    PayType: bp.PayType
  };
}

// Generic confirmation for create/update operations
export function summarizeConfirmation(entity: any, entityType: string) {
  return {
    success: true,
    entityType,
    Id: entity.Id,
    SyncToken: entity.SyncToken,
    ...(entity.DocNumber && { DocNumber: entity.DocNumber }),
    ...(entity.DisplayName && { DisplayName: entity.DisplayName }),
    ...(entity.Name && { Name: entity.Name }),
    ...(entity.TotalAmt !== undefined && { TotalAmt: entity.TotalAmt })
  };
}
