// Direct test of QuickBooks API - bypasses MCP
import dotenv from 'dotenv';
dotenv.config();

const { quickbooksClient } = await import('./dist/clients/quickbooks-client.js');

console.log('Testing QuickBooks connection directly...');
console.log('');
console.log('Environment:');
console.log('  Client ID:', process.env.QUICKBOOKS_CLIENT_ID ? '✓ Set' : '✗ Missing');
console.log('  Client Secret:', process.env.QUICKBOOKS_CLIENT_SECRET ? '✓ Set' : '✗ Missing');
console.log('  Refresh Token:', process.env.QUICKBOOKS_REFRESH_TOKEN ? '✓ Set' : '✗ Missing');
console.log('  Realm ID:', process.env.QUICKBOOKS_REALM_ID ? '✓ Set' : '✗ Missing');
console.log('  Environment:', process.env.QUICKBOOKS_ENVIRONMENT || 'sandbox');
console.log('');

try {
  console.log('Authenticating with QuickBooks...');
  await quickbooksClient.authenticate();
  console.log('✓ Authentication successful!');
  
  const qb = quickbooksClient.getQuickbooks();
  console.log('✓ QuickBooks client created');
  console.log('');
  
  console.log('Fetching customers...');
  qb.findCustomers({}, (err, customers) => {
    if (err) {
      console.error('✗ Error fetching customers:', JSON.stringify(err, null, 2));
      process.exit(1);
    } else {
      const customerList = customers?.QueryResponse?.Customer || [];
      console.log(`✓ Found ${customerList.length} customers:`);
      customerList.slice(0, 5).forEach((c, i) => {
        console.log(`  ${i + 1}. ${c.DisplayName} (ID: ${c.Id})`);
      });
      if (customerList.length > 5) {
        console.log(`  ... and ${customerList.length - 5} more`);
      }
      process.exit(0);
    }
  });
} catch (error) {
  console.error('✗ Error:', error.message);
  process.exit(1);
}
