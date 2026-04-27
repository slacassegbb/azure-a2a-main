export const COLORS = {
  moisture: "hsl(185, 90%, 55%)",
  temperature: "hsl(35, 95%, 60%)",
  humidity: "hsl(270, 70%, 65%)",
  light: "hsl(48, 95%, 65%)",
  active: "hsl(152, 75%, 50%)",
  warning: "hsl(25, 95%, 55%)",
  error: "hsl(0, 85%, 60%)",
  muted: "hsl(220, 10%, 50%)",
  cardBg: "hsl(220, 18%, 11%)",
  cardBorder: "hsl(220, 15%, 16%)",
  pageBg: "hsl(220, 20%, 7%)",
} as const;

export const VALVE_NAMES: Record<string, { label: string; color: string; icon: string }> = {
  a: { label: "Plain Water", color: COLORS.moisture, icon: "💧" },
  b: { label: "Grow 2-1-6", color: COLORS.active, icon: "🌱" },
  c: { label: "Bloom 0-5-1", color: "hsl(330, 80%, 65%)", icon: "🌸" },
};

export const POLL_INTERVAL_MS = 30000;
export const DURATION_OPTIONS = [
  { label: "30s", value: 30 },
  { label: "1m", value: 60 },
  { label: "2m", value: 120 },
  { label: "5m", value: 300 },
];
export const FAN_SPEEDS = [0, 25, 50, 75, 100];
