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

logger = logging.getLogger(__name__)

def _env(key: str, default: str = "") -> str:
    """Read env var lazily (after load_dotenv has run)."""
    return os.getenv(key, default)


MAX_VISION_IMAGES = 8


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

    # ── Artifact management ─────────────────────────────────────────────
    def pop_latest_artifacts(self) -> List[Dict[str, Any]]:
        """Return and clear accumulated artifacts (called by executor)."""
        artifacts = list(self._latest_artifacts)
        self._latest_artifacts.clear()
        return artifacts

    # ── Image date range classification ─────────────────────────────────
    async def _get_image_date_range(self, user_message: str) -> Optional[Dict[str, str]]:
        """Ask the LLM what date range of images the user wants. Returns None for 'just latest'."""
        client = self._get_client()
        model = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")

        try:
            response = await client.responses.create(
                model=model,
                instructions=f"""Today is {datetime.datetime.now().strftime('%Y-%m-%d')}.

The user is asking about their garden. Determine if they want to see historical images or just the current one.

If the user wants just the current/latest image (e.g., "how's my garden", "check my plants"), respond:
{{"date_from": null, "date_to": null}}

If the user wants historical images (e.g., "compare yesterday", "show me the last week", "what changed"), respond with the date range:
{{"date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD"}}

Respond ONLY with JSON.""",
                input=[{"role": "user", "content": f"Respond in JSON: {user_message}"}],
                text={"format": {"type": "json_object"}},
                max_output_tokens=100,
            )

            data = json.loads(response.output_text)
            if data.get("date_from") and data.get("date_to"):
                return {"date_from": data["date_from"], "date_to": data["date_to"]}
            return None
        except Exception as e:
            logger.warning(f"Date range classification failed, using latest: {e}")
            return None

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

    def _get_agent_instructions(self, vision_mode: bool = False, num_images: int = 1) -> str:
        if vision_mode:
            multi = ""
            if num_images > 1:
                multi = f"\nYou are viewing {num_images} garden images in chronological order. Each is labeled with its timestamp. Reference dates when describing what you see."
            return f"""You are a home gardening expert with access to garden camera images.{multi}
Analyze for plant health, growth stage, pest issues, and soil conditions.
Give friendly, practical advice. Be specific about what you observe.
Current date: {datetime.datetime.now().strftime('%Y-%m-%d')}"""
        return f"""You are a home gardening expert assistant with access to a live garden camera.

You help the user monitor and care for their garden by analyzing real-time images from their IoT camera.

## Capabilities
- **Garden Health Analysis**: Analyze garden images for plant health, growth stage, pest issues, disease signs, and soil conditions.
- **Watering Recommendations**: Based on visual analysis, advise when and how much to water.
- **Pest & Disease Identification**: Identify visible pests, fungal infections, nutrient deficiencies, and other issues.
- **Seasonal Advice**: Provide planting schedules, pruning tips, fertilization recommendations based on what you see.
- **General Gardening Knowledge**: Answer any gardening questions — composting, soil amendments, companion planting, etc.

## Response Style
- Be friendly and encouraging — gardening should be fun!
- Give practical, actionable advice
- If you see potential problems, explain them clearly but don't be alarmist

Current date: {datetime.datetime.now().isoformat()}
"""

    # ── Core conversation with vision ───────────────────────────────────
    async def run_conversation_stream(self, session_id: str, user_message: str, context_id: str = ""):
        """Stream a conversation, optionally fetching and analyzing the garden image."""
        if not self._initialized:
            await self.create_agent()

        client = self._get_client()
        model = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")

        # Determine if we should fetch the garden image
        needs_image = self._should_fetch_image(user_message)

        input_content: List[Dict[str, Any]] = []
        num_images = 0

        if needs_image:
            # Ask LLM if the user wants historical images or just the latest
            yield "Analyzing your request..."
            date_range = await self._get_image_date_range(user_message)

            # Select images based on date range
            image_blob_names: List[str] = []
            if date_range:
                try:
                    yield "Scanning available garden images..."
                    available = await asyncio.to_thread(self._list_iot_images)
                    image_blob_names = self._select_images_in_range(
                        date_range["date_from"], date_range["date_to"], available
                    )
                    logger.info(f"Selected {len(image_blob_names)} images for {date_range['date_from']} to {date_range['date_to']}")
                    if not image_blob_names:
                        yield f"No images found between {date_range['date_from']} and {date_range['date_to']}. Using the latest image instead."
                except Exception as e:
                    logger.warning(f"Failed to list images, falling back to latest: {e}")

            # Fetch images (selected ones or latest.jpg fallback)
            images_data: List[tuple] = []  # (filename, bytes)

            if image_blob_names:
                yield f"Fetching {len(image_blob_names)} garden images..."
                for blob_name in image_blob_names:
                    try:
                        img_bytes = await asyncio.to_thread(self._fetch_iot_image_by_name, blob_name)
                        images_data.append((blob_name, img_bytes))
                    except Exception as e:
                        logger.warning(f"Failed to fetch {blob_name}: {e}")

            if not images_data:
                yield "Fetching latest garden image from IoT camera..."
                try:
                    img_bytes = await asyncio.to_thread(self._fetch_iot_image)
                    images_data.append(("latest.jpg", img_bytes))
                except Exception as e:
                    logger.error(f"Failed to fetch garden image: {e}")
                    yield f"Could not fetch garden image: {e}. I'll answer based on my gardening knowledge."
                    input_content = [{"role": "user", "content": user_message}]

            if images_data:
                yield f"Uploading {len(images_data)} image(s) to storage..."
                num_images = len(images_data)

                vision_content_parts: List[Dict[str, Any]] = [
                    {"type": "input_text", "text": user_message}
                ]

                for filename, img_bytes in images_data:
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

                    # Label each image so the LLM can reference them by date
                    if filename != "latest.jpg" and num_images > 1:
                        date_label = filename.replace("_", " ").replace(".jpg", "").replace(".jpeg", "").replace(".png", "")
                        vision_content_parts.append({"type": "input_text", "text": f"[Image from {date_label}]"})

                    image_b64 = base64.b64encode(img_bytes).decode("utf-8")
                    image_part = {
                        "type": "input_image",
                        "image_url": f"data:image/jpeg;base64,{image_b64}",
                    }
                    # Save tokens when sending many images
                    if num_images > 2:
                        image_part["detail"] = "low"
                    vision_content_parts.append(image_part)

                input_content = [{"role": "user", "content": vision_content_parts}]
                yield f"Analyzing {num_images} garden image(s) with AI vision..."
        else:
            input_content = [{"role": "user", "content": user_message}]

        # Call the LLM
        kwargs = {
            "model": model,
            "instructions": self._get_agent_instructions(vision_mode=needs_image, num_images=num_images),
            "input": input_content,
            "stream": True,
            "max_output_tokens": 4000,
        }
        if session_id in self._response_ids:
            kwargs["previous_response_id"] = self._response_ids[session_id]

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
                            usage = getattr(resp, "usage", None)
                            if usage:
                                self.last_token_usage = {
                                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) or getattr(usage, "input_tokens", 0),
                                    "completion_tokens": getattr(usage, "completion_tokens", 0) or getattr(usage, "output_tokens", 0),
                                    "total_tokens": getattr(usage, "total_tokens", 0),
                                }
                            resp_id = getattr(resp, "id", None)
                            if resp_id:
                                self._response_ids[session_id] = resp_id

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

    def _should_fetch_image(self, message: str) -> bool:
        """Determine if the user's question requires fetching the garden image."""
        msg_lower = message.lower()
        # Keywords that imply the user wants visual analysis
        image_keywords = [
            "garden", "plant", "look", "how", "check", "water", "see",
            "photo", "image", "picture", "camera", "status", "health",
            "growing", "pest", "disease", "wilt", "yellow", "brown",
            "leaf", "leaves", "flower", "fruit", "vegetable", "weed",
            "soil", "dry", "wet", "sun", "shade", "analyze", "show",
            "what's", "whats", "hows", "how's", "doing", "progress",
            # Temporal / comparison keywords
            "compare", "comparison", "yesterday", "last week", "last month",
            "progression", "over time", "timelapse", "time lapse", "timeline",
            "changed", "changes", "difference", "growth", "trend",
            "days ago", "week ago", "history", "before and after",
        ]
        # If it's a general knowledge question, skip the image
        no_image_keywords = [
            "what is", "define", "explain", "tell me about",
            "recipe", "when to plant", "best time",
            "how to grow", "companion plant", "fertilizer type",
        ]
        for phrase in no_image_keywords:
            if phrase in msg_lower:
                return False
        return any(kw in msg_lower for kw in image_keywords)

    async def run_conversation(self, session_id: str, user_message: str) -> str:
        return "\n".join([r async for r in self.run_conversation_stream(session_id, user_message)])

    async def chat(self, session_id: str, user_message: str) -> str:
        return await self.run_conversation(session_id, user_message)
