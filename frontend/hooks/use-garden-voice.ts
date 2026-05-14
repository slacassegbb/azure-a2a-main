"use client";

import { useCallback, useRef, useState, useEffect } from "react";

// Mobile-style WebRTC voice hook for the garden dashboard.
// Identical to frontend_mobile/hooks/use-voice-realtime.ts except executeQuery
// calls /api/garden/query (server-side auth proxy) instead of requiring a JWT.

interface GardenVoiceConfig {
  onTurnComplete?: (user: string, agent: string) => void;
}

interface GardenVoiceHook {
  isConnected: boolean;
  isListening: boolean;
  isSpeaking: boolean;
  isProcessing: boolean;
  isTalking: boolean;
  isVoiceProcessing: boolean;
  currentAgent: string | null;
  transcript: string;
  result: string;
  error: string | null;
  startConversation: () => Promise<void>;
  stopConversation: () => void;
  startTalking: () => void;
  stopTalking: (options?: { interruptMode?: boolean }) => void;
}

export function useGardenVoice(config: GardenVoiceConfig = {}): GardenVoiceHook {
  const [isConnected, setIsConnected] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [currentAgent, setCurrentAgent] = useState<string | null>(null);
  const [transcript, setTranscript] = useState("");
  const [result, setResult] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isTalking, setIsTalking] = useState(false);
  const [isVoiceProcessing, setIsVoiceProcessing] = useState(false);

  const pcRef = useRef<RTCPeerConnection | null>(null);
  const dcRef = useRef<RTCDataChannel | null>(null);
  const localTrackRef = useRef<MediaStreamTrack | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null);
  const backendWsRef = useRef<WebSocket | null>(null);

  const isTalkingRef = useRef(false);
  const autoActivateRef = useRef(false);
  const pendingCallRef = useRef<{ call_id: string; item_id: string } | null>(null);
  const isProcessingRef = useRef(false);
  const lastTranscriptRef = useRef("");
  const isResponseActiveRef = useRef(false);
  const announcedAgentsRef = useRef<Set<string>>(new Set());
  const intentionalCloseRef = useRef(false);

  const sendEvent = useCallback((event: object) => {
    if (dcRef.current?.readyState === "open") {
      dcRef.current.send(JSON.stringify(event));
    }
  }, []);

  const setMicEnabled = useCallback((enabled: boolean) => {
    if (localTrackRef.current) localTrackRef.current.enabled = enabled;
  }, []);

  const speakFillerViaAzure = useCallback((text: string) => {
    if (dcRef.current?.readyState !== "open") return;
    if (isResponseActiveRef.current || !isProcessingRef.current) return;
    isResponseActiveRef.current = true;
    sendEvent({
      type: "response.create",
      response: { instructions: `Say exactly this in a brief, natural way: "${text}"` },
    });
  }, [sendEvent]);

  const connectBackendWebSocket = useCallback(() => {
    const wsBaseUrl = process.env.NEXT_PUBLIC_WEBSOCKET_URL || "";
    if (!wsBaseUrl) return;
    const wsUrl = wsBaseUrl.endsWith("/events")
      ? `${wsBaseUrl}?tenantId=user_3`
      : `${wsBaseUrl}/events?tenantId=user_3`;
    const ws = new WebSocket(wsUrl);
    backendWsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.eventType === "remote_agent_activity" && isProcessingRef.current) {
          const agentName = data.agentName || data.data?.agentName || "";
          if (agentName.toLowerCase().includes("host") || agentName.toLowerCase().includes("foundry-host")) return;
          const friendly = agentName
            .replace(/^azurefoundry_/i, "")
            .replace(/^AI Foundry /i, "")
            .replace(/_/g, " ")
            .replace(/ Agent$/i, "");
          if (friendly) {
            setCurrentAgent(friendly);
            const content = data.content || data.data?.content || "";
            if (!announcedAgentsRef.current.has(friendly.toLowerCase())) {
              announcedAgentsRef.current.add(friendly.toLowerCase());
              const workingOn = content.match(/Working on:\s*(.{10,80})/i)?.[1];
              speakFillerViaAzure(workingOn ? `Contacting the ${friendly} agent. Working on: ${workingOn}` : `Contacting the ${friendly} agent.`);
            } else if ((data.activityType || data.data?.activityType) === "agent_complete") {
              speakFillerViaAzure(`${friendly} agent is done.`);
            }
          }
        }
      } catch {}
    };
  }, [speakFillerViaAzure]);

  const disconnectBackendWs = useCallback(() => {
    backendWsRef.current?.close();
    backendWsRef.current = null;
  }, []);

  const executeQuery = useCallback(async (query: string): Promise<string> => {
    try {
      const res = await fetch("/api/garden/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      const data = await res.json();
      return data.result || "Done.";
    } catch (err: any) {
      return `Sorry, error: ${err.message || "Query failed"}`;
    }
  }, []);

  const handleMessage = useCallback(async (event: MessageEvent) => {
    try {
      const msg = JSON.parse(event.data);
      switch (msg.type) {
        case "session.created":
        case "session.updated":
          setIsListening(true);
          if (msg.type === "session.created") {
            sendEvent({
              type: "response.create",
              response: {
                instructions: "Say a brief, warm greeting like: 'Hey! How can I help with the garden today?' Keep it natural, just 1 sentence.",
              },
            });
            autoActivateRef.current = true;
          }
          break;

        case "input_audio_buffer.speech_stopped":
          if (isTalkingRef.current) {
            isTalkingRef.current = false;
            setIsTalking(false);
            setMicEnabled(false);
          }
          break;

        case "conversation.item.input_audio_transcription.completed":
          setTranscript(msg.transcript || "");
          lastTranscriptRef.current = msg.transcript || "";
          break;

        case "response.created":
          setIsListening(false);
          break;

        case "response.function_call_arguments.done":
          if (msg.name === "execute_query") {
            const callId = pendingCallRef.current?.call_id || msg.call_id;
            pendingCallRef.current = null;
            if (!callId) break;
            setIsProcessing(true);
            isProcessingRef.current = true;
            setIsVoiceProcessing(true);
            isResponseActiveRef.current = false;
            announcedAgentsRef.current.clear();
            try {
              const args = JSON.parse(msg.arguments || "{}");
              const userText = args.query || lastTranscriptRef.current || transcript;
              const queryResult = await executeQuery(userText);
              setResult(queryResult);
              if (userText && queryResult) config.onTurnComplete?.(userText, queryResult);
              if (dcRef.current?.readyState === "open") {
                if (isResponseActiveRef.current) {
                  sendEvent({ type: "response.cancel" });
                  isResponseActiveRef.current = false;
                }
                sendEvent({ type: "conversation.item.create", item: { type: "function_call_output", call_id: callId, output: queryResult } });
                sendEvent({ type: "response.create" });
              }
            } finally {
              setIsProcessing(false);
              isProcessingRef.current = false;
              setIsVoiceProcessing(false);
              setCurrentAgent(null);
            }
          }
          break;

        case "conversation.item.created":
        case "conversation.item.added":
          if (msg.item?.type === "function_call") {
            pendingCallRef.current = { call_id: msg.item.call_id, item_id: msg.item.id };
          }
          break;

        case "output_audio_buffer.started":
          setIsSpeaking(true);
          break;

        case "output_audio_buffer.stopped":
          setIsSpeaking(false);
          setIsListening(true);
          if (autoActivateRef.current) {
            autoActivateRef.current = false;
            setTimeout(() => {
              setMicEnabled(true);
              isTalkingRef.current = true;
              setIsTalking(true);
            }, 500);
          }
          break;

        case "response.done":
          isResponseActiveRef.current = false;
          break;

        case "error":
          isResponseActiveRef.current = false;
          setError(msg.error?.message || "Unknown error");
          break;
      }
    } catch {}
  }, [transcript, executeQuery, sendEvent, setMicEnabled]);

  const cancelPlayback = useCallback(() => {
    if (remoteAudioRef.current) {
      remoteAudioRef.current.volume = 0;
      setTimeout(() => { if (remoteAudioRef.current) remoteAudioRef.current.volume = 1; }, 500);
    }
    setIsSpeaking(false);
  }, []);

  const startTalking = useCallback(() => {
    if (dcRef.current?.readyState !== "open") return;
    if (isResponseActiveRef.current) {
      cancelPlayback();
      sendEvent({ type: "response.cancel" });
      isResponseActiveRef.current = false;
    }
    sendEvent({ type: "input_audio_buffer.clear" });
    setMicEnabled(true);
    isTalkingRef.current = true;
    setIsTalking(true);
  }, [cancelPlayback, sendEvent, setMicEnabled]);

  const stopTalking = useCallback((options?: { interruptMode?: boolean }) => {
    if (!isTalkingRef.current) return;
    isTalkingRef.current = false;
    setIsTalking(false);
    setMicEnabled(false);
    if (dcRef.current?.readyState === "open" && !options?.interruptMode) {
      sendEvent({ type: "response.create" });
    }
  }, [sendEvent, setMicEnabled]);

  const startConversation = useCallback(async () => {
    try {
      intentionalCloseRef.current = false;
      setError(null);
      setTranscript("");
      setResult("");

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      streamRef.current = stream;
      const audioTrack = stream.getAudioTracks()[0];
      localTrackRef.current = audioTrack;
      audioTrack.enabled = false;

      const pc = new RTCPeerConnection();
      pcRef.current = pc;

      const audioEl = document.createElement("audio");
      audioEl.autoplay = true;
      remoteAudioRef.current = audioEl;

      pc.ontrack = (event) => {
        if (event.streams.length > 0) audioEl.srcObject = event.streams[0];
      };

      pc.addTrack(audioTrack, stream);

      const dc = pc.createDataChannel("oai-events");
      dcRef.current = dc;

      dc.onopen = () => {
        setIsConnected(true);
        dc.send(JSON.stringify({
          type: "session.update",
          session: {
            type: "realtime",
            instructions: "You are a voice assistant for a smart garden. Your ONLY capability is calling execute_query.\n\nFor EVERY user message, call execute_query with their exact words. No exceptions.\nAfter receiving the result, summarize it briefly and conversationally.\nKeep responses short. Do not read technical details verbatim.\nNEVER respond without calling execute_query first.",
            output_modalities: ["audio"],
            audio: {
              input: {
                transcription: { model: "whisper-1" },
                turn_detection: { type: "semantic_vad", eagerness: "low" },
                noise_reduction: { type: "near_field" },
              },
              output: { voice: "alloy" },
            },
            tools: [
              {
                type: "function",
                name: "execute_query",
                description: "REQUIRED for every user message. Send the user's request to the garden agent. Pass their words EXACTLY as spoken.",
                parameters: {
                  type: "object",
                  strict: true,
                  properties: { query: { type: "string", description: "The user's EXACT words, copied verbatim from their transcript." } },
                  required: ["query"],
                  additionalProperties: false,
                },
              },
            ],
            tool_choice: "auto",
          },
        }));
        connectBackendWebSocket();
      };

      dc.onmessage = handleMessage;
      dc.onclose = () => { setIsConnected(false); setIsListening(false); };

      pc.onconnectionstatechange = () => {
        const state = pc.connectionState;
        if ((state === "failed" || state === "disconnected") && !intentionalCloseRef.current) {
          setError("Voice connection lost");
          setIsConnected(false);
          setIsListening(false);
        }
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      const response = await fetch("/api/rtc-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sdp: offer.sdp }),
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || err.error || "SDP exchange failed");
      }

      const { sdp: answerSdp } = await response.json();
      await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });
    } catch (err: any) {
      setError(err.message || "Failed to start voice");
    }
  }, [handleMessage, connectBackendWebSocket]);

  const stopConversation = useCallback(() => {
    intentionalCloseRef.current = true;
    dcRef.current?.close();
    dcRef.current = null;
    pcRef.current?.close();
    pcRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    localTrackRef.current = null;
    if (remoteAudioRef.current) {
      remoteAudioRef.current.srcObject = null;
      remoteAudioRef.current = null;
    }
    disconnectBackendWs();
    pendingCallRef.current = null;
    isProcessingRef.current = false;
    isTalkingRef.current = false;
    isResponseActiveRef.current = false;
    autoActivateRef.current = false;
    announcedAgentsRef.current.clear();
    setIsConnected(false);
    setIsListening(false);
    setIsSpeaking(false);
    setIsProcessing(false);
    setIsTalking(false);
    setIsVoiceProcessing(false);
    setCurrentAgent(null);
  }, [disconnectBackendWs]);

  return {
    isConnected, isListening, isSpeaking, isProcessing, isTalking,
    isVoiceProcessing, currentAgent, transcript, result, error,
    startConversation, stopConversation, startTalking, stopTalking,
  };
}
