// Quick OAuth test - triggers the browser-based authorization
import dotenv from "dotenv";
dotenv.config();

import { quickbooksClient } from "./dist/clients/quickbooks-client.js";

console.log("Starting OAuth flow...");
console.log("Client ID:", process.env.QUICKBOOKS_CLIENT_ID ? "✓ Set" : "✗ Missing");
console.log("Client Secret:", process.env.QUICKBOOKS_CLIENT_SECRET ? "✓ Set" : "✗ Missing");
console.log("Refresh Token:", process.env.QUICKBOOKS_REFRESH_TOKEN ? "✓ Set" : "✗ Missing");
console.log("Realm ID:", process.env.QUICKBOOKS_REALM_ID ? "✓ Set" : "✗ Missing");
console.log("");

try {
  console.log("Calling authenticate()...");
  await quickbooksClient.authenticate();
  console.log("Authentication successful!");
  
  const qb = quickbooksClient.getQuickbooks();
  console.log("QuickBooks instance created:", !!qb);
} catch (error) {
  console.error("Authentication failed:", error);
}
