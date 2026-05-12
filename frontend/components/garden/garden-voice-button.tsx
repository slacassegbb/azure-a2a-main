"use client";

import { Mic, Volume2, Loader2, Phone, PhoneOff, AlertTriangle } from "lucide-react";

interface GardenVoiceButtonProps {
  isConnected: boolean;
  isListening: boolean;
  isSpeaking: boolean;
  isProcessing: boolean;
  isTalking: boolean;
  isVoiceProcessing: boolean;
  currentAgent: string | null;
  error: string | null;
  onStart: () => void;
  onTalk: () => void;
  onStopTalk: () => void;
  onStop: () => void;
}

export default function GardenVoiceButton({
  isConnected, isSpeaking, isProcessing, isTalking, isVoiceProcessing,
  currentAgent, error, onStart, onTalk, onStopTalk, onStop,
}: GardenVoiceButtonProps) {
  const handleClick = () => {
    if (!isConnected) { onStart(); return; }
    if (isTalking) { onStopTalk(); } else { onTalk(); }
  };

  const getState = () => {
    if (error) return { color: "hsl(0, 85%, 60%)", icon: "error", label: "Error — tap to retry" };
    if (isTalking) return { color: "hsl(0, 85%, 60%)", icon: "talking", label: "Listening..." };
    if (isSpeaking) return { color: "hsl(270, 65%, 60%)", icon: "speaking", label: "Speaking..." };
    if (isProcessing || isVoiceProcessing) return {
      color: "hsl(48, 95%, 55%)", icon: "processing",
      label: currentAgent ? `${currentAgent}...` : "Processing...",
    };
    if (isConnected) return { color: "hsl(152, 75%, 50%)", icon: "ready", label: "Tap to talk" };
    return { color: "hsl(220, 10%, 45%)", icon: "idle", label: "Voice" };
  };

  const state = getState();

  const renderIcon = () => {
    switch (state.icon) {
      case "error": return <AlertTriangle className="w-3.5 h-3.5" />;
      case "talking": return <Mic className="w-3.5 h-3.5 animate-pulse" />;
      case "speaking": return <Volume2 className="w-3.5 h-3.5" />;
      case "processing": return <Loader2 className="w-3.5 h-3.5 animate-spin" />;
      case "ready": return <Mic className="w-3.5 h-3.5" />;
      default: return <Phone className="w-3.5 h-3.5" />;
    }
  };

  return (
    <div className="flex items-center gap-1.5">
      {isConnected && (
        <span className="text-[10px] hidden sm:block" style={{ color: state.color }}>
          {state.label}
        </span>
      )}
      <button
        onClick={handleClick}
        title={state.label}
        className="w-7 h-7 rounded-lg flex items-center justify-center transition-all hover:bg-white/5 relative"
        style={{ color: state.color }}
      >
        {isConnected && (
          <span className="absolute inset-0 rounded-lg opacity-20 animate-pulse" style={{ background: state.color }} />
        )}
        <span className="relative z-10">{renderIcon()}</span>
      </button>
      {isConnected && (
        <button
          onClick={onStop}
          title="End voice session"
          className="w-7 h-7 rounded-lg flex items-center justify-center transition-all hover:bg-white/5"
          style={{ color: "hsl(0, 85%, 60%)" }}
        >
          <PhoneOff className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
}
