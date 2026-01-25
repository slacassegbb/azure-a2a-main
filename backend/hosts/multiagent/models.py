"""
Data models for the Foundry Host Agent.

These are Pydantic models used for session state, workflow parsing,
and agent mode orchestration.
"""

import uuid
from typing import Dict, List, Any, Optional, Literal
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class SessionContext(BaseModel):
    """
    Session state management for A2A protocol conversations.
    Tracks conversation context, task states, and agent coordination across multi-agent workflows.
    """
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
    # Human-in-the-loop tracking: which agent is waiting for user input
    pending_input_agent: Optional[str] = Field(default=None, description="Agent name waiting for input_required response")
    pending_input_task_id: Optional[str] = Field(default=None, description="Task ID of the pending input_required task")
    # Workflow state for pausing/resuming on input_required
    pending_workflow: Optional[str] = Field(default=None, description="Workflow definition to resume after HITL completes")
    pending_workflow_outputs: List[str] = Field(default_factory=list, description="Task outputs collected before HITL pause")
    pending_workflow_user_message: Optional[str] = Field(default=None, description="Original user message for workflow")
    
    class Config:
        arbitrary_types_allowed = True


# Agent Mode Orchestration Models
TaskStateEnum = Literal["pending", "running", "completed", "failed", "cancelled"]
GoalStatus = Literal["incomplete", "completed"]


class AgentModeTask(BaseModel):
    """Individual task within a multi-agent workflow plan."""
    task_id: str = Field(..., description="Unique A2A task identifier.")
    task_description: str = Field(..., description="Single remote-agent instruction.")
    recommended_agent: Optional[str] = Field(None, description="Agent name to execute this task.")
    output: Optional[Dict[str, Any]] = Field(None, description="A2A remote-agent output payload.")
    state: TaskStateEnum = Field("pending", description="Current A2A task state.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error_message: Optional[str] = Field(None, description="Error message if task failed.")


class AgentModePlan(BaseModel):
    """Multi-agent workflow plan with task decomposition and state tracking."""
    goal: str = Field(..., description="User query or objective.")
    goal_status: GoalStatus = Field("incomplete", description="Completion state of the goal.")
    tasks: List[AgentModeTask] = Field(default_factory=list, description="List of all tasks in the plan.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NextStep(BaseModel):
    """Orchestrator decision for the next action in a multi-agent workflow."""
    goal_status: GoalStatus = Field(..., description="Whether the goal is completed or not.")
    next_task: Optional[Dict[str, Optional[str]]] = Field(
        None,
        description='Single task: {"task_description": str, "recommended_agent": str|None}. Use this for sequential execution. Set to null if using next_tasks for parallel execution.'
    )
    next_tasks: Optional[List[Dict[str, Optional[str]]]] = Field(
        None,
        description='Multiple tasks to execute IN PARALLEL: [{"task_description": str, "recommended_agent": str|None}, ...]. Use this when workflow has parallel steps (e.g., 2a, 2b). Set to null for sequential execution.'
    )
    parallel: bool = Field(
        False,
        description='Set to true when next_tasks should be executed in parallel (e.g., for workflow steps like 2a, 2b). Set to false for sequential execution.'
    )
    reasoning: str = Field(..., description="Short explanation of the decision.")


class WorkflowStepType(str, Enum):
    """Type of workflow step execution."""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


@dataclass
class ParsedWorkflowStep:
    """A single step within a workflow."""
    step_label: str  # e.g., "1", "2a", "2b", "3"
    description: str
    agent_hint: Optional[str] = None  # Extracted agent name if mentioned in description


@dataclass
class ParsedWorkflowGroup:
    """A group of steps that execute together (sequential = 1 step, parallel = multiple)."""
    group_number: int  # The main step number (e.g., 2 for "2a", "2b")
    group_type: WorkflowStepType
    steps: List['ParsedWorkflowStep']


@dataclass
class ParsedWorkflow:
    """Complete parsed workflow with sequential and parallel groups."""
    groups: List[ParsedWorkflowGroup]
    
    def __str__(self) -> str:
        lines = []
        for group in self.groups:
            if group.group_type == WorkflowStepType.PARALLEL:
                lines.append(f"[Parallel Group {group.group_number}]")
                for step in group.steps:
                    lines.append(f"  {step.step_label}. {step.description}")
            else:
                step = group.steps[0]
                lines.append(f"{step.step_label}. {step.description}")
        return "\n".join(lines)
