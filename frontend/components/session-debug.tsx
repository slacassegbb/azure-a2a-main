"use client"

import { useState, useEffect } from "react"
import { getOrCreateSessionId, getCollaborativeSession, isInCollaborativeSession } from "@/lib/session"
import { listConversations } from "@/lib/conversation-api"
import { Button } from "@/components/ui/button"
import { useEventHub } from "@/hooks/use-event-hub"

/**
 * Debug component to display session state
 * Add this to your layout temporarily to debug collaborative session issues
 */
export function SessionDebug() {
  const [sessionInfo, setSessionInfo] = useState<any>(null)
  const [conversations, setConversations] = useState<any[]>([])
  const [isOpen, setIsOpen] = useState(false)
  const [eventLog, setEventLog] = useState<string[]>([])
  const { subscribe, unsubscribe, isConnected } = useEventHub()

  // Log WebSocket events
  useEffect(() => {
    const logEvent = (eventType: string) => (data: any) => {
      const timestamp = new Date().toLocaleTimeString()
      const convId = data?.conversationId || data?.data?.conversationId || ''
      setEventLog(prev => [`${timestamp} ${eventType} ${convId.slice(0, 8)}`, ...prev.slice(0, 19)])
    }

    const events = ['message', 'shared_message', 'conversation_created', 'task_update', 'conversation_title_update']
    events.forEach(e => subscribe(e, logEvent(e)))
    
    return () => {
      events.forEach(e => unsubscribe(e, logEvent(e)))
    }
  }, [subscribe, unsubscribe])

  useEffect(() => {
    const updateInfo = async () => {
      const sessionId = getOrCreateSessionId()
      const collaborativeSession = getCollaborativeSession()
      const isCollab = isInCollaborativeSession()
      
      // Get auth info
      const token = sessionStorage.getItem('auth_token')
      const userInfo = sessionStorage.getItem('user_info')
      const backendSessionId = localStorage.getItem('a2a_backend_session_id')
      const justJoined = sessionStorage.getItem('a2a_collaborative_session_just_joined')
      let parsedUser = null
      try {
        parsedUser = userInfo ? JSON.parse(userInfo) : null
      } catch (e) {}

      setSessionInfo({
        sessionId,
        collaborativeSession,
        isInCollaborativeSession: isCollab,
        hasAuthToken: !!token,
        username: parsedUser?.username || 'anonymous',
        userId: parsedUser?.user_id || 'unknown',
        backendSessionId: backendSessionId?.slice(0, 12),
        justJoined: !!justJoined,
        wsConnected: isConnected,
        timestamp: new Date().toISOString()
      })

      // Load conversations
      try {
        const convs = await listConversations()
        setConversations(convs)
      } catch (e) {
        console.error('Failed to load conversations for debug:', e)
      }
    }

    updateInfo()
    // Update every 2 seconds
    const interval = setInterval(updateInfo, 2000)
    return () => clearInterval(interval)
  }, [isConnected])

  if (!isOpen) {
    return (
      <Button 
        onClick={() => setIsOpen(true)} 
        className="fixed bottom-4 left-4 z-50 bg-yellow-500 hover:bg-yellow-600 text-black text-xs px-2 py-1"
        size="sm"
      >
        🔧 Debug
      </Button>
    )
  }

  return (
    <div className="fixed bottom-4 left-4 z-50 bg-black/90 text-white p-4 rounded-lg max-w-lg max-h-[80vh] overflow-auto text-xs font-mono">
      <div className="flex justify-between items-center mb-2">
        <span className="font-bold text-yellow-400">Session Debug</span>
        <Button onClick={() => setIsOpen(false)} size="sm" variant="ghost" className="text-white h-6 w-6 p-0">×</Button>
      </div>
      
      {sessionInfo && (
        <div className="space-y-1">
          <div><span className="text-gray-400">User:</span> {sessionInfo.username} <span className="text-gray-600">({sessionInfo.userId})</span></div>
          <div><span className="text-gray-400">Session ID:</span> <span className="text-cyan-400">{sessionInfo.sessionId?.slice(0, 25)}...</span></div>
          <div><span className="text-gray-400">Collab Session:</span> <span className={sessionInfo.collaborativeSession ? 'text-green-400' : 'text-gray-600'}>{sessionInfo.collaborativeSession?.slice(0, 25) || 'none'}</span></div>
          <div><span className="text-gray-400">In Collab:</span> {sessionInfo.isInCollaborativeSession ? '✅' : '❌'} | <span className="text-gray-400">WS:</span> {sessionInfo.wsConnected ? '✅' : '❌'}</div>
          <div><span className="text-gray-400">Backend Session:</span> {sessionInfo.backendSessionId || 'none'}</div>
          
          <div className="border-t border-gray-700 pt-2 mt-2">
            <span className="text-gray-400">Conversations ({conversations.length}):</span>
            <ul className="ml-2 mt-1">
              {conversations.slice(0, 3).map((conv, i) => (
                <li key={i} className="truncate text-green-400">
                  • {conv.name || conv.conversation_id?.slice(0, 16)}
                </li>
              ))}
              {conversations.length > 3 && <li className="text-gray-500">...+{conversations.length - 3} more</li>}
            </ul>
          </div>

          <div className="border-t border-gray-700 pt-2 mt-2">
            <span className="text-gray-400">Recent Events:</span>
            <ul className="ml-2 mt-1 text-[10px]">
              {eventLog.slice(0, 5).map((log, i) => (
                <li key={i} className="text-purple-400">{log}</li>
              ))}
              {eventLog.length === 0 && <li className="text-gray-600">No events yet</li>}
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}
