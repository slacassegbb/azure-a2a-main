/**
 * Conversation API client for A2A backend
 * 
 * This provides TypeScript functions to interact with the A2A conversation endpoints
 */

import { getOrCreateSessionId } from './session'

const API_BASE_URL = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'

export interface Conversation {
  conversation_id: string
  name: string
  is_active: boolean
  task_ids: string[]
  messages: any[]
}

export interface Message {
  messageId: string
  role: string
  parts: any[]
  contextId?: string
  taskId?: string
}

// Result from listConversations including user mapping
export interface ListConversationsResult {
  conversations: Conversation[]
  messageUserMap: Record<string, string>  // messageId -> userId
}

/**
 * List all conversations for the current session
 */
export async function listConversations(): Promise<ListConversationsResult> {
  try {
    // Import session management
    const { getOrCreateSessionId } = await import('./session')
    const sessionId = getOrCreateSessionId()
    
    console.log('[ConversationAPI] Calling listConversations endpoint for session:', sessionId)
    const response = await fetch(`${API_BASE_URL}/conversation/list`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        jsonrpc: '2.0',
        method: 'conversation/list',
        params: {
          sessionId: sessionId
        },
        id: `req_${Date.now()}`
      })
    })

    if (!response.ok) {
      console.error('[ConversationAPI] HTTP error:', response.status, response.statusText)
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }

    const data = await response.json()
    console.log('[ConversationAPI] Raw response data:', JSON.stringify(data, null, 2))
    
    const conversations = data.result || []
    const messageUserMap = data.message_user_map || {}
    console.log('[ConversationAPI] Parsed conversations:', conversations.length, 'messageUserMap entries:', Object.keys(messageUserMap).length)
    
    return { conversations, messageUserMap }
  } catch (error) {
    console.error('[ConversationAPI] Failed to list conversations:', error)
    return { conversations: [], messageUserMap: {} }
  }
}

/**
 * Create a new conversation
 */
export async function createConversation(): Promise<Conversation | null> {
  try {
    const response = await fetch(`${API_BASE_URL}/conversation/create`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        jsonrpc: '2.0',
        method: 'conversation/create',
        id: `req_${Date.now()}`
      })
    })

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }

    const data = await response.json()
    console.log('[ConversationAPI] Create conversation response:', data)
    
    return data.result
  } catch (error) {
    console.error('[ConversationAPI] Failed to create conversation:', error)
    return null
  }
}

/**
 * Get a specific conversation with its embedded messages
 */
export interface GetConversationResult {
  conversation: Conversation | null
  messageUserMap: Record<string, string>
}

export async function getConversation(conversationId: string): Promise<GetConversationResult> {
  try {
    console.log('[ConversationAPI] Getting conversation:', conversationId)
    const { conversations, messageUserMap } = await listConversations()
    const conversation = conversations.find(conv => conv.conversation_id === conversationId)
    
    if (conversation) {
      console.log('[ConversationAPI] Found conversation with', conversation.messages?.length || 0, 'embedded messages')
      return { conversation, messageUserMap }
    } else {
      console.log('[ConversationAPI] Conversation not found:', conversationId)
      return { conversation: null, messageUserMap }
    }
  } catch (error) {
    console.error('[ConversationAPI] Failed to get conversation:', error)
    return { conversation: null, messageUserMap: {} }
  }
}

/**
 * List messages for a specific conversation
 */
export async function listMessages(conversationId: string): Promise<Message[]> {
  try {
    console.log('[ConversationAPI] Listing messages for conversation:', conversationId)
    const requestBody = {
      jsonrpc: '2.0',
      method: 'message/list',
      params: conversationId,  // Send conversationId directly, not as object
      id: `req_${Date.now()}`
    }
    console.log('[ConversationAPI] Request body:', JSON.stringify(requestBody, null, 2))
    
    const response = await fetch(`${API_BASE_URL}/message/list`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(requestBody)
    })

    if (!response.ok) {
      console.error('[ConversationAPI] HTTP error:', response.status, response.statusText)
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }

    const data = await response.json()
    console.log('[ConversationAPI] List messages response:', JSON.stringify(data, null, 2))
    
    if (data.error) {
      console.error('[ConversationAPI] API error:', data.error)
      return []
    }
    
    const messages = data.result || []
    console.log('[ConversationAPI] Returning', messages.length, 'messages')
    return messages
  } catch (error) {
    console.error('[ConversationAPI] Failed to list messages:', error)
    return []
  }
}

/**
 * Delete a conversation (if implemented on backend)
 */
export async function deleteConversation(conversationId: string): Promise<boolean> {
  try {
    const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
    const sessionId = getOrCreateSessionId()
    
    const response = await fetch(`${baseUrl}/conversation/delete`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        params: {
          conversationId,
          sessionId
        }
      })
    })
    
    if (!response.ok) {
      console.error('[ConversationAPI] Failed to delete conversation:', response.statusText)
      return false
    }
    
    const result = await response.json()
    
    if (result.success) {
      console.log('[ConversationAPI] Successfully deleted conversation:', conversationId)
      return true
    } else {
      console.error('[ConversationAPI] Delete conversation failed:', result.error)
      return false
    }
  } catch (error) {
    console.error('[ConversationAPI] Error deleting conversation:', error)
    return false
  }
}

/**
 * Update conversation title - persists to database and emits local event
 */
export async function updateConversationTitle(conversationId: string, title: string): Promise<boolean> {
  try {
    console.log('[ConversationAPI] Updating title:', { conversationId, title })
    
    // Persist to database
    const response = await fetch(`${API_BASE_URL}/conversation/update-title`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        params: { conversationId, title }
      })
    })
    
    const result = await response.json()
    
    if (result.success) {
      // Also emit local event for immediate UI update
      const event = new CustomEvent('conversationTitleUpdate', {
        detail: { conversationId, title }
      })
      window.dispatchEvent(event)
      console.log('[ConversationAPI] Title updated and event emitted:', { conversationId, title })
      return true
    } else {
      console.error('[ConversationAPI] Failed to update title:', result.error)
      return false
    }
  } catch (error) {
    console.error('[ConversationAPI] Error updating title:', error)
    return false
  }
}

/**
 * Notify that a new conversation was created
 */
export function notifyConversationCreated(conversation: Conversation): void {
  console.log('[ConversationAPI] About to emit conversationCreated event for:', conversation.conversation_id)
  const event = new CustomEvent('conversationCreated', {
    detail: { conversation }
  })
  window.dispatchEvent(event)
  console.log('[ConversationAPI] Conversation created event emitted successfully:', conversation)
}
