"use client";

import { useState } from "react";
import { Droplets, Loader2 } from "lucide-react";
import { DURATION_OPTIONS } from "@/lib/garden/constants";

interface IrrigationTileProps {
  onRefresh: () => void;
}

const VALVES = [
  { key: "a", label: "Water", emoji: "💧", color: "hsl(185, 90%, 55%)", level: null as number | null },
  { key: "b", label: "Grow", emoji: "🌱", color: "hsl(152, 75%, 50%)", level: null as number | null },
  { key: "c", label: "Bloom", emoji: "🌸", color: "hsl(330, 80%, 65%)", level: null as number | null },
];

async function sendControl(action: string, params: Record<string, any>) {
  await fetch("/api/garden/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, ...params }),
  });
}

export default function IrrigationTile({ onRefresh }: IrrigationTileProps) {
  const [duration, setDuration] = useState(120);
  const [loading, setLoading] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const irrigate = async (valve: string) => {
    setLoading(valve);
    setSuccess(null);
    try {
      await sendControl("irrigate_valve", { valve, duration_seconds: duration });
      setSuccess(valve);
      setTimeout(() => setSuccess(null), 2000);
      setTimeout(onRefresh, 3000);
    } catch { /* ignore */ }
    finally { setLoading(null); }
  };

  return (
    <div className="rounded-xl p-3 md:p-4 flex flex-col h-full" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Droplets className="w-4 h-4" style={{ color: "hsl(185, 90%, 55%)", opacity: 0.8 }} />
          <span className="text-[11px] uppercase tracking-wider font-medium" style={{ color: "hsl(220, 10%, 50%)" }}>
            Irrigation
          </span>
        </div>
        <select
          value={duration}
          onChange={(e) => setDuration(Number(e.target.value))}
          className="text-[10px] xl:text-xs rounded-md px-1.5 py-0.5 border-0 outline-none touch-manipulation"
          style={{ background: "hsl(220, 15%, 16%)", color: "hsl(220, 10%, 65%)" }}
        >
          {DURATION_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>

      {/* 3 Reservoirs */}
      <div className="flex gap-2 flex-1 min-h-0">
        {VALVES.map(v => {
          const isLoading = loading === v.key;
          const isSuccess = success === v.key;
          const level = v.level ?? 0.7;

          return (
            <div key={v.key} className="flex-1 flex flex-col items-center gap-1">
              {/* Reservoir graphic */}
              <div className="relative w-full flex-1 min-h-0">
                <svg viewBox="0 0 40 60" className="w-full h-full" preserveAspectRatio="xMidYMid meet">
                  <rect x="4" y="2" width="32" height="56" rx="4" ry="4"
                    fill="none" stroke="hsl(220, 15%, 22%)" strokeWidth="1.5" />
                  <rect
                    x="5" y={3 + (1 - level) * 54}
                    width="30" height={level * 54}
                    rx="3" ry="3"
                    fill={v.color} opacity={0.3}
                  />
                  <line
                    x1="5" y1={3 + (1 - level) * 54}
                    x2="35" y2={3 + (1 - level) * 54}
                    stroke={v.color} strokeWidth="1.5" opacity={0.7}
                  />
                  <text x="20" y="35" textAnchor="middle" fontSize="10" fontWeight="600"
                    fill={v.level !== null ? "white" : "hsl(220, 10%, 35%)"}>
                    {v.level !== null ? `${Math.round(v.level * 100)}%` : "—"}
                  </text>
                </svg>
              </div>

              {/* Label */}
              <span className="text-[9px] xl:text-[10px] font-medium" style={{ color: "hsl(220, 10%, 55%)" }}>
                {v.emoji} {v.label}
              </span>

              {/* Irrigate button */}
              <button
                onClick={() => irrigate(v.key)}
                disabled={isLoading}
                className="w-full py-1 xl:py-1.5 rounded text-[9px] xl:text-[10px] font-semibold transition-all active:scale-95 touch-manipulation"
                style={{
                  background: isSuccess ? "hsl(152, 75%, 50%, 0.25)" : `${v.color}15`,
                  border: `1px solid ${isSuccess ? "hsl(152, 75%, 50%)" : v.color}40`,
                  color: isSuccess ? "hsl(152, 75%, 50%)" : v.color,
                }}
              >
                {isLoading ? <Loader2 className="w-3 h-3 animate-spin mx-auto" /> : isSuccess ? "✓" : "Irrigate"}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
