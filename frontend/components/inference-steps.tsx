"use client"

/**
 * inference-steps.tsx - Workflow visualization component (v4 - clean rewrite)
 *
 * Single source of truth: the plan from backend.
 * 
 * The plan contains tasks, each with:
 * - task_description: what the agent is doing
 * - recommended_agent: which agent is handling it
 * - state: pending/running/completed/failed/input_required
 * - output.result: the agent response text
 * - error_message: if failed
 *
 * The steps (WebSocket events) are ONLY used for live progress during execution.
 * They do NOT affect the final rendered output - that comes from the plan.
 *
 * NO emoji parsing. NO fuzzy matching. NO hacks.
 */

import React, { useEffect, useRef, useMemo } from "react"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import {
  CheckCircle2, Loader, Workflow, Wrench,
  ChevronRight, Bot, AlertCircle, MessageSquare, Clock,
} from "lucide-react"

// Types
type StepData = {
  agent: string
  status: string
  eventType?: string
  metadata?: Record<string, any>
  taskId?: string
}

type WorkflowTask = {
  task_id: string
  task_description: string
  recommended_agent: string | null
  output: { result?: string } | null
  state: string
  error_message: string | null
}

type WorkflowPlan = {
  goal: string
  goal_status: string
  tasks: WorkflowTask[]
  reasoning?: string
}

type InferenceStepsProps = {
  steps: StepData[]
  isInferencing: boolean
  plan?: WorkflowPlan | null
}

// Helpers
const COLORS = ["#8b5cf6", "#06b6d4", "#10b981", "#f59e0b", "#ec4899", "#3b82f6", "#f97316", "#14b8a6"]

function hashColor(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) h = ((h << 5) - h + name.charCodeAt(i)) | 0
  return COLORS[Math.abs(h) % COLORS.length]
}

function formatAgentName(name: string): string {
  if (!name || name === "Unknown Agent") return "Agent"
  return name
    .replace(/^azurefoundry[_-]/i, "")
    .replace(/^AI Foundry\s+/i, "")
    .replace(/[-_]/g, " ")
    .split(" ")
    .map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ")
}

function parseStepNumber(desc: string, index: number): number {
  const match = desc.match(/\[Step\s+(\d+)/)
  return match ? parseInt(match[1], 10) : index + 1
}

function cleanDescription(desc: string): string {
  return desc.replace(/^\[Step\s+\d+[a-z]?\]\s*/i, "").trim()
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : text.slice(0, max) + "..."
}

function getStatus(state: string): "pending" | "running" | "complete" | "error" | "input_required" {
  switch (state) {
    case "completed": return "complete"
    case "failed": return "error"
    case "input_required": return "input_required"
    case "running": return "running"
    default: return "pending"
  }
}

function renderLinks(text: string): React.ReactNode {
  const urlRegex = /\[([^\]]+)\]\(([^)]+)\)|https?:\/\/[^\s<>\[\]"']+/g
  const parts: React.ReactNode[] = []
  let last = 0
  let match: RegExpExecArray | null
  let key = 0

  while ((match = urlRegex.exec(text)) !== null) {
    if (match.index > last) {
      parts.push(text.slice(last, match.index))
    }
    const href = match[2] || match[0]
    const label = match[1] || (match[0].length > 50 ? match[0].slice(0, 50) + "..." : match[0])
    parts.push(
      <a key={key++} href={href} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
        {label}
      </a>
    )
    last = match.index + match[0].length
  }

  if (last < text.length) parts.push(text.slice(last))
  return parts.length > 0 ? parts : text
}

// Live progress: extract tool calls from events for currently running task
function getLiveProgress(steps: StepData[], taskId: string | null): { tools: string[]; messages: string[] } {
  if (!taskId) return { tools: [], messages: [] }
  
  const tools: string[] = []
  const messages: string[] = []
  const seenTools = new Set<string>()
  const seenMessages = new Set<string>()
  
  for (const step of steps) {
    // Match by taskId - no fuzzy matching needed
    if (step.taskId !== taskId) continue
    
    const eventType = step.eventType || ""
    const status = step.status || ""
    
    if (eventType === "tool_call" && status && !seenTools.has(status)) {
      seenTools.add(status)
      const toolName = status
        .replace(/^🛠️\s*/g, "")
        .replace(/^.*is using\s+/i, "")
        .replace(/\.\.\.$/g, "")
      tools.push(toolName)
    } else if ((eventType === "agent_progress" || eventType === "info") && status.length > 10) {
      const key = status.slice(0, 80)
      if (!seenMessages.has(key)) {
        seenMessages.add(key)
        messages.push(status)
      }
    }
  }
  
  return { tools: tools.slice(-5), messages: messages.slice(-3) }
}

// Task Card Component
function TaskCard({ 
  task, 
  stepNumber, 
  isLive, 
  liveProgress 
}: { 
  task: WorkflowTask
  stepNumber: number
  isLive: boolean
  liveProgress: { tools: string[]; messages: string[] }
}) {
  const status = getStatus(task.state)
  const agentName = task.recommended_agent || "Agent"
  const displayName = formatAgentName(agentName)
  const color = hashColor(agentName)
  const description = cleanDescription(task.task_description)
  const output = task.output?.result?.trim()
  const error = task.error_message

  const isRunning = status === "running"
  const isComplete = status === "complete"
  const isError = status === "error"
  const isWaiting = status === "input_required"
  const isPending = status === "pending"

  const badgeClass = isError
    ? "bg-red-500/15 text-red-600 dark:text-red-400"
    : isComplete
      ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
      : isWaiting
        ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
        : isRunning
          ? "bg-primary/15 text-primary"
          : "bg-muted text-muted-foreground"

  return (
    <div className="py-2">
      <div className="flex items-center gap-2 mb-1.5">
        <div className={`flex items-center justify-center h-5 w-5 rounded-full text-[10px] font-bold ${badgeClass}`}>
          {stepNumber}
        </div>
        <span className="text-xs font-semibold text-foreground">Step {stepNumber}</span>
        
        {isComplete && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />}
        {isError && <AlertCircle className="h-3.5 w-3.5 text-red-500" />}
        {isWaiting && <MessageSquare className="h-3.5 w-3.5 text-amber-500" />}
        {isRunning && isLive && <Loader className="h-3.5 w-3.5 animate-spin text-primary" />}
        {isPending && <Clock className="h-3.5 w-3.5 text-muted-foreground" />}
      </div>

      <div className="ml-5 border-l-2 pl-4 py-1.5" style={{ borderColor: `${color}40` }}>
        <div className="flex items-center gap-2 mb-1">
          {isRunning && isLive ? (
            <div className="relative flex items-center justify-center h-4 w-4">
              <div className="h-2 w-2 rounded-full animate-pulse" style={{ backgroundColor: color }} />
              <div className="h-2 w-2 rounded-full absolute animate-ping opacity-50" style={{ backgroundColor: color }} />
            </div>
          ) : isComplete ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-500 flex-shrink-0" />
          ) : isError ? (
            <AlertCircle className="h-4 w-4 text-red-500 flex-shrink-0" />
          ) : isWaiting ? (
            <MessageSquare className="h-4 w-4 text-amber-500 flex-shrink-0" />
          ) : (
            <Bot className="h-4 w-4 flex-shrink-0" style={{ color }} />
          )}

          <span
            className="text-xs font-semibold px-2 py-0.5 rounded-full"
            style={{ backgroundColor: `${color}15`, color }}
          >
            {displayName}
          </span>

          {isComplete && <span className="text-[10px] text-emerald-600 dark:text-emerald-400">Done</span>}
          {isError && <span className="text-[10px] text-red-600 dark:text-red-400">Failed</span>}
          {isWaiting && <span className="text-[10px] text-amber-600 dark:text-amber-400">Waiting for input</span>}
          {isRunning && isLive && <span className="text-[10px] text-primary">Working...</span>}
        </div>

        {description && (
          <p className="text-xs text-muted-foreground ml-6 mb-1.5 leading-relaxed">
            {description}
          </p>
        )}

        {isRunning && isLive && liveProgress.tools.length > 0 && (
          <div className="ml-6 space-y-0.5 mb-1.5">
            {liveProgress.tools.map((tool, i) => (
              <div key={i} className="flex items-center gap-1.5 text-xs">
                <Wrench className="h-3 w-3 text-muted-foreground/70 flex-shrink-0" />
                <span className="text-muted-foreground">{truncate(tool, 60)}</span>
              </div>
            ))}
          </div>
        )}

        {isRunning && isLive && liveProgress.messages.length > 0 && (
          <div className="ml-6 space-y-0.5 mb-1.5">
            {liveProgress.messages.map((msg, i) => (
              <div key={i} className="flex items-start gap-1.5 text-xs">
                <ChevronRight className="h-3 w-3 text-muted-foreground/50 flex-shrink-0 mt-0.5" />
                <span className="text-muted-foreground">{truncate(msg, 100)}</span>
              </div>
            ))}
          </div>
        )}

        {isError && error && (
          <div className="ml-6 mt-1.5 rounded-md px-3 py-2 text-xs bg-red-500/5 border-l-2 border-red-400">
            <span className="text-red-600 dark:text-red-400">{error}</span>
          </div>
        )}

        {output && (
          <div
            className="ml-6 mt-1.5 rounded-md px-3 py-2 text-xs leading-relaxed border-l-2 max-h-[250px] overflow-y-auto"
            style={{ borderColor: color, backgroundColor: `${color}08` }}
          >
            <span className="text-foreground/80 whitespace-pre-wrap">
              {renderLinks(output)}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

// Goal Header
function GoalHeader({ goal, goalStatus, hasErrors }: { goal: string; goalStatus: string; hasErrors: boolean }) {
  // Remove HITL metadata from goal text
  let cleanGoal = goal || ""
  const hitlIdx = cleanGoal.indexOf("\n\n[User Provided")
  if (hitlIdx >= 0) cleanGoal = cleanGoal.substring(0, hitlIdx)
  cleanGoal = cleanGoal.trim()
  if (!cleanGoal || cleanGoal.length < 10 || cleanGoal.toLowerCase().startsWith("complete the workflow")) {
    return null
  }

  const statusLabel = hasErrors
    ? "Completed with errors"
    : goalStatus === "completed"
      ? "Completed"
      : "In Progress"
  
  const statusClass = hasErrors
    ? "bg-red-500/10 text-red-600"
    : goalStatus === "completed"
      ? "bg-emerald-500/10 text-emerald-600"
      : "bg-blue-500/10 text-blue-600"

  return (
    <div className="mb-3 pb-2 border-b border-border/30">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Goal</span>
        <span className={`text-[9px] px-1.5 py-0.5 rounded-full ml-auto ${statusClass}`}>
          {statusLabel}
        </span>
      </div>
      <p className="text-xs text-foreground/80 leading-relaxed">{cleanGoal}</p>
    </div>
  )
}

// Main Component
export function InferenceSteps({ steps, isInferencing, plan }: InferenceStepsProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  const tasks = plan?.tasks || []
  
  const runningTask = tasks.find(t => t.state === "running")
  const liveProgress = useMemo(
    () => getLiveProgress(steps, runningTask?.task_id || null),
    [steps, runningTask?.task_id]
  )

  const hasErrors = tasks.some(t => t.state === "failed")

  const agentNames = useMemo(() => {
    const names = new Set<string>()
    for (const t of tasks) {
      if (t.recommended_agent) names.add(formatAgentName(t.recommended_agent))
    }
    return Array.from(names)
  }, [tasks])

  const summaryLabel = tasks.length > 0
    ? `${agentNames.length} agent${agentNames.length !== 1 ? "s" : ""} - ${tasks.length} step${tasks.length !== 1 ? "s" : ""}`
    : ""

  useEffect(() => {
    if (containerRef.current && isInferencing) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [tasks, steps, isInferencing])

  if (tasks.length === 0 && !isInferencing) return null

  // Live view
  if (isInferencing) {
    return (
      <div className="flex items-start gap-3 w-full">
        <div className="h-8 w-8 flex items-center justify-center flex-shrink-0">
          <Loader className="h-5 w-5 animate-spin text-primary" />
        </div>
        <div className="rounded-xl p-4 bg-muted/50 border border-border/50 flex-1 shadow-sm">
          {plan && <GoalHeader goal={plan.goal} goalStatus={plan.goal_status} hasErrors={hasErrors} />}

          <div className="flex items-center justify-between mb-2">
            <p className="font-semibold text-sm flex items-center gap-2">
              <Workflow className="h-4 w-4 text-primary" />
              Workflow in progress
            </p>
            {summaryLabel && (
              <span className="text-[10px] text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
                {summaryLabel}
              </span>
            )}
          </div>

          <div ref={containerRef} className="space-y-1 max-h-[350px] overflow-y-auto pr-1">
            {tasks.map((task, i) => (
              <TaskCard
                key={task.task_id}
                task={task}
                stepNumber={parseStepNumber(task.task_description, i)}
                isLive={true}
                liveProgress={task.state === "running" ? liveProgress : { tools: [], messages: [] }}
              />
            ))}
          </div>
        </div>
      </div>
    )
  }

  // Completed view
  return (
    <Accordion type="single" collapsible className="w-full">
      <AccordionItem value="workflow" className="border border-border/50 bg-muted/30 rounded-xl px-4 shadow-sm">
        <AccordionTrigger className="hover:no-underline py-3">
          <div className="flex items-center gap-2.5">
            <div className={`h-7 w-7 rounded-lg flex items-center justify-center ${
              hasErrors ? "bg-amber-500/10" : "bg-emerald-500/10"
            }`}>
              {hasErrors
                ? <AlertCircle className="h-4 w-4 text-amber-500" />
                : <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              }
            </div>
            <span className="font-medium text-sm">
              {hasErrors ? "Workflow completed with errors" : "Workflow completed"}
            </span>
            {summaryLabel && (
              <span className="text-xs text-muted-foreground ml-1">{summaryLabel}</span>
            )}
          </div>
        </AccordionTrigger>
        <AccordionContent>
          {plan && <GoalHeader goal={plan.goal} goalStatus={plan.goal_status} hasErrors={hasErrors} />}

          <div className="space-y-1 pt-1 pb-2 max-h-[400px] overflow-y-auto">
            {tasks.map((task, i) => (
              <TaskCard
                key={task.task_id}
                task={task}
                stepNumber={parseStepNumber(task.task_description, i)}
                isLive={false}
                liveProgress={{ tools: [], messages: [] }}
              />
            ))}
          </div>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  )
}
