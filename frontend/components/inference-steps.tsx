"use client"

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { CheckCircle2, Loader, Workflow, Wrench, Brain, ChevronRight, Bot, AlertCircle } from "lucide-react"
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

type InferenceStepsProps = {
  steps: StepData[]
  isInferencing: boolean
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

type PhaseType = "init" | "planning" | "agent_execution" | "synthesis" | "complete"

interface AgentBlock {
  agent: string
  displayName: string
  color: string
  steps: StepData[]
  status: "running" | "complete" | "error"
  taskDescription?: string
  output?: string  // Agent's final response text
}

interface Phase {
  type: PhaseType
  stepNumber?: number
  reasoning?: string
  agents: AgentBlock[]
  isComplete: boolean
}

function buildPhases(steps: StepData[]): Phase[] {
  const phases: Phase[] = []
  let currentPhase: Phase | null = null
  let currentAgent: AgentBlock | null = null
  let phaseStepNum = 0

  for (const step of steps) {
    const et = step.eventType || ""
    const isOrchestrator = step.agent === "foundry-host-agent"
    const meta = step.metadata || {}

    // ── Phase markers ──
    if (et === "phase") {
      const phaseName = meta.phase as string || ""

      if (phaseName === "init") {
        currentPhase = { type: "init", agents: [], isComplete: false }
        phases.push(currentPhase)
        continue
      }
      if (phaseName === "planning" || phaseName === "planning_ai") {
        phaseStepNum = meta.step_number || phaseStepNum + 1
        currentPhase = { type: "planning", stepNumber: phaseStepNum, agents: [], isComplete: false }
        currentAgent = null
        phases.push(currentPhase)
        continue
      }
      if (phaseName === "synthesis") {
        currentPhase = { type: "synthesis", agents: [], isComplete: false }
        phases.push(currentPhase)
        continue
      }
      if (phaseName === "complete") {
        if (currentPhase) currentPhase.isComplete = true
        currentPhase = { type: "complete", agents: [], isComplete: true, stepNumber: meta.iterations }
        phases.push(currentPhase)
        continue
      }
      // Other phase events (routing, orchestration_start, parallel_execution, step_execution, hitl_resume, etc.)
      // Create an execution phase so these don't get dropped
      if (phaseName === "routing" || phaseName === "orchestration_start" || phaseName === "hitl_resume") {
        currentPhase = { type: "init", agents: [], isComplete: false }
        phases.push(currentPhase)
        continue
      }
      if (phaseName === "parallel_execution" || phaseName === "step_execution" || phaseName === "parallel_agents" || phaseName === "parallel_workflows") {
        if (!currentPhase || currentPhase.type === "complete" || currentPhase.type === "init") {
          phaseStepNum++
          currentPhase = { type: "planning", stepNumber: phaseStepNum, agents: [], isComplete: false }
          phases.push(currentPhase)
        }
        continue
      }
      continue
    }

    // ── Info events (routing decisions, status updates) ──
    if (et === "info") {
      // Info events are lightweight status updates — skip orchestrator noise, attach agent ones
      if (isOrchestrator) continue
      if (currentAgent && currentAgent.agent === step.agent) {
        currentAgent.steps.push({ ...step, eventType: "agent_progress" })
      }
      continue
    }

    // ── Reasoning ──
    if (et === "reasoning" && currentPhase) {
      currentPhase.reasoning = step.status
      continue
    }

    // ── Agent start ──
    if (et === "agent_start" && !isOrchestrator) {
      if (!currentPhase || currentPhase.type === "complete" || currentPhase.type === "init") {
        phaseStepNum++
        currentPhase = { type: "planning", stepNumber: phaseStepNum, agents: [], isComplete: false }
        phases.push(currentPhase)
      }

      currentAgent = {
        agent: step.agent,
        displayName: getDisplayName(step.agent),
        color: getAgentColor(step.agent),
        steps: [],
        status: "running",
        taskDescription: meta.task_description || step.status,
      }
      currentPhase.agents.push(currentAgent)
      continue
    }

    // ── Agent complete ──
    if (et === "agent_complete") {
      if (currentAgent && currentAgent.agent === step.agent) {
        currentAgent.status = "complete"
      }
      continue
    }

    // ── Agent output (final response text) ──
    if (et === "agent_output") {
      if (currentAgent && currentAgent.agent === step.agent) {
        currentAgent.output = step.status
      }
      continue
    }

    // ── Agent error ──
    if (et === "agent_error") {
      if (currentAgent && currentAgent.agent === step.agent) {
        currentAgent.status = "error"
        currentAgent.steps.push(step)
      }
      continue
    }

    // ── Tool calls and progress from agents ──
    if ((et === "tool_call" || et === "agent_progress") && !isOrchestrator) {
      if (currentAgent && currentAgent.agent === step.agent) {
        currentAgent.steps.push(step)
      } else {
        // Implicit agent block
        if (!currentPhase || currentPhase.type === "complete" || currentPhase.type === "init") {
          phaseStepNum++
          currentPhase = { type: "planning", stepNumber: phaseStepNum, agents: [], isComplete: false }
          phases.push(currentPhase)
        }
        currentAgent = {
          agent: step.agent,
          displayName: getDisplayName(step.agent),
          color: getAgentColor(step.agent),
          steps: [step],
          status: "running",
        }
        currentPhase.agents.push(currentAgent)
      }
      continue
    }

    // ── Fallback: untyped events (backwards compat with old backend) ──
    if (!et) {
      const statusLower = step.status.toLowerCase()

      if (isOrchestrator) {
        if (statusLower.includes("planning step")) {
          const match = step.status.match(/step\s*(\d+)/i)
          phaseStepNum = match ? parseInt(match[1]) : phaseStepNum + 1
          currentPhase = { type: "planning", stepNumber: phaseStepNum, agents: [], isComplete: false }
          currentAgent = null
          phases.push(currentPhase)
          continue
        }
        if (statusLower.startsWith("reasoning:")) {
          if (currentPhase) currentPhase.reasoning = step.status.replace(/^Reasoning:\s*/i, "")
          continue
        }
        if (statusLower.includes("goal achieved") || statusLower.includes("generating workflow summary")) {
          currentPhase = { type: "synthesis", agents: [], isComplete: false }
          phases.push(currentPhase)
          continue
        }
        // Skip generic orchestrator noise
        if (statusLower.includes("initializing") || statusLower.includes("resuming") ||
            statusLower.includes("agents available") || statusLower.includes("planning next task") ||
            statusLower.includes("calling agent")) {
          continue
        }
      }

      // Agent completion
      if (statusLower.includes("completed the task") || statusLower.includes("completed successfully")) {
        if (currentAgent && currentAgent.agent === step.agent) {
          currentAgent.status = "complete"
        }
        continue
      }

      // Agent activity
      if (!isOrchestrator) {
        const isToolLike = statusLower.includes("creating ") || statusLower.includes("searching ") ||
          statusLower.includes("looking up") || statusLower.includes("retrieving ") ||
          statusLower.includes("using ") || statusLower.includes("🛠️")

        if (currentAgent && currentAgent.agent === step.agent) {
          currentAgent.steps.push({ ...step, eventType: isToolLike ? "tool_call" : "agent_progress" })
        } else {
          if (!currentPhase || currentPhase.type === "complete") {
            phaseStepNum++
            currentPhase = { type: "planning", stepNumber: phaseStepNum, agents: [], isComplete: false }
            phases.push(currentPhase)
          }
          currentAgent = {
            agent: step.agent,
            displayName: getDisplayName(step.agent),
            color: getAgentColor(step.agent),
            steps: [{ ...step, eventType: isToolLike ? "tool_call" : "agent_progress" }],
            status: "running",
          }
          currentPhase.agents.push(currentAgent)
        }
        continue
      }
    }
  }

  return phases
}

// ──────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────

function formatToolAction(status: string): string {
  let s = status
    .replace(/^🛠️\s*/, "")
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

// Strip common markdown formatting for clean display
function stripMarkdown(text: string): string {
  return text
    .replace(/#{1,6}\s+/g, "")         // headers
    .replace(/\*\*(.+?)\*\*/g, "$1")   // bold
    .replace(/\*(.+?)\*/g, "$1")       // italic
    .replace(/__(.+?)__/g, "$1")       // bold alt
    .replace(/_(.+?)_/g, "$1")         // italic alt
    .replace(/`(.+?)`/g, "$1")         // inline code
    .replace(/^\s*[-*]\s+/gm, "• ")    // list items → bullet
    .replace(/\n{3,}/g, "\n\n")        // collapse excess newlines
    .trim()
}

// ──────────────────────────────────────────────────────────
// Sub-components
// ──────────────────────────────────────────────────────────

function AgentSection({ block, isLive }: { block: AgentBlock; isLive: boolean }) {
  const isRunning = block.status === "running" && isLive
  const isComplete = block.status === "complete"
  const isError = block.status === "error"

  const toolSteps = block.steps.filter(s => (s.eventType || "") === "tool_call")
  const progressSteps = block.steps.filter(s => {
    const et = s.eventType || ""
    if (et === "tool_call") return false
    const sl = s.status.toLowerCase()
    // Filter out contacting/working-on/request-sent noise
    return !sl.includes("contacting ") && !sl.includes("is working on") && !sl.includes("request sent to")
  })

  return (
    <div className="ml-5 border-l-2 pl-4 py-2" style={{ borderColor: `${block.color}40` }}>
      {/* Agent header */}
      <div className="flex items-center gap-2 mb-1.5">
        {isRunning ? (
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

        {isComplete && (
          <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-medium">Done</span>
        )}
      </div>

      {/* Task description */}
      {block.taskDescription && (
        <p className="text-xs text-muted-foreground ml-6 mb-1.5 leading-relaxed">
          {truncateText(block.taskDescription, 120)}
        </p>
      )}

      {/* Tool calls */}
      {toolSteps.length > 0 && (
        <div className="ml-6 space-y-0.5 mb-1">
          {toolSteps.map((s, i) => (
            <div key={i} className="flex items-center gap-1.5 text-xs">
              <Wrench className="h-3 w-3 text-muted-foreground/70 flex-shrink-0" />
              <span className="text-muted-foreground">{formatToolAction(s.status)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Progress messages */}
      {progressSteps.map((s, i) => (
        <div key={`p-${i}`} className="flex items-start gap-1.5 text-xs ml-6">
          <ChevronRight className="h-3 w-3 text-muted-foreground/50 flex-shrink-0 mt-0.5" />
          <span className="text-muted-foreground">{truncateText(s.status, 150)}</span>
        </div>
      ))}

      {/* Agent output / result */}
      {block.output && (
        <div
          className="ml-6 mt-1.5 rounded-md px-3 py-2 text-xs leading-relaxed border-l-2"
          style={{ borderColor: block.color, backgroundColor: `${block.color}08` }}
        >
          <span className="text-foreground/80 whitespace-pre-wrap">
            {stripMarkdown(truncateText(block.output, 300))}
          </span>
        </div>
      )}
    </div>
  )
}

function PhaseBlock({ phase, isLive, isLast }: { phase: Phase; isLive: boolean; isLast: boolean }) {
  if (phase.type === "init") return null

  if (phase.type === "complete") {
    return (
      <div className="flex items-center gap-2 py-1.5">
        <CheckCircle2 className="h-4 w-4 text-emerald-500" />
        <span className="text-xs font-medium text-emerald-600 dark:text-emerald-400">
          Workflow complete
        </span>
      </div>
    )
  }

  if (phase.type === "synthesis") {
    return (
      <div className="flex items-center gap-2 py-1.5">
        {isLive ? (
          <Loader className="h-3.5 w-3.5 animate-spin text-primary" />
        ) : (
          <CheckCircle2 className="h-4 w-4 text-emerald-500" />
        )}
        <span className="text-xs font-medium text-muted-foreground">Generating summary…</span>
      </div>
    )
  }

  // Planning + agent execution phase
  const phaseComplete = phase.agents.length > 0 && phase.agents.every(a => a.status === "complete")
  const phaseRunning = isLive && !phaseComplete

  return (
    <div className="py-1">
      {/* Step header */}
      <div className="flex items-center gap-2 mb-1">
        <div className={`flex items-center justify-center h-5 w-5 rounded-full text-[10px] font-bold ${
          phaseComplete
            ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
            : phaseRunning
              ? "bg-primary/15 text-primary"
              : "bg-muted text-muted-foreground"
        }`}>
          {phase.stepNumber || "•"}
        </div>
        <span className="text-xs font-semibold text-foreground">
          Step {phase.stepNumber}
        </span>
        {phaseComplete && <CheckCircle2 className="h-3 w-3 text-emerald-500" />}
        {phaseRunning && <Loader className="h-3 w-3 animate-spin text-primary" />}
      </div>

      {/* Reasoning */}
      {phase.reasoning && (
        <div className="ml-5 mb-1.5 flex items-start gap-1.5">
          <Brain className="h-3 w-3 text-amber-500 flex-shrink-0 mt-0.5" />
          <p className="text-[11px] text-muted-foreground leading-relaxed italic">
            {truncateText(phase.reasoning, 200)}
          </p>
        </div>
      )}

      {/* Agent blocks */}
      {phase.agents.map((block, i) => (
        <AgentSection key={`${block.agent}-${i}`} block={block} isLive={isLive && isLast} />
      ))}
    </div>
  )
}

// ──────────────────────────────────────────────────────────
// Main component
// ──────────────────────────────────────────────────────────

export function InferenceSteps({ steps, isInferencing }: InferenceStepsProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  const phases = useMemo(() => buildPhases(steps), [steps])

  const uniqueAgents = useMemo(() => {
    const s = new Set(steps.map(st => st.agent))
    s.delete("foundry-host-agent")
    return Array.from(s).map(getDisplayName)
  }, [steps])

  // Auto-scroll
  useEffect(() => {
    if (containerRef.current && isInferencing) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [steps, isInferencing])

  const planningPhases = phases.filter(p => p.type === "planning")
  const summaryLabel = uniqueAgents.length > 0
    ? `${uniqueAgents.length} agent${uniqueAgents.length !== 1 ? "s" : ""} · ${planningPhases.length} step${planningPhases.length !== 1 ? "s" : ""}`
    : `${steps.length} events`

  if (isInferencing) {
    return (
      <div className="flex items-start gap-3 w-full">
        <div className="h-8 w-8 flex items-center justify-center flex-shrink-0">
          <Loader className="h-5 w-5 animate-spin text-primary" />
        </div>
        <div className="rounded-xl p-4 bg-muted/50 border border-border/50 flex-1 shadow-sm">
          <div className="flex items-center justify-between mb-2">
            <p className="font-semibold text-sm flex items-center gap-2">
              <Workflow className="h-4 w-4 text-primary" />
              Workflow in progress
            </p>
            <span className="text-[10px] text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
              {summaryLabel}
            </span>
          </div>

          {/* Agent chips */}
          {uniqueAgents.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-3">
              {uniqueAgents.map(name => {
                const color = getAgentColor(name)
                return (
                  <span
                    key={name}
                    className="text-[10px] font-medium px-2 py-0.5 rounded-full"
                    style={{ backgroundColor: `${color}12`, color, border: `1px solid ${color}30` }}
                  >
                    {name}
                  </span>
                )
              })}
            </div>
          )}

          <div ref={containerRef} className="space-y-0.5 max-h-[350px] overflow-y-auto pr-1">
            {phases.map((phase, i) => (
              <PhaseBlock key={i} phase={phase} isLive={true} isLast={i === phases.length - 1} />
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
            <div className="h-7 w-7 rounded-lg bg-emerald-500/10 flex items-center justify-center">
              <CheckCircle2 className="h-4 w-4 text-emerald-500" />
            </div>
            <span className="font-medium text-sm">Workflow completed</span>
            <span className="text-xs text-muted-foreground ml-1">{summaryLabel}</span>
          </div>
        </AccordionTrigger>
        <AccordionContent>
          <div className="space-y-0.5 pt-1 pb-2 max-h-[400px] overflow-y-auto">
            {phases.map((phase, i) => (
              <PhaseBlock key={i} phase={phase} isLive={false} isLast={false} />
            ))}
          </div>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  )
}
