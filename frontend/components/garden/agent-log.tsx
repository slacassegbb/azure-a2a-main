"use client";

import { ScrollArea } from "@/components/ui/scroll-area";
import { Activity, Ghost } from "lucide-react";
import { GardenLogEntry } from "@/lib/garden/types";
import { formatTimeAgo } from "@/lib/garden/calculations";

interface AgentLogProps {
  entries: GardenLogEntry[];
}

function getEntryColor(summary: string): string {
  const s = summary.toLowerCase();
  if (s.includes("irrigat") || s.includes("water") || s.includes("valve")) return "hsl(185, 90%, 55%)";
  if (s.includes("light") || s.includes("brightness") || s.includes("sunrise")) return "hsl(48, 95%, 65%)";
  if (s.includes("fan") || s.includes("ventilat")) return "hsl(185, 70%, 55%)";
  if (s.includes("humid")) return "hsl(270, 70%, 65%)";
  if (s.includes("warn") || s.includes("error") || s.includes("fail")) return "hsl(25, 95%, 55%)";
  return "hsl(152, 75%, 50%)";
}

export default function AgentLog({ entries }: AgentLogProps) {
  const sorted = [...entries].reverse(); // newest first

  return (
    <div className="rounded-xl p-4 flex flex-col" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)", minHeight: "280px" }}>
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
        <ScrollArea className="flex-1 -mx-1 pr-2" style={{ maxHeight: "320px" }}>
          <div className="space-y-1">
            {sorted.map((entry, i) => {
              const color = getEntryColor(entry.summary);
              // Clean up markdown headers and extract meaningful content
              const cleanSummary = entry.summary
                .replace(/^#+\s*/gm, "")
                .replace(/\*\*/g, "")
                .replace(/^-\s*/gm, "• ")
                .split("\n")
                .filter(l => l.trim())
                .join("\n");
              return (
                <details
                  key={`${entry.timestamp}-${i}`}
                  className="group rounded-lg hover:bg-white/[0.02] transition-colors"
                  style={{ borderLeft: `2px solid ${color}` }}
                >
                  <summary className="flex gap-3 px-2 py-2 cursor-pointer list-none">
                    <div className="shrink-0 pt-0.5">
                      <span className="text-[10px] whitespace-nowrap" style={{ color: "hsl(220, 10%, 40%)" }}>
                        {formatTimeAgo(entry.timestamp)}
                      </span>
                    </div>
                    <p className="text-xs leading-relaxed line-clamp-2 flex-1" style={{ color: "hsl(220, 10%, 70%)" }}>
                      {cleanSummary.split("\n")[0]?.slice(0, 150)}
                    </p>
                    <span className="text-[10px] shrink-0 pt-0.5 group-open:rotate-90 transition-transform" style={{ color: "hsl(220, 10%, 35%)" }}>▶</span>
                  </summary>
                  <div className="px-2 pb-2 ml-[70px]">
                    <p className="text-[11px] leading-relaxed whitespace-pre-line" style={{ color: "hsl(220, 10%, 60%)" }}>
                      {cleanSummary}
                    </p>
                  </div>
                </details>
              );
            })}
          </div>
        </ScrollArea>
      )}
    </div>
  );
}
