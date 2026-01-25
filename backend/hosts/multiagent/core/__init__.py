"""
Core modules for the Foundry Host Agent.

This package contains the foundational components that compose the
FoundryHostAgent2 class through multiple inheritance:

- EventEmitters: WebSocket event emission for real-time UI updates
- AgentRegistry: Agent registration and discovery management
- StreamingHandlers: Task callbacks and response streaming
- MemoryOperations: Memory search and artifact handling
- AzureClients: Azure service client initialization
- WorkflowOrchestration: Multi-agent workflow execution
"""

from .event_emitters import EventEmitters
from .agent_registry import AgentRegistry
from .streaming_handlers import StreamingHandlers
from .memory_operations import MemoryOperations
from .azure_clients import AzureClients
from .workflow_orchestration import WorkflowOrchestration

__all__ = [
    "EventEmitters",
    "AgentRegistry",
    "StreamingHandlers",
    "MemoryOperations",
    "AzureClients",
    "WorkflowOrchestration",
]
