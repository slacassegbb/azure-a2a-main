# Testing Voice Live A2A Integration

## Setup

1. **Ensure backend is running**:
   ```bash
   cd backend
   python backend_production.py
   ```

2. **Ensure frontend is running**:
   ```bash
   cd Visualizer/voice-a2a-fabric
   npm run dev
   ```

3. **Check Azure AI Foundry key is configured**:
   - Key is hardcoded in `backend/backend_production.py` (line 814)
   - Endpoint: `/api/azure-token`

## Test Scenarios

### Test 1: Insurance Claim Processing (Full A2A Integration)

**Steps:**
1. Open dashboard at `http://localhost:3000`
2. Select "Insurance Claim Processing" from scenario dropdown
3. Click microphone button (turns red when recording)
4. Say: "Hi, I need to file an insurance claim"
5. AI will guide you through:
   - Asking your name
   - Type of claim (damage, theft, loss)
   - What happened
   - Date of incident
   - Device details if applicable

**Expected Behavior:**
- AI asks follow-up questions naturally
- When you provide enough info, AI says "Let me submit that for you..."
- **CRITICAL**: AI continues talking while A2A processes
  - "I've submitted your claim for processing..."
  - "Let me check with our specialists..."
  - "Do you have any questions while we verify coverage?"
- Dashboard shows agents activating (pulsing circles)
- When A2A completes, AI explains the result
- Human operator node pulses during conversation

**Watch For:**
- ✅ AI never goes silent while waiting
- ✅ Audio is ultra-smooth (no choppiness)
- ✅ Agent network visualizes activity
- ✅ Final response is communicated naturally
- ✅ Human operator pulses when voice is active

### Test 2: Technical Support (Simpler A2A)

**Steps:**
1. Select "Technical Support" scenario
2. Click microphone
3. Say: "My internet isn't working"
4. Answer AI's troubleshooting questions:
   - What service (internet)
   - What's happening (no connection)
   - What you've tried (restarted router)

**Expected Behavior:**
- AI tries basic troubleshooting first
- If needed, escalates to agent network
- Continues engaging while waiting
- Shares specialist recommendations

### Test 3: Customer Service (No A2A)

**Steps:**
1. Select "General Customer Service" scenario
2. Click microphone
3. Ask: "What plans do you offer?"

**Expected Behavior:**
- AI answers directly (no network call)
- No agent visualization
- Conversation stays in Voice Live only
- Shows Voice Live can work standalone

## Debugging

### Check WebSocket Connection
Open browser console:
```javascript
// Should see:
[VoiceLive] Connecting to: wss://owenv-foundry-resource.services.ai.azure.com/...
[VoiceLive] WebSocket connected
[VoiceLive] Session configuration sent
[VoiceLive] Session ready
```

### Check Function Calls
```javascript
// When AI calls tool:
[VoiceLive] Function call: submit_claim_to_network { customer_name: "...", ... }
[Dashboard] Tool called: submit_claim_to_network
[Dashboard] Sending to A2A network: Process damage request for ...
```

### Check A2A Response Injection
```javascript
// When network responds:
[AgentDashboard] Message received: { role: "assistant", content: [...] }
[Dashboard] Injecting A2A response into Voice Live
[VoiceLive] Injecting network response: { claim_id: "...", status: "completed" }
```

### Check Audio Playback
```javascript
// Should see smooth buffering:
[VoiceLive] Event: response.audio.delta
[VoiceLive] Event: response.audio.delta
[VoiceLive] Event: response.audio.delta
// Then playback starts after 3 chunks buffered
```

## Common Issues

### Issue: "WebSocket error: {}"
**Fix**: Check API key in `backend_production.py` line 814

### Issue: "Unable to decode audio data"
**Fix**: Already fixed with PCM16 conversion in `use-voice-live.ts`

### Issue: Audio chops/stutters
**Fix**: Already fixed with scheduled playback and 3-chunk buffer

### Issue: AI waits silently after tool call
**Fix**: Check scenario instructions include "continue talking" guidance
**Check**: `response.create` is sent after function response

### Issue: A2A response not injected
**Check**: 
- `pendingA2AResponse` state is set
- `conversation_id` matches in message event
- WebSocket is still connected

## Performance Metrics

**Expected timings:**
- Voice Live connection: <500ms
- Audio chunk latency: 50-100ms
- Function call execution: <200ms
- A2A network response: 3-10 seconds (varies by complexity)
- Response injection: <100ms

## Manual Testing Checklist

- [ ] Scenario selector shows all scenarios
- [ ] Mic button turns red when recording
- [ ] "Listening..." appears during recording
- [ ] "AI Speaking..." appears during playback
- [ ] Audio is smooth and clear
- [ ] AI asks appropriate questions for scenario
- [ ] Tool calls trigger at right time
- [ ] AI continues talking after tool call
- [ ] Agent network visualizes activity
- [ ] Human operator pulses during voice conversation
- [ ] A2A response is communicated naturally
- [ ] Voice button returns to green when done
- [ ] Can switch scenarios between conversations
- [ ] Multiple conversations work sequentially

## Advanced Testing

### Test Interruption Handling
1. Start claim submission
2. Interrupt AI while talking
3. Say something different
**Expected**: AI should handle gracefully

### Test Multiple Tools
1. Create scenario with multiple tools
2. See if AI chains tool calls appropriately

### Test Error Recovery
1. Disconnect network during conversation
2. See error handling and user messaging

### Test Long Responses
1. Ask complex question requiring long A2A processing
2. Verify AI fills time appropriately
3. Check audio remains smooth during long playback
