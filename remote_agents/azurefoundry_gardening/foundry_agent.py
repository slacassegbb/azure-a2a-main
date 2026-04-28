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
HUMIDIFIER_STATUS_BLOB_NAME = "humidifier-status.json"
GARDEN_CONFIG_BLOB_PREFIX = "garden-config"  # garden-config-{user_id}.json
VALVE_COMMAND_BLOB_NAME = "valve-command.json"
GARDEN_LOG_BLOB_PREFIX = "garden-log"  # becomes garden-log-{user_id}.json
MAX_LOG_ENTRIES = 50  # keep last ~6 days at 3-hour intervals
VESYNC_EMAIL = "slacasseibm@gmail.com"
VESYNC_PASSWORD = "Hip1hops!"
DEFAULT_LIGHT_SCHEDULE = {
    "sunrise_hour": 5,
    "sunrise_ramp_min": 90,
    "peak_brightness": 100,
    "sunset_hour": 20,
    "sunset_ramp_min": 90,
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
    def _update_fan_command(self, state: bool, duration_min: int = 0, speed: int = 100) -> str:
        """Write fan command to IoT blob. Returns request_id."""
        request_id = uuid.uuid4().hex[:8]
        command = {"request_id": request_id, "state": state}
        if duration_min > 0:
            command["duration_min"] = duration_min
        if state and speed < 100:
            command["speed"] = max(1, min(100, speed))

        client = self._get_iot_blob_client()
        container = _env("IOT_BLOB_CONTAINER", "garden-images")
        blob = client.get_blob_client(container=container, blob=FAN_COMMAND_BLOB_NAME)
        blob.upload_blob(
            json.dumps(command),
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json"),
        )
        logger.info(f"Fan command sent: {request_id} state={state} speed={speed}% duration={duration_min}min")
        return request_id

    def _trigger_valve_irrigation(self, valve: str, duration_seconds: int = 120) -> str:
        """Write valve irrigation command to IoT blob. Returns request_id."""
        request_id = uuid.uuid4().hex[:8]
        command = {
            "request_id": request_id,
            "valve": valve.lower(),
            "duration_seconds": duration_seconds,
        }

        client = self._get_iot_blob_client()
        container = _env("IOT_BLOB_CONTAINER", "garden-images")
        blob = client.get_blob_client(container=container, blob=VALVE_COMMAND_BLOB_NAME)
        blob.upload_blob(
            json.dumps(command),
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json"),
        )
        valve_names = {"a": "plain water", "b": "Grow 2-1-6", "c": "Bloom 0-5-1"}
        logger.info(f"Valve command sent: {request_id} valve={valve} ({valve_names.get(valve, '?')}) duration={duration_seconds}s")
        return request_id

    # ── Garden memory log ──────────────────────────────────────────────
    def _garden_log_blob_name(self, user_id: str) -> str:
        """Get per-user garden log blob name."""
        safe_id = user_id.replace("/", "_").replace("\\", "_") if user_id else "default"
        return f"{GARDEN_LOG_BLOB_PREFIX}-{safe_id}.json"

    def _read_garden_log(self, user_id: str = "default") -> list:
        """Read the garden activity log from blob storage."""
        try:
            client = self._get_iot_blob_client()
            container = _env("IOT_BLOB_CONTAINER", "garden-images")
            blob = client.get_blob_client(container=container, blob=self._garden_log_blob_name(user_id))
            data = json.loads(blob.download_blob().readall())
            return data.get("entries", [])
        except Exception:
            return []

    def _append_garden_log(self, summary: str, user_id: str = "default"):
        """Append an entry to the garden activity log."""
        try:
            entries = self._read_garden_log(user_id)
            entry = {
                "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "summary": summary,
            }
            entries.append(entry)
            if len(entries) > MAX_LOG_ENTRIES:
                entries = entries[-MAX_LOG_ENTRIES:]

            client = self._get_iot_blob_client()
            container = _env("IOT_BLOB_CONTAINER", "garden-images")
            blob = client.get_blob_client(container=container, blob=self._garden_log_blob_name(user_id))
            blob.upload_blob(
                json.dumps({"entries": entries}),
                overwrite=True,
                content_settings=ContentSettings(content_type="application/json"),
            )
            logger.info(f"Garden log updated for {user_id}: {len(entries)} entries")
        except Exception as e:
            logger.warning(f"Failed to update garden log: {e}")

    def _format_garden_log_for_context(self, entries: list) -> str:
        """Format recent log entries as context for the LLM."""
        if not entries:
            return ""
        recent = entries[-10:]  # last 10 entries (~30 hours)
        lines = ["## Recent Garden Activity Log"]
        for e in recent:
            lines.append(f"- **{e.get('timestamp', '?')}**: {e.get('summary', '')}")
        return "\n".join(lines)

    # ── Garden config ─────────────────────────────────────────────────
    def _read_garden_config(self, user_id: str = "default") -> str:
        """Read the user's garden description from blob storage."""
        try:
            safe_id = user_id.replace("/", "_").replace("\\", "_") if user_id else "default"
            client = self._get_iot_blob_client()
            container = _env("IOT_BLOB_CONTAINER", "garden-images")
            blob = client.get_blob_client(container=container, blob=f"{GARDEN_CONFIG_BLOB_PREFIX}-{safe_id}.json")
            data = json.loads(blob.download_blob().readall())
            return data.get("description", "")
        except Exception:
            return ""

    # ── Timelapse video ────────────────────────────────────────────────
    def _create_timelapse_video(self, date_from: str, date_to: str, fps: int = 4, context_id: str = "") -> Optional[str]:
        """Create a timelapse MP4 from historical garden images. Returns blob URL."""
        import cv2
        import numpy as np
        import tempfile

        # Get all images in range
        available = self._list_iot_images()
        candidates = [
            img['name'] for img in available
            if img['name'][:10] >= date_from and img['name'][:10] <= date_to
        ]
        candidates.sort()  # chronological

        if not candidates:
            return None

        # Pick 1 image per day at midday for daily timelapse, or all for short ranges
        days = set(c[:10] for c in candidates)
        if len(days) > 7:
            # Long range: 1 per day at midday
            by_day = {}
            for name in candidates:
                day = name[:10]
                by_day.setdefault(day, []).append(name)
            selected = []
            for day in sorted(by_day.keys()):
                day_images = by_day[day]
                best = min(day_images, key=lambda n: abs(
                    int(n[11:13]) * 60 + int(n[14:16]) - 720
                ) if len(n) > 16 and n[11:13].isdigit() else 720)
                selected.append(best)
        else:
            # Short range: use all images but cap at 100
            selected = candidates[:100]

        if len(selected) < 2:
            return None

        logger.info(f"Creating timelapse from {len(selected)} images ({date_from} to {date_to})")

        # Download images and create video
        frames = []
        for blob_name in selected:
            try:
                img_bytes = self._fetch_iot_image_by_name(blob_name)
                nparr = np.frombuffer(img_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if frame is not None:
                    # Add date label to frame
                    date_label = blob_name[:16].replace("_", " ")
                    cv2.putText(frame, date_label, (20, 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2, cv2.LINE_AA)
                    cv2.putText(frame, date_label, (20, 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 1, cv2.LINE_AA)
                    frames.append(frame)
            except Exception as e:
                logger.warning(f"Failed to load {blob_name}: {e}")

        if len(frames) < 2:
            return None

        # Write frames as images, then use ffmpeg to create H.264 MP4
        import subprocess
        height, width = frames[0].shape[:2]
        tmp_dir = tempfile.mkdtemp()
        tmp_video = os.path.join(tmp_dir, "timelapse.mp4")

        # Save frames as numbered images
        for i, frame in enumerate(frames):
            if frame.shape[:2] != (height, width):
                frame = cv2.resize(frame, (width, height))
            cv2.imwrite(os.path.join(tmp_dir, f"frame_{i:04d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])

        # Use ffmpeg to create H.264 MP4 (browser-compatible)
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", os.path.join(tmp_dir, "frame_%04d.jpg"),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            tmp_video
        ]
        result = subprocess.run(ffmpeg_cmd, capture_output=True, timeout=60)
        if result.returncode != 0:
            logger.warning(f"ffmpeg failed: {result.stderr.decode()[:200]}")
            # Fallback: use OpenCV mp4v
            tmp_video = os.path.join(tmp_dir, "timelapse_cv.mp4")
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(tmp_video, fourcc, fps, (width, height))
            for frame in frames:
                if frame.shape[:2] != (height, width):
                    frame = cv2.resize(frame, (width, height))
                out.write(frame)
            out.release()

        # Read the video file
        with open(tmp_video, 'rb') as f:
            video_bytes = f.read()

        # Cleanup temp files
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

        logger.info(f"Timelapse video: {len(frames)} frames, {len(video_bytes)} bytes")

        # Upload to blob storage
        file_name = f"timelapse_{date_from}_to_{date_to}.mp4"
        client = self._get_host_blob_client() or self._get_iot_blob_client()
        host_container = _env("AZURE_BLOB_CONTAINER", "a2a-files")
        file_id = uuid.uuid4().hex[:8]
        if context_id and "::" in context_id:
            session_id = context_id.split("::")[0]
            blob_name = f"uploads/{session_id}/{file_id}/{file_name}"
        else:
            blob_name = f"gardening-agent/{file_id}/{file_name}"

        container_client = client.get_container_client(host_container)
        container_client.upload_blob(name=blob_name, data=video_bytes, overwrite=True)

        # Generate SAS URL
        url = self._generate_sas_url(client, host_container, blob_name)
        if url:
            self._latest_artifacts.append({
                "artifact-uri": url,
                "file-name": file_name,
                "mime": "video/mp4",
                "storage-type": "azure_blob",
                "status": "stored",
                "provider": "timelapse",
                "local-path": "",
                "file-size": len(video_bytes),
            })
        return url

    # ── Humidifier control (Levoit LV600S via VeSync) ──────────────────
    async def _get_humidifier(self):
        """Connect to VeSync and return the humidifier device. Returns (None, None) on any failure."""
        try:
            from pyvesync import VeSync
            manager = VeSync(
                _env("VESYNC_EMAIL", VESYNC_EMAIL),
                _env("VESYNC_PASSWORD", VESYNC_PASSWORD),
                time_zone='America/New_York'
            )
            # Timeout the whole VeSync connection to avoid stalling the workflow
            login_ok = await asyncio.wait_for(manager.login(), timeout=10)
            if not login_ok:
                logger.warning("VeSync login failed")
                return None, None
            await asyncio.wait_for(manager.get_devices(), timeout=10)
            humidifiers = manager.devices.humidifiers
            if not humidifiers:
                logger.warning("No humidifiers found on VeSync account")
                return None, None
            return manager, humidifiers[0]
        except asyncio.TimeoutError:
            logger.warning("VeSync connection timed out — skipping humidifier")
            return None, None
        except Exception as e:
            logger.warning(f"VeSync connection failed: {e} — skipping humidifier")
            return None, None

    async def _get_humidifier_status(self) -> dict:
        """Read humidifier status including humidity level."""
        manager, h = await self._get_humidifier()
        if not h:
            return None

        await h.get_details()

        # Extract data from raw response
        result = {}
        resp = h.last_response
        if resp and hasattr(resp, 'response_data'):
            data = resp.response_data
            inner = data.get('result', {}).get('result', {})
            result = {
                "humidity": inner.get("humidity"),
                "is_on": inner.get("enabled", False),
                "mist_level": inner.get("mist_level"),
                "mode": inner.get("mode"),
                "water_lacks": inner.get("water_lacks", False),
                "warm_enabled": inner.get("warm_enabled", False),
                "warm_level": inner.get("warm_level", 0),
                "target_humidity": inner.get("configuration", {}).get("auto_target_humidity"),
            }

        return result

    def _write_humidifier_status_blob(self, status: dict):
        """Write humidifier status to blob with history for dashboard charts."""
        try:
            ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            client = self._get_iot_blob_client()
            container = _env("IOT_BLOB_CONTAINER", "garden-images")
            blob = client.get_blob_client(container=container, blob=HUMIDIFIER_STATUS_BLOB_NAME)

            # Read existing data to preserve history
            existing = {"current": {}, "readings": []}
            try:
                raw = blob.download_blob().readall()
                existing = json.loads(raw)
            except Exception:
                pass

            # Update current
            current = {**status, "timestamp": ts}

            # Append to history
            readings = existing.get("readings", [])
            if status.get("humidity") is not None:
                readings.append({"ts": ts, "humidity": status["humidity"], "is_on": status.get("is_on", False)})
            # Keep last 576 entries (~48 hours at 5-min intervals, though humidity checks are less frequent)
            if len(readings) > 576:
                readings = readings[-576:]

            blob.upload_blob(
                json.dumps({"current": current, "readings": readings}),
                overwrite=True,
                content_settings=ContentSettings(content_type="application/json"),
            )
            logger.info(f"Humidifier status written to blob: humidity={status.get('humidity')}%")
        except Exception as e:
            logger.warning(f"Failed to write humidifier status blob: {e}")

    async def _control_humidifier(self, action: str, target_humidity: int = None, mist_level: int = None) -> str:
        """Control the humidifier. Actions: on, off, auto, status."""
        manager, h = await self._get_humidifier()
        if not h:
            return "Humidifier not found or offline"

        if action == "on":
            await h.turn_on()
            if mist_level:
                try:
                    await h.set_mist_level(mist_level)
                except Exception:
                    pass
            # Write status to blob for dashboard
            try:
                status = await self._get_humidifier_status()
                if status:
                    self._write_humidifier_status_blob(status)
            except Exception:
                pass
            return "Humidifier turned on" + (f" at mist level {mist_level}" if mist_level else "")
        elif action == "off":
            await h.turn_off()
            try:
                status = await self._get_humidifier_status()
                if status:
                    self._write_humidifier_status_blob(status)
            except Exception:
                pass
            return "Humidifier turned off"
        elif action == "auto":
            await h.turn_on()
            results = []
            if target_humidity:
                try:
                    await h.set_humidity(target_humidity)
                    results.append(f"target set to {target_humidity}%")
                except Exception as e:
                    logger.warning(f"set_humidity failed: {e}")
            try:
                await h.set_auto_mode()
                results.append("auto mode enabled")
            except Exception as e:
                logger.warning(f"set_auto_mode failed: {e}")
                try:
                    await h.set_mist_level(mist_level or 3)
                    results.append(f"manual mode, mist level {mist_level or 3}")
                except Exception:
                    pass
            # Write status to blob for dashboard
            try:
                await asyncio.sleep(2)  # Wait for VeSync to update
                status = await self._get_humidifier_status()
                if status:
                    self._write_humidifier_status_blob(status)
                    logger.info(f"Humidifier status blob written after auto: humidity={status.get('humidity')}")
                else:
                    logger.warning("Humidifier status returned None after auto")
            except Exception as e:
                logger.warning(f"Failed to write humidifier blob after auto: {e}")
            return "Humidifier: " + ", ".join(results) if results else "Humidifier turned on"
        elif action == "status":
            status = await self._get_humidifier_status()
            if status:
                try:
                    self._write_humidifier_status_blob(status)
                    logger.info(f"Humidifier status blob written: humidity={status.get('humidity')}")
                except Exception as e:
                    logger.error(f"FAILED to write humidifier blob: {e}")
                return (f"Humidity: {status['humidity']}%, "
                        f"On: {status['is_on']}, "
                        f"Mist: {status['mist_level']}, "
                        f"Mode: {status['mode']}, "
                        f"Water low: {status['water_lacks']}, "
                        f"Target: {status['target_humidity']}%")
            return "Could not read humidifier status"

        return f"Unknown action: {action}"

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
- **Humidity Control**: You can read room humidity from the Levoit humidifier sensor and control the humidifier. Be CONSERVATIVE with water — only turn on when humidity drops below 40%, set target to 50%, and turn off once reached. The tank is small. Always check humidity status before deciding to turn on. If water_lacks is true, alert the user to refill.
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
            "description": "Read the soil moisture sensor data and air temperature from the IoT device. Returns the current moisture percentage, temperature in Celsius, and recent history (up to 48 hours). Call this when the user asks about soil moisture, temperature, whether they should water, or moisture/temperature trends.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        {
            "type": "function",
            "name": "get_temperature",
            "description": "Read the current air temperature from the DS18B20 sensor on the IoT device. Returns temperature in Celsius and Fahrenheit. Call this when the user asks about temperature, heat, or growing conditions.",
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
                        "description": "Hour (0-23) for sunrise to begin. Default 5.",
                    },
                    "sunrise_ramp_min": {
                        "type": "integer",
                        "description": "Minutes to ramp from night to peak brightness. Default 90 for natural sun simulation.",
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
                        "description": "Minutes to ramp from peak to night brightness. Default 90 for natural sun simulation.",
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
            "description": "Control the grow room fan for air circulation. The fan is on a KP405 dimmer so you can set the speed (1-100%). Use for ventilation, humidity control, cooling, or preventing mold. Optionally set a duration after which the fan auto-turns off.",
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {
                        "type": "boolean",
                        "description": "true to turn fan on, false to turn off",
                    },
                    "speed": {
                        "type": "integer",
                        "description": "Fan speed 1-100%. Default 100. Lower speeds for gentle circulation, higher for cooling.",
                    },
                    "duration_min": {
                        "type": "integer",
                        "description": "Optional minutes to run before auto-off. 0 or omitted = indefinite.",
                    },
                },
                "required": ["state"],
            },
        },
        {
            "type": "function",
            "name": "irrigate_with_valve",
            "description": "Irrigate the garden using a specific valve/reservoir. Valve A = plain water (flushing, light watering). Valve B = Diablo Grow 2-1-6 (vegetative growth, nitrogen/potassium). Valve C = Diablo Bloom 0-5-1 (flowering, phosphorus). Choose the valve based on the plant's growth stage. Opens the valve and runs the pump for the specified duration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "valve": {
                        "type": "string",
                        "enum": ["a", "b", "c"],
                        "description": "Which valve/reservoir: a=plain water, b=grow nutrients, c=bloom nutrients",
                    },
                    "duration_seconds": {
                        "type": "integer",
                        "description": "How long to irrigate in seconds. Default 120 (2 minutes).",
                    },
                },
                "required": ["valve"],
            },
        },
        {
            "type": "function",
            "name": "create_timelapse",
            "description": "Create a time-lapse video from historical garden photos. Stitches timestamped IoT camera images into an MP4 video showing plant growth over time. Great for visualizing progress, tracking changes, and sharing garden updates.",
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
                    "fps": {
                        "type": "integer",
                        "description": "Frames per second for the video. Default 4. Higher = faster playback.",
                    },
                },
                "required": ["date_from", "date_to"],
            },
        },
        {
            "type": "function",
            "name": "control_humidifier",
            "description": "Control the Levoit LV600S humidifier and read room humidity. Actions: 'status' to read current humidity level, 'on' to turn on, 'off' to turn off, 'auto' to set auto mode with target humidity. Be conservative — only turn on if humidity drops below 40%, target 50%, and turn off once reached. The tank is small so avoid running unnecessarily.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action: 'status' (read humidity), 'on', 'off', or 'auto' (maintain target)",
                        "enum": ["status", "on", "off", "auto"],
                    },
                    "target_humidity": {
                        "type": "integer",
                        "description": "Target humidity % for auto mode (30-80). Default 50. Be conservative.",
                    },
                    "mist_level": {
                        "type": "integer",
                        "description": "Mist level 1-9 for manual mode. Lower = less water usage. Default 3.",
                    },
                },
                "required": ["action"],
            },
        },
        {
            "type": "function",
            "name": "clear_garden_log",
            "description": "Clear the garden activity log / memory. Use when starting a new garden, new plants, or when the user asks to reset memory. This erases all previous observations and decisions.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
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
                temp_c = current.get("temp_c")

                result = f"Current soil moisture: {pct}% (raw: {raw}) as of {ts}."
                if temp_c is not None and temp_c > -100:
                    temp_f = temp_c * 9.0 / 5.0 + 32.0
                    result += f" Air temperature: {temp_c:.1f}°C ({temp_f:.1f}°F)."
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

        elif tool_name == "get_temperature":
            try:
                data = await asyncio.to_thread(self._fetch_moisture_data)
                if not data:
                    return "Temperature sensor data not available. The sensor may not be connected or hasn't uploaded yet.", images_data
                current = data.get("current", {})
                temp_c = current.get("temp_c")
                ts = current.get("timestamp", "unknown")
                if temp_c is not None and temp_c > -100:
                    temp_f = temp_c * 9.0 / 5.0 + 32.0
                    return f"Current air temperature: {temp_c:.1f}°C ({temp_f:.1f}°F) as of {ts}.", images_data
                else:
                    return "Temperature sensor is connected but no valid reading available yet.", images_data
            except Exception as e:
                return f"Failed to read temperature: {e}", images_data

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
                speed = tool_args.get("speed", 100)
                duration_min = tool_args.get("duration_min", 0)
                request_id = await asyncio.to_thread(self._update_fan_command, state, duration_min, speed)
                state_str = "ON" if state else "OFF"
                speed_str = f" at {speed}% speed" if state and speed < 100 else ""
                duration_str = f" for {duration_min} minutes" if duration_min > 0 else ""
                return f"Fan command sent (request: {request_id}). Fan turned {state_str}{speed_str}{duration_str}.", images_data
            except Exception as e:
                return f"Failed to control fan: {e}", images_data

        elif tool_name == "irrigate_with_valve":
            try:
                valve = tool_args.get("valve", "a").lower()
                duration_s = tool_args.get("duration_seconds", 120)
                request_id = await asyncio.to_thread(self._trigger_valve_irrigation, valve, duration_s)
                valve_names = {"a": "plain water", "b": "Grow 2-1-6", "c": "Bloom 0-5-1"}
                valve_name = valve_names.get(valve, valve)
                return f"Valve irrigation started (request: {request_id}). Valve {valve.upper()} ({valve_name}) + pump running for {duration_s} seconds.", images_data
            except Exception as e:
                return f"Failed to trigger valve irrigation: {e}", images_data

        elif tool_name == "create_timelapse":
            try:
                date_from = tool_args.get("date_from", "")
                date_to = tool_args.get("date_to", "")
                fps = tool_args.get("fps", 4)
                url = await asyncio.to_thread(self._create_timelapse_video, date_from, date_to, fps, context_id)
                if url:
                    return f"Timelapse video created from {date_from} to {date_to}. Video URL: {url}", images_data
                else:
                    return f"Could not create timelapse — not enough images found between {date_from} and {date_to}.", images_data
            except Exception as e:
                return f"Failed to create timelapse: {e}", images_data

        elif tool_name == "control_humidifier":
            try:
                action = tool_args.get("action", "status")
                target = tool_args.get("target_humidity")
                mist = tool_args.get("mist_level")
                if action == "status":
                    status = await self._get_humidifier_status()
                    if status:
                        try:
                            self._write_humidifier_status_blob(status)
                            logger.info(f"Humidifier status blob written from execute: humidity={status.get('humidity')}")
                        except Exception as e:
                            logger.error(f"FAILED to write humidifier blob: {e}")
                        water_warning = " ⚠️ WATER TANK LOW — needs refill!" if status.get("water_lacks") else ""
                        return (f"Room humidity: {status['humidity']}%, "
                                f"Humidifier: {'on' if status['is_on'] else 'off'}, "
                                f"Mist level: {status['mist_level']}, "
                                f"Mode: {status['mode']}, "
                                f"Target: {status['target_humidity']}%"
                                f"{water_warning}"), images_data
                    return "Could not read humidifier status.", images_data
                else:
                    result = await self._control_humidifier(action, target, mist)
                    return result, images_data
            except Exception as e:
                return f"Failed to control humidifier: {e}", images_data

        elif tool_name == "clear_garden_log":
            try:
                user_id = context_id.split("::")[0] if context_id and "::" in context_id else "default"
                client = self._get_iot_blob_client()
                container = _env("IOT_BLOB_CONTAINER", "garden-images")
                blob = client.get_blob_client(container=container, blob=self._garden_log_blob_name(user_id))
                blob.upload_blob(
                    json.dumps({"entries": []}),
                    overwrite=True,
                    content_settings=ContentSettings(content_type="application/json"),
                )
                return "Garden memory log cleared. Starting fresh.", images_data
            except Exception as e:
                return f"Failed to clear garden log: {e}", images_data

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

        # Extract user_id from context_id for per-user memory
        _user_id = context_id.split("::")[0] if context_id and "::" in context_id else "default"

        # Load garden config (user's garden description)
        try:
            garden_config = await asyncio.to_thread(self._read_garden_config, _user_id)
            if garden_config.strip():
                instructions += "\n\n## Garden Description (from the user)\n" + garden_config
        except Exception as e:
            logger.warning(f"Failed to load garden config: {e}")

        # Load garden activity log for context
        try:
            log_entries = await asyncio.to_thread(self._read_garden_log, _user_id)
            log_context = self._format_garden_log_for_context(log_entries)
            if log_context:
                instructions += "\n\n" + log_context
        except Exception as e:
            logger.warning(f"Failed to load garden log: {e}")

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
                    yield "Reading soil moisture and temperature sensors..."
                elif tool_name == "get_temperature":
                    yield "Reading temperature sensor..."
                elif tool_name == "control_lights":
                    yield "Updating light schedule..."
                elif tool_name == "control_fan":
                    yield "Sending fan command..."
                elif tool_name == "irrigate_with_valve":
                    valve = tool_args.get("valve", "a")
                    valve_names = {"a": "plain water", "b": "Grow nutrients", "c": "Bloom nutrients"}
                    yield f"Opening valve {valve.upper()} ({valve_names.get(valve, valve)}) + pump..."
                elif tool_name == "create_timelapse":
                    yield "Creating timelapse video..."
                elif tool_name == "control_humidifier":
                    yield "Checking humidifier..."
                elif tool_name == "clear_garden_log":
                    yield "Clearing garden memory..."

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
                try:
                    await asyncio.to_thread(self._append_garden_log, text_output[:500], _user_id)
                except Exception as e:
                    logger.warning(f"Failed to append garden log: {e}")
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
                    final_text = "".join(text_chunks)
                    yield final_text
                    # Append summary to garden log
                    try:
                        await asyncio.to_thread(self._append_garden_log, final_text[:500], _user_id)
                    except Exception as e:
                        logger.warning(f"Failed to append garden log: {e}")
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
