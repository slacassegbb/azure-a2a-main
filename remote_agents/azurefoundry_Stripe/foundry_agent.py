"""
AI Foundry Agent implementation with Stripe Payment Processing Capabilities.
Uses the Responses API with native MCP tool support for efficient token usage.

Migrated from Assistants/Agents API (AgentsClient with threads/runs) to the
Responses API (AsyncAzureOpenAI with responses.create) to eliminate the thread
re-processing overhead that caused 44K+ prompt tokens per workflow.

IMPORTANT: QUOTA REQUIREMENTS FOR AZURE AI FOUNDRY AGENTS
=========================================================
Ensure your model deployment has at least 20,000 TPM allocated to avoid rate limiting.
"""
import os
import time
import asyncio
import logging
from typing import Optional, Dict

import httpx
from openai import AsyncAzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

logger = logging.getLogger(__name__)


# Stripe MCP Server URL (deployed on Azure Container Apps)
STRIPE_MCP_URL = os.getenv(
    "STRIPE_MCP_URL",
    "https://mcp-stripe.ambitioussky-6c709152.westus2.azurecontainerapps.io/sse"
)

# Allowed Stripe MCP tools (trimmed to ~12 high-value tools)
# Removing granular invoice tools (superseded by create_full_invoice),
# product/price management, payment links, coupons, and docs search
# to reduce token overhead and prevent the LLM from making unnecessary calls.
# The MCP server still registers ALL tools — other clients can use them.
STRIPE_ALLOWED_TOOLS = [
    # Invoices — BATCHED (the primary tool for invoice workflows)
    "create_full_invoice",
    # Invoice queries
    "list_invoices",
    # Customer Management
    "create_customer",
    "list_customers",
    # Balance & Payments
    "retrieve_balance",
    "list_payment_intents",
    "create_refund",
    # Subscriptions
    "list_subscriptions",
    "cancel_subscription",
    "update_subscription",
    # Disputes
    "list_disputes",
    "update_dispute",
]


class FoundryStripeAgent:
    """
    AI Foundry Agent with Stripe Payment Processing capabilities.
    Uses the Responses API with native MCP tool support.
    """

    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self._client: Optional[AsyncAzureOpenAI] = None
        self._initialized = False
        self._response_ids: Dict[str, str] = {}  # session_id → last_response_id
        self.last_token_usage: Optional[Dict[str, int]] = None

        # MCP tool configuration for Responses API
        self._mcp_tool_config = {
            "type": "mcp",
            "server_label": "Stripe",
            "server_url": STRIPE_MCP_URL,
            "require_approval": "never",
            "allowed_tools": STRIPE_ALLOWED_TOOLS,
            "headers": {
                "Content-Type": "application/json",
                "User-Agent": "Azure-AI-Foundry-Agent",
                "Accept": "application/json, text/event-stream",
            },
        }

    def _get_client(self) -> AsyncAzureOpenAI:
        """Get a cached AsyncAzureOpenAI client."""
        if self._client is None:
            # Convert AI Foundry endpoint to Azure OpenAI endpoint
            # From: https://RESOURCE.services.ai.azure.com/subscriptions/...
            # To:   https://RESOURCE.openai.azure.com/openai/v1/
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
                self.credential,
                "https://cognitiveservices.azure.com/.default",
            )

            self._client = AsyncAzureOpenAI(
                base_url=openai_endpoint,
                azure_ad_token_provider=token_provider,
                api_version="preview",
            )
            logger.info(f"Created AsyncAzureOpenAI client with endpoint: {openai_endpoint}")

        return self._client

    async def create_agent(self) -> None:
        """Initialize the agent: test MCP connectivity and create client.

        Named create_agent() for backward compatibility with the executor's
        initialize_at_startup() which calls this method.
        """
        if self._initialized:
            logger.info("Agent already initialized, skipping")
            return

        logger.info("🚀 INITIALIZING STRIPE AGENT (Responses API)...")
        logger.info(f"   MCP Server: {STRIPE_MCP_URL}")

        # Test MCP server connectivity
        try:
            base_url = STRIPE_MCP_URL.rstrip("/sse")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(base_url)
                if response.status_code == 200:
                    logger.info("✅ MCP Server connectivity test PASSED")
                else:
                    logger.warning(f"⚠️ MCP Server returned status: {response.status_code}")
        except Exception as e:
            logger.warning(f"⚠️ MCP Server connectivity test failed: {e}")
            logger.warning("Continuing anyway - MCP server may still work via Responses API")

        # Initialize the OpenAI client
        self._get_client()

        model = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")
        logger.info(f"✅ Stripe agent initialized (model: {model}, tools: {len(STRIPE_ALLOWED_TOOLS)})")
        self._initialized = True

    def _get_agent_instructions(self) -> str:
        """Get the agent instructions for Stripe payment processing."""
        return """You are an expert Stripe payment processing assistant. You help users manage their Stripe account.

## Your Capabilities

You have access to Stripe MCP tools for:
- **Invoices (BATCHED)**: create_full_invoice — creates customer + invoice + all line items + finalizes in ONE call
- **Invoice Queries**: list_invoices
- **Customer Management**: create_customer, list_customers
- **Balance & Payments**: retrieve_balance, create_refund, list_payment_intents
- **Subscriptions**: list_subscriptions, cancel_subscription, update_subscription
- **Disputes**: list_disputes, update_dispute

## KEY RULES:

1. **USE THE DATA PROVIDED** - Don't ask for info already in the context
2. **MINIMIZE TOOL CALLS** - Use batched tools whenever possible
3. **Don't ask for confirmation** - If you have the data, just do the task
4. **ALWAYS PROVIDE A SUMMARY** - After completing tool calls, write a brief summary of what you did
5. **DO NOT create products or prices for invoices** - Use amount in cents directly
6. **AGGREGATE QUERIES = ALL DATA** - When asked for "total revenue", "all payments", "failed payments last month", etc., query across the ENTIRE Stripe account — do NOT ask for a specific customer ID. Use list_payment_intents without customer filters to get account-wide data.

## CRITICAL: CREATING INVOICES — USE create_full_invoice (1 TOOL CALL!)

⚠️ ALWAYS use create_full_invoice for invoice creation. It handles EVERYTHING in one call:
- Finds existing customer by email OR creates a new one
- Creates the invoice
- Adds ALL line items at once
- Finalizes the invoice

**Example — ONE tool call for a complete invoice:**
```
create_full_invoice with: {
  "customer_email": "vendor@example.com",
  "customer_name": "Vendor Name",
  "line_items": [
    {"amount": 320000, "description": "Prompt engineering - 160 hours @ $20/hr"},
    {"amount": 387200, "description": "Quality assurance - 176 hours @ $22/hr"},
    {"amount": 264000, "description": "Data annotation - 120 hours @ $22/hr"}
  ],
  "description": "Invoice for services",
  "finalize": true
}
```
- Amounts are in CENTS (100 = $1.00, so $3,200.00 = 320000)
- DO NOT use create_invoice + create_invoice_item separately!
- DO NOT use create_product or create_price!
- DO NOT call list_customers first — create_full_invoice handles customer lookup!

**After the invoice is created, ALWAYS write a summary like:**
"✅ Created invoice [invoice_id] for [customer_name] with [X] line items totaling $[amount]"

## Error Reporting (CRITICAL)

If you CANNOT complete the requested task — due to rate limits, API errors, missing data,
authentication failures, or any other reason — you MUST start your response with "Error:".

Examples:
- "Error: Rate limit exceeded. Please try again later."
- "Error: Authentication failed — invalid credentials."
- "Error: Could not complete the request due to a service outage."

Do NOT write a polite explanation without the "Error:" prefix. The system uses this prefix
to detect failures. Without it, the task is marked as successful even though it failed.

## ASKING FOR INPUT:

Only if information is genuinely MISSING:
```
NEEDS_INPUT: Your specific question here
```
"""

    async def create_session(self) -> str:
        """Create a new conversation session (replaces create_thread)."""
        session_id = f"session_{int(time.time())}_{os.urandom(4).hex()}"
        logger.info(f"Created new session: {session_id}")
        return session_id

    async def run_conversation_stream(self, session_id: str, user_message: str):
        """Run conversation using Responses API with native MCP and yield responses.

        Yields:
            - "🛠️ Remote agent executing: ..." for tool call status (real-time)
            - Final response text (after all tool calls complete)
            - "Error:" or "❌" prefixed messages on failure
        """
        logger.info(f"🚀 STARTING CONVERSATION STREAM (Responses API)")
        logger.info(f"   Session ID: {session_id}")
        logger.info(f"   Message length: {len(user_message)} chars")

        if not self._initialized:
            await self.create_agent()

        client = self._get_client()
        model = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")
        instructions = self._get_agent_instructions()

        kwargs = {
            "model": model,
            "instructions": instructions,
            "input": [{"role": "user", "content": user_message}],
            "tools": [self._mcp_tool_config],
            "stream": True,
            "max_output_tokens": 4000,
        }

        # Chain conversation for multi-turn support
        if session_id in self._response_ids:
            kwargs["previous_response_id"] = self._response_ids[session_id]
            logger.info(f"   Chaining to previous response: {self._response_ids[session_id]}")

        retry_count = 0
        max_retries = 3

        while retry_count <= max_retries:
            try:
                stream_start = time.time()
                logger.info(f"📡 Calling responses.create() (attempt {retry_count + 1}/{max_retries + 1})...")
                response = await client.responses.create(**kwargs)
                api_latency = time.time() - stream_start
                logger.info(f"📡 responses.create() returned in {api_latency:.2f}s - starting stream iteration")

                # Accumulate text deltas, yield tool status immediately
                text_chunks = []
                tool_calls_seen = set()
                mcp_failures = []  # Track MCP tool call failures
                event_count = 0
                tool_call_times = {}

                async for event in response:
                    event_count += 1
                    event_type = getattr(event, 'type', None)

                    # Debug: log every event type
                    if event_type and event_type != "response.output_text.delta":
                        logger.info(f"🔍 Event #{event_count}: {event_type}")

                    if event_type == "response.output_text.delta":
                        text_chunks.append(event.delta)

                    elif event_type == "response.mcp_call.in_progress":
                        # MCP tool call started - yield status for real-time updates
                        tool_name = getattr(event, 'name', 'mcp_tool')
                        if tool_name not in tool_calls_seen:
                            tool_calls_seen.add(tool_name)
                            tool_call_times[tool_name] = time.time()
                            elapsed = time.time() - stream_start
                            logger.info(f"🛠️ MCP tool call: {tool_name} (at +{elapsed:.1f}s)")
                            tool_description = self._get_tool_description(tool_name)
                            yield f"🛠️ Remote agent executing: {tool_description}"

                    elif event_type == "response.mcp_call.completed":
                        tool_name = getattr(event, 'name', 'mcp_tool')
                        start_t = tool_call_times.get(tool_name, stream_start)
                        duration = time.time() - start_t
                        logger.info(f"✅ MCP tool completed: {tool_name} ({duration:.1f}s)")

                    elif event_type == "response.mcp_call.failed":
                        tool_name = getattr(event, 'name', None) or getattr(event, 'item_id', 'mcp_tool')
                        start_t = tool_call_times.get(tool_name, stream_start)
                        duration = time.time() - start_t
                        logger.error(f"❌ MCP tool FAILED: {tool_name} ({duration:.1f}s)")
                        mcp_failures.append(tool_name)

                    elif event_type == "response.failed":
                        resp = getattr(event, 'response', None)
                        error_obj = getattr(resp, 'error', None) if resp else None
                        error_msg = getattr(error_obj, 'message', 'Unknown error') if error_obj else 'Unknown error'
                        logger.error(f"❌ Response FAILED: {error_msg}")
                        yield f"Error: {error_msg}"
                        return

                    elif event_type == "response.output_item.added":
                        # Alternative event for tool calls - check if it's an MCP call
                        item = getattr(event, 'item', None)
                        if item:
                            item_type = getattr(item, 'type', None)
                            if item_type in ("mcp_call", "mcp_tool_call"):
                                tool_name = getattr(item, 'name', None) or getattr(item, 'tool_name', 'mcp_tool')
                                if tool_name not in tool_calls_seen:
                                    tool_calls_seen.add(tool_name)
                                    tool_call_times[tool_name] = time.time()
                                    elapsed = time.time() - stream_start
                                    logger.info(f"🛠️ MCP tool call (via output_item): {tool_name} (at +{elapsed:.1f}s)")
                                    tool_description = self._get_tool_description(tool_name)
                                    yield f"🛠️ Remote agent executing: {tool_description}"

                    elif event_type == "response.completed" or event_type == "response.done":
                        total_time = time.time() - stream_start
                        # Extract token usage from completed response
                        resp = getattr(event, 'response', None)
                        if resp:
                            usage = getattr(resp, 'usage', None)
                            if usage:
                                self.last_token_usage = {
                                    "prompt_tokens": getattr(usage, 'prompt_tokens', 0) or getattr(usage, 'input_tokens', 0),
                                    "completion_tokens": getattr(usage, 'completion_tokens', 0) or getattr(usage, 'output_tokens', 0),
                                    "total_tokens": getattr(usage, 'total_tokens', 0),
                                }
                                logger.info(f"📊 Token usage: {self.last_token_usage}")
                                logger.info(f"📊 Total stream time: {total_time:.1f}s | Events: {event_count} | Tools: {list(tool_calls_seen)}")

                            # Store response ID for conversation continuity
                            resp_id = getattr(resp, 'id', None)
                            if resp_id:
                                self._response_ids[session_id] = resp_id

                # Yield accumulated text as the final response
                if text_chunks:
                    full_text = "".join(text_chunks)
                    if mcp_failures:
                        failed_tools = ", ".join(mcp_failures)
                        logger.error(f"❌ MCP tools failed ({failed_tools}), reporting as error")
                        yield f"Error: MCP tool(s) failed ({failed_tools}). {full_text}"
                    else:
                        logger.info(f"✅ Response text ({len(full_text)} chars)")
                        yield full_text
                else:
                    logger.warning("⚠️ No text content in response")
                    yield "Error: Agent completed but no response text was generated"

                return  # Success

            except Exception as e:
                elapsed = time.time() - stream_start
                error_str = str(e).lower()
                logger.error(f"❌ Exception after {elapsed:.1f}s, {event_count} events, tools so far: {list(tool_calls_seen)}")
                logger.error(f"❌ Error type: {type(e).__name__} | Message: {e}")

                # Try to extract rate limit details from the exception
                if hasattr(e, 'response') and e.response is not None:
                    headers = getattr(e.response, 'headers', {})
                    retry_after = headers.get('retry-after') or headers.get('Retry-After')
                    remaining = headers.get('x-ratelimit-remaining-tokens') or headers.get('x-ratelimit-remaining-requests')
                    limit = headers.get('x-ratelimit-limit-tokens') or headers.get('x-ratelimit-limit-requests')
                    logger.error(f"❌ Rate limit headers - retry-after: {retry_after}, remaining: {remaining}, limit: {limit}")

                if "rate_limit" in error_str or "429" in error_str or "too many requests" in error_str:
                    retry_count += 1
                    if retry_count <= max_retries:
                        backoff = min(15 * (2 ** retry_count), 60)
                        logger.warning(f"🔄 Rate limit - retry {retry_count}/{max_retries} after {backoff}s")
                        yield f"⏳ Rate limit hit - retrying in {backoff}s (attempt {retry_count}/{max_retries})..."
                        await asyncio.sleep(backoff)
                        continue
                    else:
                        logger.error(f"❌ Max retries ({max_retries}) exceeded for rate limit")
                        yield f"Error: Rate limit exceeded after {max_retries} retries - please wait and try again later"
                        return
                else:
                    logger.error(f"❌ Error in conversation stream: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    yield f"Error: {str(e)}"
                    return

    async def run_conversation(self, session_id: str, user_message: str) -> str:
        """Non-streaming version - collects all responses."""
        responses = []
        async for response in self.run_conversation_stream(session_id, user_message):
            responses.append(response)
        return "\n".join(responses)

    def _get_tool_description(self, tool_name: str) -> str:
        """Get a human-readable description for a Stripe tool call."""
        descriptions = {
            "create_full_invoice": "Creating Stripe invoice with all line items",
            "list_invoices": "Searching Stripe invoices",
            "create_customer": "Creating Stripe customer",
            "list_customers": "Looking up Stripe customers",
            "retrieve_balance": "Retrieving Stripe account balance",
            "list_payment_intents": "Listing Stripe payments",
            "create_refund": "Processing Stripe refund",
            "list_subscriptions": "Listing Stripe subscriptions",
            "cancel_subscription": "Cancelling Stripe subscription",
            "update_subscription": "Updating Stripe subscription",
            "list_disputes": "Listing Stripe disputes",
            "update_dispute": "Updating Stripe dispute",
        }
        return descriptions.get(tool_name, tool_name.replace("_", " ").title() if tool_name else "Processing")

    async def chat(self, session_id: str, user_message: str) -> str:
        """Alias for run_conversation - for executor compatibility."""
        return await self.run_conversation(session_id, user_message)
