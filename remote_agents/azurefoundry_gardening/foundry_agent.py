"""
AI Foundry Home Gardening Agent.
Uses the Responses API with vision to analyze garden images from IoT cameras.
Fetches latest image from IoT blob storage, uploads to host blob storage,
analyzes with GPT-4o vision, and returns image + analysis as A2A artifacts.
"""
import os
import re
import json
import time
import uuid
import base64
import datetime
import asyncio
import logging
from typing import Optional, Dict, List, Any
from datetime import timedelta

from openai import AsyncAzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.storage.blob import (
    BlobServiceClient,
    BlobSasPermissions,
    generate_blob_sas,
)

from azure.storage.blob import ContentSettings

logger = logging.getLogger(__name__)

def _env(key: str, default: str = "") -> str:
    """Read env var lazily (after load_dotenv has run)."""
    return os.getenv(key, default)


MAX_VISION_IMAGES = 8
IRRIGATION_BLOB_NAME = "irrigation-command.json"
CAPTURE_CMD_BLOB_NAME = "capture-command.json"
CAPTURE_WAIT_TIMEOUT = 30  # seconds to wait for fresh capture
CAPTURE_POLL_INTERVAL = 2  # seconds between checks
MOISTURE_BLOB_NAME = "moisture-data.json"
LIGHT_SCHEDULE_BLOB_NAME = "light-schedule.json"
FAN_COMMAND_BLOB_NAME = "fan-command.json"
DEFAULT_LIGHT_SCHEDULE = {
    "sunrise_hour": 6,
    "sunrise_ramp_min": 30,
    "peak_brightness": 100,
    "sunset_hour": 20,
    "sunset_ramp_min": 30,
    "night_brightness": 0,
}


class FoundryGardeningAgent:
    """AI Foundry Agent for home garden monitoring and advice via Responses API."""

    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self._client: Optional[AsyncAzureOpenAI] = None
        self._initialized = False
        self._response_ids: Dict[str, str] = {}
        self.last_token_usage: Optional[Dict[str, int]] = None
        self._latest_artifacts: List[Dict[str, Any]] = []

        # Blob clients (lazy)
        self._iot_blob_client: Optional[BlobServiceClient] = None
        self._host_blob_client: Optional[BlobServiceClient] = None

    # ── OpenAI client ───────────────────────────────────────────────────
    def _get_client(self) -> AsyncAzureOpenAI:
        if self._client is None:
            if "services.ai.azure.com" in self.endpoint:
                resource_name = self.endpoint.split("//")[1].split(".")[0]
                openai_endpoint = f"https://{resource_name}.openai.azure.com/openai/v1/"
            else:
                openai_endpoint = (
                    self.endpoint
                    if self.endpoint.endswith("/openai/v1/")
                    else f"{self.endpoint.rstrip('/')}/openai/v1/"
                )
            token_provider = get_bearer_token_provider(
                self.credential, "https://cognitiveservices.azure.com/.default",
            )
            self._client = AsyncAzureOpenAI(
                base_url=openai_endpoint,
                azure_ad_token_provider=token_provider,
                api_version="preview",
            )
        return self._client

    # ── Blob helpers ────────────────────────────────────────────────────
    def _get_iot_blob_client(self) -> BlobServiceClient:
        if self._iot_blob_client is None:
            conn = _env("IOT_BLOB_CONNECTION_STRING")
            if not conn or "placeholder" in conn or "YOUR_KEY_HERE" in conn:
                raise RuntimeError("IOT_BLOB_CONNECTION_STRING not configured")
            self._iot_blob_client = BlobServiceClient.from_connection_string(
                conn, api_version="2023-11-03"
            )
        return self._iot_blob_client

    def _get_host_blob_client(self) -> Optional[BlobServiceClient]:
        if self._host_blob_client is None:
            conn = _env("AZURE_STORAGE_CONNECTION_STRING")
            if not conn:
                logger.warning("AZURE_STORAGE_CONNECTION_STRING not set — artifacts will use IoT SAS URLs")
                return None
            self._host_blob_client = BlobServiceClient.from_connection_string(
                conn, api_version="2023-11-03"
            )
        return self._host_blob_client

    def _fetch_iot_image(self) -> bytes:
        """Download the latest garden image from the IoT blob storage."""
        client = self._get_iot_blob_client()
        container = _env("IOT_BLOB_CONTAINER", "garden-images")
        blob_name = _env("IOT_BLOB_NAME", "latest.jpg")
        blob = client.get_blob_client(container=container, blob=blob_name)
        logger.info(f"Downloading IoT image: {container}/{blob_name}")
        return blob.download_blob().readall()

    def _fetch_iot_image_by_name(self, blob_name: str) -> bytes:
        """Download a specific garden image by blob name."""
        client = self._get_iot_blob_client()
        container = _env("IOT_BLOB_CONTAINER", "garden-images")
        blob = client.get_blob_client(container=container, blob=blob_name)
        logger.info(f"Downloading IoT image: {container}/{blob_name}")
        return blob.download_blob().readall()

    def _list_iot_images(self) -> List[Dict[str, Any]]:
        """List all timestamped garden images from IoT blob storage.
        Returns list of dicts with 'name', 'last_modified', 'size' sorted newest first.
        Expected naming: YYYY-MM-DD_HH-MM-SS.jpg
        """
        client = self._get_iot_blob_client()
        container = _env("IOT_BLOB_CONTAINER", "garden-images")
        container_client = client.get_container_client(container)

        pattern = re.compile(r'^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.(jpg|jpeg|png)$')
        images = []
        for blob in container_client.list_blobs():
            if pattern.match(blob.name):
                images.append({
                    'name': blob.name,
                    'last_modified': blob.last_modified,
                    'size': blob.size,
                })

        # Sort by name descending (YYYY-MM-DD format is naturally sortable)
        images.sort(key=lambda x: x['name'], reverse=True)
        return images

    def _upload_to_host_blob(self, image_bytes: bytes, file_name: str, context_id: str = "") -> Optional[str]:
        """Upload image to the host blob storage and return a SAS-signed URL."""
        client = self._host_blob_client or self._get_host_blob_client()
        if client is None:
            # Fallback: generate SAS URL directly from IoT storage
            return self._generate_iot_sas_url()

        file_id = str(uuid.uuid4())[:8]
        if context_id and "::" in context_id:
            session_id = context_id.split("::")[0]
            blob_name = f"uploads/{session_id}/{file_id}/{file_name}"
        else:
            blob_name = f"gardening-agent/{file_id}/{file_name}"

        host_container = _env("AZURE_BLOB_CONTAINER", "a2a-files")
        container_client = client.get_container_client(host_container)
        try:
            if not container_client.exists():
                container_client.create_container()
        except Exception:
            pass  # container may already exist

        container_client.upload_blob(name=blob_name, data=image_bytes, overwrite=True)
        logger.info(f"Uploaded garden image to host blob: {host_container}/{blob_name}")

        # Generate SAS URL
        return self._generate_sas_url(client, host_container, blob_name)

    def _generate_sas_url(self, service_client: BlobServiceClient, container: str, blob_name: str) -> Optional[str]:
        """Generate a SAS-signed URL for a blob."""
        try:
            # Try shared key first
            account_key = None
            conn = _env("AZURE_STORAGE_CONNECTION_STRING")
            for part in conn.split(";"):
                if part.startswith("AccountKey="):
                    account_key = part[len("AccountKey="):]
                    break

            if account_key:
                sas_token = generate_blob_sas(
                    account_name=service_client.account_name,
                    container_name=container,
                    blob_name=blob_name,
                    account_key=account_key,
                    permission=BlobSasPermissions(read=True),
                    expiry=datetime.datetime.utcnow() + timedelta(minutes=int(_env("AZURE_BLOB_SAS_DURATION_MINUTES", "1440"))),
                    protocol="https",
                    version="2023-11-03",
                )
            else:
                # Fallback to user delegation key
                delegation_key = service_client.get_user_delegation_key(
                    key_start_time=datetime.datetime.utcnow() - timedelta(minutes=5),
                    key_expiry_time=datetime.datetime.utcnow() + timedelta(minutes=int(_env("AZURE_BLOB_SAS_DURATION_MINUTES", "1440"))),
                )
                sas_token = generate_blob_sas(
                    account_name=service_client.account_name,
                    container_name=container,
                    blob_name=blob_name,
                    user_delegation_key=delegation_key,
                    permission=BlobSasPermissions(read=True),
                    expiry=datetime.datetime.utcnow() + timedelta(minutes=int(_env("AZURE_BLOB_SAS_DURATION_MINUTES", "1440"))),
                    version="2023-11-03",
                )

            base_url = service_client.get_blob_client(container=container, blob=blob_name).url
            token = sas_token.lstrip("?")
            separator = "&" if "?" in base_url else "?"
            return f"{base_url}{separator}{token}"
        except Exception as e:
            logger.error(f"Failed to generate SAS URL: {e}")
            return None

    def _generate_iot_sas_url(self) -> Optional[str]:
        """Generate a SAS URL directly from the IoT blob storage as fallback."""
        try:
            client = self._get_iot_blob_client()
            return self._generate_sas_url_from_conn(
                client, _env("IOT_BLOB_CONNECTION_STRING"),
                _env("IOT_BLOB_CONTAINER", "garden-images"),
                _env("IOT_BLOB_NAME", "latest.jpg"),
            )
        except Exception as e:
            logger.error(f"Failed to generate IoT SAS URL: {e}")
            return None

    def _generate_sas_url_from_conn(self, service_client: BlobServiceClient, conn_string: str, container: str, blob_name: str) -> Optional[str]:
        """Generate SAS URL using a connection string for the account key."""
        account_key = None
        for part in conn_string.split(";"):
            if part.startswith("AccountKey="):
                account_key = part[len("AccountKey="):]
                break
        if not account_key:
            return None

        sas_token = generate_blob_sas(
            account_name=service_client.account_name,
            container_name=container,
            blob_name=blob_name,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.datetime.utcnow() + timedelta(minutes=int(_env("AZURE_BLOB_SAS_DURATION_MINUTES", "1440"))),
            protocol="https",
            version="2023-11-03",
        )
        base_url = service_client.get_blob_client(container=container, blob=blob_name).url
        token = sas_token.lstrip("?")
        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}{token}"

    # ── Irrigation control ────────────────────────────────────────────────
    DEFAULT_IRRIGATION_MS = 120000  # 2 minutes

    def _parse_irrigation_duration(self, message: str) -> int:
        """Parse a duration from the user message. Returns milliseconds.
        Examples: 'water for 30 seconds', 'irrigate for 5 minutes', 'water 1 min'
        Falls back to DEFAULT_IRRIGATION_MS (2 minutes) if no duration found.
        """
        msg = message.lower()
        # Match patterns like "30 seconds", "2 minutes", "1 min", "90 sec", "30s"
        match = re.search(r'(\d+)\s*(seconds?|secs?|s\b|minutes?|mins?|m\b)', msg)
        if not match:
            return self.DEFAULT_IRRIGATION_MS

        value = int(match.group(1))
        unit = match.group(2)

        if unit.startswith('m'):
            ms = value * 60000
        else:
            ms = value * 1000

        # Clamp: min 1 second, max 10 minutes
        return max(1000, min(ms, 600000))

    def _format_duration(self, ms: int) -> str:
        """Format milliseconds as a human-readable string."""
        if ms >= 60000:
            mins = ms // 60000
            secs = (ms % 60000) // 1000
            if secs:
                return f"{mins} minute{'s' if mins > 1 else ''} {secs} seconds"
            return f"{mins} minute{'s' if mins > 1 else ''}"
        return f"{ms // 1000} seconds"

    def _trigger_irrigation(self, duration_ms: int = None) -> tuple:
        """Write an irrigate command to the IoT blob storage.
        Returns (request_id, duration_ms) on success.
        """
        if duration_ms is None:
            duration_ms = self.DEFAULT_IRRIGATION_MS

        client = self._get_iot_blob_client()
        container = _env("IOT_BLOB_CONTAINER", "garden-images")
        blob = client.get_blob_client(container=container, blob=IRRIGATION_BLOB_NAME)

        request_id = uuid.uuid4().hex[:8]
        command = json.dumps({
            "request_id": request_id,
            "irrigate": True,
            "duration_ms": duration_ms,
        })
        blob.upload_blob(
            command,
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json"),
        )
        logger.info(f"Irrigation command sent: {request_id}, duration: {duration_ms}ms")
        return request_id, duration_ms

    # ── On-demand capture control ────────────────────────────────────────
    def _get_latest_image_modified(self) -> Optional[datetime.datetime]:
        """Get the last_modified timestamp of latest.jpg."""
        try:
            client = self._get_iot_blob_client()
            container = _env("IOT_BLOB_CONTAINER", "garden-images")
            blob_name = _env("IOT_BLOB_NAME", "latest.jpg")
            blob = client.get_blob_client(container=container, blob=blob_name)
            props = blob.get_blob_properties()
            return props.last_modified
        except Exception as e:
            logger.warning(f"Failed to get latest.jpg metadata: {e}")
            return None

    def _trigger_capture(self) -> str:
        """Write a capture command to the IoT blob storage.
        The ESP32 vision device polls this blob and captures immediately.
        Returns the request_id.
        """
        client = self._get_iot_blob_client()
        container = _env("IOT_BLOB_CONTAINER", "garden-images")
        blob = client.get_blob_client(container=container, blob=CAPTURE_CMD_BLOB_NAME)

        request_id = uuid.uuid4().hex[:8]
        command = json.dumps({"request_id": request_id, "capture": True})
        blob.upload_blob(
            command,
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json"),
        )
        logger.info(f"Capture command sent: {request_id}")
        return request_id

    async def _trigger_and_wait_for_capture(self) -> bool:
        """Trigger an on-demand capture and wait for latest.jpg to update.
        Returns True if a fresh image was captured, False on timeout.
        """
        # Record current timestamp of latest.jpg before triggering
        before_modified = await asyncio.to_thread(self._get_latest_image_modified)

        # Send capture command
        request_id = await asyncio.to_thread(self._trigger_capture)
        logger.info(f"Waiting for fresh capture (request: {request_id})...")

        # Poll until latest.jpg is newer or timeout
        elapsed = 0
        while elapsed < CAPTURE_WAIT_TIMEOUT:
            await asyncio.sleep(CAPTURE_POLL_INTERVAL)
            elapsed += CAPTURE_POLL_INTERVAL

            current_modified = await asyncio.to_thread(self._get_latest_image_modified)
            if current_modified and before_modified and current_modified > before_modified:
                logger.info(f"Fresh capture detected after {elapsed}s")
                return True
            elif current_modified and not before_modified:
                # latest.jpg didn't exist before but does now
                return True

        logger.warning(f"Capture timeout after {CAPTURE_WAIT_TIMEOUT}s, using existing image")
        return False

    # ── Moisture data ───────────────────────────────────────────────────
    def _fetch_moisture_data(self) -> dict:
        """Download moisture-data.json from IoT blob storage."""
        client = self._get_iot_blob_client()
        container = _env("IOT_BLOB_CONTAINER", "garden-images")
        blob = client.get_blob_client(container=container, blob=MOISTURE_BLOB_NAME)
        try:
            data = blob.download_blob().readall()
            return json.loads(data)
        except Exception as e:
            logger.warning(f"Failed to fetch moisture data: {e}")
            return None

    # ── Light schedule ─────────────────────────────────────────────────
    def _fetch_light_schedule(self) -> dict:
        """Download light-schedule.json from IoT blob storage."""
        client = self._get_iot_blob_client()
        container = _env("IOT_BLOB_CONTAINER", "garden-images")
        blob = client.get_blob_client(container=container, blob=LIGHT_SCHEDULE_BLOB_NAME)
        try:
            data = blob.download_blob().readall()
            return json.loads(data)
        except Exception:
            return None

    def _update_light_schedule(self, params: dict) -> tuple:
        """Read current schedule, merge with params, write back. Returns (request_id, schedule)."""
        # Read current schedule or use defaults
        current = self._fetch_light_schedule()
        if not current:
            current = dict(DEFAULT_LIGHT_SCHEDULE)

        # Merge — only update provided params
        for key in DEFAULT_LIGHT_SCHEDULE:
            if key in params:
                current[key] = params[key]

        # Write with new request_id
        request_id = uuid.uuid4().hex[:8]
        current["request_id"] = request_id

        client = self._get_iot_blob_client()
        container = _env("IOT_BLOB_CONTAINER", "garden-images")
        blob = client.get_blob_client(container=container, blob=LIGHT_SCHEDULE_BLOB_NAME)
        blob.upload_blob(
            json.dumps(current),
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json"),
        )
        logger.info(f"Light schedule updated: {request_id}")
        return request_id, current

    # ── Fan control ────────────────────────────────────────────────────
    def _update_fan_command(self, state: bool, duration_min: int = 0) -> str:
        """Write fan command to IoT blob. Returns request_id."""
        request_id = uuid.uuid4().hex[:8]
        command = {"request_id": request_id, "state": state}
        if duration_min > 0:
            command["duration_min"] = duration_min

        client = self._get_iot_blob_client()
        container = _env("IOT_BLOB_CONTAINER", "garden-images")
        blob = client.get_blob_client(container=container, blob=FAN_COMMAND_BLOB_NAME)
        blob.upload_blob(
            json.dumps(command),
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json"),
        )
        logger.info(f"Fan command sent: {request_id} state={state} duration={duration_min}min")
        return request_id

    # ── Artifact management ─────────────────────────────────────────────
    def pop_latest_artifacts(self) -> List[Dict[str, Any]]:
        """Return and clear accumulated artifacts (called by executor)."""
        artifacts = list(self._latest_artifacts)
        self._latest_artifacts.clear()
        return artifacts

    def _select_images_in_range(self, date_from: str, date_to: str, available_images: List[Dict[str, Any]]) -> List[str]:
        """Filter images to date range — pick 1 per day (closest to midday) up to MAX_VISION_IMAGES."""
        candidates = [
            img['name'] for img in available_images
            if img['name'][:10] >= date_from and img['name'][:10] <= date_to
        ]
        candidates.sort()  # chronological (oldest first)

        if not candidates:
            return []

        # Group by date and pick the image closest to midday (12:00) for each day
        by_day: Dict[str, List[str]] = {}
        for name in candidates:
            day = name[:10]  # e.g., "2026-03-18"
            by_day.setdefault(day, []).append(name)

        selected = []
        for day in sorted(by_day.keys()):
            day_images = by_day[day]
            # Pick image closest to midday by comparing time portion
            best = min(day_images, key=lambda n: abs(
                int(n[11:13]) * 60 + int(n[14:16]) - 720  # minutes from midnight, target 720 (noon)
            ) if len(n) > 16 and n[11:13].isdigit() else 720)
            selected.append(best)

        # If still too many days, evenly sample
        if len(selected) > MAX_VISION_IMAGES:
            step = len(selected) / MAX_VISION_IMAGES
            selected = [selected[int(i * step)] for i in range(MAX_VISION_IMAGES)]

        return selected

    # ── Agent lifecycle ─────────────────────────────────────────────────
    async def create_agent(self) -> None:
        if self._initialized:
            return
        logger.info("Initializing Gardening agent (Responses API with vision)...")
        self._get_client()
        self._initialized = True
        logger.info("Gardening agent initialized successfully")

    async def create_session(self) -> str:
        return f"session_{int(time.time())}_{os.urandom(4).hex()}"

    def _track_usage(self, resp):
        """Extract token usage from a response object."""
        usage = getattr(resp, "usage", None)
        if usage:
            self.last_token_usage = {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) or getattr(usage, "input_tokens", 0),
                "completion_tokens": getattr(usage, "completion_tokens", 0) or getattr(usage, "output_tokens", 0),
                "total_tokens": getattr(usage, "total_tokens", 0),
            }
        resp_id = getattr(resp, "id", None)
        if resp_id:
            # Store for conversation continuity but we don't have session_id here
            pass

    def _get_agent_instructions(self, vision_mode: bool = False, num_images: int = 1) -> str:
        if vision_mode:
            multi = ""
            if num_images > 1:
                multi = f"\nYou are viewing {num_images} garden images in chronological order. Each is labeled with its timestamp. Reference dates when describing what you see."
            return f"""You are a home gardening expert with access to garden camera images.{multi}
Analyze for plant health, growth stage, pest issues, and soil conditions.
Give friendly, practical advice. Be specific about what you observe.
If the image is completely dark/black, it is likely nighttime — say so and do NOT request another photo.
Current date/time: {datetime.datetime.now().astimezone().isoformat()}"""
        return f"""You are a home gardening expert assistant with access to a live garden camera.

You help the user monitor and care for their garden by analyzing real-time images from their IoT camera.

## Capabilities
- **Garden Health Analysis**: Analyze garden images for plant health, growth stage, pest issues, disease signs, and soil conditions.
- **Watering Recommendations**: Based on visual analysis, advise when and how much to water.
- **Irrigation Control**: You can trigger the IoT irrigation system. Default watering time is 2 minutes. The user can specify a custom duration (e.g., "water for 30 seconds", "irrigate for 5 minutes"). If irrigation was already triggered, confirm it and explain they can request more if needed.
- **Soil Moisture Monitoring**: You can read the soil moisture sensor to check current moisture levels and recent trends. Use this data to advise whether watering is needed. Below 20% is dry and needs water, 20-50% is good, above 50% is very moist.
- **Grow Light Control**: You can adjust the grow light schedule that runs autonomously on the IoT device. The schedule simulates natural sunlight with configurable sunrise/sunset times, ramp durations, and peak brightness. Adapt the schedule based on plant growth stage: seedlings need 14-16h light, vegetative growth 14-16h at full brightness, flowering plants need shorter days (12h) to trigger blooming. The lights continue following the schedule even if the internet goes down.
- **Fan Control**: You can turn the grow room fan on/off for air circulation, ventilation, and humidity/temperature control. Use it when you see signs of high humidity (condensation, mold risk), when the air looks stagnant, or to cool plants during peak light hours. Can be set to run for a specific duration then auto-off.
- **Pest & Disease Identification**: Identify visible pests, fungal infections, nutrient deficiencies, and other issues.
- **Seasonal Advice**: Provide planting schedules, pruning tips, fertilization recommendations based on what you see.
- **General Gardening Knowledge**: Answer any gardening questions — composting, soil amendments, companion planting, etc.

## Response Style
- Be friendly and encouraging — gardening should be fun!
- Give practical, actionable advice
- If you see potential problems, explain them clearly but don't be alarmist
- **Night-time awareness**: The camera has no night vision. If it is currently nighttime (roughly 8 PM – 7 AM Eastern), snapshots will be completely dark. Do NOT retry taking photos when it's dark — instead, tell the user the image is dark because it's nighttime and suggest they try again during daylight hours or turn on a grow light first.

Current date/time: {datetime.datetime.now().astimezone().isoformat()}
"""

    # ── Tool definitions for Responses API ─────────────────────────────
    TOOLS = [
        {
            "type": "function",
            "name": "irrigate_garden",
            "description": "Trigger the IoT irrigation system to water the garden. Only call this when the user explicitly asks to water/irrigate. Default duration is 120 seconds (2 minutes). Do NOT call this for questions about watering schedules or if plants need water. IMPORTANT: Only call this tool ONCE per user request.",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration_seconds": {
                        "type": "integer",
                        "description": "Duration in seconds. Convert user's request: '2 minutes' = 120, '30 seconds' = 30, '5 minutes' = 300. If user doesn't specify, use 120.",
                    }
                },
                "required": [],
            },
        },
        {
            "type": "function",
            "name": "capture_fresh_photo",
            "description": "Request a fresh real-time photo from the garden IoT camera. Call this whenever the user wants to see their garden or needs visual analysis. Do NOT call for general gardening knowledge questions that don't need a photo (e.g. 'when to plant tomatoes').",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        {
            "type": "function",
            "name": "get_historical_images",
            "description": "Fetch historical garden images for a date range to compare growth, track changes, or see progression over time. Call this when the user asks about past images, comparisons, or trends.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format",
                    },
                },
                "required": ["date_from", "date_to"],
            },
        },
        {
            "type": "function",
            "name": "get_moisture_data",
            "description": "Read the soil moisture sensor data from the IoT device. Returns the current moisture percentage and recent history (up to 48 hours). Call this when the user asks about soil moisture, whether they should water, or moisture trends.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        {
            "type": "function",
            "name": "control_lights",
            "description": "Update the grow light schedule. The lights run autonomously on the IoT device simulating natural sunlight with sunrise/sunset ramps. You can adjust any schedule parameter. Only provide the parameters you want to change — unspecified values keep their current setting. Call this when the user wants to adjust lighting, change light hours, dim lights, or optimize light for plant growth stage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sunrise_hour": {
                        "type": "integer",
                        "description": "Hour (0-23) for sunrise to begin. Default 6.",
                    },
                    "sunrise_ramp_min": {
                        "type": "integer",
                        "description": "Minutes to ramp from night to peak brightness. Default 30.",
                    },
                    "peak_brightness": {
                        "type": "integer",
                        "description": "Maximum brightness 1-100 during daytime. Default 100.",
                    },
                    "sunset_hour": {
                        "type": "integer",
                        "description": "Hour (0-23) for sunset to begin. Default 20.",
                    },
                    "sunset_ramp_min": {
                        "type": "integer",
                        "description": "Minutes to ramp from peak to night brightness. Default 30.",
                    },
                    "night_brightness": {
                        "type": "integer",
                        "description": "Brightness during night 0-100. Default 0 (off).",
                    },
                },
                "required": [],
            },
        },
        {
            "type": "function",
            "name": "control_fan",
            "description": "Control the grow room fan for air circulation. Use for ventilation, humidity control, cooling, or preventing mold. Optionally set a duration after which the fan auto-turns off.",
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {
                        "type": "boolean",
                        "description": "true to turn fan on, false to turn off",
                    },
                    "duration_min": {
                        "type": "integer",
                        "description": "Optional minutes to run before auto-off. 0 or omitted = indefinite.",
                    },
                },
                "required": ["state"],
            },
        },
    ]

    # ── Tool execution helpers ───────────────────────────────────────────
    async def _execute_tool_call(self, tool_name: str, tool_args: dict, context_id: str = ""):
        """Execute a tool call and return (result_text, images_data).
        images_data is a list of (filename, bytes) tuples if images were fetched.
        """
        images_data: List[tuple] = []

        if tool_name == "irrigate_garden":
            duration_s = tool_args.get("duration_seconds", 120)
            duration_ms = max(1000, min(duration_s * 1000, 600000))
            duration_str = self._format_duration(duration_ms)
            try:
                request_id, duration_ms = await asyncio.to_thread(self._trigger_irrigation, duration_ms)
                return f"Irrigation activated (request: {request_id}). Garden will be watered for {duration_str}.", images_data
            except Exception as e:
                return f"Irrigation failed: {e}", images_data

        elif tool_name == "capture_fresh_photo":
            try:
                fresh = await self._trigger_and_wait_for_capture()
                if fresh:
                    img_bytes = await asyncio.to_thread(self._fetch_iot_image)
                    images_data.append(("latest.jpg", img_bytes))
                    return "Fresh photo captured and ready for analysis.", images_data
                else:
                    # Timeout — use existing image
                    img_bytes = await asyncio.to_thread(self._fetch_iot_image)
                    images_data.append(("latest.jpg", img_bytes))
                    return "Camera didn't respond in time. Using most recent image.", images_data
            except Exception as e:
                try:
                    img_bytes = await asyncio.to_thread(self._fetch_iot_image)
                    images_data.append(("latest.jpg", img_bytes))
                    return f"Could not trigger camera ({e}). Using most recent image.", images_data
                except Exception as e2:
                    return f"Failed to get garden image: {e2}", images_data

        elif tool_name == "get_historical_images":
            date_from = tool_args.get("date_from", "")
            date_to = tool_args.get("date_to", "")
            try:
                available = await asyncio.to_thread(self._list_iot_images)
                selected = self._select_images_in_range(date_from, date_to, available)
                if not selected:
                    # Fallback to latest
                    img_bytes = await asyncio.to_thread(self._fetch_iot_image)
                    images_data.append(("latest.jpg", img_bytes))
                    return f"No images found between {date_from} and {date_to}. Using latest image.", images_data
                for blob_name in selected:
                    img_bytes = await asyncio.to_thread(self._fetch_iot_image_by_name, blob_name)
                    images_data.append((blob_name, img_bytes))
                return f"Fetched {len(images_data)} historical images from {date_from} to {date_to}.", images_data
            except Exception as e:
                return f"Failed to fetch historical images: {e}", images_data

        elif tool_name == "get_moisture_data":
            try:
                data = await asyncio.to_thread(self._fetch_moisture_data)
                if not data:
                    return "Moisture sensor data not available. The sensor may not be connected or hasn't uploaded yet.", images_data
                current = data.get("current", {})
                readings = data.get("readings", [])
                pct = current.get("pct", "N/A")
                raw = current.get("raw", "N/A")
                ts = current.get("timestamp", "unknown")
                irrigating = current.get("irrigating", False)

                result = f"Current soil moisture: {pct}% (raw: {raw}) as of {ts}."
                if irrigating:
                    result += " The irrigation system is currently running."

                # Summarize recent history
                if readings:
                    recent = readings[-12:]  # last hour at 5-min intervals
                    pcts = [r.get("pct", 0) for r in recent]
                    avg = sum(pcts) / len(pcts) if pcts else 0
                    result += f" Last hour average: {avg:.0f}%. Total history entries: {len(readings)} (up to 48 hours)."

                    # Include full history as JSON for the LLM to analyze
                    result += f"\n\nFull readings data: {json.dumps(readings[-48:])}"  # last 4 hours for context

                return result, images_data
            except Exception as e:
                return f"Failed to read moisture data: {e}", images_data

        elif tool_name == "control_lights":
            try:
                request_id, schedule = await asyncio.to_thread(self._update_light_schedule, tool_args)
                sched_str = (f"Sunrise: {schedule['sunrise_hour']}:00 (ramp {schedule['sunrise_ramp_min']}min), "
                             f"Peak: {schedule['peak_brightness']}%, "
                             f"Sunset: {schedule['sunset_hour']}:00 (ramp {schedule['sunset_ramp_min']}min), "
                             f"Night: {schedule['night_brightness']}%")
                return f"Light schedule updated (request: {request_id}). Schedule: {sched_str}", images_data
            except Exception as e:
                return f"Failed to update light schedule: {e}", images_data

        elif tool_name == "control_fan":
            try:
                state = tool_args.get("state", False)
                duration_min = tool_args.get("duration_min", 0)
                request_id = await asyncio.to_thread(self._update_fan_command, state, duration_min)
                state_str = "ON" if state else "OFF"
                duration_str = f" for {duration_min} minutes" if duration_min > 0 else ""
                return f"Fan command sent (request: {request_id}). Fan turned {state_str}{duration_str}.", images_data
            except Exception as e:
                return f"Failed to control fan: {e}", images_data

        return f"Unknown tool: {tool_name}", images_data

    async def _prepare_vision_input(self, user_message: str, all_images: List[tuple], context_id: str = "") -> List[Dict[str, Any]]:
        """Build the vision input content with images uploaded to blob storage."""
        num_images = len(all_images)
        vision_parts: List[Dict[str, Any]] = [
            {"type": "input_text", "text": user_message}
        ]

        for filename, img_bytes in all_images:
            display_name = f"garden_{filename}" if filename != "latest.jpg" else f"garden_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"

            blob_url = await asyncio.to_thread(
                self._upload_to_host_blob, img_bytes, display_name, context_id
            )
            if blob_url:
                self._latest_artifacts.append({
                    "artifact-uri": blob_url,
                    "file-name": display_name,
                    "mime": "image/jpeg",
                    "storage-type": "azure_blob",
                    "status": "stored",
                    "provider": "iot-camera",
                    "local-path": "",
                    "file-size": len(img_bytes),
                })

            if filename != "latest.jpg" and num_images > 1:
                date_label = filename.replace("_", " ").replace(".jpg", "").replace(".jpeg", "").replace(".png", "")
                vision_parts.append({"type": "input_text", "text": f"[Image from {date_label}]"})

            image_b64 = base64.b64encode(img_bytes).decode("utf-8")
            image_part = {
                "type": "input_image",
                "image_url": f"data:image/jpeg;base64,{image_b64}",
            }
            if num_images > 2:
                image_part["detail"] = "low"
            vision_parts.append(image_part)

        return [{"role": "user", "content": vision_parts}]

    # ── Core conversation with multi-round tool loop ───────────────────
    async def run_conversation_stream(self, session_id: str, user_message: str, context_id: str = ""):
        """Stream a conversation using LLM tool calling with multi-round agentic loop."""
        if not self._initialized:
            await self.create_agent()

        client = self._get_client()
        model = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")
        instructions = self._get_agent_instructions(vision_mode=False) + f"\nCurrent date/time: {datetime.datetime.now().astimezone().isoformat()}"

        # Build conversation history for the loop
        conversation = [{"role": "user", "content": user_message}]
        all_images: List[tuple] = []
        max_rounds = 4  # safety limit

        yield "Analyzing your request..."

        for round_num in range(max_rounds):
            # Call LLM with tools
            response = await client.responses.create(
                model=model,
                instructions=instructions,
                input=conversation,
                tools=self.TOOLS,
                tool_choice="auto",
                max_output_tokens=1000 if round_num == 0 else 500,
            )

            # Collect tool calls and text from response
            tool_calls = []
            text_output = ""
            for item in response.output:
                if getattr(item, "type", None) == "function_call":
                    tool_calls.append(item)
                    args = item.arguments if item.arguments else "{}"
                    logger.info(f"LLM tool call (round {round_num + 1}): {item.name}({args})")
                elif getattr(item, "type", None) == "message":
                    for content in getattr(item, "content", []):
                        if getattr(content, "type", None) == "output_text":
                            text_output += content.text

            # No tool calls — LLM is done, return text response
            if not tool_calls:
                if round_num == 0 and text_output:
                    logger.info("LLM returned text response (no tools called)")
                    self._track_usage(response)
                    yield text_output
                    return
                elif text_output:
                    # Final response after tool rounds
                    break
                else:
                    break

            # Execute tool calls
            for tc in tool_calls:
                tool_name = tc.name
                try:
                    tool_args = json.loads(tc.arguments) if tc.arguments else {}
                except json.JSONDecodeError:
                    tool_args = {}

                # Status messages
                if tool_name == "irrigate_garden":
                    duration_s = tool_args.get("duration_seconds", 120)
                    yield f"Sending irrigation command ({self._format_duration(duration_s * 1000)})..."
                elif tool_name == "capture_fresh_photo":
                    yield "Requesting fresh photo from garden camera..."
                elif tool_name == "get_historical_images":
                    yield "Fetching historical images..."
                elif tool_name == "get_moisture_data":
                    yield "Reading soil moisture sensor..."
                elif tool_name == "control_lights":
                    yield "Updating light schedule..."
                elif tool_name == "control_fan":
                    yield "Sending fan command..."

                result_text, images = await self._execute_tool_call(tool_name, tool_args, context_id)
                all_images.extend(images)

                # Status updates for completed actions
                if tool_name == "irrigate_garden":
                    yield result_text
                elif tool_name == "capture_fresh_photo":
                    yield "Fresh photo captured!" if "Fresh photo" in result_text else result_text

                # Add tool call + result to conversation using Responses API format
                conversation.append({
                    "type": "function_call",
                    "call_id": tc.call_id,
                    "name": tool_name,
                    "arguments": tc.arguments or "{}",
                })
                conversation.append({
                    "type": "function_call_output",
                    "call_id": tc.call_id,
                    "output": result_text,
                })

            logger.info(f"Round {round_num + 1} complete: {len(tool_calls)} tools called, {len(all_images)} images collected")

        # Final LLM call with images (if any) for analysis/response
        num_images = len(all_images)
        if all_images:
            yield f"Uploading {num_images} image(s) for analysis..."
            input_content = await self._prepare_vision_input(user_message, all_images, context_id)
            yield f"Analyzing {num_images} garden image(s) with AI vision..."

            # Add tool results context
            tool_context = "\n".join(
                msg["output"] for msg in conversation
                if isinstance(msg, dict) and msg.get("type") == "function_call_output"
            )
            if tool_context and isinstance(input_content[0]["content"], list):
                input_content[0]["content"].insert(0, {"type": "input_text", "text": f"[Previous tool results: {tool_context}]"})
        else:
            # If we already have text_output from the last round, yield it
            if text_output:
                yield text_output
                return
            input_content = conversation  # pass full conversation

        # Stream final response
        kwargs = {
            "model": model,
            "instructions": self._get_agent_instructions(vision_mode=bool(all_images), num_images=num_images),
            "input": input_content,
            "stream": True,
            "max_output_tokens": 4000,
        }

        retry_count = 0
        max_retries = 3
        while retry_count <= max_retries:
            try:
                response = await client.responses.create(**kwargs)
                text_chunks = []

                async for event in response:
                    event_type = getattr(event, "type", None)
                    if event_type == "response.output_text.delta":
                        text_chunks.append(event.delta)
                    elif event_type == "response.failed":
                        resp = getattr(event, "response", None)
                        error_obj = getattr(resp, "error", None) if resp else None
                        yield f"Error: {getattr(error_obj, 'message', 'Unknown error') if error_obj else 'Unknown error'}"
                        return
                    elif event_type in ("response.completed", "response.done"):
                        resp = getattr(event, "response", None)
                        if resp:
                            self._track_usage(resp)

                if text_chunks:
                    yield "".join(text_chunks)
                else:
                    yield "I analyzed your garden but couldn't generate a response. Please try again."
                return

            except Exception as e:
                error_str = str(e).lower()
                if "rate_limit" in error_str or "429" in error_str or "too many requests" in error_str:
                    retry_count += 1
                    if retry_count <= max_retries:
                        backoff = min(15 * (2 ** retry_count), 60)
                        yield f"Rate limit hit - retrying in {backoff}s..."
                        await asyncio.sleep(backoff)
                        continue
                    yield f"Rate limit exceeded after {max_retries} retries"
                else:
                    yield f"Error: {e}"
                return

    async def run_conversation(self, session_id: str, user_message: str) -> str:
        return "\n".join([r async for r in self.run_conversation_stream(session_id, user_message)])

    async def chat(self, session_id: str, user_message: str) -> str:
        return await self.run_conversation(session_id, user_message)
