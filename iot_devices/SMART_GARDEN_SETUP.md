# Smart Garden System

An AI-powered autonomous indoor garden using ESP32 IoT devices, Azure AI, and the A2A multi-agent platform. The system monitors plants via camera vision, reads environmental sensors (moisture, temperature, humidity), and makes intelligent decisions about watering, nutrient delivery, lighting, ventilation, and humidity — with minimal human intervention.

## System Architecture

```
                        SMART GARDEN SYSTEM
    ═══════════════════════════════════════════════════════

    ┌──────────────────────────────────────────────────────┐
    │                  AZURE CLOUD                         │
    │                                                      │
    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
    │  │  Azure Blob  │  │ Azure OpenAI│  │  A2A Backend │  │
    │  │  Storage     │  │  GPT-4o     │  │  Orchestrator│  │
    │  │             │  │  (Vision)   │  │             │  │
    │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  │
    │         │                │                │          │
    │  ┌──────┴────────────────┴────────────────┴──────┐   │
    │  │         Gardening Agent (Container App)       │   │
    │  │  13 tools · per-user memory · A2A protocol    │   │
    │  └───────────────────┬───────────────────────────┘   │
    └──────────────────────┼───────────────────────────────┘
                           │
              Azure Blob Storage (command/data bridge)
                           │
    ┌──────────────────────┼───────────────────────────────┐
    │                 LOCAL NETWORK                         │
    │                      │                               │
    │  ┌───────────────────┴───────────────────────┐       │
    │  │        ESP32 #1 — Irrigation Controller    │       │
    │  │  Moisture · Temp · Light · Fan · Valves    │       │
    │  └───────────────────┬───────────────────────┘       │
    │                      │                               │
    │  ┌───────────────────┴───────────────────────┐       │
    │  │        ESP32 #2 — Vision Camera            │       │
    │  │  1600x1200 · 30min scheduled · on-demand   │       │
    │  └───────────────────────────────────────────┘       │
    │                                                      │
    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
    │  │ KP401       │  │ KP405       │  │ Levoit      │  │
    │  │ Grow Light  │  │ Fan+Dimmer  │  │ Humidifier  │  │
    │  │ (on/off)    │  │ (speed)     │  │ (VeSync)    │  │
    │  └─────────────┘  └─────────────┘  └─────────────┘  │
    └──────────────────────────────────────────────────────┘
```

### Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ Every 3 hours (Garden Autopilot Workflow):                      │
│                                                                 │
│ 1. Backend orchestrator triggers workflow                       │
│ 2. Gardening Agent reads per-user memory log                    │
│ 3. Agent captures fresh photo → ESP32 Vision uploads to blob    │
│ 4. Agent reads moisture + temperature from blob                 │
│ 5. Agent reads humidity from Levoit VeSync API                  │
│ 6. GPT-4o analyzes photo + sensor data + memory                 │
│ 7. Agent decides: irrigate? which valve? fan speed? lights?     │
│ 8. Agent writes command blobs → ESP32 polls and executes        │
│ 9. Agent appends summary to per-user memory log                 │
│ 10. Text Message Agent sends SMS summary to owner               │
└─────────────────────────────────────────────────────────────────┘
```

### Irrigation & Fertilizer System

```
    ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
    │ Reservoir A │   │ Reservoir B │   │ Reservoir C │
    │(Plain Water)│   │(Grow 2-1-6) │   │(Bloom 0-5-1)│
    └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
           │                 │                 │
      ┌────┴────┐      ┌────┴────┐      ┌────┴────┐
      │ Valve A │      │ Valve B │      │ Valve C │
      │(GPIO 5) │      │(GPIO 7) │      │(GPIO 8) │
      └────┬────┘      └────┬────┘      └────┬────┘
           │                 │                 │
           └────────┬────────┘                 │
                    │  (T-connector)           │
                    └───────────┬──────────────┘
                                │  (T-connector)
                                │
                          ┌─────┴─────┐
                          │   PUMP    │
                          │ (GPIO 4)  │
                          └─────┬─────┘
                                │
                    ┌───────────┴───────────┐
                    │   Drip lines to pots  │
                    └───────────────────────┘

    Valve A: Plain water — flushing salts, light watering
    Valve B: Diablo Grow 2-1-6 — vegetative growth (nitrogen/potassium)
    Valve C: Diablo Bloom 0-5-1 — flowering stage (phosphorus)
    Diablo Micro 5-0-1: Mixed into both B and C reservoirs as base supplement
```

---

## Gardening Agent

**Deployed:** Azure Container Apps (`azurefoundry-gardening`)
**Port:** 9050
**LLM:** Azure OpenAI GPT-4o (Responses API with function calling + vision)
**Protocol:** A2A (Agent-to-Agent)

### Tools (13 total)

| Tool | Purpose | Method |
|------|---------|--------|
| `capture_fresh_photo` | Take real-time garden photo | Blob command → ESP32 Vision → upload → GPT-4o analysis |
| `get_moisture_data` | Read soil moisture + temperature + history | Read moisture-data.json blob |
| `get_temperature` | Read air temperature | Read moisture-data.json blob (temp_c field) |
| `irrigate_garden` | Water with main pump (configurable duration) | Write irrigation-command.json → ESP32 → relay → pump |
| `irrigate_with_valve` | Water with specific nutrient valve | Write valve-command.json → ESP32 → valve + pump |
| `control_lights` | Adjust sunrise/sunset schedule + brightness | Write light-schedule.json → ESP32 → PWM + Kasa |
| `control_fan` | Fan on/off with speed control (1-100%) | Write fan-command.json → ESP32 → Kasa KP405 dimmer |
| `control_humidifier` | Humidity control + sensor reading | VeSync cloud API → Levoit LV600S |
| `get_historical_images` | Fetch photos by date range | Read blobs from garden-images container |
| `create_timelapse` | Generate MP4 from photo archive | ffmpeg + blob upload |
| `clear_garden_log` | Reset per-user activity memory | Overwrite garden-log-{user_id}.json |

### Multi-Round Tool Loop

The agent uses an agentic loop — sends user message to LLM with tools, executes tool calls, feeds results back using proper `function_call` / `function_call_output` format, and repeats until the LLM responds with text. Max 4 rounds. Vision analysis happens in a final LLM call with base64-encoded images.

### Per-User Memory System

The agent maintains a rolling activity log per user in Azure Blob Storage:
- **Blob name:** `garden-log-{user_id}.json` (e.g., `garden-log-user_3.json`)
- **Max entries:** 50 (~6 days at 3-hour autopilot intervals)
- **Read:** At the start of each conversation, last 10 entries injected into LLM instructions
- **Write:** After each conversation, the agent's response summary (first 500 chars) appended
- **Clear:** User can say "clear my garden memory" to reset

This allows the agent to reference previous observations:
- *"3 hours ago: moisture 45%, irrigated with Grow nutrients, plants in vegetative stage"*
- *"Yesterday: noticed early flowering, switched to Bloom nutrients"*

### Skills (registered on agent card for orchestrator routing)

| Skill | Description |
|-------|-------------|
| Garden Image Analysis | Analyze plant health, growth, pests from camera |
| Gardening Expert Advice | General gardening questions and care recommendations |
| Garden Temporal Analysis | Compare garden photos over time, track growth |
| Irrigation Control | Trigger main pump with configurable duration |
| Valve Irrigation Control | Choose nutrient reservoir based on growth stage |
| Soil Moisture Sensor | Read moisture % and 48-hour history |
| Temperature Sensor | Read air temperature from DS18B20 |
| Grow Light Control | Configure sunrise/sunset schedule and brightness |
| Fan Control | On/off with variable speed (1-100%) |
| Humidity Control | Read humidity and control Levoit humidifier |
| Garden Timelapse Video | Create MP4 from historical photos |
| Garden Memory | Clear/reset per-user activity log |
| Human Expert Escalation | Escalate complex issues to human experts |

### Agent Instructions (System Prompt)

The LLM receives instructions including:
- Role as a home gardening assistant with IoT capabilities
- List of available tools and when to use them
- Valve descriptions (A=water, B=Grow, C=Bloom)
- Conservative guidelines (irrigate only when clearly dry, humidifier below 40%)
- Current date/time in local timezone
- Last 10 garden activity log entries (per-user memory)

---

## IoT Hardware

### ESP32 #1 — Irrigation Controller

**Board:** Freenove ESP32-S3-WROOM
**Firmware:** `iot_devices/irrigation/irrigation.ino`
**IP:** 10.0.0.107 (static)
**Web UI:** http://10.0.0.107 (status + valve test endpoints)

#### GPIO Pin Map

| GPIO | Device | Notes |
|------|--------|-------|
| 4 | Relay CH1 → Pump | 12V water pump via TalentCell battery, active LOW |
| 5 | Relay CH2 → Valve A | 12V solenoid, plain water reservoir |
| 6 | DS18B20 Temperature | OneWire digital sensor with PCB adapter |
| 7 | Relay CH3 → Valve B | 12V solenoid, Grow 2-1-6 reservoir |
| 8 | Relay CH4 → Valve C | 12V solenoid, Bloom 0-5-1 reservoir |
| 9 | Moisture Sensor | Capacitive v1.2, ADC1, ADC_2_5db attenuation |
| 15 | MOSFET → Mean Well Dimmer | LR7843 MOSFET module, inverted PWM |
| GND | Shared | All devices (solder connections for reliability) |
| 3.3V | Shared | Moisture sensor + temperature sensor VCC |
| 5V | Relay board VCC | Powers relay board |

#### Peripherals

| Device | Model | Purpose |
|--------|-------|---------|
| Relay board | CW-022 4-channel | Switches pump + 3 valves (12V, active LOW) |
| MOSFET module | LR7843 | PWM light dimming (opens at 2.5V, works with 3.3V) |
| Moisture sensor | Capacitive Soil Moisture v1.2 | Soil moisture ADC reading |
| Temperature probe | DS18B20 waterproof | Air temperature via OneWire (±0.5°C) |
| Solenoid valves | DIGITEN 12V 1/4" (x3) | Normally closed, 12V to open |
| Smart plug (light) | TP-Link KP401 | Hard on/off for grow light AC power |
| Smart plug (fan) | TP-Link KP405 | Fan power + speed via dimmer (1-100%) |

#### Azure Blob Polling

| Blob | Direction | Interval | Purpose |
|------|-----------|----------|---------|
| `irrigation-command.json` | Read | 5s | Irrigation trigger + duration |
| `valve-command.json` | Read | 5s | Valve selection + pump + duration |
| `light-schedule.json` | Read | 60s | Sunrise/sunset/brightness schedule |
| `fan-command.json` | Read | 30s | Fan on/off + speed + duration |
| `moisture-data.json` | Write | 5min | Current moisture + temp + 48hr history |

#### Moisture Sensor Details

**ADC Configuration:**
- GPIO 9, ADC1, `ADC_2_5db` attenuation (0-1.1V range)
- `analogSetPinAttenuation()` re-init before each batch
- 12-bit resolution (0-4095)

**Reading Process:**
1. Discard 20 readings (flush ADC)
2. Take 50 rapid readings at 500μs intervals
3. **Filter out zeros** (WiFi TX noise causes ADC to read 0 — this is a known ESP32 issue)
4. Average remaining valid readings
5. Apply EMA smoothing (alpha=0.15, heavy smoothing)

**Calibration:** Raw 40 = 0% (dry air), Raw 110 = 100% (wet soil)

**Known Issues:**
- WiFi transmissions cause ~50% of ADC reads to return 0 — filtered by discarding readings ≤5
- Different power sources (USB laptop vs wall adapter) shift the baseline by ~20 raw points
- Shared GND pin requires soldered connections — loose wires cause erratic readings
- Sensor output range is narrow (70 points) compared to the old sensor (250 points)

#### Light Schedule & Dimming

**Grow Light:** 1000W Full Spectrum LED (Samsung LM301B)
**Driver:** Mean Well XLG-100-H-AB (3-in-1 dimming: 0-10V, PWM, resistance)
**Dimming:** ESP32 GPIO 15 → LR7843 MOSFET module → DIM+/DIM- wires
**On/Off:** KP401 smart plug cuts AC power for true 0% (Mean Well can't go below ~8%)
**PWM:** Inverted signal — PWM 0 = full brightness, PWM 255 = off

**Default Schedule (natural sun simulation):**

| Time | Brightness | Phase |
|------|-----------|-------|
| 5:00 AM | 0% → ramping | First light |
| 5:45 AM | ~50% | Dawn |
| 6:30 AM | 100% | Full sun |
| 6:30 AM - 8:00 PM | 100% | Daytime |
| 8:00 PM | 100% → ramping down | Sunset begins |
| 8:45 PM | ~50% | Dusk |
| 9:30 PM | 0% + KP401 off | Night |

- 90-minute sunrise/sunset ramps (linear interpolation)
- ESP32 updates dimmer every 60 seconds
- KP401 cuts power at 0% for true darkness
- Kasa retry: re-sends command every 5 minutes as safety net
- On failure: resets `currentBrightness` to -1 for retry on next cycle
- Timezone: Eastern (EST/EDT automatic)

#### Fan Control

**Device:** Fan plugged into TP-Link KP405 outdoor dimmer
**Protocol:** Kasa local TCP (port 9999, XOR autokey cipher)
**Speed:** 1-100% via `smartlife.iot.dimmer.set_brightness`
**Auto-off:** Optional duration timer (in minutes)

#### Kasa Protocol

- TCP port 9999 on local network
- XOR autokey cipher: init key=171, `encrypted[i] = plaintext[i] XOR key; key = encrypted[i]`
- 4-byte big-endian length header + encrypted JSON payload
- Commands:
  - Relay on: `{"system":{"set_relay_state":{"state":1}}}`
  - Relay off: `{"system":{"set_relay_state":{"state":0}}}`
  - Set speed/brightness: `{"smartlife.iot.dimmer":{"set_brightness":{"brightness":N}}}`

#### Web Server Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | HTML status page |
| `/status` | GET | JSON: moisture, temp, irrigation state |
| `/valve-open?v=a` | GET | Open specific valve (a/b/c) |
| `/valve-close` | GET | Close all valves |
| `/test-valve-a?s=10` | GET | Test valve A + pump for N seconds |
| `/test-valve-b?s=10` | GET | Test valve B + pump for N seconds |
| `/test-valve-c?s=10` | GET | Test valve C + pump for N seconds |

### ESP32 #2 — Vision Camera

**Board:** ESP32-S3-EYE (with PSRAM + OV2640 camera)
**Firmware:** `iot_devices/vision/vision.ino`

**Camera Settings:**
- Resolution: 1600x1200 (UXGA)
- JPEG quality: 6 (high quality with PSRAM)
- Contrast: +1, Sharpness: +2, Brightness: +1
- Auto exposure with advanced AEC

**Features:**
- Scheduled photo upload every 30 minutes
- On-demand capture via `capture-command.json` blob polling (every 5s)
- Timestamped photos: `YYYY-MM-DD_HH-MM-SS.jpg`
- `latest.jpg` always updated
- SAS URL generation for 24-hour image links
- NVS persistence for capture request IDs
- WiFi reconnection on disconnect
- Watchdog: auto-reboot every 6 hours or if no upload for 45 minutes
- OTA update support (hostname: `esp32-vision`)

### Smart Plugs

| Device | IP Address | Purpose | Protocol |
|--------|-----------|---------|----------|
| KP401 | 10.0.0.182 | Grow light power (on/off) | Kasa TCP:9999 |
| KP405 | 10.0.0.169 | Fan power + speed (dimmer) | Kasa TCP:9999 |

### Humidifier

**Device:** Levoit LV600S (model LUH-A602S-WUS)
**Control:** VeSync cloud API via `pyvesync` Python library
**Capabilities:** On/off, mist level (1-9), auto mode with target humidity (30-80%), warm mist, humidity sensor readout
**Conservative policy:** Only activate below 40% humidity, target 50%, never above 60% (electronics safety)

---

## Azure Blob Storage

**Account:** `a2astoragefilesa2a`
**Container:** `garden-images`
**Auth:** Shared Key (HMAC-SHA256) for ESP32, DefaultAzureCredential for agent

| Blob | Purpose | Read by | Written by |
|------|---------|---------|------------|
| `latest.jpg` | Most recent garden photo | Agent | Vision ESP32 |
| `YYYY-MM-DD_HH-MM-SS.jpg` | Timestamped photo archive | Agent | Vision ESP32 |
| `irrigation-command.json` | Irrigation trigger + duration | Irrigation ESP32 | Agent |
| `valve-command.json` | Valve selection + pump + duration | Irrigation ESP32 | Agent |
| `capture-command.json` | On-demand photo capture trigger | Vision ESP32 | Agent |
| `moisture-data.json` | Moisture + temp + 48hr history | Agent | Irrigation ESP32 |
| `light-schedule.json` | Sunrise/sunset/brightness schedule | Irrigation ESP32 | Agent |
| `fan-command.json` | Fan on/off + speed + duration | Irrigation ESP32 | Agent |
| `garden-log-{user_id}.json` | Per-user agent activity memory | Agent | Agent |

### Command Blob Formats

**irrigation-command.json:**
```json
{"request_id": "abc12345", "irrigate": true, "duration_ms": 120000}
```

**valve-command.json:**
```json
{"request_id": "abc12345", "valve": "b", "duration_seconds": 120}
```

**light-schedule.json:**
```json
{
    "request_id": "abc12345",
    "sunrise_hour": 5,
    "sunrise_ramp_min": 90,
    "peak_brightness": 100,
    "sunset_hour": 20,
    "sunset_ramp_min": 90,
    "night_brightness": 0
}
```

**fan-command.json:**
```json
{"request_id": "abc12345", "state": true, "speed": 50, "duration_min": 30}
```

**capture-command.json:**
```json
{"request_id": "abc12345", "capture": true}
```

**moisture-data.json:**
```json
{
    "current": {
        "raw": 85,
        "pct": 64,
        "temp_c": 22.1,
        "timestamp": "2026-04-25T14:30:00Z",
        "irrigating": false
    },
    "readings": [
        {"ts": "2026-04-25T14:25:00Z", "raw": 83, "pct": 61},
        {"ts": "2026-04-25T14:30:00Z", "raw": 85, "pct": 64}
    ]
}
```

**garden-log-{user_id}.json:**
```json
{
    "entries": [
        {
            "timestamp": "2026-04-25T14:30:00Z",
            "summary": "Moisture 64%, temp 22.1°C. Plants in vegetative stage. Irrigated with Grow nutrients (valve B) for 2 minutes. Fan at 50%."
        }
    ]
}
```

---

## Garden Autopilot Workflow

**Schedule:** Every 3 hours
**Workflow ID:** `garden-autopilot`
**Timeout:** 300 seconds

**Step 1 — Home Gardening Agent:**
> Check my garden. Take a photo, read soil moisture and temperature, and check room humidity. Based on what you see and the sensor data: irrigate ONLY if moisture is below 5% (the sensor can be noisy, so only water when it is clearly very dry). Use the appropriate valve — valve B (Grow 2-1-6) during vegetative growth, valve C (Bloom 0-5-1) during flowering, or valve A (plain water) for flushing. Alternate between nutrient feeds and plain water flushes. Adjust the light schedule based on plant growth stage. Set fan speed based on temperature (high temp = faster fan). Turn on humidifier only if humidity is below 40% (target 50%). If temperature is above 30°C, ensure fan is on. Provide a brief summary including temperature.

**Step 2 — Text Message Agent:**
> Send a text message to 514-771-5943 with a brief summary of the garden status from the previous step. Include moisture, temperature, humidity, actions taken (including which valve/nutrient was used if irrigated), and plant health.

---

## Network

| Device | IP | Port | Protocol |
|--------|----|------|----------|
| KP401 (grow light) | 10.0.0.182 | 9999 | Kasa TCP |
| KP405 (fan+dimmer) | 10.0.0.169 | 9999 | Kasa TCP |
| Irrigation ESP32 | 10.0.0.107 | 80 | HTTP (web UI) |
| Vision ESP32 | DHCP | N/A | Azure Blob only |

---

## Files

```
iot_devices/
  irrigation/
    irrigation.ino          # Main controller firmware (moisture, temp, light, fan, valves)
    test_irrigate.py        # Test script for irrigation commands
  vision/
    vision.ino              # Camera device firmware
    app_httpd.cpp           # Camera web server handler
  SMART_GARDEN_SETUP.md     # This file

remote_agents/
  azurefoundry_gardening/
    foundry_agent.py        # Gardening agent (13 tools, vision, memory)
    foundry_agent_executor.py # A2A executor wrapper
    __main__.py             # Skills + A2A server setup
    pyproject.toml          # Dependencies (opencv, pyvesync, etc.)
    Dockerfile              # Container (includes ffmpeg)
    utils/
      self_registration.py  # Auto-register with host agent
```

---

## Troubleshooting

### Moisture Sensor Reads 0% When Soil is Wet
- **WiFi ADC noise:** ~50% of ADC reads return 0 during WiFi TX. The firmware filters these out (readings ≤5 discarded). If still bad, check that the filter is working in serial output.
- **Loose GND:** Multiple devices sharing one GND pin must be soldered together. Loose connections cause erratic readings.
- **ADC baseline drift:** Different power sources shift the baseline. Calibrate on the same power source the device will run on (wall adapter, not laptop USB).
- **Sensor dead:** Capacitive v1.2 sensors fail after extended wet soil exposure. Test: unplug data wire → should read ~2000+ (floating). Plug back in → should read 30-110. If no change, sensor is dead.

### Lights Turn Off Unexpectedly
- **Schedule:** Check if it's past sunset (8 PM Eastern). The schedule turns off lights at night.
- **Kasa failure:** If the KP401 on/off command fails, `currentBrightness` resets to -1 and retries next cycle (60s). The 5-minute safety re-send also helps.
- **Dimmer wires:** The MOSFET module connections are fragile. Ensure DIM+/DIM- wires are firmly connected (solder if possible).

### Pump Doesn't Pull Water Through Valves
- **Air leaks:** Check all T-connector and valve tubing connections. Suck on the pump end — you should feel resistance, not air.
- **Tubing too long:** Keep runs under 12 inches. Loops trap air.
- **Prime the lines:** Fill tubes with water manually before first use.

### ESP32 Won't Connect to WiFi
- After flashing, the radio sometimes needs a full power cycle. Unplug and replug.
- Check serial output for WiFi connection status.

### Agent Not Responding to Garden Queries
- Check agent health: `curl https://azurefoundry-gardening.ambitioussky-6c709152.westus2.azurecontainerapps.io/health`
- Check logs: `az containerapp logs show --name azurefoundry-gardening --resource-group rg-a2a-prod --tail 100`
- Agent needs 2-3 minutes after deployment for RBAC permissions to propagate.
