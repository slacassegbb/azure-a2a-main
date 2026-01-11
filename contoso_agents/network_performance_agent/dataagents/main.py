"""
Fabric Agent Management Module
Handles Fabric Data agents
"""

import logging
import time
import uuid
import typing as t
from typing import Optional

from openai import OpenAI
from openai._models import FinalRequestOptions
from openai._types import Omit
from openai._utils import is_given
from azure.identity import DefaultAzureCredential

import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import logging

logger = logging.getLogger("src.agents.dataagents")

FABRIC_SCOPE: str = "https://api.fabric.microsoft.com/.default"
FABRIC_SCOPE_ALTERNATIVE: str = "https://analysis.windows.net/powerbi/api/.default"
FABRIC_API_VERSION: str = "2024-05-01-preview"
DEFAULT_POLL_INTERVAL_SEC: int = 2
DEFAULT_TIMEOUT_SEC: int = 300

_cached_credential = None


def _get_bearer() -> str:
    """Get fresh bearer token for each request"""
    global _cached_credential
    return _cached_credential.get_token(FABRIC_SCOPE).token


class FabricOpenAI(OpenAI):
    def __init__(
        self, base_url: str, api_version: str = "2024-05-01-preview", **kwargs: t.Any
    ) -> None:
        self.api_version = api_version
        default_query = kwargs.pop("default_query", {})
        default_query["api-version"] = self.api_version
        super().__init__(
            api_key="",
            base_url=base_url,
            default_query=default_query,
            **kwargs,
        )

    def _prepare_options(self, options: FinalRequestOptions) -> None:
        headers: dict[str, str | Omit] = (
            {**options.headers} if is_given(options.headers) else {}
        )
        headers["Authorization"] = f"Bearer {_get_bearer()}"
        headers.setdefault("Accept", "application/json")
        headers.setdefault("ActivityId", str(uuid.uuid4()))
        options.headers = headers
        return super()._prepare_options(options)


class DataAgent(OpenAI):
    """
    OpenAI client wrapper for Microsoft Fabric Data Agents.

    This class extends the OpenAI client to work with Fabric's AI Assistant API endpoints,
    handling authentication and request formatting specific to Fabric services.
    """

    def __init__(
        self,
        base_url: str,
        api_version: str = FABRIC_API_VERSION,
        default_headers: dict = None,
        **kwargs,
    ) -> None:
        self.api_version = api_version
        self._auth_headers = default_headers or {}
        default_query = kwargs.pop("default_query", {})
        default_query["api-version"] = self.api_version
        super().__init__(
            api_key="",  # Not used, auth via bearer token
            base_url=base_url,
            default_query=default_query,
            **kwargs,
        )

    def _prepare_options(self, options: FinalRequestOptions) -> None:
        """
        Prepare request options with Fabric-specific authentication and headers.

        Args:
            options: Request options to be modified with auth headers
        """
        headers = {**options.headers} if is_given(options.headers) else {}
        headers.update(self._auth_headers)
        headers.setdefault("Accept", "application/json")
        headers.setdefault("ActivityId", str(uuid.uuid4()))
        options.headers = headers
        return super()._prepare_options(options)


def ask_fabric_agent(
    endpoint: str,
    question: str,
    credential=None,
    poll_interval_sec: int = DEFAULT_POLL_INTERVAL_SEC,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> str:
    try:
        logger.info(f"🔍 Querying Fabric agent at endpoint: {endpoint}")

        global _cached_credential
        if credential is None:
            logger.info("🔐 Creating new Azure credential...")
            credential = DefaultAzureCredential()
            _cached_credential = credential
        else:
            logger.info("♻️  Reusing cached Azure credential")
            _cached_credential = credential

        client = FabricOpenAI(base_url=endpoint)

        assistant = client.beta.assistants.create(model="not-used")
        thread = client.beta.threads.create()

        try:
            client.beta.threads.messages.create(
                thread_id=thread.id, role="user", content=question
            )

            run = client.beta.threads.runs.create(
                thread_id=thread.id, assistant_id=assistant.id
            )

            terminal = {"completed", "failed", "cancelled", "requires_action"}
            start = time.time()
            while run.status not in terminal:
                if time.time() - start > timeout_sec:
                    raise TimeoutError(f"Run polling exceeded {timeout_sec}s")
                time.sleep(poll_interval_sec)
                run = client.beta.threads.runs.retrieve(
                    thread_id=thread.id, run_id=run.id
                )

            if run.status != "completed":
                return f"[Run ended: {run.status}]"

            # Extract response
            msgs = client.beta.threads.messages.list(thread_id=thread.id, order="asc")
            out_chunks = []
            for m in msgs.data:
                if m.role == "assistant":
                    for c in m.content:
                        if getattr(c, "type", None) == "text":
                            out_chunks.append(c.text.value)

            response = "\n".join(out_chunks).strip() or "[No text content returned]"
            logger.info("Fabric agent query completed successfully")
            return response

        finally:
            try:
                client.beta.threads.delete(thread_id=thread.id)
            except Exception:
                pass

    except Exception as e:
        error_msg = f"Error querying Fabric agent: {str(e)}"
        logger.error(error_msg)
        return error_msg
