"use client"

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import { PanelRightClose, PanelRightOpen, ShieldCheck, ChevronDown, ChevronRight, Globe, Hash, Zap, FileText, ExternalLink, Settings, Clock, CheckCircle, XCircle, AlertCircle, Pause, Brain, Search, MessageSquare, Database, Shield, BarChart3, Gavel, Users, Bot, Trash2, User, ListOrdered } from "lucide-react"
import { SimulateAgentRegistration } from "./simulate-agent-registration"
import { ConnectedUsers } from "./connected-users"
import { cn } from "@/lib/utils"
import { useState, useEffect, useCallback } from "react"
import { useEventHub } from "@/contexts/event-hub-context"

type Agent = {
  name: string
  description?: string
  url?: string
  version?: string
  iconUrl?: string | null
  provider?: any
  documentationUrl?: string | null
  capabilities?: {
    streaming?: boolean
    pushNotifications?: boolean
    stateTransitionHistory?: boolean
    extensions?: any[]
  }
  skills?: Array<{
    id: string
    name: string
    description: string
    tags?: string[]
    examples?: string[]
    inputModes?: string[]
    outputModes?: string[]
  }>
  defaultInputModes?: string[]
  defaultOutputModes?: string[]
  status: string
  avatar: string
  type?: string
}

// Agent status tracking types
type TaskState = 
  | "submitted" 
  | "working" 
  | "input-required"
  | "completed" 
  | "canceled" 
  | "failed" 
  | "rejected"
  | "auth-required"
  | "unknown"

type AgentStatus = {
  agentName: string
  currentTask?: {
    taskId: string
    state: TaskState
    contextId: string
    lastUpdate: string
  }
  connectionStatus: "online" | "offline" | "connecting"
  lastSeen: string
}

type Props = {
  registeredAgents: Agent[]
  isCollapsed: boolean
  onToggle: () => void
  agentMode: boolean
  onAgentModeChange: (enabled: boolean) => void
  enableInterAgentMemory: boolean
  onInterAgentMemoryChange: (enabled: boolean) => void
  workflow?: string
  onWorkflowChange?: (workflow: string) => void
}

// Store persistent color assignments for agents
const agentColorMap = new Map<string, any>()

// Function to get consistent colors for each agent
function getAgentDisplayInfo(agentName: string) {
  // Check if we already have a color assigned for this agent
  if (agentColorMap.has(agentName)) {
    return agentColorMap.get(agentName)
  }
  
  const colors = [
    { color: "text-blue-700", bgColor: "bg-blue-100" },
    { color: "text-purple-700", bgColor: "bg-purple-100" },
    { color: "text-green-700", bgColor: "bg-green-100" },
    { color: "text-orange-700", bgColor: "bg-orange-100" },
    { color: "text-red-700", bgColor: "bg-red-100" },
    { color: "text-indigo-700", bgColor: "bg-indigo-100" },
    { color: "text-pink-700", bgColor: "bg-pink-100" },
    { color: "text-teal-700", bgColor: "bg-teal-100" },
    { color: "text-cyan-700", bgColor: "bg-cyan-100" },
    { color: "text-amber-700", bgColor: "bg-amber-100" },
    { color: "text-lime-700", bgColor: "bg-lime-100" },
    { color: "text-violet-700", bgColor: "bg-violet-100" },
    { color: "text-rose-700", bgColor: "bg-rose-100" },
    { color: "text-emerald-700", bgColor: "bg-emerald-100" },
    { color: "text-sky-700", bgColor: "bg-sky-100" },
  ]
  
  // Pick a random color and store it persistently
  const randomIndex = Math.floor(Math.random() * colors.length)
  const agentDisplayInfo = {
    ...colors[randomIndex],
    icon: Bot // Same icon for all agents
  }
  
  // Store the assignment for future use
  agentColorMap.set(agentName, agentDisplayInfo)
  
  return agentDisplayInfo
}

// Function to check if an agent has human interaction capabilities
function hasHumanInteractionSkill(agent: Agent): boolean {
  return agent.skills?.some(skill => skill.id === 'human_interaction') ?? false
}

export function AgentNetwork({ registeredAgents, isCollapsed, onToggle, agentMode, onAgentModeChange, enableInterAgentMemory, onInterAgentMemoryChange, workflow: propWorkflow, onWorkflowChange }: Props) {
  const [expandedAgents, setExpandedAgents] = useState<Set<string>>(new Set())
  const [isSystemPromptDialogOpen, setIsSystemPromptDialogOpen] = useState(false)
  const [currentInstruction, setCurrentInstruction] = useState("")
  const [editedInstruction, setEditedInstruction] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [isClearingMemory, setIsClearingMemory] = useState(false)
  
  // Workflow state - use prop if provided, otherwise local state
  const [isWorkflowDialogOpen, setIsWorkflowDialogOpen] = useState(false)
  const [localWorkflow, setLocalWorkflow] = useState("")
  const [editedWorkflow, setEditedWorkflow] = useState("")
  
  const workflow = propWorkflow !== undefined ? propWorkflow : localWorkflow
  const setWorkflow = onWorkflowChange || setLocalWorkflow
  
  // Agent status tracking state
  const [agentStatuses, setAgentStatuses] = useState<Map<string, AgentStatus>>(new Map())
  
  // Store status clear timeouts to prevent race conditions
  const statusClearTimeoutsRef = useState<Map<string, NodeJS.Timeout>>(new Map())[0]
  
  // Use existing EventHub context instead of creating new WebSocket client
  const { subscribe, unsubscribe, isConnected } = useEventHub()

  // Handle task status updates from WebSocket
  const handleTaskUpdate = useCallback((eventData: any) => {
    // Use the exact structure we tested earlier
    const { taskId, state, contextId, agentName } = eventData
    
    // For multiple agents, we need agentName to be specified
    let targetAgent = agentName
    
    // If no specific agent is provided, don't update any agent
    if (!targetAgent) {
      return
    }
    
    // Verify the agent exists in our registered agents
    const agentExists = registeredAgents.some(agent => agent.name === targetAgent)
    if (!agentExists) {
      return
    }
    
    if (targetAgent && taskId && state) {
      // Map different states appropriately
      let mappedState: TaskState = state as TaskState
      if (state === "created") {
        mappedState = "working" // Show as working when task is created
      }
      
      setAgentStatuses(prev => {
        const newStatuses = new Map(prev)
        const currentStatus = newStatuses.get(targetAgent) || {
          agentName: targetAgent,
          connectionStatus: "online" as const,
          lastSeen: new Date().toISOString()
        }
        
        const updatedStatus = {
          ...currentStatus,
          currentTask: {
            taskId,
            state: mappedState,
            contextId: contextId || '',
            lastUpdate: new Date().toISOString()
          },
          lastSeen: new Date().toISOString()
        }
        
        newStatuses.set(targetAgent, updatedStatus)
        
        console.log('[AgentNetwork] Updated status for', targetAgent, ':', updatedStatus)
        
        // Clear any existing timeout for this agent to prevent race conditions
        const existingTimeout = statusClearTimeoutsRef.get(targetAgent)
        if (existingTimeout) {
          clearTimeout(existingTimeout)
          statusClearTimeoutsRef.delete(targetAgent)
        }
        
        // Clear the task after showing completion or failure
        if (mappedState === "completed" || mappedState === "failed") {
          const timeoutId = setTimeout(() => {
            setAgentStatuses(prev => {
              const newStatuses = new Map(prev)
              const currentStatus = newStatuses.get(targetAgent)
              if (currentStatus && currentStatus.currentTask && 
                  (currentStatus.currentTask.state === "completed" || currentStatus.currentTask.state === "failed")) {
                newStatuses.set(targetAgent, {
                  ...currentStatus,
                  currentTask: undefined, // Clear the task
                  lastSeen: new Date().toISOString()
                })
                console.log('[AgentNetwork] Cleared completed/failed task for', targetAgent)
              }
              return newStatuses
            })
            statusClearTimeoutsRef.delete(targetAgent)
          }, 5000) // Show "Completed/Failed" for 5 seconds then return to "Online"
          
          statusClearTimeoutsRef.set(targetAgent, timeoutId)
        }
        
        return newStatuses
      })
    } else {
      console.warn('[AgentNetwork] Missing required data for task update:', { targetAgent, taskId, state })
    }
  }, [registeredAgents])

  // Handle agent status updates from WebSocket
  const handleAgentStatusUpdate = useCallback((eventData: any) => {
    console.log('[AgentNetwork] Agent status update received:', eventData)
    
    const { agentName, status } = eventData
    
    if (agentName) {
      setAgentStatuses(prev => {
        const newStatuses = new Map(prev)
        const currentStatus = newStatuses.get(agentName) || {
          agentName,
          connectionStatus: "online" as const,
          lastSeen: new Date().toISOString()
        }
        
        newStatuses.set(agentName, {
          ...currentStatus,
          connectionStatus: status === "online" ? "online" : "offline",
          lastSeen: new Date().toISOString()
        })
        
        return newStatuses
      })
    }
  }, [])

  // Handle status_update events (from ChatPanel)
  const handleStatusUpdate = useCallback((eventData: any) => {
    console.log('[AgentNetwork] Status update received:', eventData)
    
    const { agent, status, inferenceId } = eventData
    
    if (agent && status) {
      // Verify the agent exists in our registered agents
      const agentExists = registeredAgents.some(regAgent => regAgent.name === agent)
      if (!agentExists) {
        console.warn('[AgentNetwork] Agent from status_update not found in registered agents:', agent)
        console.log('[AgentNetwork] Available agents:', registeredAgents.map(a => a.name))
        return
      }
      
      // Map status to TaskState
      let taskState: TaskState = "working"
      let shouldClearTask = false
      
      if (status.includes("completed") || status.includes("generated") || status.includes("response")) {
        taskState = "completed"
        shouldClearTask = true
      } else if (status.includes("analyzing") || status.includes("processing")) {
        taskState = "working"
      } else if (status.includes("failed") || status.includes("error")) {
        taskState = "failed"
      }
      
      setAgentStatuses(prev => {
        const newStatuses = new Map(prev)
        const currentStatus = newStatuses.get(agent) || {
          agentName: agent,
          connectionStatus: "online" as const,
          lastSeen: new Date().toISOString()
        }
        
        newStatuses.set(agent, {
          ...currentStatus,
          currentTask: {
            taskId: inferenceId || "unknown",
            state: taskState,
            contextId: inferenceId || "",
            lastUpdate: new Date().toISOString()
          },
          lastSeen: new Date().toISOString()
        })
        
        console.log('[AgentNetwork] Updated status for', agent, 'via status_update:', newStatuses.get(agent))
        
        return newStatuses
      })
      
      // Clear any existing timeout for this agent to prevent race conditions
      const existingTimeout = statusClearTimeoutsRef.get(agent)
      if (existingTimeout) {
        clearTimeout(existingTimeout)
        statusClearTimeoutsRef.delete(agent)
      }
      
      // Clear the task after showing completion or failure (only once per completion/failure)
      if (shouldClearTask) {
        const timeoutId = setTimeout(() => {
          setAgentStatuses(prev => {
            const newStatuses = new Map(prev)
            const currentStatus = newStatuses.get(agent)
            if (currentStatus && currentStatus.currentTask && 
                (currentStatus.currentTask.state === "completed" || currentStatus.currentTask.state === "failed")) {
              newStatuses.set(agent, {
                ...currentStatus,
                currentTask: undefined, // Clear the task
                lastSeen: new Date().toISOString()
              })
              console.log('[AgentNetwork] Cleared task for', agent, 'after', currentStatus.currentTask.state)
            }
            return newStatuses
          })
          statusClearTimeoutsRef.delete(agent)
        }, 5000) // Show "Completed/Failed" for 5 seconds then return to "Online"
        
        statusClearTimeoutsRef.set(agent, timeoutId)
      }
    } else {
      console.warn('[AgentNetwork] Missing agent or status in status_update:', { agent, status, inferenceId })
    }
  }, [registeredAgents])

  // Handle tool_call events 
  const handleToolCall = useCallback((eventData: any) => {
    console.log('[AgentNetwork] Tool call received:', eventData)
    console.log('[AgentNetwork] Tool call data keys:', Object.keys(eventData || {}))
    
    // Extract agent information from tool call event
    // The log shows: agentName is in the keys, so let's extract it correctly
    const { agent, toolName, targetAgent, arguments: args, toolCallId, agentName } = eventData
    
    console.log('[AgentNetwork] Tool call extracted:', { agent, toolName, targetAgent, args, toolCallId, agentName })
    
    // Try to identify the agent - it might be in different fields
    let workingAgent = agentName || agent || targetAgent
    
    // If we still don't have an agent, check the args for agent_name
    if (!workingAgent && args && typeof args === 'object') {
      workingAgent = args.agent_name || args.agentName || args.target_agent
    }
    
    console.log('[AgentNetwork] Working agent identified:', workingAgent)
    
    if (workingAgent) {
      // Find the agent in our registered agents
      const agentExists = registeredAgents.some(regAgent => regAgent.name === workingAgent)
      if (!agentExists) {
        console.warn('[AgentNetwork] Agent from tool_call not found:', workingAgent)
        console.log('[AgentNetwork] Available agents:', registeredAgents.map(a => a.name))
        return
      }
      
      // Set status to working when an agent makes a tool call
      setAgentStatuses(prev => {
        const newStatuses = new Map(prev)
        const currentStatus = newStatuses.get(workingAgent) || {
          agentName: workingAgent,
          connectionStatus: "online" as const,
          lastSeen: new Date().toISOString()
        }
        
        newStatuses.set(workingAgent, {
          ...currentStatus,
          currentTask: {
            taskId: toolCallId || "tool-call",
            state: "working" as TaskState,
            contextId: eventData.contextId || "",
            lastUpdate: new Date().toISOString()
          },
          lastSeen: new Date().toISOString()
        })
        
        console.log('[AgentNetwork] Updated status for', workingAgent, 'via tool_call')
        
        return newStatuses
      })
    } else {
      console.warn('[AgentNetwork] No agent identified in tool_call event')
    }
  }, [registeredAgents])

  // Handle agent_activity events
  const handleAgentActivity = useCallback((eventData: any) => {
    console.log('[AgentNetwork] Agent activity received:', eventData)
    
    const { agent, activity, status } = eventData
    
    if (agent) {
      // Update agent status based on activity
      setAgentStatuses(prev => {
        const newStatuses = new Map(prev)
        const currentStatus = newStatuses.get(agent) || {
          agentName: agent,
          connectionStatus: "online" as const,
          lastSeen: new Date().toISOString()
        }
        
        newStatuses.set(agent, {
          ...currentStatus,
          currentTask: {
            taskId: "activity",
            state: "working" as TaskState,
            contextId: "",
            lastUpdate: new Date().toISOString()
          },
          lastSeen: new Date().toISOString()
        })
        
        return newStatuses
      })
    }
  }, [])

  // Handle inference_step events
  const handleInferenceStep = useCallback((eventData: any) => {
    console.log('[AgentNetwork] Inference step received:', eventData)
    
    const { agent, step, status } = eventData
    
    if (agent) {
      setAgentStatuses(prev => {
        const newStatuses = new Map(prev)
        const currentStatus = newStatuses.get(agent) || {
          agentName: agent,
          connectionStatus: "online" as const,
          lastSeen: new Date().toISOString()
        }
        
        newStatuses.set(agent, {
          ...currentStatus,
          currentTask: {
            taskId: "inference",
            state: "working" as TaskState,
            contextId: "",
            lastUpdate: new Date().toISOString()
          },
          lastSeen: new Date().toISOString()
        })
        
        return newStatuses
      })
    }
  }, [])

  // Initialize/update agent statuses - preserve existing task status, update connection status
  useEffect(() => {
    // Update agent statuses for registered agents, preserving existing task status
    setAgentStatuses(prev => {
      const updatedStatuses = new Map(prev)
      
      registeredAgents.forEach(agent => {
        const existingStatus = updatedStatuses.get(agent.name)
        
        if (existingStatus) {
          // Preserve existing status but update connection status from registry
          updatedStatuses.set(agent.name, {
            ...existingStatus,
            connectionStatus: agent.status === "online" ? "online" : "offline",
            lastSeen: new Date().toISOString()
            // Keep existing currentTask if it exists
          })
        } else {
          // New agent - initialize with just connection status
          updatedStatuses.set(agent.name, {
            agentName: agent.name,
            connectionStatus: agent.status === "online" ? "online" : "offline",
            lastSeen: new Date().toISOString()
            // No currentTask initially
          })
        }
      })
      
      // Remove agents that are no longer in the registry
      const currentAgentNames = new Set(registeredAgents.map(a => a.name))
      for (const [agentName] of updatedStatuses) {
        if (!currentAgentNames.has(agentName)) {
          updatedStatuses.delete(agentName)
        }
      }
      
      return updatedStatuses
    })
  }, [registeredAgents])

  // Note: Workflow persistence is now handled by parent ChatLayout component
  // No need to load from localStorage here since parent manages it

  // Subscribe to WebSocket events
  useEffect(() => {
    console.log('[AgentNetwork] useEffect triggered - isConnected:', isConnected)
    
    if (isConnected) {
      // Subscribe to the exact events we tested
      subscribe('task_updated', handleTaskUpdate)
      subscribe('agent_status_updated', handleAgentStatusUpdate)
      
      // Also try subscribing to other possible task-related events
      subscribe('task_created', handleTaskUpdate)
      subscribe('task_status_updated', handleTaskUpdate)
      subscribe('status_update', handleStatusUpdate)
      
      // Add more specific agent activity events
      subscribe('tool_call', handleToolCall)
      subscribe('agent_activity', handleAgentActivity)
      subscribe('inference_step', handleInferenceStep)
      
      console.log('[AgentNetwork] Subscribed to WebSocket events')
      console.log('[AgentNetwork] Current agent statuses:', Array.from(agentStatuses.keys()))
    } else {
      console.log('[AgentNetwork] Not connected to WebSocket, skipping event subscription')
    }

    return () => {
      if (isConnected) {
        unsubscribe('task_updated', handleTaskUpdate)
        unsubscribe('agent_status_updated', handleAgentStatusUpdate)
        unsubscribe('task_created', handleTaskUpdate)
        unsubscribe('task_status_updated', handleTaskUpdate)
        unsubscribe('status_update', handleStatusUpdate)
        unsubscribe('tool_call', handleToolCall)
        unsubscribe('agent_activity', handleAgentActivity)
        unsubscribe('inference_step', handleInferenceStep)
        console.log('[AgentNetwork] Unsubscribed from WebSocket events')
      }
    }
  }, [isConnected, handleTaskUpdate, handleAgentStatusUpdate, handleStatusUpdate, handleToolCall, handleAgentActivity, handleInferenceStep])

  // Get status indicator for an agent
  const getStatusIndicator = (agentName: string) => {
    const status = agentStatuses.get(agentName)
    if (!status) {
      return { icon: AlertCircle, color: "text-gray-400", label: "Unknown" }
    }

    // Check task status FIRST - task state takes priority over connection status
    // This prevents showing agents as "offline" when they're actually working on long tasks
    if (status.currentTask) {
      switch (status.currentTask.state) {
        case "working":
          return { icon: Clock, color: "text-yellow-500", label: "Working" }
        case "submitted":
          return { icon: Clock, color: "text-blue-500", label: "Pending" }
        case "completed":
          return { icon: CheckCircle, color: "text-green-500", label: "Completed" }
        case "failed":
        case "rejected":
          return { icon: XCircle, color: "text-red-500", label: "Failed" }
        case "canceled":
          return { icon: Pause, color: "text-gray-500", label: "Canceled" }
        case "input-required":
        case "auth-required":
          return { icon: AlertCircle, color: "text-orange-500", label: "Waiting" }
        default:
          return { icon: AlertCircle, color: "text-gray-400", label: "Unknown" }
      }
    }

    // Only check connection status if there's no active task
    if (status.connectionStatus === "offline") {
      return { icon: XCircle, color: "text-gray-400", label: "Offline" }
    }

    // Default to online/idle
    return { icon: CheckCircle, color: "text-green-400", label: "Online" }
  }
  
  const toggleAgent = (agentName: string) => {
    const newExpanded = new Set(expandedAgents)
    if (newExpanded.has(agentName)) {
      newExpanded.delete(agentName)
    } else {
      newExpanded.add(agentName)
    }
    setExpandedAgents(newExpanded)
  }

  const loadCurrentInstruction = async () => {
    try {
      setIsLoading(true)
      const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || "http://localhost:12000"
      const response = await fetch(`${baseUrl}/agent/root-instruction`)
      const data = await response.json()
      
      if (data.status === 'success') {
        setCurrentInstruction(data.instruction)
        setEditedInstruction(data.instruction)
      } else {
        console.error('Failed to load instruction:', data.message)
      }
    } catch (error) {
      console.error('Error loading instruction:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const updateInstruction = async () => {
    try {
      setIsLoading(true)
      const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || "http://localhost:12000"
      const response = await fetch(`${baseUrl}/agent/root-instruction`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ instruction: editedInstruction }),
      })
      
      const data = await response.json()
      
      if (data.status === 'success') {
        setCurrentInstruction(editedInstruction)
        setIsSystemPromptDialogOpen(false)
        // Show success message or toast here
        console.log('System prompt updated successfully!')
      } else {
        console.error('Failed to update instruction:', data.message)
        alert('Failed to update system prompt: ' + data.message)
      }
    } catch (error) {
      console.error('Error updating instruction:', error)
      alert('Error updating system prompt: ' + error)
    } finally {
      setIsLoading(false)
    }
  }

  const resetToDefault = async () => {
    try {
      setIsLoading(true)
      const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || "http://localhost:12000"
      const response = await fetch(`${baseUrl}/agent/root-instruction/reset`, {
        method: 'POST',
      })
      
      const data = await response.json()
      
      if (data.status === 'success') {
        // Reload the current instruction to show the default
        await loadCurrentInstruction()
        console.log('System prompt reset to default!')
      } else {
        console.error('Failed to reset instruction:', data.message)
        alert('Failed to reset system prompt: ' + data.message)
      }
    } catch (error) {
      console.error('Error resetting instruction:', error)
      alert('Error resetting system prompt: ' + error)
    } finally {
      setIsLoading(false)
    }
  }

  const clearMemory = async () => {
    setIsClearingMemory(true)
    try {
      const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
      const response = await fetch(`${baseUrl}/clear-memory`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        }
      })
      
      const data = await response.json()
      
      if (data.success) {
        console.log('Memory cleared successfully!')
        alert('Memory index cleared successfully!')
      } else {
        console.error('Failed to clear memory:', data.message)
        alert('Failed to clear memory: ' + data.message)
      }
    } catch (error) {
      console.error('Error clearing memory:', error)
      alert('Error clearing memory: ' + error)
    } finally {
      setIsClearingMemory(false)
    }
  }

  const handleRemoveAgent = async (agentName: string) => {
    if (!confirm(`Are you sure you want to remove ${agentName}? This will unregister the agent from the host.`)) {
      return
    }

    try {
      const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
      const response = await fetch(`${baseUrl}/agent/unregister`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ agentName }),
      })

      const data = await response.json()

      if (data.success) {
        console.log('Agent removed successfully:', agentName)
        // The UI will update automatically via WebSocket agent registry sync
      } else {
        console.error('Failed to remove agent:', data.message)
        alert('Failed to remove agent: ' + data.message)
      }
    } catch (error) {
      console.error('Error removing agent:', error)
      alert('Error removing agent: ' + error)
    }
  }

  const openSystemPromptDialog = () => {
    setIsSystemPromptDialogOpen(true)
    loadCurrentInstruction()
  }

  return (
    <TooltipProvider delayDuration={0}>
      <div className={cn("flex h-full flex-col bg-background transition-all duration-300")}>
        <div className="flex h-16 items-center justify-between p-2">
          {!isCollapsed && <span className="font-semibold text-lg ml-2">Network</span>}
          <Button variant="ghost" size="icon" className="h-9 w-9" onClick={onToggle}>
            {isCollapsed ? <PanelRightOpen size={20} /> : <PanelRightClose size={20} />}
          </Button>
        </div>

        {!isCollapsed && (
          <div className="p-2">
            <Card>
              <CardHeader className="p-2 pt-0 md:p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="text-primary" />
                    <CardTitle>Host Agent</CardTitle>
                  </div>
                  <Dialog open={isSystemPromptDialogOpen} onOpenChange={setIsSystemPromptDialogOpen}>
                    <DialogTrigger asChild>
                      <Button 
                        variant="ghost" 
                        size="sm" 
                        onClick={openSystemPromptDialog}
                        disabled={isLoading}
                      >
                        <Settings className="h-4 w-4" />
                      </Button>
                    </DialogTrigger>
                    <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
                      <DialogHeader>
                        <DialogTitle>Edit System Prompt</DialogTitle>
                        <DialogDescription>
                          Modify the root instruction for the Host Agent. Changes will apply immediately to new conversations.
                        </DialogDescription>
                      </DialogHeader>
                      
                      <div className="space-y-4">
                        <div>
                          <label className="text-sm font-medium">System Prompt:</label>
                          <Textarea
                            value={editedInstruction}
                            onChange={(e) => setEditedInstruction(e.target.value)}
                            placeholder="Enter the system prompt/instruction..."
                            className="min-h-[300px] font-mono text-sm"
                            disabled={isLoading}
                          />
                        </div>
                        
                        <div className="text-xs text-muted-foreground">
                          <p><strong>Tip:</strong> Use {"{agents}"} to include the current agent list and {"{current_agent}"} for the agent name.</p>
                          <p><strong>Note:</strong> Changes take effect immediately for new conversations. Current conversations continue with the previous instruction.</p>
                        </div>
                      </div>
                      
                      <DialogFooter className="gap-2">
                        <Button 
                          variant="outline" 
                          onClick={resetToDefault}
                          disabled={isLoading}
                        >
                          Reset to Default
                        </Button>
                        <Button 
                          variant="outline" 
                          onClick={() => setIsSystemPromptDialogOpen(false)}
                          disabled={isLoading}
                        >
                          Cancel
                        </Button>
                        <Button 
                          onClick={updateInstruction}
                          disabled={isLoading || !editedInstruction.trim()}
                        >
                          {isLoading ? "Updating..." : "Update System Prompt"}
                        </Button>
                      </DialogFooter>
                    </DialogContent>
                  </Dialog>
                </div>
              </CardHeader>
              <CardContent className="p-2 pt-0 md:p-4 md:pt-0">
                <div className="space-y-3">
                  <p className="text-xs text-muted-foreground">Oversees agent network.</p>
                  
                  {/* Inter-Agent Memory Toggle */}
                  <div className="flex items-center justify-between py-2">
                    <div className="flex items-center gap-2">
                      <Database className="h-4 w-4 text-muted-foreground" />
                      <Label htmlFor="inter-agent-memory" className="text-sm font-medium cursor-pointer">
                        Inter-Agent Memory
                      </Label>
                    </div>
                    <Switch 
                      id="inter-agent-memory"
                      checked={enableInterAgentMemory} 
                      onCheckedChange={onInterAgentMemoryChange}
                    />
                  </div>
                  
                  <Button 
                    variant="outline" 
                    size="sm" 
                    onClick={clearMemory}
                    disabled={isClearingMemory}
                    className="w-full"
                  >
                    <Trash2 className="h-4 w-4 mr-2" />
                    {isClearingMemory ? "Clearing..." : "Clear Memory"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        <div className="flex-1 overflow-y-auto">
          <div className="flex flex-col gap-2 p-2">
            {/* Connected Users Section */}
            {!isCollapsed && (
              <div className="mb-4">
                <div className="flex items-center gap-2 mb-2 px-1">
                  <Users className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-medium text-muted-foreground">Connected Users</span>
                </div>
                <ConnectedUsers />
              </div>
            )}
            
            {/* Agent Mode Toggle */}
            {!isCollapsed && (
              <div className="mb-4 px-1">
                <Card className="p-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Brain className="h-4 w-4 text-muted-foreground" />
                      <Label htmlFor="agent-mode" className="text-sm font-medium cursor-pointer">
                        Agent Mode
                      </Label>
                    </div>
                    <Switch 
                      id="agent-mode"
                      checked={agentMode} 
                      onCheckedChange={onAgentModeChange}
                    />
                  </div>
                  <p className="text-xs text-muted-foreground mt-2">
                    {agentMode 
                      ? "Using sequential agent-to-agent orchestration mode" 
                      : "Using parallel multi-agent orchestration mode"}
                  </p>
                  
                  {/* Workflow Button - Only show when Agent Mode is enabled */}
                  {agentMode && (
                    <div className="mt-3 pt-3 border-t">
                      <Dialog open={isWorkflowDialogOpen} onOpenChange={setIsWorkflowDialogOpen}>
                        <DialogTrigger asChild>
                          <Button 
                            variant="outline" 
                            size="sm" 
                            className="w-full"
                            onClick={() => {
                              setEditedWorkflow(workflow)
                              setIsWorkflowDialogOpen(true)
                            }}
                          >
                            <ListOrdered className="h-3 w-3 mr-2" />
                            {workflow ? "Edit Workflow" : "Define Workflow"}
                          </Button>
                        </DialogTrigger>
                        <DialogContent className="max-w-2xl">
                          <DialogHeader>
                            <DialogTitle>Agent Mode Workflow</DialogTitle>
                            <DialogDescription>
                              Define the workflow steps that will be appended to your goal. This helps guide the orchestration.
                            </DialogDescription>
                          </DialogHeader>
                          <div className="space-y-4">
                            <Textarea
                              value={editedWorkflow}
                              onChange={(e) => setEditedWorkflow(e.target.value)}
                              placeholder="Example:&#10;1. Use the image generator agent to create an image&#10;2. Use the branding agent to get branding guidelines&#10;3. Use the image generator to refine the image based on branding&#10;4. Use the image analysis agent to review the result"
                              className="min-h-[200px] font-mono text-sm"
                            />
                            {workflow && (
                              <div className="text-xs text-muted-foreground">
                                <p className="font-medium mb-1">Current workflow:</p>
                                <pre className="whitespace-pre-wrap bg-muted p-2 rounded">{workflow}</pre>
                              </div>
                            )}
                          </div>
                          <DialogFooter>
                            <Button
                              variant="outline"
                              onClick={() => {
                                setEditedWorkflow("")
                                setWorkflow("")
                                setIsWorkflowDialogOpen(false)
                              }}
                            >
                              Clear
                            </Button>
                            <Button
                              onClick={() => {
                                setWorkflow(editedWorkflow)
                                setIsWorkflowDialogOpen(false)
                              }}
                            >
                              Save Workflow
                            </Button>
                          </DialogFooter>
                        </DialogContent>
                      </Dialog>
                      {workflow && (
                        <p className="text-xs text-muted-foreground mt-2">
                          ✓ Workflow defined ({workflow.split('\n').filter(l => l.trim()).length} steps)
                        </p>
                      )}
                    </div>
                  )}
                </Card>
              </div>
            )}
            
            {/* Agents Section */}
            {!isCollapsed && registeredAgents.length > 0 && (
              <div className="mb-2">
                <div className="flex items-center gap-2 mb-2 px-1">
                  <Bot className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-medium text-muted-foreground">Remote Agents</span>
                </div>
              </div>
            )}
            
            {/* The list of agents is rendered with rich detail from the registry. */}
            {registeredAgents.map((agent, index) => {
              // Ensure agent has required properties
              const agentName = agent?.name || `Agent ${index + 1}`;
              const agentAvatar = agent?.iconUrl || agent?.avatar || "/placeholder.svg";
              const isExpanded = expandedAgents.has(agentName);
              
              if (isCollapsed) {
                const statusIndicator = getStatusIndicator(agentName)
                const StatusIcon = statusIndicator.icon
                const hasHumanInteraction = hasHumanInteractionSkill(agent)
                
                return (
                  <Tooltip key={agentName}>
                    <TooltipTrigger asChild>
                      <Button variant="ghost" className="h-12 w-12 p-0 relative">
                        {(() => {
                          const agentDisplayInfo = getAgentDisplayInfo(agentName)
                          const AgentIcon = agentDisplayInfo.icon
                          return (
                            <div className={cn(
                              "h-8 w-8 rounded-full flex items-center justify-center",
                              agentDisplayInfo.bgColor
                            )}>
                              <AgentIcon className={cn("h-4 w-4", agentDisplayInfo.color)} />
                            </div>
                          )
                        })()}
                        {/* Status indicator in bottom-right corner */}
                        <div className="absolute -bottom-1 -right-1 bg-background border border-border rounded-full p-0.5">
                          <StatusIcon className={cn("h-3 w-3", statusIndicator.color)} />
                        </div>
                        {/* Human interaction indicator in bottom-left corner */}
                        {hasHumanInteraction && (
                          <div className="absolute -bottom-1 -left-1 bg-green-500 border border-background rounded-full p-0.5">
                            <User className="h-3 w-3 text-white" />
                          </div>
                        )}
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side="left">
                      <div className="max-w-xs">
                        <p className="font-medium">{agentName}</p>
                        <div className="flex items-center gap-1 mt-1">
                          <StatusIcon className={cn("h-3 w-3", statusIndicator.color)} />
                          <span className="text-xs">{statusIndicator.label}</span>
                        </div>
                        {hasHumanInteraction && (
                          <div className="flex items-center gap-1 mt-1">
                            <User className="h-3 w-3 text-green-500" />
                            <span className="text-xs">Human Capable</span>
                          </div>
                        )}
                        {agent.description && (
                          <p className="text-xs text-muted-foreground mt-1">{agent.description}</p>
                        )}
                      </div>
                    </TooltipContent>
                  </Tooltip>
                );
              }
              
              return (
                <Card key={agentName} className="w-full">
                  <Collapsible open={isExpanded} onOpenChange={() => toggleAgent(agentName)}>
                    <CollapsibleTrigger asChild>
                      <CardHeader className="p-3 cursor-pointer hover:bg-muted/50">
                        <div className="flex items-center gap-3">
                          <div className="relative">
                            {(() => {
                              const agentDisplayInfo = getAgentDisplayInfo(agentName)
                              const AgentIcon = agentDisplayInfo.icon
                              const hasHumanInteraction = hasHumanInteractionSkill(agent)
                              return (
                                <div className={cn(
                                  "h-10 w-10 flex-shrink-0 rounded-full flex items-center justify-center",
                                  agentDisplayInfo.bgColor
                                )}>
                                  <AgentIcon className={cn("h-5 w-5", agentDisplayInfo.color)} />
                                </div>
                              )
                            })()}
                            {/* Status indicator in bottom-right corner */}
                            {(() => {
                              const statusIndicator = getStatusIndicator(agentName)
                              const StatusIcon = statusIndicator.icon
                              return (
                                <div className="absolute -bottom-1 -right-1 bg-background border border-border rounded-full p-0.5">
                                  <StatusIcon className={cn("h-3 w-3", statusIndicator.color)} />
                                </div>
                              )
                            })()}
                            {/* Human interaction indicator in bottom-left corner */}
                            {hasHumanInteractionSkill(agent) && (
                              <div className="absolute -bottom-1 -left-1 bg-green-500 border border-background rounded-full p-0.5">
                                <User className="h-3 w-3 text-white" />
                              </div>
                            )}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <h3 className="font-medium text-sm leading-tight">{agentName}</h3>
                              {/* Status badge next to name */}
                              {(() => {
                                const statusIndicator = getStatusIndicator(agentName)
                                const status = agentStatuses.get(agentName)
                                
                                if (status?.currentTask) {
                                  return (
                                    <Badge 
                                      variant="secondary" 
                                      className={cn(
                                        "text-xs font-medium",
                                        status.currentTask.state === "working" && "bg-yellow-100 text-yellow-800",
                                        status.currentTask.state === "completed" && "bg-green-100 text-green-800",
                                        (status.currentTask.state === "failed" || status.currentTask.state === "rejected") && "bg-red-100 text-red-800",
                                        status.currentTask.state === "submitted" && "bg-blue-100 text-blue-800"
                                      )}
                                    >
                                      {statusIndicator.label}
                                    </Badge>
                                  )
                                }
                                
                                return (
                                  <Badge variant="outline" className="text-xs">
                                    {statusIndicator.label}
                                  </Badge>
                                )
                              })()}
                            </div>
                            {agent.description && (
                              <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                                {agent.description}
                              </p>
                            )}
                          </div>
                          <div className="flex items-center gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 w-7 p-0 hover:bg-destructive/10 hover:text-destructive"
                              onClick={(e) => {
                                e.stopPropagation()
                                handleRemoveAgent(agentName)
                              }}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                            {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                          </div>
                        </div>
                      </CardHeader>
                    </CollapsibleTrigger>
                    
                    <CollapsibleContent>
                      <CardContent className="p-3 pt-0 space-y-3">
                        {/* Real-time Status Section */}
                        {(() => {
                          const status = agentStatuses.get(agentName)
                          const statusIndicator = getStatusIndicator(agentName)
                          const StatusIcon = statusIndicator.icon
                          
                          return (
                            <div className="bg-muted/30 rounded-lg p-3 space-y-2">
                              <div className="flex items-center gap-2">
                                <StatusIcon className={cn("h-4 w-4", statusIndicator.color)} />
                                <span className="font-medium text-sm">Real-time Status</span>
                              </div>
                              
                              <div className="space-y-1 text-xs">
                                <div className="flex justify-between">
                                  <span className="text-muted-foreground">Connection:</span>
                                  <span className={cn(
                                    "font-medium",
                                    status?.connectionStatus === "online" ? "text-green-600" : "text-gray-500"
                                  )}>
                                    {status?.connectionStatus || "Unknown"}
                                  </span>
                                </div>
                                
                                {status?.currentTask && (
                                  <>
                                    <div className="flex justify-between">
                                      <span className="text-muted-foreground">Current Task:</span>
                                      <span className="font-mono text-xs">
                                        {status.currentTask.taskId.slice(0, 8)}...
                                      </span>
                                    </div>
                                    <div className="flex justify-between">
                                      <span className="text-muted-foreground">Task State:</span>
                                      <Badge 
                                        variant="outline" 
                                        className={cn(
                                          "text-xs",
                                          status.currentTask.state === "working" && "border-yellow-300 text-yellow-800",
                                          status.currentTask.state === "completed" && "border-green-300 text-green-800",
                                          (status.currentTask.state === "failed" || status.currentTask.state === "rejected") && "border-red-300 text-red-800",
                                          status.currentTask.state === "submitted" && "border-blue-300 text-blue-800"
                                        )}
                                      >
                                        {status.currentTask.state}
                                      </Badge>
                                    </div>
                                    <div className="flex justify-between">
                                      <span className="text-muted-foreground">Last Update:</span>
                                      <span className="text-xs">
                                        {new Date(status.currentTask.lastUpdate).toLocaleTimeString()}
                                      </span>
                                    </div>
                                  </>
                                )}
                                
                                <div className="flex justify-between">
                                  <span className="text-muted-foreground">Last Seen:</span>
                                  <span className="text-xs">
                                    {status?.lastSeen ? new Date(status.lastSeen).toLocaleTimeString() : "Never"}
                                  </span>
                                </div>
                              </div>
                            </div>
                          )
                        })()}
                        
                        {/* Agent Details */}
                        <div className="space-y-2">
                          {agent.version && (
                            <div className="flex items-center gap-2 text-xs">
                              <Hash className="h-3 w-3 text-muted-foreground" />
                              <span className="text-muted-foreground">Version:</span>
                              <span className="font-mono">{agent.version}</span>
                            </div>
                          )}
                          
                          {agent.url && (
                            <div className="flex items-center gap-2 text-xs">
                              <Globe className="h-3 w-3 text-muted-foreground" />
                              <span className="text-muted-foreground">Endpoint:</span>
                              <code className="text-xs bg-muted px-1 rounded">{agent.url}</code>
                            </div>
                          )}
                          
                          {agent.documentationUrl && (
                            <div className="flex items-center gap-2 text-xs">
                              <FileText className="h-3 w-3 text-muted-foreground" />
                              <a 
                                href={agent.documentationUrl} 
                                target="_blank" 
                                rel="noopener noreferrer"
                                className="text-blue-600 hover:text-blue-800 flex items-center gap-1"
                              >
                                Documentation
                                <ExternalLink className="h-3 w-3" />
                              </a>
                            </div>
                          )}
                        </div>

                        {/* Capabilities */}
                        {agent.capabilities && Object.values(agent.capabilities).some(v => v === true || (Array.isArray(v) && v.length > 0)) && (
                          <div className="space-y-2">
                            <div className="flex items-center gap-2">
                              <Zap className="h-3 w-3 text-muted-foreground" />
                              <span className="text-xs font-medium text-muted-foreground">Capabilities</span>
                            </div>
                            <div className="flex flex-wrap gap-1">
                              {agent.capabilities.streaming && (
                                <Badge variant="secondary" className="text-xs">Streaming</Badge>
                              )}
                              {agent.capabilities.pushNotifications && (
                                <Badge variant="secondary" className="text-xs">Push Notifications</Badge>
                              )}
                              {agent.capabilities.stateTransitionHistory && (
                                <Badge variant="secondary" className="text-xs">State History</Badge>
                              )}
                              {agent.capabilities.extensions && agent.capabilities.extensions.length > 0 && (
                                <Badge variant="secondary" className="text-xs">
                                  Extensions ({agent.capabilities.extensions.length})
                                </Badge>
                              )}
                            </div>
                          </div>
                        )}

                        {/* Skills */}
                        {agent.skills && agent.skills.length > 0 && (
                          <div className="space-y-2">
                            <span className="text-xs font-medium text-muted-foreground">Skills ({agent.skills.length})</span>
                            <div className="space-y-2">
                              {agent.skills.map((skill, idx) => (
                                <div key={skill.id || idx} className="bg-muted/50 rounded p-2">
                                  <div className="font-medium text-xs">{skill.name}</div>
                                  {skill.description && (
                                    <div className="text-xs text-muted-foreground mt-1 line-clamp-2">
                                      {skill.description}
                                    </div>
                                  )}
                                  {skill.tags && skill.tags.length > 0 && (
                                    <div className="flex flex-wrap gap-1 mt-2">
                                      {skill.tags.map((tag, tagIdx) => (
                                        <Badge key={tagIdx} variant="outline" className="text-xs">
                                          {tag}
                                        </Badge>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Input/Output Modes */}
                        {((agent.defaultInputModes && agent.defaultInputModes.length > 0) || 
                          (agent.defaultOutputModes && agent.defaultOutputModes.length > 0)) && (
                          <div className="space-y-2">
                            <span className="text-xs font-medium text-muted-foreground">Supported Formats</span>
                            <div className="space-y-1">
                              {agent.defaultInputModes && agent.defaultInputModes.length > 0 && (
                                <div className="flex items-center gap-2 text-xs">
                                  <span className="text-muted-foreground">Input:</span>
                                  <div className="flex flex-wrap gap-1">
                                    {agent.defaultInputModes.map((mode, idx) => (
                                      <Badge key={idx} variant="outline" className="text-xs">
                                        {mode}
                                      </Badge>
                                    ))}
                                  </div>
                                </div>
                              )}
                              {agent.defaultOutputModes && agent.defaultOutputModes.length > 0 && (
                                <div className="flex items-center gap-2 text-xs">
                                  <span className="text-muted-foreground">Output:</span>
                                  <div className="flex flex-wrap gap-1">
                                    {agent.defaultOutputModes.map((mode, idx) => (
                                      <Badge key={idx} variant="outline" className="text-xs">
                                        {mode}
                                      </Badge>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                      </CardContent>
                    </CollapsibleContent>
                  </Collapsible>
                </Card>
              );
            })}
          </div>
          
          {!isCollapsed && (
            <div className="p-2">
              <SimulateAgentRegistration />
            </div>
          )}
        </div>
      </div>
    </TooltipProvider>
  )
}
