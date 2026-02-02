/**
 * Scheduler API client for managing scheduled workflows
 */

export type ScheduleType = 'once' | 'interval' | 'daily' | 'weekly' | 'monthly' | 'cron';

export interface ScheduledWorkflow {
  id: string;
  workflow_id: string;
  workflow_name: string;
  session_id: string;
  schedule_type: ScheduleType;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  last_run: string | null;
  next_run: string | null;
  run_count: number;
  
  // Execution status tracking
  last_status: 'success' | 'failed' | 'running' | null;
  last_error: string | null;
  success_count: number;
  failure_count: number;
  
  // Schedule parameters
  run_at?: string;
  interval_minutes?: number;
  time_of_day?: string;
  days_of_week?: number[];
  day_of_month?: number;
  cron_expression?: string;
  timezone: string;
  
  // Execution settings
  timeout: number;
  retry_on_failure: boolean;
  max_retries: number;
  max_runs: number | null;  // Maximum number of times to run (null = unlimited)
  
  // Metadata
  description?: string;
  tags: string[];
  workflow_goal?: string;  // Goal from workflow designer
}

export interface CreateScheduleRequest {
  workflow_id: string;
  workflow_name: string;
  session_id: string;
  schedule_type: ScheduleType;
  enabled?: boolean;
  
  // Schedule parameters
  run_at?: string;
  interval_minutes?: number;
  time_of_day?: string;
  days_of_week?: number[];
  day_of_month?: number;
  cron_expression?: string;
  timezone?: string;
  
  // Execution settings
  timeout?: number;
  retry_on_failure?: boolean;
  max_retries?: number;
  max_runs?: number | null;  // Maximum number of times to run (null = unlimited)
  
  // Metadata
  description?: string;
  tags?: string[];
  workflow_goal?: string;  // Goal from workflow designer
}

export interface UpdateScheduleRequest {
  enabled?: boolean;
  schedule_type?: ScheduleType;
  run_at?: string;
  interval_minutes?: number;
  time_of_day?: string;
  days_of_week?: number[];
  day_of_month?: number;
  cron_expression?: string;
  timezone?: string;
  timeout?: number;
  retry_on_failure?: boolean;
  max_retries?: number;
  description?: string;
  tags?: string[];
}

export interface UpcomingRun {
  schedule_id: string;
  workflow_id: string;
  workflow_name: string;
  next_run: string;
  schedule_type: ScheduleType;
}

export interface RunHistoryItem {
  run_id: string;
  schedule_id: string;
  workflow_id: string;
  workflow_name: string;
  timestamp: string;
  started_at: string;
  completed_at: string;
  duration_seconds: number;
  status: 'success' | 'failed';
  error: string | null;
  result: string | null;  // The actual workflow output/result
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:12000';

/**
 * Get auth token from storage
 */
function getAuthToken(): string | null {
  if (typeof window === 'undefined') return null;
  return sessionStorage.getItem('auth_token') || localStorage.getItem('auth_token');
}

/**
 * Get authorization headers
 */
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

/**
 * List all scheduled workflows, optionally filtered by session
 */
export async function listSchedules(workflowId?: string, sessionId?: string): Promise<ScheduledWorkflow[]> {
  const params = new URLSearchParams();
  if (workflowId) params.append('workflow_id', workflowId);
  if (sessionId) params.append('session_id', sessionId);
  
  const queryString = params.toString();
  const url = queryString 
    ? `${API_BASE}/api/schedules?${queryString}`
    : `${API_BASE}/api/schedules`;
  
  const response = await fetch(url, {
    headers: getAuthHeaders()
  });
  if (!response.ok) {
    throw new Error(`Failed to list schedules: ${response.statusText}`);
  }
  
  const data = await response.json();
  return data.schedules;
}

/**
 * Get upcoming scheduled runs
 */
export async function getUpcomingRuns(limit: number = 10): Promise<UpcomingRun[]> {
  const response = await fetch(`${API_BASE}/api/schedules/upcoming?limit=${limit}`, {
    headers: getAuthHeaders()
  });
  if (!response.ok) {
    throw new Error(`Failed to get upcoming runs: ${response.statusText}`);
  }
  
  const data = await response.json();
  return data.upcoming;
}

/**
 * Get a specific schedule
 */
export async function getSchedule(scheduleId: string): Promise<ScheduledWorkflow> {
  const response = await fetch(`${API_BASE}/api/schedules/${scheduleId}`, {
    headers: getAuthHeaders()
  });
  if (!response.ok) {
    throw new Error(`Failed to get schedule: ${response.statusText}`);
  }
  
  return response.json();
}

/**
 * Create a new scheduled workflow
 */
export async function createSchedule(request: CreateScheduleRequest): Promise<ScheduledWorkflow> {
  const response = await fetch(`${API_BASE}/api/schedules`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(request),
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || 'Failed to create schedule');
  }
  
  const data = await response.json();
  return data.schedule;
}

/**
 * Update a scheduled workflow
 */
export async function updateSchedule(scheduleId: string, request: UpdateScheduleRequest): Promise<ScheduledWorkflow> {
  const response = await fetch(`${API_BASE}/api/schedules/${scheduleId}`, {
    method: 'PUT',
    headers: getAuthHeaders(),
    body: JSON.stringify(request),
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || 'Failed to update schedule');
  }
  
  const data = await response.json();
  return data.schedule;
}

/**
 * Delete a scheduled workflow
 */
export async function deleteSchedule(scheduleId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/schedules/${scheduleId}`, {
    method: 'DELETE',
    headers: getAuthHeaders()
  });
  
  if (!response.ok) {
    throw new Error(`Failed to delete schedule: ${response.statusText}`);
  }
}

/**
 * Toggle a schedule enabled/disabled
 */
export async function toggleSchedule(scheduleId: string, enabled: boolean): Promise<ScheduledWorkflow> {
  const response = await fetch(`${API_BASE}/api/schedules/${scheduleId}/toggle?enabled=${enabled}`, {
    method: 'POST',
    headers: getAuthHeaders()
  });
  
  if (!response.ok) {
    throw new Error(`Failed to toggle schedule: ${response.statusText}`);
  }
  
  const data = await response.json();
  return data.schedule;
}

/**
 * Run a scheduled workflow immediately
 * @param scheduleId - The schedule ID to run
 * @param sessionId - Optional session ID to use instead of the schedule's default.
 *                    When provided from UI, the workflow will appear in the user's current chat.
 * @param wait - If true, wait for workflow completion and return full results
 */
export async function runScheduleNow(scheduleId: string, sessionId?: string, wait?: boolean): Promise<{ success: boolean; message: string; result?: string }> {
  const url = new URL(`${API_BASE}/api/schedules/${scheduleId}/run-now`);
  if (sessionId) {
    url.searchParams.set('session_id', sessionId);
  }
  if (wait) {
    url.searchParams.set('wait', 'true');
  }
  
  const response = await fetch(url.toString(), {
    method: 'POST',
    headers: getAuthHeaders()
  });
  
  if (!response.ok) {
    throw new Error(`Failed to run schedule: ${response.statusText}`);
  }
  
  return response.json();
}

/**
 * Get run history, optionally filtered by session
 */
export async function getScheduleHistory(scheduleId?: string, sessionId?: string, limit: number = 50): Promise<RunHistoryItem[]> {
  const params = new URLSearchParams();
  if (scheduleId) params.append('schedule_id', scheduleId);
  if (sessionId) params.append('session_id', sessionId);
  params.append('limit', limit.toString());
  
  const url = `${API_BASE}/api/schedules/history?${params.toString()}`;
  
  const response = await fetch(url, {
    headers: getAuthHeaders()
  });
  if (!response.ok) {
    throw new Error(`Failed to get history: ${response.statusText}`);
  }
  
  const data = await response.json();
  return data.history;
}

/**
 * Helper to format schedule description
 */
export function formatScheduleDescription(schedule: ScheduledWorkflow): string {
  switch (schedule.schedule_type) {
    case 'once':
      return schedule.run_at 
        ? `Once at ${new Date(schedule.run_at).toLocaleString()}`
        : 'Once (time not set)';
    case 'interval':
      return `Every ${schedule.interval_minutes} minute${schedule.interval_minutes !== 1 ? 's' : ''}`;
    case 'daily':
      return `Daily at ${schedule.time_of_day || '00:00'}`;
    case 'weekly':
      const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
      const selectedDays = schedule.days_of_week?.map(d => days[d]).join(', ') || 'No days';
      return `Weekly on ${selectedDays} at ${schedule.time_of_day || '00:00'}`;
    case 'monthly':
      return `Monthly on day ${schedule.day_of_month || 1} at ${schedule.time_of_day || '00:00'}`;
    case 'cron':
      return `Cron: ${schedule.cron_expression || 'Not set'}`;
    default:
      return 'Unknown schedule';
  }
}

/**
 * Helper to format next run time
 */
export function formatNextRun(nextRun: string | null): string {
  if (!nextRun) return 'Not scheduled';
  
  const date = new Date(nextRun);
  const now = new Date();
  const diffMs = date.getTime() - now.getTime();
  
  if (diffMs < 0) return 'Overdue';
  
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);
  
  if (diffMins < 1) return 'In less than a minute';
  if (diffMins < 60) return `In ${diffMins} minute${diffMins !== 1 ? 's' : ''}`;
  if (diffHours < 24) return `In ${diffHours} hour${diffHours !== 1 ? 's' : ''}`;
  if (diffDays < 7) return `In ${diffDays} day${diffDays !== 1 ? 's' : ''}`;
  
  return date.toLocaleDateString();
}

export interface WorkflowInfo {
  id: string;
  name: string;
}

/**
 * List available workflows for scheduling
 */
export async function listSchedulableWorkflows(): Promise<WorkflowInfo[]> {
  const response = await fetch(`${API_BASE}/api/schedules/workflows`, {
    headers: getAuthHeaders()
  });
  if (!response.ok) {
    throw new Error(`Failed to list workflows: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Get run history for scheduled workflows, optionally filtered by session
 */
export async function getRunHistory(scheduleId?: string, sessionId?: string, limit: number = 50): Promise<RunHistoryItem[]> {
  const params = new URLSearchParams();
  if (scheduleId) params.append('schedule_id', scheduleId);
  if (sessionId) params.append('session_id', sessionId);
  params.append('limit', limit.toString());
  
  const url = `${API_BASE}/api/schedules/history?${params.toString()}`;
  
  const response = await fetch(url, {
    headers: getAuthHeaders()
  });
  if (!response.ok) {
    throw new Error(`Failed to get run history: ${response.statusText}`);
  }
  
  const data = await response.json();
  return data.history || [];
}

/**
 * Format duration for display
 */
export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}m ${secs}s`;
}
