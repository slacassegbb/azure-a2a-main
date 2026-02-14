"use client"

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { CheckCircle2, Loader, Workflow, Wrench, MessageSquare, Zap } from "lucide-react"
import { useEffect, useRef, useMemo } from "react"

type InferenceStepsProps = {
  steps: { agent: string; status: string; imageUrl?: string; imageName?: string; agentColor?: string }[]
  isInferencing: boolean
}

// Agent color palette matching visual-workflow-designer AGENT_COLORS
const AGENT_COLORS = [
  "#ec4899", // pink
  "#8b5cf6", // purple
  "#06b6d4", // cyan
  "#10b981", // emerald
  "#f59e0b", // amber
  "#ef4444", // red
  "#3b82f6", // blue
  "#14b8a6", // teal
  "#f97316", // orange
  "#a855f7", // violet
]

// Simple hash function to get consistent color for agent name
const getAgentColorFromName = (agentName: string): string => {
  let hash = 0
  for (let i = 0; i < agentName.length; i++) {
    hash = ((hash << 5) - hash) + agentName.charCodeAt(i)
    hash = hash & hash // Convert to 32bit integer
  }
  return AGENT_COLORS[Math.abs(hash) % AGENT_COLORS.length]
}

// Categorize a step for icon and styling
type StepCategory = "tool" | "status" | "complete" | "error" | "info"

const getStepCategory = (status: string): StepCategory => {
  const lower = status.toLowerCase()
  if (lower.includes("completed") || lower.includes("complete") || lower.includes("successfully")) return "complete"
  if (lower.includes("error") || lower.includes("failed") || lower.includes("❌")) return "error"
  if (lower.includes("executing") || lower.includes("creating") || lower.includes("searching") ||
      lower.includes("looking up") || lower.includes("listing") || lower.includes("retrieving") ||
      lower.includes("processing") || lower.includes("generating") || lower.includes("using ") ||
      lower.includes("🛠️")) return "tool"
  if (lower.includes("contacting") || lower.includes("sent to") || lower.includes("started working")) return "status"
  return "info"
}

const StepIcon = ({ category, color, isLatest }: { category: StepCategory; color: string; isLatest: boolean }) => {
  const size = "h-3.5 w-3.5"
  
  if (isLatest) {
    return (
      <div className="h-4 w-4 flex-shrink-0 mt-0.5 relative flex items-center justify-center">
        <div 
          className="h-2 w-2 rounded-full animate-pulse"
          style={{ backgroundColor: color }}
        />
        <div 
          className="h-2 w-2 rounded-full absolute animate-ping opacity-75"
          style={{ backgroundColor: color }}
        />
      </div>
    )
  }
  
  switch (category) {
    case "complete":
      return <CheckCircle2 className={`${size} flex-shrink-0 mt-0.5 text-emerald-500`} />
    case "error":
      return <Zap className={`${size} flex-shrink-0 mt-0.5 text-red-500`} />
    case "tool":
      return <Wrench className={`${size} flex-shrink-0 mt-0.5`} style={{ color }} />
    case "status":
      return <MessageSquare className={`${size} flex-shrink-0 mt-0.5`} style={{ color }} />
    default:
      return (
        <div 
          className="h-1.5 w-1.5 rounded-full flex-shrink-0 mt-1.5"
          style={{ backgroundColor: color }}
        />
      )
  }
}

// Friendly agent name display (strip prefixes like "azurefoundry_")
const getDisplayAgentName = (agentName: string): string => {
  return agentName
    .replace(/^azurefoundry_/i, "")
    .replace(/^foundry-host-agent$/i, "Orchestrator")
    .replace(/-/g, " ")
    .replace(/_/g, " ")
    .split(" ")
    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ")
}

// Simple markdown-like formatting for **bold** text
const formatStatus = (status: string) => {
  // Split by **text** pattern and render bold parts
  const parts = status.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i} className="font-semibold text-foreground">{part.slice(2, -2)}</strong>
    }
    return <span key={i}>{part}</span>
  })
}

// Check if status is a long response (agent output)
const isLongResponse = (status: string): boolean => {
  return status.length > 200 || status.includes('###') || (status.match(/\*\*/g) || []).length > 4
}

// Get unique agent count for summary
const getUniqueAgents = (steps: InferenceStepsProps["steps"]): string[] => {
  const agents = new Set(steps.map(s => s.agent))
  agents.delete("foundry-host-agent") // Don't count the orchestrator
  return Array.from(agents)
}

export function InferenceSteps({ steps, isInferencing }: InferenceStepsProps) {
  const stepsContainerRef = useRef<HTMLUListElement>(null)


  // Count unique agents for the summary label
  const uniqueAgents = useMemo(() => getUniqueAgents(steps), [steps])

  // Auto-scroll to bottom when new steps are added
  useEffect(() => {
    if (stepsContainerRef.current && isInferencing) {
      stepsContainerRef.current.scrollTop = stepsContainerRef.current.scrollHeight
    }
  }, [steps, isInferencing])

  // Render a single step item
  const renderStep = (step: InferenceStepsProps["steps"][0], index: number, isLive: boolean) => {
    const isLatestStep = isLive && index === steps.length - 1
    const stepColor = step.agentColor || getAgentColorFromName(step.agent)
    const isLong = isLongResponse(step.status)
    const category = getStepCategory(step.status)
    const agentDisplay = getDisplayAgentName(step.agent)
    
    // Show agent label when agent changes from previous step
    const prevAgent = index > 0 ? steps[index - 1].agent : null
    const showAgentLabel = step.agent !== prevAgent
    
    return (
      <li key={index} className={`flex items-start gap-2.5 text-sm ${isLong ? 'bg-background/60 rounded-lg p-3 mt-2 border border-border/30' : 'py-0.5'}`}>
        <StepIcon category={category} color={stepColor} isLatest={isLatestStep} />
        <div className="flex-1 min-w-0">
          {showAgentLabel && (
            <span 
              className="inline-block text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded mb-1 mr-1"
              style={{ 
                backgroundColor: `${stepColor}15`,
                color: stepColor 
              }}
            >
              {agentDisplay}
            </span>
          )}
          <span className={`text-muted-foreground ${isLong ? 'text-xs leading-relaxed block mt-1' : ''} ${category === 'complete' ? 'text-emerald-600 dark:text-emerald-400' : ''} ${category === 'error' ? 'text-red-600 dark:text-red-400' : ''}`}>
            {formatStatus(step.status)}
          </span>
          {step.imageUrl && (
            <div className="mt-2">
              <img 
                src={step.imageUrl} 
                alt={step.imageName || 'Generated image'}
                className={`${isLive ? 'w-20 h-20' : 'w-24 h-24'} object-cover rounded-lg border border-border shadow-sm`}
                onError={(e) => {
                  e.currentTarget.style.display = 'none'
                }}
              />
            </div>
          )}
        </div>
      </li>
    )
  }

  if (isInferencing) {
    return (
      <div className="flex items-start gap-3 w-full">
        <div className="h-8 w-8 flex items-center justify-center flex-shrink-0">
          <Loader className="h-5 w-5 animate-spin text-primary" />
        </div>
        <div className="rounded-xl p-4 bg-muted/50 border border-border/50 flex-1 shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <p className="font-semibold text-sm">Processing your request...</p>
            {uniqueAgents.length > 0 && (
              <span className="text-[10px] text-muted-foreground">
                {uniqueAgents.length} agent{uniqueAgents.length !== 1 ? 's' : ''} · {steps.length} step{steps.length !== 1 ? 's' : ''}
              </span>
            )}
          </div>
          <ul 
            ref={stepsContainerRef}
            className="space-y-1 max-h-[300px] overflow-y-auto"
          >
            {steps.map((step, index) => renderStep(step, index, true))}
          </ul>
        </div>
      </div>
    )
  }

  return (
    <Accordion type="single" collapsible className="w-full">
      <AccordionItem value="item-1" className="border border-border/50 bg-muted/30 rounded-xl px-4 shadow-sm">
        <AccordionTrigger className="hover:no-underline py-3">
          <div className="flex items-center gap-2.5">
            <div className="h-7 w-7 rounded-lg bg-primary/10 flex items-center justify-center">
              <Workflow className="h-4 w-4 text-primary" />
            </div>
            <span className="font-medium text-sm">Agent workflow</span>
            <span className="text-xs text-muted-foreground ml-1">
              {uniqueAgents.length > 0 
                ? `${uniqueAgents.length} agent${uniqueAgents.length !== 1 ? 's' : ''} · ${steps.length} steps`
                : `${steps.length} steps`
              }
            </span>
          </div>
        </AccordionTrigger>
        <AccordionContent>
          <ul className="space-y-1 pt-1 pb-2 max-h-[400px] overflow-y-auto">
            {steps.map((step, index) => renderStep(step, index, false))}
          </ul>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  )
}
