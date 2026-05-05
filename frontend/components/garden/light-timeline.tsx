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

  const svgW = 600;
  const svgH = 200;
  const PAD = 55;
  const arcW = svgW - PAD * 2;
  const HORIZON = svgH - 42;
  const ARC_H = 130;

  const xToHour = useCallback((clientX: number) => {
    if (!svgRef.current) return 12;
    const rect = svgRef.current.getBoundingClientRect();
    const svgX = ((clientX - rect.left) / rect.width) * svgW;
    const hour = ((svgX - PAD) / arcW) * 24;
    return Math.max(0, Math.min(23.5, Math.round(hour * 2) / 2));
  }, [arcW]);

  const xToSvg = (hour: number) => PAD + (hour / 24) * arcW;

  const saveSchedule = useCallback(async (sunriseHour: number, sunsetHour: number) => {
    try {
      await fetch("/api/garden/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "set_light_schedule", sunrise_hour: sunriseHour, sunset_hour: sunsetHour }),
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
    setDragHour(xToHour(e.clientX));
  }, [dragging, xToHour]);

  const handlePointerUp = useCallback(() => {
    if (!dragging || dragHour === null || !schedule) { setDragging(null); setDragHour(null); return; }
    const sunrise = dragging === "sunrise" ? dragHour : schedule.sunrise_hour;
    const sunset = dragging === "sunset" ? dragHour : schedule.sunset_hour;
    if (sunrise < sunset) saveSchedule(sunrise, sunset);
    setDragging(null);
    setDragHour(null);
  }, [dragging, dragHour, schedule, saveSchedule]);

  const formatHour = (h: number) => {
    const hr = Math.floor(h);
    const min = Math.round((h - hr) * 60);
    const ampm = hr < 12 ? "AM" : "PM";
    const h12 = hr === 0 ? 12 : hr > 12 ? hr - 12 : hr;
    return min > 0 ? `${h12}:${min.toString().padStart(2, "0")} ${ampm}` : `${h12} ${ampm}`;
  };

  if (!schedule) {
    return (
      <div className="rounded-xl p-4 h-full" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
        <span className="text-sm" style={{ color: "hsl(220, 10%, 40%)" }}>No light schedule</span>
      </div>
    );
  }

  const displaySunrise = dragging === "sunrise" && dragHour !== null ? dragHour : schedule.sunrise_hour;
  const displaySunset = dragging === "sunset" && dragHour !== null ? dragHour : schedule.sunset_hour;

  const sunriseStartFrac = displaySunrise / 24;
  const sunriseEndFrac = (displaySunrise + schedule.sunrise_ramp_min / 60) / 24;
  const sunsetStartFrac = displaySunset / 24;
  const sunsetEndFrac = (displaySunset + schedule.sunset_ramp_min / 60) / 24;

  const isDaytime = progress >= sunriseStartFrac && progress <= sunsetEndFrac;
  const dayRange = sunsetEndFrac - sunriseStartFrac || 1;
  const dayProgress = isDaytime ? (progress - sunriseStartFrac) / dayRange : 0;

  const sunX = PAD + dayProgress * arcW;
  const sunY = HORIZON - Math.sin(dayProgress * Math.PI) * ARC_H;

  // Arc path (full hemisphere)
  const arcPoints: [number, number][] = [];
  for (let i = 0; i <= 80; i++) {
    const t = i / 80;
    arcPoints.push([PAD + t * arcW, HORIZON - Math.sin(t * Math.PI) * ARC_H]);
  }
  const arcFillPath = `M ${PAD},${HORIZON} ` + arcPoints.map(([x, y]) => `L ${x},${y}`).join(" ") + ` L ${PAD + arcW},${HORIZON} Z`;
  const arcStrokePath = `M ${PAD},${HORIZON} ` + arcPoints.map(([x, y]) => `L ${x},${y}`).join(" ");

  // Sky color stops based on phase
  const isTransition = phase === "sunrise" || phase === "sunset";
  const skyTop = phase === "night" ? "#060a14" : isTransition ? "#1a0e24" : "#071220";
  const skyMid = phase === "night" ? "#0a0e1a" : isTransition ? "#3d1a10" : "#0c1e30";
  const skyHorizon = phase === "night" ? "#0d1220" : isTransition ? "#c2500a" : "#112840";

  const sunriseHandleX = PAD;
  const sunsetHandleX = PAD + arcW;

  return (
    <div className="rounded-xl overflow-hidden h-full flex flex-col" style={{ background: "#060a14", border: "1px solid hsl(220, 15%, 16%)" }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 pt-3 pb-1 shrink-0">
        <span className="text-[11px] uppercase tracking-widest font-medium" style={{ color: "hsl(220, 10%, 45%)" }}>
          Light Cycle
        </span>
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full" style={{ background: brightness > 0 ? "hsl(48,95%,65%)" : "hsl(220,20%,30%)", boxShadow: brightness > 0 ? "0 0 6px hsl(48,95%,65%)" : "none" }} />
          <span className="text-lg font-semibold tabular-nums" style={{ color: brightness > 0 ? "hsl(48,95%,70%)" : "hsl(220,10%,35%)" }}>
            {brightness}%
          </span>
        </div>
      </div>

      {/* SVG */}
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
          {/* Sky gradient */}
          <linearGradient id="lc-sky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={skyTop} />
            <stop offset="60%" stopColor={skyMid} />
            <stop offset="100%" stopColor={skyHorizon} />
          </linearGradient>

          {/* Arc fill: warm glow under the arc */}
          <linearGradient id="lc-arcfill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={brightness > 30 ? "hsl(45,90%,55%)" : "hsl(35,80%,35%)"} stopOpacity={brightness > 0 ? 0.12 : 0.05} />
            <stop offset="100%" stopColor={brightness > 30 ? "hsl(35,80%,40%)" : "hsl(220,30%,15%)"} stopOpacity={0} />
          </linearGradient>

          {/* Arc stroke gradient */}
          <linearGradient id="lc-arcstroke" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="hsl(220,30%,22%)" />
            <stop offset="20%" stopColor="hsl(30,80%,50%)" stopOpacity={0.7} />
            <stop offset="50%" stopColor={brightness > 50 ? "hsl(48,95%,65%)" : "hsl(40,80%,50%)"} stopOpacity={brightness > 0 ? 0.9 : 0.3} />
            <stop offset="80%" stopColor="hsl(30,80%,50%)" stopOpacity={0.7} />
            <stop offset="100%" stopColor="hsl(220,30%,22%)" />
          </linearGradient>

          {/* Sun glow */}
          <radialGradient id="lc-sunglow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="hsl(48,100%,75%)" stopOpacity={0.7} />
            <stop offset="40%" stopColor="hsl(40,95%,60%)" stopOpacity={0.25} />
            <stop offset="100%" stopColor="hsl(35,90%,50%)" stopOpacity={0} />
          </radialGradient>

          {/* Sun core */}
          <radialGradient id="lc-suncore" cx="40%" cy="35%" r="60%">
            <stop offset="0%" stopColor="hsl(55,100%,92%)" />
            <stop offset="50%" stopColor="hsl(48,100%,72%)" />
            <stop offset="100%" stopColor="hsl(38,95%,58%)" />
          </radialGradient>

          {/* Moon glow */}
          <radialGradient id="lc-moonglow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="hsl(220,60%,70%)" stopOpacity={0.35} />
            <stop offset="100%" stopColor="hsl(220,60%,70%)" stopOpacity={0} />
          </radialGradient>

          {/* Horizon glow */}
          <radialGradient id="lc-horizonglow" cx="50%" cy="100%" r="50%">
            <stop offset="0%" stopColor={isTransition ? "hsl(25,90%,55%)" : brightness > 0 ? "hsl(40,80%,45%)" : "hsl(220,40%,20%)"} stopOpacity={isTransition ? 0.35 : brightness > 0 ? 0.15 : 0.08} />
            <stop offset="100%" stopColor="transparent" stopOpacity={0} />
          </radialGradient>

          {/* Clip for sky background */}
          <clipPath id="lc-clip">
            <rect width={svgW} height={svgH} />
          </clipPath>
        </defs>

        {/* Sky background */}
        <rect width={svgW} height={svgH} fill="url(#lc-sky)" />

        {/* Horizon ambient glow */}
        <ellipse cx={svgW / 2} cy={HORIZON} rx={svgW * 0.6} ry={svgH * 0.4} fill="url(#lc-horizonglow)" />

        {/* Stars */}
        {phase === "night" && (
          <g opacity={0.8}>
            {[
              [70, 22, 1.2], [130, 38, 0.8], [190, 15, 1], [255, 28, 1.4],
              [310, 18, 0.9], [370, 42, 1.1], [430, 20, 0.8], [490, 32, 1.3],
              [540, 14, 1], [100, 55, 0.7], [340, 55, 0.9], [460, 48, 0.8],
            ].map(([cx, cy, r], i) => (
              <circle key={i} cx={cx} cy={cy} r={r} fill="white" opacity={0.5 + Math.random() * 0.3}>
                <animate attributeName="opacity" values={`${0.3 + i * 0.05};${0.7 + i * 0.02};${0.3 + i * 0.05}`}
                  dur={`${2.5 + i * 0.4}s`} repeatCount="indefinite" />
              </circle>
            ))}
          </g>
        )}

        {/* Arc fill (glow under arc) */}
        <path d={arcFillPath} fill="url(#lc-arcfill)" />

        {/* Arc stroke */}
        <path d={arcStrokePath} fill="none" stroke="url(#lc-arcstroke)" strokeWidth={1.5} strokeLinecap="round" opacity={0.8} />

        {/* Dashed arc overlay (faint) */}
        <path d={arcStrokePath} fill="none" stroke="white" strokeWidth={0.5} strokeDasharray="3 6" strokeLinecap="round" opacity={0.06} />

        {/* Horizon line */}
        <line x1={PAD - 12} y1={HORIZON} x2={svgW - PAD + 12} y2={HORIZON}
          stroke="hsl(220,20%,22%)" strokeWidth={1} />

        {/* Historical brightness dots */}
        {readings.filter(r => r.light !== undefined && r.light! > 0).map((r, i) => {
          const d = new Date(r.ts);
          const hf = (d.getHours() + d.getMinutes() / 60) / 24;
          if (hf < sunriseStartFrac || hf > sunsetEndFrac) return null;
          const t = (hf - sunriseStartFrac) / dayRange;
          const x = PAD + t * arcW;
          const maxArc = Math.sin(t * Math.PI) * ARC_H;
          const y = HORIZON - (r.light! / 100) * maxArc;
          return <circle key={i} cx={x} cy={y} r={2.5} fill="hsl(48,95%,65%)" opacity={0.5} />;
        })}

        {/* Sun or Moon */}
        {isDaytime ? (
          <g>
            {/* Outer glow rings */}
            {brightness > 20 && (
              <>
                <circle cx={sunX} cy={sunY} r={brightness > 60 ? 42 : 28} fill="url(#lc-sunglow)" opacity={0.5}>
                  <animate attributeName="r" values={`${brightness > 60 ? 40 : 26};${brightness > 60 ? 46 : 32};${brightness > 60 ? 40 : 26}`} dur="4s" repeatCount="indefinite" />
                </circle>
                <circle cx={sunX} cy={sunY} r={brightness > 60 ? 24 : 16} fill="hsl(48,95%,65%)" opacity={0.15}>
                  <animate attributeName="r" values={`${brightness > 60 ? 22 : 14};${brightness > 60 ? 26 : 18};${brightness > 60 ? 22 : 14}`} dur="3s" repeatCount="indefinite" />
                </circle>
              </>
            )}
            {/* Sun rays */}
            {brightness > 15 && [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330].map(angle => {
              const rad = (angle * Math.PI) / 180;
              const core = 12;
              const r1 = core + (angle % 60 === 0 ? 5 : 3);
              const r2 = core + (angle % 60 === 0 ? 11 : 7);
              return (
                <line key={angle}
                  x1={sunX + Math.cos(rad) * r1} y1={sunY + Math.sin(rad) * r1}
                  x2={sunX + Math.cos(rad) * r2} y2={sunY + Math.sin(rad) * r2}
                  stroke="hsl(48,95%,70%)" strokeWidth={angle % 60 === 0 ? 1.8 : 1.2}
                  strokeLinecap="round" opacity={brightness / 100 * 0.8} />
              );
            })}
            {/* Sun disc */}
            <circle cx={sunX} cy={sunY} r={13} fill="url(#lc-suncore)" />
            <circle cx={sunX} cy={sunY} r={13} fill="none" stroke="hsl(48,100%,80%)" strokeWidth={0.8} opacity={0.5} />
          </g>
        ) : (
          <g>
            {/* Moon */}
            {(() => {
              const mx = progress < sunriseStartFrac ? PAD - 18 : PAD + arcW + 18;
              const my = HORIZON - 22;
              return (
                <>
                  <circle cx={mx} cy={my} r={22} fill="url(#lc-moonglow)" />
                  <circle cx={mx} cy={my} r={11} fill="hsl(225,35%,62%)" />
                  <circle cx={mx + 4} cy={my - 3} r={9} fill={skyMid} />
                  {/* Subtle craters */}
                  <circle cx={mx - 2} cy={my + 2} r={1.5} fill="hsl(225,25%,50%)" opacity={0.5} />
                  <circle cx={mx + 1} cy={my + 5} r={1} fill="hsl(225,25%,50%)" opacity={0.4} />
                </>
              );
            })()}
          </g>
        )}

        {/* Sunrise drag handle */}
        <g onPointerDown={handlePointerDown("sunrise")} style={{ cursor: "ew-resize" }}>
          <rect x={sunriseHandleX - 20} y={HORIZON - 22} width={40} height={44} fill="transparent" />
          {/* Vertical tick */}
          <line x1={sunriseHandleX} y1={HORIZON - 8} x2={sunriseHandleX} y2={HORIZON}
            stroke={dragging === "sunrise" ? "hsl(35,95%,60%)" : "hsl(220,20%,35%)"} strokeWidth={1.5} />
          {/* Handle circle */}
          <circle cx={sunriseHandleX} cy={HORIZON} r={6}
            fill={dragging === "sunrise" ? "hsl(35,95%,55%)" : "hsl(220,18%,14%)"}
            stroke={dragging === "sunrise" ? "hsl(35,95%,70%)" : "hsl(35,80%,50%)"}
            strokeWidth={1.5} />
          {/* Inner dot */}
          <circle cx={sunriseHandleX} cy={HORIZON} r={2}
            fill={dragging === "sunrise" ? "white" : "hsl(35,80%,55%)"} />
          {/* Time label below */}
          <text x={sunriseHandleX} y={HORIZON + 18} textAnchor="middle" fontSize="9.5" fontWeight="500"
            fill={dragging === "sunrise" ? "hsl(35,95%,65%)" : "hsl(220,10%,45%)"}>
            {formatHour(displaySunrise)}
          </text>
        </g>

        {/* Sunset drag handle */}
        <g onPointerDown={handlePointerDown("sunset")} style={{ cursor: "ew-resize" }}>
          <rect x={sunsetHandleX - 20} y={HORIZON - 22} width={40} height={44} fill="transparent" />
          <line x1={sunsetHandleX} y1={HORIZON - 8} x2={sunsetHandleX} y2={HORIZON}
            stroke={dragging === "sunset" ? "hsl(35,95%,60%)" : "hsl(220,20%,35%)"} strokeWidth={1.5} />
          <circle cx={sunsetHandleX} cy={HORIZON} r={6}
            fill={dragging === "sunset" ? "hsl(35,95%,55%)" : "hsl(220,18%,14%)"}
            stroke={dragging === "sunset" ? "hsl(35,95%,70%)" : "hsl(35,80%,50%)"}
            strokeWidth={1.5} />
          <circle cx={sunsetHandleX} cy={HORIZON} r={2}
            fill={dragging === "sunset" ? "white" : "hsl(35,80%,55%)"} />
          <text x={sunsetHandleX} y={HORIZON + 18} textAnchor="middle" fontSize="9.5" fontWeight="500"
            fill={dragging === "sunset" ? "hsl(35,95%,65%)" : "hsl(220,10%,45%)"}>
            {formatHour(displaySunset)}
          </text>
        </g>

        {/* Noon label */}
        <text x={svgW / 2} y={HORIZON + 18} textAnchor="middle" fontSize="9" fill="hsl(220,10%,30%)">
          12 PM
        </text>

        {/* Drag tooltip */}
        {dragging && dragHour !== null && (
          <g>
            <rect x={xToSvg(dragHour) - 28} y={HORIZON - 38} width={56} height={20} rx={5}
              fill="hsl(35,95%,55%)" opacity={0.95} />
            <text x={xToSvg(dragHour)} y={HORIZON - 24} textAnchor="middle" fontSize="10.5" fontWeight="700" fill="white">
              {formatHour(dragHour)}
            </text>
            <line x1={xToSvg(dragHour)} y1={HORIZON - 18} x2={xToSvg(dragHour)} y2={HORIZON - 8}
              stroke="hsl(35,95%,55%)" strokeWidth={1.5} />
          </g>
        )}
      </svg>

      {/* Footer */}
      <div className="flex items-center justify-between px-4 pb-3 shrink-0">
        <span className="text-[10px]" style={{ color: "hsl(220,10%,38%)" }}>
          🌅 {schedule.sunrise_ramp_min}min ramp
        </span>
        <span className="text-[10px] px-2.5 py-0.5 rounded-full" style={{
          background: phase === "day" ? "rgba(251,191,36,0.1)" : phase === "night" ? "rgba(99,120,180,0.12)" : "rgba(251,146,36,0.12)",
          color: phase === "day" ? "hsl(48,95%,65%)" : phase === "night" ? "hsl(225,50%,65%)" : "hsl(35,95%,60%)",
          border: `1px solid ${phase === "day" ? "rgba(251,191,36,0.2)" : phase === "night" ? "rgba(99,120,180,0.2)" : "rgba(251,146,36,0.2)"}`,
        }}>
          {phase === "day" ? "☀ Daytime" : phase === "night" ? "🌙 Night" : phase === "sunrise" ? "🌅 Sunrise" : "🌇 Sunset"}
        </span>
        <span className="text-[10px]" style={{ color: "hsl(220,10%,38%)" }}>
          🌇 {schedule.sunset_ramp_min}min ramp
        </span>
      </div>
    </div>
  );
}
