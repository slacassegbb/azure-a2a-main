"""
AI Foundry Agent with Google Maps capabilities.
Uses the Responses API with native MCP tool support.
Connects to Google's official Maps MCP endpoint.
"""
import os
import time
import datetime
import asyncio
import logging
from typing import Optional, Dict

import httpx
from openai import AsyncAzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

logger = logging.getLogger(__name__)

GOOGLEMAPS_MCP_URL = os.getenv("GOOGLEMAPS_MCP_URL", "https://mapstools.googleapis.com/mcp")

GOOGLEMAPS_ALLOWED_TOOLS = [
    "search_places",
    "lookup_weather",
    "compute_routes",
]


class FoundryGoogleMapsAgent:
    """AI Foundry Agent with Google Maps capabilities via Responses API."""

    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self._client: Optional[AsyncAzureOpenAI] = None
        self._initialized = False
        self._response_ids: Dict[str, str] = {}
        self.last_token_usage: Optional[Dict[str, int]] = None

        google_api_key = os.environ.get("GOOGLE_API_KEY", "")
        self._mcp_tool_config = {
            "type": "mcp",
            "server_label": "GoogleMaps",
            "server_url": GOOGLEMAPS_MCP_URL,
            "require_approval": "never",
            "allowed_tools": GOOGLEMAPS_ALLOWED_TOOLS,
            "headers": {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": google_api_key,
            },
        }

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
        logger.info("Initializing Google Maps agent (Responses API)...")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    GOOGLEMAPS_MCP_URL,
                    headers={
                        "Content-Type": "application/json",
                        "X-Goog-Api-Key": os.environ.get("GOOGLE_API_KEY", ""),
                    },
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "health-check", "version": "1.0.0"},
                        },
                    },
                )
                logger.info(f"MCP Server status: {response.status_code}")
        except Exception as e:
            logger.warning(f"MCP Server test failed: {e} (continuing anyway)")
        self._get_client()
        self._initialized = True

    def _get_agent_instructions(self) -> str:
        return f"""You are a Google Maps assistant. You help users with location-based queries using Google Maps tools.

Your capabilities:
- **Search Places**: Find restaurants, shops, landmarks, addresses, and any point of interest worldwide. You can bias results to specific geographic areas.
- **Weather Lookup**: Get current weather conditions, hourly forecasts (up to 48h), and daily forecasts (up to 7 days) for any location. Includes temperature, wind, precipitation, humidity, UV index, and more.
- **Route Computing**: Calculate driving or walking routes between two locations, with distance and estimated travel time.

Guidelines:
- When searching for places, always include the city/region in your query for best results.
- For weather requests, include the country name with addresses for accurate geocoding (e.g., "Montreal, QC, Canada" not just "Montreal").
- For routes, ask for both origin and destination if the user only provides one.
- Present results in a clear, readable format with key details highlighted.
- When showing places, include ratings, addresses, and Google Maps links when available.
- For weather, mention both actual temperature and feels-like temperature.
- For routes, convert duration from seconds to hours/minutes and distance to km or miles as appropriate.

Current date: {datetime.datetime.now().isoformat()}

## NEEDS_INPUT - Human-in-the-Loop

Use NEEDS_INPUT to pause and ask the user a question:

```NEEDS_INPUT
Your question here
```END_NEEDS_INPUT
"""

    async def create_session(self) -> str:
        return f"session_{int(time.time())}_{os.urandom(4).hex()}"

    async def run_conversation_stream(self, session_id: str, user_message: str):
        if not self._initialized:
            await self.create_agent()

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
                stream_start = time.time()
                response = await client.responses.create(**kwargs)
                text_chunks = []
                tool_calls_seen = set()
                mcp_failures = []
                tool_call_times = {}

                async for event in response:
                    event_type = getattr(event, 'type', None)

                    if event_type == "response.output_text.delta":
                        text_chunks.append(event.delta)
                    elif event_type == "response.mcp_call.in_progress":
                        tool_name = getattr(event, 'name', 'mcp_tool')
                        if tool_name not in tool_calls_seen:
                            tool_calls_seen.add(tool_name)
                            tool_call_times[tool_name] = time.time()
                            yield f"\U0001f6e0\ufe0f Remote agent executing: {self._get_tool_description(tool_name)}"
                    elif event_type == "response.mcp_call.completed":
                        pass
                    elif event_type == "response.mcp_call.failed":
                        tool_name = getattr(event, 'name', None) or getattr(event, 'item_id', 'mcp_tool')
                        mcp_failures.append(tool_name)
                    elif event_type == "response.failed":
                        resp = getattr(event, 'response', None)
                        error_obj = getattr(resp, 'error', None) if resp else None
                        yield f"Error: {getattr(error_obj, 'message', 'Unknown error') if error_obj else 'Unknown error'}"
                        return
                    elif event_type == "response.output_item.added":
                        item = getattr(event, 'item', None)
                        if item and getattr(item, 'type', None) in ("mcp_call", "mcp_tool_call"):
                            tool_name = getattr(item, 'name', None) or getattr(item, 'tool_name', 'mcp_tool')
                            if tool_name not in tool_calls_seen:
                                tool_calls_seen.add(tool_name)
                                tool_call_times[tool_name] = time.time()
                                yield f"\U0001f6e0\ufe0f Remote agent executing: {self._get_tool_description(tool_name)}"
                    elif event_type in ("response.completed", "response.done"):
                        resp = getattr(event, 'response', None)
                        if resp:
                            usage = getattr(resp, 'usage', None)
                            if usage:
                                self.last_token_usage = {
                                    "prompt_tokens": getattr(usage, 'prompt_tokens', 0) or getattr(usage, 'input_tokens', 0),
                                    "completion_tokens": getattr(usage, 'completion_tokens', 0) or getattr(usage, 'output_tokens', 0),
                                    "total_tokens": getattr(usage, 'total_tokens', 0),
                                }
                            resp_id = getattr(resp, 'id', None)
                            if resp_id:
                                self._response_ids[session_id] = resp_id

                if text_chunks:
                    full_text = "".join(text_chunks)
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
                    yield f"Rate limit exceeded after {max_retries} retries"
                else:
                    yield f"Error: {e}"
                return

    def _get_tool_description(self, tool_name: str) -> str:
        descriptions = {
            "search_places": "Searching Google Maps for places",
            "lookup_weather": "Looking up weather conditions",
            "compute_routes": "Computing travel route",
        }
        return descriptions.get(tool_name, tool_name.replace("_", " ").title())

    async def run_conversation(self, session_id: str, user_message: str) -> str:
        return "\n".join([r async for r in self.run_conversation_stream(session_id, user_message)])

    async def chat(self, session_id: str, user_message: str) -> str:
        return await self.run_conversation(session_id, user_message)
