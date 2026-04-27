"use client";

import { useEffect, useState } from "react";
import { Clock, Sun, Moon } from "lucide-react";
import { LightSchedule } from "@/lib/garden/types";
import { getNextEvent } from "@/lib/garden/calculations";

interface NextEventProps {
  schedule: LightSchedule | null | undefined;
}

export default function NextEvent({ schedule }: NextEventProps) {
  const [event, setEvent] = useState<ReturnType<typeof getNextEvent> | null>(null);

  useEffect(() => {
    if (!schedule) return;
    const update = () => setEvent(getNextEvent(schedule));
    update();
    const interval = setInterval(update, 60000);
    return () => clearInterval(interval);
  }, [schedule]);

  const Icon = event?.icon === "sun" ? Sun : Moon;
  const color = event?.icon === "sun" ? "hsl(48, 95%, 65%)" : "hsl(220, 60%, 65%)";

  return (
    <div className="rounded-xl p-4 flex flex-col justify-between" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
      <div className="flex items-center gap-2">
        <Clock className="w-3.5 h-3.5" style={{ color: "hsl(220, 10%, 50%)" }} />
        <span className="text-[11px] uppercase tracking-wider font-medium" style={{ color: "hsl(220, 10%, 50%)" }}>Next Event</span>
      </div>
      {event ? (
        <div className="mt-2">
          <div className="flex items-center gap-2">
            <Icon className="w-5 h-5" style={{ color }} />
            <span className="text-lg font-semibold">{event.event}</span>
          </div>
          <div className="mt-1">
            <span className="text-2xl font-bold tracking-tight" style={{ color }}>{event.countdown}</span>
          </div>
          <span className="text-[11px]" style={{ color: "hsl(220, 10%, 45%)" }}>{event.time}</span>
        </div>
      ) : (
        <span className="text-xs mt-2" style={{ color: "hsl(220, 10%, 35%)" }}>No schedule</span>
      )}
    </div>
  );
}
