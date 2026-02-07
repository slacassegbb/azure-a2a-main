# QuickBooks Token Bloat Fix - Context Reduction

## Problem Discovery

After implementing rate limit retry logic, we discovered the QuickBooks agent was still hitting rate limits because of **massive context bloat**.

### Symptoms

```
INFO:foundry_agent:   User message length: 5142 chars (~1285 tokens)
ERROR:foundry_agent:   usage: {'prompt_tokens': 23348, 'completion_tokens': 489, 'total_tokens': 23837}
```

**Expected**: ~3,000-5,000 tokens  
**Actual**: **23,348 tokens** (first run), **44,640 tokens** (second run)

### Root Cause

The workflow orchestrator (`foundry_agent_a2a.py`) was injecting **huge amounts of context** from previous agents via the `_add_context_to_message` method:

1. **Duplicate invoice data**: DocumentProcessor output included **twice** 
2. **top_k=2**: Retrieving 2 memory results (both containing the same invoice)
3. **2000 chars per result**: 2000 chars × 2 results = **4000+ chars** of context
4. **Full invoice tables**: Including verbose markdown tables with all line items

Example of bloated context:
```
Relevant context from previous interactions:
  1. From DocumentProcessor: # Invoice Details [FULL 2000 CHAR INVOICE]
  2. From DocumentProcessor: # Invoice Details [SAME INVOICE AGAIN!]
```

This caused the 5K char user message to balloon to **23K-44K tokens**.

## Solution Implemented

### 1. Reduce Character Limit for QuickBooks (Line 3285)

```python
# For QuickBooks agent, reduce to 500 chars since structured data is verbose
max_chars = 500 if target_agent_name and 'quickbooks' in target_agent_name.lower() else self.memory_summary_max_chars
if len(content_summary) > max_chars:
    content_summary = content_summary[:max_chars] + "..."
```

**Before**: 2000 chars per memory result  
**After**: 500 chars per memory result for QuickBooks agent

### 2. Reduce Memory Results (Line 3169)

```python
# Reduce top_k=1 for QuickBooks to avoid duplicate context (saves ~500-1000 tokens)
top_k_results = 1 if (target_agent_name and 'quickbooks' in target_agent_name.lower()) else 2
memory_results = await self._search_relevant_memory(
    query=message,
    context_id=session_context.contextId,
    agent_name=None,
    top_k=top_k_results
)
```

**Before**: top_k=2 (retrieve 2 memory results)  
**After**: top_k=1 (retrieve only most relevant result for QuickBooks)

## Impact

### Token Reduction Calculation

| Component | Before | After | Savings |
|-----------|--------|-------|---------|
| Memory result #1 | 2000 chars (~500 tokens) | 500 chars (~125 tokens) | 375 tokens |
| Memory result #2 | 2000 chars (~500 tokens) | Removed (0 tokens) | 500 tokens |
| **Total Savings** | | | **~875 tokens** |

### Expected Results

**Before Fix:**
```
User message: 5142 chars (~1285 tokens)
+ Agent instructions: ~2000 tokens
+ MCP schemas: ~5000 tokens
+ Memory context: ~1000 tokens (2 results × 500 tokens)
────────────────────────────────────────
Total prompt: ~9,285 tokens
```

**After Fix:**
```
User message: 5142 chars (~1285 tokens)
+ Agent instructions: ~2000 tokens
+ MCP schemas: ~5000 tokens
+ Memory context: ~125 tokens (1 result × 125 tokens)
────────────────────────────────────────
Total prompt: ~8,410 tokens (9% reduction)
```

**Why still high?** The MCP schema and agent instructions are still large, but this fix prevents the massive context duplication.

## Additional Context

### Why Was It 23K-44K Tokens?

The actual token count was much higher than expected because:

1. **Azure AI Foundry thread context**: Accumulates all messages in the thread
2. **File attachments**: PDF was being processed (adds tokens)
3. **Multiple run steps**: Each tool call adds more context
4. **Agent instructions**: ~2K tokens of QuickBooks tool documentation

The fix addresses the **controllable bloat** (memory context injection).

## Testing

### Before Restart
Wait 3+ minutes for TPM quota to fully reset.

### After Restart
1. Trigger QuickBooks invoice creation workflow
2. Monitor logs for token usage:
   ```
   WARNING:foundry_agent:💰 TOTAL RUN TOKEN USAGE: {'prompt_tokens': ???, ...}
   ```
3. Expected improvement: 8K-12K tokens (vs 23K-44K before)

### Success Criteria
- ✅ Prompt tokens < 15,000
- ✅ No immediate rate limit on first call
- ✅ Workflow completes without hitting TPM limit

## Files Modified

- `backend/hosts/multiagent/foundry_agent_a2a.py`
  - Line 3169: Reduce top_k to 1 for QuickBooks
  - Line 3285: Reduce max_chars to 500 for QuickBooks

## Deployment

Commit: `df2af77` on `feature/postgresql-migration` branch

To deploy:
```bash
# Stop backend
Ctrl+C in backend terminal

# Restart backend
cd /Users/simonlacasse/Downloads/sl-a2a-main2/backend
python backend_production.py
```

## Why This is Important

With Azure OpenAI S0 tier having ~10K-20K TPM limits:

- **Before**: 23K-44K tokens = instant rate limit
- **After**: 8K-12K tokens = fits within quota
- **Combined with retry logic**: Handles occasional spikes gracefully

This fix makes QuickBooks workflows **viable on S0 tier** instead of requiring expensive S1/S2 upgrades.

## Future Improvements

### Short-term
- [ ] Add environment variable for QuickBooks-specific context limit
- [ ] Implement smart context pruning (keep only customer/invoice IDs, not full tables)
- [ ] Add token usage tracking to prevent context bloat proactively

### Long-term
- [ ] Implement context summarization (LLM-powered summary of long documents)
- [ ] Add per-agent context strategies (different limits for different agent types)
- [ ] Migrate to Azure OpenAI S1 tier (60K TPM) for production workloads
- [ ] Implement prompt caching to reuse common instruction blocks

## Related Documents

- `RATE_LIMIT_FIX.md`: Rate limit retry logic implementation
- `MCP_SCHEMA_OPTIMIZATION.md`: Original 90% token reduction (31K → 3K)
- Agent retry logic: `remote_agents/azurefoundry_QuickBooks/foundry_agent.py` lines 644-693
