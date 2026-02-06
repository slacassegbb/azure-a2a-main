# 📊 Code Coverage Testing - Complete Setup

## ✅ Status: READY TO RUN

All infrastructure is in place for comprehensive code coverage testing of your backend, specifically `foundry_agent_a2a.py`.

## 🎯 What You Can Test

### Backend Integration (All Working!)
- ✅ **14 Azure Agents Online** (Branding, Classification, QuickBooks, Stripe, HubSpot, Video, etc.)
- ✅ **Backend API** responding on localhost:12000
- ✅ **WebSocket Server** connected on localhost:8080
- ✅ **Frontend UI** available on localhost:3000
- ✅ **Test User Registered** (test@example.com / password123)
- ✅ **2 Workflows** available in database

### Test Coverage Areas
1. **API Endpoints** - REST API calls
2. **Single Agent** - One agent queries
3. **Parallel Workflows** - Multiple agents simultaneously
4. **Sequential Workflows** - Multi-step agent chains
5. **Chat Mode** - Direct LLM interactions
6. **Memory System** - Context persistence

## 🚀 Quick Start (3 Steps)

### Terminal 1: Start Backend with Coverage
```bash
cd backend
source .venv/bin/activate
coverage run --source=hosts/multiagent backend_production.py
```
**Keep this running! Don't close this terminal.**

### Terminal 2: Run Automated Tests
```bash
cd backend  
source .venv/bin/activate
python3 ../comprehensive_test_suite.py --verbose
```

### Browser: Manual UI Testing
1. Open http://localhost:3000
2. Login: test@example.com / password123
3. Try workflows, chat, agents
4. Test different features

### Terminal 1 Again: Generate Reports
Press **Ctrl+C** to stop backend, then:
```bash
coverage report           # View summary
coverage html             # Generate HTML
open htmlcov/index.html  # Open in browser
```

## 📁 Files Created

| File | Purpose |
|------|---------|
| `comprehensive_test_suite.py` | Main test suite (7 test scenarios) |
| `validate_test_environment.py` | Pre-flight checks |
| `.coveragerc` | Coverage configuration |
| `COVERAGE_TESTING_GUIDE.md` | Detailed documentation |
| `run_coverage_session.sh` | Automated helper script |

## 🔍 Pre-Flight Check

Before running, validate everything is ready:

```bash
cd backend
source .venv/bin/activate
python3 ../validate_test_environment.py
```

This shows:
- ✅ Backend status
- ✅ Agent availability (should show 14 online)
- ✅ WebSocket connectivity
- ✅ Workflow database
- ✅ Which test scenarios will work

**Expected output**: "All test scenarios should work!"

## 📊 What the Report Shows

The coverage report (`htmlcov/index.html`) highlights:

### Color Coding
- **🟢 Green** = Code was executed
- **🔴 Red** = Code never reached (dead code?)
- **🟡 Yellow** = Partial branch coverage

### Key Metrics
- **Coverage %** = Lines executed / Total lines
- **Missing Lines** = Specific line numbers not covered
- **Branch Coverage** = `if/else` path coverage

### Focus Areas
- `foundry_agent_a2a.py` - Your main orchestration file
- Look for red lines (unused code)
- Check error handlers (often untested)
- Identify dead code to remove

## 💡 Tips

### Get Higher Coverage
1. Run automated tests first
2. Then manually test UI features
3. Try different workflow types
4. Test error scenarios
5. Use multiple agents

### Common Issues

**"403 Forbidden"**
- Test user not authenticated
- Should auto-register on first run
- Check backend logs

**"Agents offline"**
- Azure Container Apps cold start
- Wait 30-60 seconds
- Backend wakes them automatically

**"Low coverage %"**
- Need more manual testing
- Try different UI features
- Test error paths
- Execute more workflows

## 🎯 Success Criteria

### Good Coverage Session:
- ✅ Automated tests all pass
- ✅ Manual UI testing done
- ✅ Coverage report generated
- ✅ Coverage % > 70%
- ✅ Key workflows tested

### Coverage Report Review:
- 🔍 Identify dead code (always red)
- 🔍 Find untested error handlers
- 🔍 Discover unused features
- 🔍 Validate critical paths are green

## 📚 Documentation

- **Full Guide**: `COVERAGE_TESTING_GUIDE.md`
- **Original Docs**: `COVERAGE_TESTING.md`
- **Quick Ref**: This file (README summary)

## 🏁 You're Ready!

Everything is configured and working. Just follow the **Quick Start** steps above.

**Test user is already registered** - no setup needed!

**14 agents are online** - full workflow testing available!

**All test categories work** - comprehensive coverage possible!

---

**Next Command**: 
```bash
cd backend && source .venv/bin/activate && coverage run --source=hosts/multiagent backend_production.py
```

🚀 Happy testing!
