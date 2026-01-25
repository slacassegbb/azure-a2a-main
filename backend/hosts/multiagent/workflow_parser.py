"""
Workflow Parser for the Foundry Host Agent.

Parses workflow text into structured groups with parallel execution support.
"""

import re
from typing import Dict, List, Optional

from .models import (
    ParsedWorkflow,
    ParsedWorkflowStep,
    ParsedWorkflowGroup,
    WorkflowStepType,
)


class WorkflowParser:
    """
    Parse workflow text into structured groups with parallel execution support.
    
    Workflow Text Format:
    - Sequential steps: "1. Do something", "2. Do another thing"
    - Parallel steps: "2a. First parallel task", "2b. Second parallel task"
    
    Example:
        1. Use Classification agent to analyze document
        2a. Use Branding agent to check guidelines
        2b. Use Legal agent to verify compliance
        3. Use Reporter agent to synthesize results
        
    In this example:
    - Step 1 runs first (sequential)
    - Steps 2a and 2b run in parallel
    - Step 3 runs after both 2a and 2b complete
    """
    
    # Regex to match step labels like "1.", "2a.", "2b.", "10c."
    STEP_PATTERN = re.compile(r'^(\d+)([a-z])?\.?\s*(.+)$', re.IGNORECASE)
    
    @classmethod
    def parse(cls, workflow_text: str) -> ParsedWorkflow:
        """Parse workflow text into structured groups."""
        if not workflow_text or not workflow_text.strip():
            return ParsedWorkflow(groups=[])
        
        lines = workflow_text.strip().split('\n')
        steps_by_number: Dict[int, List[ParsedWorkflowStep]] = {}
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Try to match step pattern
            match = cls.STEP_PATTERN.match(line)
            if match:
                main_number = int(match.group(1))
                sub_letter = match.group(2)  # Could be None for "1.", or "a" for "1a."
                description = match.group(3).strip()
                
                # Create step label
                if sub_letter:
                    step_label = f"{main_number}{sub_letter.lower()}"
                else:
                    step_label = str(main_number)
                
                # Extract agent hint if agent name is mentioned
                agent_hint = cls._extract_agent_hint(description)
                
                step = ParsedWorkflowStep(
                    step_label=step_label,
                    description=description,
                    agent_hint=agent_hint
                )
                
                if main_number not in steps_by_number:
                    steps_by_number[main_number] = []
                steps_by_number[main_number].append(step)
        
        # Convert to groups
        groups = []
        for main_number in sorted(steps_by_number.keys()):
            steps = steps_by_number[main_number]
            
            if len(steps) > 1:
                # Multiple steps with same number = parallel
                group_type = WorkflowStepType.PARALLEL
            else:
                group_type = WorkflowStepType.SEQUENTIAL
            
            groups.append(ParsedWorkflowGroup(
                group_number=main_number,
                group_type=group_type,
                steps=steps
            ))
        
        return ParsedWorkflow(groups=groups)
    
    @staticmethod
    def _extract_agent_hint(description: str) -> Optional[str]:
        """Try to extract agent name from description like 'Use the Classification agent to...'"""
        # Pattern: "Use (the)? <AgentName> agent"
        match = re.search(r'[Uu]se\s+(?:the\s+)?(\w+)\s+agent', description)
        if match:
            return match.group(1)
        return None
