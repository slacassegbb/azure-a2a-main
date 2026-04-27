"use client";

import { Thermometer, Droplets, Sun, Cloud, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { AreaChart, Area, ResponsiveContainer } from "recharts";
import { getTrend } from "@/lib/garden/calculations";

const ICONS: Record<string, any> = { thermometer: Thermometer, droplets: Droplets, sun: Sun, cloud: Cloud };

interface SensorCardProps {
  label: string;
  value: string;
  unit: string;
  secondaryValue?: string;
  color: string;
  icon: string;
  history?: { ts: string; value: number }[];
  dataKey?: string;
}

export default function SensorCard({ label, value, unit, secondaryValue, color, icon, history = [] }: SensorCardProps) {
  const Icon = ICONS[icon] || Sun;
  const trend = history.length > 2 ? getTrend(history.map(h => ({ pct: h.value })), 6) : null;

  return (
    <div className="rounded-xl p-4 flex flex-col justify-between min-h-[160px] relative overflow-hidden"
      style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4" style={{ color, opacity: 0.8 }} />
          <span className="text-[11px] uppercase tracking-wider font-medium" style={{ color: "hsl(220, 10%, 50%)" }}>
            {label}
          </span>
        </div>
        {trend && trend.direction !== "stable" && (
          <div className="flex items-center gap-1 text-[10px]" style={{ color: trend.direction === "up" ? "hsl(152, 75%, 50%)" : "hsl(25, 95%, 55%)" }}>
            {trend.direction === "up" ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
            {trend.change}%
          </div>
        )}
      </div>

      {/* Value */}
      <div className="mt-2">
        <div className="flex items-baseline gap-1">
          <span className="text-3xl font-semibold tracking-tight" style={{ color: "white" }}>{value}</span>
          <span className="text-sm font-medium" style={{ color: "hsl(220, 10%, 50%)" }}>{unit}</span>
        </div>
        {secondaryValue && (
          <span className="text-xs" style={{ color: "hsl(220, 10%, 45%)" }}>{secondaryValue}</span>
        )}
      </div>

      {/* Sparkline */}
      {history.length > 3 && (
        <div className="mt-2 -mx-2 -mb-1">
          <ResponsiveContainer width="100%" height={48}>
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
    </div>
  );
}
