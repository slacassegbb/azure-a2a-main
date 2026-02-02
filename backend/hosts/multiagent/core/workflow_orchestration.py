"""
WorkflowOrchestration - Workflow execution and agent mode orchestration for FoundryHostAgent2.

This module contains methods related to:
- Parsed workflow execution (parallel and sequential)
- Agent mode orchestration loop
- Task execution with state management
- Workflow step processing
- Artifact collection

These are extracted from foundry_agent_a2a.py to improve code organization.
The class is designed to be used as a mixin with FoundryHostAgent2.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

# Import logging utilities
import sys
from pathlib import Path
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from a2a.types import Task, DataPart

from log_config import (
    log_debug,
    log_error,
    log_info,
)

from ..models import (
    SessionContext,
    AgentModeTask,
    AgentModePlan,
    NextStep,
    RouteSelection,
    ParsedWorkflow,
    ParsedWorkflowStep,
    WorkflowStepType,
)
from ..tool_context import DummyToolContext


class WorkflowOrchestration:
    """
    Mixin providing workflow execution and agent mode orchestration methods.
    
    This mixin handles:
    - Parsed workflow execution (parallel and sequential)
    - Agent mode orchestration loop with LLM planning
    - Task execution with state management
    - HITL (human-in-the-loop) support
    - Artifact collection and context passing
    
    Expected instance attributes (set by main class):
    - self.cards: Dict of agent cards
    - self._azure_blob_client: Azure blob client
    - self._active_conversations: Dict for conversation tracking
    - self.host_token_usage: Dict for token tracking
    
    Expected methods from other mixins:
    - self._emit_status_event()
    - self._emit_granular_agent_event()
    - self._extract_text_from_response()
    - self.send_message()
    - self._select_agent_for_task()
    - self._call_azure_openai_structured()
    """

    async def _execute_parsed_workflow(
        self,
        parsed_workflow: ParsedWorkflow,
        user_message: str,
        context_id: str,
        session_context: SessionContext
    ) -> List[str]:
        """
        Execute a pre-parsed workflow with support for parallel step groups.
        
        This method uses the Pydantic AgentModePlan for proper state management,
        retry logic, HITL support, and artifact tracking - just like the dynamic
        orchestration loop, but with a pre-defined workflow structure.
        
        Parallel groups (e.g., steps 2a, 2b) are executed concurrently using 
        asyncio.gather() while still creating proper AgentModeTask objects for
        state persistence.
        
        Args:
            parsed_workflow: The parsed workflow with sequential and parallel groups
            user_message: Original user message for context
            context_id: Conversation identifier
            session_context: Session state
            
        Returns:
            List of output strings from all executed steps
        """
        log_info(f"🚀 [Workflow] Executing parsed workflow with {len(parsed_workflow.groups)} groups")
        print(f"📋 [Workflow] Parsed structure:\n{parsed_workflow}")
        
        # Use the class method for extracting clean text from A2A response objects
        extract_text_from_response = self._extract_text_from_response
        
        # Initialize Pydantic plan for state tracking (just like dynamic orchestration)
        plan = AgentModePlan(goal=user_message, goal_status="incomplete")
        all_task_outputs = []
        
        # Log initial plan
        print(f"\n{'='*80}")
        log_debug(f"📋 [Parsed Workflow] INITIAL PLAN")
        print(f"{'='*80}")
        print(f"Goal: {plan.goal}")
        print(f"Groups: {len(parsed_workflow.groups)}")
        print(f"{'='*80}\n")
        
        for group_idx, group in enumerate(parsed_workflow.groups):
            group_type = "PARALLEL" if group.group_type == WorkflowStepType.PARALLEL else "SEQUENTIAL"
            log_info(f"📦 [Workflow] Executing group {group.group_number} ({group_type}, {len(group.steps)} steps)")
            
            if group.group_type == WorkflowStepType.PARALLEL:
                # ============================================================
                # PARALLEL EXECUTION with proper state tracking
                # ============================================================
                await self._emit_status_event(
                    f"Executing parallel group {group.group_number} ({len(group.steps)} agents simultaneously)...",
                    context_id
                )
                
                # Create AgentModeTask objects for each parallel step
                parallel_tasks: List[AgentModeTask] = []
                for step in group.steps:
                    task = AgentModeTask(
                        task_id=str(uuid.uuid4()),
                        task_description=f"[Step {step.step_label}] {step.description}",
                        recommended_agent=None,  # Will be resolved during execution
                        state="pending"
                    )
                    plan.tasks.append(task)
                    parallel_tasks.append(task)
                
                # Execute all steps in parallel
                async def execute_parallel_step(step: ParsedWorkflowStep, task: AgentModeTask):
                    """Execute a single step and update its task state."""
                    task.state = "running"
                    task.updated_at = datetime.now(timezone.utc)
                    
                    try:
                        result = await self._execute_workflow_step_with_state(
                            step=step,
                            task=task,
                            session_context=session_context,
                            context_id=context_id,
                            user_message=user_message,
                            extract_text_fn=extract_text_from_response
                        )
                        return result
                    except Exception as e:
                        task.state = "failed"
                        task.error_message = str(e)
                        task.updated_at = datetime.now(timezone.utc)
                        log_error(f"[Workflow] Parallel step {step.step_label} failed: {e}")
                        return {"error": str(e), "step_label": step.step_label}
                
                # Run in parallel
                results = await asyncio.gather(
                    *[execute_parallel_step(step, task) for step, task in zip(group.steps, parallel_tasks)],
                    return_exceptions=True
                )
                
                # Collect results and check for HITL pause
                for i, result in enumerate(results):
                    step = group.steps[i]
                    task = parallel_tasks[i]
                    
                    if isinstance(result, Exception):
                        log_error(f"[Workflow] Parallel step {step.step_label} exception: {result}")
                        all_task_outputs.append(f"[Step {step.step_label} Error]: {str(result)}")
                    elif isinstance(result, dict):
                        # Check for HITL pause
                        if result.get("hitl_pause"):
                            log_info(f"⏸️ [Workflow] HITL pause triggered by step {step.step_label}")
                            # Store workflow state for resumption
                            session_context.pending_workflow = str(parsed_workflow)
                            session_context.pending_workflow_outputs = all_task_outputs.copy()
                            session_context.pending_workflow_user_message = user_message
                            return all_task_outputs
                        
                        if result.get("output"):
                            all_task_outputs.append(f"[Step {step.step_label} - {result.get('agent', 'unknown')}]: {result['output']}")
                        elif result.get("error"):
                            all_task_outputs.append(f"[Step {step.step_label} Error]: {result['error']}")
                
                log_info(f"✅ [Workflow] Parallel group {group.group_number} completed")
                
            else:
                # ============================================================
                # SEQUENTIAL EXECUTION with proper state tracking
                # ============================================================
                step = group.steps[0]
                
                # Create AgentModeTask for this step
                task = AgentModeTask(
                    task_id=str(uuid.uuid4()),
                    task_description=f"[Step {step.step_label}] {step.description}",
                    recommended_agent=None,
                    state="running"
                )
                plan.tasks.append(task)
                
                await self._emit_status_event(f"Executing step {step.step_label}: {step.description[:50]}...", context_id)
                
                try:
                    result = await self._execute_workflow_step_with_state(
                        step=step,
                        task=task,
                        session_context=session_context,
                        context_id=context_id,
                        user_message=user_message,
                        extract_text_fn=extract_text_from_response
                    )
                    
                    # Check for HITL pause
                    if result.get("hitl_pause"):
                        log_info(f"⏸️ [Workflow] HITL pause triggered by step {step.step_label}")
                        session_context.pending_workflow = str(parsed_workflow)
                        session_context.pending_workflow_outputs = all_task_outputs.copy()
                        session_context.pending_workflow_user_message = user_message
                        return all_task_outputs
                    
                    if result.get("output"):
                        all_task_outputs.append(f"[Step {step.step_label} - {result.get('agent', 'unknown')}]: {result['output']}")
                    elif result.get("error"):
                        all_task_outputs.append(f"[Step {step.step_label} Error]: {result['error']}")
                    
                except Exception as e:
                    task.state = "failed"
                    task.error_message = str(e)
                    task.updated_at = datetime.now(timezone.utc)
                    log_error(f"[Workflow] Sequential step {step.step_label} failed: {e}")
                    all_task_outputs.append(f"[Step {step.step_label} Error]: {str(e)}")
                
                log_info(f"✅ [Workflow] Sequential step {step.step_label} completed")
        
        # Mark plan as completed
        plan.goal_status = "completed"
        plan.updated_at = datetime.now(timezone.utc)
        
        # Log final plan summary
        print(f"\n{'='*80}")
        print(f"🎬 [Parsed Workflow] FINAL PLAN SUMMARY")
        print(f"{'='*80}")
        print(f"Goal: {plan.goal}")
        print(f"Final Status: {plan.goal_status}")
        print(f"Total Tasks Created: {len(plan.tasks)}")
        print(f"\nTask Breakdown:")
        for i, task in enumerate(plan.tasks, 1):
            print(f"  {i}. [{task.state.upper()}] {task.task_description[:60]}...")
            print(f"     Agent: {task.recommended_agent or 'None'}")
            if task.error_message:
                print(f"     Error: {task.error_message}")
        print(f"\nTask Outputs Collected: {len(all_task_outputs)}")
        print(f"{'='*80}\n")
        
        log_info(f"🎉 [Workflow] All {len(parsed_workflow.groups)} groups completed, collected {len(all_task_outputs)} outputs")
        return all_task_outputs
    
    def _make_step_result(
        self,
        step_label: str,
        agent: str | None,
        state: str,
        output: str | None = None,
        error: str | None = None,
        hitl_pause: bool = False
    ) -> Dict[str, Any]:
        """Create a standardized workflow step result dict."""
        result = {
            "step_label": step_label,
            "agent": agent,
            "state": state,
            "error": error,
            "output": output
        }
        if hitl_pause:
            result["hitl_pause"] = True
        return result
    
    def _deduplicate_workflow_files(self, session_context: SessionContext) -> None:
        """Deduplicate files for multi-step workflows to prevent context explosion."""
        if not hasattr(session_context, '_latest_processed_parts'):
            return
        if len(session_context._latest_processed_parts) <= 1:
            return
            
        from collections import defaultdict
        
        MAX_GENERATED_FILES = 3
        editing_roles = {}
        generated_artifacts = []
        
        for part in reversed(session_context._latest_processed_parts):
            role = None
            if isinstance(part, DataPart) and isinstance(part.data, dict):
                role = part.data.get('role')
            elif hasattr(part, 'root') and isinstance(part.root, DataPart) and isinstance(part.root.data, dict):
                role = part.root.data.get('role')
            
            if role in ['base', 'mask', 'overlay']:
                if role not in editing_roles:
                    editing_roles[role] = part
            else:
                if len(generated_artifacts) < MAX_GENERATED_FILES:
                    generated_artifacts.append(part)
        
        session_context._latest_processed_parts = list(editing_roles.values()) + generated_artifacts
    
    def _extract_file_uris_from_parts(self, parts: List[Any]) -> List[str]:
        """Extract file URIs from A2A parts for explicit file routing.
        
        This enables workflow orchestration to use the same explicit file routing
        as agent mode, preventing race conditions during parallel execution.
        
        Args:
            parts: List of A2A Part objects that may contain file URIs
            
        Returns:
            List of file URI strings
        """
        file_uris = []
        
        for part in parts:
            try:
                # Handle Part wrapper objects
                if hasattr(part, 'root'):
                    inner_part = part.root
                else:
                    inner_part = part
                
                # Extract URI from FilePart
                if hasattr(inner_part, 'file'):
                    file_obj = inner_part.file
                    if hasattr(file_obj, 'uri') and file_obj.uri:
                        file_uris.append(file_obj.uri)
                        log_debug(f"  Extracted URI: {file_obj.uri}")
                    elif hasattr(file_obj, 'url') and file_obj.url:
                        file_uris.append(file_obj.url)
                        log_debug(f"  Extracted URL: {file_obj.url}")
                
                # Handle dict format (sometimes used internally)
                elif isinstance(inner_part, dict):
                    if inner_part.get('kind') == 'file':
                        file_data = inner_part.get('file', {})
                        if 'uri' in file_data:
                            file_uris.append(file_data['uri'])
                            log_debug(f"  Extracted URI from dict: {file_data['uri']}")
            
            except Exception as e:
                log_error(f"Error extracting URI from part: {e}")
                continue
        
        return file_uris
    
    async def _execute_workflow_step_with_state(
        self,
        step: ParsedWorkflowStep,
        task: AgentModeTask,
        session_context: SessionContext,
        context_id: str,
        user_message: str,
        extract_text_fn: Callable
    ) -> Dict[str, Any]:
        """
        Execute a single workflow step with full state tracking.
        
        Includes HITL detection, artifact collection, and proper error handling.
        """
        # Resolve agent (by hint or LLM selection)
        agent_name = self._resolve_agent_for_step(step)
        
        if not agent_name:
            available_agents = [{"name": card.name, "description": card.description} for card in self.cards.values()]
            agent_name = await self._select_agent_for_task(step.description, available_agents, context_id)
        
        if not agent_name or agent_name not in self.cards:
            task.state = "failed"
            task.error_message = "No suitable agent found"
            task.updated_at = datetime.now(timezone.utc)
            return self._make_step_result(step.step_label, None, "failed", error="No suitable agent found")
        
        # Update task with resolved agent
        task.recommended_agent = agent_name
        task.updated_at = datetime.now(timezone.utc)
        
        # DEBUG: Log agent execution start
        print(f"🚀 [HEADLESS DEBUG] Step {step.step_label}: Starting agent '{agent_name}'")
        print(f"   📝 Description: {step.description[:80]}...")
        print(f"   🔗 Context ID: {context_id}")
        
        await self._emit_granular_agent_event(
            agent_name=agent_name,
            status_text=f"Starting: {step.description[:50]}...",
            context_id=context_id
        )
        
        # Deduplicate files for multi-step workflows
        self._deduplicate_workflow_files(session_context)
        
        # EXPLICIT FILE ROUTING: Extract file URIs from _latest_processed_parts
        file_uris = []
        if hasattr(session_context, '_latest_processed_parts'):
            file_uris = self._extract_file_uris_from_parts(session_context._latest_processed_parts)
            log_debug(f"[Workflow] Passing {len(file_uris)} file URIs to {agent_name}")
        
        try:
            task_message = f"{step.description}\n\nContext: {user_message}"
            dummy_context = DummyToolContext(session_context, self._azure_blob_client)
            
            responses = await self.send_message(
                agent_name=agent_name,
                message=task_message,
                tool_context=dummy_context,
                suppress_streaming=False,
                file_uris=file_uris  # Pass explicit file URIs
            )
            
            # DEBUG: Log agent response
            print(f"✅ [HEADLESS DEBUG] Step {step.step_label}: Agent '{agent_name}' responded")
            print(f"   📦 Response count: {len(responses) if responses else 0}")
            
            if not responses:
                task.state = "failed"
                task.error_message = "No response from agent"
                task.updated_at = datetime.now(timezone.utc)
                return self._make_step_result(step.step_label, agent_name, "failed", error="No response from agent")
            
            response_obj = responses[0] if isinstance(responses, list) else responses
            
            # Check for HITL (input_required)
            if session_context.pending_input_agent:
                task.state = "input_required"
                task.updated_at = datetime.now(timezone.utc)
                output_text = extract_text_fn(response_obj)
                return self._make_step_result(step.step_label, agent_name, "input_required", output=output_text, hitl_pause=True)
            
            # Process response
            output_text = self._process_workflow_response(response_obj, task, session_context, extract_text_fn)
            
            if task.state == "failed":
                return self._make_step_result(step.step_label, agent_name, "failed", error=task.error_message)
            
            return self._make_step_result(step.step_label, agent_name, "completed", output=output_text)
                
        except Exception as e:
            task.state = "failed"
            task.error_message = str(e)
            task.updated_at = datetime.now(timezone.utc)
            log_error(f"[Workflow] Error executing step {step.step_label}: {e}")
            return self._make_step_result(step.step_label, agent_name, "failed", error=str(e))
    
    def _resolve_agent_for_step(self, step: ParsedWorkflowStep) -> str | None:
        """Resolve agent name from step hint."""
        if not step.agent_hint:
            return None
        for card_name in self.cards.keys():
            if step.agent_hint.lower() in card_name.lower():
                return card_name
        return None
    
    def _process_workflow_response(
        self,
        response_obj: Any,
        task: AgentModeTask,
        session_context: SessionContext,
        extract_text_fn: Callable
    ) -> str:
        """Process workflow response and update task state. Returns output text."""
        if isinstance(response_obj, Task):
            task.state = response_obj.status.state
            task.output = {
                "task_id": response_obj.id,
                "state": response_obj.status.state,
                "result": response_obj.result if hasattr(response_obj, 'result') else None,
                "artifacts": [a.model_dump() for a in response_obj.artifacts] if response_obj.artifacts else []
            }
            task.updated_at = datetime.now(timezone.utc)
            
            if task.state == "failed":
                task.error_message = response_obj.status.message or "Task failed"
                return ""
            
            output_text = str(response_obj.result) if response_obj.result else ""
            
            # Collect artifacts
            if response_obj.artifacts:
                artifact_texts = self._collect_artifacts(response_obj.artifacts, session_context)
                if artifact_texts:
                    output_text = f"{output_text}\n\nArtifacts:\n" + "\n".join(artifact_texts)
            
            return output_text
        else:
            # Simple string response
            task.state = "completed"
            output_text = extract_text_fn(response_obj)
            task.output = {"result": output_text}
            task.updated_at = datetime.now(timezone.utc)
            return output_text
    
    def _collect_artifacts(self, artifacts: list, session_context: SessionContext) -> List[str]:
        """Collect artifacts from response and add to session context. Returns descriptions."""
        artifact_descriptions = []
        
        if not hasattr(session_context, '_latest_processed_parts'):
            session_context._latest_processed_parts = []
        
        for artifact in artifacts:
            if not hasattr(artifact, 'parts'):
                continue
            for part in artifact.parts:
                session_context._latest_processed_parts.append(part)
                
                if hasattr(part, 'root'):
                    if hasattr(part.root, 'file'):
                        file_name = getattr(part.root.file, 'name', 'unknown')
                        artifact_descriptions.append(f"[File: {file_name}]")
                    elif hasattr(part.root, 'text'):
                        artifact_descriptions.append(part.root.text)
        
        return artifact_descriptions

    async def _execute_orchestrated_task(
        self,
        task: AgentModeTask,
        session_context: SessionContext,
        context_id: str,
        workflow: Optional[str],
        user_message: str,
        extract_text_fn: Callable,
        previous_task_outputs: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Execute a single orchestrated task with full state management.
        
        This method handles:
        - File deduplication for multi-step workflows
        - Agent calling via send_message
        - HITL (input_required) detection
        - Response parsing (A2A Task or legacy format)
        - Artifact collection
        - State updates on the AgentModeTask
        
        Args:
            task: The AgentModeTask to execute
            session_context: Session state
            context_id: Conversation identifier  
            workflow: Optional workflow definition
            user_message: Original user message
            extract_text_fn: Function to extract text from responses
            
        Returns:
            Dict with output, hitl_pause flag, and error info
        """
        recommended_agent = task.recommended_agent
        task_desc = task.task_description
        
        log_debug(f"🚀 [Agent Mode] Executing task: {task_desc[:50]}...")
        
        # Stream task creation event
        await self._emit_granular_agent_event(
            agent_name=recommended_agent or "orchestrator",
            status_text=f"Executing: {task_desc[:50]}...",
            context_id=context_id
        )
        
        if not recommended_agent or recommended_agent not in self.cards:
            task.state = "failed"
            task.error_message = f"Agent '{recommended_agent}' not found"
            task.updated_at = datetime.now(timezone.utc)
            log_error(f"[Agent Mode] Agent not found: {recommended_agent}")
            return {"error": task.error_message, "output": None}
        
        log_debug(f"🎯 [Agent Mode] Calling agent: {recommended_agent}")
        
        # Build enhanced task message with previous task output for sequential context
        # This enables agents to build upon previous work in the workflow
        enhanced_task_message = task_desc
        
        # For sequential workflows: Include ONLY the immediately previous task output as context
        # This allows step N to access the output from step N-1 without context window explosion
        if previous_task_outputs and len(previous_task_outputs) > 0:
            print(f"📋 [Agent Mode] Including previous task output as context (limited to last step only)")
            # Truncate to prevent context overflow (keep first 1000 chars)
            prev_output = previous_task_outputs[0]
            if len(prev_output) > 1000:
                prev_output = prev_output[:1000] + "... [truncated for context window management]"
            
            enhanced_task_message = f"""{task_desc}

## Context from Previous Step:
{prev_output}

Use the above output from the previous workflow step to complete your task."""
        
        # File deduplication for multi-step workflows
        self._deduplicate_workflow_files(session_context)
        
        # EXPLICIT FILE ROUTING: Extract file URIs from _latest_processed_parts
        file_uris = []
        if hasattr(session_context, '_latest_processed_parts'):
            file_uris = self._extract_file_uris_from_parts(session_context._latest_processed_parts)
            log_debug(f"[Agent Mode] Passing {len(file_uris)} file URIs to {recommended_agent}")
        
        # Create tool context and call agent
        dummy_context = DummyToolContext(session_context, self._azure_blob_client)
        
        responses = await self.send_message(
            agent_name=recommended_agent,
            message=enhanced_task_message,  # ✅ Now includes previous task outputs!
            tool_context=dummy_context,
            suppress_streaming=True,  # Suppress agent's internal streaming to avoid duplicates in workflow mode
            file_uris=file_uris  # Pass explicit file URIs
        )
        
        if not responses or len(responses) == 0:
            task.state = "failed"
            task.error_message = "No response from agent"
            task.updated_at = datetime.now(timezone.utc)
            log_error(f"[Agent Mode] No response from agent")
            return {"error": "No response from agent", "output": None}
        
        response_obj = responses[0] if isinstance(responses, list) else responses
        
        # Check for HITL (input_required)
        if session_context.pending_input_agent:
            log_info(f"⏸️ [Agent Mode] Agent '{recommended_agent}' returned input_required")
            task.state = "input_required"
            task.updated_at = datetime.now(timezone.utc)
            
            output_text = extract_text_fn(response_obj)
            log_info(f"⏸️ [Agent Mode] Waiting for user response to '{recommended_agent}'")
            await self._emit_status_event(f"Waiting for your response...", context_id)
            
            return {"output": output_text, "hitl_pause": True}
        
        # Parse response
        if isinstance(response_obj, Task):
            task.state = response_obj.status.state
            task.output = {
                "task_id": response_obj.id,
                "state": response_obj.status.state,
                "result": response_obj.result if hasattr(response_obj, 'result') else None,
                "artifacts": [a.model_dump() for a in response_obj.artifacts] if response_obj.artifacts else []
            }
            task.updated_at = datetime.now(timezone.utc)
            
            if task.state == "failed":
                task.error_message = response_obj.status.message or "Task failed"
                log_error(f"[Agent Mode] Task failed: {task.error_message}")
                return {"error": task.error_message, "output": None}
            
            output_text = str(response_obj.result) if response_obj.result else ""
            
            # Collect artifacts using helper
            if response_obj.artifacts:
                artifact_texts = self._collect_artifacts(response_obj.artifacts, session_context)
                if artifact_texts:
                    output_text = f"{output_text}\n\nArtifacts:\n" + "\n".join(artifact_texts)
            
            return {"output": output_text, "hitl_pause": False}
        else:
            # Simple string response (legacy format)
            task.state = "completed"
            output_text = extract_text_fn(response_obj)
            task.output = {"result": output_text}
            task.updated_at = datetime.now(timezone.utc)
            return {"output": output_text, "hitl_pause": False}

    async def _intelligent_route_selection(
        self,
        user_message: str,
        available_workflows: List[Dict[str, Any]],
        context_id: str
    ) -> RouteSelection:
        """
        Use LLM to intelligently select the best execution approach for the user's request.
        
        This is the "router" that decides whether to:
        - Use a specific pre-defined workflow (structured multi-step process)
        - Use agents directly (free-form multi-agent orchestration)
        - Respond directly (simple queries that don't need orchestration)
        
        Args:
            user_message: The user's request/goal
            available_workflows: List of workflow metadata dicts with keys:
                - name: Workflow name
                - description: What the workflow does
                - goal: The workflow's objective
                - steps: List of workflow steps (optional, for context)
            context_id: Conversation identifier
            
        Returns:
            RouteSelection with approach, selected_workflow, confidence, and reasoning
        """
        log_debug(f"🔀 [Route Selection] Analyzing request with {len(available_workflows)} available workflows")
        
        # Build workflow descriptions for the prompt
        workflow_descriptions = []
        for i, wf in enumerate(available_workflows, 1):
            wf_name = wf.get('name', f'Workflow {i}')
            wf_desc = wf.get('description', 'No description provided')
            wf_goal = wf.get('goal', '')
            
            desc = f"""**{wf_name}**
- Description: {wf_desc}
- Goal: {wf_goal if wf_goal else 'Execute the workflow steps'}"""
            
            # Optionally include step count or step preview
            if wf.get('steps'):
                steps = wf['steps']
                if isinstance(steps, list):
                    desc += f"\n- Steps: {len(steps)} steps"
                elif isinstance(steps, str):
                    step_count = len([l for l in steps.split('\n') if l.strip() and l.strip()[0].isdigit()])
                    desc += f"\n- Steps: {step_count} steps"
            
            workflow_descriptions.append(desc)
        
        workflows_text = "\n\n".join(workflow_descriptions)
        
        # Build available agents summary
        agent_descriptions = []
        for card in self.cards.values():
            agent_info = f"**{card.name}**: {card.description[:150]}..."
            if hasattr(card, 'skills') and card.skills:
                skill_names = [s.name for s in card.skills[:3]]  # First 3 skills
                agent_info += f" (Skills: {', '.join(skill_names)})"
            agent_descriptions.append(agent_info)
        
        agents_text = "\n".join(agent_descriptions) if agent_descriptions else "No agents available"
        
        system_prompt = f"""You are an intelligent routing assistant. Analyze the user's request and decide the best execution approach.

### 📋 AVAILABLE WORKFLOWS
These are pre-defined multi-step processes. Use them when the user's goal clearly matches.

{workflows_text}

### 🤖 AVAILABLE AGENTS
These are specialized agents that can handle specific tasks.

{agents_text}

### 🎯 DECISION RULES

**Choose "workflow"** when:
- User's goal clearly matches ONE workflow's description or purpose
- The task requires a specific sequence of coordinated steps
- A workflow exists that handles this exact use case
- User explicitly mentions a workflow name

**Choose "workflows_parallel"** when:
- User's request matches TWO OR MORE workflows that should run SIMULTANEOUSLY
- The workflows are INDEPENDENT and don't depend on each other's output
- User explicitly asks for multiple things that map to different workflows
- Example: "Run the legal review AND the financial analysis" → both workflows in parallel
- Set selected_workflows to the list of workflow names to execute

**Choose "agents"** when:
- Goal needs multi-agent coordination but no workflow fits
- Task is complex but doesn't match any workflow pattern
- User needs something custom or ad-hoc
- Multiple agents could help but in a non-standard way

**Choose "direct"** when:
- Simple question that can be answered without agents
- General conversation or greetings
- Request doesn't require any specialized agent capabilities
- Single simple task that the host can handle directly

### 📤 OUTPUT FORMAT
Return a JSON object with:
- approach: "workflow" | "workflows_parallel" | "agents" | "direct"
- selected_workflow: Name of workflow (if approach="workflow") or null
- selected_workflows: List of workflow names (if approach="workflows_parallel") or null
- confidence: 0.0 to 1.0 (how confident you are in this choice)
- reasoning: Brief explanation of your decision"""

        user_prompt = f"""User request: {user_message}

Analyze this request and decide the best approach."""

        try:
            selection = await self._call_azure_openai_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=RouteSelection,
                context_id=context_id
            )
            
            if selection.approach == "workflows_parallel":
                log_debug(f"🔀 [Route Selection] Decision: approach={selection.approach}, workflows={selection.selected_workflows}, confidence={selection.confidence}")
            else:
                log_debug(f"🔀 [Route Selection] Decision: approach={selection.approach}, workflow={selection.selected_workflow}, confidence={selection.confidence}")
            log_debug(f"🔀 [Route Selection] Reasoning: {selection.reasoning}")
            
            return selection
            
        except Exception as e:
            log_error(f"[Route Selection] Error during selection: {e}")
            # Fallback to agents approach on error
            return RouteSelection(
                approach="agents",
                selected_workflow=None,
                selected_workflows=None,
                confidence=0.5,
                reasoning=f"Fallback to agents due to selection error: {str(e)}"
            )

    async def _agent_mode_orchestration_loop(
        self,
        user_message: str,
        context_id: str,
        session_context: SessionContext,
        event_logger=None,
        workflow: Optional[str] = None,
        workflow_goal: Optional[str] = None
    ) -> List[str]:
        """
        Execute agent-mode orchestration: AI-driven task decomposition and multi-agent coordination.
        
        This is the core intelligence loop that:
        1. Uses Azure OpenAI to analyze the user's goal and available agents
        2. Breaks down complex requests into discrete, delegable tasks
        3. Selects the best agent for each task based on skills and capabilities
        4. Executes tasks sequentially or in parallel as appropriate
        5. Synthesizes results from multiple agents into coherent responses
        6. Adapts to failures, rate limits, and user feedback dynamically
        
        The loop continues until the goal is marked "completed" by the orchestrator LLM
        or the maximum iteration limit is reached (safety mechanism).
        
        Args:
            user_message: The user's original request or follow-up message
            context_id: Conversation identifier for state management
            session_context: Session state with agent task tracking
            event_logger: Optional callback for logging orchestration events
            workflow: Optional predefined workflow steps to enforce
            workflow_goal: Optional goal from workflow designer for completion evaluation
            
        Returns:
            List of response strings from executed tasks for final synthesis
        """
        log_debug(f"🎯 [Agent Mode] Starting orchestration loop for goal: {user_message[:100]}...")
        
        # Reset host token usage for this workflow
        self.host_token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        
        await self._emit_status_event("Initializing orchestration...", context_id)
        
        # =====================================================================
        # LLM ORCHESTRATION PATH: All workflows go through the orchestrator
        # =====================================================================
        # The LLM orchestrator handles both sequential and parallel workflows.
        # For parallel steps (e.g., 2a., 2b.), the LLM will return next_tasks
        # with parallel=True, and we execute them via asyncio.gather().
        # =====================================================================
        # orchestrator LLM decides which agents to call and in what order.
        # =====================================================================
        
        # Handle conversation continuity - distinguish new goals from follow-up clarifications
        if context_id in self._active_conversations and not workflow:
            original_goal = self._active_conversations[context_id]
            goal_text = f"{original_goal}\n\n[Additional Information Provided]: {user_message}"
        else:
            # Use workflow_goal from the designer if provided, otherwise fall back to user_message
            if workflow_goal and workflow_goal.strip():
                goal_text = workflow_goal
                log_debug(f"🎯 [Workflow Mode] Using workflow designer goal: {goal_text[:100]}...")
            else:
                goal_text = user_message
            if context_id not in self._active_conversations:
                self._active_conversations[context_id] = goal_text
        
        # Use the class method for extracting clean text from A2A response objects
        extract_text_from_response = self._extract_text_from_response
        
        # Initialize execution plan with empty task list
        plan = AgentModePlan(goal=goal_text, goal_status="incomplete")
        iteration = 0
        max_iterations = 20
        workflow_step_count = 0
        
        # Accumulate outputs from all completed tasks
        all_task_outputs = []
        
        # System prompt that guides the orchestrator's decision-making
        # This is the "brain" that decides which agents to use and when
        system_prompt = """You are the Host Orchestrator in an A2A multi-agent system.

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

### 🔀 PARALLEL EXECUTION SUPPORT
When the workflow contains parallel steps (indicated by letter suffixes like 2a., 2b., 2c.):
- These steps can be executed SIMULTANEOUSLY - they do not depend on each other
- Use `next_tasks` (list) instead of `next_task` (single) to propose multiple parallel tasks
- Set `parallel=true` to indicate these tasks should run concurrently
- Example: For steps "2a. Legal review" and "2b. Technical assessment":
  ```json
  {
    "goal_status": "incomplete",
    "next_task": null,
    "next_tasks": [
      {"task_description": "Legal review of requirements", "recommended_agent": "Legal Agent"},
      {"task_description": "Technical assessment", "recommended_agent": "Tech Agent"}
    ],
    "parallel": true,
    "reasoning": "Steps 2a and 2b can run in parallel as they are independent"
  }
  ```
- After parallel tasks complete, proceed to the next sequential step (e.g., step 3)
- If NO parallel steps, use `next_task` (single) and set `parallel=false`

### 🚨 CRITICAL: WHEN TO USE PARALLEL EXECUTION
**ALWAYS use parallel execution (next_tasks + parallel=true) when:**
1. User requests MULTIPLE similar items (e.g., "generate 3 images", "create 2 documents")
2. Workflow steps have letter suffixes (1a, 1b, 1c or 2a, 2b)
3. Tasks are independent and can run simultaneously
4. User explicitly says "in parallel", "simultaneously", or "at the same time"

**Example - User says "Generate 3 images: a car, a bike, a backpack":**
```json
{
  "goal_status": "incomplete",
  "next_task": null,
  "next_tasks": [
    {"task_description": "Generate an image of a car", "recommended_agent": "AI Foundry Image Generator Agent"},
    {"task_description": "Generate an image of a bike", "recommended_agent": "AI Foundry Image Generator Agent"},
    {"task_description": "Generate an image of a backpack", "recommended_agent": "AI Foundry Image Generator Agent"}
  ],
  "parallel": true,
  "reasoning": "User requested 3 independent images - executing in parallel for efficiency"
}
```

**DO NOT bundle multiple items into a single task like "Generate 3 images" - split them into separate parallel tasks!**

MULTI-AGENT STRATEGY:
- **MAXIMIZE AGENT UTILIZATION**: Break complex goals into specialized subtasks
- Use multiple agents when their combined expertise adds value
- Don't force one agent to handle everything when others can help
- The same agent can be used multiple times for related subtasks

FAILURE HANDLING:
- Consider failed tasks in planning
- You can retry with modifications or try alternative agents/approaches

### 🔄 TASK DECOMPOSITION PRINCIPLES
- **Read ALL Agent Skills First**: Before creating any task, carefully read through the skill descriptions of ALL available agents to understand what each can provide.
- **Identify Skill Dependencies**: Determine if completing the goal requires outputs from multiple agents. If Agent B needs information/context that Agent A specializes in, Agent A must be tasked first.
- **Match Task to Skill Domain**: Each task should align with exactly ONE agent's skill domain. If a concept in the goal matches words in an agent's skill name or description, that agent should handle that aspect.
- **Information Producers vs Consumers**: Some agents produce information/context/specifications (e.g., skills about "guidelines", "direction", "specifications"). Others consume that information to execute (e.g., skills about "generate", "create", "build"). Producers come first.
- **Sequential Task Chain**: When the goal involves multiple skill domains, create Task 1 for the information producer, let it complete, then Task 2 for the executor using Task 1's output.
- **No Shortcuts**: Don't try to have one agent do another agent's specialty work. Decompose properly even if it means more tasks.

### 🎯 DELEGATION FIRST PRINCIPLE
- ALWAYS delegate to an appropriate agent if you have ANY actionable information related to the goal
- **BUT** check if the task requires prerequisite skills from a different agent - if so, delegate to that agent FIRST
- Each agent should work within their skill domain - use the "skills" field to match task requirements to agent capabilities
- Tasks should arrive at agents with all necessary context already gathered by appropriate upstream agents
"""
        
        # Inject workflow if provided
        print(f"🔍 [Agent Mode] Checking workflow: workflow={workflow}, stripped={workflow.strip() if workflow else 'N/A'}")
        if workflow and workflow.strip():
            workflow_section = f"""

### 🔥 MANDATORY WORKFLOW - FOLLOW ALL STEPS IN ORDER 🔥
**CRITICAL**: The following workflow steps are MANDATORY and must ALL be completed before marking the goal as "completed".
Do NOT skip steps. Do NOT mark goal as completed until ALL workflow steps are done.

{workflow.strip()}

**AGENT ROUTING**: 
- Each step specifies the agent to use in [brackets] - e.g., "[QuickBooks Online Agent]"
- You MUST use the agent specified in brackets for that step - do NOT substitute a different agent
- Set `recommended_agent` to the exact agent name from the brackets

**EXECUTION RULES**: 
- Execute sequential steps (1, 2, 3) one after another
- **PARALLEL STEPS** (e.g., 2a, 2b, 2c): When you see steps with letter suffixes, these can run SIMULTANEOUSLY
  - Use `next_tasks` (list) with `parallel=true` to execute them concurrently
  - Wait for ALL parallel tasks to complete before moving to the next sequential step
- Only mark goal_status="completed" after ALL workflow steps are finished
- If a step fails, you may retry or adapt, but you must complete all steps
"""
            system_prompt += workflow_section
            log_debug(f"📋 [Agent Mode] ✅ Injected workflow into planner prompt ({len(workflow)} chars)")
        
        # Add workflow-specific completion logic if workflow is present
        if workflow and workflow.strip():
            workflow_step_count = len([line for line in workflow.strip().split('\n') if line.strip() and (line.strip()[0].isdigit() or line.strip().startswith('-'))])
            log_debug(f"📊 [Agent Mode] Workflow step count: {workflow_step_count}")
            
            system_prompt += f"""

### 🚨 CRITICAL: WHEN TO STOP (WORKFLOW MODE)
- A WORKFLOW IS ACTIVE with **{workflow_step_count} MANDATORY STEPS** - You MUST complete ALL {workflow_step_count} workflow steps before marking goal as "completed"
- **STEP COUNTING**: The workflow has EXACTLY {workflow_step_count} steps. Count your completed tasks carefully!
- **VERIFICATION CHECKLIST**:
  1. Count the number of workflow steps above (should be {workflow_step_count})
  2. Count the number of successfully completed tasks in your plan
  3. Match each workflow step to a completed task
  4. If completed tasks < {workflow_step_count}, goal_status MUST be "incomplete"
- **COMPLETION CRITERIA** - Mark goal_status="completed" ONLY when:
  1. You have AT LEAST {workflow_step_count} successfully completed tasks, AND
  2. Each workflow step has been addressed by a completed task, AND
  3. All completed tasks succeeded (or agents are waiting for user input)
- **WARNING**: Do NOT mark as completed after only 1, 2, or 3 steps if the workflow has {workflow_step_count} steps!
- If ANY workflow step is missing or incomplete, goal_status MUST be "incomplete" and you must create the next task"""
        else:
            system_prompt += """

### 🚨 CRITICAL: WHEN TO STOP (LOOP DETECTION & USER INPUT)
- ONLY mark goal as "completed" in these specific cases:
  1. The goal is actually fully accomplished with successful task outputs
  2. You have 2+ completed tasks where agents explicitly asked the USER for information
  3. The last agent response clearly states they need user input to proceed
- If NO tasks have been created yet, DO NOT mark as completed - create a task first!
- When agents request information, synthesize their questions and present to the user
- When the user provides information in a follow-up, create a NEW task with that information"""
        
        while plan.goal_status == "incomplete" and iteration < max_iterations:
            iteration += 1
            print(f"🔄 [Agent Mode] Iteration {iteration}/{max_iterations}")
            await self._emit_status_event(f"Planning step {iteration}...", context_id)
            
            # Build user prompt with current plan state
            available_agents = []
            for card in self.cards.values():
                agent_info = {
                    "name": card.name,
                    "description": card.description
                }
                
                # Add skills if present
                if hasattr(card, 'skills') and card.skills:
                    skills_list = []
                    for skill in card.skills:
                        skill_dict = {
                            "id": getattr(skill, 'id', ''),
                            "name": getattr(skill, 'name', ''),
                            "description": getattr(skill, 'description', ''),
                        }
                        skills_list.append(skill_dict)
                    agent_info['skills'] = skills_list
                
                available_agents.append(agent_info)
            
            user_prompt = f"""Goal:
{plan.goal}

Current Plan (JSON):
{json.dumps(plan.model_dump(), indent=2, default=str)}

Available Agents (JSON):
{json.dumps(available_agents, indent=2)}

Analyze the plan and determine the next step. Proceed autonomously - do NOT ask the user for permission or confirmation."""
            
            # Get next step from orchestrator
            try:
                next_step = await self._call_azure_openai_structured(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_model=NextStep,
                    context_id=context_id
                )
                
                log_debug(f"🤖 [Agent Mode] Orchestrator: {next_step.reasoning[:100]}... | status={next_step.goal_status}")
                await self._emit_status_event(f"Reasoning: {next_step.reasoning}", context_id)
                
                # Update plan status
                plan.goal_status = next_step.goal_status
                plan.updated_at = datetime.now(timezone.utc)
                
                if next_step.goal_status == "completed":
                    completed_tasks_count = len([t for t in plan.tasks if t.state == "completed"])
                    log_info(f"✅ [Agent Mode] Goal completed after {iteration} iterations ({completed_tasks_count} tasks)")
                    await self._emit_status_event("Goal achieved! Generating final response...", context_id)
                    break
                
                # =========================================================
                # TASK EXECUTION: Handle both sequential and parallel tasks
                # =========================================================
                
                # Determine which tasks to execute
                tasks_to_execute = []
                is_parallel = next_step.parallel and next_step.next_tasks
                
                if is_parallel and next_step.next_tasks:
                    log_info(f"🔀 [Agent Mode] PARALLEL execution: {len(next_step.next_tasks)} tasks")
                    await self._emit_status_event(f"Executing {len(next_step.next_tasks)} tasks in parallel...", context_id)
                    for task_dict in next_step.next_tasks:
                        tasks_to_execute.append({
                            "task_description": task_dict.get("task_description"),
                            "recommended_agent": task_dict.get("recommended_agent")
                        })
                elif next_step.next_task:
                    # SEQUENTIAL EXECUTION: Single task via next_task
                    tasks_to_execute.append({
                        "task_description": next_step.next_task.get("task_description"),
                        "recommended_agent": next_step.next_task.get("recommended_agent")
                    })
                
                if not tasks_to_execute:
                    print(f"⚠️ [Agent Mode] No tasks to execute, breaking loop")
                    break
                
                # Validate all tasks have descriptions
                for task_dict in tasks_to_execute:
                    if not task_dict.get("task_description"):
                        print(f"⚠️ [Agent Mode] Task missing description, skipping")
                        tasks_to_execute.remove(task_dict)
                
                if not tasks_to_execute:
                    print(f"⚠️ [Agent Mode] No valid tasks after validation, breaking loop")
                    break
                
                # Create AgentModeTask objects for all tasks
                pydantic_tasks = []
                for task_dict in tasks_to_execute:
                    task = AgentModeTask(
                        task_id=str(uuid.uuid4()),
                        task_description=task_dict["task_description"],
                        recommended_agent=task_dict.get("recommended_agent"),
                        state="pending"
                    )
                    plan.tasks.append(task)
                    pydantic_tasks.append(task)
                    log_debug(f"📋 [Agent Mode] Created task: {task.task_description[:50]}...")
                
                # Execute tasks (parallel or sequential)
                if is_parallel:
                    # ============================================
                    # PARALLEL EXECUTION via asyncio.gather()
                    # ============================================
                    import asyncio as async_lib  # Import locally to avoid any scoping issues
                    log_info(f"🔀 [Agent Mode] Executing {len(pydantic_tasks)} tasks IN PARALLEL")
                    await self._emit_status_event(f"Executing {len(pydantic_tasks)} tasks simultaneously...", context_id)
                    
                    async def execute_task_parallel(task: AgentModeTask) -> Dict[str, Any]:
                        """Execute a single task and return result dict."""
                        task.state = "running"
                        task.updated_at = datetime.now(timezone.utc)
                        
                        try:
                            # For parallel tasks, pass only the LAST task output (from the step before parallel group)
                            # Don't pass all accumulated outputs - that would grow context exponentially
                            previous_output = [all_task_outputs[-1]] if all_task_outputs else None
                            
                            result = await self._execute_orchestrated_task(
                                task=task,
                                session_context=session_context,
                                context_id=context_id,
                                workflow=workflow,
                                user_message=user_message,
                                extract_text_fn=extract_text_from_response,
                                previous_task_outputs=previous_output  # ✅ Only LAST output
                            )
                            return result
                        except Exception as e:
                            task.state = "failed"
                            task.error_message = str(e)
                            task.updated_at = datetime.now(timezone.utc)
                            log_error(f"[Agent Mode] Parallel task failed: {e}")
                            return {"error": str(e), "task_id": task.task_id}
                    
                    # Run all tasks in parallel
                    try:
                        results = await async_lib.gather(
                            *[execute_task_parallel(t) for t in pydantic_tasks],
                            return_exceptions=True
                        )
                    except Exception as gather_error:
                        log_error(f"[Agent Mode] asyncio.gather failed: {gather_error}")
                        raise
                    
                    # Process results
                    hitl_pause = False
                    for i, result in enumerate(results):
                        task = pydantic_tasks[i]
                        if isinstance(result, Exception):
                            task.state = "failed"
                            task.error_message = str(result)
                        elif isinstance(result, dict):
                            if result.get("hitl_pause"):
                                hitl_pause = True
                                if result.get("output"):
                                    all_task_outputs.append(result["output"])
                            elif result.get("output"):
                                all_task_outputs.append(result["output"])
                        task.updated_at = datetime.now(timezone.utc)
                    
                    # If any task triggered HITL pause, pause the workflow
                    if hitl_pause:
                        session_context.pending_workflow = workflow
                        session_context.pending_workflow_outputs = all_task_outputs.copy()
                        session_context.pending_workflow_user_message = user_message
                        return all_task_outputs
                    
                    log_info(f"✅ [Agent Mode] {len(pydantic_tasks)} parallel tasks completed")
                    
                else:
                    # ============================================
                    # SEQUENTIAL EXECUTION (single task)
                    # ============================================
                    task = pydantic_tasks[0]
                    task.state = "running"
                    task.updated_at = datetime.now(timezone.utc)
                    
                    try:
                        previous_output = [all_task_outputs[-1]] if all_task_outputs else None
                        
                        result = await self._execute_orchestrated_task(
                            task=task,
                            session_context=session_context,
                            context_id=context_id,
                            workflow=workflow,
                            user_message=user_message,
                            extract_text_fn=extract_text_from_response,
                            previous_task_outputs=previous_output
                        )
                        
                        if result.get("hitl_pause"):
                            if result.get("output"):
                                all_task_outputs.append(result["output"])
                            session_context.pending_workflow = workflow
                            session_context.pending_workflow_outputs = all_task_outputs.copy()
                            session_context.pending_workflow_user_message = user_message
                            return all_task_outputs
                        
                        if result.get("output"):
                            all_task_outputs.append(result["output"])
                        
                    except Exception as e:
                        task.state = "failed"
                        task.error_message = str(e)
                        log_error(f"[Agent Mode] Task execution error: {e}")
                    
                    finally:
                        task.updated_at = datetime.now(timezone.utc)
                
            except Exception as e:
                log_error(f"[Agent Mode] Orchestration error: {e}")
                await self._emit_status_event(f"Error in orchestration: {str(e)}", context_id)
                break
        
        if iteration >= max_iterations:
            log_debug(f"⚠️ [Agent Mode] Reached max iterations ({max_iterations})")
            await self._emit_status_event("Maximum iterations reached, completing...", context_id)
        
        log_info(f"🎬 [Agent Mode] Complete: {len(all_task_outputs)} outputs, {iteration} iterations, {len(plan.tasks)} tasks")
        
        # Emit host token usage to frontend
        try:
            from service.websocket_streamer import get_websocket_streamer
            
            async def emit_host_tokens():
                streamer = await get_websocket_streamer()
                if streamer:
                    event_data = {
                        "agentName": "foundry-host-agent",
                        "tokenUsage": self.host_token_usage,
                        "state": "completed",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    await streamer._send_event("host_token_usage", event_data, context_id)
            
            asyncio.create_task(emit_host_tokens())
        except Exception:
            pass  # Don't let token emission failures break the flow
        
        return all_task_outputs
