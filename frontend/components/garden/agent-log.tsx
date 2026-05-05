"use client";

import { Activity, Ghost } from "lucide-react";
import { GardenLogEntry } from "@/lib/garden/types";
import { formatTimeAgo } from "@/lib/garden/calculations";

interface AgentLogProps {
  entries: GardenLogEntry[];
}

export default function AgentLog({ entries }: AgentLogProps) {
  const sorted = [...entries].reverse(); // newest first

  return (
    <div className="rounded-xl p-3 md:p-4 flex flex-col" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
      <div className="flex items-center gap-2 mb-3">
        <Activity className="w-4 h-4" style={{ color: "hsl(152, 75%, 50%)" }} />
        <span className="text-[11px] uppercase tracking-wider font-medium" style={{ color: "hsl(220, 10%, 50%)" }}>
          AI Agent Log
        </span>
        {entries.length > 0 && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full ml-auto" style={{ background: "hsl(220, 15%, 16%)", color: "hsl(220, 10%, 50%)" }}>
            {entries.length}
          </span>
        )}
      </div>

      {sorted.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-2" style={{ color: "hsl(220, 10%, 30%)" }}>
          <Ghost className="w-8 h-8" />
          <span className="text-xs">No activity recorded yet</span>
        </div>
      ) : (
        <div className="overflow-y-auto -mx-1 pr-2" style={{ maxHeight: "500px" }}>
          <div className="space-y-0.5">
            {sorted.map((entry, i) => {
              const cleanSummary = entry.summary
                .replace(/^#+\s*/gm, "")
                .replace(/\*\*/g, "")
                .replace(/^-\s*/gm, "• ")
                .split("\n")
                .filter(l => l.trim())
                .join("\n");

              const firstLine = cleanSummary.split("\n")[0]?.slice(0, 150) || entry.summary;

              return (
                <details
                  key={`${entry.timestamp}-${i}`}
                  className="group rounded-lg hover:bg-white/[0.03] transition-colors"
                  open={i === 0}
                >
                  <summary className="flex items-center gap-3 px-2 py-2 cursor-pointer list-none">
                    <span className="text-[10px] shrink-0 w-16 text-right" style={{ color: "hsl(220, 10%, 40%)" }}>
                      {formatTimeAgo(entry.timestamp)}
                    </span>
                    <p className="text-xs flex-1 truncate" style={{ color: "hsl(220, 10%, 70%)" }}>
                      {firstLine}
                    </p>
                    <span className="text-[10px] shrink-0 group-open:rotate-90 transition-transform" style={{ color: "hsl(220, 10%, 30%)" }}>▶</span>
                  </summary>
                  <div className="px-2 pb-2 ml-[76px]">
                    <div style={{ maxHeight: "240px", overflowY: "scroll", overscrollBehavior: "contain" }}>
                      <p className="text-[11px] leading-relaxed whitespace-pre-line" style={{ color: "hsl(220, 10%, 55%)" }}>
                        {cleanSummary}
                      </p>
                    </div>
                  </div>
                </details>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
