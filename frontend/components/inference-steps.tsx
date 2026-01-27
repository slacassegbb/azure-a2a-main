"use client"

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { Loader, Workflow } from "lucide-react"
import { useEffect, useRef } from "react"

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

// Pulsing dot component with dynamic agent color
const PulsingDot = ({ size = "small", color }: { size?: "small" | "large"; color?: string }) => {
  const sizeClass = size === "small" ? "h-1.5 w-1.5" : "h-2 w-2"
  const dotColor = color || "hsl(var(--primary))"
  
  return (
    <div className={`${sizeClass} flex-shrink-0 mt-1.5 relative`}>
      <div 
        className={`${sizeClass} rounded-full animate-pulse`}
        style={{ backgroundColor: dotColor }}
      />
      <div 
        className={`${sizeClass} rounded-full absolute top-0 left-0 animate-ping opacity-75`}
        style={{ backgroundColor: dotColor }}
      />
    </div>
  )
}

export function InferenceSteps({ steps, isInferencing }: InferenceStepsProps) {
  const stepsContainerRef = useRef<HTMLUListElement>(null)

  // Auto-scroll to bottom when new steps are added
  useEffect(() => {
    if (stepsContainerRef.current && isInferencing) {
      stepsContainerRef.current.scrollTop = stepsContainerRef.current.scrollHeight
    }
  }, [steps, isInferencing])

  if (isInferencing) {
    return (
      <div className="flex items-start gap-3 w-full">
        <div className="h-8 w-8 flex items-center justify-center flex-shrink-0">
          <Loader className="h-5 w-5 animate-spin text-primary" />
        </div>
        <div className="rounded-xl p-4 bg-muted/50 border border-border/50 flex-1 shadow-sm">
          <p className="font-semibold text-sm mb-3">Processing your request...</p>
          <ul 
            ref={stepsContainerRef}
            className="space-y-1.5 max-h-[300px] overflow-y-auto"
          >
            {steps.map((step, index) => {
              const isLatestStep = index === steps.length - 1
              const stepColor = step.agentColor || getAgentColorFromName(step.agent)
              const isLong = isLongResponse(step.status)
              
              return (
                <li key={index} className={`flex items-start gap-2.5 text-sm ${isLong ? 'bg-background/50 rounded-lg p-2.5 mt-2 border border-border/30' : ''}`}>
                  {isLatestStep ? (
                    <PulsingDot size="small" color={stepColor} />
                  ) : (
                    <div 
                      className="h-1.5 w-1.5 rounded-full flex-shrink-0 mt-1.5"
                      style={{ backgroundColor: stepColor }}
                    />
                  )}
                  <div className="flex-1 min-w-0">
                    <span className={`text-muted-foreground ${isLong ? 'text-xs leading-relaxed block' : ''}`}>
                      {formatStatus(step.status)}
                    </span>
                    {step.imageUrl && (
                      <div className="mt-2">
                        <img 
                          src={step.imageUrl} 
                          alt={step.imageName || 'Generated image'}
                          className="w-20 h-20 object-cover rounded-lg border border-border shadow-sm"
                          onError={(e) => {
                            e.currentTarget.style.display = 'none'
                          }}
                        />
                      </div>
                    )}
                  </div>
                </li>
              )
            })}
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
            <span className="font-medium text-sm">Show agent workflow</span>
            <span className="text-xs text-muted-foreground ml-1">({steps.length} steps)</span>
          </div>
        </AccordionTrigger>
        <AccordionContent>
          <ul className="space-y-1.5 pt-1 pb-2 max-h-[400px] overflow-y-auto">
            {steps.map((step, index) => {
              const stepColor = step.agentColor || getAgentColorFromName(step.agent)
              const isLong = isLongResponse(step.status)
              
              return (
                <li key={index} className={`flex items-start gap-2.5 text-sm ${isLong ? 'bg-background/80 rounded-lg p-3 mt-2 border border-border/30' : 'py-0.5'}`}>
                  <div 
                    className="h-2 w-2 rounded-full flex-shrink-0 mt-1"
                    style={{ backgroundColor: stepColor }}
                  />
                  <div className="flex-1 min-w-0">
                    <span className={`text-muted-foreground ${isLong ? 'text-xs leading-relaxed block' : ''}`}>
                      {formatStatus(step.status)}
                    </span>
                    {step.imageUrl && (
                      <div className="mt-2">
                        <img 
                          src={step.imageUrl} 
                          alt={step.imageName || 'Generated image'}
                          className="w-24 h-24 object-cover rounded-lg border border-border shadow-sm"
                          onError={(e) => {
                            e.currentTarget.style.display = 'none'
                          }}
                        />
                      </div>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  )
}
