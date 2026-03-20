/**
 * Session management for mobile frontend.
 * Uses localStorage exclusively (no sessionStorage) for persistence across app reopens.
 */

import { logDebug, logInfo } from '@/lib/debug'

const SESSION_STORAGE_KEY = 'a2a_session_id'

function generateSessionId(): string {
  return `sess_${crypto.randomUUID()}`
}

export function getOrCreateSessionId(): string {
  if (typeof window === 'undefined') return generateSessionId()

  // Check if user is logged in (JWT in localStorage)
  const token = localStorage.getItem('auth_token')
  if (token) {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]))
      if (payload.user_id) {
        logInfo('[Session] Using user-based session:', payload.user_id)
        return payload.user_id
      }
    } catch (error) {
      console.warn('[Session] Failed to decode JWT:', error)
    }
  }

  // Fall back to anonymous session
  let sessionId = localStorage.getItem(SESSION_STORAGE_KEY)
  if (!sessionId) {
    sessionId = generateSessionId()
    localStorage.setItem(SESSION_STORAGE_KEY, sessionId)
    logInfo('[Session] Created new anonymous session:', sessionId)
  }
  return sessionId
}

export function clearSession(): void {
  if (typeof window === 'undefined') return
  localStorage.removeItem(SESSION_STORAGE_KEY)
  localStorage.removeItem('auth_token')
  localStorage.removeItem('user_info')
  logInfo('[Session] Session and auth cleared')
}

export const TENANT_SEPARATOR = '::'

export function createContextId(conversationId?: string): string {
  const sessionId = getOrCreateSessionId()
  const convId = conversationId || crypto.randomUUID()
  return `${sessionId}${TENANT_SEPARATOR}${convId}`
}

export function parseContextId(contextId: string): { sessionId: string; conversationId: string } {
  if (contextId.includes(TENANT_SEPARATOR)) {
    const [sessionId, conversationId] = contextId.split(TENANT_SEPARATOR, 2)
    return { sessionId, conversationId: conversationId || contextId }
  }
  return { sessionId: `anon_${contextId}`, conversationId: contextId }
}
