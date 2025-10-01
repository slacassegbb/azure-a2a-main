"use client"

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { CheckCircle2, Loader, Workflow } from "lucide-react"
import { useEffect, useRef } from "react"

type InferenceStepsProps = {
  steps: { agent: string; status: string }[]
  isInferencing: boolean
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
            {steps.map((step, index) => (
              <li key={index} className="flex items-center gap-2 text-xs text-muted-foreground">
                <CheckCircle2 className="h-3 w-3 text-green-500 flex-shrink-0" />
                <span>
                  <span className="font-semibold text-foreground">{step.agent}:</span> {step.status}
                </span>
              </li>
            ))}
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
            {steps.map((step, index) => (
              <li key={index} className="flex items-center gap-2 text-sm text-muted-foreground">
                <CheckCircle2 className="h-4 w-4 text-green-500 flex-shrink-0" />
                <span>
                  <span className="font-semibold text-foreground">{step.agent}:</span> {step.status}
                </span>
              </li>
            ))}
          </ul>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  )
}
