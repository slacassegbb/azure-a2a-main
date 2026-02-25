"use client"

import React, { useMemo } from "react"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { CheckCircle2, Loader, AlertCircle, MessageSquare, Bot, Workflow, Wrench, FileSearch, Send, Zap, FileText, Paperclip, Square } from "lucide-react"
import { getAgentHexColor } from "@/lib/agent-colors"
import { logDebug } from '@/lib/debug'

interface StepEvent {
  agent: string
  status: string
  eventType?: string
  metadata?: Record<string, any>
  taskId?: string
  imageUrl?: string
  imageName?: string
  mediaType?: string
}

interface InferenceStepsProps {
  steps: StepEvent[]
  isInferencing: boolean
  plan?: any
  cancelled?: boolean
  agentColors?: Record<string, string>
}

interface AgentInfo {
  name: string
  displayName: string
  color: string
  taskDescription: string
  status: "running" | "complete" | "error" | "waiting" | "cancelled"
  output: string | null
  progressMessages: string[]
  extractedFiles: { name: string; url?: string; type?: string }[]
  stepNumber?: string  // Extracted from [Step X] in content, e.g. "2", "2a", "2b"
  mapKey: string       // Unique key for React rendering (handles parallel same-agent cards)
}

interface OrchestratorActivity {
  type: "tool_call" | "agent_dispatch" | "planning" | "document" | "info"
  label: string
  detail?: string
  timestamp: number
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
  orchestratorStatus: "idle" | "planning" | "dispatching" | "complete" | "error"
}

function parseEventsToAgents(steps: StepEvent[], agentColors?: Record<string, string>): ParsedData {
  const agentMap = new Map<string, AgentInfo>()
  const orchestratorActivities: OrchestratorActivity[] = []
  const seenOrchestratorLabels = new Set<string>()
  let orchestratorStatus: "idle" | "planning" | "dispatching" | "complete" | "error" = "idle"
  let activityIndex = 0
  // Track the current map key for each agent name to support multiple invocations
  // When an agent completes and new events arrive, a new key (e.g., "AgentName::2") is created
  const currentAgentKey = new Map<string, string>()
  
  // Debug: log all incoming steps
  logDebug("[InferenceSteps] Parsing steps:", steps.map(s => ({ agent: s.agent, eventType: s.eventType, statusLen: s.status?.length, hasImage: !!s.imageUrl })))

  // Debug: specifically check for Teams Agent
  const teamsEvents = steps.filter(s => s.agent?.toLowerCase().includes("teams"))
  if (teamsEvents.length > 0) {
    logDebug("[InferenceSteps] TEAMS AGENT EVENTS FOUND:", teamsEvents)
  } else {
    logDebug("[InferenceSteps] No Teams Agent events in steps array")
  }
  
  for (const step of steps) {
    const agentName = step.agent
    if (!agentName) continue
    
    const eventType = step.eventType || ""
    const content = step.status || ""
    
    // Handle orchestrator events - show useful info about what the orchestrator is doing
    if (agentName === "foundry-host-agent") {
      let activity: OrchestratorActivity | null = null
      const phase = step.metadata?.phase  // Check phase early for both "phase" and "info" events
      
      if (eventType === "reasoning" && content) {
        // The AI's reasoning about what to do - this is the most valuable!
        activityIndex++
        activity = {
          type: "planning",
          label: content,  // Show full reasoning, UI will handle overflow
          timestamp: activityIndex,
        }
        orchestratorStatus = "planning"
      } else if (eventType === "phase" || (eventType === "info" && phase)) {
        // Phase events describe what step is being executed
        // Also handle "info" events that have a phase in metadata
        if (phase === "step_execution") {
          activityIndex++
          const stepLabel = step.metadata?.step_label || ""
          activity = {
            type: "agent_dispatch",
            label: `Executing Step ${stepLabel}`,
            detail: content,
            timestamp: activityIndex,
          }
          orchestratorStatus = "dispatching"
        } else if (phase === "complete") {
          orchestratorStatus = "complete"
        } else if (phase === "parallel_execution") {
          activityIndex++
          activity = {
            type: "agent_dispatch",
            label: `Running ${step.metadata?.steps || "multiple"} agents in parallel`,
            timestamp: activityIndex,
          }
          orchestratorStatus = "dispatching"
        } else if (phase === "preflight_check") {
          activityIndex++
          activity = {
            type: "info",
            label: content || "Preparing agents...",
            timestamp: activityIndex,
          }
        } else if (phase === "workflow_planning") {
          activityIndex++
          activity = {
            type: "planning",
            label: content || "Planning workflow steps...",
            timestamp: activityIndex,
          }
          orchestratorStatus = "planning"
        } else if (phase === "document_indexing") {
          // Orchestrator received files from agent
          activityIndex++
          activity = {
            type: "document",
            label: content,  // "📥 Received X file(s) from AgentName..."
            timestamp: activityIndex,
          }
        } else if (phase === "document_extraction") {
          // Orchestrator is extracting content from a file
          activityIndex++
          activity = {
            type: "document",
            label: content,  // "📄 Extracting content from: filename.pdf"
            timestamp: activityIndex,
          }
        } else if (phase === "document_extraction_complete") {
          // Orchestrator finished extracting - show the content preview
          activityIndex++
          activity = {
            type: "document",
            label: content,  // Full extraction message with content preview
            timestamp: activityIndex,
          }
        }
      } else if (eventType === "tool_call") {
        const toolName = step.metadata?.tool_name || "tool"
        const isDocTool = toolName.includes("file_search") || toolName.includes("document") || toolName.includes("search")
        if (isDocTool) {
          activityIndex++
          activity = {
            type: "document",
            label: "Searching documents",
            timestamp: activityIndex,
          }
        }
      } else if (content.includes("Goal achieved") || content.includes("Workflow completed")) {
        orchestratorStatus = "complete"
      } else if (content.includes("Resuming workflow")) {
        activityIndex++
        activity = {
          type: "info",
          label: "Resuming workflow with your input",
          timestamp: activityIndex,
        }
      } else if (eventType === "agent_error" || content.includes("Error in orchestration") || content.includes("Cannot run workflow")) {
        activityIndex++
        activity = {
          type: "info",
          label: content,
          timestamp: activityIndex,
        }
        orchestratorStatus = "error"
      }
      // Skip noise: "Planning step X...", "X agents available", "Initializing orchestration..."
      
      // Dedupe orchestrator activities
      if (activity && !seenOrchestratorLabels.has(activity.label)) {
        seenOrchestratorLabels.add(activity.label)
        orchestratorActivities.push(activity)
      }
      continue
    }
    
    // Skip if this looks like orchestrator content leaked through
    if (agentName.includes("foundry") || agentName.includes("host-agent")) continue
    
    // Handle regular agents - support multiple invocations of the same agent
    // Two strategies:
    // 1. Parallel calls: backend sends parallel_call_id in metadata → use as grouping key
    // 2. Sequential calls: detect when a completed agent gets new dispatch events
    const parallelCallId = step.metadata?.parallel_call_id
    let mapKey: string

    if (parallelCallId) {
      // Parallel execution: each call has a unique ID from the backend
      mapKey = `${agentName}::${parallelCallId}`
    } else {
      // Sequential execution: track by completion state
      mapKey = currentAgentKey.get(agentName) || agentName
      if (agentMap.has(mapKey)) {
        const existing = agentMap.get(mapKey)!
        // If the agent already completed and we see a new dispatch event, it's a new invocation
        const isNewDispatchEvent = eventType === "agent_start" || eventType === "agent_progress"
        if (existing.status === "complete" && isNewDispatchEvent) {
          let invocation = 2
          while (agentMap.has(`${agentName}::${invocation}`)) {
            const prev = agentMap.get(`${agentName}::${invocation}`)!
            if (prev.status !== "complete") break
            invocation++
          }
          mapKey = `${agentName}::${invocation}`
          currentAgentKey.set(agentName, mapKey)
        }
      } else {
        currentAgentKey.set(agentName, mapKey)
      }
    }

    if (!agentMap.has(mapKey)) {
      // Extract step number from content if present (supports letter suffixes like 2a, 2b for parallel)
      const stepMatch = content.match(/\[Step\s*(\d+[a-z]?)\]/i)
      agentMap.set(mapKey, {
        name: agentName,
        displayName: formatAgentName(agentName),
        color: getAgentHexColor(agentName, agentColors?.[agentName]),
        taskDescription: "",
        status: "running",
        output: null,
        progressMessages: [],
        extractedFiles: [],
        stepNumber: stepMatch ? stepMatch[1] : undefined,
        mapKey,
      })
    }

    const agent = agentMap.get(mapKey)!
    
    // Check for file extraction events (📎 prefix or imageUrl present)
    if (step.imageName || content.startsWith("📎")) {
      const fileName = step.imageName || content.replace(/^📎\s*(Extracted|Generated)\s*/i, "").trim()
      if (fileName && !agent.extractedFiles.some(f => f.name === fileName)) {
        agent.extractedFiles.push({
          name: fileName,
          url: step.imageUrl,
          type: step.mediaType,
        })
      }
      continue  // Don't process as regular event
    }
    
    // Extract step number if we haven't yet
    if (!agent.stepNumber) {
      const stepMatch = content.match(/\[Step\s*(\d+[a-z]?)\]/i)
      if (stepMatch) agent.stepNumber = stepMatch[1]
    }
    
    if (eventType === "agent_start") {
      agent.taskDescription = step.metadata?.task_description || content
      agent.status = "running"
    } else if (eventType === "agent_output") {
      // Set agent output (extraction content is now shown in orchestrator section)
      if (!agent.output || agent.output !== content) {
        agent.output = content
      }
    } else if (eventType === "agent_complete") {
      agent.status = "complete"
    } else if (eventType === "agent_error") {
      agent.status = "error"
      // Always capture error content
      if (content) {
        agent.output = agent.output ? `${agent.output}\n\n❌ Error: ${content}` : `❌ Error: ${content}`
      }
    } else if (eventType === "info" || eventType === "agent_progress") {
      const phase = step.metadata?.phase
      
      // Document indexing phases are now handled by orchestrator, skip them here
      if (phase === "document_extraction" || phase === "document_indexing" || phase === "document_extraction_complete") {
        continue  // These events go to orchestrator section, not agent cards
      }
      
      // HITL waiting state — only from structured metadata, not content guessing
      if (step.metadata?.hitl) {
        agent.status = "waiting"
      }
      if (content && content.length > 5 && !agent.progressMessages.includes(content)) {
        agent.progressMessages.push(content)
      }
    } else if (eventType === "tool_call") {
      // Tool calls from agents (not orchestrator) - add as progress
      const toolName = step.metadata?.tool_name || "tool"
      if (!agent.progressMessages.includes(`Using ${toolName}`)) {
        agent.progressMessages.push(`Using ${toolName}`)
      }
    } else if (!eventType && content) {
      // Untyped events — treat as output or progress, never override status.
      // Status comes exclusively from typed events (agent_complete, agent_error, etc.)
      if (content.length > 100) {
        if (!agent.output || agent.output.length < content.length) {
          agent.output = content
        }
      } else if (content.length > 10) {
        if (!agent.progressMessages.includes(content)) {
          agent.progressMessages.push(content)
        }
      }
    }
  }
  
  // Sort agents by step number if available (supports "2a" < "2b" < "3")
  const sortedAgents = Array.from(agentMap.values()).sort((a, b) => {
    if (a.stepNumber && b.stepNumber) {
      const aNum = parseInt(a.stepNumber)
      const bNum = parseInt(b.stepNumber)
      if (aNum !== bNum) return aNum - bNum
      // Same numeric prefix — compare suffix (e.g. "a" vs "b")
      return a.stepNumber.localeCompare(b.stepNumber)
    }
    if (a.stepNumber) return -1
    if (b.stepNumber) return 1
    return 0
  })
  
  // Debug: log parsed result
  logDebug("[InferenceSteps] Parsed agents:", sortedAgents.map(a => ({
    name: a.name,
    status: a.status,
    stepNumber: a.stepNumber,
    hasOutput: !!a.output,
    outputLen: a.output?.length,
    filesCount: a.extractedFiles.length,
    progressCount: a.progressMessages.length
  })))
  logDebug("[InferenceSteps] Orchestrator activities:", orchestratorActivities.length, orchestratorStatus)
  
  return {
    agents: sortedAgents,
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
  
  // Check if an activity is a detailed extraction (has multi-line content)
  const isDetailedExtraction = (label: string) => label.includes("**Extracted from") && label.includes("\n")
  
  const isWorking = isLive && status !== "complete" && status !== "error"
  
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
        <div className="ml-5 space-y-2">
          {activities.slice(-5).map((activity, i) => {
            // For detailed extractions, show in a scrollable box
            if (isDetailedExtraction(activity.label)) {
              return (
                <div key={i} className="space-y-1">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span className="text-violet-500/70">{getIcon(activity.type)}</span>
                    <span>Document extracted</span>
                  </div>
                  <div className="ml-5 rounded-md px-3 py-2 text-xs border border-border/50 bg-muted/30 max-h-[200px] overflow-y-auto">
                    <div className="text-foreground/80 whitespace-pre-wrap">{activity.label}</div>
                  </div>
                </div>
              )
            }
            
            // Regular activities - allow text to wrap
            return (
              <div key={i} className="flex items-start gap-2 text-xs text-muted-foreground">
                <span className="text-violet-500/70 flex-shrink-0 mt-0.5">{getIcon(activity.type)}</span>
                <span className="break-words">{activity.label}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function AgentCard({ agent, stepNumber, isLive }: { agent: AgentInfo; stepNumber: number; isLive: boolean }) {
  const { displayName, color, taskDescription, status, output, progressMessages, extractedFiles } = agent
  
  const isRunning = status === "running"
  const isComplete = status === "complete"
  const isError = status === "error"
  const isWaiting = status === "waiting"
  const isCancelled = status === "cancelled"
  
  // Use agent's extracted step number (preserving letter suffix for parallel steps like 1a, 1b)
  const displayStepNumber = agent.stepNumber || String(stepNumber)

  // Clean task description - remove [Step X] prefix (with optional letter suffix)
  const cleanTaskDesc = taskDescription?.replace(/^\[Step\s*\d+[a-z]?\]\s*/i, "").trim()

  // Clean output - remove duplicated sections (same text appearing twice)
  const cleanOutput = useMemo(() => {
    if (!output) return null
    // Remove [Step X] prefix from output
    let cleaned = output.replace(/^\[Step\s*\d+[a-z]?\]\s*/i, "").trim()
    // If output has same paragraph twice, dedupe it
    const paragraphs = cleaned.split(/\n\n+/)
    const seen = new Set<string>()
    const uniqueParagraphs = paragraphs.filter(p => {
      const normalized = p.trim().slice(0, 100) // Use first 100 chars as key
      if (seen.has(normalized)) return false
      seen.add(normalized)
      return true
    })
    return uniqueParagraphs.join("\n\n")
  }, [output])

  return (
    <div className="py-2">
      <div className="flex items-center gap-2 mb-1.5">
        <div className={`flex items-center justify-center h-5 w-5 rounded-full text-[10px] font-bold ${
          isComplete ? "bg-emerald-500/15 text-emerald-600" :
          isError ? "bg-red-500/15 text-red-600" :
          isCancelled ? "bg-gray-500/15 text-gray-600" :
          isWaiting ? "bg-amber-500/15 text-amber-600" :
          "bg-primary/15 text-primary"
        }`}>
          {displayStepNumber}
        </div>
        <span className="text-xs font-semibold text-foreground">Step {displayStepNumber}</span>
        {isComplete && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />}
        {isError && <AlertCircle className="h-3.5 w-3.5 text-red-500" />}
        {isCancelled && <Square className="h-3.5 w-3.5 text-gray-500" />}
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
          ) : isCancelled ? (
            <Square className="h-4 w-4 text-gray-500" />
          ) : isWaiting ? (
            <MessageSquare className="h-4 w-4 text-amber-500" />
          ) : (
            <Bot className="h-4 w-4" style={{ color }} />
          )}
          <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ backgroundColor: `${color}15`, color }}>
            {displayName}
          </span>
          {isComplete && <span className="text-[10px] text-emerald-600">Done</span>}
          {isError && <span className="text-[10px] text-red-600">Error</span>}
          {isCancelled && <span className="text-[10px] text-gray-600">Cancelled</span>}
          {isWaiting && <span className="text-[10px] text-amber-600">Awaiting response</span>}
          {isRunning && isLive && <span className="text-[10px] text-primary">Working...</span>}
        </div>

        {cleanTaskDesc && (
          <p className="text-xs text-muted-foreground ml-6 mb-1.5">{cleanTaskDesc.replace(/^Starting:\s*/i, "").replace(/\.\.\.$/g, "")}</p>
        )}

        {isLive && isRunning && progressMessages.length > 0 && (
          <div className="ml-6 space-y-0.5 mb-1.5">
            {progressMessages.slice(-3).map((msg, i) => (
              <div key={i} className="text-xs text-muted-foreground/70 break-words">› {msg}</div>
            ))}
          </div>
        )}

        {/* Show extracted/generated files */}
        {extractedFiles.length > 0 && (
          <div className="ml-6 mt-1.5 space-y-2">
            {extractedFiles.map((file, i) => {
              const ext = file.name.toLowerCase().split('.').pop() || ''
              const imageExtensions = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp']
              const videoExtensions = ['mp4', 'webm', 'mov', 'avi', 'mkv']
              const isImage = file.type?.startsWith('image/') || imageExtensions.includes(ext)
              const isVideo = file.type?.startsWith('video/') || videoExtensions.includes(ext)
              const isMedia = isImage || isVideo
              const label = isMedia ? "Generated" : "Attachment"
              
              return (
                <div key={i} className="space-y-1">
                  <div className="flex items-start gap-2 text-xs">
                    <span className="flex-shrink-0 mt-0.5">
                      {isMedia ? (
                        <FileText className="h-3 w-3 text-muted-foreground" />
                      ) : (
                        <Paperclip className="h-3 w-3 text-muted-foreground" />
                      )}
                    </span>
                    <span className="text-muted-foreground flex-shrink-0">{label}:</span>
                    {file.url ? (
                      <a href={file.url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline break-all">
                        {file.name}
                      </a>
                    ) : (
                      <span className="text-foreground/80 break-all">{file.name}</span>
                    )}
                  </div>
                  {/* Show image thumbnail - only for actual images, not PDFs */}
                  {isImage && file.url && (
                    <div className="ml-5">
                      <a href={file.url} target="_blank" rel="noopener noreferrer">
                        <img 
                          src={file.url} 
                          alt={file.name}
                          className="max-w-[200px] max-h-[150px] rounded border border-border/50 hover:border-primary transition-colors"
                          onError={(e) => { e.currentTarget.style.display = 'none' }}
                        />
                      </a>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {cleanOutput && (
          <div className="ml-6 mt-1.5 rounded-md px-3 py-2 text-xs border-l-2 max-h-[300px] overflow-y-auto" style={{ borderColor: color, backgroundColor: `${color}08` }}>
            <div className="text-foreground/80 whitespace-pre-wrap">{cleanOutput}</div>
          </div>
        )}
      </div>
    </div>
  )
}

export function InferenceSteps({ steps, isInferencing, plan, cancelled, agentColors }: InferenceStepsProps) {
  const { agents, orchestratorActivities, orchestratorStatus } = useMemo(() => parseEventsToAgents(steps, agentColors), [steps, agentColors])
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
          
          <div className="space-y-1 pr-1">
            {agents.map((agent: AgentInfo, i: number) => <AgentCard key={agent.mapKey} agent={agent} stepNumber={i + 1} isLive={true} />)}
          </div>
        </div>
      </div>
    )
  }

  const isCancelled = cancelled || plan?.goal_status === "cancelled"
  const hasErrors = agents.some((a: AgentInfo) => a.status === "error")

  const headerLabel = isCancelled
    ? "Workflow cancelled"
    : hasErrors
      ? "Workflow completed with errors"
      : "Workflow completed"

  const headerIconBg = isCancelled
    ? "bg-red-500/10"
    : hasErrors ? "bg-amber-500/10" : "bg-emerald-500/10"

  const HeaderIcon = isCancelled
    ? Square
    : hasErrors ? AlertCircle : CheckCircle2

  const headerIconColor = isCancelled
    ? "text-red-500"
    : hasErrors ? "text-amber-500" : "text-emerald-500"

  return (
    <Accordion type="single" collapsible className="w-full">
      <AccordionItem value="workflow" className="border border-border/50 bg-muted/30 rounded-xl px-4 shadow-sm">
        <AccordionTrigger className="hover:no-underline py-3">
          <div className="flex items-center gap-2.5">
            <div className={`h-7 w-7 rounded-lg flex items-center justify-center ${headerIconBg}`}>
              <HeaderIcon className={`h-4 w-4 ${headerIconColor}`} />
            </div>
            <span className="font-medium text-sm">{headerLabel}</span>
            {summaryLabel && <span className="text-xs text-muted-foreground ml-1">{summaryLabel}</span>}
          </div>
        </AccordionTrigger>
        <AccordionContent>
          <OrchestratorSection activities={orchestratorActivities} status={orchestratorStatus} isLive={false} />
          <div className="space-y-1 pt-1 pb-2">
            {agents.map((agent: AgentInfo, i: number) => <AgentCard key={agent.mapKey} agent={agent} stepNumber={i + 1} isLive={false} />)}
          </div>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  )
}
