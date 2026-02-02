"use client"

import React, { useState, useEffect } from 'react'
import { 
  Clock, 
  Calendar, 
  Play, 
  Pause, 
  Trash2, 
  RefreshCw,
  ChevronDown,
  Plus,
  X,
  Check,
  AlertCircle
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { getOrCreateSessionId } from '@/lib/session'
import {
  listSchedules,
  createSchedule,
  deleteSchedule,
  toggleSchedule,
  runScheduleNow,
  getUpcomingRuns,
  getRunHistory,
  listSchedulableWorkflows,
  formatScheduleDescription,
  formatNextRun,
  formatDuration,
  ScheduledWorkflow,
  ScheduleType,
  CreateScheduleRequest,
  UpcomingRun,
  RunHistoryItem,
  WorkflowInfo,
} from '@/lib/scheduler-api'

interface ScheduleWorkflowDialogProps {
  // When used as standalone scheduler manager
  open?: boolean
  onOpenChange?: (open: boolean) => void
  // When used for a specific workflow
  workflowId?: string
  workflowName?: string
  workflowGoal?: string  // Goal from workflow designer
  sessionId?: string
  trigger?: React.ReactNode
  // Callback when schedules change (create, delete, toggle)
  onScheduleChange?: () => void
}

const DAYS_OF_WEEK = [
  { value: 0, label: 'Mon' },
  { value: 1, label: 'Tue' },
  { value: 2, label: 'Wed' },
  { value: 3, label: 'Thu' },
  { value: 4, label: 'Fri' },
  { value: 5, label: 'Sat' },
  { value: 6, label: 'Sun' },
]

const INTERVAL_PRESETS = [
  { value: 5, label: 'Every 5 minutes' },
  { value: 15, label: 'Every 15 minutes' },
  { value: 30, label: 'Every 30 minutes' },
  { value: 60, label: 'Every hour' },
  { value: 120, label: 'Every 2 hours' },
  { value: 360, label: 'Every 6 hours' },
  { value: 720, label: 'Every 12 hours' },
]

export function ScheduleWorkflowDialog({ 
  open: controlledOpen,
  onOpenChange: controlledOnOpenChange,
  workflowId: initialWorkflowId, 
  workflowName: initialWorkflowName,
  workflowGoal: initialWorkflowGoal,
  sessionId: initialSessionId,
  trigger,
  onScheduleChange
}: ScheduleWorkflowDialogProps) {
  // Support both controlled and uncontrolled modes
  const [internalOpen, setInternalOpen] = useState(false)
  const isControlled = controlledOpen !== undefined
  const open = isControlled ? controlledOpen : internalOpen
  const setOpen = isControlled ? controlledOnOpenChange || (() => {}) : setInternalOpen
  
  const [schedules, setSchedules] = useState<ScheduledWorkflow[]>([])
  const [upcomingRuns, setUpcomingRuns] = useState<UpcomingRun[]>([])
  const [runHistory, setRunHistory] = useState<RunHistoryItem[]>([])
  const [availableWorkflows, setAvailableWorkflows] = useState<WorkflowInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Auto-show create form when a workflow is pre-selected
  const [showCreateForm, setShowCreateForm] = useState(!!initialWorkflowId)
  const [showHistory, setShowHistory] = useState(false)
  const [selectedHistoryItem, setSelectedHistoryItem] = useState<RunHistoryItem | null>(null)
  
  // Form state
  const [selectedWorkflowId, setSelectedWorkflowId] = useState(initialWorkflowId || '')
  const [selectedWorkflowName, setSelectedWorkflowName] = useState(initialWorkflowName || '')
  const [scheduleType, setScheduleType] = useState<ScheduleType>('interval')
  const [intervalMinutes, setIntervalMinutes] = useState(5)
  const [timeOfDay, setTimeOfDay] = useState('09:00')
  const [daysOfWeek, setDaysOfWeek] = useState<number[]>([0, 1, 2, 3, 4]) // Mon-Fri
  const [dayOfMonth, setDayOfMonth] = useState(1)
  const [runAt, setRunAt] = useState('')
  const [cronExpression, setCronExpression] = useState('0 9 * * *')
  const [description, setDescription] = useState('')
  const [retryOnFailure, setRetryOnFailure] = useState(false)
  const [maxRuns, setMaxRuns] = useState<number | null>(null) // null = unlimited
  // Use the user's actual session ID so scheduled workflows are visible to them
  const [sessionId, setSessionId] = useState(initialSessionId || getOrCreateSessionId())
  
  // Load schedules and available workflows
  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      // Load all schedules for this session (filtered by session_id for security)
      const currentSessionId = getOrCreateSessionId()
      const [schedulesData, upcomingData, historyData] = await Promise.all([
        listSchedules(initialWorkflowId, currentSessionId),
        getUpcomingRuns(5),
        getRunHistory(undefined, currentSessionId, 50)
      ])
      setSchedules(schedulesData)
      setUpcomingRuns(upcomingData)
      setRunHistory(historyData)
      
      // Load available workflows from the backend
      try {
        const workflows = await listSchedulableWorkflows()
        setAvailableWorkflows(workflows)
      } catch (e) {
        console.error('Failed to load available workflows:', e)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load schedules')
    } finally {
      setLoading(false)
    }
  }
  
  useEffect(() => {
    if (open) {
      loadData()
      // Always show create form when a specific workflow is pre-selected
      setShowCreateForm(!!initialWorkflowId)
      // Sync workflow ID and name from props when dialog opens
      if (initialWorkflowId) {
        setSelectedWorkflowId(initialWorkflowId)
        setSelectedWorkflowName(initialWorkflowName || initialWorkflowId)
      }
    } else {
      // Reset form state when dialog closes
      setShowCreateForm(false)
    }
  }, [open, initialWorkflowId, initialWorkflowName])
  
  const handleCreateSchedule = async () => {
    if (!selectedWorkflowId || !selectedWorkflowName) {
      setError('Please select a workflow')
      return
    }
    
    setLoading(true)
    setError(null)
    
    try {
      const request: CreateScheduleRequest = {
        workflow_id: selectedWorkflowId,
        workflow_name: selectedWorkflowName,
        session_id: sessionId,
        schedule_type: scheduleType,
        enabled: true,
        retry_on_failure: retryOnFailure,
        max_runs: maxRuns,  // Add max_runs parameter
        description: description || undefined,
        workflow_goal: initialWorkflowGoal || undefined,  // Include the goal
      }
      
      // Add schedule-specific parameters
      switch (scheduleType) {
        case 'once':
          request.run_at = runAt
          break
        case 'interval':
          request.interval_minutes = intervalMinutes
          break
        case 'daily':
          request.time_of_day = timeOfDay
          break
        case 'weekly':
          request.time_of_day = timeOfDay
          request.days_of_week = daysOfWeek
          break
        case 'monthly':
          request.time_of_day = timeOfDay
          request.day_of_month = dayOfMonth
          break
        case 'cron':
          request.cron_expression = cronExpression
          break
      }
      
      await createSchedule(request)
      // Notify parent that schedules changed
      onScheduleChange?.()
      // Close the dialog after successful creation
      setOpen(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create schedule')
    } finally {
      setLoading(false)
    }
  }
  
  const handleToggle = async (scheduleId: string, enabled: boolean) => {
    try {
      await toggleSchedule(scheduleId, enabled)
      await loadData()
      // Notify parent that schedules changed
      onScheduleChange?.()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to toggle schedule')
    }
  }
  
  const handleDelete = async (scheduleId: string) => {
    try {
      await deleteSchedule(scheduleId)
      await loadData()
      // Notify parent that schedules changed
      onScheduleChange?.()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete schedule')
    }
  }
  
  const handleRunNow = async (scheduleId: string) => {
    try {
      // Pass the current user's session ID so the workflow appears in their chat
      const currentSessionId = getOrCreateSessionId()
      await runScheduleNow(scheduleId, currentSessionId)
      alert('Workflow started! Check your chat to see the execution.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to run workflow')
    }
  }
  
  const toggleDayOfWeek = (day: number) => {
    setDaysOfWeek(prev => 
      prev.includes(day) 
        ? prev.filter(d => d !== day)
        : [...prev, day].sort()
    )
  }
  
  // Dialog content is shared between controlled and uncontrolled modes
  const dialogContent = (
    <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <Calendar className="h-5 w-5" />
          Schedule a Workflow
        </DialogTitle>
        <DialogDescription>
          Set up automated runs for your workflows
        </DialogDescription>
      </DialogHeader>
      
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 p-3 rounded-md flex items-center gap-2">
          <AlertCircle className="h-4 w-4" />
          {error}
        </div>
      )}
        
        {/* Existing Schedules - hide when create form is showing */}
        {!showCreateForm && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium">Active Schedules</h3>
            <div className="flex gap-2">
              <Button 
                variant="ghost" 
                size="sm" 
                onClick={loadData}
                disabled={loading}
              >
                <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
              </Button>
              <Button 
                variant="default" 
                size="sm" 
                onClick={() => setShowCreateForm(true)}
              >
                <Plus className="h-4 w-4 mr-1" />
                New Schedule
              </Button>
            </div>
          </div>
          
          {schedules.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <Clock className="h-12 w-12 mx-auto mb-2 opacity-50" />
              <p>No schedules configured</p>
              <p className="text-sm">Create a schedule to automate this workflow</p>
            </div>
          ) : (
            <div className="space-y-2">
              {schedules.map(schedule => (
                <div 
                  key={schedule.id}
                  className={`p-3 rounded-lg border ${
                    schedule.enabled 
                      ? schedule.last_status === 'failed'
                        ? 'bg-red-50 border-red-200 dark:bg-red-950/20 dark:border-red-900'
                        : 'bg-background border-border' 
                      : 'bg-muted/50 border-muted'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <Switch
                        checked={schedule.enabled}
                        onCheckedChange={(checked) => handleToggle(schedule.id, checked)}
                      />
                      <div>
                        <p className={`font-medium ${!schedule.enabled ? 'text-muted-foreground' : ''}`}>
                          {formatScheduleDescription(schedule)}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          Next run: {formatNextRun(schedule.next_run)}
                          {schedule.run_count > 0 && ` • ${schedule.success_count}✓ ${schedule.failure_count}✗`}
                          {schedule.max_runs && ` (${schedule.success_count}/${schedule.max_runs})`}
                          {!schedule.enabled && schedule.max_runs && schedule.success_count >= schedule.max_runs && ' • Completed'}
                        </p>
                        {schedule.last_status === 'failed' && schedule.last_error && (
                          <p className="text-xs text-red-600 dark:text-red-400 mt-1">
                            ❌ Last error: {schedule.last_error.length > 80 ? schedule.last_error.substring(0, 80) + '...' : schedule.last_error}
                          </p>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      {schedule.last_status === 'success' && (
                        <Badge variant="default" className="bg-green-600">✓</Badge>
                      )}
                      {schedule.last_status === 'failed' && (
                        <Badge variant="destructive">✗</Badge>
                      )}
                      {schedule.last_status === 'running' && (
                        <Badge variant="secondary">⏳</Badge>
                      )}
                      <Badge variant={schedule.enabled ? "default" : "secondary"}>
                        {schedule.schedule_type}
                      </Badge>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="sm">
                            <ChevronDown className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem onClick={() => handleRunNow(schedule.id)}>
                            <Play className="h-4 w-4 mr-2" />
                            Run Now
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem 
                            onClick={() => handleDelete(schedule.id)}
                            className="text-red-600"
                          >
                            <Trash2 className="h-4 w-4 mr-2" />
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </div>
                  {schedule.description && (
                    <p className="text-sm text-muted-foreground mt-2">
                      {schedule.description}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
        )}
        
        {/* Create Schedule Form */}
        {showCreateForm && (
          <div className="border-t pt-4 mt-4 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium">Create New Schedule</h3>
              <Button 
                variant="ghost" 
                size="sm" 
                onClick={() => {
                  // If we have a pre-selected workflow, close the dialog entirely
                  if (initialWorkflowId) {
                    setOpen(false)
                  } else {
                    setShowCreateForm(false)
                  }
                }}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
            
            {/* Workflow Selector - always show so user can pick any workflow */}
            <div className="space-y-2">
              <Label>Workflow</Label>
              <Select 
                value={selectedWorkflowId} 
                onValueChange={(v) => {
                  setSelectedWorkflowId(v)
                  const workflow = availableWorkflows.find(w => w.id === v)
                  if (workflow) {
                    setSelectedWorkflowName(workflow.name)
                  }
                }}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select a workflow..." />
                </SelectTrigger>
                <SelectContent>
                  {/* Show selected workflow even if not in available list yet */}
                  {selectedWorkflowId && selectedWorkflowName && 
                   !availableWorkflows.find(w => w.id === selectedWorkflowId) && (
                    <SelectItem key={selectedWorkflowId} value={selectedWorkflowId}>
                      {selectedWorkflowName}
                    </SelectItem>
                  )}
                  {availableWorkflows.map(workflow => (
                    <SelectItem key={workflow.id} value={workflow.id}>
                      {workflow.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {availableWorkflows.length === 0 && (
                <p className="text-xs text-slate-400">No saved workflows found. Save a workflow first to schedule it.</p>
              )}
            </div>
            
            {/* Session ID */}
            <div className="space-y-2">
              <Label>Session ID</Label>
              <Input
                value={sessionId}
                onChange={(e) => setSessionId(e.target.value)}
                placeholder="e.g., user_3, scheduler_default"
              />
              <p className="text-xs text-slate-400">
                The session ID determines which agents will be used. Use an existing session ID that has agents registered.
              </p>
            </div>
            
            {/* Schedule Type */}
            <div className="space-y-2">
              <Label>Schedule Type</Label>
              <Select value={scheduleType} onValueChange={(v) => setScheduleType(v as ScheduleType)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="interval">Interval (every X minutes)</SelectItem>
                  <SelectItem value="daily">Daily (at specific time)</SelectItem>
                  <SelectItem value="weekly">Weekly (specific days)</SelectItem>
                  <SelectItem value="monthly">Monthly (specific day)</SelectItem>
                  <SelectItem value="once">Once (specific date/time)</SelectItem>
                  <SelectItem value="cron">Cron (advanced)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            
            {/* Interval Options */}
            {scheduleType === 'interval' && (
              <div className="space-y-2">
                <Label>Run Frequency</Label>
                <Select 
                  value={intervalMinutes.toString()} 
                  onValueChange={(v) => setIntervalMinutes(parseInt(v))}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {INTERVAL_PRESETS.map(preset => (
                      <SelectItem key={preset.value} value={preset.value.toString()}>
                        {preset.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="flex items-center gap-2 mt-2">
                  <Label className="text-sm">Or custom:</Label>
                  <Input 
                    type="number" 
                    value={intervalMinutes}
                    onChange={(e) => setIntervalMinutes(parseInt(e.target.value) || 5)}
                    className="w-24"
                    min={1}
                  />
                  <span className="text-sm text-muted-foreground">minutes</span>
                </div>
              </div>
            )}
            
            {/* Daily Options */}
            {scheduleType === 'daily' && (
              <div className="space-y-2">
                <Label>Time of Day</Label>
                <Input 
                  type="time" 
                  value={timeOfDay}
                  onChange={(e) => setTimeOfDay(e.target.value)}
                />
              </div>
            )}
            
            {/* Weekly Options */}
            {scheduleType === 'weekly' && (
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label>Days of Week</Label>
                  <div className="flex gap-2 flex-wrap">
                    {DAYS_OF_WEEK.map(day => (
                      <Button
                        key={day.value}
                        variant={daysOfWeek.includes(day.value) ? "default" : "outline"}
                        size="sm"
                        onClick={() => toggleDayOfWeek(day.value)}
                      >
                        {day.label}
                      </Button>
                    ))}
                  </div>
                </div>
                <div className="space-y-2">
                  <Label>Time of Day</Label>
                  <Input 
                    type="time" 
                    value={timeOfDay}
                    onChange={(e) => setTimeOfDay(e.target.value)}
                  />
                </div>
              </div>
            )}
            
            {/* Monthly Options */}
            {scheduleType === 'monthly' && (
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label>Day of Month</Label>
                  <Select 
                    value={dayOfMonth.toString()} 
                    onValueChange={(v) => setDayOfMonth(parseInt(v))}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {Array.from({ length: 28 }, (_, i) => i + 1).map(day => (
                        <SelectItem key={day} value={day.toString()}>
                          {day}{day === 1 ? 'st' : day === 2 ? 'nd' : day === 3 ? 'rd' : 'th'}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Time of Day</Label>
                  <Input 
                    type="time" 
                    value={timeOfDay}
                    onChange={(e) => setTimeOfDay(e.target.value)}
                  />
                </div>
              </div>
            )}
            
            {/* Once Options */}
            {scheduleType === 'once' && (
              <div className="space-y-2">
                <Label>Run At</Label>
                <Input 
                  type="datetime-local" 
                  value={runAt}
                  onChange={(e) => setRunAt(e.target.value)}
                />
              </div>
            )}
            
            {/* Cron Options */}
            {scheduleType === 'cron' && (
              <div className="space-y-2">
                <Label>Cron Expression</Label>
                <Input 
                  value={cronExpression}
                  onChange={(e) => setCronExpression(e.target.value)}
                  placeholder="0 9 * * *"
                />
                <p className="text-xs text-muted-foreground">
                  Format: minute hour day month day_of_week (e.g., "0 9 * * 1-5" for 9am weekdays)
                </p>
              </div>
            )}
            
            {/* Description */}
            <div className="space-y-2">
              <Label>Description (optional)</Label>
              <Input 
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="e.g., Daily financial report"
              />
            </div>
            
            {/* Max Runs - limit how many times to execute */}
            <div className="space-y-2">
              <Label htmlFor="max-runs">Maximum Runs (optional)</Label>
              <Input
                id="max-runs"
                type="number"
                min="1"
                value={maxRuns || ''}
                onChange={(e) => setMaxRuns(e.target.value ? parseInt(e.target.value) : null)}
                placeholder="Unlimited"
              />
              <p className="text-xs text-muted-foreground">
                Leave empty for unlimited runs, or specify how many times this workflow should execute before stopping automatically.
              </p>
            </div>
            
            {/* Retry on failure */}
            <div className="flex items-center gap-2">
              <Switch
                checked={retryOnFailure}
                onCheckedChange={setRetryOnFailure}
              />
              <Label>Retry on failure (up to 3 times)</Label>
            </div>
            
            {/* Create Button */}
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => {
                // If we have a pre-selected workflow, close the dialog entirely
                // Otherwise just hide the form to show the schedules list
                if (initialWorkflowId) {
                  setOpen(false)
                } else {
                  setShowCreateForm(false)
                }
              }}>
                Cancel
              </Button>
              <Button onClick={handleCreateSchedule} disabled={loading}>
                {loading ? (
                  <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Check className="h-4 w-4 mr-2" />
                )}
                Create Schedule
              </Button>
            </div>
          </div>
        )}
        
        {/* Upcoming Runs Preview */}
        {upcomingRuns.length > 0 && !showCreateForm && !showHistory && (
          <div className="border-t pt-4 mt-4">
            <h3 className="text-sm font-medium mb-2">Upcoming Runs (All Workflows)</h3>
            <div className="space-y-1">
              {upcomingRuns.map((run, idx) => (
                <div key={idx} className="text-sm flex justify-between items-center">
                  <span className="text-muted-foreground">{run.workflow_name}</span>
                  <span>{formatNextRun(run.next_run)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        
        {/* Run History Toggle */}
        {!showCreateForm && (
          <div className="border-t pt-4 mt-4">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium">Run History</h3>
              <Button 
                variant="ghost" 
                size="sm" 
                onClick={() => {
                  setShowHistory(!showHistory)
                  setSelectedHistoryItem(null)
                }}
              >
                {showHistory ? 'Hide' : 'Show'} History
              </Button>
            </div>
            
            {showHistory && (
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {runHistory.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-4">
                    No run history yet. Workflows will appear here after they run.
                  </p>
                ) : (
                  <>
                    {runHistory.map((item) => (
                      <div 
                        key={item.run_id}
                        className={`p-2 rounded-md border cursor-pointer transition-colors ${
                          item.status === 'success' 
                            ? 'border-green-200 dark:border-green-900 hover:bg-green-50 dark:hover:bg-green-950/20' 
                            : 'border-red-200 dark:border-red-900 hover:bg-red-50 dark:hover:bg-red-950/20'
                        } ${selectedHistoryItem?.run_id === item.run_id ? 'ring-2 ring-primary' : ''}`}
                        onClick={() => setSelectedHistoryItem(
                          selectedHistoryItem?.run_id === item.run_id ? null : item
                        )}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className={item.status === 'success' ? 'text-green-600' : 'text-red-600'}>
                              {item.status === 'success' ? '✓' : '✗'}
                            </span>
                            <span className="text-sm font-medium">{item.workflow_name}</span>
                          </div>
                          <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            <span>{formatDuration(item.duration_seconds)}</span>
                            <span>{new Date(item.timestamp).toLocaleString()}</span>
                          </div>
                        </div>
                      </div>
                    ))}
                    
                    {/* Selected History Item Detail */}
                    {selectedHistoryItem && (
                      <div className="mt-3 p-3 rounded-md bg-muted/50 border">
                        <div className="flex items-center justify-between mb-2">
                          <h4 className="text-sm font-medium">
                            {selectedHistoryItem.status === 'success' ? '✓ Success' : '✗ Failed'}
                          </h4>
                          <Button 
                            variant="ghost" 
                            size="sm" 
                            onClick={() => setSelectedHistoryItem(null)}
                          >
                            <X className="h-4 w-4" />
                          </Button>
                        </div>
                        <div className="space-y-1 text-xs text-muted-foreground">
                          <p><strong>Started:</strong> {new Date(selectedHistoryItem.started_at).toLocaleString()}</p>
                          <p><strong>Completed:</strong> {new Date(selectedHistoryItem.completed_at).toLocaleString()}</p>
                          <p><strong>Duration:</strong> {formatDuration(selectedHistoryItem.duration_seconds)}</p>
                        </div>
                        
                        {selectedHistoryItem.error && (
                          <div className="mt-2 p-2 rounded bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-400 text-xs">
                            <strong>Error:</strong> {selectedHistoryItem.error}
                          </div>
                        )}
                        
                        {selectedHistoryItem.result && (
                          <div className="mt-2">
                            <p className="text-xs font-medium mb-1">Result:</p>
                            <pre className="p-2 rounded bg-background border text-xs overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap">
                              {selectedHistoryItem.result}
                            </pre>
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </DialogContent>
  )
  
  // In controlled mode, don't render DialogTrigger - the parent controls open state
  // In uncontrolled mode, render with a trigger button
  if (isControlled) {
    return (
      <Dialog open={open} onOpenChange={setOpen}>
        {dialogContent}
      </Dialog>
    )
  }
  
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger || (
          <Button variant="outline" size="sm">
            <Clock className="h-4 w-4 mr-2" />
            Schedule
          </Button>
        )}
      </DialogTrigger>
      {dialogContent}
    </Dialog>
  )
}

export default ScheduleWorkflowDialog
