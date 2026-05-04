"""Quick test: send the gardening agent system prompt to GPT-4o and see what tool calls it makes."""
import json, datetime
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential

system_prompt = """You are an autonomous gardening agent that manages a grow room via IoT sensors and controls. You run on a schedule without human input.

## YOUR #1 JOB (read this first)
You are a professional gardener. The Garden Description tells you what was planted and when — it may be minimal (e.g. "planted basil seeds"). That is enough. You are the expert. Determine the growth stage from the planting date and the camera image, then set all controls to match.

**What each growth stage needs:**
- **Germination** → low light (peak_brightness 10-20), high humidity (70-80%), warm temps, minimal air disturbance, no irrigation unless bone dry
- **Seedling** → moderate light (40-60%), humidity 60-70%, gentle air circulation
- **Vegetative** → full light (80-100%), humidity 50-60%, good airflow
- **Flowering/Fruiting** → strong light, humidity 40-50%, strong airflow

**Every run, do this:**
1. Take a photo, read sensors (weight, temp, humidity), read current light schedule
2. Determine growth stage → decide correct settings
3. Call ALL THREE: `control_lights`, `control_fan`, `control_humidifier` — EVERY RUN, no exceptions
4. Call `irrigate_garden` only if pot weight shows below 20% water AND growth stage allows it
5. Report what you did

A run where you skip calling the three control tools is a FAILED run.

## Capabilities
- **Irrigation Control**: Base watering on pot WEIGHT (not moisture sensor).
- **Grow Light Control**: Adjust light schedule (sunrise/sunset, ramp, peak brightness 0-100).
- **Fan Control**: On/off, speed, duration.
- **Humidity Control**: Read/control Levoit humidifier.

Current date/time: """ + datetime.datetime.now().astimezone().isoformat() + """

## Garden Description (from the user)
GERMINATION MODE (planted May 4, 2026). Seeds just planted. DO NOT auto-irrigate — irrigation is manual only while we calibrate dry weights over the next few days. Monitor weight trends but do not trigger any irrigation. Keep humidity 50-60% via humidifier. Report observations only."""

tools = [
    {"type": "function", "function": {"name": "capture_fresh_photo", "description": "Take a photo of the garden", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_moisture_data", "description": "Read sensor data including weight, moisture, temperature", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "control_lights", "description": "Set or get grow light schedule", "parameters": {"type": "object", "properties": {"sunrise_hour": {"type": "integer"}, "sunrise_ramp_min": {"type": "integer"}, "peak_brightness": {"type": "integer", "description": "0-100 percent"}, "sunset_hour": {"type": "integer"}, "sunset_ramp_min": {"type": "integer"}, "night_brightness": {"type": "integer"}, "action": {"type": "string", "enum": ["set_schedule", "get_schedule"]}}}}},
    {"type": "function", "function": {"name": "control_fan", "description": "Control grow room fan", "parameters": {"type": "object", "properties": {"state": {"type": "boolean"}, "speed": {"type": "integer", "description": "0-100"}, "duration_min": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "control_humidifier", "description": "Control the Levoit humidifier", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["on", "off", "status", "set_target"]}, "target_humidity": {"type": "integer"}, "mist_level": {"type": "integer", "description": "1-9"}}}}},
    {"type": "function", "function": {"name": "get_temperature", "description": "Read temperature from sensor", "parameters": {"type": "object", "properties": {}}}},
]

cred = DefaultAzureCredential()
token = cred.get_token("https://cognitiveservices.azure.com/.default").token
client = AzureOpenAI(
    azure_endpoint="https://simonfoundry.services.ai.azure.com",
    api_version="2024-12-01-preview",
    azure_ad_token=token,
)

# === ROUND 1: Initial check-in ===
print("=" * 60)
print("ROUND 1: Scheduled check-in (no sensor data yet)")
print("=" * 60)
messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": "Scheduled garden check-in. Analyze the garden and take action."}
]
r1 = client.chat.completions.create(model="gpt-4o", messages=messages, tools=tools, tool_choice="auto", max_tokens=800)
msg1 = r1.choices[0].message
print(f"Finish: {r1.choices[0].finish_reason}")
if msg1.tool_calls:
    print(f"Tool calls ({len(msg1.tool_calls)}):")
    for tc in msg1.tool_calls:
        print(f"  → {tc.function.name}({tc.function.arguments})")
if msg1.content:
    print(f"Text: {msg1.content[:300]}")

# === ROUND 2: Simulate tool responses ===
if msg1.tool_calls:
    print("\n" + "=" * 60)
    print("ROUND 2: After receiving sensor data")
    print("=" * 60)
    
    messages.append(msg1)
    
    fake_responses = {
        "capture_fresh_photo": '{"status": "ok", "image": "garden_photo.jpg", "description": "Two pots with soil visible, no sprouts yet. Grow light is on at medium brightness. Room looks warm."}',
        "get_moisture_data": '{"weight_g": 1980.5, "weight2_g": 1890.2, "moisture": 650, "temperature_c": 23.4, "humidity": 57}',
        "get_temperature": '{"temperature_c": 23.4, "humidity": 57}',
        "control_lights": '{"status": "ok", "current_schedule": {"sunrise_hour": 5, "sunrise_ramp_min": 90, "peak_brightness": 100, "sunset_hour": 20, "sunset_ramp_min": 90, "night_brightness": 0}}',
        "control_fan": '{"status": "ok", "state": false, "speed": 0}',
        "control_humidifier": '{"status": "ok", "humidity": 57, "target_humidity": 50, "mist_level": 3, "on": true, "water_lacks": false}',
    }
    
    for tc in msg1.tool_calls:
        resp = fake_responses.get(tc.function.name, '{"status": "ok"}')
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": resp})
    
    r2 = client.chat.completions.create(model="gpt-4o", messages=messages, tools=tools, tool_choice="auto", max_tokens=800)
    msg2 = r2.choices[0].message
    print(f"Finish: {r2.choices[0].finish_reason}")
    if msg2.tool_calls:
        print(f"Tool calls ({len(msg2.tool_calls)}):")
        for tc in msg2.tool_calls:
            print(f"  → {tc.function.name}({tc.function.arguments})")
    if msg2.content:
        print(f"\nAgent response:\n{msg2.content[:800]}")
    
    # === ROUND 3 if needed ===
    if msg2.tool_calls:
        print("\n" + "=" * 60)
        print("ROUND 3: After control tool responses")
        print("=" * 60)
        messages.append(msg2)
        for tc in msg2.tool_calls:
            resp = fake_responses.get(tc.function.name, '{"status": "ok", "applied": true}')
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": resp})
        
        r3 = client.chat.completions.create(model="gpt-4o", messages=messages, tools=tools, tool_choice="auto", max_tokens=800)
        msg3 = r3.choices[0].message
        print(f"Finish: {r3.choices[0].finish_reason}")
        if msg3.tool_calls:
            print(f"Tool calls ({len(msg3.tool_calls)}):")
            for tc in msg3.tool_calls:
                print(f"  → {tc.function.name}({tc.function.arguments})")
        if msg3.content:
            print(f"\nAgent response:\n{msg3.content[:800]}")
