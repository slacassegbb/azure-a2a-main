"use client";

import { useState } from "react";
import { DURATION_OPTIONS } from "@/lib/garden/constants";

interface IrrigationTileProps {
  onRefresh: () => void;
}

const VALVES = [
  { key: "a", label: "Water",  emoji: "💧", hue: 185, sat: "90%", lit: "55%" },
  { key: "b", label: "Grow",   emoji: "🌱", hue: 152, sat: "75%", lit: "50%" },
  { key: "c", label: "Bloom",  emoji: "🌸", hue: 330, sat: "80%", lit: "65%" },
];

function hsl(hue: number, sat: string, lit: string, a = 1) {
  return a < 1 ? `hsla(${hue},${sat},${lit},${a})` : `hsl(${hue},${sat},${lit})`;
}

/** Cartoon droplet + wave bottle graphic */
function ZoneBottle({ hue, sat, lit, loading, success }: { hue: number; sat: string; lit: string; loading: boolean; success: boolean }) {
  const c = hsl(hue, sat, lit);
  const cDim = hsl(hue, sat, lit, 0.18);
  const cMid = hsl(hue, sat, lit, 0.55);
  const fillY = 38; // fixed decorative level

  return (
    <svg viewBox="0 0 52 80" className="w-full" style={{ display: "block", overflow: "visible" }}>
      <defs>
        <clipPath id={`bottle-clip-${hue}`}>
          {/* neck */}
          <rect x="18" y="6" width="16" height="10" rx="3" />
          {/* body */}
          <rect x="8" y="15" width="36" height="56" rx="8" />
        </clipPath>
        <linearGradient id={`shine-${hue}`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="white" stopOpacity="0.18" />
          <stop offset="40%" stopColor="white" stopOpacity="0.06" />
          <stop offset="100%" stopColor="white" stopOpacity="0" />
        </linearGradient>
      </defs>

      {/* Bottle body outline */}
      <rect x="18" y="5" width="16" height="11" rx="3"
        fill={cDim} stroke={hsl(hue, sat, lit, 0.35)} strokeWidth="1.5" />
      <rect x="8" y="14" width="36" height="57" rx="9"
        fill={cDim} stroke={hsl(hue, sat, lit, 0.35)} strokeWidth="1.5" />

      {/* Liquid fill */}
      <g clipPath={`url(#bottle-clip-${hue})`}>
        <rect x="6" y={fillY} width="42" height="40" fill={cMid} />
        {/* Wave 1 */}
        <path d={`M6,${fillY} Q17,${fillY - 5} 26,${fillY} Q37,${fillY + 5} 48,${fillY} L48,80 L6,80 Z`}
          fill={c} opacity={0.45}>
          <animateTransform attributeName="transform" type="translate"
            values="-8 0; 8 0; -8 0" dur="3.2s" repeatCount="indefinite" />
        </path>
        {/* Wave 2 */}
        <path d={`M6,${fillY + 3} Q20,${fillY - 2} 26,${fillY + 3} Q34,${fillY + 8} 48,${fillY + 3} L48,80 L6,80 Z`}
          fill={c} opacity={0.3}>
          <animateTransform attributeName="transform" type="translate"
            values="6 0; -6 0; 6 0" dur="2.4s" repeatCount="indefinite" />
        </path>
        {/* Shine overlay */}
        <rect x="6" y={fillY} width="42" height="40" fill={`url(#shine-${hue})`} />
      </g>

      {/* Bottle shine streak */}
      <rect x="13" y="18" width="4" height="26" rx="2"
        fill="white" opacity={0.09} />

      {/* Droplet at spout (animated when loading) */}
      {loading && (
        <ellipse cx="26" cy="3" rx="3.5" ry="4" fill={c} opacity={0.9}>
          <animate attributeName="cy" values="3; 12; 3" dur="0.8s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.9; 0.2; 0.9" dur="0.8s" repeatCount="indefinite" />
        </ellipse>
      )}
      {success && (
        <text x="26" y="5" textAnchor="middle" fontSize="10">✅</text>
      )}
    </svg>
  );
}

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
    <div className="rounded-2xl flex flex-col h-full overflow-hidden"
      style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>

      {/* Header */}
      <div className="flex items-center justify-between px-3 pt-3 pb-2">
        <div className="flex items-center gap-1.5">
          <span style={{ fontSize: 14 }}>🚿</span>
          <span className="text-[11px] uppercase tracking-wider font-semibold"
            style={{ color: "hsl(220, 10%, 50%)" }}>Irrigation</span>
        </div>
        <select
          value={duration}
          onChange={(e) => setDuration(Number(e.target.value))}
          className="text-[10px] rounded-lg px-2 py-0.5 border-0 outline-none touch-manipulation font-semibold"
          style={{ background: "hsl(220, 15%, 17%)", color: "hsl(220, 10%, 65%)", border: "1px solid hsl(220,15%,22%)" }}
        >
          {DURATION_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>

      {/* Zone cards */}
      <div className="flex gap-2 flex-1 min-h-0 px-3 pb-3">
        {VALVES.map(v => {
          const isLoading = loading === v.key;
          const isSuccess = success === v.key;
          const c = hsl(v.hue, v.sat, v.lit);
          const cBg = hsl(v.hue, v.sat, v.lit, 0.07);
          const cBorder = hsl(v.hue, v.sat, v.lit, 0.25);

          return (
            <div key={v.key} className="flex-1 flex flex-col items-center gap-1.5 rounded-xl py-2 px-1"
              style={{ background: cBg, border: `1.5px solid ${cBorder}` }}>

              {/* Bottle graphic */}
              <div className="w-full px-1" style={{ maxWidth: 52 }}>
                <ZoneBottle hue={v.hue} sat={v.sat} lit={v.lit} loading={isLoading} success={isSuccess} />
              </div>

              {/* Zone name */}
              <div className="text-center">
                <div style={{ fontSize: 13 }}>{v.emoji}</div>
                <div className="text-[9px] font-bold tracking-wide mt-0.5" style={{ color: c }}>{v.label}</div>
              </div>

              {/* Irrigate button */}
              <button
                onClick={() => irrigate(v.key)}
                disabled={isLoading}
                className="w-full py-1 rounded-lg text-[9px] font-bold tracking-wide transition-all active:scale-95 touch-manipulation mt-auto"
                style={{
                  background: isSuccess ? hsl(152, "75%", "50%", 0.2) : hsl(v.hue, v.sat, v.lit, 0.18),
                  border: `1.5px solid ${isSuccess ? hsl(152, "75%", "50%", 0.7) : hsl(v.hue, v.sat, v.lit, 0.5)}`,
                  color: isSuccess ? "hsl(152,75%,55%)" : c,
                  letterSpacing: "0.05em",
                }}
              >
                {isLoading ? "…" : isSuccess ? "✓" : "Irrigate"}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
