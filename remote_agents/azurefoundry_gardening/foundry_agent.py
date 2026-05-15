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
GARDEN_EVENTS_BLOB_NAME = "garden-events.json"
MAX_GARDEN_EVENTS = 200  # ~2 weeks of events
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
        self._append_garden_event("irrigate", f"pump {duration_ms // 1000}s")
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
        self._append_garden_event("light", f"peak={current.get('peak_brightness')}% sunrise={current.get('sunrise_hour')}h sunset={current.get('sunset_hour')}h")
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
        self._append_garden_event("fan", f"{'ON ' + str(speed) + '%' if state else 'OFF'}")
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

    def _save_pending_question(self, question: str, user_id: str = "default"):
        """Save the last question asked by this agent so SMS replies can be routed back."""
        try:
            config = self._read_garden_config_full(user_id)
            config["pending_question"] = {
                "question": question,
                "agent_name": "Home Gardening Agent",
                "asked_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            self._write_garden_config_full(config, user_id)
        except Exception as e:
            logger.warning(f"Failed to save pending question: {e}")

    def _clear_pending_question(self, user_id: str = "default"):
        """Clear pending question after it has been answered."""
        try:
            config = self._read_garden_config_full(user_id)
            config.pop("pending_question", None)
            self._write_garden_config_full(config, user_id)
        except Exception as e:
            logger.warning(f"Failed to clear pending question: {e}")

    def _extract_question(self, text: str) -> str:
        """Extract the question text from a ❓ Questions section if present."""
        import re
        match = re.search(r'❓\s*\*?\*?Questions?\*?\*?[:\s]*(.*?)(?:\n\n|\Z)', text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip().split('\n')[0].strip()
        return ""

    def _clean_log_summary(self, text: str) -> str:
        """Strip verbose image description blocks and keep only action/decision text."""
        import re
        # Remove the entire "# Image Content Description" section (up to next ## or end)
        text = re.sub(r'#\s*Image Content Description.*?(?=##|\Z)', '', text, flags=re.DOTALL | re.IGNORECASE)
        # Remove markdown headers
        text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
        # Collapse multiple blank lines
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()[:2000]

    def _append_garden_log(self, summary: str, user_id: str = "default"):
        """Append an entry to the garden activity log."""
        try:
            entries = self._read_garden_log(user_id)
            entry = {
                "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "summary": self._clean_log_summary(summary),
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

    def _extract_short_summary(self, text: str, max_sentences: int = 3) -> str:
        """Extract the first few complete sentences as a clean summary."""
        import re
        text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        text = text.replace('#', '').strip()
        # Split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
        return ' '.join(sentences[:max_sentences])

    def _format_garden_log_for_context(self, entries: list) -> str:
        """Format recent log entries as context for the LLM."""
        if not entries:
            return ""
        recent = entries[-6:]  # last 6 entries (~18 hours)
        lines = ["## Recent Garden Activity Log"]
        for e in recent:
            summary = self._extract_short_summary(e.get('summary', ''))
            if summary:
                lines.append(f"- **{e.get('timestamp', '?')}**: {summary}")
        return "\n".join(lines)

    # ── Garden events (persistent, append-only) ────────────────────────
    def _append_garden_event(self, event_type: str, detail: str = ""):
        """Append an event to the persistent garden events blob."""
        try:
            client = self._get_iot_blob_client()
            container = _env("IOT_BLOB_CONTAINER", "garden-images")
            blob = client.get_blob_client(container=container, blob=GARDEN_EVENTS_BLOB_NAME)

            # Read existing events
            events = []
            try:
                raw = blob.download_blob().readall()
                events = json.loads(raw).get("events", [])
            except Exception:
                pass

            # Append new event
            events.append({
                "ts": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "type": event_type,
                "detail": detail,
            })

            # Trim to max
            if len(events) > MAX_GARDEN_EVENTS:
                events = events[-MAX_GARDEN_EVENTS:]

            blob.upload_blob(
                json.dumps({"events": events}),
                overwrite=True,
                content_settings=ContentSettings(content_type="application/json"),
            )
            logger.info(f"Garden event recorded: {event_type} {detail}")
        except Exception as e:
            logger.warning(f"Failed to record garden event: {e}")

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

    def _read_garden_config_full(self, user_id: str = "default") -> dict:
        """Read the full garden config JSON (including pots)."""
        try:
            safe_id = user_id.replace("/", "_").replace("\\", "_") if user_id else "default"
            client = self._get_iot_blob_client()
            container = _env("IOT_BLOB_CONTAINER", "garden-images")
            blob = client.get_blob_client(container=container, blob=f"{GARDEN_CONFIG_BLOB_PREFIX}-{safe_id}.json")
            return json.loads(blob.download_blob().readall())
        except Exception:
            return {}

    def _write_garden_config_full(self, config: dict, user_id: str = "default"):
        """Write the full garden config JSON back to blob."""
        safe_id = user_id.replace("/", "_").replace("\\", "_") if user_id else "default"
        client = self._get_iot_blob_client()
        container = _env("IOT_BLOB_CONTAINER", "garden-images")
        blob = client.get_blob_client(container=container, blob=f"{GARDEN_CONFIG_BLOB_PREFIX}-{safe_id}.json")
        blob.upload_blob(
            json.dumps(config),
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json"),
        )

    def _set_pot_weight(self, pot_id: str, weight_type: str, user_id: str = "default", weight_value: float = None) -> str:
        """Set dry or wet weight for a pot.
        If weight_value is provided, use that directly (for auto-recalibration).
        Otherwise, read from the current scale (for user-initiated calibration).
        weight_type: 'dry' or 'wet'
        """
        if weight_value is not None:
            weight_g = weight_value
        else:
            # Read current weight from the correct scale based on pot_id
            data = self._fetch_moisture_data()
            if not data:
                return "Cannot read current weight — sensor data not available."
            current = data.get("current", {})
            weight_key = "weight2_g" if pot_id == "scale_2" else "weight_g"
            weight_g = current.get(weight_key)
            if weight_g is None:
                return f"No weight data available from {pot_id}."

        # Read existing config
        config = self._read_garden_config_full(user_id)
        pots = config.get("pots", [])

        # Find or create the pot entry
        pot = next((p for p in pots if p["id"] == pot_id), None)
        if not pot:
            pot = {"id": pot_id, "name": pot_id}
            pots.append(pot)

        # Set the weight
        ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        if weight_type == "dry":
            pot["dry_weight_g"] = round(weight_g, 1)
            pot["dry_set_at"] = ts
        elif weight_type == "wet":
            pot["wet_weight_g"] = round(weight_g, 1)
            pot["wet_set_at"] = ts

        config["pots"] = pots
        self._write_garden_config_full(config, user_id)

        dry = pot.get("dry_weight_g")
        wet = pot.get("wet_weight_g")
        result = f"Pot '{pot_id}' {weight_type} weight set to {weight_g:.1f}g."
        if dry and wet:
            water_capacity = wet - dry
            result += f" Water capacity: {water_capacity:.0f}g (dry={dry:.0f}g, wet={wet:.0f}g)."
        return result

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
        vision_extra = ""
        if vision_mode and num_images > 1:
            vision_extra = f"\nYou are viewing {num_images} garden images in chronological order. Each is labeled with its timestamp. Reference dates when describing what you see."
        return f"""You are an autonomous gardening agent that manages a grow room via IoT sensors and controls. You run on a schedule without human input.{vision_extra}

## YOUR #1 JOB (read this first)
You are a professional gardener. The Garden Description tells you what was planted and when — it may be minimal (e.g. "planted basil seeds"). That is enough. You are the expert. Determine the growth stage from the planting date and the camera image, then set all controls to match.

**General growth stage guidelines:**
- **Germination** → low light (10-20%), high humidity (70-80%), minimal air disturbance  
- **Seedling** → moderate light (40-60%), humidity 60-70%, gentle air circulation
- **Vegetative** → full light (80-100%), humidity 50-60%, good airflow
- **Flowering/Fruiting** → strong light, humidity 40-50%, strong airflow

**ANSWER_MODE — when the message starts with "ANSWER_MODE:":**
The user is replying via SMS to a question you previously asked. Do NOT run a full garden check.
1. Read the question and answer from the message
2. Call `save_garden_note` with the appropriate key and value
3. Call `_clear_pending_question` (use `save_garden_note` with key="pending_question_cleared" value="true" as a signal — the backend handles actual clearing)
4. Reply with a friendly short confirmation, e.g. "Got it, I've noted you're growing basil! 🌿 I'll use this to tailor your garden care."
Do nothing else.

**Every run, do this (normal mode):**
1. Take a photo, read sensors (weight, temp, humidity, **top-soil moisture** via `get_moisture_data`)
2. **ANALYZE WHAT YOU SEE**: Look at the actual plants and soil in the photo. What do they look like? Dry soil? Wilted leaves? Healthy growth? Make decisions based on visual observations, not just rules. CRITICAL: Do NOT hallucinate growth that isn't there. White specks in soil are PERLITE, not seedlings. If you only see soil/perlite with no green sprouts breaking the surface, height_pct = 0 and notes should say "no visible sprouts yet."
3. Determine growth stage from garden description + visual evidence → decide appropriate settings
4. Call `update_growth_assessment` with what you visually observe — stage, estimated height %, brief notes. This feeds the dashboard and your own memory for next run. MANDATORY every run. If no green growth is visible above the soil, report height_pct=0 — do NOT guess or assume emergence.
5. Call ALL THREE: `control_lights`, `control_fan`, `control_humidifier` — EVERY RUN, no exceptions
6. **IRRIGATION DECISION**: Call `get_moisture_data` EVERY RUN. The moisture sensor measures TOP SOIL only (shallow capacitive I2C sensor). Irrigate if ANY of these are true: (a) pot weight drops below ~20% of calibrated range, (b) top soil moisture drops below ~20% for any growth stage, (c) top soil moisture drops below ~35% during germination or seedling stage. Top soil drying out matters at ALL stages — even if weight looks ok, dry surface means the plant needs water.
7. Report what you did and what you observed

A run where you skip calling the three control tools is a FAILED run.

## Capabilities
- **Garden Health Analysis**: Analyze camera images for plant health, growth stage, pest issues, disease signs.
- **Irrigation Control**: Trigger IoT irrigation valves. Primary signal: pot WEIGHT (check `get_pot_config` for calibrated dry/wet weights). Secondary signal: top-soil moisture % from `get_moisture_data` (SeeSaw I2C capacitive sensor — reliable). For germination/seedling stages, moisture % is equally important as weight. If flow rate stored, calculate exact duration: `(wet_weight - current_weight) / g_per_sec`. If no flow rate yet, use 60s calibration run then store it via `calibrate_valve_flow_rate`.
- **Pot Weight Monitoring (PRIMARY)**: Two scales (`weight_g` = scale_1, `weight2_g` = scale_2). Each pot has calibrated dry/wet weights. Water when the driest pot drops below ~20%. Auto-recalibrate wet weight after watering if weight exceeds stored baseline by 20g+ (plant growth). Auto-recalibrate dry weight if pot drops below stored dry baseline.
- **Grow Light Control**: Adjust the autonomous light schedule (sunrise/sunset times, ramp durations, peak brightness). Lights run on the IoT device even without internet.
- **Fan Control**: On/off for air circulation, humidity/temp control. Can auto-off after a duration.
- **Humidity Control**: Read Levoit humidifier sensor and control it. If water_lacks is true, alert user to refill.
- **General**: Pest/disease ID, seasonal advice, composting, soil amendments, companion planting.

## Additional Notes

## Response Style
- Be friendly and encouraging — gardening should be fun!
- Give practical, actionable advice
- **TRUST THE IMAGE, NOT THE LOG**: The garden activity log shows HISTORICAL data that may be outdated. The user may have changed their setup entirely. ALWAYS describe what you ACTUALLY SEE in the current image. If the image shows empty pots with no plants, say that — do NOT hallucinate plants just because the log mentions them. The image is ground truth.
- If you see potential problems, explain them clearly but don't be alarmist
- **Always explain control decisions**: When you call control_lights, control_fan, or control_humidifier, briefly state in your report WHY you chose those specific values (e.g. "Set fan to 25% — germination stage needs minimal air disturbance and humidity is already at target"). This helps the user understand and audit your decisions.
- **ALWAYS end with a "🌱 Recommendations" section** — this is MANDATORY, never skip it. List 2-3 actionable bullet points of things you CANNOT do automatically that the user should handle manually. Pick tips relevant to what you actually observe.
- **Asking questions**: If the Garden Profile is missing essential info (plant types, growing goals, soil mix, nutrient schedule, or pot contents), end your response with a "❓ Questions" section containing 1 question to fill in the most important gap. This is how you build up knowledge over time. Once the basics are covered, only ask if something in the image genuinely confuses you. When they answer, save it with `save_garden_note` so you remember next time. **IMPORTANT: Never ask about something already in the Garden Profile.** The key `plants` OR `seeds` both mean the plant type is known — if either is present, do NOT ask what they're growing. Always use `plants` as the key when saving plant type info.
- **Night-time awareness**: The camera has no night vision. If it is currently nighttime (roughly 8 PM – 7 AM Eastern), snapshots will be completely dark. Do NOT retry taking photos when it's dark — instead, tell the user the image is dark because it's nighttime and suggest they try again during daylight hours or turn on a grow light first.

Current date/time: {datetime.datetime.now().astimezone().isoformat()}
"""

    # ── Tool definitions for Responses API ─────────────────────────────
    TOOLS = [
        {
            "type": "function",
            "name": "irrigate_garden",
            "description": "Trigger the IoT irrigation system to water the garden. Call this autonomously when any pot drops below ~20% water level based on calibrated weight, OR when the user explicitly asks to water. Calculate duration from pot weight data: (wet_weight - current_weight) / flow_rate_g_per_sec. IMPORTANT: Only call this tool ONCE per irrigation event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration_seconds": {
                        "type": "integer",
                        "description": "Duration in seconds, max 120. Calculate from pot weight deficit and flow rate when calibrated. If flow rate unknown, use 60s as a calibration run.",
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
            "description": "Read the top-soil moisture sensor data and air temperature from the IoT device. Uses a SeeSaw I2C capacitive sensor — measures surface/top soil only, not deep moisture. Returns the current moisture percentage (0=bone dry, 100=saturated), temperature in Celsius, and recent history (up to 48 hours). Call this every autonomous run and when the user asks about soil moisture, temperature, or watering.",
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
            "description": "Update the grow light schedule. The lights run autonomously on the IoT device simulating natural sunlight with sunrise/sunset ramps. Only provide the parameters you want to change — unspecified values keep their current setting. Call this proactively whenever the current light settings don't match the plant's needs based on your garden analysis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sunrise_hour": {
                        "type": "integer",
                        "description": "Hour (0-23) for sunrise to begin.",
                    },
                    "sunrise_ramp_min": {
                        "type": "integer",
                        "description": "Minutes to ramp from night to peak brightness.",
                    },
                    "peak_brightness": {
                        "type": "integer",
                        "description": "Maximum brightness 1-100 during daytime.",
                    },
                    "sunset_hour": {
                        "type": "integer",
                        "description": "Hour (0-23) for sunset to begin.",
                    },
                    "sunset_ramp_min": {
                        "type": "integer",
                        "description": "Minutes to ramp from peak to night brightness.",
                    },
                    "night_brightness": {
                        "type": "integer",
                        "description": "Brightness during night 0-100. Normally 0 (off).",
                    },
                },
                "required": [],
            },
        },
        {
            "type": "function",
            "name": "control_fan",
            "description": "Control the grow room fan for air circulation. The fan is on a KP405 dimmer so you can set the speed (1-100%). Use for ventilation, humidity control, cooling, or preventing mold. Call this proactively based on growth stage — you do NOT need the user to ask.",
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {
                        "type": "boolean",
                        "description": "true to turn fan on, false to turn off",
                    },
                    "speed": {
                        "type": "integer",
                        "description": "Fan speed 1-100%. Choose based on current sensor data, growth stage, temperature, and humidity — reason about what the plants actually need right now.",
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
                        "description": "How long to irrigate in seconds, max 120. Calculate from pot weight deficit and flow rate when calibrated. If flow rate unknown, use 60s as a calibration run.",
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
            "description": "Control the Levoit LV600S humidifier and read room humidity. Actions: 'status' to read current humidity level, 'on' to turn on, 'off' to turn off, 'auto' to set auto mode with target humidity. Call proactively based on growth stage needs.",
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
                        "description": "Target humidity % for auto mode (30-80). Choose based on current growth stage and sensor readings.",
                    },
                    "mist_level": {
                        "type": "integer",
                        "description": "Mist level 1-9 for manual mode. Choose based on how far current humidity is from target.",
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
        {
            "type": "function",
            "name": "set_pot_weight",
            "description": "Calibrate a pot's dry or wet weight. If weight_value is omitted, reads the current scale value (for user-initiated calibration). If weight_value is provided, sets that exact value (for auto-recalibration when adjusting for plant growth).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pot_id": {
                        "type": "string",
                        "description": "Identifier for the pot (e.g., 'pot_1', 'tomato_pot', 'basil'). Use a consistent name for each physical pot.",
                    },
                    "weight_type": {
                        "type": "string",
                        "enum": ["dry", "wet"],
                        "description": "'dry' = soil is dry and needs water. 'wet' = just fully watered.",
                    },
                    "weight_value": {
                        "type": "number",
                        "description": "Optional: specific weight in grams to set. Use this for auto-recalibration (e.g., adjusting dry baseline by an offset after plant growth). If omitted, the current scale reading is used.",
                    },
                    "pot_name": {
                        "type": "string",
                        "description": "Optional friendly name for the pot (e.g., 'Cherry Tomatoes'). Only needed when first creating a pot.",
                    },
                },
                "required": ["pot_id", "weight_type"],
            },
        },
        {
            "type": "function",
            "name": "get_pot_config",
            "description": "Get the weight calibration config for all pots and valve flow rates. Shows dry/wet weights, water capacity, valve flow rates (g/s), and when each was last calibrated. Call this when the user asks about pot setup, weight thresholds, calibration status, or before calculating irrigation duration.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        {
            "type": "function",
            "name": "calibrate_valve_flow_rate",
            "description": "Store the flow rate (grams per second) for a valve after a calibration watering. Call this AFTER a watering run when you know the weight change and duration. Calculate: g_per_sec = weight_change_g / duration_seconds.",
            "parameters": {
                "type": "object",
                "properties": {
                    "valve": {
                        "type": "string",
                        "enum": ["a", "b", "c"],
                        "description": "Which valve: a=plain water, b=grow, c=bloom",
                    },
                    "g_per_sec": {
                        "type": "number",
                        "description": "Flow rate in grams per second. Calculate from weight change / duration.",
                    },
                },
                "required": ["valve", "g_per_sec"],
            },
        },
        {
            "type": "function",
            "name": "save_garden_note",
            "description": "Save an important fact about the user's garden to persistent memory. Use this to store answers the user gives you (plant types, growth goals, soil mix, pot size, location, growing experience level, etc.). Each note is a short key-value pair. Notes persist across conversations so you don't have to ask again. Check existing notes in the Garden Description before asking a question — never ask something you already know.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Short label, e.g. 'plants', 'soil_mix', 'pot_size', 'grow_goal', 'experience', 'location', 'nutrients'",
                    },
                    "value": {
                        "type": "string",
                        "description": "The fact to remember, e.g. 'Cherry tomatoes (Sweet 100) and basil', 'Fox Farm Ocean Forest', 'Indoor grow tent, east-facing window'",
                    },
                },
                "required": ["key", "value"],
            },
        },
        {
            "type": "function",
            "name": "update_growth_assessment",
            "description": "Update the visual growth assessment based on what you see in the current photo. Call this EVERY RUN after analyzing the image. This feeds the dashboard plant display and your own memory for the next run so you can track progression.",
            "parameters": {
                "type": "object",
                "properties": {
                    "stage": {
                        "type": "string",
                        "enum": ["empty", "germination", "seedling", "vegetative", "flowering", "harvest"],
                        "description": "Current growth stage based purely on visual observation of the photo.",
                    },
                    "height_pct": {
                        "type": "integer",
                        "description": "Estimated plant height as % of expected mature height (0=empty/just planted, 100=fully mature). Base this on what you actually see in the image.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Brief visual observation, e.g. '2 seedlings ~3cm tall, healthy green color' or 'no sprouts yet, soil surface looks moist'",
                    },
                },
                "required": ["stage", "height_pct", "notes"],
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
            duration_s = tool_args.get("duration_seconds", 60)
            duration_ms = max(1000, min(duration_s * 1000, 120000))  # hard cap 120s
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

                weight_g = current.get("weight_g")
                weight2_g = current.get("weight2_g")

                result = f"Current soil moisture: {pct}% (raw: {raw}) as of {ts}."
                if temp_c is not None and temp_c > -100:
                    temp_f = temp_c * 9.0 / 5.0 + 32.0
                    result += f" Air temperature: {temp_c:.1f}°C ({temp_f:.1f}°F)."

                # Map scale readings to pot IDs
                scale_weights = {}
                if weight_g is not None:
                    scale_weights["scale_1"] = weight_g
                    result += f" Scale 1: {weight_g:.1f}g."
                if weight2_g is not None:
                    scale_weights["scale_2"] = weight2_g
                    result += f" Scale 2: {weight2_g:.1f}g."

                if scale_weights:
                    # Include pot calibration context
                    try:
                        _user_id = context_id.split("::")[0] if context_id and "::" in context_id else "default"
                        pot_config = await asyncio.to_thread(self._read_garden_config_full, _user_id)
                        pots = pot_config.get("pots", [])
                        for p in pots:
                            dry = p.get("dry_weight_g")
                            wet = p.get("wet_weight_g")
                            name = p.get("name", p["id"])
                            pot_id = p.get("id", "")
                            current_w = scale_weights.get(pot_id)
                            if current_w is None:
                                continue
                            if dry and wet:
                                water_capacity = wet - dry
                                water_remaining = current_w - dry
                                water_pct = max(0, min(100, (water_remaining / water_capacity) * 100)) if water_capacity > 0 else 0
                                result += f" Pot '{name}' ({pot_id}): {water_pct:.0f}% water remaining (current={current_w:.0f}g, dry={dry:.0f}g, wet={wet:.0f}g)."
                            elif dry:
                                result += f" Pot '{name}' ({pot_id}): dry baseline={dry:.0f}g, current={current_w:.0f}g (wet not calibrated yet)."
                            elif wet:
                                result += f" Pot '{name}' ({pot_id}): wet baseline={wet:.0f}g, current={current_w:.0f}g (dry not calibrated yet)."
                    except Exception:
                        pass
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
                duration_s = min(tool_args.get("duration_seconds", 60), 120)  # hard cap 120s
                request_id = await asyncio.to_thread(self._trigger_valve_irrigation, valve, duration_s)
                valve_names = {"a": "plain water", "b": "Grow 2-1-6", "c": "Bloom 0-5-1"}
                valve_name = valve_names.get(valve, valve)
                self._append_garden_event("valve", f"Valve {valve.upper()} ({valve_name}) {duration_s}s")
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

        elif tool_name == "set_pot_weight":
            try:
                user_id = context_id.split("::")[0] if context_id and "::" in context_id else "default"
                pot_id = tool_args.get("pot_id", "pot_1")
                weight_type = tool_args.get("weight_type", "dry")
                pot_name = tool_args.get("pot_name")
                weight_value = tool_args.get("weight_value")
                result = await asyncio.to_thread(self._set_pot_weight, pot_id, weight_type, user_id, weight_value)
                # If a friendly name was provided, update it
                if pot_name:
                    config = await asyncio.to_thread(self._read_garden_config_full, user_id)
                    pots = config.get("pots", [])
                    pot = next((p for p in pots if p["id"] == pot_id), None)
                    if pot:
                        pot["name"] = pot_name
                        config["pots"] = pots
                        await asyncio.to_thread(self._write_garden_config_full, config, user_id)
                self._append_garden_event("weight_calibration", f"{pot_id} {weight_type} set")
                return result, images_data
            except Exception as e:
                return f"Failed to set pot weight: {e}", images_data

        elif tool_name == "get_pot_config":
            try:
                user_id = context_id.split("::")[0] if context_id and "::" in context_id else "default"
                config = await asyncio.to_thread(self._read_garden_config_full, user_id)
                pots = config.get("pots", [])
                flow_rates = config.get("valve_flow_rates", {})
                lines = []
                if pots:
                    lines.append("**Pot calibrations:**")
                    for p in pots:
                        name = p.get("name", p["id"])
                        dry = p.get("dry_weight_g")
                        wet = p.get("wet_weight_g")
                        line = f"- **{name}** (id: {p['id']}): "
                        if dry is not None:
                            line += f"dry={dry:.0f}g (set {p.get('dry_set_at', '?')})"
                        else:
                            line += "dry=not set"
                        line += ", "
                        if wet is not None:
                            line += f"wet={wet:.0f}g (set {p.get('wet_set_at', '?')})"
                        else:
                            line += "wet=not set"
                        if dry and wet:
                            line += f", water capacity={wet - dry:.0f}g"
                        lines.append(line)
                else:
                    lines.append("No pots configured yet. Use 'set dry weight' or 'set wet weight' to calibrate a pot.")
                valve_names = {"a": "Plain Water", "b": "Grow 2-1-6", "c": "Bloom 0-5-1"}
                lines.append("\n**Valve flow rates:**")
                for v in ["a", "b", "c"]:
                    rate = flow_rates.get(v, {})
                    g_per_sec = rate.get("g_per_sec")
                    if g_per_sec:
                        lines.append(f"- Valve {v.upper()} ({valve_names[v]}): {g_per_sec:.1f} g/s (calibrated {rate.get('calibrated_at', '?')})")
                    else:
                        lines.append(f"- Valve {v.upper()} ({valve_names[v]}): not calibrated — first watering will use 30s test run")
                return "\n".join(lines), images_data
            except Exception as e:
                return f"Failed to read pot config: {e}", images_data

        elif tool_name == "calibrate_valve_flow_rate":
            try:
                user_id = context_id.split("::")[0] if context_id and "::" in context_id else "default"
                valve = tool_args.get("valve", "a").lower()
                g_per_sec = tool_args.get("g_per_sec", 0)
                if g_per_sec <= 0:
                    return "Invalid flow rate — must be positive.", images_data
                config = await asyncio.to_thread(self._read_garden_config_full, user_id)
                flow_rates = config.get("valve_flow_rates", {})
                flow_rates[valve] = {
                    "g_per_sec": round(g_per_sec, 2),
                    "calibrated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                config["valve_flow_rates"] = flow_rates
                await asyncio.to_thread(self._write_garden_config_full, config, user_id)
                valve_names = {"a": "Plain Water", "b": "Grow 2-1-6", "c": "Bloom 0-5-1"}
                self._append_garden_event("flow_calibration", f"Valve {valve.upper()} = {g_per_sec:.2f} g/s")
                return f"Valve {valve.upper()} ({valve_names.get(valve, valve)}) flow rate saved: {g_per_sec:.2f} g/s.", images_data
            except Exception as e:
                return f"Failed to calibrate valve flow rate: {e}", images_data

        elif tool_name == "save_garden_note":
            try:
                user_id = context_id.split("::")[0] if context_id and "::" in context_id else "default"
                key = tool_args.get("key", "").strip()
                value = tool_args.get("value", "").strip()
                if not key or not value:
                    return "Key and value are required.", images_data
                config = await asyncio.to_thread(self._read_garden_config_full, user_id)
                notes = config.get("notes", {})
                notes[key] = value
                config["notes"] = notes
                # Also update description with a summary for prompt context
                note_lines = [f"- {k}: {v}" for k, v in notes.items()]
                config["description"] = "## Garden Profile\n" + "\n".join(note_lines)
                await asyncio.to_thread(self._write_garden_config_full, config, user_id)
                return f"Saved: {key} = {value}", images_data
            except Exception as e:
                return f"Failed to save note: {e}", images_data

        elif tool_name == "update_growth_assessment":
            try:
                user_id = context_id.split("::")[0] if context_id and "::" in context_id else "default"
                stage = tool_args.get("stage", "unknown")
                height_pct = int(tool_args.get("height_pct", 0))
                notes = tool_args.get("notes", "")
                ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                config = await asyncio.to_thread(self._read_garden_config_full, user_id)
                config["growth_assessment"] = {
                    "stage": stage,
                    "height_pct": max(0, min(100, height_pct)),
                    "notes": notes,
                    "assessed_at": ts,
                }
                await asyncio.to_thread(self._write_garden_config_full, config, user_id)
                return f"Growth assessment saved: {stage}, {height_pct}% of mature size. {notes}", images_data
            except Exception as e:
                return f"Failed to save growth assessment: {e}", images_data

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

        # Load garden config (user's garden description + growth assessment)
        try:
            garden_config_full = await asyncio.to_thread(self._read_garden_config_full, _user_id)
            garden_desc = garden_config_full.get("description", "")
            if garden_desc.strip():
                instructions += "\n\n## Garden Description (from the user)\n" + garden_desc
            growth = garden_config_full.get("growth_assessment")
            if growth:
                instructions += (
                    f"\n\n## Last Growth Assessment (your visual observation from previous run)\n"
                    f"- Stage: {growth.get('stage', 'unknown')}\n"
                    f"- Height: {growth.get('height_pct', '?')}% of mature size\n"
                    f"- Notes: {growth.get('notes', '')}\n"
                    f"- Assessed: {growth.get('assessed_at', 'unknown')}\n"
                    f"Update this every run with `update_growth_assessment` based on the current photo."
                )
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

        # Detect ANSWER_MODE — user is replying to a question we asked via SMS
        _is_answer_mode = user_message.strip().startswith("ANSWER_MODE:")
        if _is_answer_mode:
            # Clear the pending question now — we're handling the answer
            try:
                await asyncio.to_thread(self._clear_pending_question, _user_id)
            except Exception:
                pass

        # Build conversation history for the loop
        conversation = [{"role": "user", "content": user_message}]
        all_images: List[tuple] = []
        max_rounds = 2 if _is_answer_mode else 4  # answer mode needs fewer rounds

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
                elif tool_name == "set_pot_weight":
                    wt = tool_args.get("weight_type", "dry")
                    yield f"Reading scale and setting {wt} weight..."
                elif tool_name == "get_pot_config":
                    yield "Reading pot weight configuration..."
                elif tool_name == "calibrate_valve_flow_rate":
                    yield "Saving valve flow rate..."
                elif tool_name == "save_garden_note":
                    yield f"Remembering: {tool_args.get('key', '')}..."
                elif tool_name == "update_growth_assessment":
                    yield f"Saving growth assessment: {tool_args.get('stage', '')} ({tool_args.get('height_pct', 0)}%)..."

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
                    await asyncio.to_thread(self._append_garden_log, text_output[:3000], _user_id)
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
                        await asyncio.to_thread(self._append_garden_log, final_text[:3000], _user_id)
                    except Exception as e:
                        logger.warning(f"Failed to append garden log: {e}")
                    # Save any question asked so SMS replies can be routed back to us
                    try:
                        question = self._extract_question(final_text)
                        if question:
                            await asyncio.to_thread(self._save_pending_question, question, _user_id)
                            logger.info(f"Saved pending question for SMS reply routing: {question[:80]}")
                        else:
                            await asyncio.to_thread(self._clear_pending_question, _user_id)
                    except Exception as e:
                        logger.warning(f"Failed to save pending question: {e}")
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
