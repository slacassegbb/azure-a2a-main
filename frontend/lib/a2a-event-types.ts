/**
 * TypeScript interfaces for A2A event-stream data structures
 * 
 * These interfaces define the structure of events sent from the A2A system
 * over the WebSocket relay for consumption by external frontends.
 */

// Base event envelope structure
export interface A2AEventEnvelope {
  eventType: string;
  timestamp: string; // ISO 8601 format
  eventId: string;   // UUID
  source: "a2a-system";
  data: A2AEventData;
}

// Union type for all possible event data types
export type A2AEventData = 
  | MessageEventData
  | MessageChunkEventData
  | ConversationCreatedEventData
  | ConversationUpdatedEventData
  | TaskCreatedEventData
  | TaskUpdatedEventData
  | SystemEventData
  | FileUploadedEventData
  | FormSubmittedEventData
  | ApiKeyUpdatedEventData
  | AgentRegisteredEventData
  | AgentSelfRegisteredEventData
  | ToolCallEventData
  | ToolResponseEventData
  | RemoteAgentToolCallEventData;

// Message events (sent/received)
export interface MessageEventData {
  messageId: string;
  conversationId: string;
  contextId?: string;
  role: string;
  content: MessageContent[];
  direction: "outgoing" | "incoming";
}

// Message chunk events (streaming tokens in real-time)
export interface MessageChunkEventData {
  type: 'message_chunk';
  contextId: string;
  chunk: string;
  timestamp: string; // ISO 8601 format
}

export interface MessageContent {
  type: "text" | "file";
  content?: string;     // For text content
  fileName?: string;    // For file content
  fileSize?: number;    // For file content
  mediaType: string;
}

// Conversation events
export interface ConversationCreatedEventData {
  conversationId: string;
  conversationName: string;
  isActive: boolean;
  messageCount: number;
}

export interface ConversationUpdatedEventData {
  conversationId: string;
  conversationName: string;
  isActive: boolean;
  messageCount: number;
}

// Task events
export interface TaskCreatedEventData {
  taskId: string;
  conversationId: string;
  contextId?: string;
  state?: string;
  artifactsCount: number;
}

export interface TaskUpdatedEventData {
  taskId: string;
  conversationId: string;
  contextId?: string;
  state?: string;
  artifactsCount: number;
}

// System events
export interface SystemEventData {
  eventId: string;
  conversationId: string;
  actor: string;
  role: string;
  content: Array<[string, string]>; // [content, mediaType] tuples
}

// File upload events
export interface FileUploadedEventData {
  fileName?: string;
  fileSize: number;
  mimeType?: string;
  conversationId: string;
  uploadTimestamp: string; // ISO 8601 format
}

// Form submission events
export interface FormSubmittedEventData {
  conversationId: string;
  formData: Record<string, any>;
  submissionTimestamp: string; // ISO 8601 format
}

// API key update events
export interface ApiKeyUpdatedEventData {
  success: boolean;
  timestamp: string; // ISO 8601 format
}

// Agent registration events
export interface AgentRegisteredEventData {
  agentPath: string;
  agentName: string;
  status: "registered";
  timestamp: string; // ISO 8601 format
  avatar: string;
}

export interface AgentSelfRegisteredEventData {
  agentName: string;
  agentType: string;
  capabilities: string[];
  status: "online";
  timestamp: string; // ISO 8601 format
  avatar: string;
  endpoint?: string;
  metadata: Record<string, any>;
}

// Tool call events
export interface ToolCallEventData {
  toolCallId: string;
  conversationId: string;
  contextId?: string;
  toolName: string;
  arguments: Record<string, any>;
  agentName: string;
  timestamp: string; // ISO 8601 format
  suppressedResponse?: boolean;
}

export interface ToolResponseEventData {
  toolCallId: string;
  conversationId: string;
  contextId?: string;
  toolName: string;
  response: any;
  agentName: string;
  timestamp: string; // ISO 8601 format
  status: "success" | "error";
  error?: string;
}

export interface RemoteAgentToolCallEventData {
  eventId: string;
  conversationId: string;
  contextId?: string;
  actor: string;
  role: "agent";
  eventType: string;
  content: string;
  timestamp: string; // ISO 8601 format
  taskId?: string;
  agentName: string;
  isRemoteAgent: boolean;
  isToolCall: boolean;
  toolName?: string;
  toolArgs?: Record<string, any>;
}

