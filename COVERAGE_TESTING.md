# Backend Code Coverage Testing

This directory contains tools for measuring code coverage of `foundry_agent_a2a.py` and related backend modules.

## Quick Start

### Step 1: Start Backend with Coverage Tracking

```bash
cd backend
coverage run --source=hosts/multiagent backend_production.py
```

### Step 2: Run Comprehensive Test Suite (in another terminal)

```bash
cd /Users/simonlacasse/Downloads/sl-a2a-main2
python comprehensive_test_suite.py --verbose
```

### Step 3: Stop Backend and Generate Coverage Report

Stop the backend (Ctrl+C), then:

```bash
coverage report
coverage html
open htmlcov/index.html
```

## Test Suite Options

- `--verbose` or `-v`: Show detailed output
- `--quick` or `-q`: Skip long-running tests (faster)

## What Gets Tested

### ✅ API Tests
- Health check endpoint
- Agent registry

### ✅ Single Agent Tests  
- Simple agent queries
- Classification workflows

### ✅ Parallel Workflows
- Multiple agents running simultaneously
- Concurrent execution patterns

### ✅ Sequential Workflows
- Step-by-step agent execution
- Context passing between agents

### ✅ Chat Mode
- Direct LLM queries (no agent routing)

### ✅ Memory Tests
- Context storage and recall

## Alternative: Run Individual Test Files

The original test files are still available in `backend/tests/`:

```bash
python backend/tests/test_workflow_execution.py
python backend/tests/test_multiagent_flows.py
python backend/tests/test_workflow_parallel_execution.py
```

## Coverage Configuration

Coverage settings are in `.coveragerc`:
- Tracks: `backend/hosts/multiagent/`
- Branch coverage: Enabled
- HTML report: `htmlcov/index.html`

## Troubleshooting

**Backend not responding:**
- Check if backend is running: `curl http://localhost:12000/health`
- Check if WebSocket server is running on port 8080

**Tests timing out:**
- Increase timeout values in comprehensive_test_suite.py
- Use `--quick` mode to skip long tests

**No coverage data:**
- Make sure backend was started with `coverage run`
- Don't use `python backend_production.py` directly
