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
  const [showWeight2, setShowWeight2] = useState(true);

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

  // Compute dry/wet thresholds from calibrated pots
  const pot1Cfg = gardenConfig?.pots?.find(p => p.id === "scale_1" && p.dry_weight_g != null && p.wet_weight_g != null);
  const pot2Cfg = gardenConfig?.pots?.find(p => p.id === "scale_2" && p.dry_weight_g != null && p.wet_weight_g != null);
  const dry1 = pot1Cfg?.dry_weight_g ?? null;
  const wet1 = pot1Cfg?.wet_weight_g ?? null;
  const hasCal1 = dry1 != null && wet1 != null && wet1 > dry1;
  const dry2 = pot2Cfg?.dry_weight_g ?? null;
  const wet2 = pot2Cfg?.wet_weight_g ?? null;
  const hasCal2 = dry2 != null && wet2 != null && wet2 > dry2;

  // Take last 96 readings (~8 hours at 5-min intervals)
  let lastHumidity: number | null = null;
  const chartData = readings.slice(-96).map(r => {
    const key = r.ts.slice(0, 16);
    const h = humidityMap.get(key) ?? null;
    if (h !== null) lastHumidity = h;
    const wg = (r as any).weight_g ?? null;
    const wg2 = (r as any).weight2_g ?? null;
    let waterPct: number | null = null;
    let waterPct2: number | null = null;
    if (wg != null && hasCal1) {
      waterPct = Math.min(100, Math.max(0, Math.round(((wg - dry1!) / (wet1! - dry1!)) * 100)));
    }
    if (wg2 != null && hasCal2) {
      waterPct2 = Math.min(100, Math.max(0, Math.round(((wg2 - dry2!) / (wet2! - dry2!)) * 100)));
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
      water2: waterPct2,
    };
  });

  return (
    <div className="rounded-xl p-4" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
      <div className="flex items-center justify-between mb-4">
        <span className="text-[11px] uppercase tracking-wider font-medium" style={{ color: "hsl(220, 10%, 50%)" }}>
          Sensor History
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
              background: showFan ? "hsl(200, 60%, 45%, 0.15)" : "hsl(220, 15%, 13%)",
              color: showFan ? "hsl(200, 60%, 45%)" : "hsl(220, 10%, 40%)",
              border: `1px solid ${showFan ? "hsl(200, 60%, 45%, 0.3)" : "hsl(220, 15%, 18%)"}`,
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
          <button
            onClick={() => setShowWeight2(!showWeight2)}
            className="text-[10px] px-2 py-1 rounded-md font-medium transition-all"
            style={{
              background: showWeight2 ? "hsl(340, 75%, 55%, 0.15)" : "hsl(220, 15%, 13%)",
              color: showWeight2 ? "hsl(340, 75%, 55%)" : "hsl(220, 10%, 40%)",
              border: `1px solid ${showWeight2 ? "hsl(340, 75%, 55%, 0.3)" : "hsl(220, 15%, 18%)"}`,
            }}
          >
            Pot 2
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
              <stop offset="0%" stopColor="hsl(200, 60%, 45%)" stopOpacity={0.2} />
              <stop offset="100%" stopColor="hsl(200, 60%, 45%)" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="weightGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(152, 75%, 50%)" stopOpacity={0.25} />
              <stop offset="100%" stopColor="hsl(152, 75%, 50%)" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="weight2Grad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(340, 75%, 55%)" stopOpacity={0.25} />
              <stop offset="100%" stopColor="hsl(340, 75%, 55%)" stopOpacity={0} />
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
              stroke="hsl(200, 60%, 45%)"
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
          {showWeight2 && (
            <Area
              type="monotone"
              dataKey="water2"
              stroke="hsl(340, 75%, 55%)"
              strokeWidth={2}
              fill="url(#weight2Grad)"
              dot={false}
              name="Pot 2"
              connectNulls
            />
          )}
          {(() => {
            if (chartData.length === 0) return [];
            const chartStartMs = new Date(chartData[0].ts).getTime();
            const chartEndMs   = new Date(chartData[chartData.length - 1].ts).getTime();

            // Pre-compute domain max so we can place pills at the sensor's Y position
            const domainMax = Math.max(
              ...chartData.map(d => Math.max(
                d.moisture ?? 0, d.temp ?? 0, d.light ?? 0,
                d.humidity ?? 0, d.fan ?? 0, d.water ?? 0, d.water2 ?? 0
              ))
            ) * 1.08; // match recharts auto padding

            const visible = events.filter(ev => {
              const t = new Date(ev.ts).getTime();
              return t >= chartStartMs && t <= chartEndMs;
            });

            // Deduplicate: keep only the last event per type per 30-min window
            const buckets: Record<string, GardenEvent> = {};
            visible.forEach(ev => {
              const t = new Date(ev.ts).getTime();
              const bucket = Math.floor(t / (30 * 60 * 1000));
              const key = `${ev.type || "other"}-${bucket}`;
              buckets[key] = ev;
            });
            const deduped = Object.values(buckets).sort((a, b) =>
              new Date(a.ts).getTime() - new Date(b.ts).getTime()
            );

            const colCount: Record<string, number> = {};
            return deduped.flatMap((ev, i) => {
              const evMs = new Date(ev.ts).getTime();
              const nearestEntry = chartData.reduce((best, d) => {
                const diff = Math.abs(new Date(d.ts).getTime() - evMs);
                return diff < best.diff ? { d, diff } : best;
              }, { d: chartData[0], diff: Infinity });
              const evTime = nearestEntry.d.time;
              const slot = colCount[evTime] ?? 0;
              if (slot >= 2) return [];
              colCount[evTime] = slot + 1;

              const type = ev.type || "";
              const isValve = type === "valve" || type === "irrigate";
              const isLight = type === "light";
              const isFan   = type === "fan";
              const isHumid = type === "humidifier";

              const color = isValve ? "hsl(185, 90%, 55%)"
                          : isLight ? "hsl(48, 95%, 65%)"
                          : isFan   ? "hsl(200, 60%, 55%)"
                          : isHumid ? "hsl(270, 70%, 65%)"
                          : "hsl(220, 10%, 55%)";

              // Pick the data series value this event corresponds to, to place pill on that line
              const nd = nearestEntry.d;
              const seriesValue = isValve ? (nd.moisture ?? 50)
                                : isLight ? (nd.light ?? 80)
                                : isFan   ? (nd.fan ?? 40)
                                : isHumid ? (nd.humidity ?? 60)
                                : 50;

              const detail = (ev.detail || "")
                .replace("Valve A (plain water)", "A").replace("Valve B (grow nutrients)", "B").replace("Valve C (bloom nutrients)", "C")
                .replace(/peak=(\d+)%.*/, "$1%")
                .replace(/ON (\d+)%.*/, "$1%")
                .replace(/pump (\d+)s/, (_, s) => `${Math.round(parseInt(s)/60) || 1}m`)
                .split(" ")[0]
                .slice(0, 8);

              const pillH = 15;
              const pillPad = 5;
              const iconSize = 7;
              const gap = 3;
              const textW = detail.length * 5.5;
              const pillW = pillPad + iconSize + gap + textW + pillPad;

              const iconPath = isValve
                ? "M0-3.5 C1.5-3.5 3-1.5 3 0 C3 2 1.5 3.5 0 4.5 C-1.5 3.5-3 2-3 0 C-3-1.5-1.5-3.5 0-3.5Z"
                : isLight
                ? "M0-2.8a2.8 2.8 0 1 1 0 5.6 2.8 2.8 0 0 1 0-5.6zM0-4.5v-1M0 4.5v1M-4.5 0h-1M4.5 0h1M-3.2-3.2l-.7-.7M3.2 3.2l.7.7M3.2-3.2l.7-.7M-3.2 3.2l-.7.7"
                : isFan
                ? "M0-1 C0-3.5-3-3-2-1 C-3.5-2-3 2-1 2 C-2 3 2 3 2 1 C3.5 2 3-2 1-2 C2-3-2-3-2 1Z"
                : isHumid
                ? "M-3-0.5 Q0-4 3-0.5 Q3 3-0 3.5 Q-3 3-3-0.5Z"
                : "M0-2a2 2 0 1 1 0 4 2 2 0 0 1 0-4Z";

              return (
                <ReferenceLine
                  key={`ev-${i}`}
                  x={evTime}
                  stroke="none"
                  label={(props: any) => {
                    const cx = (props.viewBox?.x ?? 0);
                    const chartTop = props.viewBox?.y ?? 0;
                    const chartH   = props.viewBox?.height ?? 200;
                    // Place pill centered on the sensor's data line Y position
                    const lineY = chartTop + chartH * (1 - Math.min(1, seriesValue / domainMax));
                    const top = lineY - pillH / 2 - slot * (pillH + 4);
                    const midY = top + pillH / 2;
                    const left = cx - pillW / 2;

                    return (
                      <g style={{ pointerEvents: "none" }}>
                        <rect
                          x={left} y={top} width={pillW} height={pillH}
                          rx={pillH / 2} ry={pillH / 2}
                          fill={color} fillOpacity={0.18}
                          stroke={color} strokeOpacity={0.55} strokeWidth={0.8}
                        />
                        <g transform={`translate(${left + pillPad + iconSize / 2}, ${midY}) scale(0.95)`}>
                          <path d={iconPath} fill={isValve || isHumid ? color : "none"} fillOpacity={isValve || isHumid ? 0.9 : 0}
                            stroke={color} strokeWidth={1.1} strokeLinecap="round" strokeLinejoin="round" />
                        </g>
                        <text
                          x={left + pillPad + iconSize + gap}
                          y={midY + 3.5}
                          fontSize={8} fontWeight={700}
                          fill={color} textAnchor="start"
                          dominantBaseline="auto"
                        >
                          {detail}
                        </text>
                      </g>
                    );
                  }}
                />
              );
            });
          })()}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
