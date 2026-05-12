"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { LightSchedule, MoistureReading, GardenConfig } from "@/lib/garden/types";
import { getCurrentBrightness, getLightPhase, getDayProgress } from "@/lib/garden/calculations";

interface LightTimelineProps {
  schedule: LightSchedule | null | undefined;
  readings?: MoistureReading[];
  gardenConfig?: GardenConfig | null;
}

// ── Sky multi-stop gradients (Rayleigh-inspired) ───────────────────────────
const SKY_STOPS: Record<string, [string, string][]> = {
  night:   [["0%","#010208"],["30%","#030a1c"],["60%","#051230"],["100%","#080f3a"]],
  sunrise: [["0%","#07081e"],["22%","#1c1240"],["46%","#681808"],["66%","#cc4210"],["82%","#e87828"],["100%","#f8a848"]],
  day:     [["0%","#091830"],["20%","#1255a8"],["50%","#2888d8"],["78%","#58aae0"],["100%","#90ccf4"]],
  sunset:  [["0%","#060418"],["18%","#2a0840"],["40%","#801030"],["62%","#c83c20"],["80%","#e46830"],["100%","#f49050"]],
};
const SKY_DARK: Record<string, string> = {
  night: "#010208", sunrise: "#07081e", day: "#091830", sunset: "#060418",
};

// ── Ground palettes ────────────────────────────────────────────────────────
// ── Ground multi-stop gradient ─────────────────────────────────────────────
const GROUND_STOPS: Record<string, [string, string][]> = {
  night:   [["0%","#122a14"],["40%","#0c1e0e"],["100%","#060c06"]],
  sunrise: [["0%","#2a5018"],["40%","#162e0c"],["100%","#0a1608"]],
  day:     [["0%","#58b830"],["25%","#3e8c20"],["60%","#246014"],["100%","#14400a"]],
  sunset:  [["0%","#1e4010"],["40%","#102208"],["100%","#080e04"]],
};
const GRASS_COL: Record<string, string> = {
  night: "#1a4018", sunrise: "#3a7020", day: "#6acf32", sunset: "#285018",
};
const GRASS_MID: Record<string, string> = {
  night: "#0e2410", sunrise: "#224010", day: "#4aa020", sunset: "#183010",
};
// keep these for the moon crescent cutout
const GROUND_TOP: Record<string, string> = {
  night: "#122a14", sunrise: "#2a5018", day: "#58b830", sunset: "#1e4010",
};
const GROUND_BOT: Record<string, string> = {
  night: "#060c06", sunrise: "#0a1608", day: "#14400a", sunset: "#080e04",
};

// ── Horizon haze colour per phase ──────────────────────────────────────────
const HAZE_COL: Record<string, string> = {
  night: "#0a1858", sunrise: "#ff9060", day: "#c8e8ff", sunset: "#ff7048",
};
const HAZE_OPC: Record<string, number> = {
  night: 0.30, sunrise: 0.60, day: 0.28, sunset: 0.65,
};

// ── Mountain colours per phase ─────────────────────────────────────────────
const MTN_FAR: Record<string, string>  = { night: "#10102a", sunrise: "#1e1438", day: "#6888a4", sunset: "#1c1038" };
const MTN_MID: Record<string, string>  = { night: "#0b130b", sunrise: "#111e11", day: "#3e6430", sunset: "#0e160e" };
const MTN_NEAR: Record<string, string> = { night: "#080d08", sunrise: "#0c160c", day: "#2e5420", sunset: "#0a120a" };
const PINE_COL: Record<string, string> = { night: "#030703", sunrise: "#070d07", day: "#1e4210", sunset: "#050905" };

// ── Mountain peak tables ───────────────────────────────────────────────────
// [x_fraction_of_W,  y_fraction_of_maxH]
const FAR_PEAKS: [number, number][] = [
  [0, 0.15], [0.08, 0.30], [0.18, 0.72], [0.28, 0.38], [0.38, 0.85],
  [0.50, 0.50], [0.60, 0.78], [0.70, 0.28], [0.82, 0.62], [0.92, 0.20], [1.0, 0.35],
];
const MID_PEAKS: [number, number][] = [
  [0, 0.08], [0.10, 0.38], [0.22, 0.16], [0.35, 0.52], [0.48, 0.22],
  [0.60, 0.46], [0.72, 0.14], [0.84, 0.40], [0.95, 0.10], [1.0, 0.26],
];
const NEAR_PEAKS: [number, number][] = [
  [0, 0.05], [0.12, 0.32], [0.26, 0.12], [0.42, 0.44], [0.57, 0.18],
  [0.70, 0.36], [0.84, 0.08], [1.0, 0.22],
];

// Pine tree x-positions on near mountain
const PINE_XS = [0.04, 0.09, 0.16, 0.25, 0.32, 0.38, 0.44, 0.53, 0.60, 0.65, 0.72, 0.79, 0.87, 0.93, 0.98];

function buildMtnPath(peaks: [number, number][], W: number, GNDLINE: number, maxH: number): string {
  // Convert to pixel coords
  const pts = peaks.map(([fx, fy]) => [fx * W, GNDLINE - fy * maxH] as [number, number]);
  if (pts.length < 2) return "";
  // Smooth curve using cardinal spline (tension 0.4) — rounds the peaks nicely
  const tension = 0.4;
  let d = `M ${pts[0][0].toFixed(1)},${GNDLINE}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[Math.min(pts.length - 1, i + 2)];
    const cp1x = p1[0] + (p2[0] - p0[0]) * tension;
    const cp1y = p1[1] + (p2[1] - p0[1]) * tension;
    const cp2x = p2[0] - (p3[0] - p1[0]) * tension;
    const cp2y = p2[1] - (p3[1] - p1[1]) * tension;
    d += ` C ${cp1x.toFixed(1)},${cp1y.toFixed(1)} ${cp2x.toFixed(1)},${cp2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  d += ` L ${W},${GNDLINE} Z`;
  return d;
}

function getMtnY(peaks: [number, number][], fx: number, GNDLINE: number, maxH: number): number {
  let i = 0;
  while (i < peaks.length - 1 && peaks[i + 1][0] < fx) i++;
  const [x1, y1] = peaks[i] ?? [0, 0];
  const [x2, y2] = peaks[Math.min(i + 1, peaks.length - 1)] ?? [1, 0];
  const t = (x2 - x1 < 0.0001) ? 0 : Math.max(0, Math.min(1, (fx - x1) / (x2 - x1)));
  return GNDLINE - (y1 + t * (y2 - y1)) * maxH;
}

export default function LightTimeline({ schedule, readings = [], gardenConfig }: LightTimelineProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [size, setSize] = useState({ w: 600, h: 400 });
  const [progress, setProgress] = useState(getDayProgress());
  const [brightness, setBrightness] = useState(0);
  const [phase, setPhase] = useState<string>("night");
  const [dragging, setDragging] = useState<"sunrise" | "sunset" | null>(null);
  const [dragHour, setDragHour] = useState<number | null>(null);

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
      const p = getDayProgress();
      setProgress(p);
      if (videoRef.current) videoRef.current.currentTime = p * 8.0;
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
  const PAD = W * 0.03;
  const arcW = W - PAD * 2;
  const GNDLINE = H * 0.72;
  const ARC_H  = H * 0.55;

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
    const sunset  = dragging === "sunset"  ? dragHour : schedule.sunset_hour;
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
    <div ref={containerRef} className="rounded-2xl w-full h-full flex items-center justify-center" style={{ background: "#0a0b1e" }}>
      <span style={{ color: "#555", fontSize: 14 }}>No light schedule</span>
    </div>
  );

  const displaySunrise = dragging === "sunrise" && dragHour !== null ? dragHour : schedule.sunrise_hour;
  const displaySunset  = dragging === "sunset"  && dragHour !== null ? dragHour : schedule.sunset_hour;

  const sunriseFrac    = displaySunrise / 24;
  const sunriseEndFrac = (displaySunrise + schedule.sunrise_ramp_min / 60) / 24;
  const sunsetEndFrac  = (displaySunset  + schedule.sunset_ramp_min / 60) / 24;

  const isDaytime = progress >= sunriseFrac && progress <= sunsetEndFrac;
  const dayRange  = sunsetEndFrac - sunriseFrac || 1;
  const dayProg   = isDaytime ? (progress - sunriseFrac) / dayRange : 0;

  const arcStartX = PAD + (displaySunrise / 24) * arcW;
  const arcEndX   = PAD + (displaySunset  / 24) * arcW;
  const arcSpanX  = arcEndX - arcStartX;
  const arcMidX   = (arcStartX + arcEndX) / 2;

  const sunX = arcStartX + dayProg * arcSpanX;
  const sunY = GNDLINE - (brightness / 100) * ARC_H;

  const nightDuration = (1 - sunsetEndFrac) + sunriseFrac;
  const nightProg = !isDaytime
    ? (progress > sunsetEndFrac
        ? (progress - sunsetEndFrac) / nightDuration
        : (progress + 1 - sunsetEndFrac) / nightDuration)
    : 0;
  // Moon travels the mirror arc: from arcEndX (sunset) back to arcStartX (sunrise)
  const moonX = arcEndX + (arcStartX - arcEndX) * nightProg;
  const moonY = GNDLINE - 4 * ARC_H * nightProg * (1 - nightProg);

  const isNight = phase === "night";
  const isDay   = phase === "day";

  // Mountain geometry
  const FAR_MAX  = GNDLINE * 0.46;
  const MID_MAX  = GNDLINE * 0.32;
  const NEAR_MAX = GNDLINE * 0.22;
  const farPath  = buildMtnPath(FAR_PEAKS,  W, GNDLINE, FAR_MAX);
  const midPath  = buildMtnPath(MID_PEAKS,  W, GNDLINE, MID_MAX);
  const nearPath = buildMtnPath(NEAR_PEAKS, W, GNDLINE, NEAR_MAX);

  const srX = xToSvg(displaySunrise);
  const ssX = xToSvg(displaySunset);

  const handleR  = Math.max(16, W * 0.028);
  const fontSize = Math.max(10, W * 0.018);
  const labelFS  = Math.max(9,  W * 0.015);
  const groundBump = H * 0.055;

  // Growth stage from agent
  const growthStage = gardenConfig?.growth_assessment?.stage ?? "germination";
  const growthFrac  = gardenConfig?.growth_assessment
    ? Math.max(0.06, gardenConfig.growth_assessment.height_pct / 100)
    : 0.06;

  // Garden plant colours
  const leafCol  = isDay ? "#40a832" : isNight ? "#193e0c" : "#2d8020";
  const leafDark = isDay ? "#2d7820" : "#0f2206";
  const stemCol  = isDay ? "#28601a" : "#102808";
  const budCol   = isDay ? "#7a3e8a" : "#3e1a48";

  // Pot geometry
  const potW  = Math.max(34, W * 0.095);
  const potH  = Math.max(26, H * 0.07);
  const potY  = GNDLINE - groundBump * 0.25;
  const potBase = potY + potH * 0.05; // bottom of pot (soil surface at potY)
  const plantMaxH = H * 0.26;
  const plantH    = plantMaxH * growthFrac;

  // 2 pot positions
  const POT_XS = [W * 0.38, W * 0.62];

  // Water % per pot (derived from calibrated weight range)
  const latestReading = readings && readings.length > 0 ? readings[readings.length - 1] : null;
  const potWaterPcts: (number | null)[] = POT_XS.map((_, i) => {
    const pot = gardenConfig?.pots?.[i];
    if (!pot || pot.dry_weight_g == null || pot.wet_weight_g == null || pot.wet_weight_g <= pot.dry_weight_g) return null;
    const weightG = i === 0 ? latestReading?.weight_g : latestReading?.weight2_g;
    if (weightG == null) return null;
    return Math.min(100, Math.max(0, ((weightG - pot.dry_weight_g) / (pot.wet_weight_g - pot.dry_weight_g)) * 100));
  });

  // Stars
  const starList = [
    [0.08, 0.08], [0.18, 0.22], [0.28, 0.06], [0.42, 0.14], [0.55, 0.05],
    [0.63, 0.20], [0.73, 0.09], [0.83, 0.17], [0.92, 0.07], [0.15, 0.35],
    [0.48, 0.30], [0.70, 0.32], [0.35, 0.25],
  ].map(([fx, fy]) => ({ x: fx * W, y: fy * GNDLINE }));

  const renderPine = (cx: number, baseY: number, h: number, col: string, key: number) => {
    const w = h * 0.52;
    return (
      <g key={key}>
        <rect x={cx - w * 0.09} y={baseY - h * 0.10} width={w * 0.18} height={h * 0.12} fill="#2a1408" />
        <polygon points={`${cx},${baseY - h} ${cx - w * 0.48},${baseY - h * 0.60} ${cx + w * 0.48},${baseY - h * 0.60}`} fill={col} />
        <polygon points={`${cx},${baseY - h * 0.66} ${cx - w * 0.74},${baseY - h * 0.30} ${cx + w * 0.74},${baseY - h * 0.30}`} fill={col} />
        <polygon points={`${cx},${baseY - h * 0.36} ${cx - w},${baseY - h * 0.08} ${cx + w},${baseY - h * 0.08}`} fill={col} />
      </g>
    );
  };

  const renderPot = (cx: number, potIdx: number, waterPct: number | null) => {
    const rim = potW * 0.55;
    const bot = potW * 0.42;
    const clipId = `lt-pot-clip-${potIdx}`;
    const wgId   = `lt-water-grad-${potIdx}`;

    // Water fill inside pot (from bottom up)
    const fillH = waterPct != null ? (waterPct / 100) * potH * 0.88 : 0;
    const fillY = potY + potH * 0.88 - fillH;

    const waterCol = waterPct == null ? "#4a3728"
      : waterPct <= 10 ? "#c0392b"
      : waterPct <= 30 ? "#e67e22"
      : waterPct <= 70 ? "#27ae60"
      : "#2980b9";
    const waterLight = waterPct == null ? "#5a4738"
      : waterPct <= 10 ? "#e74c3c"
      : waterPct <= 30 ? "#f39c12"
      : waterPct <= 70 ? "#2ecc71"
      : "#3498db";

    return (
      <g>
        <defs>
          <clipPath id={clipId}>
            <path d={`M ${cx - rim},${potY} L ${cx - bot},${potY + potH} L ${cx + bot},${potY + potH} L ${cx + rim},${potY} Z`} />
          </clipPath>
          <linearGradient id={wgId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={waterLight} />
            <stop offset="100%" stopColor={waterCol} />
          </linearGradient>
        </defs>

        {/* Pot body */}
        <path d={`M ${cx - rim},${potY} L ${cx - bot},${potY + potH} L ${cx + bot},${potY + potH} L ${cx + rim},${potY} Z`}
          fill="#9e5c28" stroke="#7a4018" strokeWidth={1.5} />

        {/* Soil fill inside pot */}
        <rect x={cx - rim} y={potY} width={rim * 2} height={potH}
          fill="#4a3020" clipPath={`url(#${clipId})`} />

        {/* Water fill */}
        {fillH > 0 && (
          <g clipPath={`url(#${clipId})`}>
            <rect x={cx - rim} y={fillY} width={rim * 2} height={fillH + 2}
              fill={`url(#${wgId})`} opacity={0.82} />
            {/* Wave */}
            <path d={`M${cx - rim},${fillY} Q${cx - rim * 0.5},${fillY - potH * 0.05} ${cx},${fillY} Q${cx + rim * 0.5},${fillY + potH * 0.05} ${cx + rim},${fillY} L${cx + rim},${fillY + potH * 0.07} Q${cx + rim * 0.5},${fillY + potH * 0.12} ${cx},${fillY + potH * 0.07} Q${cx - rim * 0.5},${fillY + potH * 0.02} ${cx - rim},${fillY + potH * 0.07} Z`}
              fill={waterLight} opacity={0.45}>
              <animateTransform attributeName="transform" type="translate"
                values={`0 0; ${rim * 0.2} 0; 0 0`} dur="3.5s" repeatCount="indefinite" />
            </path>
          </g>
        )}

        {/* Rim */}
        <rect x={cx - rim - 2} y={potY - potH * 0.12} width={(rim + 2) * 2} height={potH * 0.14} rx={3}
          fill="#b86c30" stroke="#8a4e1e" strokeWidth={1} />
        {/* Soil top surface */}
        <ellipse cx={cx} cy={potY - potH * 0.05} rx={rim - 1} ry={potH * 0.08}
          fill="#3d2410" stroke="#2a1808" strokeWidth={1} />
      </g>
    );
  };

  const renderPlant = (cx: number, idx: number) => {
    const baseY = potY - potH * 0.05; // soil surface

    switch (growthStage) {
      case "empty":
        return null;

      case "germination": {
        const sh = Math.max(8, plantH * 0.7);
        const domeW = potW * 0.55; // match pot rim width
        const domeH = domeW * 1.1; // keep proportional — shorter so it looks like a cloche not a cone
        return (
          <g key={idx}>
            {/* Tiny curved sprout */}
            <path d={`M ${cx},${baseY} C ${cx - 4},${baseY - sh * 0.4} ${cx + 3},${baseY - sh * 0.75} ${cx},${baseY - sh}`}
              fill="none" stroke={stemCol} strokeWidth={2} strokeLinecap="round" />
            {/* Seed leaves */}
            <ellipse cx={cx - 6} cy={baseY - sh * 0.55} rx={7} ry={3.5}
              fill={leafCol} transform={`rotate(-25,${cx - 6},${baseY - sh * 0.55})`} />
            <ellipse cx={cx + 6} cy={baseY - sh * 0.55} rx={7} ry={3.5}
              fill={leafCol} transform={`rotate(25,${cx + 6},${baseY - sh * 0.55})`} />
            {/* Plastic dome (bell cloche) — wide rounded shape */}
            <path d={`M ${cx - domeW},${baseY + 2} C ${cx - domeW * 1.15},${baseY - domeH * 0.3} ${cx - domeW * 0.6},${baseY - domeH} ${cx},${baseY - domeH} C ${cx + domeW * 0.6},${baseY - domeH} ${cx + domeW * 1.15},${baseY - domeH * 0.3} ${cx + domeW},${baseY + 2}`}
              fill="rgba(200,230,255,0.07)" stroke="rgba(220,240,255,0.30)" strokeWidth={1.5} />
            {/* Dome highlight */}
            <path d={`M ${cx - domeW * 0.65},${baseY - domeH * 0.15} C ${cx - domeW * 0.7},${baseY - domeH * 0.55} ${cx - domeW * 0.35},${baseY - domeH * 0.9} ${cx - domeW * 0.1},${baseY - domeH * 0.97}`}
              fill="none" stroke="rgba(255,255,255,0.38)" strokeWidth={1} />
          </g>
        );
      }

      case "seedling": {
        const h = plantH;
        const lw = Math.max(8, h * 0.30);
        return (
          <g key={idx}>
            <line x1={cx} y1={baseY} x2={cx} y2={baseY - h} stroke={stemCol} strokeWidth={2.5} strokeLinecap="round" />
            {/* Cotyledons */}
            <ellipse cx={cx - lw * 0.8} cy={baseY - h * 0.22} rx={lw * 0.85} ry={lw * 0.30}
              fill={leafCol} transform={`rotate(-30,${cx - lw * 0.8},${baseY - h * 0.22})`} />
            <ellipse cx={cx + lw * 0.8} cy={baseY - h * 0.22} rx={lw * 0.85} ry={lw * 0.30}
              fill={leafCol} transform={`rotate(30,${cx + lw * 0.8},${baseY - h * 0.22})`} />
            {/* First true leaves */}
            <ellipse cx={cx - lw} cy={baseY - h * 0.52} rx={lw * 0.90} ry={lw * 0.28}
              fill={leafCol} transform={`rotate(-38,${cx - lw},${baseY - h * 0.52})`} />
            <ellipse cx={cx + lw} cy={baseY - h * 0.52} rx={lw * 0.90} ry={lw * 0.28}
              fill={leafCol} transform={`rotate(38,${cx + lw},${baseY - h * 0.52})`} />
            {/* Growing tip */}
            <ellipse cx={cx} cy={baseY - h} rx={lw * 0.5} ry={lw * 0.42} fill={leafCol} />
          </g>
        );
      }

      case "vegetative": {
        const h = plantH;
        const lw = Math.max(10, h * 0.34);
        return (
          <g key={idx}>
            <line x1={cx} y1={baseY} x2={cx} y2={baseY - h} stroke={stemCol} strokeWidth={3} strokeLinecap="round" />
            {[0.18, 0.36, 0.54, 0.72].map((frac, i) => {
              const ly = baseY - h * frac;
              const fw = lw * (1.0 - frac * 0.3);
              const ang = 35 + (i % 2) * 10;
              return (
                <g key={i}>
                  <ellipse cx={cx - fw * 0.9} cy={ly - fw * 0.22} rx={fw * 0.95} ry={fw * 0.26}
                    fill={leafCol} stroke={leafDark} strokeWidth={0.6}
                    transform={`rotate(${-ang},${cx - fw * 0.9},${ly - fw * 0.22})`} />
                  <ellipse cx={cx + fw * 0.9} cy={ly - fw * 0.22} rx={fw * 0.95} ry={fw * 0.26}
                    fill={leafCol} stroke={leafDark} strokeWidth={0.6}
                    transform={`rotate(${ang},${cx + fw * 0.9},${ly - fw * 0.22})`} />
                </g>
              );
            })}
            {/* Bushy top */}
            <ellipse cx={cx - lw * 0.35} cy={baseY - h - lw * 0.2} rx={lw * 0.55} ry={lw * 0.30} fill={leafCol} />
            <ellipse cx={cx + lw * 0.35} cy={baseY - h - lw * 0.2} rx={lw * 0.55} ry={lw * 0.30} fill={leafCol} />
            <ellipse cx={cx} cy={baseY - h - lw * 0.35} rx={lw * 0.45} ry={lw * 0.28} fill={leafCol} />
          </g>
        );
      }

      case "flowering": {
        const h = plantH;
        const lw = Math.max(10, h * 0.32);
        return (
          <g key={idx}>
            <line x1={cx} y1={baseY} x2={cx} y2={baseY - h} stroke={stemCol} strokeWidth={3} strokeLinecap="round" />
            {[0.16, 0.33, 0.50, 0.68].map((frac, i) => {
              const ly = baseY - h * frac;
              const fw = lw * (1.0 - frac * 0.25);
              const ang = 38 + (i % 2) * 8;
              return (
                <g key={i}>
                  <ellipse cx={cx - fw * 0.9} cy={ly - fw * 0.20} rx={fw * 0.92} ry={fw * 0.25}
                    fill={leafCol} stroke={leafDark} strokeWidth={0.6}
                    transform={`rotate(${-ang},${cx - fw * 0.9},${ly - fw * 0.20})`} />
                  <ellipse cx={cx + fw * 0.9} cy={ly - fw * 0.20} rx={fw * 0.92} ry={fw * 0.25}
                    fill={leafCol} stroke={leafDark} strokeWidth={0.6}
                    transform={`rotate(${ang},${cx + fw * 0.9},${ly - fw * 0.20})`} />
                  {/* Bud at each node */}
                  <ellipse cx={cx} cy={ly - fw * 0.05} rx={fw * 0.22} ry={fw * 0.28} fill={budCol} opacity={0.88} />
                </g>
              );
            })}
            {/* Top flower cluster */}
            <ellipse cx={cx} cy={baseY - h - lw * 0.15} rx={lw * 0.42} ry={lw * 0.52} fill={budCol} opacity={0.92} />
            <ellipse cx={cx - lw * 0.28} cy={baseY - h - lw * 0.40} rx={lw * 0.26} ry={lw * 0.35} fill={budCol} opacity={0.85} />
            <ellipse cx={cx + lw * 0.28} cy={baseY - h - lw * 0.35} rx={lw * 0.26} ry={lw * 0.32} fill={budCol} opacity={0.85} />
            {/* Orange pistil hairs */}
            {[-6, -2, 2, 6].map((dx, i) => (
              <line key={i} x1={cx + dx} y1={baseY - h - lw * 0.55}
                x2={cx + dx + (i % 2 === 0 ? -5 : 5)} y2={baseY - h - lw * 0.72}
                stroke="#f08030" strokeWidth={1.5} strokeLinecap="round" />
            ))}
          </g>
        );
      }

      case "harvest": {
        const h = plantH;
        const lw = Math.max(10, h * 0.30);
        return (
          <g key={idx}>
            <line x1={cx} y1={baseY} x2={cx} y2={baseY - h} stroke={stemCol} strokeWidth={4} strokeLinecap="round" />
            {[0.13, 0.26, 0.40, 0.54, 0.68, 0.82].map((frac, i) => {
              const ly = baseY - h * frac;
              const fw = lw * (1.0 - frac * 0.20);
              const ang = 36 + (i % 2) * 9;
              const amber = frac > 0.55;
              return (
                <g key={i}>
                  <ellipse cx={cx - fw * 0.88} cy={ly - fw * 0.18} rx={fw * 0.94} ry={fw * 0.25}
                    fill={amber ? "#c8a030" : leafCol} stroke={leafDark} strokeWidth={0.6}
                    transform={`rotate(${-ang},${cx - fw * 0.88},${ly - fw * 0.18})`} />
                  <ellipse cx={cx + fw * 0.88} cy={ly - fw * 0.18} rx={fw * 0.94} ry={fw * 0.25}
                    fill={amber ? "#c8a030" : leafCol} stroke={leafDark} strokeWidth={0.6}
                    transform={`rotate(${ang},${cx + fw * 0.88},${ly - fw * 0.18})`} />
                  {/* Dense node buds */}
                  <ellipse cx={cx} cy={ly - fw * 0.05} rx={fw * 0.28} ry={fw * 0.35} fill={budCol} opacity={0.90} />
                </g>
              );
            })}
            {/* Massive top cola */}
            <ellipse cx={cx} cy={baseY - h - lw * 0.22} rx={lw * 0.55} ry={lw * 0.68} fill={budCol} opacity={0.95} />
            <ellipse cx={cx - lw * 0.32} cy={baseY - h - lw * 0.52} rx={lw * 0.30} ry={lw * 0.44} fill={budCol} opacity={0.88} />
            <ellipse cx={cx + lw * 0.32} cy={baseY - h - lw * 0.48} rx={lw * 0.30} ry={lw * 0.40} fill={budCol} opacity={0.88} />
            {/* Amber pistils */}
            {[-7, -3, 0, 3, 7].map((dx, i) => (
              <line key={i} x1={cx + dx} y1={baseY - h - lw * 0.78}
                x2={cx + dx + (i % 2 === 0 ? -6 : 6)} y2={baseY - h - lw * 1.0}
                stroke="#f07820" strokeWidth={1.5} strokeLinecap="round" />
            ))}
          </g>
        );
      }

      default:
        return null;
    }
  };

  return (
    <div ref={containerRef} className="rounded-2xl overflow-hidden w-full h-full" style={{ background: "#000", position: "relative" }}>
      {/* Video sky background — scrubbed to current time of day */}
      <video
        ref={videoRef}
        src="/sky_background.mp4"
        muted playsInline preload="auto"
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", pointerEvents: "none" }}
      />
      <svg
        ref={svgRef}
        width={W} height={H}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        style={{ display: "block", touchAction: "none", position: "relative" }}
      >
        <defs>
          <linearGradient id="ct-ground" x1="0" y1="0" x2="0" y2="1">
            {GROUND_STOPS[phase].map(([off, col]) => (
              <stop key={off} offset={off} stopColor={col} />
            ))}
          </linearGradient>
          <radialGradient id="ct-sunhalo" cx="50%" cy="50%" r="50%">
            <stop offset="0%"   stopColor="#FFE060" stopOpacity={0.65} />
            <stop offset="55%"  stopColor="#FFB800" stopOpacity={0.20} />
            <stop offset="100%" stopColor="#FF8C00" stopOpacity={0} />
          </radialGradient>
          <radialGradient id="ct-moonhalo" cx="50%" cy="50%" r="50%">
            <stop offset="0%"   stopColor="#e8eaf6" stopOpacity={0.45} />
            <stop offset="100%" stopColor="#9fa8da" stopOpacity={0} />
          </radialGradient>
          <filter id="ct-glow">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="ct-softshadow">
            <feDropShadow dx="0" dy="2" stdDeviation="3" floodOpacity="0.3" />
          </filter>
        </defs>

        {/* ── Celestial arcs (behind mountains) ── */}
        {(() => {
          const cpY = GNDLINE - 2 * ARC_H;
          const dayArcPath = `M ${arcStartX},${GNDLINE} Q ${arcMidX},${cpY} ${arcEndX},${GNDLINE}`;
          const nightArcPath = `M ${arcEndX},${GNDLINE} Q ${arcMidX},${cpY} ${arcStartX},${GNDLINE}`;
          const dayTrailProg = isDaytime ? dayProg : 1;
          const daySubCpX = arcStartX + (arcMidX - arcStartX) * dayTrailProg;
          const daySubCpY = GNDLINE - 2 * ARC_H * dayTrailProg;
          const dayTrailEnd = isDaytime ? `${sunX},${sunY}` : `${arcEndX},${GNDLINE}`;
          const dayTrailPath = `M ${arcStartX},${GNDLINE} Q ${daySubCpX},${daySubCpY} ${dayTrailEnd}`;
          const nightSubCpX = arcEndX + (arcMidX - arcEndX) * nightProg;
          const nightSubCpY = GNDLINE - 2 * ARC_H * nightProg;
          const nightTrailPath = nightProg > 0.01
            ? `M ${arcEndX},${GNDLINE} Q ${nightSubCpX},${nightSubCpY} ${moonX},${moonY}`
            : null;
          return (
            <>
              <path d={dayArcPath} fill="none" stroke="#FFD700" strokeWidth={1.5}
                strokeDasharray="6 10" opacity={isDaytime ? 0.22 : 0.12}>
                <animate attributeName="stroke-dashoffset" from="16" to="0" dur="1.2s" repeatCount="indefinite" />
              </path>
              <path d={dayTrailPath} fill="none" stroke="#FF8C00" strokeWidth={12}
                strokeLinecap="round" opacity={isDaytime ? 0.14 : 0.07} />
              <path d={dayTrailPath} fill="none" stroke="#FFD700" strokeWidth={2.5} strokeLinecap="round">
                <animate attributeName="opacity"
                  values={isDaytime ? "0.65;0.92;0.65" : "0.28;0.45;0.28"}
                  dur="2.5s" repeatCount="indefinite" />
              </path>
              {!isDaytime && (
                <path d={nightArcPath} fill="none" stroke="#9fa8da" strokeWidth={1.5}
                  strokeDasharray="6 10" opacity={0.20}>
                  <animate attributeName="stroke-dashoffset" from="0" to="16" dur="1.8s" repeatCount="indefinite" />
                </path>
              )}
              {nightTrailPath && (
                <>
                  <path d={nightTrailPath} fill="none" stroke="#7986cb" strokeWidth={10}
                    strokeLinecap="round" opacity={0.13} />
                  <path d={nightTrailPath} fill="none" stroke="#c5cae9" strokeWidth={2.5} strokeLinecap="round">
                    <animate attributeName="opacity" values="0.50;0.80;0.50" dur="3s" repeatCount="indefinite" />
                  </path>
                </>
              )}
            </>
          );
        })()}

        {/* ── Mid mountain range ── */}
        <path d={midPath} fill={MTN_MID[phase]} opacity={0.96} />

        {/* ── Near mountain range ── */}
        <path d={nearPath} fill={MTN_NEAR[phase]} />

        {/* ── Pine trees on near mountain slopes ── */}
        {PINE_XS.map((fx, i) => {
          const px  = fx * W;
          const baseY = getMtnY(NEAR_PEAKS, fx, GNDLINE, NEAR_MAX);
          const ph  = Math.max(12, NEAR_MAX * 0.30 * (0.7 + (i % 3) * 0.22));
          return renderPine(px, baseY, ph, PINE_COL[phase], i);
        })}

        {/* ── Brightness overlay ── */}
        {isDaytime && brightness < 98 && (
          <rect width={W} height={GNDLINE} fill="#0b0c2a"
            opacity={(1 - brightness / 100) * 0.82}
            style={{ pointerEvents: "none" }} />
        )}


        {/* ── Sun ── */}
        {isDaytime && (() => {
          const brightFrac = brightness / 100;
          const r    = Math.max(10, W * 0.038) * (0.5 + 0.5 * brightFrac);
          const glowR  = r * 2.8;
          const rayLen = r * 0.7;
          const rayGap = r * 1.25;
          const sunColor = brightness > 50 ? "#FFD700" : `hsl(48,${40 + 55 * brightFrac}%,${50 + 20 * brightFrac}%)`;
          return (
            <g filter="url(#ct-glow)" opacity={0.4 + 0.6 * brightFrac}>
              <circle cx={sunX} cy={sunY} r={glowR} fill="url(#ct-sunhalo)">
                <animate attributeName="r" values={`${glowR};${glowR * 1.15};${glowR}`} dur="3s" repeatCount="indefinite" />
              </circle>
              {[0, 45, 90, 135, 180, 225, 270, 315].map(angle => {
                const rad = (angle * Math.PI) / 180;
                return <line key={angle}
                  x1={sunX + Math.cos(rad) * rayGap} y1={sunY + Math.sin(rad) * rayGap}
                  x2={sunX + Math.cos(rad) * (rayGap + rayLen)} y2={sunY + Math.sin(rad) * (rayGap + rayLen)}
                  stroke={sunColor} strokeWidth={3.5} strokeLinecap="round" opacity={brightFrac * 0.9}>
                  <animateTransform attributeName="transform" type="rotate"
                    from={`0 ${sunX} ${sunY}`} to={`360 ${sunX} ${sunY}`}
                    dur="20s" repeatCount="indefinite" />
                </line>;
              })}
              <circle cx={sunX} cy={sunY} r={r} fill={sunColor} stroke="#FF8C00" strokeWidth={3} />
              {brightness > 30 && <>
                <circle cx={sunX - r * 0.28} cy={sunY - r * 0.10} r={r * 0.12} fill="#FF8C00" />
                <circle cx={sunX + r * 0.28} cy={sunY - r * 0.10} r={r * 0.12} fill="#FF8C00" />
                <path d={`M ${sunX - r * 0.30},${sunY + r * 0.20} Q ${sunX},${sunY + r * 0.45} ${sunX + r * 0.30},${sunY + r * 0.20}`}
                  fill="none" stroke="#FF8C00" strokeWidth={2.5} strokeLinecap="round" />
              </>}
            </g>
          );
        })()}

        {/* ── Moon ── */}
        {!isDaytime && (() => {
          const mr = Math.max(14, W * 0.026);
          return (
            <g>
              <circle cx={moonX} cy={moonY} r={mr * 2.8} fill="url(#ct-moonhalo)" />
              <circle cx={moonX} cy={moonY} r={mr} fill="#f5f0e8" stroke="#c8c0b0" strokeWidth={2.5} />
              <circle cx={moonX + mr * 0.38} cy={moonY - mr * 0.22} r={mr * 0.82} fill={SKY_DARK[phase]} />
              <circle cx={moonX - mr * 0.30} cy={moonY + mr * 0.20} r={mr * 0.14} fill="#ddd8cc" opacity={0.70} />
              <circle cx={moonX - mr * 0.50} cy={moonY - mr * 0.10} r={mr * 0.09} fill="#ddd8cc" opacity={0.60} />
            </g>
          );
        })()}

        {(() => {
          const edge = `M 0,${GNDLINE}
            C ${W*0.15},${GNDLINE-groundBump*0.9} ${W*0.28},${GNDLINE-groundBump*0.4} ${W*0.42},${GNDLINE-groundBump*0.7}
            C ${W*0.56},${GNDLINE-groundBump*1.0} ${W*0.68},${GNDLINE-groundBump*0.3} ${W*0.82},${GNDLINE-groundBump*0.6}
            C ${W*0.92},${GNDLINE-groundBump*0.8} ${W*0.97},${GNDLINE-groundBump*0.2} ${W},${GNDLINE-groundBump*0.3}`;

          return (
            <>
              {/* Main ground fill with gradient */}
              <path d={`${edge} L ${W},${H} L 0,${H} Z`} fill="url(#ct-ground)" />
            </>
          );
        })()}

        {/* ── Garden pots & plants ── */}
        {POT_XS.map((cx, i) => (
          <g key={i}>
            {renderPlant(cx, i)}
            {renderPot(cx, i, potWaterPcts[i])}
          </g>
        ))}


        {/* Drag handles on arc in sky */}
        {(() => {
          const cpY = GNDLINE - 2 * ARC_H;
          const qBez = (t: number): [number, number] => {
            const mt = 1 - t;
            return [
              mt*mt*arcStartX + 2*mt*t*arcMidX + t*t*arcEndX,
              mt*mt*GNDLINE   + 2*mt*t*cpY      + t*t*GNDLINE,
            ];
          };
          const T = 0.13;
          const [srMx, srMy] = qBez(T);
          const [ssMx, ssMy] = qBez(1 - T);
          return (
            <>
              {([
                { mx: srMx, my: srMy, hx: srX, label: fmt(displaySunrise), type: "sunrise" as const, col: "#ff9f43", anchor: "end" as const },
                { mx: ssMx, my: ssMy, hx: ssX, label: fmt(displaySunset),  type: "sunset"  as const, col: "#f7971e", anchor: "start" as const },
              ] as const).map(({ mx, my, hx, label, type, col, anchor }) => {
                const active = dragging === type;
                const cr = 5;
                return (
                  <g key={type} onPointerDown={handlePointerDown(type)} style={{ cursor: "ew-resize" }}>
                    <rect x={mx - 26} y={my - 26} width={52} height={52} fill="transparent" />
                    <rect x={hx - 16} y={GNDLINE - 6} width={32} height={20} fill="transparent" />
                    <circle cx={mx} cy={my} r={active ? cr + 2 : cr}
                      fill={active ? col : "rgba(0,0,0,0.60)"}
                      stroke={col} strokeWidth={1.5}
                      filter={active ? "url(#ct-glow)" : undefined} />
                    <text x={anchor === "end" ? mx - 9 : mx + 9} y={my - 8}
                      textAnchor={anchor} fontSize={labelFS} fontWeight="600"
                      fill={active ? col : "rgba(255,255,255,0.75)"} fontFamily="monospace">
                      {label}
                    </text>
                  </g>
                );
              })}
            </>
          );
        })()}

        {/* ── Drag tooltip (floats above while dragging) ── */}
        {dragging && dragHour !== null && (() => {
          const tx = Math.max(40, Math.min(W - 40, xToSvg(dragHour)));
          const col = dragging === "sunrise" ? "#ff9f43" : "#f7971e";
          return (
            <g>
              <rect x={tx - 28} y={GNDLINE - 30} width={56} height={22} rx={6}
                fill={col} opacity={0.95} filter="url(#ct-softshadow)" />
              <text x={tx} y={GNDLINE - 15} textAnchor="middle" fontSize={fontSize} fontWeight="700"
                fill="white" fontFamily="monospace">{fmt(dragHour)}</text>
            </g>
          );
        })()}

        {/* ── 12 PM label ── */}
        <text x={W / 2} y={H - 6} textAnchor="middle" fontSize={labelFS}
          fill="rgba(255,255,255,0.25)" fontFamily="sans-serif">12 PM</text>


      </svg>
    </div>
  );
}
