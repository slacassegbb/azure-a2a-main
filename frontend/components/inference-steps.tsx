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

// FALLBACK: Build phases from individual events when no plan is available
// This is used for backward compatibility with old messages or before plan arrives
// The primary rendering path uses plan.tasks directly (see main component)
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

      {/* Progress messages - show full content with clickable links */}
      {uniqueProgressSteps.map((s, i) => (
        <div key={`p-${i}`} className="flex items-start gap-1.5 text-xs ml-6 mb-1">
          <ChevronRight className="h-3 w-3 text-muted-foreground/50 flex-shrink-0 mt-0.5" />
          <span className="text-muted-foreground whitespace-pre-wrap">{renderWithLinks(cleanAgentStatus(s.status))}</span>
        </div>
      ))}

      {/* Agent output / result - show full content with clickable links */}
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

function PhaseBlock({ phase, isLive, isLast }: { phase: Phase; isLive: boolean; isLast: boolean }) {
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
      {phase.agents.map((block, i) => (
        <AgentSection key={`${block.agent}-${i}`} block={block} isLive={isLive && isLast} />
      ))}
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
      // Build phases from plan tasks (source of truth)
      // Match events to tasks based on agent name for real-time progress
      const eventsByAgent = new Map<string, StepData[]>()
      for (const step of steps) {
        const agent = step.agent
        if (!eventsByAgent.has(agent)) {
          eventsByAgent.set(agent, [])
        }
        eventsByAgent.get(agent)!.push(step)
      }

      const planPhases = plan.tasks.map((task, idx): Phase => {
        const agentName = task.recommended_agent || "Unknown Agent"
        // Try exact match first, then try case-insensitive partial match
        let agentEvents = eventsByAgent.get(agentName) || []
        if (agentEvents.length === 0) {
          // Try to find events by partial match (e.g., "Email Agent" matches "azurefoundry_email-agent")
          const lowerAgentName = agentName.toLowerCase().replace(/[\s-_]/g, "")
          for (const [key, events] of eventsByAgent.entries()) {
            const lowerKey = key.toLowerCase().replace(/[\s-_]/g, "")
            if (lowerKey.includes(lowerAgentName) || lowerAgentName.includes(lowerKey)) {
              agentEvents = events
              break
            }
          }
        }
        
        // Filter events relevant to this task (progress messages)
        const progressSteps = agentEvents.filter(e => {
          const et = e.eventType || ""
          return et !== "agent_start" && et !== "agent_complete"
        })

        return {
          type: "planning",
          stepNumber: idx + 1,
          agents: [{
            agent: agentName,
            displayName: getDisplayName(agentName),
            color: getAgentColor(agentName),
            status: task.state === "completed" ? "complete" : 
                    task.state === "failed" ? "error" : "running",
            taskDescription: task.task_description,
            output: task.output?.result || undefined,
            steps: progressSteps,
          }],
          orchestratorMessages: [],
          isComplete: task.state === "completed",
          reasoning: idx === 0 ? plan.reasoning : undefined,
        }
      })

      // Add orchestrator events to the appropriate phases
      const orchestratorEvents = eventsByAgent.get("foundry-host-agent") || []
      if (orchestratorEvents.length > 0 && planPhases.length > 0) {
        // Add reasoning/phase messages to first phase
        for (const event of orchestratorEvents) {
          const et = event.eventType || ""
          if (et === "reasoning" || et === "phase") {
            // Already have reasoning from plan, skip duplicates
            continue
          }
          // Add as orchestrator message to first phase
          if (!isNoiseMessage(event.status)) {
            planPhases[0].orchestratorMessages.push({ text: event.status, type: "info" })
          }
        }
      }

      return planPhases
    }
    // Fall back to event-based rendering
    return renumberPhases(buildPhases(steps))
  }, [steps, plan])

  const uniqueAgents = useMemo(() => {
    // Prefer plan agents if available (includes agents that may not have emitted events yet)
    if (plan && plan.tasks.length > 0) {
      const agents = new Set(plan.tasks.map(t => t.recommended_agent).filter(Boolean))
      // Also add any agents from events not in plan
      steps.forEach(st => {
        if (st.agent !== "foundry-host-agent") {
          agents.add(st.agent)
        }
      })
      return Array.from(agents).map(a => getDisplayName(a as string))
    }
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
  const summaryLabel = uniqueAgents.length > 0
    ? `${uniqueAgents.length} agent${uniqueAgents.length !== 1 ? "s" : ""} · ${planningPhases.length} step${planningPhases.length !== 1 ? "s" : ""}`
    : `${steps.length} events`

  // Build agent status map from plan tasks OR infer from events
  const agentStatusMap = useMemo(() => {
    const map = new Map<string, { state: string; task: string }>()
    
    if (plan && plan.tasks.length > 0) {
      // Use plan tasks as source of truth
      for (const task of plan.tasks) {
        if (task.recommended_agent) {
          // Keep the most recent (or running) state per agent
          const existing = map.get(task.recommended_agent)
          if (!existing || task.state === "running" || (task.state === "completed" && existing.state !== "running")) {
            map.set(task.recommended_agent, { state: task.state, task: task.task_description })
          }
        }
      }
    } else {
      // No plan - infer status from events for single-agent calls
      for (const step of steps) {
        if (step.agent === "foundry-host-agent") continue
        const existing = map.get(step.agent)
        const eventType = step.eventType || ""
        
        if (eventType === "agent_complete") {
          map.set(step.agent, { state: "completed", task: step.status })
        } else if (eventType === "agent_error") {
          map.set(step.agent, { state: "failed", task: step.status })
        } else if (!existing || existing.state === "pending") {
          // Any activity means running
          map.set(step.agent, { state: "running", task: step.status })
        }
      }
    }
    return map
  }, [plan, steps])

  // Get status badge style
  const getStatusStyle = (state: string) => {
    switch (state) {
      case "completed":
        return { bg: "bg-emerald-500/10", text: "text-emerald-600", label: "Done" }
      case "running":
        return { bg: "bg-blue-500/10", text: "text-blue-600", label: "Working" }
      case "failed":
        return { bg: "bg-red-500/10", text: "text-red-600", label: "Error" }
      case "input_required":
        return { bg: "bg-amber-500/10", text: "text-amber-600", label: "Waiting" }
      default:
        return { bg: "bg-muted", text: "text-muted-foreground", label: "Pending" }
    }
  }

  if (isInferencing) {
    return (
      <div className="flex items-start gap-3 w-full">
        <div className="h-8 w-8 flex items-center justify-center flex-shrink-0">
          <Loader className="h-5 w-5 animate-spin text-primary" />
        </div>
        <div className="rounded-xl p-4 bg-muted/50 border border-border/50 flex-1 shadow-sm">
          {/* Goal display */}
          {plan?.goal && (
            <div className="mb-3 pb-2 border-b border-border/30">
              <div className="flex items-center gap-2 mb-1">
                <Brain className="h-3.5 w-3.5 text-amber-500" />
                <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Goal</span>
                <span className={`text-[9px] px-1.5 py-0.5 rounded-full ml-auto ${
                  plan.goal_status === "completed" 
                    ? "bg-emerald-500/10 text-emerald-600" 
                    : "bg-blue-500/10 text-blue-600"
                }`}>
                  {plan.goal_status === "completed" ? "Completed" : "In Progress"}
                </span>
              </div>
              <p className="text-xs text-foreground/80 leading-relaxed">{plan.goal}</p>
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

          {/* Agent chips with status */}
          {(uniqueAgents.length > 0 || agentStatusMap.size > 0) && (
            <div className="flex flex-wrap gap-1.5 mb-3">
              {(plan && plan.tasks.length > 0 ? 
                Array.from(new Set(plan.tasks.map(t => t.recommended_agent).filter(Boolean))) : 
                uniqueAgents
              ).map(name => {
                const agentName = name as string
                const displayName = getDisplayName(agentName)
                const color = getAgentColor(agentName)
                const statusInfo = agentStatusMap.get(agentName)
                const statusStyle = getStatusStyle(statusInfo?.state || "pending")
                
                return (
                  <div key={agentName} className="flex items-center gap-1">
                    <span
                      className="text-[10px] font-medium px-2 py-0.5 rounded-l-full"
                      style={{ backgroundColor: `${color}12`, color, border: `1px solid ${color}30`, borderRight: 'none' }}
                    >
                      {displayName}
                    </span>
                    <span className={`text-[9px] font-medium px-1.5 py-0.5 rounded-r-full ${statusStyle.bg} ${statusStyle.text}`}
                      style={{ borderTop: `1px solid ${color}30`, borderRight: `1px solid ${color}30`, borderBottom: `1px solid ${color}30` }}
                    >
                      {statusInfo?.state === "running" && <Loader className="h-2 w-2 animate-spin inline mr-0.5" />}
                      {statusInfo?.state === "completed" && <CheckCircle2 className="h-2 w-2 inline mr-0.5" />}
                      {statusStyle.label}
                    </span>
                  </div>
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
          {/* Goal display for completed workflows with plan */}
          {plan?.goal && (
            <div className="mb-3 pb-2 border-b border-border/30">
              <div className="flex items-center gap-2 mb-1">
                <Brain className="h-3.5 w-3.5 text-amber-500" />
                <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Goal</span>
                <span className={`text-[9px] px-1.5 py-0.5 rounded-full ml-auto ${
                  plan.goal_status === "completed" 
                    ? "bg-emerald-500/10 text-emerald-600" 
                    : "bg-blue-500/10 text-blue-600"
                }`}>
                  {plan.goal_status === "completed" ? "Completed" : "In Progress"}
                </span>
              </div>
              <p className="text-xs text-foreground/80 leading-relaxed">{plan.goal}</p>
            </div>
          )}
          
          {/* Agent status chips */}
          {plan && plan.tasks && plan.tasks.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-3">
              {Array.from(new Set(plan.tasks.map((t: any) => t.recommended_agent).filter(Boolean))).map(agentName => {
                const displayName = getDisplayName(agentName as string)
                const color = getAgentColor(agentName as string)
                const task = plan.tasks.find((t: any) => t.recommended_agent === agentName)
                const statusStyle = getStatusStyle(task?.state || "completed")
                
                return (
                  <div key={agentName as string} className="flex items-center gap-1">
                    <span
                      className="text-[10px] font-medium px-2 py-0.5 rounded-l-full"
                      style={{ backgroundColor: `${color}12`, color, border: `1px solid ${color}30`, borderRight: 'none' }}
                    >
                      {displayName}
                    </span>
                    <span className={`text-[9px] font-medium px-1.5 py-0.5 rounded-r-full ${statusStyle.bg} ${statusStyle.text}`}
                      style={{ borderTop: `1px solid ${color}30`, borderRight: `1px solid ${color}30`, borderBottom: `1px solid ${color}30` }}
                    >
                      {task?.state === "completed" && <CheckCircle2 className="h-2 w-2 inline mr-0.5" />}
                      {statusStyle.label}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
          
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
