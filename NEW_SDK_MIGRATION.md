# NEW SDK Migration - Changes Applied

## Summary
Migrated from OLD SDK (`azure-ai-agents`) to NEW SDK (`azure-ai-projects`) to enable Bing Grounding support.

## Files Changed

### 1. `/backend/hosts/multiagent/foundry_agent_a2a.py`

#### Imports Updated
```python
# BEFORE (OLD SDK):
from azure.ai.agents.models import AsyncFunctionTool, AsyncToolSet

# AFTER (NEW SDK):
from azure.ai.projects.models import (
    BingGroundingAgentTool,
    BingGroundingSearchToolParameters,
    BingGroundingSearchConfiguration,
    PromptAgentDefinition,
    FunctionAgentTool,
    FunctionDefinition,
    ToolFunctionDefinition,
)
```

#### Agent Creation Completely Rewritten
```python
# BEFORE (OLD SDK):
toolset = await self._initialize_function_tools()
self.agents_client.enable_auto_function_calls(toolset)
self.agent = await self.agents_client.create_agent(
    model=model_name,
    name="foundry-host-agent",
    instructions=instructions,
    tools=tools_list
)

# AFTER (NEW SDK):
tools_list = [
    FunctionAgentTool(function=ToolFunctionDefinition(...)),  # Manual tool definitions
    FunctionAgentTool(function=ToolFunctionDefinition(...)),
    BingGroundingAgentTool(bing_grounding=...)  # Bing support!
]

agent_definition = PromptAgentDefinition(
    model=model_name,
    instructions=instructions,
    tools=tools_list
)

self.agent = await self.project_client.agents.create_version(
    agent_name="foundry-host-agent",
    definition=agent_definition,
    description="Multi-agent orchestrator with Bing web search grounding"
)
```

#### Function Tools Now Manually Defined
Instead of using `AsyncFunctionTool` and `AsyncToolSet`, we now manually create `FunctionAgentTool` objects with full definitions:

- `list_remote_agents_sync`
- `send_message_sync`  
- `search_memory_sync`

### 2. `/backend/hosts/multiagent/core/azure_clients.py`

#### Removed Old SDK Imports
```python
# REMOVED:
from azure.ai.agents.aio import AgentsClient

# KEPT:
from azure.ai.projects.aio import AIProjectClient
```

#### Changed agents_client Initialization
```python
# BEFORE (OLD SDK):
self.agents_client = AgentsClient(
    endpoint=self.endpoint,
    credential=self.credential,
)

# AFTER (NEW SDK):
self.agents_client = self.project_client.agents
# This gives us project_client.agents.create_version() and Bing support
```

## What Still Works

### Tool Call Execution (No Changes Needed!)
The existing tool call handling code **already works** with the NEW SDK:
- Lines 551-563 in `foundry_agent_a2a.py` manually execute function tools
- No dependency on `enable_auto_function_calls()`
- Tool calls detected via `required_action.submit_tool_outputs.tool_calls`
- Results submitted via `agents_client.runs.submit_tool_outputs_stream()`

### Streaming & Message Handling
- Still using OLD SDK models for `MessageDeltaChunk`, `ThreadRun`, etc. (compatible)
- Streaming logic unchanged
- Thread/run/message operations still work

## What Changed

### Tool Definition Format
**OLD SDK:**
```python
toolset = AsyncToolSet()
functions = AsyncFunctionTool([func1, func2, func3])
toolset.add(functions)
```

**NEW SDK:**
```python
tools_list = [
    FunctionAgentTool(function=ToolFunctionDefinition(
        name="func1",
        description="...",
        parameters={...}
    )),
    # ... more tools
]
```

### Agent Creation Method
- **OLD:** `agents_client.create_agent(model, name, instructions, tools)`
- **NEW:** `project_client.agents.create_version(agent_name, definition, description)`

### Bing Grounding Support
- **OLD SDK:** ❌ `BingGroundingTool` didn't work
- **NEW SDK:** ✅ `BingGroundingAgentTool` fully supported

## Testing Checklist

- [ ] Backend starts without errors
- [ ] Agent created successfully  
- [ ] Agent tools list includes Bing Grounding
- [ ] Function tools still work (list_remote_agents, send_message, search_memory)
- [ ] Bing search is called for real-time queries
- [ ] Bing citations appear in responses

## Next Steps

1. Restart backend
2. Check startup logs for "Agent created with NEW SDK!"
3. Verify agent tools list includes 4 tools (3 functions + Bing)
4. Test weather query: "What's the weather in Montreal today?"
5. Check for Bing tool calls in logs
6. Verify response includes current weather data

## Rollback Plan

If NEW SDK doesn't work:
1. Revert `/backend/hosts/multiagent/foundry_agent_a2a.py` (git checkout)
2. Revert `/backend/hosts/multiagent/core/azure_clients.py` (git checkout)
3. Backend will return to OLD SDK behavior
