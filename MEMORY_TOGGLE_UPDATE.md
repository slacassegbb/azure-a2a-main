# Conversation Memory Toggle - Implementation Summary

## Date: February 4, 2026

## Problem
The "Memory Enabled" toggle in the Host Orchestrator card was only controlling READ access to memory (search_memory tool), but NOT WRITE access. This meant:
- A2A interactions were always being stored in Azure Search regardless of toggle setting
- Caused unnecessary costs and data duplication
- Created confusion when finding old conversation data even with memory "disabled"

## Solution Implemented

### 1. Changed Default to Disabled (Frontend)
**File:** `frontend/components/chat-layout.tsx`
- Changed `useState(true)` → `useState(false)`
- Conversation memory is now OFF by default, saving costs
- Uploaded documents are ALWAYS stored and searchable

### 2. Renamed to "Conversation Memory" (Frontend)
**File:** `frontend/components/agent-network.tsx`
- Updated tooltip to clearly show "Conversation Memory: ON/OFF"
- Shows what's being stored: "Storing conversations + documents" vs "Storing documents only"
- Makes it clear that files are always available

### 3. Conditional Storage of A2A Interactions (Backend)
**File:** `backend/hosts/multiagent/foundry_agent_a2a.py`
- Added check for `enable_inter_agent_memory` flag before storing interactions
- Two locations updated (Task-based and Message-based responses)
- Log messages added to track when storage is skipped

**Changes:**
```python
# Before: Always store
asyncio.create_task(self._store_a2a_interaction_background(...))

# After: Only store when memory enabled
enable_memory = getattr(session_context, 'enable_inter_agent_memory', False)
if enable_memory:
    asyncio.create_task(self._store_a2a_interaction_background(...))
    log_debug(f"[Memory] Storing A2A interaction for {agent_name} (memory enabled)")
else:
    log_debug(f"[Memory] Skipping A2A interaction storage for {agent_name} (memory disabled)")
```

### 4. Document Processing Always Stores (Backend)
**File:** `backend/hosts/multiagent/a2a_document_processor.py`
- Added comment clarifying that uploaded document content is ALWAYS stored
- This ensures files are searchable via `search_memory` tool regardless of toggle
- Only A2A conversation interactions respect the toggle

## Behavior Matrix

| Toggle State | Files Stored & Searchable | Conversations Stored & Searchable | search_memory Tool | Passed to Remote Agents |
|-------------|---------------------------|----------------------------------|-------------------|------------------------|
| **OFF** (default) | ✅ YES | ❌ NO | ✅ Available (finds docs only) | ✅ YES (via search) |
| **ON** | ✅ YES | ✅ YES | ✅ Available (finds both) | ✅ YES (via search) |

## How It Works

### Data Flow with Conversation Memory OFF (default):
1. User uploads PDF → Document processor extracts text → Stores in Azure Search ✅
2. User asks "What's in the PDF?" → Host uses `search_memory` → Finds document content → Responds ✅
3. User says "Call QuickBooks" → Host calls QB agent → QB responds → Conversation NOT stored ❌
4. New chat session → User asks "What did QuickBooks say?" → No results (conversation wasn't stored) ❌
5. New chat session → User asks "What's in the PDF?" → Still finds it (documents always stored) ✅

### Data Flow with Conversation Memory ON:
1. User uploads PDF → Stores in Azure Search ✅
2. User calls QuickBooks → Conversation stored in Azure Search ✅
3. New chat session → Can search for both PDF content AND QB conversation ✅

### Remote Agent Access:
- Remote agents receive context via the host's `search_memory` tool
- Host searches memory → Gets relevant docs → Includes in delegation message
- Works REGARDLESS of conversation memory toggle (files always available)

## Benefits

1. **Cost Savings**: By default, no A2A conversations stored (only documents)
2. **Clarity**: "Conversation Memory" toggle clearly shows what it controls
3. **Privacy**: Conversations don't leak across sessions unless explicitly enabled
4. **File Management**: Uploaded documents always searchable and available to agents
5. **Predictable Behavior**: Toggle does exactly what the label says

## What Gets Stored in Azure Search

### When Conversation Memory is OFF (default):
- ✅ Document processing results (PDFs, Word docs, images analyzed)
- ❌ Agent-to-agent conversation messages
- ❌ QuickBooks responses
- ❌ Email agent responses
- ❌ Any other A2A interaction

### When Conversation Memory is ON:
- ✅ Document processing results
- ✅ Agent-to-agent conversation messages
- ✅ All remote agent responses
- ✅ Full A2A protocol payloads

## Migration Notes

- Existing stored interactions in Azure Search are NOT automatically deleted
- Users can manually clear memory using the "Clear Memory" button
- New sessions will use the new default (disabled)

## Testing Recommendations

1. Test with memory disabled (default):
   - Upload and analyze a document → Should work
   - Ask agent about uploaded doc → Should find it
   - Ask agent to call QuickBooks → Should work
   - Start new conversation → Should NOT see previous QB results

2. Test with memory enabled:
   - Upload and analyze a document → Should work
   - Ask agent about uploaded doc → Should find it
   - Ask agent to call QuickBooks → Should work
   - Start new conversation → SHOULD see previous QB results

3. Test toggle switching:
   - Start with memory ON, have conversation
   - Toggle OFF → search_memory should be unavailable
   - New interactions should NOT be stored
   - Toggle back ON → old stored data should be accessible again

## Related Files Modified

1. `frontend/components/chat-layout.tsx` - Default state change
2. `backend/hosts/multiagent/foundry_agent_a2a.py` - Conditional storage logic
3. `backend/hosts/multiagent/a2a_document_processor.py` - Documentation update
