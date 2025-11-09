# Testing the Visualizer Integration

## Pre-flight Checklist

Before testing, ensure:
- [ ] Backend is running on `localhost:12000`
- [ ] WebSocket server is running on `localhost:8080`
- [ ] Visualizer dependencies installed (`npm install`)
- [ ] Root `.env` file has correct configuration (inherited automatically)

## Test Suite

### Test 1: WebSocket Connection ✅

**Steps:**
1. Start backend: `python backend/backend_production.py`
2. Start Visualizer: `npm run dev` (in Visualizer directory)
3. Open `http://localhost:3000`
4. Open browser console (F12)

**Expected Results:**
- ✅ Green dot next to "Connected to Backend"
- ✅ Console shows: `[EventHubProvider] Successfully connected to WebSocket server`
- ✅ Console shows: `[WebSocket] Connected successfully`

**If Failed:**
- Check backend is running: `curl http://localhost:12000/health`
- Check WebSocket port: Try connecting to `ws://localhost:8080/events` in browser tools
- Verify root `.env` has correct `NEXT_PUBLIC_WEBSOCKET_URL`

---

### Test 2: Agent Registry Sync ✅

**Steps:**
1. Ensure backend has registered agents
2. Wait 2-3 seconds after connection
3. Check right sidebar "Connected Agents"
4. Check activity log (left sidebar)

**Expected Results:**
- ✅ Right sidebar shows all agents from backend registry
- ✅ Activity log shows "Agent connected to network" for each agent
- ✅ Network visualization shows agents in a circle around host
- ✅ KPI shows correct agent count (e.g., "5" if 5 agents total)

**If Failed:**
- Check backend agent registry: `curl http://localhost:12000/agents`
- Look for console message: `[AgentDashboard] Agent registry sync received`
- Check console for `agent_registry_sync` event

---

### Test 3: Send Request (Real Backend) ✅

**Steps:**
1. Ensure connection is green
2. Click "Send Request" button (top right)
3. Watch the visualization

**Expected Results:**
- ✅ Button shows "Processing..." briefly
- ✅ Host Agent (center) glows immediately
- ✅ Activity log shows "Processing request and routing to agents..."
- ✅ Remote agents glow one by one as they process
- ✅ Thought bubbles appear above agents
- ✅ Activity log fills with agent updates
- ✅ "Events Processed" KPI increments
- ✅ Console shows: `[WebSocket] Message sent`

**If Failed:**
- Check console for errors
- Verify backend is processing requests
- Look for `task_updated` and `message` events in console
- Enable debug mode: `NEXT_PUBLIC_DEBUG_LOGS=true`

---

### Test 4: Real-time Event Handling ✅

**Steps:**
1. Keep Visualizer open
2. From main frontend (if available), send a chat message
3. Watch Visualizer for updates

**Expected Results:**
- ✅ Visualizer shows agent activity from frontend request
- ✅ Agents glow as they process
- ✅ Activity log shows events from both sources
- ✅ Demonstrates true real-time sync

**Note:** This tests that both UIs can observe the same agent network

---

### Test 5: Connection Resilience ✅

**Steps:**
1. Start with everything connected (green dot)
2. Stop the backend
3. Wait 5 seconds
4. Restart the backend
5. Wait 10 seconds

**Expected Results:**
- ✅ Indicator turns red when backend stops
- ✅ Console shows reconnection attempts
- ✅ Indicator turns green when backend restarts
- ✅ Agent registry re-syncs automatically
- ✅ No page refresh needed

**If Failed:**
- Check reconnection logic in console
- Verify backend WebSocket is running after restart
- Check for errors preventing reconnection

---

### Test 6: Debug Mode ✅

**Steps:**
1. Set `NEXT_PUBLIC_DEBUG_LOGS=true` in root `.env`
2. Restart Visualizer
3. Open console
4. Send a request

**Expected Results:**
- ✅ Detailed WebSocket logs in console
- ✅ Event handler logs: `[AgentDashboard] Task updated`
- ✅ Message logs: `[WebSocket] Message sent`
- ✅ Connection state logs

**Use Debug Mode When:**
- Troubleshooting connection issues
- Investigating event handling
- Understanding event flow
- Debugging integration

---

## Performance Tests

### Agent Capacity
- [ ] Test with 5 agents
- [ ] Test with 10 agents
- [ ] Test with 20+ agents

### Event Throughput
- [ ] Send multiple rapid requests
- [ ] Observe activity log performance
- [ ] Check for event lag or missing events

### Long Running
- [ ] Keep Visualizer open for 30+ minutes
- [ ] Verify no memory leaks
- [ ] Check WebSocket stays connected

## Manual Verification

### Visual Elements
- [ ] All agents render correctly
- [ ] Connection lines visible
- [ ] Glow effects work smoothly
- [ ] Thought bubbles animate properly
- [ ] Activity log scrolls correctly

### UI Components
- [ ] Connection indicator updates
- [ ] Send Request button enables/disables correctly
- [ ] KPIs update in real-time
- [ ] Agent cards expand/collapse
- [ ] All text is readable

### Error Handling
- [ ] Graceful degradation when backend down
- [ ] Clear error messages in console
- [ ] No UI crashes on connection loss
- [ ] Reconnection works after errors

## Common Issues & Solutions

### Issue: WebSocket Connection Fails

```
[WebSocket] Connection error on attempt 1 (readyState=3)
```

**Solutions:**
1. Check backend is running: `curl http://localhost:12000/health`
2. Check WebSocket server: `netstat -an | grep 8080`
3. Verify firewall isn't blocking port 8080
4. Try different port in root `.env` if needed

---

### Issue: No Events Received

```
[AgentDashboard] WebSocket event handlers subscribed
```
But no events after sending request.

**Solutions:**
1. Check backend is sending events: Look at backend console
2. Verify event format matches A2A spec
3. Check event type names match handlers
4. Enable debug mode to see raw events

---

### Issue: Agents Not Showing

```
[AgentDashboard] Agent registry sync received: []
```

**Solutions:**
1. Check backend has agents: `curl http://localhost:12000/agents`
2. Verify backend is sending agent data in sync event
3. Check agent format matches expected structure
4. Look for JavaScript errors in agent mapping

---

## Test Commands

```bash
# Check backend health
curl http://localhost:12000/health

# Check agent registry
curl http://localhost:12000/agents

# Check WebSocket port
netstat -an | grep 8080

# Start backend (from project root)
python backend/backend_production.py

# Start Visualizer (from Visualizer directory)
npm run dev

# Install dependencies (if needed)
npm install

# Check environment (inherited from root)
cat ../../.env
```

## Success Criteria

Integration is successful when:

- ✅ WebSocket connects automatically on app start
- ✅ Green indicator shows when connected
- ✅ Agents populate from backend registry
- ✅ Send Request sends real messages to backend
- ✅ Activity log shows real-time events
- ✅ Agents glow and show thought bubbles
- ✅ KPIs update correctly
- ✅ Reconnection works after backend restart
- ✅ No console errors during normal operation
- ✅ Both main frontend and Visualizer can coexist

## All Tests Passing? 🎉

If all tests pass, the integration is **BULLETPROOF** and production-ready!

The Visualizer now has:
- ✅ Real-time WebSocket connection
- ✅ Full A2A event integration
- ✅ Bidirectional communication
- ✅ Robust error handling
- ✅ Auto-reconnection
- ✅ Live agent synchronization
- ✅ Production-grade logging
- ✅ Comprehensive documentation

You're all set! 🚀
