# Dead Code Removal Report

## Summary

| Category | Files | Verdict |
|----------|-------|---------|
| Frontend — unused UI components | 26 | CANDIDATE FOR REMOVAL |
| Frontend — unused hooks | 5 | CANDIDATE FOR REMOVAL |
| Frontend — unused lib files | 4 | CANDIDATE FOR REMOVAL |
| Frontend — unused custom components | 2 | CANDIDATE FOR REMOVAL |
| Frontend — dead exports in used files | 2 files | CLEAN UP |
| Frontend — unused imports | 2 files | CLEAN UP |
| Backend — dead endpoints | ~15 | CANDIDATE FOR REMOVAL |
| Backend — unused modules | 3 | CANDIDATE FOR REMOVAL |
| Backend — debug scripts (not in CI) | 9 | CANDIDATE FOR REMOVAL |
| Backend — orphaned test files | 13 | CANDIDATE FOR REMOVAL |
| Root — dead Python scripts | 7 | CANDIDATE FOR REMOVAL |
| Root — dead shell/PS1 scripts | 9 | CANDIDATE FOR REMOVAL |
| Root — stale markdown docs | 28 | CANDIDATE FOR REMOVAL |
| Root — dead misc files | 6 | CANDIDATE FOR REMOVAL |
| Root — dead scripts/ directory files | 10 | CANDIDATE FOR REMOVAL |
| Root — `frontend_light/` directory | entire dir | **KEEP** — actively used |
| **Total** | **~140+ files** | |

---

## 1. FRONTEND — Unused shadcn/ui Components (26 files, CANDIDATE FOR REMOVAL)

These were installed but never imported by any application code:

| File | Verified by |
|------|------------|
| `components/ui/alert.tsx` | 0 imports |
| `components/ui/alert-dialog.tsx` | 0 imports |
| `components/ui/aspect-ratio.tsx` | 0 imports |
| `components/ui/breadcrumb.tsx` | 0 imports |
| `components/ui/carousel.tsx` | 0 imports |
| `components/ui/chart.tsx` | 0 imports |
| `components/ui/command.tsx` | 0 imports |
| `components/ui/context-menu.tsx` | 0 imports |
| `components/ui/drawer.tsx` | 0 imports |
| `components/ui/form.tsx` | 0 imports |
| `components/ui/hover-card.tsx` | 0 imports |
| `components/ui/input-otp.tsx` | 0 imports |
| `components/ui/menubar.tsx` | 0 imports |
| `components/ui/navigation-menu.tsx` | 0 imports |
| `components/ui/pagination.tsx` | 0 imports |
| `components/ui/popover.tsx` | 0 imports |
| `components/ui/progress.tsx` | 0 imports |
| `components/ui/radio-group.tsx` | only by other dead UI files |
| `components/ui/resizable.tsx` | 0 imports |
| `components/ui/separator.tsx` | 0 imports |
| `components/ui/skeleton.tsx` | 0 imports |
| `components/ui/slider.tsx` | 0 imports |
| `components/ui/sonner.tsx` | not in layout or pages |
| `components/ui/table.tsx` | 0 imports |
| `components/ui/tabs.tsx` | 0 imports |
| `components/ui/toast.tsx` | only by unused toaster.tsx |
| `components/ui/toaster.tsx` | not in layout or pages |
| `components/ui/toggle.tsx` | only by unused toggle-group |
| `components/ui/toggle-group.tsx` | 0 imports |

---

## 2. FRONTEND — Unused Hooks (5 files, CANDIDATE FOR REMOVAL)

| File | Notes |
|------|-------|
| `components/ui/use-toast.ts` | DUPLICATE of `hooks/use-toast.ts`, never imported |
| `hooks/use-event-hub-new.ts` | Empty file (0 bytes) |
| `hooks/use-event-hub-local.ts` | Empty file (0 bytes) |
| `hooks/use-event-hub-websocket.ts` | Empty file (0 bytes) |
| `hooks/use-voice-live.ts` | 38KB, fully implemented but never imported |

---

## 3. FRONTEND — Unused Lib Files (4 files, CANDIDATE FOR REMOVAL)

| File | Notes |
|------|-------|
| `lib/local-websocket-client.ts` | 0 imports |
| `lib/debug.ts` | 0 imports |
| `lib/voice-scenarios.ts` | Only imported by dead `use-voice-live.ts` |
| `lib/websocket-server.js` | 0 imports |

---

## 4. FRONTEND — Unused Custom Components (2 files, CANDIDATE FOR REMOVAL)

| File | Notes |
|------|-------|
| `components/run-logs-modal.tsx` | Exports `RunLogsModal`, never imported |
| `components/session-debug.tsx` | Exports `SessionDebug`, never imported |

---

## 5. FRONTEND — Dead Exports in Used Files (CLEAN UP)

### `lib/workflow-api.ts` — 5 unused interfaces + 2 unused functions

- **Unused interfaces:** `WorkflowStep`, `WorkflowConnection`, `Workflow`, `WorkflowCreateRequest`, `WorkflowUpdateRequest`
- **Unused functions:** `getAllWorkflows()`, `getWorkflow()`
- **Used functions:** `getUserWorkflows()`, `createWorkflow()`, `updateWorkflow()`, `deleteWorkflow()`, `isAuthenticated()`

### `lib/a2a-event-types.ts` — Nearly entirely dead

- 15+ unused event data interfaces (`MessageEventData`, `SystemEventData`, etc.)
- 10 unused type guard functions (`isMessageEvent()`, `isTaskEvent()`, etc.)
- Unused constants: `A2A_EVENT_TYPES`, `A2AEventType`
- Unused function: `parseA2AEvent()`
- **Only `A2AEventEnvelope` is actually used** (imported in websocket-client.ts)

---

## 6. FRONTEND — Unused Imports (CLEAN UP)

| File | Import | Notes |
|------|--------|-------|
| `components/chat-panel.tsx` | `AvatarImage` | Imported but never used in JSX |
| `components/visual-workflow-designer.tsx` | `X as CloseIcon` | `CloseIcon` never used (`X` imported twice) |

---

## 7. FRONTEND — Commented-Out Code (CLEAN UP)

- `chat-panel.tsx` lines ~1543-1558: 15-line commented-out markdown URL regex block. Comment says "Disable markdown URL extraction". Safe to delete.

---

## 8. BACKEND — Dead API Endpoints (CANDIDATE FOR REMOVAL)

### In `backend_production.py`:

| Endpoint | Line | Reason |
|----------|------|--------|
| `GET /api/agents/search` | ~791 | No frontend callers |
| `GET /api/auth/me` | ~1022 | No frontend callers |
| `GET /api/auth/users` (duplicate) | ~1030 | Shadows identical route at line ~909 |
| `GET /api/workflows/list` | ~1174 | Duplicates `/api/workflows/all` which IS used |
| `POST /api/workflows/run` | ~1206 | No callers + BUG: references undefined `sorted_steps` |
| `GET /api/schedules/debug` | ~1950 | Debug endpoint, no frontend usage |
| `POST /start-agent` | ~2249 | Hardcodes agents, violates dynamic agent principle, no callers |

### In `server.py`:

| Endpoint | Reason |
|----------|--------|
| `POST /workflow/cancel` | No frontend callers |
| `POST /workflow/interrupt` | No frontend callers |
| `GET /events/get` | No frontend callers |
| `POST /task/list` | No frontend callers |
| `POST /message/pending` | No frontend callers |
| `POST /api_key/update` | No frontend callers |
| `GET /agents/catalog` | Frontend uses `/agents/session` instead |

---

## 9. BACKEND — Unused Modules (3 files, CANDIDATE FOR REMOVAL)

| File | Notes |
|------|-------|
| `hosts/multiagent/workflow_parser.py` | Zero imports in entire backend |
| `data/merge_agent_registries.py` | One-time migration script, zero imports |
| `hosts/multiagent/websocket_streamer.py` | Dead duplicate of `service/websocket_streamer.py` |

---

## 10. BACKEND — Debug Scripts Not in CI (9 files, CANDIDATE FOR REMOVAL)

| File |
|------|
| `backend/check_agent_urls.py` |
| `backend/check_all_memory.py` |
| `backend/check_azure_memory.py` |
| `backend/check_doc.py` |
| `backend/check_memory_index.py` |
| `backend/check_memory_size.py` |
| `backend/inspect_invoice_docs.py` |
| `backend/list_session_files.py` |
| `backend/update_test77_workflow.py` |

---

## 11. BACKEND — Orphaned Test Files (13 files, CANDIDATE FOR REMOVAL)

These sit in `backend/` root (not `tests/`), not in CI, not in Makefile:

| File |
|------|
| `backend/test_agent_registry_database.py` |
| `backend/test_azure_agents.py` |
| `backend/test_azure_scheduled_workflow.py` |
| `backend/test_hitl_clean.py` |
| `backend/test_hitl_full_workflow.py` |
| `backend/test_hitl_full.py` |
| `backend/test_hitl_scenarios.py` |
| `backend/test_schedule_via_api.py` |
| `backend/test_scheduled_workflow_execution.py` |
| `backend/test_teams_hitl_simple.py` |
| `backend/test_unified_registry.py` |
| `backend/test_workflow_database.py` |
| `backend/service/server/test_image.py` (1.4MB base64 blob, only used by `in_memory_manager.py`) |

---

## 12. ROOT — Dead Python Scripts (7 files, CANDIDATE FOR REMOVAL)

- `analyze_coverage.py`
- `comprehensive_test_suite.py`
- `run_coverage.py`
- `test_coverage_foundry.py`
- `test_quickbooks_mcp.py`
- `test_stripe_mcp.py`
- `validate_test_environment.py`

---

## 13. ROOT — Dead Shell/PowerShell Scripts (9 files, CANDIDATE FOR REMOVAL)

- `deploy-azure.sh`
- `deploy-frontend-light.sh`
- `quick_coverage.sh`
- `run_all_tests.sh`
- `run_coverage_session.sh`
- `setup-github-cicd.sh`
- `deploy-aca-managed-identity.ps1`
- `deploy-azure.ps1`
- `deploy-remote-agent.ps1`

**KEEP:** `deploy-remote-agent.sh` (actively used for manual agent deployment)

---

## 14. ROOT — Stale Markdown Docs (28 files, CANDIDATE FOR REMOVAL)

All are one-time status/completion docs from past features. None referenced by live code:

- `AGENT_REGISTRY_MIGRATION_COMPLETE.md`
- `BING_GROUNDING_SDK_ISSUE.md`
- `CI-CD-GUIDE.md`
- `CONTEXT_BLOAT_FIX.md`
- `COVERAGE_LIMITATIONS.md`
- `COVERAGE_READY.md`
- `COVERAGE_TESTING_GUIDE.md`
- `COVERAGE_TESTING.md`
- `CUSTOM_MCP_CLIENT_IMPLEMENTATION.md`
- `DATABASE_MIGRATION_COMPLETE.md`
- `DEPLOYMENT.md`
- `FIXES-APPLIED.md`
- `IMAGE_DISPLAY_FIX_EXPLANATION.md`
- `IMAGE_GENERATOR_DEPLOYMENT_FIX.md`
- `IMPLEMENTATION_SUMMARY.md`
- `MEMORY_TOGGLE_UPDATE.md`
- `NEW_SDK_MIGRATION.md`
- `PARALLEL_WORKFLOW_GUIDE.md`
- `PRE_IMPLEMENTATION_REVIEW.md`
- `RATE_LIMIT_FIX.md`
- `RESPONSES_API_MIGRATION_PLAN.md`
- `RESPONSES_API_PROGRESS.md`
- `SCHEDULED_WORKFLOWS_COLD_START_FIX.md`
- `SCHEDULED_WORKFLOWS_SUMMARY.md`
- `TEAMS_AGENT_COMPLETE.md`
- `VISUAL_WORKFLOW_DESIGNER.md`
- `VISUAL_WORKFLOW_UI_GUIDE.md`
- `documentation.md`
- `quick_documentation_setup.md`

---

## 15. ROOT — Other Dead Files (6 files, CANDIDATE FOR REMOVAL)

- `test-workflow.js`
- `.coverage`
- `.coveragerc`
- `a2a_logo.png` (duplicate — frontend uses its own in `public/`)
- `a2a_transparent.png` (duplicate — frontend uses its own in `public/`)

---

## 16. ROOT — Dead scripts/ Directory Files (10 files, CANDIDATE FOR REMOVAL)

- `scripts/start_backend.sh` (Makefile uses `.py` version)
- `scripts/setup-github-secrets.sh`
- `scripts/setup-storage-permissions.sh`
- `scripts/setup-storage-permissions.ps1`
- `scripts/deploy-sora2.sh`
- `scripts/apply_parallel_fixes.py`
- `scripts/start_all_agents.ps1`
- `scripts/start_backend.ps1`
- `scripts/start_frontend.ps1`
- `scripts/__init__.py`

**KEEP:** `scripts/start_backend.py`, `scripts/start_frontend.sh`, `scripts/start_devtunnel_host.sh`, `scripts/start_remote_agents.sh`

---

## 17. `frontend_light/` Directory — KEEP

**Actively used by the developer.** Not referenced in CI/CD or other code, but used manually. Not a removal candidate.

---

## BUG FOUND

`POST /api/workflows/run` in `backend_production.py` (~line 1300) references `sorted_steps` which is **never defined** in that scope. Should be `workflow.steps`. This endpoint is broken regardless and has no callers.

---

## Recommended Removal Order

1. Delete root-level dead files first (scripts, markdown, coverage artifacts) — zero risk
2. Delete `frontend_light/` directory
3. Delete unused frontend UI components, hooks, and lib files
4. Delete unused frontend custom components
5. Clean up dead exports in `workflow-api.ts` and `a2a-event-types.ts`
6. Remove unused imports in `chat-panel.tsx` and `visual-workflow-designer.tsx`
7. Delete backend debug scripts and orphaned test files
8. Delete unused backend modules
9. Remove dead backend endpoints
10. Delete dead `scripts/` directory files
