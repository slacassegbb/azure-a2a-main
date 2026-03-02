"""
AI Foundry Video & Audio Agent with media editing capabilities.
Uses the Responses API with native MCP tool support to interact with a
remote Video & Audio MCP server (FFmpeg-based).  After the LLM finishes
processing media it calls download_file, and this agent fetches the
resulting file, uploads it to Azure Blob Storage, and exposes it as an
A2A artifact.
"""
import os
import time
import datetime
import asyncio
import logging
import json
import uuid
import tempfile
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import timedelta

import httpx
from openai import AsyncAzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.core.credentials import AzureNamedKeyCredential, AzureSasCredential

logger = logging.getLogger(__name__)

VIDEO_AUDIO_MCP_URL = os.getenv(
    "VIDEO_AUDIO_MCP_URL",
    "https://mcp-video-audio.ambitioussky-6c709152.westus2.azurecontainerapps.io/mcp",
)

# Base URL of the MCP server (for downloading generated files)
_MCP_BASE_URL = VIDEO_AUDIO_MCP_URL.rsplit("/mcp", 1)[0]

# MIME type lookup for video/audio file extensions
_MEDIA_MIME_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".m4v": "video/mp4",
    ".wmv": "video/x-ms-wmv",
    ".flv": "video/x-flv",
    ".srt": "application/x-subrip",
    ".vtt": "text/vtt",
    ".ass": "text/x-ssa",
}

VIDEO_AUDIO_ALLOWED_TOOLS = [
    "download_file",
    "generate_test_media",
    "health_check",
    "extract_audio_from_video",
    "add_audio_to_video",
    "trim_video",
    "convert_video_format",
    "convert_video_properties",
    "change_aspect_ratio",
    "set_video_resolution",
    "set_video_codec",
    "set_video_bitrate",
    "set_video_frame_rate",
    "convert_audio_format",
    "convert_audio_properties",
    "set_audio_bitrate",
    "set_audio_sample_rate",
    "set_audio_channels",
    "set_video_audio_track_codec",
    "set_video_audio_track_bitrate",
    "set_video_audio_track_sample_rate",
    "set_video_audio_track_channels",
    "add_subtitles",
    "add_text_overlay",
    "add_image_overlay",
    "concatenate_videos",
    "change_video_speed",
    "remove_silence",
    "add_b_roll",
    "add_basic_transitions",
]


class FoundryVideoAudioAgent:
    """AI Foundry Agent with Video & Audio capabilities via Responses API."""

    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self._client: Optional[AsyncAzureOpenAI] = None
        self._initialized = False
        self._response_ids: Dict[str, str] = {}
        self.last_token_usage: Optional[Dict[str, int]] = None
        self._latest_artifacts: List[Dict[str, Any]] = []
        self._blob_service_client: Optional[BlobServiceClient] = None
        self._current_context_id: Optional[str] = None
        self._mcp_tool_config = {
            "type": "mcp",
            "server_label": "VideoAudio",
            "server_url": VIDEO_AUDIO_MCP_URL,
            "require_approval": "never",
            "allowed_tools": VIDEO_AUDIO_ALLOWED_TOOLS,
            "headers": {
                "Content-Type": "application/json",
                "User-Agent": "Azure-AI-Foundry-Agent",
                "Accept": "application/json, text/event-stream",
            },
        }

    # ------------------------------------------------------------------
    # Azure Blob Storage helpers
    # ------------------------------------------------------------------

    def _get_blob_service_client(self) -> Optional[BlobServiceClient]:
        force_blob = os.getenv("FORCE_AZURE_BLOB", "false").lower() == "true"
        if not force_blob:
            return None
        if self._blob_service_client is not None:
            return self._blob_service_client
        connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            logger.error("AZURE_STORAGE_CONNECTION_STRING must be set when FORCE_AZURE_BLOB=true")
            raise RuntimeError("Missing AZURE_STORAGE_CONNECTION_STRING for blob uploads")
        try:
            self._blob_service_client = BlobServiceClient.from_connection_string(
                connection_string, api_version="2023-11-03",
            )
            return self._blob_service_client
        except Exception as e:
            logger.error(f"Failed to create BlobServiceClient: {e}")
            raise

    def _upload_to_blob(self, file_path: Path) -> Optional[str]:
        """Upload *file_path* to Azure Blob Storage and return a SAS URL."""
        blob_client = self._get_blob_service_client()
        if not blob_client:
            return None

        container_name = os.getenv("AZURE_BLOB_CONTAINER", "a2a-files")

        file_id = uuid.uuid4().hex
        context_id = self._current_context_id
        if context_id and "::" in context_id:
            session_id = context_id.split("::")[0]
        elif context_id:
            session_id = context_id
        else:
            session_id = "unknown"

        blob_name = f"uploads/{session_id}/{file_id}/{file_path.name}"

        try:
            container_client = blob_client.get_container_client(container_name)
            if not container_client.exists():
                container_client.create_container()
            with open(file_path, "rb") as data:
                container_client.upload_blob(name=blob_name, data=data, overwrite=True)

            sas_duration_minutes = int(os.getenv("AZURE_BLOB_SAS_DURATION_MINUTES", str(24 * 60)))
            sas_token: Optional[str] = None
            service_client = self._blob_service_client

            if service_client is not None:
                credential = getattr(service_client, "credential", None)
                account_key_value: Optional[str] = None

                if isinstance(credential, AzureNamedKeyCredential):
                    account_key_value = credential.key
                elif isinstance(credential, AzureSasCredential):
                    sas_token = credential.signature.lstrip("?")
                elif hasattr(credential, "account_key"):
                    account_key_value = getattr(credential, "account_key")
                elif hasattr(credential, "key"):
                    account_key_value = getattr(credential, "key")

                if callable(account_key_value):
                    account_key_value = account_key_value()
                if isinstance(account_key_value, bytes):
                    account_key_value = account_key_value.decode()

                if account_key_value:
                    try:
                        sas_token = generate_blob_sas(
                            account_name=service_client.account_name,
                            container_name=container_name,
                            blob_name=blob_name,
                            account_key=account_key_value,
                            permission=BlobSasPermissions(read=True),
                            expiry=datetime.datetime.utcnow() + timedelta(minutes=sas_duration_minutes),
                            protocol="https",
                            version="2023-11-03",
                        )
                    except Exception as sas_error:
                        logger.error(f"Failed to generate SAS URL with shared key: {sas_error}")

            if sas_token is None and self._blob_service_client is not None:
                try:
                    delegation_key = self._blob_service_client.get_user_delegation_key(
                        key_start_time=datetime.datetime.utcnow() - timedelta(minutes=5),
                        key_expiry_time=datetime.datetime.utcnow() + timedelta(minutes=sas_duration_minutes),
                    )
                    sas_token = generate_blob_sas(
                        account_name=self._blob_service_client.account_name,
                        container_name=container_name,
                        blob_name=blob_name,
                        user_delegation_key=delegation_key,
                        permission=BlobSasPermissions(read=True),
                        expiry=datetime.datetime.utcnow() + timedelta(minutes=sas_duration_minutes),
                        version="2023-11-03",
                    )
                except Exception as ude_err:
                    logger.warning(f"Failed to generate user delegation SAS: {ude_err}")

            if sas_token:
                base_url = blob_client.get_blob_client(container=container_name, blob=blob_name).url
                token = sas_token.lstrip("?")
                separator = "&" if "?" in base_url else "?"
                return f"{base_url}{separator}{token}"

            raise RuntimeError("Unable to generate SAS token; verify storage credentials")
        except Exception as e:
            logger.error(f"Failed to upload {file_path} to blob storage: {e}")
            return None

    def pop_latest_artifacts(self) -> List[Dict[str, Any]]:
        artifacts = self._latest_artifacts
        self._latest_artifacts = []
        return artifacts

    # ------------------------------------------------------------------
    # Media file download helper
    # ------------------------------------------------------------------

    async def _download_media_file(self, download_path: str, filename: str) -> Optional[Path]:
        """Download a media file from the MCP server and return the local Path."""
        url = f"{_MCP_BASE_URL}{download_path}"
        logger.info(f"Downloading media file from {url}")
        try:
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                tmp_dir = Path(tempfile.gettempdir()) / "video_audio_agent"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                local_path = tmp_dir / filename
                local_path.write_bytes(resp.content)
                logger.info(f"Saved media file to {local_path} ({len(resp.content)} bytes)")
                return local_path
        except Exception as e:
            logger.error(f"Failed to download media file: {e}")
            return None

    @staticmethod
    def _get_mime_type(filename: str) -> str:
        """Determine MIME type from file extension."""
        ext = Path(filename).suffix.lower()
        return _MEDIA_MIME_TYPES.get(ext, "application/octet-stream")

    # ------------------------------------------------------------------
    # OpenAI / Azure client
    # ------------------------------------------------------------------

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

    async def create_agent(self) -> None:
        if self._initialized:
            return
        logger.info("Initializing Video & Audio agent (Responses API)...")
        try:
            base_url = _MCP_BASE_URL
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{base_url}/health")
                logger.info(f"MCP Server status: {response.status_code}")
        except Exception as e:
            logger.warning(f"MCP Server health check failed: {e} (continuing anyway)")
        self._get_client()
        self._initialized = True

    def _get_agent_instructions(self) -> str:
        return f"""You are a professional video and audio editing assistant.
You have access to a comprehensive set of FFmpeg-powered MCP tools that let you
process, convert, trim, merge, and transform video and audio files.

## Receiving Input Files

Input files are provided as URLs (typically Azure Blob Storage SAS URLs from other
agents like Sora Video Generator or Music Generator). When you receive a file URL,
pass it directly to the appropriate MCP tool as the input path — the MCP server
can download files from URLs.

## Processing Workflow

1. Analyze the user's request and determine which FFmpeg operation(s) to apply
2. Call the appropriate MCP tool(s) with the input file URL and desired parameters
3. After processing, call `download_file` to stage the output file for download
4. The system automatically handles file upload to Azure Blob Storage and delivery

## Available Operations

**Video Processing:**
- `trim_video` — Cut a segment from a video (start/end timestamps)
- `convert_video_format` — Convert between formats (mp4, mov, avi, mkv, webm)
- `convert_video_properties` — Change multiple video properties at once
- `change_aspect_ratio` — Change aspect ratio (16:9, 4:3, 1:1, 9:16, etc.)
- `set_video_resolution` — Resize video (1920x1080, 1280x720, etc.)
- `set_video_codec` — Change codec (h264, h265, vp9, etc.)
- `set_video_bitrate` — Adjust quality/file size
- `set_video_frame_rate` — Change FPS (24, 30, 60, etc.)
- `change_video_speed` — Speed up or slow down video
- `concatenate_videos` — Join multiple videos together
- `add_subtitles` — Burn subtitles into video (.srt, .vtt, .ass)
- `add_text_overlay` — Add text directly on video
- `add_image_overlay` — Add image watermark/overlay
- `add_b_roll` — Insert B-roll footage
- `add_basic_transitions` — Add transitions between clips

**Combining Audio + Video:**
- `add_audio_to_video` — Add an audio file (music, voiceover) to a video.
  Use mode='replace' (default) to set the audio track, or mode='mix' to blend
  with existing audio. This is the PRIMARY tool for adding background music.

**Audio Processing:**
- `extract_audio_from_video` — Extract audio track from video
- `convert_audio_format` — Convert between formats (mp3, wav, aac, ogg, flac)
- `convert_audio_properties` — Change multiple audio properties at once
- `set_audio_bitrate` — Adjust audio quality
- `set_audio_sample_rate` — Change sample rate (44100, 48000, etc.)
- `set_audio_channels` — Set mono/stereo
- `remove_silence` — Remove silent sections from audio

**Video Audio Track:**
- `set_video_audio_track_codec` — Change audio codec in video
- `set_video_audio_track_bitrate` — Adjust audio bitrate in video
- `set_video_audio_track_sample_rate` — Change audio sample rate in video
- `set_video_audio_track_channels` — Set audio channels in video

## Important Rules

- ALWAYS call `download_file` after processing to stage the output for delivery.
  The `download_file` tool takes the path to the processed file and returns a
  `download_url` that the system uses to fetch the result.
- Prefer action over asking. If the request is clear enough to produce a result,
  make assumptions and proceed immediately rather than asking for details.
- Only use NEEDS_INPUT when genuinely critical information is missing.
- For format conversions, default to widely-compatible formats (mp4/h264 for video,
  mp3 for audio) unless the user specifies otherwise.

## File References in Output (CRITICAL)

NEVER mention local file paths (e.g. `/tmp/...`), sandbox paths, or MCP server URLs
in your text response. Simply describe what processing was done and the result.
The system automatically handles file delivery via Azure Blob Storage URIs.

## Error Reporting (CRITICAL)

If you CANNOT complete the requested task, you MUST start your response with "Error:".
Examples:
- "Error: Rate limit exceeded. Please try again later."
- "Error: The input file format is not supported."
- "Error: Could not process the video due to a service outage."

Current date: {datetime.datetime.now().isoformat()}

## NEEDS_INPUT - Human-in-the-Loop

Use NEEDS_INPUT to pause and ask the user a question:

```NEEDS_INPUT
Your question here
```END_NEEDS_INPUT
"""

    async def create_session(self) -> str:
        return f"session_{int(time.time())}_{os.urandom(4).hex()}"

    async def run_conversation_stream(self, session_id: str, user_message: str, context_id: Optional[str] = None):
        if not self._initialized:
            await self.create_agent()

        if context_id:
            self._current_context_id = context_id

        client = self._get_client()
        model = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")

        kwargs = {
            "model": model,
            "instructions": self._get_agent_instructions(),
            "input": [{"role": "user", "content": user_message}],
            "tools": [self._mcp_tool_config],
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
                text_chunks: List[str] = []
                tool_calls_seen: set = set()
                mcp_failures: List[str] = []
                download_info: Optional[Dict[str, Any]] = None

                logger.info("Stream started — iterating events...")
                async for event in response:
                    event_type = getattr(event, "type", None)
                    if event_type != "response.output_text.delta":
                        logger.info(f"[STREAM] event_type={event_type}")

                    if event_type == "response.output_text.delta":
                        text_chunks.append(event.delta)

                    elif event_type == "response.mcp_call.in_progress":
                        tool_name = getattr(event, "name", "mcp_tool")
                        if tool_name not in tool_calls_seen:
                            tool_calls_seen.add(tool_name)
                            yield f"\U0001f6e0\ufe0f Remote agent executing: {self._get_tool_description(tool_name)}"

                    elif event_type == "response.mcp_call.completed":
                        # Capture download_file result
                        item = getattr(event, "item", None) or event
                        tool_name = getattr(item, "name", None) or getattr(event, "name", None)
                        if tool_name == "download_file":
                            output = getattr(item, "output", None) or getattr(event, "output", None)
                            if output:
                                try:
                                    data = json.loads(output) if isinstance(output, str) else output
                                    if isinstance(data, dict) and data.get("download_url"):
                                        download_info = data
                                        logger.info(f"Captured download_file result: {data}")
                                except (json.JSONDecodeError, TypeError):
                                    pass

                    elif event_type == "response.mcp_call.failed":
                        tool_name = getattr(event, "name", None) or getattr(event, "item_id", "mcp_tool")
                        mcp_failures.append(tool_name)

                    elif event_type == "response.failed":
                        resp = getattr(event, "response", None)
                        error_obj = getattr(resp, "error", None) if resp else None
                        yield f"Error: {getattr(error_obj, 'message', 'Unknown error') if error_obj else 'Unknown error'}"
                        return

                    elif event_type == "response.output_item.added":
                        item = getattr(event, "item", None)
                        if item and getattr(item, "type", None) in ("mcp_call", "mcp_tool_call"):
                            tool_name = getattr(item, "name", None) or getattr(item, "tool_name", "mcp_tool")
                            if tool_name not in tool_calls_seen:
                                tool_calls_seen.add(tool_name)
                                yield f"\U0001f6e0\ufe0f Remote agent executing: {self._get_tool_description(tool_name)}"

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

                            # Fallback: scan response output items for download_file result
                            if download_info is None:
                                output_items = getattr(resp, "output", None) or []
                                for out_item in output_items:
                                    item_type = getattr(out_item, "type", None)
                                    if item_type in ("mcp_call", "mcp_tool_call"):
                                        name = getattr(out_item, "name", None)
                                        if name == "download_file":
                                            raw = getattr(out_item, "output", None)
                                            if raw:
                                                try:
                                                    data = json.loads(raw) if isinstance(raw, str) else raw
                                                    if isinstance(data, dict) and data.get("download_url"):
                                                        download_info = data
                                                        logger.info(f"Captured download info from response output: {data}")
                                                except (json.JSONDecodeError, TypeError):
                                                    pass

                # ---- Post-stream: handle file download + blob upload ----
                logger.info(f"Stream finished. text_chunks={len(text_chunks)}, tools_seen={tool_calls_seen}, download_info={download_info}, mcp_failures={mcp_failures}")
                if download_info and download_info.get("download_url"):
                    filename = download_info.get("filename", "output.mp4")
                    local_path = await self._download_media_file(
                        download_info["download_url"], filename
                    )
                    if local_path and local_path.exists():
                        blob_url = self._upload_to_blob(local_path)
                        if blob_url:
                            mime_type = self._get_mime_type(filename)
                            artifact: Dict[str, Any] = {
                                "artifact-uri": blob_url,
                                "file-name": filename,
                                "mime": mime_type,
                                "storage-type": "azure_blob",
                                "status": "stored",
                                "file-size": local_path.stat().st_size,
                            }
                            self._latest_artifacts.append(artifact)
                            logger.info(f"Created media artifact: {filename} -> {blob_url[:80]}...")
                        else:
                            logger.warning("Blob upload failed; artifact not created")
                    else:
                        logger.warning("Media file download failed; artifact not created")

                if text_chunks:
                    full_text = "".join(text_chunks)
                    # Append blob URI so downstream agents get the real file reference
                    if self._latest_artifacts:
                        blob_uri = self._latest_artifacts[-1].get("artifact-uri", "")
                        file_name = self._latest_artifacts[-1].get("file-name", "output.mp4")
                        if blob_uri:
                            full_text = full_text.rstrip() + f"\n\nFile: {file_name} ({blob_uri})"
                    if mcp_failures:
                        yield f"Error: MCP tool(s) failed ({', '.join(mcp_failures)}). {full_text}"
                    else:
                        yield full_text
                else:
                    yield "Error: Agent completed but no response text was generated"
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
                    yield f"Error: Rate limit exceeded after {max_retries} retries"
                else:
                    yield f"Error: {e}"
                return

    def _get_tool_description(self, tool_name: str) -> str:
        descriptions = {
            "download_file": "Download File",
            "generate_test_media": "Generate Test Media",
            "health_check": "Health Check",
            "extract_audio_from_video": "Extract Audio",
            "trim_video": "Trim Video",
            "convert_video_format": "Convert Video Format",
            "convert_video_properties": "Convert Video Properties",
            "change_aspect_ratio": "Change Aspect Ratio",
            "set_video_resolution": "Set Video Resolution",
            "set_video_codec": "Set Video Codec",
            "set_video_bitrate": "Set Video Bitrate",
            "set_video_frame_rate": "Set Frame Rate",
            "convert_audio_format": "Convert Audio Format",
            "convert_audio_properties": "Convert Audio Properties",
            "set_audio_bitrate": "Set Audio Bitrate",
            "set_audio_sample_rate": "Set Sample Rate",
            "set_audio_channels": "Set Audio Channels",
            "set_video_audio_track_codec": "Set Audio Track Codec",
            "set_video_audio_track_bitrate": "Set Audio Track Bitrate",
            "set_video_audio_track_sample_rate": "Set Audio Track Sample Rate",
            "set_video_audio_track_channels": "Set Audio Track Channels",
            "add_subtitles": "Add Subtitles",
            "add_text_overlay": "Add Text Overlay",
            "add_image_overlay": "Add Image Overlay",
            "concatenate_videos": "Concatenate Videos",
            "change_video_speed": "Change Video Speed",
            "remove_silence": "Remove Silence",
            "add_b_roll": "Add B-Roll",
            "add_basic_transitions": "Add Transitions",
        }
        return descriptions.get(tool_name, tool_name.replace("_", " ").title())

    async def run_conversation(self, session_id: str, user_message: str) -> str:
        return "\n".join([r async for r in self.run_conversation_stream(session_id, user_message)])

    async def chat(self, session_id: str, user_message: str) -> str:
        return await self.run_conversation(session_id, user_message)
