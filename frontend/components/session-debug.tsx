"use client"

import { useState, useEffect } from "react"
import { getOrCreateSessionId, getCollaborativeSession, isInCollaborativeSession } from "@/lib/session"
import { listConversations } from "@/lib/conversation-api"
import { Button } from "@/components/ui/button"

/**
 * Debug component to display session state
 * Add this to your layout temporarily to debug collaborative session issues
 */
export function SessionDebug() {
  const [sessionInfo, setSessionInfo] = useState<any>(null)
  const [conversations, setConversations] = useState<any[]>([])
  const [isOpen, setIsOpen] = useState(false)

  useEffect(() => {
    const updateInfo = async () => {
      const sessionId = getOrCreateSessionId()
      const collaborativeSession = getCollaborativeSession()
      const isCollab = isInCollaborativeSession()
      
      // Get auth info
      const token = sessionStorage.getItem('auth_token')
      const userInfo = sessionStorage.getItem('user_info')
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
    // Update every 5 seconds
    const interval = setInterval(updateInfo, 5000)
    return () => clearInterval(interval)
  }, [])

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
    <div className="fixed bottom-4 left-4 z-50 bg-black/90 text-white p-4 rounded-lg max-w-md max-h-96 overflow-auto text-xs font-mono">
      <div className="flex justify-between items-center mb-2">
        <span className="font-bold text-yellow-400">Session Debug</span>
        <Button onClick={() => setIsOpen(false)} size="sm" variant="ghost" className="text-white">×</Button>
      </div>
      
      {sessionInfo && (
        <div className="space-y-2">
          <div><span className="text-gray-400">User:</span> {sessionInfo.username}</div>
          <div><span className="text-gray-400">Session ID:</span> {sessionInfo.sessionId?.slice(0, 20)}...</div>
          <div><span className="text-gray-400">Collab Session:</span> {sessionInfo.collaborativeSession || 'none'}</div>
          <div><span className="text-gray-400">In Collab:</span> {sessionInfo.isInCollaborativeSession ? '✅ YES' : '❌ NO'}</div>
          <div><span className="text-gray-400">Authenticated:</span> {sessionInfo.hasAuthToken ? '✅ YES' : '❌ NO'}</div>
          <div className="border-t border-gray-700 pt-2 mt-2">
            <span className="text-gray-400">Conversations ({conversations.length}):</span>
            <ul className="ml-2 mt-1">
              {conversations.slice(0, 5).map((conv, i) => (
                <li key={i} className="truncate text-green-400">
                  • {conv.name || conv.conversation_id?.slice(0, 12)}...
                </li>
              ))}
              {conversations.length > 5 && <li className="text-gray-500">...and {conversations.length - 5} more</li>}
            </ul>
          </div>
          <div className="text-gray-500 text-[10px]">Updated: {sessionInfo.timestamp}</div>
        </div>
      )}
    </div>
  )
}
