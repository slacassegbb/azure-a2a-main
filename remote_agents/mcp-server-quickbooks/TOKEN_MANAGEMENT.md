# QuickBooks OAuth Token Management

## Understanding QuickBooks Tokens

QuickBooks uses OAuth 2.0 with two types of tokens:

1. **Access Token** 
   - Expires: **1 hour**
   - Used for API calls
   - Automatically refreshed by the server

2. **Refresh Token**
   - Expires: **100 days** (if unused)
   - Used to get new access tokens
   - **Rotates** when used (old token becomes invalid)

## The Token Rotation Problem

When you refresh an access token, QuickBooks gives you a **new** refresh token. The old one becomes invalid. This creates a challenge for containerized deployments:

1. Server refreshes access token
2. Gets new refresh token
3. Saves it to local memory (works for current session)
4. Container restarts → uses old refresh token from environment variable → **FAILS**

## Solutions

### Option 1: Long-lived Refresh Tokens (Recommended)

**Keep your refresh token alive by using it regularly:**

- Refresh tokens expire after 100 days of **inactivity**
- Each time you refresh, you get a new 100-day window
- As long as your server calls QuickBooks APIs at least once every 100 days, the token stays valid

**What the server does:**
- ✅ Automatically refreshes access tokens every hour
- ✅ Updates `process.env.QUICKBOOKS_REFRESH_TOKEN` in memory
- ✅ Logs the new refresh token when it rotates
- ✅ Continues working until container restarts

**What you need to do:**
- Monitor server logs for "REFRESH TOKEN ROTATED" messages
- When you see one, update Azure environment variable:
  ```bash
  az containerapp update \
    --name mcp-quickbooks \
    --resource-group rg-a2a-prod \
    --set-env-vars "QUICKBOOKS_REFRESH_TOKEN=<new_token>"
  ```
- Or redeploy: `./deploy-mcp-quickbooks.sh`

### Option 2: Automated Token Persistence (Advanced)

Store tokens in Azure Key Vault or a database, and have the server update them automatically. This requires additional infrastructure.

### Option 3: Manual Token Refresh (Simplest)

If you don't use the server frequently:

1. Every ~90 days, refresh your token manually via:
   - **Intuit OAuth Playground**: https://developer.intuit.com/app/developer/playground
   - Or run local OAuth flow and copy new token

2. Update Azure:
   ```bash
   az containerapp update \
     --name mcp-quickbooks \
     --resource-group rg-a2a-prod \
     --set-env-vars "QUICKBOOKS_REFRESH_TOKEN=<new_token>"
   ```

## How to Get a New Refresh Token

### Method 1: Intuit OAuth Playground (Fastest)

1. Go to: https://developer.intuit.com/app/developer/playground
2. Select your app
3. Select scopes: **Accounting**
4. Click **Get OAuth 2.0 tokens**
5. Sign in with your QuickBooks account
6. Copy the **Refresh Token**
7. Update `.env` locally:
   ```
   QUICKBOOKS_REFRESH_TOKEN=<new_token>
   ```
8. Redeploy: `./deploy-mcp-quickbooks.sh`

### Method 2: Local OAuth Flow

1. Start server locally:
   ```bash
   TRANSPORT_MODE=http PORT=3001 node dist/index.js
   ```

2. Trigger OAuth by making any API call:
   ```bash
   curl -X POST http://localhost:3001/sse \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","method":"tools/call","id":1,"params":{"name":"qbo_search_customers","arguments":{}}}'
   ```

3. Browser opens → Complete OAuth flow
4. New tokens saved to `.env`
5. Redeploy: `./deploy-mcp-quickbooks.sh`

## Monitoring Token Health

### Test your current token:
```bash
node test-tokens.js
```

### Check Azure logs:
```bash
az containerapp logs show \
  --name mcp-quickbooks \
  --resource-group rg-a2a-prod \
  --follow
```

Look for:
- ✅ "Access token refreshed successfully"
- ✅ "Token expires at: ..."
- ❌ "Token refresh failed: invalid_grant"
- 🔄 "REFRESH TOKEN ROTATED - ACTION REQUIRED"

## Best Practices

1. **Use your MCP server regularly** - Each API call refreshes the token window
2. **Monitor logs weekly** - Check for token rotation messages
3. **Set up alerts** - Azure Monitor can alert on specific log messages
4. **Keep local `.env` updated** - Always use latest token for local development
5. **Document token refresh dates** - Track when you last updated tokens

## Troubleshooting

### Server hangs on API calls
- **Cause**: Refresh token expired
- **Fix**: Get new token from OAuth Playground, update Azure

### "invalid_grant" error
- **Cause**: Refresh token is invalid or expired
- **Fix**: Get new token, redeploy

### Container works after deploy, fails after restart
- **Cause**: New refresh token not updated in Azure environment variables
- **Fix**: Check logs for rotated token, update Azure

## Quick Reference

| Action | Command |
|--------|---------|
| Test tokens | `node test-tokens.js` |
| Get new tokens locally | `TRANSPORT_MODE=http PORT=3001 node dist/index.js` |
| Update Azure token | `az containerapp update --name mcp-quickbooks --resource-group rg-a2a-prod --set-env-vars "QUICKBOOKS_REFRESH_TOKEN=<token>"` |
| Redeploy | `./deploy-mcp-quickbooks.sh` |
| View logs | `az containerapp logs show --name mcp-quickbooks --resource-group rg-a2a-prod --follow` |
| OAuth Playground | https://developer.intuit.com/app/developer/playground |
