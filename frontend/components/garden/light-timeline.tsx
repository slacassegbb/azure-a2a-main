"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { LightSchedule, MoistureReading } from "@/lib/garden/types";
import { getCurrentBrightness, getLightPhase, getDayProgress } from "@/lib/garden/calculations";

interface LightTimelineProps {
  schedule: LightSchedule | null | undefined;
  readings?: MoistureReading[];
}

// Sky palette per phase
const SKY: Record<string, [string, string]> = {
  night:   ["#0b0c2a", "#1a1b4b"],
  sunrise: ["#ff6b35", "#ffd166"],
  day:     ["#48cae4", "#90e0ef"],
  sunset:  ["#c1440e", "#f4a261"],
};
const GROUND: Record<string, [string, string]> = {
  night:   ["#0d1f0d", "#0a160a"],
  sunrise: ["#1a3a10", "#0d2009"],
  day:     ["#2d6a1f", "#1a4012"],
  sunset:  ["#1a3010", "#0d1a08"],
};

export default function LightTimeline({ schedule, readings = [] }: LightTimelineProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ w: 600, h: 400 });
  const [progress, setProgress] = useState(getDayProgress());
  const [brightness, setBrightness] = useState(0);
  const [phase, setPhase] = useState<string>("night");
  const [dragging, setDragging] = useState<"sunrise" | "sunset" | null>(null);
  const [dragHour, setDragHour] = useState<number | null>(null);

  // Track container size
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      if (width > 10 && height > 10) setSize({ w: width, h: height });
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

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

  const { w: W, h: H } = size;
  const PAD = W * 0.07;
  const arcW = W - PAD * 2;
  const GNDLINE = H * 0.72;
  const ARC_H = H * 0.55;

  const xToHour = useCallback((clientX: number) => {
    if (!svgRef.current) return 12;
    const rect = svgRef.current.getBoundingClientRect();
    const svgX = clientX - rect.left;
    const hour = ((svgX - PAD) / arcW) * 24;
    return Math.max(0, Math.min(23.5, Math.round(hour * 2) / 2));
  }, [PAD, arcW]);

  const xToSvg = useCallback((hour: number) => PAD + (hour / 24) * arcW, [PAD, arcW]);

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

  const fmt = (h: number) => {
    const hr = Math.floor(h), min = Math.round((h - hr) * 60);
    const ampm = hr < 12 ? "AM" : "PM";
    const h12 = hr === 0 ? 12 : hr > 12 ? hr - 12 : hr;
    return min > 0 ? `${h12}:${min.toString().padStart(2, "0")}${ampm}` : `${h12}${ampm}`;
  };

  if (!schedule) return (
    <div ref={containerRef} className="rounded-2xl w-full h-full flex items-center justify-center" style={{ background: "#1a1a2e" }}>
      <span style={{ color: "#666", fontSize: 14 }}>No light schedule</span>
    </div>
  );

  const displaySunrise = dragging === "sunrise" && dragHour !== null ? dragHour : schedule.sunrise_hour;
  const displaySunset  = dragging === "sunset"  && dragHour !== null ? dragHour : schedule.sunset_hour;

  const sunriseFrac    = displaySunrise / 24;
  const sunriseEndFrac = (displaySunrise + schedule.sunrise_ramp_min / 60) / 24;
  const sunsetEndFrac  = (displaySunset  + schedule.sunset_ramp_min / 60) / 24;

  const isDaytime  = progress >= sunriseFrac && progress <= sunsetEndFrac;
  const dayRange   = sunsetEndFrac - sunriseFrac || 1;
  const dayProg    = isDaytime ? (progress - sunriseFrac) / dayRange : 0;

  const sunX = PAD + dayProg * arcW;
  const sunY = GNDLINE - Math.sin(dayProg * Math.PI) * ARC_H;

  // Moon travels the same arc at night
  const nightDuration = (1 - sunsetEndFrac) + sunriseFrac;
  const nightProg = !isDaytime
    ? (progress > sunsetEndFrac
        ? (progress - sunsetEndFrac) / nightDuration
        : (progress + 1 - sunsetEndFrac) / nightDuration)
    : 0;
  // Moon travels right→left (sunset side to sunrise side)
  const moonX = PAD + (1 - nightProg) * arcW;
  const moonY = GNDLINE - Math.sin((1 - nightProg) * Math.PI) * ARC_H;

  const sky    = SKY[phase]    ?? SKY.night;
  const ground = GROUND[phase] ?? GROUND.night;

  // Arc path
  const arcPts: [number, number][] = Array.from({ length: 81 }, (_, i) => {
    const t = i / 80;
    return [PAD + t * arcW, GNDLINE - Math.sin(t * Math.PI) * ARC_H];
  });
  const arcD = `M ${arcPts.map(([x, y]) => `${x},${y}`).join(" L ")}`;

  // Handle positions
  const srX = xToSvg(displaySunrise);
  const ssX = xToSvg(displaySunset);

  const handleR    = Math.max(16, W * 0.028);
  const fontSize   = Math.max(10, W * 0.018);
  const labelFS    = Math.max(9, W * 0.015);
  const groundBump = H * 0.055;
  const plantScale = H * 0.0012;

  // Stars
  const stars = [
    [0.08, 0.08], [0.18, 0.22], [0.28, 0.06], [0.42, 0.14], [0.55, 0.05],
    [0.63, 0.20], [0.73, 0.09], [0.83, 0.17], [0.92, 0.07], [0.15, 0.35],
    [0.48, 0.30], [0.70, 0.32], [0.35, 0.25],
  ].map(([fx, fy]) => ({ x: fx * W, y: fy * GNDLINE }));

  const isNight = phase === "night";
  const isDay   = phase === "day";

  return (
    <div ref={containerRef} className="rounded-2xl overflow-hidden w-full h-full" style={{ background: sky[0] }}>
      <svg
        ref={svgRef}
        width={W} height={H}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        style={{ display: "block", touchAction: "none" }}
      >
        <defs>
          <linearGradient id="ct-sky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={sky[0]} />
            <stop offset="100%" stopColor={sky[1]} />
          </linearGradient>
          <linearGradient id="ct-ground" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={ground[0]} />
            <stop offset="100%" stopColor={ground[1]} />
          </linearGradient>
          <radialGradient id="ct-sunhalo" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#FFD700" stopOpacity={0.5} />
            <stop offset="60%" stopColor="#FFB800" stopOpacity={0.15} />
            <stop offset="100%" stopColor="#FF8C00" stopOpacity={0} />
          </radialGradient>
          <radialGradient id="ct-moonhalo" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#e8eaf6" stopOpacity={0.4} />
            <stop offset="100%" stopColor="#9fa8da" stopOpacity={0} />
          </radialGradient>
          <filter id="ct-glow">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <filter id="ct-softshadow">
            <feDropShadow dx="0" dy="2" stdDeviation="3" floodOpacity="0.3" />
          </filter>
        </defs>

        {/* Sky */}
        <rect width={W} height={H} fill="url(#ct-sky)" />

        {/* === STARS (night) === */}
        {isNight && stars.map((s, i) => (
          <g key={i}>
            {/* 4-pointed cartoon star */}
            <path
              d={`M ${s.x},${s.y - 4} L ${s.x + 1.2},${s.y - 1.2} L ${s.x + 4},${s.y} L ${s.x + 1.2},${s.y + 1.2} L ${s.x},${s.y + 4} L ${s.x - 1.2},${s.y + 1.2} L ${s.x - 4},${s.y} L ${s.x - 1.2},${s.y - 1.2} Z`}
              fill="white" opacity={0.7 + (i % 3) * 0.1}
            >
              <animate attributeName="opacity"
                values={`${0.4 + (i % 4) * 0.1};${0.9};${0.4 + (i % 4) * 0.1}`}
                dur={`${1.8 + i * 0.3}s`} repeatCount="indefinite" />
            </path>
          </g>
        ))}

        {/* === CARTOON CLOUDS (day) === */}
        {isDay && [
          { x: W * 0.15, y: H * 0.12, s: 1.0 },
          { x: W * 0.62, y: H * 0.08, s: 0.75 },
          { x: W * 0.82, y: H * 0.18, s: 0.6 },
        ].map((c, i) => (
          <g key={i} transform={`translate(${c.x}, ${c.y}) scale(${c.s})`} opacity={0.92}>
            <ellipse cx={0}   cy={0}  rx={36} ry={22} fill="white" />
            <ellipse cx={-22} cy={4}  rx={24} ry={16} fill="white" />
            <ellipse cx={24}  cy={4}  rx={26} ry={17} fill="white" />
            <ellipse cx={0}   cy={8}  rx={38} ry={16} fill="white" />
            {/* Outline */}
            <ellipse cx={0}   cy={0}  rx={36} ry={22} fill="none" stroke="#e0e0e0" strokeWidth={2} />
            <ellipse cx={-22} cy={4}  rx={24} ry={16} fill="none" stroke="#e0e0e0" strokeWidth={2} />
            <ellipse cx={24}  cy={4}  rx={26} ry={17} fill="none" stroke="#e0e0e0" strokeWidth={2} />
          </g>
        ))}

        {/* === ARC PATH === */}
        {/* Glow under arc */}
        <path d={arcD} fill="none"
          stroke={isDay ? "#FFD700" : isNight ? "#4a5568" : "#ff9f43"}
          strokeWidth={8} strokeLinecap="round" opacity={0.15} />
        {/* Main arc — thick dashed cartoon style */}
        <path d={arcD} fill="none"
          stroke={isDay ? "#FFD700" : isNight ? "#6c757d" : "#ffd166"}
          strokeWidth={3} strokeLinecap="round"
          strokeDasharray={isNight ? "8 10" : "none"}
          opacity={isNight ? 0.4 : 0.7} />

        {/* === SUN === */}
        {isDaytime && (() => {
          const r = Math.max(18, W * 0.038);
          const glowR = r * 2.8;
          const rayLen = r * 0.7;
          const rayGap = r * 1.25;
          return (
            <g filter="url(#ct-glow)">
              {/* Halo */}
              <circle cx={sunX} cy={sunY} r={glowR} fill="url(#ct-sunhalo)">
                <animate attributeName="r" values={`${glowR};${glowR * 1.15};${glowR}`} dur="3s" repeatCount="indefinite" />
              </circle>
              {/* Rays */}
              {[0, 45, 90, 135, 180, 225, 270, 315].map(angle => {
                const rad = (angle * Math.PI) / 180;
                const x1 = sunX + Math.cos(rad) * rayGap;
                const y1 = sunY + Math.sin(rad) * rayGap;
                const x2 = sunX + Math.cos(rad) * (rayGap + rayLen);
                const y2 = sunY + Math.sin(rad) * (rayGap + rayLen);
                return <line key={angle} x1={x1} y1={y1} x2={x2} y2={y2}
                  stroke="#FFD700" strokeWidth={3.5} strokeLinecap="round"
                  opacity={brightness / 100 * 0.9}>
                  <animateTransform attributeName="transform" type="rotate"
                    from={`0 ${sunX} ${sunY}`} to={`360 ${sunX} ${sunY}`}
                    dur="20s" repeatCount="indefinite" />
                </line>;
              })}
              {/* Sun disc */}
              <circle cx={sunX} cy={sunY} r={r} fill="#FFD700" stroke="#FF8C00" strokeWidth={3} />
              {/* Face */}
              {brightness > 30 && <>
                <circle cx={sunX - r * 0.28} cy={sunY - r * 0.1} r={r * 0.12} fill="#FF8C00" />
                <circle cx={sunX + r * 0.28} cy={sunY - r * 0.1} r={r * 0.12} fill="#FF8C00" />
                <path d={`M ${sunX - r * 0.3},${sunY + r * 0.2} Q ${sunX},${sunY + r * 0.45} ${sunX + r * 0.3},${sunY + r * 0.2}`}
                  fill="none" stroke="#FF8C00" strokeWidth={2.5} strokeLinecap="round" />
              </>}
            </g>
          );
        })()}

        {/* === HISTORICAL BRIGHTNESS DOTS === */}
        {readings.filter(r => r.light !== undefined && r.light! > 0).map((r, i) => {
          const d = new Date(r.ts);
          const hf = (d.getHours() + d.getMinutes() / 60) / 24;
          if (hf < sunriseFrac || hf > sunsetEndFrac) return null;
          const t = (hf - sunriseFrac) / dayRange;
          const x = PAD + t * arcW;
          const y = GNDLINE - (r.light! / 100) * Math.sin(t * Math.PI) * ARC_H;
          return <circle key={i} cx={x} cy={y} r={3} fill="#FFD700" opacity={0.55} />;
        })}

        {/* === MOON (travels the arc at night) === */}
        {!isDaytime && (() => {
          const mr = Math.max(14, W * 0.026);
          return (
            <g>
              <circle cx={moonX} cy={moonY} r={mr * 2.8} fill="url(#ct-moonhalo)" />
              <circle cx={moonX} cy={moonY} r={mr} fill="#f5f0e8" stroke="#c8c0b0" strokeWidth={2.5} />
              <circle cx={moonX + mr * 0.38} cy={moonY - mr * 0.22} r={mr * 0.82} fill={sky[1]} />
              <circle cx={moonX - mr * 0.3} cy={moonY + mr * 0.2} r={mr * 0.14} fill="#ddd8cc" opacity={0.7} />
              <circle cx={moonX - mr * 0.5} cy={moonY - mr * 0.1} r={mr * 0.09} fill="#ddd8cc" opacity={0.6} />
            </g>
          );
        })()}

        {/* === BACKGROUND HILLS === */}
        <path
          d={`M 0,${GNDLINE - groundBump * 0.6}
              C ${W*0.12},${GNDLINE - groundBump * 1.4} ${W*0.22},${GNDLINE - groundBump * 1.0} ${W*0.35},${GNDLINE - groundBump * 1.3}
              C ${W*0.48},${GNDLINE - groundBump * 1.6} ${W*0.58},${GNDLINE - groundBump * 0.9} ${W*0.70},${GNDLINE - groundBump * 1.2}
              C ${W*0.82},${GNDLINE - groundBump * 1.5} ${W*0.92},${GNDLINE - groundBump * 0.8} ${W},${GNDLINE - groundBump * 1.0}
              L ${W},${H} L 0,${H} Z`}
          fill={ground[0]} opacity={0.6}
        />

        {/* === MAIN GROUND === */}
        <path
          d={`M 0,${GNDLINE}
              C ${W*0.15},${GNDLINE - groundBump * 0.9} ${W*0.28},${GNDLINE - groundBump * 0.4} ${W*0.42},${GNDLINE - groundBump * 0.7}
              C ${W*0.56},${GNDLINE - groundBump * 1.0} ${W*0.68},${GNDLINE - groundBump * 0.3} ${W*0.82},${GNDLINE - groundBump * 0.6}
              C ${W*0.92},${GNDLINE - groundBump * 0.8} ${W*0.97},${GNDLINE - groundBump * 0.2} ${W},${GNDLINE - groundBump * 0.3}
              L ${W},${H} L 0,${H} Z`}
          fill="url(#ct-ground)"
          stroke={phase === "day" ? "#3a7d1e" : "#1a3a0e"}
          strokeWidth={2.5}
        />

        {/* === CARTOON PLANTS === */}
        {[0.10, 0.22, 0.37, 0.50, 0.63, 0.77, 0.90].map((fx, i) => {
          const px = fx * W;
          const py = GNDLINE - groundBump * 0.3;
          const ph = H * (0.08 + (i % 3) * 0.03);
          const pw = ph * 0.5;
          const leafColor = isDay ? "#4caf50" : isNight ? "#1a3a10" : "#388e3c";
          const stemColor = isDay ? "#2e7d32" : "#1a2e10";
          return (
            <g key={i}>
              {/* Stem */}
              <line x1={px} y1={py} x2={px} y2={py - ph}
                stroke={stemColor} strokeWidth={Math.max(2, pw * 0.18)} strokeLinecap="round" />
              {/* Left leaf */}
              <path d={`M ${px},${py - ph * 0.55} C ${px - pw * 1.2},${py - ph * 0.75} ${px - pw * 0.8},${py - ph * 0.4} ${px},${py - ph * 0.42}`}
                fill={leafColor} stroke={stemColor} strokeWidth={1} />
              {/* Right leaf */}
              <path d={`M ${px},${py - ph * 0.38} C ${px + pw * 1.2},${py - ph * 0.58} ${px + pw * 0.8},${py - ph * 0.22} ${px},${py - ph * 0.20}`}
                fill={leafColor} stroke={stemColor} strokeWidth={1} />
              {/* Top bud */}
              <ellipse cx={px} cy={py - ph} rx={pw * 0.55} ry={pw * 0.65}
                fill={isDay ? "#81c784" : leafColor} stroke={stemColor} strokeWidth={1.2} />
            </g>
          );
        })}

        {/* === HORIZON LINE === */}
        <line x1={0} y1={GNDLINE} x2={W} y2={GNDLINE}
          stroke={phase === "day" ? "#4caf50" : "#2a4a1a"} strokeWidth={2} opacity={0.5} />

        {/* === SUNRISE DRAG HANDLE === */}
        <g onPointerDown={handlePointerDown("sunrise")} style={{ cursor: "ew-resize" }}>
          <rect x={srX - handleR * 1.5} y={GNDLINE - handleR * 3.5} width={handleR * 3} height={handleR * 5} fill="transparent" />
          {/* Pole */}
          <line x1={srX} y1={GNDLINE} x2={srX} y2={GNDLINE - handleR * 2.2}
            stroke={dragging === "sunrise" ? "#ff9f43" : "#666"} strokeWidth={3} strokeLinecap="round" />
          {/* Button */}
          <circle cx={srX} cy={GNDLINE - handleR * 2.4} r={handleR}
            fill={dragging === "sunrise" ? "#ff9f43" : "#2d3748"}
            stroke={dragging === "sunrise" ? "#fff" : "#ff9f43"}
            strokeWidth={2.5} filter={dragging === "sunrise" ? "url(#ct-glow)" : undefined} />
          {/* Icon: sunrise arrow */}
          <path d={`M ${srX - handleR * 0.35},${GNDLINE - handleR * 2.55} L ${srX},${GNDLINE - handleR * 2.85} L ${srX + handleR * 0.35},${GNDLINE - handleR * 2.55}`}
            fill="none" stroke={dragging === "sunrise" ? "white" : "#ff9f43"} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
          {/* Time label */}
          <rect x={srX - handleR * 1.7} y={GNDLINE + handleR * 0.3} width={handleR * 3.4} height={handleR * 1.1} rx={handleR * 0.4}
            fill={dragging === "sunrise" ? "#ff9f43" : "#1a202c"} opacity={0.9} />
          <text x={srX} y={GNDLINE + handleR * 1.15} textAnchor="middle" fontSize={labelFS} fontWeight="700"
            fill={dragging === "sunrise" ? "white" : "#ff9f43"} fontFamily="monospace">
            {fmt(displaySunrise)}
          </text>
        </g>

        {/* === SUNSET DRAG HANDLE === */}
        <g onPointerDown={handlePointerDown("sunset")} style={{ cursor: "ew-resize" }}>
          <rect x={ssX - handleR * 1.5} y={GNDLINE - handleR * 3.5} width={handleR * 3} height={handleR * 5} fill="transparent" />
          <line x1={ssX} y1={GNDLINE} x2={ssX} y2={GNDLINE - handleR * 2.2}
            stroke={dragging === "sunset" ? "#f7971e" : "#666"} strokeWidth={3} strokeLinecap="round" />
          <circle cx={ssX} cy={GNDLINE - handleR * 2.4} r={handleR}
            fill={dragging === "sunset" ? "#f7971e" : "#2d3748"}
            stroke={dragging === "sunset" ? "#fff" : "#f7971e"}
            strokeWidth={2.5} filter={dragging === "sunset" ? "url(#ct-glow)" : undefined} />
          {/* Icon: sunset arrow */}
          <path d={`M ${ssX - handleR * 0.35},${GNDLINE - handleR * 2.25} L ${ssX},${GNDLINE - handleR * 1.95} L ${ssX + handleR * 0.35},${GNDLINE - handleR * 2.25}`}
            fill="none" stroke={dragging === "sunset" ? "white" : "#f7971e"} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
          <rect x={ssX - handleR * 1.7} y={GNDLINE + handleR * 0.3} width={handleR * 3.4} height={handleR * 1.1} rx={handleR * 0.4}
            fill={dragging === "sunset" ? "#f7971e" : "#1a202c"} opacity={0.9} />
          <text x={ssX} y={GNDLINE + handleR * 1.15} textAnchor="middle" fontSize={labelFS} fontWeight="700"
            fill={dragging === "sunset" ? "white" : "#f7971e"} fontFamily="monospace">
            {fmt(displaySunset)}
          </text>
        </g>

        {/* === DRAG TOOLTIP === */}
        {dragging && dragHour !== null && (() => {
          const tx = Math.max(50, Math.min(W - 50, xToSvg(dragHour)));
          const ty = GNDLINE - handleR * 4.5;
          return (
            <g>
              <rect x={tx - 34} y={ty - 14} width={68} height={26} rx={8}
                fill={dragging === "sunrise" ? "#ff9f43" : "#f7971e"}
                filter="url(#ct-softshadow)" />
              <text x={tx} y={ty + 4} textAnchor="middle" fontSize={fontSize} fontWeight="800"
                fill="white" fontFamily="monospace">{fmt(dragHour)}</text>
              {/* Arrow pointing down */}
              <path d={`M ${tx - 7},${ty + 12} L ${tx},${ty + 20} L ${tx + 7},${ty + 12}`}
                fill={dragging === "sunrise" ? "#ff9f43" : "#f7971e"} />
            </g>
          );
        })()}

        {/* === 12PM LABEL === */}
        <text x={W / 2} y={GNDLINE + handleR * 1.15} textAnchor="middle" fontSize={labelFS}
          fill="#4a5568" fontFamily="sans-serif">12 PM</text>

        {/* === PHASE BADGE === */}
        {(() => {
          const label = phase === "day" ? "☀ Daytime" : phase === "night" ? "🌙 Night" : phase === "sunrise" ? "🌅 Sunrise" : "🌇 Sunset";
          const bg = phase === "night" ? "#1a237e" : phase === "day" ? "#f9a825" : "#e65100";
          const fg = phase === "day" ? "#fff8e1" : "white";
          const bw = 80, bh = 22, bx = W / 2 - bw / 2, by = H - bh - H * 0.02;
          return (
            <g>
              <rect x={bx} y={by} width={bw} height={bh} rx={11} fill={bg} opacity={0.9} />
              <text x={W / 2} y={by + 14} textAnchor="middle" fontSize={11} fontWeight="700" fill={fg}>
                {label}
              </text>
            </g>
          );
        })()}

      </svg>
    </div>
  );
}
