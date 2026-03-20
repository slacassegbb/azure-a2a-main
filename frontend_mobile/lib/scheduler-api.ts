import { API_BASE_URL } from '@/lib/api-config'
import { getAuthHeaders } from '@/lib/auth'

export type ScheduleType = 'once' | 'interval' | 'daily' | 'weekly' | 'monthly' | 'cron'

export interface ScheduledWorkflow {
  id: string
  workflow_id: string
  workflow_name: string
  session_id: string
  schedule_type: ScheduleType
  enabled: boolean
  created_at: string
  updated_at: string
  last_run: string | null
  next_run: string | null
  run_count: number
  last_status: 'success' | 'failed' | 'running' | null
  last_error: string | null
  success_count: number
  failure_count: number
  interval_minutes?: number
  time_of_day?: string
  days_of_week?: number[]
  day_of_month?: number
  cron_expression?: string
  timezone: string
  timeout: number
  description?: string
  tags: string[]
}

export interface RunHistoryItem {
  run_id: string
  schedule_id: string
  workflow_id: string
  workflow_name: string
  timestamp: string
  started_at: string
  completed_at: string
  duration_seconds: number
  status: 'success' | 'failed'
  error: string | null
  result: string | null
}

export async function listSchedules(workflowId?: string, sessionId?: string): Promise<ScheduledWorkflow[]> {
  const params = new URLSearchParams()
  if (workflowId) params.append('workflow_id', workflowId)
  if (sessionId) params.append('session_id', sessionId)
  const qs = params.toString()
  const url = qs ? `${API_BASE_URL}/api/schedules?${qs}` : `${API_BASE_URL}/api/schedules`
  try {
    const response = await fetch(url, { headers: getAuthHeaders() })
    if (!response.ok) return []
    const data = await response.json()
    return data.schedules
  } catch {
    return []
  }
}

export async function toggleSchedule(scheduleId: string, enabled: boolean): Promise<ScheduledWorkflow | null> {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/schedules/${scheduleId}/toggle?enabled=${enabled}`,
      { method: 'POST', headers: getAuthHeaders() }
    )
    if (!response.ok) return null
    const data = await response.json()
    return data.schedule
  } catch {
    return null
  }
}

export async function deleteSchedule(scheduleId: string): Promise<boolean> {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/schedules/${scheduleId}`,
      { method: 'DELETE', headers: getAuthHeaders() }
    )
    return response.ok
  } catch {
    return false
  }
}

export async function runScheduleNow(scheduleId: string, sessionId?: string): Promise<boolean> {
  try {
    const url = new URL(`${API_BASE_URL}/api/schedules/${scheduleId}/run-now`)
    if (sessionId) url.searchParams.set('session_id', sessionId)
    const response = await fetch(url.toString(), { method: 'POST', headers: getAuthHeaders() })
    return response.ok
  } catch {
    return false
  }
}

export async function getRunHistory(scheduleId?: string, sessionId?: string, limit = 20): Promise<RunHistoryItem[]> {
  const params = new URLSearchParams()
  if (scheduleId) params.append('schedule_id', scheduleId)
  if (sessionId) params.append('session_id', sessionId)
  params.append('limit', limit.toString())
  try {
    const response = await fetch(`${API_BASE_URL}/api/schedules/history?${params}`, { headers: getAuthHeaders() })
    if (!response.ok) return []
    const data = await response.json()
    return data.history || []
  } catch {
    return []
  }
}

export function formatScheduleDescription(schedule: ScheduledWorkflow): string {
  switch (schedule.schedule_type) {
    case 'once': return schedule.next_run ? `Once at ${new Date(schedule.next_run).toLocaleString()}` : 'Once'
    case 'interval': return `Every ${schedule.interval_minutes} min`
    case 'daily': return `Daily at ${schedule.time_of_day || '00:00'}`
    case 'weekly': {
      const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
      const sel = schedule.days_of_week?.map(d => days[d]).join(', ') || ''
      return `Weekly ${sel} at ${schedule.time_of_day || '00:00'}`
    }
    case 'monthly': return `Monthly day ${schedule.day_of_month || 1}`
    case 'cron': return `Cron: ${schedule.cron_expression || '?'}`
    default: return 'Unknown'
  }
}

export function formatNextRun(nextRun: string | null): string {
  if (!nextRun) return 'Not scheduled'
  const diff = new Date(nextRun).getTime() - Date.now()
  if (diff < 0) return 'Overdue'
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'Less than a minute'
  if (mins < 60) return `${mins}m`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h`
  return `${Math.floor(hours / 24)}d`
}
