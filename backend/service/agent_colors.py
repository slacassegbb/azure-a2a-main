"""
Canonical agent color palette and auto-assignment logic.

The 10 colors in this palette are the single source of truth.
When an agent registers without specifying a color, one is auto-assigned
using a deterministic hash of the agent name, so the same name always
gets the same color.
"""

DEFAULT_AGENT_COLORS = [
    "#ec4899",  # pink
    "#8b5cf6",  # purple
    "#06b6d4",  # cyan
    "#10b981",  # emerald
    "#f59e0b",  # amber
    "#ef4444",  # red
    "#3b82f6",  # blue
    "#14b8a6",  # teal
    "#f97316",  # orange
    "#a855f7",  # violet
]


def hash_agent_name(name: str) -> int:
    """Deterministic hash matching the frontend's hashAgentName()."""
    hash_val = 0
    for ch in name:
        hash_val = ((hash_val << 5) - hash_val) + ord(ch)
        hash_val = hash_val & 0xFFFFFFFF  # 32-bit
    return hash_val


def assign_color_for_agent(name: str) -> str:
    """Return a deterministic hex color for an agent name."""
    index = hash_agent_name(name) % len(DEFAULT_AGENT_COLORS)
    return DEFAULT_AGENT_COLORS[index]
