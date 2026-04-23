# Smart Garden System

An AI-powered autonomous indoor garden using ESP32 IoT devices, Azure AI, and the A2A multi-agent platform.

## System Architecture

```
                    SMART GARDEN SYSTEM
    ═══════════════════════════════════════════════

    ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
    │ Reservoir A │   │ Reservoir B │   │ Reservoir C │
    │  (Nitrogen) │   │(Phosphorus) │   │(Plain Water)│
    └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
           │                 │                 │
      ┌────┴────┐      ┌────┴────┐      ┌────┴────┐
      │ Valve A │      │ Valve B │      │ Valve C │
      │(Relay 2)│      │(Relay 3)│      │(Relay 4)│
      └────┬────┘      └────┬────┘      └────┬────┘
           │                 │                 │
           └────────┬────────┘                 │
                    │  (T-connector)           │
                    └───────────┬──────────────┘
                                │  (T-connector)
                                │
                          ┌─────┴─────┐
                          │   PUMP    │
                          │ (Relay 1) │
                          └─────┬─────┘
                                │
                    ┌───────────┴───────────┐
                    │   Drip lines to pots  │
                    └───────────────────────┘
```

## Hardware

### ESP32 #1 — Irrigation Controller
**Board:** Freenove ESP32-S3-WROOM
**Firmware:** `iot_devices/irrigation/irrigation.ino`

| GPIO | Device | Notes |
|------|--------|-------|
| 4 | Relay CH1 → Pump | 12V water pump via TalentCell battery |
| 9 | Moisture Sensor | Capacitive Soil Moisture v1.2, ADC_2_5db, EMA smoothing |
| 15 | MOSFET → Mean Well Dimmer | LR7843 MOSFET module, inverted PWM signal |
| TBD | Relay CH2 → Valve A | 12V solenoid, nitrogen fertilizer reservoir |
| TBD | Relay CH3 → Valve B | 12V solenoid, phosphorus fertilizer reservoir |
| TBD | Relay CH4 → Valve C | 12V solenoid, plain water reservoir |
| TBD | DS18B20 Temperature | Waterproof probe with PCB adapter |
| GND | Shared | Moisture sensor, MOSFET, relay board |
| 3.3V | Moisture sensor VCC | |
| 5V | Relay board VCC | Also powers moisture sensor alternative |

**Peripherals:**
- CW-022 4-channel relay board (12V switching)
- LR7843 MOSFET module (PWM light dimming)
- Capacitive Soil Moisture Sensor v1.2
- DS18B20 temperature probe (arriving Friday)
- 3x DIGITEN 12V 1/4" solenoid valves (arriving Friday)

**Azure Blob Polling:**
- `irrigation-command.json` — irrigation commands (every 5s)
- `light-schedule.json` — light schedule (every 60s)
- `fan-command.json` — fan on/off commands (every 30s)

**Azure Blob Uploads:**
- `moisture-data.json` — moisture readings + 48hr history (every 5min)

### ESP32 #2 — Vision Camera
**Board:** ESP32-S3-EYE (with PSRAM + OV2640 camera)
**Firmware:** `iot_devices/vision/vision.ino`

**Camera Settings:**
- Resolution: 1600x1200 (UXGA)
- JPEG quality: 6 (high quality with PSRAM)
- Contrast: +1, Sharpness: +2
- Auto exposure with advanced AEC

**Features:**
- Scheduled photo upload every 30 minutes
- On-demand capture via `capture-command.json` blob polling (every 5s)
- Timestamped photos: `YYYY-MM-DD_HH-MM-SS.jpg`
- `latest.jpg` always updated
- NVS persistence for capture request IDs
- WiFi reconnection on disconnect
- Watchdog: auto-reboot every 6 hours or if no upload for 45 minutes
- OTA update support (hostname: `esp32-vision`)

### Smart Plugs (TP-Link Kasa, local TCP control)

| Device | IP Address | Purpose | Protocol |
|--------|-----------|---------|----------|
| KP405 | 10.0.0.169 | Grow light power (on/off) | Kasa TCP:9999 |
| KP401 | 10.0.0.182 | Fan (on/off) | Kasa TCP:9999 |

**Kasa Protocol:** XOR autokey cipher (init key=171) over TCP port 9999. 4-byte big-endian length header + encrypted JSON payload.

### Grow Light
**Light:** 1000W Full Spectrum LED (Samsung LM301B)
**Driver:** Mean Well XLG-100-H-AB (3-in-1 dimming: 0-10V, PWM, resistance)
**Dimming:** ESP32 GPIO 15 → LR7843 MOSFET module → DIM+/DIM- wires
**On/Off:** KP405 smart plug cuts AC power for true 0% (Mean Well can't go below ~8%)
**PWM:** Inverted signal — PWM 0 = full brightness, PWM 255 = off

### Humidifier
**Device:** Levoit LV600S (model LUH-A602S-WUS)
**Control:** VeSync cloud API via `pyvesync` Python library
**Capabilities:** On/off, mist level (1-9), auto mode with target humidity (30-80%), warm mist, humidity sensor readout
**Credentials:** VeSync account (slacasseibm@gmail.com)
**Conservative policy:** Only activate below 40% humidity, target 50%, never above 60% (electronics safety)

## Light Schedule

**Default production schedule (natural sun simulation):**

| Time | Brightness | Phase |
|------|-----------|-------|
| 5:00 AM | 0% → ramping | First light |
| 5:45 AM | ~50% | Dawn |
| 6:30 AM | 100% | Full sun |
| 6:30 AM - 8:00 PM | 100% | Daytime |
| 8:00 PM | 100% → ramping down | Sunset begins |
| 8:45 PM | ~50% | Dusk |
| 9:30 PM | 0% + KP405 off | Night |

- 90-minute sunrise/sunset ramps (1% per minute)
- ESP32 updates dimmer every 60 seconds
- KP405 cuts power at 0% for true darkness
- KP405 turns on when brightness goes above 0%
- Timezone: Eastern (EST/EDT automatic)

## Moisture Sensor Calibration

**ESP32-S3 ADC quirks:**
- GPIO 9, ADC_2_5db attenuation, 12-bit resolution
- `analogSetPinAttenuation()` re-init before each batch (prevents ADC drift)
- 50 rapid readings + exponential moving average (alpha=0.3)
- Discard readings during irrigation (relay causes electrical noise)
- 30-second settling period after irrigation before resuming reads

**Calibration (production, with wires):**
- Raw 290 → 0% (dry)
- Raw 540 → 100% (wet)
- Readings skip during irrigation (pump noise)
- EMA resets after irrigation stops

## Azure Blob Storage

**Account:** `a2astoragefilesa2a`
**Container:** `garden-images`
**Auth:** Shared Key (HMAC-SHA256)

| Blob | Purpose | Updated by |
|------|---------|-----------|
| `latest.jpg` | Most recent garden photo | Vision ESP32 |
| `YYYY-MM-DD_HH-MM-SS.jpg` | Timestamped photo archive | Vision ESP32 |
| `irrigation-command.json` | Irrigation trigger + duration | Gardening Agent |
| `capture-command.json` | On-demand photo capture trigger | Gardening Agent |
| `moisture-data.json` | Current + 48hr moisture history | Irrigation ESP32 |
| `light-schedule.json` | Sunrise/sunset/brightness schedule | Gardening Agent |
| `fan-command.json` | Fan on/off + duration | Gardening Agent |

## Gardening Agent

**Deployed:** Azure Container Apps (`azurefoundry-gardening`)
**Port:** 9050
**LLM:** Azure OpenAI GPT-4o (Responses API with function calling)
**Protocol:** A2A (Agent-to-Agent)

### Tools (10 total)

| Tool | Purpose | Method |
|------|---------|--------|
| `capture_fresh_photo` | Take real-time garden photo | Blob command → ESP32 → upload |
| `get_moisture_data` | Read soil moisture + history | Read blob |
| `irrigate_garden` | Water with configurable duration | Blob command → ESP32 → relay → pump |
| `control_lights` | Adjust sunrise/sunset schedule | Write blob → ESP32 → PWM + Kasa |
| `control_fan` | Fan on/off with optional duration | Blob command → ESP32 → Kasa KP401 |
| `control_humidifier` | Humidity control + sensor reading | VeSync cloud API → Levoit LV600S |
| `get_historical_images` | Fetch photos by date range | Read blobs |
| `create_timelapse` | Generate MP4 from photo archive | ffmpeg + blob upload |
| `get_temperature` | Read air temperature (coming soon) | DS18B20 → blob |
| `irrigate_with_valve` | Choose fertilizer reservoir (coming soon) | Blob → ESP32 → relay → valve + pump |

### Multi-Round Tool Loop
The agent uses an agentic loop — sends user message to LLM with tools, executes tool calls, feeds results back using proper `function_call` / `function_call_output` format, and repeats until the LLM responds with text. Max 4 rounds.

### Skills (registered on agent card for orchestrator routing)
- Garden Image Analysis
- Gardening Expert Advice
- Garden Temporal Analysis
- Irrigation Control
- Soil Moisture Sensor
- Grow Light Control
- Fan Control
- Humidity Control
- Garden Timelapse Video
- Human Expert Escalation

## Garden Autopilot Workflow

**Schedule:** Every 3 hours
**Workflow ID:** `garden-autopilot`
**Schedule ID:** `fab76d85-c5d9-4117-a340-911e338d1fe7`
**Timeout:** 300 seconds

**Step 1 — Home Gardening Agent:**
> Check my garden. Take a photo, read soil moisture, and check room humidity. Based on what you see and the sensor data: irrigate if moisture is below 20%, adjust the light schedule based on plant growth stage, keep fan running during light hours, and turn on humidifier only if humidity is below 40% (target 50%, be conservative with water). Provide a brief summary.

**Step 2 — Text Message Agent:**
> Send a text message to 514-771-5943 with a brief summary of the garden status from the previous step. Include moisture, humidity, actions taken, and plant health.

## Network

| Device | IP | Port |
|--------|-----|------|
| KP405 (grow light) | 10.0.0.169 | 9999 |
| KP401 (fan) | 10.0.0.182 | 9999 |
| Irrigation ESP32 | 10.0.0.107 | 80 (web UI) |
| Vision ESP32 | DHCP | N/A |

## Coming Soon (parts arriving Friday)

### Temperature Sensor
- DS18B20 waterproof probe with PCB adapter
- Connects to irrigation ESP32, free GPIO
- Uploads to `temperature-data.json` blob
- New agent tool: `get_temperature`

### Multi-Valve Fertilizer System
- 3x DIGITEN 12V 1/4" solenoid valves (normally closed)
- Connected to relay channels 2, 3, 4
- 3 reservoirs: nitrogen mix, phosphorus mix, plain water
- T-connectors merge outputs → single pump input
- New agent tool: `irrigate_with_valve(valve, duration)`
- Agent chooses fertilizer based on plant growth stage

## Files

```
iot_devices/
  irrigation/
    irrigation.ino          # Main irrigation controller firmware
    test_irrigate.py        # Test script for irrigation commands
  vision/
    vision.ino              # Camera device firmware
    app_httpd.cpp           # Camera web server handler

remote_agents/
  azurefoundry_gardening/
    foundry_agent.py        # Gardening agent with all tools
    foundry_agent_executor.py # A2A executor wrapper
    __main__.py             # Skills + A2A server setup
    pyproject.toml          # Dependencies
    Dockerfile              # Container (includes ffmpeg)
```
