"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { logDebug } from '@/lib/debug';
import { useVoiceRealtime } from "@/hooks/use-voice-realtime";
import { Phone, PhoneOff, Mic, MicOff, AlertTriangle, Volume2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

import { API_BASE_URL } from '@/lib/api-config';

// Message type for conversation history
export interface VoiceMessage {
  id: string;
  timestamp: Date;
  userQuery: string;
  response: string;
}

interface VoiceButtonProps {
  sessionId: string;  // The session ID for agent lookup (e.g., sess_xxx)
  contextId: string;  // The full context ID for conversation tracking (e.g., sess_xxx::conversation-id)
  conversationId: string;  // The raw conversation ID from URL (to detect 'frontend-chat-context')
  workflow?: string;  // Optional explicit workflow for workflow designer testing
  onEnsureConversation?: () => Promise<string | null>;  // Callback to create conversation if needed, returns new conversation ID
  onFirstMessage?: (conversationId: string, transcript: string) => void;  // Callback when first voice message is sent (for title update)
  onNewMessage?: (message: VoiceMessage) => void;
  isInferencing?: boolean;  // Whether a text-initiated workflow is running
  onVoiceInterrupt?: (transcript: string) => void;  // Callback when voice interrupt is spoken during workflow
  disabled?: boolean;
  disabledMessage?: string;
}


export function VoiceButton({ sessionId, contextId, conversationId, workflow, onEnsureConversation, onFirstMessage, onNewMessage, isInferencing = false, onVoiceInterrupt, disabled = false, disabledMessage }: VoiceButtonProps) {
  const [showDisabledTooltip, setShowDisabledTooltip] = useState(false);
  const [activeContextId, setActiveContextId] = useState(contextId);
  const [activeConversationId, setActiveConversationId] = useState(conversationId);
  const lastResultRef = useRef<string>("");
  const lastTranscriptRef = useRef<string>("");
  const isNewConversationRef = useRef<boolean>(false);  // Track if this is a new conversation needing title
  const firstMessageSentRef = useRef<boolean>(false);  // Track if first message callback was fired
  const interruptModeRef = useRef<boolean>(false);  // Track if current speech should be routed as interrupt
  
  // Update activeContextId when contextId prop changes (e.g., after conversation is created)
  useEffect(() => {
    setActiveContextId(contextId);
  }, [contextId]);
  
  // Update activeConversationId when conversationId prop changes
  useEffect(() => {
    setActiveConversationId(conversationId);
    // Don't reset titleUpdatedRef here - it causes the old transcript to update new conversations
    // titleUpdatedRef is only reset when starting a new voice session (in handleStartConversation)
  }, [conversationId]);
  
  const voice = useVoiceRealtime({
    apiUrl: API_BASE_URL,
    sessionId: sessionId,    // Session ID for agent lookup (e.g., sess_xxx)
    contextId: activeContextId,    // Full context ID for conversation tracking (may be updated after conversation creation)
    workflow: workflow,    // Optional explicit workflow for workflow designer testing
    onTranscript: (text, isFinal) => {
      logDebug("[VoiceButton] Transcript:", text, "isFinal:", isFinal, "interruptMode:", interruptModeRef.current);
      lastTranscriptRef.current = text;
      // In interrupt mode, route the final transcript through the interrupt system
      if (isFinal && interruptModeRef.current && onVoiceInterrupt && text.trim()) {
        logDebug("[VoiceButton] Routing voice transcript as interrupt:", text);
        onVoiceInterrupt(text.trim());
        interruptModeRef.current = false;
      }
    },
    onResult: (result) => {
      logDebug("[VoiceButton] Result:", result);
      lastResultRef.current = result;
    },
    onError: (error) => {
      console.error("[VoiceButton] Error:", error);
    },
  });
  
  // Wrapper for startConversation that ensures we have a real conversation first
  const handleStartConversation = useCallback(async () => {
    // Reset first message flag when starting a new voice session
    firstMessageSentRef.current = false;
    isNewConversationRef.current = false;
    
    // If we're on the default conversation and have a callback to create one, do it first
    if (conversationId === 'frontend-chat-context' && onEnsureConversation) {
      logDebug("[VoiceButton] Creating conversation before starting voice...");
      const newConversationId = await onEnsureConversation();
      if (newConversationId) {
        // Mark as new conversation - needs title update on first message
        isNewConversationRef.current = true;
        
        // Update the active context ID to use the new conversation
        const newContextId = `${sessionId}::${newConversationId}`;
        logDebug("[VoiceButton] Using new conversation:", newContextId);
        
        // Update the voice hook's context synchronously via ref (before React re-renders)
        voice.updateContextId(newContextId);
        
        // Also update local state for UI
        setActiveContextId(newContextId);
        setActiveConversationId(newConversationId);
      }
    }
    
    // Now start the voice conversation
    voice.startConversation();
  }, [conversationId, onEnsureConversation, sessionId, voice]);
  
  // Fire onFirstMessage callback when we get the first transcript for a new conversation
  // This allows chat-panel to update the title like it does for text messages
  useEffect(() => {
    if (voice.isConnected && voice.transcript && isNewConversationRef.current && !firstMessageSentRef.current && onFirstMessage && activeConversationId && activeConversationId !== 'frontend-chat-context') {
      logDebug("[VoiceButton] First voice message for new conversation:", voice.transcript);
      onFirstMessage(activeConversationId, voice.transcript);
      firstMessageSentRef.current = true;
    }
  }, [voice.isConnected, voice.transcript, onFirstMessage, activeConversationId]);
  
  // Save message to history when done speaking
  useEffect(() => {
    if (voice.result && !voice.isSpeaking && !voice.isProcessing) {
      if (onNewMessage && voice.transcript && voice.result) {
        onNewMessage({
          id: crypto.randomUUID(),
          timestamp: new Date(),
          userQuery: voice.transcript,
          response: voice.result,
        });
      }
    }
  }, [voice.result, voice.isSpeaking, voice.isProcessing, voice.transcript, onNewMessage]);

  // Disconnect the voice session
  const handleDisconnect = useCallback(() => {
    voice.stopConversation();
  }, [voice]);

  // Main button click: connect or push-to-talk toggle
  const handleClick = () => {
    if (!voice.isConnected) {
      // Not connected: start voice session
      handleStartConversation();
      return;
    }

    if (voice.isTalking) {
      // Currently talking: stop and submit
      const isInInterruptMode = isInferencing || voice.isVoiceProcessing;
      if (isInInterruptMode) {
        interruptModeRef.current = true;
        voice.stopTalking({ interruptMode: true });
      } else {
        voice.stopTalking();
      }
    } else {
      // Connected but not talking: start push-to-talk
      voice.startTalking();
    }
  };

  // Determine button state and styling
  const getButtonState = () => {
    if (voice.error) {
      return {
        color: "bg-red-500",
        pulseColor: "bg-red-400",
        icon: "error",
        label: "Error - Tap to retry",
      };
    }
    if (voice.isTalking) {
      return {
        color: "bg-red-500",
        pulseColor: "bg-red-400",
        icon: "talking",
        label: "Tap to send",
      };
    }
    if (voice.isSpeaking) {
      return {
        color: "bg-purple-500",
        pulseColor: "bg-purple-400",
        icon: "speaking",
        label: "Speaking... (tap to interrupt)",
      };
    }
    if (voice.isProcessing || voice.isVoiceProcessing) {
      return {
        color: "bg-yellow-500",
        pulseColor: "bg-yellow-400",
        icon: "processing",
        label: voice.currentAgent ? `Contacting ${voice.currentAgent}... (tap to interrupt)` : "Processing... (tap to interrupt)",
      };
    }
    if (voice.isConnected) {
      return {
        color: "bg-blue-500",
        pulseColor: "bg-blue-400",
        icon: "ready",
        label: "Tap to talk",
      };
    }
    return {
      color: "bg-primary",
      pulseColor: "bg-primary/70",
      icon: "idle",
      label: "Start voice conversation",
    };
  };

  const state = getButtonState();
  const isActive = voice.isConnected || voice.isTalking || voice.isSpeaking || voice.isProcessing || voice.isVoiceProcessing;
  

  // Render the icon based on state
  const renderIcon = () => {
    if (disabled) {
      return <MicOff className="h-5 w-5 opacity-70" />;
    }
    switch (state.icon) {
      case "error":
        return <AlertTriangle className="h-5 w-5" />;
      case "talking":
        return <Mic className="h-5 w-5 animate-pulse" />;
      case "speaking":
        return <Volume2 className="h-5 w-5" />;
      case "processing":
        return <Loader2 className="h-5 w-5 animate-spin" />;
      case "ready":
        return <Mic className="h-5 w-5" />;
      default:
        return <Phone className="h-5 w-5" />;
    }
  };

  return (
    <>
      {/* Error display only - no floating panels for transcript/result/status */}
      {voice.error && (
        <div className="fixed bottom-20 left-1/2 -translate-x-1/2 z-50 animate-in slide-in-from-bottom-4">
          <div className="bg-background rounded-xl shadow-xl border border-red-300 p-4">
            <p className="text-sm text-red-500">{voice.error}</p>
          </div>
        </div>
      )}

      {/* Voice Button + Disconnect */}
      <div className="flex items-center gap-1">
        {/* Disconnect button - only shown when connected */}
        {voice.isConnected && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 rounded-full bg-muted hover:bg-red-100 hover:text-red-600 text-muted-foreground"
                onClick={handleDisconnect}
              >
                <PhoneOff className="h-3.5 w-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="top">End voice session</TooltipContent>
          </Tooltip>
        )}

        {/* Main push-to-talk / connect button */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className={`h-9 w-9 rounded-full relative ${
                disabled
                  ? "bg-muted cursor-not-allowed"
                  : isActive
                  ? `${state.color} text-white hover:${state.color}/90`
                  : state.icon === "error"
                  ? "bg-red-100 text-red-600"
                  : "hover:bg-primary/20"
              }`}
              disabled={disabled}
              onClick={() => {
                if (disabled) {
                  setShowDisabledTooltip(true);
                  setTimeout(() => setShowDisabledTooltip(false), 2000);
                  return;
                }
                handleClick();
              }}
            >
              {/* Pulse animation when active */}
              {isActive && !disabled && (
                <>
                  <span className={`absolute inset-0 rounded-full ${state.pulseColor} animate-ping opacity-75`} />
                  <span className={`absolute inset-0 rounded-full ${state.pulseColor} animate-pulse opacity-50`} />
                </>
              )}
              <span className="relative z-10">
                {renderIcon()}
              </span>
            </Button>
          </TooltipTrigger>
          <TooltipContent side="top">
            {disabled
              ? (disabledMessage || "Disabled")
              : state.label
            }
          </TooltipContent>
        </Tooltip>
      </div>
    </>
  );
}
