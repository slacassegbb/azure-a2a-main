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
        <div className="rounded-lg p-3 bg-muted flex-1">
          <p className="font-semibold text-sm mb-2">Thinking...</p>
          <ul 
            ref={stepsContainerRef}
            className="space-y-2"
          >
            {steps.map((step, index) => {
              // Show pulsing dot for the latest step, static dot for previous steps
              const isLatestStep = index === steps.length - 1
              // Get agent color - use provided color, derive from name, or fallback to primary
              const stepColor = step.agentColor || getAgentColorFromName(step.agent)
              
              return (
                <li key={index} className="flex items-start gap-2 text-sm text-muted-foreground">
                  {isLatestStep ? (
                    <PulsingDot size="small" color={stepColor} />
                  ) : (
                    <div 
                      className="h-1.5 w-1.5 rounded-full flex-shrink-0 mt-1.5 opacity-60"
                      style={{ backgroundColor: stepColor }}
                    />
                  )}
                  <div className="flex-1 min-w-0">
                    <span className="text-foreground">{step.status}</span>
                    {step.imageUrl && (
                      <div className="mt-1">
                        <img 
                          src={step.imageUrl} 
                          alt={step.imageName || 'Generated image'}
                          className="w-20 h-20 object-cover rounded border border-gray-200"
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
      <AccordionItem value="item-1" className="border bg-muted/50 rounded-lg px-4">
        <AccordionTrigger>
          <div className="flex items-center gap-2">
            <Workflow className="h-5 w-5 text-primary" />
            <span className="font-semibold">Show agent workflow</span>
          </div>
        </AccordionTrigger>
        <AccordionContent>
          <ul className="space-y-2 pt-2">
            {steps.map((step, index) => {
              // All steps in collapsed view show static dots with agent color
              const stepColor = step.agentColor || getAgentColorFromName(step.agent)
              return (
                <li key={index} className="flex items-start gap-2 text-sm text-muted-foreground">
                  <div 
                    className="h-2 w-2 rounded-full flex-shrink-0 mt-1.5 opacity-60"
                    style={{ backgroundColor: stepColor }}
                  />
                  <div className="flex-1 min-w-0">
                    <span className="text-foreground">{step.status}</span>
                    {step.imageUrl && (
                      <div className="mt-1">
                        <img 
                          src={step.imageUrl} 
                          alt={step.imageName || 'Generated image'}
                          className="w-24 h-24 object-cover rounded border border-gray-200"
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
