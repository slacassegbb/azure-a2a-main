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
  onQueryStart?: () => void
  compact?: boolean
}

export function MobileVoiceButton({ conversationId, onConversationCreated, onFirstMessage, onVoiceStateChange, onQueryStart, compact }: MobileVoiceButtonProps) {
  const sessionId = getOrCreateSessionId()
  const [activeConvId, setActiveConvId] = useState(conversationId)
  const [activeContextId, setActiveContextId] = useState(
    conversationId ? createContextId(conversationId) : createContextId("mobile-default")
  )
  const firstMessageSentRef = useRef(false)
  const isNewConvRef = useRef(false)

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

  // Keep active IDs in sync when conversationId prop changes
  useEffect(() => {
    if (conversationId) {
      setActiveConvId(conversationId)
      const newCtx = createContextId(conversationId)
      setActiveContextId(newCtx)
      voice.updateContextId(newCtx)
    }
  }, [conversationId])

  // Notify parent of voice state changes
  const prevConnected = useRef(false)
  useEffect(() => {
    if (voice.isConnected !== prevConnected.current) {
      prevConnected.current = voice.isConnected
      onVoiceStateChange?.(voice.isConnected)
    }
  }, [voice.isConnected, onVoiceStateChange])

  // Detect when talking stops (manual tap OR server-side VAD) → fire onQueryStart
  const prevTalkingRef = useRef(false)
  useEffect(() => {
    if (prevTalkingRef.current && !voice.isTalking) {
      // Talking just ended → query about to be processed
      onQueryStart?.()
    }
    prevTalkingRef.current = voice.isTalking
  }, [voice.isTalking, onQueryStart])

  const handleStart = useCallback(async () => {
    firstMessageSentRef.current = false
    isNewConvRef.current = false

    // Only create a new conversation if we don't already have one
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
    } else {
      // Already in a conversation — make sure voice targets it
      const currentCtx = createContextId(conversationId)
      voice.updateContextId(currentCtx)
      setActiveConvId(conversationId)
      setActiveContextId(currentCtx)
    }

    voice.startConversation()
  }, [conversationId, voice, onConversationCreated])

  const handleClick = async () => {
    if (!voice.isConnected) {
      handleStart()
      return
    }
    if (voice.isTalking) {
      // User finished speaking → useEffect on isTalking will fire onQueryStart
      voice.stopTalking()
    } else {
      // If no conversation selected (e.g. user navigated back to list), create one first
      if (!conversationId) {
        const conv = await createConversation()
        if (conv) {
          isNewConvRef.current = true
          firstMessageSentRef.current = false
          const newCtx = createContextId(conv.conversation_id)
          voice.updateContextId(newCtx)
          setActiveConvId(conv.conversation_id)
          setActiveContextId(newCtx)
          onConversationCreated?.(conv.conversation_id)
        }
      }
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
    const size = compact ? "h-6 w-6" : "h-8 w-8"
    switch (state.icon) {
      case "error": return <AlertTriangle className={size} />
      case "talking": return <Mic className={`${size} animate-pulse`} />
      case "speaking": return <Volume2 className={size} />
      case "processing": return <Loader2 className={`${size} animate-spin`} />
      case "ready": return <Mic className={size} />
      default: return <Phone className={size} />
    }
  }

  if (compact) {
    return (
      <div className="flex flex-col items-center -mt-5">
        {/* The circle button */}
        <div className="relative">
          {isActive && (
            <span className={`absolute -inset-1 rounded-full ${state.color} opacity-20 animate-pulse`} />
          )}
          <button
            onClick={handleClick}
            className={`relative z-10 h-14 w-14 rounded-full ${state.color} text-white shadow-lg active:scale-95 transition-all duration-150 flex items-center justify-center ${isActive ? `ring-2 ${state.ring}` : ""}`}
          >
            {renderIcon()}
          </button>
        </div>

        {/* Only show yellow agent-working text */}
        {voice.currentAgent && (
          <span className="mt-2 text-[10px] text-amber-500 animate-pulse font-medium leading-none whitespace-nowrap">
            {voice.currentAgent} working…
          </span>
        )}
      </div>
    )
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
