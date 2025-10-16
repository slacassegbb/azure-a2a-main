/**
 * Conversation API client for A2A backend
 * 
 * This provides TypeScript functions to interact with the A2A conversation endpoints
 */

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

/**
 * List all conversations
 */
export async function listConversations(): Promise<Conversation[]> {
  try {
    console.log('[ConversationAPI] Calling listConversations endpoint...')
    const response = await fetch(`${API_BASE_URL}/conversation/list`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        jsonrpc: '2.0',
        method: 'conversation/list',
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
    console.log('[ConversationAPI] Parsed conversations:', conversations)
    
    return conversations
  } catch (error) {
    console.error('[ConversationAPI] Failed to list conversations:', error)
    return []
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
export async function getConversation(conversationId: string): Promise<Conversation | null> {
  try {
    console.log('[ConversationAPI] Getting conversation:', conversationId)
    const conversations = await listConversations()
    const conversation = conversations.find(conv => conv.conversation_id === conversationId)
    
    if (conversation) {
      console.log('[ConversationAPI] Found conversation with', conversation.messages?.length || 0, 'embedded messages')
      return conversation
    } else {
      console.log('[ConversationAPI] Conversation not found:', conversationId)
      return null
    }
  } catch (error) {
    console.error('[ConversationAPI] Failed to get conversation:', error)
    return null
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
  // Note: This endpoint might not exist yet, but we can add it later
  console.log('[ConversationAPI] Delete conversation not implemented yet:', conversationId)
  return false
}

/**
 * Update conversation title (simple client-side approach)
 * For now, we'll emit an event that the sidebar can listen to
 */
export function updateConversationTitle(conversationId: string, title: string): void {
  // Emit a custom event that the sidebar can listen to
  const event = new CustomEvent('conversationTitleUpdate', {
    detail: { conversationId, title }
  })
  window.dispatchEvent(event)
  console.log('[ConversationAPI] Title update event emitted:', { conversationId, title })
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
