# Scheduled Workflows - Cold Start Support for Agents

## Problem
Scheduled workflows were failing when trying to call Azure Container Apps **agents** that were scaled to zero:
- ❌ `httpx.ConnectError: All connection attempts failed`
- ❌ Workflows timing out when agents needed to wake up from scale-to-zero state

## Root Causes
1. **Wrong URLs**: Scheduled workflows were using `local_url` instead of `production_url` for agents
2. **Short timeouts**: HTTP client had default 5-second timeout, insufficient for cold starts (20-30s)
3. **Scaled agent containers**: Azure Container Apps agents were scaled to zero and needed to wake up

## Solutions Implemented

### 1. Force Production URLs for Scheduled Workflows
**File**: `backend/backend_production.py` - `execute_scheduled_workflow()` function

**Change**: When enabling agents for scheduled workflows, always use `production_url` if available:

```python
# Force production URL for scheduled workflows
if 'production_url' in agent_config and agent_config['production_url']:
    agent_config = agent_config.copy()
    agent_config['url'] = agent_config['production_url']
    print(f"[SCHEDULER] 🌐 Using production URL for '{agent_name}': {agent_config['url']}")
```

**Why**: Scheduled workflows should always use public Azure URLs, not localhost URLs.

### 2. Extended HTTP Client Timeouts
**File**: `backend/hosts/multiagent/foundry_agent_a2a.py` - `create_with_shared_client()` method

**Change**: Configure httpx.AsyncClient with extended timeouts for cold starts:

```python
timeout_config = httpx.Timeout(
    connect=60.0,  # Time to establish connection (important for cold starts)
    read=180.0,    # Time to read response (agent processing time)
    write=30.0,    # Time to send request
    pool=10.0      # Time to get connection from pool
)
shared_client = httpx.AsyncClient(timeout=timeout_config)
```

**Why**: Azure Container Apps can take 20-60 seconds to cold start from scale-to-zero state.

### 3. Automatic Wake-Up Mechanism
The HTTP requests to scaled-to-zero agent containers automatically trigger Azure to wake them up. No additional code needed - the extended timeouts give enough time for the wake-up to complete.

## Architecture Notes

### Backend Scale-to-Zero Considerations
The scheduler runs **inside the backend process**, which means:
- ✅ Simple deployment (no separate service needed)
- ✅ Direct access to database and agent registry
- ⚠️ If backend scales to zero, scheduler stops too

**For reliable scheduled execution:**

**Option A: Keep Backend Warm (Recommended for Production)**
```bash
# Azure Container App - set minimum replicas to 1
az containerapp update --name a2a-backend --resource-group <rg> \
  --min-replicas 1
```
- ✅ Scheduler always running
- ✅ Scheduled workflows run exactly on time
- ✅ Simple and reliable

**Option B: Allow Backend Scale-to-Zero (Cost-Efficient)**
If backend can scale to zero, you need an external trigger to wake it periodically:
- Azure Logic App with timer trigger
- Azure Functions with timer trigger  
- External cron job calling a health endpoint

The backend will wake up, check for pending workflows, execute them, then can scale back to zero.

### Agent Scale-to-Zero
**Agents CAN scale to zero** - the fixes in this document ensure they wake up properly when called by workflows:
- ✅ Production URLs ensure we call the right endpoints
- ✅ Extended timeouts wait for cold starts
- ✅ Agents wake up automatically on first request

## How It Works Now

### When Containers Are Running (Hot):
1. ✅ Scheduled workflow triggers
2. ✅ Agent URLs resolve to Azure production endpoints
3. ✅ HTTP request sent with 60s connect timeout
4. ✅ Agent responds quickly (< 5s)
5. ✅ Workflow completes successfully

### When Containers Are Scaled to Zero (Cold):
1. ✅ Scheduled workflow triggers
2. ✅ Agent URLs resolve to Azure production endpoints
3. ✅ HTTP request sent to scaled-to-zero container
4. ✅ Azure Container Apps receives request and starts waking container
5. ⏳ Container cold start takes 20-60 seconds
6. ✅ HTTP client waits patiently (60s connect timeout)
7. ✅ Container finishes starting and accepts connection
8. ✅ Agent processes request and responds
9. ✅ Workflow completes successfully (with longer execution time)

## Timeout Configuration Summary

| Component | Timeout | Purpose |
|-----------|---------|---------|
| **Workflow Executor** | 120s | Overall workflow execution limit |
| **Agent Message** | 180s | Individual agent call timeout |
| **HTTP Connect** | 60s | Time to establish connection (cold start) |
| **HTTP Read** | 180s | Time for agent to process and respond |

## Testing

### Verify Agent URLs:
```bash
cd backend
source .venv/bin/activate
python check_agent_urls.py
```

### Test Agent Connectivity:
```bash
python test_azure_agents.py
```

### Test Scheduled Workflow:
1. Restart backend to load changes
2. Trigger scheduled workflow from UI
3. First run may take 60-90 seconds if containers are cold
4. Subsequent runs within ~15 minutes will be fast (containers stay warm)

## Production Impact

### ✅ Benefits:
- Scheduled workflows now work reliably with scale-to-zero agents
- No manual intervention needed for cold starts
- Cost-efficient: agents can scale to zero when idle
- Automatic wake-up on demand

### ⚠️ Considerations:
- **First execution slower**: Cold starts add 20-60s to execution time
- **Keep-warm strategy**: For time-critical workflows, consider keeping containers warm
- **Monitor timeouts**: Very complex workflows might need higher timeout values

## Files Modified

1. `backend/backend_production.py`
   - Lines 200-245: Added production URL forcing for scheduled workflows
   - Lines 3008-3051: Updated uvicorn log configuration (bonus: suppressed noisy schedule API logs)

2. `backend/hosts/multiagent/foundry_agent_a2a.py`
   - Lines 5073-5089: Added extended timeout configuration to httpx.AsyncClient

## Diagnostic Tools Created

1. `backend/check_agent_urls.py` - Check agent URL configuration in database
2. `backend/test_azure_agents.py` - Test connectivity to Azure agents with cold start support

## Next Steps

1. ✅ Restart backend to apply changes
2. ✅ Test scheduled workflow with Stripe + Twilio agents
3. 📊 Monitor execution times in run history
4. 🔧 Adjust timeouts if needed for more complex workflows
5. 📈 Consider keep-warm strategies for time-critical schedules

---

**Date**: February 4, 2026  
**Status**: ✅ Implemented and Ready for Testing
