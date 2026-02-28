"""
Test script to reproduce and fix the web_search_preview vs send_message routing issue.

This sends the EXACT same tools + instructions to Azure OpenAI Responses API
as the production backend does, so we can iterate on the prompt without deploying.
"""
import asyncio
import json
import os
from dotenv import load_dotenv

load_dotenv()

# ─── Azure setup ──────────────────────────────────────────────────────
ENDPOINT = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
MODEL = os.environ.get("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")

# Extract resource name for OpenAI endpoint
resource_name = ENDPOINT.split("//")[1].split(".")[0]
AZURE_ENDPOINT = f"https://{resource_name}.services.ai.azure.com"


# ─── Simulated agent card (Stock Market Agent) ───────────────────────
STOCK_AGENT_CARD = {
    "name": "AI Foundry Stock Market Agent",
    "description": "Stock market data agent powered by Alpha Vantage. Access stock prices, forex, crypto, commodities, economic indicators, technical analysis, news sentiment, and company fundamentals.",
    "skills": [
        {"id": "stockmarket_price_lookup", "name": "Stock Price Lookup", "description": "Get current and historical stock prices, quotes, and OHLCV data for any publicly traded company."},
        {"id": "stockmarket_historical_data", "name": "Historical Market Data", "description": "Retrieve historical price data for stocks, forex, crypto, and commodities with daily/weekly/monthly/intraday frequency."},
        {"id": "stockmarket_technical_analysis", "name": "Technical Analysis", "description": "Calculate technical indicators including SMA, EMA, RSI, MACD, Bollinger Bands, Stochastic, ADX, and 40+ more."},
        {"id": "stockmarket_intelligence", "name": "Market Intelligence", "description": "Access news sentiment analysis, earnings call transcripts, insider transactions, and top market movers."},
        {"id": "stockmarket_economic_data", "name": "Economic & Commodity Data", "description": "Retrieve economic indicators (GDP, CPI, inflation, unemployment, treasury yields) and commodity prices."},
    ],
}

AGENTS_JSON = json.dumps([STOCK_AGENT_CARD], indent=2)


# ─── Tools array (same as production) ────────────────────────────────
TOOLS = [
    {
        "type": "function",
        "name": "list_remote_agents",
        "description": "List the available remote agents you can use to delegate the task.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "send_message",
        "description": "HIGHEST PRIORITY TOOL — Always use this BEFORE web_search_preview when any available agent's skills match the user's request. Send a message to a remote agent to delegate the task.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "The name of the agent to send the task to."},
                "message": {"type": "string", "description": "The message to send to the agent."},
            },
            "required": ["agent_name", "message"],
        },
    },
    {
        "type": "function",
        "name": "search_memory",
        "description": "Search user-uploaded files and past conversation history.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
            },
            "required": ["query"],
        },
    },
    {"type": "web_search_preview"},
]


# ─── Instructions (current production version) ───────────────────────
def build_instructions(agents_json: str) -> str:
    """Build the current production instructions."""
    return f"""You are an intelligent **Multi-Agent Orchestrator** designed to coordinate specialized agents to produce complete, personalized responses.
Your goal is to understand the user's request, engage the right agents in the right order, and respond in a friendly, professional tone.

---

### 🧩 CORE BEHAVIOR
Before answering any user request, always:
1. **FIRST: Check if any available agent can handle the request** - Review the agents listed at the end of this prompt and their skills. If an agent's capabilities match the user's request, ALWAYS delegate to that agent using send_message.
2. **Check if user is asking about previously uploaded documents** - If so, use the `search_memory` tool to find relevant content.
3. **For real-time information** - ONLY if no agent's skills match the request, use your Bing web search capability as a fallback.
4. **CRITICAL: Detect sequential dependencies** - If the user says "then", "after that", "using the output from", or similar sequential language, you MUST call agents ONE AT A TIME in the specified order, NOT in parallel.
5. **Data Flow Analysis**: If Agent B needs the actual output/results from Agent A (not just conceptual knowledge), call Agent A first, wait for results, then call Agent B.
6. Plan the collaboration strategy leveraging each agent's skills.

**🚨 CRITICAL OVERRIDE: YOU DO NOT HAVE DIRECT ACCESS LIMITATIONS 🚨**

If you see an agent in the AVAILABLE AGENTS list that can handle the user's request:
- ❌ DO NOT say "I cannot access..."
- ❌ DO NOT say "I don't have permission..."
- ❌ DO NOT say "I cannot directly..."
- ❌ DO NOT say "Unfortunately, I can't..."
- ✅ INSTEAD: **IMMEDIATELY call send_message to delegate to that agent**

**YOU ARE AN ORCHESTRATOR** - Your role is to DELEGATE to agents, not to refuse requests. If an agent exists that can handle the request, you MUST delegate to it. Never refuse a task that an available agent can perform.

### 🌐 WEB SEARCH (Bing Grounding)

You have access to real-time web search powered by Bing Grounding. This tool is automatically available and will be used when you need current information from the internet.

**When to use web search:**
- ONLY when no available agent's skills match the user's request
- User asks about topics not covered by any connected agent's capabilities
- General knowledge questions with no matching agent

**When NOT to use web search:**
- Any available agent has skills that match the request topic — ALWAYS delegate to the agent instead
- User explicitly asks to "use" a specific agent by name

---

### 🧠 DECISION PRIORITIES
1. **Delegate to agents** — If any available agent's skills match the user's request topic, ALWAYS delegate via send_message. This is the highest priority.
2. **Coordinate multiple agents** when the request spans multiple agent domains.
3. **Search memory** — ONLY when the user explicitly references a document they uploaded or asks about a past conversation. Never use search_memory as a substitute for calling an agent whose skills match the request.
4. **Answer directly** only if no agent matches AND the information is already in the current conversation.
5. Always provide transparency about which agents were used and why.

---

### 🧩 AVAILABLE AGENTS
{agents_json}

Each agent may have a "skills" field listing their specific capabilities. Use these skills to select the best agent(s) for each task.

---

### 💬 SUMMARY
- Always show which agents you used and summarize their work.
- Be friendly, helpful, and professional."""


def build_instructions_v2(agents_json: str) -> str:
    """V2: Stronger tool-selection rule that explicitly names web_search_preview."""
    return f"""You are an intelligent **Multi-Agent Orchestrator** designed to coordinate specialized agents to produce complete, personalized responses.
Your goal is to understand the user's request, engage the right agents in the right order, and respond in a friendly, professional tone.

---

### ⚠️ MANDATORY TOOL SELECTION RULE ⚠️

You have two ways to get real-time data: the `send_message` function (to delegate to remote agents) and the `web_search_preview` tool (to search the web).

**BEFORE using `web_search_preview`, you MUST check if any AVAILABLE AGENT listed below can handle the request. If an agent's skills match, you MUST call `send_message` instead of `web_search_preview`.**

- If user asks about stocks/prices/market data AND a stock market agent is available → call `send_message`, NOT `web_search_preview`
- If user asks about emails AND an email agent is available → call `send_message`, NOT `web_search_preview`
- `web_search_preview` is ONLY for topics where NO available agent has relevant skills

**Even if you used `web_search_preview` for a similar question earlier in this conversation, you MUST now use `send_message` if an agent with matching skills is available.** Agent availability can change during a conversation.

---

### 🧩 CORE BEHAVIOR
Before answering any user request, always:
1. **FIRST: Check AVAILABLE AGENTS below** — If any agent's skills match, call `send_message` to delegate. This takes absolute priority over `web_search_preview`.
2. **Check if user is asking about uploaded documents** — If so, use `search_memory`.
3. **Only if no agent matches** — Use `web_search_preview` as a last resort for real-time information.
4. **Detect sequential dependencies** — "then", "after that" → call agents ONE AT A TIME.
5. **Data Flow Analysis**: If Agent B needs Agent A's output, call A first, wait, then call B.

---

### 🧩 AVAILABLE AGENTS
{agents_json}

Each agent may have a "skills" field listing their specific capabilities. Use these skills to select the best agent(s) for each task.

---

### 💬 SUMMARY
- Always show which agents you used and summarize their work.
- Be friendly, helpful, and professional."""


async def test_prompt(instructions: str, user_message: str, label: str = ""):
    """Send a request to Azure OpenAI and see which tool the model chooses."""
    from openai import AsyncAzureOpenAI
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )
    client = AsyncAzureOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        azure_ad_token_provider=token_provider,
        api_version="2025-03-01-preview",
    )

    print(f"\n{'='*70}")
    print(f"TEST: {label}")
    print(f"User message: {user_message}")
    print(f"{'='*70}")

    response = await client.responses.create(
        input=user_message,
        instructions=instructions,
        model=MODEL,
        tools=TOOLS,
        # Don't stream — we just want to see which tool was chosen
    )

    # Analyze the response
    print(f"\nResponse ID: {response.id}")
    print(f"Status: {response.status}")

    function_calls = []
    web_search_used = False
    text_output = ""

    for item in response.output:
        item_type = getattr(item, 'type', 'unknown')
        if item_type == "function_call":
            function_calls.append({
                "name": item.name,
                "arguments": item.arguments[:200] if item.arguments else "",
            })
        elif item_type == "web_search_call":
            web_search_used = True
        elif item_type == "message":
            for content in getattr(item, 'content', []):
                text = getattr(content, 'text', '')
                if text:
                    text_output += text

    print(f"\n--- RESULTS ---")
    print(f"Function calls: {json.dumps(function_calls, indent=2) if function_calls else 'NONE'}")
    print(f"Web search used: {web_search_used}")
    print(f"Text output (first 200 chars): {text_output[:200]}...")

    if function_calls:
        print(f"\n✅ Model chose FUNCTION TOOL: {function_calls[0]['name']}")
    elif web_search_used:
        print(f"\n❌ Model chose WEB_SEARCH_PREVIEW (not function tool)")
    else:
        print(f"\n⚠️ Model answered directly without any tool")

    return {
        "function_calls": function_calls,
        "web_search_used": web_search_used,
        "text": text_output[:200],
    }


async def test_multiturn():
    """
    Simulate the PRODUCTION scenario:
    1. User asks stock question WITH NO AGENTS (model uses web search)
    2. User connects stock agent (instructions now include agent)
    3. User asks another stock question (should route to agent, not web search)

    Uses previous_response_id chaining, just like production.
    """
    from openai import AsyncAzureOpenAI
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )
    client = AsyncAzureOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        azure_ad_token_provider=token_provider,
        api_version="2025-03-01-preview",
    )

    # No-agent instructions (empty agent list)
    no_agent_instructions = build_instructions("[]")
    with_agent_instructions = build_instructions(AGENTS_JSON)

    # Tools WITHOUT agents — only web search and memory
    tools_no_agents = [
        {
            "type": "function",
            "name": "search_memory",
            "description": "Search user-uploaded files and past conversation history.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        },
        {"type": "web_search_preview"},
    ]

    print("\n" + "=" * 70)
    print("TEST: MULTI-TURN with previous_response_id chaining")
    print("Simulating: no agents → user asks stock → agent connected → user asks stock again")
    print("=" * 70)

    # TURN 1: Stock question with NO agents connected
    print(f"\n--- TURN 1: Stock question, NO agents ---")
    resp1 = await client.responses.create(
        input="What is the current stock price of AMD?",
        instructions=no_agent_instructions,
        model=MODEL,
        tools=tools_no_agents,
    )
    resp1_id = resp1.id
    web_used = any(getattr(item, 'type', '') == 'web_search_call' for item in resp1.output)
    text1 = ""
    for item in resp1.output:
        if getattr(item, 'type', '') == 'message':
            for c in getattr(item, 'content', []):
                text1 += getattr(c, 'text', '')
    print(f"  Response ID: {resp1_id}")
    print(f"  Web search used: {web_used}")
    print(f"  Answer: {text1[:150]}...")

    await asyncio.sleep(3)

    # TURN 2a: WITH previous_response_id (reproduces the bug)
    print(f"\n--- TURN 2a: WITH previous_response_id (current production) ---")
    resp2a = await client.responses.create(
        input="What is the current stock price of NVIDIA?",
        instructions=with_agent_instructions,
        model=MODEL,
        tools=TOOLS,
        previous_response_id=resp1_id,
    )

    fc2a = [{"name": i.name, "args": i.arguments[:100]} for i in resp2a.output if getattr(i, 'type', '') == "function_call"]
    ws2a = any(getattr(i, 'type', '') == 'web_search_call' for i in resp2a.output)
    if fc2a:
        print(f"  ✅ send_message: {fc2a[0]['name']}")
    elif ws2a:
        print(f"  ❌ web_search_preview used (bug!)")
    else:
        print(f"  ⚠️ Answered directly")

    await asyncio.sleep(3)

    # TURN 2b: WITHOUT previous_response_id but WITH context in input
    print(f"\n--- TURN 2b: NO previous_response_id, context passed in input ---")
    context_input = [
        {"role": "user", "content": "What is the current stock price of AMD?"},
        {"role": "assistant", "content": text1[:300]},
        {"role": "user", "content": "What is the current stock price of NVIDIA?"},
    ]
    resp2b = await client.responses.create(
        input=context_input,
        instructions=with_agent_instructions,
        model=MODEL,
        tools=TOOLS,
        # NO previous_response_id — fresh chain
    )

    fc2b = [{"name": i.name, "args": i.arguments[:100]} for i in resp2b.output if getattr(i, 'type', '') == "function_call"]
    ws2b = any(getattr(i, 'type', '') == 'web_search_call' for i in resp2b.output)
    if fc2b:
        print(f"  ✅ send_message: {fc2b[0]['name']}")
    elif ws2b:
        print(f"  ❌ web_search_preview used")
    else:
        print(f"  ⚠️ Answered directly")

    await asyncio.sleep(3)

    # TURN 2c: Just reset previous_response_id (no context at all — fresh start)
    print(f"\n--- TURN 2c: NO previous_response_id, NO context (clean slate) ---")
    resp2c = await client.responses.create(
        input="What is the current stock price of NVIDIA?",
        instructions=with_agent_instructions,
        model=MODEL,
        tools=TOOLS,
        # NO previous_response_id
    )

    fc2c = [{"name": i.name, "args": i.arguments[:100]} for i in resp2c.output if getattr(i, 'type', '') == "function_call"]
    ws2c = any(getattr(i, 'type', '') == 'web_search_call' for i in resp2c.output)
    if fc2c:
        print(f"  ✅ send_message: {fc2c[0]['name']}")
    elif ws2c:
        print(f"  ❌ web_search_preview used")
    else:
        print(f"  ⚠️ Answered directly")


async def test_multiturn_v2():
    """Test V2 instructions in multi-turn with previous_response_id chaining."""
    from openai import AsyncAzureOpenAI
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )
    client = AsyncAzureOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        azure_ad_token_provider=token_provider,
        api_version="2025-03-01-preview",
    )

    no_agent_instructions = build_instructions("[]")
    v2_instructions = build_instructions_v2(AGENTS_JSON)

    tools_no_agents = [
        {
            "type": "function",
            "name": "search_memory",
            "description": "Search user-uploaded files and past conversation history.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        },
        {"type": "web_search_preview"},
    ]

    print("\n" + "=" * 70)
    print("TEST: V2 INSTRUCTIONS — multi-turn with previous_response_id")
    print("=" * 70)

    # TURN 1: No agents, uses web search
    print(f"\n--- TURN 1: Stock question, NO agents ---")
    resp1 = await client.responses.create(
        input="What is the current stock price of AMD?",
        instructions=no_agent_instructions,
        model=MODEL,
        tools=tools_no_agents,
    )
    resp1_id = resp1.id
    ws1 = any(getattr(i, 'type', '') == 'web_search_call' for i in resp1.output)
    print(f"  Web search used: {ws1}")

    await asyncio.sleep(3)

    # TURN 2: V2 instructions with agent, CHAINED via previous_response_id
    print(f"\n--- TURN 2: V2 instructions, WITH previous_response_id ---")
    resp2 = await client.responses.create(
        input="What is the current stock price of NVIDIA?",
        instructions=v2_instructions,
        model=MODEL,
        tools=TOOLS,
        previous_response_id=resp1_id,
    )

    fc2 = [{"name": i.name, "args": i.arguments[:100]} for i in resp2.output if getattr(i, 'type', '') == "function_call"]
    ws2 = any(getattr(i, 'type', '') == 'web_search_call' for i in resp2.output)
    if fc2:
        print(f"  ✅ send_message: {fc2[0]['name']}")
        return True
    elif ws2:
        print(f"  ❌ web_search_preview used (V2 failed to override chain bias)")
        return False
    else:
        print(f"  ⚠️ Answered directly")
        return False


async def main():
    # Run V2 multi-turn test 5 times for consistency
    print("\n" + "=" * 70)
    print("CONSISTENCY TEST: V2 instructions, 5 runs")
    print("=" * 70)

    results = {"pass": 0, "fail": 0}
    for i in range(5):
        print(f"\n--- Run {i+1}/5 ---")
        try:
            passed = await test_multiturn_v2()
            if passed:
                results["pass"] += 1
            else:
                results["fail"] += 1
        except Exception as e:
            print(f"  Error: {e}")
            results["fail"] += 1
        await asyncio.sleep(5)

    print(f"\n{'='*70}")
    print(f"RESULTS: {results['pass']}/5 passed")
    print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())
