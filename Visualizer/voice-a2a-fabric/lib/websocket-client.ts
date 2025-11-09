/**
 * WebSocket client for the Visualizer frontend
 * 
 * This module provides real-time event consumption from the A2A system
 * via WebSocket for the agent network visualization.
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
  private isInitializing: boolean = false;

  constructor(config: WebSocketConfig) {
    this.config = {
      reconnectInterval: 3000,
      maxReconnectAttempts: 10,
      ...config
    };
    
    logDebug(`[WebSocket] Client initialized with URL: ${this.config.url}`);
  }

  async initialize(): Promise<boolean> {
    if (this.isInitializing) {
      logDebug("[WebSocket] Initialization already in progress, waiting...");
      return false;
    }
    
    if (this.isConnected && this.websocket?.readyState === WebSocket.OPEN) {
      logDebug("[WebSocket] Already connected, skipping initialization");
      return true;
    }
    
    this.isInitializing = true;
    
    try {
      if (this.websocket) {
        this.websocket.close();
        this.websocket = null;
      }
      
      const envAttempts = (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_WEBSOCKET_MAX_INITIAL_ATTEMPTS)
        ? parseInt(process.env.NEXT_PUBLIC_WEBSOCKET_MAX_INITIAL_ATTEMPTS, 10)
        : NaN;
      const maxInitialAttempts = !isNaN(envAttempts) && envAttempts > 0 ? envAttempts : 3;
      let attempts = 0;
    
    while (attempts < maxInitialAttempts) {
      try {
        attempts++;
        logDebug(`[WebSocket] Connection attempt ${attempts}/${maxInitialAttempts} to ${this.config.url}`);
        
        let wsUrl = this.config.url;
        if (typeof window !== 'undefined') {
          const token = sessionStorage.getItem('auth_token');
          if (token) {
            const separator = wsUrl.includes('?') ? '&' : '?';
            wsUrl = `${wsUrl}${separator}token=${encodeURIComponent(token)}`;
          }
        }
        
        this.websocket = new WebSocket(wsUrl);
        
        const connectionResult = await new Promise<boolean>((resolve) => {
          const connectionTimeout = setTimeout(() => {
            logDebug("[WebSocket] Connection timeout");
            resolve(false);
          }, 5000);
          
          this.websocket!.onopen = () => {
            clearTimeout(connectionTimeout);
            logDebug("[WebSocket] Connected successfully");
            this.isConnected = true;
            this.isReconnecting = false;
            this.reconnectAttempts = 0;
            
            if (this.reconnectTimeout) {
              clearTimeout(this.reconnectTimeout);
              this.reconnectTimeout = null;
            }
            resolve(true);
          };
          
          this.websocket!.onerror = (error: Event) => {
            clearTimeout(connectionTimeout);
            const socket = this.websocket as any;
            const readyState = socket?.readyState;
            console.error(`[WebSocket] Connection error on attempt ${attempts} (readyState=${readyState}):`, error);
            this.isConnected = false;
            resolve(false);
          };
          
          this.websocket!.onclose = (event) => {
            clearTimeout(connectionTimeout);
            logDebug(`[WebSocket] Connection closed on attempt ${attempts}: code=${event.code} reason='${event.reason || 'n/a'}' wasClean=${event.wasClean}`);
            if (event.code === 1006) {
              warnDebug('[WebSocket] Abnormal closure (1006). Server may be unreachable.');
            }
            this.isConnected = false;
            resolve(false);
          };
        });
        
        if (connectionResult) {
          this.websocket.onmessage = (event) => {
            try {
              const data = JSON.parse(event.data);
              this.handleEvent(data);
            } catch (error) {
              console.error("[WebSocket] Error parsing message:", error);
            }
          };
          
          this.websocket.onclose = (event) => {
            logDebug(`[WebSocket] Connection closed: code=${event.code} reason='${event.reason || 'n/a'}' wasClean=${event.wasClean}`);
            this.isConnected = false;
            
            if (event.code !== 1000 && this.reconnectAttempts < this.config.maxReconnectAttempts!) {
              this.scheduleReconnect();
            }
          };
          
          this.websocket.onerror = (error: Event) => {
            console.error(`[WebSocket] Runtime error:`, error);
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
      if (DEBUG && typeof eventData === 'object') {
        const preview = JSON.stringify(eventData).slice(0, 500);
        logDebug("[WebSocket] Received event (preview):", preview);
      }
      
      const eventType = eventData.eventType || 'unknown';
      
      switch (eventType) {
        case 'message':
          this.handleMessageEvent(eventData);
          break;
        case 'remote_agent_activity':
          this.emit('remote_agent_activity', eventData);
          break;
        case 'conversation':
          this.handleConversationEvent(eventData);
          break;
        case 'task':
          this.handleTaskEvent(eventData);
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
        case 'user_list_update':
          this.handleUserListUpdateEvent(eventData);
          break;
        default:
          logDebug(`[WebSocket] Unknown event type: ${eventType}`);
          this.emit(eventType, eventData);
      }
      
      this.emit('raw_event', eventData);
      
    } catch (error) {
      console.error("[WebSocket] Error handling event:", error);
    }
  }

  private handleMessageEvent(eventData: any) {
    let messageText = '';
    if (eventData.content && Array.isArray(eventData.content)) {
      const textContent = eventData.content.find((c: any) => c.type === 'text');
      messageText = textContent?.content || '';
    } else if (eventData.message) {
      messageText = eventData.message;
    }
    
    const messageEvent = {
      eventType: 'message',
      conversationId: eventData.conversationId,
      messageId: eventData.messageId,
      message: messageText,
      content: eventData.content,
      contextId: eventData.contextId,
      direction: eventData.direction,
      role: eventData.role,
      agentName: eventData.agentName,
      timestamp: eventData.timestamp
    };
    
    logDebug('[WebSocket] Processed message event:', messageEvent);
    this.emit('message', messageEvent);
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
      state: eventData.state,
      agentName: eventData.agentName,
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
      name: eventData.agentName || eventData.name || 'Unknown Agent',
      agentName: eventData.agentName || eventData.name || 'Unknown Agent',
      agentPath: eventData.agentPath,
      status: eventData.status || 'online',
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
    
    const agents = eventData.data?.agents || [];
    
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
        status: agent.status || 'offline',
        avatar: agent.iconUrl || '/placeholder.svg?height=32&width=32',
        type: agent.type || 'remote'
      };
    });
    
    console.log(`[WebSocket] Registry sync: ${agentList.length} agents with enhanced data`);
    
    this.emit('agent_registry_sync', {
      eventType: 'agent_registry_sync',
      agents: agentList,
      timestamp: eventData.timestamp
    });
  }

  private handleSharedMessageEvent(eventData: any) {
    console.log("[WebSocket] Shared message event received:", eventData);
    
    const messageData = eventData.data?.message;
    if (messageData) {
      this.emit('shared_message', {
        eventType: 'shared_message',
        message: messageData,
        timestamp: eventData.timestamp || new Date().toISOString()
      });
    }
  }

  private handleUserListUpdateEvent(eventData: any) {
    console.log("[WebSocket] User list update event received:", eventData);
    
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
    logDebug(`[WebSocket] Subscribed to event: ${eventName}`);
  }

  unsubscribe(eventName: string, callback: EventCallback): void {
    if (this.subscribers[eventName]) {
      this.subscribers[eventName] = this.subscribers[eventName].filter(cb => cb !== callback);
      logDebug(`[WebSocket] Unsubscribed from event: ${eventName}`);
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
      this.isInitializing = false;
      
      if (this.reconnectTimeout) {
        clearTimeout(this.reconnectTimeout);
        this.reconnectTimeout = null;
      }
      
      this.isReconnecting = false;
      this.reconnectAttempts = this.config.maxReconnectAttempts!;
      
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
    return true;
  }

  async close(): Promise<void> {
    this.isConnected = false;
    console.log("[WebSocket] Mock client closed");
  }
}
