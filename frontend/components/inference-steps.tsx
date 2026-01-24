"use client"

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { Loader, Workflow } from "lucide-react"
import { useEffect, useRef } from "react"

type InferenceStepsProps = {
  steps: { agent: string; status: string; imageUrl?: string; imageName?: string }[]
  isInferencing: boolean
}

// Pulsing blue dot component - small bullet point style
const PulsingDot = ({ size = "small" }: { size?: "small" | "large" }) => {
  const sizeClass = size === "small" ? "h-1.5 w-1.5" : "h-2 w-2"
  return (
    <div className={`${sizeClass} flex-shrink-0 mt-1.5 relative`}>
      <div className={`${sizeClass} bg-primary rounded-full animate-pulse`} />
      <div className={`${sizeClass} bg-primary rounded-full absolute top-0 left-0 animate-ping opacity-75`} />
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
      <div className="flex items-start gap-3">
        <div className="h-8 w-8 flex items-center justify-center flex-shrink-0">
          <Loader className="animate-spin text-primary" />
        </div>
        <div className="rounded-lg p-3 max-w-md bg-muted w-full">
          <p className="font-semibold text-sm mb-2">Thinking...</p>
          <ul 
            ref={stepsContainerRef}
            className="space-y-2 max-h-48 overflow-y-auto scrollbar-thin scrollbar-thumb-gray-300 scrollbar-track-transparent"
          >
            {steps.map((step, index) => {
              // Show pulsing dot for the latest step, static dot for previous steps
              const isLatestStep = index === steps.length - 1
              return (
                <li key={index} className="flex items-start gap-2 text-xs text-muted-foreground">
                  {isLatestStep ? (
                    <PulsingDot size="small" />
                  ) : (
                    <div className="h-1.5 w-1.5 bg-primary rounded-full flex-shrink-0 mt-1.5 opacity-60" />
                  )}
                  <div className="flex-1 min-w-0">
                    <span className="text-foreground">
                      {step.status}
                    </span>
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
          <ul className="space-y-2 pt-2 max-h-48 overflow-y-auto scrollbar-thin scrollbar-thumb-gray-300 scrollbar-track-transparent">
            {steps.map((step, index) => {
              // All steps in collapsed view show static dots
              return (
                <li key={index} className="flex items-start gap-2 text-sm text-muted-foreground">
                  <div className="h-2 w-2 bg-primary rounded-full flex-shrink-0 mt-1.5 opacity-60" />
                  <div className="flex-1 min-w-0">
                    <span className="text-foreground">
                      {step.status}
                    </span>
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
