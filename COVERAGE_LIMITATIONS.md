# Coverage Testing - Known Limitations

## `/api/query` Endpoint Requires UI Agent Enablement

### Issue
The comprehensive test suite shows that `/api/query` endpoint returns:
```
400 Bad Request: No agents enabled for this session. 
Please enable agents from the Agents tab first.
```

### Why This Happens
The `/api/query` endpoint is designed for use by the UI and requires agents to be pre-enabled in the session registry. This is done through the Agents tab in the frontend, not programmatically via API.

### Workaround for Coverage Testing

**Option 1: Manual UI Testing (Recommended)**
1. Start backend with coverage
2. Open UI at http://localhost:3000
3. Login with test@example.com / test123
4. **Go to Agents tab and enable agents**
5. Use chat/workflows normally
6. Stop backend and generate report

**Option 2: Use Workflow API Instead**
The `/api/workflows/run` endpoint automatically enables agents. Update tests to use this endpoint instead.

**Option 3: Enable Agents via WebSocket**
Connect to WebSocket and send agent enable messages (requires implementing WebSocket client in test suite).

### Current Test Coverage

With the automated test suite as-is:
- ✅ **API Tests Pass**: Health check, agent registry
- ⚠️  **Query Tests Skipped**: Require UI agent enablement
- ⚠️  **Workflow Tests Skipped**: Same requirement
- ⚠️  **Chat Tests Skipped**: Same requirement
- ⚠️  **Memory Tests Skipped**: Same requirement

### Recommended Approach

For best code coverage:
1. Run automated test suite (covers API endpoints)
2. **Manually test through UI** (covers agent queries, workflows, chat)
3. Generate combined coverage report

The manual UI testing is ESSENTIAL for meaningful coverage of `foundry_agent_a2a.py`.

### Future Improvement

Add a programmatic way to enable agents for test sessions, either:
- New API endpoint: `POST /api/sessions/{session_id}/agents/enable`
- WebSocket message: `{"type": "enable_agents", "agents": [...]}`
- Test-only bypass flag in `/api/query`

---

**For now**: The test suite validates that authentication works and API endpoints respond. Full coverage requires manual UI testing after enabling agents.
