/**
 * Canonical agent color palette and utilities.
 * The database is the source of truth for agent colors.
 * This palette is ONLY used as a fallback when the database color is unavailable.
 */

export const DEFAULT_AGENT_COLORS = [
  "#ec4899", // pink
  "#8b5cf6", // purple
  "#06b6d4", // cyan
  "#10b981", // emerald
  "#f59e0b", // amber
  "#ef4444", // red
  "#3b82f6", // blue
  "#14b8a6", // teal
  "#f97316", // orange
  "#a855f7", // violet
]

const HEX_TO_TAILWIND: Record<string, { text: string; bg: string }> = {
  "#ec4899": { text: "text-pink-400", bg: "bg-pink-950" },
  "#8b5cf6": { text: "text-purple-400", bg: "bg-purple-950" },
  "#06b6d4": { text: "text-cyan-400", bg: "bg-cyan-950" },
  "#10b981": { text: "text-emerald-400", bg: "bg-emerald-950" },
  "#f59e0b": { text: "text-amber-400", bg: "bg-amber-950" },
  "#ef4444": { text: "text-red-400", bg: "bg-red-950" },
  "#3b82f6": { text: "text-blue-400", bg: "bg-blue-950" },
  "#14b8a6": { text: "text-teal-400", bg: "bg-teal-950" },
  "#f97316": { text: "text-orange-400", bg: "bg-orange-950" },
  "#a855f7": { text: "text-violet-400", bg: "bg-violet-950" },
}

function hashAgentName(name: string): number {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = ((hash << 5) - hash) + name.charCodeAt(i)
    hash = hash | 0  // Convert to 32-bit signed integer (matches Python's & 0xFFFFFFFF)
  }
  return Math.abs(hash)
}

/**
 * Get the hex color for an agent.
 * Prefers the color from the database (agent.color), falls back to hash.
 */
export function getAgentHexColor(agentName: string, dbColor?: string | null): string {
  if (dbColor) return dbColor
  return DEFAULT_AGENT_COLORS[hashAgentName(agentName) % DEFAULT_AGENT_COLORS.length]
}

/**
 * Get Tailwind text class for an agent color.
 */
export function getAgentTextClass(agentName: string, dbColor?: string | null): string {
  const hex = getAgentHexColor(agentName, dbColor)
  return HEX_TO_TAILWIND[hex]?.text ?? "text-purple-400"
}

/**
 * Get Tailwind bg class for an agent color.
 */
export function getAgentBgClass(agentName: string, dbColor?: string | null): string {
  const hex = getAgentHexColor(agentName, dbColor)
  return HEX_TO_TAILWIND[hex]?.bg ?? "bg-purple-950"
}

/**
 * Get full display info (hex + Tailwind classes) for an agent.
 */
export function getAgentDisplayColors(agentName: string, dbColor?: string | null) {
  const hex = getAgentHexColor(agentName, dbColor)
  const tw = HEX_TO_TAILWIND[hex]
  return {
    hex,
    color: tw?.text ?? "text-purple-400",
    bgColor: tw?.bg ?? "bg-purple-950",
  }
}
