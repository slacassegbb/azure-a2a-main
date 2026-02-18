"use client";

import { useCallback, useRef, useState, useEffect } from "react";

interface VoiceRealtimeConfig {
  apiUrl: string;
  sessionId: string;  // Session ID for agent lookup (e.g., sess_xxx)
  contextId: string;  // Full context ID for WebSocket routing (e.g., sess_xxx::conversation-id)
  workflow?: string;  // Optional explicit workflow for workflow designer testing
  onTranscript?: (text: string, isFinal: boolean) => void;
  onResult?: (result: string) => void;
  onError?: (error: string) => void;
}

interface VoiceRealtimeHook {
  isConnected: boolean;
  isListening: boolean;
  isSpeaking: boolean;
  isProcessing: boolean;
  currentAgent: string | null;
  transcript: string;
  result: string;
  error: string | null;
  startConversation: () => Promise<void>;
  stopConversation: () => void;
  updateContextId: (newContextId: string) => void;  // Allow updating contextId synchronously
}

// Convert base64 to ArrayBuffer for audio playback
function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const binaryString = atob(base64);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes.buffer;
}

// Convert Float32 to Int16 for sending audio
function floatTo16BitPCM(float32Array: Float32Array): Int16Array {
  const int16Array = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return int16Array;
}

// Downsample audio from browser's sample rate to 24kHz
function downsampleBuffer(
  buffer: Float32Array,
  inputSampleRate: number,
  outputSampleRate: number
): Float32Array {
  if (inputSampleRate === outputSampleRate) {
    return buffer;
  }
  const ratio = inputSampleRate / outputSampleRate;
  const newLength = Math.round(buffer.length / ratio);
  const result = new Float32Array(newLength);
  let offsetResult = 0;
  let offsetBuffer = 0;
  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
    let accum = 0,
      count = 0;
    for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
      accum += buffer[i];
      count++;
    }
    result[offsetResult] = accum / count;
    offsetResult++;
    offsetBuffer = nextOffsetBuffer;
  }
  return result;
}

export function useVoiceRealtime(config: VoiceRealtimeConfig): VoiceRealtimeHook {
  const [isConnected, setIsConnected] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [currentAgent, setCurrentAgent] = useState<string | null>(null);
  const [transcript, setTranscript] = useState("");
  const [result, setResult] = useState("");
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const backendWsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const playbackContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const audioQueueRef = useRef<ArrayBuffer[]>([]);
  const isPlayingRef = useRef(false);
  const nextStartTimeRef = useRef(0);
  const pendingCallRef = useRef<{ call_id: string; item_id: string } | null>(null);
  const fillerSpokenRef = useRef(false);
  const isProcessingRef = useRef(false);
  const isResponseActiveRef = useRef(false);  // Track if Azure is generating a response
  const announcedAgentsRef = useRef<Set<string>>(new Set());  // Track announced agents to avoid repeats
  
  // Use refs for contextId and sessionId so they can be updated synchronously
  // This avoids closure issues where callbacks capture stale values
  const contextIdRef = useRef(config.contextId);
  const sessionIdRef = useRef(config.sessionId);
  
  // Keep refs in sync with props
  useEffect(() => {
    contextIdRef.current = config.contextId;
    sessionIdRef.current = config.sessionId;
  }, [config.contextId, config.sessionId]);
  
  // Allow external code to update contextId synchronously (before React re-renders)
  const updateContextId = useCallback((newContextId: string) => {
    console.log("[VoiceRealtime] Updating contextId to:", newContextId);
    contextIdRef.current = newContextId;
    // Also extract and update sessionId
    if (newContextId.includes('::')) {
      sessionIdRef.current = newContextId.split('::')[0];
    }
  }, []);

  // Get Azure token from the API route
  const getAzureToken = async (): Promise<string> => {
    const response = await fetch("/api/azure-token");
    if (!response.ok) {
      throw new Error("Failed to get Azure token");
    }
    const data = await response.json();
    return data.token;
  };

  // Speak a filler message using Azure Voice Live API with out-of-band TTS
  // Uses response.create with conversation: "none" to avoid corrupting the conversation state
  const speakFillerViaAzure = useCallback((text: string) => {
    // Check if we have an active Azure WebSocket connection
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.log("[VoiceRealtime] Azure WebSocket not ready for filler TTS");
      return;
    }
    
    // Skip if there's already an active response (to avoid "Conversation already has an active response" error)
    if (isResponseActiveRef.current) {
      console.log("[VoiceRealtime] Skipping filler - response already active:", text);
      return;
    }
    
    console.log("[VoiceRealtime] 🗣️ Filler skipped (not supported on standard Realtime API):", text);
  }, []);

  // Connect to backend WebSocket for status events
  const connectBackendWebSocket = useCallback(() => {
    // Connect to the /events WebSocket endpoint with tenantId parameter
    // Use dedicated WebSocket URL if available, otherwise derive from API URL
    let wsBaseUrl = process.env.NEXT_PUBLIC_WEBSOCKET_URL || config.apiUrl.replace(/^http/, 'ws');
    
    // If NEXT_PUBLIC_WEBSOCKET_URL already includes /events, don't append it again
    const wsUrl = wsBaseUrl.endsWith('/events') 
      ? `${wsBaseUrl}?tenantId=${encodeURIComponent(contextIdRef.current)}`
      : `${wsBaseUrl}/events?tenantId=${encodeURIComponent(contextIdRef.current)}`;
    console.log("[VoiceRealtime] Connecting to backend WebSocket:", wsUrl);

    const ws = new WebSocket(wsUrl);
    backendWsRef.current = ws;

    ws.onopen = () => {
      console.log("[VoiceRealtime] Backend WebSocket connected");
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        // Debug: Log all incoming events (reduce noise)
        if (data.eventType !== "agent_registry_sync") {
          console.log("[VoiceRealtime] Backend event received:", data.eventType, "isProcessing:", isProcessingRef.current);
        }
        
        // Handle remote_agent_activity events - update visual status
        if (data.eventType === "remote_agent_activity") {
          console.log("[VoiceRealtime] 📣 remote_agent_activity event:", JSON.stringify(data).substring(0, 300));
          
          if (!isProcessingRef.current) {
            console.log("[VoiceRealtime] ⚠️ Ignoring remote_agent_activity - not processing");
            return;
          }
          
          const agentName = data.data?.agentName || data.agentName || "";
          const content = data.data?.content || data.content || "";
          
          // Skip host agent messages
          if (agentName.toLowerCase().includes("host") || agentName.toLowerCase().includes("foundry-host")) {
            return;
          }
          
          // Create friendly name for visual display
          const friendlyName = agentName
            .replace(/^azurefoundry_/i, "")
            .replace(/^AI Foundry /i, "")
            .replace(/_/g, " ")
            .replace(/ Agent$/i, "");
          
          if (friendlyName) {
            // Update visual status
            setCurrentAgent(friendlyName);
            
            // Only announce each agent once per request
            if (!announcedAgentsRef.current.has(friendlyName.toLowerCase())) {
              announcedAgentsRef.current.add(friendlyName.toLowerCase());
              console.log("[VoiceRealtime] 🎯 Announcing agent:", friendlyName);
              // Speak filler via Azure Voice Live TTS (out-of-band, won't corrupt conversation)
              speakFillerViaAzure(`Calling the ${friendlyName} agent.`);
            } else {
              console.log("[VoiceRealtime] Agent already announced, skipping:", friendlyName);
            }
          }
        }
      } catch (err) {
        console.log("[VoiceRealtime] Parse error:", err);
      }
    };

    ws.onerror = () => {
      console.log("[VoiceRealtime] Backend WebSocket error");
    };

    ws.onclose = () => {
      console.log("[VoiceRealtime] Backend WebSocket disconnected");
    };
  }, [config.apiUrl, speakFillerViaAzure]);  // contextId is now read from ref, no need in deps

  // Disconnect backend WebSocket
  const disconnectBackendWebSocket = useCallback(() => {
    if (backendWsRef.current) {
      backendWsRef.current.close();
      backendWsRef.current = null;
    }
  }, []);

  // Call the /api/query endpoint
  const executeQuery = useCallback(async (query: string): Promise<string> => {
    try {
      // Get auth token from sessionStorage
      const token = typeof window !== 'undefined' ? sessionStorage.getItem('auth_token') : null;
      const headers: HeadersInit = { "Content-Type": "application/json" };
      
      // Extract user_id from JWT token (required for /api/query authentication)
      let authenticatedUserId: string | null = null;
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
        try {
          const payload = JSON.parse(atob(token.split('.')[1]));
          authenticatedUserId = payload.user_id || null;
        } catch (e) {
          console.warn("[VoiceRealtime] Failed to decode JWT:", e);
        }
      }
      
      if (!authenticatedUserId) {
        throw new Error("Not authenticated - please log in");
      }
      
      // Extract the conversation ID from the contextId (format: sessionId::conversationId)
      // The backend will create its own contextId by combining session_id and conversation_id
      // Use refs to get the latest values (avoids stale closure issues)
      const currentContextId = contextIdRef.current;
      const currentSessionId = sessionIdRef.current;
      let conversationIdOnly = currentContextId;
      if (currentContextId.includes('::')) {
        conversationIdOnly = currentContextId.split('::')[1];
      }
      
      console.log("[VoiceRealtime] Calling /api/query with:", { 
        query, 
        user_id: authenticatedUserId, 
        session_id: currentSessionId,  // Session ID for agent lookup (sess_xxx)
        conversation_id: conversationIdOnly,  // Just the conversation part (e.g., frontend-chat-context)
      });
      
      // Get activated workflow IDs from sessionStorage
      let activatedWorkflowIds: string[] | undefined;
      try {
        const stored = typeof window !== 'undefined' ? sessionStorage.getItem('a2a_activated_workflows') : null;
        if (stored) {
          const parsed = JSON.parse(stored);
          // Only include if it's a non-empty array
          if (Array.isArray(parsed) && parsed.length > 0) {
            activatedWorkflowIds = parsed;
            console.log("[VoiceRealtime] Including activated workflows:", activatedWorkflowIds);
          }
        }
      } catch (e) {
        console.warn("[VoiceRealtime] Failed to get activated workflows:", e);
      }
      
      // Build request body - use ref values for session/context to get latest
      const requestBody: Record<string, unknown> = {
        query,
        user_id: authenticatedUserId,  // Must match authenticated user
        session_id: currentSessionId,  // Session ID for agent lookup (e.g., sess_xxx)
        conversation_id: conversationIdOnly,  // Just the conversation ID, backend will combine with session_id
        timeout: 120,
      };
      
      // Only include activated_workflow_ids if we have them (and no explicit workflow)
      if (activatedWorkflowIds && activatedWorkflowIds.length > 0 && !config.workflow) {
        requestBody.activated_workflow_ids = activatedWorkflowIds;
      }
      
      // Include explicit workflow if provided (workflow designer testing mode)
      if (config.workflow) {
        requestBody.workflow = config.workflow;
        console.log("[VoiceRealtime] 🎯 Using explicit workflow (workflow designer mode)");
      }
      
      console.log("[VoiceRealtime] Request body:", requestBody);
      
      const response = await fetch(`${config.apiUrl}/api/query`, {
        method: "POST",
        headers,
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        // Try to get more details from the response body
        let errorDetail = response.statusText;
        try {
          const errorData = await response.json();
          errorDetail = errorData.detail || errorData.message || errorData.error || response.statusText;
          console.error("[VoiceRealtime] API error response:", errorData);
        } catch {
          // Couldn't parse JSON, use status text
        }
        throw new Error(`Query failed: ${errorDetail}`);
      }

      const data = await response.json();
      console.log("[VoiceRealtime] Query result:", data);
      
      return data.result || "I completed the task but have no additional details to share.";
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : "Query failed";
      console.error("[VoiceRealtime] Query error:", err);
      return `Sorry, I encountered an error: ${errorMessage}`;
    }
  }, [config.apiUrl]);  // sessionId and contextId are now read from refs

  // Track active audio sources
  const currentSourcesRef = useRef<AudioBufferSourceNode[]>([]);

  // Process a single audio chunk
  const processAudioChunk = useCallback(() => {
    if (!playbackContextRef.current || audioQueueRef.current.length === 0) {
      return;
    }

    const audioData = audioQueueRef.current.shift();
    if (!audioData) return;

    try {
      const audioContext = playbackContextRef.current;
      
      // Convert PCM16 to Float32
      const int16Array = new Int16Array(audioData);
      const float32Array = new Float32Array(int16Array.length);
      for (let i = 0; i < int16Array.length; i++) {
        float32Array[i] = int16Array[i] / 32768;
      }

      const audioBuffer = audioContext.createBuffer(1, float32Array.length, 24000);
      audioBuffer.copyToChannel(float32Array, 0);

      const source = audioContext.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(audioContext.destination);

      // Track source for cleanup
      currentSourcesRef.current.push(source);

      // Handle source completion
      source.onended = () => {
        const index = currentSourcesRef.current.indexOf(source);
        if (index > -1) {
          currentSourcesRef.current.splice(index, 1);
        }
        
        // Check if we're done playing all audio
        if (currentSourcesRef.current.length === 0 && audioQueueRef.current.length === 0) {
          // Add a small delay before re-enabling mic to avoid feedback
          setTimeout(() => {
            isPlayingRef.current = false;
            setIsSpeaking(false);
            console.log("[VoiceRealtime] 🔊 Playback complete, mic re-enabled");
          }, 300);
        }
      };

      // Schedule with precise timing
      const now = audioContext.currentTime;
      const scheduleTime = Math.max(now, nextStartTimeRef.current);
      source.start(scheduleTime);
      nextStartTimeRef.current = scheduleTime + audioBuffer.duration;
    } catch (err) {
      console.error("[VoiceRealtime] Audio chunk error:", err);
    }
  }, []);

  // Play audio from queue
  const playAudioQueue = useCallback(async () => {
    if (!playbackContextRef.current) {
      playbackContextRef.current = new AudioContext({ sampleRate: 24000 });
      await playbackContextRef.current.resume();
    }

    // Initialize timing on first call
    if (!isPlayingRef.current) {
      isPlayingRef.current = true;
      setIsSpeaking(true);
      nextStartTimeRef.current = playbackContextRef.current.currentTime + 0.05;
      console.log("[VoiceRealtime] 🔊 Starting playback, mic muted");
    }

    // Process all available chunks
    while (audioQueueRef.current.length > 0) {
      processAudioChunk();
    }
  }, [processAudioChunk]);

  // Handle WebSocket messages
  const handleMessage = useCallback(
    async (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data);
        console.log("[VoiceRealtime] Event:", msg.type);

        switch (msg.type) {
          case "session.created":
          case "session.updated":
            console.log("[VoiceRealtime] Session ready");
            setIsListening(true);
            
            // Send a friendly greeting (only on session.created)
            if (msg.type === "session.created" && wsRef.current?.readyState === WebSocket.OPEN) {
              wsRef.current.send(JSON.stringify({
                type: "response.create",
                response: {
                  modalities: ["audio", "text"],
                  instructions: "Say a brief, warm greeting like: 'Hey there! How can I help you today?' Keep it natural and friendly, just 1 sentence.",
                }
              }));
            }
            break;

          case "input_audio_buffer.speech_started":
            console.log("[VoiceRealtime] 🎤 Speech started - VAD detected voice");
            break;

          case "input_audio_buffer.speech_stopped":
            console.log("[VoiceRealtime] 🎤 Speech stopped - VAD detected silence");
            break;

          case "input_audio_buffer.committed":
            console.log("[VoiceRealtime] 🎤 Audio buffer committed");
            break;

          case "conversation.item.input_audio_transcription.completed":
            console.log("[VoiceRealtime] User said:", msg.transcript);
            setTranscript(msg.transcript || "");
            config.onTranscript?.(msg.transcript || "", true);
            break;

          case "response.created":
            console.log("[VoiceRealtime] 🤖 Response started");
            setIsListening(false);
            break;

          case "response.function_call_arguments.done":
            console.log("[VoiceRealtime] Function call:", msg.name, msg.arguments);
            // Only process if we have a pending call and haven't processed it yet
            if (msg.name === "execute_query" && pendingCallRef.current) {
              const currentCallId = pendingCallRef.current.call_id;
              // Clear pending immediately to prevent duplicate processing
              pendingCallRef.current = null;
              
              setIsProcessing(true);
              isProcessingRef.current = true;
              fillerSpokenRef.current = false; // Reset filler flag for this request
              announcedAgentsRef.current.clear(); // Clear announced agents for new request
              setIsListening(false);
              
              try {
                const args = JSON.parse(msg.arguments || "{}");
                console.log("[VoiceRealtime] 📤 Calling /api/query with:", args.query || transcript);
                const queryResult = await executeQuery(args.query || transcript);
                
                console.log("[VoiceRealtime] 📥 Query result received:", queryResult?.substring(0, 200));
                setResult(queryResult);
                config.onResult?.(queryResult);

                // Inject result back to Realtime API
                if (wsRef.current?.readyState === WebSocket.OPEN) {
                  console.log("[VoiceRealtime] 📤 Sending function output to Realtime API");
                  // Send function output
                  wsRef.current.send(
                    JSON.stringify({
                      type: "conversation.item.create",
                      item: {
                        type: "function_call_output",
                        call_id: currentCallId,
                        output: queryResult,
                      },
                    })
                  );

                  console.log("[VoiceRealtime] 📤 Requesting response.create");
                  // Request AI to respond with the result
                  wsRef.current.send(JSON.stringify({ type: "response.create" }));
                } else {
                  console.error("[VoiceRealtime] ❌ WebSocket not open, cannot send result");
                }
              } catch (err) {
                console.error("[VoiceRealtime] Function execution error:", err);
              } finally {
                setIsProcessing(false);
                isProcessingRef.current = false;
                setCurrentAgent(null);
              }
            }
            break;

          case "conversation.item.created":
            if (msg.item?.type === "function_call") {
              console.log("[VoiceRealtime] Function call created:", msg.item.name);
              pendingCallRef.current = {
                call_id: msg.item.call_id,
                item_id: msg.item.id,
              };
            }
            break;

          case "response.audio.delta":
            if (msg.delta) {
              const audioData = base64ToArrayBuffer(msg.delta);
              audioQueueRef.current.push(audioData);
              
              // Start playback after buffering some chunks OR continue if already playing
              if (audioQueueRef.current.length >= 5 || isPlayingRef.current) {
                playAudioQueue();
              }
            }
            break;

          case "response.audio.done":
            console.log("[VoiceRealtime] 🔊 All audio chunks received");
            // Flush any remaining chunks
            if (audioQueueRef.current.length > 0) {
              playAudioQueue();
            }
            break;

          case "response.done":
            console.log("[VoiceRealtime] Response complete");
            isResponseActiveRef.current = false;  // Allow new fillers
            setIsListening(true);
            break;

          case "error":
            console.error("[VoiceRealtime] API error:", msg.error);
            isResponseActiveRef.current = false;  // Reset on error
            setError(msg.error?.message || "Unknown error");
            config.onError?.(msg.error?.message || "Unknown error");
            break;
        }
      } catch (err) {
        console.error("[VoiceRealtime] Message parse error:", err);
      }
    },
    [config, transcript, playAudioQueue, executeQuery]
  );

  // Start microphone capture
  const startMicrophone = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          sampleRate: 24000,
        },
      });
      streamRef.current = stream;

      audioContextRef.current = new AudioContext({ sampleRate: 24000 });
      const source = audioContextRef.current.createMediaStreamSource(stream);
      
      // Use ScriptProcessor for audio capture (deprecated but widely supported)
      const processor = audioContextRef.current.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      let audioChunkCount = 0;
      processor.onaudioprocess = (e) => {
        // Only send audio when NOT playing back (to avoid echo/feedback)
        if (wsRef.current?.readyState === WebSocket.OPEN && !isPlayingRef.current) {
          const inputData = e.inputBuffer.getChannelData(0);
          const downsampledData = downsampleBuffer(
            inputData,
            audioContextRef.current?.sampleRate || 44100,
            24000
          );
          const pcm16Data = floatTo16BitPCM(downsampledData);
          
          // Convert to base64 without spread operator for TypeScript compatibility
          const uint8Array = new Uint8Array(pcm16Data.buffer);
          let binaryString = "";
          for (let i = 0; i < uint8Array.length; i++) {
            binaryString += String.fromCharCode(uint8Array[i]);
          }
          const base64Audio = btoa(binaryString);

          wsRef.current.send(
            JSON.stringify({
              type: "input_audio_buffer.append",
              audio: base64Audio,
            })
          );

          // Log every 50th chunk
          audioChunkCount++;
          if (audioChunkCount % 50 === 0) {
            console.log("[VoiceRealtime] 🎤 Sent", audioChunkCount, "audio chunks");
          }
        }
      };

      source.connect(processor);
      processor.connect(audioContextRef.current.destination);

      console.log("[VoiceRealtime] Microphone started");
    } catch (err) {
      console.error("[VoiceRealtime] Microphone error:", err);
      setError("Microphone access denied");
    }
  }, []);

  // Stop microphone
  const stopMicrophone = useCallback(() => {
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
  }, []);

  // Start voice conversation
  const startConversation = useCallback(async () => {
    try {
      setError(null);
      setTranscript("");
      setResult("");

      // Get Azure token
      const token = await getAzureToken();

      // Build WebSocket URL from resource host and deployment name
      const voiceHost = process.env.NEXT_PUBLIC_VOICE_HOST || "";
      const voiceDeployment = process.env.NEXT_PUBLIC_VOICE_DEPLOYMENT || "gpt-realtime";

      if (!voiceHost) {
        throw new Error("NEXT_PUBLIC_VOICE_HOST is not configured");
      }

      const wsUrl = `wss://${voiceHost}/openai/realtime?api-version=2025-04-01-preview&deployment=${voiceDeployment}&api-key=${token}`;

      console.log("[VoiceRealtime] Connecting to:", wsUrl.replace(token, "***"));

      // Create WebSocket
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      // Initialize audio contexts
      playbackContextRef.current = new AudioContext({ sampleRate: 24000 });
      nextStartTimeRef.current = 0;

      ws.onopen = () => {
        console.log("[VoiceRealtime] Connected");
        setIsConnected(true);

        // Configure session - using Voice Live API format (matching main frontend)
        ws.send(
          JSON.stringify({
            type: "session.update",
            session: {
              instructions: `You are a helpful assistant. When the user asks you to do something, you MUST call the execute_query function with their request. After receiving the function result, summarize it conversationally and briefly.

IMPORTANT RULES:
1. For ANY user request, call execute_query immediately
2. Keep your spoken responses brief and natural
3. Do not read long technical details - summarize them
4. Be conversational and friendly`,
              modalities: ["text", "audio"],
              turn_detection: {
                type: "server_vad",
                threshold: 0.5,
                prefix_padding_ms: 300,
                silence_duration_ms: 500,
              },
              input_audio_format: "pcm16",
              output_audio_format: "pcm16",
              input_audio_transcription: {
                model: "whisper-1",
              },
              voice: "alloy",
              temperature: 0.6,
              tools: [
                {
                  type: "function",
                  name: "execute_query",
                  description:
                    "Execute any user request by sending it to the agent network. Use this for ALL user requests.",
                  parameters: {
                    type: "object",
                    properties: {
                      query: {
                        type: "string",
                        description: "The user's request to execute",
                      },
                    },
                    required: ["query"],
                  },
                },
              ],
              tool_choice: "auto",
            },
          })
        );

        // Start microphone
        startMicrophone();
        
        // Connect to backend WebSocket for agent activity events (voice fillers)
        connectBackendWebSocket();
      };

      ws.onmessage = handleMessage;

      ws.onerror = (err) => {
        console.error("[VoiceRealtime] WebSocket error:", err);
        setError("Connection error - check Azure configuration");
        setIsConnected(false);
      };

      ws.onclose = (event) => {
        console.log("[VoiceRealtime] Disconnected:", event.code, event.reason);
        if (event.code === 1006) {
          setError("Connection failed - check NEXT_PUBLIC_VOICE_HOST configuration");
        }
        setIsConnected(false);
        setIsListening(false);
        stopMicrophone();
      };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : "Failed to start";
      console.error("[VoiceRealtime] Start error:", err);
      setError(errorMessage);
    }
  }, [handleMessage, startMicrophone, stopMicrophone, connectBackendWebSocket]);

  // Stop conversation
  const stopConversation = useCallback(() => {
    console.log("[VoiceRealtime] Stopping conversation");
    
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    
    // Disconnect backend WebSocket
    disconnectBackendWebSocket();
    
    stopMicrophone();
    
    if (playbackContextRef.current) {
      playbackContextRef.current.close();
      playbackContextRef.current = null;
    }

    audioQueueRef.current = [];
    isPlayingRef.current = false;
    pendingCallRef.current = null;
    fillerSpokenRef.current = false;
    isProcessingRef.current = false;

    setIsConnected(false);
    setIsListening(false);
    setIsSpeaking(false);
    setIsProcessing(false);
    setCurrentAgent(null);
  }, [disconnectBackendWebSocket, stopMicrophone]);

  return {
    isConnected,
    isListening,
    isSpeaking,
    isProcessing,
    currentAgent,
    transcript,
    result,
    error,
    startConversation,
    stopConversation,
    updateContextId,
  };
}
