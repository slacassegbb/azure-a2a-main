"use client"

/**
 * inference-steps.tsx — Workflow visualization component (v3 — full rewrite)
 *
 * ARCHITECTURE
 * ────────────
 * Two data sources flow into a unified Phase[] model:
 *
 * 1. `plan` (WorkflowPlan) — authoritative backend model (plan_update WS event)
 *    Each task carries "[Step N] description", state, output, error_message.
 *    This is the structural skeleton: it defines what steps exist and their states.
 *
 * 2. `steps` (StepData[]) — flat stream of WebSocket events
 *    Each carries `agent`, `status`, `eventType`, `metadata`.
 *    eventType values from backend:
 *      "phase"          — orchestrator phase markers ("Planning step N...")
 *      "reasoning"      — LLM orchestrator reasoning text
 *      "info"           — informational ("N agents available", "Waiting for response")
 *      "agent_start"    — agent starting a task
 *      "agent_progress" — agent working (tool calls, status)
 *      "agent_output"   — full agent result text (up to 2000 chars)
 *      "agent_complete" — agent finished
 *      "agent_error"    — agent failed
 *      "tool_call"      — MCP tool invocation
 *      (undefined)      — legacy untyped events
 *
 * RENDERING STRATEGY
 * ──────────────────
 * When plan exists → plan tasks define the steps; events enrich with live detail.
 * When plan is null → events are grouped by agent into ad-hoc steps.
 * Both paths produce Phase[] → PhaseBlock → AgentSection.
 *
 * KEY PRINCIPLES (lessons from v1/v2 failures)
 * ─────────────────────────────────────────────
 * • NEVER suppress agent_output events — they are the user-visible result
 * • NEVER suppress reasoning events — they explain what the planner is thinking
 * • Structured eventType events are ALWAYS trusted (no content-based filtering)
 * • Content-based filtering ONLY applies to legacy untyped events
 * • The plan is the skeleton; events are the flesh. Both matter.
 * • Orchestrator events (agent=foundry-host-agent) with eventType are categorized,
 *   not suppressed. Only legacy untyped orchestrator noise is filtered.
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

// ── Internal structures ──

type AgentStatus = "running" | "complete" | "error" | "waiting" | "input_required"

interface AgentBlock {
  agent: string
  displayName: string
  color: string
  status: AgentStatus
  taskDescription?: string
  output?: string
  errorMessage?: string
  toolCalls: StepData[]       // tool_call events
  progressMessages: string[]  // agent_progress / info status text
  agentOutputs: string[]      // agent_output events (the important results)
}

interface Phase {
  kind: "init" | "step"
  stepNumber?: number
  reasoning?: string          // LLM planner reasoning for this step
  agents: AgentBlock[]
  orchestratorMessages: string[]  // phase/info messages from orchestrator
  isComplete: boolean
}

// ════════════════════════════════════════════════════════════
// Constants & pure helpers
// ════════════════════════════════════════════════════════════

const AGENT_COLORS = [
  "#8b5cf6", "#06b6d4", "#10b981", "#f59e0b",
  "#ec4899", "#3b82f6", "#f97316", "#14b8a6",
]

function hashColor(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) h = ((h << 5) - h + name.charCodeAt(i)) | 0
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

/** Replace plain URLs and markdown links with clickable <a> elements. */
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

function taskStateToStatus(state: string): AgentStatus {
  switch (state) {
    case "completed": return "complete"
    case "failed": return "error"
    case "input_required": return "input_required"
    case "pending": case "submitted": return "waiting"
    default: return "running"
  }
}

function formatToolName(status: string): string {
  return status
    .replace(/^🛠️\s*/, "")
    .replace(/^Remote agent executing:\s*/i, "")
    .replace(/^Calling:\s*/i, "")
    .replace(/_/g, " ")
    .replace(/\.{3,}$/, "")
    .replace(/^./, c => c.toUpperCase())
}

/** Is the goal a generic placeholder from the visual workflow designer? */
function isGenericGoal(goal: string): boolean {
  const l = goal.toLowerCase().trim()
  return !l || l.length < 5 || l.startsWith("complete the workflow tasks")
}

/**
 * Clean HITL metadata that gets appended to goal text.
 */
function cleanGoal(raw: string): string {
  let g = raw
  const hitlIdx = g.indexOf("\n\n[User Provided Additional Info]:")
  if (hitlIdx >= 0) g = g.substring(0, hitlIdx)
  const addlIdx = g.indexOf("\n\n[Additional Information Provided]:")
  if (addlIdx >= 0) g = g.substring(0, addlIdx)
  return g.trim()
}

/**
 * Clean plan output text for display.
 */
function cleanOutput(raw: string | undefined | null): string | undefined {
  if (!raw) return undefined
  let out = raw.replace(/^HITL Response:\s*/i, "")
  const t = out.trim()
  if (!t) return undefined
  if (t.length < 20 && /^(approve|approved|yes|no|reject|ok|confirm)$/i.test(t)) {
    return '✅ User responded: "' + t + '"'
  }
  return out
}

/**
 * Filter for UNTYPED legacy orchestrator events only.
 * Typed events (with eventType) bypass this entirely.
 * Returns null to suppress, or cleaned string to show.
 */
function filterUntypedOrchMessage(status: string): string | null {
  const l = status.toLowerCase()
  if (
    l.startsWith("contacting ") ||
    l.startsWith("request sent to ") ||
    l.includes(" is working on:") ||
    l.includes("has started working on:") ||
    l === "working on:" ||
    l === "started:" ||
    l === "processing" ||
    l === "processing request" ||
    l === "task started" ||
    l.length < 5
  ) return null
  return status
}

/**
 * Condense long document extraction blobs into a short summary.
 * "📄 **Extracted from invoice.pdf:**\n\n[1500 chars]..." → "📄 Extracted content from invoice.pdf"
 */
function condenseDocExtraction(text: string): string {
  if (text.includes("📄") && text.includes("Extracted from") && text.length > 150) {
    const nameMatch = text.match(/Extracted from\s+(.+?)(?:\*\*|:|$)/)
    const name = nameMatch ? nameMatch[1].trim() : "document"
    return `📄 Extracted content from ${name}`
  }
  return text
}

// ════════════════════════════════════════════════════════════
// Phase builders
// ════════════════════════════════════════════════════════════

/**
 * Classify events by agent name.
 * Orchestrator events (foundry-host-agent) are separated.
 */
function indexEventsByAgent(steps: StepData[]) {
  const byAgent = new Map<string, StepData[]>()
  const orchestrator: StepData[] = []
  for (const s of steps) {
    if (s.agent === "foundry-host-agent") {
      orchestrator.push(s)
    } else {
      const list = byAgent.get(s.agent)
      if (list) list.push(s)
      else byAgent.set(s.agent, [s])
    }
  }
  return { byAgent, orchestrator }
}

/**
 * Build phases from the authoritative plan + enrich with events.
 *
 * Plan tasks carry "[Step N]" prefixes. Tasks with the same step number are
 * grouped (parallel agents or retries). Events are matched by agent name.
 */
function buildPhasesFromPlan(plan: WorkflowPlan, steps: StepData[]): Phase[] {
  const { byAgent, orchestrator } = indexEventsByAgent(steps)

  // ── Extract orchestrator-level info ──
  let plannerReasoning: string | undefined = undefined
  const orchMessages: string[] = []

  for (const ev of orchestrator) {
    const et = ev.eventType || ""
    const status = ev.status || ""

    if (et === "reasoning") {
      // Always keep the LAST reasoning — it is the most up-to-date
      plannerReasoning = status
    } else if (et === "phase" || et === "info") {
      const l = status.toLowerCase()
      // Skip redundant internal markers
      if (l.includes("goal achieved") || l.includes("generating final")) continue
      if (l.includes("planning step")) continue
      if (l.includes("maximum iterations")) {
        orchMessages.push("⚠️ Maximum planning iterations reached")
        continue
      }
      // Keep useful info (agent counts, etc.)
      orchMessages.push(status)
    }
    // Other typed orchestrator events (agent_start etc. on foundry-host-agent) — skip
  }

  // Use plan.reasoning if we did not get a better one from events
  if (!plannerReasoning && plan.reasoning) {
    const l = plan.reasoning.toLowerCase().trim()
    if (!l.startsWith("planning step") && l !== "goal completed" && l !== "goal completed." && l.length > 15) {
      plannerReasoning = plan.reasoning
    }
  }

  // ── Build step phases from plan tasks ──
  const phases: Phase[] = []
  const stepMap = new Map<number, Phase>()
  const claimedAgents = new Set<string>()

  for (let i = 0; i < plan.tasks.length; i++) {
    const task = plan.tasks[i]
    const agentName = task.recommended_agent || "Unknown Agent"

    // Parse step number
    let stepNum = i + 1
    const m = task.task_description.match(/\[Step\s+(\d+)[a-z]?\]/)
    if (m) stepNum = parseInt(m[1], 10) || i + 1

    // Clean description (remove [Step N] prefix)
    const desc = task.task_description.replace(/^\[Step\s+\d+[a-z]?\]\s*/, "")

    // Clean output
    const out = cleanOutput(task.output?.result)

    // ── Attach events for this agent ──
    let toolCalls: StepData[] = []
    let progressMessages: string[] = []
    let agentOutputs: string[] = []

    if (!claimedAgents.has(agentName)) {
      claimedAgents.add(agentName)
      // Find events by exact name or fuzzy match
      let agentEvents = byAgent.get(agentName) || []
      if (agentEvents.length === 0) {
        const norm = agentName.toLowerCase().replace(/[\s\-_]/g, "")
        for (const [key, evts] of byAgent.entries()) {
          const kn = key.toLowerCase().replace(/[\s\-_]/g, "")
          if (kn.includes(norm) || norm.includes(kn)) { agentEvents = evts; break }
        }
      }

      for (const ev of agentEvents) {
        const et = ev.eventType || ""
        const status = ev.status || ""

        switch (et) {
          case "tool_call":
            toolCalls.push(ev)
            break
          case "agent_output":
            // Full agent result — ALWAYS keep
            if (status.length > 5) {
              agentOutputs.push(condenseDocExtraction(status))
            }
            break
          case "agent_progress":
          case "info":
            if (status.length > 5) {
              progressMessages.push(condenseDocExtraction(status))
            }
            break
          case "agent_start":
          case "agent_complete":
          case "agent_error":
            // State transitions — already reflected in plan task state
            break
          default:
            // Legacy untyped event — filter
            if (status.length > 5) {
              const cleaned = filterUntypedOrchMessage(status)
              if (cleaned) progressMessages.push(condenseDocExtraction(cleaned))
            }
            break
        }
      }
    }

    // Deduplicate progress messages
    const seenProgress = new Set<string>()
    progressMessages = progressMessages.filter(m => {
      const key = m.slice(0, 100)
      if (seenProgress.has(key)) return false
      seenProgress.add(key)
      return true
    })

    const block: AgentBlock = {
      agent: agentName,
      displayName: displayName(agentName),
      color: hashColor(agentName),
      status: taskStateToStatus(task.state),
      taskDescription: desc,
      output: out,
      errorMessage: task.error_message || undefined,
      toolCalls,
      progressMessages,
      agentOutputs,
    }

    const isTerminal = task.state === "completed" || task.state === "failed"
    const existing = stepMap.get(stepNum)
    if (existing) {
      existing.agents.push(block)
      if (isTerminal) existing.isComplete = true
    } else {
      const phase: Phase = {
        kind: "step",
        stepNumber: stepNum,
        agents: [block],
        orchestratorMessages: [],
        isComplete: isTerminal,
        // Attach planner reasoning to the first step only
        reasoning: i === 0 ? plannerReasoning : undefined,
      }
      phases.push(phase)
      stepMap.set(stepNum, phase)
    }
  }

  // ── Build init phase from orchestrator messages ──
  const initPhase = orchMessages.length > 0
    ? { kind: "init" as const, agents: [] as AgentBlock[], orchestratorMessages: orchMessages, isComplete: true }
    : null

  // ── Renumber phases sequentially ──
  let counter = 0
  const renumbered = phases.map(p => { counter++; return { ...p, stepNumber: counter } })

  return initPhase ? [initPhase, ...renumbered] : renumbered
}

/**
 * Build phases purely from WebSocket events when no plan is available.
 * Groups events by agent name. Each unique agent gets its own step.
 */
function buildPhasesFromEvents(steps: StepData[]): Phase[] {
  const { byAgent, orchestrator } = indexEventsByAgent(steps)
  const phases: Phase[] = []

  // ── Extract orchestrator info ──
  const orchMessages: string[] = []
  for (const ev of orchestrator) {
    const et = ev.eventType || ""
    const status = ev.status || ""
    if (et === "reasoning" || et === "phase" || et === "info") {
      if (status.length > 5) orchMessages.push(status)
    } else if (!et) {
      const cleaned = filterUntypedOrchMessage(status)
      if (cleaned && cleaned.length > 5) orchMessages.push(condenseDocExtraction(cleaned))
    }
  }

  // ── Build a phase per agent ──
  let stepNum = 0
  for (const [agentName, events] of byAgent.entries()) {
    stepNum++
    const toolCalls: StepData[] = []
    let progressMessages: string[] = []
    const agentOutputs: string[] = []
    let status: AgentStatus = "running"
    let taskDescription: string | undefined
    let output: string | undefined
    let errorMessage: string | undefined
    let isComplete = false

    for (const ev of events) {
      const et = ev.eventType || ""
      const s = ev.status || ""

      switch (et) {
        case "agent_start":
          taskDescription = ev.metadata?.task_description || s
          break
        case "agent_complete":
          status = "complete"
          isComplete = true
          break
        case "agent_error":
          status = "error"
          errorMessage = s
          isComplete = true
          break
        case "agent_output":
          if (s.length > 5) agentOutputs.push(condenseDocExtraction(s))
          output = s
          break
        case "tool_call":
          toolCalls.push(ev)
          break
        case "agent_progress":
        case "info":
          if (s.length > 5) progressMessages.push(condenseDocExtraction(s))
          break
        default:
          // Untyped
          if (s.length > 10) {
            const l = s.toLowerCase()
            if (l.includes("input_required") || l.includes("waiting for")) {
              status = "input_required"
            } else if (l.includes("completed") || l.includes("done")) {
              status = "complete"
              isComplete = true
            }
            const cleaned = filterUntypedOrchMessage(s)
            if (cleaned) progressMessages.push(condenseDocExtraction(cleaned))
          }
          break
      }
    }

    // Deduplicate progress
    const seen = new Set<string>()
    progressMessages = progressMessages.filter(m => {
      const key = m.slice(0, 100)
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })

    phases.push({
      kind: "step",
      stepNumber: stepNum,
      agents: [{
        agent: agentName,
        displayName: displayName(agentName),
        color: hashColor(agentName),
        status,
        taskDescription,
        output,
        errorMessage,
        toolCalls,
        progressMessages,
        agentOutputs,
      }],
      orchestratorMessages: [],
      isComplete,
    })
  }

  // ── Init phase ──
  const initPhase = orchMessages.length > 0
    ? { kind: "init" as const, agents: [] as AgentBlock[], orchestratorMessages: orchMessages, isComplete: true }
    : null

  return initPhase ? [initPhase, ...phases] : phases
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

  // Show live detail (tool calls, progress) when agent is actively working
  const showLiveDetail = isLive && (isRunning || isInputRequired)
  // Always show agent outputs and final output — they are the important results
  const hasAgentOutputs = block.agentOutputs.length > 0
  const hasFinalOutput = !!block.output

  return (
    <div className="ml-5 border-l-2 pl-4 py-2" style={{ borderColor: `${block.color}40` }}>
      {/* ── Header: agent name + status ── */}
      <div className="flex items-center gap-2 mb-1.5">
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

      {/* ── Task description ── */}
      {block.taskDescription && (
        <p className="text-xs text-muted-foreground ml-6 mb-1.5 leading-relaxed">
          {block.taskDescription}
        </p>
      )}

      {/* ── Tool calls (live only while running) ── */}
      {showLiveDetail && block.toolCalls.length > 0 && (
        <div className="ml-6 space-y-0.5 mb-1">
          {block.toolCalls.map((tc, i) => (
            <div key={i} className="flex items-center gap-1.5 text-xs">
              <Wrench className="h-3 w-3 text-muted-foreground/70 flex-shrink-0" />
              <span className="text-muted-foreground">{formatToolName(tc.status)}</span>
            </div>
          ))}
        </div>
      )}

      {/* ── Progress messages (live only while running) ── */}
      {showLiveDetail && block.progressMessages.map((msg, i) => (
        <div key={`p-${i}`} className="flex items-start gap-1.5 text-xs ml-6 mb-1">
          <ChevronRight className="h-3 w-3 text-muted-foreground/50 flex-shrink-0 mt-0.5" />
          <span className="text-muted-foreground whitespace-pre-wrap">{renderLinks(msg)}</span>
        </div>
      ))}

      {/* ── Agent outputs (always visible — these are the important results) ── */}
      {hasAgentOutputs && !hasFinalOutput && block.agentOutputs.map((ao, i) => (
        <div
          key={`ao-${i}`}
          className="ml-6 mt-1.5 rounded-md px-3 py-2 text-xs leading-relaxed border-l-2 max-h-[300px] overflow-y-auto"
          style={{ borderColor: block.color, backgroundColor: `${block.color}08` }}
        >
          <span className="text-foreground/80 whitespace-pre-wrap">
            {renderLinks(stripMd(ao))}
          </span>
        </div>
      ))}

      {/* ── Error message ── */}
      {isError && block.errorMessage && (
        <div className="ml-6 mt-1 rounded-md px-3 py-2 text-xs leading-relaxed bg-red-500/5 border-l-2 border-red-400">
          <span className="text-red-600 dark:text-red-400">{block.errorMessage}</span>
        </div>
      )}

      {/* ── Final output from plan (always visible) ── */}
      {hasFinalOutput && (
        <div
          className="ml-6 mt-1.5 rounded-md px-3 py-2 text-xs leading-relaxed border-l-2 max-h-[300px] overflow-y-auto"
          style={{ borderColor: block.color, backgroundColor: `${block.color}08` }}
        >
          <span className="text-foreground/80 whitespace-pre-wrap">
            {renderLinks(stripMd(block.output!))}
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
            <span className="text-muted-foreground whitespace-pre-wrap">{renderLinks(msg)}</span>
          </div>
        ))}
      </div>
    )
  }

  // ── Step phase ──

  // Retry detection: same agent repeated in the same step
  const isRetry = phase.agents.length > 1 && phase.agents.every(a => a.agent === phase.agents[0].agent)
  const lastAgent = phase.agents[phase.agents.length - 1]

  // Phase-level status
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
              <span className="text-muted-foreground whitespace-pre-wrap">{renderLinks(msg)}</span>
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
// Goal header
// ════════════════════════════════════════════════════════════

function GoalHeader({ plan, hasFailures }: { plan: WorkflowPlan; hasFailures: boolean }) {
  const goal = cleanGoal(plan.goal)
  if (!goal || isGenericGoal(goal)) return null

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

  // ── Auto-scroll ──
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
