export interface MoistureReading {
  ts: string;
  raw: number;
  pct: number;
  temp_c?: number;
  light?: number;
}

export interface GardenEvent {
  ts: string;
  type: string;
  detail?: string;
}

export interface MoistureData {
  current: {
    raw: number;
    pct: number;
    temp_c: number | null;
    timestamp: string;
    irrigating: boolean;
  };
  readings: MoistureReading[];
  events?: GardenEvent[];
}

export interface LightSchedule {
  request_id: string;
  sunrise_hour: number;
  sunrise_ramp_min: number;
  peak_brightness: number;
  sunset_hour: number;
  sunset_ramp_min: number;
  night_brightness: number;
}

export interface FanCommand {
  request_id: string;
  state: boolean;
  speed?: number;
  duration_min?: number;
}

export interface ValveCommand {
  request_id: string;
  valve: string;
  duration_seconds: number;
}

export interface IrrigationCommand {
  request_id: string;
  irrigate: boolean;
  duration_ms: number;
}

export interface GardenLogEntry {
  timestamp: string;
  summary: string;
}

export interface GardenPhoto {
  name: string;
  url: string;
  timestamp: string;
}

export interface HumidityReading {
  ts: string;
  humidity: number;
  is_on: boolean;
}

export interface HumidifierStatus {
  current: {
    humidity: number | null;
    is_on: boolean;
    mist_level: number | null;
    mode: string | null;
    water_lacks: boolean;
    target_humidity: number | null;
    timestamp: string;
  };
  readings: HumidityReading[];
}

export interface GardenDashboardData {
  timestamp: string;
  moisture: MoistureData | null;
  light_schedule: LightSchedule | null;
  fan: FanCommand | null;
  valve: ValveCommand | null;
  irrigation: IrrigationCommand | null;
  camera_url: string | null;
  camera_timestamp: string | null;
  garden_log: GardenLogEntry[];
  photos: GardenPhoto[];
  humidifier: HumidifierStatus | null;
}
