"use client"

import { useCallback, useEffect, useRef, useState } from 'react'
import { VoiceScenario } from '@/lib/voice-scenarios'

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
  const [isConnected, setIsConnected] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [isMuted, setIsMuted] = useState(false)
  const [error, setError] = useState<string | null>(null)

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

  // Response lifecycle tracking (following Python SDK pattern)
  const activeResponseRef = useRef(false)
  const responseDoneRef = useRef(false)
  const pendingFunctionCallRef = useRef<{
    name: string
    call_id: string
    previous_item_id?: string
    arguments?: string
  } | null>(null)
  
  // Track multiple async A2A operations by call_id (for later injection)
  const pendingA2ACallsRef = useRef<Map<string, {
    previous_item_id?: string
  }>>(new Map())

  // Get authentication token from Azure CLI
  const getAuthToken = async (): Promise<string> => {
    try {
      // Fetch token from Next.js API route (uses relative URL to work on any port)
      const response = await fetch('/api/azure-token', {
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
      const token = await getAuthToken()
      
      console.log('[VoiceLive] Foundry Project URL:', config.foundryProjectUrl)
      
      // Extract resource name from project URL
      const resourceName = config.foundryProjectUrl.match(/https:\/\/([^.]+)/)?.[1]
      if (!resourceName) {
        console.error('[VoiceLive] Failed to extract resource name from URL:', config.foundryProjectUrl)
        throw new Error(`Invalid Foundry project URL: ${config.foundryProjectUrl}. Expected format: https://[resource-name].services.ai.azure.com/...`)
      }
      
      console.log('[VoiceLive] Extracted resource name:', resourceName)

      // Build WebSocket URL with api-key authentication (exactly like template)
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
        setIsConnected(true)
        setError(null)

        // Send session configuration per Voice live API documentation
        console.log('[VoiceLive] 📤 Preparing session.update message...')
        const sessionConfig: any = {
          type: 'session.update',
          session: {
            instructions: config.scenario?.instructions || "You are a helpful Contoso customer service assistant.",
            modalities: ['text', 'audio'],
            // Voice live API enhanced turn detection
            turn_detection: {
              type: 'azure_semantic_vad',
              threshold: 0.3,
              prefix_padding_ms: 200,
              silence_duration_ms: 200,
              remove_filler_words: false
            },
            input_audio_format: 'pcm16',
            output_audio_format: 'pcm16',
            input_audio_sampling_rate: 24000,
            input_audio_noise_reduction: {
              type: 'azure_deep_noise_suppression'
            },
            input_audio_echo_cancellation: {
              type: 'server_echo_cancellation'
            },
            input_audio_transcription: {
              model: 'whisper-1'
            },
            voice: {
              name: 'en-US-Ava:DragonHDLatestNeural',
              type: 'azure-standard',
              temperature: 0.6
            },
            temperature: 0.6
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
      }

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data)
          handleVoiceLiveEvent(message)
        } catch (err) {
          console.error('[VoiceLive] Error parsing message:', err)
        }
      }

      ws.onerror = (err: any) => {
        console.error('[VoiceLive] ❌ WebSocket ERROR occurred')
        console.error('[VoiceLive] Error event:', err)
        console.error('[VoiceLive] Error type:', err.type)
        console.error('[VoiceLive] WebSocket readyState:', ws.readyState)
        console.error('[VoiceLive] WebSocket URL:', wsUrl.replace(token, '***TOKEN***'))
        setError('Voice connection error - check console for details')
      }

      ws.onclose = (event: CloseEvent) => {
        console.log('[VoiceLive] 🔌 WebSocket CLOSED')
        console.log('[VoiceLive] Close code:', event.code)
        console.log('[VoiceLive] Close reason:', event.reason || 'No reason provided')
        console.log('[VoiceLive] Was clean:', event.wasClean)
        
        if (event.code === 1006) {
          console.error('[VoiceLive] Connection failed - possibly invalid endpoint or authentication issue')
          setError(`Connection failed (code: ${event.code}). Check endpoint URL and authentication.`)
        } else if (event.code !== 1000) {
          console.error(`[VoiceLive] Abnormal closure: ${event.code} - ${event.reason}`)
          setError(`Connection closed: ${event.reason || event.code}`)
        }
        
        setIsConnected(false)
        setIsRecording(false)
        setIsSpeaking(false)
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
          // - First time: wait for 8 chunks for smooth start
          // - After that: process every chunk immediately for low latency
          if (!isPlayingRef.current && audioQueueRef.current.length >= 8) {
            console.log('[VoiceLive] 🎵 Starting playback (buffered 8 chunks)')
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
        console.log('[VoiceLive] ✅✅✅ USER SAID:', event.transcript)
        console.log('[VoiceLive] This should trigger the AI to respond or call a tool...')
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
          
          pendingFunctionCallRef.current = {
            name: event.item.name,
            call_id: event.item.call_id,
            previous_item_id: event.item.id // This ID will be used to insert output after this call
          }
          
          console.log('[VoiceLive] 📝 ✅ Stored in pendingFunctionCallRef.current:', JSON.stringify(pendingFunctionCallRef.current))
          console.log('[VoiceLive] ⏳ Waiting for arguments in response.function_call_arguments.done...')
        } else {
          console.log('[VoiceLive] ℹ️ Item created but not a function_call, type:', event.item?.type)
        }
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

      case 'response.function_call_arguments.done':
        console.log('[VoiceLive] 📋 response.function_call_arguments.done received')
        console.log('[VoiceLive] 🔑 Event call_id:', event.call_id)
        console.log('[VoiceLive] 📝 Arguments:', event.arguments)
        console.log('[VoiceLive] 🔍 Checking pendingFunctionCallRef.current:', JSON.stringify(pendingFunctionCallRef.current))
        
        // Python pattern: Add arguments to pending function call
        if (pendingFunctionCallRef.current && event.call_id === pendingFunctionCallRef.current.call_id) {
          console.log('[VoiceLive] ✅ MATCH! Adding arguments to pending function call')
          pendingFunctionCallRef.current.arguments = event.arguments
          console.log('[VoiceLive] ✅ Updated pendingFunctionCallRef.current:', JSON.stringify(pendingFunctionCallRef.current))
          console.log('[VoiceLive] ⏳ Waiting for response.done to execute function...')
        } else {
          console.warn('[VoiceLive] ⚠️ NO MATCH! Arguments not added.')
          console.warn('[VoiceLive] Expected call_id:', pendingFunctionCallRef.current?.call_id)
          console.warn('[VoiceLive] Received call_id:', event.call_id)
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
        
        // Python pattern: Mark response done and execute pending function
        activeResponseRef.current = false
        responseDoneRef.current = true
        console.log('[VoiceLive] 📊 State: activeResponseRef = false, responseDoneRef = true')
        
        // Execute pending function call if arguments are ready
        console.log('[VoiceLive] 🔍 Checking for pending function call...')
        console.log('[VoiceLive] pendingFunctionCallRef.current:', JSON.stringify(pendingFunctionCallRef.current))
        
        if (pendingFunctionCallRef.current && pendingFunctionCallRef.current.arguments) {
          console.log('[VoiceLive] ✅✅✅ EXECUTING FUNCTION CALL ✅✅✅')
          console.log('[VoiceLive] 🔧 Function name:', pendingFunctionCallRef.current.name)
          console.log('[VoiceLive] 🔑 call_id:', pendingFunctionCallRef.current.call_id)
          console.log('[VoiceLive] 📝 Arguments:', pendingFunctionCallRef.current.arguments)
          console.log('[VoiceLive] 🆔 previous_item_id:', pendingFunctionCallRef.current.previous_item_id)
          
          await handleFunctionCall(pendingFunctionCallRef.current)
          console.log('[VoiceLive] ✅ Function call execution completed')
          
          pendingFunctionCallRef.current = null
          console.log('[VoiceLive] 🗑️ Cleared pendingFunctionCallRef.current')
        } else {
          console.log('[VoiceLive] ℹ️ No pending function call to execute')
          if (pendingFunctionCallRef.current) {
            console.log('[VoiceLive] ⚠️ Function call exists but missing arguments:', pendingFunctionCallRef.current)
          }
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
            previous_item_id: previousItemId
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
    console.log('[VOICE-A2A] ✅ STEP 10: Determining injection strategy')
    console.log('[VOICE-A2A] call_id:', response.call_id)
    console.log('[VOICE-A2A] status:', response.status || 'completed')
    console.log('[VOICE-A2A] message:', response.message)
    console.log('[VOICE-A2A] previous_item_id:', callInfo.previous_item_id)
    console.log('[VOICE-A2A] activeResponseRef.current:', activeResponseRef.current)

    // Check if there's already an active response
    if (activeResponseRef.current) {
      console.warn('[VOICE-A2A] ⚠️ Active response detected - queuing injection to avoid error')
      console.warn('[VOICE-A2A] Will retry after a short delay...')
      
      // Retry after a short delay (100ms) to allow current response to complete
      setTimeout(() => {
        console.log('[VOICE-A2A] 🔄 Retrying injection after delay...')
        injectNetworkResponse(response)
      }, 100)
      return
    }

    const isInProgress = response.status === 'in_progress'
    
    if (isInProgress) {
      // For in-progress messages (workflow steps), inject as USER message
      console.log('[VOICE-A2A] 📝 Strategy: Injecting as USER message (workflow step)')
      
      const userMessage = {
        type: 'conversation.item.create',
        item: {
          type: 'message',
          role: 'user',
          content: [
            {
              type: 'input_text',
              text: response.message
            }
          ]
        }
      }
      
      console.log('[VOICE-A2A] 📤 SENDING user message')
      console.log('[VoiceLive] Full payload:', JSON.stringify(userMessage, null, 2))
      
      wsRef.current.send(JSON.stringify(userMessage))
      console.log('[VOICE-A2A] ✅ User message SENT')
      
      // Mark that we're creating a response
      activeResponseRef.current = true
      console.log('[VOICE-A2A] 📊 Set activeResponseRef = true')
      
      // Trigger Voice Live to respond to this user message
      wsRef.current.send(JSON.stringify({ type: 'response.create' }))
      console.log('[VOICE-A2A] ✅ response.create SENT - Voice Live should speak the message')
      
      // Keep call_id in map for the final response
      console.log('[VOICE-A2A] 🔄 Keeping call_id in map for final response')
      
    } else {
      // For completed status, inject as function_call_output (final result)
      console.log('[VOICE-A2A] 🎯 Strategy: Injecting as FUNCTION_CALL_OUTPUT (final result)')
      
      const functionOutput = {
        type: 'conversation.item.create',
        previous_item_id: callInfo.previous_item_id,
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
      
      console.log('[VOICE-A2A] 📤 SENDING function_call_output')
      console.log('[VoiceLive] Full payload:', JSON.stringify(functionOutput, null, 2))
      
      wsRef.current.send(JSON.stringify(functionOutput))
      console.log('[VOICE-A2A] ✅ function_call_output SENT')
      
      // Mark that we're creating a response
      activeResponseRef.current = true
      console.log('[VOICE-A2A] 📊 Set activeResponseRef = true')
      
      wsRef.current.send(JSON.stringify({ type: 'response.create' }))
      console.log('[VOICE-A2A] ✅ response.create SENT - AI should summarize result')
      
      // Remove call_id from pending map (workflow complete)
      pendingA2ACallsRef.current.delete(response.call_id)
      console.log('[VoiceLive] 🗑️ Removed call_id from pending map (workflow complete)')
      console.log('[VoiceLive] 📊 Remaining pending calls:', pendingA2ACallsRef.current.size)
    }
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
      // Start with a small buffer (50ms) to reduce initial latency
      nextStartTimeRef.current = audioContext.currentTime + 0.05
      console.log('[VoiceLive] Starting playback at', nextStartTimeRef.current)
    }

    // Process all available chunks immediately for smooth playback
    while (audioQueueRef.current.length > 0) {
      processAudioChunk()
    }
  }

  // Start recording audio
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          sampleRate: 24000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true
        } 
      })
      
      audioStreamRef.current = stream

      // Create AudioContext for PCM16 conversion
      const audioContext = new AudioContext({ sampleRate: 24000 })
      const source = audioContext.createMediaStreamSource(stream)
      const processor = audioContext.createScriptProcessor(4096, 1, 1)

      source.connect(processor)
      processor.connect(audioContext.destination)

      let audioChunkCount = 0
      processor.onaudioprocess = (e) => {
        // Only send audio when connected, not playing, recording is active, and NOT muted
        if (wsRef.current?.readyState === WebSocket.OPEN && !isPlayingRef.current && isRecordingRef.current && !isMutedRef.current) {
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
          
          // Log every 50th chunk to avoid spam
          audioChunkCount++
          if (audioChunkCount % 50 === 0) {
            console.log('[VoiceLive] 🎤 Sent', audioChunkCount, 'audio chunks to server')
          }
        }
      }

      // Store references for cleanup
      recordingContextRef.current = audioContext
      audioProcessorRef.current = processor
      
      isRecordingRef.current = true
      setIsRecording(true)
      console.log('[VoiceLive] ✅ Recording STARTED - 24kHz PCM16 conversion active')
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

  // Start voice conversation
  const startVoiceConversation = useCallback(async () => {
    if (!isConnected) {
      await initializeWebSocket()
      // Wait a bit for connection to establish
      await new Promise(resolve => setTimeout(resolve, 1000))
    }
    await startRecording()
  }, [isConnected])

  // Stop voice conversation
  const stopVoiceConversation = useCallback(() => {
    stopRecording()
    
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
    setIsMuted(false)
    isMutedRef.current = false
    audioQueueRef.current = []
    isPlayingRef.current = false
    nextStartTimeRef.current = 0
  }, [])

  // Toggle mute (stops sending audio but keeps recording active)
  const toggleMute = useCallback(() => {
    const newMutedState = !isMutedRef.current
    isMutedRef.current = newMutedState
    setIsMuted(newMutedState)
    console.log('[VoiceLive] Microphone', newMutedState ? 'MUTED' : 'UNMUTED')
  }, [])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
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
