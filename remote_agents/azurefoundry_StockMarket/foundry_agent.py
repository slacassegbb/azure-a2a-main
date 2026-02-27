"""
AI Foundry Agent with Stock Market capabilities.
Uses the Responses API with native MCP tool support via Alpha Vantage.
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

# Default MCP URL (read lazily after dotenv loads)
_ALPHA_VANTAGE_DEFAULT_URL = "https://mcp.alphavantage.co/mcp?apikey=demo"

STOCKMARKET_ALLOWED_TOOLS = [
    "TOOL_LIST",
    "TOOL_GET",
    "TOOL_CALL",
]


class FoundryStockMarketAgent:
    """AI Foundry Agent with Stock Market capabilities via Responses API."""

    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self._client: Optional[AsyncAzureOpenAI] = None
        self._initialized = False
        self._response_ids: Dict[str, str] = {}
        self.last_token_usage: Optional[Dict[str, int]] = None
        mcp_url = os.getenv("ALPHA_VANTAGE_MCP_URL", _ALPHA_VANTAGE_DEFAULT_URL)
        self._mcp_tool_config = {
            "type": "mcp",
            "server_label": "AlphaVantage",
            "server_url": mcp_url,
            "require_approval": "never",
            "allowed_tools": STOCKMARKET_ALLOWED_TOOLS,
            "headers": {
                "Content-Type": "application/json",
                "User-Agent": "Azure-AI-Foundry-Agent",
                "Accept": "application/json, text/event-stream",
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
        logger.info("Initializing Stock Market agent (Responses API)...")
        mcp_url = os.getenv("ALPHA_VANTAGE_MCP_URL", _ALPHA_VANTAGE_DEFAULT_URL)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    mcp_url,
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                     "clientInfo": {"name": "test", "version": "1.0"}}},
                    headers={"Content-Type": "application/json"},
                )
                logger.info(f"Alpha Vantage MCP status: {response.status_code}")
        except Exception as e:
            logger.warning(f"Alpha Vantage MCP test failed: {e} (continuing anyway)")
        self._get_client()
        self._initialized = True

    def _get_agent_instructions(self) -> str:
        return f"""You are an expert Stock Market Data analyst with access to comprehensive financial market data via Alpha Vantage.

You have access to 100+ financial data tools through a meta-tool pattern. Here's how to use them:

## Tool Discovery Workflow
1. First call TOOL_LIST to discover available tools
2. Then call TOOL_GET with the tool name to get its full schema and parameters
3. Finally call TOOL_CALL with the tool name and arguments to execute it

## CRITICAL: Free Tier Endpoint Rules

You are on the Alpha Vantage FREE tier. You MUST use only these free endpoints:

**For stock prices, ALWAYS use these tool names (via TOOL_CALL):**
- `TIME_SERIES_DAILY` — daily OHLCV (NOT TIME_SERIES_DAILY_ADJUSTED, that's premium)
- `GLOBAL_QUOTE` — current/latest quote for a symbol
- `TIME_SERIES_WEEKLY` — weekly OHLCV
- `TIME_SERIES_MONTHLY` — monthly OHLCV
- `TIME_SERIES_INTRADAY` — intraday data (1min, 5min, 15min, 30min, 60min)

**DO NOT use any of these premium endpoints** (they will fail):
- TIME_SERIES_DAILY_ADJUSTED
- TIME_SERIES_WEEKLY_ADJUSTED
- TIME_SERIES_MONTHLY_ADJUSTED
- Any endpoint that returns "premium subscription required"

**Other free endpoints:**
- `CURRENCY_EXCHANGE_RATE` — forex exchange rates
- `CRYPTO_RATING` — crypto ratings
- `SMA`, `EMA`, `RSI`, `MACD`, `BBANDS`, `STOCH`, `ADX`, `CCI`, `AROON` — technical indicators
- `NEWS_SENTIMENT` — news and sentiment data
- `TOP_GAINERS_LOSERS` — market movers
- `REAL_GDP`, `CPI`, `INFLATION`, `UNEMPLOYMENT`, `FEDERAL_FUNDS_RATE` — economic indicators
- `WTI`, `BRENT`, `NATURAL_GAS`, `COPPER`, `ALUMINUM`, `WHEAT`, `CORN`, `SUGAR`, `COFFEE` — commodities

## Efficiency: Minimize API Calls

The free tier has only 25 calls/day. Each TOOL_LIST, TOOL_GET, and TOOL_CALL counts as one call.

**To minimize calls:**
- If you already know the tool name and parameters from the list above, skip TOOL_LIST and TOOL_GET — go directly to TOOL_CALL
- For `TIME_SERIES_DAILY`, the parameters are: `symbol` (e.g., "AMD"), `outputsize` ("full" for 100+ days, "compact" for last 100)
- For `GLOBAL_QUOTE`, the only parameter is: `symbol`
- Only use TOOL_LIST and TOOL_GET when you genuinely don't know which tool to use

## Available Data Categories
- **Stock Prices**: Daily/weekly/monthly OHLCV data, intraday (1min-60min), 20+ years of history
- **Market Intelligence**: News sentiment, top gainers/losers
- **Forex**: Currency exchange rates
- **Commodities**: Oil (WTI/Brent), natural gas, copper, aluminum, wheat, corn, sugar, coffee, cotton
- **Economic Indicators**: Real GDP, CPI, inflation, unemployment, federal funds rate
- **Technical Indicators**: SMA, EMA, RSI, MACD, Bollinger Bands, Stochastic, ADX, etc.

## CRITICAL: Complete Data Output

You MUST output EVERY row of data returned by the API. NEVER abbreviate, truncate, or skip rows.
- NEVER use "..." or "…" to represent omitted rows
- NEVER write "showing first N rows" or "remaining rows omitted" or "continues with full dataset"
- Output a CSV code block with the header followed by EVERY single row
- Long output is expected and correct — do NOT shorten it

## Error Reporting (CRITICAL)

If you CANNOT complete the requested task — due to rate limits, API errors, missing data,
premium-only endpoints, or any other reason — you MUST start your response with "Error:".

Examples:
- "Error: Daily API call limit reached. The free tier allows 25 calls/day."
- "Error: TIME_SERIES_DAILY_ADJUSTED requires a premium subscription."
- "Error: No data returned for symbol XYZ."

Do NOT write a polite explanation without the "Error:" prefix. The system uses this prefix
to detect failures. Without it, the task is marked as successful even though it failed.

## Response Guidelines
- Always include the date range and number of data points in your response
- For stock quotes, include key metrics: price, change, change%, volume
- When asked for historical data, default to daily frequency unless specified otherwise
- For technical indicators, explain what the indicator measures and what the values suggest

## Important Notes
- The free tier allows 25 API calls per day — be efficient, skip TOOL_LIST/TOOL_GET when possible

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
            "max_output_tokens": 16000,
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
                        error_msg = getattr(event, 'error', None) or getattr(event, 'message', None)
                        logger.error(f"MCP call failed — tool: {tool_name}, error: {error_msg}, event attrs: {vars(event) if hasattr(event, '__dict__') else event}")
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
                    yield f"Error: Rate limit exceeded after {max_retries} retries"
                else:
                    yield f"Error: {e}"
                return

    def _get_tool_description(self, tool_name: str) -> str:
        descriptions = {
            "TOOL_LIST": "Discovering available financial tools",
            "TOOL_GET": "Getting tool schema",
            "TOOL_CALL": "Fetching market data",
        }
        return descriptions.get(tool_name, tool_name.replace("_", " ").title())

    async def run_conversation(self, session_id: str, user_message: str) -> str:
        return "\n".join([r async for r in self.run_conversation_stream(session_id, user_message)])

    async def chat(self, session_id: str, user_message: str) -> str:
        return await self.run_conversation(session_id, user_message)
