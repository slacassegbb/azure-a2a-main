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
    (lower.includes(" is working on:") && lower.length < 100) ||
    (lower.includes("has started working on:") && lower.length < 100) ||
    lower === "working on:" ||
    lower === "started:" ||
    lower.length < 5
  )
}

function buildPhases(steps: StepData[]): Phase[] {
  const phases: Phase[] = []
  let currentPhase: Phase | null = null
  let currentAgent: AgentBlock | null = null
  let lastStepNumber = 0
  
  // Map step numbers to phases to avoid duplicates
  const stepPhaseMap = new Map<number, Phase>()

  // Helper to get or create a planning phase for a specific step number
  const getOrCreatePlanningPhase = (stepNum: number): Phase => {
    // Check if we already have this step number
    const existing = stepPhaseMap.get(stepNum)
    if (existing) {
      currentPhase = existing
      return existing
    }
    
    // Create new planning phase
    lastStepNumber = Math.max(lastStepNumber, stepNum)
    const phase = mkPhase("planning", { stepNumber: stepNum })
    phases.push(phase)
    stepPhaseMap.set(stepNum, phase)
    currentPhase = phase
    return phase
  }
  
  // Helper to ensure we have ANY planning phase (auto-increment step number)
  const ensureAnyPlanningPhase = (): Phase => {
    if (currentPhase && currentPhase.type === "planning") {
      return currentPhase
    }
    return getOrCreatePlanningPhase(lastStepNumber + 1)
  }
  
  // Helper to find or create agent block
  const getAgentBlock = (agentName: string, phase: Phase): AgentBlock => {
    let block = phase.agents.find(a => a.agent === agentName)
    if (!block) {
      block = {
        agent: agentName,
        displayName: getDisplayName(agentName),
        color: getAgentColor(agentName),
        steps: [],
        status: "running",
      } as AgentBlock
      phase.agents.push(block)
    }
    currentAgent = block
    return block
  }
  
  // Helper to get current agent if it matches
  const getCurrentAgentIfMatch = (agentName: string): AgentBlock | null => {
    if (currentAgent && currentAgent.agent === agentName) {
      return currentAgent
    }
    return null
  }

  for (const step of steps) {
    const et = step.eventType || ""
    const isOrchestrator = step.agent === "foundry-host-agent"
    const meta = step.metadata || {}
    const statusLower = step.status.toLowerCase()

    // ── Phase markers ──
    if (et === "phase") {
      const phaseName = meta.phase as string || ""
      
      if (phaseName === "init" || phaseName === "routing" || phaseName === "orchestration_start") {
        if (!currentPhase || currentPhase.type !== "init") {
          currentPhase = mkPhase("init")
          phases.push(currentPhase)
        }
        continue
      }
      if (phaseName === "planning" || phaseName === "planning_ai") {
        const stepNum = meta.step_number || lastStepNumber + 1
        getOrCreatePlanningPhase(stepNum)
        currentAgent = null
        continue
      }
      if (phaseName === "synthesis") {
        currentPhase = mkPhase("synthesis")
        phases.push(currentPhase)
        continue
      }
      if (phaseName === "complete") {
        currentPhase = mkPhase("complete", { isComplete: true })
        phases.push(currentPhase)
        continue
      }
      if (phaseName === "hitl_resume") {
        // Continue with current planning phase
        continue
      }
      continue
    }

    // ── Reasoning ──
    if (et === "reasoning") {
      // Reasoning always goes to a planning phase
      const phase = currentPhase?.type === "planning" ? currentPhase : ensureAnyPlanningPhase()
      phase.reasoning = step.status
      continue
    }

    // ── Agent start ──
    if (et === "agent_start" && !isOrchestrator) {
      const phase = ensureAnyPlanningPhase()
      const block = getAgentBlock(step.agent, phase)
      block.taskDescription = meta.task_description || step.status
      continue
    }

    // ── Agent complete ──
    if (et === "agent_complete" && !isOrchestrator) {
      const agent = getCurrentAgentIfMatch(step.agent)
      if (agent) {
        agent.status = "complete"
      }
      continue
    }

    // ── Agent output ──
    if (et === "agent_output" && !isOrchestrator) {
      const agent = getCurrentAgentIfMatch(step.agent)
      if (agent) {
        agent.output = step.status
      }
      continue
    }

    // ── Agent error ──
    if (et === "agent_error") {
      const agent = getCurrentAgentIfMatch(step.agent)
      if (agent) {
        agent.status = "error"
        agent.steps.push(step)
      }
      continue
    }

    // ── Info events ──
    if (et === "info") {
      if (isOrchestrator) {
        // Orchestrator info messages: use current phase, or create init if no phase exists
        let phase: Phase = currentPhase as Phase
        if (!currentPhase) {
          phase = mkPhase("init")
          phases.push(phase)
          currentPhase = phase
        }
        if (step.status.length > 10 && !isNoiseMessage(step.status)) {
          phase.orchestratorMessages.push({ text: step.status, type: "info" })
        }
      } else {
        const phase = ensureAnyPlanningPhase()
        const block = getAgentBlock(step.agent, phase)
        if (!isNoiseMessage(step.status)) {
          block.steps.push(step)
        }
      }
      continue
    }

    // ── Tool calls and progress ──
    if (et === "tool_call" || et === "agent_progress") {
      if (isOrchestrator) {
        // Orchestrator progress: use current phase, or create init if no phase exists
        let phase: Phase = currentPhase as Phase
        if (!currentPhase) {
          phase = mkPhase("init")
          phases.push(phase)
          currentPhase = phase
        }
        if (step.status.length > 10 && !isNoiseMessage(step.status)) {
          phase.orchestratorMessages.push({ text: step.status, type: "progress" })
        }
      } else {
        const phase = ensureAnyPlanningPhase()
        const block = getAgentBlock(step.agent, phase)
        if (!isNoiseMessage(step.status)) {
          block.steps.push(step)
        }
      }
      continue
    }

    // ── Fallback: untyped events ──
    if (!et) {
      // Skip noise
      if (isNoiseMessage(step.status)) continue

      if (isOrchestrator) {
        // Check for phase markers in content
        if (statusLower.includes("planning step")) {
          const match = step.status.match(/step\s*(\d+)/i)
          lastStepNumber = match ? parseInt(match[1]) : lastStepNumber + 1
          currentPhase = mkPhase("planning", { stepNumber: lastStepNumber })
          phases.push(currentPhase)
          currentAgent = null
          continue
        }
        if (statusLower.startsWith("reasoning:")) {
          const phase = currentPhase?.type === "planning" ? currentPhase : ensureAnyPlanningPhase()
          phase.reasoning = step.status.replace(/^Reasoning:\s*/i, "")
          continue
        }
        if (statusLower.includes("goal achieved") || statusLower.includes("generating workflow summary")) {
          currentPhase = mkPhase("synthesis")
          phases.push(currentPhase)
          continue
        }
        // General orchestrator message
        if (step.status.length > 10) {
          const phase = currentPhase || ensureAnyPlanningPhase()
          phase.orchestratorMessages.push({ text: step.status, type: "info" })
        }
        continue
      }

      // Non-orchestrator agent event
      if (statusLower.includes("completed the task") || statusLower.includes("completed successfully")) {
        const agent = getCurrentAgentIfMatch(step.agent)
        if (agent) {
          agent.status = "complete"
        }
        continue
      }

      // Regular agent activity
      const phase = ensureAnyPlanningPhase()
      const block = getAgentBlock(step.agent, phase)
      const isToolLike = statusLower.includes("🛠️") || statusLower.includes("creating ") || 
                         statusLower.includes("searching ") || statusLower.includes("retrieving ")
      block.steps.push({ ...step, eventType: isToolLike ? "tool_call" : "agent_progress" })
    }
  }

  // Post-process: Remove empty planning phases (no agents, no messages, no reasoning)
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
