"""
Workflow Service - Handles workflow persistence to JSON file.

Workflows are persisted to a local JSON file for restart resilience and 
cross-browser/device sharing. Each workflow is associated with a user.
"""

import json
from datetime import datetime, UTC
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

# Default data directory (matches other services)
DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"


@dataclass
class WorkflowStep:
    """A single step in a workflow."""
    id: str
    agentId: str
    agentName: str
    description: str
    order: int
    x: float = 0
    y: float = 0
    agentColor: str = ""


@dataclass
class WorkflowConnection:
    """A connection between two workflow steps."""
    id: str
    fromStepId: str
    toStepId: str


@dataclass
class Workflow:
    """A saved workflow template."""
    id: str
    name: str
    description: str
    category: str
    user_id: str
    steps: List[Dict[str, Any]]
    connections: List[Dict[str, Any]]
    goal: str = ""
    is_custom: bool = True
    created_at: str = ""
    updated_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat().replace('+00:00', 'Z')
        if not self.updated_at:
            self.updated_at = self.created_at


class WorkflowService:
    """Handles workflow persistence using JSON file storage."""
    
    def __init__(self, workflows_file: Path | str = None):
        if workflows_file is None:
            workflows_file = DEFAULT_DATA_DIR / "workflows.json"
        self.workflows_file = Path(workflows_file)
        self.workflows: Dict[str, Workflow] = {}
        
        # Ensure data directory exists
        self.workflows_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Load workflows from JSON file
        self._load_workflows_from_file()
    
    def _load_workflows_from_file(self):
        """Load workflows from JSON file."""
        try:
            with open(self.workflows_file, 'r') as f:
                data = json.load(f)
                for workflow_data in data.get('workflows', []):
                    workflow = Workflow(
                        id=workflow_data['id'],
                        name=workflow_data['name'],
                        description=workflow_data.get('description', ''),
                        category=workflow_data.get('category', 'Custom'),
                        user_id=workflow_data['user_id'],
                        steps=workflow_data.get('steps', []),
                        connections=workflow_data.get('connections', []),
                        goal=workflow_data.get('goal', ''),
                        is_custom=workflow_data.get('is_custom', True),
                        created_at=workflow_data.get('created_at', ''),
                        updated_at=workflow_data.get('updated_at', '')
                    )
                    self.workflows[workflow.id] = workflow
            print(f"[WorkflowService] Loaded {len(self.workflows)} workflows from {self.workflows_file}")
        except FileNotFoundError:
            print(f"[WorkflowService] Workflows file {self.workflows_file} not found, creating empty file")
            self._create_empty_workflows_file()
        except json.JSONDecodeError as e:
            print(f"[WorkflowService] Error parsing {self.workflows_file}: {e}")
            self._create_empty_workflows_file()
        except Exception as e:
            print(f"[WorkflowService] Error loading workflows: {e}")
            self._create_empty_workflows_file()
    
    def _create_empty_workflows_file(self):
        """Create empty workflows file."""
        workflows_data = {"workflows": []}
        with open(self.workflows_file, 'w') as f:
            json.dump(workflows_data, f, indent=2)
        print(f"[WorkflowService] Created empty {self.workflows_file}")
    
    def _save_workflows_to_file(self):
        """Save current workflows to JSON file."""
        workflows_data = {"workflows": []}
        for workflow in self.workflows.values():
            workflow_record = {
                "id": workflow.id,
                "name": workflow.name,
                "description": workflow.description,
                "category": workflow.category,
                "user_id": workflow.user_id,
                "steps": workflow.steps,
                "connections": workflow.connections,
                "goal": workflow.goal,
                "is_custom": workflow.is_custom,
                "created_at": workflow.created_at,
                "updated_at": workflow.updated_at
            }
            workflows_data["workflows"].append(workflow_record)
        
        with open(self.workflows_file, 'w') as f:
            json.dump(workflows_data, f, indent=2)
        print(f"[WorkflowService] Saved {len(self.workflows)} workflows to {self.workflows_file}")
    
    def create_workflow(
        self,
        workflow_id: str,
        name: str,
        user_id: str,
        steps: List[Dict[str, Any]],
        connections: List[Dict[str, Any]],
        description: str = "",
        category: str = "Custom",
        goal: str = ""
    ) -> Workflow:
        """Create a new workflow and save to file."""
        now = datetime.now(UTC).isoformat().replace('+00:00', 'Z')
        
        workflow = Workflow(
            id=workflow_id,
            name=name,
            description=description,
            category=category,
            user_id=user_id,
            steps=steps,
            connections=connections,
            goal=goal,
            is_custom=True,
            created_at=now,
            updated_at=now
        )
        
        self.workflows[workflow.id] = workflow
        self._save_workflows_to_file()
        print(f"[WorkflowService] Created workflow '{name}' (id={workflow_id}) for user {user_id}")
        return workflow
    
    def update_workflow(
        self,
        workflow_id: str,
        user_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        goal: Optional[str] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
        connections: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[Workflow]:
        """Update an existing workflow. Returns None if not found or not owned by user."""
        workflow = self.workflows.get(workflow_id)
        if not workflow:
            return None
        
        # Check ownership
        if workflow.user_id != user_id:
            print(f"[WorkflowService] User {user_id} cannot update workflow {workflow_id} owned by {workflow.user_id}")
            return None
        
        # Update fields
        if name is not None:
            workflow.name = name
        if description is not None:
            workflow.description = description
        if category is not None:
            workflow.category = category
        if goal is not None:
            workflow.goal = goal
        if steps is not None:
            workflow.steps = steps
        if connections is not None:
            workflow.connections = connections
        
        workflow.updated_at = datetime.now(UTC).isoformat().replace('+00:00', 'Z')
        
        self._save_workflows_to_file()
        print(f"[WorkflowService] Updated workflow '{workflow.name}' (id={workflow_id})")
        return workflow
    
    def delete_workflow(self, workflow_id: str, user_id: str) -> bool:
        """Delete a workflow. Returns False if not found or not owned by user."""
        workflow = self.workflows.get(workflow_id)
        if not workflow:
            return False
        
        # Check ownership
        if workflow.user_id != user_id:
            print(f"[WorkflowService] User {user_id} cannot delete workflow {workflow_id} owned by {workflow.user_id}")
            return False
        
        del self.workflows[workflow_id]
        self._save_workflows_to_file()
        print(f"[WorkflowService] Deleted workflow {workflow_id}")
        return True
    
    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get a workflow by ID."""
        return self.workflows.get(workflow_id)
    
    def get_workflow_by_name(self, workflow_name: str) -> Optional[Workflow]:
        """Get a workflow by name (case-insensitive)."""
        for workflow in self.workflows.values():
            if workflow.name.lower() == workflow_name.lower():
                return workflow
        return None
    
    def get_user_workflows(self, user_id: str) -> List[Workflow]:
        """Get all workflows for a specific user."""
        return [w for w in self.workflows.values() if w.user_id == user_id]
    
    def get_all_workflows(self) -> List[Workflow]:
        """Get all workflows (for admin or shared catalog)."""
        return list(self.workflows.values())
    
    def workflow_to_dict(self, workflow: Workflow) -> Dict[str, Any]:
        """Convert a Workflow to a dictionary for JSON response."""
        return {
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "category": workflow.category,
            "user_id": workflow.user_id,
            "steps": workflow.steps,
            "connections": workflow.connections,
            "goal": workflow.goal,
            "isCustom": workflow.is_custom,
            "created_at": workflow.created_at,
            "updated_at": workflow.updated_at
        }


# Singleton instance
_workflow_service: Optional[WorkflowService] = None


def get_workflow_service() -> WorkflowService:
    """Get the singleton WorkflowService instance."""
    global _workflow_service
    if _workflow_service is None:
        _workflow_service = WorkflowService()
    return _workflow_service
