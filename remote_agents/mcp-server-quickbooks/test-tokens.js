// Test if QuickBooks tokens are valid
import dotenv from 'dotenv';
import OAuthClient from 'intuit-oauth';

dotenv.config();

const client_id = process.env.QUICKBOOKS_CLIENT_ID;
const client_secret = process.env.QUICKBOOKS_CLIENT_SECRET;
const refresh_token = process.env.QUICKBOOKS_REFRESH_TOKEN;
const environment = process.env.QUICKBOOKS_ENVIRONMENT || 'sandbox';

console.log('🔍 Testing QuickBooks OAuth Tokens');
console.log('='.repeat(60));
console.log(`Client ID: ${client_id?.substring(0, 10)}...`);
console.log(`Environment: ${environment}`);
console.log(`Refresh Token: ${refresh_token?.substring(0, 15)}...`);
console.log('='.repeat(60));
console.log('');

const oauthClient = new OAuthClient({
  clientId: client_id,
  clientSecret: client_secret,
  environment: environment,
  redirectUri: 'http://localhost:3001/oauth/callback',
});

console.log('Attempting to refresh access token...');

try {
  const authResponse = await oauthClient.refreshUsingToken(refresh_token);
  
  console.log('✅ SUCCESS! Token refresh worked!');
  console.log('');
  console.log(`Access Token: ${authResponse.token.access_token.substring(0, 20)}...`);
  console.log(`Expires in: ${authResponse.token.expires_in} seconds`);
  console.log(`Token Type: ${authResponse.token.token_type}`);
  
  if (authResponse.token.refresh_token) {
    console.log(`New Refresh Token: ${authResponse.token.refresh_token.substring(0, 20)}...`);
  }
  
} catch (error) {
  console.log('❌ FAILED! Token refresh did not work!');
  console.log('');
  console.log('Error:', error.message);
  console.log('');
  
  if (error.authResponse) {
    console.log('Auth Response Status:', error.authResponse.status);
    console.log('Auth Response Body:', JSON.stringify(error.authResponse.body || error.authResponse, null, 2));
  }
  
  console.log('');
  console.log('⚠️  Your refresh token is likely expired or invalid.');
  console.log('');
  console.log('To fix this:');
  console.log('1. Run: npm run auth');
  console.log('2. Complete the OAuth flow in your browser');
  console.log('3. The new refresh token will be saved to your .env file');
  console.log('4. Redeploy with: ./deploy-mcp-quickbooks.sh');
  
  process.exit(1);
}
