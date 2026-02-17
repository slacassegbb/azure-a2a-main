"""
Test: Does the orchestrator LLM reliably follow IF-TRUE / IF-FALSE branches
after an evaluation step?

This test simulates the orchestration loop with a branching workflow,
feeding it fake task outputs where the evaluation result is known (true/false),
and checks whether the LLM proposes the correct branch.

Run:  python backend/tests/test_evaluation_branching.py
"""

import asyncio
import os
import sys
import json
from pathlib import Path

# Load .env from project root
from dotenv import load_dotenv
project_root = Path(__file__).resolve().parents[2]
load_dotenv(project_root / ".env")

# Add backend to path
backend_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_dir))

from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Literal


# --- Models (copied from hosts/multiagent/models.py) ---

GoalStatus = Literal["incomplete", "completed"]


class NextStep(BaseModel):
    goal_status: GoalStatus = Field(...)
    next_task: Optional[Dict[str, Optional[str]]] = Field(None)
    next_tasks: Optional[List[Dict[str, Optional[str]]]] = Field(None)
    parallel: bool = Field(False)
    reasoning: str = Field(...)


# --- The actual system prompt, same as workflow_orchestration.py builds ---

BASE_SYSTEM_PROMPT = """You are the Host Orchestrator in an A2A multi-agent system.

PRIMARY RESPONSIBILITIES:
- **FIRST**: Check if a MANDATORY WORKFLOW exists below - if it does, you MUST complete ALL workflow steps before marking goal as "completed"
- Evaluate whether the user's goal is achieved by analyzing all completed tasks and their outputs
- If incomplete, propose the next task(s) that move closer to the goal
- Select the most appropriate agent based on their specialized skills

DECISION-MAKING RULES:
- Analyze the ENTIRE plan history - don't ignore previous tasks or outputs
- Never repeat completed tasks unless explicitly retrying a failure
- Keep each task atomic and delegable to a single agent
- Match tasks to agents using their "skills" field for best results
- If no agent fits, set recommended_agent=null
- Mark goal_status="completed" ONLY when: (1) ALL MANDATORY WORKFLOW steps are completed (if workflow exists), AND (2) the objective is fully achieved

### 🛑 AGENT ASKS FOR MORE INFO - STOP AND COMPLETE
If an agent's response asks for more information:
- Mark goal_status="completed" and include the agent's question in your reasoning
- The user will see the agent's question and can provide the needed info

FAILURE HANDLING:
- Consider failed tasks in planning
- You can retry with modifications or try alternative agents/approaches

### 🎯 DELEGATION FIRST PRINCIPLE
- ALWAYS delegate to an appropriate agent
"""


def build_workflow_prompt(workflow_text: str) -> str:
    """Build the full system prompt with workflow injection, same as the real orchestrator."""
    workflow_section = f"""

### 🔥 MANDATORY WORKFLOW - FOLLOW ALL STEPS IN ORDER 🔥
**CRITICAL**: The following workflow steps are MANDATORY and must ALL be completed before marking the goal as "completed".
Do NOT skip steps. Do NOT mark goal as completed until ALL workflow steps are done.

{workflow_text.strip()}

**AGENT ROUTING**:
- Each step specifies the agent to use in [brackets] - e.g., "[QuickBooks Online Agent]"
- [EVALUATE] steps are special evaluation/decision steps handled by the host - not by a remote agent
- You MUST use the agent specified in brackets for that step

**EVALUATION & BRANCHING**:
- Steps marked [EVALUATE] are conditional decision points that return true or false
- After an [EVALUATE] step completes, its result (true/false) will be shown in the task output
- IF-TRUE → lines indicate the step to follow when evaluation is true
- IF-FALSE → lines indicate the step to follow when evaluation is false
- **CRITICAL**: Only follow the branch matching the evaluation result. NEVER execute the other branch.
- Steps in the skipped branch must NOT be executed at all

**EXECUTION RULES**:
- Execute sequential steps (1, 2, 3) one after another
- Only mark goal_status="completed" after ALL required workflow steps are finished
- Skipped branch steps do NOT count toward completion
"""
    return BASE_SYSTEM_PROMPT + workflow_section


def build_user_prompt(goal: str, agents: list, tasks_history: list) -> str:
    """Build the user prompt with plan history, same as the real orchestrator."""
    agents_text = "\n".join([f"- **{a['name']}**: {a['description']}" for a in agents])

    tasks_text = ""
    if tasks_history:
        for i, t in enumerate(tasks_history, 1):
            status_emoji = "✅" if t["state"] == "completed" else "❌"
            tasks_text += f"\n{status_emoji} Task {i}: {t['description']}"
            tasks_text += f"\n   Agent: {t['agent']}"
            tasks_text += f"\n   State: {t['state']}"
            if t.get("output"):
                tasks_text += f"\n   Output: {t['output'][:300]}"
    else:
        tasks_text = "(no tasks yet)"

    return f"""### GOAL
{goal}

### AVAILABLE AGENTS
{agents_text}

### EXECUTION PLAN (tasks so far)
{tasks_text}

### YOUR DECISION
Based on the completed tasks and the MANDATORY WORKFLOW, what is the next step?
If a branch was determined by an [EVALUATE] step, follow ONLY the correct branch."""


async def call_llm(system_prompt: str, user_prompt: str) -> NextStep:
    """Call Azure OpenAI structured output, same as _call_azure_openai_structured."""
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import AsyncAzureOpenAI

    endpoint = os.environ.get("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "")
    base_endpoint = endpoint.split('/api/projects')[0] if '/api/projects' in endpoint else endpoint
    model = os.environ.get("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")

    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")

    client = AsyncAzureOpenAI(
        azure_endpoint=base_endpoint,
        azure_ad_token_provider=token_provider,
        api_version="2024-08-01-preview"
    )

    completion = await client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format=NextStep,
        temperature=0.0,
        max_tokens=2000
    )

    return completion.choices[0].message.parsed


# ============================================================
# TEST SCENARIOS
# ============================================================

def _extract_agent_from_task(task_dict: Optional[dict]) -> Optional[str]:
    """Extract agent name from next_task dict regardless of key naming."""
    if not task_dict:
        return None
    # The LLM may use different key names depending on prompt phrasing
    for key in ["recommended_agent", "agent", "agent_name"]:
        val = task_dict.get(key)
        if val and isinstance(val, str):
            return val
    # Fallback: check all string values for agent-like names
    return None


WORKFLOW_TEXT = """1. [DocumentProcessor] Extract and analyze the invoice
2. [EVALUATE] Is the invoice total greater than $10,000?
   IF-TRUE → 3. [ManagerApproval] Route to manager for high-value approval
   IF-FALSE → 4. [AutoApproval] Auto-approve the low-value invoice
5. [Notification] Send confirmation email to the requester"""

AGENTS = [
    {"name": "DocumentProcessor", "description": "Extracts and analyzes document content (invoices, contracts, etc.)"},
    {"name": "ManagerApproval", "description": "Routes items to management for approval of high-value transactions"},
    {"name": "AutoApproval", "description": "Automatically approves low-value transactions that don't need manager review"},
    {"name": "Notification", "description": "Sends email notifications and confirmations"},
]


async def test_scenario(scenario_name: str, eval_result: bool, expected_agent: str, wrong_agent: str):
    """Run a single test scenario and check the LLM picks the right branch."""
    print(f"\n{'='*70}")
    print(f"SCENARIO: {scenario_name}")
    print(f"Evaluation result: {eval_result} → expected next agent: {expected_agent}")
    print(f"{'='*70}")

    system_prompt = build_workflow_prompt(WORKFLOW_TEXT)

    # Use different invoice data based on eval_result to avoid contradiction
    if eval_result:
        invoice_output = "Invoice #INV-2024-001. Vendor: Acme Corp. Total: $25,000.00. Date: 2024-01-15. Items: 5 consulting hours at $5,000/hr."
        eval_reasoning = "The invoice total is $25,000 which is greater than $10,000"
    else:
        invoice_output = "Invoice #INV-2024-002. Vendor: SmallCo. Total: $3,500.00. Date: 2024-01-15. Items: Office supplies."
        eval_reasoning = "The invoice total is $3,500 which is less than $10,000"

    # Simulate: step 1 completed, step 2 (evaluate) completed with known result
    tasks_history = [
        {
            "description": "[Step 1] Extract and analyze the invoice using DocumentProcessor",
            "agent": "DocumentProcessor",
            "state": "completed",
            "output": invoice_output
        },
        {
            "description": "[Step 2] [EVALUATE] Is the invoice total greater than $10,000?",
            "agent": "EVALUATE",
            "state": "completed",
            "output": json.dumps({
                "result": eval_result,
                "reasoning": eval_reasoning
            })
        }
    ]

    user_prompt = build_user_prompt(
        goal='Run the "Invoice Processing" workflow.',
        agents=AGENTS,
        tasks_history=tasks_history
    )

    print(f"\nCalling LLM...")
    result = await call_llm(system_prompt, user_prompt)

    print(f"\n--- LLM Response (raw) ---")
    print(f"  {result.model_dump_json(indent=2)}")

    # Extract agent from next_task regardless of key name (LLM may use
    # "recommended_agent", "agent", "agent_name", etc.)
    proposed_agent = _extract_agent_from_task(result.next_task) or _extract_agent_from_task(
        result.next_tasks[0] if result.next_tasks else None
    )

    # Verify
    correct = proposed_agent and expected_agent.lower() in proposed_agent.lower()
    chose_wrong = proposed_agent and wrong_agent.lower() in proposed_agent.lower()

    if correct:
        print(f"\n  ✅ PASS — LLM correctly chose {expected_agent}")
    elif chose_wrong:
        print(f"\n  ❌ FAIL — LLM chose WRONG branch: {proposed_agent} (should be {expected_agent})")
    else:
        print(f"\n  ⚠️  UNEXPECTED — LLM proposed: {proposed_agent} (expected {expected_agent})")

    return correct


async def test_full_workflow_completion():
    """Test that the LLM correctly marks the workflow as completed after the branch + final step."""
    print(f"\n{'='*70}")
    print(f"SCENARIO: Full workflow completion (does it skip to step 5 after branch?)")
    print(f"{'='*70}")

    system_prompt = build_workflow_prompt(WORKFLOW_TEXT)

    # Steps 1, 2, 3 (true branch) all done. Should propose step 5 next.
    tasks_history = [
        {
            "description": "[Step 1] Extract and analyze the invoice",
            "agent": "DocumentProcessor",
            "state": "completed",
            "output": "Invoice total: $25,000"
        },
        {
            "description": "[Step 2] [EVALUATE] Is the invoice total greater than $10,000?",
            "agent": "EVALUATE",
            "state": "completed",
            "output": json.dumps({"result": True, "reasoning": "$25,000 > $10,000"})
        },
        {
            "description": "[Step 3] Route to manager for high-value approval",
            "agent": "ManagerApproval",
            "state": "completed",
            "output": "Manager approved the invoice."
        }
    ]

    user_prompt = build_user_prompt(
        goal='Run the "Invoice Processing" workflow.',
        agents=AGENTS,
        tasks_history=tasks_history
    )

    result = await call_llm(system_prompt, user_prompt)

    print(f"\n--- LLM Response (raw) ---")
    print(f"  {result.model_dump_json(indent=2)}")

    proposed_agent = _extract_agent_from_task(result.next_task) or _extract_agent_from_task(
        result.next_tasks[0] if result.next_tasks else None
    )

    correct = proposed_agent and "notification" in proposed_agent.lower()
    skipped_to_complete = result.goal_status == "completed"

    if correct:
        print(f"\n  ✅ PASS — LLM correctly proposed step 5 (Notification) after branch")
    elif skipped_to_complete:
        print(f"\n  ❌ FAIL — LLM marked goal as completed without step 5 (Notification)")
    else:
        print(f"\n  ⚠️  UNEXPECTED — proposed: {proposed_agent}")

    return correct


async def test_step_count_awareness():
    """Test that the LLM doesn't insist on executing ALL 5 lines when a branch is skipped."""
    print(f"\n{'='*70}")
    print(f"SCENARIO: Step count — does it try to run step 4 (wrong branch) after completing 3→5?")
    print(f"{'='*70}")

    system_prompt = build_workflow_prompt(WORKFLOW_TEXT)

    # Steps 1, 2 (eval=true), 3 (true branch), 5 (notification) all done.
    # Step 4 (false branch) was correctly skipped.
    # The LLM should mark as COMPLETED, not try to run step 4.
    tasks_history = [
        {
            "description": "[Step 1] Extract and analyze the invoice",
            "agent": "DocumentProcessor",
            "state": "completed",
            "output": "Invoice total: $25,000"
        },
        {
            "description": "[Step 2] [EVALUATE] Is the invoice total greater than $10,000?",
            "agent": "EVALUATE",
            "state": "completed",
            "output": json.dumps({"result": True, "reasoning": "$25,000 > $10,000"})
        },
        {
            "description": "[Step 3] Route to manager for high-value approval",
            "agent": "ManagerApproval",
            "state": "completed",
            "output": "Manager approved."
        },
        {
            "description": "[Step 5] Send confirmation email",
            "agent": "Notification",
            "state": "completed",
            "output": "Confirmation email sent."
        }
    ]

    user_prompt = build_user_prompt(
        goal='Run the "Invoice Processing" workflow.',
        agents=AGENTS,
        tasks_history=tasks_history
    )

    result = await call_llm(system_prompt, user_prompt)

    print(f"\n--- LLM Response (raw) ---")
    print(f"  {result.model_dump_json(indent=2)}")

    correct = result.goal_status == "completed"
    tried_wrong_branch = (
        result.next_task and
        result.next_task.get("recommended_agent") and
        "autoapproval" in result.next_task["recommended_agent"].lower()
    )

    if correct:
        print(f"\n  ✅ PASS — LLM correctly marked workflow as completed (skipped branch not required)")
    elif tried_wrong_branch:
        print(f"\n  ❌ FAIL — LLM tried to execute the skipped branch (AutoApproval) after workflow was done")
    else:
        print(f"\n  ⚠️  UNEXPECTED — goal_status={result.goal_status}, next_task={result.next_task}")

    return correct


async def main():
    print("=" * 70)
    print("EVALUATION STEP BRANCHING TEST")
    print("Testing if the orchestrator LLM reliably follows IF-TRUE/IF-FALSE branches")
    print("=" * 70)
    print(f"\nWorkflow under test:\n{WORKFLOW_TEXT}")

    results = []

    # Test 1: Eval = TRUE → should go to ManagerApproval (step 3)
    r1 = await test_scenario(
        "Evaluation = TRUE → ManagerApproval",
        eval_result=True,
        expected_agent="ManagerApproval",
        wrong_agent="AutoApproval"
    )
    results.append(("TRUE branch", r1))

    # Test 2: Eval = FALSE → should go to AutoApproval (step 4)
    r2 = await test_scenario(
        "Evaluation = FALSE → AutoApproval",
        eval_result=False,
        expected_agent="AutoApproval",
        wrong_agent="ManagerApproval"
    )
    results.append(("FALSE branch", r2))

    # Test 3: After branch completes, should go to step 5
    r3 = await test_full_workflow_completion()
    results.append(("Post-branch continuation", r3))

    # Test 4: After full workflow, should mark completed (not run skipped branch)
    r4 = await test_step_count_awareness()
    results.append(("Step count / completion", r4))

    # Summary
    print(f"\n\n{'='*70}")
    print("RESULTS SUMMARY")
    print(f"{'='*70}")
    passed = 0
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}  {name}")
        if result:
            passed += 1
    print(f"\n  {passed}/{len(results)} tests passed")

    if passed == len(results):
        print("\n  🎉 All tests passed! The LLM reliably follows branches.")
    else:
        print("\n  ⚠️  Some tests failed. A deterministic guard may be needed.")


if __name__ == "__main__":
    asyncio.run(main())
