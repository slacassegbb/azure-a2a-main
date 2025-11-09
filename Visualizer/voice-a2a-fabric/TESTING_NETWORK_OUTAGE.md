# Testing Network Outage Scenario

## Scenario Overview
This is a multi-stage voice conversation that demonstrates:
1. Customer authentication
2. Outage detection
3. Modem diagnostics
4. Detailed investigation results
5. Seamless conversation flow throughout

## Test Script

### Prerequisites
- Backend running on `localhost:12000`
- Frontend running on `localhost:3000`
- "Network Outage Support" scenario selected

### Stage 1: Initial Contact & Authentication

**User says:** "Help me, my internet is down and I need to work!"

**Expected AI Response:**
- Acknowledges urgency: "I understand how important internet access is for your work..."
- Asks for authentication:
  - Full name
  - Postal code  
  - Date of birth (MM/DD/YYYY)

**User provides:**
- Name: "John Smith"
- Postal: "M5H 2N2"
- DOB: "03/15/1985"

**Expected AI Actions:**
1. ✅ Calls `authenticate_and_check_outage` tool
2. ✅ Says: "Thank you! I'm authenticating your account and checking for outages..."
3. ✅ Asks: "While I'm checking, can you tell me more about what's happening?"
4. ✅ **CRITICAL**: AI continues talking, doesn't wait silently

**Backend Processing (3-5 seconds):**
- Outage check agent investigates area
- Network status analyzed
- Returns outage information

**Watch For:**
- 🎯 AI keeps conversation flowing during wait
- 🎯 No awkward silence
- 🎯 `authenticate_and_check_outage` appears in network activity

---

### Stage 2: Outage Information Delivery

**Expected AI Response (when backend returns):**
- "I can see there IS an outage affecting your area"
- Explains outage details:
  - Area: "Downtown Toronto - M5H region"
  - Cause: "Fiber optic cable damage from construction"
  - ETA: "2-3 hours for full restoration"
- Empathizes: "I know this is frustrating, especially when you need to work"
- Asks: "Can you describe the lights on your modem? What colors are showing?"

**User responds:** "The lights are blinking yellow"

**Expected AI Actions:**
1. ✅ Calls `submit_modem_diagnostics` tool with "blinking yellow"
2. ✅ Says: "Thank you! I've sent that to our network engineers..."
3. ✅ Reassures: "They're analyzing your connection with advanced diagnostic tools..."
4. ✅ Keeps engaging: "Have you noticed any error messages on your devices?"

**Watch For:**
- 🎯 Clear outage explanation
- 🎯 Modem light info captured correctly
- 🎯 AI continues conversation while engineers analyze

---

### Stage 3: Detailed Investigation

**Expected AI Behavior (while waiting for detailed results):**
- Fills time with helpful conversation
- Asks about error messages
- Suggests mobile data workaround
- Explains what engineers are checking
- Maintains empathetic tone

**Example AI Statements:**
- "Our engineers have access to advanced diagnostic tools..."
- "They can see exactly what's affecting your connection..."
- "Is there anything else you've noticed?"
- "Have you been able to use mobile data as a workaround?"

**Backend Processing (5-10 seconds):**
- Modem check agent analyzes lights
- Network performance agent checks connection quality
- Technical dispatch agent coordinates investigation
- Returns detailed findings

**Watch For:**
- 🎯 No silence longer than 2-3 seconds
- 🎯 Natural conversation flow
- 🎯 Agent network visualizations show activity

---

### Stage 4: Final Results Delivery

**Expected AI Response (when detailed results arrive):**
- Summarizes technical findings in plain language
- Example: "Our engineers have completed the analysis. Here's what they found:
  - The blinking yellow light indicates your modem is trying to establish a connection but can't reach our network due to the outage
  - Your modem hardware is functioning correctly - this is purely a network issue
  - Once the fiber optic repair is complete in 2-3 hours, your modem should automatically reconnect
  - No action needed on your part - just watch for the lights to turn solid green
  - If it doesn't reconnect within 15 minutes after the estimated time, you can restart your modem"

- Offers additional help: "Is there anything else I can help you with?"

**User might say:** "No, that's all. Thank you."

**Expected AI Response:**
- "You're very welcome! I know how critical internet is for work. Our team is working hard to restore service"
- "If you have any other issues, don't hesitate to call back"
- "Have a great day!"

---

## Success Criteria

### Conversation Flow ✅
- [ ] AI never has awkward silences
- [ ] Transitions between stages are smooth
- [ ] Customer feels heard and supported throughout
- [ ] Technical info explained in plain language

### Function Calls ✅
- [ ] `authenticate_and_check_outage` called after collecting auth info
- [ ] `submit_modem_diagnostics` called after modem lights described
- [ ] Both functions send data to A2A network correctly

### A2A Integration ✅
- [ ] Stage 1: Authentication response returns outage info
- [ ] Stage 2: Diagnostics response returns detailed findings
- [ ] Dashboard shows agent activity during both stages
- [ ] Responses injected back to Voice Live automatically

### Audio Quality ✅
- [ ] Ultra-smooth playback throughout
- [ ] No choppiness or gaps
- [ ] Listening/Speaking indicators work correctly

### Customer Experience ✅
- [ ] Feels urgent and empathetic
- [ ] No waiting without explanation
- [ ] Clear information delivery
- [ ] Professional and helpful tone
- [ ] Natural conversation pace

---

## Console Debugging

### Expected Console Output

**Stage 1 - Authentication:**
```
[Dashboard] Tool called: authenticate_and_check_outage { full_name: "John Smith", ... }
[Dashboard] Sending to A2A network: Authenticate customer John Smith...
[VoiceLive] Function call: authenticate_and_check_outage
[AgentDashboard] Message received: { role: "assistant", content: [...] }
[Dashboard] Injecting A2A response into Voice Live
```

**Stage 2 - Diagnostics:**
```
[Dashboard] Tool called: submit_modem_diagnostics { modem_lights_description: "blinking yellow" }
[Dashboard] Sending to A2A network: Customer reports modem lights: blinking yellow
[VoiceLive] Function call: submit_modem_diagnostics
[AgentDashboard] Message received: { role: "assistant", content: [...] }
[Dashboard] Injecting A2A response into Voice Live
```

---

## Backend A2A Network Behavior

### Stage 1 Response (Outage Check)
Should return something like:
```json
{
  "conversation_id": "conv_123",
  "role": "assistant",
  "content": [{
    "type": "text",
    "content": "OUTAGE DETECTED: Downtown Toronto M5H region affected by fiber optic cable damage from construction. Estimated resolution: 2-3 hours. Multiple households impacted. Repair crews dispatched."
  }]
}
```

### Stage 2 Response (Detailed Diagnostics)
Should return something like:
```json
{
  "conversation_id": "conv_456",
  "role": "assistant",
  "content": [{
    "type": "text",
    "content": "DIAGNOSTIC RESULTS: Modem status - blinking yellow indicates connection attempt failure. Hardware functioning normally. Issue confirmed as network-side fiber damage. Customer modem will auto-reconnect when service restored. No customer action required. If not reconnected 15min post-ETA, advise modem restart."
  }]
}
```

---

## Testing Variations

### Variation 1: No Outage Detected
- Test authentication when there's NO outage
- AI should investigate individual connection issue instead
- Should ask more diagnostic questions

### Variation 2: Different Modem Lights
- Test with "solid red" or "all lights off"
- AI should handle different diagnostic info
- Network should provide appropriate response

### Variation 3: User Interruptions
- Interrupt AI while talking
- User changes topic mid-conversation
- Verify AI handles gracefully

### Variation 4: Extended Wait Time
- Simulate 15+ second A2A response
- Verify AI fills time appropriately
- Customer doesn't feel abandoned

---

## Troubleshooting

### Issue: AI waits silently after authentication
**Check:** 
- Scenario instructions include "continue talking" after tool calls
- `response.create` is sent after function response
- Backend returns response within reasonable time

### Issue: Outage info not delivered
**Check:**
- `pendingA2AResponse` state is set correctly
- `conversation_id` matches in response
- `injectNetworkResponse` is called

### Issue: Second tool call (modem diagnostics) fails
**Check:**
- AI received and processed first A2A response
- Conversation context maintained
- WebSocket still connected

### Issue: AI doesn't call tools
**Check:**
- Scenario tools are defined correctly
- Instructions clearly state when to call tools
- Authentication info collected before calling tool
