import { API_BASE_URL } from '@/lib/api-config'
import { getAuthHeaders } from '@/lib/auth'
import { getOrCreateSessionId } from '@/lib/session'

export interface RegistryAgent {
  name: string
  description: string
  url: string
  skills?: string[]
  [key: string]: any
}

/**
 * Fetch all agents from backend and enable them for the current session.
 * On mobile, all agents are auto-enabled on startup.
 */
export async function fetchAndEnableAllAgents(): Promise<RegistryAgent[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/agents`)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const data = await response.json()
    const agents: RegistryAgent[] = data.agents || data

    // Enable all agents for the current session
    const sessionId = getOrCreateSessionId()
    await Promise.allSettled(
      agents.map(agent =>
        fetch(`${API_BASE_URL}/agents/session/enable`, {
          method: 'POST',
          headers: getAuthHeaders(),
          body: JSON.stringify({ session_id: sessionId, agent })
        })
      )
    )

    return agents
  } catch (error) {
    console.error('[AgentRegistry] Failed to fetch/enable agents:', error)
    return []
  }
}
