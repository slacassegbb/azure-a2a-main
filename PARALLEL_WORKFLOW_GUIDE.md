# 🔀 Parallel Workflow Designer Guide

## How to Create Parallel Workflows in the Visual Designer

### ✅ What Was Fixed

The visual workflow designer previously had constraints that prevented **fan-out** connections (one step connecting to multiple steps). This has been fixed - you can now create parallel workflows directly in the UI.

---

## 📝 Step-by-Step: Creating a Parallel Workflow

### 1. **Add Your Agents to the Canvas**
   - Drag agents from the Agent Catalog onto the workflow canvas
   - Position them where you want them

### 2. **Select an Agent to Show the Connection Handle**
   - Click on any agent step to select it
   - You'll see a **glowing arrow button** appear on the right side of the agent hexagon
   - This is the **connection handle**

### 3. **Create the First Connection**
   - Click and hold the **arrow button** (connection handle)
   - Drag to another agent and release to create a connection
   - **Previously**: The arrow button would disappear after one connection (sequential workflow)
   - **Now**: The arrow button stays visible, allowing you to create more connections

### 4. **Create Additional Parallel Connections**
   - **Select the same agent again** (click on it)
   - The arrow button will appear again
   - Click and drag to create a second (or third, fourth, etc.) connection
   - This creates **parallel branches** (fan-out)

### 5. **Verify Parallel Text Notation**
   - Click "Generate Text Workflow" or "View Workflow Text"
   - You should see parallel steps labeled with letters:
     ```
     1. First Agent
     2a. Second Agent (runs in parallel)
     2b. Third Agent (runs in parallel)
     2c. Fourth Agent (runs in parallel)
     3. Fifth Agent (continues after all parallel tasks complete)
     ```

---

## 🎯 Visual Example

```
         ┌─────────────┐
         │  Step 1     │
         │  Claims     │
         └──────┬──────┘
                │
                ├──────────┐
                │          │
                ▼          ▼
         ┌─────────┐  ┌─────────┐
         │ Step 2a │  │ Step 2b │
         │  Fraud  │  │  Legal  │
         └────┬────┘  └────┬────┘
              │            │
              └──────┬─────┘
                     ▼
              ┌─────────────┐
              │   Step 3    │
              │   Reporter  │
              └─────────────┘
```

**Generated Text Workflow:**
```
1. Analyze the insurance claim for coverage and validity (Claims Agent)
2a. Check for fraud indicators and red flags (Fraud Agent)
2b. Review legal compliance and policy terms (Legal Agent)
3. Generate comprehensive claim report with recommendations (Reporter Agent)
```

---

## 🔧 Technical Details

### What Happens Behind the Scenes

1. **Visual Designer**: Allows multiple outgoing connections from one step (fan-out)
2. **Text Generation**: BFS algorithm detects fan-out and generates `2a`, `2b`, `2c` notation
3. **Host Agent**: LLM orchestrator sees workflow text with parallel notation
4. **NextStep Response**: LLM returns `next_tasks: [{...}, {...}]` with `parallel: true`
5. **Execution**: Backend uses `asyncio.gather()` to run tasks concurrently

### Key Implementation Files

- **Frontend**: `frontend/components/visual-workflow-designer.tsx`
  - Removed `hasOutgoingConnection` constraint (line ~2131)
  - Connection handle now always visible when agent is selected
  
- **Backend**: `backend/hosts/multiagent/foundry_agent_a2a.py`
  - `NextStep` model supports `next_tasks` list and `parallel` flag
  - Orchestration loop handles parallel execution with `asyncio.gather()`

---

## 🐛 Troubleshooting

### "I don't see the arrow button"
- **Make sure you've selected the agent** (click on it) - the arrow only appears on selected agents
- The arrow appears on the **right side** of the hexagon with a glowing animation

### "The arrow button disappears after one connection"
- This was the bug - it's now fixed
- Make sure you're running the latest version from the `feature/parallel-workflows` branch
- Try refreshing the frontend (`npm run dev`)

### "My parallel workflow shows as sequential (1, 2, 3 instead of 1, 2a, 2b, 3)"
- Check that you've created connections from **the same step** to **multiple different steps**
- The text generation uses BFS to detect when a step has multiple children (outgoing connections)

### "Tasks aren't running in parallel"
- Check the backend logs for `DEBUG: Parallel execution detected`
- Verify the LLM is returning `parallel: true` in the NextStep response
- Ensure you're in "workflow mode" (workflow text must be present)

---

## ✨ Tips for Parallel Workflows

1. **Use parallel execution for independent tasks**
   - Example: Fraud check + Legal review can run simultaneously
   
2. **Add a convergence step after parallel branches**
   - Example: Reporter agent that summarizes all parallel results
   
3. **Parallel tasks should not depend on each other's output**
   - Each parallel branch should have all the context it needs
   
4. **Test with logging enabled**
   - Check backend logs to verify `asyncio.gather()` is executing
   - Look for concurrent API calls to remote agents

---

## 🚀 Ready to Test!

1. Start your backend: `cd backend && python backend_production.py`
2. Start your frontend: `cd frontend && npm run dev`
3. Open the visual workflow designer
4. Try creating a parallel workflow following the steps above
5. Check the generated text workflow for `2a`, `2b` notation
6. Run the workflow and watch the backend logs for parallel execution

**Happy parallel orchestrating!** 🎉
