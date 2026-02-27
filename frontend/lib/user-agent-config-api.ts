/**
 * API utilities for per-user agent configuration.
 *
 * Users configure agent-specific credentials (e.g., phone numbers, API keys)
 * which are stored encrypted on the backend. These functions manage that config.
 */

import { API_BASE_URL } from './api-config'
import { getAuthHeaders } from './auth'

export interface AgentConfigStatus {
  agent_name: string
  is_configured: boolean
  created_at?: string
  updated_at?: string
}

export interface AgentConfigDetail {
  config_data: Record<string, string> | null
  is_configured: boolean
}

export interface ConfigSchemaField {
  key: string
  label: string
  type: 'text' | 'password' | 'tel' | 'email' | 'url' | 'number'
  required: boolean
  description?: string
  placeholder?: string
}

/**
 * Get config status for all agents the current user has configured.
 * Returns status only (no secrets) — use getAgentConfig for values.
 */
export async function getUserAgentConfigs(): Promise<AgentConfigStatus[]> {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/user-agent-config`, {
      headers: getAuthHeaders(),
    })
    if (!resp.ok) return []
    const data = await resp.json()
    return data.success ? data.configs : []
  } catch {
    return []
  }
}

/**
 * Get decrypted config values for a specific agent (for form pre-fill).
 */
export async function getAgentConfig(agentName: string): Promise<AgentConfigDetail | null> {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/user-agent-config/${encodeURIComponent(agentName)}`, {
      headers: getAuthHeaders(),
    })
    if (!resp.ok) return null
    const data = await resp.json()
    return data.success ? { config_data: data.config_data, is_configured: data.is_configured } : null
  } catch {
    return null
  }
}

/**
 * Save or update config for an agent.
 */
export async function saveAgentConfig(agentName: string, configData: Record<string, string>): Promise<boolean> {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/user-agent-config/${encodeURIComponent(agentName)}`, {
      method: 'PUT',
      headers: getAuthHeaders(),
      body: JSON.stringify({ config_data: configData }),
    })
    if (!resp.ok) return false
    const data = await resp.json()
    return data.success
  } catch {
    return false
  }
}

/**
 * Delete config for an agent.
 */
export async function deleteAgentConfig(agentName: string): Promise<boolean> {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/user-agent-config/${encodeURIComponent(agentName)}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    })
    if (!resp.ok) return false
    const data = await resp.json()
    return data.success
  } catch {
    return false
  }
}
