/**
 * WebSocket client for the Next.js frontend
 * 
 * This module provides real-time event consumption from the A2A system
 * via WebSocket, replacing Azure Event Hub for local development.
 */

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
import { DEBUG, logDebug, warnDebug } from "./debug";

export type EventCallback = (data: any) => void;
type Subscribers = {
  [key: string]: EventCallback[];
};

interface WebSocketConfig {
  url: string;
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
}

export class WebSocketClient {
  private subscribers: Subscribers = {};
  private websocket: WebSocket | null = null;
  private isConnected: boolean = false;
  private isReconnecting: boolean = false;
  private reconnectAttempts: number = 0;
  private reconnectTimeout: NodeJS.Timeout | null = null;
  private config: WebSocketConfig;
  private recentToolCalls: Set<string> = new Set(); // Track recent tool calls to prevent duplicates
  private isInitializing: boolean = false; // Prevent concurrent initialization
  private pingInterval: NodeJS.Timeout | null = null; // Keepalive ping interval
  private hasEverConnected: boolean = false; // Track if we've ever had a successful connection

  constructor(config: WebSocketConfig) {
    this.config = {
      reconnectInterval: 3000,
      maxReconnectAttempts: 10,
      ...config
    };
    
    logDebug(`[WebSocket] Client initialized with URL: ${this.config.url}`);
  }
  
  // Start sending periodic pings to keep connection alive
  private startPingInterval() {
    // Clear any existing interval
    this.stopPingInterval();
    
    // Send ping every 30 seconds to keep connection alive
    this.pingInterval = setInterval(() => {
      if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
        try {
          this.websocket.send(JSON.stringify({ type: 'ping' }));
          logDebug('[WebSocket] Sent keepalive ping');
        } catch (error) {
          console.error('[WebSocket] Failed to send ping:', error);
        }
      }
    }, 30000); // 30 seconds
  }
  
  private stopPingInterval() {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }

  async initialize(): Promise<boolean> {
    // Prevent multiple concurrent initializations
    if (this.isInitializing) {
      logDebug("[WebSocket] Initialization already in progress, waiting...");
      return false;
    }
    
    // If already connected, don't reinitialize
    if (this.isConnected && this.websocket?.readyState === WebSocket.OPEN) {
      logDebug("[WebSocket] Already connected, skipping initialization");
      return true;
    }
    
    this.isInitializing = true;
    
    // NOTE: We do NOT clear collaborative session on fresh page load.
    // The session should persist across page refreshes.
    // We only clear it on RECONNECT (when backend restarts and WebSocket auto-reconnects).
    // See the isReconnecting check in onopen handler.
    
    try {
      // Close any existing connection first
      if (this.websocket) {
        this.websocket.close();
        this.websocket = null;
      }
      
      // Add initial retry logic for better connection reliability
      const envAttempts = (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_WEBSOCKET_MAX_INITIAL_ATTEMPTS)
        ? parseInt(process.env.NEXT_PUBLIC_WEBSOCKET_MAX_INITIAL_ATTEMPTS, 10)
        : NaN;
      const maxInitialAttempts = !isNaN(envAttempts) && envAttempts > 0 ? envAttempts : 3;
      let attempts = 0;
    
    while (attempts < maxInitialAttempts) {
      try {
        attempts++;
        logDebug(`[WebSocket] Connection attempt ${attempts}/${maxInitialAttempts} to ${this.config.url}`);

        // Optional lightweight health check (best‑effort) before opening WS to distinguish server down vs handshake issues
        try {
          if (attempts === 1 && typeof window !== 'undefined') {
            const healthUrl = this.config.url.replace('ws://', 'http://').replace('wss://', 'https://').replace(/\/events?.*$/, '/health');
            // Only run if looks like same origin or localhost
            if (healthUrl.includes('localhost') || healthUrl.includes('127.0.0.1')) {
              const controller = new AbortController();
              const t = setTimeout(() => controller.abort(), 2000);
              fetch(healthUrl, { signal: controller.signal })
                .then(r => r.ok ? r.json() : Promise.reject(new Error(`Health status ${r.status}`)))
                .then(data => logDebug('[WebSocket] Health probe OK:', data))
                .catch(err => warnDebug('[WebSocket] Health probe failed (continuing anyway):', err))
                .finally(() => clearTimeout(t));
            }
          }
        } catch (probeErr) {
          warnDebug('[WebSocket] Health probe setup error (ignored):', probeErr);
        }
        
        // Build WebSocket URL with authentication token and tenant ID if available
        let wsUrl = this.config.url;
        if (typeof window !== 'undefined') {
          const params: string[] = [];
          
          // Add authentication token if available
          const token = sessionStorage.getItem('auth_token');
          console.log('[WebSocket] Auth token present:', !!token, token ? `(${token.substring(0, 20)}...)` : '(none)');
          if (token) {
            params.push(`token=${encodeURIComponent(token)}`);
          }
          
          // Add tenant ID (session ID) for multi-tenancy isolation
          const { getOrCreateSessionId } = await import('./session');
          const tenantId = getOrCreateSessionId();
          console.log('[WebSocket] Tenant ID:', tenantId);
          if (tenantId) {
            params.push(`tenantId=${encodeURIComponent(tenantId)}`);
          }
          
          if (params.length > 0) {
            const separator = wsUrl.includes('?') ? '&' : '?';
            wsUrl = `${wsUrl}${separator}${params.join('&')}`;
          }
          console.log('[WebSocket] Connecting with URL params:', params.length, 'params');
        }
        
        this.websocket = new WebSocket(wsUrl);
        
        // Wait for connection to complete (success or failure)
        const connectionResult = await new Promise<boolean>((resolve) => {
          const connectionTimeout = setTimeout(() => {
            logDebug("[WebSocket] Connection timeout");
            resolve(false);
          }, 5000); // 5 second timeout
          
          this.websocket!.onopen = () => {
            clearTimeout(connectionTimeout);
            console.log("[WebSocket] CONNECTED successfully");
            
            // If this was a reconnection after disconnect, clear collaborative session
            // This handles the case where backend restarted and session state is lost
            // Note: The backend will also validate and send session_invalid if needed
            if (this.isReconnecting) {
              const hadSession = sessionStorage.getItem('a2a_collaborative_session');
              if (hadSession) {
                console.log("[WebSocket] Reconnected after disconnect - clearing collaborative session");
                sessionStorage.removeItem('a2a_collaborative_session');
                // Emit event for logging/debugging, but don't reload here
                // The backend validation will handle the session properly
                this.emit('session_cleared', { reason: 'reconnect' });
              }
            }
            
            this.isConnected = true;
            this.isReconnecting = false;
            this.reconnectAttempts = 0;
            this.hasEverConnected = true; // Mark that we've successfully connected
            
            // Start keepalive pings
            this.startPingInterval();
            
            // Clear any pending reconnection timeout
            if (this.reconnectTimeout) {
              clearTimeout(this.reconnectTimeout);
              this.reconnectTimeout = null;
            }
            resolve(true);
          };
          
          this.websocket!.onerror = (error: Event) => {
            clearTimeout(connectionTimeout);
            // Try to surface additional diagnostic info
            const socket = this.websocket as any;
            const readyState = socket?.readyState;
            let readyStateLabel = 'UNKNOWN';
            switch (readyState) {
              case 0: readyStateLabel = 'CONNECTING'; break;
              case 1: readyStateLabel = 'OPEN'; break;
              case 2: readyStateLabel = 'CLOSING'; break;
              case 3: readyStateLabel = 'CLOSED'; break;
            }
            // Keep as error
            console.error(`[WebSocket] Connection error on attempt ${attempts} (readyState=${readyState} ${readyStateLabel}):`, error);
            // Some browsers (Chrome) expose a CloseEvent via onclose only; network errors appear here without details.
            // Encourage user to inspect network tab for the failing WS handshake (101 vs 404/500). 
            this.isConnected = false;
            resolve(false);
          };
          
          this.websocket!.onclose = (event) => {
            clearTimeout(connectionTimeout);
            logDebug(`[WebSocket] Connection closed on attempt ${attempts}: code=${event.code} reason='${event.reason || 'n/a'}' wasClean=${event.wasClean}`);
            if (event.code === 1006) {
              warnDebug('[WebSocket] Abnormal closure (1006). This often indicates the server is unreachable, the handshake failed, or a proxy blocked the upgrade.');
            }
            this.isConnected = false;
            resolve(false);
          };
        });
        
        if (connectionResult) {
          // Connection successful, set up message handling
          this.websocket.onmessage = (event) => {
            try {
              const data = JSON.parse(event.data);
              this.handleEvent(data);
            } catch (error) {
              console.error("[WebSocket] Error parsing message:", error);
            }
          };
          
          this.websocket.onclose = (event) => {
            // Always log close events to help debug connection issues
            console.log(`[WebSocket] CLOSED: code=${event.code} reason='${event.reason || 'n/a'}' wasClean=${event.wasClean}`);
            this.isConnected = false;
            
            // Stop keepalive pings
            this.stopPingInterval();
            
            // Only attempt to reconnect if not a clean close
            if (event.code !== 1000 && this.reconnectAttempts < this.config.maxReconnectAttempts!) {
              this.scheduleReconnect();
            }
          };
          
          this.websocket.onerror = (error: Event) => {
            const socket = this.websocket as any;
            const readyState = socket?.readyState;
            console.error(`[WebSocket] Runtime error after open (readyState=${readyState}):`, error);
            this.isConnected = false;
          };
          
          return true;
        } else if (attempts < maxInitialAttempts) {
          logDebug(`[WebSocket] Connection attempt ${attempts} failed, retrying in 1 second...`);
          await new Promise(resolve => setTimeout(resolve, 1000));
        }
      } catch (error: any) {
        console.error(`[WebSocket] Failed to initialize on attempt ${attempts}:`, error);
        if (attempts < maxInitialAttempts) {
          await new Promise(resolve => setTimeout(resolve, 1000));
        }
      }
    }
    
    console.error(`[WebSocket] Failed to connect after ${maxInitialAttempts} attempts`);
    return false;
    } finally {
      this.isInitializing = false;
    }
  }

  private scheduleReconnect() {
    if (this.isReconnecting || this.reconnectTimeout) {
      return;
    }

    this.isReconnecting = true;
    this.reconnectAttempts++;
    
    logDebug(`[WebSocket] Scheduling reconnection attempt ${this.reconnectAttempts}/${this.config.maxReconnectAttempts} in ${this.config.reconnectInterval}ms`);
    
    this.reconnectTimeout = setTimeout(async () => {
      this.reconnectTimeout = null;
      try {
        await this.initialize();
      } catch (error) {
        console.error("[WebSocket] Reconnection failed:", error);
        this.isReconnecting = false;
        
        if (this.reconnectAttempts < this.config.maxReconnectAttempts!) {
          this.scheduleReconnect();
        } else {
          console.error("[WebSocket] Max reconnection attempts reached");
        }
      }
    }, this.config.reconnectInterval);
  }

  private handleEvent(eventData: any) {
    try {
      // Always log event type for debugging collaborative features
      const incomingEventType = eventData.eventType || eventData.type || 'unknown';
      console.log(`[WebSocket] handleEvent called with eventType: ${incomingEventType}`);
      
      if (DEBUG && typeof eventData === 'object') {
        // Avoid massive spam by eliding big payloads
        const preview = JSON.stringify(eventData).slice(0, 500);
        logDebug("[WebSocket] Received event (preview):", preview);
      }
      
      // Log connection status when handling events
      if (this.websocket) {
        logDebug(`[WebSocket] Connection state during event handling: readyState=${this.websocket.readyState} isConnected=${this.isConnected}`);
      }
      
      // Use the incoming event type for routing
      const eventType = incomingEventType;
      
      // Handle different event types
      switch (eventType) {
        case 'message': {
          this.handleMessageEvent(eventData);
          break;
        }
        case 'remote_agent_activity':
          this.emit('remote_agent_activity', eventData);
          break;
        case 'conversation':
          this.handleConversationEvent(eventData);
          break;
        case 'task':
          this.handleTaskEvent(eventData);
          break;
        case 'task_updated':
          // Direct emission for sidebar status updates
          // Contains: taskId, conversationId, contextId, state, agentName, timestamp
          logDebug(`[WebSocket] task_updated event for ${eventData.agentName}: state=${eventData.state}`);
          this.emit('task_updated', eventData);
          break;
        case 'task_created':
          logDebug(`[WebSocket] task_created event for ${eventData.agentName}`);
          this.emit('task_created', eventData);
          break;
        case 'event':
          this.handleGeneralEvent(eventData);
          break;
        case 'file':
          this.handleFileEvent(eventData);
          break;
        case 'form':
          this.handleFormEvent(eventData);
          break;
        case 'agent_registered':
          this.handleAgentRegisteredEvent(eventData);
          break;
        case 'agent_registry_sync':
          this.handleAgentRegistrySync(eventData);
          break;
        case 'shared_message':
          this.handleSharedMessageEvent(eventData);
          break;
        case 'shared_inference_started':
          this.handleSharedInferenceStartedEvent(eventData);
          break;
        case 'shared_inference_ended':
          this.handleSharedInferenceEndedEvent(eventData);
          break;
        case 'user_list_update':
          this.handleUserListUpdateEvent(eventData);
          break;
        case 'online_users':
          console.log('[WebSocket] Received online_users event:', eventData);
          this.emit('online_users', eventData);
          break;
        case 'session_agent_enabled':
        case 'session_agent_disabled':
          console.log(`[WebSocket] Received ${eventType} event:`, eventData);
          this.emit(eventType, eventData);
          break;
        case 'session_invite_sent':
        case 'session_invite_error':
        case 'session_invite_received':
        case 'session_invite_response_received':
        case 'session_invite_response_error':
        case 'session_members_updated':
          console.log(`[WebSocket] Received ${eventType} event:`, eventData);
          this.emit(eventType, eventData);
          break;
        case 'session_invalid':
          // Collaborative session no longer exists - clear local storage
          // Don't reload - just clear the stale session and continue
          // The user will now be on their own session
          const hadCollaborativeSession = sessionStorage.getItem('a2a_collaborative_session');
          if (hadCollaborativeSession) {
            console.log('[WebSocket] Collaborative session invalid, clearing (no reload):', eventData);
            sessionStorage.removeItem('a2a_collaborative_session');
            // Emit event so UI can show a notification
            this.emit('session_invalid', eventData);
          } else {
            console.log('[WebSocket] Received session_invalid but no collaborative session stored, ignoring');
          }
          break;
        default:
          logDebug(`[WebSocket] Unknown event type: ${eventType}`);
          this.emit(eventType, eventData);
      }
      
      // Always emit the raw event as well
      this.emit('raw_event', eventData);
      
    } catch (error) {
      console.error("[WebSocket] Error handling event:", error);
    }
  }

  private handleMessageEvent(eventData: any) {
    // Extract message text from content array (A2A format)
    let messageText = '';
    if (eventData.content && Array.isArray(eventData.content)) {
      const textContent = eventData.content.find((c: any) => c.type === 'text');
      messageText = textContent?.content || '';
    } else if (eventData.message) {
      // Fallback to direct message field
      messageText = eventData.message;
    }
    
    const messageEvent = {
      eventType: 'message',
      conversationId: eventData.conversationId,
      messageId: eventData.messageId,
      message: messageText,
      content: eventData.content, // Also pass the full content array
      contextId: eventData.contextId,
      direction: eventData.direction,
      role: eventData.role,
      agentName: eventData.agentName,
      timestamp: eventData.timestamp
    };
    
    logDebug('[WebSocket] Processed message event:', messageEvent);
    

    this.emit('message', messageEvent);
    if (DEBUG) {
      // Only emit extra aliases when debugging to reduce subscriber churn
      this.emit('message_sent', messageEvent);
      this.emit('message_received', messageEvent);
    }

    return messageEvent;
  }

  private handleConversationEvent(eventData: any) {
    const conversationEvent = {
      eventType: 'conversation',
      conversationId: eventData.conversationId,
      title: eventData.title,
      contextId: eventData.contextId,
      action: eventData.action,
      timestamp: eventData.timestamp
    };
    
    this.emit('conversation', conversationEvent);
    
    if (eventData.action === 'created') {
      this.emit('conversation_created', conversationEvent);
    } else if (eventData.action === 'updated') {
      this.emit('conversation_updated', conversationEvent);
    }
  }

  private handleTaskEvent(eventData: any) {
    const taskEvent = {
      eventType: 'task',
      conversationId: eventData.conversationId,
      taskId: eventData.taskId,
      task: eventData.task,
      contextId: eventData.contextId,
      action: eventData.action,
      timestamp: eventData.timestamp
    };
    
    this.emit('task', taskEvent);
    
    if (eventData.action === 'created') {
      this.emit('task_created', taskEvent);
    } else if (eventData.action === 'updated') {
      this.emit('task_updated', taskEvent);
    }
  }

  private handleGeneralEvent(eventData: any) {
    const generalEvent = {
      eventType: 'event',
      eventId: eventData.eventId,
      event: eventData.event,
      contextId: eventData.contextId,
      timestamp: eventData.timestamp
    };
    
    this.emit('event', generalEvent);
    this.emit('event_occurred', generalEvent);
  }

  private handleFileEvent(eventData: any) {
    const fileEvent = {
      eventType: 'file',
      conversationId: eventData.conversationId,
      fileInfo: eventData.fileInfo,
      contextId: eventData.contextId,
      action: eventData.action,
      timestamp: eventData.timestamp
    };
    
    this.emit('file', fileEvent);
    this.emit('file_uploaded', fileEvent);
  }

  private handleFormEvent(eventData: any) {
    const formEvent = {
      eventType: 'form',
      conversationId: eventData.conversationId,
      formData: eventData.formData,
      contextId: eventData.contextId,
      action: eventData.action,
      timestamp: eventData.timestamp
    };
    
    this.emit('form', formEvent);
    this.emit('form_submitted', formEvent);
  }

  private handleAgentRegisteredEvent(eventData: any) {
    const agentEvent = {
      eventType: 'agent_registered',
      name: eventData.agentName || eventData.name || 'Unknown Agent', // Use 'name' for UI compatibility
      agentName: eventData.agentName || eventData.name || 'Unknown Agent',
      agentPath: eventData.agentPath,
      status: eventData.status || 'online', // Default to 'online' instead of 'registered'
      agentType: eventData.agentType,
      capabilities: eventData.capabilities,
      avatar: eventData.avatar || '/placeholder.svg',
      timestamp: eventData.timestamp
    };
    
    console.log('[WebSocket] Agent registered event:', agentEvent);
    
    this.emit('agent_registered', agentEvent);
  }

  private handleAgentRegistrySync(eventData: any) {
    console.log('[WebSocket] Agent registry sync received:', eventData);
    
    // Extract agent list from the event data
    const agents = eventData.data?.agents || [];
    
    // Convert to UI format with all the rich data
    const agentList = agents.map((agent: any) => {
      console.log(`[WebSocket] Processing agent ${agent.name} with status: ${agent.status}`);
      return {
        name: agent.name || 'Unknown Agent',
        description: agent.description || '',
        url: agent.url || '',
        version: agent.version || '',
        iconUrl: agent.iconUrl || null,
        provider: agent.provider || null,
        documentationUrl: agent.documentationUrl || null,
        capabilities: agent.capabilities || {
          streaming: false,
          pushNotifications: false,
          stateTransitionHistory: false,
          extensions: []
        },
        skills: agent.skills || [],
        defaultInputModes: agent.defaultInputModes || [],
        defaultOutputModes: agent.defaultOutputModes || [],
        status: agent.status || 'offline', // Use actual status from backend
        avatar: agent.iconUrl || '/placeholder.svg?height=32&width=32',
        type: agent.type || 'remote'
      };
    });
    
    console.log(`[WebSocket] Registry sync: ${agentList.length} agents with enhanced data`);
    
    // Emit the registry sync event with the enhanced agent list
    this.emit('agent_registry_sync', {
      eventType: 'agent_registry_sync',
      agents: agentList,
      timestamp: eventData.timestamp
    });
  }

  private handleSharedMessageEvent(eventData: any) {
    console.log("[WebSocket] Shared message event received:", eventData);
    
    // Extract the message data
    const messageData = eventData.data?.message;
    if (messageData) {
      // Emit the shared_message event for the frontend to handle
      this.emit('shared_message', {
        eventType: 'shared_message',
        message: messageData,
        timestamp: eventData.timestamp || new Date().toISOString()
      });
    }
  }

  private handleSharedInferenceStartedEvent(eventData: any) {
    console.log("[WebSocket] Shared inference started event received:", eventData);
    
    // Emit the shared_inference_started event for the frontend to handle
    this.emit('shared_inference_started', {
      eventType: 'shared_inference_started',
      data: eventData.data,
      timestamp: eventData.timestamp || new Date().toISOString()
    });
  }

  private handleSharedInferenceEndedEvent(eventData: any) {
    console.log("[WebSocket] Shared inference ended event received:", eventData);
    
    // Emit the shared_inference_ended event for the frontend to handle  
    this.emit('shared_inference_ended', {
      eventType: 'shared_inference_ended',
      data: eventData.data,
      timestamp: eventData.timestamp || new Date().toISOString()
    });
  }

  private handleUserListUpdateEvent(eventData: any) {
    console.log("[WebSocket] User list update event received:", eventData);
    
    // Emit the user_list_update event for the frontend to handle
    this.emit('user_list_update', {
      eventType: 'user_list_update',
      data: eventData.data,
      timestamp: eventData.timestamp || new Date().toISOString()
    });
  }

  subscribe(eventName: string, callback: EventCallback): void {
    if (!this.subscribers[eventName]) {
      this.subscribers[eventName] = [];
    }
    this.subscribers[eventName].push(callback);
    console.log(`[WebSocket] Subscribed to event: ${eventName}`);
  }

  unsubscribe(eventName: string, callback: EventCallback): void {
    if (this.subscribers[eventName]) {
      this.subscribers[eventName] = this.subscribers[eventName].filter(cb => cb !== callback);
      console.log(`[WebSocket] Unsubscribed from event: ${eventName}`);
    }
  }

  emit(eventName: string, data: any): void {
    if (this.subscribers[eventName]) {
      this.subscribers[eventName].forEach(callback => {
        try {
          callback(data);
        } catch (error) {
          console.error(`[WebSocket] Error in callback for ${eventName}:`, error);
        }
      });
    }
  }

  sendMessage(message: any): boolean {
    if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
      try {
        const messageStr = typeof message === 'string' ? message : JSON.stringify(message);
        this.websocket.send(messageStr);
        console.log('[WebSocket] Message sent:', messageStr);
        return true;
      } catch (error) {
        console.error('[WebSocket] Error sending message:', error);
        return false;
      }
    } else {
      console.warn('[WebSocket] Cannot send message - connection not open. ReadyState:', this.websocket?.readyState);
      return false;
    }
  }

  getConnectionStatus(): boolean {
    return this.isConnected && this.websocket?.readyState === WebSocket.OPEN;
  }

  async close(): Promise<void> {
    try {
      this.isInitializing = false; // Reset initialization flag
      
      // Stop keepalive pings
      this.stopPingInterval();
      
      if (this.reconnectTimeout) {
        clearTimeout(this.reconnectTimeout);
        this.reconnectTimeout = null;
      }
      
      this.isReconnecting = false;
      this.reconnectAttempts = this.config.maxReconnectAttempts!; // Prevent reconnection
      
      if (this.websocket) {
        this.websocket.close(1000, "Client closing");
        this.websocket = null;
      }
      
      this.isConnected = false;
      console.log("[WebSocket] Client closed");
    } catch (error) {
      console.error("[WebSocket] Error closing client:", error);
    }
  }
}

// Mock implementation for testing
export class MockWebSocketClient {
  private subscribers: Subscribers = {};
  private isConnected: boolean = false;

  constructor() {
    console.log("[WebSocket] Using mock WebSocket client");
  }

  async initialize(): Promise<boolean> {
    console.log("[WebSocket] Mock client initialized");
    this.isConnected = true;
    
    // Simulate some events for testing
    setTimeout(() => {
      this.emit('message', {
        eventType: 'message',
        conversationId: 'test-conv-1',
        messageId: 'test-msg-1',
        message: [{ type: 'text', content: 'Test message from mock WebSocket' }],
        direction: 'received',
        timestamp: new Date().toISOString()
      });
    }, 2000);
    
    return true;
  }

  subscribe(eventName: string, callback: EventCallback): void {
    if (!this.subscribers[eventName]) {
      this.subscribers[eventName] = [];
    }
    this.subscribers[eventName].push(callback);
    console.log(`[WebSocket] Mock subscribed to event: ${eventName}`);
  }

  unsubscribe(eventName: string, callback: EventCallback): void {
    if (this.subscribers[eventName]) {
      this.subscribers[eventName] = this.subscribers[eventName].filter(cb => cb !== callback);
      console.log(`[WebSocket] Mock unsubscribed from event: ${eventName}`);
    }
  }

  emit(eventName: string, data: any): void {
    if (this.subscribers[eventName]) {
      this.subscribers[eventName].forEach(callback => {
        try {
          callback(data);
        } catch (error) {
          console.error(`[WebSocket] Mock error in callback for ${eventName}:`, error);
        }
      });
    }
  }

  getConnectionStatus(): boolean {
    return this.isConnected;
  }

  sendMessage(message: any): boolean {
    console.log("[WebSocket] Mock sendMessage called with:", message);
    return true; // Mock always succeeds
  }

  async close(): Promise<void> {
    this.isConnected = false;
    console.log("[WebSocket] Mock client closed");
  }
}


