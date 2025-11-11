# Voice Live API - Critical Fixes Needed

## Problems:
1. **Voice changes** - Multiple `response.create` calls creating responses with different voices
2. **AI has no knowledge of A2A responses** - Injection timing/pattern is wrong
3. **Call ID misalignment** - Using old call_ids in new response contexts

## Root Cause:
You have `create_response: true` in VAD settings, but you're ALSO manually calling `response.create`. This creates MULTIPLE responses, each potentially with different voice settings.

## The Fix:

### 1. In `handleFunctionCall` (lines ~307-338):
**REMOVE the manual `response.create` call**

```typescript
// BEFORE (WRONG):
wsRef.current?.send(JSON.stringify(functionOutput))
wsRef.current?.send(JSON.stringify({ type: 'response.create' })) // ❌ REMOVE THIS

// AFTER (CORRECT):
wsRef.current?.send(JSON.stringify(functionOutput))
// ✅ Let VAD's create_response: true handle it automatically
```

### 2. In `injectNetworkResponse` (lines ~360-385):
**Change from function_call_output to user message + remove response.create**

```typescript
// BEFORE (WRONG):
const networkResultMessage = {
  type: 'conversation.item.create',
  item: {
    type: 'message',
    role: 'user',
    content: [{
      type: 'input_text',
      text: `Network check results: ${response.message}`
    }]
  }
}
wsRef.current.send(JSON.stringify(networkResultMessage))
wsRef.current.send(JSON.stringify({ type: 'response.create' })) // ❌ REMOVE THIS

// AFTER (CORRECT):
const networkResultMessage = {
  type: 'conversation.item.create',
  item: {
    type: 'message',
    role: 'user',
    content: [{
      type: 'input_text',
      text: `Network check results: ${response.message}`
    }]
  }
}
wsRef.current.send(JSON.stringify(networkResultMessage))
// ✅ VAD will detect this as new user input and auto-create response
```

## Why This Works:

1. **Single voice throughout**: Only one response per turn, always using session voice
2. **Proper flow**: 
   - Function called → output sent → VAD creates response
   - A2A arrives → injected as user message → VAD creates next response
3. **AI has context**: User messages are always in conversation context
4. **Natural conversation**: VAD handles all response timing

## Implementation:

Search for these two lines and DELETE them:
1. Line ~324: `wsRef.current?.send(JSON.stringify({ type: 'response.create' }))`  
2. Line ~382: `wsRef.current.send(JSON.stringify({ type: 'response.create' }))`

The session's `create_response: true` will handle everything automatically.
