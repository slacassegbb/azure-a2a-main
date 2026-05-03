"use client";

import { useState } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from "recharts";
import { MoistureReading, LightSchedule, HumidityReading, GardenEvent, GardenConfig } from "@/lib/garden/types";
import { getCurrentBrightness } from "@/lib/garden/calculations";

interface EnvironmentChartProps {
  readings: MoistureReading[];
  schedule: LightSchedule | null | undefined;
  humidityReadings?: HumidityReading[];
  events?: GardenEvent[];
  gardenConfig?: GardenConfig | null;
}

function formatTime(ts: string): string {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: true });
}

function getBrightnessAtTime(schedule: LightSchedule, ts: string): number {
  const d = new Date(ts);
  const minutes = d.getHours() * 60 + d.getMinutes();
  const sunriseStart = schedule.sunrise_hour * 60;
  const sunriseEnd = sunriseStart + schedule.sunrise_ramp_min;
  const sunsetStart = schedule.sunset_hour * 60;
  const sunsetEnd = sunsetStart + schedule.sunset_ramp_min;
  if (minutes < sunriseStart || minutes >= sunsetEnd) return schedule.night_brightness;
  if (minutes < sunriseEnd) return schedule.night_brightness + (schedule.peak_brightness - schedule.night_brightness) * (minutes - sunriseStart) / schedule.sunrise_ramp_min;
  if (minutes < sunsetStart) return schedule.peak_brightness;
  return schedule.peak_brightness - (schedule.peak_brightness - schedule.night_brightness) * (minutes - sunsetStart) / schedule.sunset_ramp_min;
}

export default function EnvironmentChart({ readings, schedule, humidityReadings = [], events = [], gardenConfig }: EnvironmentChartProps) {
  const [showMoisture, setShowMoisture] = useState(true);
  const [showTemp, setShowTemp] = useState(true);
  const [showLight, setShowLight] = useState(true);
  const [showHumidity, setShowHumidity] = useState(true);
  const [showFan, setShowFan] = useState(true);
  const [showWeight, setShowWeight] = useState(true);

  if (readings.length < 3) {
    return (
      <div className="rounded-xl p-4" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
        <span className="text-sm" style={{ color: "hsl(220, 10%, 35%)" }}>Not enough data for charts yet</span>
      </div>
    );
  }

  // Build a map of humidity readings by nearest timestamp for merging
  const humidityMap = new Map<string, number>();
  humidityReadings.forEach(h => {
    const key = h.ts.slice(0, 16); // match to minute precision
    humidityMap.set(key, h.humidity);
  });

  // Compute dry/wet thresholds from first calibrated pot (if any)
  const pot = gardenConfig?.pots?.find(p => p.dry_weight_g != null && p.wet_weight_g != null);
  const dryG = pot?.dry_weight_g ?? null;
  const wetG = pot?.wet_weight_g ?? null;
  const hasWeightCal = dryG != null && wetG != null && wetG > dryG;

  // Take last 96 readings (~8 hours at 5-min intervals)
  let lastHumidity: number | null = null;
  const chartData = readings.slice(-96).map(r => {
    const key = r.ts.slice(0, 16);
    const h = humidityMap.get(key) ?? null;
    if (h !== null) lastHumidity = h;
    const wg = (r as any).weight_g ?? null;
    let waterPct: number | null = null;
    if (wg != null && hasWeightCal) {
      const capacity = wetG - dryG;
      waterPct = Math.min(100, Math.max(0, Math.round(((wg - dryG) / capacity) * 100)));
    }
    return {
      time: formatTime(r.ts),
      ts: r.ts,
      moisture: r.pct,
      temp: (r as any).temp_c ?? null,
      light: schedule ? Math.round(getBrightnessAtTime(schedule, r.ts)) : null,
      humidity: h ?? lastHumidity,
      fan: (r as any).fan ?? null,
      water: waterPct,
    };
  });

  return (
    <div className="rounded-xl p-4" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
      <div className="flex items-center justify-between mb-4">
        <span className="text-[11px] uppercase tracking-wider font-medium" style={{ color: "hsl(220, 10%, 50%)" }}>
          Environment History
        </span>
        <div className="flex gap-2">
          <button
            onClick={() => setShowMoisture(!showMoisture)}
            className="text-[10px] px-2 py-1 rounded-md font-medium transition-all"
            style={{
              background: showMoisture ? "hsl(185, 90%, 55%, 0.15)" : "hsl(220, 15%, 13%)",
              color: showMoisture ? "hsl(185, 90%, 55%)" : "hsl(220, 10%, 40%)",
              border: `1px solid ${showMoisture ? "hsl(185, 90%, 55%, 0.3)" : "hsl(220, 15%, 18%)"}`,
            }}
          >
            Moisture
          </button>
          <button
            onClick={() => setShowTemp(!showTemp)}
            className="text-[10px] px-2 py-1 rounded-md font-medium transition-all"
            style={{
              background: showTemp ? "hsl(35, 95%, 60%, 0.15)" : "hsl(220, 15%, 13%)",
              color: showTemp ? "hsl(35, 95%, 60%)" : "hsl(220, 10%, 40%)",
              border: `1px solid ${showTemp ? "hsl(35, 95%, 60%, 0.3)" : "hsl(220, 15%, 18%)"}`,
            }}
          >
            Temperature
          </button>
          <button
            onClick={() => setShowLight(!showLight)}
            className="text-[10px] px-2 py-1 rounded-md font-medium transition-all"
            style={{
              background: showLight ? "hsl(48, 95%, 65%, 0.15)" : "hsl(220, 15%, 13%)",
              color: showLight ? "hsl(48, 95%, 65%)" : "hsl(220, 10%, 40%)",
              border: `1px solid ${showLight ? "hsl(48, 95%, 65%, 0.3)" : "hsl(220, 15%, 18%)"}`,
            }}
          >
            Light
          </button>
          <button
            onClick={() => setShowHumidity(!showHumidity)}
            className="text-[10px] px-2 py-1 rounded-md font-medium transition-all"
            style={{
              background: showHumidity ? "hsl(270, 70%, 65%, 0.15)" : "hsl(220, 15%, 13%)",
              color: showHumidity ? "hsl(270, 70%, 65%)" : "hsl(220, 10%, 40%)",
              border: `1px solid ${showHumidity ? "hsl(270, 70%, 65%, 0.3)" : "hsl(220, 15%, 18%)"}`,
            }}
          >
            Humidity
          </button>
          <button
            onClick={() => setShowFan(!showFan)}
            className="text-[10px] px-2 py-1 rounded-md font-medium transition-all"
            style={{
              background: showFan ? "hsl(185, 70%, 55%, 0.15)" : "hsl(220, 15%, 13%)",
              color: showFan ? "hsl(185, 70%, 55%)" : "hsl(220, 10%, 40%)",
              border: `1px solid ${showFan ? "hsl(185, 70%, 55%, 0.3)" : "hsl(220, 15%, 18%)"}`,
            }}
          >
            Fan
          </button>
          <button
            onClick={() => setShowWeight(!showWeight)}
            className="text-[10px] px-2 py-1 rounded-md font-medium transition-all"
            style={{
              background: showWeight ? "hsl(152, 75%, 50%, 0.15)" : "hsl(220, 15%, 13%)",
              color: showWeight ? "hsl(152, 75%, 50%)" : "hsl(220, 10%, 40%)",
              border: `1px solid ${showWeight ? "hsl(152, 75%, 50%, 0.3)" : "hsl(220, 15%, 18%)"}`,
            }}
          >
            Pot 1
          </button>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={220}>
        <AreaChart data={chartData} margin={{ top: 5, right: 5, bottom: 0, left: -20 }}>
          <defs>
            <linearGradient id="moistureGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(185, 90%, 55%)" stopOpacity={0.25} />
              <stop offset="100%" stopColor="hsl(185, 90%, 55%)" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="tempGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(35, 95%, 60%)" stopOpacity={0.25} />
              <stop offset="100%" stopColor="hsl(35, 95%, 60%)" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="lightGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(48, 95%, 65%)" stopOpacity={0.2} />
              <stop offset="100%" stopColor="hsl(48, 95%, 65%)" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="humidityGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(270, 70%, 65%)" stopOpacity={0.25} />
              <stop offset="100%" stopColor="hsl(270, 70%, 65%)" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="fanGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(185, 70%, 55%)" stopOpacity={0.2} />
              <stop offset="100%" stopColor="hsl(185, 70%, 55%)" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="weightGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(152, 75%, 50%)" stopOpacity={0.25} />
              <stop offset="100%" stopColor="hsl(152, 75%, 50%)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(220, 15%, 14%)" />
          <XAxis
            dataKey="time"
            tick={{ fontSize: 10, fill: "hsl(220, 10%, 40%)" }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fontSize: 10, fill: "hsl(220, 10%, 40%)" }}
            tickLine={false}
            axisLine={false}
            domain={[0, "auto"]}
          />
          <Tooltip
            contentStyle={{
              background: "hsl(220, 18%, 14%)",
              border: "1px solid hsl(220, 15%, 20%)",
              borderRadius: "8px",
              fontSize: "12px",
              color: "white",
            }}
          />
          {showMoisture && (
            <Area
              type="monotone"
              dataKey="moisture"
              stroke="hsl(185, 90%, 55%)"
              strokeWidth={2}
              fill="url(#moistureGrad)"
              dot={false}
              name="Moisture %"
            />
          )}
          {showTemp && (
            <Area
              type="monotone"
              dataKey="temp"
              stroke="hsl(35, 95%, 60%)"
              strokeWidth={2}
              fill="url(#tempGrad)"
              dot={false}
              name="Temp °C"
              connectNulls
            />
          )}
          {showLight && (
            <Area
              type="monotone"
              dataKey="light"
              stroke="hsl(48, 95%, 65%)"
              strokeWidth={1.5}
              fill="url(#lightGrad)"
              dot={false}
              name="Light %"
              strokeDasharray="4 2"
              connectNulls
            />
          )}
          {showHumidity && (
            <Area
              type="monotone"
              dataKey="humidity"
              stroke="hsl(270, 70%, 65%)"
              strokeWidth={2}
              fill="url(#humidityGrad)"
              dot={false}
              name="Humidity %"
              connectNulls
            />
          )}
          {showFan && (
            <Area
              type="stepAfter"
              dataKey="fan"
              stroke="hsl(185, 70%, 55%)"
              strokeWidth={1.5}
              fill="url(#fanGrad)"
              dot={false}
              name="Fan %"
              connectNulls
            />
          )}
          {showWeight && (
            <Area
              type="monotone"
              dataKey="water"
              stroke="hsl(152, 75%, 50%)"
              strokeWidth={2}
              fill="url(#weightGrad)"
              dot={false}
              name="Pot 1"
              connectNulls
            />
          )}
          {events.map((ev, i) => {
            const evTime = formatTime(ev.ts);
            const isValve = ev.type === "valve";
            const color = isValve ? "hsl(152, 75%, 50%)" : "hsl(185, 90%, 55%)";
            const label = isValve ? `💧${ev.detail?.charAt(0) || ""}` : "💧";
            return (
              <ReferenceLine
                key={`ev-${i}`}
                x={evTime}
                stroke={color}
                strokeDasharray="3 3"
                strokeWidth={1.5}
                label={{ value: label, position: "top", fontSize: 10, fill: color }}
              />
            );
          })}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
