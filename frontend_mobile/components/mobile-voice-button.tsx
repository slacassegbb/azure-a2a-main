"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import { useVoiceRealtime } from "@/hooks/use-voice-realtime"
import { API_BASE_URL } from "@/lib/api-config"
import { getOrCreateSessionId, createContextId } from "@/lib/session"
import { createConversation } from "@/lib/conversation-api"
import { Phone, PhoneOff, Mic, Volume2, Loader2, AlertTriangle } from "lucide-react"

interface MobileVoiceButtonProps {
  conversationId: string | null
  onConversationCreated?: (id: string) => void
  onFirstMessage?: (conversationId: string, transcript: string) => void
  onVoiceStateChange?: (active: boolean) => void
}

export function MobileVoiceButton({ conversationId, onConversationCreated, onFirstMessage, onVoiceStateChange }: MobileVoiceButtonProps) {
  const sessionId = getOrCreateSessionId()
  const [activeConvId, setActiveConvId] = useState(conversationId)
  const [activeContextId, setActiveContextId] = useState(
    conversationId ? createContextId(conversationId) : createContextId("mobile-default")
  )
  const firstMessageSentRef = useRef(false)
  const isNewConvRef = useRef(false)

  useEffect(() => {
    if (conversationId) {
      setActiveConvId(conversationId)
      setActiveContextId(createContextId(conversationId))
    }
  }, [conversationId])

  const voice = useVoiceRealtime({
    apiUrl: API_BASE_URL,
    sessionId,
    contextId: activeContextId,
    onTranscript: (text, isFinal) => {
      if (isFinal && isNewConvRef.current && !firstMessageSentRef.current && activeConvId && onFirstMessage) {
        onFirstMessage(activeConvId, text)
        firstMessageSentRef.current = true
      }
    },
  })

  // Notify parent of voice state changes
  const prevConnected = useRef(false)
  useEffect(() => {
    if (voice.isConnected !== prevConnected.current) {
      prevConnected.current = voice.isConnected
      onVoiceStateChange?.(voice.isConnected)
    }
  }, [voice.isConnected, onVoiceStateChange])

  const handleStart = useCallback(async () => {
    firstMessageSentRef.current = false
    isNewConvRef.current = false

    // Create a new conversation if we don't have one
    if (!conversationId) {
      const conv = await createConversation()
      if (conv) {
        isNewConvRef.current = true
        const newCtx = createContextId(conv.conversation_id)
        voice.updateContextId(newCtx)
        setActiveConvId(conv.conversation_id)
        setActiveContextId(newCtx)
        onConversationCreated?.(conv.conversation_id)
      }
    }

    voice.startConversation()
  }, [conversationId, voice, onConversationCreated])

  const handleClick = () => {
    if (!voice.isConnected) {
      handleStart()
      return
    }
    if (voice.isTalking) {
      voice.stopTalking()
    } else {
      voice.startTalking()
    }
  }

  const getState = () => {
    if (voice.error) return { color: "bg-red-500", ring: "ring-red-500/30", icon: "error", label: "Error - tap to retry" }
    if (voice.isTalking) return { color: "bg-red-500", ring: "ring-red-500/30", icon: "talking", label: "Listening... Tap to send" }
    if (voice.isSpeaking) return { color: "bg-purple-500", ring: "ring-purple-500/30", icon: "speaking", label: "Speaking..." }
    if (voice.isProcessing || voice.isVoiceProcessing) return {
      color: "bg-amber-500", ring: "ring-amber-500/30",
      icon: "processing",
      label: voice.currentAgent ? `${voice.currentAgent}...` : "Processing..."
    }
    if (voice.isConnected) return { color: "bg-blue-500", ring: "ring-blue-500/30", icon: "ready", label: "Tap to talk" }
    return { color: "bg-primary", ring: "ring-primary/30", icon: "idle", label: "Start conversation" }
  }

  const state = getState()
  const isActive = voice.isConnected

  const renderIcon = () => {
    switch (state.icon) {
      case "error": return <AlertTriangle className="h-8 w-8" />
      case "talking": return <Mic className="h-8 w-8 animate-pulse" />
      case "speaking": return <Volume2 className="h-8 w-8" />
      case "processing": return <Loader2 className="h-8 w-8 animate-spin" />
      case "ready": return <Mic className="h-8 w-8" />
      default: return <Phone className="h-8 w-8" />
    }
  }

  return (
    <div className="flex flex-col items-center gap-3">
      {/* Status label */}
      <p className="text-sm text-muted-foreground h-5">
        {isActive ? state.label : ""}
      </p>

      {/* Main voice button */}
      <div className="relative">
        {isActive && (
          <>
            <span className={`absolute inset-0 rounded-full ${state.color} animate-ping opacity-20`} />
            <span className={`absolute -inset-2 rounded-full ${state.color} opacity-10 animate-pulse`} />
          </>
        )}
        <button
          onClick={handleClick}
          className={`relative z-10 h-20 w-20 rounded-full ${state.color} text-white shadow-lg active:scale-95 transition-all duration-150 flex items-center justify-center ${isActive ? `ring-4 ${state.ring}` : ""}`}
        >
          {renderIcon()}
        </button>
      </div>

      {/* Disconnect button */}
      {voice.isConnected && (
        <button
          onClick={() => voice.stopConversation()}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-red-500 transition-colors mt-1"
        >
          <PhoneOff className="h-3.5 w-3.5" />
          End session
        </button>
      )}

      {/* Current agent indicator */}
      {voice.currentAgent && (
        <div className="text-xs text-amber-500 animate-pulse">
          {voice.currentAgent} agent working...
        </div>
      )}

      {/* Error display */}
      {voice.error && (
        <div className="text-xs text-red-500 max-w-[250px] text-center">
          {voice.error}
        </div>
      )}
    </div>
  )
}
