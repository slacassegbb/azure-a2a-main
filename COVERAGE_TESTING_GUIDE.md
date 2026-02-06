# Coverage Testing Guide

This guide explains how to measure code coverage for `foundry_agent_a2a.py` and the entire backend.

## Quick Start

**The test user is already registered!** From the previous run, a test user was created:
- Email: `test@example.com`  
- Password: `password123`

### Method 1: Run Everything (Automated)

```bash
# Terminal 1: Start backend with coverage
cd backend
source .venv/bin/activate
coverage run --source=hosts/multiagent backend_production.py
```

```bash
# Terminal 2: Run automated tests
cd backend
source .venv/bin/activate
python3 ../comprehensive_test_suite.py --verbose
```

Then manually test through the UI at http://localhost:3000

When done, stop backend (Ctrl+C) and run:
```bash
coverage report          # View summary
coverage html            # Generate HTML report  
open htmlcov/index.html  # View detailed report
```

### Method 2: Validate First

Check which tests will work before running:

```bash
cd backend
source .venv/bin/activate
python3 ../validate_test_environment.py
```

This shows:
- ✅ Backend status
- ✅ WebSocket status  
- ✅ Which agents are online
- ✅ Which test scenarios will work

## What Gets Tested

### 1. Automated Tests (`comprehensive_test_suite.py`)

**API Tests:**
- ✅ Health check endpoint
- ✅ Agent registry listing

**Single Agent Tests:**
- Query routing to Classification agent
- Simple agent interactions

**Parallel Workflow Tests:**
- Multiple agents working simultaneously
- Concurrent execution paths

**Sequential Workflow Tests:**
- Multi-step agent workflows
- Context passing between agents

**Chat Mode Tests:**
- Direct LLM queries (no agent routing)
- WebSocket streaming

**Memory Tests:**
- Context persistence across queries
- Memory recall functionality

### 2. Manual UI Testing

After running automated tests, test through the frontend:

1. **Login**: Use test@example.com / password123
2. **Single Agent**: Run a classification query
3. **Workflow**: Execute a saved workflow  
4. **Chat**: Send messages in chat mode
5. **Memory**: Test context recall

## Understanding the Coverage Report

The `htmlcov/index.html` report shows:

- **Green lines**: Code that was executed ✅
- **Red lines**: Code never reached ❌
- **Yellow lines**: Partial branch coverage (e.g., only `if`, not `else`)

### Key Files to Check

1. **`hosts/multiagent/foundry_agent_a2a.py`** - Main orchestration file
   - Look for unused error handlers
   - Check workflow routing logic
   - Verify agent communication paths

2. **Coverage %** - Higher is better
   - 70-80%: Good coverage
   - 80-90%: Great coverage
   - 90%+: Excellent coverage

3. **Missing Lines** - Red lines indicate:
   - Dead code that could be removed
   - Error paths never tested
   - Features not being used

## Test Scenarios Explained

### ✅ What Works

With 14 Azure agents online, all test scenarios should work:
- API tests (basic connectivity)
- Single agent tests (one agent at a time)
- Parallel workflows (multiple agents simultaneously)
- Sequential workflows (agents in sequence)
- Chat mode (direct LLM queries)
- Memory tests (context persistence)

### ⏭️ Skipped Tests

Tests are skipped if:
- No authentication token (login failed)
- No agents are online
- WebSocket server not running

Check `validate_test_environment.py` output to see why.

## Files Created

1. **`comprehensive_test_suite.py`** - Main test suite
   - Combines all backend tests
   - Tests API, agents, workflows, chat, memory
   - Automatically registers test user if needed

2. **`validate_test_environment.py`** - Pre-flight checks
   - Validates backend is running
   - Checks agent availability
   - Predicts which tests will work

3. **`.coveragerc`** - Coverage configuration
   - Tracks `hosts/multiagent` directory
   - Enables branch coverage
   - Omits test files from report

4. **`COVERAGE_TESTING.md`** - Detailed documentation

## Troubleshooting

### "403 Forbidden" errors
- **Cause**: No authentication token
- **Fix**: Test user should auto-register, check logs

### "Connection refused" errors
- **Cause**: Backend not running
- **Fix**: Start backend with `coverage run` command

### "Agents offline" warnings
- **Cause**: Azure Container Apps scaled to zero
- **Fix**: Wait 30-60s for cold start, agents will wake up

### Low coverage %
- **Cause**: Not enough testing
- **Fix**: 
  1. Run more automated tests
  2. Test more UI features manually
  3. Try different workflows
  4. Test error scenarios

## Advanced Usage

### Quick Mode (Skip Long Tests)

```bash
python3 ../comprehensive_test_suite.py --quick
```

Skips tests that take >30 seconds.

### Combine Multiple Test Runs

Coverage accumulates across runs:

```bash
# Run 1: Automated tests
coverage run --source=hosts/multiagent backend_production.py
# ... run automated tests ...
# Ctrl+C

# Run 2: Manual testing (appends to .coverage)
coverage run --source=hosts/multiagent backend_production.py
# ... use UI manually ...
# Ctrl+C

# View combined report
coverage report
coverage html
```

### Focus on Specific File

```bash
coverage report --include="**/foundry_agent_a2a.py"
```

### See Uncovered Lines

```bash
coverage report -m
```

Shows line numbers for missing coverage.

## Next Steps

After reviewing the coverage report:

1. **Identify Dead Code**
   - Red lines that are never executed
   - Consider removing if truly unused

2. **Add Tests for Low Coverage Areas**
   - Focus on red sections
   - Add specific tests in `comprehensive_test_suite.py`

3. **Test Error Paths**
   - Many red lines are error handlers
   - Intentionally trigger errors to test them

4. **Document Findings**
   - Note which features are well-tested
   - Identify areas needing more coverage

## Support

If you encounter issues:

1. Check `validate_test_environment.py` output
2. Review backend logs for errors
3. Ensure all services are running:
   - Backend on port 12000
   - WebSocket on port 8080  
   - Frontend on port 3000
4. Verify Azure agents are awake (check startup logs)

Happy testing! 🚀
