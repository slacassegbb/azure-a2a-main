/**
 * Active Workflow API client
 * 
 * Manages session-scoped active workflow state.
 * Unlike localStorage, this syncs across collaborative sessions.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:12000';

export interface ActiveWorkflow {
  workflow: string;
  name: string;
  goal: string;
}

/**
 * Get the active workflow for a session
 */
export async function getActiveWorkflow(sessionId: string): Promise<ActiveWorkflow> {
  const response = await fetch(`${API_BASE}/api/active-workflow?session_id=${encodeURIComponent(sessionId)}`);
  
  if (!response.ok) {
    console.error('[ActiveWorkflow API] Failed to get active workflow:', response.statusText);
    return { workflow: '', name: '', goal: '' };
  }
  
  return response.json();
}

/**
 * Set the active workflow for a session
 * This broadcasts to all users in the collaborative session
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
 * Clear the active workflow for a session
 * This broadcasts to all users in the collaborative session
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
