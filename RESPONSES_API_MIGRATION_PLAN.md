# Responses API Migration Plan

## Overview
Migrate from Azure AI Foundry **Assistants API** to **Responses API** to enable native streaming support while maintaining all A2A functionality.

**Reference Implementation**: `remote_agents/azurefoundry_classification_responseAPI/foundry_agent.py`

---

## Executive Summary

### What Changes
- ✅ **Azure Communication Layer**: Thread/Run polling → Single Response call with streaming
- ✅ **Streaming**: Add native token-by-token streaming support
- ✅ **API Endpoint**: Use `/openai/v1/responses` instead of `/threads/{id}/runs`

### What Stays the Same
- ✅ **A2A Protocol**: 100% unchanged (RemoteAgentConnections, send_message, list_remote_agents)
- ✅ **Tool Definitions**: Same function calling structure
- ✅ **Business Logic**: Agent orchestration, memory, file handling
- ✅ **Frontend**: WebSocket events (just add new streaming event)

---

## Current Architecture Analysis

### Files Affected
1. **`backend/hosts/multiagent/foundry_agent_a2a.py`** (PRIMARY - ~300 line changes)
2. **`frontend/lib/a2a-event-types.ts`** (add streaming event type)
3. **`frontend/components/chat-panel.tsx`** (add streaming handler)

### Two Operational Modes

#### 1. **Agent Mode** (`agent_mode=True`)
- Sequential task delegation to specialized agents
- AI-driven orchestration loop (`_agent_mode_orchestration_loop`)
- Uses `root_instruction()` with agent-mode prompt
- Tool calls: `list_remote_agents` + `send_message` (sequential)

#### 2. **Standard Mode** (`agent_mode=False`)
- Direct user conversation with agent coordination
- Parallel tool execution when possible
- Uses `root_instruction()` with standard prompt
- Tool calls: `list_remote_agents` + `send_message` (parallel)

**Both modes** use the same underlying Azure API calls - just different prompts and execution strategies.

---

## Current Implementation (Assistants API)

### Request Flow
```
1. create_thread(context_id) 
   └─> POST /threads → thread_id

2. send_message_to_thread(thread_id, content)
   └─> POST /threads/{thread_id}/messages

3. _http_create_run(thread_id, agent_id)
   └─> POST /threads/{thread_id}/runs
   └─> Body: { assistant_id, tools, instructions, parallel_tool_calls }

4. POLLING LOOP:
   └─> _http_get_run(thread_id, run_id)
   └─> GET /threads/{thread_id}/runs/{run_id}
   └─> Check status: queued → in_progress → requires_action → completed
   
5. IF requires_action:
   └─> handle_required_action() → execute tools
   └─> _http_submit_tool_outputs(thread_id, run_id, tool_outputs)
   └─> POST /threads/{thread_id}/runs/{run_id}/submit_tool_outputs
   └─> BACK TO STEP 4 (polling)

6. IF completed:
   └─> _http_list_messages(thread_id, limit=20)
   └─> GET /threads/{thread_id}/messages
   └─> Extract assistant message
```

### Key Methods
- `create_thread()` - Create Azure thread
- `send_message_to_thread()` - Add user message
- `_http_create_run()` - Start assistant run
- `_http_get_run()` - Poll run status
- `_http_submit_tool_outputs()` - Submit tool results
- `_http_list_messages()` - Fetch messages after completion
- `handle_required_action()` - Execute tool calls

---

## Target Implementation (Responses API)

### Reference: `foundry_agent.py` Key Patterns

```python
# 1. CLIENT SETUP
from openai import AzureOpenAI
from azure.identity import get_bearer_token_provider

# Convert AI Foundry endpoint to OpenAI format
# From: https://RESOURCE.services.ai.azure.com/subscriptions/.../
# To:   https://RESOURCE.openai.azure.com/openai/v1/
if "services.ai.azure.com" in self.endpoint:
    parts = self.endpoint.split("//")[1].split(".")[0]
    openai_endpoint = f"https://{parts}.openai.azure.com/openai/v1/"

token_provider = get_bearer_token_provider(
    DefaultAzureCredential(),
    "https://cognitiveservices.azure.com/.default"
)

client = AzureOpenAI(
    base_url=openai_endpoint,
    azure_ad_token_provider=token_provider,
    api_version="preview"  # REQUIRED for Responses API
)

# 2. CREATE RESPONSE WITH STREAMING
response = client.responses.create(
    model=os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-4o"),
    input=[{
        "role": "user",
        "content": [
            {"type": "input_text", "text": user_message}
        ]
    }],
    instructions=agent_instructions,
    tools=[...],  # Same tool format as Assistants API
    stream=True,
    max_output_tokens=4000
)

# 3. HANDLE STREAMING EVENTS
for event in response:
    if event.type == 'response.output_text.delta':
        # TEXT CHUNK - stream to user
        chunk = event.delta
        yield chunk
    
    elif event.type == 'response.function_call':
        # TOOL CALL - execute tool
        function_name = event.name
        arguments = json.loads(event.arguments)
        # Execute and continue...
    
    elif event.type == 'response.done':
        # COMPLETION
        break

# 4. CHAINING CONVERSATIONS (replaces thread persistence)
# Use previous_response_id to maintain context
second_response = client.responses.create(
    model="gpt-4o",
    previous_response_id=first_response.id,  # Links to previous response
    input=[{"role": "user", "content": "follow-up question"}]
)
```

---

## Migration Steps

### Phase 1: Client Setup

#### 1.1 Update `__init__()` Method
```python
# BEFORE (Assistants API)
self.client = AsyncAzureOpenAI(
    azure_endpoint=endpoint,
    azure_ad_token_provider=get_bearer_token_provider(...)
)

# AFTER (Responses API)
def _get_openai_endpoint(self) -> str:
    """Convert AI Foundry endpoint to OpenAI /v1/ endpoint."""
    endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
    
    if "services.ai.azure.com" in endpoint:
        # Extract resource name
        parts = endpoint.split("//")[1].split(".")[0]
        return f"https://{parts}.openai.azure.com/openai/v1/"
    else:
        # Already in OpenAI format
        return f"{endpoint.rstrip('/')}/openai/v1/"

self.client = AzureOpenAI(  # Note: NOT AsyncAzureOpenAI
    base_url=self._get_openai_endpoint(),
    azure_ad_token_provider=get_bearer_token_provider(
        self.credential,
        "https://cognitiveservices.azure.com/.default"
    ),
    api_version="preview"  # CRITICAL: Required for Responses API
)
```

#### 1.2 Update Thread Management
```python
# BEFORE: Store thread_id from Azure
self.threads: Dict[str, str] = {}  # context_id -> thread_id

# AFTER: Store response_id for chaining
self.response_history: Dict[str, List[str]] = {}  # context_id -> [response_ids]
```

### Phase 2: Replace Core Methods

#### 2.1 Remove Assistants API Methods
**DELETE these methods:**
- `create_thread()` - No longer needed
- `send_message_to_thread()` - Replaced by responses.create()
- `_http_create_run()` - Replaced by responses.create()
- `_http_get_run()` - No polling needed
- `_http_submit_tool_outputs()` - Tools handled in stream
- `_http_list_messages()` - Response includes output directly

#### 2.2 Create New Response Method
```python
async def _create_response_with_streaming(
    self,
    user_message: str,
    context_id: str,
    session_context: SessionContext,
    tools: List[Dict[str, Any]],
    instructions: str,
    event_logger=None
) -> Dict[str, Any]:
    """
    Create a response using Responses API with streaming support.
    
    Handles:
    - Text streaming (response.output_text.delta events)
    - Tool calls (response.function_call events)
    - Response chaining (previous_response_id)
    """
    
    # Build input content
    input_content = [{"type": "input_text", "text": user_message}]
    
    # Get previous response ID for chaining (if exists)
    previous_response_id = None
    if context_id in self.response_history and self.response_history[context_id]:
        previous_response_id = self.response_history[context_id][-1]
    
    # Determine parallel tool calls based on agent_mode
    agent_mode = session_context.agent_mode if session_context else False
    parallel_tool_calls = not agent_mode
    
    # Create streaming response
    response_stream = self.client.responses.create(
        model=os.environ.get("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o"),
        input=[{
            "role": "user",
            "content": input_content
        }],
        instructions=instructions,
        tools=tools,
        stream=True,
        previous_response_id=previous_response_id,  # Chain conversation
        parallel_tool_calls=parallel_tool_calls,
        max_output_tokens=4000
    )
    
    # Process streaming events
    full_text = ""
    tool_calls = []
    response_id = None
    
    for event in response_stream:
        if event.type == 'response.created':
            response_id = event.id
            
        elif event.type == 'response.output_text.delta':
            # TEXT CHUNK - stream to WebSocket
            chunk = event.delta
            full_text += chunk
            
            # Emit streaming chunk to frontend
            await self._emit_text_chunk(chunk, context_id)
            
        elif event.type == 'response.function_call':
            # TOOL CALL REQUEST
            tool_calls.append({
                "id": event.call_id,
                "type": "function",
                "function": {
                    "name": event.name,
                    "arguments": event.arguments
                }
            })
            
        elif event.type == 'response.done':
            # Response completed
            break
    
    # Store response ID for future chaining
    if response_id:
        if context_id not in self.response_history:
            self.response_history[context_id] = []
        self.response_history[context_id].append(response_id)
    
    return {
        "id": response_id,
        "text": full_text,
        "tool_calls": tool_calls,
        "status": "completed" if not tool_calls else "requires_action"
    }
```

#### 2.3 Add Streaming Event Emitter
```python
async def _emit_text_chunk(self, chunk: str, context_id: str):
    """Emit text chunk to WebSocket for real-time streaming."""
    if self.websocket_streamer:
        try:
            await self.websocket_streamer.stream_event({
                "type": "message_chunk",
                "contextId": context_id,
                "chunk": chunk,
                "timestamp": datetime.now().isoformat()
            })
        except Exception as e:
            log_error(f"Failed to emit text chunk: {e}")
```

### Phase 3: Update Orchestration Loops

#### 3.1 Agent Mode Loop
**Location**: `_agent_mode_orchestration_loop()` method (~line 1271)

**BEFORE** (Assistants API pattern):
```python
# Create thread if needed
if context_id not in self.threads:
    thread = await self.create_thread(context_id)
    self.threads[context_id] = thread["id"]

# Send message
await self.send_message_to_thread(
    self.threads[context_id],
    planning_prompt,
    role="user"
)

# Create run
run = await self._http_create_run(
    thread_id=self.threads[context_id],
    agent_id=self.agent_id,
    session_context=session_context
)

# Poll until complete or requires_action
while run["status"] in ["queued", "in_progress", "requires_action"]:
    if run["status"] == "requires_action":
        output = await self.handle_required_action(
            run,
            self.threads[context_id],
            session_context,
            event_logger
        )
    run = await self._http_get_run(self.threads[context_id], run["id"])
```

**AFTER** (Responses API pattern):
```python
# Create streaming response
response = await self._create_response_with_streaming(
    user_message=planning_prompt,
    context_id=context_id,
    session_context=session_context,
    tools=self._get_tools(),
    instructions=self.root_instruction('foundry-host-agent', agent_mode=True),
    event_logger=event_logger
)

# Handle tool calls if present
if response["tool_calls"]:
    tool_outputs = await self._handle_tool_calls(
        response["tool_calls"],
        session_context,
        context_id,
        event_logger
    )
    
    # Create follow-up response with tool outputs
    # (Responses API handles this internally via previous_response_id)
```

#### 3.2 Standard Mode (Main Process Flow)
**Location**: `send_message()` method and main processing (~line 4900-5200)

**Same pattern as Agent Mode** - replace thread/run/poll with single response creation.

### Phase 4: Tool Calling

#### 4.1 Tool Call Handling
**KEEP** the existing tool execution logic in `handle_required_action()`, but rename and adapt:

```python
async def _handle_tool_calls(
    self,
    tool_calls: List[Dict[str, Any]],
    session_context: SessionContext,
    context_id: str,
    event_logger=None
) -> List[Dict[str, Any]]:
    """
    Execute tool calls and return outputs.
    
    This is the SAME logic as handle_required_action(), just renamed.
    Tool definitions and execution logic are identical.
    """
    
    tool_outputs = []
    
    # Separate send_message vs other tools (for parallel execution)
    send_message_calls = []
    other_calls = []
    
    for tool_call in tool_calls:
        function_name = tool_call["function"]["name"]
        if function_name == "send_message":
            send_message_calls.append(tool_call)
        else:
            other_calls.append(tool_call)
    
    # Execute send_message calls in parallel (if not agent_mode)
    if send_message_calls and not session_context.agent_mode:
        # KEEP existing parallel execution logic
        ...
    
    # Execute other tools sequentially
    for tool_call in other_calls:
        function_name = tool_call["function"]["name"]
        arguments = json.loads(tool_call["function"]["arguments"])
        
        if function_name == "list_remote_agents":
            output = self.list_remote_agents()
        else:
            output = {"error": f"Unknown function: {function_name}"}
        
        tool_outputs.append({
            "tool_call_id": tool_call["id"],
            "output": json.dumps(output)
        })
    
    return tool_outputs
```

### Phase 5: Frontend Updates

#### 5.1 Add Streaming Event Type
**File**: `frontend/lib/a2a-event-types.ts`

```typescript
export interface MessageChunkEventData {
  type: 'message_chunk';
  contextId: string;
  chunk: string;
  timestamp: string;
}

// Add to union type
export type A2AEventData = 
  | MessageEventData
  | MessageChunkEventData  // NEW
  | StatusEventData
  // ... existing types
```

#### 5.2 Handle Streaming in Chat Panel
**File**: `frontend/components/chat-panel.tsx`

```typescript
const [streamingMessage, setStreamingMessage] = useState<string>('');

// Add to useEffect WebSocket handler
useEffect(() => {
  const handleWebSocketMessage = (event: MessageEvent) => {
    const data = JSON.parse(event.data);
    
    switch (data.type) {
      case 'message_chunk':
        // Append chunk to current streaming message
        setStreamingMessage(prev => prev + data.chunk);
        break;
        
      case 'message':
        // Final message - clear streaming buffer
        setStreamingMessage('');
        // Handle complete message...
        break;
    }
  };
  
  // ...
}, []);

// Render streaming message in UI
{streamingMessage && (
  <div className="streaming-message">
    {streamingMessage}
    <span className="cursor-blink">▋</span>
  </div>
)}
```

---

## Detailed Change List

### Backend Changes

#### `foundry_agent_a2a.py`

**Lines to DELETE** (~150 lines):
- Lines 724-760: `_http_list_messages()`
- Lines 760-810: `_http_create_run()`
- Lines 812-842: `_http_get_run()`
- Lines 844-877: `_http_submit_tool_outputs()`
- Lines 2540-2580: `create_thread()`
- Lines 2580-2640: `send_message_to_thread()`

**Lines to ADD** (~200 lines):
- New: `_get_openai_endpoint()` method
- New: `_create_response_with_streaming()` method
- New: `_emit_text_chunk()` method
- Update: `__init__()` - change client initialization
- Update: `_handle_tool_calls()` - rename from `handle_required_action()`
- Update: `_agent_mode_orchestration_loop()` - replace thread/run/poll logic
- Update: Main processing flow (~line 4900) - replace thread/run/poll logic

**Net Change**: ~50 lines added (simpler code!)

### Frontend Changes

#### `a2a-event-types.ts`
- Add `MessageChunkEventData` interface (~5 lines)

#### `chat-panel.tsx`
- Add `streamingMessage` state (~1 line)
- Add `message_chunk` handler (~5 lines)
- Add streaming UI rendering (~5 lines)

**Net Change**: ~16 lines

---

## Testing Checklist

### Unit Tests
- [ ] Client initialization with correct endpoint format
- [ ] Response creation without streaming
- [ ] Response creation with streaming
- [ ] Tool call handling (list_remote_agents)
- [ ] Tool call handling (send_message)
- [ ] Response chaining with previous_response_id
- [ ] Error handling for API failures

### Integration Tests

#### Agent Mode
- [ ] Simple goal with one agent
- [ ] Complex goal requiring multiple agents
- [ ] Goal with workflow steps
- [ ] Follow-up questions in same conversation
- [ ] Streaming displays in real-time
- [ ] Tool calls execute correctly
- [ ] Parallel tool execution disabled

#### Standard Mode
- [ ] Direct user question
- [ ] Question requiring file upload
- [ ] Multi-turn conversation
- [ ] Streaming displays in real-time
- [ ] Tool calls execute correctly
- [ ] Parallel tool execution enabled

### A2A Integration Tests
- [ ] Remote agent communication unchanged
- [ ] File passing between agents works
- [ ] Memory service integration works
- [ ] WebSocket events still fire correctly
- [ ] Agent discovery works
- [ ] Task state tracking works

---

## Rollback Plan

### If Issues Arise
1. **Switch back to branch**: `git checkout benjamin-highschool`
2. **Assistants API still works** - no breaking changes deployed
3. **Frontend compatible** - can handle both event types

### Risk Mitigation
- ✅ Separate feature branch
- ✅ Reference implementation tested
- ✅ A2A protocol unchanged
- ✅ Can deploy incrementally (backend first, then frontend)

---

## Performance Improvements

### Expected Benefits
1. **Latency**: No polling overhead - immediate streaming
2. **UX**: Token-by-token display like ChatGPT
3. **Code**: ~100 fewer lines, simpler logic
4. **Reliability**: Fewer HTTP calls (1 vs 5-10 per request)

### Monitoring
- Track `response_id` chains for conversation continuity
- Monitor streaming event counts
- Compare token usage (should be identical)
- Watch for timeout issues on long responses

---

## Environment Variables

### Required
```bash
# Existing (unchanged)
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=https://YOUR-RESOURCE.services.ai.azure.com/...
AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=gpt-4o  # or gpt-5, gpt-5.1, etc.

# No new variables needed!
```

### API Version
- Responses API uses `api_version="preview"` in client initialization
- This is handled in code, not environment variable

---

## Timeline Estimate

### Phase 1: Backend Core (4-6 hours)
- Client setup and endpoint conversion
- New `_create_response_with_streaming()` method
- Delete old thread/run methods
- Update `__init__()` and class attributes

### Phase 2: Orchestration (3-4 hours)
- Update `_agent_mode_orchestration_loop()`
- Update main processing flow
- Rename and adapt `handle_required_action()`

### Phase 3: Frontend (1-2 hours)
- Add streaming event types
- Add streaming handler
- Update UI rendering

### Phase 4: Testing (4-6 hours)
- Unit tests
- Integration tests
- End-to-end validation
- Performance testing

### Phase 5: Documentation (1-2 hours)
- Update README
- Add streaming documentation
- Update deployment guides

**Total**: 13-20 hours

---

## Success Criteria

### Must Have
- ✅ All existing functionality works (A2A, agent mode, standard mode)
- ✅ Streaming displays token-by-token in UI
- ✅ Tool calls execute correctly
- ✅ No regressions in agent communication
- ✅ Response times improved vs polling

### Nice to Have
- ✅ Streaming visible in "thinking" box for tool calls
- ✅ Conversation history persisted via response chaining
- ✅ Error messages streamed in real-time

---

## Next Steps

1. **Review this plan** - confirm approach
2. **Start Phase 1** - backend client setup
3. **Test incrementally** - each phase independently
4. **Deploy to feature branch** - keep main stable
5. **Validate with real agents** - end-to-end testing
6. **Merge to main** - after full validation

---

## Questions to Answer Before Starting

1. **File handling**: How do PDFs work in Responses API? (Answer: Same as reference - use file_id in input)
2. **Memory service**: Does response chaining replace thread persistence? (Answer: Yes - response_id links conversations)
3. **Parallel tools**: Is `parallel_tool_calls` parameter supported? (Answer: Check docs - likely yes)
4. **Error recovery**: How to handle mid-stream errors? (Answer: Try/catch on event loop, fallback to non-streaming)
5. **Token limits**: Does max_output_tokens work same as Assistants? (Answer: Yes, same parameter)

---

## Reference Links

- [Azure OpenAI Responses API Docs](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/responses?view=foundry-classic)
- [Reference Implementation](remote_agents/azurefoundry_classification_responseAPI/foundry_agent.py)
- [OpenAI Python SDK - Responses](https://github.com/openai/openai-python)

---

**Status**: Ready for implementation
**Last Updated**: 2026-01-23
**Reviewed By**: GitHub Copilot
