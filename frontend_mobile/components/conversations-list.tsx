"use client"

import { useEffect, useState, useCallback } from "react"
import { listConversations, deleteConversation, deleteAllConversations, type Conversation } from "@/lib/conversation-api"
import { useEventHub } from "@/contexts/event-hub-context"
import { MessageSquare, Trash2, RefreshCw, Plus, Trash } from "lucide-react"

interface ConversationsListProps {
  onSelect: (conversationId: string) => void
  onNew: () => void
  selectedId?: string | null
}

export function ConversationsList({ onSelect, onNew, selectedId }: ConversationsListProps) {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const { subscribe, unsubscribe } = useEventHub()

  const refresh = useCallback(async () => {
    setIsLoading(true)
    const { conversations: convs } = await listConversations()
    // Sort by most recent (reverse order, newest first)
    setConversations(convs.reverse())
    setIsLoading(false)
  }, [])

  useEffect(() => { refresh() }, [refresh])

  // Listen for real-time conversation updates
  useEffect(() => {
    const handleConversation = () => { refresh() }
    const handleMessage = () => { refresh() }

    subscribe("conversation_created", handleConversation)
    subscribe("conversation_updated", handleConversation)
    subscribe("message", handleMessage)

    return () => {
      unsubscribe("conversation_created", handleConversation)
      unsubscribe("conversation_updated", handleConversation)
      unsubscribe("message", handleMessage)
    }
  }, [subscribe, unsubscribe, refresh])

  const handleDelete = async (e: React.MouseEvent, convId: string) => {
    e.stopPropagation()
    if (confirm("Delete this conversation?")) {
      await deleteConversation(convId)
      refresh()
    }
  }

  const handleDeleteAll = async () => {
    if (conversations.length === 0) return
    if (confirm(`Delete all ${conversations.length} conversations? This cannot be undone.`)) {
      await deleteAllConversations()
      refresh()
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <h2 className="text-lg font-semibold">Conversations</h2>
        <div className="flex items-center gap-1">
          {conversations.length > 0 && (
            <button onClick={handleDeleteAll} className="p-2 text-muted-foreground hover:text-red-500 transition-colors" title="Delete all">
              <Trash className="h-4 w-4" />
            </button>
          )}
          <button onClick={refresh} className="p-2 text-muted-foreground hover:text-foreground transition-colors">
            <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} />
          </button>
          <button onClick={onNew} className="p-2 text-primary hover:text-primary/80 transition-colors">
            <Plus className="h-5 w-5" />
          </button>
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto scroll-smooth">
        {conversations.length === 0 && !isLoading && (
          <div className="flex flex-col items-center justify-center h-40 text-muted-foreground text-sm">
            <MessageSquare className="h-8 w-8 mb-2 opacity-50" />
            <p>No conversations yet</p>
            <p className="text-xs mt-1">Start one with the voice button below</p>
          </div>
        )}

        {conversations.map((conv) => {
          const title = conv.name || "Untitled conversation"
          const msgCount = conv.messages?.length || 0
          const isSelected = conv.conversation_id === selectedId

          return (
            <div
              key={conv.conversation_id}
              role="button"
              tabIndex={0}
              onClick={() => onSelect(conv.conversation_id)}
              className={`w-full text-left px-4 py-3 border-b border-border/50 flex items-center gap-3 transition-colors active:bg-accent/50 cursor-pointer ${
                isSelected ? "bg-accent/30" : ""
              }`}
            >
              <div className="h-10 w-10 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                <MessageSquare className="h-5 w-5 text-primary" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{title}</p>
                <p className="text-xs text-muted-foreground">
                  Tap to view
                </p>
              </div>
              <button
                onClick={(e) => handleDelete(e, conv.conversation_id)}
                className="p-2 text-muted-foreground hover:text-red-500 transition-colors shrink-0"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
