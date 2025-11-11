# Async Function Calling Fix - Voice Live API

## The Core Issue

The previous implementation had a fundamental misunderstanding: we were trying to execute the function and send output immediately in `response.done`, but for **async A2A operations** that take 5-10 seconds, we can't send the function output until we have the actual result.

## The Correct Flow for Async Operations

### Flow Diagram

```
1. User speaks: "Check the network status"
   └─> VAD commits audio

2. conversation.item.created (type: function_call)
   └─> Store in pendingFunctionCallRef
       { name: "send_to_agent_network", call_id, previous_item_id }

3. response.function_call_arguments.done
   └─> Add arguments to pendingFunctionCallRef
       { name, call_id, previous_item_id, arguments: "{request: '...'}" }

4. response.created
   └─> activeResponseRef = true

5. response.done
   └─> Execute handleFunctionCall()
       ├─> Store A2A call info separately in pendingA2ACallRef
       │   { call_id, previous_item_id }
       ├─> Send A2A request (async, don't await)
       └─> Clear pendingFunctionCallRef (we're done with this response)

6. (5-10 seconds pass... user may be speaking or waiting)

7. A2A response arrives → injectNetworkResponse() called
   ├─> Create function_call_output with A2A result
   │   {
   │     type: 'conversation.item.create',
   │     previous_item_id: <from pendingA2ACallRef>,
   │     item: {
   │       type: 'function_call_output',
   │       call_id: <from pendingA2ACallRef>,
   │       output: JSON.stringify({ status: 'completed', message: '...' })
   │     }
   │   }
   ├─> Send function_call_output
   ├─> Send response.create (ONLY ONCE)
   └─> Clear pendingA2ACallRef

8. AI processes function output and responds with network results
```

## Key Code Structures

### State References

```typescript
// Tracks the current response lifecycle
const activeResponseRef = useRef(false)
const responseDoneRef = useRef(false)

// Stores function call info DURING response processing
const pendingFunctionCallRef = useRef<{
  name: string
  call_id: string
  previous_item_id?: string
  arguments?: string
} | null>(null)

// Stores async A2A call info AFTER response.done (for later injection)
const pendingA2ACallRef = useRef<{
  call_id: string
  previous_item_id?: string
} | null>(null)

// Legacy ref for tracking call_id
const pendingCallIdRef = useRef<string | null>(null)
```

### Why Two Separate Refs?

**pendingFunctionCallRef**:
- Active during response processing
- Cleared in `response.done` after function starts executing
- Used for the immediate function call handling

**pendingA2ACallRef**:
- Set when async A2A operation starts
- Persists until A2A response arrives (could be seconds later)
- Used to inject function_call_output when A2A completes

This separation is critical because the function execution (`response.done`) happens immediately, but the A2A result arrives much later.

## Updated handleFunctionCall

```typescript
const handleFunctionCall = async (functionCallInfo: {
  name: string
  call_id: string
  previous_item_id?: string
  arguments?: string
}) => {
  const args = JSON.parse(functionCallInfo.arguments)
  
  if (functionName === 'send_to_agent_network') {
    // Store A2A call info for LATER injection (when response arrives)
    pendingA2ACallRef.current = {
      call_id: functionCallInfo.call_id,
      previous_item_id: functionCallInfo.previous_item_id
    }
    pendingCallIdRef.current = functionCallInfo.call_id
    
    // Send to A2A network (async - DON'T await, let it run in background)
    config.onSendToA2A(requestString, {...})
      .then(conversationId => {
        console.log('Waiting for A2A response to inject as function_call_output...')
      })
      .catch(err => {
        // Send error as function output
        wsRef.current.send(JSON.stringify({
          type: 'conversation.item.create',
          previous_item_id: pendingA2ACallRef.current.previous_item_id,
          item: {
            type: 'function_call_output',
            call_id: pendingA2ACallRef.current.call_id,
            output: JSON.stringify({ status: 'error', ... })
          }
        }))
        wsRef.current.send(JSON.stringify({ type: 'response.create' }))
        
        pendingA2ACallRef.current = null
      })
  }
}
```

**Key Points:**
1. ✅ Store A2A info in `pendingA2ACallRef` (separate from pendingFunctionCallRef)
2. ✅ Send A2A request without awaiting (let it run in background)
3. ✅ DON'T send function_call_output here (wait for A2A response)
4. ✅ Handle errors by sending function_call_output with error status

## Updated injectNetworkResponse

```typescript
const injectNetworkResponse = useCallback((response: any) => {
  if (!pendingA2ACallRef.current) {
    console.warn('No pending A2A call to inject response for')
    return
  }

  // Send the A2A response as function_call_output
  const functionOutput = {
    type: 'conversation.item.create',
    previous_item_id: pendingA2ACallRef.current.previous_item_id,
    item: {
      type: 'function_call_output',
      call_id: pendingA2ACallRef.current.call_id,
      output: JSON.stringify({
        status: 'completed',
        message: response.message || response.response,
        timestamp: Date.now()
      })
    }
  }
  
  wsRef.current.send(JSON.stringify(functionOutput))
  
  // Request new response to process the function result (ONLY ONCE)
  wsRef.current.send(JSON.stringify({ type: 'response.create' }))
  
  // Clear the references
  pendingA2ACallRef.current = null
  pendingCallIdRef.current = null
}, [])
```

**Key Points:**
1. ✅ Use `pendingA2ACallRef` (not pendingFunctionCallRef which is already cleared)
2. ✅ Send function_call_output with `previous_item_id` to link it to the function call
3. ✅ Send `response.create` ONCE to process the result
4. ✅ Clear the A2A refs after injection

## Why This Works

### Problem: Timing Mismatch
- Function call happens in response.done (immediate)
- A2A response arrives 5-10 seconds later
- Can't send function_call_output without the actual data

### Solution: Deferred Output
1. **Immediate**: Store call info, start async A2A request, return from handler
2. **Later**: When A2A completes, inject function_call_output with real data
3. **Result**: AI gets the actual network results, not a placeholder

### Voice Live API Requirements
According to the API documentation:
- `function_call_output` items must reference the `call_id` from the function call
- Use `previous_item_id` to link the output to the original function call item
- After adding function output, call `response.create` to process it
- The API will use the function output in its next response

## Expected Behavior

### Logs When Working Correctly

```
[VoiceLive] 🔧 Function call item created: send_to_agent_network
[VoiceLive] ✅ Function arguments received: {"request":"Check network status"}
[VoiceLive] ✅ RESPONSE CREATED - AI is generating response
[VoiceLive] ✅ Response complete
[VoiceLive] 🔧 Executing pending function call: send_to_agent_network
[VoiceLive] 📝 Storing A2A call info for async response
[VoiceLive] 🔄 Sending request to A2A network in background...
[VoiceLive] ✅ Request sent to A2A network, conversation ID: voice-123456
[VoiceLive] ⏳ Waiting for A2A response to inject as function_call_output...

(5-10 seconds pass...)

[Dashboard] ✅ A2A response ready for Voice Live!
[Dashboard] 📦 Storing response for injection
[VoiceLive] 💉 Injecting A2A network response as function_call_output
[VoiceLive] 📤 Sending function_call_output with A2A response
[VoiceLive] ✅ Function output sent to conversation
[VoiceLive] 📤 Requesting response to process function result
[VoiceLive] ✅ Response requested - AI will process A2A network results
[VoiceLive] ✅ RESPONSE CREATED - AI is generating response
(AI speaks about the network results)
```

### What the AI Should Say

**Before fix:**
- AI: "Let me check the network..." (then silence, or talks about something else)

**After fix:**
- AI: "Let me check the network status for you..."
- (5 seconds pass)
- AI: "Based on the network check results, I can see that your connection is stable with a latency of 25ms..."

## Testing Checklist

- [ ] Function call stored correctly in conversation.item.created
- [ ] Arguments stored correctly in response.function_call_arguments.done
- [ ] Function executes in response.done
- [ ] A2A request sent in background (not blocking)
- [ ] pendingA2ACallRef stores call_id and previous_item_id
- [ ] When A2A response arrives, function_call_output sent
- [ ] response.create called after function_call_output
- [ ] AI processes and speaks about the network results
- [ ] Voice stays consistent throughout
