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

      // Auto-persist rotated refresh token to Azure Container App env var
      // so it survives container restarts. Uses managed identity (IMDS).
      this.persistTokenToAzure().catch((err) => {
        console.error("⚠ Azure token persistence failed (non-fatal):", err.message);
      });
    } catch (error) {
      console.error("Error saving tokens:", error);
    }
  }

  /**
   * Persist the rotated refresh token to the Azure Container App's env vars
   * using managed identity via IMDS. This ensures the token survives container
   * restarts without manual intervention.
   */
  private async persistTokenToAzure(): Promise<void> {
    const subscriptionId = process.env.AZURE_SUBSCRIPTION_ID;
    const resourceGroup = process.env.AZURE_RESOURCE_GROUP || "rg-a2a-prod";
    const containerAppName = process.env.AZURE_CONTAINER_APP_NAME || "mcp-quickbooks";
    const clientId = process.env.AZURE_CLIENT_ID;

    if (!subscriptionId) {
      console.error("⚠ AZURE_SUBSCRIPTION_ID not set — skipping Azure token persistence");
      return;
    }

    // Step 1: Get an access token from IMDS using managed identity
    const imdsUrl = new URL("http://169.254.169.254/metadata/identity/oauth2/token");
    imdsUrl.searchParams.set("api-version", "2018-02-01");
    imdsUrl.searchParams.set("resource", "https://management.azure.com/");
    if (clientId) {
      imdsUrl.searchParams.set("client_id", clientId);
    }

    const tokenResp = await fetch(imdsUrl.toString(), {
      headers: { Metadata: "true" },
    });
    if (!tokenResp.ok) {
      throw new Error(`IMDS token request failed: ${tokenResp.status} ${await tokenResp.text()}`);
    }
    const { access_token: azureToken } = await tokenResp.json() as any;

    // Step 2: GET the current container app config
    const armBase = `https://management.azure.com/subscriptions/${subscriptionId}/resourceGroups/${resourceGroup}/providers/Microsoft.App/containerApps/${containerAppName}`;
    const apiVersion = "2024-03-01";

    const appResp = await fetch(`${armBase}?api-version=${apiVersion}`, {
      headers: { Authorization: `Bearer ${azureToken}` },
    });
    if (!appResp.ok) {
      throw new Error(`Failed to GET container app: ${appResp.status}`);
    }
    const appConfig = await appResp.json() as any;

    // Step 3: Update the QUICKBOOKS_REFRESH_TOKEN env var in the template
    const containers = appConfig.properties?.template?.containers;
    if (!containers || containers.length === 0) {
      throw new Error("No containers found in app config");
    }

    const envVars: Array<{ name: string; value?: string; secretRef?: string }> = containers[0].env || [];
    const idx = envVars.findIndex((e: any) => e.name === "QUICKBOOKS_REFRESH_TOKEN");
    if (idx !== -1) {
      envVars[idx].value = this.refreshToken!;
    } else {
      envVars.push({ name: "QUICKBOOKS_REFRESH_TOKEN", value: this.refreshToken! });
    }
    containers[0].env = envVars;

    // Step 4: PATCH the container app with the updated config
    const patchResp = await fetch(`${armBase}?api-version=${apiVersion}`, {
      method: "PATCH",
      headers: {
        Authorization: `Bearer ${azureToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        properties: {
          template: appConfig.properties.template,
        },
      }),
    });

    if (!patchResp.ok) {
      throw new Error(`Failed to PATCH container app: ${patchResp.status} ${await patchResp.text()}`);
    }

    console.error("✓ Refresh token auto-persisted to Azure Container App env var");
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

    // Check if token exists and is still valid (or will expire soon)
    // Refresh proactively if token expires within 10 minutes
    // This keeps refresh token active even with scale-to-zero (min replicas = 0)
    const now = new Date();
    const tenMinutesFromNow = new Date(now.getTime() + 10 * 60 * 1000);

    if (
      !this.accessToken ||
      !this.accessTokenExpiry ||
      this.accessTokenExpiry <= tenMinutesFromNow
    ) {
      console.error("Access token missing or expiring soon, refreshing...");
      console.error(`- Current time: ${now.toISOString()}`);
      console.error(`- Token expiry: ${this.accessTokenExpiry?.toISOString() || 'unknown'}`);
      const tokenResponse = await this.refreshAccessToken();
      this.accessToken = tokenResponse.access_token;
    } else {
      const minutesRemaining = Math.floor((this.accessTokenExpiry.getTime() - now.getTime()) / 60000);
      console.error(`✓ Using cached access token (valid for ${minutesRemaining} more minutes)`);
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

    return this.quickbooksInstance;
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
