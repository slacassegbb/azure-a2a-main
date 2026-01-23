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

// Event type constants
export const A2A_EVENT_TYPES = {
  MESSAGE: "message",
  CONVERSATION_CREATED: "conversation_created",
  CONVERSATION_UPDATED: "conversation_updated", 
  TASK_CREATED: "task_created",
  TASK_UPDATED: "task_updated",
  SYSTEM_EVENT: "system_event",
  FILE_UPLOADED: "file_uploaded",
  FORM_SUBMITTED: "form_submitted",
  API_KEY_UPDATED: "api_key_updated",
  AGENT_REGISTERED: "agent_registered",
  AGENT_SELF_REGISTERED: "agent_self_registered",
  TOOL_CALL: "tool_call",
  TOOL_RESPONSE: "tool_response",
  REMOTE_AGENT_TOOL_CALL: "remote_agent_tool_call",
  REMOTE_AGENT_TOOL_RESPONSE: "remote_agent_tool_response",
  REMOTE_AGENT_TOOL_ACTIVITY: "remote_agent_tool_activity",
  REMOTE_AGENT_ARTIFACT: "remote_agent_artifact",
  REMOTE_AGENT_RESPONSE: "remote_agent_response",
  REMOTE_AGENT_TASK: "remote_agent_task"
} as const;

export type A2AEventType = typeof A2A_EVENT_TYPES[keyof typeof A2A_EVENT_TYPES];

// Type guards for event data
export function isMessageEvent(data: A2AEventData): data is MessageEventData {
  return 'messageId' in data && 'direction' in data;
}

export function isConversationCreatedEvent(data: A2AEventData): data is ConversationCreatedEventData {
  return 'conversationId' in data && 'isActive' in data && !('direction' in data);
}

export function isTaskEvent(data: A2AEventData): data is TaskCreatedEventData | TaskUpdatedEventData {
  return 'taskId' in data;
}

export function isFileUploadEvent(data: A2AEventData): data is FileUploadedEventData {
  return 'fileName' in data && 'uploadTimestamp' in data;
}

export function isFormSubmittedEvent(data: A2AEventData): data is FormSubmittedEventData {
  return 'formData' in data && 'submissionTimestamp' in data;
}

export function isAgentRegisteredEvent(data: A2AEventData): data is AgentRegisteredEventData {
  return 'agentPath' in data && 'agentName' in data && 'status' in data;
}

export function isAgentSelfRegisteredEvent(data: A2AEventData): data is AgentSelfRegisteredEventData {
  return 'agentName' in data && 'agentType' in data && 'capabilities' in data;
}

export function isToolCallEvent(data: A2AEventData): data is ToolCallEventData {
  return 'toolCallId' in data && 'toolName' in data && 'arguments' in data;
}

export function isToolResponseEvent(data: A2AEventData): data is ToolResponseEventData {
  return 'toolCallId' in data && 'response' in data && 'status' in data;
}

export function isRemoteAgentToolCallEvent(data: A2AEventData): data is RemoteAgentToolCallEventData {
  return 'isRemoteAgent' in data && 'isToolCall' in data && 'agentName' in data;
}

// Helper function to parse a WebSocket event payload
export function parseA2AEvent(eventStreamMessage: string): A2AEventEnvelope | null {
  try {
    const parsed = JSON.parse(eventStreamMessage);
    
    // Validate basic structure
    if (!parsed.eventType || !parsed.timestamp || !parsed.eventId || !parsed.data) {
      console.warn('Invalid A2A event structure:', parsed);
      return null;
    }
    
    return parsed as A2AEventEnvelope;
  } catch (error) {
    console.error('Failed to parse A2A event:', error);
    return null;
  }
}
