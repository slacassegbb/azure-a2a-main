"use client"

import { useCallback, useEffect, useRef, useState } from 'react'
import { VoiceScenario } from '@/lib/voice-scenarios'
import { VOICE_CONFIG } from '@/lib/voice-config'
import { VoiceStateMachine, VoiceState, createVoiceStateMachine } from '@/lib/voice-state-machine'

interface VoiceLiveConfig {
  foundryProjectUrl: string
  model?: string
  agentId?: string
  projectId?: string
  scenario?: VoiceScenario
  onToolCall?: (toolName: string, args: any) => void
  onSendToA2A?: (message: string, claimData?: any) => Promise<string>
}

interface VoiceLiveHook {
  isConnected: boolean
  isRecording: boolean
  isSpeaking: boolean
  isMuted: boolean
  startVoiceConversation: () => Promise<void>
  stopVoiceConversation: () => void
  toggleMute: () => void
  injectNetworkResponse: (response: any) => void
  error: string | null
}

export function useVoiceLive(config: VoiceLiveConfig): VoiceLiveHook {
  // State machine for voice lifecycle (replaces scattered boolean flags)
  const stateMachineRef = useRef<VoiceStateMachine>(createVoiceStateMachine())
  
  // Exposed state (derived from state machine)
  const [isConnected, setIsConnected] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Reconnection state
  const reconnectAttemptsRef = useRef(0)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const maxReconnectAttempts = 3
  const reconnectDelay = 3000 // 3 seconds
  const isReconnectingRef = useRef(false)
  const manualDisconnectRef = useRef(false)

  const wsRef = useRef<WebSocket | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const recordingContextRef = useRef<AudioContext | null>(null)
  const playbackContextRef = useRef<AudioContext | null>(null)
  const audioProcessorRef = useRef<ScriptProcessorNode | null>(null)
  const audioStreamRef = useRef<MediaStream | null>(null)
  const audioQueueRef = useRef<ArrayBuffer[]>([])
  const isPlayingRef = useRef(false)
  const nextStartTimeRef = useRef(0)
  const currentSourcesRef = useRef<AudioBufferSourceNode[]>([])
  const pendingCallIdRef = useRef<string | null>(null)
  const isRecordingRef = useRef(false)
  const isMutedRef = useRef(false)
  const [isMuted, setIsMuted] = useState(false)
  
  // Barge-in detection
  const analyserRef = useRef<AnalyserNode | null>(null)
  const bargeInCheckIntervalRef = useRef<NodeJS.Timeout | null>(null)
  
  // Track if we've sent the initial greeting (only once per session)
  const hasGreetedRef = useRef(false)

  // Response lifecycle tracking (following Python SDK pattern)
  const activeResponseRef = useRef(false)
  const responseDoneRef = useRef(false)
  
  // Conversation state tracking for proper truncation (Voice Live API best practice)
  const currentAssistantItemRef = useRef<{
    item_id: string
    response_id: string
    audio_start_time: number
  } | null>(null)
  const audioPlaybackTimeRef = useRef(0) // Track current playback position in milliseconds
  
  // Track MULTIPLE pending function calls by call_id (fixes issue where 2nd call overwrites 1st)
  const pendingFunctionCallsRef = useRef<Map<string, {
    name: string
    call_id: string
    previous_item_id?: string
    arguments?: string
  }>>(new Map())
  
  // Track multiple async A2A operations by call_id (for later injection)
  const pendingA2ACallsRef = useRef<Map<string, {
    previous_item_id?: string
    timestamp?: number  // For timeout cleanup
  }>>(new Map())

  // Sync state machine with exposed state variables
  useEffect(() => {
    const stateMachine = stateMachineRef.current
    
    // Subscribe to state changes
    const unsubscribe = stateMachine.subscribe((newState, prevState) => {
      console.log(`[VoiceState] ${prevState} → ${newState}`)
      
      // Update exposed state based on state machine
      setIsConnected(stateMachine.isConnected())
      setIsRecording(stateMachine.isRecording())
      setIsSpeaking(stateMachine.isSpeaking())
      
      // Clear error when leaving error state
      if (prevState === VoiceState.ERROR && newState !== VoiceState.ERROR) {
        setError(null)
      }
    })
    
    return unsubscribe
  }, [])

  // Get authentication token from backend
  const getAuthToken = async (): Promise<string> => {
    try {
      // Use the configured backend URL (works for both localhost and deployed)
      const backendUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
      const response = await fetch(`${backendUrl}/api/azure-token`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
      })
      
      if (!response.ok) {
        throw new Error('Failed to get Azure token from backend')
      }
      
      const data = await response.json()
      return data.token
    } catch (err: any) {
      console.error('[VoiceLive] Token fetch error:', err)
      throw new Error('Failed to get authentication token. Please run: az login')
    }
  }

  // Initialize WebSocket connection
  const initializeWebSocket = async () => {
    try {
      // Update state machine
      stateMachineRef.current.transitionTo(VoiceState.CONNECTING)
      
      const token = await getAuthToken()
      
      // Extract resource name from project URL
      const resourceName = config.foundryProjectUrl.match(/https:\/\/([^.]+)/)?.[1]
      if (!resourceName) {
        throw new Error('Invalid Foundry project URL')
      }

      // Build WebSocket URL with api-key authentication
      let wsUrl = `wss://${resourceName}.services.ai.azure.com/voice-live/realtime?api-version=2025-10-01&api-key=${token}`
      
      if (config.model) {
        wsUrl += `&model=${config.model}`
      }
      if (config.agentId && config.projectId) {
        wsUrl += `&agent_id=${config.agentId}&project_id=${config.projectId}`
      }

      console.log('[VoiceLive] Connecting to:', wsUrl.replace(token, '***'))

      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        console.log('[VoiceLive] ✅ WebSocket CONNECTED')
        console.log('[VoiceLive] WebSocket URL:', wsUrl.replace(token, '***'))
        
        // Update state machine
        stateMachineRef.current.transitionTo(VoiceState.CONNECTED)
        setError(null)

        // Send session configuration per Voice live API documentation
        console.log('[VoiceLive] 📤 Preparing session.update message...')
        const sessionConfig: any = {
          type: 'session.update',
          session: {
            instructions: config.scenario?.instructions || VOICE_CONFIG.DEFAULT_INSTRUCTIONS,
            modalities: ['text', 'audio'],
            // Voice live API enhanced turn detection
            turn_detection: {
              type: VOICE_CONFIG.TURN_DETECTION.TYPE,
              threshold: VOICE_CONFIG.TURN_DETECTION.THRESHOLD,
              prefix_padding_ms: VOICE_CONFIG.TURN_DETECTION.PREFIX_PADDING_MS,
              silence_duration_ms: VOICE_CONFIG.TURN_DETECTION.SILENCE_DURATION_MS,
              remove_filler_words: VOICE_CONFIG.TURN_DETECTION.REMOVE_FILLER_WORDS,
              interrupt_response: VOICE_CONFIG.TURN_DETECTION.INTERRUPT_RESPONSE,
              create_response: VOICE_CONFIG.TURN_DETECTION.CREATE_RESPONSE
            },
            input_audio_format: VOICE_CONFIG.AUDIO.INPUT_FORMAT,
            output_audio_format: VOICE_CONFIG.AUDIO.OUTPUT_FORMAT,
            input_audio_sampling_rate: VOICE_CONFIG.AUDIO.SAMPLE_RATE,
            input_audio_noise_reduction: {
              type: VOICE_CONFIG.AUDIO_PROCESSING.NOISE_REDUCTION_TYPE
            },
            input_audio_echo_cancellation: {
              type: VOICE_CONFIG.AUDIO_PROCESSING.ECHO_CANCELLATION_TYPE
            },
            input_audio_transcription: {
              model: VOICE_CONFIG.TRANSCRIPTION.MODEL,
              ...(VOICE_CONFIG.TRANSCRIPTION.LANGUAGE && { language: VOICE_CONFIG.TRANSCRIPTION.LANGUAGE }),
              ...(VOICE_CONFIG.TRANSCRIPTION.PROMPT && { prompt: VOICE_CONFIG.TRANSCRIPTION.PROMPT })
            },
            voice: {
              name: VOICE_CONFIG.VOICE.NAME,
              type: VOICE_CONFIG.VOICE.TYPE,
              temperature: VOICE_CONFIG.VOICE.TEMPERATURE
            },
            temperature: VOICE_CONFIG.MODEL_TEMPERATURE
          }
        }

        // Add tools if scenario has them
        if (config.scenario?.tools && config.scenario.tools.length > 0) {
          sessionConfig.session.tools = config.scenario.tools
          sessionConfig.session.tool_choice = 'auto'
          console.log('[VoiceLive] Configuring tools:', config.scenario.tools.map((t: { name: string }) => t.name))
        }

        console.log('[VoiceLive] 📤 SENDING session.update:', JSON.stringify(sessionConfig, null, 2))
        ws.send(JSON.stringify(sessionConfig))
        console.log('[VoiceLive] ✅ session.update sent successfully')
        
        // GREETING DISABLED - Wait for user to speak first
        // Voice Live API will listen and respond when user starts talking
        console.log('[VoiceLive] ✅ Ready to listen - speak to start the conversation')
      }

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data)
          handleVoiceLiveEvent(message)
        } catch (err) {
          console.error('[VoiceLive] Error parsing message:', err)
        }
      }

      ws.onerror = (err) => {
        console.error('[VoiceLive] WebSocket error:', err)
        console.error('[VoiceLive] Error details:', JSON.stringify(err, null, 2))
        
        // Transition to error state
        try {
          stateMachineRef.current.transitionTo(VoiceState.ERROR)
        } catch {
          // Force transition if needed
          stateMachineRef.current.transitionTo(VoiceState.ERROR, true)
        }
        
        // Only set error if not reconnecting
        if (!isReconnectingRef.current) {
          setError('Voice connection error - attempting to reconnect...')
        }
      }

      ws.onclose = (event) => {
        console.log('[VoiceLive] WebSocket closed', {
          code: event.code,
          reason: event.reason,
          wasClean: event.wasClean
        })
        
        // Transition to disconnected state
        try {
          stateMachineRef.current.transitionTo(VoiceState.DISCONNECTED)
        } catch {
          stateMachineRef.current.transitionTo(VoiceState.DISCONNECTED, true)
        }
        
        // Attempt reconnection if not manually disconnected
        if (!manualDisconnectRef.current && reconnectAttemptsRef.current < maxReconnectAttempts) {
          attemptReconnect()
        } else if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
          setError('Voice connection lost - max reconnection attempts reached')
        }
      }
    } catch (err: any) {
      console.error('[VoiceLive] Initialization error:', err)
      setError(err.message || 'Failed to initialize voice connection')
      setIsConnected(false)
    }
  }

  // Handle Voice Live API events
  const handleVoiceLiveEvent = async (event: any) => {
    console.log('[VoiceLive] ===== EVENT RECEIVED =====')
    console.log('[VoiceLive] Event Type:', event.type)
    console.log('[VoiceLive] Full Event:', JSON.stringify(event, null, 2))
    console.log('[VoiceLive] ===========================')

    switch (event.type) {
      case 'session.created':
      case 'session.updated':
        console.log('[VoiceLive] Session ready, full session config:', JSON.stringify(event.session, null, 2))
        break

      case 'response.audio.delta':
        // Queue audio chunk for playback
        if (event.delta) {
          const audioData = base64ToArrayBuffer(event.delta)
          audioQueueRef.current.push(audioData)
          // console.log('[VoiceLive] 🔊 Audio chunk received. Queue length:', audioQueueRef.current.length, 'Playing:', isPlayingRef.current)
          
          // Production-grade buffering strategy:
          // - First time: wait for initial buffer for smooth start
          // - After that: process every chunk immediately for low latency
          if (!isPlayingRef.current && audioQueueRef.current.length >= VOICE_CONFIG.INITIAL_AUDIO_BUFFER_SIZE) {
            console.log('[VoiceLive] 🎵 Starting playback (buffered', VOICE_CONFIG.INITIAL_AUDIO_BUFFER_SIZE, 'chunks)')
            playAudioQueue()
          } else if (isPlayingRef.current) {
            // Already playing, process new chunk immediately
            processAudioChunk()
          }
        }
        break

      case 'response.audio.done':
        console.log('[VoiceLive] ✅ Audio response complete - total chunks received')
        // Don't stop speaking immediately - let the queue finish
        break

      case 'conversation.item.input_audio_transcription.completed':
        console.log('[VoiceLive] Transcription:', event.transcript)
        break

      case 'conversation.item.created':
        console.log('[VoiceLive] 📦 conversation.item.created:', {
          type: event.item?.type,
          id: event.item?.id,
          name: event.item?.name,
          call_id: event.item?.call_id
        })
        
        // Python pattern: Store function call info when item is created
        if (event.item?.type === 'function_call') {
          console.log('[VoiceLive] ✅ FUNCTION CALL DETECTED:', event.item.name)
          console.log('[VoiceLive] 🔑 call_id:', event.item.call_id)
          console.log('[VoiceLive] 🆔 item.id (will be previous_item_id):', event.item.id)
          
          // Store in Map to support MULTIPLE function calls in one response
          pendingFunctionCallsRef.current.set(event.item.call_id, {
            name: event.item.name,
            call_id: event.item.call_id,
            previous_item_id: event.item.id // This ID will be used to insert output after this call
          })
          
          console.log('[VoiceLive] 📝 ✅ Stored in Map. Call ID:', event.item.call_id)
          console.log('[VoiceLive] 📊 Total pending function calls:', pendingFunctionCallsRef.current.size)
          console.log('[VoiceLive] ⏳ Waiting for arguments in response.function_call_arguments.done...')
        } else {
          console.log('[VoiceLive] ℹ️ Item created but not a function_call, type:', event.item?.type)
        }
        break
      
      case 'conversation.item.truncated':
        console.log('[VoiceLive] ✂️ conversation.item.truncated confirmed')
        console.log('[VoiceLive] Item ID:', event.item_id)
        console.log('[VoiceLive] Truncated at:', event.audio_end_ms, 'ms')
        console.log('[VoiceLive] ✅ Server understanding synchronized with client playback')
        break

      case 'input_audio_buffer.speech_started':
        console.log('[VoiceLive] ✅ SPEECH STARTED - User is speaking')
        break

      case 'input_audio_buffer.speech_stopped':
        console.log('[VoiceLive] ✅ SPEECH STOPPED - User finished speaking')
        console.log('[VoiceLive] Waiting for auto-commit from azure_semantic_vad...')
        break

      case 'input_audio_buffer.committed':
        console.log('[VoiceLive] ✅ AUDIO BUFFER COMMITTED')
        console.log('[VoiceLive] Response will be auto-created by azure_semantic_vad (create_response: true)')
        // Don't send response.create - the API auto-creates responses when create_response: true
        break

      case 'response.created':
        console.log('[VoiceLive] ✅✅✅ RESPONSE CREATED - AI is generating response ✅✅✅')
        console.log('[VoiceLive] Response ID:', event.response?.id)
        console.log('[VoiceLive] Response status:', event.response?.status)
        // Python pattern: Track active response
        activeResponseRef.current = true
        console.log('[VoiceLive] 📊 State: activeResponseRef = true, responseDoneRef = false')
        responseDoneRef.current = false
        break
      
      case 'response.output_item.added':
        // Track assistant message items for truncation support
        if (event.item?.type === 'message' && event.item?.role === 'assistant') {
          console.log('[VoiceLive] 📝 Tracking assistant item for truncation:', event.item.id)
          currentAssistantItemRef.current = {
            item_id: event.item.id,
            response_id: event.response_id,
            audio_start_time: Date.now()
          }
          audioPlaybackTimeRef.current = 0
        }
        break

      case 'response.function_call_arguments.done':
        console.log('[VoiceLive] 📋 response.function_call_arguments.done received')
        console.log('[VoiceLive] 🔑 Event call_id:', event.call_id)
        console.log('[VoiceLive] 📝 Arguments:', event.arguments)
        
        // Python pattern: Add arguments to pending function call in Map
        const pendingCall = pendingFunctionCallsRef.current.get(event.call_id)
        if (pendingCall) {
          console.log('[VoiceLive] ✅ MATCH! Adding arguments to pending function call:', event.call_id)
          pendingCall.arguments = event.arguments
          pendingFunctionCallsRef.current.set(event.call_id, pendingCall)
          console.log('[VoiceLive] ✅ Updated function call in Map')
          console.log('[VoiceLive] ⏳ Waiting for response.done to execute function...')
        } else {
          console.warn('[VoiceLive] ⚠️ NO MATCH! Call ID not found in Map:', event.call_id)
          console.warn('[VoiceLive] Available call IDs:', Array.from(pendingFunctionCallsRef.current.keys()))
        }
        break
      
      case 'response.output_item.done':
        // Python pattern: Don't handle function calls here - they're handled in response.done
        // This prevents duplicate execution
        if (event.item?.type === 'function_call') {
          console.log('[VoiceLive] � Function call output item done (will execute in response.done):', event.item.name)
        }
        break

      case 'response.done':
        console.log('[VoiceLive] ✅✅✅ RESPONSE.DONE - Response complete ✅✅✅')
        console.log('[VoiceLive] Response ID:', event.response?.id)
        console.log('[VoiceLive] Response status:', event.response?.status)
        
        // Python pattern: Mark response done and execute ALL pending functions
        activeResponseRef.current = false
        responseDoneRef.current = true
        console.log('[VoiceLive] 📊 State: activeResponseRef = false, responseDoneRef = true')
        
        // Execute ALL pending function calls (fixes 2nd function call issue!)
        console.log('[VoiceLive] 🔍 Checking for pending function calls...')
        console.log('[VoiceLive] 📊 Total pending function calls:', pendingFunctionCallsRef.current.size)
        console.log('[VoiceLive] 🔑 Call IDs:', Array.from(pendingFunctionCallsRef.current.keys()))
        
        if (pendingFunctionCallsRef.current.size > 0) {
          // Execute each function call that has arguments ready
          for (const [callId, functionCallInfo] of pendingFunctionCallsRef.current.entries()) {
            if (functionCallInfo.arguments) {
              console.log('[VoiceLive] ✅✅✅ EXECUTING FUNCTION CALL ✅✅✅')
              console.log('[VoiceLive] 🔧 Function name:', functionCallInfo.name)
              console.log('[VoiceLive] 🔑 call_id:', callId)
              console.log('[VoiceLive] 📝 Arguments:', functionCallInfo.arguments)
              console.log('[VoiceLive] 🆔 previous_item_id:', functionCallInfo.previous_item_id)
              
              await handleFunctionCall(functionCallInfo)
              console.log('[VoiceLive] ✅ Function call execution completed')
            } else {
              console.log('[VoiceLive] ⚠️ Function call missing arguments:', callId, functionCallInfo.name)
            }
          }
          
          // Clear all processed function calls
          pendingFunctionCallsRef.current.clear()
          console.log('[VoiceLive] 🗑️ Cleared all pending function calls')
        } else {
          console.log('[VoiceLive] ℹ️ No pending function calls to execute')
        }
        break

      case 'error':
        console.error('[VoiceLive] ❌ ERROR EVENT:', JSON.stringify(event, null, 2))
        setError(event.error?.message || 'Voice Live API error')
        break

      default:
        console.log('[VoiceLive] ℹ️ Unhandled event type:', event.type)
        break
    }
  }

  // Handle function call from Voice Live API (Python SDK pattern)
  const handleFunctionCall = async (functionCallInfo: {
    name: string
    call_id: string
    previous_item_id?: string
    arguments?: string
  }) => {
    console.log('[VoiceLive] ════════════════════════════════════════════════')
    console.log('[VoiceLive] 🔧 handleFunctionCall STARTED')
    console.log('[VoiceLive] ════════════════════════════════════════════════')
    
    const functionName = functionCallInfo.name
    const callId = functionCallInfo.call_id
    const previousItemId = functionCallInfo.previous_item_id
    const argsString = functionCallInfo.arguments

    console.log('[VoiceLive] Function details:', {
      functionName,
      callId,
      previousItemId,
      argsString: argsString?.substring(0, 100) + '...'
    })

    if (!argsString) {
      console.error('[VoiceLive] No arguments available for function call')
      return
    }

    let args: any = {}
    try {
      args = JSON.parse(argsString)
    } catch (err) {
      console.error('[VoiceLive] Failed to parse arguments:', argsString, err)
      return
    }

    console.log('[VoiceLive] Function:', functionName, 'Args:', args)

    // Notify parent component
    if (config.onToolCall) {
      config.onToolCall(functionName, args)
    }

    // Handle the universal send_to_agent_network tool
    if (functionName === 'send_to_agent_network') {
      console.log('[VoiceLive] ✅ Function is send_to_agent_network - processing...')
      console.log('[VoiceLive] 🔍 Step 1: About to check config')
      
      const hasCallback = typeof config.onSendToA2A === 'function'
      console.log('[VoiceLive] 🔍 Step 2: hasCallback =', hasCallback)
      
      try {
        const requestString = args.request
        console.log('[VoiceLive] � Step 3: Request string:', requestString?.substring(0, 100))
        
        console.log('[VoiceLive] 🔍 Step 4: About to enter if block, hasCallback =', hasCallback)
        if (hasCallback) {
          console.log('[VoiceLive] 🔍 Step 5: INSIDE IF BLOCK - This should appear!')
          console.log('[VoiceLive] ✅ config.onSendToA2A is available')
          
          // Store A2A call info by call_id for later injection (when real response arrives)
          console.log('[VoiceLive] ════════════════════════════════════════════════')
          console.log('[VoiceLive] 📝 STORING CALL INFO IN MAP')
          console.log('[VoiceLive] ════════════════════════════════════════════════')
          console.log('[VoiceLive] call_id:', callId)
          console.log('[VoiceLive] previous_item_id:', previousItemId)
          
          pendingA2ACallsRef.current.set(callId, {
            previous_item_id: previousItemId,
            timestamp: Date.now()  // Add timestamp for timeout cleanup
          })
          console.log('[VoiceLive] ✅ Stored in Map. Current Map size:', pendingA2ACallsRef.current.size)
          console.log('[VoiceLive] ✅ Map keys:', Array.from(pendingA2ACallsRef.current.keys()))
          
          pendingCallIdRef.current = callId
          console.log('[VoiceLive] ✅ Set pendingCallIdRef.current to:', callId)
          
          // DON'T send response.create here - let the initial response complete naturally
          // We'll send response.create when we inject the actual A2A result
          console.log('[VoiceLive] ℹ️ NOT sending response.create - letting initial response finish')
          
          // Send to A2A network (async - don't await, let it run in background)
          console.log('[VoiceLive] ════════════════════════════════════════════════')
          console.log('[VoiceLive] 🔄 SENDING TO A2A NETWORK (ASYNC)')
          console.log('[VoiceLive] ════════════════════════════════════════════════')
          console.log('[VoiceLive] Metadata: tool_call_id:', callId)
          
          if (config.onSendToA2A) {
            config.onSendToA2A(requestString, {
              tool_call_id: callId,
              request_type: 'voice_network_request'
            }).then((conversationId) => {
            console.log('[VoiceLive] ════════════════════════════════════════════════')
            console.log('[VoiceLive] ✅ A2A REQUEST SENT SUCCESSFULLY')
            console.log('[VoiceLive] ════════════════════════════════════════════════')
            console.log('[VoiceLive] Conversation ID:', conversationId)
            console.log('[VoiceLive] ⏳ Now waiting for dashboard to receive response and add to queue...')
          }).catch((err) => {
            console.log('[VoiceLive] ════════════════════════════════════════════════')
            console.error('[VoiceLive] ❌ A2A NETWORK ERROR')
            console.log('[VoiceLive] ════════════════════════════════════════════════')
            console.error('[VoiceLive] ❌ Network request error:', err)
            
            // Send error as function output
            const callInfo = pendingA2ACallsRef.current.get(callId)
            if (wsRef.current && callInfo) {
              const errorOutput = {
                type: 'conversation.item.create',
                previous_item_id: callInfo.previous_item_id,
                item: {
                  type: 'function_call_output',
                  call_id: callId,
                  output: JSON.stringify({
                    status: 'error',
                    message: 'Failed to contact agent network',
                    error: String(err)
                  })
                }
              }
              wsRef.current.send(JSON.stringify(errorOutput))
              wsRef.current.send(JSON.stringify({ type: 'response.create' }))
              
              pendingA2ACallsRef.current.delete(callId)
              pendingCallIdRef.current = null
            }
          })
          }
        }
      } catch (err) {
        console.error('[VoiceLive] ❌ Network request error:', err)
        
        // Send error as function output
        const errorOutput = {
          type: 'conversation.item.create',
          previous_item_id: previousItemId,
          item: {
            type: 'function_call_output',
            call_id: callId,
            output: JSON.stringify({
              status: 'error',
              message: 'Failed to contact agent network',
              error: String(err)
            })
          }
        }
        wsRef.current?.send(JSON.stringify(errorOutput))
        
        // Request response with error
        wsRef.current?.send(JSON.stringify({ type: 'response.create' }))
      }
    }
  }

  // Inject network response into conversation
  const injectNetworkResponse = useCallback((response: any) => {
    console.log('[VOICE-A2A] ════════════════════════════════════════════════')
    console.log('[VOICE-A2A] 💉 STEP 9: injectNetworkResponse CALLED')
    console.log('[VOICE-A2A] ════════════════════════════════════════════════')
    
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.warn('[VOICE-A2A] ❌ WebSocket not connected - readyState:', wsRef.current?.readyState)
      return
    }

    console.log('[VOICE-A2A] ✅ WebSocket connected')
    console.log('[VoiceLive] � Response object:', {
      call_id: response.call_id,
      message_preview: response.message?.substring(0, 100),
      claim_id: response.claim_id,
      status: response.status
    })

    // Lookup call info by call_id
    console.log('[VoiceLive] � Looking up call info in Map for call_id:', response.call_id)
    console.log('[VoiceLive] 📊 Current Map size:', pendingA2ACallsRef.current.size)
    console.log('[VoiceLive] 🔑 Map keys:', Array.from(pendingA2ACallsRef.current.keys()))
    
    const callInfo = pendingA2ACallsRef.current.get(response.call_id)
    if (!callInfo) {
      console.warn('[VoiceLive] ════════════════════════════════════════════════')
      console.warn('[VOICE-A2A] ❌ NO MATCHING call_id IN MAP')
      console.warn('[VOICE-A2A] Looking for:', response.call_id)
      console.warn('[VOICE-A2A] Available:', Array.from(pendingA2ACallsRef.current.keys()))
      return
    }

    console.log('[VoiceLive] ════════════════════════════════════════════════')
    console.log('[VOICE-A2A] ✅ STEP 10: Sending function_call_output to WebSocket')
    console.log('[VOICE-A2A] call_id:', response.call_id)
    console.log('[VOICE-A2A] previous_item_id:', callInfo.previous_item_id)

    // Python SDK pattern: Send the A2A response as function_call_output
    const functionOutput = {
      type: 'conversation.item.create',
      previous_item_id: callInfo.previous_item_id, // Insert after the function call
      item: {
        type: 'function_call_output',
        call_id: response.call_id,
        output: JSON.stringify({
          status: 'completed',
          message: response.message || response.response,
          claim_id: response.claim_id,
          timestamp: Date.now()
        })
      }
    }
    
    console.log('[VOICE-A2A] ════════════════════════════════════════════════')
    console.log('[VOICE-A2A] 📤 STEP 11: SENDING function_call_output')
    console.log('[VOICE-A2A] ════════════════════════════════════════════════')
    console.log('[VoiceLive] Full payload:', JSON.stringify(functionOutput, null, 2))
    
    wsRef.current.send(JSON.stringify(functionOutput))
    console.log('[VOICE-A2A] ✅ function_call_output SENT')
    
    // Python SDK pattern: Request new response to process the function result (ONLY ONCE)
    // Check if there's already an active response before sending response.create
    console.log('[VOICE-A2A] ════════════════════════════════════════════════')
    console.log('[VOICE-A2A] 📤 STEP 12: CHECKING response state before sending response.create')
    console.log('[VOICE-A2A] ════════════════════════════════════════════════')
    console.log('[VOICE-A2A] activeResponseRef:', activeResponseRef.current)
    console.log('[VOICE-A2A] responseDoneRef:', responseDoneRef.current)
    
    if (activeResponseRef.current) {
      console.log('[VOICE-A2A] ⚠️ SKIPPING response.create - response already active')
      console.log('[VOICE-A2A] Will wait for response.done before triggering new response')
    } else {
      console.log('[VOICE-A2A] ✅ Safe to send response.create')
      wsRef.current.send(JSON.stringify({ type: 'response.create' }))
      console.log('[VOICE-A2A] ✅ response.create SENT - AI should process result')
    }
    
    // Remove this call from pending map
    pendingA2ACallsRef.current.delete(response.call_id)
    console.log('[VoiceLive] 🗑️ Removed call_id from pending map:', response.call_id)
    console.log('[VoiceLive] 📊 Remaining pending calls:', pendingA2ACallsRef.current.size)
    console.log('[VoiceLive] ════════════════════════════════════════════════')
    console.log('[VoiceLive] 💉 injectNetworkResponse COMPLETED')
    console.log('[VoiceLive] ════════════════════════════════════════════════')
  }, [])

  // Convert base64 to ArrayBuffer
  const base64ToArrayBuffer = (base64: string): ArrayBuffer => {
    const binaryString = atob(base64)
    const bytes = new Uint8Array(binaryString.length)
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i)
    }
    return bytes.buffer
  }

  // Process a single audio chunk from the queue
  const processAudioChunk = () => {
    if (audioQueueRef.current.length === 0) return
    if (!playbackContextRef.current) return

    const audioContext = playbackContextRef.current
    const audioData = audioQueueRef.current.shift()
    if (!audioData) return

    try {
      // Convert PCM16 to AudioBuffer
      const pcm16 = new Int16Array(audioData)
      const audioBuffer = audioContext.createBuffer(1, pcm16.length, 24000)
      const channelData = audioBuffer.getChannelData(0)
      
      // Convert PCM16 to Float32 with proper normalization
      for (let j = 0; j < pcm16.length; j++) {
        channelData[j] = pcm16[j] / (pcm16[j] < 0 ? 0x8000 : 0x7FFF)
      }
      
      const source = audioContext.createBufferSource()
      source.buffer = audioBuffer
      source.connect(audioContext.destination)
      
      // Track sources for cleanup
      currentSourcesRef.current.push(source)
      
      // Handle source completion
      source.onended = () => {
        const index = currentSourcesRef.current.indexOf(source)
        if (index > -1) {
          currentSourcesRef.current.splice(index, 1)
        }
        
        // Check if we're done playing
        if (currentSourcesRef.current.length === 0 && audioQueueRef.current.length === 0) {
          isPlayingRef.current = false
          setIsSpeaking(false)
          nextStartTimeRef.current = 0
          stopBargeInDetection() // Stop monitoring when AI finishes speaking
          console.log('[VoiceLive] Playback complete')
        }
      }
      
      // Schedule with precise timing - catch up if we're behind
      const now = audioContext.currentTime
      const scheduleTime = Math.max(now, nextStartTimeRef.current)
      
      source.start(scheduleTime)
      nextStartTimeRef.current = scheduleTime + audioBuffer.duration
    } catch (err) {
      console.error('[VoiceLive] Audio playback error:', err)
    }
  }

  // Barge-in detection: Stop playback when user starts speaking
  const startBargeInDetection = () => {
    if (bargeInCheckIntervalRef.current || !analyserRef.current) {
      return // Already running or no analyser
    }

    // Wait before enabling barge-in to prevent accidental interruptions
    console.log('[VoiceLive] 👂 Starting barge-in detection in', VOICE_CONFIG.BARGE_IN_DELAY_MS, 'ms...')
    
    setTimeout(() => {
      if (!isPlayingRef.current) {
        console.log('[VoiceLive] ⏹️ Playback stopped before barge-in enabled')
        return
      }
      
      console.log('[VoiceLive] ✅ Barge-in detection now ACTIVE')
      const dataArray = new Uint8Array(analyserRef.current!.frequencyBinCount)

      bargeInCheckIntervalRef.current = setInterval(() => {
        if (!analyserRef.current || !isPlayingRef.current) {
          stopBargeInDetection()
          return
        }

        analyserRef.current.getByteTimeDomainData(dataArray)
        
        // Calculate RMS (root mean square) audio level
        let sum = 0
        for (let i = 0; i < dataArray.length; i++) {
          const normalized = (dataArray[i] - 128) / 128
          sum += normalized * normalized
        }
        const rms = Math.sqrt(sum / dataArray.length)

        // If user audio exceeds threshold, trigger barge-in
        if (rms > VOICE_CONFIG.BARGE_IN_THRESHOLD) {
          console.log('[VoiceLive] 🛑 BARGE-IN DETECTED! Audio level:', rms.toFixed(4))
          handleBargeIn()
        }
      }, VOICE_CONFIG.BARGE_IN_CHECK_INTERVAL_MS)
    }, VOICE_CONFIG.BARGE_IN_DELAY_MS)
  }

  const stopBargeInDetection = () => {
    if (bargeInCheckIntervalRef.current) {
      clearInterval(bargeInCheckIntervalRef.current)
      bargeInCheckIntervalRef.current = null
      console.log('[VoiceLive] ⏹️ Stopped barge-in detection')
    }
  }

  const handleBargeIn = () => {
    console.log('[VoiceLive] ════════════════════════════════════════════════')
    console.log('[VoiceLive] 🛑 HANDLING BARGE-IN - User interrupted AI')
    console.log('[VoiceLive] ════════════════════════════════════════════════')

    // Stop barge-in detection
    stopBargeInDetection()

    // Stop all audio playback immediately
    currentSourcesRef.current.forEach(source => {
      try {
        source.stop()
      } catch (e) {
        // Source may already be stopped
      }
    })
    currentSourcesRef.current = []
    audioQueueRef.current = [] // Clear remaining audio chunks
    
    isPlayingRef.current = false
    setIsSpeaking(false)
    console.log('[VoiceLive] ✅ Stopped AI audio playback')

    // Voice Live API best practice: Truncate conversation item to sync server understanding
    // The server produces audio faster than realtime, so this synchronizes what was actually played
    if (currentAssistantItemRef.current && wsRef.current?.readyState === WebSocket.OPEN) {
      const currentTime = Date.now()
      const audioElapsed = currentTime - currentAssistantItemRef.current.audio_start_time
      const audioEndMs = audioElapsed + VOICE_CONFIG.CONVERSATION_TRUNCATE.AUDIO_OFFSET_MS
      
      console.log('[VoiceLive] 📝 Sending conversation.item.truncate to sync server state')
      console.log('[VoiceLive] Item ID:', currentAssistantItemRef.current.item_id)
      console.log('[VoiceLive] Audio played:', audioElapsed, 'ms')
      console.log('[VoiceLive] Truncate at:', audioEndMs, 'ms (with', VOICE_CONFIG.CONVERSATION_TRUNCATE.AUDIO_OFFSET_MS, 'ms offset)')
      
      const truncateMessage = {
        type: 'conversation.item.truncate',
        item_id: currentAssistantItemRef.current.item_id,
        content_index: VOICE_CONFIG.CONVERSATION_TRUNCATE.CONTENT_INDEX,
        audio_end_ms: audioEndMs
      }
      
      wsRef.current.send(JSON.stringify(truncateMessage))
      console.log('[VoiceLive] ✅ Sent conversation.item.truncate')
      
      // Clear the tracked item after truncation
      currentAssistantItemRef.current = null
      audioPlaybackTimeRef.current = 0
    }

    // Cancel current AI response generation
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const cancelMessage = {
        type: 'response.cancel'
      }
      wsRef.current.send(JSON.stringify(cancelMessage))
      console.log('[VoiceLive] ✅ Sent response.cancel to stop AI generation')
    }

    // User audio is already being captured by the processor
    // The recording stream is still active, so user's speech will be sent
    console.log('[VoiceLive] ✅ User audio will continue to be captured')
    console.log('[VoiceLive] ════════════════════════════════════════════════')
  }

  // Production-grade audio playback - initialize and process buffered chunks
  const playAudioQueue = async () => {
    if (!playbackContextRef.current) {
      playbackContextRef.current = new AudioContext({ sampleRate: 24000 })
      await playbackContextRef.current.resume()
    }

    const audioContext = playbackContextRef.current
    
    // Initialize timing on first call
    if (!isPlayingRef.current) {
      isPlayingRef.current = true
      setIsSpeaking(true)
      // Start with a small buffer to reduce initial latency
      nextStartTimeRef.current = audioContext.currentTime + VOICE_CONFIG.PLAYBACK_BUFFER_SECONDS
      console.log('[VoiceLive] Starting playback at', nextStartTimeRef.current)
      
      // Start barge-in detection when AI starts speaking (with delay)
      startBargeInDetection()
    }

    // Process all available chunks immediately for smooth playback
    while (audioQueueRef.current.length > 0) {
      processAudioChunk()
    }
  }

  // Toggle mute without stopping recording or websocket
  const toggleMute = useCallback(() => {
    isMutedRef.current = !isMutedRef.current
    setIsMuted(isMutedRef.current)
    console.log('[VoiceLive] 🔇 Mute toggled:', isMutedRef.current ? 'MUTED' : 'UNMUTED')
  }, [])

  // Start recording audio
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          sampleRate: VOICE_CONFIG.MICROPHONE.SAMPLE_RATE,
          channelCount: VOICE_CONFIG.MICROPHONE.CHANNEL_COUNT,
          echoCancellation: VOICE_CONFIG.MICROPHONE.ECHO_CANCELLATION,
          noiseSuppression: VOICE_CONFIG.MICROPHONE.NOISE_SUPPRESSION
        } 
      })
      
      audioStreamRef.current = stream

      // Create AudioContext for PCM16 conversion
      const audioContext = new AudioContext({ sampleRate: VOICE_CONFIG.AUDIO.SAMPLE_RATE })
      const source = audioContext.createMediaStreamSource(stream)
      const processor = audioContext.createScriptProcessor(VOICE_CONFIG.PROCESSOR_BUFFER_SIZE, 1, 1)

      // Create analyser for barge-in detection
      const analyser = audioContext.createAnalyser()
      analyser.fftSize = VOICE_CONFIG.ANALYSER.FFT_SIZE
      analyser.smoothingTimeConstant = VOICE_CONFIG.ANALYSER.SMOOTHING_TIME_CONSTANT
      source.connect(analyser)
      analyserRef.current = analyser

      source.connect(processor)
      processor.connect(audioContext.destination)

      let audioChunkCount = 0
      processor.onaudioprocess = (e) => {
        // Send audio when connected, recording is active, AND not muted
        // IMPORTANT: Keep sending even when AI is speaking (isPlayingRef doesn't matter)
        // This allows barge-in detection and Azure Semantic VAD to work properly
        if (wsRef.current?.readyState === WebSocket.OPEN && isRecordingRef.current && !isMutedRef.current) {
          const inputData = e.inputBuffer.getChannelData(0)
          
          // Convert Float32 to PCM16
          const pcm16 = new Int16Array(inputData.length)
          for (let i = 0; i < inputData.length; i++) {
            const s = Math.max(-1, Math.min(1, inputData[i]))
            pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
          }
          
          // PCM16 is always even bytes (2 bytes per sample)
          const base64 = btoa(String.fromCharCode(...new Uint8Array(pcm16.buffer)))
          
          const message = {
            type: 'input_audio_buffer.append',
            audio: base64
          }
          
          wsRef.current.send(JSON.stringify(message))
          
          // Log periodically to avoid spam
          audioChunkCount++
          if (audioChunkCount % VOICE_CONFIG.AUDIO_LOG_INTERVAL === 0) {
            console.log('[VoiceLive] 🎤 Sent', audioChunkCount, 'audio chunks to server')
          }
        }
      }

      // Store references for cleanup
      recordingContextRef.current = audioContext
      audioProcessorRef.current = processor
      
      isRecordingRef.current = true
      setIsRecording(true)
      console.log('[VoiceLive] ✅ Recording STARTED -', VOICE_CONFIG.AUDIO.SAMPLE_RATE / 1000, 'kHz', VOICE_CONFIG.AUDIO.INPUT_FORMAT.toUpperCase(), 'conversion active')
      console.log('[VoiceLive] 🎤 Audio chunks will be sent to WebSocket')
      console.log('[VoiceLive] 🎤 isRecordingRef.current =', isRecordingRef.current)
    } catch (err: any) {
      console.error('[VoiceLive] ❌ Recording error:', err)
      setError(err.message || 'Failed to start recording')
    }
  }

  // Convert ArrayBuffer to base64
  const arrayBufferToBase64 = (buffer: ArrayBuffer): string => {
    const bytes = new Uint8Array(buffer)
    let binary = ''
    for (let i = 0; i < bytes.byteLength; i++) {
      binary += String.fromCharCode(bytes[i])
    }
    return btoa(binary)
  }

  // Stop recording
  const stopRecording = () => {
    isRecordingRef.current = false
    if (audioProcessorRef.current) {
      try {
        audioProcessorRef.current.disconnect()
        audioProcessorRef.current = null
      } catch (e) {
        // Already disconnected
      }
    }
    if (recordingContextRef.current) {
      try {
        recordingContextRef.current.close()
        recordingContextRef.current = null
      } catch (e) {
        // Already closed
      }
    }
    if (audioStreamRef.current) {
      audioStreamRef.current.getTracks().forEach(track => track.stop())
    }
    setIsRecording(false)
    console.log('[VoiceLive] Recording stopped')
  }

  // Attempt to reconnect after connection loss
  const attemptReconnect = useCallback(() => {
    if (isReconnectingRef.current) {
      console.log('[VoiceLive] Reconnection already in progress')
      return
    }
    
    isReconnectingRef.current = true
    reconnectAttemptsRef.current += 1
    
    console.log(`[VoiceLive] Attempting reconnection ${reconnectAttemptsRef.current}/${maxReconnectAttempts}...`)
    setError(`Reconnecting... (attempt ${reconnectAttemptsRef.current}/${maxReconnectAttempts})`)
    
    reconnectTimeoutRef.current = setTimeout(async () => {
      try {
        // Clean up old connection
        if (wsRef.current) {
          wsRef.current.onclose = null // Prevent triggering another reconnect
          wsRef.current.close()
          wsRef.current = null
        }
        
        // Try to reinitialize
        await initializeWebSocket()
        
        // If successful, reset counters
        reconnectAttemptsRef.current = 0
        isReconnectingRef.current = false
        setError(null)
        console.log('[VoiceLive] ✅ Reconnection successful')
        
        // Restart recording if it was active
        if (isRecordingRef.current) {
          console.log('[VoiceLive] Restarting recording after reconnection')
          await startRecording()
        }
      } catch (err) {
        isReconnectingRef.current = false
        console.error('[VoiceLive] Reconnection failed:', err)
        
        // Try again if we haven't hit max attempts
        if (reconnectAttemptsRef.current < maxReconnectAttempts) {
          attemptReconnect()
        } else {
          setError('Failed to reconnect - please refresh the page')
        }
      }
    }, reconnectDelay)
  }, [])

  // Start voice conversation
  const startVoiceConversation = useCallback(async () => {
    manualDisconnectRef.current = false
    reconnectAttemptsRef.current = 0
    
    if (!isConnected) {
      await initializeWebSocket()
      // Wait a bit for connection to establish
      await new Promise(resolve => setTimeout(resolve, 1000))
    }
    await startRecording()
  }, [isConnected])

  // Stop voice conversation
  const stopVoiceConversation = useCallback(() => {
    manualDisconnectRef.current = true // Mark as intentional disconnect
    
    // Clear any pending reconnection attempts
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    reconnectAttemptsRef.current = 0
    isReconnectingRef.current = false
    
    stopRecording()
    stopBargeInDetection() // Clean up barge-in monitoring
    
    // Stop all playing audio sources
    currentSourcesRef.current.forEach(source => {
      try {
        source.stop()
        source.disconnect()
      } catch (e) {
        // Already stopped
      }
    })
    currentSourcesRef.current = []
    
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    if (playbackContextRef.current) {
      playbackContextRef.current.close()
      playbackContextRef.current = null
    }
    setIsConnected(false)
    setIsSpeaking(false)
    setIsRecording(false)
    audioQueueRef.current = []
    isPlayingRef.current = false
    nextStartTimeRef.current = 0
  }, [])

  // Cleanup stale pending A2A calls
  useEffect(() => {
    const cleanupInterval = setInterval(() => {
      const now = Date.now()
      const staleCallIds: string[] = []
      
      // Find stale entries in pendingA2ACallsRef
      pendingA2ACallsRef.current.forEach((callData, call_id) => {
        const timestamp = (callData as any).timestamp || 0
        if (now - timestamp > VOICE_CONFIG.A2A_TIMEOUT_MS) {
          staleCallIds.push(call_id)
        }
      })
      
      // Clean up and send error responses for timed-out calls
      if (staleCallIds.length > 0) {
        console.log('[VoiceLive] Cleaning up', staleCallIds.length, 'timed-out A2A calls:', staleCallIds)
        
        staleCallIds.forEach(call_id => {
          const callData = pendingA2ACallsRef.current.get(call_id)
          
          // Send error function_call_output to Voice Live
          if (wsRef.current?.readyState === WebSocket.OPEN && callData?.previous_item_id) {
            console.log('[VoiceLive] Sending timeout error for call_id:', call_id)
            
            const errorOutput = {
              type: 'conversation.item.create',
              item: {
                type: 'function_call_output',
                call_id: call_id,
                output: JSON.stringify({
                  status: 'error',
                  message: `Request timed out after ${VOICE_CONFIG.A2A_TIMEOUT_MS / 1000} seconds`,
                  error: 'TIMEOUT'
                })
              }
            }
            
            wsRef.current.send(JSON.stringify(errorOutput))
            
            // Trigger response generation
            const responseCreate = { type: 'response.create' }
            wsRef.current.send(JSON.stringify(responseCreate))
          }
          
          // Remove from pending
          pendingA2ACallsRef.current.delete(call_id)
        })
      }
    }, VOICE_CONFIG.A2A_CLEANUP_INTERVAL_MS)
    
    return () => {
      clearInterval(cleanupInterval)
    }
  }, [])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      // Clear reconnection timer
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      
      // Stop everything
      stopVoiceConversation()
    }
  }, [])

  return {
    isConnected,
    isRecording,
    isSpeaking,
    isMuted,
    startVoiceConversation,
    stopVoiceConversation,
    toggleMute,
    injectNetworkResponse,
    error
  }
}
