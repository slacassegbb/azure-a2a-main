"use client";

import { useState } from "react";
import { Droplets, Flower2, FlaskConical, Fan, Lightbulb, Loader2, Check } from "lucide-react";
import { GardenDashboardData } from "@/lib/garden/types";
import { DURATION_OPTIONS, FAN_SPEEDS } from "@/lib/garden/constants";

interface QuickControlsProps {
  data: GardenDashboardData | null;
  onRefresh: () => void;
  inline?: boolean;
}

async function sendControl(action: string, params: Record<string, any>) {
  const res = await fetch("/api/garden/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, ...params }),
  });
  return res.json();
}

function ActionButton({ icon: Icon, label, color, onClick, loading, success }: {
  icon: any; label: string; color: string; onClick: () => void; loading?: boolean; success?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className="flex items-center gap-2 px-4 py-2.5 rounded-lg font-medium text-sm transition-all active:scale-95 disabled:opacity-50"
      style={{
        background: success ? "hsl(152, 75%, 50%, 0.2)" : `${color}15`,
        border: `1px solid ${success ? "hsl(152, 75%, 50%)" : color}30`,
        color: success ? "hsl(152, 75%, 50%)" : color,
      }}
    >
      {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : success ? <Check className="w-4 h-4" /> : <Icon className="w-4 h-4" />}
      {label}
    </button>
  );
}

export default function QuickControls({ data, onRefresh, inline = false }: QuickControlsProps) {
  const [duration, setDuration] = useState(120);
  const [lightBrightness, setLightBrightness] = useState(100);
  const [loading, setLoading] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [activeFanSpeed, setActiveFanSpeed] = useState<number | null>(data?.fan?.state ? (data.fan.speed || 100) : 0);

  const doAction = async (key: string, action: string, params: Record<string, any>) => {
    setLoading(key);
    setSuccess(null);
    try {
      await sendControl(action, params);
      setSuccess(key);
      setTimeout(() => setSuccess(null), 2000);
      setTimeout(onRefresh, 3000);
    } catch { /* ignore */ }
    finally { setLoading(null); }
  };

  if (inline) {
    // Compact horizontal layout for the header bar — big touch targets
    return (
      <div className="flex items-center gap-1.5 md:gap-2 flex-wrap">
        {/* Irrigation */}
        <span className="text-[10px] uppercase tracking-wider font-medium shrink-0" style={{ color: "hsl(220, 10%, 45%)" }}>Irrigate</span>
        {[
          { key: "a", label: "💧 Water", color: "hsl(185, 90%, 55%)" },
          { key: "b", label: "🌱 Grow", color: "hsl(152, 75%, 50%)" },
          { key: "c", label: "🌸 Bloom", color: "hsl(330, 80%, 65%)" },
        ].map(v => (
          <button
            key={v.key}
            onClick={() => doAction(`valve-${v.key}`, "irrigate_valve", { valve: v.key, duration_seconds: duration })}
            disabled={loading === `valve-${v.key}`}
            className="px-3 py-2 rounded-lg text-xs font-semibold transition-all active:scale-95 touch-manipulation"
            style={{
              background: success === `valve-${v.key}` ? "hsl(152, 75%, 50%, 0.2)" : `${v.color}12`,
              border: `1px solid ${success === `valve-${v.key}` ? "hsl(152, 75%, 50%)" : v.color}30`,
              color: success === `valve-${v.key}` ? "hsl(152, 75%, 50%)" : v.color,
              minHeight: "32px",
            }}
          >
            {loading === `valve-${v.key}` ? <Loader2 className="w-3 h-3 animate-spin" /> : v.label}
          </button>
        ))}
        <select
          value={duration}
          onChange={(e) => setDuration(Number(e.target.value))}
          className="text-xs rounded-lg px-2 py-2 border-0 outline-none touch-manipulation"
          style={{ background: "hsl(220, 15%, 16%)", color: "hsl(220, 10%, 70%)", minHeight: "32px" }}
        >
          {DURATION_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>

        <div className="w-px h-6 mx-1" style={{ background: "hsl(220, 15%, 20%)" }} />

        {/* Fan */}
        <span className="text-[10px] uppercase tracking-wider font-medium shrink-0" style={{ color: "hsl(220, 10%, 45%)" }}>Fan</span>
        {FAN_SPEEDS.map(speed => {
          const isActive = activeFanSpeed === speed;
          return (
            <button
              key={speed}
              onClick={() => { setActiveFanSpeed(speed); doAction(`fan-${speed}`, "set_fan", { state: speed > 0, speed }); }}
              className="px-2.5 py-2 rounded-lg text-[11px] font-semibold transition-all active:scale-95 touch-manipulation"
              style={{
                background: isActive ? "hsl(185, 70%, 55%, 0.2)" : "hsl(220, 15%, 13%)",
                border: `1px solid ${isActive ? "hsl(185, 70%, 55%)" : "hsl(220, 15%, 18%)"}`,
                color: isActive ? "hsl(185, 70%, 55%)" : "hsl(220, 10%, 45%)",
                minHeight: "32px", minWidth: "32px",
              }}
            >
              {loading === `fan-${speed}` ? <Loader2 className="w-3 h-3 animate-spin mx-auto" /> : speed === 0 ? "OFF" : `${speed}%`}
            </button>
          );
        })}

        <div className="w-px h-6 mx-1" style={{ background: "hsl(220, 15%, 20%)" }} />

        {/* Light */}
        <span className="text-[10px] uppercase tracking-wider font-medium shrink-0" style={{ color: "hsl(220, 10%, 45%)" }}>Light</span>
        {[0, 25, 50, 75, 100].map(brightness => {
          const isActive = lightBrightness === brightness;
          return (
            <button
              key={brightness}
              onClick={() => {
                setLightBrightness(brightness);
                doAction(`light-${brightness}`, brightness === 0 ? "set_light_power" : "set_light_brightness",
                  brightness === 0 ? { state: false } : { brightness });
              }}
              className="px-2.5 py-2 rounded-lg text-[11px] font-semibold transition-all active:scale-95 touch-manipulation"
              style={{
                background: isActive ? "hsl(48, 95%, 65%, 0.2)" : "hsl(220, 15%, 13%)",
                border: `1px solid ${isActive ? "hsl(48, 95%, 65%)" : "hsl(220, 15%, 18%)"}`,
                color: isActive ? "hsl(48, 95%, 65%)" : "hsl(220, 10%, 45%)",
                minHeight: "32px", minWidth: "32px",
              }}
            >
              {loading === `light-${brightness}` ? <Loader2 className="w-3 h-3 animate-spin mx-auto" /> : brightness === 0 ? "OFF" : `${brightness}%`}
            </button>
          );
        })}
      </div>
    );
  }

  // Full card layout (fallback, not currently used)
  return (
    <div className="rounded-xl p-5" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
      <span className="text-[11px] uppercase tracking-wider font-medium" style={{ color: "hsl(220, 10%, 50%)" }}>
        🎛 Quick Controls
      </span>
      <p className="text-xs mt-2" style={{ color: "hsl(220, 10%, 40%)" }}>Controls are in the header bar above.</p>
    </div>
  );
}
