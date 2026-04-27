"use client";

import { Droplets, Fan, Lightbulb, Waves, FlaskConical, Flower2, CloudRain } from "lucide-react";
import { GardenDashboardData } from "@/lib/garden/types";
import { getCurrentBrightness } from "@/lib/garden/calculations";

interface SystemStatusProps {
  data: GardenDashboardData | null;
}

interface StatusPill {
  label: string;
  status: string;
  active: boolean;
  icon: any;
  color: string;
}

export default function SystemStatus({ data }: SystemStatusProps) {
  const irrigating = data?.moisture?.current?.irrigating || false;
  const fanOn = data?.fan?.state || false;
  const fanSpeed = data?.fan?.speed || 100;
  const lightBrightness = data?.light_schedule ? getCurrentBrightness(data.light_schedule) : 0;
  const lastValve = data?.valve?.valve || null;
  const humidifierOn = data?.humidifier?.current?.is_on || false;

  const pills: StatusPill[] = [
    {
      label: "Pump",
      status: irrigating ? "Active" : "Idle",
      active: irrigating,
      icon: Waves,
      color: "hsl(185, 90%, 55%)",
    },
    {
      label: "Valve A",
      status: "Water",
      active: lastValve === "a",
      icon: Droplets,
      color: "hsl(185, 90%, 55%)",
    },
    {
      label: "Valve B",
      status: "Grow",
      active: lastValve === "b",
      icon: FlaskConical,
      color: "hsl(152, 75%, 50%)",
    },
    {
      label: "Valve C",
      status: "Bloom",
      active: lastValve === "c",
      icon: Flower2,
      color: "hsl(330, 80%, 65%)",
    },
    {
      label: "Fan",
      status: fanOn ? `${fanSpeed}%` : "Off",
      active: fanOn,
      icon: Fan,
      color: "hsl(185, 70%, 55%)",
    },
    {
      label: "Lights",
      status: lightBrightness > 0 ? `${lightBrightness}%` : "Off",
      active: lightBrightness > 0,
      icon: Lightbulb,
      color: "hsl(48, 95%, 65%)",
    },
    {
      label: "Humidifier",
      status: humidifierOn ? "On" : "Off",
      active: humidifierOn,
      icon: CloudRain,
      color: "hsl(270, 70%, 65%)",
    },
  ];

  return (
    <div className="rounded-xl p-4" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
      <span className="text-[11px] uppercase tracking-wider font-medium" style={{ color: "hsl(220, 10%, 50%)" }}>
        System Status
      </span>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-3">
        {pills.map((pill) => {
          const Icon = pill.icon;
          return (
            <div key={pill.label} className="flex items-center gap-2.5 px-3 py-2 rounded-lg"
              style={{ background: pill.active ? `${pill.color}10` : "hsl(220, 15%, 13%)" }}>
              <div className="relative">
                <Icon
                  className={`w-4 h-4 ${pill.label === "Fan" && pill.active ? "animate-spin" : ""}`}
                  style={{
                    color: pill.active ? pill.color : "hsl(220, 10%, 35%)",
                    animationDuration: pill.label === "Fan" ? `${Math.max(0.3, 2 - (fanSpeed / 100) * 1.7)}s` : undefined,
                  }}
                />
                <span
                  className={`absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full ${pill.active ? "animate-pulse" : ""}`}
                  style={{ background: pill.active ? pill.color : "hsl(220, 10%, 30%)" }}
                />
              </div>
              <div className="min-w-0">
                <div className="text-xs font-medium truncate" style={{ color: pill.active ? "white" : "hsl(220, 10%, 55%)" }}>
                  {pill.label}
                </div>
                <div className="text-[10px]" style={{ color: pill.active ? pill.color : "hsl(220, 10%, 35%)" }}>
                  {pill.status}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
