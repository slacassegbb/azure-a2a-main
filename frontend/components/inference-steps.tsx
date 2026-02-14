"use client"

/**
 * inference-steps.tsx — Workflow visualization component
 *
 * Renders the step-by-step progress of an agent workflow, both live (during
 * execution) and as a collapsed accordion (after completion).
 *
 * DATA SOURCES
 * ────────────
 * 1. `plan` (WorkflowPlan | null)
 *    Authoritative backend model. Each task carries a "[Step N] description"
 *    prefix, a `state` enum, optional `output` and `error_message`.
 *    Arrives via `plan_update` WebSocket events during live execution, and is
 *    persisted in `inference_summary` message metadata for completed workflows.
 *
 * 2. `steps` (StepData[])
 *    Flat stream of WebSocket events (`remote_agent_activity`, `tool_call`,
 *    `file_uploaded`). Provides real-time tool calls, progress messages, and
 *    file attachments that enrich the plan-based view with live detail.
 *    For completed workflows loaded from the database, events are the steps
 *    saved alongside the inference_summary message.
 *
 * RENDERING STRATEGY
 * ──────────────────
 * • When `plan` has tasks → build phases from plan tasks; enrich with events.
 * • When `plan` is null/empty → build phases from events (grouped by agent).
 * • Both paths produce the same `Phase[]` structure consumed by PhaseBlock.
 *
 * SCENARIOS HANDLED
 * ─────────────────
 * • Live workflow in progress (isInferencing=true, plan arrives incrementally)
 * • Early workflow before first plan_update (isInferencing=true, plan=null)
 * • Completed workflow accordion (isInferencing=false, plan from metadata)
 * • Legacy completed workflow (isInferencing=false, plan=null, events only)
 * • HITL paused workflow (plan has input_required task)
 * • Retries (same agent appears multiple times in same step number)
 * • Parallel execution (different agents in same step, e.g. [Step 2a], [Step 2b])
 * • Failures (task.state=failed, with error_message)
 */

import React, { useEffect, useRef, useMemo } from "react"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import {
  CheckCircle2, Loader, Workflow, Wrench, Brain,
  ChevronRight, Bot, AlertCircle, MessageSquare,
} from "lucide-react"

// ════════════════════════════════════════════════════════════
// Types
// ════════════════════════════════════════════════════════════

type StepData = {
  agent: string
  status: string
  imageUrl?: string
  imageName?: string
  agentColor?: string
  eventType?: string
  metadata?: Record<string, any>
}

type WorkflowPlan = {
  goal: string
  goal_status: string
  tasks: Array<{
    task_id: string
    task_description: string
    recommended_agent: string | null
    output: { result?: string } | null
    state: string
    error_message: string | null
  }>
  reasoning?: string
}

type InferenceStepsProps = {
  steps: StepData[]
  isInferencing: boolean
  plan?: WorkflowPlan | null
}

// Internal structures

type AgentStatus = "running" | "complete" | "error" | "waiting" | "input_required"

interface AgentBlock {
  agent: string
  displayName: string
  color: string
  steps: StepData[]          // live tool calls / progress events
  status: AgentStatus
  taskDescription?: string
  output?: string
  errorMessage?: string
}

interface OrchestratorMessage {
  text: string
  type: "info" | "routing" | "progress"
}

interface Phase {
  kind: "init" | "step"
  stepNumber?: number
  reasoning?: string
  agents: AgentBlock[]
  orchestratorMessages: OrchestratorMessage[]
  isComplete: boolean
}

// ════════════════════════════════════════════════════════════
// Constants & helpers
// ════════════════════════════════════════════════════════════

const AGENT_COLORS = [
  "#8b5cf6", "#06b6d4", "#10b981", "#f59e0b",
  "#ec4899", "#3b82f6", "#f97316", "#14b8a6",
]

function hashColor(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) {
    h = ((h << 5) - h) + name.charCodeAt(i)
    h = h & h
  }
  return AGENT_COLORS[Math.abs(h) % AGENT_COLORS.length]
}

function displayName(name: string): string {
  if (/^foundry-host-agent$/i.test(name)) return "Orchestrator"
  return name
    .replace(/^azurefoundry_/i, "")
    .replace(/^AI Foundry\s+/i, "")
    .replace(/[-_]/g, " ")
    .split(" ")
    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ")
}

function isNoise(text: string): boolean {
  const l = text.toLowerCase()
  return (
    l.startsWith("contacting ") ||
    l.startsWith("request sent to ") ||
    (l.includes(" is working on:") && l.length < 100) ||
    (l.includes("has started working on:") && l.length < 100) ||
    l === "working on:" ||
    l === "started:" ||
    l.length < 5
  )
}

function cleanStatus(text: string): string {
  let s = text.replace(/📎\s*Generated\s+/g, "📎 Extracted ")
  s = s.replace(/^[A-Za-z\s]+Agent\s+is working on:\s*"?/i, "")
  s = s.replace(/^[A-Za-z\s]+Agent\s+has started working on:\s*"?/i, "")
  s = s.replace(/"?\s*\(\d+s\)\s*$/, "")
  return s.trim()
}

function formatTool(status: string): string {
  let s = status
    .replace(/^🛠️\s*/, "")
    .replace(/^Remote agent executing:\s*/i, "")
    .replace(/^Calling:\s*/i, "")
    .replace(/_/g, " ")
  s = s.charAt(0).toUpperCase() + s.slice(1)
  return s.replace(/\.{3,}$/, "")
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : text.slice(0, max) + "…"
}

function stripMd(text: string): string {
  return text
    .replace(/#{1,6}\s+/g, "")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/\*(.+?)\*/g, "$1")
    .replace(/__(.+?)__/g, "$1")
    .replace(/_(.+?)_/g, "$1")
    .replace(/\x60(.+?)\x60/g, "$1")
    .replace(/^\s*[-*]\s+/gm, "• ")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
}

/** Replace plain URLs and markdown links with <a> elements. */
function renderLinks(text: string): React.ReactNode {
  const rx = /\[([^\]]+)\]\(([^)]+)\)|https?:\/\/[^\s<>\[\]"']+/g
  const parts: React.ReactNode[] = []
  let last = 0, m: RegExpExecArray | null, k = 0
  while ((m = rx.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    if (m[1] && m[2]) {
      parts.push(<a key={`l${k++}`} href={m[2]} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">{m[1]}</a>)
    } else {
      parts.push(<a key={`l${k++}`} href={m[0]} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline break-all">{m[0].length > 60 ? m[0].slice(0, 60) + "…" : m[0]}</a>)
    }
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts.length > 0 ? parts : text
}

/** Map backend task state to UI status */
function taskStateToStatus(state: string): AgentStatus {
  switch (state) {
    case "completed": return "complete"
    case "failed": return "error"
    case "input_required": return "input_required"
    case "pending":
    case "submitted": return "waiting"
    default: return "running"
  }
}

/** Is this an orchestrator-level message worth showing in the init phase? */
function isUsefulOrchMsg(status: string): boolean {
  return !!(
    status.includes("📄") ||
    status.includes("Extracted") ||
    status.includes("chunks") ||
    status.includes("memory") ||
    status.includes("📱") ||
    status.includes("⏸️") ||
    status.includes("Waiting for") ||
    status.includes("paused")
  )
}

/** Is this orchestrator noise we should suppress? */
function isOrchNoise(status: string): boolean {
  const l = status.toLowerCase()
  return (
    l.includes("planning step") ||
    l.includes("agents available") ||
    l.includes("route decision") ||
    l.includes("executing step") ||
    l.includes("executing parallel") ||
    l.includes("initializing orchestration") ||
    l.includes("resuming workflow") ||
    l.includes("workflow paused") ||
    l.includes("goal achieved") ||
    l.includes("generating workflow summary")
  )
}

// ════════════════════════════════════════════════════════════
// Phase builders
// ════════════════════════════════════════════════════════════

/**
 * Build phases from the authoritative plan.
 *
 * Plan tasks carry "[Step N]" prefixes set by the backend. Tasks with the same
 * step number are grouped (parallel agents or retries). Events from `steps`
 * are matched by agent name and attached as live detail.
 */
function buildPhasesFromPlan(plan: WorkflowPlan, steps: StepData[]): Phase[] {
  // --- 1. Index events by agent name (for live detail enrichment) ---
  const eventsByAgent = new Map<string, StepData[]>()
  for (const s of steps) {
    if (s.agent === "foundry-host-agent") continue
    const list = eventsByAgent.get(s.agent)
    if (list) list.push(s); else eventsByAgent.set(s.agent, [s])
  }

  // --- 2. Build phases from plan tasks ---
  const phases: Phase[] = []
  const stepMap = new Map<number, Phase>()    // stepNumber → Phase
  const claimedAgents = new Set<string>()     // first-come-first-served for events

  for (let i = 0; i < plan.tasks.length; i++) {
    const task = plan.tasks[i]
    const agentName = task.recommended_agent || "Unknown Agent"

    // Parse step number from "[Step 3]" or "[Step 2a]"
    let stepNum = i + 1
    const m = task.task_description.match(/\[Step\s+(\d+)[a-z]?\]/)
    if (m) stepNum = parseInt(m[1], 10) || i + 1

    // Clean description
    const desc = task.task_description.replace(/^\[Step\s+\d+[a-z]?\]\s*/, "")

    // Clean output
    let out = task.output?.result || undefined
    if (out) {
      out = out.replace(/^HITL Response:\s*/i, "")
      const t = out.trim()
      if (!t) { out = undefined }
      else if (t.length < 20 && /^(approve|approved|yes|no|reject|ok|confirm)$/i.test(t)) {
        out = '✅ User responded: "' + t + '"'
      }
    }

    // Attach events — first task for each agent gets them
    let taskEvents: StepData[] = []
    if (!claimedAgents.has(agentName)) {
      claimedAgents.add(agentName)
      let found = eventsByAgent.get(agentName) || []
      // Fuzzy match if exact name doesn't hit
      if (found.length === 0) {
        const norm = agentName.toLowerCase().replace(/[\s\-_]/g, "")
        for (const [key, evts] of eventsByAgent.entries()) {
          const kn = key.toLowerCase().replace(/[\s\-_]/g, "")
          if (kn.includes(norm) || norm.includes(kn)) { found = evts; break }
        }
      }
      taskEvents = found.filter(e => {
        const et = e.eventType || ""
        return et !== "agent_start" && et !== "agent_complete"
      })
    }

    const block: AgentBlock = {
      agent: agentName,
      displayName: displayName(agentName),
      color: hashColor(agentName),
      status: taskStateToStatus(task.state),
      taskDescription: desc,
      output: out,
      errorMessage: task.error_message || undefined,
      steps: taskEvents,
    }

    const isTerminal = task.state === "completed" || task.state === "failed"
    const existing = stepMap.get(stepNum)
    if (existing) {
      existing.agents.push(block)
      existing.isComplete = isTerminal
    } else {
      const phase: Phase = {
        kind: "step",
        stepNumber: stepNum,
        agents: [block],
        orchestratorMessages: [],
        isComplete: isTerminal,
        reasoning: i === 0 ? plan.reasoning : undefined,
      }
      phases.push(phase)
      stepMap.set(stepNum, phase)
    }
  }

  // --- 3. Build init phase from orchestrator events ---
  const init = buildInitPhase(steps)

  // --- 4. Renumber phases sequentially (close gaps) ---
  let counter = 0
  const renumbered = phases.map(p => { counter++; return { ...p, stepNumber: counter } })

  return init ? [init, ...renumbered] : renumbered
}

/**
 * Build phases purely from WebSocket events when no plan is available.
 *
 * This covers:
 * - Early workflow before the first plan_update arrives
 * - Legacy sessions without plan persistence
 * - Edge cases where plan is empty
 *
 * Strategy: group events by agent name; each unique agent gets its own step.
 */
function buildPhasesFromEvents(steps: StepData[]): Phase[] {
  const phases: Phase[] = []
  const agentMap = new Map<string, Phase>()

  for (const step of steps) {
    if (step.agent === "foundry-host-agent") continue
    if (isNoise(step.status || "")) continue

    // Create or reuse phase for this agent
    if (!agentMap.has(step.agent)) {
      const phase: Phase = {
        kind: "step",
        stepNumber: agentMap.size + 1,
        agents: [{
          agent: step.agent,
          displayName: displayName(step.agent),
          color: hashColor(step.agent),
          steps: [],
          status: "running",
          taskDescription: undefined,
          output: undefined,
          errorMessage: undefined,
        }],
        orchestratorMessages: [],
        isComplete: false,
      }
      agentMap.set(step.agent, phase)
      phases.push(phase)
    }

    const phase = agentMap.get(step.agent)!
    const block = phase.agents[0]
    const et = step.eventType || ""
    const status = step.status || ""

    switch (et) {
      case "agent_start":
        block.taskDescription = step.metadata?.task_description || status
        break
      case "agent_complete":
        block.status = "complete"
        phase.isComplete = true
        break
      case "agent_output":
        block.output = status
        break
      case "agent_error":
        block.status = "error"
        block.errorMessage = status
        phase.isComplete = true
        break
      case "tool_call":
      case "agent_progress":
      case "info":
        block.steps.push(step)
        break
      default:
        // Untyped event — interpret from content
        if (status.length > 10) {
          const lower = status.toLowerCase()
          if (lower.includes("input_required") || lower.includes("waiting for")) {
            block.status = "input_required"
          } else if (lower.includes("completed") || lower.includes("done")) {
            block.status = "complete"
            phase.isComplete = true
          }
          block.steps.push({ ...step, eventType: "agent_progress" })
        }
        break
    }
  }

  const init = buildInitPhase(steps)
  return init ? [init, ...phases] : phases
}

/** Extract orchestrator messages into an init phase (shared by both builders). */
function buildInitPhase(steps: StepData[]): Phase | null {
  const seen = new Set<string>()
  const msgs: OrchestratorMessage[] = []

  for (const s of steps) {
    if (s.agent !== "foundry-host-agent") continue
    const status = s.status || ""
    if (seen.has(status)) continue
    seen.add(status)
    if (isNoise(status)) continue
    const et = s.eventType || ""
    if (et === "reasoning" || et === "phase") continue
    if (isOrchNoise(status)) continue
    if (isUsefulOrchMsg(status)) {
      msgs.push({ text: status, type: "info" })
    }
  }

  if (msgs.length === 0) return null
  return {
    kind: "init",
    agents: [],
    orchestratorMessages: msgs,
    isComplete: true,
  }
}

// ════════════════════════════════════════════════════════════
// Sub-components
// ════════════════════════════════════════════════════════════

function AgentSection({ block, isLive }: { block: AgentBlock; isLive: boolean }) {
  const isRunning = block.status === "running"
  const isComplete = block.status === "complete"
  const isError = block.status === "error"
  const isInputRequired = block.status === "input_required"
  const isPending = block.status === "waiting"

  // Separate tool calls from progress messages
  const toolSteps = block.steps.filter(s => (s.eventType || "") === "tool_call")
  const progressSteps: StepData[] = []
  const seenProgress = new Set<string>()
  for (const s of block.steps) {
    if ((s.eventType || "") === "tool_call") continue
    const l = s.status.toLowerCase()
    if (l.startsWith("contacting ") || l.startsWith("request sent to ") || l.includes(" is working on:")) continue
    const key = s.status.slice(0, 100)
    if (seenProgress.has(key)) continue
    seenProgress.add(key)
    progressSteps.push(s)
  }

  // Show tool calls / progress only while the agent is actively working in live mode
  const showDetail = isLive && (isRunning || isInputRequired)

  return (
    <div className="ml-5 border-l-2 pl-4 py-2" style={{ borderColor: `${block.color}40` }}>
      {/* Header */}
      <div className="flex items-center gap-2 mb-1.5">
        {/* Status indicator */}
        {isInputRequired && isLive ? (
          <div className="h-4 w-4 flex items-center justify-center">
            <div className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
          </div>
        ) : isRunning && isLive ? (
          <div className="relative flex items-center justify-center h-4 w-4">
            <div className="h-2 w-2 rounded-full animate-pulse" style={{ backgroundColor: block.color }} />
            <div className="h-2 w-2 rounded-full absolute animate-ping opacity-50" style={{ backgroundColor: block.color }} />
          </div>
        ) : isComplete ? (
          <CheckCircle2 className="h-4 w-4 text-emerald-500 flex-shrink-0" />
        ) : isError ? (
          <AlertCircle className="h-4 w-4 text-red-500 flex-shrink-0" />
        ) : (
          <Bot className="h-4 w-4 flex-shrink-0" style={{ color: block.color }} />
        )}

        <span
          className="text-xs font-semibold px-2 py-0.5 rounded-full"
          style={{ backgroundColor: `${block.color}15`, color: block.color }}
        >
          {block.displayName}
        </span>

        {isInputRequired && <span className="text-[10px] text-amber-600 dark:text-amber-400 font-medium">Waiting for input</span>}
        {isPending && isLive && <span className="text-[10px] text-muted-foreground font-medium">Pending</span>}
        {isComplete && <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-medium">Done</span>}
        {isError && <span className="text-[10px] text-red-600 dark:text-red-400 font-medium">Failed</span>}
      </div>

      {/* Task description */}
      {block.taskDescription && (
        <p className="text-xs text-muted-foreground ml-6 mb-1.5 leading-relaxed">
          {block.taskDescription}
        </p>
      )}

      {/* Tool calls (live only) */}
      {showDetail && toolSteps.length > 0 && (
        <div className="ml-6 space-y-0.5 mb-1">
          {toolSteps.map((s, i) => (
            <div key={i} className="flex items-center gap-1.5 text-xs">
              <Wrench className="h-3 w-3 text-muted-foreground/70 flex-shrink-0" />
              <span className="text-muted-foreground">{formatTool(cleanStatus(s.status))}</span>
            </div>
          ))}
        </div>
      )}

      {/* Progress messages (live only) */}
      {showDetail && progressSteps.map((s, i) => (
        <div key={`p-${i}`} className="flex items-start gap-1.5 text-xs ml-6 mb-1">
          <ChevronRight className="h-3 w-3 text-muted-foreground/50 flex-shrink-0 mt-0.5" />
          <span className="text-muted-foreground whitespace-pre-wrap">{renderLinks(cleanStatus(s.status))}</span>
        </div>
      ))}

      {/* Error message (always visible when failed) */}
      {isError && block.errorMessage && (
        <div className="ml-6 mt-1 rounded-md px-3 py-2 text-xs leading-relaxed bg-red-500/5 border-l-2 border-red-400">
          <span className="text-red-600 dark:text-red-400">{block.errorMessage}</span>
        </div>
      )}

      {/* Output / result */}
      {block.output && (
        <div
          className="ml-6 mt-1.5 rounded-md px-3 py-2 text-xs leading-relaxed border-l-2 max-h-[300px] overflow-y-auto"
          style={{ borderColor: block.color, backgroundColor: `${block.color}08` }}
        >
          <span className="text-foreground/80 whitespace-pre-wrap">
            {renderLinks(stripMd(cleanStatus(block.output)))}
          </span>
        </div>
      )}
    </div>
  )
}

function PhaseBlock({ phase, isLive }: { phase: Phase; isLive: boolean }) {
  // ── Init phase (orchestrator messages) ──
  if (phase.kind === "init") {
    if (phase.orchestratorMessages.length === 0) return null
    return (
      <div className="py-1">
        {phase.orchestratorMessages.map((msg, i) => (
          <div key={i} className="flex items-start gap-1.5 text-xs ml-1 mb-0.5">
            <MessageSquare className="h-3 w-3 text-primary/60 flex-shrink-0 mt-0.5" />
            <span className="text-muted-foreground whitespace-pre-wrap">{renderLinks(msg.text)}</span>
          </div>
        ))}
      </div>
    )
  }

  // ── Step phase ──

  // Retry detection: same agent repeated in the same step
  const isRetry = phase.agents.length > 1 && phase.agents.every(a => a.agent === phase.agents[0].agent)
  const lastAgent = phase.agents[phase.agents.length - 1]

  // Determine phase-level status
  const phaseFailed = isRetry
    ? lastAgent?.status === "error"
    : phase.agents.some(a => a.status === "error")
  const phaseWaiting = lastAgent?.status === "input_required"
  const phaseComplete = phase.isComplete
  const phaseSucceeded = phaseComplete && !phaseFailed
  const phasePending = !phaseComplete && !phaseFailed && !phaseWaiting &&
    phase.agents.every(a => a.status === "waiting")
  const phaseRunning = isLive && !phaseComplete && !phaseFailed && !phaseWaiting && !phasePending &&
    phase.agents.some(a => a.status === "running")

  // Step number badge color
  const badgeClass = phaseFailed
    ? "bg-red-500/15 text-red-600 dark:text-red-400"
    : phaseSucceeded
      ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
      : phaseWaiting
        ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
        : phaseRunning
          ? "bg-primary/15 text-primary"
          : "bg-muted text-muted-foreground"

  return (
    <div className="py-1">
      {/* Step header */}
      <div className="flex items-center gap-2 mb-1">
        <div className={`flex items-center justify-center h-5 w-5 rounded-full text-[10px] font-bold ${badgeClass}`}>
          {phase.stepNumber || "•"}
        </div>
        <span className="text-xs font-semibold text-foreground">
          {phase.stepNumber ? `Step ${phase.stepNumber}` : "Step"}
        </span>
        {isRetry && (
          <span className="text-[9px] text-amber-600 dark:text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded-full">
            {phase.agents.length} attempts
          </span>
        )}
        {phaseFailed && <AlertCircle className="h-3 w-3 text-red-500" />}
        {phaseSucceeded && <CheckCircle2 className="h-3 w-3 text-emerald-500" />}
        {phaseWaiting && <MessageSquare className="h-3 w-3 text-amber-500" />}
        {phaseRunning && <Loader className="h-3 w-3 animate-spin text-primary" />}
      </div>

      {/* Reasoning */}
      {phase.reasoning && (
        <div className="ml-5 mb-1.5 flex items-start gap-1.5">
          <Brain className="h-3 w-3 text-amber-500 flex-shrink-0 mt-0.5" />
          <p className="text-[11px] text-muted-foreground leading-relaxed italic whitespace-pre-wrap">
            {renderLinks(phase.reasoning)}
          </p>
        </div>
      )}

      {/* Orchestrator messages */}
      {phase.orchestratorMessages.length > 0 && (
        <div className="ml-5 mb-1.5 space-y-0.5">
          {phase.orchestratorMessages.map((msg, i) => (
            <div key={i} className="flex items-start gap-1.5 text-xs">
              <MessageSquare className="h-3 w-3 text-primary/50 flex-shrink-0 mt-0.5" />
              <span className="text-muted-foreground whitespace-pre-wrap">{renderLinks(msg.text)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Agent blocks */}
      {phase.agents.map((block, i) => {
        const isLastAttempt = i === phase.agents.length - 1

        // Retries: show earlier failed attempts as compact one-liners
        if (isRetry && !isLastAttempt) {
          const reason = block.errorMessage ? `: ${truncate(block.errorMessage, 80)}` : ""
          return (
            <div key={`${block.agent}-${i}`} className="ml-5 flex items-center gap-1.5 py-0.5 opacity-60">
              <AlertCircle className="h-3 w-3 text-red-400 flex-shrink-0" />
              <span className="text-[10px] text-muted-foreground">Attempt {i + 1} failed{reason}</span>
            </div>
          )
        }

        return <AgentSection key={`${block.agent}-${i}`} block={block} isLive={isLive} />
      })}
    </div>
  )
}

// ════════════════════════════════════════════════════════════
// Goal header (shared between live & accordion views)
// ════════════════════════════════════════════════════════════

function GoalHeader({ plan, hasFailures }: { plan: WorkflowPlan; hasFailures: boolean }) {
  // Strip internal metadata appended during HITL
  let goal = plan.goal
  const hitlIdx = goal.indexOf("\n\n[User Provided Additional Info]:")
  if (hitlIdx >= 0) goal = goal.substring(0, hitlIdx)
  const addlIdx = goal.indexOf("\n\n[Additional Information Provided]:")
  if (addlIdx >= 0) goal = goal.substring(0, addlIdx)
  goal = goal.trim()
  if (!goal) return null

  const statusLabel = hasFailures
    ? "Completed with errors"
    : plan.goal_status === "completed"
      ? "Completed"
      : "In Progress"
  const statusClass = hasFailures
    ? "bg-red-500/10 text-red-600"
    : plan.goal_status === "completed"
      ? "bg-emerald-500/10 text-emerald-600"
      : "bg-blue-500/10 text-blue-600"

  return (
    <div className="mb-3 pb-2 border-b border-border/30">
      <div className="flex items-center gap-2 mb-1">
        <Brain className="h-3.5 w-3.5 text-amber-500" />
        <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Goal</span>
        <span className={`text-[9px] px-1.5 py-0.5 rounded-full ml-auto ${statusClass}`}>
          {statusLabel}
        </span>
      </div>
      <p className="text-xs text-foreground/80 leading-relaxed">{goal}</p>
    </div>
  )
}

// ════════════════════════════════════════════════════════════
// Main component
// ════════════════════════════════════════════════════════════

export function InferenceSteps({ steps, isInferencing, plan }: InferenceStepsProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  // ── Build phases ──
  const phases = useMemo((): Phase[] => {
    const hasPlan = plan && plan.tasks && plan.tasks.length > 0
    return hasPlan
      ? buildPhasesFromPlan(plan, steps)
      : buildPhasesFromEvents(steps)
  }, [steps, plan])

  // ── Derived stats ──
  const stepPhases = phases.filter(p => p.kind === "step")

  const hasFailures = stepPhases.some(p => {
    const isRetry = p.agents.length > 1 && p.agents.every(a => a.agent === p.agents[0].agent)
    if (isRetry) return p.agents[p.agents.length - 1]?.status === "error"
    return p.agents.some(a => a.status === "error")
  })

  const uniqueAgents = useMemo(() => {
    if (plan && plan.tasks && plan.tasks.length > 0) {
      const set = new Set<string>()
      for (const t of plan.tasks) {
        const a = t.recommended_agent
        if (a && a !== "foundry-host-agent" && a !== "Unknown Agent") set.add(a)
      }
      return Array.from(set).map(displayName)
    }
    const set = new Set(steps.map(s => s.agent))
    set.delete("foundry-host-agent")
    return Array.from(set).map(displayName)
  }, [steps, plan])

  const summaryLabel = uniqueAgents.length > 0
    ? `${uniqueAgents.length} agent${uniqueAgents.length !== 1 ? "s" : ""} · ${stepPhases.length} step${stepPhases.length !== 1 ? "s" : ""}`
    : `${steps.length} events`

  // ── Auto-scroll during live execution ──
  useEffect(() => {
    if (containerRef.current && isInferencing) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [steps, isInferencing])

  // ── Nothing to render ──
  if (phases.length === 0 && !isInferencing) return null

  // ═══════════════════════════════════════════════════
  // LIVE VIEW
  // ═══════════════════════════════════════════════════
  if (isInferencing) {
    return (
      <div className="flex items-start gap-3 w-full">
        <div className="h-8 w-8 flex items-center justify-center flex-shrink-0">
          <Loader className="h-5 w-5 animate-spin text-primary" />
        </div>
        <div className="rounded-xl p-4 bg-muted/50 border border-border/50 flex-1 shadow-sm">
          {plan && <GoalHeader plan={plan} hasFailures={hasFailures} />}

          <div className="flex items-center justify-between mb-2">
            <p className="font-semibold text-sm flex items-center gap-2">
              <Workflow className="h-4 w-4 text-primary" />
              Workflow in progress
            </p>
            <span className="text-[10px] text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
              {summaryLabel}
            </span>
          </div>

          <div ref={containerRef} className="space-y-0.5 max-h-[350px] overflow-y-auto pr-1">
            {phases.map((phase, i) => (
              <PhaseBlock key={i} phase={phase} isLive={true} />
            ))}
          </div>
        </div>
      </div>
    )
  }

  // ═══════════════════════════════════════════════════
  // COMPLETED ACCORDION VIEW
  // ═══════════════════════════════════════════════════
  return (
    <Accordion type="single" collapsible className="w-full">
      <AccordionItem value="item-1" className="border border-border/50 bg-muted/30 rounded-xl px-4 shadow-sm">
        <AccordionTrigger className="hover:no-underline py-3">
          <div className="flex items-center gap-2.5">
            <div className={`h-7 w-7 rounded-lg flex items-center justify-center ${
              hasFailures ? "bg-amber-500/10" : "bg-emerald-500/10"
            }`}>
              {hasFailures
                ? <AlertCircle className="h-4 w-4 text-amber-500" />
                : <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              }
            </div>
            <span className="font-medium text-sm">
              {hasFailures ? "Workflow completed with errors" : "Workflow completed"}
            </span>
            <span className="text-xs text-muted-foreground ml-1">{summaryLabel}</span>
          </div>
        </AccordionTrigger>
        <AccordionContent>
          {plan && <GoalHeader plan={plan} hasFailures={hasFailures} />}

          <div className="space-y-0.5 pt-1 pb-2 max-h-[400px] overflow-y-auto">
            {phases.map((phase, i) => (
              <PhaseBlock key={i} phase={phase} isLive={false} />
            ))}
          </div>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  )
}
