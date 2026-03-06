/**
 * Shared agent registry utilities.
 *
 * Used by both agent-catalog.tsx and visual-workflow-designer.tsx to
 * fetch agents from the backend registry and health-check them with
 * local→production URL fallback.
 */

import { API_BASE_URL } from '@/lib/api-config'

/** Raw agent shape returned by GET /api/agents */
export interface RegistryAgent {
  name: string
  description: string
  url: string
  production_url?: string
  color?: string
  version?: string
  skills?: string[]
  capabilities?: string[]
  defaultInputModes?: string[]
  defaultOutputModes?: string[]
  [key: string]: any            // pass-through for extra fields
}

/** Minimal common shape after transform (components can extend) */
export interface BaseAgent {
  id: string
  name: string
  description: string
  endpoint: string
  productionUrl?: string
  color?: string
  iconUrl?: string | null
  skills?: string[]
  /** The full raw payload, so consumers can map extra fields */
  _raw: RegistryAgent
}

// ---------------------------------------------------------------------------
// Health check
// ---------------------------------------------------------------------------

/**
 * Check whether a single agent URL is reachable via the backend health proxy.
 */
export async function checkAgentHealth(url: string): Promise<boolean> {
  try {
    const urlParts = url.replace('http://', '').replace('https://', '')
    const res = await fetch(`${API_BASE_URL}/api/agents/health/${urlParts}`)
    if (res.ok) {
      const data = await res.json()
      return data.success && data.online === true
    }
  } catch {
    /* offline */
  }
  return false
}

/**
 * Health-check with local→production fallback.
 *
 * Returns the agent with `endpoint` set to whichever URL responded,
 * or `null` if neither is reachable.
 */
export async function checkAgentHealthWithFallback<T extends { endpoint: string; productionUrl?: string }>(
  agent: T
): Promise<(T & { endpoint: string }) | null> {
  // Try primary URL first (local when running locally)
  if (await checkAgentHealth(agent.endpoint)) return agent

  // Fallback: try production URL if it differs
  if (agent.productionUrl && agent.productionUrl !== agent.endpoint) {
    if (await checkAgentHealth(agent.productionUrl)) {
      return { ...agent, endpoint: agent.productionUrl }
    }
  }

  return null
}

// ---------------------------------------------------------------------------
// Environment filtering
// ---------------------------------------------------------------------------

const isProduction = !API_BASE_URL.includes('localhost')

/**
 * Filter agents to only those reachable in the current environment.
 *
 * In production: exclude agents that only have localhost URLs, and prefer
 * the production URL as the endpoint.
 * In dev: keep everything as-is.
 */
export function filterAgentsForEnvironment<T extends { endpoint: string; productionUrl?: string }>(
  agents: T[]
): T[] {
  if (!isProduction) return agents

  return agents
    .map((agent) => {
      // In production, prefer the production URL
      if (agent.productionUrl && !agent.productionUrl.includes('localhost')) {
        return { ...agent, endpoint: agent.productionUrl }
      }
      // Primary endpoint is already a production URL
      if (!agent.endpoint.includes('localhost')) return agent
      // Only has localhost URLs — not usable in production
      return null
    })
    .filter(Boolean) as T[]
}

// ---------------------------------------------------------------------------
// Fetch + transform
// ---------------------------------------------------------------------------

/**
 * Fetch all agents from the registry and return them as `BaseAgent[]`.
 *
 * Does NOT run health checks — call `checkAgentHealthWithFallback` on each
 * entry (or use `fetchOnlineAgents`) for that.
 */
export async function fetchRegistryAgents(): Promise<BaseAgent[]> {
  const response = await fetch(`${API_BASE_URL}/api/agents`)
  if (!response.ok) throw new Error(`Failed to fetch agents: ${response.status}`)

  const data = await response.json()
  const agents: RegistryAgent[] = data.agents || data

  return agents.map((agent) => ({
    id: agent.name.toLowerCase().replace(/\s+/g, '-'),
    name: agent.name,
    description: agent.description,
    endpoint: agent.url,
    productionUrl: agent.production_url,
    color: agent.color,
    iconUrl: agent.logo_url || null,
    skills: agent.skills,
    _raw: agent,
  }))
}

/**
 * Fetch all agents, health-check each (with fallback), and return only those
 * that are online.  Useful for the workflow designer palette.
 */
export async function fetchOnlineAgents(): Promise<BaseAgent[]> {
  const agents = await fetchRegistryAgents()
  const results = await Promise.all(
    agents.map((agent) => checkAgentHealthWithFallback(agent))
  )
  return results.filter(Boolean) as BaseAgent[]
}
