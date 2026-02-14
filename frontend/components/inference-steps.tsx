"use client"

import React from "react"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { CheckCircle2, Loader, Workflow, Wrench, Brain, ChevronRight, Bot, AlertCircle, MessageSquare } from "lucide-react"
import { useEffect, useRef, useMemo } from "react"

type StepData = {
  agent: string
  status: string
  imageUrl?: string
  imageName?: string
  agentColor?: string
  eventType?: string
  metadata?: Record<string, any>
}

// Plan-based data structure (source of truth from backend)
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
  plan?: WorkflowPlan | null  // Optional plan - if provided, render from plan directly
}

// Agent color palette
const AGENT_COLORS = [
  "#8b5cf6", // purple
  "#06b6d4", // cyan
  "#10b981", // emerald
  "#f59e0b", // amber
  "#ec4899", // pink
  "#3b82f6", // blue
  "#f97316", // orange
  "#14b8a6", // teal
]

const getAgentColor = (name: string): string => {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = ((hash << 5) - hash) + name.charCodeAt(i)
    hash = hash & hash
  }
  return AGENT_COLORS[Math.abs(hash) % AGENT_COLORS.length]
}

// Friendly agent name display
const getDisplayName = (name: string): string => {
  if (/^foundry-host-agent$/i.test(name)) return "Orchestrator"
  return name
    .replace(/^azurefoundry_/i, "")
    .replace(/^AI Foundry\s+/i, "")
    .replace(/-/g, " ")
    .replace(/_/g, " ")
    .split(" ")
    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ")
}

// ──────────────────────────────────────────────────────────
// Group flat steps into structured phases
// ──────────────────────────────────────────────────────────

type PhaseType = "init" | "planning"

interface AgentBlock {
  agent: string
  displayName: string
  color: string
  steps: StepData[]
  status: "running" | "complete" | "error" | "waiting" | "input_required"
  taskDescription?: string
  output?: string
  errorMessage?: string
}

interface OrchestratorMessage {
  text: string
  type: "info" | "routing" | "progress"
}

interface Phase {
  type: PhaseType
  stepNumber?: number
  reasoning?: string
  agents: AgentBlock[]
  orchestratorMessages: OrchestratorMessage[]
  isComplete: boolean
}

// ──────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────

// Clean up agent status messages for display
function cleanAgentStatus(text: string): string {
  let s = text.replace(/📎\s*Generated\s+/g, "📎 Extracted ")
  s = s.replace(/^[A-Za-z\s]+Agent\s+is working on:\s*"?/i, "")
  s = s.replace(/^[A-Za-z\s]+Agent\s+has started working on:\s*"?/i, "")
  s = s.replace(/"?\s*\(\d+s\)\s*$/, "")
  return s.trim()
}

// Check if a message is noise that should be filtered
function isNoiseMessage(text: string): boolean {
  const lower = text.toLowerCase()
  return (
    lower.startsWith("contacting ") ||
    lower.startsWith("request sent to ") ||
    (lower.includes(" is working on:") && lower.length < 100) ||
    (lower.includes("has started working on:") && lower.length < 100) ||
    lower === "working on:" ||
    lower === "started:" ||
    lower.length < 5
  )
}

function formatToolAction(status: string): string {
  let s = status
    .replace(/^🛠️\s*/, "")
    .replace(/^Remote agent executing:\s*/i, "")
    .replace(/^Calling:\s*/i, "")
    .replace(/_/g, " ")
  s = s.charAt(0).toUpperCase() + s.slice(1)
  s = s.replace(/\.{3,}$/, "")
  return s
}

function truncateText(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text
  return text.slice(0, maxLen) + "…"
}

function stripMarkdown(text: string): string {
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

// Parse text and make URLs clickable
function renderWithLinks(text: string): React.ReactNode {
  // Match URLs (http/https) and markdown links [text](url)
  const urlRegex = /\[([^\]]+)\]\(([^)]+)\)|https?:\/\/[^\s<>\[\]"']+/g
  const parts: React.ReactNode[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  let keyIdx = 0
  
  while ((match = urlRegex.exec(text)) !== null) {
    // Add text before the match
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index))
    }
    
    if (match[1] && match[2]) {
      // Markdown link [text](url)
      parts.push(
        <a 
          key={`link-${keyIdx++}`}
          href={match[2]} 
          target="_blank" 
          rel="noopener noreferrer"
          className="text-primary hover:underline"
        >
          {match[1]}
        </a>
      )
    } else {
      // Plain URL
      parts.push(
        <a 
          key={`link-${keyIdx++}`}
          href={match[0]} 
          target="_blank" 
          rel="noopener noreferrer"
          className="text-primary hover:underline break-all"
        >
          {match[0].length > 60 ? match[0].slice(0, 60) + "…" : match[0]}
        </a>
      )
    }
    
    lastIndex = match.index + match[0].length
  }
  
  // Add remaining text
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }
  
  return parts.length > 0 ? parts : text
}

// Renumber planning phases consecutively (1, 2, 3...) to avoid gaps
function renumberPhases(phases: Phase[]): Phase[] {
  let stepCounter = 0
  return phases.map(p => {
    if (p.type === "planning") {
      stepCounter++
      return { ...p, stepNumber: stepCounter }
    }
    return p
  })
}

// ──────────────────────────────────────────────────────────
// Sub-components
// ──────────────────────────────────────────────────────────

function AgentSection({ block, isLive }: { block: AgentBlock; isLive: boolean }) {
  const isRunning = block.status === "running"
  const isComplete = block.status === "complete"
  const isError = block.status === "error"
  const isInputRequired = block.status === "input_required"
  const isPending = block.status === "waiting"  // submitted/pending task, not yet started

  // Filter out noise and duplicates from progress steps
  const toolSteps = block.steps.filter(s => (s.eventType || "") === "tool_call")
  const progressSteps = block.steps.filter(s => {
    const et = s.eventType || ""
    if (et === "tool_call") return false
    const lower = s.status.toLowerCase()
    if (lower.startsWith("contacting ")) return false
    if (lower.startsWith("request sent to ")) return false
    if (lower.includes(" is working on:")) return false
    if (lower.startsWith("working on:") && lower.length < 50) return false
    return true
  })
  
  // Deduplicate progress steps by content
  const seenProgress = new Set<string>()
  const uniqueProgressSteps = progressSteps.filter(s => {
    const key = s.status.slice(0, 100)
    if (seenProgress.has(key)) return false
    seenProgress.add(key)
    return true
  })

  // During live execution: show tool calls and progress
  // After completion: only show output/error (the user cares about results, not process)
  const showActivityDetail = isLive && (isRunning || isInputRequired)

  return (
    <div className="ml-5 border-l-2 pl-4 py-2" style={{ borderColor: `${block.color}40` }}>
      {/* Agent header */}
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

        {isInputRequired && (
          <span className="text-[10px] text-amber-600 dark:text-amber-400 font-medium">Waiting for input</span>
        )}
        {isPending && isLive && (
          <span className="text-[10px] text-muted-foreground font-medium">Pending</span>
        )}
        {isComplete && (
          <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-medium">Done</span>
        )}
        {isError && (
          <span className="text-[10px] text-red-600 dark:text-red-400 font-medium">Failed</span>
        )}
      </div>

      {/* Task description - what the agent was asked to do */}
      {block.taskDescription && (
        <p className="text-xs text-muted-foreground ml-6 mb-1.5 leading-relaxed">
          {block.taskDescription}
        </p>
      )}

      {/* Tool calls - only during live execution */}
      {showActivityDetail && toolSteps.length > 0 && (
        <div className="ml-6 space-y-0.5 mb-1">
          {toolSteps.map((s, i) => (
            <div key={i} className="flex items-center gap-1.5 text-xs">
              <Wrench className="h-3 w-3 text-muted-foreground/70 flex-shrink-0" />
              <span className="text-muted-foreground">{formatToolAction(cleanAgentStatus(s.status))}</span>
            </div>
          ))}
        </div>
      )}

      {/* Progress messages - only during live execution */}
      {showActivityDetail && uniqueProgressSteps.map((s, i) => (
        <div key={`p-${i}`} className="flex items-start gap-1.5 text-xs ml-6 mb-1">
          <ChevronRight className="h-3 w-3 text-muted-foreground/50 flex-shrink-0 mt-0.5" />
          <span className="text-muted-foreground whitespace-pre-wrap">{renderWithLinks(cleanAgentStatus(s.status))}</span>
        </div>
      ))}

      {/* Error message - always visible when task failed */}
      {isError && block.errorMessage && (
        <div className="ml-6 mt-1 rounded-md px-3 py-2 text-xs leading-relaxed bg-red-500/5 border-l-2 border-red-400">
          <span className="text-red-600 dark:text-red-400">{block.errorMessage}</span>
        </div>
      )}

      {/* Agent output / result - the actual deliverable */}
      {block.output && (
        <div
          className="ml-6 mt-1.5 rounded-md px-3 py-2 text-xs leading-relaxed border-l-2 max-h-[300px] overflow-y-auto"
          style={{ borderColor: block.color, backgroundColor: `${block.color}08` }}
        >
          <span className="text-foreground/80 whitespace-pre-wrap">
            {renderWithLinks(stripMarkdown(cleanAgentStatus(block.output)))}
          </span>
        </div>
      )}
    </div>
  )
}

function PhaseBlock({ phase, isLive }: { phase: Phase; isLive: boolean }) {
  if (phase.type === "init") {
    if (phase.orchestratorMessages.length === 0) return null
    return (
      <div className="py-1">
        {phase.orchestratorMessages.map((msg, i) => (
          <div key={i} className="flex items-start gap-1.5 text-xs ml-1 mb-0.5">
            <MessageSquare className="h-3 w-3 text-primary/60 flex-shrink-0 mt-0.5" />
            <span className="text-muted-foreground whitespace-pre-wrap">{renderWithLinks(msg.text)}</span>
          </div>
        ))}
      </div>
    )
  }

  // Planning + agent execution phase
  const phaseComplete = phase.isComplete

  // Check if the last agent in this phase failed (determines step icon)
  // For retries: only check the last agent (latest attempt is what matters)
  // For parallel: check ALL agents (any failure means the step had issues)
  const isRetryPhase = phase.agents.length > 1 &&
    phase.agents.every(a => a.agent === phase.agents[0].agent)
  
  const lastAgent = phase.agents[phase.agents.length - 1]
  const phaseFailed = isRetryPhase
    ? lastAgent?.status === "error"
    : phase.agents.some(a => a.status === "error")
  const phaseSucceeded = phaseComplete && !phaseFailed
  const phaseWaiting = lastAgent?.status === "input_required"
  const phasePending = !phaseComplete && !phaseFailed && !phaseWaiting &&
    phase.agents.every(a => a.status === "waiting")  // all agents are submitted/pending
  // Running = live view + has an agent that is actively running (not just submitted/pending)
  const phaseRunning = isLive && !phaseComplete && !phaseFailed && !phaseWaiting && !phasePending &&
    phase.agents.some(a => a.status === "running")

  // Detect retries vs parallel:
  // - Retries: multiple blocks with the SAME agent name (same agent called multiple times)
  // - Parallel: multiple blocks with DIFFERENT agent names (different agents in same step)

  return (
    <div className="py-1">
      {/* Step header */}
      <div className="flex items-center gap-2 mb-1">
        <div className={`flex items-center justify-center h-5 w-5 rounded-full text-[10px] font-bold ${
          phaseFailed
            ? "bg-red-500/15 text-red-600 dark:text-red-400"
            : phaseSucceeded
              ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
              : phaseWaiting
                ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                : phaseRunning
                  ? "bg-primary/15 text-primary"
                  : "bg-muted text-muted-foreground"
        }`}>
          {phase.stepNumber || "•"}
        </div>
        <span className="text-xs font-semibold text-foreground">
          {phase.stepNumber ? `Step ${phase.stepNumber}` : "Step"}
        </span>
        {isRetryPhase && (
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
            {renderWithLinks(phase.reasoning)}
          </p>
        </div>
      )}

      {/* Orchestrator messages */}
      {phase.orchestratorMessages.length > 0 && (
        <div className="ml-5 mb-1.5 space-y-0.5">
          {phase.orchestratorMessages.map((msg, i) => (
            <div key={i} className="flex items-start gap-1.5 text-xs">
              <MessageSquare className="h-3 w-3 text-primary/50 flex-shrink-0 mt-0.5" />
              <span className="text-muted-foreground whitespace-pre-wrap">{renderWithLinks(msg.text)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Agent blocks */}
      {phase.agents.map((block, i) => {
        const isLastAttempt = i === phase.agents.length - 1

        // For retries: show earlier failed attempts as compact one-liners with error reason
        // Only the latest attempt gets the full AgentSection treatment
        if (isRetryPhase && !isLastAttempt) {
          const reason = block.errorMessage
            ? `: ${truncateText(block.errorMessage, 80)}`
            : ""
          return (
            <div key={`${block.agent}-${i}`} className="ml-5 flex items-center gap-1.5 py-0.5 opacity-60">
              <AlertCircle className="h-3 w-3 text-red-400 flex-shrink-0" />
              <span className="text-[10px] text-muted-foreground">
                Attempt {i + 1} failed{reason}
              </span>
            </div>
          )
        }

        // Full rendering for: the last retry attempt, parallel agents, or single agents
        return <AgentSection key={`${block.agent}-${i}`} block={block} isLive={isLive} />
      })}
    </div>
  )
}

// ──────────────────────────────────────────────────────────
// Main component
// ──────────────────────────────────────────────────────────

export function InferenceSteps({ steps, isInferencing, plan }: InferenceStepsProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  // Build phases: prefer plan tasks if available, fall back to event-based
  const phases = useMemo((): Phase[] => {
    if (plan && plan.tasks.length > 0) {
      // ════════════════════════════════════════════════════════════════
      // PLAN-BASED RENDERING (source of truth)
      //
      // Data flow:
      //   Backend creates AgentModeTask objects with "[Step N] description"
      //   Plan is persisted in message metadata as workflow_plan
      //   Frontend groups tasks by step number into visual phases
      //
      // Design decisions:
      //   1. Step number is extracted from "[Step N]" prefix in task_description
      //   2. Tasks with same step number are grouped (retries, parallel steps)
      //   3. Task description is cleaned: "[Step N] text" → "text"
      //   4. Events (steps prop) add tool/progress detail to phases
      //   5. Events are matched to agents, not to individual task invocations
      //      (because we can't reliably know which retry an event belongs to)
      //   6. For agents with multiple tasks, events go to the FIRST phase only
      // ════════════════════════════════════════════════════════════════

      // --- Step 1: Group events by agent name (for enriching phases) ---
      const eventsByAgent = new Map<string, StepData[]>()
      for (const step of steps) {
        if (step.agent === "foundry-host-agent") continue  // orchestrator events handled separately
        const key = step.agent
        if (!eventsByAgent.has(key)) eventsByAgent.set(key, [])
        eventsByAgent.get(key)!.push(step)
      }

      // --- Step 2: Build phases from plan tasks ---
      const planPhases: Phase[] = []
      const stepPhaseMap = new Map<number, Phase>()
      // Track which agents have already been assigned events (first occurrence wins)
      const agentsWithEvents = new Set<string>()

      for (let idx = 0; idx < plan.tasks.length; idx++) {
        const task = plan.tasks[idx]
        const agentName = task.recommended_agent || "Unknown Agent"

        // Extract step number from "[Step 3]" or "[Step 2a]" prefix
        let stepNum = idx + 1  // fallback if no prefix
        const stepMatch = task.task_description.match(/\[Step\s+(\d+)[a-z]?\]/)
        if (stepMatch) {
          stepNum = parseInt(stepMatch[1], 10) || idx + 1
        }

        // Clean the task description: remove "[Step N] " prefix for display
        const cleanDescription = task.task_description.replace(/^\[Step\s+\d+[a-z]?\]\s*/, "")

        // Clean output: strip HITL internal metadata
        let displayOutput = task.output?.result || undefined
        if (displayOutput) {
          displayOutput = displayOutput.replace(/^HITL Response:\s*/i, "")
          const trimmed = displayOutput.trim()
          // Empty or whitespace-only → don't show
          if (!trimmed) {
            displayOutput = undefined
          } else if (trimmed.length < 20 && /^(approve|approved|yes|no|reject|ok|confirm)$/i.test(trimmed)) {
            displayOutput = `✅ User responded: "${trimmed}"`
          }
        }

        // Assign events to this agent block ONLY if this is the first task for this agent
        // For retries (same agent, same step number), the plan output is sufficient
        let taskEvents: StepData[] = []
        if (!agentsWithEvents.has(agentName)) {
          agentsWithEvents.add(agentName)
          const agentEvents = eventsByAgent.get(agentName) || []
          // Try partial match if exact name doesn't work
          if (agentEvents.length === 0) {
            const lowerName = agentName.toLowerCase().replace(/[\s\-_]/g, "")
            for (const [key, events] of eventsByAgent.entries()) {
              const lowerKey = key.toLowerCase().replace(/[\s\-_]/g, "")
              if (lowerKey.includes(lowerName) || lowerName.includes(lowerKey)) {
                taskEvents = events.filter(e => {
                  const et = e.eventType || ""
                  return et !== "agent_start" && et !== "agent_complete"
                })
                break
              }
            }
          } else {
            taskEvents = agentEvents.filter(e => {
              const et = e.eventType || ""
              return et !== "agent_start" && et !== "agent_complete"
            })
          }
        }

        // Map task state to UI status
        // "submitted" tasks haven't started — they're rendered but shown as pending
        const uiStatus: AgentBlock["status"] =
          task.state === "completed" ? "complete" :
          task.state === "failed" ? "error" :
          task.state === "input_required" ? "input_required" :
          task.state === "submitted" || task.state === "pending" ? "waiting" : "running"

        const agentBlock: AgentBlock = {
          agent: agentName,
          displayName: getDisplayName(agentName),
          color: getAgentColor(agentName),
          status: uiStatus,
          taskDescription: cleanDescription,
          output: displayOutput,
          errorMessage: task.error_message || undefined,
          steps: taskEvents,
        }

        // Group into phases by step number
        const isTerminal = task.state === "completed" || task.state === "failed"
        const existingPhase = stepPhaseMap.get(stepNum)
        if (existingPhase) {
          // Same step number = retry or parallel sibling → add to existing phase
          existingPhase.agents.push(agentBlock)
          // Phase is "complete" (done) when the LATEST task reached a terminal state
          existingPhase.isComplete = isTerminal
        } else {
          const phase: Phase = {
            type: "planning",
            stepNumber: stepNum,
            agents: [agentBlock],
            orchestratorMessages: [],
            isComplete: isTerminal,
            reasoning: idx === 0 ? plan.reasoning : undefined,
          }
          planPhases.push(phase)
          stepPhaseMap.set(stepNum, phase)
        }
      }

      // --- Step 3: Collect orchestrator events into an init phase ---
      // Document extraction, routing, and other pre-workflow events
      // (orchestrator events are excluded from eventsByAgent, so use original steps)
      const seen = new Set<string>()
      const orchestratorEvents = steps
        .filter(s => s.agent === "foundry-host-agent")
        .filter(s => {
          // Deduplicate by status text
          if (seen.has(s.status)) return false
          seen.add(s.status)
          return true
        })

      const initPhase: Phase = {
        type: "init",
        agents: [],
        orchestratorMessages: [],
        isComplete: true,
      }

      for (const event of orchestratorEvents) {
        const et = event.eventType || ""
        const status = event.status || ""
        const statusLower = status.toLowerCase()
        if (isNoiseMessage(status)) continue
        if (et === "reasoning" || et === "phase") continue
        // Skip planning/routing/agent management noise
        if (statusLower.includes("planning step")) continue
        if (statusLower.includes("agents available")) continue
        if (statusLower.includes("route decision")) continue
        if (statusLower.includes("executing step")) continue
        if (statusLower.includes("executing parallel")) continue
        if (statusLower.includes("initializing orchestration")) continue
        if (statusLower.includes("resuming workflow")) continue
        if (statusLower.includes("workflow paused")) continue
        if (statusLower.includes("goal achieved")) continue
        if (statusLower.includes("generating workflow summary")) continue
        // Only keep genuinely useful init events: document extraction, file processing
        if (status.includes("📄") || status.includes("Extracted") ||
            status.includes("chunks") || status.includes("memory")) {
          initPhase.orchestratorMessages.push({ text: status, type: "info" })
        }
      }

      // Renumber plan phases sequentially (close gaps like 1, 2, 5 → 1, 2, 3)
      const renumbered = renumberPhases(planPhases)

      if (initPhase.orchestratorMessages.length > 0) {
        return [initPhase, ...renumbered]
      }
      return renumbered
    }

    // No plan available — nothing to render
    return []
  }, [steps, plan])

  const uniqueAgents = useMemo(() => {
    if (plan && plan.tasks.length > 0) {
      // Use plan tasks as source of truth for agent list
      const agents = new Set<string>()
      for (const t of plan.tasks) {
        const a = t.recommended_agent
        if (a && a !== "foundry-host-agent" && a !== "Unknown Agent") {
          agents.add(a)
        }
      }
      return Array.from(agents).map(getDisplayName)
    }
    // Fallback: infer from events
    const s = new Set(steps.map(st => st.agent))
    s.delete("foundry-host-agent")
    return Array.from(s).map(getDisplayName)
  }, [steps, plan])

  // Auto-scroll
  useEffect(() => {
    if (containerRef.current && isInferencing) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [steps, isInferencing])

  const planningPhases = phases.filter(p => p.type === "planning")
  const hasFailures = planningPhases.some(p => {
    // For retries (same agent): only the last attempt matters
    const isRetry = p.agents.length > 1 && p.agents.every(a => a.agent === p.agents[0].agent)
    if (isRetry) {
      const last = p.agents[p.agents.length - 1]
      return last?.status === "error"
    }
    // For parallel or single agents: any failure counts
    return p.agents.some(a => a.status === "error")
  })
  const summaryLabel = uniqueAgents.length > 0
    ? `${uniqueAgents.length} agent${uniqueAgents.length !== 1 ? "s" : ""} · ${planningPhases.length} step${planningPhases.length !== 1 ? "s" : ""}`
    : `${steps.length} events`

  // Clean goal text - remove internal metadata like "[User Provided Additional Info]: ..."
  const cleanGoal = useMemo(() => {
    if (!plan?.goal) return null
    let goal = plan.goal
    // Remove "[User Provided Additional Info]: ..." suffix (everything after it)
    const hitlIdx = goal.indexOf("\n\n[User Provided Additional Info]:")
    if (hitlIdx >= 0) goal = goal.substring(0, hitlIdx)
    // Remove "[Additional Information Provided]: ..." suffix
    const addlIdx = goal.indexOf("\n\n[Additional Information Provided]:")
    if (addlIdx >= 0) goal = goal.substring(0, addlIdx)
    return goal.trim()
  }, [plan?.goal])

  if (isInferencing) {
    return (
      <div className="flex items-start gap-3 w-full">
        <div className="h-8 w-8 flex items-center justify-center flex-shrink-0">
          <Loader className="h-5 w-5 animate-spin text-primary" />
        </div>
        <div className="rounded-xl p-4 bg-muted/50 border border-border/50 flex-1 shadow-sm">
          {/* Goal display */}
          {cleanGoal && (
            <div className="mb-3 pb-2 border-b border-border/30">
              <div className="flex items-center gap-2 mb-1">
                <Brain className="h-3.5 w-3.5 text-amber-500" />
                <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Goal</span>
                <span className={`text-[9px] px-1.5 py-0.5 rounded-full ml-auto ${
                  hasFailures
                    ? "bg-red-500/10 text-red-600"
                    : plan?.goal_status === "completed" 
                      ? "bg-emerald-500/10 text-emerald-600" 
                      : "bg-blue-500/10 text-blue-600"
                }`}>
                  {hasFailures ? "Completed with errors" : plan?.goal_status === "completed" ? "Completed" : "In Progress"}
                </span>
              </div>
              <p className="text-xs text-foreground/80 leading-relaxed">{cleanGoal}</p>
            </div>
          )}

          <div className="flex items-center justify-between mb-2">
            <p className="font-semibold text-sm flex items-center gap-2">
              <Workflow className="h-4 w-4 text-primary" />
              Workflow in progress
            </p>
            <span className="text-[10px] text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
              {summaryLabel}
            </span>
          </div>

          {/* Agent status chips removed - redundant with step-level agent display */}

          <div ref={containerRef} className="space-y-0.5 max-h-[350px] overflow-y-auto pr-1">
            {phases.map((phase, i) => (
              <PhaseBlock key={i} phase={phase} isLive={true} />
            ))}
          </div>
        </div>
      </div>
    )
  }

  // ── Collapsed accordion (after completion) ──
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
          {/* Goal display for completed workflows with plan */}
          {cleanGoal && (
            <div className="mb-3 pb-2 border-b border-border/30">
              <div className="flex items-center gap-2 mb-1">
                <Brain className="h-3.5 w-3.5 text-amber-500" />
                <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Goal</span>
                <span className={`text-[9px] px-1.5 py-0.5 rounded-full ml-auto ${
                  hasFailures
                    ? "bg-red-500/10 text-red-600"
                    : plan?.goal_status === "completed" 
                      ? "bg-emerald-500/10 text-emerald-600" 
                      : "bg-blue-500/10 text-blue-600"
                }`}>
                  {hasFailures ? "Completed with errors" : plan?.goal_status === "completed" ? "Completed" : "In Progress"}
                </span>
              </div>
              <p className="text-xs text-foreground/80 leading-relaxed">{cleanGoal}</p>
            </div>
          )}
          
          {/* Agent status chips removed - redundant with step-level agent display */}
          
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
