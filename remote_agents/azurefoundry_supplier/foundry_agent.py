"""
AI Foundry Supplier Agent with PostgreSQL-backed product catalog.
Uses the Responses API with function tools for database queries.
The LLM writes SQL dynamically based on user questions.
"""
import os
import json
import time
import datetime
import asyncio
import logging
from typing import Optional, Dict

from openai import AsyncAzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

logger = logging.getLogger(__name__)

# Database schema provided to the LLM so it can write accurate SQL
DATABASE_SCHEMA = """
## Database Tables (PostgreSQL)

### supplier_categories
- id SERIAL PRIMARY KEY
- name VARCHAR(100) NOT NULL (e.g., "Fine Paper", "Packaging", "Industrial Supplies")
- parent_category_id INTEGER (self-referencing FK for subcategories)
- description TEXT

### supplier_manufacturers
- id SERIAL PRIMARY KEY
- name VARCHAR(150) NOT NULL (e.g., "Domtar", "International Paper", "3M")
- website VARCHAR(255)
- country VARCHAR(100)
- lead_time_days_min INTEGER (typical minimum lead time)
- lead_time_days_max INTEGER (typical maximum lead time)

### supplier_products
- id SERIAL PRIMARY KEY
- sku VARCHAR(50) UNIQUE NOT NULL (e.g., "FP-BOND-2024-001")
- name VARCHAR(255) NOT NULL
- description TEXT
- category_id INTEGER REFERENCES supplier_categories(id)
- manufacturer_id INTEGER REFERENCES supplier_manufacturers(id)
- unit_price DECIMAL(10,2) (base unit price)
- unit_of_measure VARCHAR(50) (e.g., "ream", "case", "roll", "box", "each")
- weight_lbs DECIMAL(8,2)
- dimensions VARCHAR(100) (e.g., "8.5x11", "24x36")
- stock_status VARCHAR(20) (in_stock, low_stock, backordered, discontinued)
- stock_quantity INTEGER
- lead_time_days INTEGER (specific product lead time)
- minimum_order_quantity INTEGER DEFAULT 1
- is_active BOOLEAN DEFAULT TRUE
- tags TEXT[] (PostgreSQL array, e.g., {"recycled", "FSC-certified", "bulk"})
- created_at TIMESTAMP DEFAULT NOW()

### supplier_price_tiers
- id SERIAL PRIMARY KEY
- product_id INTEGER REFERENCES supplier_products(id)
- min_quantity INTEGER NOT NULL
- max_quantity INTEGER
- unit_price DECIMAL(10,2) NOT NULL
- discount_percent DECIMAL(5,2)

### supplier_product_relations
- id SERIAL PRIMARY KEY
- product_id INTEGER REFERENCES supplier_products(id)
- related_product_id INTEGER REFERENCES supplier_products(id)
- relation_type VARCHAR(30) NOT NULL (alternative, complementary, upsell, accessory)
- relevance_score DECIMAL(3,2) DEFAULT 0.5 (0.0 to 1.0)

### Useful JOINs
- Products with category: supplier_products p JOIN supplier_categories c ON p.category_id = c.id
- Products with manufacturer: supplier_products p JOIN supplier_manufacturers m ON p.manufacturer_id = m.id
- Price tiers: supplier_products p JOIN supplier_price_tiers t ON t.product_id = p.id
- Related products: supplier_product_relations r JOIN supplier_products rp ON r.related_product_id = rp.id
"""

# Function tool definitions for the Responses API
SQL_QUERY_TOOL = {
    "type": "function",
    "name": "execute_sql_query",
    "description": (
        "Execute a read-only SQL SELECT query against the supplier product database. "
        "Use this to look up products, pricing, availability, lead times, alternatives, "
        "and any other product catalog information. Only SELECT statements are allowed. "
        "Returns rows as JSON array. Limit results to 25 rows unless the user needs more."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A PostgreSQL SELECT query. Must start with SELECT."
            },
            "explanation": {
                "type": "string",
                "description": "Brief explanation of what this query does and why."
            }
        },
        "required": ["query"],
        "additionalProperties": False
    }
}

SQL_UPDATE_TOOL = {
    "type": "function",
    "name": "update_supplier_data",
    "description": (
        "Update product data in the supplier database. Use this to update lead times, "
        "stock status, stock quantities, or pricing when new information is received "
        "(e.g., supplier confirmed a new lead time, product is now backordered, etc.). "
        "Only UPDATE statements on supplier_* tables are allowed. Returns number of rows affected."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A PostgreSQL UPDATE query. Must start with UPDATE and target a supplier_* table."
            },
            "explanation": {
                "type": "string",
                "description": "What is being updated and why (e.g., 'Updating lead time for SKU X per supplier response')."
            }
        },
        "required": ["query", "explanation"],
        "additionalProperties": False
    }
}


class FoundrySupplierAgent:
    """AI Foundry Supplier Agent with PostgreSQL product catalog via Responses API."""

    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self._client: Optional[AsyncAzureOpenAI] = None
        self._initialized = False
        self._response_ids: Dict[str, str] = {}
        self.last_token_usage: Optional[Dict[str, int]] = None
        self._db_pool = None

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

    async def _get_db_pool(self):
        """Get or create async connection pool for PostgreSQL."""
        if self._db_pool is None:
            import asyncpg
            database_url = os.environ.get("DATABASE_URL", "")
            if not database_url:
                raise ValueError("DATABASE_URL environment variable is required")
            self._db_pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
        return self._db_pool

    async def _execute_sql(self, query: str) -> str:
        """Execute a read-only SQL SELECT query and return results as JSON."""
        query_stripped = query.strip().rstrip(";").strip()

        if not query_stripped.upper().startswith("SELECT"):
            return json.dumps({"error": "Only SELECT queries are allowed. Use update_supplier_data for updates."})

        # Block dangerous patterns
        dangerous = ["DROP", "DELETE", "INSERT", "ALTER", "CREATE", "TRUNCATE", "GRANT", "REVOKE"]
        upper_query = query_stripped.upper()
        for keyword in dangerous:
            if f" {keyword} " in f" {upper_query} ":
                return json.dumps({"error": f"Query contains disallowed keyword: {keyword}"})

        try:
            pool = await self._get_db_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(query_stripped)
                results = [dict(row) for row in rows]
                for row in results:
                    for key, value in row.items():
                        if isinstance(value, (datetime.datetime, datetime.date)):
                            row[key] = value.isoformat()
                        elif isinstance(value, bytes):
                            row[key] = value.hex()
                        elif hasattr(value, '__float__'):
                            row[key] = float(value)

                if not results:
                    return json.dumps({"results": [], "message": "No rows found."})
                return json.dumps({"results": results, "row_count": len(results)})
        except Exception as e:
            logger.error(f"SQL execution error: {e}")
            return json.dumps({"error": str(e)})

    async def _execute_update(self, query: str) -> str:
        """Execute an UPDATE query on supplier_* tables only."""
        query_stripped = query.strip().rstrip(";").strip()
        upper_query = query_stripped.upper()

        # Must be UPDATE
        if not upper_query.startswith("UPDATE"):
            return json.dumps({"error": "Only UPDATE statements are allowed."})

        # Must target a supplier_ table
        import re
        table_match = re.match(r'UPDATE\s+(\w+)', query_stripped, re.IGNORECASE)
        if not table_match or not table_match.group(1).startswith("supplier_"):
            return json.dumps({"error": "Can only UPDATE supplier_* tables (supplier_products, supplier_manufacturers, etc.)."})

        # Block dangerous patterns
        for keyword in ["DROP", "DELETE", "INSERT", "ALTER", "CREATE", "TRUNCATE", "GRANT", "REVOKE", ";", "--"]:
            if keyword in upper_query and keyword not in ("UPDATE",):
                return json.dumps({"error": f"Query contains disallowed keyword: {keyword}"})

        # Must have a WHERE clause (no blanket updates)
        if "WHERE" not in upper_query:
            return json.dumps({"error": "UPDATE must include a WHERE clause to target specific rows."})

        try:
            pool = await self._get_db_pool()
            async with pool.acquire() as conn:
                result = await conn.execute(query_stripped)
                rows_affected = int(result.split()[-1]) if result else 0
                logger.info(f"UPDATE executed: {rows_affected} rows affected. Query: {query_stripped[:200]}")
                return json.dumps({"success": True, "rows_affected": rows_affected, "message": f"Updated {rows_affected} row(s)."})
        except Exception as e:
            logger.error(f"SQL update error: {e}")
            return json.dumps({"error": str(e)})

    async def create_agent(self) -> None:
        if self._initialized:
            return
        logger.info("Initializing Supplier agent (Responses API with PostgreSQL)...")

        # Ensure database is seeded
        try:
            from seed_database import ensure_database_seeded
            await ensure_database_seeded()
            logger.info("Database seed check complete.")
        except Exception as e:
            logger.warning(f"Database seed check failed: {e} (continuing anyway)")

        self._get_client()
        self._initialized = True

    def _get_agent_instructions(self) -> str:
        return f"""You are an intelligent Supplier Agent that helps users find products, check pricing and availability, look up lead times, find replacements or alternatives, and make cross-sell/upsell recommendations.

You have access to a PostgreSQL product catalog database via two tools:
- **execute_sql_query**: For SELECT queries — look up products, pricing, inventory, lead times, relationships.
- **update_supplier_data**: For UPDATE queries — update lead times, stock status, pricing when new information is received from suppliers.

{DATABASE_SCHEMA}

## Guidelines

1. **Always query the database** to answer questions — never make up product information.
2. **Be helpful and proactive**: If a product is out of stock or has long lead times, automatically suggest alternatives.
3. **Show pricing clearly**: Include unit prices and bulk discount tiers when relevant.
4. **Format responses nicely**: Use markdown tables for product comparisons, bullet points for details.
5. **Handle ambiguity**: If a query is vague, search broadly and present options. Ask for clarification if needed.
   **When searching by product name from an external source (email, alert, message), the name may not match exactly. Always search using individual keywords rather than the full name string.** For example, for "Bond Paper 24lb" search with `p.name ILIKE '%bond%' AND p.name ILIKE '%24lb%'` — never use the full multi-word name as a single ILIKE pattern.
6. **Cross-sell/Upsell**: When appropriate, mention complementary products or premium alternatives.
7. **Lead time awareness**: Always mention lead times when they could affect a buying decision.
8. **Stock status**: Flag low stock or backordered items proactively.
9. **Update data when instructed**: When told a supplier has confirmed new lead times, stock changes, or pricing changes, use update_supplier_data to persist the changes. Always confirm what was updated.

## Example Query Patterns

- Product search: SELECT p.*, c.name as category, m.name as manufacturer FROM supplier_products p JOIN supplier_categories c ON p.category_id = c.id JOIN supplier_manufacturers m ON p.manufacturer_id = m.id WHERE p.name ILIKE '%search_term%' AND p.is_active = TRUE LIMIT 25
- Alternatives: SELECT rp.*, m.name as manufacturer FROM supplier_product_relations r JOIN supplier_products rp ON r.related_product_id = rp.id JOIN supplier_manufacturers m ON rp.manufacturer_id = m.id WHERE r.product_id = X AND r.relation_type = 'alternative' AND rp.is_active = TRUE ORDER BY rp.lead_time_days ASC
- Price tiers: SELECT * FROM supplier_price_tiers WHERE product_id = X ORDER BY min_quantity ASC

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
            "tools": [SQL_QUERY_TOOL, SQL_UPDATE_TOOL],
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
                function_calls = {}  # id -> {name, arguments}

                async for event in response:
                    event_type = getattr(event, 'type', None)

                    if event_type == "response.output_text.delta":
                        text_chunks.append(event.delta)

                    elif event_type == "response.function_call_arguments.delta":
                        call_id = getattr(event, 'item_id', None) or 'default'
                        if call_id not in function_calls:
                            function_calls[call_id] = {"name": "", "arguments": ""}
                        function_calls[call_id]["arguments"] += event.delta

                    elif event_type == "response.output_item.added":
                        item = getattr(event, 'item', None)
                        if item and getattr(item, 'type', None) == "function_call":
                            call_id = getattr(item, 'id', None) or getattr(item, 'item_id', 'default')
                            fn_name = getattr(item, 'name', '')
                            function_calls[call_id] = {"name": fn_name, "arguments": ""}
                            yield f"\U0001f6e0\ufe0f Remote agent executing: {self._get_tool_description(fn_name)}"

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

                            # Check if the model wants to call functions
                            output = getattr(resp, 'output', [])
                            pending_calls = []
                            for item in output:
                                if getattr(item, 'type', None) == 'function_call':
                                    pending_calls.append(item)

                            if pending_calls:
                                # Execute function calls and continue conversation
                                tool_results = []
                                for call in pending_calls:
                                    fn_name = getattr(call, 'name', '')
                                    fn_args_str = getattr(call, 'arguments', '{}')
                                    call_id = getattr(call, 'call_id', '') or getattr(call, 'id', '')

                                    try:
                                        fn_args = json.loads(fn_args_str)
                                    except json.JSONDecodeError:
                                        fn_args = {}

                                    if fn_name == "execute_sql_query":
                                        sql_query = fn_args.get("query", "")
                                        logger.info(f"Executing SQL: {sql_query[:200]}")
                                        result = await self._execute_sql(sql_query)
                                    elif fn_name == "update_supplier_data":
                                        sql_query = fn_args.get("query", "")
                                        logger.info(f"Executing UPDATE: {sql_query[:200]}")
                                        result = await self._execute_update(sql_query)
                                    else:
                                        result = json.dumps({"error": f"Unknown function: {fn_name}"})

                                    tool_results.append({
                                        "type": "function_call_output",
                                        "call_id": call_id,
                                        "output": result,
                                    })

                                # Continue conversation with tool results
                                follow_kwargs = {
                                    "model": model,
                                    "instructions": self._get_agent_instructions(),
                                    "input": tool_results,
                                    "tools": [SQL_QUERY_TOOL, SQL_UPDATE_TOOL],
                                    "stream": True,
                                    "max_output_tokens": 4000,
                                    "previous_response_id": resp_id,
                                }

                                # Recursive call to handle multi-turn tool use
                                follow_text = []
                                async for follow_event in await client.responses.create(**follow_kwargs):
                                    ft = getattr(follow_event, 'type', None)
                                    if ft == "response.output_text.delta":
                                        follow_text.append(follow_event.delta)
                                    elif ft == "response.output_item.added":
                                        fi = getattr(follow_event, 'item', None)
                                        if fi and getattr(fi, 'type', None) == "function_call":
                                            fn_name = getattr(fi, 'name', '')
                                            yield f"\U0001f6e0\ufe0f Remote agent executing: {self._get_tool_description(fn_name)}"
                                    elif ft in ("response.completed", "response.done"):
                                        follow_resp = getattr(follow_event, 'response', None)
                                        if follow_resp:
                                            follow_output = getattr(follow_resp, 'output', [])
                                            follow_pending = [i for i in follow_output if getattr(i, 'type', None) == 'function_call']

                                            if follow_pending:
                                                # Handle second round of tool calls
                                                follow_tool_results = []
                                                for call in follow_pending:
                                                    fn_name = getattr(call, 'name', '')
                                                    fn_args_str = getattr(call, 'arguments', '{}')
                                                    call_id = getattr(call, 'call_id', '') or getattr(call, 'id', '')
                                                    try:
                                                        fn_args = json.loads(fn_args_str)
                                                    except json.JSONDecodeError:
                                                        fn_args = {}
                                                    if fn_name == "execute_sql_query":
                                                        result = await self._execute_sql(fn_args.get("query", ""))
                                                    else:
                                                        result = json.dumps({"error": f"Unknown function: {fn_name}"})
                                                    follow_tool_results.append({
                                                        "type": "function_call_output",
                                                        "call_id": call_id,
                                                        "output": result,
                                                    })

                                                follow_resp_id = getattr(follow_resp, 'id', None)
                                                third_kwargs = {
                                                    "model": model,
                                                    "instructions": self._get_agent_instructions(),
                                                    "input": follow_tool_results,
                                                    "tools": [SQL_QUERY_TOOL, SQL_UPDATE_TOOL],
                                                    "stream": True,
                                                    "max_output_tokens": 4000,
                                                    "previous_response_id": follow_resp_id,
                                                }
                                                async for third_event in await client.responses.create(**third_kwargs):
                                                    tt = getattr(third_event, 'type', None)
                                                    if tt == "response.output_text.delta":
                                                        follow_text.append(third_event.delta)
                                                    elif tt in ("response.completed", "response.done"):
                                                        tr = getattr(third_event, 'response', None)
                                                        if tr:
                                                            tu = getattr(tr, 'usage', None)
                                                            if tu:
                                                                self.last_token_usage = {
                                                                    "prompt_tokens": getattr(tu, 'prompt_tokens', 0) or getattr(tu, 'input_tokens', 0),
                                                                    "completion_tokens": getattr(tu, 'completion_tokens', 0) or getattr(tu, 'output_tokens', 0),
                                                                    "total_tokens": getattr(tu, 'total_tokens', 0),
                                                                }
                                                            tid = getattr(tr, 'id', None)
                                                            if tid:
                                                                self._response_ids[session_id] = tid

                                            fu = getattr(follow_resp, 'usage', None)
                                            if fu:
                                                self.last_token_usage = {
                                                    "prompt_tokens": getattr(fu, 'prompt_tokens', 0) or getattr(fu, 'input_tokens', 0),
                                                    "completion_tokens": getattr(fu, 'completion_tokens', 0) or getattr(fu, 'output_tokens', 0),
                                                    "total_tokens": getattr(fu, 'total_tokens', 0),
                                                }
                                            fid = getattr(follow_resp, 'id', None)
                                            if fid:
                                                self._response_ids[session_id] = fid

                                if follow_text:
                                    yield "".join(follow_text)
                                else:
                                    yield "I queried the database but couldn't generate a response. Please try rephrasing your question."
                                return

                if text_chunks:
                    yield "".join(text_chunks)
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
            "execute_sql_query": "Database Query",
            "update_supplier_data": "Database Update",
        }
        return descriptions.get(tool_name, tool_name.replace("_", " ").title())

    async def run_conversation(self, session_id: str, user_message: str) -> str:
        return "\n".join([r async for r in self.run_conversation_stream(session_id, user_message)])

    async def chat(self, session_id: str, user_message: str) -> str:
        return await self.run_conversation(session_id, user_message)
