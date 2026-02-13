#!/usr/bin/env node

/**
 * QuickBooks OAuth Token Generator
 * Run this locally to get a new refresh token
 *
 * Usage: node get-oauth-token.js
 */

import OAuthClient from 'intuit-oauth';
import open from 'open';
import http from 'http';
import { URL } from 'url';
import dotenv from 'dotenv';

dotenv.config();

const CLIENT_ID = process.env.QUICKBOOKS_CLIENT_ID;
const CLIENT_SECRET = process.env.QUICKBOOKS_CLIENT_SECRET;
const ENVIRONMENT = process.env.QUICKBOOKS_ENVIRONMENT || 'sandbox';
const REDIRECT_URI = 'http://localhost:3002/oauth/callback';

if (!CLIENT_ID || !CLIENT_SECRET) {
  console.error('❌ Missing QUICKBOOKS_CLIENT_ID or QUICKBOOKS_CLIENT_SECRET in .env file');
  process.exit(1);
}

const oauthClient = new OAuthClient({
  clientId: CLIENT_ID,
  clientSecret: CLIENT_SECRET,
  environment: ENVIRONMENT,
  redirectUri: REDIRECT_URI,
});

console.log('🔐 QuickBooks OAuth Token Generator');
console.log('=' .repeat(50));
console.log(`Environment: ${ENVIRONMENT}`);
console.log(`Redirect URI: ${REDIRECT_URI}`);
console.log('');

// Create a simple HTTP server to handle the callback
const server = http.createServer(async (req, res) => {
  if (!req.url?.startsWith('/oauth/callback')) {
    res.writeHead(404);
    res.end('Not found');
    return;
  }

  try {
    // Extract the authorization code from the callback URL
    const url = new URL(req.url, `http://localhost:3002`);
    const authCode = url.searchParams.get('code');
    const realmId = url.searchParams.get('realmId');

    if (!authCode || !realmId) {
      throw new Error('Missing code or realmId in callback');
    }

    console.log('✓ Received OAuth callback');
    console.log(`  Realm ID: ${realmId}`);

    // Exchange authorization code for tokens
    const authResponse = await oauthClient.createToken(req.url);
    const token = authResponse.getJson();

    console.log('');
    console.log('✅ Successfully obtained tokens!');
    console.log('=' .repeat(50));
    console.log('');
    console.log('📋 Copy these values to your environment:');
    console.log('');
    console.log(`QUICKBOOKS_REALM_ID="${realmId}"`);
    console.log(`QUICKBOOKS_REFRESH_TOKEN="${token.refresh_token}"`);
    console.log('');
    console.log('=' .repeat(50));
    console.log('');
    console.log('🔧 Update your Azure Container App:');
    console.log('');
    console.log(`az containerapp update \\`);
    console.log(`  --name mcp-quickbooks \\`);
    console.log(`  --resource-group rg-a2a-prod \\`);
    console.log(`  --set-env-vars \\`);
    console.log(`    "QUICKBOOKS_REALM_ID=${realmId}" \\`);
    console.log(`    "QUICKBOOKS_REFRESH_TOKEN=${token.refresh_token}"`);
    console.log('');

    // Send success response to browser
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(`
      <html>
        <head>
          <title>QuickBooks OAuth Success</title>
          <style>
            body {
              font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
              display: flex;
              justify-content: center;
              align-items: center;
              height: 100vh;
              margin: 0;
              background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            }
            .container {
              background: white;
              padding: 3rem;
              border-radius: 10px;
              box-shadow: 0 10px 40px rgba(0,0,0,0.2);
              text-align: center;
              max-width: 500px;
            }
            h1 { color: #2E8B57; margin-bottom: 1rem; }
            p { color: #666; line-height: 1.6; }
            .success { font-size: 64px; margin-bottom: 1rem; }
          </style>
        </head>
        <body>
          <div class="container">
            <div class="success">✓</div>
            <h1>Authentication Successful!</h1>
            <p>You can close this window and return to your terminal to see the tokens.</p>
          </div>
        </body>
      </html>
    `);

    // Close server after successful auth
    setTimeout(() => {
      server.close();
      process.exit(0);
    }, 1000);

  } catch (error) {
    console.error('❌ Error during OAuth callback:', error.message);
    res.writeHead(500, { 'Content-Type': 'text/html' });
    res.end(`
      <html>
        <body style="font-family: Arial; padding: 20px;">
          <h2 style="color: #d32f2f;">OAuth Error</h2>
          <p>${error.message}</p>
        </body>
      </html>
    `);
  }
});

// Start the server
server.listen(3002, () => {
  console.log('✓ Local OAuth server started on http://localhost:3002');
  console.log('');

  // Generate OAuth authorization URL
  const authUri = oauthClient.authorizeUri({
    scope: [
      'com.intuit.quickbooks.accounting',
      'com.intuit.quickbooks.payment',
    ],
    state: 'oauth-state-' + Date.now(),
  });

  console.log('🌐 Opening QuickBooks authorization page in your browser...');
  console.log('');
  console.log('If it doesn\'t open automatically, visit:');
  console.log(authUri);
  console.log('');

  // Open browser automatically
  open(authUri).catch(() => {
    console.log('(Could not open browser automatically)');
  });
});

// Handle server errors
server.on('error', (error) => {
  console.error('❌ Server error:', error.message);
  process.exit(1);
});
