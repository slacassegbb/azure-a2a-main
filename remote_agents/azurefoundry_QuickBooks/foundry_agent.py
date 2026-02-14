"""
AI Foundry Agent implementation with QuickBooks Online Accounting Capabilities.
Uses the Responses API with native MCP tool support for efficient token usage.

Migrated from Assistants/Agents API (AgentsClient with threads/runs) to the
Responses API (AsyncAzureOpenAI with responses.create) to eliminate the thread
re-processing overhead that caused excessive prompt tokens per workflow.

IMPORTANT: QUOTA REQUIREMENTS FOR AZURE AI FOUNDRY AGENTS
=========================================================
Ensure your model deployment has at least 20,000 TPM allocated to avoid rate limiting.
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


# QuickBooks MCP Server URL (deployed on Azure Container Apps)
QUICKBOOKS_MCP_URL = os.getenv(
    "QUICKBOOKS_MCP_URL",
    "https://mcp-quickbooks.ambitioussky-6c709152.westus2.azurecontainerapps.io/sse"
)

# Allowed QuickBooks MCP tools (trimmed to 16 high-value tools)
# Removed: qbo_search_vendors (qbo_create_vendor handles duplicate detection internally)
# Removed: qbo_query (power tool the LLM misuses — all queries covered by search tools)
# Removed: qbo_search_accounts, qbo_get_account (default account "7" — LLM wastes calls)
# Removed: qbo_search_items, qbo_get_item (bills/invoices use amount directly)
# The MCP server still registers ALL tools — other clients can use them.
QUICKBOOKS_ALLOWED_TOOLS = [
    # === Reports & Company ===
    "qbo_report",           # Financial reports (ProfitAndLoss, BalanceSheet, CashFlow)
    "qbo_company_info",     # Get company information
    # === Invoices (AR) ===
    "qbo_search_invoices",  # Search invoices
    "qbo_get_invoice",      # Get invoice by ID
    "qbo_create_invoice",   # Create invoice with line items array
    # === Customers ===
    "qbo_search_customers", # Search customers
    "qbo_get_customer",     # Get customer by ID
    "qbo_create_customer",  # Create customer
    # === Bills (AP) ===
    "qbo_search_bills",     # Search bills/payables (NOT during creation!)
    "qbo_get_bill",         # Get bill by ID
    "qbo_create_bill",      # Create bill with line items array
    # === Vendors ===
    "qbo_get_vendor",       # Get vendor by ID
    "qbo_create_vendor",    # Create vendor (handles duplicates internally — no search needed)
    # === Bill Payments ===
    "qbo_search_bill_payments",  # Search bill payments
    "qbo_get_bill_payment",      # Get payment by ID
    "qbo_create_bill_payment",   # Pay a bill
]


class FoundryQuickBooksAgent:
    """
    AI Foundry Agent with QuickBooks Online accounting capabilities.
    Uses the Responses API with native MCP tool support.
    """

    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self._client: Optional[AsyncAzureOpenAI] = None
        self._initialized = False
        self._response_ids: Dict[str, str] = {}  # session_id -> last_response_id
        self.last_token_usage: Optional[Dict[str, int]] = None

        # MCP tool configuration for Responses API
        self._mcp_tool_config = {
            "type": "mcp",
            "server_label": "QuickBooks",
            "server_url": QUICKBOOKS_MCP_URL,
            "require_approval": "never",
            "allowed_tools": QUICKBOOKS_ALLOWED_TOOLS,
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

        logger.info("🚀 INITIALIZING QUICKBOOKS AGENT (Responses API)...")
        logger.info(f"   MCP Server: {QUICKBOOKS_MCP_URL}")

        # Test MCP server connectivity
        try:
            base_url = QUICKBOOKS_MCP_URL.rstrip("/sse")
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
        logger.info(f"✅ QuickBooks agent initialized (model: {model}, tools: {len(QUICKBOOKS_ALLOWED_TOOLS)})")
        self._initialized = True

    def _get_agent_instructions(self) -> str:
        """Get the agent instructions for QuickBooks Online accounting capabilities."""
        return f"""You are a QuickBooks Online assistant. Current date: {datetime.datetime.now().isoformat()}

SYSTEM TOOL HINT: When users ask about QuickBooks data, use the appropriate qbo_* tools.
For customers use qbo_search_customers/qbo_get_customer/qbo_create_customer.
For invoices use qbo_search_invoices/qbo_get_invoice/qbo_create_invoice.
For bills use qbo_search_bills/qbo_get_bill/qbo_create_bill.
For vendors use qbo_get_vendor/qbo_create_vendor (create_vendor handles duplicate detection).
For reports use qbo_report. For company info use qbo_company_info.

## CRITICAL: BILL vs INVOICE - KNOW THE DIFFERENCE!

**BILL (qbo_create_bill)** = Money YOU OWE to a VENDOR
- Use when: "Create bill for vendor", "Record vendor invoice", "Enter payable", "Pay U1 Software"
- The VENDOR sent YOU an invoice that you need to pay
- Example: Vendor U1 Software LLC sends you an invoice for $18,828

**INVOICE (qbo_create_invoice)** = Money a CUSTOMER OWES YOU
- Use when: "Invoice the customer", "Bill the client", "Create invoice for Cay Digital"
- YOU are billing a CUSTOMER for your services
- Example: You invoice Cay Digital LLC $18,828 for work you did

## WORKFLOW: CREATING A BILL (Vendor Payable) — EXACTLY 2 TOOL CALLS!

When asked to "create a BILL" or record a vendor invoice:

**Step 1**: Call qbo_create_vendor with displayName — it handles duplicates automatically (returns existing vendor if found)
**Step 2**: Call qbo_create_bill with vendorId from step 1 + all line items

```json
{{{{
  "vendorId": "123",
  "lineItems": [
    {{{{ "amount": 3200.00, "description": "Prompt engineering - 160 hours @ $20/hr" }}}},
    {{{{ "amount": 3872.00, "description": "Quality assurance - 176 hours @ $22/hr" }}}}
  ],
  "dueDate": "2025-02-15",
  "docNumber": "2512-036-1"
}}}}
```

⚠️ **PROHIBITED during bill creation — DO NOT call these tools:**
- DO NOT call qbo_search_vendors before qbo_create_vendor (it handles duplicates internally)
- DO NOT call qbo_query for any reason during bill creation
- DO NOT call qbo_search_bills during bill creation
- DO NOT call qbo_search_accounts — use default account "7" for expenses

That's it — 2 tool calls total! The tools handle all the QuickBooks API complexity internally.

## WORKFLOW: CREATING AN INVOICE (Customer Receivable)

When asked to "create an INVOICE" or bill a customer:

1. **Get/Create Customer**: Call qbo_search_customers or qbo_create_customer
2. **Create Invoice**: Call qbo_create_invoice:

```json
{{{{
  "customerId": "77",
  "lineItems": [
    {{{{ "amount": 3200.00, "description": "Software development services" }}}},
    {{{{ "amount": 1500.00, "description": "Cloud hosting" }}}}
  ],
  "dueDate": "2025-02-15",
  "docNumber": "INV-2025-001"
}}}}
```

## KEY RULES:

1. **USE THE DATA PROVIDED** - Don't ask for info already in context
2. **MINIMIZE TOOL CALLS** - Bill creation = exactly 2 calls. Invoice creation = exactly 2 calls.
3. **qbo_create_vendor handles duplicates** - NEVER search for vendors before creating. Just call qbo_create_vendor directly.
4. **Don't ask for confirmation** - If data is provided, just create the bill/invoice (UNLESS the instruction says "HITL REQUIRED" or "ask the user")
5. **Default account for bills is "7"** - NEVER call qbo_search_accounts or qbo_query to look up accounts
6. **NO unnecessary queries** - Do NOT call qbo_query, qbo_search_bills, or qbo_search_vendors during bill/invoice creation workflows

## NEEDS_INPUT - Human-in-the-Loop (HITL)

Use NEEDS_INPUT to pause and ask the user a question. This will pause the workflow until the user responds.

```NEEDS_INPUT
Your question to the user here
```END_NEEDS_INPUT

**When to use NEEDS_INPUT:**
1. When information is genuinely MISSING from the context
2. When the workflow instruction says "HITL REQUIRED" or "ask the user" - you MUST ask even if you have some data

**IMPORTANT:** If a workflow step says "HITL REQUIRED", ALWAYS use NEEDS_INPUT to ask the user.
Do NOT skip asking just because you have some data - the workflow explicitly wants human confirmation.
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
                        # MCP tools failed — report as error with the LLM's explanation
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
                        yield f"❌ Rate limit exceeded after {max_retries} retries - please wait and try again later"
                        return
                else:
                    logger.error(f"❌ Error in conversation stream: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    yield f"Error: {str(e)}"
                    return

    def _get_tool_description(self, tool_name: str) -> str:
        """Get a human-readable description for a QuickBooks tool call."""
        if not tool_name or not tool_name.startswith("qbo_"):
            return tool_name or "mcp_tool"

        # Parse the QuickBooks tool name
        parts = tool_name.replace("qbo_", "").split("_")
        action = parts[0] if parts else "executing"
        entity = " ".join(parts[1:]) if len(parts) > 1 else "data"

        descriptions = {
            "search": f"Searching QuickBooks {entity}",
            "get": f"Getting QuickBooks {entity}",
            "create": f"Creating QuickBooks {entity}",
            "update": f"Updating QuickBooks {entity}",
            "delete": f"Deleting QuickBooks {entity}",
            "query": "Executing QuickBooks query",
            "company": "Getting QuickBooks company info",
            "report": "Generating QuickBooks report",
        }

        return descriptions.get(action, f"QuickBooks: {tool_name.replace('qbo_', '').replace('_', ' ').title()}")

    async def run_conversation(self, session_id: str, user_message: str) -> str:
        """Non-streaming version - collects all responses."""
        responses = []
        async for response in self.run_conversation_stream(session_id, user_message):
            responses.append(response)
        return "\n".join(responses)

    async def chat(self, session_id: str, user_message: str) -> str:
        """Alias for run_conversation - for executor compatibility."""
        return await self.run_conversation(session_id, user_message)
