import { getOrCreateSessionId } from './session'
import { logDebug } from '@/lib/debug'
import { API_BASE_URL } from '@/lib/api-config'

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

export interface ListConversationsResult {
  conversations: Conversation[]
  messageUserMap: Record<string, string>
}

export async function listConversations(): Promise<ListConversationsResult> {
  try {
    const sessionId = getOrCreateSessionId()
    const response = await fetch(`${API_BASE_URL}/conversation/list`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        jsonrpc: '2.0',
        method: 'conversation/list',
        params: { sessionId },
        id: `req_${Date.now()}`
      })
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const data = await response.json()
    return {
      conversations: data.result || [],
      messageUserMap: data.message_user_map || {}
    }
  } catch (error) {
    console.error('[ConversationAPI] Failed to list:', error)
    return { conversations: [], messageUserMap: {} }
  }
}

export async function createConversation(): Promise<Conversation | null> {
  try {
    const response = await fetch(`${API_BASE_URL}/conversation/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        jsonrpc: '2.0',
        method: 'conversation/create',
        id: `req_${Date.now()}`
      })
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const data = await response.json()
    return data.result
  } catch (error) {
    console.error('[ConversationAPI] Failed to create:', error)
    return null
  }
}

export async function listMessages(conversationId: string): Promise<Message[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/message/list`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        jsonrpc: '2.0',
        method: 'message/list',
        params: conversationId,
        id: `req_${Date.now()}`
      })
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const data = await response.json()
    return data.result || []
  } catch (error) {
    console.error('[ConversationAPI] Failed to list messages:', error)
    return []
  }
}

export async function deleteConversation(conversationId: string): Promise<boolean> {
  try {
    const sessionId = getOrCreateSessionId()
    const response = await fetch(`${API_BASE_URL}/conversation/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ params: { conversationId, sessionId } })
    })
    if (!response.ok) return false
    const result = await response.json()
    return result.success === true
  } catch {
    return false
  }
}

export async function deleteAllConversations(): Promise<boolean> {
  try {
    const sessionId = getOrCreateSessionId()
    const response = await fetch(`${API_BASE_URL}/conversation/delete-all`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ params: { sessionId } })
    })
    if (!response.ok) return false
    const result = await response.json()
    return result.success === true
  } catch {
    return false
  }
}

export async function updateConversationTitle(conversationId: string, title: string): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/conversation/update-title`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ params: { conversationId, title } })
    })
    const result = await response.json()
    return result.success === true
  } catch {
    return false
  }
}
