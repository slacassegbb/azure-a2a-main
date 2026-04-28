"use client";

import { useState } from "react";
import { Droplets, Flower2, FlaskConical, Loader2 } from "lucide-react";
import { GardenDashboardData } from "@/lib/garden/types";
import { DURATION_OPTIONS } from "@/lib/garden/constants";

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

export default function QuickControls({ data, onRefresh, inline = false }: QuickControlsProps) {
  const [duration, setDuration] = useState(120);
  const [loading, setLoading] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

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

  if (!inline) return null;

  return (
    <div className="flex items-center gap-1 xl:gap-2 flex-wrap">
      <span className="text-[9px] xl:text-[10px] uppercase tracking-wider font-medium shrink-0 mr-0.5" style={{ color: "hsl(220, 10%, 45%)" }}>Irrigate</span>
      {[
        { key: "a", label: "💧", labelXl: "💧 Water", color: "hsl(185, 90%, 55%)" },
        { key: "b", label: "🌱", labelXl: "🌱 Grow", color: "hsl(152, 75%, 50%)" },
        { key: "c", label: "🌸", labelXl: "🌸 Bloom", color: "hsl(330, 80%, 65%)" },
      ].map(v => (
        <button
          key={v.key}
          onClick={() => doAction(`valve-${v.key}`, "irrigate_valve", { valve: v.key, duration_seconds: duration })}
          disabled={loading === `valve-${v.key}`}
          className="px-2 py-1 xl:px-3 xl:py-1.5 rounded-md xl:rounded-lg text-[11px] xl:text-xs font-semibold transition-all active:scale-95 touch-manipulation"
          style={{
            background: success === `valve-${v.key}` ? "hsl(152, 75%, 50%, 0.2)" : `${v.color}12`,
            border: `1px solid ${success === `valve-${v.key}` ? "hsl(152, 75%, 50%)" : v.color}30`,
            color: success === `valve-${v.key}` ? "hsl(152, 75%, 50%)" : v.color,
          }}
        >
          {loading === `valve-${v.key}` ? <Loader2 className="w-3 h-3 animate-spin" /> : <><span className="xl:hidden">{v.label}</span><span className="hidden xl:inline">{v.labelXl}</span></>}
        </button>
      ))}
      <select
        value={duration}
        onChange={(e) => setDuration(Number(e.target.value))}
        className="text-[10px] xl:text-xs rounded-md px-1.5 py-1 xl:px-2 xl:py-1.5 border-0 outline-none touch-manipulation"
        style={{ background: "hsl(220, 15%, 16%)", color: "hsl(220, 10%, 70%)" }}
      >
        {DURATION_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}
