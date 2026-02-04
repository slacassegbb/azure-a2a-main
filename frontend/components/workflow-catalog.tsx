"use client"

import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Sparkles, Download, Trash2, Save, Search, Clock, Plus, X, Pencil, Play, Pause, ChevronDown, ChevronRight, CheckCircle, XCircle } from "lucide-react"
import { useState, useEffect } from "react"
import { ScheduleWorkflowDialog } from "./schedule-workflow-dialog"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"

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
  onActivateWorkflow?: (workflow: WorkflowTemplate) => void
  onDeactivateWorkflow?: (workflowId: string) => void
  currentWorkflowSteps: number
  refreshTrigger?: number
  selectedWorkflowId?: string | null
  activatedWorkflowIds?: string[]
}

export function WorkflowCatalog({ onLoadWorkflow, onSaveWorkflow, onNewWorkflow, onActivateWorkflow, onDeactivateWorkflow, currentWorkflowSteps, refreshTrigger, selectedWorkflowId, activatedWorkflowIds = [] }: Props) {
  console.log('[WorkflowCatalog] Component mounted/rendered')
  
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
  
  // Scheduled workflows state
  const [scheduledWorkflows, setScheduledWorkflows] = useState<any[]>([])
  const [isLoadingScheduled, setIsLoadingScheduled] = useState(true)
  const [runHistory, setRunHistory] = useState<any[]>([])
  const [expandedScheduleId, setExpandedScheduleId] = useState<string | null>(null)
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)
  
  // Edit mode state
  const [editingWorkflowId, setEditingWorkflowId] = useState<string | null>(null)
  const [editName, setEditName] = useState("")
  const [editDescription, setEditDescription] = useState("")
  const [editGoal, setEditGoal] = useState("")
  const [editCategory, setEditCategory] = useState("")
  
  // Function to delete a scheduled workflow
  const handleDeleteScheduledWorkflow = async (scheduleId: string, workflowName: string) => {
    if (!confirm(`Are you sure you want to delete the schedule for "${workflowName}"?`)) {
      return
    }
    
    try {
      const API_BASE_URL = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
      const response = await fetch(`${API_BASE_URL}/api/schedules/${scheduleId}`, {
        method: 'DELETE'
      })
      
      if (response.ok) {
        console.log('[WorkflowCatalog] Deleted scheduled workflow:', scheduleId)
        // Remove from local state
        setScheduledWorkflows(prev => prev.filter(s => s.id !== scheduleId))
      } else {
        alert('Failed to delete scheduled workflow')
      }
    } catch (err) {
      console.error('[WorkflowCatalog] Failed to delete scheduled workflow:', err)
      alert('Failed to delete scheduled workflow')
    }
  }
  
  // Function to toggle (pause/resume) a scheduled workflow
  const handleToggleScheduledWorkflow = async (scheduleId: string, currentlyEnabled: boolean) => {
    try {
      const API_BASE_URL = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
      const response = await fetch(`${API_BASE_URL}/api/schedules/${scheduleId}/toggle?enabled=${!currentlyEnabled}`, {
        method: 'POST'
      })
      
      if (response.ok) {
        const data = await response.json()
        console.log('[WorkflowCatalog] Toggled scheduled workflow:', scheduleId, 'enabled:', !currentlyEnabled)
        // Update local state
        setScheduledWorkflows(prev => prev.map(s => 
          s.id === scheduleId ? { ...s, enabled: !currentlyEnabled } : s
        ))
      } else {
        alert('Failed to toggle scheduled workflow')
      }
    } catch (err) {
      console.error('[WorkflowCatalog] Failed to toggle scheduled workflow:', err)
      alert('Failed to toggle scheduled workflow')
    }
  }
  
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

  // Load scheduled workflows and run history
  useEffect(() => {
    const loadScheduledWorkflows = async () => {
      setIsLoadingScheduled(true)
      try {
        const { isAuthenticated } = await import('@/lib/workflow-api')
        if (!isAuthenticated()) {
          console.log('[WorkflowCatalog] User not authenticated, skipping scheduled workflows fetch')
          setIsLoadingScheduled(false)
          return
        }
        
        console.log('[WorkflowCatalog] User authenticated, fetching scheduled workflows...')

        const API_BASE_URL = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
        
        // Fetch both schedules and run history
        const [schedulesResponse, historyResponse] = await Promise.all([
          fetch(`${API_BASE_URL}/api/schedules`),
          fetch(`${API_BASE_URL}/api/schedules/history?limit=100`)
        ])
        
        if (schedulesResponse.ok) {
          const data = await schedulesResponse.json()
          setScheduledWorkflows(data.schedules || [])
          console.log('[WorkflowCatalog] Loaded', data.schedules?.length || 0, 'scheduled workflows:', data.schedules)
        } else {
          console.error('[WorkflowCatalog] Failed to fetch scheduled workflows:', schedulesResponse.status)
        }
        
        if (historyResponse.ok) {
          const historyData = await historyResponse.json()
          setRunHistory(historyData.history || [])
          console.log('[WorkflowCatalog] Loaded', historyData.history?.length || 0, 'run history items')
        }
      } catch (err) {
        console.error('[WorkflowCatalog] Failed to load scheduled workflows:', err)
      }
      setIsLoadingScheduled(false)
    }
    
    loadScheduledWorkflows()
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

  const handleStartEdit = (workflow: WorkflowTemplate) => {
    setEditingWorkflowId(workflow.id)
    setEditName(workflow.name)
    setEditDescription(workflow.description)
    setEditGoal(workflow.goal || "")
    setEditCategory(workflow.category)
  }

  const handleSaveEdit = async (workflowId: string) => {
    const { updateWorkflow, isAuthenticated } = await import('@/lib/workflow-api')
    
    const workflow = customWorkflows.find(w => w.id === workflowId)
    if (!workflow) return
    
    const updatedWorkflow = {
      ...workflow,
      name: editName,
      description: editDescription,
      goal: editGoal,
      category: editCategory
    }
    
    if (isAuthenticated()) {
      // Update in backend
      const saved = await updateWorkflow(workflowId, {
        name: editName,
        description: editDescription,
        goal: editGoal,
        category: editCategory
      })
      if (saved) {
        console.log('[WorkflowCatalog] Updated workflow in backend:', workflowId)
        setCustomWorkflows(prev => prev.map(w => w.id === workflowId ? updatedWorkflow : w))
      } else {
        alert("Failed to update workflow")
        return
      }
    } else {
      // Update in localStorage
      const updated = customWorkflows.map(w => w.id === workflowId ? updatedWorkflow : w)
      setCustomWorkflows(updated)
      localStorage.setItem('custom-workflows', JSON.stringify(updated))
      console.log('[WorkflowCatalog] Updated workflow in localStorage:', workflowId)
    }
    
    setEditingWorkflowId(null)
  }

  const handleCancelEdit = () => {
    setEditingWorkflowId(null)
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
          {/* Regular Workflows */}
          {filteredWorkflows.length === 0 ? (
            <p className="text-xs text-slate-500 text-center py-8">
              No workflows found matching "{searchQuery}"
            </p>
          ) : (
            filteredWorkflows.map((workflow) => {
              const isSelected = selectedWorkflowId === workflow.id
              const isEditing = editingWorkflowId === workflow.id
              const isActivated = activatedWorkflowIds.includes(workflow.id)
              
              return (
            <Card 
              key={workflow.id} 
              className={`transition-colors ${
                isActivated
                  ? 'bg-green-900/20 border-green-500/50 border-2'
                  : isEditing 
                    ? 'bg-slate-800 border-indigo-500 border-2' 
                    : isSelected 
                      ? 'bg-slate-800 border-indigo-500 border-2 cursor-pointer' 
                      : 'bg-slate-800 border-slate-700 hover:border-indigo-500 cursor-pointer'
              }`}
              onClick={() => !isEditing && onLoadWorkflow(workflow)}
            >
              <CardHeader className="p-3 relative">
                {/* Buttons - positioned absolutely in top-right */}
                <div className="absolute top-3 right-3 flex gap-1 z-10">
                  {workflow.isCustom && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation()
                        if (isEditing) {
                          handleSaveEdit(workflow.id)
                        } else {
                          handleStartEdit(workflow)
                        }
                      }}
                      className={`h-6 w-6 p-0 ${isEditing ? 'text-indigo-400 hover:text-indigo-300 hover:bg-indigo-400/10' : 'text-slate-400 hover:text-indigo-400 hover:bg-indigo-400/10'}`}
                      title={isEditing ? "Save changes" : "Edit workflow"}
                    >
                      {isEditing ? <Save className="h-3 w-3" /> : <Pencil className="h-3 w-3" />}
                    </Button>
                  )}
                  {!isEditing && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation()
                        setWorkflowToSchedule(workflow)
                        setShowScheduleDialog(true)
                      }}
                      className="h-6 w-6 p-0 text-slate-400 hover:text-blue-400 hover:bg-blue-400/10"
                      title="Schedule workflow"
                    >
                      <Clock className="h-3 w-3" />
                    </Button>
                  )}
                  {!isEditing && (isActivated ? onDeactivateWorkflow : onActivateWorkflow) && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation()
                        if (isActivated && onDeactivateWorkflow) {
                          onDeactivateWorkflow(workflow.id)
                        } else if (onActivateWorkflow) {
                          onActivateWorkflow(workflow)
                        }
                      }}
                      className={`h-6 w-6 p-0 ${
                        isActivated 
                          ? 'text-red-400 hover:text-red-300 hover:bg-red-400/10' 
                          : 'text-slate-400 hover:text-green-400 hover:bg-green-400/10'
                      }`}
                      title={isActivated ? "Deactivate workflow" : "Activate workflow"}
                    >
                      {isActivated ? <X className="h-3 w-3" /> : <Play className="h-3 w-3" />}
                    </Button>
                  )}
                  {workflow.isCustom && !isEditing && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDeleteCustomWorkflow(workflow.id)
                      }}
                      className="h-6 w-6 p-0 text-slate-400 hover:text-red-400 hover:bg-red-400/10"
                      title="Delete workflow"
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  )}
                </div>

                {/* Content */}
                <div>
                  {/* Title with padding for buttons */}
                  <div className="flex items-center gap-2 pr-16">
                    <CardTitle className="text-sm text-slate-200 break-words">
                      <span className="break-words">
                        {isEditing ? (
                          <span
                            contentEditable
                            suppressContentEditableWarning
                            onBlur={(e) => setEditName(e.currentTarget.textContent || '')}
                            onInput={(e) => setEditName(e.currentTarget.textContent || '')}
                            onClick={(e) => e.stopPropagation()}
                            className="outline-none border-b border-dashed border-indigo-400"
                          >
                            {editName}
                          </span>
                        ) : (
                          workflow.name
                        )}
                      </span>
                    </CardTitle>
                    <Badge variant="secondary" className="text-xs flex-shrink-0">
                      {workflow.category}
                    </Badge>
                  </div>
                  
                  {/* Goal field - full width */}
                  {(workflow.goal || isEditing) && (
                    <div className="mt-2">
                      <span className="text-[10px] text-slate-500 uppercase tracking-wide">Goal</span>
                      <p 
                        className={`text-xs text-slate-400 mt-0.5 break-words ${isEditing ? 'outline-none border-b border-dashed border-indigo-400' : ''}`}
                        contentEditable={isEditing}
                        suppressContentEditableWarning
                        onBlur={(e) => isEditing && setEditGoal(e.currentTarget.textContent || '')}
                        onInput={(e) => isEditing && setEditGoal(e.currentTarget.textContent || '')}
                        onClick={(e) => isEditing && e.stopPropagation()}
                        data-placeholder="What should this accomplish..."
                      >
                        {isEditing ? editGoal : workflow.goal}
                      </p>
                    </div>
                  )}
                  
                  {/* Description - full width */}
                  <div className="mt-2">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wide">Description</span>
                    <CardDescription 
                      className={`text-xs mt-0.5 break-words ${isEditing ? 'outline-none border-b border-dashed border-indigo-400' : ''}`}
                      contentEditable={isEditing}
                      suppressContentEditableWarning
                      onBlur={(e) => isEditing && setEditDescription(e.currentTarget.textContent || '')}
                      onInput={(e) => isEditing && setEditDescription(e.currentTarget.textContent || '')}
                      onClick={(e) => isEditing && e.stopPropagation()}
                    >
                      {isEditing ? editDescription : workflow.description}
                    </CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="p-3 pt-0">
                <div className="flex items-center justify-end gap-2">
                  <span className="text-xs text-slate-400">
                    {workflow.steps.length} steps
                  </span>
                </div>
              </CardContent>
            </Card>
          )
          }))}
        </div>
        
        {/* Scheduled Workflows Section */}
        {isUserAuthenticated && scheduledWorkflows.length > 0 && (
          <div className="mt-6 space-y-3">
            <div className="flex items-center gap-2 px-1">
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Scheduled Workflows
              </h3>
              <span className="text-xs text-slate-500">({scheduledWorkflows.length})</span>
            </div>
            
            <div className="space-y-3">
              {scheduledWorkflows.map((schedule) => {
                const nextRun = schedule.next_run ? new Date(schedule.next_run) : null
                const isEnabled = schedule.enabled
                
                const scheduleRuns = runHistory.filter(run => run.schedule_id === schedule.id)
                const isExpanded = expandedScheduleId === schedule.id
                
                return (
                  <Card 
                    key={schedule.id}
                    className="bg-slate-800 border-slate-700 hover:border-purple-500 transition-colors cursor-pointer"
                    onClick={() => setExpandedScheduleId(isExpanded ? null : schedule.id)}
                  >
                    <CardHeader className="p-3 relative">
                      {/* Action buttons - positioned absolutely in top-right */}
                      <div className="absolute top-3 right-3 z-10 flex gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation()
                            handleToggleScheduledWorkflow(schedule.id, isEnabled)
                          }}
                          className={`h-6 w-6 p-0 ${
                            isEnabled 
                              ? 'text-yellow-400 hover:text-yellow-300 hover:bg-yellow-400/10' 
                              : 'text-green-400 hover:text-green-300 hover:bg-green-400/10'
                          }`}
                          title={isEnabled ? "Pause schedule" : "Resume schedule"}
                        >
                          {isEnabled ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation()
                            handleDeleteScheduledWorkflow(schedule.id, schedule.workflow_name)
                          }}
                          className="h-6 w-6 p-0 text-slate-400 hover:text-red-400 hover:bg-red-400/10"
                          title="Delete schedule"
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                        {isExpanded ? (
                          <ChevronDown className="h-4 w-4 text-purple-400" />
                        ) : (
                          <ChevronRight className="h-4 w-4 text-purple-400" />
                        )}
                      </div>
                      
                      <div className="flex items-start justify-between gap-2 pr-20">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <CardTitle className="text-sm font-medium text-slate-200 truncate">
                              {schedule.workflow_name}
                            </CardTitle>
                            <Badge 
                              variant="secondary" 
                              className={`text-[10px] px-1.5 py-0 ${
                                isEnabled 
                                  ? 'bg-purple-500/20 text-purple-300 border-purple-500/30' 
                                  : 'bg-slate-700/50 text-slate-400 border-slate-600'
                              }`}
                            >
                              {schedule.schedule_type}
                            </Badge>
                            <Badge 
                              variant="secondary"
                              className={`text-[10px] px-1.5 py-0 ${
                                isEnabled 
                                  ? 'bg-green-500/20 text-green-300 border-green-500/30' 
                                  : 'bg-slate-700/50 text-slate-400 border-slate-600'
                              }`}
                            >
                              {isEnabled ? 'enabled' : 'paused'}
                            </Badge>
                          </div>
                          
                          {schedule.description && (
                            <CardDescription className="text-xs text-slate-400 line-clamp-2">
                              {schedule.description}
                            </CardDescription>
                          )}
                          
                          {/* Schedule Info */}
                          <div className="mt-2 space-y-1">
                            {nextRun && (
                              <div className="flex items-center gap-1.5 text-xs text-slate-400">
                                <Clock className="h-3 w-3" />
                                <span>Next run: {nextRun.toLocaleString()}</span>
                              </div>
                            )}
                            
                            {schedule.run_count > 0 && (
                              <div className="flex items-center gap-2 text-xs">
                                <span className="text-slate-400">
                                  Runs: {schedule.run_count}
                                </span>
                                {schedule.success_count > 0 && (
                                  <span className="text-green-400">
                                    ✓ {schedule.success_count}
                                  </span>
                                )}
                                {schedule.failure_count > 0 && (
                                  <span className="text-red-400">
                                    ✗ {schedule.failure_count}
                                  </span>
                                )}
                              </div>
                            )}
                            
                            {schedule.last_status && (
                              <div className="flex items-center gap-1.5 text-xs">
                                <span className="text-slate-400">Last run:</span>
                                <Badge 
                                  variant="secondary"
                                  className={`text-[10px] px-1.5 py-0 ${
                                    schedule.last_status === 'success'
                                      ? 'bg-green-500/20 text-green-300 border-green-500/30'
                                      : schedule.last_status === 'failed'
                                        ? 'bg-red-500/20 text-red-300 border-red-500/30'
                                        : 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30'
                                  }`}
                                >
                                  {schedule.last_status}
                                </Badge>
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                      
                      {/* Expanded Run History */}
                      {isExpanded && (
                        <div className="mt-3 pt-3 border-t border-slate-700" onClick={(e) => e.stopPropagation()}>
                          <div className="bg-slate-900/50 rounded-md p-2 max-h-64 overflow-y-auto">
                            <p className="text-[10px] text-slate-400 uppercase tracking-wider mb-2">
                              Run History ({schedule.run_count} runs)
                            </p>
                            {scheduleRuns.length === 0 ? (
                              <p className="text-xs text-slate-500 text-center py-2">No runs recorded yet</p>
                            ) : (
                              <div className="space-y-1">
                                {scheduleRuns.slice(0, 5).map((run) => {
                                  const isRunExpanded = expandedRunId === run.run_id
                                  return (
                                    <div key={run.run_id} className="border-b border-slate-800 last:border-0">
                                      <button
                                        onClick={(e) => {
                                          e.stopPropagation()
                                          setExpandedRunId(isRunExpanded ? null : run.run_id)
                                        }}
                                        className="w-full flex items-center justify-between gap-2 py-1.5 hover:bg-slate-800/50 rounded px-1 transition-colors"
                                      >
                                        <div className="flex items-center gap-1.5 min-w-0 flex-1">
                                          {run.status === 'success' ? (
                                            <CheckCircle className="h-3 w-3 text-green-500 flex-shrink-0" />
                                          ) : (
                                            <XCircle className="h-3 w-3 text-red-500 flex-shrink-0" />
                                          )}
                                          <span className="text-[10px] text-slate-300 truncate">
                                            {new Date(run.started_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} at {new Date(run.started_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
                                          </span>
                                        </div>
                                        <div className="flex items-center gap-1.5 flex-shrink-0">
                                          <span className="text-[9px] text-slate-500">
                                            {Math.round(run.duration_seconds)}s
                                          </span>
                                          {isRunExpanded ? (
                                            <ChevronDown className="h-3 w-3 text-slate-500" />
                                          ) : (
                                            <ChevronRight className="h-3 w-3 text-slate-500" />
                                          )}
                                        </div>
                                      </button>
                                      
                                      {/* Expanded run details */}
                                      {isRunExpanded && (
                                        <div className="px-2 pb-2 pt-1 space-y-2 bg-slate-800/30 rounded-b">
                                          <div className="grid grid-cols-2 gap-x-2 gap-y-1">
                                            <div>
                                              <p className="text-[9px] text-slate-500">Started</p>
                                              <p className="text-[9px] text-slate-400 font-mono">{new Date(run.started_at).toLocaleTimeString()}</p>
                                            </div>
                                            <div>
                                              <p className="text-[9px] text-slate-500">Duration</p>
                                              <p className="text-[9px] text-slate-400 font-mono">{run.duration_seconds.toFixed(1)}s</p>
                                            </div>
                                          </div>
                                          
                                          {run.error && (
                                            <div>
                                              <p className="text-[9px] text-red-400 mb-0.5">Error</p>
                                              <div className="bg-red-500/10 border border-red-500/20 rounded p-1.5 max-h-20 overflow-y-auto">
                                                <p className="text-[9px] text-red-300 font-mono whitespace-pre-wrap break-words">{run.error}</p>
                                              </div>
                                            </div>
                                          )}
                                          
                                          {run.result && (
                                            <div>
                                              <p className="text-[9px] text-slate-500 mb-0.5">Result</p>
                                              <div className="bg-slate-900/50 rounded p-1.5 max-h-24 overflow-y-auto">
                                                <p className="text-[9px] text-slate-400 font-mono whitespace-pre-wrap break-words">{run.result}</p>
                                              </div>
                                            </div>
                                          )}
                                        </div>
                                      )}
                                    </div>
                                  )
                                })}
                                {scheduleRuns.length > 5 && (
                                  <p className="text-[9px] text-slate-500 italic text-center pt-1">
                                    +{scheduleRuns.length - 5} more runs
                                  </p>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </CardHeader>
                  </Card>
                )
              })}
            </div>
          </div>
        )}
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

