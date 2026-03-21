"use client"

import { useCallback, useRef, useState, useEffect } from "react"
import { logDebug, logInfo, warnDebug } from "@/lib/debug"

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

function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const bin = atob(base64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return bytes.buffer
}

function floatTo16BitPCM(float32: Float32Array): Int16Array {
  const int16 = new Int16Array(float32.length)
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]))
    int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff
  }
  return int16
}

function downsampleBuffer(buffer: Float32Array, inputRate: number, outputRate: number): Float32Array {
  if (inputRate === outputRate) return buffer
  const ratio = inputRate / outputRate
  const newLen = Math.round(buffer.length / ratio)
  const result = new Float32Array(newLen)
  for (let i = 0; i < newLen; i++) {
    const next = Math.round((i + 1) * ratio)
    let accum = 0, count = 0
    for (let j = Math.round(i * ratio); j < next && j < buffer.length; j++) {
      accum += buffer[j]; count++
    }
    result[i] = accum / count
  }
  return result
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

  const isTalkingRef = useRef(false)
  const autoActivateRef = useRef(false)
  const wsRef = useRef<WebSocket | null>(null)
  const backendWsRef = useRef<WebSocket | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const playbackCtxRef = useRef<AudioContext | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const audioQueueRef = useRef<ArrayBuffer[]>([])
  const isPlayingRef = useRef(false)
  const nextStartRef = useRef(0)
  const pendingCallRef = useRef<{ call_id: string; item_id: string } | null>(null)
  const isProcessingRef = useRef(false)
  const isResponseActiveRef = useRef(false)
  const announcedAgentsRef = useRef<Set<string>>(new Set())
  const contextIdRef = useRef(config.contextId)
  const sessionIdRef = useRef(config.sessionId)
  const currentSourcesRef = useRef<AudioBufferSourceNode[]>([])

  useEffect(() => {
    contextIdRef.current = config.contextId
    sessionIdRef.current = config.sessionId
  }, [config.contextId, config.sessionId])

  const updateContextId = useCallback((newContextId: string) => {
    contextIdRef.current = newContextId
    if (newContextId.includes("::")) sessionIdRef.current = newContextId.split("::")[0]
  }, [])

  const getAzureToken = async (): Promise<string> => {
    const res = await fetch("/api/azure-token")
    if (!res.ok) throw new Error("Failed to get Azure token")
    const data = await res.json()
    return data.token
  }

  const speakFillerViaAzure = useCallback((text: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    if (isResponseActiveRef.current || !isProcessingRef.current) return
    isResponseActiveRef.current = true
    wsRef.current.send(JSON.stringify({
      type: "response.create",
      response: { modalities: ["audio", "text"], instructions: `Say exactly this in a brief, natural way: "${text}"` }
    }))
  }, [])

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
          const friendly = agentName.replace(/^azurefoundry_/i, "").replace(/^AI Foundry /i, "").replace(/_/g, " ").replace(/ Agent$/i, "")
          if (friendly) {
            setCurrentAgent(friendly)
            const activity = data.activityType || data.data?.activityType || ""
            const content = data.content || data.data?.content || ""

            if (!announcedAgentsRef.current.has(friendly.toLowerCase())) {
              announcedAgentsRef.current.add(friendly.toLowerCase())
              // Speak the task description if available, otherwise just announce the agent
              const workingOn = content.match(/Working on:\s*(.{10,80})/i)?.[1]
                || content.match(/^Starting task:\s*(.{10,80})/i)?.[1]
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
    if (backendWsRef.current) { backendWsRef.current.close(); backendWsRef.current = null }
  }, [])

  const executeQuery = useCallback(async (query: string): Promise<string> => {
    try {
      const token = typeof window !== "undefined" ? localStorage.getItem("auth_token") : null
      const headers: HeadersInit = { "Content-Type": "application/json" }
      let userId: string | null = null
      if (token) {
        headers["Authorization"] = `Bearer ${token}`
        try { userId = JSON.parse(atob(token.split(".")[1])).user_id } catch {}
      }
      if (!userId) throw new Error("Not authenticated")

      const ctx = contextIdRef.current
      const sess = sessionIdRef.current
      let convId = ctx
      if (ctx.includes("::")) convId = ctx.split("::")[1]

      // Get activated workflow IDs
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

      const res = await fetch(`${config.apiUrl}/api/query`, { method: "POST", headers, body: JSON.stringify(body) })
      if (!res.ok) {
        let detail = res.statusText
        try { const d = await res.json(); detail = d.detail || d.message || d.error || detail } catch {}
        throw new Error(detail)
      }
      const data = await res.json()
      return data.result || "Task completed."
    } catch (err: any) {
      return `Sorry, error: ${err.message || "Query failed"}`
    }
  }, [config.apiUrl])

  const processAudioChunk = useCallback(() => {
    if (!playbackCtxRef.current || !audioQueueRef.current.length) return
    const audioData = audioQueueRef.current.shift()
    if (!audioData) return
    try {
      const ctx = playbackCtxRef.current
      const int16 = new Int16Array(audioData)
      const float32 = new Float32Array(int16.length)
      for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768
      const buf = ctx.createBuffer(1, float32.length, 24000)
      buf.copyToChannel(float32, 0)
      const source = ctx.createBufferSource()
      source.buffer = buf
      source.connect(ctx.destination)
      currentSourcesRef.current.push(source)
      source.onended = () => {
        const idx = currentSourcesRef.current.indexOf(source)
        if (idx > -1) currentSourcesRef.current.splice(idx, 1)
        if (!currentSourcesRef.current.length && !audioQueueRef.current.length) {
          setTimeout(() => {
            isPlayingRef.current = false
            setIsSpeaking(false)
            if (autoActivateRef.current) {
              autoActivateRef.current = false
              if (wsRef.current?.readyState === WebSocket.OPEN)
                wsRef.current.send(JSON.stringify({ type: "input_audio_buffer.clear" }))
              isTalkingRef.current = true
              setIsTalking(true)
            }
          }, 300)
        }
      }
      const now = ctx.currentTime
      const t = Math.max(now, nextStartRef.current)
      source.start(t)
      nextStartRef.current = t + buf.duration
    } catch {}
  }, [])

  const playAudioQueue = useCallback(async () => {
    if (!playbackCtxRef.current) {
      playbackCtxRef.current = new AudioContext({ sampleRate: 24000 })
      await playbackCtxRef.current.resume()
    }
    if (!isPlayingRef.current) {
      isPlayingRef.current = true
      setIsSpeaking(true)
      nextStartRef.current = playbackCtxRef.current.currentTime + 0.05
    }
    while (audioQueueRef.current.length) processAudioChunk()
  }, [processAudioChunk])

  const handleMessage = useCallback(async (event: MessageEvent) => {
    try {
      const msg = JSON.parse(event.data)
      switch (msg.type) {
        case "session.created":
        case "session.updated":
          setIsListening(true)
          if (msg.type === "session.created" && wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({
              type: "response.create",
              response: { modalities: ["audio", "text"], instructions: "Say a brief, warm greeting like: 'Hey there! How can I help you today?' Keep it natural, just 1 sentence." }
            }))
            autoActivateRef.current = true
            setTimeout(() => {
              if (autoActivateRef.current) {
                autoActivateRef.current = false
                if (wsRef.current?.readyState === WebSocket.OPEN)
                  wsRef.current.send(JSON.stringify({ type: "input_audio_buffer.clear" }))
                isTalkingRef.current = true
                setIsTalking(true)
              }
            }, 3000)
          }
          break

        case "input_audio_buffer.speech_stopped":
          if (isTalkingRef.current) { isTalkingRef.current = false; setIsTalking(false) }
          break

        case "conversation.item.input_audio_transcription.completed":
          setTranscript(msg.transcript || "")
          config.onTranscript?.(msg.transcript || "", true)
          break

        case "response.created":
          setIsListening(false)
          break

        case "response.function_call_arguments.done":
          if (msg.name === "execute_query" && pendingCallRef.current) {
            const callId = pendingCallRef.current.call_id
            pendingCallRef.current = null
            setIsProcessing(true); isProcessingRef.current = true; setIsVoiceProcessing(true)
            isResponseActiveRef.current = false; announcedAgentsRef.current.clear()
            try {
              const args = JSON.parse(msg.arguments || "{}")
              const queryResult = await executeQuery(args.query || transcript)
              setResult(queryResult); config.onResult?.(queryResult)
              if (wsRef.current?.readyState === WebSocket.OPEN) {
                if (isResponseActiveRef.current) {
                  wsRef.current.send(JSON.stringify({ type: "response.cancel" }))
                  isResponseActiveRef.current = false
                }
                wsRef.current.send(JSON.stringify({
                  type: "conversation.item.create",
                  item: { type: "function_call_output", call_id: callId, output: queryResult }
                }))
                wsRef.current.send(JSON.stringify({ type: "response.create" }))
              }
            } finally {
              setIsProcessing(false); isProcessingRef.current = false; setIsVoiceProcessing(false); setCurrentAgent(null)
            }
          }
          break

        case "conversation.item.created":
          if (msg.item?.type === "function_call") {
            pendingCallRef.current = { call_id: msg.item.call_id, item_id: msg.item.id }
          }
          break

        case "response.audio.delta":
          if (msg.delta) {
            audioQueueRef.current.push(base64ToArrayBuffer(msg.delta))
            if (audioQueueRef.current.length >= 5 || isPlayingRef.current) playAudioQueue()
          }
          break

        case "response.audio.done":
          if (audioQueueRef.current.length) playAudioQueue()
          break

        case "response.done":
          isResponseActiveRef.current = false
          break

        case "error":
          isResponseActiveRef.current = false
          setError(msg.error?.message || "Unknown error")
          config.onError?.(msg.error?.message || "Unknown error")
          break
      }
    } catch {}
  }, [config, transcript, playAudioQueue, executeQuery])

  const startMicrophone = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, sampleRate: 24000 }
      })
      streamRef.current = stream
      audioCtxRef.current = new AudioContext({ sampleRate: 24000 })
      const source = audioCtxRef.current.createMediaStreamSource(stream)
      const processor = audioCtxRef.current.createScriptProcessor(4096, 1, 1)
      processorRef.current = processor

      processor.onaudioprocess = (e) => {
        if (wsRef.current?.readyState === WebSocket.OPEN && isTalkingRef.current && !isPlayingRef.current) {
          const input = e.inputBuffer.getChannelData(0)
          const ds = downsampleBuffer(input, audioCtxRef.current?.sampleRate || 44100, 24000)
          const pcm = floatTo16BitPCM(ds)
          const u8 = new Uint8Array(pcm.buffer)
          let bin = ""
          for (let i = 0; i < u8.length; i++) bin += String.fromCharCode(u8[i])
          wsRef.current.send(JSON.stringify({ type: "input_audio_buffer.append", audio: btoa(bin) }))
        }
      }
      source.connect(processor)
      processor.connect(audioCtxRef.current.destination)
    } catch {
      setError("Microphone access denied")
    }
  }, [])

  const stopMicrophone = useCallback(() => {
    processorRef.current?.disconnect(); processorRef.current = null
    audioCtxRef.current?.close(); audioCtxRef.current = null
    streamRef.current?.getTracks().forEach((t) => t.stop()); streamRef.current = null
  }, [])

  const cancelPlayback = useCallback(() => {
    audioQueueRef.current = []
    currentSourcesRef.current.forEach((s) => { try { s.stop() } catch {} })
    currentSourcesRef.current = []
    isPlayingRef.current = false; setIsSpeaking(false); nextStartRef.current = 0
  }, [])

  const startTalking = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    if (isPlayingRef.current) cancelPlayback()
    if (isResponseActiveRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "response.cancel" })); isResponseActiveRef.current = false
    }
    wsRef.current.send(JSON.stringify({ type: "input_audio_buffer.clear" }))
    isTalkingRef.current = true; setIsTalking(true)
  }, [cancelPlayback])

  const stopTalking = useCallback((options?: { interruptMode?: boolean }) => {
    if (!isTalkingRef.current) return
    isTalkingRef.current = false; setIsTalking(false)
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "input_audio_buffer.commit" }))
      if (!options?.interruptMode) wsRef.current.send(JSON.stringify({ type: "response.create" }))
    }
  }, [])

  const startConversation = useCallback(async () => {
    try {
      setError(null); setTranscript(""); setResult("")
      const token = await getAzureToken()
      const voiceHost = process.env.NEXT_PUBLIC_VOICE_HOST || ""
      const voiceDeploy = process.env.NEXT_PUBLIC_VOICE_DEPLOYMENT || "gpt-realtime"
      if (!voiceHost) throw new Error("NEXT_PUBLIC_VOICE_HOST not configured")

      const wsUrl = `wss://${voiceHost}/openai/realtime?api-version=2025-04-01-preview&deployment=${voiceDeploy}&api-key=${token}`
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws
      playbackCtxRef.current = new AudioContext({ sampleRate: 24000 })
      nextStartRef.current = 0

      ws.onopen = () => {
        setIsConnected(true)
        ws.send(JSON.stringify({
          type: "session.update",
          session: {
            instructions: `You are a voice interface to an AI agent network. You NEVER answer questions yourself. You ALWAYS delegate to the agent network by calling execute_query.\n\nCRITICAL RULES:\n1. NEVER answer a question directly. ALWAYS call execute_query first, no matter how simple the question seems.\n2. After receiving the function result, summarize it conversationally and briefly. Do NOT call execute_query again after receiving a result.\n3. Match the user's language - if they speak English, respond in English; if French, respond in French, etc.\n4. Keep your spoken responses brief and natural.\n5. Do not read long technical details - summarize them.\n6. You have NO knowledge of your own. Every user request must go through execute_query.`,
            modalities: ["text", "audio"],
            turn_detection: { type: "server_vad", threshold: 0.8, prefix_padding_ms: 300, silence_duration_ms: 600 },
            input_audio_format: "pcm16",
            output_audio_format: "pcm16",
            input_audio_transcription: { model: "whisper-1" },
            voice: "alloy",
            temperature: 0.6,
            tools: [{
              type: "function",
              name: "execute_query",
              description: "Send the user's request to the agent network for execution. IMPORTANT: Pass the user's words EXACTLY as they said them. Do NOT rephrase, summarize, or interpret. Copy their transcript verbatim.",
              parameters: { type: "object", properties: { query: { type: "string", description: "The user's EXACT words, copied verbatim from their transcript. Do not rephrase." } }, required: ["query"] }
            }],
            tool_choice: "auto",
          }
        }))
        startMicrophone()
        connectBackendWebSocket()
      }

      ws.onmessage = handleMessage
      ws.onerror = () => { setError("Connection error"); setIsConnected(false) }
      ws.onclose = (e) => {
        if (e.code === 1006) setError("Connection failed - check voice config")
        setIsConnected(false); setIsListening(false); stopMicrophone()
      }
    } catch (err: any) {
      setError(err.message || "Failed to start")
    }
  }, [handleMessage, startMicrophone, stopMicrophone, connectBackendWebSocket])

  const stopConversation = useCallback(() => {
    wsRef.current?.close(); wsRef.current = null
    disconnectBackendWs(); stopMicrophone()
    playbackCtxRef.current?.close(); playbackCtxRef.current = null
    audioQueueRef.current = []; isPlayingRef.current = false
    pendingCallRef.current = null; isProcessingRef.current = false; isTalkingRef.current = false
    setIsConnected(false); setIsListening(false); setIsSpeaking(false)
    setIsProcessing(false); setIsTalking(false); setIsVoiceProcessing(false); setCurrentAgent(null)
  }, [disconnectBackendWs, stopMicrophone])

  return {
    isConnected, isListening, isSpeaking, isProcessing, isTalking,
    isVoiceProcessing, currentAgent, transcript, result, error,
    startConversation, stopConversation, startTalking, stopTalking, updateContextId,
  }
}
