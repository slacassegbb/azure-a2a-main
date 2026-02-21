"""
AI Foundry Agent with Time Series Intelligence capabilities.
Uses the Responses API with function tools that call Nixtla TimeGEN-1 SDK.
"""
import os
import time
import json
import datetime
import asyncio
import logging
from typing import Optional, Dict

import pandas as pd
from nixtla import NixtlaClient
from openai import AsyncAzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

logger = logging.getLogger(__name__)

# TimeGEN-1 configuration (read lazily after dotenv loads)
_TIMEGEN_DEFAULT_URL = "https://TimeGEN-1-anfqi.eastus2.models.ai.azure.com"

# Tool definitions for the Responses API
TIMESERIES_TOOLS = [
    {
        "type": "function",
        "name": "forecast",
        "description": (
            "Generate time series forecasts for future values. "
            "Supports single-series and multi-series data with optional exogenous variables. "
            "Use for predicting stock prices, sales, demand, resource usage, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "data_json": {
                    "type": "string",
                    "description": (
                        "JSON array of objects containing the time series data. "
                        "Each object must have at least a timestamp column and a target value column. "
                        "Example: [{\"date\": \"2024-01-01\", \"sales\": 100}, ...]"
                    ),
                },
                "time_col": {
                    "type": "string",
                    "description": "Name of the timestamp/date column in the data.",
                },
                "target_col": {
                    "type": "string",
                    "description": "Name of the target value column to forecast.",
                },
                "h": {
                    "type": "integer",
                    "description": "Forecast horizon — number of future time steps to predict.",
                },
                "freq": {
                    "type": "string",
                    "description": (
                        "Pandas frequency string for the time series. "
                        "Examples: 'D' (daily), 'W' (weekly), 'MS' (month start), "
                        "'H' (hourly), 'B' (business day), 'QS' (quarter start)."
                    ),
                },
                "id_col": {
                    "type": "string",
                    "description": (
                        "Optional. Name of the column identifying different series "
                        "in multi-series data (e.g., ticker symbol, store ID)."
                    ),
                },
                "level": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": (
                        "Optional. Prediction interval confidence levels as percentages. "
                        "Example: [80, 95] for 80% and 95% intervals."
                    ),
                },
            },
            "required": ["data_json", "time_col", "target_col", "h", "freq"],
        },
    },
    {
        "type": "function",
        "name": "anomaly_detection",
        "description": (
            "Detect anomalies in time series data. Identifies unusual patterns, "
            "outliers, and unexpected behavior. Use for fraud detection, system monitoring, "
            "quality control, transaction analysis, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "data_json": {
                    "type": "string",
                    "description": "JSON array of objects containing the time series data.",
                },
                "time_col": {
                    "type": "string",
                    "description": "Name of the timestamp/date column.",
                },
                "target_col": {
                    "type": "string",
                    "description": "Name of the target value column to check for anomalies.",
                },
                "freq": {
                    "type": "string",
                    "description": "Pandas frequency string for the time series.",
                },
                "id_col": {
                    "type": "string",
                    "description": "Optional. Column identifying different series in multi-series data.",
                },
            },
            "required": ["data_json", "time_col", "target_col", "freq"],
        },
    },
    {
        "type": "function",
        "name": "historic_forecast",
        "description": (
            "Generate backtested historical forecasts to evaluate how well the model "
            "would have predicted past data. Useful for model validation and "
            "understanding prediction accuracy on known outcomes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "data_json": {
                    "type": "string",
                    "description": "JSON array of objects containing the time series data.",
                },
                "time_col": {
                    "type": "string",
                    "description": "Name of the timestamp/date column.",
                },
                "target_col": {
                    "type": "string",
                    "description": "Name of the target value column.",
                },
                "h": {
                    "type": "integer",
                    "description": "Forecast horizon used for backtesting.",
                },
                "freq": {
                    "type": "string",
                    "description": "Pandas frequency string for the time series.",
                },
                "id_col": {
                    "type": "string",
                    "description": "Optional. Column identifying different series in multi-series data.",
                },
                "level": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Optional. Prediction interval confidence levels.",
                },
            },
            "required": ["data_json", "time_col", "target_col", "h", "freq"],
        },
    },
    {
        "type": "function",
        "name": "cross_validation",
        "description": (
            "Evaluate forecast model accuracy using rolling-window cross-validation. "
            "Produces predictions at multiple historical cutoff points to assess "
            "reliability and consistency of forecasts over time."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "data_json": {
                    "type": "string",
                    "description": "JSON array of objects containing the time series data.",
                },
                "time_col": {
                    "type": "string",
                    "description": "Name of the timestamp/date column.",
                },
                "target_col": {
                    "type": "string",
                    "description": "Name of the target value column.",
                },
                "h": {
                    "type": "integer",
                    "description": "Forecast horizon for each cross-validation window.",
                },
                "freq": {
                    "type": "string",
                    "description": "Pandas frequency string for the time series.",
                },
                "n_windows": {
                    "type": "integer",
                    "description": "Number of rolling cross-validation windows. Default: 3.",
                },
                "id_col": {
                    "type": "string",
                    "description": "Optional. Column identifying different series in multi-series data.",
                },
            },
            "required": ["data_json", "time_col", "target_col", "h", "freq"],
        },
    },
]


def _get_nixtla_client() -> NixtlaClient:
    """Create a NixtlaClient for the Azure-hosted TimeGEN-1 endpoint."""
    base_url = os.getenv("TIMEGEN_BASE_URL", _TIMEGEN_DEFAULT_URL)
    api_key = os.getenv("TIMEGEN_API_KEY", "")
    if not api_key:
        raise ValueError("TIMEGEN_API_KEY environment variable is not set")
    return NixtlaClient(
        base_url=base_url,
        api_key=api_key,
    )


def _parse_data(data_json: str, time_col: str) -> pd.DataFrame:
    """Parse JSON data string into a DataFrame with proper datetime column."""
    data = json.loads(data_json)
    df = pd.DataFrame(data)
    df[time_col] = pd.to_datetime(df[time_col])
    return df


def execute_tool(tool_name: str, arguments: dict) -> str:
    """Execute a TimeGEN-1 tool and return the result as a string."""
    try:
        client = _get_nixtla_client()
        data_json = arguments["data_json"]
        time_col = arguments["time_col"]
        target_col = arguments["target_col"]
        freq = arguments["freq"]
        id_col = arguments.get("id_col")

        df = _parse_data(data_json, time_col)

        kwargs = {
            "df": df,
            "freq": freq,
            "time_col": time_col,
            "target_col": target_col,
        }
        if id_col:
            kwargs["id_col"] = id_col

        if tool_name == "forecast":
            kwargs["h"] = arguments["h"]
            if "level" in arguments:
                kwargs["level"] = arguments["level"]
            result_df = client.forecast(**kwargs)

        elif tool_name == "anomaly_detection":
            result_df = client.detect_anomalies(**kwargs)

        elif tool_name == "historic_forecast":
            kwargs["h"] = arguments["h"]
            if "level" in arguments:
                kwargs["level"] = arguments["level"]
            result_df = client.historic_forecast(**kwargs)

        elif tool_name == "cross_validation":
            kwargs["h"] = arguments["h"]
            kwargs["n_windows"] = arguments.get("n_windows", 3)
            result_df = client.cross_validation(**kwargs)

        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

        # Convert result to JSON-friendly format
        result_dict = result_df.to_dict(orient="records")
        # Serialize datetimes
        for row in result_dict:
            for k, v in row.items():
                if isinstance(v, (pd.Timestamp, datetime.datetime)):
                    row[k] = v.isoformat()

        summary = {
            "tool": tool_name,
            "rows_returned": len(result_dict),
            "columns": list(result_df.columns),
            "data": result_dict,
        }
        return json.dumps(summary, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)})


class FoundryTimeSeriesAgent:
    """AI Foundry Agent with Time Series Intelligence capabilities via Responses API."""

    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self._client: Optional[AsyncAzureOpenAI] = None
        self._initialized = False
        self._response_ids: Dict[str, str] = {}
        self.last_token_usage: Optional[Dict[str, int]] = None

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
        logger.info("Initializing Time Series agent (Responses API with function tools)...")
        # Validate TimeGEN-1 credentials
        api_key = os.getenv("TIMEGEN_API_KEY", "")
        if not api_key:
            logger.warning("TIMEGEN_API_KEY not set — tools will fail at runtime")
        else:
            logger.info(f"TimeGEN-1 endpoint: {os.getenv('TIMEGEN_BASE_URL', _TIMEGEN_DEFAULT_URL)}")
        self._get_client()
        self._initialized = True

    def _get_agent_instructions(self) -> str:
        return f"""You are an expert Time Series Intelligence analyst powered by Nixtla's TimeGEN-1 foundation model.

You help users analyze time series data by calling the right tool for their task:

- **forecast**: Predict future values (stock prices, sales, demand, resource usage, etc.)
- **anomaly_detection**: Find unusual patterns, outliers, fraud, system anomalies
- **historic_forecast**: Backtest predictions on historical data to evaluate accuracy
- **cross_validation**: Evaluate model reliability with rolling-window validation

## How to handle data

When the user provides data (CSV text, JSON, tables, or describes a dataset):

1. **Identify columns**: Determine which column is the timestamp, which is the target value, and whether there's an ID column for multi-series data. Any remaining numeric columns are exogenous variables.
2. **Determine frequency**: Infer the time frequency from the data (daily, weekly, monthly, hourly, etc.) and use the correct pandas frequency string.
3. **Structure the data**: Convert the user's data into a JSON array of objects for the tool call.
4. **Choose the right tool** based on what the user is asking for.

## Column mapping guidelines

- The timestamp column might be called: date, timestamp, ds, time, period, month, year, day, etc.
- The target column might be called: value, y, sales, price, close, amount, count, revenue, etc.
- The ID column (for multi-series) might be called: unique_id, id, ticker, symbol, store_id, category, series, etc.
- Extra numeric columns are automatically treated as exogenous features by TimeGEN-1.

## Frequency strings

Common pandas frequency aliases:
- 'D' = daily, 'B' = business day, 'W' = weekly
- 'MS' = month start, 'ME' = month end, 'QS' = quarter start
- 'H' = hourly, 'min' = minutely, 'YS' = year start

## Response guidelines

After getting tool results:
- Summarize the key findings clearly
- For forecasts: highlight trends, seasonality, and notable predictions
- For anomaly detection: list the detected anomalies with their dates and severity
- For cross-validation: report accuracy metrics and model reliability
- Always mention the number of data points analyzed and the time range
- If the data has issues (missing values, wrong format), explain what you found and ask for clarification

Current date: {datetime.datetime.now().isoformat()}

## NEEDS_INPUT - Human-in-the-Loop

Use NEEDS_INPUT to pause and ask the user a question when you need clarification:

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
            "tools": TIMESERIES_TOOLS,
            "stream": True,
            "max_output_tokens": 16000,
        }
        if session_id in self._response_ids:
            kwargs["previous_response_id"] = self._response_ids[session_id]

        retry_count = 0
        max_retries = 3

        while retry_count <= max_retries:
            try:
                response = await client.responses.create(**kwargs)
                text_chunks = []
                function_calls = {}  # id -> {name, arguments}

                async for event in response:
                    event_type = getattr(event, "type", None)

                    if event_type == "response.output_text.delta":
                        text_chunks.append(event.delta)

                    elif event_type == "response.function_call_arguments.delta":
                        item_id = getattr(event, "item_id", None)
                        if item_id and item_id in function_calls:
                            function_calls[item_id]["arguments"] += event.delta

                    elif event_type == "response.output_item.added":
                        item = getattr(event, "item", None)
                        if item and getattr(item, "type", None) == "function_call":
                            call_id = getattr(item, "id", None) or getattr(item, "item_id", None)
                            if call_id:
                                function_calls[call_id] = {
                                    "name": getattr(item, "name", ""),
                                    "call_id": getattr(item, "call_id", call_id),
                                    "arguments": "",
                                }

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

                    elif event_type == "response.failed":
                        resp = getattr(event, "response", None)
                        error_obj = getattr(resp, "error", None) if resp else None
                        yield f"Error: {getattr(error_obj, 'message', 'Unknown error') if error_obj else 'Unknown error'}"
                        return

                # If there were function calls, execute them and get final response
                if function_calls:
                    tool_results = []
                    for call_id, call_info in function_calls.items():
                        tool_name = call_info["name"]
                        yield f"\U0001f6e0\ufe0f Remote agent executing: {tool_name.replace('_', ' ').title()}"

                        try:
                            arguments = json.loads(call_info["arguments"])
                        except json.JSONDecodeError:
                            arguments = {}

                        # Run tool synchronously in executor to not block
                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(
                            None, execute_tool, tool_name, arguments
                        )

                        tool_results.append({
                            "type": "function_call_output",
                            "call_id": call_info["call_id"],
                            "output": result,
                        })

                    # Send tool results back to get final text response
                    follow_up_kwargs = {
                        "model": model,
                        "instructions": self._get_agent_instructions(),
                        "input": tool_results,
                        "previous_response_id": self._response_ids.get(session_id),
                        "stream": True,
                        "max_output_tokens": 4000,
                    }

                    follow_up_response = await client.responses.create(**follow_up_kwargs)
                    final_chunks = []

                    async for event in follow_up_response:
                        event_type = getattr(event, "type", None)
                        if event_type == "response.output_text.delta":
                            final_chunks.append(event.delta)
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

                    if final_chunks:
                        yield "".join(final_chunks)
                    else:
                        yield "Analysis complete but no summary was generated."

                elif text_chunks:
                    yield "".join(text_chunks)
                else:
                    yield "Error: Agent completed but no response was generated."
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
