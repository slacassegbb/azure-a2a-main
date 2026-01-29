/**
 * Session Management for Multi-Tenancy
 * 
 * This module manages tenant sessions by generating and storing unique session IDs.
 * The session ID is used as the tenant identifier in the A2A protocol's contextId.
 * 
 * Format: contextId = `${sessionId}::${conversationId}`
 */

const SESSION_STORAGE_KEY = 'a2a_session_id';
const SESSION_CREATED_KEY = 'a2a_session_created';

/**
 * Generate a new unique session ID
 */
function generateSessionId(): string {
  // Format: sess_<uuid>
  const uuid = crypto.randomUUID();
  return `sess_${uuid}`;
}

/**
 * Get the user's own user_id from JWT, ignoring collaborative session.
 * Used to determine if a message originated from the current user's session.
 * 
 * @returns The user's own user_id or null if not logged in
 */
export function getOwnUserId(): string | null {
  if (typeof window === 'undefined') {
    return null;
  }
  
  const token = sessionStorage.getItem('auth_token');
  if (token) {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      if (payload.user_id) {
        return payload.user_id;
      }
    } catch (error) {
      console.warn('[Session] Failed to decode JWT:', error);
    }
  }
  
  return null;
}

/**
 * Get or create a session ID for the current browser session.
 * 
 * For logged-in users: Uses user_id as session (data syncs across devices)
 * For anonymous users: Uses browser-based session ID (isolated per browser)
 * For collaborative sessions: Uses the shared session ID
 * 
 * @returns The session ID (tenant identifier)
 */
export function getOrCreateSessionId(): string {
  if (typeof window === 'undefined') {
    // Server-side rendering - return a temporary ID
    return generateSessionId();
  }
  
  // Check if in a collaborative session first (takes priority)
  const collaborativeSession = sessionStorage.getItem('a2a_collaborative_session');
  console.log('[Session] getOrCreateSessionId called. a2a_collaborative_session =', collaborativeSession);
  if (collaborativeSession) {
    console.log('[Session] Using collaborative session:', collaborativeSession);
    return collaborativeSession;
  }
  
  // Check if user is logged in (JWT token in sessionStorage)
  const token = sessionStorage.getItem('auth_token');
  if (token) {
    try {
      // Decode JWT to get user_id (JWT format: header.payload.signature)
      const payload = JSON.parse(atob(token.split('.')[1]));
      if (payload.user_id) {
        // Use user_id as session for logged-in users (already has "user_" prefix from backend)
        console.log('[Session] Using user-based session:', payload.user_id);
        return payload.user_id;
      }
    } catch (error) {
      console.warn('[Session] Failed to decode JWT, falling back to anonymous session:', error);
    }
  }
  
  // Fall back to anonymous browser-based session
  let sessionId = localStorage.getItem(SESSION_STORAGE_KEY);
  
  if (!sessionId) {
    sessionId = generateSessionId();
    localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
    localStorage.setItem(SESSION_CREATED_KEY, new Date().toISOString());
    console.log('[Session] Created new anonymous session:', sessionId);
  }
  
  return sessionId;
}

/**
 * Get the current session ID without creating a new one
 * 
 * @returns The session ID or null if none exists
 */
export function getCurrentSessionId(): string | null {
  if (typeof window === 'undefined') {
    return null;
  }
  return localStorage.getItem(SESSION_STORAGE_KEY);
}

/**
 * Clear the current session (useful for logout or reset)
 * Call this when user logs out to ensure they get a fresh anonymous session
 */
export function clearSession(): void {
  if (typeof window === 'undefined') {
    return;
  }
  localStorage.removeItem(SESSION_STORAGE_KEY);
  localStorage.removeItem(SESSION_CREATED_KEY);
  // Also clear auth token if present (check both storage locations)
  localStorage.removeItem('auth_token');
  sessionStorage.removeItem('auth_token');
  sessionStorage.removeItem('user_info');
  // Clear collaborative session data
  sessionStorage.removeItem('a2a_collaborative_session');
  sessionStorage.removeItem('a2a_collaborative_session_just_joined');
  localStorage.removeItem('a2a_backend_session_id');
  console.log('[Session] Session and auth cleared');
}

/**
 * Get session creation timestamp
 * 
 * @returns ISO timestamp string or null
 */
export function getSessionCreatedAt(): string | null {
  if (typeof window === 'undefined') {
    return null;
  }
  return localStorage.getItem(SESSION_CREATED_KEY);
}

// ============================================
// Context ID Utilities (A2A Protocol Integration)
// ============================================

/** Separator used to encode tenant_id in contextId */
export const TENANT_SEPARATOR = '::';

/**
 * Create a tenant-aware contextId for A2A protocol
 * 
 * @param conversationId - The conversation ID (can be from URL params)
 * @returns Context ID in format: sessionId::conversationId
 * 
 * @example
 * createContextId('conv_123') // 'sess_abc-def::conv_123'
 * createContextId()          // 'sess_abc-def::new-uuid'
 */
export function createContextId(conversationId?: string): string {
  const sessionId = getOrCreateSessionId();
  const convId = conversationId || crypto.randomUUID();
  return `${sessionId}${TENANT_SEPARATOR}${convId}`;
}

/**
 * Parse a contextId to extract session (tenant) and conversation IDs
 * 
 * @param contextId - The context ID to parse
 * @returns Object with sessionId and conversationId
 * 
 * @example
 * parseContextId('sess_abc::conv_xyz') // { sessionId: 'sess_abc', conversationId: 'conv_xyz' }
 * parseContextId('legacy-uuid')        // { sessionId: 'anon_legacy-uuid', conversationId: 'legacy-uuid' }
 */
export function parseContextId(contextId: string): { sessionId: string; conversationId: string } {
  if (contextId.includes(TENANT_SEPARATOR)) {
    const [sessionId, conversationId] = contextId.split(TENANT_SEPARATOR, 2);
    return { sessionId, conversationId: conversationId || contextId };
  }
  
  // Legacy format - no tenant encoded
  return {
    sessionId: `anon_${contextId}`,
    conversationId: contextId
  };
}

/**
 * Extract just the session ID (tenant) from a contextId
 * 
 * @param contextId - The context ID
 * @returns The session/tenant ID
 */
export function getSessionFromContext(contextId: string): string {
  return parseContextId(contextId).sessionId;
}

/**
 * Extract just the conversation ID from a contextId
 * 
 * @param contextId - The context ID
 * @returns The conversation ID
 */
export function getConversationFromContext(contextId: string): string {
  return parseContextId(contextId).conversationId;
}

/**
 * Check if a contextId contains tenant information
 * 
 * @param contextId - The context ID to check
 * @returns True if contextId has tenant separator
 */
export function isTenantAwareContext(contextId: string): boolean {
  return contextId.includes(TENANT_SEPARATOR);
}

/**
 * Get session info for debugging/display
 */
export function getSessionInfo(): {
  sessionId: string | null;
  createdAt: string | null;
  isTenantAware: boolean;
} {
  const sessionId = getCurrentSessionId();
  return {
    sessionId,
    createdAt: getSessionCreatedAt(),
    isTenantAware: sessionId !== null
  };
}

// ============================================
// Collaborative Session Support
// ============================================

const COLLABORATIVE_SESSION_KEY = 'a2a_collaborative_session';
const COLLABORATIVE_CONVERSATION_KEY = 'a2a_collaborative_conversation';

/**
 * Join a collaborative session (switch to another user's session)
 * 
 * @param sessionId - The session ID to join (e.g., "user_3")
 * @param conversationId - Optional conversation ID to navigate to after joining
 * @param reload - Whether to reload the page after joining (default: true)
 */
export function joinCollaborativeSession(sessionId: string, conversationId?: string, reload: boolean = true): void {
  if (typeof window === 'undefined') {
    return;
  }
  
  // Store the collaborative session we're joining
  sessionStorage.setItem(COLLABORATIVE_SESSION_KEY, sessionId);
  // Mark as "just joined" to protect against immediate session_started clear
  // This flag is checked by websocket-client.ts and cleared after first session_started
  sessionStorage.setItem('a2a_collaborative_session_just_joined', 'true');
  
  // Store the target conversation for auto-navigation after reload
  if (conversationId) {
    sessionStorage.setItem(COLLABORATIVE_CONVERSATION_KEY, conversationId);
    console.log('[Session] Joining collaborative session:', sessionId, 'with conversation:', conversationId);
  } else {
    sessionStorage.removeItem(COLLABORATIVE_CONVERSATION_KEY);
    console.log('[Session] Joining collaborative session:', sessionId);
  }
  
  if (reload) {
    // If we have a target conversation, navigate directly to it
    if (conversationId) {
      window.location.href = `/?conversationId=${conversationId}`;
    } else {
      // Reload to pick up the new session
      window.location.reload();
    }
  }
}

/**
 * Get and clear the pending collaborative conversation (for auto-navigation)
 * 
 * @returns The conversation ID to navigate to, or null
 */
export function getAndClearPendingCollaborativeConversation(): string | null {
  if (typeof window === 'undefined') {
    return null;
  }
  const conversationId = sessionStorage.getItem(COLLABORATIVE_CONVERSATION_KEY);
  if (conversationId) {
    sessionStorage.removeItem(COLLABORATIVE_CONVERSATION_KEY);
  }
  return conversationId;
}

/**
 * Get the active collaborative session if any
 * 
 * @returns The collaborative session ID or null
 */
export function getCollaborativeSession(): string | null {
  if (typeof window === 'undefined') {
    return null;
  }
  return sessionStorage.getItem(COLLABORATIVE_SESSION_KEY);
}

/**
 * Leave the current collaborative session and return to own session
 * The backend will be notified via WebSocket disconnect
 */
export function leaveCollaborativeSession(
  reload: boolean = true, 
  sendMessage?: (message: any) => void
): void {
  if (typeof window === 'undefined') {
    return;
  }
  
  // Just clear local storage - the WebSocket disconnect will notify the backend
  sessionStorage.removeItem(COLLABORATIVE_SESSION_KEY);
  console.log('[Session] Left collaborative session, returning to own session');
  
  if (reload) {
    window.location.reload();
  }
}

/**
 * Check if currently in a collaborative session
 */
export function isInCollaborativeSession(): boolean {
  return getCollaborativeSession() !== null;
}

