"use client";

import { MessageSquare, Mic, Bot } from "lucide-react";
import { VoiceLogEntry } from "@/lib/garden/types";
import { formatTimeAgo } from "@/lib/garden/calculations";

interface VoiceConversationTileProps {
  entries: VoiceLogEntry[];
  liveUser?: string;
  liveAgent?: string;
}

export default function VoiceConversationTile({ entries, liveUser, liveAgent }: VoiceConversationTileProps) {
  const sorted = [...entries].reverse(); // newest first
  const hasLive = liveUser || liveAgent;

  return (
    <div
      className="rounded-xl p-3 md:p-4 flex flex-col"
      style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}
    >
      <div className="flex items-center gap-2 mb-3">
        <MessageSquare className="w-4 h-4" style={{ color: "hsl(152, 75%, 50%)" }} />
        <span className="text-[11px] uppercase tracking-wider font-medium" style={{ color: "hsl(220, 10%, 50%)" }}>
          Voice Conversations
        </span>
        {entries.length > 0 && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full ml-auto" style={{ background: "hsl(220, 15%, 16%)", color: "hsl(220, 10%, 50%)" }}>
            {entries.length}
          </span>
        )}
      </div>

      <div className="space-y-3 overflow-y-auto max-h-64">
        {/* Live turn — shown at top while processing */}
        {hasLive && (
          <div className="rounded-lg p-2 space-y-2" style={{ background: "hsl(152, 75%, 50%, 0.05)", border: "1px solid hsl(152, 75%, 50%, 0.15)" }}>
            {liveUser && (
              <div className="flex items-start gap-2">
                <Mic className="w-3 h-3 mt-0.5 shrink-0 animate-pulse" style={{ color: "hsl(0, 85%, 60%)" }} />
                <p className="text-[11px] leading-relaxed" style={{ color: "hsl(220, 10%, 75%)" }}>{liveUser}</p>
              </div>
            )}
            {liveAgent && (
              <div className="flex items-start gap-2">
                <Bot className="w-3 h-3 mt-0.5 shrink-0" style={{ color: "hsl(152, 75%, 50%)" }} />
                <p className="text-[11px] leading-relaxed" style={{ color: "hsl(220, 10%, 60%)" }}>{liveAgent}</p>
              </div>
            )}
          </div>
        )}

        {/* Historical entries */}
        {sorted.length === 0 && !hasLive && (
          <p className="text-[11px]" style={{ color: "hsl(220, 10%, 35%)" }}>
            No voice conversations yet — tap the mic to start.
          </p>
        )}

        {sorted.map((entry, i) => (
          <div key={`${entry.timestamp}-${i}`} className="space-y-1.5">
            <span className="text-[10px]" style={{ color: "hsl(220, 10%, 35%)" }}>
              {formatTimeAgo(entry.timestamp)}
            </span>
            <div className="flex items-start gap-2">
              <Mic className="w-3 h-3 mt-0.5 shrink-0" style={{ color: "hsl(220, 10%, 45%)" }} />
              <p className="text-[11px] leading-relaxed" style={{ color: "hsl(220, 10%, 65%)" }}>{entry.user}</p>
            </div>
            <div className="flex items-start gap-2">
              <Bot className="w-3 h-3 mt-0.5 shrink-0" style={{ color: "hsl(152, 75%, 45%)" }} />
              <p className="text-[11px] leading-relaxed" style={{ color: "hsl(220, 10%, 55%)" }}>{entry.agent}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
