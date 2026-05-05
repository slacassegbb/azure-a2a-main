"use client";

import { useState, useRef, useEffect } from "react";
import { Loader2, Pencil, RotateCcw } from "lucide-react";
import { GardenConfig, PotConfig } from "@/lib/garden/types";

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function statusInfo(waterPct: number | null, hasDry: boolean, hasWet: boolean) {
  if (waterPct != null) {
    if (waterPct <= 10) return { text: "Thirsty! 🥵",   color: "#ff4d4d", bg: "rgba(255,77,77,0.12)",   bar: "#ff4d4d" };
    if (waterPct <= 30) return { text: "Getting dry 🏜",  color: "#ff9f43", bg: "rgba(255,159,67,0.12)",  bar: "#ff9f43" };
    if (waterPct <= 70) return { text: "Feeling good 😊", color: "#26de81", bg: "rgba(38,222,129,0.12)",  bar: "#20bf6b" };
    return                     { text: "Well watered 💧", color: "#45aaf2", bg: "rgba(69,170,242,0.12)",  bar: "#2d98da" };
  }
  if (!hasDry && !hasWet) return { text: "① Set dry weight", color: "#a29bfe", bg: "rgba(162,155,254,0.1)", bar: "#a29bfe" };
  if (hasDry && !hasWet)  return { text: "② Now set wet",    color: "#74b9ff", bg: "rgba(116,185,255,0.1)", bar: "#74b9ff" };
  return                         { text: "Calibrated ✓",     color: "#26de81", bg: "rgba(38,222,129,0.1)",  bar: "#20bf6b" };
}

// Cartoon pot SVG with animated water fill
function CartoonPot({ pot, weightG, flash }: { pot: PotConfig; weightG: number | null; flash: boolean }) {
  const dry = pot.dry_weight_g;
  const wet = pot.wet_weight_g;
  const hasRange = dry != null && wet != null && wet > dry;
  const waterPct = hasRange && weightG != null
    ? Math.min(100, Math.max(0, ((weightG - dry!) / (wet! - dry!)) * 100))
    : null;

  // Water fill height inside pot (the pot fill area goes from y=22 to y=72, height=50)
  const fillH = waterPct != null ? (waterPct / 100) * 50 : 0;
  const fillY = 72 - fillH;

  // Water color based on level
  const waterColor = waterPct == null ? "#4a3728"
    : waterPct <= 10  ? "#c0392b"
    : waterPct <= 30  ? "#e67e22"
    : waterPct <= 70  ? "#27ae60"
    : "#2980b9";

  const waterLight = waterPct == null ? "#5a4738"
    : waterPct <= 10  ? "#e74c3c"
    : waterPct <= 30  ? "#f39c12"
    : waterPct <= 70  ? "#2ecc71"
    : "#3498db";

  return (
    <svg viewBox="0 0 72 88" className="w-full h-full" style={{ filter: flash ? "drop-shadow(0 0 6px rgba(69,170,242,0.8))" : "none", transition: "filter 0.5s" }}>
      <defs>
        <clipPath id={`pot-clip-${pot.id}`}>
          <path d="M14 20 L10 72 Q10 78 17 78 L55 78 Q62 78 62 72 L58 20 Z" />
        </clipPath>
        <linearGradient id={`pot-body-${pot.id}`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%"   stopColor="#7d4e2a" />
          <stop offset="40%"  stopColor="#a0623a" />
          <stop offset="100%" stopColor="#6b3e20" />
        </linearGradient>
        <linearGradient id={`water-grad-${pot.id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor={waterLight} />
          <stop offset="100%" stopColor={waterColor} />
        </linearGradient>
        <linearGradient id={`soil-grad-${pot.id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor="#5c3d1e" />
          <stop offset="100%" stopColor="#3d2710" />
        </linearGradient>
      </defs>

      {/* Pot body */}
      <path d="M14 20 L10 72 Q10 78 17 78 L55 78 Q62 78 62 72 L58 20 Z"
        fill={`url(#pot-body-${pot.id})`} stroke="#4a2e10" strokeWidth="1.5" />

      {/* Soil base */}
      <rect x="10" y="22" width="52" height="52"
        fill={`url(#soil-grad-${pot.id})`} clipPath={`url(#pot-clip-${pot.id})`} />

      {/* Water fill */}
      {fillH > 0 && (
        <g clipPath={`url(#pot-clip-${pot.id})`}>
          <rect x="10" y={fillY} width="52" height={fillH + 2}
            fill={`url(#water-grad-${pot.id})`} opacity={0.85} />
          {/* Wave on top of water */}
          <path d={`M10,${fillY} Q22,${fillY - 3} 36,${fillY} Q50,${fillY + 3} 62,${fillY} L62,${fillY + 4} Q50,${fillY + 7} 36,${fillY + 4} Q22,${fillY + 1} 10,${fillY + 4} Z`}
            fill={waterLight} opacity={0.5}>
            <animateTransform attributeName="transform" type="translate"
              values="0 0; 4 0; 0 0" dur="3s" repeatCount="indefinite" />
          </path>
        </g>
      )}

      {/* Pot rim */}
      <rect x="9" y="14" width="54" height="9" rx="4"
        fill={`url(#pot-body-${pot.id})`} stroke="#4a2e10" strokeWidth="1.5" />
      {/* Rim highlight */}
      <rect x="10" y="15" width="52" height="3" rx="2" fill="rgba(255,255,255,0.12)" />

      {/* Weight text */}
      <text x="36" y="54" textAnchor="middle" fill="white" fontSize="10" fontWeight="700"
        style={{ textShadow: "0 1px 3px rgba(0,0,0,0.8)" }}>
        {weightG != null ? `${Math.round(weightG)}g` : "—"}
      </text>
      {waterPct != null && (
        <text x="36" y="66" textAnchor="middle" fill="rgba(255,255,255,0.75)" fontSize="8.5" fontWeight="600">
          {Math.round(waterPct)}%
        </text>
      )}

      {/* Little plant sprout on top */}
      <g opacity={waterPct != null && waterPct > 20 ? 1 : 0.35}>
        <line x1="36" y1="14" x2="36" y2="4" stroke="#2d8a3e" strokeWidth="1.8" strokeLinecap="round" />
        <ellipse cx="31" cy="8" rx="5" ry="3" fill="#3aaf52" transform="rotate(-30 31 8)" />
        <ellipse cx="41" cy="7" rx="5" ry="3" fill="#2d8a3e" transform="rotate(30 41 7)" />
      </g>
    </svg>
  );
}

interface PotWeightTileProps {
  config: GardenConfig | null;
  scaleWeights: { id: string; weightG: number | null }[];
  onSetWeight: (potId: string, type: "dry" | "wet") => Promise<void>;
  onRenamePot: (potId: string, name: string) => Promise<void>;
  onResetCalibration: (potId: string) => Promise<void>;
  onTare: (scaleId: string) => Promise<void>;
}

export default function PotWeightTile({ config, scaleWeights, onSetWeight, onRenamePot, onResetCalibration, onTare }: PotWeightTileProps) {
  const [loading, setLoading]               = useState<string | null>(null);
  const [editingName, setEditingName]       = useState<string | null>(null);
  const [nameInput, setNameInput]           = useState("");
  const [showCalibration, setShowCalibration] = useState<string | null>(null);
  const [flash, setFlash]                   = useState(false);
  const prevValsRef                         = useRef<string | null>(null);

  const potConfigs = config?.pots || [];
  const scalePots  = scaleWeights.map(s => ({
    scale: s,
    pot: potConfigs.find(p => p.id === s.id)
      ?? { id: s.id, name: `Pot ${s.id.replace("scale_", "")}`, dry_weight_g: null, wet_weight_g: null, dry_set_at: null, wet_set_at: null } as PotConfig,
  }));

  const firstPot = scalePots[0]?.pot;
  const valsKey  = firstPot ? `${firstPot.dry_weight_g}-${firstPot.wet_weight_g}` : null;
  useEffect(() => {
    if (prevValsRef.current !== null && valsKey !== null && valsKey !== prevValsRef.current && loading === null) {
      setFlash(true);
      const t = setTimeout(() => setFlash(false), 2000);
      return () => clearTimeout(t);
    }
    prevValsRef.current = valsKey;
  }, [valsKey, loading]);

  const handleSetWeight = async (potId: string, type: "dry" | "wet") => {
    setLoading(`${potId}-${type}`);
    try { await onSetWeight(potId, type); } finally { setLoading(null); }
  };
  const handleRename = async (potId: string) => {
    if (!nameInput.trim()) return;
    setLoading("rename");
    try { await onRenamePot(potId, nameInput.trim()); setEditingName(null); } finally { setLoading(null); }
  };
  const handleReset = async (potId: string) => {
    setLoading("reset");
    try { await onResetCalibration(potId); setShowCalibration(null); } finally { setLoading(null); }
  };
  const handleTare = async (scaleId: string) => {
    setLoading(`tare-${scaleId}`);
    try { await onTare(scaleId); } finally { setLoading(null); }
  };

  if (scalePots.length === 0) return (
    <div className="rounded-2xl px-4 py-3" style={{ background: "hsl(220,18%,11%)", border: "1px solid hsl(220,15%,16%)" }}>
      <span className="text-xs" style={{ color: "hsl(220,10%,35%)" }}>⚖️ Scale offline</span>
    </div>
  );

  return (
    <div className="rounded-2xl p-3 space-y-3" style={{ background: "hsl(220,18%,11%)", border: "1px solid hsl(220,15%,16%)" }}>
      {scalePots.map(({ scale, pot }) => {
        const dry          = pot.dry_weight_g;
        const wet          = pot.wet_weight_g;
        const isCalibrated = dry != null && wet != null && wet > dry;
        const hasDry       = dry != null;
        const hasWet       = wet != null;
        const waterPct     = isCalibrated && scale.weightG != null
          ? Math.min(100, Math.max(0, Math.round(((scale.weightG - dry!) / (wet! - dry!)) * 100)))
          : null;
        const status       = statusInfo(waterPct, hasDry, hasWet);
        const displayName  = pot.name && !pot.name.startsWith("scale_") ? pot.name : `Pot ${pot.id.replace("scale_", "")}`;

        return (
          <div key={pot.id} className="rounded-xl p-3 flex gap-3"
            style={{ background: "hsl(220,18%,13%)", border: `1px solid ${status.color}22` }}>

            {/* Cartoon pot */}
            <div className="shrink-0 flex flex-col items-center gap-1" style={{ width: 64 }}>
              <div style={{ width: 64, height: 76 }}>
                <CartoonPot pot={pot} weightG={scale.weightG} flash={flash} />
              </div>
            </div>

            {/* Right side */}
            <div className="flex-1 min-w-0 flex flex-col gap-2">

              {/* Name row */}
              {editingName === pot.id ? (
                <div className="flex gap-1 items-center">
                  <input type="text" value={nameInput} onChange={e => setNameInput(e.target.value)}
                    onKeyDown={e => e.key === "Enter" && handleRename(pot.id)} autoFocus
                    className="flex-1 px-2 py-1 rounded-lg text-xs outline-none"
                    style={{ background: "hsl(220,15%,18%)", border: "1px solid hsl(220,15%,28%)", color: "white" }} />
                  <button onClick={() => handleRename(pot.id)} className="text-xs px-2 py-1 rounded-lg font-bold"
                    style={{ background: "#26de8122", color: "#26de81" }}>
                    {loading === "rename" ? <Loader2 className="w-3 h-3 animate-spin" /> : "✓"}
                  </button>
                  <button onClick={() => setEditingName(null)} className="text-xs px-2 py-1 rounded-lg"
                    style={{ color: "hsl(220,10%,45%)" }}>✕</button>
                </div>
              ) : (
                <div className="flex items-center gap-2 flex-wrap">
                  <button onClick={() => { setEditingName(pot.id); setNameInput(pot.name || pot.id); }}
                    className="flex items-center gap-1 font-bold text-sm hover:opacity-80" style={{ color: "white" }}>
                    {displayName}
                    <Pencil className="w-3 h-3" style={{ color: "hsl(220,10%,40%)" }} />
                  </button>
                  {/* Status badge */}
                  <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
                    style={{ background: status.bg, color: status.color }}>
                    {status.text}
                  </span>
                </div>
              )}

              {isCalibrated && showCalibration !== pot.id ? (
                /* ── Calibrated view ── */
                <div className="space-y-2">
                  {/* Chunky progress bar */}
                  {waterPct != null && (
                    <div className="relative h-3 rounded-full overflow-hidden" style={{ background: "hsl(220,15%,18%)" }}>
                      <div className="h-full rounded-full transition-all duration-700"
                        style={{ width: `${waterPct}%`, background: `linear-gradient(90deg, ${status.bar}99, ${status.bar})` }} />
                      {/* Shine */}
                      <div className="absolute inset-0 rounded-full" style={{ background: "linear-gradient(180deg, rgba(255,255,255,0.08) 0%, transparent 60%)" }} />
                    </div>
                  )}

                  {/* Dry / Wet + Tare + Reset */}
                  <div className={`flex items-center gap-2 flex-wrap transition-colors duration-700 ${flash ? "rounded-lg px-1 -mx-1" : ""}`}
                    style={flash ? { background: "rgba(69,170,242,0.08)" } : {}}>
                    <span className="text-[10px] tabular-nums" style={{ color: "hsl(220,10%,50%)" }}>
                      🏜 <span style={{ color: "#ff9f43" }}>{dry!.toFixed(0)}g</span>
                    </span>
                    <span className="text-[10px] tabular-nums" style={{ color: "hsl(220,10%,50%)" }}>
                      💧 <span style={{ color: "#45aaf2" }}>{wet!.toFixed(0)}g</span>
                    </span>
                    {(pot.dry_set_at || pot.wet_set_at) && (
                      <span className="text-[9px]" style={{ color: "hsl(220,10%,30%)" }}>
                        · {timeAgo([pot.dry_set_at, pot.wet_set_at].filter(Boolean).sort().pop()!)}
                      </span>
                    )}
                    <div className="flex items-center gap-1.5 ml-auto">
                      {/* Tare button */}
                      <button onClick={() => handleTare(pot.id)} disabled={loading !== null}
                        className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold transition-all hover:brightness-125"
                        style={{ background: "hsl(220,15%,18%)", border: "1px solid hsl(220,15%,26%)", color: "hsl(220,10%,55%)" }}>
                        {loading === `tare-${pot.id}` ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : "⚖️"} Tare
                      </button>
                      {/* Reset */}
                      <button onClick={() => setShowCalibration(pot.id)}
                        className="flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[10px] transition-all hover:brightness-125"
                        style={{ background: "hsl(220,15%,18%)", border: "1px solid hsl(220,15%,26%)", color: "hsl(220,10%,40%)" }}>
                        <RotateCcw className="w-2.5 h-2.5" /> Reset
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                /* ── Setup / recalibrate ── */
                <div className="space-y-2">
                  <div className="flex gap-1.5">
                    <button onClick={() => handleSetWeight(pot.id, "dry")} disabled={loading !== null}
                      className="flex-1 flex items-center justify-between px-2.5 py-1.5 rounded-xl text-[11px] font-semibold transition-all hover:brightness-110"
                      style={{
                        background: hasDry ? "rgba(255,159,67,0.06)" : "rgba(255,159,67,0.15)",
                        border: `1.5px solid ${hasDry ? "rgba(255,159,67,0.2)" : "rgba(255,159,67,0.6)"}`,
                      }}>
                      <span className="flex items-center gap-1">
                        {loading === `${pot.id}-dry`
                          ? <Loader2 className="w-3 h-3 animate-spin" style={{ color: "#ff9f43" }} />
                          : hasDry ? <span style={{ color: "#26de81" }}>✓</span> : "🏜"}
                        <span style={{ color: hasDry ? "hsl(220,10%,55%)" : "#ff9f43" }}>
                          {hasDry ? "Dry" : "① Set Dry"}
                        </span>
                      </span>
                      <span className="font-bold tabular-nums" style={{ color: hasDry ? "white" : "hsl(220,10%,35%)" }}>
                        {hasDry ? `${dry!.toFixed(0)}g` : "—"}
                      </span>
                    </button>

                    <button onClick={() => handleSetWeight(pot.id, "wet")} disabled={loading !== null}
                      className="flex-1 flex items-center justify-between px-2.5 py-1.5 rounded-xl text-[11px] font-semibold transition-all hover:brightness-110"
                      style={{
                        background: hasWet ? "rgba(69,170,242,0.06)" : hasDry ? "rgba(69,170,242,0.15)" : "rgba(69,170,242,0.04)",
                        border: `1.5px solid ${hasWet ? "rgba(69,170,242,0.2)" : hasDry ? "rgba(69,170,242,0.6)" : "rgba(69,170,242,0.15)"}`,
                        opacity: !hasDry && !hasWet ? 0.45 : 1,
                      }}>
                      <span className="flex items-center gap-1">
                        {loading === `${pot.id}-wet`
                          ? <Loader2 className="w-3 h-3 animate-spin" style={{ color: "#45aaf2" }} />
                          : hasWet ? <span style={{ color: "#26de81" }}>✓</span> : "💧"}
                        <span style={{ color: hasWet ? "hsl(220,10%,55%)" : "#45aaf2" }}>
                          {hasWet ? "Wet" : hasDry ? "② Set Wet" : "Set Wet"}
                        </span>
                      </span>
                      <span className="font-bold tabular-nums" style={{ color: hasWet ? "white" : "hsl(220,10%,35%)" }}>
                        {hasWet ? `${wet!.toFixed(0)}g` : "—"}
                      </span>
                    </button>
                  </div>

                  <div className="flex items-center gap-2">
                    {/* Tare */}
                    <button onClick={() => handleTare(pot.id)} disabled={loading !== null}
                      className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-semibold transition-all hover:brightness-125"
                      style={{ background: "hsl(220,15%,18%)", border: "1px solid hsl(220,15%,26%)", color: "hsl(220,10%,55%)" }}>
                      {loading === `tare-${pot.id}` ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : "⚖️"} Tare
                    </button>
                    {isCalibrated && (
                      <button onClick={() => setShowCalibration(null)}
                        className="text-[10px] hover:opacity-80" style={{ color: "hsl(220,10%,40%)" }}>
                        ← Back
                      </button>
                    )}
                    {(hasDry || hasWet) && (
                      <button onClick={() => handleReset(pot.id)} disabled={loading === "reset"}
                        className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-semibold transition-all hover:brightness-110 ml-auto"
                        style={{ background: "rgba(255,77,77,0.1)", border: "1px solid rgba(255,77,77,0.3)", color: "#ff6b6b" }}>
                        {loading === "reset" ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <RotateCcw className="w-2.5 h-2.5" />}
                        Clear
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
