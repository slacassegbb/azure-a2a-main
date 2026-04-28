"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { LightSchedule, MoistureReading } from "@/lib/garden/types";
import { getCurrentBrightness, getLightPhase, getDayProgress } from "@/lib/garden/calculations";

interface LightTimelineProps {
  schedule: LightSchedule | null | undefined;
  readings?: MoistureReading[];
}

export default function LightTimeline({ schedule, readings = [] }: LightTimelineProps) {
  const [progress, setProgress] = useState(getDayProgress());
  const [brightness, setBrightness] = useState(0);
  const [phase, setPhase] = useState<string>("night");
  const [dragging, setDragging] = useState<"sunrise" | "sunset" | null>(null);
  const [dragHour, setDragHour] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    const update = () => {
      setProgress(getDayProgress());
      if (schedule) {
        setBrightness(getCurrentBrightness(schedule));
        setPhase(getLightPhase(schedule));
      }
    };
    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, [schedule]);

  const svgW = 500;
  const svgH = 160;
  const arcPadding = 40;
  const arcW = svgW - arcPadding * 2;
  const arcBottom = svgH - 25;
  const arcHeight = 100;

  // Convert SVG X position to hour (0-24)
  const xToHour = useCallback((clientX: number) => {
    if (!svgRef.current) return 12;
    const rect = svgRef.current.getBoundingClientRect();
    const svgX = ((clientX - rect.left) / rect.width) * svgW;
    const hour = ((svgX - arcPadding) / arcW) * 24;
    // Snap to 0.5 hour increments
    return Math.max(0, Math.min(23.5, Math.round(hour * 2) / 2));
  }, [arcW]);

  const saveSchedule = useCallback(async (sunriseHour: number, sunsetHour: number) => {
    try {
      await fetch("/api/garden/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "set_light_schedule",
          sunrise_hour: sunriseHour,
          sunset_hour: sunsetHour,
        }),
      });
    } catch { /* ignore */ }
  }, []);

  const handlePointerDown = (type: "sunrise" | "sunset") => (e: React.PointerEvent) => {
    e.preventDefault();
    (e.target as Element).setPointerCapture(e.pointerId);
    setDragging(type);
    setDragHour(type === "sunrise" ? schedule?.sunrise_hour ?? 5 : schedule?.sunset_hour ?? 20);
  };

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragging) return;
    const hour = xToHour(e.clientX);
    setDragHour(hour);
  }, [dragging, xToHour]);

  const handlePointerUp = useCallback(() => {
    if (!dragging || dragHour === null || !schedule) {
      setDragging(null);
      setDragHour(null);
      return;
    }
    const sunrise = dragging === "sunrise" ? dragHour : schedule.sunrise_hour;
    const sunset = dragging === "sunset" ? dragHour : schedule.sunset_hour;
    if (sunrise < sunset) {
      saveSchedule(sunrise, sunset);
    }
    setDragging(null);
    setDragHour(null);
  }, [dragging, dragHour, schedule, saveSchedule]);

  if (!schedule) {
    return (
      <div className="rounded-xl p-3 md:p-4 h-full" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
        <span className="text-sm" style={{ color: "hsl(220, 10%, 40%)" }}>No light schedule</span>
      </div>
    );
  }

  // Use drag values if actively dragging
  const displaySunrise = dragging === "sunrise" && dragHour !== null ? dragHour : schedule.sunrise_hour;
  const displaySunset = dragging === "sunset" && dragHour !== null ? dragHour : schedule.sunset_hour;

  const sunriseStart = displaySunrise / 24;
  const sunriseEnd = (displaySunrise + schedule.sunrise_ramp_min / 60) / 24;
  const sunsetStart = displaySunset / 24;
  const sunsetEnd = (displaySunset + schedule.sunset_ramp_min / 60) / 24;

  const isDaytime = progress >= sunriseStart && progress <= sunsetEnd;
  const dayRange = sunsetEnd - sunriseStart || 1;
  const dayProgress = isDaytime ? (progress - sunriseStart) / dayRange : 0;

  const sunX = arcPadding + dayProgress * arcW;
  const sunY = arcBottom - Math.sin(dayProgress * Math.PI) * arcHeight;

  const arcPoints: string[] = [];
  for (let i = 0; i <= 50; i++) {
    const t = i / 50;
    const x = arcPadding + t * arcW;
    const y = arcBottom - Math.sin(t * Math.PI) * arcHeight;
    arcPoints.push(`${x},${y}`);
  }
  const arcPath = `M ${arcPadding},${arcBottom} ` +
    arcPoints.map(p => `L ${p}`).join(" ") +
    ` L ${arcPadding + arcW},${arcBottom} Z`;
  const arcLinePath = `M ${arcPadding},${arcBottom} ` +
    arcPoints.map(p => `L ${p}`).join(" ");

  const sunSize = brightness > 0 ? 14 : 10;
  const sunGlow = brightness > 50 ? 20 : brightness > 0 ? 12 : 0;

  // Handle positions on horizon
  const sunriseHandleX = arcPadding;
  const sunsetHandleX = arcPadding + arcW;

  const formatHour = (h: number) => {
    const hr = Math.floor(h);
    const min = Math.round((h - hr) * 60);
    const ampm = hr < 12 ? "AM" : "PM";
    const h12 = hr === 0 ? 12 : hr > 12 ? hr - 12 : hr;
    return min > 0 ? `${h12}:${min.toString().padStart(2, "0")} ${ampm}` : `${h12} ${ampm}`;
  };

  return (
    <div className="rounded-xl p-3 md:p-4 h-full flex flex-col" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] uppercase tracking-wider font-medium" style={{ color: "hsl(220, 10%, 50%)" }}>
          Light Cycle
        </span>
        <div className="flex items-center gap-2">
          <span className="text-xl font-semibold" style={{ color: brightness > 0 ? "hsl(48, 95%, 65%)" : "hsl(220, 10%, 40%)" }}>
            {brightness}%
          </span>
        </div>
      </div>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${svgW} ${svgH}`}
        className="w-full flex-1"
        preserveAspectRatio="xMidYMid meet"
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        style={{ touchAction: "none" }}
      >
        <defs>
          <linearGradient id="skyGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={brightness > 50 ? "hsl(200, 80%, 55%)" : brightness > 0 ? "hsl(25, 70%, 35%)" : "hsl(220, 30%, 12%)"} stopOpacity={0.15} />
            <stop offset="100%" stopColor="hsl(220, 20%, 7%)" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="arcFill" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="hsl(220, 30%, 15%)" stopOpacity={0.3} />
            <stop offset={`${sunriseStart / (sunsetEnd || 1) * 100}%`} stopColor="hsl(35, 90%, 40%)" stopOpacity={0.2} />
            <stop offset="50%" stopColor="hsl(48, 95%, 55%)" stopOpacity={0.15} />
            <stop offset={`${sunsetStart / (sunsetEnd || 1) * 100}%`} stopColor="hsl(35, 90%, 40%)" stopOpacity={0.2} />
            <stop offset="100%" stopColor="hsl(220, 30%, 15%)" stopOpacity={0.3} />
          </linearGradient>
          <radialGradient id="sunGlow">
            <stop offset="0%" stopColor="hsl(48, 95%, 70%)" stopOpacity={0.6} />
            <stop offset="50%" stopColor="hsl(48, 95%, 65%)" stopOpacity={0.2} />
            <stop offset="100%" stopColor="hsl(48, 95%, 65%)" stopOpacity={0} />
          </radialGradient>
          <radialGradient id="moonGlow">
            <stop offset="0%" stopColor="hsl(220, 60%, 75%)" stopOpacity={0.4} />
            <stop offset="100%" stopColor="hsl(220, 60%, 75%)" stopOpacity={0} />
          </radialGradient>
        </defs>

        {/* Horizon line */}
        <line x1={arcPadding - 10} y1={arcBottom} x2={svgW - arcPadding + 10} y2={arcBottom}
          stroke="hsl(220, 15%, 18%)" strokeWidth="1" />

        {/* Arc fill */}
        <path d={arcPath} fill="url(#arcFill)" />

        {/* Dashed arc line */}
        <path d={arcLinePath} fill="none" stroke="hsl(220, 15%, 25%)" strokeWidth="1" strokeDasharray="4 4" />

        {/* Sunrise drag handle */}
        <g
          onPointerDown={handlePointerDown("sunrise")}
          style={{ cursor: "ew-resize" }}
        >
          <rect x={sunriseHandleX - 15} y={arcBottom - 15} width={30} height={30} fill="transparent" />
          <circle cx={sunriseHandleX} cy={arcBottom} r={5} fill={dragging === "sunrise" ? "hsl(35, 95%, 55%)" : "hsl(220, 15%, 30%)"} stroke="hsl(35, 95%, 55%)" strokeWidth={1.5} />
          <text x={sunriseHandleX} y={arcBottom + 15} textAnchor="middle" fontSize="9"
            fill={dragging === "sunrise" ? "hsl(35, 95%, 55%)" : "hsl(220, 10%, 40%)"} fontWeight={dragging === "sunrise" ? "bold" : "normal"}>
            {formatHour(displaySunrise)}
          </text>
        </g>

        {/* Sunset drag handle */}
        <g
          onPointerDown={handlePointerDown("sunset")}
          style={{ cursor: "ew-resize" }}
        >
          <rect x={sunsetHandleX - 15} y={arcBottom - 15} width={30} height={30} fill="transparent" />
          <circle cx={sunsetHandleX} cy={arcBottom} r={5} fill={dragging === "sunset" ? "hsl(35, 95%, 55%)" : "hsl(220, 15%, 30%)"} stroke="hsl(35, 95%, 55%)" strokeWidth={1.5} />
          <text x={sunsetHandleX} y={arcBottom + 15} textAnchor="middle" fontSize="9"
            fill={dragging === "sunset" ? "hsl(35, 95%, 55%)" : "hsl(220, 10%, 40%)"} fontWeight={dragging === "sunset" ? "bold" : "normal"}>
            {formatHour(displaySunset)}
          </text>
        </g>

        {/* Noon label */}
        <text x={svgW / 2} y={arcBottom + 15} textAnchor="middle" fontSize="9" fill="hsl(220, 10%, 35%)">
          12PM
        </text>

        {/* Drag tooltip */}
        {dragging && dragHour !== null && (
          <g>
            <rect x={xToSvg(dragHour) - 25} y={arcBottom - 35} width={50} height={18} rx={4}
              fill="hsl(35, 95%, 55%)" />
            <text x={xToSvg(dragHour)} y={arcBottom - 22} textAnchor="middle" fontSize="10" fontWeight="bold" fill="white">
              {formatHour(dragHour)}
            </text>
            <line x1={xToSvg(dragHour)} y1={arcBottom - 17} x2={xToSvg(dragHour)} y2={arcBottom}
              stroke="hsl(35, 95%, 55%)" strokeWidth={1.5} strokeDasharray="2 2" />
          </g>
        )}

        {/* Sun/Moon on the arc */}
        {isDaytime ? (
          <g>
            {sunGlow > 0 && (
              <circle cx={sunX} cy={sunY} r={sunGlow} fill="url(#sunGlow)">
                <animate attributeName="r" values={`${sunGlow};${sunGlow + 4};${sunGlow}`} dur="3s" repeatCount="indefinite" />
              </circle>
            )}
            <circle cx={sunX} cy={sunY} r={sunSize} fill="hsl(48, 95%, 65%)" />
            {brightness > 20 && [0, 45, 90, 135, 180, 225, 270, 315].map(angle => {
              const rad = (angle * Math.PI) / 180;
              const r1 = sunSize + 3;
              const r2 = sunSize + 7;
              return (
                <line key={angle}
                  x1={sunX + Math.cos(rad) * r1} y1={sunY + Math.sin(rad) * r1}
                  x2={sunX + Math.cos(rad) * r2} y2={sunY + Math.sin(rad) * r2}
                  stroke="hsl(48, 95%, 65%)" strokeWidth="1.5" strokeLinecap="round" opacity={brightness / 100} />
              );
            })}
            <text x={sunX} y={sunY - sunSize - 8} textAnchor="middle" fontSize="10" fontWeight="600" fill="hsl(48, 95%, 70%)">
              {brightness}%
            </text>
          </g>
        ) : (
          <g>
            <circle cx={progress < sunriseStart ? arcPadding - 15 : arcPadding + arcW + 15} cy={arcBottom - 15} r={8} fill="hsl(220, 40%, 55%)" />
            <circle cx={progress < sunriseStart ? arcPadding - 12 : arcPadding + arcW + 18} cy={arcBottom - 18} r={6} fill="hsl(220, 20%, 7%)" />
            <circle cx={progress < sunriseStart ? arcPadding - 15 : arcPadding + arcW + 15} cy={arcBottom - 15} r={14} fill="url(#moonGlow)" />
          </g>
        )}

        {/* Stars at night */}
        {phase === "night" && (
          <>
            <circle cx={80} cy={25} r={1} fill="hsl(220, 30%, 40%)" opacity={0.6} />
            <circle cx={150} cy={40} r={0.8} fill="hsl(220, 30%, 45%)" opacity={0.5} />
            <circle cx={250} cy={20} r={1.2} fill="hsl(220, 30%, 40%)" opacity={0.7} />
            <circle cx={350} cy={35} r={0.8} fill="hsl(220, 30%, 45%)" opacity={0.5} />
            <circle cx={420} cy={15} r={1} fill="hsl(220, 30%, 40%)" opacity={0.6} />
          </>
        )}

        {/* Real brightness history dots */}
        {readings.filter(r => r.light !== undefined && r.light > 0).map((r, i) => {
          const d = new Date(r.ts);
          const hourFrac = (d.getHours() + d.getMinutes() / 60) / 24;
          if (hourFrac < sunriseStart || hourFrac > sunsetEnd) return null;
          const t = (hourFrac - sunriseStart) / dayRange;
          const x = arcPadding + t * arcW;
          const maxY = Math.sin(t * Math.PI) * arcHeight;
          const y = arcBottom - (r.light! / 100) * maxY;
          return <circle key={i} cx={x} cy={y} r={2} fill="hsl(48, 95%, 65%)" opacity={0.6} />;
        })}
      </svg>

      {/* Ramp info */}
      <div className="flex justify-between mt-1 text-[10px]" style={{ color: "hsl(220, 10%, 40%)" }}>
        <span>🌅 {schedule.sunrise_ramp_min}min ramp</span>
        <span className="text-[10px] px-2 py-0.5 rounded-full" style={{
          background: phase === "day" ? "hsl(48, 95%, 65%, 0.1)" : phase === "night" ? "hsl(220, 30%, 20%, 0.5)" : "hsl(35, 95%, 55%, 0.1)",
          color: phase === "day" ? "hsl(48, 95%, 65%)" : phase === "night" ? "hsl(220, 40%, 55%)" : "hsl(35, 95%, 55%)",
        }}>
          {phase === "day" ? "☀ Daytime" : phase === "night" ? "🌙 Night" : phase === "sunrise" ? "🌅 Sunrise" : "🌇 Sunset"}
        </span>
        <span>🌇 {schedule.sunset_ramp_min}min ramp</span>
      </div>
    </div>
  );

  // Helper: convert hour to SVG X coordinate
  function xToSvg(hour: number): number {
    return arcPadding + (hour / 24) * arcW;
  }
}
