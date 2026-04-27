"use client";

import { useState } from "react";
import { Droplets, Flower2, FlaskConical, Fan, Lightbulb, Loader2, Check } from "lucide-react";
import { GardenDashboardData } from "@/lib/garden/types";
import { DURATION_OPTIONS, FAN_SPEEDS } from "@/lib/garden/constants";

interface QuickControlsProps {
  data: GardenDashboardData | null;
  onRefresh: () => void;
}

async function sendControl(action: string, params: Record<string, any>) {
  const res = await fetch("/api/garden/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, ...params }),
  });
  return res.json();
}

function ActionButton({ icon: Icon, label, color, onClick, loading, success }: {
  icon: any; label: string; color: string; onClick: () => void; loading?: boolean; success?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className="flex items-center gap-2 px-4 py-2.5 rounded-lg font-medium text-sm transition-all active:scale-95 disabled:opacity-50"
      style={{
        background: success ? "hsl(152, 75%, 50%, 0.2)" : `${color}15`,
        border: `1px solid ${success ? "hsl(152, 75%, 50%)" : color}30`,
        color: success ? "hsl(152, 75%, 50%)" : color,
      }}
    >
      {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : success ? <Check className="w-4 h-4" /> : <Icon className="w-4 h-4" />}
      {label}
    </button>
  );
}

export default function QuickControls({ data, onRefresh }: QuickControlsProps) {
  const [duration, setDuration] = useState(120);
  const [lightBrightness, setLightBrightness] = useState(100);
  const [loading, setLoading] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [activeFanSpeed, setActiveFanSpeed] = useState<number | null>(data?.fan?.state ? (data.fan.speed || 100) : 0);

  const doAction = async (key: string, action: string, params: Record<string, any>) => {
    setLoading(key);
    setSuccess(null);
    try {
      await sendControl(action, params);
      setSuccess(key);
      setTimeout(() => setSuccess(null), 2000);
      setTimeout(onRefresh, 3000);
    } catch { /* ignore */ }
    finally { setLoading(null); }
  };

  return (
    <div className="rounded-xl p-5" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
      <span className="text-[11px] uppercase tracking-wider font-medium" style={{ color: "hsl(220, 10%, 50%)" }}>
        🎛 Quick Controls
      </span>

      <div className="mt-4 space-y-5">
        {/* Irrigation */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-medium" style={{ color: "hsl(220, 10%, 65%)" }}>Irrigation</span>
            <select
              value={duration}
              onChange={(e) => setDuration(Number(e.target.value))}
              className="ml-auto text-xs rounded-md px-2 py-1 border-0 outline-none"
              style={{ background: "hsl(220, 15%, 16%)", color: "hsl(220, 10%, 70%)" }}
            >
              {DURATION_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          <div className="flex gap-2 flex-wrap">
            <ActionButton
              icon={Droplets}
              label="Water"
              color="hsl(185, 90%, 55%)"
              onClick={() => doAction("valve-a", "irrigate_valve", { valve: "a", duration_seconds: duration })}
              loading={loading === "valve-a"}
              success={success === "valve-a"}
            />
            <ActionButton
              icon={FlaskConical}
              label="Grow"
              color="hsl(152, 75%, 50%)"
              onClick={() => doAction("valve-b", "irrigate_valve", { valve: "b", duration_seconds: duration })}
              loading={loading === "valve-b"}
              success={success === "valve-b"}
            />
            <ActionButton
              icon={Flower2}
              label="Bloom"
              color="hsl(330, 80%, 65%)"
              onClick={() => doAction("valve-c", "irrigate_valve", { valve: "c", duration_seconds: duration })}
              loading={loading === "valve-c"}
              success={success === "valve-c"}
            />
          </div>
        </div>

        {/* Fan Speed */}
        <div>
          <span className="text-xs font-medium" style={{ color: "hsl(220, 10%, 65%)" }}>Fan Speed</span>
          <div className="flex gap-1.5 mt-2">
            {FAN_SPEEDS.map(speed => {
              const isActive = activeFanSpeed === speed;
              const isCurrentLoading = loading === `fan-${speed}`;
              return (
                <button
                  key={speed}
                  onClick={() => {
                    setActiveFanSpeed(speed);
                    doAction(`fan-${speed}`, "set_fan", { state: speed > 0, speed });
                  }}
                  disabled={isCurrentLoading}
                  className="flex-1 py-2 rounded-lg text-xs font-medium transition-all active:scale-95"
                  style={{
                    background: isActive ? "hsl(185, 70%, 55%, 0.2)" : "hsl(220, 15%, 13%)",
                    border: `1px solid ${isActive ? "hsl(185, 70%, 55%)" : "hsl(220, 15%, 18%)"}`,
                    color: isActive ? "hsl(185, 70%, 55%)" : "hsl(220, 10%, 45%)",
                  }}
                >
                  {isCurrentLoading ? <Loader2 className="w-3 h-3 animate-spin mx-auto" /> :
                    speed === 0 ? "OFF" : `${speed}%`}
                </button>
              );
            })}
          </div>
        </div>

        {/* Light Control */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium" style={{ color: "hsl(220, 10%, 65%)" }}>Light</span>
            <div className="flex items-center gap-3">
              <span className="text-sm font-semibold" style={{ color: "hsl(48, 95%, 65%)" }}>{lightBrightness}%</span>
              <button
                onClick={() => {
                  const newState = lightBrightness === 0;
                  setLightBrightness(newState ? 100 : 0);
                  doAction("light-power", "set_light_power", { state: newState });
                }}
                disabled={loading === "light-power"}
                className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all active:scale-95"
                style={{
                  background: lightBrightness > 0 ? "hsl(48, 95%, 65%, 0.15)" : "hsl(220, 15%, 13%)",
                  border: `1px solid ${lightBrightness > 0 ? "hsl(48, 95%, 65%)" : "hsl(220, 15%, 18%)"}30`,
                  color: lightBrightness > 0 ? "hsl(48, 95%, 65%)" : "hsl(220, 10%, 45%)",
                }}
              >
                {loading === "light-power" ? <Loader2 className="w-3 h-3 animate-spin" /> : lightBrightness > 0 ? "ON" : "OFF"}
              </button>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={lightBrightness}
              onChange={(e) => setLightBrightness(Number(e.target.value))}
              className="flex-1 h-2 rounded-full appearance-none cursor-pointer"
              style={{
                background: `linear-gradient(to right, hsl(48, 95%, 65%) ${lightBrightness}%, hsl(220, 15%, 16%) ${lightBrightness}%)`,
              }}
            />
            <button
              onClick={() => doAction("light", "set_light_brightness", { brightness: lightBrightness })}
              disabled={loading === "light"}
              className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all active:scale-95"
              style={{
                background: success === "light" ? "hsl(152, 75%, 50%, 0.2)" : "hsl(48, 95%, 65%, 0.15)",
                border: `1px solid ${success === "light" ? "hsl(152, 75%, 50%)" : "hsl(48, 95%, 65%)"}30`,
                color: success === "light" ? "hsl(152, 75%, 50%)" : "hsl(48, 95%, 65%)",
              }}
            >
              {loading === "light" ? <Loader2 className="w-3 h-3 animate-spin" /> : success === "light" ? <Check className="w-3 h-3" /> : "Set"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
