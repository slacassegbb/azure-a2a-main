"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useVoiceRealtime } from "@/hooks/use-voice-realtime";
import { Phone, PhoneOff, Mic, MicOff, AlertTriangle, Volume2, Loader2, X, Maximize2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

// Get API URL for voice
const API_BASE_URL = process.env.NEXT_PUBLIC_A2A_API_URL || "http://localhost:12000";

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
  onEnsureConversation?: () => Promise<string | null>;  // Callback to create conversation if needed, returns new conversation ID
  onFirstMessage?: (conversationId: string, transcript: string) => void;  // Callback when first voice message is sent (for title update)
  onNewMessage?: (message: VoiceMessage) => void;
  disabled?: boolean;
  disabledMessage?: string;
}

// Simple markdown to HTML converter
function formatMarkdown(text: string): string {
  return text
    // Headers
    .replace(/^### (.*$)/gm, '<h3 class="text-base font-semibold mt-3 mb-1">$1</h3>')
    .replace(/^## (.*$)/gm, '<h2 class="text-lg font-semibold mt-4 mb-2">$1</h2>')
    .replace(/^# (.*$)/gm, '<h1 class="text-xl font-bold mt-4 mb-2">$1</h1>')
    // Bold
    .replace(/\*\*(.*?)\*\*/g, '<strong class="font-semibold">$1</strong>')
    // Italic
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    // List items
    .replace(/^- (.*$)/gm, '<li class="ml-4">• $1</li>')
    // Line breaks
    .replace(/\n\n/g, '<br/><br/>')
    .replace(/\n/g, '<br/>');
}

export function VoiceButton({ sessionId, contextId, conversationId, onEnsureConversation, onFirstMessage, onNewMessage, disabled = false, disabledMessage }: VoiceButtonProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isVisible, setIsVisible] = useState(false);
  const [showDisabledTooltip, setShowDisabledTooltip] = useState(false);
  const [activeContextId, setActiveContextId] = useState(contextId);
  const [activeConversationId, setActiveConversationId] = useState(conversationId);
  const hideTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const lastResultRef = useRef<string>("");
  const lastTranscriptRef = useRef<string>("");
  const isNewConversationRef = useRef<boolean>(false);  // Track if this is a new conversation needing title
  const firstMessageSentRef = useRef<boolean>(false);  // Track if first message callback was fired
  
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
  
  // Clear hide timeout
  const clearHideTimeout = useCallback(() => {
    if (hideTimeoutRef.current) {
      clearTimeout(hideTimeoutRef.current);
      hideTimeoutRef.current = null;
    }
  }, []);
  
  const voice = useVoiceRealtime({
    apiUrl: API_BASE_URL,
    sessionId: sessionId,    // Session ID for agent lookup (e.g., sess_xxx)
    contextId: activeContextId,    // Full context ID for conversation tracking (may be updated after conversation creation)
    onTranscript: (text) => {
      console.log("[VoiceButton] Transcript:", text);
      lastTranscriptRef.current = text;
    },
    onResult: (result) => {
      console.log("[VoiceButton] Result:", result);
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
      console.log("[VoiceButton] Creating conversation before starting voice...");
      const newConversationId = await onEnsureConversation();
      if (newConversationId) {
        // Mark as new conversation - needs title update on first message
        isNewConversationRef.current = true;
        
        // Update the active context ID to use the new conversation
        const newContextId = `${sessionId}::${newConversationId}`;
        console.log("[VoiceButton] Using new conversation:", newContextId);
        
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
      console.log("[VoiceButton] First voice message for new conversation:", voice.transcript);
      onFirstMessage(activeConversationId, voice.transcript);
      firstMessageSentRef.current = true;
    }
  }, [voice.isConnected, voice.transcript, onFirstMessage, activeConversationId]);
  
  // Show/hide response panel and store message when done speaking
  useEffect(() => {
    // Show panel when we have a result and are speaking
    if (voice.result && voice.isSpeaking) {
      setIsVisible(true);
      clearHideTimeout();
    }
    
    // When speaking finishes, start the hide timer and save the message
    if (voice.result && !voice.isSpeaking && !voice.isProcessing && isVisible) {
      // Save to message history
      if (onNewMessage && voice.transcript && voice.result) {
        onNewMessage({
          id: crypto.randomUUID(),
          timestamp: new Date(),
          userQuery: voice.transcript,
          response: voice.result,
        });
      }
      
      // Start 5-second hide timer
      clearHideTimeout();
      hideTimeoutRef.current = setTimeout(() => {
        setIsVisible(false);
        setIsExpanded(false);
      }, 5000);
    }
    
    return () => clearHideTimeout();
  }, [voice.result, voice.isSpeaking, voice.isProcessing, voice.transcript, isVisible, onNewMessage, clearHideTimeout]);

  const handleClick = () => {
    if (voice.isConnected) {
      voice.stopConversation();
    } else {
      handleStartConversation();
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
    if (voice.isSpeaking) {
      return {
        color: "bg-purple-500",
        pulseColor: "bg-purple-400",
        icon: "speaking",
        label: "Speaking...",
      };
    }
    if (voice.isProcessing) {
      return {
        color: "bg-yellow-500",
        pulseColor: "bg-yellow-400",
        icon: "processing",
        label: voice.currentAgent ? `Contacting ${voice.currentAgent}...` : "Processing...",
      };
    }
    if (voice.isListening) {
      return {
        color: "bg-green-500",
        pulseColor: "bg-green-400",
        icon: "listening",
        label: "Listening...",
      };
    }
    if (voice.isConnected) {
      return {
        color: "bg-blue-500",
        pulseColor: "bg-blue-400",
        icon: "connected",
        label: "Connected",
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
  const isActive = voice.isConnected || voice.isListening || voice.isSpeaking || voice.isProcessing;
  
  // Show the panel if: actively processing/speaking, or visible with result, or has error
  const showPanel = voice.error || voice.isProcessing || voice.isSpeaking || isVisible;

  // Render the icon based on state
  const renderIcon = () => {
    if (disabled) {
      return <MicOff className="h-5 w-5 opacity-70" />;
    }
    switch (state.icon) {
      case "error":
        return <AlertTriangle className="h-5 w-5" />;
      case "speaking":
        return <Volume2 className="h-5 w-5" />;
      case "processing":
        return <Loader2 className="h-5 w-5 animate-spin" />;
      case "listening":
        return <Mic className="h-5 w-5" />;
      case "connected":
        return <PhoneOff className="h-5 w-5" />;
      default:
        return <Phone className="h-5 w-5" />;
    }
  };

  return (
    <>
      {/* Floating Response Panel - shows transcript, status, and results */}
      {/* Container is pointer-events-none so it doesn't block clicks on sidebar/other UI */}
      {/* Individual bubbles have pointer-events-auto so they can still be interacted with */}
      {showPanel && (voice.transcript || voice.result || voice.error || voice.isProcessing || voice.isSpeaking) && (
        <div className="fixed bottom-20 left-1/2 -translate-x-1/2 z-50 flex flex-col items-center gap-2 animate-in slide-in-from-bottom-4 pointer-events-none w-[90vw] max-w-3xl">
          
          {/* Transcript bubble - "You said:" */}
          {voice.transcript && !voice.error && (
            <div 
              className="bg-background rounded-xl shadow-xl border border-border p-4 pointer-events-auto shrink-0"
              onMouseEnter={clearHideTimeout}
              onMouseLeave={() => {
                if (voice.result && !voice.isSpeaking && !voice.isProcessing) {
                  hideTimeoutRef.current = setTimeout(() => {
                    setIsVisible(false);
                    setIsExpanded(false);
                  }, 3000);
                }
              }}
            >
              <p className="text-xs font-medium text-muted-foreground mb-0.5">You said:</p>
              <p className="text-sm text-foreground font-medium leading-snug whitespace-nowrap">{voice.transcript}</p>
            </div>
          )}
          
          {/* Error bubble */}
          {voice.error && (
            <div 
              className="bg-background rounded-xl shadow-xl border border-red-300 p-4 pointer-events-auto shrink-0"
            >
              <p className="text-sm text-red-500">{voice.error}</p>
            </div>
          )}
          
          {/* Status indicator - Processing/Speaking */}
          {(voice.isProcessing || voice.isSpeaking) && !voice.result && (
            <div className="bg-background rounded-full shadow-lg border border-border px-4 py-2 flex items-center gap-2 pointer-events-auto">
              {voice.isProcessing ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin text-yellow-500" />
                  <span className="text-sm font-medium text-foreground">
                    {voice.currentAgent ? `Contacting ${voice.currentAgent}...` : "Processing..."}
                  </span>
                </>
              ) : (
                <>
                  <Volume2 className="w-4 h-4 text-purple-500" />
                  <span className="text-sm font-medium text-foreground">Speaking...</span>
                </>
              )}
            </div>
          )}
          
          {/* Result bubble */}
          {voice.result && !voice.error && (
            <div 
              className={`relative bg-background rounded-xl shadow-xl border border-border p-4 pointer-events-auto w-fit max-w-full ${
                isExpanded ? 'max-h-[60vh]' : 'max-h-[40vh]'
              }`}
              onMouseEnter={clearHideTimeout}
              onMouseLeave={() => {
                if (!voice.isSpeaking && !voice.isProcessing) {
                  hideTimeoutRef.current = setTimeout(() => {
                    setIsVisible(false);
                    setIsExpanded(false);
                  }, 3000);
                }
              }}
            >
              {/* Expand button */}
              <button
                onClick={() => setIsExpanded(!isExpanded)}
                className="absolute top-2 right-2 p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted rounded-md transition-colors"
                title={isExpanded ? "Minimize" : "Expand"}
              >
                {isExpanded ? (
                  <X className="w-4 h-4" />
                ) : (
                  <Maximize2 className="w-4 h-4" />
                )}
              </button>
              
              <div className={`overflow-y-auto pr-6 ${isExpanded ? 'max-h-[55vh]' : 'max-h-[35vh]'}`}>
                <p className="text-xs font-medium text-muted-foreground mb-1">Result:</p>
                <div 
                  className="text-sm text-muted-foreground leading-relaxed [&_h1]:text-base [&_h1]:font-semibold [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:text-sm [&_h3]:font-medium [&_strong]:font-semibold [&_li]:ml-3"
                  dangerouslySetInnerHTML={{ __html: formatMarkdown(voice.result) }}
                />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Voice Button */}
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
            onClick={(e) => {
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
    </>
  );
}
