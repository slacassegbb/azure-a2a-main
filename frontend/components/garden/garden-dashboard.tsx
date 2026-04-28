"use client";

import { useEffect, useState, useCallback } from "react";
import { RefreshCw, Sprout, Settings } from "lucide-react";
import GardenConfig from "./garden-config";
import { GardenDashboardData } from "@/lib/garden/types";
import { POLL_INTERVAL_MS } from "@/lib/garden/constants";
import SensorCard from "./sensor-card";
import CameraFeed from "./camera-feed";
import LightTimeline from "./light-timeline";
import SystemStatus from "./system-status";
import AgentLog from "./agent-log";
import QuickControls from "./quick-controls";
import NextEvent from "./next-event";
import LastAction from "./last-action";
import EnvironmentChart from "./environment-chart";
// PhotoTimeline is now integrated into CameraFeed

export default function GardenDashboard() {
  const [data, setData] = useState<GardenDashboardData | null>(null);
  const [lastFetched, setLastFetched] = useState<Date | null>(null);
  const [secondsAgo, setSecondsAgo] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setRefreshing(true);
      const res = await fetch("/api/garden/data");
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      const json = await res.json();
      setData(json);
      setLastFetched(new Date());
      setSecondsAgo(0);
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchData]);

  useEffect(() => {
    const tick = setInterval(() => {
      if (lastFetched) setSecondsAgo(Math.floor((Date.now() - lastFetched.getTime()) / 1000));
    }, 1000);
    return () => clearInterval(tick);
  }, [lastFetched]);

  const moisture = data?.moisture;
  const schedule = data?.light_schedule;
  const tempC = moisture?.current?.temp_c;
  const moisturePct = moisture?.current?.pct;
  const humidity = data?.humidifier?.current?.humidity;
  const humidityReadings = data?.humidifier?.readings || [];

  return (
    <div className="min-h-screen text-white" style={{ background: "hsl(220, 20%, 7%)" }}>
      {/* Header + Quick Controls */}
      <header className="sticky top-0 z-50 backdrop-blur-md border-b"
        style={{ background: "hsla(220, 20%, 7%, 0.9)", borderColor: "hsl(220, 15%, 16%)" }}>
        <div className="max-w-[1400px] mx-auto px-3 py-2 md:px-4 md:py-2 flex items-center gap-2 md:gap-3">
          {/* Title — left */}
          <div className="flex items-center gap-1.5 xl:gap-2 shrink-0">
            <div className="w-6 h-6 xl:w-8 xl:h-8 rounded xl:rounded-lg flex items-center justify-center" style={{ background: "hsl(152, 75%, 50%, 0.15)" }}>
              <Sprout className="w-3.5 h-3.5 xl:w-4 xl:h-4" style={{ color: "hsl(152, 75%, 50%)" }} />
            </div>
            <h1 className="text-sm xl:text-base font-semibold tracking-tight hidden md:block">Smart Garden</h1>
            <GardenConfig />
          </div>

          <div className="w-px h-5 shrink-0" style={{ background: "hsl(220, 15%, 20%)" }} />

          {/* Quick controls — centered */}
          <div className="flex-1 flex justify-center">
            <QuickControls data={data} onRefresh={fetchData} inline />
          </div>

          <div className="w-px h-5 shrink-0" style={{ background: "hsl(220, 15%, 20%)" }} />

          {/* Status + refresh — right */}
          <div className="flex items-center gap-2 shrink-0">
            {error && <span className="text-[10px] px-2 py-1 rounded-full" style={{ background: "hsl(0, 85%, 60%, 0.15)", color: "hsl(0, 85%, 60%)" }}>Error</span>}
            <span className="text-[10px]" style={{ color: "hsl(220, 10%, 45%)" }}>
              {lastFetched ? `${secondsAgo}s` : "..."}
            </span>
            <button
              onClick={fetchData}
              disabled={refreshing}
              className="w-7 h-7 rounded-lg flex items-center justify-center transition-colors hover:bg-white/5"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`} style={{ color: "hsl(220, 10%, 45%)" }} />
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-[1400px] mx-auto p-2 md:p-3 xl:p-4 space-y-2 md:space-y-3 xl:space-y-4">
        {/* Row 1: Camera + Light Cycle side by side */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2 md:gap-3">
          <CameraFeed url={data?.camera_url} timestamp={data?.camera_timestamp} photos={data?.photos || []} />
          <LightTimeline schedule={schedule} readings={moisture?.readings} />
        </div>

        {/* Row 2: Sensor cards — 3 across */}
        <div className="grid grid-cols-3 gap-2 md:gap-3">
          <SensorCard
            label="Temperature"
            value={tempC != null ? tempC.toFixed(1) : "--"}
            unit="°C"
            secondaryValue={tempC != null ? `${(tempC * 9 / 5 + 32).toFixed(0)}°F` : ""}
            color="hsl(35, 95%, 60%)"
            icon="thermometer"
            history={moisture?.readings?.map(r => ({ ts: r.ts, value: (r as any).temp_c ?? tempC ?? 0 })) || []}
            dataKey="value"
          />
          <SensorCard
            label="Soil Moisture"
            value={moisturePct != null ? String(moisturePct) : "--"}
            unit="%"
            color="hsl(185, 90%, 55%)"
            icon="droplets"
            history={moisture?.readings?.map(r => ({ ts: r.ts, value: r.pct })) || []}
            dataKey="value"
          />
          <SensorCard
            label="Humidity"
            value={humidity != null ? String(humidity) : "--"}
            unit="%"
            secondaryValue={data?.humidifier?.current?.is_on ? "Humidifier ON" : data?.humidifier ? "Humidifier OFF" : "Via agent"}
            color="hsl(270, 70%, 65%)"
            icon="cloud"
            history={humidityReadings.map(r => ({ ts: r.ts, value: r.humidity }))}
            dataKey="value"
          />
        </div>

        {/* Middle row: Status + Agent Log */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2 md:gap-3 xl:gap-4">
          <div className="space-y-4">
            <SystemStatus data={data} />
            <div className="grid grid-cols-2 gap-4">
              <NextEvent schedule={schedule} />
              <LastAction log={data?.garden_log || []} />
            </div>
          </div>
          <AgentLog entries={data?.garden_log || []} />
        </div>

        {/* Historical Charts */}
        <EnvironmentChart readings={moisture?.readings || []} schedule={schedule} humidityReadings={humidityReadings} events={moisture?.events || []} />
      </main>
    </div>
  );
}
