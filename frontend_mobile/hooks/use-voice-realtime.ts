"use client"

import { useCallback, useRef, useState, useEffect } from "react"

interface VoiceRealtimeConfig {
  apiUrl: string
  sessionId: string
  contextId: string
  onTranscript?: (text: string, isFinal: boolean) => void
  onResult?: (result: string) => void
  onError?: (error: string) => void
}

interface VoiceRealtimeHook {
  isConnected: boolean
  isListening: boolean
  isSpeaking: boolean
  isProcessing: boolean
  isTalking: boolean
  isVoiceProcessing: boolean
  currentAgent: string | null
  transcript: string
  result: string
  error: string | null
  startConversation: () => Promise<void>
  stopConversation: () => void
  startTalking: () => void
  stopTalking: (options?: { interruptMode?: boolean }) => void
  updateContextId: (newContextId: string) => void
}

export function useVoiceRealtime(config: VoiceRealtimeConfig): VoiceRealtimeHook {
  const [isConnected, setIsConnected] = useState(false)
  const [isListening, setIsListening] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [currentAgent, setCurrentAgent] = useState<string | null>(null)
  const [transcript, setTranscript] = useState("")
  const [result, setResult] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [isTalking, setIsTalking] = useState(false)
  const [isVoiceProcessing, setIsVoiceProcessing] = useState(false)

  // WebRTC refs
  const pcRef = useRef<RTCPeerConnection | null>(null)
  const dcRef = useRef<RTCDataChannel | null>(null)
  const localTrackRef = useRef<MediaStreamTrack | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null)

  // Backend WebSocket for agent activity filler announcements
  const backendWsRef = useRef<WebSocket | null>(null)

  // State refs for use in callbacks
  const isTalkingRef = useRef(false)
  const autoActivateRef = useRef(false)
  const pendingCallRef = useRef<{ call_id: string; item_id: string } | null>(null)
  const isProcessingRef = useRef(false)
  const isResponseActiveRef = useRef(false)
  const announcedAgentsRef = useRef<Set<string>>(new Set())
  const contextIdRef = useRef(config.contextId)
  const sessionIdRef = useRef(config.sessionId)

  useEffect(() => {
    contextIdRef.current = config.contextId
    sessionIdRef.current = config.sessionId
  }, [config.contextId, config.sessionId])

  const updateContextId = useCallback((newContextId: string) => {
    contextIdRef.current = newContextId
    if (newContextId.includes("::")) sessionIdRef.current = newContextId.split("::")[0]
  }, [])

  // ── Data channel helpers ──────────────────────────────────────────────

  const sendEvent = useCallback((event: object) => {
    if (dcRef.current?.readyState === "open") {
      dcRef.current.send(JSON.stringify(event))
    }
  }, [])

  /** Mute/unmute the local mic track (WebRTC sends silence when disabled) */
  const setMicEnabled = useCallback((enabled: boolean) => {
    if (localTrackRef.current) localTrackRef.current.enabled = enabled
  }, [])

  // ── Filler speech via Azure Realtime (same mechanism, now via data channel) ──

  const speakFillerViaAzure = useCallback((text: string) => {
    if (dcRef.current?.readyState !== "open") return
    if (isResponseActiveRef.current || !isProcessingRef.current) return
    isResponseActiveRef.current = true
    sendEvent({
      type: "response.create",
      response: { modalities: ["audio", "text"], instructions: `Say exactly this in a brief, natural way: "${text}"` },
    })
  }, [sendEvent])

  // ── Backend WebSocket for agent activity events ───────────────────────

  const connectBackendWebSocket = useCallback(() => {
    let wsBaseUrl = process.env.NEXT_PUBLIC_WEBSOCKET_URL || config.apiUrl.replace(/^http/, "ws")
    const wsUrl = wsBaseUrl.endsWith("/events")
      ? `${wsBaseUrl}?tenantId=${encodeURIComponent(contextIdRef.current)}`
      : `${wsBaseUrl}/events?tenantId=${encodeURIComponent(contextIdRef.current)}`

    const ws = new WebSocket(wsUrl)
    backendWsRef.current = ws

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.eventType === "remote_agent_activity" && isProcessingRef.current) {
          const agentName = data.agentName || data.data?.agentName || ""
          if (agentName.toLowerCase().includes("host") || agentName.toLowerCase().includes("foundry-host")) return
          const friendly = agentName
            .replace(/^azurefoundry_/i, "")
            .replace(/^AI Foundry /i, "")
            .replace(/_/g, " ")
            .replace(/ Agent$/i, "")
          if (friendly) {
            setCurrentAgent(friendly)
            const activity = data.activityType || data.data?.activityType || ""
            const content = data.content || data.data?.content || ""

            if (!announcedAgentsRef.current.has(friendly.toLowerCase())) {
              announcedAgentsRef.current.add(friendly.toLowerCase())
              const workingOn =
                content.match(/Working on:\s*(.{10,80})/i)?.[1] ||
                content.match(/^Starting task:\s*(.{10,80})/i)?.[1]
              if (workingOn) {
                speakFillerViaAzure(`Contacting the ${friendly} agent. Working on: ${workingOn}`)
              } else {
                speakFillerViaAzure(`Contacting the ${friendly} agent.`)
              }
            } else if (activity === "agent_complete") {
              speakFillerViaAzure(`${friendly} agent is done.`)
            }
          }
        }
      } catch {}
    }
  }, [config.apiUrl, speakFillerViaAzure])

  const disconnectBackendWs = useCallback(() => {
    if (backendWsRef.current) {
      backendWsRef.current.close()
      backendWsRef.current = null
    }
  }, [])

  // ── Backend query execution ───────────────────────────────────────────

  const executeQuery = useCallback(
    async (query: string): Promise<string> => {
      try {
        const token = typeof window !== "undefined" ? localStorage.getItem("auth_token") : null
        const headers: HeadersInit = { "Content-Type": "application/json" }
        let userId: string | null = null
        if (token) {
          headers["Authorization"] = `Bearer ${token}`
          try {
            userId = JSON.parse(atob(token.split(".")[1])).user_id
          } catch {}
        }
        if (!userId) throw new Error("Not authenticated")

        const ctx = contextIdRef.current
        const sess = sessionIdRef.current
        let convId = ctx
        if (ctx.includes("::")) convId = ctx.split("::")[1]

        let activatedWorkflowIds: string[] | undefined
        try {
          const stored = typeof window !== "undefined" ? localStorage.getItem("a2a_activated_workflows") : null
          if (stored) {
            const parsed = JSON.parse(stored)
            if (Array.isArray(parsed) && parsed.length > 0) activatedWorkflowIds = parsed
          }
        } catch {}

        const body: Record<string, unknown> = {
          query,
          user_id: userId,
          session_id: sess,
          conversation_id: convId,
          timeout: 600,
          enable_routing: true,
        }
        if (activatedWorkflowIds?.length) body.activated_workflow_ids = activatedWorkflowIds

        const res = await fetch(`${config.apiUrl}/api/query`, {
          method: "POST",
          headers,
          body: JSON.stringify(body),
        })
        if (!res.ok) {
          let detail = res.statusText
          try {
            const d = await res.json()
            detail = d.detail || d.message || d.error || detail
          } catch {}
          throw new Error(detail)
        }
        const data = await res.json()
        return data.result || "Task completed."
      } catch (err: any) {
        return `Sorry, error: ${err.message || "Query failed"}`
      }
    },
    [config.apiUrl]
  )

  // ── Data channel message handler ──────────────────────────────────────

  const handleMessage = useCallback(
    async (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data)
        switch (msg.type) {
          case "session.created":
          case "session.updated":
            setIsListening(true)
            if (msg.type === "session.created") {
              // Send greeting
              sendEvent({
                type: "response.create",
                response: {
                  modalities: ["audio", "text"],
                  instructions:
                    "Say a brief, warm greeting like: 'Hey there! How can I help you today?' Keep it natural, just 1 sentence.",
                },
              })
              autoActivateRef.current = true
              // Fallback: auto-activate mic after 3s if greeting hasn't finished
              setTimeout(() => {
                if (autoActivateRef.current) {
                  autoActivateRef.current = false
                  sendEvent({ type: "input_audio_buffer.clear" })
                  setMicEnabled(true)
                  isTalkingRef.current = true
                  setIsTalking(true)
                }
              }, 3000)
            }
            break

          case "input_audio_buffer.speech_stopped":
            if (isTalkingRef.current) {
              isTalkingRef.current = false
              setIsTalking(false)
              setMicEnabled(false) // Mute mic when user stops talking
            }
            break

          case "conversation.item.input_audio_transcription.completed":
            setTranscript(msg.transcript || "")
            config.onTranscript?.(msg.transcript || "", true)
            break

          case "response.created":
            setIsListening(false)
            setMicEnabled(false) // Mute mic when AI starts responding
            break

          case "response.function_call_arguments.done":
            if (msg.name === "execute_query" && pendingCallRef.current) {
              const callId = pendingCallRef.current.call_id
              pendingCallRef.current = null
              setIsProcessing(true)
              isProcessingRef.current = true
              setIsVoiceProcessing(true)
              isResponseActiveRef.current = false
              announcedAgentsRef.current.clear()
              try {
                const args = JSON.parse(msg.arguments || "{}")
                const queryResult = await executeQuery(args.query || transcript)
                setResult(queryResult)
                config.onResult?.(queryResult)
                if (dcRef.current?.readyState === "open") {
                  // Cancel any filler speech before sending result
                  if (isResponseActiveRef.current) {
                    sendEvent({ type: "response.cancel" })
                    isResponseActiveRef.current = false
                  }
                  sendEvent({
                    type: "conversation.item.create",
                    item: { type: "function_call_output", call_id: callId, output: queryResult },
                  })
                  sendEvent({ type: "response.create" })
                }
              } finally {
                setIsProcessing(false)
                isProcessingRef.current = false
                setIsVoiceProcessing(false)
                setCurrentAgent(null)
              }
            }
            break

          case "conversation.item.created":
            if (msg.item?.type === "function_call") {
              pendingCallRef.current = { call_id: msg.item.call_id, item_id: msg.item.id }
            }
            break

          // WebRTC-specific: audio buffer coordination events
          case "output_audio_buffer.started":
            setIsSpeaking(true)
            setMicEnabled(false) // Extra safety: mute mic during AI audio output
            break

          case "output_audio_buffer.stopped":
            setIsSpeaking(false)
            setIsListening(true)
            break

          case "response.done":
            isResponseActiveRef.current = false
            setIsSpeaking(false)
            setIsListening(true)
            // Auto-activate mic after greeting finishes
            if (autoActivateRef.current) {
              autoActivateRef.current = false
              sendEvent({ type: "input_audio_buffer.clear" })
              setMicEnabled(true)
              isTalkingRef.current = true
              setIsTalking(true)
            }
            break

          case "error":
            isResponseActiveRef.current = false
            console.error("[voice-rtc] Server error:", msg.error)
            setError(msg.error?.message || "Unknown error")
            config.onError?.(msg.error?.message || "Unknown error")
            break
        }
      } catch {}
    },
    [config, transcript, executeQuery, sendEvent, setMicEnabled]
  )

  // ── Playback control ──────────────────────────────────────────────────

  const cancelPlayback = useCallback(() => {
    // Mute remote audio briefly to cut off current speech
    if (remoteAudioRef.current) {
      remoteAudioRef.current.volume = 0
      setTimeout(() => {
        if (remoteAudioRef.current) remoteAudioRef.current.volume = 1
      }, 500)
    }
    setIsSpeaking(false)
  }, [])

  // ── Talk controls ─────────────────────────────────────────────────────

  const startTalking = useCallback(() => {
    if (dcRef.current?.readyState !== "open") return
    // Interrupt AI if it's speaking
    if (isResponseActiveRef.current) {
      cancelPlayback()
      sendEvent({ type: "response.cancel" })
      isResponseActiveRef.current = false
    }
    sendEvent({ type: "input_audio_buffer.clear" })
    setMicEnabled(true)
    isTalkingRef.current = true
    setIsTalking(true)
  }, [cancelPlayback, sendEvent, setMicEnabled])

  const stopTalking = useCallback(
    (options?: { interruptMode?: boolean }) => {
      if (!isTalkingRef.current) return
      isTalkingRef.current = false
      setIsTalking(false)
      setMicEnabled(false)
      if (dcRef.current?.readyState === "open") {
        sendEvent({ type: "input_audio_buffer.commit" })
        if (!options?.interruptMode) sendEvent({ type: "response.create" })
      }
    },
    [sendEvent, setMicEnabled]
  )

  // ── Connection lifecycle ──────────────────────────────────────────────

  const startConversation = useCallback(async () => {
    try {
      setError(null)
      setTranscript("")
      setResult("")

      // 1. Get microphone with mobile-optimized constraints
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
      streamRef.current = stream
      const audioTrack = stream.getAudioTracks()[0]
      localTrackRef.current = audioTrack
      audioTrack.enabled = false // Start muted until greeting finishes

      // 2. Create RTCPeerConnection
      const pc = new RTCPeerConnection()
      pcRef.current = pc

      // 3. Setup remote audio playback via <audio> element
      const audioEl = document.createElement("audio")
      audioEl.autoplay = true
      remoteAudioRef.current = audioEl

      pc.ontrack = (event) => {
        if (event.streams.length > 0) {
          audioEl.srcObject = event.streams[0]
        }
      }

      // 4. Add local audio track to peer connection
      pc.addTrack(audioTrack, stream)

      // 5. Create data channel for JSON messaging
      const dc = pc.createDataChannel("oai-events")
      dcRef.current = dc

      dc.onopen = () => {
        setIsConnected(true)
        // Send session configuration
        dc.send(
          JSON.stringify({
            type: "session.update",
            session: {
              instructions:
                "You are a voice-only dispatcher. You cannot answer questions. Your ONLY capability is calling execute_query.\n\nFor EVERY user message, call execute_query with their exact words. No exceptions.\nAfter receiving the result, summarize it briefly and conversationally.\nMatch the user's language. Keep responses short. Do not read technical details verbatim.\nNEVER respond without calling execute_query first. You have zero knowledge of your own.",
              modalities: ["text", "audio"],
              turn_detection: { type: "semantic_vad", eagerness: "low" },
              input_audio_transcription: { model: "whisper-1" },
              voice: "alloy",
              temperature: 0.5,
              tools: [
                {
                  type: "function",
                  name: "execute_query",
                  description:
                    "REQUIRED for every user message. Send the user's request to the agent network. Pass their words EXACTLY as spoken — do NOT rephrase, summarize, or interpret.",
                  parameters: {
                    type: "object",
                    strict: true,
                    properties: {
                      query: {
                        type: "string",
                        description: "The user's EXACT words, copied verbatim from their transcript.",
                      },
                    },
                    required: ["query"],
                    additionalProperties: false,
                  },
                },
              ],
              tool_choice: "auto",
            },
          })
        )
        connectBackendWebSocket()
      }

      dc.onmessage = handleMessage

      dc.onclose = () => {
        setIsConnected(false)
        setIsListening(false)
      }

      // 6. Monitor peer connection state
      pc.onconnectionstatechange = () => {
        const state = pc.connectionState
        if (state === "failed" || state === "disconnected") {
          setError("Voice connection lost")
          setIsConnected(false)
          setIsListening(false)
        }
      }

      // 7. Create SDP offer and exchange via server-side proxy
      const offer = await pc.createOffer()
      await pc.setLocalDescription(offer)

      const response = await fetch("/api/rtc-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sdp: offer.sdp }),
      })

      if (!response.ok) {
        const err = await response.json()
        throw new Error(err.detail || err.error || "SDP exchange failed")
      }

      const { sdp: answerSdp } = await response.json()
      await pc.setRemoteDescription({ type: "answer", sdp: answerSdp })
    } catch (err: any) {
      console.error("[voice-rtc] Start failed:", err)
      setError(err.message || "Failed to start voice")
    }
  }, [handleMessage, connectBackendWebSocket])

  const stopConversation = useCallback(() => {
    // Close data channel and peer connection
    dcRef.current?.close()
    dcRef.current = null
    pcRef.current?.close()
    pcRef.current = null

    // Stop mic tracks
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    localTrackRef.current = null

    // Clean up remote audio element
    if (remoteAudioRef.current) {
      remoteAudioRef.current.srcObject = null
      remoteAudioRef.current = null
    }

    // Disconnect backend WebSocket
    disconnectBackendWs()

    // Reset all state
    pendingCallRef.current = null
    isProcessingRef.current = false
    isTalkingRef.current = false
    isResponseActiveRef.current = false
    autoActivateRef.current = false
    announcedAgentsRef.current.clear()
    setIsConnected(false)
    setIsListening(false)
    setIsSpeaking(false)
    setIsProcessing(false)
    setIsTalking(false)
    setIsVoiceProcessing(false)
    setCurrentAgent(null)
  }, [disconnectBackendWs])

  return {
    isConnected,
    isListening,
    isSpeaking,
    isProcessing,
    isTalking,
    isVoiceProcessing,
    currentAgent,
    transcript,
    result,
    error,
    startConversation,
    stopConversation,
    startTalking,
    stopTalking,
    updateContextId,
  }
}
