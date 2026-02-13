import dotenv from "dotenv";
import QuickBooks from "node-quickbooks";
import OAuthClient from "intuit-oauth";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import open from "open";

dotenv.config();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const client_id = process.env.QUICKBOOKS_CLIENT_ID;
const client_secret = process.env.QUICKBOOKS_CLIENT_SECRET;
const refresh_token = process.env.QUICKBOOKS_REFRESH_TOKEN;
const realm_id = process.env.QUICKBOOKS_REALM_ID;
const environment = process.env.QUICKBOOKS_ENVIRONMENT || "sandbox";
const redirect_uri = process.env.QUICKBOOKS_REDIRECT_URI || "http://localhost:3001/oauth/callback";

// Only throw error if client_id or client_secret is missing
if (!client_id || !client_secret) {
  throw Error(
    "QUICKBOOKS_CLIENT_ID and QUICKBOOKS_CLIENT_SECRET must be set in environment variables"
  );
}

class QuickbooksClient {
  private readonly clientId: string;
  private readonly clientSecret: string;
  private refreshToken?: string;
  private realmId?: string;
  private readonly environment: string;
  private accessToken?: string;
  private accessTokenExpiry?: Date;
  private quickbooksInstance?: QuickBooks;
  private oauthClient: OAuthClient;
  private isAuthenticating: boolean = false;
  private redirectUri: string;
  private tokenRefreshInterval?: NodeJS.Timeout;

  constructor(config: {
    clientId: string;
    clientSecret: string;
    refreshToken?: string;
    realmId?: string;
    environment: string;
    redirectUri: string;
  }) {
    this.clientId = config.clientId;
    this.clientSecret = config.clientSecret;
    this.refreshToken = config.refreshToken;
    this.realmId = config.realmId;
    this.environment = config.environment;
    this.redirectUri = config.redirectUri;
    this.oauthClient = new OAuthClient({
      clientId: this.clientId,
      clientSecret: this.clientSecret,
      environment: this.environment,
      redirectUri: this.redirectUri,
    });
  }

  // Method to handle OAuth callback URL from external server
  async handleOAuthCallback(callbackUrl: string): Promise<void> {
    try {
      // Extract the path portion for createToken
      const url = new URL(callbackUrl);
      const pathWithQuery = url.pathname + url.search;
      
      const response = await this.oauthClient.createToken(pathWithQuery);
      const tokens = response.token;

      // Save tokens
      this.refreshToken = tokens.refresh_token;
      this.realmId = tokens.realmId;
      this.accessToken = tokens.access_token;
      
      // Calculate expiry
      const expiresIn = tokens.expires_in || 3600;
      this.accessTokenExpiry = new Date(Date.now() + expiresIn * 1000);
      
      this.saveTokensToEnv();
      this.isAuthenticating = false;
      
      console.error("OAuth tokens received and saved successfully");
    } catch (error) {
      this.isAuthenticating = false;
      throw error;
    }
  }

  private async startOAuthFlow(): Promise<void> {
    if (this.isAuthenticating) {
      // Wait for existing auth flow
      return new Promise((resolve) => {
        const checkInterval = setInterval(() => {
          if (!this.isAuthenticating) {
            clearInterval(checkInterval);
            resolve();
          }
        }, 500);
      });
    }

    this.isAuthenticating = true;

    return new Promise((resolve, reject) => {
      // Import the setOAuthCallbackResolver dynamically to avoid circular dependency
      import("../index.js").then(({ setOAuthCallbackResolver }) => {
        // Set up callback resolver
        setOAuthCallbackResolver(async (callbackUrl: string) => {
          try {
            await this.handleOAuthCallback(callbackUrl);
            resolve();
          } catch (error) {
            reject(error);
          }
        });

        // Generate authorization URL
        const authUri = this.oauthClient
          .authorizeUri({
            scope: [OAuthClient.scopes.Accounting as string],
            state: "testState",
          })
          .toString();

        console.error("");
        console.error("=".repeat(60));
        console.error("QUICKBOOKS AUTHORIZATION REQUIRED");
        console.error("=".repeat(60));
        console.error("");
        console.error("Please open this URL in your browser to authorize:");
        console.error("");
        console.error(authUri);
        console.error("");
        console.error("=".repeat(60));
        console.error("");

        // Try to open browser automatically
        open(authUri).catch(() => {
          console.error("Could not open browser automatically. Please open the URL manually.");
        });
      });
    });
  }

  private saveTokensToEnv(): void {
    try {
      // Always update process.env so the running container uses the new token
      if (this.refreshToken) {
        process.env.QUICKBOOKS_REFRESH_TOKEN = this.refreshToken;
      }
      if (this.realmId) {
        process.env.QUICKBOOKS_REALM_ID = this.realmId;
      }

      // Also try to save to .env file (works locally, but not in Docker)
      const tokenPath = path.join(__dirname, "..", "..", ".env");
      
      if (fs.existsSync(tokenPath)) {
        let envContent = fs.readFileSync(tokenPath, "utf-8");
        const envLines = envContent.split("\n");

        const updateEnvVar = (name: string, value: string) => {
          const index = envLines.findIndex((line) =>
            line.startsWith(`${name}=`)
          );
          if (index !== -1) {
            envLines[index] = `${name}=${value}`;
          } else {
            envLines.push(`${name}=${value}`);
          }
        };

        if (this.refreshToken)
          updateEnvVar("QUICKBOOKS_REFRESH_TOKEN", this.refreshToken);
        if (this.realmId) updateEnvVar("QUICKBOOKS_REALM_ID", this.realmId);

        fs.writeFileSync(tokenPath, envLines.join("\n"));
        console.error("✓ Tokens saved to local .env file");
      }
      
      // Log the new refresh token for Azure update
      console.error("");
      console.error("=".repeat(80));
      console.error("🔄 REFRESH TOKEN ROTATED - ACTION REQUIRED");
      console.error("=".repeat(80));
      console.error("");
      console.error("QuickBooks issued a new refresh token. To persist this in Azure:");
      console.error("");
      console.error("Run this command:");
      console.error("");
      console.error(`az containerapp update \\`);
      console.error(`  --name mcp-quickbooks \\`);
      console.error(`  --resource-group rg-a2a-prod \\`);
      console.error(`  --set-env-vars "QUICKBOOKS_REFRESH_TOKEN=${this.refreshToken}"`);
      console.error("");
      console.error("Or redeploy with: ./deploy-mcp-quickbooks.sh");
      console.error("");
      console.error("=".repeat(80));
      console.error("");
    } catch (error) {
      console.error("Error saving tokens:", error);
    }
  }

  async refreshAccessToken() {
    if (!this.refreshToken) {
      const errorMsg = "No refresh token available. Please set QUICKBOOKS_REFRESH_TOKEN in environment variables.";
      console.error(errorMsg);
      throw new Error(errorMsg);
    }

    try {
      console.error("Attempting to refresh QuickBooks access token...");
      
      // At this point we know refreshToken is not undefined
      const authResponse = await this.oauthClient.refreshUsingToken(
        this.refreshToken
      );

      this.accessToken = authResponse.token.access_token;
      console.error("✓ Access token refreshed successfully");
      
      // Update refresh token if a new one was provided
      if (authResponse.token.refresh_token) {
        this.refreshToken = authResponse.token.refresh_token;
        this.saveTokensToEnv();
        console.error("✓ New refresh token saved");
      }

      // Calculate expiry time
      const expiresIn = authResponse.token.expires_in || 3600; // Default to 1 hour
      this.accessTokenExpiry = new Date(Date.now() + expiresIn * 1000);
      console.error(`✓ Token expires at: ${this.accessTokenExpiry.toISOString()}`);

      return {
        access_token: this.accessToken,
        expires_in: expiresIn,
      };
    } catch (error: any) {
      // Log the full error for debugging
      console.error("❌ Token refresh failed:", error.message);
      console.error("Error details:", error);
      
      // Check if it's an expired refresh token error
      if (error.message?.includes("invalid_grant") || error.message?.includes("token") || error.authResponse?.status === 400) {
        const errorMsg = "QuickBooks refresh token is invalid or expired. Please re-authenticate using the OAuth flow locally and update QUICKBOOKS_REFRESH_TOKEN environment variable.";
        console.error(errorMsg);
        throw new Error(errorMsg);
      }
      
      throw new Error(`Failed to refresh QuickBooks token: ${error.message}`);
    }
  }

  async authenticate() {
    if (!this.refreshToken || !this.realmId) {
      const errorMsg = `Missing required credentials: ${!this.refreshToken ? 'QUICKBOOKS_REFRESH_TOKEN' : ''} ${!this.realmId ? 'QUICKBOOKS_REALM_ID' : ''}`;
      console.error(errorMsg);
      throw new Error(errorMsg);
    }

    console.error("Authenticating with QuickBooks...");
    console.error(`- Realm ID: ${this.realmId}`);
    console.error(`- Environment: ${this.environment}`);
    console.error(`- Refresh Token: ${this.refreshToken?.substring(0, 10)}...`);

    // Check if token exists and is still valid
    const now = new Date();
    if (
      !this.accessToken ||
      !this.accessTokenExpiry ||
      this.accessTokenExpiry <= now
    ) {
      console.error("Access token missing or expired, refreshing...");
      const tokenResponse = await this.refreshAccessToken();
      this.accessToken = tokenResponse.access_token;
    } else {
      console.error("✓ Using cached access token (still valid)");
    }

    // At this point we know all tokens are available
    this.quickbooksInstance = new QuickBooks(
      this.clientId,
      this.clientSecret,
      this.accessToken!, // Safe to use ! here as we just set it
      false, // no token secret for OAuth 2.0
      this.realmId!, // Safe to use ! here as we checked above
      this.environment === "sandbox", // use the sandbox?
      false, // debug?
      null, // minor version
      "2.0", // oauth version
      this.refreshToken
    );

    console.error("✓ QuickBooks client authenticated successfully");

    // Start proactive token refresh to prevent expiration
    this.startProactiveTokenRefresh();

    return this.quickbooksInstance;
  }

  /**
   * Starts a background interval that proactively refreshes tokens every 50 minutes.
   * This prevents the refresh token from expiring by keeping it actively used.
   * QuickBooks extends the refresh token lifetime each time it's used to get a new access token.
   */
  private startProactiveTokenRefresh() {
    // Clear any existing interval
    if (this.tokenRefreshInterval) {
      clearInterval(this.tokenRefreshInterval);
    }

    // Refresh access token every 50 minutes (before 1-hour expiry)
    // This keeps the refresh token active and extends its lifetime
    const REFRESH_INTERVAL_MS = 50 * 60 * 1000; // 50 minutes

    this.tokenRefreshInterval = setInterval(async () => {
      try {
        console.error("🔄 Proactive token refresh starting...");
        await this.refreshAccessToken();
        console.error("✓ Proactive token refresh completed successfully");
      } catch (error: any) {
        console.error("❌ Proactive token refresh failed:", error.message);
        // Don't stop the interval - maybe next refresh will succeed
      }
    }, REFRESH_INTERVAL_MS);

    console.error(`✓ Proactive token refresh enabled (every ${REFRESH_INTERVAL_MS / 60000} minutes)`);
  }

  /**
   * Stops the proactive token refresh interval (for cleanup)
   */
  stopProactiveTokenRefresh() {
    if (this.tokenRefreshInterval) {
      clearInterval(this.tokenRefreshInterval);
      this.tokenRefreshInterval = undefined;
      console.error("✓ Proactive token refresh stopped");
    }
  }

  getQuickbooks() {
    if (!this.quickbooksInstance) {
      throw new Error(
        "QuickBooks not authenticated. Call authenticate() first"
      );
    }
    return this.quickbooksInstance;
  }

  getRealmId(): string | undefined {
    return this.realmId;
  }

  isConnected(): boolean {
    return !!(this.refreshToken && this.realmId && this.accessToken);
  }
}

export const quickbooksClient = new QuickbooksClient({
  clientId: client_id,
  clientSecret: client_secret,
  refreshToken: refresh_token,
  realmId: realm_id,
  environment: environment,
  redirectUri: redirect_uri,
});
