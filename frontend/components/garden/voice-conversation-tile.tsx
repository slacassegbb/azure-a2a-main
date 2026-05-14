"use client";

import { useEffect, useRef, useState } from "react";
import { Send, Loader2, MessageSquare, Mic } from "lucide-react";
import GardenVoiceButton from "./garden-voice-button";
import { VoiceLogEntry } from "@/lib/garden/types";
import { formatTimeAgo } from "@/lib/garden/calculations";

interface ChatMessage {
  id: string;
  role: "user" | "agent";
  text: string;
  timestamp: string;
  source: "voice" | "text";
  pending?: boolean;
}

function buildMessages(entries: VoiceLogEntry[], liveUser?: string, liveAgent?: string): ChatMessage[] {
  const msgs: ChatMessage[] = [];
  for (const e of entries) {
    msgs.push({ id: `${e.timestamp}-u`, role: "user",  text: e.user,  timestamp: e.timestamp, source: e.source ?? "voice" });
    msgs.push({ id: `${e.timestamp}-a`, role: "agent", text: e.agent, timestamp: e.timestamp, source: e.source ?? "voice" });
  }
  if (liveUser)  msgs.push({ id: "live-u", role: "user",  text: liveUser,  timestamp: new Date().toISOString(), source: "voice", pending: true });
  if (liveAgent) msgs.push({ id: "live-a", role: "agent", text: liveAgent, timestamp: new Date().toISOString(), source: "voice", pending: true });
  return msgs;
}

interface Props {
  entries: VoiceLogEntry[];
  liveUser?: string;
  liveAgent?: string;
  // voice controls (passed straight to GardenVoiceButton)
  isConnected?: boolean;
  isListening?: boolean;
  isSpeaking?: boolean;
  isProcessing?: boolean;
  isTalking?: boolean;
  isVoiceProcessing?: boolean;
  currentAgent?: string | null;
  voiceError?: string | null;
  onStartVoice?: () => void;
  onTalk?: () => void;
  onStopTalk?: () => void;
  onStopVoice?: () => void;
  onTextSent?: (user: string, agent: string) => void;
}

export default function VoiceConversationTile({
  entries, liveUser, liveAgent,
  isConnected, isListening, isSpeaking, isProcessing, isTalking, isVoiceProcessing,
  currentAgent, voiceError,
  onStartVoice, onTalk, onStopTalk, onStopVoice, onTextSent,
}: Props) {
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [localMessages, setLocalMessages] = useState<ChatMessage[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevEntriesLen = useRef(entries.length);

  // Clear local optimistic messages once they've been persisted and appear in entries
  useEffect(() => {
    if (entries.length > prevEntriesLen.current) {
      setLocalMessages([]);
      prevEntriesLen.current = entries.length;
    } else {
      prevEntriesLen.current = entries.length;
    }
  }, [entries.length]);

  const historicalMsgs = buildMessages(entries, liveUser, liveAgent);
  const allMessages = [...historicalMsgs, ...localMessages];

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [allMessages.length, liveUser, liveAgent]);

  const sendText = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    setSending(true);

    const ts = new Date().toISOString();
    const userMsg: ChatMessage = { id: `txt-u-${ts}`, role: "user", text, timestamp: ts, source: "text", pending: true };
    const agentMsg: ChatMessage = { id: `txt-a-${ts}`, role: "agent", text: "...", timestamp: ts, source: "text", pending: true };
    setLocalMessages(prev => [...prev, userMsg, agentMsg]);

    try {
      const res = await fetch("/api/garden/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: text }),
      });
      const data = await res.json();
      const agentText = data.result || "No response.";

      setLocalMessages(prev => prev.map(m =>
        m.id === `txt-a-${ts}` ? { ...m, text: agentText, pending: false } :
        m.id === `txt-u-${ts}` ? { ...m, pending: false } : m
      ));

      // Persist to voice log
      await fetch("/api/garden/voice-log", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user: text, agent: agentText, source: "text" }),
      });

      onTextSent?.(text, agentText);
    } catch {
      setLocalMessages(prev => prev.map(m =>
        m.id === `txt-a-${ts}` ? { ...m, text: "Failed to get response.", pending: false } : m
      ));
    } finally {
      setSending(false);
    }
  };


  return (
    <div className="rounded-xl flex flex-col" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)", height: "340px" }}>
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2.5 border-b shrink-0" style={{ borderColor: "hsl(220, 15%, 16%)" }}>
        <MessageSquare className="w-3.5 h-3.5" style={{ color: "hsl(152, 75%, 50%)" }} />
        <span className="text-[10px] uppercase tracking-wider font-medium" style={{ color: "hsl(220, 10%, 50%)" }}>Garden Chat</span>
        {isConnected && (
          <span className="ml-auto text-[9px] px-1.5 py-0.5 rounded-full" style={{ background: "hsl(152, 75%, 50%, 0.15)", color: "hsl(152, 75%, 50%)" }}>
            {(isListening || isSpeaking || isProcessing || isVoiceProcessing || isTalking) ? "Listening..." : "Voice on"}
          </span>
        )}
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-3 py-2 space-y-2 min-h-0">
        {allMessages.length === 0 && (
          <div className="h-full flex items-center justify-center">
            <p className="text-[11px] text-center" style={{ color: "hsl(220, 10%, 35%)" }}>
              Ask your garden anything — type or use the mic
            </p>
          </div>
        )}
        {allMessages.map(msg => (
          <div key={msg.id} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className="max-w-[80%] px-2.5 py-1.5 rounded-xl"
              style={{
                background: msg.role === "user"
                  ? "hsl(220, 15%, 20%)"
                  : "hsl(152, 40%, 12%)",
                border: `1px solid ${msg.role === "user" ? "hsl(220, 15%, 26%)" : "hsl(152, 40%, 18%)"}`,
                opacity: msg.pending ? 0.7 : 1,
              }}
            >
              <p className="text-[11px] leading-relaxed whitespace-pre-wrap" style={{ color: msg.role === "user" ? "hsl(220, 10%, 78%)" : "hsl(152, 40%, 72%)" }}>
                {msg.text}
              </p>
              <div className="flex items-center gap-1 mt-0.5">
                {msg.source === "voice"
                  ? <Mic className="w-2.5 h-2.5" style={{ color: "hsl(220, 10%, 35%)" }} />
                  : <MessageSquare className="w-2.5 h-2.5" style={{ color: "hsl(220, 10%, 35%)" }} />
                }
                <span className="text-[9px]" style={{ color: "hsl(220, 10%, 35%)" }}>
                  {formatTimeAgo(msg.timestamp)}
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Input */}
      <div className="px-3 py-2 border-t shrink-0 flex items-center gap-2" style={{ borderColor: "hsl(220, 15%, 16%)" }}>
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && !e.shiftKey && sendText()}
          placeholder="Message your garden agent..."
          className="flex-1 text-[11px] px-2.5 py-1.5 rounded-lg outline-none"
          style={{
            background: "hsl(220, 15%, 16%)",
            border: "1px solid hsl(220, 15%, 22%)",
            color: "hsl(220, 10%, 75%)",
          }}
        />
        <button
          onClick={sendText}
          disabled={!input.trim() || sending}
          className="w-7 h-7 rounded-lg flex items-center justify-center transition-colors"
          style={{
            background: input.trim() && !sending ? "hsl(152, 75%, 50%, 0.15)" : "transparent",
            color: input.trim() && !sending ? "hsl(152, 75%, 50%)" : "hsl(220, 10%, 35%)",
          }}
        >
          {sending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
        </button>
        <GardenVoiceButton
          isConnected={isConnected ?? false}
          isListening={isListening ?? false}
          isSpeaking={isSpeaking ?? false}
          isProcessing={isProcessing ?? false}
          isTalking={isTalking ?? false}
          isVoiceProcessing={isVoiceProcessing ?? false}
          currentAgent={currentAgent ?? null}
          error={voiceError ?? null}
          onStart={onStartVoice ?? (() => {})}
          onTalk={onTalk ?? (() => {})}
          onStopTalk={onStopTalk ?? (() => {})}
          onStop={onStopVoice ?? (() => {})}
        />
      </div>
    </div>
  );
}
