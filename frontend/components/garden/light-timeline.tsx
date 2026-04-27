"use client";

import { useEffect, useState } from "react";
import { LightSchedule } from "@/lib/garden/types";
import { getCurrentBrightness, getLightPhase, getDayProgress } from "@/lib/garden/calculations";

interface LightTimelineProps {
  schedule: LightSchedule | null | undefined;
}

export default function LightTimeline({ schedule }: LightTimelineProps) {
  const [progress, setProgress] = useState(getDayProgress());
  const [brightness, setBrightness] = useState(0);
  const [phase, setPhase] = useState<string>("night");

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

  if (!schedule) {
    return (
      <div className="rounded-xl p-4" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
        <span className="text-sm" style={{ color: "hsl(220, 10%, 40%)" }}>No light schedule</span>
      </div>
    );
  }

  const sunriseStart = schedule.sunrise_hour / 24;
  const sunriseEnd = (schedule.sunrise_hour + schedule.sunrise_ramp_min / 60) / 24;
  const sunsetStart = schedule.sunset_hour / 24;
  const sunsetEnd = (schedule.sunset_hour + schedule.sunset_ramp_min / 60) / 24;

  // Sun position on the arc
  // Map progress to position on a semicircular arc
  // Only show sun above horizon between sunrise start and sunset end
  const isDaytime = progress >= sunriseStart && progress <= sunsetEnd;
  const dayRange = sunsetEnd - sunriseStart;
  const dayProgress = isDaytime ? (progress - sunriseStart) / dayRange : 0;

  // Arc path: semicircle from left to right
  const svgW = 500;
  const svgH = 160;
  const arcPadding = 40;
  const arcW = svgW - arcPadding * 2;
  const arcBottom = svgH - 25;
  const arcHeight = 100;

  // Calculate sun position on arc
  const sunX = arcPadding + dayProgress * arcW;
  const sunY = arcBottom - Math.sin(dayProgress * Math.PI) * arcHeight;

  // Generate arc path points for the gradient fill
  const arcPoints: string[] = [];
  for (let i = 0; i <= 50; i++) {
    const t = i / 50;
    const x = arcPadding + t * arcW;
    const y = arcBottom - Math.sin(t * Math.PI) * arcHeight;
    arcPoints.push(`${x},${y}`);
  }
  // Close the path along the bottom
  const arcPath = `M ${arcPadding},${arcBottom} ` +
    arcPoints.map((p, i) => (i === 0 ? `L ${p}` : `L ${p}`)).join(" ") +
    ` L ${arcPadding + arcW},${arcBottom} Z`;

  // Dashed arc line (just the curve, no fill)
  const arcLinePath = `M ${arcPadding},${arcBottom} ` +
    arcPoints.map(p => `L ${p}`).join(" ");

  const phaseColor = phase === "night" ? "hsl(220, 40%, 30%)" : phase === "day" ? "hsl(48, 95%, 65%)" : "hsl(35, 95%, 55%)";
  const sunSize = brightness > 0 ? 14 : 10;
  const sunGlow = brightness > 50 ? 20 : brightness > 0 ? 12 : 0;

  return (
    <div className="rounded-xl p-4" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
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

      <svg viewBox={`0 0 ${svgW} ${svgH}`} className="w-full" style={{ maxHeight: "160px" }}>
        <defs>
          {/* Sky gradient */}
          <linearGradient id="skyGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={brightness > 50 ? "hsl(200, 80%, 55%)" : brightness > 0 ? "hsl(25, 70%, 35%)" : "hsl(220, 30%, 12%)"} stopOpacity={0.15} />
            <stop offset="100%" stopColor="hsl(220, 20%, 7%)" stopOpacity={0} />
          </linearGradient>
          {/* Arc fill gradient */}
          <linearGradient id="arcFill" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="hsl(220, 30%, 15%)" stopOpacity={0.3} />
            <stop offset={`${sunriseStart / (sunsetEnd || 1) * 100}%`} stopColor="hsl(35, 90%, 40%)" stopOpacity={0.2} />
            <stop offset="50%" stopColor="hsl(48, 95%, 55%)" stopOpacity={0.15} />
            <stop offset={`${sunsetStart / (sunsetEnd || 1) * 100}%`} stopColor="hsl(35, 90%, 40%)" stopOpacity={0.2} />
            <stop offset="100%" stopColor="hsl(220, 30%, 15%)" stopOpacity={0.3} />
          </linearGradient>
          {/* Sun glow */}
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

        {/* Sunrise label */}
        <text x={arcPadding} y={arcBottom + 15} textAnchor="middle" fontSize="9" fill="hsl(220, 10%, 40%)">
          {schedule.sunrise_hour}AM
        </text>

        {/* Sunset label */}
        <text x={arcPadding + arcW} y={arcBottom + 15} textAnchor="middle" fontSize="9" fill="hsl(220, 10%, 40%)">
          {schedule.sunset_hour > 12 ? schedule.sunset_hour - 12 : schedule.sunset_hour}PM
        </text>

        {/* Noon label */}
        <text x={svgW / 2} y={arcBottom + 15} textAnchor="middle" fontSize="9" fill="hsl(220, 10%, 35%)">
          12PM
        </text>

        {/* Sun/Moon on the arc */}
        {isDaytime ? (
          <g>
            {/* Glow */}
            {sunGlow > 0 && (
              <circle cx={sunX} cy={sunY} r={sunGlow} fill="url(#sunGlow)">
                <animate attributeName="r" values={`${sunGlow};${sunGlow + 4};${sunGlow}`} dur="3s" repeatCount="indefinite" />
              </circle>
            )}
            {/* Sun body */}
            <circle cx={sunX} cy={sunY} r={sunSize} fill="hsl(48, 95%, 65%)" />
            {/* Sun rays */}
            {brightness > 20 && [0, 45, 90, 135, 180, 225, 270, 315].map(angle => {
              const rad = (angle * Math.PI) / 180;
              const r1 = sunSize + 3;
              const r2 = sunSize + 7;
              return (
                <line
                  key={angle}
                  x1={sunX + Math.cos(rad) * r1}
                  y1={sunY + Math.sin(rad) * r1}
                  x2={sunX + Math.cos(rad) * r2}
                  y2={sunY + Math.sin(rad) * r2}
                  stroke="hsl(48, 95%, 65%)"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  opacity={brightness / 100}
                />
              );
            })}
            {/* Brightness label near sun */}
            <text x={sunX} y={sunY - sunSize - 8} textAnchor="middle" fontSize="10" fontWeight="600" fill="hsl(48, 95%, 70%)">
              {brightness}%
            </text>
          </g>
        ) : (
          <g>
            {/* Moon position — show at edges */}
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
      </svg>

      {/* Ramp info */}
      <div className="flex justify-between mt-1 text-[10px]" style={{ color: "hsl(220, 10%, 40%)" }}>
        <span>🌅 Sunrise {schedule.sunrise_ramp_min}min ramp</span>
        <span className="text-[10px] px-2 py-0.5 rounded-full" style={{
          background: phase === "day" ? "hsl(48, 95%, 65%, 0.1)" : phase === "night" ? "hsl(220, 30%, 20%, 0.5)" : "hsl(35, 95%, 55%, 0.1)",
          color: phase === "day" ? "hsl(48, 95%, 65%)" : phase === "night" ? "hsl(220, 40%, 55%)" : "hsl(35, 95%, 55%)",
        }}>
          {phase === "day" ? "☀ Daytime" : phase === "night" ? "🌙 Night" : phase === "sunrise" ? "🌅 Sunrise" : "🌇 Sunset"}
        </span>
        <span>🌇 Sunset {schedule.sunset_ramp_min}min ramp</span>
      </div>
    </div>
  );
}
