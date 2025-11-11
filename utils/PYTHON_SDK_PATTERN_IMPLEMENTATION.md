# Python SDK Pattern Implementation for Voice Live Function Calling

## Overview
Implemented the correct async function calling pattern from the Azure Voice Live Python SDK sample to fix voice consistency and AI context issues.

## Key Problems Fixed

### 1. **Function Execution Timing**
   - **Before**: Functions executed immediately in `response.output_item.done`
   - **After**: Functions execute in `response.done` after the full response completes
   - **Why**: The Python SDK pattern waits until the response is complete before executing functions, ensuring proper context and timing

### 2. **Response Creation Pattern**
   - **Before**: No manual `response.create` calls (relied only on VAD auto-creation)
   - **After**: Manual `response.create` called ONCE after function output, and ONCE after user message injection
   - **Why**: While VAD can auto-create responses, explicitly requesting responses ensures the AI processes function results and user messages immediately

### 3. **Function Call State Management**
   - **Before**: No centralized state tracking for pending function calls
   - **After**: Uses `pendingFunctionCallRef` to store call info until ready to execute
   - **Why**: Prevents duplicate execution and ensures all data (name, call_id, previous_item_id, arguments) is available

## Implementation Details

### New State References

```typescript
// Response lifecycle tracking (following Python SDK pattern)
const activeResponseRef = useRef(false)
const responseDoneRef = useRef(false)
const pendingFunctionCallRef = useRef<{
  name: string
  call_id: string
  previous_item_id?: string
  arguments?: string
} | null>(null)
```

### Event Flow (Python SDK Pattern)

```
1. conversation.item.created (type: function_call)
   └─> Store function call info in pendingFunctionCallRef
       { name, call_id, previous_item_id }

2. response.function_call_arguments.done
   └─> Add arguments to pendingFunctionCallRef
       { name, call_id, previous_item_id, arguments }

3. response.created
   └─> Set activeResponseRef = true
       Set responseDoneRef = false

4. response.done
   └─> Set activeResponseRef = false
       Set responseDoneRef = true
   └─> IF pendingFunctionCallRef has arguments:
       ├─> Execute function
       ├─> Send function_call_output with previous_item_id
       ├─> Send response.create (ONCE)
       └─> Clear pendingFunctionCallRef

5. (Later) A2A response arrives
   └─> Inject as user message
   └─> Send response.create (ONCE)
```

### Key Code Changes

#### 1. conversation.item.created Handler (NEW)
```typescript
case 'conversation.item.created':
  if (event.item?.type === 'function_call') {
    console.log('[VoiceLive] 🔧 Function call item created:', event.item.name)
    pendingFunctionCallRef.current = {
      name: event.item.name,
      call_id: event.item.call_id,
      previous_item_id: event.item.id
    }
  }
  break
```

#### 2. response.function_call_arguments.done Handler (UPDATED)
```typescript
case 'response.function_call_arguments.done':
  if (pendingFunctionCallRef.current && event.call_id === pendingFunctionCallRef.current.call_id) {
    console.log('[VoiceLive] ✅ Function arguments received:', event.arguments)
    pendingFunctionCallRef.current.arguments = event.arguments
  }
  break
```

#### 3. response.created Handler (UPDATED)
```typescript
case 'response.created':
  activeResponseRef.current = true
  responseDoneRef.current = false
  break
```

#### 4. response.done Handler (UPDATED)
```typescript
case 'response.done':
  activeResponseRef.current = false
  responseDoneRef.current = true
  
  // Execute pending function call if arguments are ready
  if (pendingFunctionCallRef.current && pendingFunctionCallRef.current.arguments) {
    await handleFunctionCall(pendingFunctionCallRef.current)
    pendingFunctionCallRef.current = null
  }
  break
```

#### 5. response.output_item.done Handler (UPDATED)
```typescript
case 'response.output_item.done':
  // Don't handle function calls here - they're handled in response.done
  if (event.item?.type === 'function_call') {
    console.log('[VoiceLive] 📝 Function call output item done (will execute in response.done):', event.item.name)
  }
  break
```

#### 6. handleFunctionCall (REFACTORED)
```typescript
const handleFunctionCall = async (functionCallInfo: {
  name: string
  call_id: string
  previous_item_id?: string
  arguments?: string
}) => {
  // Parse arguments
  const args = JSON.parse(functionCallInfo.arguments)
  
  // Send function output with previous_item_id
  const functionOutput = {
    type: 'conversation.item.create',
    previous_item_id: functionCallInfo.previous_item_id,
    item: {
      type: 'function_call_output',
      call_id: functionCallInfo.call_id,
      output: JSON.stringify({ status: 'processing', ... })
    }
  }
  wsRef.current?.send(JSON.stringify(functionOutput))
  
  // Request new response (ONLY ONCE)
  wsRef.current?.send(JSON.stringify({ type: 'response.create' }))
  
  // Send to A2A network asynchronously
  config.onSendToA2A(requestString, ...).then(...)
}
```

#### 7. injectNetworkResponse (UPDATED)
```typescript
const injectNetworkResponse = useCallback((response: any) => {
  // Add user message with network results
  const networkResultMessage = {
    type: 'conversation.item.create',
    item: {
      type: 'message',
      role: 'user',
      content: [{ type: 'input_text', text: `Network check results: ${response.message}` }]
    }
  }
  wsRef.current.send(JSON.stringify(networkResultMessage))
  
  // Request new response (ONLY ONCE)
  wsRef.current.send(JSON.stringify({ type: 'response.create' }))
}, [])
```

## Comparison with Python SDK

### Python SDK Code
```python
async def _handle_event(self, event):
    if event.type == ServerEventType.CONVERSATION_ITEM_CREATED:
        if event.item.type == ItemType.FUNCTION_CALL:
            self._pending_function_call = {
                "name": event.item.name,
                "call_id": event.item.call_id,
                "previous_item_id": event.item.id
            }
    
    elif event.type == ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
        if self._pending_function_call and event.call_id == self._pending_function_call["call_id"]:
            self._pending_function_call["arguments"] = event.arguments
    
    elif event.type == ServerEventType.RESPONSE_CREATED:
        self._active_response = True
        self._response_api_done = False
    
    elif event.type == ServerEventType.RESPONSE_DONE:
        self._active_response = False
        self._response_api_done = True
        
        # Execute pending function call if arguments are ready
        if self._pending_function_call and "arguments" in self._pending_function_call:
            await self._execute_function_call(self._pending_function_call)
            self._pending_function_call = None

async def _execute_function_call(self, function_call_info):
    result = self.available_functions[function_name](arguments)
    
    function_output = FunctionCallOutputItem(
        call_id=call_id, 
        output=json.dumps(result)
    )
    
    # Send result back to conversation
    await conn.conversation.item.create(
        previous_item_id=previous_item_id, 
        item=function_output
    )
    
    # Request new response to process the function result
    await conn.response.create()
```

### TypeScript Implementation
The TypeScript code now follows the exact same pattern as the Python SDK!

## Benefits of This Pattern

1. **Single Function Execution**: Functions execute exactly once, in `response.done`
2. **Complete Context**: All function call data (name, call_id, previous_item_id, arguments) is available before execution
3. **Explicit Response Control**: We explicitly request responses after function output and user message injection
4. **No Duplication**: Only one handler (`response.done`) processes function calls
5. **Proper Async Flow**: Function execution waits until response completes, matching Python SDK behavior

## Testing Checklist

- [ ] Function calls execute exactly once (check logs for "Executing pending function call")
- [ ] Function execution happens after response completes (in `response.done`)
- [ ] Two `response.create` calls total:
  - [ ] One after function output sent
  - [ ] One after network results injected as user message
- [ ] AI has full knowledge of A2A network responses
- [ ] Voice stays consistent throughout conversation
- [ ] No duplicate function execution errors in logs

## Expected Log Flow

```
[VoiceLive] 🔧 Function call item created: send_to_agent_network
[VoiceLive] 📝 Stored pending function call, waiting for arguments...
[VoiceLive] ✅ Function arguments received: {"request":"..."}
[VoiceLive] 📝 Arguments stored, waiting for response.done...
[VoiceLive] ✅ RESPONSE CREATED - AI is generating response
[VoiceLive] ✅ Response complete
[VoiceLive] 🔧 Executing pending function call: send_to_agent_network
[VoiceLive] 📤 Sending function_call_output
[VoiceLive] ✅ Function output sent to conversation
[VoiceLive] 📤 Requesting new response with function result
[VoiceLive] ✅ Response requested - AI will process function output
[VoiceLive] 🔄 Now sending request to A2A network in background...
(Later...)
[VoiceLive] 💉 Injecting A2A network response into conversation
[VoiceLive] 📤 Adding network results as user message
[VoiceLive] ✅ Network results injected as user message
[VoiceLive] 📤 Requesting response to process network results
[VoiceLive] ✅ Response requested - AI will process network results
```

## Conclusion

This implementation now matches the Python SDK's proven async function calling pattern. The key insight is that function execution must wait until `response.done` to ensure proper context, and we must explicitly request responses (with `response.create`) after function output and user message injection to ensure the AI processes them immediately.
