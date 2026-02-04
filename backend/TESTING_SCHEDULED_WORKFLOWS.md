# Testing Scheduled Workflows from Terminal

## Quick Test (Headless)

Since scheduled workflows are headless and don't require a browser, you can test them directly from the terminal.

### Method 1: Via API Test Script (Recommended)

**Prerequisites**: Backend must be running

**Step 1**: In one terminal, start the backend:
```bash
cd /Users/simonlacasse/Downloads/sl-a2a-main2/backend
source .venv/bin/activate
python backend_production.py
```

**Step 2**: In another terminal, run the test script:
```bash
cd /Users/simonlacasse/Downloads/sl-a2a-main2/backend
source .venv/bin/activate
python test_schedule_via_api.py
```

**What it does**:
1. ✅ Checks if backend is running
2. ✅ Gets list of workflows
3. ✅ Creates a one-time schedule (runs in 5 seconds)
4. ✅ Waits for execution to complete
5. ✅ Shows the result
6. ✅ Cleans up the test schedule

**Expected output**:
```
======================================================================
🧪 TESTING SCHEDULED WORKFLOW VIA API
======================================================================

📋 Step 1: Checking if backend is running at http://localhost:12000...
✅ Backend is running!

📋 Step 2: Getting list of workflows...
✅ Found 1 workflow(s):
   1. tst_stripe_twilio - Check my Stripe balance and send me a text...

   Selected: tst_stripe_twilio

📋 Step 3: Creating test schedule (one-time immediate execution)...
✅ Schedule created with ID: schedule_abc123
   Will run at: 2026-02-04T15:30:05.123456

📋 Step 4: Waiting for workflow to execute...
   ⏳ This may take 30-90s for cold starts...
   💡 Check your backend terminal for [SCHEDULER] logs

📋 Step 5: Checking run history...
   ⏳ Attempt 1/30: No run history yet...
   ⏳ Attempt 2/30: Still running...
   
======================================================================
📊 WORKFLOW EXECUTION RESULT
======================================================================
✅ Status: SUCCESS
⏱️  Started: 2026-02-04T15:30:05.123456Z
⏱️  Completed: 2026-02-04T15:30:47.654321Z
⏱️  Duration: 42.5s

📄 Result:
[Result from agents will appear here]

======================================================================

📋 Cleaning up: Deleting test schedule...
✅ Test schedule deleted

✅ Test completed successfully!
```

### Method 2: Check Backend Logs

Just watch the backend terminal while a scheduled workflow runs. Look for:

```
[SCHEDULER] Workflow 'tst_stripe_twilio' needs agents: ['AI Foundry Stripe Agent', 'Twilio SMS Agent']
[SCHEDULER] 🌐 Using production URL for 'AI Foundry Stripe Agent': https://azurefoundry-stripe...
[SCHEDULER] 🌐 Using production URL for 'Twilio SMS Agent': https://azurefoundry-twilio2...
[SCHEDULER] ✅ Enabled agent 'AI Foundry Stripe Agent' for session scheduler_xxxxx
[SCHEDULER] ✅ Enabled agent 'Twilio SMS Agent' for session scheduler_xxxxx
[SCHEDULER] ⏳ Calling agent_server.manager.process_message()...
[SCHEDULER] ✅ Workflow execution completed in 42.5s
```

### Method 3: Manual Trigger via API

Use curl or httpx to trigger a workflow directly:

```bash
# Create a one-time schedule
curl -X POST http://localhost:12000/api/schedules \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_name": "tst_stripe_twilio",
    "schedule_type": "once",
    "schedule_time": "2026-02-04T15:30:00",
    "enabled": true,
    "session_id": "test_user"
  }'

# Check run history
curl http://localhost:12000/api/schedules/history?limit=1
```

## What to Look For

### ✅ Success Indicators:
- `[SCHEDULER] 🌐 Using production URL` - Confirms using Azure URLs
- `[SCHEDULER] ✅ Enabled agent` - Agents registered for session
- `[SCHEDULER] ✅ Workflow execution completed` - Success!
- Execution time reasonable (5-90s depending on cold start)

### ❌ Failure Indicators:
- `httpx.ConnectError: All connection attempts failed` - Agents not reachable
- `TimeoutError` - Execution took too long
- `Agent server is None` - Backend not properly initialized
- `Missing agents in registry` - Agents not found in database

## Cold Start Behavior

**First execution** (containers scaled to zero):
- ⏱️ Takes 60-90 seconds
- 🌡️ Azure wakes up containers
- ✅ Should succeed with new timeout settings

**Subsequent executions** (within ~15 minutes):
- ⏱️ Takes 5-15 seconds  
- 🔥 Containers already warm
- ✅ Fast execution

## Troubleshooting

### Backend not running
```
❌ Backend is not running or not accessible!
```
**Solution**: Start backend in another terminal

### Agents timeout
```
❌ httpx.ConnectError: All connection attempts failed
```
**Solution**: Agents may be scaled to zero. First request wakes them up (takes 20-60s)

### Wrong URLs
```
[SCHEDULER] 🔗 Using URL for 'Agent Name': http://localhost:9030/
```
**Should see**:
```
[SCHEDULER] 🌐 Using production URL for 'Agent Name': https://azurefoundry-...
```
**Solution**: Make sure the code changes were applied (check backend_production.py line ~220)

## Files

- `test_schedule_via_api.py` - API-based test (works with running backend)
- `test_scheduled_workflow_execution.py` - Direct execution test (requires agent_server init)
- `check_agent_urls.py` - Check agent URL configuration
- `test_azure_agents.py` - Test Azure agent connectivity
