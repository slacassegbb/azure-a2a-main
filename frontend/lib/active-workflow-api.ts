/**
 * Active Workflow API client
 * 
 * Manages session-scoped active workflow state.
 * Supports multiple active workflows for intelligent routing.
 * Unlike localStorage, this syncs across collaborative sessions.
 */

const API_BASE = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000';

export interface ActiveWorkflow {
  id: string;  // Unique identifier for this workflow instance
  workflow: string;  // The workflow steps text
  name: string;
  description?: string;
  goal: string;
}

export interface ActiveWorkflowsState {
  workflows: ActiveWorkflow[];
}

/**
 * Generate a unique ID for a workflow
 */
export function generateWorkflowId(): string {
  return `wf-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * Get the active workflows for a session
 */
export async function getActiveWorkflows(sessionId: string): Promise<ActiveWorkflowsState> {
  const response = await fetch(`${API_BASE}/api/active-workflows?session_id=${encodeURIComponent(sessionId)}`);
  
  if (!response.ok) {
    console.error('[ActiveWorkflow API] Failed to get active workflows:', response.statusText);
    return { workflows: [] };
  }
  
  return response.json();
}

/**
 * Set the active workflows for a session
 * This broadcasts to all users in the collaborative session
 */
export async function setActiveWorkflows(
  sessionId: string, 
  workflows: ActiveWorkflow[]
): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/api/active-workflows?session_id=${encodeURIComponent(sessionId)}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ workflows }),
    });
    
    if (!response.ok) {
      console.error('[ActiveWorkflow API] Failed to set active workflows:', response.statusText);
      return false;
    }
    
    return true;
  } catch (error) {
    console.error('[ActiveWorkflow API] Error setting active workflows:', error);
    return false;
  }
}

/**
 * Add a workflow to the active workflows
 */
export async function addActiveWorkflow(
  sessionId: string,
  workflow: ActiveWorkflow
): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/api/active-workflows/add?session_id=${encodeURIComponent(sessionId)}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(workflow),
    });
    
    if (!response.ok) {
      console.error('[ActiveWorkflow API] Failed to add active workflow:', response.statusText);
      return false;
    }
    
    return true;
  } catch (error) {
    console.error('[ActiveWorkflow API] Error adding active workflow:', error);
    return false;
  }
}

/**
 * Remove a workflow from the active workflows
 */
export async function removeActiveWorkflow(
  sessionId: string,
  workflowId: string
): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/api/active-workflows/${encodeURIComponent(workflowId)}?session_id=${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
    });
    
    if (!response.ok) {
      console.error('[ActiveWorkflow API] Failed to remove active workflow:', response.statusText);
      return false;
    }
    
    return true;
  } catch (error) {
    console.error('[ActiveWorkflow API] Error removing active workflow:', error);
    return false;
  }
}

/**
 * Clear all active workflows for a session
 */
export async function clearActiveWorkflows(sessionId: string): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/api/active-workflows?session_id=${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
    });
    
    if (!response.ok) {
      console.error('[ActiveWorkflow API] Failed to clear active workflows:', response.statusText);
      return false;
    }
    
    return true;
  } catch (error) {
    console.error('[ActiveWorkflow API] Error clearing active workflows:', error);
    return false;
  }
}

// ============================================================================
// LEGACY API - Keep for backward compatibility during migration
// ============================================================================

export interface LegacyActiveWorkflow {
  workflow: string;
  name: string;
  goal: string;
}

/**
 * @deprecated Use getActiveWorkflows instead
 */
export async function getActiveWorkflow(sessionId: string): Promise<LegacyActiveWorkflow> {
  const response = await fetch(`${API_BASE}/api/active-workflow?session_id=${encodeURIComponent(sessionId)}`);
  
  if (!response.ok) {
    console.error('[ActiveWorkflow API] Failed to get active workflow:', response.statusText);
    return { workflow: '', name: '', goal: '' };
  }
  
  return response.json();
}

/**
 * @deprecated Use setActiveWorkflows instead
 */
export async function setActiveWorkflow(
  sessionId: string, 
  workflow: string, 
  name: string, 
  goal: string
): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/api/active-workflow?session_id=${encodeURIComponent(sessionId)}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ workflow, name, goal }),
    });
    
    if (!response.ok) {
      console.error('[ActiveWorkflow API] Failed to set active workflow:', response.statusText);
      return false;
    }
    
    return true;
  } catch (error) {
    console.error('[ActiveWorkflow API] Error setting active workflow:', error);
    return false;
  }
}

/**
 * @deprecated Use clearActiveWorkflows instead
 */
export async function clearActiveWorkflow(sessionId: string): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/api/active-workflow?session_id=${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
    });
    
    if (!response.ok) {
      console.error('[ActiveWorkflow API] Failed to clear active workflow:', response.statusText);
      return false;
    }
    
    return true;
  } catch (error) {
    console.error('[ActiveWorkflow API] Error clearing active workflow:', error);
    return false;
  }
}
