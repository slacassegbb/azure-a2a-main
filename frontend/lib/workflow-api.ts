/**
 * Workflow API client for A2A backend
 * 
 * This provides TypeScript functions to interact with the workflow endpoints.
 * Workflows are persisted server-side and can be shared across browsers/devices.
 */

import { logDebug } from '@/lib/debug'

const API_BASE_URL = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'

export interface WorkflowStep {
  id: string
  agentId: string
  agentName: string
  description: string
  order: number
  x?: number
  y?: number
  agentColor?: string
}

export interface WorkflowConnection {
  id: string
  fromStepId: string
  toStepId: string
  condition?: "true" | "false"  // For evaluation step branching
}

export interface Workflow {
  id: string
  name: string
  description: string
  category: string
  user_id: string
  steps: WorkflowStep[]
  connections: WorkflowConnection[]
  goal?: string
  isCustom: boolean
  created_at: string
  updated_at: string
}

export interface WorkflowCreateRequest {
  id: string
  name: string
  description?: string
  category?: string
  steps: WorkflowStep[]
  connections: WorkflowConnection[]
  goal?: string
}

export interface WorkflowUpdateRequest {
  name?: string
  description?: string
  category?: string
  steps?: WorkflowStep[]
  connections?: WorkflowConnection[]
  goal?: string
}

/**
 * Get auth token from storage
 */
function getAuthToken(): string | null {
  if (typeof window === 'undefined') return null
  return sessionStorage.getItem('auth_token') || localStorage.getItem('auth_token')
}

/**
 * Get authorization headers
 */
function getAuthHeaders(): HeadersInit {
  const token = getAuthToken()
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return headers
}

/**
 * Get all workflows for the current user (requires authentication)
 */
export async function getUserWorkflows(): Promise<Workflow[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/workflows`, {
      method: 'GET',
      headers: getAuthHeaders(),
    })

    if (!response.ok) {
      if (response.status === 401) {
        console.warn('[WorkflowAPI] User not authenticated, returning empty workflows')
        return []
      }
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }

    const data = await response.json()
    return data.workflows || []
  } catch (error) {
    console.error('[WorkflowAPI] Failed to get user workflows:', error)
    return []
  }
}

/**
 * Create a new workflow (requires authentication)
 */
export async function createWorkflow(workflow: WorkflowCreateRequest): Promise<Workflow | null> {
  try {
    const token = getAuthToken()
    if (!token) {
      console.warn('[WorkflowAPI] Cannot create workflow: user not authenticated')
      return null
    }

    const response = await fetch(`${API_BASE_URL}/api/workflows`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(workflow),
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      throw new Error(error.detail || `HTTP ${response.status}: ${response.statusText}`)
    }

    const data = await response.json()
    logDebug('[WorkflowAPI] Workflow created/updated:', data.message)
    return data.workflow || null
  } catch (error) {
    console.error('[WorkflowAPI] Failed to create workflow:', error)
    return null
  }
}

/**
 * Update an existing workflow (requires authentication)
 */
export async function updateWorkflow(workflowId: string, updates: WorkflowUpdateRequest): Promise<Workflow | null> {
  try {
    const token = getAuthToken()
    if (!token) {
      console.warn('[WorkflowAPI] Cannot update workflow: user not authenticated')
      return null
    }

    const response = await fetch(`${API_BASE_URL}/api/workflows/${workflowId}`, {
      method: 'PUT',
      headers: getAuthHeaders(),
      body: JSON.stringify(updates),
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      throw new Error(error.detail || `HTTP ${response.status}: ${response.statusText}`)
    }

    const data = await response.json()
    logDebug('[WorkflowAPI] Workflow updated:', data.message)
    return data.workflow || null
  } catch (error) {
    console.error('[WorkflowAPI] Failed to update workflow:', error)
    return null
  }
}

/**
 * Delete a workflow (requires authentication)
 */
export async function deleteWorkflow(workflowId: string): Promise<boolean> {
  try {
    const token = getAuthToken()
    if (!token) {
      console.warn('[WorkflowAPI] Cannot delete workflow: user not authenticated')
      return false
    }

    const response = await fetch(`${API_BASE_URL}/api/workflows/${workflowId}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    })

    if (!response.ok) {
      if (response.status === 404) {
        console.warn('[WorkflowAPI] Workflow not found or access denied')
        return false
      }
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }

    logDebug('[WorkflowAPI] Workflow deleted')
    return true
  } catch (error) {
    console.error('[WorkflowAPI] Failed to delete workflow:', error)
    return false
  }
}

/**
 * Check if user is authenticated (has token)
 */
export function isAuthenticated(): boolean {
  return getAuthToken() !== null
}
