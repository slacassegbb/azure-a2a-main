"""
AI Foundry Music Agent with Suno API capabilities.
Uses the Responses API with function tools for music generation,
lyrics creation, audio processing, and more via the Suno API.
Generated audio files are uploaded to Azure Blob Storage and
returned as A2A artifacts.
"""
import os
import json
import time
import uuid
import asyncio
import logging
import tempfile
import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import timedelta

import httpx
from openai import AsyncAzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.core.credentials import AzureNamedKeyCredential, AzureSasCredential

logger = logging.getLogger(__name__)

SUNO_API_BASE = "https://api.sunoapi.org/api/v1"
DEFAULT_MODEL = "V4_5ALL"
POLL_INTERVAL = 15  # seconds between status checks
MAX_POLL_TIME = 420  # 7 minutes max wait


class FoundryMusicAgent:
    """AI Foundry Agent with Suno API music capabilities via Responses API."""

    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self._client: Optional[AsyncAzureOpenAI] = None
        self._initialized = False
        self._response_ids: Dict[str, str] = {}
        self.last_token_usage: Optional[Dict[str, int]] = None
        self._suno_api_key = os.environ.get("SUNO_API_KEY", "")
        self._blob_service_client: Optional[BlobServiceClient] = None
        self._latest_artifacts: List[Dict[str, Any]] = []
        self._current_context_id: Optional[str] = None
        self._http_client: Optional[httpx.AsyncClient] = None

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

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=60.0)
        return self._http_client

    def _suno_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._suno_api_key}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Blob storage
    # ------------------------------------------------------------------

    def _get_blob_service_client(self) -> Optional[BlobServiceClient]:
        force_blob = os.getenv("FORCE_AZURE_BLOB", "false").lower() == "true"
        if not force_blob:
            return None
        if self._blob_service_client is not None:
            return self._blob_service_client
        connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            raise RuntimeError("Missing AZURE_STORAGE_CONNECTION_STRING for blob uploads")
        self._blob_service_client = BlobServiceClient.from_connection_string(
            connection_string, api_version="2023-11-03",
        )
        return self._blob_service_client

    def _upload_to_blob(self, file_path: Path) -> Optional[str]:
        blob_client = self._get_blob_service_client()
        if not blob_client:
            return None
        container_name = os.getenv("AZURE_BLOB_CONTAINER", "a2a-files")

        file_id = uuid.uuid4().hex
        context_id = self._current_context_id
        session_id = None
        if context_id and "::" in context_id:
            session_id = context_id.split("::")[0]
        elif context_id:
            session_id = context_id

        if session_id:
            blob_name = f"uploads/{session_id}/{file_id}/{file_path.name}"
        else:
            blob_name = f"music-generator/{file_id}/{file_path.name}"

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

            if sas_token is None and self._blob_service_client is not None:
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

            if sas_token:
                base_url = blob_client.get_blob_client(container=container_name, blob=blob_name).url
                token = sas_token.lstrip("?")
                separator = "&" if "?" in base_url else "?"
                return f"{base_url}{separator}{token}"

            raise RuntimeError("Unable to generate SAS token; verify storage credentials")
        except Exception as e:
            logger.error(f"Failed to upload {file_path} to blob storage: {e}")
            return None

    # ------------------------------------------------------------------
    # Artifact management
    # ------------------------------------------------------------------

    def pop_latest_artifacts(self) -> List[Dict[str, Any]]:
        artifacts = self._latest_artifacts
        self._latest_artifacts = []
        return artifacts

    def _create_artifact(self, blob_url: str, filename: str, mime: str, file_size: int = 0):
        artifact = {
            "artifact-uri": blob_url,
            "file-name": filename,
            "mime": mime,
            "storage-type": "azure_blob",
            "status": "stored",
            "file-size": file_size,
        }
        self._latest_artifacts.append(artifact)
        logger.info(f"Created artifact: {filename} -> {blob_url[:80]}...")

    # ------------------------------------------------------------------
    # Download helpers
    # ------------------------------------------------------------------

    async def _download_file(self, url: str, filename: str) -> Optional[Path]:
        tmp_dir = Path(tempfile.gettempdir()) / "music_agent"
        tmp_dir.mkdir(exist_ok=True)
        local_path = tmp_dir / filename
        try:
            client = await self._get_http_client()
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            local_path.write_bytes(resp.content)
            logger.info(f"Downloaded {filename} ({len(resp.content)} bytes)")
            return local_path
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            return None

    async def _download_and_store(self, url: str, filename: str, mime: str) -> Optional[str]:
        """Download a file, upload to blob, create artifact, return blob URL."""
        local_path = await self._download_file(url, filename)
        if not local_path:
            # Download failed — still create artifact with original URL
            logger.warning(f"Download failed for {filename}, creating artifact with original URL")
            self._create_artifact(url, filename, mime)
            return url
        file_size = local_path.stat().st_size
        blob_url = self._upload_to_blob(local_path)
        if blob_url:
            self._create_artifact(blob_url, filename, mime, file_size)
            return blob_url
        # Blob upload failed — still create artifact with original URL
        logger.warning(f"Blob upload failed for {filename}, creating artifact with original URL")
        self._create_artifact(url, filename, mime, file_size)
        return url

    # ------------------------------------------------------------------
    # Suno API helpers
    # ------------------------------------------------------------------

    async def _suno_post(self, path: str, payload: dict) -> dict:
        client = await self._get_http_client()
        url = f"{SUNO_API_BASE}{path}"
        resp = await client.post(url, headers=self._suno_headers(), json=payload)
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(f"Suno API error ({path}): {data.get('msg', 'Unknown error')} (code {data.get('code')})")
        return data

    async def _suno_get(self, path: str, params: dict = None) -> dict:
        client = await self._get_http_client()
        url = f"{SUNO_API_BASE}{path}"
        resp = await client.get(url, headers=self._suno_headers(), params=params)
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(f"Suno API error ({path}): {data.get('msg', 'Unknown error')} (code {data.get('code')})")
        return data

    async def _poll_task(self, task_id: str, poll_path: str = "/generate/record-info") -> dict:
        """Poll a Suno task until completion or timeout."""
        start = time.time()
        while time.time() - start < MAX_POLL_TIME:
            data = await self._suno_get(poll_path, {"taskId": task_id})
            status = data.get("data", {}).get("status", "")
            if status == "SUCCESS":
                return data["data"]
            if status in ("FAILED", "CREATE_TASK_FAILED", "GENERATE_AUDIO_FAILED",
                          "CALLBACK_EXCEPTION", "SENSITIVE_WORD_ERROR"):
                error_msg = data.get("data", {}).get("errorMessage", status)
                raise RuntimeError(f"Task {task_id} failed: {error_msg}")
            await asyncio.sleep(POLL_INTERVAL)
        raise RuntimeError(f"Task {task_id} timed out after {MAX_POLL_TIME}s")

    def _extract_tracks(self, task_data: dict) -> List[dict]:
        """Extract track list from Suno task data, checking multiple response shapes."""
        resp = task_data.get("response", {})

        # Shape 1 (actual API): task_data["response"]["sunoData"]
        if isinstance(resp, dict):
            tracks = resp.get("sunoData", [])
            if tracks and isinstance(tracks, list):
                logger.info(f"Found {len(tracks)} track(s) in response.sunoData")
                return tracks

        # Shape 2 (documented): task_data["response"]["data"]
        if isinstance(resp, dict):
            tracks = resp.get("data", [])
            if tracks and isinstance(tracks, list):
                logger.info(f"Found {len(tracks)} track(s) in response.data")
                return tracks

        # Shape 3: response is a list directly
        if isinstance(resp, list):
            logger.info(f"Found {len(resp)} track(s) in response (list)")
            return resp

        # Shape 4: task_data["data"] (flat)
        tracks = task_data.get("data", [])
        if isinstance(tracks, list) and tracks and isinstance(tracks[0], dict):
            if any(k in tracks[0] for k in ("audioUrl", "audio_url")):
                logger.info(f"Found {len(tracks)} track(s) in task_data.data")
                return tracks

        # Debug: log what we actually received
        logger.warning(f"Could not find tracks in task_data. Keys: {list(task_data.keys())}")
        if isinstance(resp, dict):
            logger.warning(f"  response keys: {list(resp.keys())}")
        else:
            logger.warning(f"  response type: {type(resp)}, value: {str(resp)[:300]}")
        return []

    async def _process_audio_results(self, task_data: dict) -> List[dict]:
        """Download audio tracks from a completed task and store as artifacts."""
        response_data = self._extract_tracks(task_data)
        logger.info(f"Processing {len(response_data)} track(s) from Suno response")
        results = []
        for i, track in enumerate(response_data):
            # Suno API uses camelCase: audioUrl, imageUrl, sourceAudioUrl
            audio_url = track.get("audioUrl") or track.get("audio_url") or track.get("sourceAudioUrl", "")
            title = track.get("title", f"track_{i+1}")
            duration = track.get("duration", 0)
            tags = track.get("tags", "")
            track_id = track.get("id", "")
            image_url = track.get("imageUrl") or track.get("image_url") or track.get("sourceImageUrl", "")
            safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in title)
            filename = f"{safe_title}.mp3"

            logger.info(f"Track {i+1}: title={title}, audio_url={audio_url[:80] if audio_url else 'EMPTY'}")

            blob_url = None
            if audio_url:
                blob_url = await self._download_and_store(audio_url, filename, "audio/mpeg")

            results.append({
                "track_id": track_id,
                "title": title,
                "duration": duration,
                "tags": tags,
                "audio_url": blob_url or audio_url,
                "image_url": image_url,
            })
        return results

    # ------------------------------------------------------------------
    # Function tool implementations
    # ------------------------------------------------------------------

    async def _execute_function(self, name: str, args: dict) -> dict:
        """Route a function call to the appropriate Suno API handler."""
        handlers = {
            "generate_music": self._fn_generate_music,
            "generate_lyrics": self._fn_generate_lyrics,
            "extend_music": self._fn_extend_music,
            "replace_section": self._fn_replace_section,
            "upload_and_cover": self._fn_upload_and_cover,
            "upload_and_extend": self._fn_upload_and_extend,
            "mashup": self._fn_mashup,
            "vocal_separation": self._fn_vocal_separation,
            "add_instrumental": self._fn_add_instrumental,
            "add_vocals": self._fn_add_vocals,
            "convert_to_wav": self._fn_convert_to_wav,
            "generate_midi": self._fn_generate_midi,
            "create_music_video": self._fn_create_music_video,
            "generate_cover_art": self._fn_generate_cover_art,
            "generate_persona": self._fn_generate_persona,
            "boost_style": self._fn_boost_style,
            "get_credits": self._fn_get_credits,
            "check_task_status": self._fn_check_task_status,
            "get_timestamped_lyrics": self._fn_get_timestamped_lyrics,
        }
        handler = handlers.get(name)
        if not handler:
            return {"error": f"Unknown function: {name}"}
        try:
            return await handler(args)
        except Exception as e:
            logger.error(f"Function {name} failed: {e}")
            return {"error": str(e)}

    async def _fn_generate_music(self, args: dict) -> dict:
        payload = {
            "prompt": args.get("prompt", ""),
            "customMode": args.get("custom_mode", False),
            "instrumental": args.get("instrumental", False),
            "model": args.get("model", DEFAULT_MODEL),
            "callBackUrl": "https://example.com/noop",
        }
        if args.get("style"):
            payload["style"] = args["style"]
        if args.get("title"):
            payload["title"] = args["title"]
        if args.get("negative_tags"):
            payload["negativeTags"] = args["negative_tags"]
        if args.get("vocal_gender"):
            payload["vocalGender"] = args["vocal_gender"]

        data = await self._suno_post("/generate", payload)
        task_id = data["data"]["taskId"]
        logger.info(f"Music generation started: {task_id}")

        task_data = await self._poll_task(task_id)
        logger.info(f"Poll completed. task_data keys: {list(task_data.keys()) if isinstance(task_data, dict) else type(task_data)}")
        tracks = await self._process_audio_results(task_data)
        logger.info(f"Processed {len(tracks)} track(s), artifacts pending: {len(self._latest_artifacts)}")
        return {"status": "success", "task_id": task_id, "tracks": tracks}

    async def _fn_generate_lyrics(self, args: dict) -> dict:
        payload = {
            "prompt": args.get("prompt", ""),
            "callBackUrl": "https://example.com/noop",
        }
        data = await self._suno_post("/lyrics", payload)
        task_id = data["data"]["taskId"]

        task_data = await self._poll_task(task_id, "/lyrics/record-info")
        lyrics_list = task_data.get("response", {}).get("data", [])
        results = []
        for lyric in lyrics_list:
            results.append({
                "title": lyric.get("title", ""),
                "text": lyric.get("text", ""),
                "status": lyric.get("status", ""),
            })
        return {"status": "success", "task_id": task_id, "lyrics": results}

    async def _fn_extend_music(self, args: dict) -> dict:
        payload = {
            "audioId": args["audio_id"],
            "defaultParamFlag": args.get("default_params", True),
            "model": args.get("model", DEFAULT_MODEL),
            "callBackUrl": "https://example.com/noop",
        }
        if args.get("prompt"):
            payload["prompt"] = args["prompt"]
        if args.get("style"):
            payload["style"] = args["style"]
        if args.get("title"):
            payload["title"] = args["title"]
        if args.get("continue_at") is not None:
            payload["continueAt"] = args["continue_at"]

        data = await self._suno_post("/generate/extend", payload)
        task_id = data["data"]["taskId"]
        task_data = await self._poll_task(task_id)
        tracks = await self._process_audio_results(task_data)
        return {"status": "success", "task_id": task_id, "tracks": tracks}

    async def _fn_replace_section(self, args: dict) -> dict:
        payload = {
            "taskId": args["task_id"],
            "audioId": args["audio_id"],
            "prompt": args.get("prompt", ""),
            "tags": args.get("tags", ""),
            "title": args.get("title", ""),
            "infillStartS": args["start_time"],
            "infillEndS": args["end_time"],
        }
        if args.get("negative_tags"):
            payload["negativeTags"] = args["negative_tags"]
        payload["callBackUrl"] = "https://example.com/noop"

        data = await self._suno_post("/generate/replace-section", payload)
        task_id = data["data"]["taskId"]
        task_data = await self._poll_task(task_id)
        tracks = await self._process_audio_results(task_data)
        return {"status": "success", "task_id": task_id, "tracks": tracks}

    async def _fn_upload_and_cover(self, args: dict) -> dict:
        payload = {
            "uploadUrl": args["upload_url"],
            "customMode": args.get("custom_mode", False),
            "instrumental": args.get("instrumental", False),
            "model": args.get("model", DEFAULT_MODEL),
            "callBackUrl": "https://example.com/noop",
        }
        if args.get("prompt"):
            payload["prompt"] = args["prompt"]
        if args.get("style"):
            payload["style"] = args["style"]
        if args.get("title"):
            payload["title"] = args["title"]

        data = await self._suno_post("/generate/upload-cover", payload)
        task_id = data["data"]["taskId"]
        task_data = await self._poll_task(task_id)
        tracks = await self._process_audio_results(task_data)
        return {"status": "success", "task_id": task_id, "tracks": tracks}

    async def _fn_upload_and_extend(self, args: dict) -> dict:
        payload = {
            "uploadUrl": args["upload_url"],
            "defaultParamFlag": args.get("default_params", True),
            "model": args.get("model", DEFAULT_MODEL),
            "callBackUrl": "https://example.com/noop",
        }
        if args.get("prompt"):
            payload["prompt"] = args["prompt"]
        if args.get("style"):
            payload["style"] = args["style"]
        if args.get("title"):
            payload["title"] = args["title"]
        if args.get("continue_at") is not None:
            payload["continueAt"] = args["continue_at"]
        if args.get("instrumental") is not None:
            payload["instrumental"] = args["instrumental"]

        data = await self._suno_post("/generate/upload-extend", payload)
        task_id = data["data"]["taskId"]
        task_data = await self._poll_task(task_id)
        tracks = await self._process_audio_results(task_data)
        return {"status": "success", "task_id": task_id, "tracks": tracks}

    async def _fn_mashup(self, args: dict) -> dict:
        payload = {
            "uploadUrlList": args["upload_urls"],
            "customMode": args.get("custom_mode", False),
            "model": args.get("model", DEFAULT_MODEL),
            "callBackUrl": "https://example.com/noop",
        }
        if args.get("prompt"):
            payload["prompt"] = args["prompt"]
        if args.get("style"):
            payload["style"] = args["style"]
        if args.get("title"):
            payload["title"] = args["title"]
        if args.get("instrumental") is not None:
            payload["instrumental"] = args["instrumental"]

        data = await self._suno_post("/generate/mashup", payload)
        task_id = data["data"]["taskId"]
        task_data = await self._poll_task(task_id)
        tracks = await self._process_audio_results(task_data)
        return {"status": "success", "task_id": task_id, "tracks": tracks}

    async def _fn_vocal_separation(self, args: dict) -> dict:
        payload = {
            "taskId": args["task_id"],
            "audioId": args["audio_id"],
            "callBackUrl": "https://example.com/noop",
        }
        if args.get("type"):
            payload["type"] = args["type"]

        data = await self._suno_post("/vocal-removal/generate", payload)
        sep_task_id = data["data"]["taskId"]
        task_data = await self._poll_task(sep_task_id, "/vocal-removal/record-info")

        resp = task_data.get("response", {})
        vocal_info = resp.get("vocal_removal_info") or resp.get("vocalRemovalInfo", {})
        results = {}
        vocal_url = vocal_info.get("vocalUrl") or vocal_info.get("vocal_url", "")
        if vocal_url:
            blob = await self._download_and_store(vocal_url, "vocals.mp3", "audio/mpeg")
            results["vocal_url"] = blob or vocal_url
        instrumental_url = vocal_info.get("instrumentalUrl") or vocal_info.get("instrumental_url", "")
        if instrumental_url:
            blob = await self._download_and_store(instrumental_url, "instrumental.mp3", "audio/mpeg")
            results["instrumental_url"] = blob or instrumental_url
        # stem separation may include additional URLs (both camelCase and snake_case)
        stem_keys = {
            "drums": ("drumsUrl", "drums_url"),
            "bass": ("bassUrl", "bass_url"),
            "guitar": ("guitarUrl", "guitar_url"),
            "keyboard": ("keyboardUrl", "keyboard_url"),
            "strings": ("stringsUrl", "strings_url"),
            "brass": ("brassUrl", "brass_url"),
            "woodwinds": ("woodwindsUrl", "woodwinds_url"),
            "percussion": ("percussionUrl", "percussion_url"),
            "synth": ("synthUrl", "synth_url"),
            "fx": ("fxUrl", "fx_url"),
            "backing_vocals": ("backingVocalsUrl", "backing_vocals_url"),
        }
        for stem_name, (camel_key, snake_key) in stem_keys.items():
            url = vocal_info.get(camel_key) or vocal_info.get(snake_key, "")
            if url:
                blob = await self._download_and_store(url, f"{stem_name}.mp3", "audio/mpeg")
                results[f"{stem_name}_url"] = blob or url

        return {"status": "success", "task_id": sep_task_id, "stems": results}

    async def _fn_add_instrumental(self, args: dict) -> dict:
        payload = {
            "uploadUrl": args["upload_url"],
            "title": args.get("title", ""),
            "tags": args.get("tags", ""),
            "negativeTags": args.get("negative_tags", ""),
            "callBackUrl": "https://example.com/noop",
        }
        if args.get("model"):
            payload["model"] = args["model"]
        if args.get("vocal_gender"):
            payload["vocalGender"] = args["vocal_gender"]

        data = await self._suno_post("/generate/add-instrumental", payload)
        task_id = data["data"]["taskId"]
        task_data = await self._poll_task(task_id)
        tracks = await self._process_audio_results(task_data)
        return {"status": "success", "task_id": task_id, "tracks": tracks}

    async def _fn_add_vocals(self, args: dict) -> dict:
        payload = {
            "uploadUrl": args["upload_url"],
            "prompt": args.get("prompt", ""),
            "title": args.get("title", ""),
            "style": args.get("style", ""),
            "negativeTags": args.get("negative_tags", ""),
            "callBackUrl": "https://example.com/noop",
        }
        if args.get("model"):
            payload["model"] = args["model"]
        if args.get("vocal_gender"):
            payload["vocalGender"] = args["vocal_gender"]

        data = await self._suno_post("/generate/add-vocals", payload)
        task_id = data["data"]["taskId"]
        task_data = await self._poll_task(task_id)
        tracks = await self._process_audio_results(task_data)
        return {"status": "success", "task_id": task_id, "tracks": tracks}

    async def _fn_convert_to_wav(self, args: dict) -> dict:
        payload = {
            "taskId": args["task_id"],
            "audioId": args["audio_id"],
            "callBackUrl": "https://example.com/noop",
        }
        data = await self._suno_post("/wav/generate", payload)
        wav_task_id = data["data"]["taskId"]
        task_data = await self._poll_task(wav_task_id, "/wav/record-info")

        resp = task_data.get("response", {})
        wav_url = resp.get("audioWavUrl") or resp.get("audio_wav_url", "")
        if wav_url:
            blob = await self._download_and_store(wav_url, "converted.wav", "audio/wav")
            return {"status": "success", "task_id": wav_task_id, "wav_url": blob or wav_url}
        return {"status": "success", "task_id": wav_task_id, "message": "WAV conversion submitted", "data": resp}

    async def _fn_generate_midi(self, args: dict) -> dict:
        payload = {
            "taskId": args["task_id"],
            "callBackUrl": "https://example.com/noop",
        }
        if args.get("audio_id"):
            payload["audioId"] = args["audio_id"]

        data = await self._suno_post("/midi/generate", payload)
        midi_task_id = data["data"]["taskId"]
        task_data = await self._poll_task(midi_task_id, "/midi/record-info")

        resp = task_data.get("response", {})
        midi_url = resp.get("midiUrl") or resp.get("midi_url", "")
        if midi_url:
            blob = await self._download_and_store(midi_url, "output.mid", "audio/midi")
            return {"status": "success", "task_id": midi_task_id, "midi_url": blob or midi_url}
        return {"status": "success", "task_id": midi_task_id, "data": resp}

    async def _fn_create_music_video(self, args: dict) -> dict:
        payload = {
            "taskId": args["task_id"],
            "audioId": args["audio_id"],
            "callBackUrl": "https://example.com/noop",
        }
        if args.get("author"):
            payload["author"] = args["author"]
        if args.get("domain_name"):
            payload["domainName"] = args["domain_name"]

        data = await self._suno_post("/mp4/generate", payload)
        video_task_id = data["data"]["taskId"]
        task_data = await self._poll_task(video_task_id, "/mp4/record-info")

        resp = task_data.get("response", {})
        video_url = resp.get("videoUrl") or resp.get("video_url", "")
        if video_url:
            blob = await self._download_and_store(video_url, "music_video.mp4", "video/mp4")
            return {"status": "success", "task_id": video_task_id, "video_url": blob or video_url}
        return {"status": "success", "task_id": video_task_id, "data": resp}

    async def _fn_generate_cover_art(self, args: dict) -> dict:
        payload = {
            "taskId": args["task_id"],
            "callBackUrl": "https://example.com/noop",
        }
        data = await self._suno_post("/suno/cover/generate", payload)
        cover_task_id = data["data"]["taskId"]
        task_data = await self._poll_task(cover_task_id, "/suno/cover/record-info")

        images = task_data.get("response", {}).get("images", [])
        results = []
        for i, img_url in enumerate(images):
            blob = await self._download_and_store(img_url, f"cover_{i+1}.png", "image/png")
            results.append(blob or img_url)
        return {"status": "success", "task_id": cover_task_id, "cover_images": results}

    async def _fn_generate_persona(self, args: dict) -> dict:
        payload = {
            "taskId": args["task_id"],
            "audioId": args["audio_id"],
            "name": args["name"],
            "description": args.get("description", ""),
        }
        if args.get("vocal_start") is not None:
            payload["vocalStart"] = args["vocal_start"]
        if args.get("vocal_end") is not None:
            payload["vocalEnd"] = args["vocal_end"]
        if args.get("style"):
            payload["style"] = args["style"]

        data = await self._suno_post("/generate/generate-persona", payload)
        persona = data.get("data", {})
        return {
            "status": "success",
            "persona_id": persona.get("personaId", ""),
            "name": persona.get("name", ""),
            "description": persona.get("description", ""),
        }

    async def _fn_boost_style(self, args: dict) -> dict:
        payload = {"content": args.get("content", "")}
        data = await self._suno_post("/style/generate", payload)
        return {"status": "success", "style_text": data.get("data", {}).get("text", "")}

    async def _fn_get_credits(self, _args: dict) -> dict:
        data = await self._suno_get("/generate/credit")
        return {"status": "success", "credits": data.get("data", 0)}

    async def _fn_check_task_status(self, args: dict) -> dict:
        task_id = args["task_id"]
        poll_path = args.get("poll_path", "/generate/record-info")
        data = await self._suno_get(poll_path, {"taskId": task_id})
        return {"status": "success", "task_status": data.get("data", {}).get("status", ""), "data": data.get("data", {})}

    async def _fn_get_timestamped_lyrics(self, args: dict) -> dict:
        payload = {
            "taskId": args["task_id"],
            "audioId": args["audio_id"],
        }
        data = await self._suno_post("/generate/get-timestamped-lyrics", payload)
        return {"status": "success", "lyrics_data": data.get("data", {})}

    # ------------------------------------------------------------------
    # Function tool definitions
    # ------------------------------------------------------------------

    def _get_function_tools(self) -> list:
        return [
            {
                "type": "function",
                "name": "generate_music",
                "description": "Generate AI music from a text description. Returns 2 audio tracks. Use custom_mode=true with style and title for precise control, or custom_mode=false with just a prompt for automatic generation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Text description of desired music, or lyrics in custom mode. Max 3000-5000 chars depending on model."},
                        "custom_mode": {"type": "boolean", "description": "Enable custom mode for style/title control. Default false."},
                        "instrumental": {"type": "boolean", "description": "Generate instrumental only (no vocals). Default false."},
                        "style": {"type": "string", "description": "Music style/genre (required in custom mode). e.g. 'Jazz', 'Electronic Dance', 'Folk Pop'."},
                        "title": {"type": "string", "description": "Song title (required in custom mode). Max 80-100 chars."},
                        "model": {"type": "string", "description": "Model version. Default V4_5ALL.", "enum": ["V4", "V4_5", "V4_5PLUS", "V4_5ALL", "V5"]},
                        "negative_tags": {"type": "string", "description": "Styles to exclude from generation."},
                        "vocal_gender": {"type": "string", "description": "Preferred vocal gender.", "enum": ["m", "f"]},
                    },
                    "required": ["prompt"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "generate_lyrics",
                "description": "Generate AI-powered song lyrics from a description. Returns structured lyrics with title.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Description of desired lyrics content. Max 200 characters."},
                    },
                    "required": ["prompt"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "extend_music",
                "description": "Extend an existing music track. Requires the audio_id from a previous generation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "audio_id": {"type": "string", "description": "Audio ID from a previously generated track."},
                        "prompt": {"type": "string", "description": "Description of how to continue the music."},
                        "style": {"type": "string", "description": "Music style for the extension."},
                        "title": {"type": "string", "description": "Title for the extended version."},
                        "continue_at": {"type": "number", "description": "Start extending from this timestamp (seconds)."},
                        "default_params": {"type": "boolean", "description": "Use default parameters from original track. Default true."},
                        "model": {"type": "string", "description": "Model version.", "enum": ["V4", "V4_5", "V4_5PLUS", "V4_5ALL", "V5"]},
                    },
                    "required": ["audio_id"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "replace_section",
                "description": "Replace a specific time range within an existing track. Duration must be 6-60 seconds and cannot exceed 50% of original duration.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Original music's parent task ID."},
                        "audio_id": {"type": "string", "description": "Audio ID of the track to modify."},
                        "prompt": {"type": "string", "description": "Description of the replacement segment."},
                        "tags": {"type": "string", "description": "Music style tags (e.g. 'Jazz')."},
                        "title": {"type": "string", "description": "Music title."},
                        "start_time": {"type": "number", "description": "Start time in seconds (2 decimal places)."},
                        "end_time": {"type": "number", "description": "End time in seconds (2 decimal places)."},
                        "negative_tags": {"type": "string", "description": "Styles to exclude."},
                    },
                    "required": ["task_id", "audio_id", "prompt", "tags", "title", "start_time", "end_time"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "upload_and_cover",
                "description": "Create an AI cover version of uploaded audio with a new style. Requires a publicly accessible audio URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "upload_url": {"type": "string", "description": "Publicly accessible URL of the audio file to cover."},
                        "prompt": {"type": "string", "description": "Description or lyrics for the cover."},
                        "custom_mode": {"type": "boolean", "description": "Enable custom mode."},
                        "instrumental": {"type": "boolean", "description": "Instrumental only."},
                        "style": {"type": "string", "description": "Target music style."},
                        "title": {"type": "string", "description": "Cover song title."},
                        "model": {"type": "string", "description": "Model version.", "enum": ["V4", "V4_5", "V4_5PLUS", "V4_5ALL", "V5"]},
                    },
                    "required": ["upload_url"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "upload_and_extend",
                "description": "Upload audio and extend it with AI-generated continuation. Requires a publicly accessible audio URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "upload_url": {"type": "string", "description": "Publicly accessible URL of the audio to extend."},
                        "prompt": {"type": "string", "description": "Description of how to continue."},
                        "style": {"type": "string", "description": "Music style for extension."},
                        "title": {"type": "string", "description": "Title."},
                        "continue_at": {"type": "number", "description": "Timestamp (seconds) to start extending from."},
                        "instrumental": {"type": "boolean", "description": "Instrumental only."},
                        "default_params": {"type": "boolean", "description": "Use default parameters. Default true."},
                        "model": {"type": "string", "description": "Model version.", "enum": ["V4", "V4_5", "V4_5PLUS", "V4_5ALL", "V5"]},
                    },
                    "required": ["upload_url"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "mashup",
                "description": "Create a mashup combining exactly 2 audio files into a new composition.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "upload_urls": {"type": "array", "items": {"type": "string"}, "description": "Exactly 2 publicly accessible audio file URLs."},
                        "prompt": {"type": "string", "description": "Description for the mashup."},
                        "custom_mode": {"type": "boolean", "description": "Enable custom mode."},
                        "style": {"type": "string", "description": "Target style."},
                        "title": {"type": "string", "description": "Mashup title."},
                        "instrumental": {"type": "boolean", "description": "Instrumental only."},
                        "model": {"type": "string", "description": "Model version.", "enum": ["V4", "V4_5", "V4_5PLUS", "V4_5ALL", "V5"]},
                    },
                    "required": ["upload_urls"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "vocal_separation",
                "description": "Separate vocals from instrumentals in a previously generated track. Can do simple vocal/instrumental split or full stem separation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Task ID of the music generation."},
                        "audio_id": {"type": "string", "description": "Audio ID of the track to separate."},
                        "type": {"type": "string", "description": "Separation mode.", "enum": ["separate_vocal", "split_stem"]},
                    },
                    "required": ["task_id", "audio_id"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "add_instrumental",
                "description": "Add AI-generated instrumental accompaniment to an uploaded vocal track.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "upload_url": {"type": "string", "description": "URL of the vocal track."},
                        "title": {"type": "string", "description": "Track title."},
                        "tags": {"type": "string", "description": "Music style tags."},
                        "negative_tags": {"type": "string", "description": "Styles to exclude."},
                        "vocal_gender": {"type": "string", "description": "Vocal gender.", "enum": ["m", "f"]},
                        "model": {"type": "string", "description": "Model version.", "enum": ["V4_5PLUS", "V5"]},
                    },
                    "required": ["upload_url", "title", "tags", "negative_tags"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "add_vocals",
                "description": "Add AI-generated vocals to an uploaded instrumental track.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "upload_url": {"type": "string", "description": "URL of the instrumental track."},
                        "prompt": {"type": "string", "description": "Lyrics or vocal description."},
                        "title": {"type": "string", "description": "Track title."},
                        "style": {"type": "string", "description": "Vocal style."},
                        "negative_tags": {"type": "string", "description": "Styles to exclude."},
                        "vocal_gender": {"type": "string", "description": "Vocal gender.", "enum": ["m", "f"]},
                        "model": {"type": "string", "description": "Model version.", "enum": ["V4_5PLUS", "V5"]},
                    },
                    "required": ["upload_url", "prompt", "title", "style", "negative_tags"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "convert_to_wav",
                "description": "Convert a generated track to high-quality WAV format.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Task ID of the music generation."},
                        "audio_id": {"type": "string", "description": "Audio ID of the track to convert."},
                    },
                    "required": ["task_id", "audio_id"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "generate_midi",
                "description": "Generate a MIDI file from a previously separated track (requires vocal separation first).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Task ID from a completed vocal separation."},
                        "audio_id": {"type": "string", "description": "Audio ID of the separated track."},
                    },
                    "required": ["task_id"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "create_music_video",
                "description": "Generate a visual music video from a generated audio track.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Task ID of the music generation."},
                        "audio_id": {"type": "string", "description": "Audio ID of the track."},
                        "author": {"type": "string", "description": "Artist/creator name (max 50 chars)."},
                        "domain_name": {"type": "string", "description": "Website/brand name (max 50 chars)."},
                    },
                    "required": ["task_id", "audio_id"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "generate_cover_art",
                "description": "Generate cover art images for a previously generated music track. Returns 2 cover image variations.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Task ID of the music generation."},
                    },
                    "required": ["task_id"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "generate_persona",
                "description": "Create a reusable music persona from an existing track. The persona captures vocal style and musical characteristics for use in future generations.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Task ID from music generation."},
                        "audio_id": {"type": "string", "description": "Audio ID of the track."},
                        "name": {"type": "string", "description": "Persona name capturing the musical style."},
                        "description": {"type": "string", "description": "Detailed description of the persona's musical characteristics."},
                        "vocal_start": {"type": "number", "description": "Audio segment start time (seconds, default 0)."},
                        "vocal_end": {"type": "number", "description": "Audio segment end time (seconds, default 30). Segment must be 10-30s."},
                        "style": {"type": "string", "description": "Music style label."},
                    },
                    "required": ["task_id", "audio_id", "name"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "boost_style",
                "description": "Generate an enhanced, detailed style description from a short style input. Use the result as the 'style' parameter in music generation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Style description to enhance."},
                    },
                    "required": ["content"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "get_credits",
                "description": "Check remaining Suno API credits.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "check_task_status",
                "description": "Check the status of any previously submitted task.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Task ID to check."},
                        "poll_path": {"type": "string", "description": "Status endpoint path. Default /generate/record-info. Use /lyrics/record-info for lyrics, /wav/record-info for WAV, etc."},
                    },
                    "required": ["task_id"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "get_timestamped_lyrics",
                "description": "Get time-aligned lyrics with word-level timestamps for a generated track.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Task ID of the music generation."},
                        "audio_id": {"type": "string", "description": "Audio ID of the track."},
                    },
                    "required": ["task_id", "audio_id"],
                    "additionalProperties": False,
                },
            },
        ]

    # ------------------------------------------------------------------
    # Agent initialization and lifecycle
    # ------------------------------------------------------------------

    async def create_agent(self) -> None:
        if self._initialized:
            return
        logger.info("Initializing Music agent (Responses API with Suno API tools)...")
        if not self._suno_api_key:
            logger.warning("SUNO_API_KEY not set - Suno API calls will fail")
        self._get_client()
        self._initialized = True

    def _get_agent_instructions(self) -> str:
        return f"""You are the AI Foundry Music Agent, powered by the Suno API. You help users create, edit, and process music using AI.

## Capabilities
You have access to the full Suno API through function tools:

**Music Creation:**
- `generate_music` — Create songs from text descriptions or lyrics (returns 2 tracks)
- `generate_lyrics` — Generate AI-powered song lyrics
- `boost_style` — Enhance a short style description into a detailed one

**Audio Editing:**
- `extend_music` — Extend an existing track (needs audio_id from a previous generation)
- `replace_section` — Replace a time range within a track
- `upload_and_cover` — Create a cover version of uploaded audio
- `upload_and_extend` — Extend uploaded audio with AI
- `mashup` — Combine 2 audio files into a new composition

**Audio Processing:**
- `vocal_separation` — Separate vocals from instrumentals (or full stem split)
- `add_instrumental` — Add instrumental to a vocal track
- `add_vocals` — Add vocals to an instrumental track
- `convert_to_wav` — Convert to high-quality WAV format
- `generate_midi` — Generate MIDI (requires vocal separation first)

**Visual & Identity:**
- `create_music_video` — Generate a visual music video
- `generate_cover_art` — Generate cover art images
- `generate_persona` — Create a reusable voice/style persona

**Utility:**
- `get_credits` — Check remaining API credits
- `check_task_status` — Check any task's progress
- `get_timestamped_lyrics` — Get time-aligned lyrics

## Usage Guidelines

1. **For simple requests** like "create a jazz song": use `generate_music` with a descriptive prompt.
2. **For custom songs with specific lyrics**: set `custom_mode=true`, provide `style`, `title`, and use lyrics as the `prompt`.
3. **Model selection**: Default is V4_5ALL (best structure). Use V5 for faster generation, V4 for highest audio quality.
4. **Task chaining**: Many operations need task_id/audio_id from previous generations. Always provide these from earlier results.
5. **Vocal separation before MIDI**: `generate_midi` requires a task_id from a completed vocal separation, not from music generation.

## Important Notes
- Music generation typically takes 30-120 seconds. The tool handles polling automatically.
- Each generation returns 2 track variations — present both to the user.
- Track IDs (audio_id) and task IDs are needed for follow-up operations — always include them in your response.
- Audio files are automatically uploaded to cloud storage for reliable access.

## Error Reporting
If a tool call fails, report the error clearly. Start with "Error:" for system-detectable failures.

Current date: {datetime.datetime.now().isoformat()}

## NEEDS_INPUT - Human-in-the-Loop
Use NEEDS_INPUT to pause and ask the user a question:
```NEEDS_INPUT
Your question here
```END_NEEDS_INPUT
"""

    async def create_session(self) -> str:
        return f"session_{int(time.time())}_{os.urandom(4).hex()}"

    # ------------------------------------------------------------------
    # Main conversation stream
    # ------------------------------------------------------------------

    async def run_conversation_stream(self, session_id: str, user_message: str, context_id: Optional[str] = None):
        if context_id:
            self._current_context_id = context_id

        if not self._initialized:
            await self.create_agent()

        client = self._get_client()
        model = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")
        tools = self._get_function_tools()

        kwargs = {
            "model": model,
            "instructions": self._get_agent_instructions(),
            "input": [{"role": "user", "content": user_message}],
            "tools": tools,
            "stream": True,
            "max_output_tokens": 4000,
        }
        if session_id in self._response_ids:
            kwargs["previous_response_id"] = self._response_ids[session_id]

        max_rounds = 5
        for round_num in range(max_rounds):
            retry_count = 0
            max_retries = 3

            while retry_count <= max_retries:
                try:
                    response = await client.responses.create(**kwargs)
                    break
                except Exception as e:
                    error_str = str(e).lower()
                    if "rate_limit" in error_str or "429" in error_str:
                        retry_count += 1
                        if retry_count <= max_retries:
                            backoff = min(15 * (2 ** retry_count), 60)
                            yield f"Rate limit hit - retrying in {backoff}s..."
                            await asyncio.sleep(backoff)
                            continue
                        yield f"Error: Rate limit exceeded after {max_retries} retries"
                        return
                    yield f"Error: {e}"
                    return

            text_chunks: List[str] = []
            function_calls: Dict[str, Dict[str, str]] = {}
            current_call_id: Optional[str] = None
            response_id: Optional[str] = None

            async for event in response:
                event_type = getattr(event, "type", None)

                if event_type == "response.output_text.delta":
                    text_chunks.append(event.delta)

                elif event_type == "response.output_item.added":
                    item = getattr(event, "item", None)
                    if item and getattr(item, "type", None) == "function_call":
                        call_id = getattr(item, "call_id", None)
                        func_name = getattr(item, "name", None)
                        if call_id:
                            function_calls[call_id] = {"name": func_name or "", "arguments": ""}
                            current_call_id = call_id
                            yield f"🎵 Calling: {self._get_tool_description(func_name)}"

                elif event_type == "response.function_call_arguments.delta":
                    if current_call_id and current_call_id in function_calls:
                        function_calls[current_call_id]["arguments"] += event.delta

                elif event_type in ("response.completed", "response.done"):
                    resp = getattr(event, "response", None)
                    if resp:
                        response_id = getattr(resp, "id", None)
                        if response_id:
                            self._response_ids[session_id] = response_id
                        usage = getattr(resp, "usage", None)
                        if usage:
                            self.last_token_usage = {
                                "prompt_tokens": getattr(usage, "input_tokens", 0) or getattr(usage, "prompt_tokens", 0),
                                "completion_tokens": getattr(usage, "output_tokens", 0) or getattr(usage, "completion_tokens", 0),
                                "total_tokens": getattr(usage, "total_tokens", 0),
                            }

                elif event_type == "response.failed":
                    resp = getattr(event, "response", None)
                    error_obj = getattr(resp, "error", None) if resp else None
                    yield f"Error: {getattr(error_obj, 'message', 'Unknown error') if error_obj else 'Unknown error'}"
                    return

            # If there are function calls, execute them and continue
            if function_calls:
                function_outputs = []
                for call_id, call_info in function_calls.items():
                    func_name = call_info["name"]
                    try:
                        args = json.loads(call_info["arguments"]) if call_info["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {}

                    yield f"🎵 Processing: {self._get_tool_description(func_name)}..."
                    result = await self._execute_function(func_name, args)

                    if result.get("error"):
                        yield f"⚠️ {func_name} error: {result['error']}"

                    function_outputs.append({
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(result, default=str),
                    })

                # Continue with function results
                kwargs = {
                    "model": model,
                    "instructions": self._get_agent_instructions(),
                    "input": function_outputs,
                    "tools": tools,
                    "stream": True,
                    "max_output_tokens": 4000,
                    "previous_response_id": response_id,
                }
                continue  # next round

            # No function calls — final text response
            if text_chunks:
                full_text = "".join(text_chunks)
                # Append artifact info to text if available
                if self._latest_artifacts:
                    for art in self._latest_artifacts:
                        blob_uri = art.get("artifact-uri", "")
                        file_name = art.get("file-name", "")
                        if blob_uri:
                            full_text = full_text.rstrip() + f"\n\nFile: {file_name} ({blob_uri})"
                yield full_text
            else:
                yield "Error: Agent completed but no response text was generated"
            return

        yield "Error: Maximum function call rounds exceeded"

    def _get_tool_description(self, tool_name: str) -> str:
        descriptions = {
            "generate_music": "Generate Music",
            "generate_lyrics": "Generate Lyrics",
            "extend_music": "Extend Music",
            "replace_section": "Replace Section",
            "upload_and_cover": "Upload & Cover",
            "upload_and_extend": "Upload & Extend",
            "mashup": "Create Mashup",
            "vocal_separation": "Vocal Separation",
            "add_instrumental": "Add Instrumental",
            "add_vocals": "Add Vocals",
            "convert_to_wav": "Convert to WAV",
            "generate_midi": "Generate MIDI",
            "create_music_video": "Create Music Video",
            "generate_cover_art": "Generate Cover Art",
            "generate_persona": "Create Persona",
            "boost_style": "Boost Style",
            "get_credits": "Check Credits",
            "check_task_status": "Check Task Status",
            "get_timestamped_lyrics": "Get Timestamped Lyrics",
        }
        return descriptions.get(tool_name, tool_name.replace("_", " ").title())

    async def run_conversation(self, session_id: str, user_message: str) -> str:
        return "\n".join([r async for r in self.run_conversation_stream(session_id, user_message)])

    async def chat(self, session_id: str, user_message: str) -> str:
        return await self.run_conversation(session_id, user_message)
