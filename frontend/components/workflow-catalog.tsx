"use client"

import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Sparkles, Download, Trash2, Save, Search } from "lucide-react"
import { useState, useEffect } from "react"

interface WorkflowTemplate {
  id: string
  name: string
  description: string
  category: string
  steps: Array<{
    id: string
    agentId: string
    agentName: string
    description: string
    order: number
    x: number
    y: number
  }>
  connections: Array<{
    id: string
    fromStepId: string
    toStepId: string
  }>
  isCustom?: boolean
}

const PREDEFINED_WORKFLOWS: WorkflowTemplate[] = [
  {
    id: "image-generation-pipeline",
    name: "Image Generation Pipeline",
    description: "Complete image creation workflow with analysis and brand refinement",
    category: "Image Creation",
    steps: [
      {
        id: "step-img-gen-1",
        agentId: "ai-foundry-image-generator-agent",
        agentName: "AI Foundry Image Generator Agent",
        description: "Generate initial image concept",
        order: 0,
        x: -300,
        y: 0
      },
      {
        id: "step-img-analysis-1",
        agentId: "ai-foundry-image-analysis-agent",
        agentName: "AI Foundry Image Analysis Agent",
        description: "Analyze generated image for quality and composition",
        order: 1,
        x: -100,
        y: 0
      },
      {
        id: "step-branding-1",
        agentId: "ai-foundry-branding-content-agent",
        agentName: "AI Foundry Branding & Content Agent",
        description: "Check brand compliance and get style guidelines",
        order: 2,
        x: 100,
        y: 0
      },
      {
        id: "step-img-gen-2",
        agentId: "ai-foundry-image-generator-agent-2",
        agentName: "AI Foundry Image Generator Agent",
        description: "Refine image based on analysis and branding feedback",
        order: 3,
        x: 300,
        y: 0
      }
    ],
    connections: [
      { id: "conn-img-1-2", fromStepId: "step-img-gen-1", toStepId: "step-img-analysis-1" },
      { id: "conn-img-2-3", fromStepId: "step-img-analysis-1", toStepId: "step-branding-1" },
      { id: "conn-img-3-4", fromStepId: "step-branding-1", toStepId: "step-img-gen-2" }
    ]
  },
  {
    id: "brand-compliant-content",
    name: "Brand-Compliant Content Creation",
    description: "Ensure all generated content meets brand guidelines",
    category: "Branding",
    steps: [
      {
        id: "step-brand-1",
        agentId: "ai-foundry-branding-content-agent",
        agentName: "AI Foundry Branding & Content Agent",
        description: "Get brand guidelines and requirements",
        order: 0,
        x: -200,
        y: 0
      },
      {
        id: "step-brand-gen-1",
        agentId: "ai-foundry-image-generator-agent",
        agentName: "AI Foundry Image Generator Agent",
        description: "Generate brand-compliant image",
        order: 1,
        x: 0,
        y: 0
      },
      {
        id: "step-brand-analysis-1",
        agentId: "ai-foundry-image-analysis-agent",
        agentName: "AI Foundry Image Analysis Agent",
        description: "Verify brand compliance and quality",
        order: 2,
        x: 200,
        y: 0
      }
    ],
    connections: [
      { id: "conn-brand-1-2", fromStepId: "step-brand-1", toStepId: "step-brand-gen-1" },
      { id: "conn-brand-2-3", fromStepId: "step-brand-gen-1", toStepId: "step-brand-analysis-1" }
    ]
  },
  {
    id: "iterative-design",
    name: "Iterative Design Refinement",
    description: "Multiple passes of generation and analysis for perfect results",
    category: "Image Creation",
    steps: [
      {
        id: "step-iter-gen-1",
        agentId: "ai-foundry-image-generator-agent",
        agentName: "AI Foundry Image Generator Agent",
        description: "Create initial design concept",
        order: 0,
        x: -200,
        y: 0
      },
      {
        id: "step-iter-analysis-1",
        agentId: "ai-foundry-image-analysis-agent",
        agentName: "AI Foundry Image Analysis Agent",
        description: "Analyze design and identify improvements",
        order: 1,
        x: 0,
        y: 0
      },
      {
        id: "step-iter-gen-2",
        agentId: "ai-foundry-image-generator-agent-2",
        agentName: "AI Foundry Image Generator Agent",
        description: "Generate improved version based on feedback",
        order: 2,
        x: 200,
        y: 0
      }
    ],
    connections: [
      { id: "conn-iter-1-2", fromStepId: "step-iter-gen-1", toStepId: "step-iter-analysis-1" },
      { id: "conn-iter-2-3", fromStepId: "step-iter-analysis-1", toStepId: "step-iter-gen-2" }
    ]
  },
  {
    id: "quality-assurance",
    name: "Quality Assurance Pipeline",
    description: "Automated quality checks and fixes for generated content",
    category: "Quality Control",
    steps: [
      {
        id: "step-qa-gen-1",
        agentId: "ai-foundry-image-generator-agent",
        agentName: "AI Foundry Image Generator Agent",
        description: "Generate content",
        order: 0,
        x: -150,
        y: 0
      },
      {
        id: "step-qa-analysis-1",
        agentId: "ai-foundry-image-analysis-agent",
        agentName: "AI Foundry Image Analysis Agent",
        description: "Perform quality analysis and identify issues",
        order: 1,
        x: 150,
        y: 0
      }
    ],
    connections: [
      { id: "conn-qa-1-2", fromStepId: "step-qa-gen-1", toStepId: "step-qa-analysis-1" }
    ]
  }
]

interface Props {
  onLoadWorkflow: (workflow: WorkflowTemplate) => void
  onSaveWorkflow: () => void
  currentWorkflowSteps: number
  refreshTrigger?: number
}

export function WorkflowCatalog({ onLoadWorkflow, onSaveWorkflow, currentWorkflowSteps, refreshTrigger }: Props) {
  const [customWorkflows, setCustomWorkflows] = useState<WorkflowTemplate[]>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('custom-workflows')
      return saved ? JSON.parse(saved) : []
    }
    return []
  })
  const [searchQuery, setSearchQuery] = useState("")
  
  // Refresh custom workflows when refreshTrigger changes
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('custom-workflows')
      setCustomWorkflows(saved ? JSON.parse(saved) : [])
    }
  }, [refreshTrigger])

  const handleDeleteCustomWorkflow = (id: string) => {
    const updated = customWorkflows.filter(w => w.id !== id)
    setCustomWorkflows(updated)
    localStorage.setItem('custom-workflows', JSON.stringify(updated))
  }

  const allWorkflows = [...PREDEFINED_WORKFLOWS, ...customWorkflows]
  
  // Filter workflows based on search query
  const filteredWorkflows = allWorkflows.filter(workflow => {
    if (!searchQuery.trim()) return true
    const query = searchQuery.toLowerCase()
    return (
      workflow.name.toLowerCase().includes(query) ||
      workflow.description.toLowerCase().includes(query) ||
      workflow.category.toLowerCase().includes(query)
    )
  })

  return (
    <div className="h-full flex flex-col bg-slate-900 rounded-lg border border-slate-800">
      <div className="p-4 border-b border-slate-800">
        <h3 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-indigo-400" />
          Workflow Templates
        </h3>
        <p className="text-xs text-slate-400 mt-1">
          Start with a predefined workflow or save your own
        </p>
      </div>

      <div className="p-4 border-b border-slate-800 space-y-3">
        <Button
          onClick={onSaveWorkflow}
          disabled={currentWorkflowSteps === 0}
          className="w-full"
          variant="outline"
          size="sm"
        >
          <Save className="h-3 w-3 mr-2" />
          Save Current Workflow
        </Button>
        
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-3 w-3 text-slate-400" />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search workflows..."
            className="pl-9 h-8 text-xs bg-slate-800 border-slate-700 text-slate-200 placeholder:text-slate-500"
          />
        </div>
      </div>

      <ScrollArea className="flex-1 p-4">
        <div className="space-y-3">
          {filteredWorkflows.length === 0 ? (
            <p className="text-xs text-slate-500 text-center py-8">
              No workflows found matching "{searchQuery}"
            </p>
          ) : (
            filteredWorkflows.map((workflow) => (
            <Card key={workflow.id} className="bg-slate-800 border-slate-700 hover:border-indigo-500 transition-colors">
              <CardHeader className="p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1">
                    <CardTitle className="text-sm text-slate-200 flex items-center gap-2">
                      {workflow.name}
                      {workflow.isCustom && (
                        <Badge variant="outline" className="text-xs">Custom</Badge>
                      )}
                    </CardTitle>
                    <CardDescription className="text-xs mt-1">
                      {workflow.description}
                    </CardDescription>
                  </div>
                  {workflow.isCustom && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDeleteCustomWorkflow(workflow.id)}
                      className="h-6 w-6 p-0 text-slate-400 hover:text-red-400"
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  )}
                </div>
              </CardHeader>
              <CardContent className="p-3 pt-0">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary" className="text-xs">
                      {workflow.category}
                    </Badge>
                    <span className="text-xs text-slate-400">
                      {workflow.steps.length} steps
                    </span>
                  </div>
                  <Button
                    onClick={() => onLoadWorkflow(workflow)}
                    variant="ghost"
                    size="sm"
                    className="h-7 text-xs"
                  >
                    <Download className="h-3 w-3 mr-1" />
                    Load
                  </Button>
                </div>
              </CardContent>
            </Card>
          )))}
        </div>
      </ScrollArea>
    </div>
  )
}

