# Bing Grounding Integration - SDK Compatibility Issue

## Problem Summary

Bing Grounding with Azure AI Foundry Agents requires using **TWO INCOMPATIBLE SDKs**:

### Current Setup (NOT WORKING)
```python
# Using OLD SDK: azure-ai-agents (1.1.0)
from azure.ai.agents.aio import AgentsClient

agents_client = AgentsClient(endpoint=..., credential=...)
agents_client.enable_auto_function_calls(toolset)  # ✅ Available
agent = await agents_client.create_agent(
    model=model_name,
    tools=[...],  # ❌ Bing Grounding NOT supported
)
```

### Microsoft's Example (NEW SDK)
```python
# Using NEW SDK: azure-ai-projects (2.0.0b3)
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    BingGroundingAgentTool,  # ✅ Available in NEW SDK
    PromptAgentDefinition
)

project_client = AIProjectClient(endpoint=..., credential=...)
agent = project_client.agents.create_version(  # Different method!
    agent_name="MyAgent",
    definition=PromptAgentDefinition(
        model=model_name,
        tools=[BingGroundingAgentTool(...)]  # ✅ Bing supported
    )
)
# ❌ NO enable_auto_function_calls() available
```

## The Conflict

| Feature | OLD SDK (`azure-ai-agents`) | NEW SDK (`azure.ai.projects`) |
|---------|----------------------------|------------------------------|
| **Bing Grounding** | ❌ `BingGroundingTool` doesn't work | ✅ `BingGroundingAgentTool` works |
| **Auto Function Calls** | ✅ `enable_auto_function_calls()` | ❌ Not available |
| **Agent Creation** | `create_agent()` | `create_version()` with `PromptAgentDefinition` |
| **Tools Parameter** | Simple list | Different structure |

## Current Architecture

Your code mixes both SDKs:
```python
from azure.ai.projects.aio import AIProjectClient  # NEW SDK
from azure.ai.agents.aio import AgentsClient        # OLD SDK

# Initialize both
self.project_client = AIProjectClient(...)  # For project-level operations
self.agents_client = AgentsClient(...)       # For agent operations

# Use OLD SDK for everything
self.agents_client.enable_auto_function_calls(toolset)
agent = await self.agents_client.create_agent(...)
```

## Solutions

### Option 1: Switch Fully to NEW SDK (RECOMMENDED)
- **Pros:** Bing Grounding will work
- **Cons:** Need to handle function tool calls manually (no `enable_auto_function_calls`)

**Required Changes:**
1. Use `project_client.agents.create_version()` instead of `agents_client.create_agent()`
2. Use `PromptAgentDefinition` to define the agent
3. Manually handle function tool execution in run loops
4. Remove `enable_auto_function_calls()` dependency

### Option 2: Wait for SDK Convergence
- Wait for Microsoft to add Bing support to `azure-ai-agents` OR
- Wait for `enable_auto_function_calls()` to be added to `azure.ai.projects`

### Option 3: Use Azure Portal to Configure Bing
- Configure Bing Grounding in Azure AI Foundry Portal UI
- Reference the agent by ID in code
- Might work with OLD SDK if agent is pre-configured

## Recommended Next Steps

1. **Test Option 3 first** (quickest):
   - Go to Azure AI Foundry Portal
   - Create/edit your agent in the UI
   - Add Bing Grounding tool via portal
   - Reference agent by ID in code

2. **If that fails, implement Option 1** (more work but definitive):
   - Refactor to use NEW SDK completely
   - Implement manual function tool handling
   - Test Bing Grounding

## References

- **NEW SDK Docs:** https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/tools/bing-tools
- **NEW SDK Package:** `azure-ai-projects` (2.0.0b3)
- **OLD SDK Package:** `azure-ai-agents` (1.1.0)
- **Key Finding:** "You need the latest prerelease package" - the NEW SDK is still in beta

## Current Status

- ✅ Bing connection created and configured
- ✅ Connection ID format correct  
- ✅ Permissions configured (Azure AI Developer role)
- ❌ Bing tool not appearing in agent's tools list
- ❌ Agent not calling Bing for real-time queries
- **Root Cause:** Using OLD SDK which doesn't support `BingGroundingAgentTool`
