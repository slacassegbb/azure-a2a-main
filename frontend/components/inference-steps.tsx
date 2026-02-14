"use client"

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
  output?: string
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

function mkPhase(type: PhaseType, opts?: Partial<Phase>): Phase {
  return { type, agents: [], orchestratorMessages: [], isComplete: false, ...opts }
}

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
    lower.includes(" is working on:") ||
    lower.includes("has started working on:") ||
    lower === "working on:" ||
    lower === "started:" ||
    lower.length < 5
  )
}

function buildPhases(steps: StepData[]): Phase[] {
  const phases: Phase[] = []
  let currentPhase: Phase | null = null
  let currentAgent: AgentBlock | null = null
  let phaseStepNum = 0
  
  // Track seen step numbers to avoid duplicates
  const seenStepNumbers = new Set<number>()

  const getOrCreatePhase = (stepNum?: number): Phase => {
    // If we have a step number, check if phase already exists
    if (stepNum !== undefined && seenStepNumbers.has(stepNum)) {
      // Find existing phase with this step number
      const existing = phases.find(p => p.type === "planning" && p.stepNumber === stepNum)
      if (existing) {
        currentPhase = existing
        return existing
      }
    }
    
    // Create new phase only if needed
    if (!currentPhase || currentPhase.type === "complete" || currentPhase.type === "synthesis") {
      const num = stepNum ?? phaseStepNum + 1
      phaseStepNum = num
      seenStepNumbers.add(num)
      currentPhase = mkPhase("planning", { stepNumber: num })
      phases.push(currentPhase)
    }
    return currentPhase
  }

  for (const step of steps) {
    const et = step.eventType || ""
    const isOrchestrator = step.agent === "foundry-host-agent"
    const meta = step.metadata || {}

    // ── Phase markers ──
    if (et === "phase") {
      const phaseName = meta.phase as string || ""

      if (phaseName === "init" || phaseName === "routing" || phaseName === "orchestration_start" || phaseName === "hitl_resume") {
        if (!currentPhase || currentPhase.type !== "init") {
          currentPhase = mkPhase("init")
          phases.push(currentPhase)
        }
        continue
      }
      if (phaseName === "planning" || phaseName === "planning_ai") {
        const stepNum = meta.step_number || phaseStepNum + 1
        getOrCreatePhase(stepNum)
        currentAgent = null
        continue
      }
      if (phaseName === "synthesis") {
        currentPhase = mkPhase("synthesis")
        phases.push(currentPhase)
        continue
      }
      if (phaseName === "complete") {
        if (currentPhase) currentPhase.isComplete = true
        currentPhase = mkPhase("complete", { isComplete: true, stepNumber: meta.iterations })
        phases.push(currentPhase)
        continue
      }
      // Ignore other phase markers, don't create new phases
      continue
    }

    // ── Reasoning - add to current phase, don't create new one ──
    if (et === "reasoning") {
      if (currentPhase && currentPhase.type === "planning") {
        currentPhase.reasoning = step.status
      } else {
        // If no planning phase yet, create one
        const phase = getOrCreatePhase()
        phase.reasoning = step.status
      }
      continue
    }

    // ── Info events ──
    if (et === "info") {
      if (isOrchestrator) {
        const text = step.status
        if (text.length > 10 && !isNoiseMessage(text)) {
          const phase = currentPhase || getOrCreatePhase()
          // Avoid duplicate messages
          if (!phase.orchestratorMessages.some(m => m.text === text)) {
            phase.orchestratorMessages.push({ text, type: "info" })
          }
        }
      } else {
        // Agent info - add to agent steps
        if (currentAgent && currentAgent.agent === step.agent) {
          if (!isNoiseMessage(step.status)) {
            currentAgent.steps.push({ ...step, eventType: "agent_progress" })
          }
        }
      }
      continue
    }

    // ── Agent start ──
    if (et === "agent_start" && !isOrchestrator) {
      const phase = getOrCreatePhase()
      currentAgent = {
        agent: step.agent,
        displayName: getDisplayName(step.agent),
        color: getAgentColor(step.agent),
        steps: [],
        status: "running",
        taskDescription: meta.task_description || step.status,
      }
      phase.agents.push(currentAgent)
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

    // ── Tool calls and progress ──
    if (et === "tool_call" || et === "agent_progress") {
      // Filter noise messages
      if (isNoiseMessage(step.status)) continue
      
      if (isOrchestrator) {
        const phase = currentPhase || getOrCreatePhase()
        const text = step.status
        const sl = text.toLowerCase()
        if (sl.length > 10 &&
            !sl.includes("planning next task") &&
            !sl.includes("agents available") &&
            !isNoiseMessage(text)) {
          if (!phase.orchestratorMessages.some(m => m.text === text)) {
            phase.orchestratorMessages.push({ text, type: "progress" })
          }
        }
      } else {
        if (currentAgent && currentAgent.agent === step.agent) {
          currentAgent.steps.push(step)
        } else {
          const phase = getOrCreatePhase()
          currentAgent = {
            agent: step.agent,
            displayName: getDisplayName(step.agent),
            color: getAgentColor(step.agent),
            steps: [step],
            status: "running",
          }
          phase.agents.push(currentAgent)
        }
      }
      continue
    }

    // ── Fallback: untyped events ──
    if (!et) {
      const statusLower = step.status.toLowerCase()
      
      // Filter noise
      if (isNoiseMessage(step.status)) continue

      if (isOrchestrator) {
        if (statusLower.includes("planning step")) {
          const match = step.status.match(/step\s*(\d+)/i)
          const stepNum = match ? parseInt(match[1]) : phaseStepNum + 1
          getOrCreatePhase(stepNum)
          currentAgent = null
          continue
        }
        if (statusLower.startsWith("reasoning:")) {
          const phase = currentPhase || getOrCreatePhase()
          phase.reasoning = step.status.replace(/^Reasoning:\s*/i, "")
          continue
        }
        if (statusLower.includes("goal achieved") || statusLower.includes("generating workflow summary")) {
          currentPhase = mkPhase("synthesis")
          phases.push(currentPhase)
          continue
        }
        // Show other orchestrator messages
        if (statusLower.length > 10 &&
            !statusLower.includes("initializing") &&
            !statusLower.includes("resuming")) {
          const phase = currentPhase || getOrCreatePhase()
          if (!phase.orchestratorMessages.some(m => m.text === step.status)) {
            phase.orchestratorMessages.push({ text: step.status, type: "info" })
          }
        }
        continue
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
          const phase = getOrCreatePhase()
          currentAgent = {
            agent: step.agent,
            displayName: getDisplayName(step.agent),
            color: getAgentColor(step.agent),
            steps: [{ ...step, eventType: isToolLike ? "tool_call" : "agent_progress" }],
            status: "running",
          }
          phase.agents.push(currentAgent)
        }
        continue
      }
    }
  }

  // Post-process: Remove empty planning phases
  return phases.filter(phase => {
    if (phase.type === "planning") {
      return phase.agents.length > 0 || phase.orchestratorMessages.length > 0 || phase.reasoning
    }
    return true
  })
}

// ──────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────

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

// ──────────────────────────────────────────────────────────
// Sub-components
// ──────────────────────────────────────────────────────────

function AgentSection({ block, isLive }: { block: AgentBlock; isLive: boolean }) {
  const isRunning = block.status === "running" && isLive
  const isComplete = block.status === "complete"
  const isError = block.status === "error"

  // Filter out noise and duplicates from progress steps
  const toolSteps = block.steps.filter(s => (s.eventType || "") === "tool_call")
  const progressSteps = block.steps.filter(s => {
    const et = s.eventType || ""
    if (et === "tool_call") return false
    // Filter redundant progress messages
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
          {block.taskDescription}
        </p>
      )}

      {/* Tool calls */}
      {toolSteps.length > 0 && (
        <div className="ml-6 space-y-0.5 mb-1">
          {toolSteps.map((s, i) => (
            <div key={i} className="flex items-center gap-1.5 text-xs">
              <Wrench className="h-3 w-3 text-muted-foreground/70 flex-shrink-0" />
              <span className="text-muted-foreground">{formatToolAction(cleanAgentStatus(s.status))}</span>
            </div>
          ))}
        </div>
      )}

      {/* Progress messages - show full content */}
      {uniqueProgressSteps.map((s, i) => (
        <div key={`p-${i}`} className="flex items-start gap-1.5 text-xs ml-6 mb-1">
          <ChevronRight className="h-3 w-3 text-muted-foreground/50 flex-shrink-0 mt-0.5" />
          <span className="text-muted-foreground whitespace-pre-wrap">{cleanAgentStatus(s.status)}</span>
        </div>
      ))}

      {/* Agent output / result - show more content */}
      {block.output && (
        <div
          className="ml-6 mt-1.5 rounded-md px-3 py-2 text-xs leading-relaxed border-l-2 max-h-[300px] overflow-y-auto"
          style={{ borderColor: block.color, backgroundColor: `${block.color}08` }}
        >
          <span className="text-foreground/80 whitespace-pre-wrap">
            {stripMarkdown(cleanAgentStatus(block.output))}
          </span>
        </div>
      )}
    </div>
  )
}

function PhaseBlock({ phase, isLive, isLast }: { phase: Phase; isLive: boolean; isLast: boolean }) {
  if (phase.type === "init") {
    if (phase.orchestratorMessages.length === 0) return null
    return (
      <div className="py-1">
        {phase.orchestratorMessages.map((msg, i) => (
          <div key={i} className="flex items-start gap-1.5 text-xs ml-1 mb-0.5">
            <MessageSquare className="h-3 w-3 text-primary/60 flex-shrink-0 mt-0.5" />
            <span className="text-muted-foreground whitespace-pre-wrap">{msg.text}</span>
          </div>
        ))}
      </div>
    )
  }

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
          <p className="text-[11px] text-muted-foreground leading-relaxed italic whitespace-pre-wrap">
            {phase.reasoning}
          </p>
        </div>
      )}

      {/* Orchestrator messages */}
      {phase.orchestratorMessages.length > 0 && (
        <div className="ml-5 mb-1.5 space-y-0.5">
          {phase.orchestratorMessages.map((msg, i) => (
            <div key={i} className="flex items-start gap-1.5 text-xs">
              <MessageSquare className="h-3 w-3 text-primary/50 flex-shrink-0 mt-0.5" />
              <span className="text-muted-foreground whitespace-pre-wrap">{msg.text}</span>
            </div>
          ))}
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
