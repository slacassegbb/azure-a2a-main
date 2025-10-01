/**
 * Azure Event Hub client for the Next.js frontend
 * 
 * This module provides real-time event consumption from the A2A system
 * via Azure Event Hub, replacing the mock implementation.
 */

import { EventHubConsumerClient, ReceivedEventData } from "@azure/event-hubs";
import { DefaultAzureCredential } from "@azure/identity";
import {
  A2AEventEnvelope,
  A2A_EVENT_TYPES,
  parseA2AEvent,
  isAgentRegisteredEvent,
  isAgentSelfRegisteredEvent,
  isMessageEvent,
  isConversationCreatedEvent,
  isTaskEvent,
  isFileUploadEvent,
  isFormSubmittedEvent,
  isToolCallEvent,
  isToolResponseEvent,
  isRemoteAgentToolCallEvent
} from "./a2a-event-types";

type EventCallback = (data: any) => void;
type Subscribers = {
  [key: string]: EventCallback[];
};

interface AzureEventHubConfig {
  fullyQualifiedNamespace: string;
  eventHubName: string;
  consumerGroup: string;
  connectionString?: string;
  useManagedIdentity?: boolean;
}

class AzureEventHubClient {
  private subscribers: Subscribers = {};
  private consumerClient: EventHubConsumerClient | null = null;
  private isConnected: boolean = false;
  private isReconnecting: boolean = false;
  private reconnectionTimeout: NodeJS.Timeout | null = null;
  private connectionLifetimeTimeout: NodeJS.Timeout | null = null;
  private subscription: any = null;
  private config: AzureEventHubConfig;
  private recentToolCalls: Set<string> = new Set(); // Track recent tool calls to prevent duplicates
  private connectionStartTime: number = 0;
  private readonly CONNECTION_LIFETIME_MS = 5 * 60 * 1000; // 5 minutes
  private availableConsumerGroups: string[] = ['a1', 'a2', 'a3', 'a4', 'a5'];
  private currentConsumerGroupIndex: number = 0;
  private currentConsumerGroup: string;

  constructor(config: AzureEventHubConfig) {
    this.config = {
      useManagedIdentity: true,
      ...config
    };
    
    // Initialize with a random consumer group to distribute load
    this.currentConsumerGroupIndex = Math.floor(Math.random() * this.availableConsumerGroups.length);
    this.currentConsumerGroup = this.availableConsumerGroups[this.currentConsumerGroupIndex];
    console.log(`[EventHub] Starting with consumer group: ${this.currentConsumerGroup}`);
  }

  async initialize(): Promise<boolean> {
    try {
      console.log(`[EventHub] Initializing with consumer group: ${this.currentConsumerGroup}`);
      
      if (this.config.connectionString) {
        // Use connection string authentication
        this.consumerClient = new EventHubConsumerClient(
          this.currentConsumerGroup,
          this.config.connectionString,
          this.config.eventHubName
        );
        console.log("[EventHub] Initialized with connection string");
      } else {
        // Use Managed Identity authentication
        const credential = new DefaultAzureCredential();
        this.consumerClient = new EventHubConsumerClient(
          this.currentConsumerGroup,
          this.config.fullyQualifiedNamespace,
          this.config.eventHubName,
          credential
        );
        console.log(`[EventHub] Initialized with Managed Identity for ${this.config.fullyQualifiedNamespace}`);
      }

      await this.startListening();
      this.isConnected = true;
      this.connectionStartTime = Date.now();
      
      // Set up automatic connection refresh to prevent receiver accumulation
      this.scheduleConnectionRefresh();
      
      console.log(`[EventHub] Successfully connected to consumer group ${this.currentConsumerGroup} and listening for events`);
      return true;
    } catch (error: any) {
      console.error(`[EventHub] Failed to initialize with consumer group ${this.currentConsumerGroup}:`, error);
      
      // If this is a receiver limit error, rotate to next consumer group and try again
      if (error.message?.includes('maximum number of allowed receivers')) {
        console.log(`[EventHub] Consumer group ${this.currentConsumerGroup} has reached receiver limit, rotating to next group...`);
        this.rotateToNextConsumerGroup();
        // Don't wait as long since we're using a different consumer group
        return false; // Let the caller handle retry logic
      }
      
      return false;
    }
  }

  private async startListening(): Promise<void> {
    if (!this.consumerClient) {
      throw new Error("Event Hub client not initialized");
    }

    console.log("[EventHub] Starting to listen for events...");

    try {
      // Use a unique subscription ID to avoid conflicts between instances
      const instanceId = Math.random().toString(36).substring(2, 8);
      const subscriptionOptions = {
        // Start from the latest events to avoid replaying old events
        startPosition: { enqueuedOn: new Date() },
        maxBatchSize: 1,
        maxWaitTimeInSeconds: 60,
        // Add instance identifier for debugging
        identifier: `frontend-${instanceId}`
      };

      this.subscription = this.consumerClient.subscribe({
        processEvents: async (events: ReceivedEventData[], context) => {
          for (const event of events) {
            await this.handleEvent(event);
          }
        },
        processError: async (err, context) => {
          console.error("[EventHub] Error processing events:", err);
          
          // Don't attempt reconnect if already reconnecting
          if (this.isReconnecting) {
            console.log("[EventHub] Already reconnecting, skipping error handling...");
            return;
          }
          
          // Check for various receiver/connection limit errors
          const errorMessage = err.message?.toLowerCase() || '';
          if (errorMessage.includes('maximum number of allowed receivers') ||
              errorMessage.includes('receiver limit') ||
              errorMessage.includes('too many receivers') ||
              errorMessage.includes('receiver already exists')) {
            console.log(`[EventHub] Receiver limit reached on consumer group ${this.currentConsumerGroup}, rotating to next group...`);
            this.isConnected = false;
            
            // Rotate to the next consumer group
            this.rotateToNextConsumerGroup();
            
            // Shorter delay since we're switching to a different consumer group
            this.reconnectionTimeout = setTimeout(() => this.reconnect(), 2000 + Math.random() * 3000);
          } else if (errorMessage.includes('connection was disconnected') ||
                    errorMessage.includes('connection lost') ||
                    errorMessage.includes('amqp error')) {
            console.log("[EventHub] Connection lost, attempting reconnect...");
            this.isConnected = false;
            this.reconnectionTimeout = setTimeout(() => this.reconnect(), 2000 + Math.random() * 3000);
          } else {
            // For other errors, try to reconnect after shorter delay
            this.isConnected = false;
            this.reconnectionTimeout = setTimeout(() => this.reconnect(), 5000);
          }
        }
      }, subscriptionOptions);

      this.isConnected = true;
      console.log(`[EventHub] Successfully connected and listening for events (instance: ${instanceId})`);
    } catch (error) {
      console.error("[EventHub] Failed to start listening:", error);
      throw error;
    }
  }

  private async handleEvent(event: ReceivedEventData): Promise<void> {
    try {
      let a2aEvent: A2AEventEnvelope | null = null;
      
      // Handle both string and object event bodies
      if (typeof event.body === 'string') {
        a2aEvent = parseA2AEvent(event.body);
      } else if (typeof event.body === 'object' && event.body !== null) {
        // Event body is already an object, validate and use directly
        const eventBody = event.body as any;
        if (eventBody.eventType && eventBody.timestamp && eventBody.eventId && eventBody.data) {
          a2aEvent = eventBody as A2AEventEnvelope;
        } else {
          console.warn("[EventHub] Invalid A2A event structure:", eventBody);
          return;
        }
      } else {
        console.warn("[EventHub] Unexpected event body type:", typeof event.body, event.body);
        return;
      }

      if (!a2aEvent) {
        console.warn("[EventHub] Failed to parse A2A event:", event.body);
        return;
      }

      console.log(`[EventHub] Received event: ${a2aEvent.eventType}`, a2aEvent.data);

      // Handle specific event types and emit to subscribers
      switch (a2aEvent.eventType) {
        case A2A_EVENT_TYPES.AGENT_REGISTERED:
        case A2A_EVENT_TYPES.AGENT_SELF_REGISTERED:
          if (isAgentRegisteredEvent(a2aEvent.data) || isAgentSelfRegisteredEvent(a2aEvent.data)) {
            // Transform to format expected by frontend
            const agentData = {
              name: a2aEvent.data.agentName,
              status: "online",
              avatar: a2aEvent.data.avatar,
              type: isAgentSelfRegisteredEvent(a2aEvent.data) ? a2aEvent.data.agentType : "generic",
              capabilities: isAgentSelfRegisteredEvent(a2aEvent.data) ? a2aEvent.data.capabilities : [],
              endpoint: isAgentSelfRegisteredEvent(a2aEvent.data) ? a2aEvent.data.endpoint : undefined
            };
            // Only emit one event to avoid duplicates
            this._emit("agent_registered", agentData);
          }
          break;

        case A2A_EVENT_TYPES.MESSAGE:
          if (isMessageEvent(a2aEvent.data)) {
            this._emit("message", a2aEvent.data);
          }
          break;

        case A2A_EVENT_TYPES.CONVERSATION_CREATED:
          if (isConversationCreatedEvent(a2aEvent.data)) {
            this._emit("conversation_created", a2aEvent.data);
          }
          break;

        case A2A_EVENT_TYPES.TASK_CREATED:
        case A2A_EVENT_TYPES.TASK_UPDATED:
          if (isTaskEvent(a2aEvent.data)) {
            this._emit("task_updated", a2aEvent.data);
          }
          break;

        case A2A_EVENT_TYPES.FILE_UPLOADED:
          if (isFileUploadEvent(a2aEvent.data)) {
            this._emit("file_uploaded", a2aEvent.data);
          }
          break;

        case A2A_EVENT_TYPES.FORM_SUBMITTED:
          if (isFormSubmittedEvent(a2aEvent.data)) {
            this._emit("form_submitted", a2aEvent.data);
          }
          break;

        case A2A_EVENT_TYPES.TOOL_CALL:
          if (isToolCallEvent(a2aEvent.data)) {
            // Skip generic remote_agent_call events as they will be followed by more specific events
            if (a2aEvent.data.toolName === "remote_agent_call") {
              console.log("[EventHub] Skipping generic remote_agent_call event - more specific event will follow");
              break;
            }
            
            // Create a unique key for this tool call to prevent duplicates
            const toolCallKey = `${a2aEvent.data.agentName}-${a2aEvent.data.timestamp}-${a2aEvent.data.toolName}`;
            
            // Skip if we've already processed this tool call recently
            if (this.recentToolCalls.has(toolCallKey)) {
              console.log("[EventHub] Skipping duplicate tool call:", toolCallKey);
              break;
            }
            
            // Add to recent tool calls
            this.recentToolCalls.add(toolCallKey);
            
            // Transform tool call data for frontend
            const toolCallData = {
              agent: a2aEvent.data.agentName,
              status: `🛠️ Calling ${a2aEvent.data.toolName}`,
              timestamp: a2aEvent.data.timestamp,
              toolName: a2aEvent.data.toolName,
              arguments: a2aEvent.data.arguments
            };
            this._emit("inference_step", toolCallData);
            this._emit("tool_call", a2aEvent.data);
          }
          break;

        case A2A_EVENT_TYPES.TOOL_RESPONSE:
          if (isToolResponseEvent(a2aEvent.data)) {
            // Create a unique key for this tool response to prevent duplicates
            const toolResponseKey = `response-${a2aEvent.data.agentName}-${a2aEvent.data.timestamp}-${a2aEvent.data.toolName}`;
            
            // Skip if we've already processed this tool response recently
            if (this.recentToolCalls.has(toolResponseKey)) {
              console.log("[EventHub] Skipping duplicate tool response:", toolResponseKey);
              break;
            }
            
            // Add to recent tool calls
            this.recentToolCalls.add(toolResponseKey);
            
            // Transform tool response data for frontend
            const toolResponseData = {
              agent: a2aEvent.data.agentName,
              status: `✅ ${a2aEvent.data.toolName} completed`,
              timestamp: a2aEvent.data.timestamp,
              toolName: a2aEvent.data.toolName,
              response: a2aEvent.data.response
            };
            this._emit("inference_step", toolResponseData);
            this._emit("tool_response", a2aEvent.data);
          }
          break;

        case A2A_EVENT_TYPES.REMOTE_AGENT_TOOL_CALL:
        case A2A_EVENT_TYPES.REMOTE_AGENT_TOOL_RESPONSE:
        case A2A_EVENT_TYPES.REMOTE_AGENT_TOOL_ACTIVITY:
        case A2A_EVENT_TYPES.REMOTE_AGENT_ARTIFACT:
        case A2A_EVENT_TYPES.REMOTE_AGENT_RESPONSE:
        case A2A_EVENT_TYPES.REMOTE_AGENT_TASK:
          // Handle remote agent events with proper typing
          if (isRemoteAgentToolCallEvent(a2aEvent.data)) {
            // Create a unique key for this tool call to prevent duplicates
            const toolCallKey = `${a2aEvent.data.agentName}-${a2aEvent.data.timestamp}-${a2aEvent.data.toolName || 'unknown'}`;
            
            // Skip if we've already processed this tool call recently
            if (this.recentToolCalls.has(toolCallKey)) {
              console.log("[EventHub] Skipping duplicate tool call:", toolCallKey);
              break;
            }
            
            // Add to recent tool calls and clean up old entries
            this.recentToolCalls.add(toolCallKey);
            
            // Clean up old entries (keep only last 100)
            if (this.recentToolCalls.size > 100) {
              const entries = Array.from(this.recentToolCalls);
              this.recentToolCalls.clear();
              entries.slice(-50).forEach(entry => this.recentToolCalls.add(entry));
            }
            
            let displayStatus = a2aEvent.data.content;
            
            // If this is a tool call and we have the actual tool name, ensure it's displayed properly
            if (a2aEvent.data.isToolCall && a2aEvent.data.toolName) {
              // If the content still shows "🛠️ Calling tool: toolname", clean it up to just show the tool name
              if (displayStatus.includes('🛠️ Calling tool:')) {
                displayStatus = `🛠️ Calling ${a2aEvent.data.toolName}`;
              } else if (displayStatus.includes('✅ Tool ') && displayStatus.includes(' completed')) {
                displayStatus = `✅ ${a2aEvent.data.toolName} completed`;
              } else if (!displayStatus.includes(a2aEvent.data.toolName)) {
                // If the content doesn't contain the tool name at all, add it
                displayStatus = `🛠️ Calling ${a2aEvent.data.toolName}`;
              }
            }
            
            const remoteAgentData = {
              agent: a2aEvent.data.agentName,
              status: displayStatus,
              timestamp: a2aEvent.data.timestamp,
              isToolCall: a2aEvent.data.isToolCall,
              toolName: a2aEvent.data.toolName,
              toolArgs: a2aEvent.data.toolArgs
            };
            
            // Only emit inference_step to avoid duplicates in thinking window
            this._emit("inference_step", remoteAgentData);
          }
          break;

        default:
          // Emit generic event for any other types
          this._emit(a2aEvent.eventType, a2aEvent.data);
          break;
      }

      // Always emit the raw event for subscribers who want everything
      this._emit("*", a2aEvent);

    } catch (error) {
      console.error("[EventHub] Error handling event:", error);
    }
  }

  private async reconnect(): Promise<void> {
    // Prevent multiple concurrent reconnection attempts
    if (this.isReconnecting) {
      console.log("[EventHub] Reconnection already in progress, skipping...");
      return;
    }

    this.isReconnecting = true;
    console.log("[EventHub] Attempting to reconnect...");
    
    try {
      // Clear any existing timeout
      if (this.reconnectionTimeout) {
        clearTimeout(this.reconnectionTimeout);
        this.reconnectionTimeout = null;
      }
      
      // Close current connection first
      await this.close();
      
      // Wait a bit before reconnecting to allow other connections to stabilize
      const delay = 2000 + Math.random() * 3000; // Random delay 2-5 seconds
      await new Promise(resolve => setTimeout(resolve, delay));
      
      // Try to reinitialize
      const success = await this.initialize();
      if (!success) {
        console.log("[EventHub] Reconnection failed, will retry...");
        // Try again after longer delay
        this.reconnectionTimeout = setTimeout(() => {
          this.isReconnecting = false;
          this.reconnect();
        }, 15000 + Math.random() * 10000);
      } else {
        this.isReconnecting = false;
      }
    } catch (error) {
      console.error("[EventHub] Reconnection failed:", error);
      // Try again after longer delay
      this.reconnectionTimeout = setTimeout(() => {
        this.isReconnecting = false;
        this.reconnect();
      }, 15000 + Math.random() * 10000);
    }
  }

  private scheduleConnectionRefresh(): void {
    // Automatically refresh the connection after the lifetime expires
    // This helps prevent receiver accumulation by cycling connections
    console.log(`[EventHub] Scheduling connection refresh in ${this.CONNECTION_LIFETIME_MS / 1000 / 60} minutes`);
    
    this.connectionLifetimeTimeout = setTimeout(async () => {
      if (this.isConnected && !this.isReconnecting) {
        console.log("[EventHub] Connection lifetime expired, refreshing connection...");
        
        // Rotate to next consumer group on scheduled refresh for better load distribution
        this.rotateToNextConsumerGroup();
        
        await this.close();
        await this.reconnect();
      }
    }, this.CONNECTION_LIFETIME_MS);
  }

  private rotateToNextConsumerGroup(): void {
    this.currentConsumerGroupIndex = (this.currentConsumerGroupIndex + 1) % this.availableConsumerGroups.length;
    this.currentConsumerGroup = this.availableConsumerGroups[this.currentConsumerGroupIndex];
    console.log(`[EventHub] Rotating to next consumer group: ${this.currentConsumerGroup}`);
  }

  subscribe(eventName: string, callback: EventCallback): void {
    if (!this.subscribers[eventName]) {
      this.subscribers[eventName] = [];
    }
    this.subscribers[eventName].push(callback);
    console.log(`[EventHub] Subscribed to event: ${eventName}`);
  }

  unsubscribe(eventName: string, callback: EventCallback): void {
    if (this.subscribers[eventName]) {
      this.subscribers[eventName] = this.subscribers[eventName].filter((cb) => cb !== callback);
      console.log(`[EventHub] Unsubscribed from event: ${eventName}`);
    }
  }

  private _emit(eventName: string, data: any): void {
    if (this.subscribers[eventName]) {
      this.subscribers[eventName].forEach((callback) => {
        try {
          callback(data);
        } catch (error) {
          console.error(`[EventHub] Error in event handler for ${eventName}:`, error);
        }
      });
    }
  }

  // Public emit method for frontend components to emit internal events
  emit(eventName: string, data: any): void {
    this._emit(eventName, data);
  }

  async close(): Promise<void> {
    try {
      // Clear any pending reconnection timeout
      if (this.reconnectionTimeout) {
        clearTimeout(this.reconnectionTimeout);
        this.reconnectionTimeout = null;
      }
      
      // Clear any pending connection lifetime timeout
      if (this.connectionLifetimeTimeout) {
        clearTimeout(this.connectionLifetimeTimeout);
        this.connectionLifetimeTimeout = null;
      }
      
      if (this.subscription) {
        await this.subscription.close();
        this.subscription = null;
      }
      if (this.consumerClient) {
        await this.consumerClient.close();
        this.consumerClient = null;
      }
      this.isConnected = false;
      this.isReconnecting = false;
      console.log("[EventHub] Connection closed");
    } catch (error) {
      console.error("[EventHub] Error closing connection:", error);
    }
  }

  getConnectionStatus(): boolean {
    return this.isConnected;
  }

  getCurrentConsumerGroup(): string {
    return this.currentConsumerGroup;
  }

  getConnectionInfo(): { isConnected: boolean; consumerGroup: string; connectionTime: number } {
    return {
      isConnected: this.isConnected,
      consumerGroup: this.currentConsumerGroup,
      connectionTime: this.connectionStartTime
    };
  }
}

// Mock Event Hub for development/fallback
class MockEventHub {
  private subscribers: Subscribers = {};

  subscribe(eventName: string, callback: EventCallback) {
    if (!this.subscribers[eventName]) {
      this.subscribers[eventName] = [];
    }
    this.subscribers[eventName].push(callback);
    console.log(`[MockEventHub] Subscribed to event: ${eventName}`);
  }

  unsubscribe(eventName: string, callback: EventCallback) {
    if (this.subscribers[eventName]) {
      this.subscribers[eventName] = this.subscribers[eventName].filter((cb) => cb !== callback);
      console.log(`[MockEventHub] Unsubscribed from event: ${eventName}`);
    }
  }

  emit(eventName: string, data: any) {
    if (this.subscribers[eventName]) {
      this.subscribers[eventName].forEach((callback) => {
        try {
          callback(data);
        } catch (error) {
          console.error(`[MockEventHub] Error in event handler for ${eventName}:`, error);
        }
      });
    }
  }

  getConnectionStatus(): boolean {
    return false; // Mock is always "disconnected" from real Event Hub
  }
}

// Factory function to create the appropriate event hub client
function createEventHubClient(): AzureEventHubClient | MockEventHub {
  // Check if running in browser environment
  if (typeof window === 'undefined') {
    console.log("[EventHub] Server-side rendering, using mock client");
    return new MockEventHub();
  }

  // Get configuration from environment variables
  const fullyQualifiedNamespace = process.env.NEXT_PUBLIC_AZURE_EVENTHUB_NAMESPACE;
  const eventHubName = process.env.NEXT_PUBLIC_AZURE_EVENTHUB_NAME;
  const connectionString = process.env.NEXT_PUBLIC_AZURE_EVENTHUB_CONNECTION_STRING;
  const consumerGroup = process.env.NEXT_PUBLIC_AZURE_EVENTHUB_CONSUMER_GROUP || "$Default";

  console.log(`[EventHub] Using consumer group: ${consumerGroup}`);

  // Validate configuration
  if (!eventHubName) {
    console.warn("[EventHub] NEXT_PUBLIC_AZURE_EVENTHUB_NAME not configured, using mock client");
    return new MockEventHub();
  }

  if (!fullyQualifiedNamespace && !connectionString) {
    console.warn("[EventHub] Neither namespace nor connection string configured, using mock client");
    return new MockEventHub();
  }

  // Create real Azure Event Hub client
  try {
    const config: AzureEventHubConfig = {
      fullyQualifiedNamespace: fullyQualifiedNamespace || "",
      eventHubName,
      consumerGroup,
      connectionString,
      useManagedIdentity: !connectionString
    };

    const client = new AzureEventHubClient(config);

    // Add cleanup when page unloads to prevent lingering connections
    if (typeof window !== 'undefined') {
      const cleanup = () => {
        console.log("[EventHub] Page unload detected, closing connections...");
        client.close().catch(err => console.error("[EventHub] Error during cleanup:", err));
      };
      
      window.addEventListener('beforeunload', cleanup);
      window.addEventListener('unload', cleanup);
      
      // Also cleanup on visibility change (tab switch, minimize)
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') {
          console.log("[EventHub] Page hidden, closing connections...");
          client.close().catch(err => console.error("[EventHub] Error during cleanup:", err));
        }
      });
    }

    // Initialize the client asynchronously
    client.initialize().then((success) => {
      if (success) {
        console.log(`[EventHub] Real Azure Event Hub client initialized successfully with consumer group: ${client.getCurrentConsumerGroup()}`);
      } else {
        console.warn("[EventHub] Failed to initialize real client, using mock");
      }
    }).catch((error) => {
      console.error("[EventHub] Failed to initialize real client:", error);
    });

    return client;
  } catch (error) {
    console.error("[EventHub] Error creating Azure Event Hub client, falling back to mock:", error);
    return new MockEventHub();
  }
}

// Singleton instance to be used throughout the app
export const eventHub = createEventHubClient();

// Export types for consumers
export type { EventCallback, AzureEventHubConfig };
export { AzureEventHubClient, MockEventHub };
