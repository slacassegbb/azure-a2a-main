"use client"

import React, { useMemo } from "react"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { CheckCircle2, Loader, AlertCircle, MessageSquare, Bot, Workflow, Wrench, FileSearch, Send, Zap } from "lucide-react"

interface StepEvent {
  agent: string
  status: string
  eventType?: string
  metadata?: Record<string, any>
  taskId?: string
}

interface InferenceStepsProps {
  steps: StepEvent[]
  isInferencing: boolean
  plan?: any
}

interface AgentInfo {
  name: string
  displayName: string
  color: string
  taskDescription: string
  status: "running" | "complete" | "error" | "waiting"
  output: string | null
  progressMessages: string[]
}

interface OrchestratorActivity {
  type: "tool_call" | "agent_dispatch" | "planning" | "document" | "info"
  label: string
  detail?: string
  timestamp: number
}

const COLORS = ["#8b5cf6", "#06b6d4", "#10b981", "#f59e0b", "#ec4899", "#3b82f6", "#f97316", "#14b8a6"]

function getAgentColor(name: string): string {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = ((hash << 5) - hash + name.charCodeAt(i)) | 0
  }
  return COLORS[Math.abs(hash) % COLORS.length]
}

function formatAgentName(name: string): string {
  if (!name) return "Agent"
  if (name === "foundry-host-agent") return "Orchestrator"
  return name
    .replace(/^azurefoundry[_-]/i, "")
    .replace(/^AI Foundry\s+/i, "")
    .replace(/[-_]/g, " ")
    .split(" ")
    .map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ")
}

interface ParsedData {
  agents: AgentInfo[]
  orchestratorActivities: OrchestratorActivity[]
  orchestratorStatus: "idle" | "planning" | "dispatching" | "complete"
}

function parseEventsToAgents(steps: StepEvent[]): ParsedData {
  const agentMap = new Map<string, AgentInfo>()
  const orchestratorActivities: OrchestratorActivity[] = []
  let orchestratorStatus: "idle" | "planning" | "dispatching" | "complete" = "idle"
  let activityIndex = 0
  
  for (const step of steps) {
    const agentName = step.agent
    if (!agentName) continue
    
    const eventType = step.eventType || ""
    const content = step.status || ""
    
    // Handle orchestrator events separately
    if (agentName === "foundry-host-agent") {
      activityIndex++
      
      if (eventType === "tool_call") {
        const toolName = step.metadata?.tool_name || "tool"
        const isDocTool = toolName.includes("file_search") || toolName.includes("document") || toolName.includes("search")
        const isAgentCall = toolName.includes("send_task") || toolName.includes("agent")
        orchestratorActivities.push({
          type: isDocTool ? "document" : isAgentCall ? "agent_dispatch" : "tool_call",
          label: isDocTool ? "Searching documents" : isAgentCall ? "Dispatching to agent" : `Using ${toolName}`,
          detail: step.metadata?.arguments ? JSON.stringify(step.metadata.arguments).slice(0, 100) : undefined,
          timestamp: activityIndex,
        })
        orchestratorStatus = "dispatching"
      } else if (eventType === "phase" || content.includes("Planning") || content.includes("planning") || content.includes("Analyzing")) {
        const phaseLabel = step.metadata?.phase === "planning" ? `Planning step ${step.metadata?.step_number || ""}` : "Planning workflow"
        orchestratorActivities.push({
          type: "planning",
          label: phaseLabel,
          detail: content,
          timestamp: activityIndex,
        })
        orchestratorStatus = "planning"
      } else if (content.includes("Delegating") || content.includes("Calling") || content.includes("Dispatching") || content.includes("agents available")) {
        // Extract agent name if mentioned
        const agentMatch = content.match(/(?:to|calling|dispatching)\s+([A-Za-z\s]+(?:Agent)?)/i)
        orchestratorActivities.push({
          type: "agent_dispatch",
          label: agentMatch ? `Calling ${agentMatch[1].trim()}` : content.includes("agents available") ? content : "Dispatching to agent",
          detail: content,
          timestamp: activityIndex,
        })
        orchestratorStatus = "dispatching"
      } else if (eventType === "agent_complete" || content.includes("complete") || content.includes("finished")) {
        orchestratorStatus = "complete"
      } else if (content.length > 5) {
        // Other info messages
        orchestratorActivities.push({
          type: "info",
          label: content.slice(0, 60),
          timestamp: activityIndex,
        })
      }
      continue
    }
    
    // Handle regular agents
    if (!agentMap.has(agentName)) {
      agentMap.set(agentName, {
        name: agentName,
        displayName: formatAgentName(agentName),
        color: getAgentColor(agentName),
        taskDescription: "",
        status: "running",
        output: null,
        progressMessages: [],
      })
    }
    
    const agent = agentMap.get(agentName)!
    
    if (eventType === "agent_start") {
      agent.taskDescription = step.metadata?.task_description || content
      agent.status = "running"
    } else if (eventType === "agent_output") {
      agent.output = content
    } else if (eventType === "agent_complete") {
      agent.status = "complete"
    } else if (eventType === "agent_error") {
      agent.status = "error"
      if (!agent.output) agent.output = content
    } else if (eventType === "info" || eventType === "agent_progress") {
      if (content && content.length > 5 && !agent.progressMessages.includes(content)) {
        agent.progressMessages.push(content)
      }
    } else if (content.includes("input_required") || content.includes("Waiting for")) {
      agent.status = "waiting"
    }
  }
  
  return {
    agents: Array.from(agentMap.values()),
    orchestratorActivities,
    orchestratorStatus,
  }
}

function OrchestratorSection({ activities, status, isLive }: { activities: OrchestratorActivity[]; status: string; isLive: boolean }) {
  if (activities.length === 0 && !isLive) return null
  
  const getIcon = (type: OrchestratorActivity["type"]) => {
    switch (type) {
      case "tool_call": return <Wrench className="h-3 w-3" />
      case "document": return <FileSearch className="h-3 w-3" />
      case "agent_dispatch": return <Send className="h-3 w-3" />
      case "planning": return <Zap className="h-3 w-3" />
      default: return <Bot className="h-3 w-3" />
    }
  }
  
  const isWorking = isLive && status !== "complete"
  
  return (
    <div className="mb-3 pb-3 border-b border-border/30">
      <div className="flex items-center gap-2 mb-2">
        {isWorking ? (
          <div className="relative flex items-center justify-center h-5 w-5">
            <div className="h-2.5 w-2.5 rounded-full bg-violet-500 animate-pulse" />
          </div>
        ) : (
          <CheckCircle2 className="h-4 w-4 text-emerald-500" />
        )}
        <span className="text-xs font-semibold text-violet-600">Orchestrator</span>
        {isWorking && <span className="text-[10px] text-muted-foreground">coordinating...</span>}
      </div>
      
      {activities.length > 0 && (
        <div className="ml-5 space-y-1">
          {activities.slice(-5).map((activity, i) => (
            <div key={i} className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="text-violet-500/70">{getIcon(activity.type)}</span>
              <span>{activity.label}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function AgentCard({ agent, stepNumber, isLive }: { agent: AgentInfo; stepNumber: number; isLive: boolean }) {
  const { displayName, color, taskDescription, status, output, progressMessages } = agent
  
  const isRunning = status === "running"
  const isComplete = status === "complete"
  const isError = status === "error"
  const isWaiting = status === "waiting"

  return (
    <div className="py-2">
      <div className="flex items-center gap-2 mb-1.5">
        <div className={`flex items-center justify-center h-5 w-5 rounded-full text-[10px] font-bold ${
          isComplete ? "bg-emerald-500/15 text-emerald-600" :
          isError ? "bg-red-500/15 text-red-600" :
          isWaiting ? "bg-amber-500/15 text-amber-600" :
          "bg-primary/15 text-primary"
        }`}>
          {stepNumber}
        </div>
        <span className="text-xs font-semibold text-foreground">Step {stepNumber}</span>
        {isComplete && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />}
        {isError && <AlertCircle className="h-3.5 w-3.5 text-red-500" />}
        {isWaiting && <MessageSquare className="h-3.5 w-3.5 text-amber-500" />}
        {isRunning && isLive && <Loader className="h-3.5 w-3.5 animate-spin text-primary" />}
      </div>

      <div className="ml-5 border-l-2 pl-4 py-1.5" style={{ borderColor: `${color}40` }}>
        <div className="flex items-center gap-2 mb-1">
          {isRunning && isLive ? (
            <div className="relative flex items-center justify-center h-4 w-4">
              <div className="h-2 w-2 rounded-full animate-pulse" style={{ backgroundColor: color }} />
            </div>
          ) : isComplete ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
          ) : isError ? (
            <AlertCircle className="h-4 w-4 text-red-500" />
          ) : isWaiting ? (
            <MessageSquare className="h-4 w-4 text-amber-500" />
          ) : (
            <Bot className="h-4 w-4" style={{ color }} />
          )}
          <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ backgroundColor: `${color}15`, color }}>
            {displayName}
          </span>
          {isComplete && <span className="text-[10px] text-emerald-600">Done</span>}
          {isError && <span className="text-[10px] text-red-600">Failed</span>}
          {isWaiting && <span className="text-[10px] text-amber-600">Waiting for input</span>}
          {isRunning && isLive && <span className="text-[10px] text-primary">Working...</span>}
        </div>

        {taskDescription && (
          <p className="text-xs text-muted-foreground ml-6 mb-1.5">{taskDescription.replace(/^Starting:\s*/i, "").replace(/\.\.\.$/g, "")}</p>
        )}

        {isLive && isRunning && progressMessages.length > 0 && (
          <div className="ml-6 space-y-0.5 mb-1.5">
            {progressMessages.slice(-3).map((msg, i) => (
              <div key={i} className="text-xs text-muted-foreground/70 truncate">› {msg.slice(0, 80)}</div>
            ))}
          </div>
        )}

        {output && (
          <div className="ml-6 mt-1.5 rounded-md px-3 py-2 text-xs border-l-2 max-h-[300px] overflow-y-auto" style={{ borderColor: color, backgroundColor: `${color}08` }}>
            <div className="text-foreground/80 whitespace-pre-wrap">{output}</div>
          </div>
        )}
      </div>
    </div>
  )
}

export function InferenceSteps({ steps, isInferencing, plan }: InferenceStepsProps) {
  const { agents, orchestratorActivities, orchestratorStatus } = useMemo(() => parseEventsToAgents(steps), [steps])
  const summaryLabel = agents.length > 0 ? `${agents.length} agent${agents.length !== 1 ? "s" : ""}` : ""
  const hasOrchestratorActivity = orchestratorActivities.length > 0

  if (agents.length === 0 && !hasOrchestratorActivity && !isInferencing) return null

  if (agents.length === 0 && !hasOrchestratorActivity && isInferencing) {
    return (
      <div className="flex items-start gap-3 w-full">
        <div className="h-8 w-8 flex items-center justify-center flex-shrink-0">
          <Loader className="h-5 w-5 animate-spin text-primary" />
        </div>
        <div className="rounded-xl p-4 bg-muted/50 border border-border/50 flex-1">
          <p className="text-sm text-muted-foreground">Starting workflow...</p>
        </div>
      </div>
    )
  }

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
            {summaryLabel && <span className="text-[10px] text-muted-foreground bg-muted px-2 py-0.5 rounded-full">{summaryLabel}</span>}
          </div>
          
          <OrchestratorSection activities={orchestratorActivities} status={orchestratorStatus} isLive={true} />
          
          <div className="space-y-1 max-h-[400px] overflow-y-auto pr-1">
            {agents.map((agent: AgentInfo, i: number) => <AgentCard key={agent.name} agent={agent} stepNumber={i + 1} isLive={true} />)}
          </div>
        </div>
      </div>
    )
  }

  const hasErrors = agents.some((a: AgentInfo) => a.status === "error")
  
  return (
    <Accordion type="single" collapsible className="w-full">
      <AccordionItem value="workflow" className="border border-border/50 bg-muted/30 rounded-xl px-4 shadow-sm">
        <AccordionTrigger className="hover:no-underline py-3">
          <div className="flex items-center gap-2.5">
            <div className={`h-7 w-7 rounded-lg flex items-center justify-center ${hasErrors ? "bg-amber-500/10" : "bg-emerald-500/10"}`}>
              {hasErrors ? <AlertCircle className="h-4 w-4 text-amber-500" /> : <CheckCircle2 className="h-4 w-4 text-emerald-500" />}
            </div>
            <span className="font-medium text-sm">{hasErrors ? "Workflow completed with errors" : "Workflow completed"}</span>
            {summaryLabel && <span className="text-xs text-muted-foreground ml-1">{summaryLabel}</span>}
          </div>
        </AccordionTrigger>
        <AccordionContent>
          <OrchestratorSection activities={orchestratorActivities} status={orchestratorStatus} isLive={false} />
          <div className="space-y-1 pt-1 pb-2 max-h-[400px] overflow-y-auto">
            {agents.map((agent: AgentInfo, i: number) => <AgentCard key={agent.name} agent={agent} stepNumber={i + 1} isLive={false} />)}
          </div>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  )
}
