"use client"

import { useEffect, useState, useCallback } from "react"
import {
  listSchedules,
  toggleSchedule,
  deleteSchedule,
  runScheduleNow,
  getRunHistory,
  formatScheduleDescription,
  formatNextRun,
  type ScheduledWorkflow,
  type RunHistoryItem,
} from "@/lib/scheduler-api"
import { getOrCreateSessionId } from "@/lib/session"
import { Switch } from "@/components/ui/switch"
import {
  Calendar,
  Clock,
  Play,
  Trash,
  Trash2,
  RefreshCw,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronUp,
  Timer,
} from "lucide-react"

export function SchedulesTab() {
  const [schedules, setSchedules] = useState<ScheduledWorkflow[]>([])
  const [history, setHistory] = useState<RunHistoryItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const sessionId = getOrCreateSessionId()

  const refresh = useCallback(async () => {
    setIsLoading(true)
    const [scheds, hist] = await Promise.all([
      listSchedules(undefined, sessionId),
      getRunHistory(undefined, sessionId, 20),
    ])
    setSchedules(scheds)
    setHistory(hist)
    setIsLoading(false)
  }, [sessionId])

  useEffect(() => { refresh() }, [refresh])

  const handleToggle = async (id: string, enabled: boolean) => {
    const result = await toggleSchedule(id, enabled)
    if (result) {
      setSchedules((prev) => prev.map((s) => (s.id === id ? { ...s, enabled } : s)))
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this schedule?")) return
    if (await deleteSchedule(id)) {
      setSchedules((prev) => prev.filter((s) => s.id !== id))
    }
  }

  const handleRunNow = async (id: string) => {
    const ok = await runScheduleNow(id, sessionId)
    if (ok) {
      alert("Workflow triggered! Check your conversations for results.")
    } else {
      alert("Failed to run workflow. The run-now feature may not be available yet.")
    }
    setTimeout(refresh, 2000)
  }

  const handleDeleteAll = async () => {
    if (schedules.length === 0) return
    if (!confirm(`Delete all ${schedules.length} scheduled workflows? This cannot be undone.`)) return
    await Promise.all(schedules.map((s) => deleteSchedule(s.id)))
    refresh()
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <h2 className="text-lg font-semibold">Scheduled Workflows</h2>
        <div className="flex items-center gap-1">
          {schedules.length > 0 && (
            <button onClick={handleDeleteAll} className="p-2 text-muted-foreground hover:text-red-500 transition-colors" title="Delete all">
              <Trash className="h-4 w-4" />
            </button>
          )}
          <button onClick={refresh} className="p-2 text-muted-foreground hover:text-foreground transition-colors">
            <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto scroll-smooth">
        {/* Schedules */}
        {schedules.length === 0 && !isLoading && (
          <div className="flex flex-col items-center justify-center h-40 text-muted-foreground text-sm">
            <Calendar className="h-8 w-8 mb-2 opacity-50" />
            <p>No scheduled workflows</p>
            <p className="text-xs mt-1">Use voice to say "run this every hour"</p>
          </div>
        )}

        {schedules.map((schedule) => {
          const isExpanded = expandedId === schedule.id
          const schedHistory = history.filter((h) => h.schedule_id === schedule.id)

          return (
            <div key={schedule.id} className="border-b border-border/50">
              {/* Schedule row */}
              <div className="px-4 py-3 flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{schedule.workflow_name}</p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <Clock className="h-3 w-3 text-muted-foreground" />
                    <span className="text-xs text-muted-foreground">
                      {formatScheduleDescription(schedule)}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <Timer className="h-3 w-3 text-muted-foreground" />
                    <span className="text-xs text-muted-foreground">
                      Next: {formatNextRun(schedule.next_run)}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <Switch
                    checked={schedule.enabled}
                    onCheckedChange={(checked) => handleToggle(schedule.id, checked)}
                  />
                  <button
                    onClick={() => handleRunNow(schedule.id)}
                    className="p-1.5 text-muted-foreground hover:text-primary transition-colors"
                    title="Run now"
                  >
                    <Play className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => setExpandedId(isExpanded ? null : schedule.id)}
                    className="p-1.5 text-muted-foreground hover:text-foreground transition-colors"
                  >
                    {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                  </button>
                </div>
              </div>

              {/* Expanded: stats + history */}
              {isExpanded && (
                <div className="px-4 pb-3 space-y-3">
                  {/* Stats */}
                  <div className="flex gap-4 text-xs">
                    <span className="text-muted-foreground">
                      Runs: <strong className="text-foreground">{schedule.run_count}</strong>
                    </span>
                    <span className="text-green-500">
                      Success: {schedule.success_count}
                    </span>
                    <span className="text-red-500">
                      Failed: {schedule.failure_count}
                    </span>
                  </div>

                  {/* Run history */}
                  {schedHistory.length > 0 && (
                    <div className="space-y-1.5">
                      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                        Recent Runs
                      </p>
                      {schedHistory.slice(0, 5).map((run) => (
                        <div key={run.run_id} className="flex items-center gap-2 text-xs">
                          {run.status === "success" ? (
                            <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
                          ) : (
                            <XCircle className="h-3.5 w-3.5 text-red-500" />
                          )}
                          <span className="text-muted-foreground">
                            {new Date(run.started_at).toLocaleString()}
                          </span>
                          <span className="text-muted-foreground">
                            ({run.duration_seconds.toFixed(1)}s)
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Delete */}
                  <button
                    onClick={() => handleDelete(schedule.id)}
                    className="flex items-center gap-1.5 text-xs text-red-500 hover:text-red-400 transition-colors"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    Delete schedule
                  </button>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
