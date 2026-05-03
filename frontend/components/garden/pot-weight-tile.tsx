"use client";

import { useState, useRef, useEffect } from "react";
import { Scale, Droplets, Loader2, Pencil, RotateCcw } from "lucide-react";
import { GardenConfig, PotConfig } from "@/lib/garden/types";

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

interface PotWeightTileProps {
  config: GardenConfig | null;
  currentWeightG: number | null;
  onSetWeight: (potId: string, type: "dry" | "wet") => Promise<void>;
  onRenamePot: (potId: string, name: string) => Promise<void>;
  onResetCalibration: (potId: string) => Promise<void>;
}

function PotGraphic({ pot, weightG }: { pot: PotConfig; weightG: number | null }) {
  const dry = pot.dry_weight_g;
  const wet = pot.wet_weight_g;
  const hasRange = dry != null && wet != null && wet > dry;

  let waterPct = 0;
  if (hasRange && weightG != null) {
    waterPct = Math.min(100, Math.max(0, Math.round(((weightG - dry!) / (wet! - dry!)) * 100)));
  }

  const soilL = hasRange ? 45 - (waterPct * 27) / 100 : 32;
  const soilS = hasRange ? 30 + (waterPct * 25) / 100 : 40;
  const soilColor = `hsl(25, ${soilS}%, ${soilL}%)`;
  const soilTopColor = `hsl(25, ${soilS + 5}%, ${soilL + 6}%)`;

  return (
    <div className="w-14 h-[70px] shrink-0">
      <svg viewBox="0 0 64 80" className="w-full h-full">
        <defs>
          <clipPath id={`clip-${pot.id}`}><path d="M12 15 L8 70 Q8 75 13 75 L51 75 Q56 75 56 70 L52 15 Z" /></clipPath>
        </defs>
        <path d="M12 15 L8 70 Q8 75 13 75 L51 75 Q56 75 56 70 L52 15 Z" fill="hsl(15, 50%, 28%)" stroke="hsl(15, 40%, 22%)" strokeWidth="1.5" />
        <rect x="8" y="22" width="48" height="55" fill={soilColor} clipPath={`url(#clip-${pot.id})`} />
        <line x1="10" y1="23" x2="54" y2="23" stroke={soilTopColor} strokeWidth="1.5" clipPath={`url(#clip-${pot.id})`} />
        <rect x="8" y="12" width="48" height="6" rx="2" fill="hsl(15, 45%, 32%)" stroke="hsl(15, 40%, 22%)" strokeWidth="1" />
        <text x="32" y="48" textAnchor="middle" fill="white" fontSize="11" fontWeight="600" style={{ textShadow: "0 1px 2px rgba(0,0,0,0.6)" }}>
          {weightG != null ? `${weightG.toFixed(0)}g` : "—"}
        </text>
        {hasRange && <text x="32" y="62" textAnchor="middle" fill="hsla(0,0%,100%,0.7)" fontSize="9" style={{ textShadow: "0 1px 2px rgba(0,0,0,0.5)" }}>{waterPct}%</text>}
      </svg>
    </div>
  );
}

export default function PotWeightTile({ config, currentWeightG, onSetWeight, onRenamePot, onResetCalibration }: PotWeightTileProps) {
  const [loading, setLoading] = useState<string | null>(null);
  const [editingName, setEditingName] = useState<string | null>(null);
  const [nameInput, setNameInput] = useState("");
  const [showCalibration, setShowCalibration] = useState(false);
  const [flash, setFlash] = useState(false);
  const prevValsRef = useRef<string | null>(null);

  const scales: { id: string; weightG: number | null }[] = [];
  if (currentWeightG != null) scales.push({ id: "scale_1", weightG: currentWeightG });

  const potConfigs = config?.pots || [];
  const scalePots = scales.map((s) => {
    const existing = potConfigs.find((p) => p.id === s.id);
    return {
      scale: s,
      pot: existing || { id: s.id, name: "Pot 1", dry_weight_g: null, wet_weight_g: null, dry_set_at: null, wet_set_at: null } as PotConfig,
    };
  });

  // Detect when calibration values change externally (agent auto-recalibration)
  const firstPot = scalePots[0]?.pot;
  const valsKey = firstPot ? `${firstPot.dry_weight_g}-${firstPot.wet_weight_g}` : null;
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
    try { await onResetCalibration(potId); setShowCalibration(false); } finally { setLoading(null); }
  };

  if (scalePots.length === 0) {
    return (
      <div className="rounded-xl px-4 py-3" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
        <div className="flex items-center gap-2">
          <Scale className="w-3.5 h-3.5" style={{ color: "hsl(220, 10%, 30%)" }} />
          <span className="text-[11px] uppercase tracking-wider font-medium" style={{ color: "hsl(220, 10%, 35%)" }}>Scale offline</span>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl p-3" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
      {scalePots.map(({ scale, pot }) => {
        const dry = pot.dry_weight_g;
        const wet = pot.wet_weight_g;
        const isCalibrated = dry != null && wet != null && wet > dry;
        const waterPct = isCalibrated && scale.weightG != null
          ? Math.min(100, Math.max(0, Math.round(((scale.weightG - dry!) / (wet! - dry!)) * 100)))
          : null;

        // Status logic
        const hasDry = dry != null;
        const hasWet = wet != null;
        let statusText = "";
        let statusColor = "hsl(220, 10%, 40%)";
        if (waterPct != null) {
          if (waterPct <= 10) { statusText = "Needs water"; statusColor = "hsl(0, 85%, 60%)"; }
          else if (waterPct <= 30) { statusText = "Getting dry"; statusColor = "hsl(35, 95%, 60%)"; }
          else if (waterPct <= 70) { statusText = "Good"; statusColor = "hsl(152, 75%, 50%)"; }
          else { statusText = "Well watered"; statusColor = "hsl(185, 90%, 55%)"; }
        } else if (!hasDry && !hasWet) {
          statusText = "① Set dry weight";
        } else if (hasDry && !hasWet) {
          statusText = "② Now set wet";
          statusColor = "hsl(185, 90%, 55%)";
        } else {
          statusText = "Calibrated";
          statusColor = "hsl(152, 75%, 50%)";
        }

        const displayName = pot.name && !pot.name.startsWith("scale_") ? pot.name : `Pot ${pot.id.replace("scale_", "")}`;

        return (
          <div key={pot.id} className="flex gap-3">
            {/* Pot graphic */}
            <div className="flex flex-col items-center gap-1">
              <PotGraphic pot={pot} weightG={scale.weightG} />
              <span className="text-[9px] font-medium" style={{ color: statusColor }}>{statusText}</span>
            </div>

            {/* Info + controls */}
            <div className="flex-1 min-w-0 space-y-2">
              {/* Name row */}
              {editingName === pot.id ? (
                <div className="flex gap-1 items-center">
                  <input type="text" value={nameInput} onChange={(e) => setNameInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleRename(pot.id)} autoFocus
                    className="flex-1 px-1.5 py-0.5 rounded text-xs outline-none"
                    style={{ background: "hsl(220, 15%, 15%)", border: "1px solid hsl(220, 15%, 25%)", color: "white" }} />
                  <button onClick={() => handleRename(pot.id)} className="text-[10px]" style={{ color: "hsl(152, 75%, 50%)" }}>
                    {loading === "rename" ? <Loader2 className="w-3 h-3 animate-spin" /> : "✓"}
                  </button>
                  <button onClick={() => setEditingName(null)} className="text-[10px]" style={{ color: "hsl(220, 10%, 45%)" }}>✕</button>
                </div>
              ) : (
                <button onClick={() => { setEditingName(pot.id); setNameInput(pot.name || pot.id); }}
                  className="flex items-center gap-1 text-xs font-medium hover:opacity-80" style={{ color: "white" }}>
                  {displayName}
                  <Pencil className="w-2.5 h-2.5" style={{ color: "hsl(220, 10%, 35%)" }} />
                </button>
              )}

              {isCalibrated && !showCalibration ? (
                /* ── Calibrated view: water bar + dry/wet values ── */
                <div className="space-y-1.5">
                  {waterPct != null && (
                    <div className="space-y-0.5">
                      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "hsl(220, 15%, 15%)" }}>
                        <div className="h-full rounded-full transition-all duration-500"
                          style={{ width: `${waterPct}%`, background: waterPct <= 10 ? "hsl(0, 70%, 50%)" : waterPct <= 30 ? "hsl(35, 80%, 55%)" : "hsl(185, 80%, 50%)" }} />
                      </div>
                    </div>
                  )}
                  {/* Dry/Wet values — flash briefly when agent auto-adjusts */}
                  <div className={`flex items-center gap-3 rounded px-1 -mx-1 transition-colors duration-700 ${flash ? "bg-[hsla(185,80%,50%,0.08)]" : ""}`}>
                    <div className="flex items-center gap-1">
                      <Scale className="w-2.5 h-2.5" style={{ color: "hsl(35, 95%, 60%)" }} />
                      <span className="text-[9px] tabular-nums" style={{ color: "hsl(220, 10%, 50%)" }}>
                        Dry <span style={{ color: "white" }}>{dry!.toFixed(0)}g</span>
                      </span>
                    </div>
                    <div className="flex items-center gap-1">
                      <Droplets className="w-2.5 h-2.5" style={{ color: "hsl(185, 90%, 55%)" }} />
                      <span className="text-[9px] tabular-nums" style={{ color: "hsl(220, 10%, 50%)" }}>
                        Wet <span style={{ color: "white" }}>{wet!.toFixed(0)}g</span>
                      </span>
                    </div>
                    <button onClick={() => setShowCalibration(true)}
                      className="ml-auto flex items-center gap-0.5 text-[8px] hover:opacity-80 transition-opacity"
                      style={{ color: "hsl(220, 10%, 30%)" }}>
                      <RotateCcw className="w-2 h-2" />
                      Reset
                    </button>
                  </div>
                  {/* Last updated timestamp */}
                  {(pot.dry_set_at || pot.wet_set_at) && (
                    <span className="text-[8px]" style={{ color: "hsl(220, 10%, 30%)" }}>
                      Calibrated {timeAgo(
                        [pot.dry_set_at, pot.wet_set_at]
                          .filter(Boolean)
                          .sort()
                          .pop()!
                      )}
                    </span>
                  )}
                </div>
              ) : (
                /* ── Setup / recalibrate: step-by-step Dry then Wet ── */
                <div className="space-y-1.5">
                  <div className="flex gap-1.5">
                    {/* Dry button — prominent when not set, shows ✓ when done */}
                    <button onClick={() => handleSetWeight(pot.id, "dry")} disabled={loading !== null}
                      className="flex-1 flex items-center justify-between px-2 py-1.5 rounded-md text-[10px] transition-all hover:brightness-110"
                      style={{
                        background: hasDry ? "hsl(35, 95%, 60%, 0.04)" : "hsl(35, 95%, 60%, 0.12)",
                        border: `1px solid ${hasDry ? "hsl(35, 95%, 60%, 0.15)" : "hsl(35, 95%, 60%, 0.4)"}`,
                      }}>
                      <div className="flex items-center gap-1">
                        {loading === `${pot.id}-dry`
                          ? <Loader2 className="w-3 h-3 animate-spin" style={{ color: "hsl(35, 95%, 60%)" }} />
                          : hasDry
                            ? <span style={{ color: "hsl(152, 75%, 50%)", fontSize: "11px" }}>✓</span>
                            : <Scale className="w-3 h-3" style={{ color: "hsl(35, 95%, 60%)" }} />
                        }
                        <span style={{ color: hasDry ? "hsl(220, 10%, 50%)" : "hsl(35, 95%, 60%)" }}>
                          {hasDry ? "Dry" : "① Set Dry"}
                        </span>
                      </div>
                      <span className="font-medium tabular-nums" style={{ color: hasDry ? "white" : "hsl(220, 10%, 30%)" }}>
                        {hasDry ? `${dry!.toFixed(0)}g` : "—"}
                      </span>
                    </button>
                    {/* Wet button — highlighted after dry is set */}
                    <button onClick={() => handleSetWeight(pot.id, "wet")} disabled={loading !== null}
                      className="flex-1 flex items-center justify-between px-2 py-1.5 rounded-md text-[10px] transition-all hover:brightness-110"
                      style={{
                        background: hasWet ? "hsl(185, 90%, 55%, 0.04)" : hasDry ? "hsl(185, 90%, 55%, 0.12)" : "hsl(185, 90%, 55%, 0.04)",
                        border: `1px solid ${hasWet ? "hsl(185, 90%, 55%, 0.15)" : hasDry ? "hsl(185, 90%, 55%, 0.4)" : "hsl(185, 90%, 55%, 0.1)"}`,
                        opacity: !hasDry && !hasWet ? 0.4 : 1,
                      }}>
                      <div className="flex items-center gap-1">
                        {loading === `${pot.id}-wet`
                          ? <Loader2 className="w-3 h-3 animate-spin" style={{ color: "hsl(185, 90%, 55%)" }} />
                          : hasWet
                            ? <span style={{ color: "hsl(152, 75%, 50%)", fontSize: "11px" }}>✓</span>
                            : <Droplets className="w-3 h-3" style={{ color: "hsl(185, 90%, 55%)" }} />
                        }
                        <span style={{ color: hasWet ? "hsl(220, 10%, 50%)" : "hsl(185, 90%, 55%)" }}>
                          {hasWet ? "Wet" : hasDry ? "② Set Wet" : "Set Wet"}
                        </span>
                      </div>
                      <span className="font-medium tabular-nums" style={{ color: hasWet ? "white" : "hsl(220, 10%, 30%)" }}>
                        {hasWet ? `${wet!.toFixed(0)}g` : "—"}
                      </span>
                    </button>
                  </div>
                  {isCalibrated && showCalibration && (
                    <button onClick={() => setShowCalibration(false)}
                      className="text-[9px] hover:opacity-80" style={{ color: "hsl(220, 10%, 35%)" }}>
                      ← Done
                    </button>
                  )}
                  {(hasDry || hasWet) && (
                    <button onClick={() => handleReset(pot.id)} disabled={loading === "reset"}
                      className="flex items-center gap-0.5 text-[9px] hover:opacity-80 transition-opacity"
                      style={{ color: "hsl(0, 60%, 50%)" }}>
                      {loading === "reset" ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <RotateCcw className="w-2.5 h-2.5" />}
                      Clear & start over
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
