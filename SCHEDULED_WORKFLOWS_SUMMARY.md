# Summary: Scheduled Workflows Cold-Start Support

## What Was Fixed ✅

### Problem
Scheduled workflows failed when calling Azure Container Apps agents that were scaled to zero.

### Root Cause
1. Workflows used `localhost` URLs instead of production Azure URLs
2. HTTP timeouts too short (5s) for container cold starts (20-60s)

### Solution
**Two simple changes:**

1. **Force Production URLs** (`backend/backend_production.py` line ~220)
   - Scheduled workflows now automatically use `production_url` instead of `local_url`
   - Ensures workflows call public Azure endpoints, not localhost

2. **Extended HTTP Timeouts** (`backend/hosts/multiagent/foundry_agent_a2a.py` line ~5080)
   - Increased connect timeout: 5s → 60s (allows container wake-up)
   - Increased read timeout: default → 180s (allows agent processing)

## What This Enables 🎯

✅ **Agent containers can scale to zero**
- First request wakes them up (20-60s)
- Subsequent requests are fast (<5s)
- Cost-efficient when not in use

✅ **Scheduled workflows work reliably**
- Production URLs ensure correct endpoints
- Extended timeouts wait for cold starts
- No manual intervention needed

## Important: Backend Must Be Running ⚠️

The scheduler runs **inside** the backend, so:
- Backend running → Scheduler active → Workflows execute on time ✅
- Backend scaled to zero → Scheduler stopped → Workflows don't run ❌

**Recommendation for Production:**
```bash
az containerapp update --name a2a-backend --resource-group <your-rg> --min-replicas 1
```

This keeps the backend (and scheduler) always running while allowing agents to scale to zero.

## Files Changed

1. `backend/backend_production.py` - Force production URLs for scheduled workflows
2. `backend/hosts/multiagent/foundry_agent_a2a.py` - Extended HTTP client timeouts
3. `SCHEDULED_WORKFLOWS_COLD_START_FIX.md` - Full documentation

## Testing

Test locally with running backend:
```bash
cd backend
source .venv/bin/activate
python test_schedule_via_api.py
```

This will:
- Create a test schedule
- Wait for execution
- Show results
- Clean up

## Deployment

Commit and deploy changes:
```bash
git add backend/
git commit -m "fix: scheduled workflows support for agent cold starts - force production URLs and extend timeouts"
git push
```

Then deploy to Azure using your existing deployment script.

---

**Date**: February 4, 2026  
**Status**: ✅ Complete and Ready
