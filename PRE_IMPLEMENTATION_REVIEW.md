# Pre-Implementation Review: Parallel Agent Execution

**Date:** 2025-11-16
**Feature:** Add support for parallel and sequential agent execution in Agent Mode

---

## 🔍 Pre-Implementation Findings

### 1. ✅ SessionContext Thread-Safety

**Current State:**
- `SessionContext` is a Pydantic `BaseModel` with mutable fields (`dict`, `list`)
- `_latest_processed_parts` is accessed and modified in multiple places
- Multiple parallel agents could append to this list simultaneously → **RACE CONDITION RISK**

**Example Risk:**
```python
# Thread 1: Agent A adds artifact
session_context._latest_processed_parts.append(artifact_a)

# Thread 2: Agent B adds artifact (simultaneously)
session_context._latest_processed_parts.append(artifact_b)

# Potential issue: List corruption or lost updates
```

**Required Fix:** ✅ MUST FIX
- Add asyncio lock for concurrent modifications
- Ensure atomic operations on shared state

**Fix Implementation:**
```python
class SessionContext(BaseModel):
    # ... existing fields ...
    _state_lock: asyncio.Lock = Field(default_factory=asyncio.Lock, exclude=True, repr=False)
    
    async def add_processed_part(self, part):
        """Thread-safe artifact addition"""
        async with self._state_lock:
            if not hasattr(self, '_latest_processed_parts'):
                self._latest_processed_parts = []
            self._latest_processed_parts.append(part)
    
    async def set_processed_parts(self, parts: List):
        """Thread-safe artifact replacement"""
        async with self._state_lock:
            self._latest_processed_parts = parts
```

---

### 2. ✅ a2a_memory_service Concurrent Safety

**Current State:**
- Uses Azure Cognitive Search `SearchClient`
- Azure SDK clients are designed to be thread-safe
- Each request is independent (no shared state modifications)

**Verdict:** ✅ SAFE
- Memory service can handle concurrent reads/writes
- Azure manages concurrency internally
- No additional fixes needed

---

### 3. ✅ DummyToolContext for Parallel Usage

**Current State:**
- Each `send_message()` call creates a NEW `DummyToolContext` instance
- Each context has its own `_artifacts` dict (isolated)
- All contexts share the same `session_context` reference

**Verdict:** ⚠️ MOSTLY SAFE
- Each parallel task gets its own context instance ✅
- But they all modify shared `session_context` ⚠️
- **Depends on fix #1 (SessionContext locking)**

---

### 4. ✅ Partial Failure Policy Decision

**Question:** If 3 parallel tasks run and 1 fails, what should happen?

**Options:**

**A) fail_fast** - Abort all on first failure
```python
results = await asyncio.gather(*tasks, return_exceptions=False)
# Any exception cancels all tasks
```

**B) best_effort** - Continue with successes ✅ RECOMMENDED
```python
results = await asyncio.gather(*tasks, return_exceptions=True)
if success_rate >= 0.5:  # At least 50% succeeded
    continue_workflow()
```

**C) require_all** - Fail workflow if any task fails
```python
if any(isinstance(r, Exception) for r in results):
    mark_workflow_as_failed()
```

**Decision:** **best_effort** with configurable threshold
- Most flexible for real-world scenarios
- Failed tasks logged but don't block workflow
- User can see partial results
- Threshold: 50% success rate minimum (configurable)

---

## 📋 Required Changes Before Implementation

### Priority 1: Must Fix (Blocking)

#### 1.1 Add SessionContext Thread Safety
**File:** `backend/hosts/multiagent/foundry_agent_a2a.py`
**Location:** Line ~155 (SessionContext class)

```python
class SessionContext(BaseModel):
    """Session state management for A2A protocol conversations."""
    contextId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: Optional[str] = None
    message_id: Optional[str] = None
    task_state: Optional[str] = None
    session_active: bool = True
    retry_count: int = 0
    agent_mode: bool = False
    enable_inter_agent_memory: bool = True
    agent_task_ids: dict[str, str] = Field(default_factory=dict)
    agent_task_states: dict[str, str] = Field(default_factory=dict)
    agent_cooldowns: dict[str, float] = Field(default_factory=dict)
    last_host_turn_text: Optional[str] = Field(default=None)
    last_host_turn_agent: Optional[str] = Field(default=None)
    host_turn_history: List[Dict[str, str]] = Field(default_factory=list)
    
    # NEW: Add lock for thread-safe operations
    _state_lock: asyncio.Lock = Field(default_factory=asyncio.Lock, exclude=True, repr=False)
    
    # NEW: Thread-safe methods
    async def add_processed_part(self, part):
        """Thread-safe artifact addition"""
        async with self._state_lock:
            if not hasattr(self, '_latest_processed_parts'):
                self._latest_processed_parts = []
            self._latest_processed_parts.append(part)
    
    async def get_processed_parts(self) -> List:
        """Thread-safe artifact retrieval"""
        async with self._state_lock:
            if not hasattr(self, '_latest_processed_parts'):
                return []
            return list(self._latest_processed_parts)  # Return copy
    
    async def set_processed_parts(self, parts: List):
        """Thread-safe artifact replacement"""
        async with self._state_lock:
            self._latest_processed_parts = parts
```

#### 1.2 Update Artifact Collection to Use Locks
**File:** `backend/hosts/multiagent/foundry_agent_a2a.py`
**Location:** Line ~1584, ~3225, ~4713 (all places modifying `_latest_processed_parts`)

**Current:**
```python
if not hasattr(session_context, '_latest_processed_parts'):
    session_context._latest_processed_parts = []
session_context._latest_processed_parts.append(part)
```

**Updated:**
```python
await session_context.add_processed_part(part)
```

#### 1.3 Add Configuration Constants
**File:** `backend/hosts/multiagent/foundry_agent_a2a.py`
**Location:** Top of file, after imports (~line 80)

```python
# Parallel execution configuration
MAX_PARALLEL_TASKS = int(os.environ.get("MAX_PARALLEL_TASKS", "10"))
PARALLEL_TASK_TIMEOUT = int(os.environ.get("PARALLEL_TASK_TIMEOUT", "300"))  # 5 minutes
PARALLEL_MIN_SUCCESS_RATE = float(os.environ.get("PARALLEL_MIN_SUCCESS_RATE", "0.5"))  # 50%

log_info(f"⚙️ Parallel execution config: MAX={MAX_PARALLEL_TASKS}, TIMEOUT={PARALLEL_TASK_TIMEOUT}s, MIN_SUCCESS={PARALLEL_MIN_SUCCESS_RATE}")
```

---

### Priority 2: Should Fix (Important)

#### 2.1 Add Timeout Handling
Prevent hanging parallel tasks from blocking workflow

```python
async def execute_task_with_timeout(task, timeout=PARALLEL_TASK_TIMEOUT):
    try:
        return await asyncio.wait_for(
            execute_single_task(task), 
            timeout=timeout
        )
    except asyncio.TimeoutError:
        log_error(f"⏱️ Task timed out after {timeout}s: {task.task_description[:50]}")
        return (task, None, f"Task timed out after {timeout}s")
```

#### 2.2 Add Batching for Large Parallel Groups
Prevent resource exhaustion from too many concurrent requests

```python
if len(new_tasks) > MAX_PARALLEL_TASKS:
    log_warning(f"⚠️ {len(new_tasks)} tasks exceed limit, batching...")
    all_results = []
    for i in range(0, len(new_tasks), MAX_PARALLEL_TASKS):
        batch = new_tasks[i:i+MAX_PARALLEL_TASKS]
        batch_results = await asyncio.gather(*[execute_task(t) for t in batch])
        all_results.extend(batch_results)
    results = all_results
else:
    results = await asyncio.gather(*[execute_task(t) for t in new_tasks])
```

---

### Priority 3: Nice to Have (Enhancement)

#### 3.1 Add Parallel Execution Tracking for UI
```python
parallel_group_id = str(uuid.uuid4())
for task in new_tasks:
    await self._emit_granular_agent_event(
        agent_name=task.recommended_agent,
        status_text=f"Starting parallel task",
        extra_data={
            "parallel_group_id": parallel_group_id,
            "group_size": len(new_tasks)
        }
    )
```

---

## ✅ Implementation Readiness

### Ready to Proceed: YES, with fixes

**Before starting implementation:**
1. ✅ Apply Priority 1 fixes (SessionContext locking + config)
2. ✅ Apply Priority 2 fixes (timeout + batching)
3. ⚠️ Priority 3 is optional (can add later)

**Estimated time to apply fixes:** 30 minutes

---

## 📊 Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Race conditions on shared state | 🔴 HIGH | Add asyncio locks (Priority 1.1) |
| Task timeouts blocking workflow | 🟡 MEDIUM | Add timeout wrapper (Priority 2.1) |
| Resource exhaustion (too many parallel) | 🟡 MEDIUM | Add batching (Priority 2.2) |
| Partial failures breaking workflow | 🟢 LOW | Use best_effort policy |
| Memory service concurrency | 🟢 LOW | Already safe (Azure SDK) |

---

## 🎯 Next Steps

1. **Apply Priority 1 & 2 fixes** (30 min)
2. **Run tests** to verify thread safety (15 min)
3. **Proceed with main implementation** (2.5 hours)

**Total estimated time:** ~3.25 hours

---

## 📝 Notes

- Azure Cognitive Search SDK is thread-safe ✅
- Each `DummyToolContext` instance is isolated ✅
- Main concern is shared `SessionContext` state (fixed with locks)
- Recommend `best_effort` policy for production flexibility
- Configuration via environment variables for easy tuning

