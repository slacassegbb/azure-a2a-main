declare module "node-quickbooks" {
  export default class QuickBooks {
    constructor(
      consumerKey: string,
      consumerSecret: string,
      oauthToken: string,
      oauthTokenSecret: boolean,
      realmId: string,
      useSandbox: boolean,
      debug: boolean,
      minorVersion: string | null,
      oauthVersion: string,
      refreshToken?: string
    );

    // Customer methods
    createCustomer(customer: object, callback: (err: any, customer: any) => void): void;
    getCustomer(id: string, callback: (err: any, customer: any) => void): void;
    updateCustomer(customer: object, callback: (err: any, customer: any) => void): void;
    deleteCustomer(customer: object, callback: (err: any, customer: any) => void): void;
    findCustomers(criteria: any, callback: (err: any, customers: any) => void): void;

    // Invoice methods
    createInvoice(invoice: object, callback: (err: any, invoice: any) => void): void;
    getInvoice(id: string, callback: (err: any, invoice: any) => void): void;
    updateInvoice(invoice: object, callback: (err: any, invoice: any) => void): void;
    deleteInvoice(invoice: object, callback: (err: any, result: any) => void): void;
    findInvoices(criteria: any, callback: (err: any, invoices: any) => void): void;

    // Account methods
    createAccount(account: object, callback: (err: any, account: any) => void): void;
    getAccount(id: string, callback: (err: any, account: any) => void): void;
    updateAccount(account: object, callback: (err: any, account: any) => void): void;
    findAccounts(criteria: any, callback: (err: any, accounts: any) => void): void;

    // Item methods
    createItem(item: object, callback: (err: any, item: any) => void): void;
    getItem(id: string, callback: (err: any, item: any) => void): void;
    updateItem(item: object, callback: (err: any, item: any) => void): void;
    findItems(criteria: any, callback: (err: any, items: any) => void): void;

    // Vendor methods
    createVendor(vendor: object, callback: (err: any, vendor: any) => void): void;
    getVendor(id: string, callback: (err: any, vendor: any) => void): void;
    updateVendor(vendor: object, callback: (err: any, vendor: any) => void): void;
    deleteVendor(vendor: object, callback: (err: any, vendor: any) => void): void;
    findVendors(criteria: any, callback: (err: any, vendors: any) => void): void;

    // Bill methods
    createBill(bill: object, callback: (err: any, bill: any) => void): void;
    getBill(id: string, callback: (err: any, bill: any) => void): void;
    updateBill(bill: object, callback: (err: any, bill: any) => void): void;
    deleteBill(bill: object, callback: (err: any, result: any) => void): void;
    findBills(criteria: any, callback: (err: any, bills: any) => void): void;

    // Employee methods
    createEmployee(employee: object, callback: (err: any, employee: any) => void): void;
    getEmployee(id: string, callback: (err: any, employee: any) => void): void;
    updateEmployee(employee: object, callback: (err: any, employee: any) => void): void;
    findEmployees(criteria: any, callback: (err: any, employees: any) => void): void;

    // Estimate methods
    createEstimate(estimate: object, callback: (err: any, estimate: any) => void): void;
    getEstimate(id: string, callback: (err: any, estimate: any) => void): void;
    updateEstimate(estimate: object, callback: (err: any, estimate: any) => void): void;
    deleteEstimate(estimate: object, callback: (err: any, result: any) => void): void;
    findEstimates(criteria: any, callback: (err: any, estimates: any) => void): void;

    // Purchase methods
    createPurchase(purchase: object, callback: (err: any, purchase: any) => void): void;
    getPurchase(id: string, callback: (err: any, purchase: any) => void): void;
    updatePurchase(purchase: object, callback: (err: any, purchase: any) => void): void;
    deletePurchase(purchase: object, callback: (err: any, result: any) => void): void;
    findPurchases(criteria: any, callback: (err: any, purchases: any) => void): void;

    // Journal Entry methods
    createJournalEntry(entry: object, callback: (err: any, entry: any) => void): void;
    getJournalEntry(id: string, callback: (err: any, entry: any) => void): void;
    updateJournalEntry(entry: object, callback: (err: any, entry: any) => void): void;
    deleteJournalEntry(entry: object, callback: (err: any, result: any) => void): void;
    findJournalEntries(criteria: any, callback: (err: any, entries: any) => void): void;

    // Bill Payment methods
    createBillPayment(payment: object, callback: (err: any, payment: any) => void): void;
    getBillPayment(id: string, callback: (err: any, payment: any) => void): void;
    updateBillPayment(payment: object, callback: (err: any, payment: any) => void): void;
    deleteBillPayment(payment: object, callback: (err: any, result: any) => void): void;
    findBillPayments(criteria: any, callback: (err: any, payments: any) => void): void;

    // Company info
    getCompanyInfo(realmId: string, callback: (err: any, info: any) => void): void;

    // Query
    query(query: string, callback: (err: any, result: any) => void): void;

    // Reports
    reportProfitAndLoss(options: object, callback: (err: any, report: any) => void): void;
    reportBalanceSheet(options: object, callback: (err: any, report: any) => void): void;
    reportCashFlow(options: object, callback: (err: any, report: any) => void): void;
    reportGeneralLedger(options: object, callback: (err: any, report: any) => void): void;
    reportTrialBalance(options: object, callback: (err: any, report: any) => void): void;
    reportAccountList(options: object, callback: (err: any, report: any) => void): void;
    reportCustomerBalance(options: object, callback: (err: any, report: any) => void): void;
    reportVendorBalance(options: object, callback: (err: any, report: any) => void): void;
    reportAgedReceivables(options: object, callback: (err: any, report: any) => void): void;
    reportAgedPayables(options: object, callback: (err: any, report: any) => void): void;
  }
}

declare module "intuit-oauth" {
  export default class OAuthClient {
    static scopes: {
      Accounting: string;
      Payment: string;
      Payroll: string;
      TimeTracking: string;
      Benefits: string;
      OpenId: string;
      Profile: string;
      Email: string;
      Phone: string;
      Address: string;
    };

    constructor(config: {
      clientId: string;
      clientSecret: string;
      environment: string;
      redirectUri: string;
    });

    authorizeUri(options: { scope: string[]; state: string }): string;
    createToken(url: string): Promise<{ token: any }>;
    refreshUsingToken(refreshToken: string): Promise<{ token: any }>;
    getToken(): any;
    setToken(token: any): void;
    isAccessTokenValid(): boolean;
  }
}
