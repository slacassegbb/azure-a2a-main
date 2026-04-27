import { LightSchedule } from "./types";

export function getCurrentBrightness(schedule: LightSchedule): number {
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  const sunriseStart = schedule.sunrise_hour * 60;
  const sunriseEnd = sunriseStart + schedule.sunrise_ramp_min;
  const sunsetStart = schedule.sunset_hour * 60;
  const sunsetEnd = sunsetStart + schedule.sunset_ramp_min;

  if (minutes < sunriseStart) return schedule.night_brightness;
  if (minutes < sunriseEnd) {
    const progress = (minutes - sunriseStart) / schedule.sunrise_ramp_min;
    return Math.round(schedule.night_brightness + progress * (schedule.peak_brightness - schedule.night_brightness));
  }
  if (minutes < sunsetStart) return schedule.peak_brightness;
  if (minutes < sunsetEnd) {
    const progress = (minutes - sunsetStart) / schedule.sunset_ramp_min;
    return Math.round(schedule.peak_brightness - progress * (schedule.peak_brightness - schedule.night_brightness));
  }
  return schedule.night_brightness;
}

export function getNextEvent(schedule: LightSchedule): { event: string; time: string; countdown: string; icon: "sun" | "moon" } {
  const now = new Date();
  const hour = now.getHours() + now.getMinutes() / 60;

  if (hour < schedule.sunrise_hour) {
    return { event: "Sunrise", time: `${schedule.sunrise_hour}:00 AM`, countdown: formatCountdown(schedule.sunrise_hour - hour), icon: "sun" };
  }
  if (hour < schedule.sunset_hour) {
    const h = schedule.sunset_hour > 12 ? schedule.sunset_hour - 12 : schedule.sunset_hour;
    return { event: "Sunset", time: `${h}:00 PM`, countdown: formatCountdown(schedule.sunset_hour - hour), icon: "moon" };
  }
  return { event: "Sunrise", time: `${schedule.sunrise_hour}:00 AM`, countdown: formatCountdown(24 - hour + schedule.sunrise_hour), icon: "sun" };
}

function formatCountdown(hours: number): string {
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  if (h === 0) return `${m}m`;
  return `${h}h ${m}m`;
}

export function getDayProgress(): number {
  const now = new Date();
  return (now.getHours() * 60 + now.getMinutes()) / 1440;
}

export function getLightPhase(schedule: LightSchedule): "night" | "sunrise" | "day" | "sunset" {
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  const sunriseStart = schedule.sunrise_hour * 60;
  const sunriseEnd = sunriseStart + schedule.sunrise_ramp_min;
  const sunsetStart = schedule.sunset_hour * 60;
  const sunsetEnd = sunsetStart + schedule.sunset_ramp_min;

  if (minutes < sunriseStart || minutes >= sunsetEnd) return "night";
  if (minutes < sunriseEnd) return "sunrise";
  if (minutes < sunsetStart) return "day";
  return "sunset";
}

export function generateLightCurve(schedule: LightSchedule): { hour: number; brightness: number }[] {
  const points: { hour: number; brightness: number }[] = [];
  for (let m = 0; m < 1440; m += 15) {
    const sunriseStart = schedule.sunrise_hour * 60;
    const sunriseEnd = sunriseStart + schedule.sunrise_ramp_min;
    const sunsetStart = schedule.sunset_hour * 60;
    const sunsetEnd = sunsetStart + schedule.sunset_ramp_min;

    let brightness = schedule.night_brightness;
    if (m >= sunriseStart && m < sunriseEnd) {
      const progress = (m - sunriseStart) / schedule.sunrise_ramp_min;
      brightness = schedule.night_brightness + progress * (schedule.peak_brightness - schedule.night_brightness);
    } else if (m >= sunriseEnd && m < sunsetStart) {
      brightness = schedule.peak_brightness;
    } else if (m >= sunsetStart && m < sunsetEnd) {
      const progress = (m - sunsetStart) / schedule.sunset_ramp_min;
      brightness = schedule.peak_brightness - progress * (schedule.peak_brightness - schedule.night_brightness);
    }
    points.push({ hour: m / 60, brightness: Math.round(brightness) });
  }
  return points;
}

export function formatTimeAgo(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ${mins % 60}m ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export function getTrend(readings: { pct: number }[], hoursAgo: number = 6): { direction: "up" | "down" | "stable"; change: number } {
  if (readings.length < 2) return { direction: "stable", change: 0 };
  const recent = readings[readings.length - 1].pct;
  const cutoff = readings.length - Math.min(Math.floor(hoursAgo * 12), readings.length);
  const past = readings[cutoff]?.pct ?? recent;
  const change = recent - past;
  if (Math.abs(change) < 2) return { direction: "stable", change: 0 };
  return { direction: change > 0 ? "up" : "down", change: Math.abs(Math.round(change)) };
}
