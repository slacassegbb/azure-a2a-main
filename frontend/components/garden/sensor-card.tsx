"use client";

import { useState } from "react";
import { Thermometer, Droplets, Sun, Cloud, Fan, TrendingUp, TrendingDown, Loader2 } from "lucide-react";
import { AreaChart, Area, ResponsiveContainer } from "recharts";
import { getTrend } from "@/lib/garden/calculations";

const ICONS: Record<string, any> = { thermometer: Thermometer, droplets: Droplets, sun: Sun, cloud: Cloud, fan: Fan };

interface ControlButton {
  label: string;
  value: number;
}

interface SensorCardProps {
  label: string;
  value: string;
  unit: string;
  secondaryValue?: string;
  color: string;
  icon: string;
  history?: { ts: string; value: number }[];
  dataKey?: string;
  controls?: {
    buttons: ControlButton[];
    activeValue: number;
    onSelect: (value: number) => Promise<void>;
  };
}

export default function SensorCard({ label, value, unit, secondaryValue, color, icon, history = [], controls }: SensorCardProps) {
  const Icon = ICONS[icon] || Sun;
  const trend = history.length > 2 ? getTrend(history.map(h => ({ pct: h.value })), 6) : null;
  const [loading, setLoading] = useState<number | null>(null);
  const [activeVal, setActiveVal] = useState(controls?.activeValue ?? 0);
  const isSpinning = icon === "fan" && activeVal > 0;

  const handleControl = async (val: number) => {
    if (!controls) return;
    setLoading(val);
    try {
      await controls.onSelect(val);
      setActiveVal(val);
    } catch { /* ignore */ }
    finally { setLoading(null); }
  };

  return (
    <div className="rounded-xl p-2 md:p-3 xl:p-4 flex flex-col justify-between min-h-[110px] md:min-h-[140px] xl:min-h-[160px] relative overflow-hidden"
      style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1 md:gap-2">
          <Icon
            className={`w-3 h-3 md:w-4 md:h-4 shrink-0 ${isSpinning ? "animate-spin" : ""}`}
            style={{ color, opacity: 0.8, animationDuration: isSpinning ? `${Math.max(0.3, 2 - (activeVal / 100) * 1.7)}s` : undefined }}
          />
          <span className="text-[8px] md:text-[10px] xl:text-[11px] uppercase tracking-wider font-medium truncate" style={{ color: "hsl(220, 10%, 50%)" }}>
            {label}
          </span>
        </div>
        {trend && trend.direction !== "stable" && (
          <div className="hidden md:flex items-center gap-1 text-[10px]" style={{ color: trend.direction === "up" ? "hsl(152, 75%, 50%)" : "hsl(25, 95%, 55%)" }}>
            {trend.direction === "up" ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
            {trend.change}%
          </div>
        )}
      </div>

      {/* Value */}
      <div className="mt-1">
        <div className="flex items-baseline gap-0.5 md:gap-1">
          <span className="text-lg md:text-2xl xl:text-3xl font-semibold tracking-tight" style={{ color: "white" }}>{value}</span>
          <span className="text-[9px] md:text-xs xl:text-sm font-medium" style={{ color: "hsl(220, 10%, 50%)" }}>{unit}</span>
        </div>
        {secondaryValue && (
          <span className="text-[8px] md:text-xs" style={{ color: "hsl(220, 10%, 45%)" }}>{secondaryValue}</span>
        )}
      </div>

      {/* Sparkline */}
      {history.length > 3 && (
        <div className="-mx-1 md:-mx-2 -mb-1" style={{ marginTop: controls ? "2px" : "6px" }}>
          <ResponsiveContainer width="100%" height={controls ? 24 : 36}>
            <AreaChart data={history.slice(-72)}>
              <defs>
                <linearGradient id={`grad-${label}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={color} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={color} stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area
                type="monotone"
                dataKey="value"
                stroke={color}
                strokeWidth={1.5}
                fill={`url(#grad-${label})`}
                dot={false}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Inline controls */}
      {controls && (
        <div className="flex gap-0.5 md:gap-1 mt-1">
          {controls.buttons.map(btn => {
            const isActive = activeVal === btn.value;
            const isLoading = loading === btn.value;
            return (
              <button
                key={btn.value}
                onClick={() => handleControl(btn.value)}
                disabled={isLoading}
                className="flex-1 py-0.5 md:py-1 xl:py-1.5 rounded text-[7px] md:text-[9px] xl:text-[10px] font-semibold transition-all active:scale-95 touch-manipulation"
                style={{
                  background: isActive ? `${color}25` : "hsl(220, 15%, 13%)",
                  border: `1px solid ${isActive ? color : "hsl(220, 15%, 18%)"}`,
                  color: isActive ? color : "hsl(220, 10%, 42%)",
                }}
              >
                {isLoading ? <Loader2 className="w-2 h-2 animate-spin mx-auto" /> : btn.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
