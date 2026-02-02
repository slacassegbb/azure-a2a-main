"use client"

import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Sparkles, Download, Trash2, Save, Search, Clock, Plus, X } from "lucide-react"
import { useState, useEffect } from "react"
import { ScheduleWorkflowDialog } from "./schedule-workflow-dialog"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"

interface WorkflowTemplate {
  id: string
  name: string
  description: string
  category: string
  goal?: string
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
  onNewWorkflow?: (name: string, description: string, category: string, goal: string) => void
  currentWorkflowSteps: number
  refreshTrigger?: number
  selectedWorkflowId?: string | null
}

export function WorkflowCatalog({ onLoadWorkflow, onSaveWorkflow, onNewWorkflow, currentWorkflowSteps, refreshTrigger, selectedWorkflowId }: Props) {
  const [customWorkflows, setCustomWorkflows] = useState<WorkflowTemplate[]>([])
  const [searchQuery, setSearchQuery] = useState("")
  const [isLoading, setIsLoading] = useState(true)
  const [isUserAuthenticated, setIsUserAuthenticated] = useState(false)
  const [showScheduleDialog, setShowScheduleDialog] = useState(false)
  const [workflowToSchedule, setWorkflowToSchedule] = useState<WorkflowTemplate | null>(null)
  const [showNewWorkflowDialog, setShowNewWorkflowDialog] = useState(false)
  const [newWorkflowName, setNewWorkflowName] = useState("")
  const [newWorkflowDescription, setNewWorkflowDescription] = useState("")
  const [newWorkflowCategory, setNewWorkflowCategory] = useState("Custom")
  const [newWorkflowGoal, setNewWorkflowGoal] = useState("Complete the workflow tasks efficiently and accurately")
  
  // Load workflows from backend (if authenticated) or localStorage on mount and when refreshTrigger changes
  useEffect(() => {
    const loadWorkflows = async () => {
      setIsLoading(true)
      
      try {
        const { getAllWorkflows, isAuthenticated } = await import('@/lib/workflow-api')
        const authenticated = isAuthenticated()
        setIsUserAuthenticated(authenticated)
        
        if (authenticated) {
          // User is authenticated - load from backend only
          const backendWorkflows = await getAllWorkflows()
          
          // Convert backend format to WorkflowTemplate format
          const converted: WorkflowTemplate[] = backendWorkflows.map(w => ({
            id: w.id,
            name: w.name,
            description: w.description,
            category: w.category,
            goal: w.goal || "",
            steps: w.steps.map(s => ({
              id: s.id,
              agentId: s.agentId,
              agentName: s.agentName,
              description: s.description,
              order: s.order,
              x: s.x ?? 0,
              y: s.y ?? 0
            })),
            connections: w.connections,
            isCustom: w.isCustom
          }))
          
          setCustomWorkflows(converted)
          console.log('[WorkflowCatalog] Loaded', converted.length, 'workflows from backend')
        } else {
          // Not authenticated - load from localStorage only
          if (typeof window !== 'undefined') {
            const saved = localStorage.getItem('custom-workflows')
            const localWorkflows = saved ? JSON.parse(saved) : []
            setCustomWorkflows(localWorkflows)
            console.log('[WorkflowCatalog] Loaded', localWorkflows.length, 'workflows from localStorage')
          }
        }
      } catch (err) {
        console.error('[WorkflowCatalog] Failed to load workflows:', err)
        // Fallback to localStorage on error
        if (typeof window !== 'undefined') {
          const saved = localStorage.getItem('custom-workflows')
          setCustomWorkflows(saved ? JSON.parse(saved) : [])
        }
      }
      
      setIsLoading(false)
    }
    
    loadWorkflows()
  }, [refreshTrigger])

  const handleDeleteCustomWorkflow = async (id: string) => {
    const { deleteWorkflow, isAuthenticated } = await import('@/lib/workflow-api')
    
    if (isAuthenticated()) {
      // Delete from backend
      const success = await deleteWorkflow(id)
      if (success) {
        console.log('[WorkflowCatalog] Deleted workflow from backend:', id)
        setCustomWorkflows(prev => prev.filter(w => w.id !== id))
      } else {
        alert("Failed to delete workflow")
      }
    } else {
      // Delete from localStorage
      const updated = customWorkflows.filter(w => w.id !== id)
      setCustomWorkflows(updated)
      localStorage.setItem('custom-workflows', JSON.stringify(updated))
      console.log('[WorkflowCatalog] Deleted workflow from localStorage:', id)
    }
  }

  // Only show custom/user workflows, not predefined ones
  const allWorkflows = customWorkflows
  
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
      <div className="p-4 border-b border-slate-800 space-y-3">
        <Button
          onClick={() => setShowNewWorkflowDialog(true)}
          className="w-full"
          size="sm"
        >
          <Plus className="h-3 w-3 mr-2" />
          New Workflow
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
            filteredWorkflows.map((workflow) => {
              const isSelected = selectedWorkflowId === workflow.id
              return (
            <Card 
              key={workflow.id} 
              className={`bg-slate-800 transition-colors cursor-pointer ${
                isSelected 
                  ? 'border-indigo-500 border-2' 
                  : 'border-slate-700 hover:border-indigo-500'
              }`}
              onClick={() => onLoadWorkflow(workflow)}
            >
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
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDeleteCustomWorkflow(workflow.id)
                      }}
                      className="h-6 w-6 p-0 text-slate-400 hover:text-primary hover:bg-primary/10"
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  )}
                </div>
              </CardHeader>
              <CardContent className="p-3 pt-0">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary" className="text-xs">
                      {workflow.category}
                    </Badge>
                    <span className="text-xs text-slate-400">
                      {workflow.steps.length} steps
                    </span>
                  </div>
                  
                  {/* Show action buttons when this workflow is selected */}
                  {isSelected && (
                    <div className="flex gap-2">
                      <Button
                        onClick={(e) => {
                          e.stopPropagation()
                          onSaveWorkflow()
                        }}
                        disabled={currentWorkflowSteps === 0}
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0"
                        title="Save workflow"
                      >
                        <Save className="h-3 w-3" />
                      </Button>
                      <Button
                        onClick={(e) => {
                          e.stopPropagation()
                          setWorkflowToSchedule(workflow)
                          setShowScheduleDialog(true)
                        }}
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0"
                        title="Schedule workflow"
                      >
                        <Clock className="h-3 w-3" />
                      </Button>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          )
          }))}
        </div>
      </ScrollArea>
      
      {/* Schedule Workflow Dialog */}
      <ScheduleWorkflowDialog
        open={showScheduleDialog}
        onOpenChange={(open) => {
          setShowScheduleDialog(open)
          if (!open) {
            setWorkflowToSchedule(null)
          }
        }}
        workflowId={workflowToSchedule?.id}
        workflowName={workflowToSchedule?.name}
      />
      
      {/* New Workflow Dialog */}
      <Dialog open={showNewWorkflowDialog} onOpenChange={(open) => {
        if (!open) {
          // Dialog is closing - reset form without creating workflow
          setNewWorkflowName("")
          setNewWorkflowDescription("")
          setNewWorkflowCategory("Custom")
          setNewWorkflowGoal("Complete the workflow tasks efficiently and accurately")
        }
        setShowNewWorkflowDialog(open)
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create New Workflow</DialogTitle>
            <DialogDescription>
              Enter the details for your new workflow. You'll start with a blank canvas.
            </DialogDescription>
          </DialogHeader>
          
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="workflow-name">Workflow Name *</Label>
              <Input
                id="workflow-name"
                value={newWorkflowName}
                onChange={(e) => setNewWorkflowName(e.target.value)}
                placeholder="e.g., Customer Onboarding Flow"
              />
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="workflow-description">Description</Label>
              <Input
                id="workflow-description"
                value={newWorkflowDescription}
                onChange={(e) => setNewWorkflowDescription(e.target.value)}
                placeholder="Brief description of what this workflow does"
              />
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="workflow-category">Category</Label>
              <Input
                id="workflow-category"
                value={newWorkflowCategory}
                onChange={(e) => setNewWorkflowCategory(e.target.value)}
                placeholder="e.g., Customer Service, Sales, Marketing"
              />
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="workflow-goal">Goal (optional)</Label>
              <Input
                id="workflow-goal"
                value={newWorkflowGoal}
                onChange={(e) => setNewWorkflowGoal(e.target.value)}
                placeholder="Complete the workflow tasks efficiently and accurately"
              />
              <p className="text-xs text-slate-400">
                The goal helps guide the AI agents in executing this workflow
              </p>
            </div>
          </div>
          
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setShowNewWorkflowDialog(false)
                setNewWorkflowName("")
                setNewWorkflowDescription("")
                setNewWorkflowCategory("Custom")
                setNewWorkflowGoal("Complete the workflow tasks efficiently and accurately")
              }}
            >
              Cancel
            </Button>
            <Button
              onClick={() => {
                if (!newWorkflowName.trim()) {
                  alert("Please enter a workflow name")
                  return
                }
                
                if (onNewWorkflow) {
                  onNewWorkflow(newWorkflowName, newWorkflowDescription, newWorkflowCategory, newWorkflowGoal)
                }
                
                setShowNewWorkflowDialog(false)
                setNewWorkflowName("")
                setNewWorkflowDescription("")
                setNewWorkflowCategory("Custom")
                setNewWorkflowGoal("Complete the workflow tasks efficiently and accurately")
              }}
              disabled={!newWorkflowName.trim()}
            >
              Create Workflow
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

