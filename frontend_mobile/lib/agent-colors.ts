export const DEFAULT_AGENT_COLORS = [
  "#ec4899", "#8b5cf6", "#06b6d4", "#10b981", "#f59e0b",
  "#ef4444", "#3b82f6", "#14b8a6", "#f97316", "#a855f7",
]

function hashAgentName(name: string): number {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = ((hash << 5) - hash) + name.charCodeAt(i)
    hash = hash | 0
  }
  return Math.abs(hash)
}

export function getAgentHexColor(agentName: string, dbColor?: string | null): string {
  if (dbColor) return dbColor
  return DEFAULT_AGENT_COLORS[hashAgentName(agentName) % DEFAULT_AGENT_COLORS.length]
}
