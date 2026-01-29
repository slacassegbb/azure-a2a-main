"use client"

import { useState, useEffect, useCallback } from "react"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { MessageSquarePlus, PanelLeftClose, PanelLeftOpen, Trash2, LogOut, SquarePen } from "lucide-react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { cn } from "@/lib/utils"
import { listConversations, createConversation, deleteConversation, listMessages, notifyConversationCreated, type Conversation } from "@/lib/conversation-api"
import { LoginDialog } from "@/components/login-dialog"
import { useEventHub } from "@/hooks/use-event-hub"
import { getOrCreateSessionId } from "@/lib/session"

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

  const handleLogout = () => {
    if (typeof window !== 'undefined') {
      sessionStorage.removeItem('auth_token')
      sessionStorage.removeItem('user_info')
      setCurrentUser(null)
      // Reload to disconnect authenticated WebSocket connection
      window.location.reload()
    }
  }

  const loadConversations = useCallback(async () => {
    try {
      setIsLoading(true)
      setError(null)
      console.log('[ChatHistorySidebar] Loading conversations...')
      const conversations = await listConversations()
      console.log('[ChatHistorySidebar] Received conversations:', conversations)
      
      // For each conversation without a name, try to get the first message as title
      const conversationsWithTitles = await Promise.all(
        conversations.map(async (conv) => {
          if (!conv.name?.trim()) {
            try {
              // Use the embedded messages from the conversation object instead of making a separate API call
              const messages = conv.messages || []
              console.log('[ChatHistorySidebar] Using embedded messages for conversation:', conv.conversation_id, 'count:', messages.length)
              
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
                  return { ...conv, name: title }
                }
              }
            } catch (err) {
              console.error('[ChatHistorySidebar] Failed to process embedded messages for conversation:', conv.conversation_id, err)
            }
          }
          return conv
        })
      )
      
      setConversations(conversationsWithTitles)
      console.log('[ChatHistorySidebar] Final conversations with titles:', conversationsWithTitles.map(c => ({ 
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
    console.log('[ChatHistorySidebar] Component mounting or session changed, loading conversations...')
    loadConversations()
  }, [loadConversations, currentSessionId])

  // Monitor for session changes (joining collaborative session)
  useEffect(() => {
    const checkSessionChange = () => {
      const newSessionId = getOrCreateSessionId()
      setCurrentSessionId(prev => {
        if (prev !== newSessionId) {
          console.log('[ChatHistorySidebar] Session ID changed:', prev, '->', newSessionId)
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
        console.log('[ChatHistorySidebar] session_started event but no sessionId found')
        return
      }
      
      const storedSessionId = localStorage.getItem(BACKEND_SESSION_KEY)
      
      if (storedSessionId && storedSessionId !== newSessionId) {
        // Backend restarted - clear conversation list and reload from server
        console.log('[ChatHistorySidebar] Backend restarted (session changed), clearing conversations')
        console.log('[ChatHistorySidebar] Old session:', storedSessionId?.slice(0, 8), '-> New session:', newSessionId.slice(0, 8))
        setConversations([])
        // Reload conversations from the (new) backend
        loadConversations()
        // If we're currently viewing a conversation, navigate away since it may not exist
        if (currentConversationId) {
          console.log('[ChatHistorySidebar] Navigating away from stale conversation')
          router.push('/')
        }
      }
      
      // Store the new session ID
      localStorage.setItem(BACKEND_SESSION_KEY, newSessionId)
      console.log('[ChatHistorySidebar] Backend session ID stored:', newSessionId.slice(0, 8))
    }

    // Handle session members updated - fires when we join a collaborative session
    const handleSessionMembersUpdated = (data: any) => {
      console.log('[ChatHistorySidebar] Session members updated:', data)
      // Check if our session ID changed
      const newSessionId = getOrCreateSessionId()
      setCurrentSessionId(prev => {
        if (prev !== newSessionId) {
          console.log('[ChatHistorySidebar] Session ID changed after members update:', prev, '->', newSessionId)
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
        console.log('[ChatHistorySidebar] conversation_title_update event missing data:', data)
        return
      }
      
      console.log('[ChatHistorySidebar] Received WebSocket title update:', { conversationId, title })
      
      setConversations(prev => prev.map(conv => 
        conv.conversation_id === conversationId 
          ? { ...conv, name: title }
          : conv
      ))
    }

    subscribe('conversation_title_update', handleWebSocketTitleUpdate)
    
    // Reload conversations after subscribing to catch any updates we missed during mount
    // Small delay to ensure subscriptions are fully set up
    const reloadTimeout = setTimeout(() => {
      console.log('[ChatHistorySidebar] Reloading conversations after subscriptions ready')
      loadConversations()
    }, 500)
    
    return () => {
      unsubscribe('conversation_title_update', handleWebSocketTitleUpdate)
      clearTimeout(reloadTimeout)
    }
  }, [subscribe, unsubscribe, loadConversations])

  useEffect(() => {
    console.log('[ChatHistorySidebar] Setting up event listeners...')
    
    const handleTitleUpdate = (event: CustomEvent) => {
      const { conversationId, title } = event.detail
      console.log('[ChatHistorySidebar] Received title update:', { conversationId, title })
      
      setConversations(prev => prev.map(conv => 
        conv.conversation_id === conversationId 
          ? { ...conv, name: title }
          : conv
      ))
    }

    const handleConversationCreated = (event: CustomEvent) => {
      const { conversation } = event.detail
      console.log('[ChatHistorySidebar] Received new conversation event:', conversation)
      
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
    console.log('[ChatHistorySidebar] Event listeners set up successfully')
    
    return () => {
      console.log('[ChatHistorySidebar] Cleaning up event listeners')
      window.removeEventListener('conversationTitleUpdate', handleTitleUpdate as EventListener)
      window.removeEventListener('conversationCreated', handleConversationCreated as EventListener)
    }
  }, [])

  const handleNewChat = useCallback(() => {
    // Just navigate to home - no conversationId
    // This will show a blank chat, and a conversation will be created on first message
    console.log("[ChatHistorySidebar] Starting new chat (clearing conversation)")
    router.push("/")
  }, [router])

  const handleConversationClick = useCallback((conversationId: string) => {
    console.log('[ChatHistorySidebar] Clicking on conversation:', conversationId)
    console.log('[ChatHistorySidebar] Current URL params:', searchParams.toString())
    router.push(`/?conversationId=${conversationId}`)
    console.log('[ChatHistorySidebar] Navigating to:', `/?conversationId=${conversationId}`)
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

  return (
    <TooltipProvider delayDuration={0}>
      <div className={cn("flex h-full flex-col transition-all duration-300")}>
        {isCollapsed ? (
          // Collapsed state - minimal vertical layout
          <div className="flex flex-col items-center justify-start h-full py-2">
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
                      console.log("Login successful for:", email)
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
            
            <div className="flex-1 overflow-y-auto">
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
