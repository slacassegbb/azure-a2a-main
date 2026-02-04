// API URL: Uses environment variable, or falls back to same-origin (for reverse proxy setups)
// For Azure Container Apps: Set NEXT_PUBLIC_A2A_API_URL at build time
// Or use a reverse proxy to route /api/* to the backend
function getApiBaseUrl(): string {
  // Build-time environment variable (Next.js)
  if (process.env.NEXT_PUBLIC_A2A_API_URL) {
    return process.env.NEXT_PUBLIC_A2A_API_URL;
  }
  
  // Runtime: check for window config (can be injected via script tag)
  if (typeof window !== 'undefined' && (window as { __API_URL__?: string }).__API_URL__) {
    return (window as { __API_URL__?: string }).__API_URL__!;
  }
  
  // Default: localhost for development
  return 'http://localhost:12000';
}

const API_BASE_URL = getApiBaseUrl();

export interface UserInfo {
  user_id: string;
  email: string;
  name: string;
  role: string;
  description?: string;
  skills?: string[];
  color: string;
}

export interface LoginResponse {
  success: boolean;
  access_token?: string;
  user_info?: UserInfo;
  message?: string;
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  category: string;
  user_id: string;
  steps: WorkflowStep[];
  connections: WorkflowConnection[];
  goal?: string;
  isCustom: boolean;
  created_at: string;
  updated_at: string;
}

export interface WorkflowStep {
  id: string;
  agentId: string;
  agentName: string;
  description: string;
  order: number;
}

export interface WorkflowConnection {
  id: string;
  fromStepId: string;
  toStepId: string;
}

export interface Agent {
  name: string;
  description: string;
  url: string;
  version?: string;
  iconUrl?: string;
  provider?: {
    organization?: string;
  };
  capabilities?: {
    streaming?: boolean;
    pushNotifications?: boolean;
  };
  skills?: Array<{
    name: string;
    description?: string;
  }>;
  status: 'online' | 'offline';
}

function getAuthToken(): string | null {
  if (typeof window === 'undefined') return null;
  return sessionStorage.getItem('auth_token');
}

function getAuthHeaders(): HeadersInit {
  const token = getAuthToken();
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email, password }),
    });

    const data = await response.json();
    return data;
  } catch (error) {
    console.error('[API] Login error:', error);
    return {
      success: false,
      message: 'Unable to connect to server',
    };
  }
}

export async function getUserWorkflows(): Promise<Workflow[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/workflows`, {
      method: 'GET',
      headers: getAuthHeaders(),
    });

    if (!response.ok) {
      if (response.status === 401) {
        console.warn('[API] User not authenticated');
        return [];
      }
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();
    return data.workflows || [];
  } catch (error) {
    console.error('[API] Failed to get workflows:', error);
    return [];
  }
}

// Schedule info (lightweight)
export interface ScheduleInfo {
  id: string;
  workflow_id: string;
  schedule_type: string;
  enabled: boolean;
  next_run?: string;
  workflow_name?: string;
}

// Map of workflow_id -> ScheduleInfo for workflows that have schedules
export type WorkflowScheduleMap = Map<string, ScheduleInfo>;

export async function getWorkflowSchedules(): Promise<WorkflowScheduleMap> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/schedules`, {
      method: 'GET',
      headers: getAuthHeaders(),
    });

    if (!response.ok) {
      return new Map();
    }

    const data = await response.json();
    const schedules: ScheduleInfo[] = data.schedules || [];
    
    // Return map of workflow_id -> schedule info
    const scheduleMap = new Map<string, ScheduleInfo>();
    for (const schedule of schedules) {
      // If multiple schedules for same workflow, prefer enabled ones
      const existing = scheduleMap.get(schedule.workflow_id);
      if (!existing || (schedule.enabled && !existing.enabled)) {
        scheduleMap.set(schedule.workflow_id, schedule);
      }
    }
    return scheduleMap;
  } catch (error) {
    console.error('[API] Failed to get schedules:', error);
    return new Map();
  }
}

export async function toggleSchedule(scheduleId: string, enabled: boolean): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/schedules/${scheduleId}/toggle?enabled=${enabled}`, {
      method: 'POST',
      headers: getAuthHeaders(),
    });

    if (!response.ok) {
      console.error('[API] Failed to toggle schedule:', response.statusText);
      return false;
    }

    return true;
  } catch (error) {
    console.error('[API] Failed to toggle schedule:', error);
    return false;
  }
}

export async function getAgents(): Promise<Agent[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/agents`, {
      method: 'GET',
      headers: getAuthHeaders(),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();
    
    // Transform agent data
    const agents: Agent[] = (data.agents || []).map((agent: Record<string, unknown>) => ({
      name: agent.name as string,
      description: agent.description as string || '',
      url: agent.url as string || '',
      version: agent.version as string || '',
      iconUrl: agent.iconUrl as string || null,
      provider: agent.provider as { organization?: string } || null,
      capabilities: agent.capabilities as { streaming?: boolean; pushNotifications?: boolean } || {},
      skills: agent.skills as Array<{ name: string; description?: string }> || [],
      status: agent.status === 'online' ? 'online' : 'offline',
    }));

    return agents;
  } catch (error) {
    console.error('[API] Failed to get agents:', error);
    return [];
  }
}

// Session-based agent management
let sessionId: string | null = null;

function getOrCreateSessionId(): string {
  if (typeof window === 'undefined') return 'server-session';
  
  if (!sessionId) {
    sessionId = sessionStorage.getItem('a2a_session_id');
    if (!sessionId) {
      sessionId = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      sessionStorage.setItem('a2a_session_id', sessionId);
    }
  }
  return sessionId;
}

export function getSessionId(): string {
  return getOrCreateSessionId();
}

export async function getSessionAgents(): Promise<Agent[]> {
  try {
    const sid = getOrCreateSessionId();
    const response = await fetch(`${API_BASE_URL}/agents/session?session_id=${sid}`, {
      method: 'GET',
      headers: getAuthHeaders(),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();
    return (data.agents || []).map((agent: Record<string, unknown>) => ({
      name: agent.name as string,
      description: agent.description as string || '',
      url: agent.url as string || '',
      version: agent.version as string || '',
      iconUrl: agent.iconUrl as string || null,
      provider: agent.provider as { organization?: string } || null,
      capabilities: agent.capabilities as { streaming?: boolean; pushNotifications?: boolean } || {},
      skills: agent.skills as Array<{ name: string; description?: string }> || [],
      status: 'online' as const, // Session agents are always considered online
    }));
  } catch (error) {
    console.error('[API] Failed to get session agents:', error);
    return [];
  }
}

export async function enableSessionAgent(agent: Agent): Promise<boolean> {
  try {
    const sid = getOrCreateSessionId();
    const response = await fetch(`${API_BASE_URL}/agents/session/enable`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        session_id: sid,
        agent: {
          name: agent.name,
          description: agent.description,
          url: agent.url,
          version: agent.version,
          capabilities: agent.capabilities,
          skills: agent.skills,  // Include skills for orchestrator routing
          provider: agent.provider,
        }
      }),
    });

    return response.ok;
  } catch (error) {
    console.error('[API] Failed to enable agent:', error);
    return false;
  }
}

export async function disableSessionAgent(agentUrl: string): Promise<boolean> {
  try {
    const sid = getOrCreateSessionId();
    const response = await fetch(`${API_BASE_URL}/agents/session/disable`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        session_id: sid,
        agent_url: agentUrl,
      }),
    });

    return response.ok;
  } catch (error) {
    console.error('[API] Failed to disable agent:', error);
    return false;
  }
}

// ============ Workflow Activation (Database-backed via API) ============

// In-memory cache for activated workflow IDs (synced with backend)
let _activatedWorkflowsCache: Set<string> = new Set();
let _cacheSessionId: string | null = null;

/**
 * Fetch activated workflow IDs from backend API
 * This should be called once on page load with the user's session ID
 */
export async function fetchActivatedWorkflowIds(sessionId: string): Promise<Set<string>> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/active-workflows?session_id=${encodeURIComponent(sessionId)}`);
    if (!response.ok) {
      console.error('[API] Failed to fetch activated workflows:', response.statusText);
      return new Set();
    }
    const data = await response.json();
    const workflows = data.workflows || [];
    const ids = new Set<string>(workflows.map((w: { id?: string }) => w.id).filter(Boolean));
    
    // Update cache
    _activatedWorkflowsCache = ids;
    _cacheSessionId = sessionId;
    
    console.log(`[API] Loaded ${ids.size} activated workflows from database`);
    return ids;
  } catch (error) {
    console.error('[API] Failed to fetch activated workflows:', error);
    return new Set();
  }
}

/**
 * Get activated workflow IDs from cache (synchronous)
 * Call fetchActivatedWorkflowIds first to populate the cache
 */
export function getActivatedWorkflowIds(): Set<string> {
  return new Set(_activatedWorkflowsCache);
}

/**
 * Save activated workflow IDs to backend API
 * Also updates the local cache
 */
export async function saveActivatedWorkflowIdsAsync(sessionId: string, ids: Set<string>, workflows: Workflow[]): Promise<void> {
  // Update cache immediately
  _activatedWorkflowsCache = new Set(ids);
  _cacheSessionId = sessionId;
  
  try {
    // Build workflow data array from IDs
    const workflowData = Array.from(ids).map(id => {
      const workflow = workflows.find(w => w.id === id);
      return {
        id,
        workflow: workflow?.steps?.map((s, i) => `${i + 1}. [${s.agentName}] ${s.description}`).join('\n') || '',
        name: workflow?.name || '',
        goal: workflow?.goal || workflow?.description || '',
        description: workflow?.description || ''
      };
    });
    
    const response = await fetch(`${API_BASE_URL}/api/active-workflows?session_id=${encodeURIComponent(sessionId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workflows: workflowData })
    });
    
    if (!response.ok) {
      console.error('[API] Failed to save activated workflows:', response.statusText);
    }
  } catch (error) {
    console.error('[API] Failed to save activated workflows:', error);
  }
}

/**
 * Legacy sync function for backward compatibility
 * This just updates the cache - actual save happens via saveActivatedWorkflowIdsAsync
 */
export function saveActivatedWorkflowIds(ids: Set<string>): void {
  _activatedWorkflowsCache = new Set(ids);
}

export function activateWorkflow(workflowId: string): void {
  _activatedWorkflowsCache.add(workflowId);
}

export function deactivateWorkflow(workflowId: string): void {
  _activatedWorkflowsCache.delete(workflowId);
}

export function isWorkflowActivated(workflowId: string): boolean {
  return _activatedWorkflowsCache.has(workflowId);
}

