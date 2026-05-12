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
const GROUND_TOP: Record<string, string> = {
  night: "#0e2410", sunrise: "#1e4012", day: "#4a9c28", sunset: "#183210",
};
const GROUND_BOT: Record<string, string> = {
  night: "#080e08", sunrise: "#0a1808", day: "#1e5014", sunset: "#0c1808",
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
  [0, 0.12], [0.04, 0.44], [0.09, 0.20], [0.14, 0.66], [0.20, 0.36],
  [0.25, 0.74], [0.31, 0.40], [0.36, 0.58], [0.42, 0.24], [0.47, 0.82],
  [0.53, 0.46], [0.58, 0.72], [0.63, 0.30], [0.69, 0.64], [0.74, 0.22],
  [0.80, 0.56], [0.85, 0.18], [0.91, 0.50], [0.96, 0.14], [1.0, 0.30],
];
const MID_PEAKS: [number, number][] = [
  [0, 0.10], [0.06, 0.32], [0.12, 0.14], [0.19, 0.44], [0.26, 0.22],
  [0.33, 0.40], [0.40, 0.12], [0.47, 0.50], [0.54, 0.26], [0.61, 0.42],
  [0.68, 0.16], [0.75, 0.38], [0.82, 0.10], [0.89, 0.32], [0.96, 0.08], [1.0, 0.24],
];
const NEAR_PEAKS: [number, number][] = [
  [0, 0.06], [0.07, 0.26], [0.14, 0.10], [0.21, 0.36], [0.29, 0.16],
  [0.37, 0.30], [0.45, 0.08], [0.52, 0.40], [0.60, 0.20], [0.68, 0.34],
  [0.76, 0.10], [0.84, 0.28], [0.92, 0.06], [1.0, 0.18],
];

// Pine tree x-positions on near mountain
const PINE_XS = [0.04, 0.09, 0.16, 0.25, 0.32, 0.38, 0.44, 0.53, 0.60, 0.65, 0.72, 0.79, 0.87, 0.93, 0.98];

function buildMtnPath(peaks: [number, number][], W: number, GNDLINE: number, maxH: number): string {
  const pts = peaks.map(([fx, fy]) => `${(fx * W).toFixed(1)},${(GNDLINE - fy * maxH).toFixed(1)}`);
  return `M 0,${GNDLINE} L ${pts.join(" L ")} L ${W},${GNDLINE} Z`;
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

  const renderPot = (cx: number) => {
    const rim = potW * 0.55;
    const bot = potW * 0.42;
    return (
      <g>
        {/* Pot body */}
        <path d={`M ${cx - rim},${potY} L ${cx - bot},${potY + potH} L ${cx + bot},${potY + potH} L ${cx + rim},${potY} Z`}
          fill="#9e5c28" stroke="#7a4018" strokeWidth={1.5} />
        {/* Rim */}
        <rect x={cx - rim - 2} y={potY - potH * 0.12} width={(rim + 2) * 2} height={potH * 0.14} rx={3}
          fill="#b86c30" stroke="#8a4e1e" strokeWidth={1} />
        {/* Soil */}
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
        const domeW = potW * 1.1;
        const domeH = plantMaxH * 0.75;
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
            {/* Plastic dome (bell cloche) */}
            <path d={`M ${cx - domeW},${baseY + 2} Q ${cx - domeW * 1.05},${baseY - domeH * 0.6} ${cx},${baseY - domeH} Q ${cx + domeW * 1.05},${baseY - domeH * 0.6} ${cx + domeW},${baseY + 2}`}
              fill="rgba(200,230,255,0.07)" stroke="rgba(220,240,255,0.30)" strokeWidth={1.5} />
            {/* Dome highlight */}
            <path d={`M ${cx - domeW * 0.7},${baseY - domeH * 0.2} Q ${cx - domeW * 0.65},${baseY - domeH * 0.7} ${cx - domeW * 0.2},${baseY - domeH * 0.92}`}
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
    <div ref={containerRef} className="rounded-2xl overflow-hidden w-full h-full" style={{ background: SKY_DARK[phase] }}>
      <svg
        ref={svgRef}
        width={W} height={H}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        style={{ display: "block", touchAction: "none" }}
      >
        <defs>
          {/* Multi-stop sky gradient */}
          <linearGradient id="ct-sky" x1="0" y1="0" x2="0" y2="1">
            {SKY_STOPS[phase].map(([off, col]) => (
              <stop key={off} offset={off} stopColor={col} />
            ))}
          </linearGradient>
          <linearGradient id="ct-ground" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stopColor={GROUND_TOP[phase]} />
            <stop offset="100%" stopColor={GROUND_BOT[phase]} />
          </linearGradient>
          {/* Horizon haze: transparent → haze colour at ground */}
          <linearGradient id="ct-haze" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stopColor={HAZE_COL[phase]} stopOpacity={0} />
            <stop offset="65%"  stopColor={HAZE_COL[phase]} stopOpacity={0} />
            <stop offset="100%" stopColor={HAZE_COL[phase]} stopOpacity={HAZE_OPC[phase]} />
          </linearGradient>
          {/* Milky Way radial smear */}
          <radialGradient id="ct-milky" cx="55%" cy="38%" r="55%">
            <stop offset="0%"   stopColor="#7080b8" stopOpacity={0.10} />
            <stop offset="60%"  stopColor="#4858a0" stopOpacity={0.04} />
            <stop offset="100%" stopColor="#4858a0" stopOpacity={0} />
          </radialGradient>
          <radialGradient id="ct-sunhalo" cx="50%" cy="50%" r="50%">
            <stop offset="0%"   stopColor="#FFE060" stopOpacity={0.65} />
            <stop offset="55%"  stopColor="#FFB800" stopOpacity={0.20} />
            <stop offset="100%" stopColor="#FF8C00" stopOpacity={0} />
          </radialGradient>
          <radialGradient id="ct-moonhalo" cx="50%" cy="50%" r="50%">
            <stop offset="0%"   stopColor="#e8eaf6" stopOpacity={0.45} />
            <stop offset="70%"  stopColor="#9fa8da" stopOpacity={0.08} />
            <stop offset="100%" stopColor="#9fa8da" stopOpacity={0} />
          </radialGradient>
          {/* Horizon burst for sunrise / sunset */}
          <radialGradient id="ct-hglow" cx="50%" cy="100%" r="70%" fx="50%" fy="100%">
            <stop offset="0%"   stopColor={phase === "sunrise" ? "#ff9040" : "#e85828"} stopOpacity={0.80} />
            <stop offset="50%"  stopColor={phase === "sunrise" ? "#ff6010" : "#c03010"} stopOpacity={0.30} />
            <stop offset="100%" stopColor="#000" stopOpacity={0} />
          </radialGradient>
          {/* Soft cloud blur */}
          <filter id="ct-cloudblur" x="-30%" y="-60%" width="160%" height="220%">
            <feGaussianBlur stdDeviation="6 5" />
          </filter>
          <filter id="ct-glow">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="ct-softshadow">
            <feDropShadow dx="0" dy="2" stdDeviation="3" floodOpacity="0.3" />
          </filter>
        </defs>

        {/* ── Sky ── */}
        <rect width={W} height={H} fill="url(#ct-sky)" />

        {/* ── Milky Way smear (night only) ── */}
        {isNight && (
          <ellipse cx={W * 0.55} cy={GNDLINE * 0.42} rx={W * 0.60} ry={GNDLINE * 0.38}
            fill="url(#ct-milky)" style={{ pointerEvents: "none" }} />
        )}

        {/* ── Stars (night / transition) ── */}
        {(isNight || phase === "sunrise") && starList.map((s, i) => {
          const dim = phase === "sunrise" ? 0.3 : 1;
          const r   = i % 5 === 0 ? 2.0 : i % 3 === 0 ? 1.4 : 1.0;
          return (
            <circle key={i} cx={s.x} cy={s.y} r={r}
              fill={i % 7 === 0 ? "#ffe8c8" : i % 5 === 0 ? "#c8d8ff" : "white"}
              opacity={(0.50 + (i % 4) * 0.12) * dim}>
              <animate attributeName="opacity"
                values={`${(0.28 + (i % 4) * 0.10) * dim};${(0.85 + (i % 3) * 0.08) * dim};${(0.28 + (i % 4) * 0.10) * dim}`}
                dur={`${2.0 + i * 0.22}s`} repeatCount="indefinite" />
            </circle>
          );
        })}

        {/* ── Crepuscular rays (sunrise / sunset) ── */}
        {(phase === "sunrise" || phase === "sunset") && (
          <g opacity={0.10} style={{ pointerEvents: "none" }}>
            {[0.22, 0.35, 0.50, 0.65, 0.78].map((fx, i) => {
              const x = fx * W;
              const spread = W * 0.035;
              const col = phase === "sunrise" ? "#ffa860" : "#ff8040";
              return (
                <path key={i}
                  d={`M ${W * 0.50},${GNDLINE * 1.1} L ${x - spread},0 L ${x + spread},0 Z`}
                  fill={col} opacity={0.6 - i * 0.08} />
              );
            })}
          </g>
        )}

        {/* ── Horizon atmospheric glow (sunrise / sunset) ── */}
        {(phase === "sunrise" || phase === "sunset") && (
          <ellipse cx={W / 2} cy={GNDLINE} rx={W * 0.78} ry={GNDLINE * 0.58}
            fill="url(#ct-hglow)" opacity={0.90} />
        )}

        {/* ── Horizon haze (always — colour varies by phase) ── */}
        <rect width={W} height={GNDLINE} fill="url(#ct-haze)" style={{ pointerEvents: "none" }} />

        {/* ── Far mountain range ── */}
        <path d={farPath} fill={MTN_FAR[phase]} opacity={0.92} />

        {/* Snow caps on tall far peaks (day only) */}
        {isDay && FAR_PEAKS.filter(([, fy]) => fy > 0.60).map(([fx, fy], i) => {
          const px = fx * W;
          const py = GNDLINE - fy * FAR_MAX;
          const sw = FAR_MAX * fy * 0.18;
          return (
            <polygon key={i}
              points={`${px},${py} ${px - sw},${py + sw * 1.1} ${px + sw},${py + sw * 1.1}`}
              fill="white" opacity={0.82} />
          );
        })}

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

        {/* ── Clouds (day / sunrise) ── */}
        {(isDay || phase === "sunrise") && [
          { x: W * 0.14, y: H * 0.09, s: 1.00, op: 0.92 },
          { x: W * 0.58, y: H * 0.06, s: 0.78, op: 0.85 },
          { x: W * 0.82, y: H * 0.15, s: 0.62, op: 0.80 },
        ].map((c, i) => {
          const sc = c.s * W * 0.055;
          const tint = phase === "sunrise" ? "#ffe0c0" : "white";
          const shadow = phase === "sunrise" ? "#d09060" : "#b8ccd8";
          return (
            <g key={i} opacity={c.op}>
              {/* Soft shadow beneath */}
              <g transform={`translate(${c.x + sc * 0.15},${c.y + sc * 0.45})`} filter="url(#ct-cloudblur)">
                <ellipse cx={0} cy={0} rx={sc * 2.0} ry={sc * 0.55} fill={shadow} opacity={0.35} />
              </g>
              {/* Cloud body — blurred blob cluster */}
              <g transform={`translate(${c.x},${c.y})`} filter="url(#ct-cloudblur)">
                <ellipse cx={0}         cy={0}         rx={sc * 2.0} ry={sc * 1.1} fill={tint} />
                <ellipse cx={sc * -1.2} cy={sc * 0.4}  rx={sc * 1.3} ry={sc * 0.9} fill={tint} />
                <ellipse cx={sc * 1.3}  cy={sc * 0.3}  rx={sc * 1.5} ry={sc * 1.0} fill={tint} />
                <ellipse cx={sc * -0.5} cy={sc * -0.5} rx={sc * 1.1} ry={sc * 0.9} fill={tint} />
                <ellipse cx={sc * 0.7}  cy={sc * -0.4} rx={sc * 1.2} ry={sc * 0.9} fill={tint} />
                <ellipse cx={0}         cy={sc * 0.7}  rx={sc * 2.2} ry={sc * 0.7} fill={tint} />
              </g>
            </g>
          );
        })}

        {/* ── Celestial arcs ── */}
        {(() => {
          // Both arcs share the same apex: arcMidX, GNDLINE - 2*ARC_H (so peak = GNDLINE - ARC_H)
          const cpY = GNDLINE - 2 * ARC_H;

          // Day arc: sunrise → sunset (golden)
          const dayArcPath = `M ${arcStartX},${GNDLINE} Q ${arcMidX},${cpY} ${arcEndX},${GNDLINE}`;

          // Night arc: sunset → sunrise (silver), mirror of day arc, shares endpoints
          const nightArcPath = `M ${arcEndX},${GNDLINE} Q ${arcMidX},${cpY} ${arcStartX},${GNDLINE}`;

          // Day trail: grows from arcStartX to sunX as day progresses; full arc at night
          const dayTrailProg = isDaytime ? dayProg : 1;
          const daySubCpX = arcStartX + (arcMidX - arcStartX) * dayTrailProg;
          const daySubCpY = GNDLINE - 2 * ARC_H * dayTrailProg;
          const dayTrailEnd = isDaytime ? `${sunX},${sunY}` : `${arcEndX},${GNDLINE}`;
          const dayTrailPath = `M ${arcStartX},${GNDLINE} Q ${daySubCpX},${daySubCpY} ${dayTrailEnd}`;

          // Night trail: grows from arcEndX to moonX as night progresses
          const nightSubCpX = arcEndX + (arcMidX - arcEndX) * nightProg;
          const nightSubCpY = GNDLINE - 2 * ARC_H * nightProg;
          const nightTrailPath = nightProg > 0.01
            ? `M ${arcEndX},${GNDLINE} Q ${nightSubCpX},${nightSubCpY} ${moonX},${moonY}`
            : null;

          return (
            <>
              {/* Full day arc — animated flowing dashes */}
              <path d={dayArcPath} fill="none" stroke="#FFD700" strokeWidth={1.5}
                strokeDasharray="6 10" opacity={isDaytime ? 0.22 : 0.12}>
                <animate attributeName="stroke-dashoffset" from="16" to="0" dur="1.2s" repeatCount="indefinite" />
              </path>

              {/* Day trail — glowing gold with pulse */}
              <path d={dayTrailPath} fill="none" stroke="#FF8C00" strokeWidth={12}
                strokeLinecap="round" opacity={isDaytime ? 0.14 : 0.07} />
              <path d={dayTrailPath} fill="none" stroke="#FFD700" strokeWidth={2.5}
                strokeLinecap="round">
                <animate attributeName="opacity"
                  values={isDaytime ? "0.65;0.92;0.65" : "0.28;0.45;0.28"}
                  dur="2.5s" repeatCount="indefinite" />
              </path>

              {/* Full night arc — animated flowing dashes silver */}
              {!isDaytime && (
                <path d={nightArcPath} fill="none" stroke="#9fa8da" strokeWidth={1.5}
                  strokeDasharray="6 10" opacity={0.20}>
                  <animate attributeName="stroke-dashoffset" from="0" to="16" dur="1.8s" repeatCount="indefinite" />
                </path>
              )}

              {/* Night trail — glowing silver with pulse */}
              {nightTrailPath && (
                <>
                  <path d={nightTrailPath} fill="none" stroke="#7986cb" strokeWidth={10}
                    strokeLinecap="round" opacity={0.13} />
                  <path d={nightTrailPath} fill="none" stroke="#c5cae9" strokeWidth={2.5}
                    strokeLinecap="round">
                    <animate attributeName="opacity" values="0.50;0.80;0.50" dur="3s" repeatCount="indefinite" />
                  </path>
                </>
              )}
            </>
          );
        })()}

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

        {/* ── Main ground ── */}
        <path
          d={`M 0,${GNDLINE}
              C ${W*0.15},${GNDLINE - groundBump * 0.9} ${W*0.28},${GNDLINE - groundBump * 0.4} ${W*0.42},${GNDLINE - groundBump * 0.7}
              C ${W*0.56},${GNDLINE - groundBump * 1.0} ${W*0.68},${GNDLINE - groundBump * 0.3} ${W*0.82},${GNDLINE - groundBump * 0.6}
              C ${W*0.92},${GNDLINE - groundBump * 0.8} ${W*0.97},${GNDLINE - groundBump * 0.2} ${W},${GNDLINE - groundBump * 0.3}
              L ${W},${H} L 0,${H} Z`}
          fill="url(#ct-ground)"
        />
        {/* Soft grass edge — slightly lighter strip along the top of the ground, no hard line */}
        <path
          d={`M 0,${GNDLINE}
              C ${W*0.15},${GNDLINE - groundBump * 0.9} ${W*0.28},${GNDLINE - groundBump * 0.4} ${W*0.42},${GNDLINE - groundBump * 0.7}
              C ${W*0.56},${GNDLINE - groundBump * 1.0} ${W*0.68},${GNDLINE - groundBump * 0.3} ${W*0.82},${GNDLINE - groundBump * 0.6}
              C ${W*0.92},${GNDLINE - groundBump * 0.8} ${W*0.97},${GNDLINE - groundBump * 0.2} ${W},${GNDLINE - groundBump * 0.3}`}
          fill="none"
          stroke={isDay ? "#5abf28" : isNight ? "#1e4a14" : "#3a8a18"}
          strokeWidth={groundBump * 0.55}
          strokeLinecap="round"
          opacity={0.55}
          style={{ pointerEvents: "none" }}
        />

        {/* ── Garden pots & plants ── */}
        {POT_XS.map((cx, i) => (
          <g key={i}>
            {renderPlant(cx, i)}
            {renderPot(cx)}
          </g>
        ))}


        {/* ══ SUNRISE DRAG HANDLE ══════════════════════════════════════════ */}
        <g onPointerDown={handlePointerDown("sunrise")} style={{ cursor: "ew-resize" }}>
          <rect x={srX - handleR * 1.5} y={GNDLINE - handleR * 3.5} width={handleR * 3} height={handleR * 5} fill="transparent" />
          <line x1={srX} y1={GNDLINE} x2={srX} y2={GNDLINE - handleR * 2.2}
            stroke={dragging === "sunrise" ? "#ff9f43" : "#666"} strokeWidth={3} strokeLinecap="round" />
          <circle cx={srX} cy={GNDLINE - handleR * 2.4} r={handleR}
            fill={dragging === "sunrise" ? "#ff9f43" : "#2d3748"}
            stroke={dragging === "sunrise" ? "#fff" : "#ff9f43"} strokeWidth={2.5}
            filter={dragging === "sunrise" ? "url(#ct-glow)" : undefined} />
          <path d={`M ${srX - handleR * 0.35},${GNDLINE - handleR * 2.55} L ${srX},${GNDLINE - handleR * 2.85} L ${srX + handleR * 0.35},${GNDLINE - handleR * 2.55}`}
            fill="none" stroke={dragging === "sunrise" ? "white" : "#ff9f43"} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
          <rect x={srX - handleR * 1.7} y={GNDLINE + handleR * 0.3} width={handleR * 3.4} height={handleR * 1.1} rx={handleR * 0.4}
            fill={dragging === "sunrise" ? "#ff9f43" : "#1a202c"} opacity={0.9} />
          <text x={srX} y={GNDLINE + handleR * 1.15} textAnchor="middle" fontSize={labelFS} fontWeight="700"
            fill={dragging === "sunrise" ? "white" : "#ff9f43"} fontFamily="monospace">
            {fmt(displaySunrise)}
          </text>
        </g>

        {/* ══ SUNSET DRAG HANDLE ═══════════════════════════════════════════ */}
        <g onPointerDown={handlePointerDown("sunset")} style={{ cursor: "ew-resize" }}>
          <rect x={ssX - handleR * 1.5} y={GNDLINE - handleR * 3.5} width={handleR * 3} height={handleR * 5} fill="transparent" />
          <line x1={ssX} y1={GNDLINE} x2={ssX} y2={GNDLINE - handleR * 2.2}
            stroke={dragging === "sunset" ? "#f7971e" : "#666"} strokeWidth={3} strokeLinecap="round" />
          <circle cx={ssX} cy={GNDLINE - handleR * 2.4} r={handleR}
            fill={dragging === "sunset" ? "#f7971e" : "#2d3748"}
            stroke={dragging === "sunset" ? "#fff" : "#f7971e"} strokeWidth={2.5}
            filter={dragging === "sunset" ? "url(#ct-glow)" : undefined} />
          <path d={`M ${ssX - handleR * 0.35},${GNDLINE - handleR * 2.25} L ${ssX},${GNDLINE - handleR * 1.95} L ${ssX + handleR * 0.35},${GNDLINE - handleR * 2.25}`}
            fill="none" stroke={dragging === "sunset" ? "white" : "#f7971e"} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
          <rect x={ssX - handleR * 1.7} y={GNDLINE + handleR * 0.3} width={handleR * 3.4} height={handleR * 1.1} rx={handleR * 0.4}
            fill={dragging === "sunset" ? "#f7971e" : "#1a202c"} opacity={0.9} />
          <text x={ssX} y={GNDLINE + handleR * 1.15} textAnchor="middle" fontSize={labelFS} fontWeight="700"
            fill={dragging === "sunset" ? "white" : "#f7971e"} fontFamily="monospace">
            {fmt(displaySunset)}
          </text>
        </g>

        {/* ── Drag tooltip ── */}
        {dragging && dragHour !== null && (() => {
          const tx = Math.max(50, Math.min(W - 50, xToSvg(dragHour)));
          const ty = GNDLINE - handleR * 4.5;
          return (
            <g>
              <rect x={tx - 34} y={ty - 14} width={68} height={26} rx={8}
                fill={dragging === "sunrise" ? "#ff9f43" : "#f7971e"} filter="url(#ct-softshadow)" />
              <text x={tx} y={ty + 4} textAnchor="middle" fontSize={fontSize} fontWeight="800"
                fill="white" fontFamily="monospace">{fmt(dragHour)}</text>
              <path d={`M ${tx - 7},${ty + 12} L ${tx},${ty + 20} L ${tx + 7},${ty + 12}`}
                fill={dragging === "sunrise" ? "#ff9f43" : "#f7971e"} />
            </g>
          );
        })()}

        {/* ── 12 PM label ── */}
        <text x={W / 2} y={GNDLINE + handleR * 1.15} textAnchor="middle" fontSize={labelFS}
          fill="#4a5568" fontFamily="sans-serif">12 PM</text>

        {/* ── Phase badge ── */}
        {(() => {
          const label = phase === "day" ? "☀ Daytime" : phase === "night" ? "🌙 Night" : phase === "sunrise" ? "🌅 Sunrise" : "🌇 Sunset";
          const bg = phase === "night" ? "#1a237e" : phase === "day" ? "#f9a825" : "#e65100";
          const fg = phase === "day" ? "#fff8e1" : "white";
          const bw = 80, bh = 22, bx = W / 2 - bw / 2, by = H - bh - H * 0.02;
          return (
            <g>
              <rect x={bx} y={by} width={bw} height={bh} rx={11} fill={bg} opacity={0.9} />
              <text x={W / 2} y={by + 14} textAnchor="middle" fontSize={11} fontWeight="700" fill={fg}>{label}</text>
            </g>
          );
        })()}

      </svg>
    </div>
  );
}
