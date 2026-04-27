"use client";

import { Zap } from "lucide-react";
import { GardenLogEntry } from "@/lib/garden/types";
import { formatTimeAgo } from "@/lib/garden/calculations";

interface LastActionProps {
  log: GardenLogEntry[];
}

export default function LastAction({ log }: LastActionProps) {
  const last = log.length > 0 ? log[log.length - 1] : null;

  // Extract the meaningful action, skip headers like "Garden Autopilot Summary"
  const lines = last?.summary
    ?.replace(/\*\*/g, "")
    ?.replace(/^#+\s*/gm, "")
    ?.split("\n")
    ?.filter(l => l.trim())
    ?.filter(l => !l.match(/^(garden|summary|status|update|report|observations?|readings?|environmental|conditions?|sensor)/i)) || [];

  // Find lines that describe actions or key data
  const actionLine = lines.find(l =>
    l.match(/(irrigat|water|valve|fan|light|humid|moisture|temp|no action|condition|optimal|healthy)/i)
  ) || lines[0] || last?.summary || "";

  return (
    <div className="rounded-xl p-4 flex flex-col justify-between" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
      <div className="flex items-center gap-2">
        <Zap className="w-3.5 h-3.5" style={{ color: "hsl(220, 10%, 50%)" }} />
        <span className="text-[11px] uppercase tracking-wider font-medium" style={{ color: "hsl(220, 10%, 50%)" }}>Last Action</span>
      </div>
      {last ? (
        <div className="mt-2">
          <p className="text-xs leading-relaxed line-clamp-3" style={{ color: "hsl(220, 10%, 75%)" }}>
            {actionLine.replace(/^[-•]\s*/, "").trim().slice(0, 150)}
          </p>
          <span className="text-[10px] mt-1 block" style={{ color: "hsl(220, 10%, 40%)" }}>
            {formatTimeAgo(last.timestamp)}
          </span>
        </div>
      ) : (
        <span className="text-xs mt-2" style={{ color: "hsl(220, 10%, 35%)" }}>No actions yet</span>
      )}
    </div>
  );
}
