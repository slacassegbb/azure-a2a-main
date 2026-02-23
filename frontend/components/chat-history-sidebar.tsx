"use client"

import { useState, useEffect, useCallback } from "react"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { MessageSquarePlus, PanelLeftClose, PanelLeftOpen, Trash2, LogOut, SquarePen } from "lucide-react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { cn } from "@/lib/utils"
import { listConversations, createConversation, deleteConversation, deleteAllConversations, listMessages, notifyConversationCreated, updateConversationTitle, type Conversation } from "@/lib/conversation-api"
import { LoginDialog } from "@/components/login-dialog"
import { useEventHub } from "@/hooks/use-event-hub"
import { getOrCreateSessionId, leaveCollaborativeSession, isInCollaborativeSession } from "@/lib/session"
import { clearActiveWorkflow } from "@/lib/active-workflow-api"
import { logDebug, warnDebug, errorDebug, logInfo } from '@/lib/debug'

type Props = {
  isCollapsed: boolean
  onToggle: () => void
}

export function ChatHistorySidebar({ isCollapsed, onToggle }: Props) {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [currentUser, setCurrentUser] = useState<any>(null)
  const pathname = usePathname()
  const router = useRouter()
  const searchParams = useSearchParams()
  const currentConversationId = searchParams.get("conversationId")
  const { sendMessage } = useEventHub()

  // Check authentication status
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const token = sessionStorage.getItem('auth_token')
      const userInfo = sessionStorage.getItem('user_info')
      if (token && userInfo) {
        try {
          setCurrentUser(JSON.parse(userInfo))
        } catch (e) {
          console.error('Failed to parse user info:', e)
        }
      }
    }
  }, [])

  const handleLogout = async () => {
    if (typeof window !== 'undefined') {
      // Send logout message to backend to clean up all sessions
      // This handles both: owning a session (others joined you) and being in someone else's session
      sendMessage({ type: 'user_logout' })
      
      // Also clear collaborative session local storage if we're in one
      if (isInCollaborativeSession()) {
        leaveCollaborativeSession(false, sendMessage) // Don't reload yet
      }
      
      // Clear auth data
      sessionStorage.removeItem('auth_token')
      sessionStorage.removeItem('user_info')
      setCurrentUser(null)
      
      // Clear active workflow state via API (session-scoped)
      const sessionId = getOrCreateSessionId()
      try {
        await clearActiveWorkflow(sessionId)
      } catch (error) {
        console.error('[Logout] Failed to clear active workflow:', error)
      }
      
      // Small delay to allow WebSocket message to be sent before reload
      setTimeout(() => {
        window.location.reload()
      }, 100)
    }
  }

  const loadConversations = useCallback(async () => {
    try {
      setIsLoading(true)
      setError(null)
      logDebug('[ChatHistorySidebar] Loading conversations...')
      const { conversations } = await listConversations()
      logDebug('[ChatHistorySidebar] Received conversations:', conversations)
      
      // For each conversation without a name, try to get the first message as title
      const conversationsWithTitles = await Promise.all(
        conversations.map(async (conv) => {
          if (!conv.name?.trim()) {
            try {
              // Use the embedded messages from the conversation object instead of making a separate API call
              const messages = conv.messages || []
              logDebug('[ChatHistorySidebar] Using embedded messages for conversation:', conv.conversation_id, 'count:', messages.length)
              
              const firstUserMessage = messages.find(msg => msg.role === 'user')
              if (firstUserMessage && firstUserMessage.parts) {
                // Extract text from message parts
                const text = firstUserMessage.parts
                  .map((part: any) => part.text || part.content || '')
                  .join(' ')
                  .trim()
                
                if (text) {
                  // Generate a title from the first message
                  const title = text.length > 50 ? text.slice(0, 47) + '...' : text
                  // Persist the generated title to the database (fire and forget)
                  updateConversationTitle(conv.conversation_id, title)
                  return { ...conv, name: title }
                }
              }
            } catch (err) {
              errorDebug('[ChatHistorySidebar] Failed to process embedded messages for conversation:', conv.conversation_id, err)
            }
          }
          return conv
        })
      )
      
      setConversations(conversationsWithTitles)
      logDebug('[ChatHistorySidebar] Final conversations with titles:', conversationsWithTitles.map(c => ({
        id: c.conversation_id,
        name: c.name
      })))
    } catch (err) {
      setError("Failed to load conversations")
      console.error("Error loading conversations:", err)
    } finally {
      setIsLoading(false)
    }
  }, []) // Empty dependencies since we're not using any external values

  // Track the current session ID to detect when joining collaborative sessions
  const [currentSessionId, setCurrentSessionId] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      return getOrCreateSessionId()
    }
    return ''
  })

  // Load conversations on component mount AND when session changes
  useEffect(() => {
    logDebug('[ChatHistorySidebar] Component mounting or session changed, loading conversations...')
    loadConversations()
  }, [loadConversations, currentSessionId])

  // Monitor for session changes (joining collaborative session)
  useEffect(() => {
    const checkSessionChange = () => {
      const newSessionId = getOrCreateSessionId()
      setCurrentSessionId(prev => {
        if (prev !== newSessionId) {
          logDebug('[ChatHistorySidebar] Session ID changed:', prev, '->', newSessionId)
          return newSessionId
        }
        return prev
      })
    }
    
    // Listen for storage events (cross-tab changes)
    window.addEventListener('storage', checkSessionChange)
    
    // Check periodically for same-tab sessionStorage changes
    const interval = setInterval(checkSessionChange, 500)
    
    return () => {
      window.removeEventListener('storage', checkSessionChange)
      clearInterval(interval)
    }
  }, [])

  // Use Event Hub to listen for WebSocket events
  const { subscribe, unsubscribe } = useEventHub()

  // Handle backend session changes - clear conversation list when backend restarts
  useEffect(() => {
    const BACKEND_SESSION_KEY = 'a2a_backend_session_id'
    
    const handleSessionStarted = (data: any) => {
      const newSessionId = data?.data?.sessionId || data?.sessionId
      if (!newSessionId) {
        logDebug('[ChatHistorySidebar] session_started event but no sessionId found')
        return
      }
      
      const storedSessionId = localStorage.getItem(BACKEND_SESSION_KEY)
      
      if (storedSessionId && storedSessionId !== newSessionId) {
        // Backend restarted - clear conversation list and reload from server
        logDebug('[ChatHistorySidebar] Backend restarted (session changed), clearing conversations')
        logDebug('[ChatHistorySidebar] Old session:', storedSessionId?.slice(0, 8), '-> New session:', newSessionId.slice(0, 8))
        setConversations([])
        // Reload conversations from the (new) backend
        loadConversations()
        // If we're currently viewing a conversation, navigate away since it may not exist
        if (currentConversationId) {
          logDebug('[ChatHistorySidebar] Navigating away from stale conversation')
          router.push('/')
        }
      }
      
      // Store the new session ID
      localStorage.setItem(BACKEND_SESSION_KEY, newSessionId)
      logDebug('[ChatHistorySidebar] Backend session ID stored:', newSessionId.slice(0, 8))
    }

    // Handle session members updated - fires when we join a collaborative session
    const handleSessionMembersUpdated = (data: any) => {
      logDebug('[ChatHistorySidebar] Session members updated:', data)
      // Check if our session ID changed
      const newSessionId = getOrCreateSessionId()
      setCurrentSessionId(prev => {
        if (prev !== newSessionId) {
          logDebug('[ChatHistorySidebar] Session ID changed after members update:', prev, '->', newSessionId)
          // Small delay to let session storage settle
          setTimeout(() => loadConversations(), 100)
          return newSessionId
        }
        return prev
      })
    }

    subscribe('session_started', handleSessionStarted)
    subscribe('session_members_updated', handleSessionMembersUpdated)
    
    return () => {
      unsubscribe('session_started', handleSessionStarted)
      unsubscribe('session_members_updated', handleSessionMembersUpdated)
    }
  }, [subscribe, unsubscribe, loadConversations, currentConversationId, router])

  // Listen for conversation title updates from collaborative session members via WebSocket
  useEffect(() => {
    const handleWebSocketTitleUpdate = (data: any) => {
      const conversationId = data?.data?.conversationId || data?.conversationId
      const title = data?.data?.title || data?.title
      
      if (!conversationId || !title) {
        logDebug('[ChatHistorySidebar] conversation_title_update event missing data:', data)
        return
      }
      
      logDebug('[ChatHistorySidebar] Received WebSocket title update:', { conversationId, title })
      
      setConversations(prev => {
        const exists = prev.some(conv => conv.conversation_id === conversationId)
        if (exists) {
          // Update existing conversation's title
          return prev.map(conv => 
            conv.conversation_id === conversationId 
              ? { ...conv, name: title }
              : conv
          )
        } else {
          // Conversation doesn't exist yet - add it with the title
          // This handles the case where title_update arrives before/without conversation_created
          logDebug('[ChatHistorySidebar] Adding new conversation from title update:', conversationId)
          return [{
            conversation_id: conversationId,
            name: title,
            is_active: true,
            task_ids: [],
            messages: []
          }, ...prev]
        }
      })
    }

    subscribe('conversation_title_update', handleWebSocketTitleUpdate)
    
    // Reload conversations after subscribing to catch any updates we missed during mount
    // Small delay to ensure subscriptions are fully set up
    const reloadTimeout = setTimeout(() => {
      logDebug('[ChatHistorySidebar] Reloading conversations after subscriptions ready')
      loadConversations()
    }, 500)
    
    return () => {
      unsubscribe('conversation_title_update', handleWebSocketTitleUpdate)
      clearTimeout(reloadTimeout)
    }
  }, [subscribe, unsubscribe, loadConversations])

  useEffect(() => {
    logDebug('[ChatHistorySidebar] Setting up event listeners...')
    
    const handleTitleUpdate = (event: CustomEvent) => {
      const { conversationId, title } = event.detail
      logDebug('[ChatHistorySidebar] Received title update:', { conversationId, title })
      
      setConversations(prev => prev.map(conv => 
        conv.conversation_id === conversationId 
          ? { ...conv, name: title }
          : conv
      ))
    }

    const handleConversationCreated = (event: CustomEvent) => {
      const { conversation } = event.detail
      logDebug('[ChatHistorySidebar] Received new conversation event:', conversation)
      
      // Add the conversation to the list immediately for instant feedback
      setConversations(prev => {
        const exists = prev.some(conv => conv.conversation_id === conversation.conversation_id)
        if (exists) {
          return prev
        }
        return [conversation, ...prev]
      })
    }

    window.addEventListener('conversationTitleUpdate', handleTitleUpdate as EventListener)
    window.addEventListener('conversationCreated', handleConversationCreated as EventListener)
    logDebug('[ChatHistorySidebar] Event listeners set up successfully')
    
    return () => {
      logDebug('[ChatHistorySidebar] Cleaning up event listeners')
      window.removeEventListener('conversationTitleUpdate', handleTitleUpdate as EventListener)
      window.removeEventListener('conversationCreated', handleConversationCreated as EventListener)
    }
  }, [])

  const handleNewChat = useCallback(() => {
    // Just navigate to home - no conversationId
    // This will show a blank chat, and a conversation will be created on first message
    logDebug("[ChatHistorySidebar] Starting new chat (clearing conversation)")
    router.push("/")
  }, [router])

  const handleConversationClick = useCallback((conversationId: string) => {
    logDebug('[ChatHistorySidebar] Clicking on conversation:', conversationId)
    logDebug('[ChatHistorySidebar] Current URL params:', searchParams.toString())
    router.push(`/?conversationId=${conversationId}`)
    logDebug('[ChatHistorySidebar] Navigating to:', `/?conversationId=${conversationId}`)
  }, [router, searchParams])

  const handleDeleteConversation = useCallback(async (conversationId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      const success = await deleteConversation(conversationId)
      if (success) {
        // Remove the conversation from the list
        setConversations(prev => prev.filter(conv => conv.conversation_id !== conversationId))
        // If we're currently viewing this conversation, navigate away
        if (currentConversationId === conversationId) {
          router.push("/")
        }
      } else {
        setError("Failed to delete conversation")
      }
    } catch (err) {
      setError("Failed to delete conversation")
      console.error("Error deleting conversation:", err)
    }
  }, [currentConversationId, router])

  const handleClearAllChats = useCallback(async () => {
    if (conversations.length === 0) return

    try {
      logDebug('[ChatHistorySidebar] Clearing all chats...')
      const success = await deleteAllConversations()
      if (success) {
        // Clear the conversations list
        setConversations([])
        // Navigate away if we're viewing a conversation
        if (currentConversationId) {
          router.push("/")
        }
        logDebug('[ChatHistorySidebar] All chats cleared successfully')
      } else {
        setError("Failed to clear all chats")
      }
    } catch (err) {
      setError("Failed to clear all chats")
      console.error("Error clearing all chats:", err)
    }
  }, [conversations.length, currentConversationId, router])

  return (
    <TooltipProvider delayDuration={0}>
      <div className={cn("flex flex-col h-full transition-all duration-300")}>
        {isCollapsed ? (
          // Collapsed state - minimal vertical layout
          <div className="flex flex-col items-center justify-start py-2">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon" className="h-9 w-9" onClick={onToggle}>
                  <PanelLeftOpen size={20} />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">Expand Sidebar</TooltipContent>
            </Tooltip>
          </div>
        ) : (
          // Expanded state - full layout
          <>
            <div className="flex h-16 items-center justify-between p-2">
              <div className="flex items-center gap-3 min-w-0 flex-1">
                <img 
                  src="/a2a_transparent.png" 
                  alt="A2A Logo" 
                  className="h-8 object-contain"
                />
              </div>
              <div className="flex items-center gap-2">
                {currentUser ? (
                  <>
                    <span className="text-sm font-medium text-foreground truncate max-w-[100px]">
                      {currentUser.name}
                    </span>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-9 w-9" onClick={handleLogout}>
                          <LogOut size={20} />
                          <span className="sr-only">Logout</span>
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent side="bottom">Logout {currentUser.name}</TooltipContent>
                    </Tooltip>
                  </>
                ) : (
                  <LoginDialog 
                    onLogin={(email, password) => {
                      // Handle login logic here when implemented
                      logDebug("Login successful for:", email)
                    }} 
                  />
                )}
                <Button variant="ghost" size="icon" className="h-9 w-9" onClick={onToggle}>
                  <PanelLeftClose size={20} />
                </Button>
              </div>
            </div>
            
            {error && (
              <div className="p-2 text-sm text-red-500">
                {error}
              </div>
            )}
            
            {/* Chats Header with New Chat Button */}
            <div className="px-3 py-2 flex items-center justify-between">
              <span className="text-sm font-medium text-muted-foreground">Chats</span>
              <div className="flex items-center gap-1">
                {conversations.length > 0 && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button 
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs rounded-md hover:bg-destructive/10 hover:text-destructive"
                        onClick={handleClearAllChats}
                      >
                        Clear All
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side="right">Clear all chats</TooltipContent>
                  </Tooltip>
                )}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button 
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 rounded-md hover:bg-accent"
                      onClick={handleNewChat}
                    >
                      <SquarePen size={16} />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="right">New chat</TooltipContent>
                </Tooltip>
              </div>
            </div>
            
            <div className="flex-1 overflow-y-auto min-h-0">
              {isLoading && (
                <div className="p-2 text-sm text-muted-foreground">
                  Loading conversations...
                </div>
              )}
              
              <ul className="flex flex-col gap-1 p-2">
                {conversations.map((convo, index) => {
                  // Provide fallback for empty names
                  const displayName = convo.name?.trim() || `Conversation ${index + 1}`
                  const conversationId = convo.conversation_id
                  
                  return (
                    <li key={conversationId}>
                      <div className="group relative">
                        <Button
                          variant={currentConversationId === conversationId ? "secondary" : "ghost"}
                          className="h-9 w-full justify-start gap-2 pr-8"
                          onClick={() => handleConversationClick(conversationId)}
                        >
                          <span className="truncate">{displayName}</span>
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="absolute right-1 top-1/2 -translate-y-1/2 h-6 w-6 opacity-0 group-hover:opacity-100 hover:bg-primary/10 hover:text-primary"
                          onClick={(e) => handleDeleteConversation(conversationId, e)}
                        >
                          <Trash2 size={14} />
                        </Button>
                      </div>
                    </li>
                  )
                })}
              </ul>
            </div>
          </>
        )}
      </div>
    </TooltipProvider>
  )
}
