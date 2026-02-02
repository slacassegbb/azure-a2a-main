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
import { PanelRightClose, PanelRightOpen, ShieldCheck, ChevronDown, ChevronRight, Globe, Hash, Zap, FileText, ExternalLink, Settings, Clock, CheckCircle, XCircle, AlertCircle, Pause, Brain, Search, MessageSquare, Database, Shield, BarChart3, Gavel, Users, Bot, Trash2, User, ListOrdered, Network, RotateCcw, Play, Calendar, Square, Workflow, History, X } from "lucide-react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { SimulateAgentRegistration } from "./simulate-agent-registration"
import { ConnectedUsers } from "./connected-users"
import { SessionInvitationNotification } from "./session-invite"
import { VisualWorkflowDesigner } from "./visual-workflow-designer"
import { AgentNetworkDag } from "./agent-network-dag"
import { cn } from "@/lib/utils"
import { getRunHistory, listSchedules, deleteSchedule, RunHistoryItem, ScheduledWorkflow, formatNextRun } from "@/lib/scheduler-api"
import { generateWorkflowId } from "@/lib/active-workflow-api"
import { ScheduleWorkflowDialog } from "./schedule-workflow-dialog"
import { useState, useEffect, useCallback, useRef } from "react"
import { useEventHub } from "@/contexts/event-hub-context"
import { useSearchParams } from "next/navigation"
import { getOrCreateSessionId } from "@/lib/session"

type Agent = {
  name: string
  description?: string
  url?: string
  endpoint?: string  // Added for session-scoped agents
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
    timestamp: string
    lastUpdate: string
  }
  connectionStatus: "online" | "offline" | "connecting"
  lastSeen: string
}

type Props = {
  registeredAgents: Agent[]
  isCollapsed: boolean
  onToggle: () => void
  enableInterAgentMemory: boolean
  onInterAgentMemoryChange: (enabled: boolean) => void
  workflow?: string
  workflowName?: string
  workflowGoal?: string
  activeWorkflows?: Array<{
    id: string
    workflow: string
    name: string
    description?: string
    goal: string
  }>
  onWorkflowChange?: (workflow: string) => void
  onWorkflowNameChange?: (name: string) => void
  onWorkflowGoalChange?: (goal: string) => void
  onAddWorkflow?: (workflow: { id: string; workflow: string; name: string; description?: string; goal: string }) => Promise<boolean>
  onRemoveWorkflow?: (workflowId: string) => Promise<boolean>
  onClearAllWorkflows?: () => Promise<boolean>
  onRunWorkflow?: () => void
  onScheduleWorkflow?: () => void
  dagNodes?: any[]
  dagLinks?: any[]
  activeNode?: string | null
}

// Store persistent color assignments for agents
const agentColorMap = new Map<string, any>()

// Simple hash function to get consistent color for agent name
function hashAgentName(name: string): number {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = ((hash << 5) - hash) + name.charCodeAt(i)
    hash = hash & hash // Convert to 32bit integer
  }
  return Math.abs(hash)
}

// Function to get consistent colors for each agent
function getAgentDisplayInfo(agentName: string) {
  // Check if we already have a color assigned for this agent
  if (agentColorMap.has(agentName)) {
    return agentColorMap.get(agentName)
  }
  
  const colors = [
    { color: "text-pink-700", bgColor: "bg-pink-100", hex: "#ec4899" },      // pink - matches AGENT_COLORS[0]
    { color: "text-purple-700", bgColor: "bg-purple-100", hex: "#8b5cf6" },  // purple - matches AGENT_COLORS[1]
    { color: "text-cyan-700", bgColor: "bg-cyan-100", hex: "#06b6d4" },      // cyan - matches AGENT_COLORS[2]
    { color: "text-emerald-700", bgColor: "bg-emerald-100", hex: "#10b981" }, // emerald - matches AGENT_COLORS[3]
    { color: "text-amber-700", bgColor: "bg-amber-100", hex: "#f59e0b" },    // amber - matches AGENT_COLORS[4]
    { color: "text-red-700", bgColor: "bg-red-100", hex: "#ef4444" },        // red - matches AGENT_COLORS[5]
    { color: "text-blue-700", bgColor: "bg-blue-100", hex: "#3b82f6" },      // blue - matches AGENT_COLORS[6]
    { color: "text-teal-700", bgColor: "bg-teal-100", hex: "#14b8a6" },      // teal - matches AGENT_COLORS[7]
    { color: "text-orange-700", bgColor: "bg-orange-100", hex: "#f97316" },  // orange - matches AGENT_COLORS[8]
    { color: "text-violet-700", bgColor: "bg-violet-100", hex: "#a855f7" },  // violet - matches AGENT_COLORS[9]
  ]
  
  // Use hash for deterministic color selection - same agent name always gets same color
  const colorIndex = hashAgentName(agentName) % colors.length
  const agentDisplayInfo = {
    ...colors[colorIndex],
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

export function AgentNetwork({ registeredAgents, isCollapsed, onToggle, enableInterAgentMemory, onInterAgentMemoryChange, workflow: propWorkflow, workflowName: propWorkflowName, workflowGoal: propWorkflowGoal, activeWorkflows = [], onWorkflowChange, onWorkflowNameChange, onWorkflowGoalChange, onAddWorkflow, onRemoveWorkflow, onClearAllWorkflows, onRunWorkflow, onScheduleWorkflow, dagNodes = [], dagLinks = [], activeNode = null }: Props) {
  const searchParams = useSearchParams()
  const currentConversationId = searchParams.get('conversationId') || undefined
  
  const [expandedAgents, setExpandedAgents] = useState<Set<string>>(new Set())
  const [isSystemPromptDialogOpen, setIsSystemPromptDialogOpen] = useState(false)
  const [currentInstruction, setCurrentInstruction] = useState("")
  const [editedInstruction, setEditedInstruction] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [isClearingMemory, setIsClearingMemory] = useState(false)
  
  // Host agent inferencing state (tracks when host is actively processing)
  const [isHostInferencing, setIsHostInferencing] = useState(false)
  
  // Collapsible section states
  const [isConnectedUsersOpen, setIsConnectedUsersOpen] = useState(true)
  const [isRemoteAgentsOpen, setIsRemoteAgentsOpen] = useState(true)
  
  // Workflow state - use prop if provided, otherwise local state
  const [isWorkflowDialogOpen, setIsWorkflowDialogOpen] = useState(false)
  const [localWorkflow, setLocalWorkflow] = useState("")
  const [localWorkflowName, setLocalWorkflowName] = useState("")
  const [localWorkflowGoal, setLocalWorkflowGoal] = useState("")
  const [editedWorkflow, setEditedWorkflow] = useState("")
  
  const workflow = propWorkflow !== undefined ? propWorkflow : localWorkflow
  const setWorkflow = onWorkflowChange || setLocalWorkflow
  const workflowName = propWorkflowName !== undefined ? propWorkflowName : localWorkflowName
  const setWorkflowName = onWorkflowNameChange || setLocalWorkflowName
  const workflowGoal = propWorkflowGoal !== undefined ? propWorkflowGoal : localWorkflowGoal
  const setWorkflowGoal = onWorkflowGoalChange || setLocalWorkflowGoal
  
  // Run history state
  const [runHistory, setRunHistory] = useState<RunHistoryItem[]>([])
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)
  const [expandedScheduledRunId, setExpandedScheduledRunId] = useState<string | null>(null)
  
  // Workflow card expansion state - track which workflow ID is expanded (null = none)
  const [expandedWorkflowId, setExpandedWorkflowId] = useState<string | null>(null)
  const [expandedScheduleId, setExpandedScheduleId] = useState<string | null>(null)
  
  // Scheduled workflows state
  const [scheduledWorkflows, setScheduledWorkflows] = useState<ScheduledWorkflow[]>([])
  const [isScheduleDialogOpen, setIsScheduleDialogOpen] = useState(false)
  
  // Agent status tracking state
  const [agentStatuses, setAgentStatuses] = useState<Map<string, AgentStatus>>(new Map())
  
  // Store status clear timeouts to prevent race conditions
  const statusClearTimeoutsRef = useState<Map<string, NodeJS.Timeout>>(new Map())[0]
  
  // Track when agents entered "working" state to ensure minimum display time
  const workingStartTimeRef = useRef<Map<string, number>>(new Map())
  const pendingCompletedRef = useRef<Map<string, { eventData: any, timeoutId: NodeJS.Timeout }>>(new Map())
  
  // Minimum time to show "working" state (in ms) before allowing transition to completed
  const MIN_WORKING_DISPLAY_TIME = 800
  
  // Use existing EventHub context instead of creating new WebSocket client
  const { subscribe, unsubscribe, isConnected, emit } = useEventHub()
  
  // Use ref for registeredAgents to avoid recreating callback on every agent list update
  const registeredAgentsRef = useRef<Agent[]>(registeredAgents)
  registeredAgentsRef.current = registeredAgents // Keep ref in sync

  // Helper function to apply status update
  const applyStatusUpdate = useCallback((targetAgent: string, taskId: string, mappedState: TaskState, contextId: string, timestamp: string) => {
    setAgentStatuses(prev => {
      const newStatuses = new Map(prev)
      const currentStatus = newStatuses.get(targetAgent) || {
        agentName: targetAgent,
        connectionStatus: "online" as const,
        lastSeen: new Date().toISOString()
      }
      
      // Track when we enter "working" state
      if (mappedState === "working") {
        workingStartTimeRef.current.set(targetAgent, Date.now())
      }
      
      // Clear working start time on terminal states
      if (mappedState === "completed" || mappedState === "failed") {
        workingStartTimeRef.current.delete(targetAgent)
      }
      
      const currentTaskState = currentStatus.currentTask?.state
      const currentTimestamp = currentStatus.currentTask?.timestamp
      
      // Never allow backwards transition from terminal states
      const isCurrentTerminal = currentTaskState === "completed" || currentTaskState === "failed"
      const isNewNonTerminal = mappedState === "working" || mappedState === "submitted"
      
      if (isCurrentTerminal && isNewNonTerminal) {
        console.log('[AgentNetwork] ⏭️ Blocking backwards transition:', currentTaskState, '→', mappedState)
        return prev
      }
      
      // Check timestamp ordering
      if (currentTimestamp && timestamp) {
        const currentTime = new Date(currentTimestamp).getTime()
        const newTime = new Date(timestamp).getTime()
        if (newTime < currentTime) {
          console.log('[AgentNetwork] ⏭️ Ignoring older event')
          return prev
        }
      }
      
      console.log('[AgentNetwork] ✅ State transition:', currentTaskState || 'none', '→', mappedState, 'for', targetAgent)
      
      const updatedStatus = {
        ...currentStatus,
        currentTask: {
          taskId,
          state: mappedState,
          contextId: contextId || '',
          timestamp: timestamp || new Date().toISOString(),
          lastUpdate: new Date().toISOString()
        },
        lastSeen: new Date().toISOString()
      }
      
      newStatuses.set(targetAgent, updatedStatus)
      
      // Clear any existing timeout for this agent
      const existingTimeout = statusClearTimeoutsRef.get(targetAgent)
      if (existingTimeout) {
        clearTimeout(existingTimeout)
        statusClearTimeoutsRef.delete(targetAgent)
      }
      
      // Clear the task after showing completion or failure for 5 seconds
      if (mappedState === "completed" || mappedState === "failed") {
        const timeoutId = setTimeout(() => {
          setAgentStatuses(prev => {
            const newStatuses = new Map(prev)
            const currentStatus = newStatuses.get(targetAgent)
            if (currentStatus && currentStatus.currentTask && 
                (currentStatus.currentTask.state === "completed" || currentStatus.currentTask.state === "failed")) {
              newStatuses.set(targetAgent, {
                ...currentStatus,
                currentTask: undefined,
                lastSeen: new Date().toISOString()
              })
            }
            return newStatuses
          })
          statusClearTimeoutsRef.delete(targetAgent)
        }, 5000)
        
        statusClearTimeoutsRef.set(targetAgent, timeoutId)
      }
      
      return newStatuses
    })
  }, [statusClearTimeoutsRef])

  // Handle task status updates from WebSocket
  // FIXED: Prevents out-of-order events from causing backwards state transitions
  // ENHANCED: Ensures "working" state is visible for minimum time before showing "completed"
  const handleTaskUpdate = useCallback((eventData: any) => {
    try {
      const { taskId, state, contextId, agentName, timestamp } = eventData
      
      console.log('[AgentNetwork] 📥 task_updated received:', { agentName, state, taskId: taskId?.substring?.(0, 8), timestamp })
      console.log('[AgentNetwork] 🔍 About to check targetAgent...')
      
      let targetAgent = agentName
    
    if (!targetAgent) {
      console.log('[AgentNetwork] ❌ No targetAgent, returning early')
      return
    }
    
    // Check if agent exists in registry
    // If not, DON'T return early - we want to update the status anyway
    // The agent might be registered later, and status should still show
    const agentExists = registeredAgentsRef.current.some(agent => agent.name === targetAgent)
    if (!agentExists) {
      console.log('[AgentNetwork] ⚠️ Agent not in registry yet, but continuing with status update:', targetAgent)
      // Continue processing - don't return early
    }
    
    if (!taskId || !state) {
      console.log('[AgentNetwork] ❌ Missing taskId or state:', { taskId, state })
      return
    }
    
    console.log('[AgentNetwork] ✅ Passed validation checks, processing event...')
    
    // Map A2A task states to our UI states
    let mappedState: TaskState = "working"
    const stateStr = String(state).toLowerCase()
    
    if (stateStr === "completed" || stateStr === "done" || stateStr === "success" || stateStr === "finished") {
      mappedState = "completed"
    } else if (stateStr === "failed" || stateStr === "error" || stateStr === "cancelled") {
      mappedState = "failed"
    } else if (stateStr === "submitted" || stateStr === "pending" || stateStr === "queued" || stateStr === "created") {
      mappedState = "submitted"
    } else if (stateStr === "working" || stateStr === "running" || stateStr === "in-progress" || stateStr === "in_progress") {
      mappedState = "working"
    } else if (stateStr === "input_required" || stateStr === "input-required") {
      mappedState = "input-required"
    }
    
    console.log('[AgentNetwork] 🎨 Mapped state:', stateStr, '→', mappedState)
    
    // ========================================================================
    // MINIMUM WORKING TIME: Ensure "working" state is visible before "completed"
    // ========================================================================
    if (mappedState === "completed" || mappedState === "failed") {
      const workingStartTime = workingStartTimeRef.current.get(targetAgent)
      
      if (workingStartTime) {
        const elapsedTime = Date.now() - workingStartTime
        const remainingTime = MIN_WORKING_DISPLAY_TIME - elapsedTime
        
        if (remainingTime > 0) {
          console.log(`[AgentNetwork] ⏳ Delaying ${mappedState} by ${remainingTime}ms to show working state for ${targetAgent}`)
          
          // Cancel any existing pending completed for this agent
          const existing = pendingCompletedRef.current.get(targetAgent)
          if (existing) {
            clearTimeout(existing.timeoutId)
          }
          
          // Schedule the completed update after remaining time
          const timeoutId = setTimeout(() => {
            console.log(`[AgentNetwork] ⏰ Delayed ${mappedState} now applying for ${targetAgent}`)
            applyStatusUpdate(targetAgent, taskId, mappedState, contextId, timestamp)
            pendingCompletedRef.current.delete(targetAgent)
          }, remainingTime)
          
          pendingCompletedRef.current.set(targetAgent, { eventData, timeoutId })
          return // Don't apply immediately
        }
      }
    }
    
    // Apply the status update immediately
    applyStatusUpdate(targetAgent, taskId, mappedState, contextId, timestamp)
    } catch (error) {
      console.error('[AgentNetwork] ❌ ERROR in handleTaskUpdate:', error)
    }
  }, [applyStatusUpdate]) // Depend on applyStatusUpdate

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

  // REMOVED: handleStatusUpdate was updating agent sidebar status from status_update events
  // This caused conflicts - agent sidebar should ONLY use task_updated events (single source of truth)
  // status_update events are for the chat panel's inference steps UI, not the agent sidebar

  // REMOVED: handleToolCall, handleAgentActivity, handleInferenceStep
  // These were causing conflicts with task_updated (the single source of truth)
  // Agent status should ONLY come from task_updated events

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

  // Fetch scheduled workflows - extracted as useCallback so it can be passed to dialog
  // Filter by session_id to only show user's own scheduled workflows
  const fetchScheduledWorkflows = useCallback(async () => {
    try {
      const sessionId = getOrCreateSessionId()
      const schedules = await listSchedules(undefined, sessionId)
      setScheduledWorkflows(schedules)
    } catch (error) {
      console.error('[AgentNetwork] Failed to fetch scheduled workflows:', error)
    }
  }, [])

  // Delete a scheduled workflow
  const handleDeleteSchedule = useCallback(async (scheduleId: string, _workflowName: string) => {
    try {
      await deleteSchedule(scheduleId)
      await fetchScheduledWorkflows()
    } catch (error) {
      console.error('[AgentNetwork] Failed to delete schedule:', error)
      alert('Failed to delete schedule. Please try again.')
    }
  }, [fetchScheduledWorkflows])

  // Note: Workflow persistence is now handled by parent ChatLayout component
  // No need to load from localStorage here since parent manages it

  // Fetch run history when workflow is active
  useEffect(() => {
    const fetchRunHistory = async () => {
      if (!workflow) {
        setRunHistory([])
        return
      }
      setIsLoadingHistory(true)
      try {
        const sessionId = getOrCreateSessionId()
        const history = await getRunHistory(undefined, sessionId, 10)
        setRunHistory(history)
      } catch (error) {
        console.error('[AgentNetwork] Failed to fetch run history:', error)
      } finally {
        setIsLoadingHistory(false)
      }
    }
    
    fetchRunHistory()
    fetchScheduledWorkflows()
    
    // Refresh history and schedules every 30 seconds
    const interval = setInterval(() => {
      fetchRunHistory()
      fetchScheduledWorkflows()
    }, 30000)
    return () => clearInterval(interval)
  }, [workflow, fetchScheduledWorkflows])

  // Subscribe to WebSocket events - STABLE subscriptions (no churn)
  useEffect(() => {
    if (!isConnected) {
      return
    }
    
    // SINGLE SOURCE OF TRUTH: task_updated contains all agent status info
    subscribe('task_updated', handleTaskUpdate)
    subscribe('agent_status_updated', handleAgentStatusUpdate)
    
    // Track host agent inference state
    const handleInferenceStarted = () => {
      console.log('[AgentNetwork] Host inference started')
      setIsHostInferencing(true)
    }
    const handleInferenceEnded = () => {
      console.log('[AgentNetwork] Host inference ended')
      setIsHostInferencing(false)
    }
    
    subscribe('shared_inference_started', handleInferenceStarted)
    subscribe('shared_inference_ended', handleInferenceEnded)
    
    console.log('[AgentNetwork] ✅ Subscribed to task_updated, agent_status_updated, shared_inference_*')

    return () => {
      unsubscribe('task_updated', handleTaskUpdate)
      unsubscribe('agent_status_updated', handleAgentStatusUpdate)
      unsubscribe('shared_inference_started', handleInferenceStarted)
      unsubscribe('shared_inference_ended', handleInferenceEnded)
    }
  }, [isConnected, subscribe, unsubscribe, handleTaskUpdate, handleAgentStatusUpdate])

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

  // Get host agent status indicator (uses inference state + task tracking)
  const getHostAgentStatus = () => {
    // Primary: Use inference state (most reliable for host agent)
    if (isHostInferencing) {
      return { bgColor: "bg-yellow-500", label: "Working", animate: true }
    }
    
    // Secondary: Check task-based status from WebSocket events
    const hostAgentNames = ["foundry-host-agent", "host-agent", "Host Agent"]
    
    for (const name of hostAgentNames) {
      const status = agentStatuses.get(name)
      if (status?.currentTask) {
        switch (status.currentTask.state) {
          case "working":
            return { bgColor: "bg-yellow-500", label: "Working", animate: true }
          case "submitted":
            return { bgColor: "bg-blue-500", label: "Pending", animate: true }
          case "completed":
            return { bgColor: "bg-green-500", label: "Completed", animate: false }
          case "failed":
          case "rejected":
            return { bgColor: "bg-red-500", label: "Failed", animate: false }
          case "canceled":
            return { bgColor: "bg-gray-500", label: "Canceled", animate: false }
          case "input-required":
          case "auth-required":
            return { bgColor: "bg-orange-500", label: "Waiting", animate: true }
        }
      }
    }
    
    // Default to online
    return { bgColor: "bg-green-500", label: "Online", animate: false }
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
    // Find the agent object to get its endpoint URL
    const agent = registeredAgents.find(a => a.name === agentName)
    const agentUrl = agent?.endpoint || agent?.url
    
    if (!agent || !agentUrl) {
      console.error('Agent not found or missing endpoint:', agentName, agent)
      alert('Error: Could not find agent endpoint')
      return
    }

    if (!confirm(`Are you sure you want to remove ${agentName}? This will disable the agent for your session.`)) {
      return
    }

    try {
      const sessionId = getOrCreateSessionId()
      const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
      
      const response = await fetch(`${baseUrl}/agents/session/disable`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, agent_url: agentUrl })
      })

      if (response.ok) {
        console.log('Agent disabled successfully:', agentName)
        // Emit event to update UI (AgentNetwork will handle removal from registeredAgents)
        emit('session_agent_disabled', { agent_url: agentUrl })
      } else {
        const data = await response.json()
        console.error('Failed to disable agent:', data.message)
        alert('Failed to disable agent: ' + data.message)
      }
    } catch (error) {
      console.error('Error disabling agent:', error)
      alert('Error disabling agent: ' + error)
    }
  }

  const openSystemPromptDialog = () => {
    setIsSystemPromptDialogOpen(true)
    loadCurrentInstruction()
  }

  return (
    <TooltipProvider delayDuration={0}>
      <div className={cn("flex h-full flex-col transition-all duration-300")}>
        {isCollapsed ? (
          // Collapsed state - minimal vertical layout
          <div className="flex flex-col items-center justify-start h-full py-2">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon" className="h-9 w-9" onClick={onToggle}>
                  <PanelRightOpen size={20} />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="left">Expand Sidebar</TooltipContent>
            </Tooltip>
          </div>
        ) : (
          // Expanded state - full layout
          <>
            <div className="flex h-10 items-center justify-end p-2">
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onToggle}>
                <PanelRightClose size={18} />
              </Button>
            </div>

            <div className="p-2 pt-0">
            <Card>
              <CardHeader className="p-3 pb-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div 
                      className="p-2 rounded-lg flex items-center justify-center"
                      style={{ backgroundColor: "rgba(59, 130, 246, 0.1)" }}
                    >
                      <ShieldCheck className="h-4 w-4" style={{ color: "#3b82f6" }} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <CardTitle className="text-sm font-semibold">Host Agent</CardTitle>
                        {(() => {
                          const hostStatus = getHostAgentStatus()
                          return (
                            <div 
                              className={`w-2 h-2 rounded-full ${hostStatus.bgColor} ${hostStatus.animate ? 'animate-pulse' : ''}`} 
                              title={hostStatus.label}
                            />
                          )
                        })()}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    {/* DAG Network Button */}
                    <Dialog>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <DialogTrigger asChild>
                            <Button variant="ghost" size="sm" className="h-7 w-7 p-0">
                              <Network className="h-3.5 w-3.5" />
                            </Button>
                          </DialogTrigger>
                        </TooltipTrigger>
                        <TooltipContent side="left">View agent network diagram</TooltipContent>
                      </Tooltip>
                      <DialogContent className="max-w-4xl max-h-[85vh]">
                        <DialogHeader>
                          <DialogTitle>Agent Network DAG</DialogTitle>
                        </DialogHeader>
                        <div className="h-[600px] w-full">
                          <AgentNetworkDag 
                            nodes={dagNodes} 
                            links={dagLinks}
                            activeNodeId={activeNode}
                            key="agent-network-dag-stable"
                          />
                        </div>
                      </DialogContent>
                    </Dialog>
                    {/* Clear Memory Button */}
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button 
                          variant="ghost" 
                          size="sm"
                          className="h-7 w-7 p-0"
                          onClick={clearMemory}
                          disabled={isClearingMemory}
                        >
                          <RotateCcw className="h-3.5 w-3.5" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent side="left">
                        {isClearingMemory ? "Clearing..." : "Clear memory"}
                      </TooltipContent>
                    </Tooltip>
                    {/* Memory Toggle */}
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div className="flex items-center">
                          <Switch 
                            id="inter-agent-memory"
                            checked={enableInterAgentMemory} 
                            onCheckedChange={onInterAgentMemoryChange}
                            className="scale-75"
                          />
                        </div>
                      </TooltipTrigger>
                      <TooltipContent side="left">
                        {enableInterAgentMemory ? "Memory enabled" : "Memory disabled"}
                      </TooltipContent>
                    </Tooltip>
                    {/* Settings Button */}
                    <Dialog open={isSystemPromptDialogOpen} onOpenChange={setIsSystemPromptDialogOpen}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <DialogTrigger asChild>
                            <Button 
                              variant="ghost" 
                              size="sm" 
                              className="h-7 w-7 p-0"
                              onClick={openSystemPromptDialog}
                              disabled={isLoading}
                            >
                              <Settings className="h-3.5 w-3.5" />
                            </Button>
                          </DialogTrigger>
                        </TooltipTrigger>
                        <TooltipContent side="left">Edit system prompt</TooltipContent>
                      </Tooltip>
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
                </div>
              </CardHeader>
              <CardContent className="px-3 pb-3 pt-2">
                {/* Workflow Buttons Row */}
                <div className="flex gap-2">
                  {/* Define/Edit Workflow Button */}
                  <Dialog 
                    open={isWorkflowDialogOpen} 
                    onOpenChange={(open) => {
                      // When dialog closes, auto-sync the edited workflow to parent
                      if (!open && editedWorkflow && editedWorkflow !== workflow) {
                        console.log('[AgentNetwork] Auto-syncing workflow on dialog close')
                        setWorkflow(editedWorkflow)
                      }
                      setIsWorkflowDialogOpen(open)
                    }}
                  >
                    <DialogTrigger asChild>
                      <Button 
                        variant="outline" 
                        size="sm" 
                        className="flex-1 h-8 text-xs"
                        onClick={() => {
                          setEditedWorkflow(workflow)
                          setIsWorkflowDialogOpen(true)
                        }}
                      >
                        <ListOrdered className="h-3 w-3 mr-2" />
                        {activeWorkflows.length > 0 ? "Add Another Workflow" : "Add Workflow"}
                      </Button>
                    </DialogTrigger>
                        <DialogContent className="max-w-[95vw] max-h-[95vh] h-[900px]">
                          <Tabs defaultValue="visual" className="flex-1 flex flex-col w-full">
                            <DialogHeader className="mb-4">
                              <DialogTitle>Workflow Designer</DialogTitle>
                              <DialogDescription>
                                Define workflow steps to orchestrate agents. Connect one step to multiple agents for parallel execution.
                              </DialogDescription>
                            </DialogHeader>
                            
                            <TabsList className="grid w-full grid-cols-2 mb-4">
                              <TabsTrigger value="visual">Visual Designer</TabsTrigger>
                              <TabsTrigger value="text">Text Editor</TabsTrigger>
                            </TabsList>
                            
                            <TabsContent value="visual" className="flex-1 overflow-hidden w-full">
                              <div className="h-[680px] w-full">
                                <VisualWorkflowDesigner
                                  registeredAgents={registeredAgents.map(agent => ({
                                    ...agent,
                                    id: agent.name.toLowerCase().replace(/\s+/g, '-')
                                  }))}
                                  onWorkflowGenerated={(text) => setEditedWorkflow(text)}
                                  onWorkflowNameChange={setWorkflowName}
                                  onWorkflowGoalChange={setWorkflowGoal}
                                  initialWorkflow={editedWorkflow}
                                  initialWorkflowName={workflowName}
                                  conversationId={currentConversationId}
                                />
                              </div>
                            </TabsContent>                            
                            <TabsContent value="text" className="flex-1 overflow-hidden w-full">
                              <div className="space-y-4 h-full flex-col w-full">
                                <Textarea
                                  value={editedWorkflow}
                                    onChange={(e) => setEditedWorkflow(e.target.value)}
                                    placeholder="Example:&#10;1. Use the image generator agent to create an image&#10;2. Use the branding agent to get branding guidelines&#10;3. Use the image generator to refine the image based on branding&#10;4. Use the image analysis agent to review the result"
                                    className="flex-1 font-mono text-sm"
                                  />
                                  {workflow && (
                                    <div className="text-xs text-muted-foreground">
                                      <p className="font-medium mb-1">Current workflow:</p>
                                      <pre className="whitespace-pre-wrap bg-muted p-2 rounded">{workflow}</pre>
                                    </div>
                                  )}
                                </div>
                              </TabsContent>
                            </Tabs>
                            
                            <DialogFooter>
                              <Button
                                variant="outline"
                                onClick={() => {
                                  setEditedWorkflow("")
                                  setIsWorkflowDialogOpen(false)
                                }}
                              >
                                Cancel
                              </Button>
                              <Button
                                onClick={async () => {
                                  if (!editedWorkflow.trim()) return
                                  
                                  // Create new workflow object
                                  const newWorkflow = {
                                    id: generateWorkflowId(),
                                    workflow: editedWorkflow,
                                    name: workflowName || "Untitled Workflow",
                                    goal: workflowGoal || ""
                                  }
                                  
                                  // Use onAddWorkflow if available (multi-workflow mode)
                                  if (onAddWorkflow) {
                                    await onAddWorkflow(newWorkflow)
                                  } else {
                                    // Fallback to legacy single workflow mode
                                    setWorkflow(editedWorkflow)
                                  }
                                  
                                  // Clear the editor and close dialog
                                  setEditedWorkflow("")
                                  setIsWorkflowDialogOpen(false)
                                }}
                                disabled={!editedWorkflow.trim()}
                              >
                                Add Workflow to Session
                              </Button>
                            </DialogFooter>
                          </DialogContent>
                        </Dialog>
                        
                        {/* Schedule Workflow Button */}
                        <Button 
                          variant="outline" 
                          size="sm" 
                          className="flex-1 h-8 text-xs"
                          onClick={() => setIsScheduleDialogOpen(true)}
                        >
                          <Calendar className="h-3 w-3 mr-2" />
                          Schedules
                        </Button>
                      </div>
                        {/* Active Workflows - show multiple workflow cards */}
                        {activeWorkflows.length > 0 && (
                          <div className="mt-3 space-y-2">
                            <div className="flex items-center justify-between px-1">
                              <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium">
                                Active Workflows ({activeWorkflows.length})
                              </p>
                              {activeWorkflows.length > 1 && (
                                <TooltipProvider>
                                  <Tooltip>
                                    <TooltipTrigger asChild>
                                      <Button
                                        variant="ghost"
                                        size="sm"
                                        className="h-5 px-1.5 text-[10px] text-red-400 hover:text-red-300 hover:bg-red-500/10"
                                        onClick={() => onClearAllWorkflows?.()}
                                      >
                                        Clear All
                                      </Button>
                                    </TooltipTrigger>
                                    <TooltipContent>
                                      <p>Remove all active workflows</p>
                                    </TooltipContent>
                                  </Tooltip>
                                </TooltipProvider>
                              )}
                            </div>
                            
                            {/* Workflow Cards */}
                            <div className="space-y-2">
                              {activeWorkflows.map((wf, index) => (
                                <div key={wf.id} className="group">
                                  {/* Workflow Header with name and actions - Clickable to expand */}
                                  <div
                                    onClick={() => setExpandedWorkflowId(expandedWorkflowId === wf.id ? null : wf.id)}
                                    className="flex items-center justify-between bg-gradient-to-r from-purple-500/10 to-blue-500/10 rounded-lg p-2 border border-purple-500/20 hover:border-purple-400/40 transition-colors cursor-pointer"
                                  >
                                    <div className="flex items-center gap-2 flex-1 min-w-0">
                                      <div className="p-1.5 rounded-md bg-purple-500/20">
                                        <Workflow className="h-3.5 w-3.5 text-purple-400" />
                                      </div>
                                      <div className="flex-1 min-w-0 text-left">
                                        <p className="text-xs font-semibold text-slate-200 truncate">
                                          {wf.name || "Untitled"}
                                        </p>
                                        <p className="text-[10px] text-purple-300/70">
                                          {wf.workflow.split('\n').filter(l => l.trim()).length} steps
                                        </p>
                                        {wf.goal && (
                                          <p className="text-[10px] text-slate-400 truncate mt-0.5" title={wf.goal}>
                                            Goal: {wf.goal}
                                          </p>
                                        )}
                                      </div>
                                    </div>
                                    <div className="flex items-center gap-0.5">
                                      <TooltipProvider>
                                        <Tooltip>
                                          <TooltipTrigger asChild>
                                            <Button
                                              variant="ghost"
                                              size="icon"
                                              className="h-6 w-6 text-red-500 hover:text-red-400 hover:bg-red-500/10"
                                              onClick={(e) => {
                                                e.stopPropagation()
                                                onRemoveWorkflow?.(wf.id)
                                              }}
                                            >
                                              <X className="h-3 w-3" />
                                            </Button>
                                          </TooltipTrigger>
                                          <TooltipContent>
                                            <p>Remove from session</p>
                                          </TooltipContent>
                                        </Tooltip>
                                      </TooltipProvider>
                                      {expandedWorkflowId === wf.id ? (
                                        <ChevronDown className="h-4 w-4 text-purple-400 ml-1" />
                                      ) : (
                                        <ChevronRight className="h-4 w-4 text-purple-400 ml-1" />
                                      )}
                                    </div>
                                  </div>
                                  
                                  {/* Expanded content - View Steps */}
                                  {expandedWorkflowId === wf.id && (
                                    <div className="space-y-2 pl-2 border-l-2 border-purple-500/20 mt-1">
                                      {/* Workflow Steps Preview */}
                                      <div className="bg-slate-900/50 rounded-md p-2 max-h-32 overflow-y-auto">
                                        <p className="text-[9px] text-slate-500 uppercase tracking-wider mb-1.5">Steps</p>
                                        <div className="space-y-1">
                                          {wf.workflow.split('\n').filter(l => l.trim()).map((step, stepIndex) => (
                                            <div key={stepIndex} className="flex items-start gap-2">
                                              <div className="flex-shrink-0 w-4 h-4 rounded-full bg-purple-500/20 flex items-center justify-center mt-0.5">
                                                <span className="text-[9px] font-bold text-purple-400">{stepIndex + 1}</span>
                                              </div>
                                              <p className="text-[10px] text-slate-400 leading-tight line-clamp-1">
                                                {step.replace(/^\d+\.\s*/, '')}
                                              </p>
                                            </div>
                                          ))}
                                        </div>
                                      </div>
                                      
                                      {/* Run History */}
                                      <div className="bg-slate-900/50 rounded-md p-2 max-h-64 overflow-y-auto">
                                        <p className="text-[9px] text-slate-500 uppercase tracking-wider mb-1.5">Run History</p>
                                        {isLoadingHistory ? (
                                          <p className="text-[10px] text-slate-500 text-center py-2">Loading...</p>
                                        ) : runHistory.length === 0 ? (
                                          <p className="text-[10px] text-slate-500 text-center py-2">No runs yet</p>
                                        ) : (
                                          <div className="space-y-1">
                                            {runHistory.filter(run => run.workflow_name === wf.name).slice(0, 5).map((run) => (
                                              <div key={run.run_id} className="border-b border-slate-800 last:border-0">
                                                <button
                                                  onClick={(e) => {
                                                    e.stopPropagation()
                                                    setExpandedRunId(expandedRunId === run.run_id ? null : run.run_id)
                                                  }}
                                                  className="w-full flex items-center justify-between gap-2 py-1.5 hover:bg-slate-800/50 rounded px-1 cursor-pointer transition-colors"
                                                >
                                                  <div className="flex items-center gap-1.5 min-w-0 flex-1">
                                                    {run.status === 'success' ? (
                                                      <CheckCircle className="h-3 w-3 text-green-500 flex-shrink-0" />
                                                    ) : (
                                                      <XCircle className="h-3 w-3 text-red-500 flex-shrink-0" />
                                                    )}
                                                    <span className="text-[10px] text-slate-300 truncate">
                                                      {run.workflow_name || wf.name || 'Workflow'}
                                                    </span>
                                                  </div>
                                                  <div className="flex items-center gap-1.5 flex-shrink-0">
                                                    <span className="text-[9px] text-slate-500">
                                                      {new Date(run.started_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                                                    </span>
                                                    <span className="text-[9px] text-slate-500">
                                                      {Math.round(run.duration_seconds)}s
                                                    </span>
                                                    {expandedRunId === run.run_id ? (
                                                      <ChevronDown className="h-3 w-3 text-slate-500" />
                                                    ) : (
                                                      <ChevronRight className="h-3 w-3 text-slate-500" />
                                                    )}
                                                  </div>
                                                </button>
                                                
                                                {/* Expanded run details */}
                                                {expandedRunId === run.run_id && (
                                                  <div className="px-2 pb-2 pt-1 space-y-2 bg-slate-800/30 rounded-b">
                                                    {/* Timing */}
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
                                                    
                                                    {/* Error */}
                                                    {run.error && (
                                                      <div>
                                                        <p className="text-[9px] text-red-400 mb-0.5">Error</p>
                                                        <div className="bg-red-500/10 border border-red-500/20 rounded p-1.5 max-h-20 overflow-y-auto">
                                                          <p className="text-[9px] text-red-300 font-mono whitespace-pre-wrap break-words">{run.error}</p>
                                                        </div>
                                                      </div>
                                                    )}
                                                    
                                                    {/* Result */}
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
                                            ))}
                                          </div>
                                        )}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                            
                            {/* Info text about multi-workflow routing */}
                            <p className="text-[9px] text-slate-500 px-1 italic">
                              The AI will automatically choose the best workflow for each request.
                            </p>
                          </div>
                        )}

                        {/* Scheduled Workflows - shown as cards like active workflow */}
                        {scheduledWorkflows.length > 0 && (
                          <div className="mt-3 space-y-2">
                            <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium px-1">Scheduled Workflows</p>
                            {scheduledWorkflows.map((schedule) => (
                              <div key={schedule.id} className="space-y-2">
                                {/* Scheduled Workflow Header - Clickable to expand */}
                                <div
                                  onClick={() => setExpandedScheduleId(expandedScheduleId === schedule.id ? null : schedule.id)}
                                  className={cn(
                                    "flex items-center justify-between rounded-lg p-2 border cursor-pointer transition-colors",
                                    schedule.enabled 
                                      ? "bg-gradient-to-r from-blue-500/10 to-cyan-500/10 border-blue-500/20 hover:border-blue-400/40"
                                      : "bg-slate-800/30 border-slate-700/30 opacity-60 hover:border-slate-600/40"
                                  )}
                                >
                                  <div className="flex items-center gap-2 flex-1 min-w-0">
                                    <div className={cn(
                                      "p-1.5 rounded-md",
                                      schedule.enabled ? "bg-blue-500/20" : "bg-slate-700/50"
                                    )}>
                                      <Calendar className={cn(
                                        "h-3.5 w-3.5",
                                        schedule.enabled ? "text-blue-400" : "text-slate-500"
                                      )} />
                                    </div>
                                    <div className="flex-1 min-w-0 text-left">
                                      <p className="text-xs font-semibold text-slate-200 truncate">
                                        {schedule.workflow_name}
                                      </p>
                                      <p className={cn(
                                        "text-[10px]",
                                        schedule.enabled ? "text-blue-300/70" : "text-slate-500"
                                      )}>
                                        {schedule.schedule_type === 'interval' && `Every ${schedule.interval_minutes} min`}
                                        {schedule.schedule_type === 'daily' && `Daily at ${schedule.time_of_day}`}
                                        {schedule.schedule_type === 'weekly' && `Weekly at ${schedule.time_of_day}`}
                                        {schedule.schedule_type === 'monthly' && `Monthly on day ${schedule.day_of_month}`}
                                        {schedule.schedule_type === 'once' && 'One-time run'}
                                        {schedule.schedule_type === 'cron' && 'Custom schedule'}
                                        {schedule.enabled && schedule.next_run && ` • Next: ${formatNextRun(schedule.next_run)}`}
                                        {!schedule.enabled && ' • Disabled'}
                                      </p>
                                      {schedule.workflow_goal && (
                                        <p className="text-[10px] text-slate-400 truncate mt-0.5" title={schedule.workflow_goal}>
                                          Goal: {schedule.workflow_goal}
                                        </p>
                                      )}
                                    </div>
                                  </div>
                                  <div className="flex items-center gap-1">
                                    {/* Status indicators */}
                                    {schedule.success_count > 0 && (
                                      <span className="text-[9px] text-green-400 px-1">{schedule.success_count}✓</span>
                                    )}
                                    {schedule.failure_count > 0 && (
                                      <span className="text-[9px] text-red-400 px-1">{schedule.failure_count}✗</span>
                                    )}
                                    {/* Edit Schedule Button */}
                                    <TooltipProvider>
                                      <Tooltip>
                                        <TooltipTrigger asChild>
                                          <Button
                                            variant="ghost"
                                            size="icon"
                                            className="h-6 w-6 text-blue-400 hover:text-blue-300 hover:bg-blue-500/10"
                                            onClick={(e) => {
                                              e.stopPropagation()
                                              setIsScheduleDialogOpen(true)
                                            }}
                                          >
                                            <Settings className="h-3 w-3" />
                                          </Button>
                                        </TooltipTrigger>
                                        <TooltipContent>
                                          <p>Edit Schedule</p>
                                        </TooltipContent>
                                      </Tooltip>
                                    </TooltipProvider>
                                    {/* Delete Schedule Button */}
                                    <TooltipProvider>
                                      <Tooltip>
                                        <TooltipTrigger asChild>
                                          <Button
                                            variant="ghost"
                                            size="icon"
                                            className="h-6 w-6 text-red-400 hover:text-red-300 hover:bg-red-500/10"
                                            onClick={(e) => {
                                              e.stopPropagation()
                                              handleDeleteSchedule(schedule.id, schedule.workflow_name)
                                            }}
                                          >
                                            <Trash2 className="h-3 w-3" />
                                          </Button>
                                        </TooltipTrigger>
                                        <TooltipContent>
                                          <p>Delete Schedule</p>
                                        </TooltipContent>
                                      </Tooltip>
                                    </TooltipProvider>
                                    {expandedScheduleId === schedule.id ? (
                                      <ChevronDown className="h-4 w-4 text-blue-400" />
                                    ) : (
                                      <ChevronRight className="h-4 w-4 text-blue-400" />
                                    )}
                                  </div>
                                </div>

                                {/* Expanded content - Run History */}
                                {expandedScheduleId === schedule.id && (
                                  <div className="space-y-2 pl-2 border-l-2 border-blue-500/20">
                                    <div className="bg-slate-900/50 rounded-md p-2 max-h-64 overflow-y-auto">
                                      <p className="text-[9px] text-slate-500 uppercase tracking-wider mb-1.5">Run History ({schedule.run_count} runs)</p>
                                      {runHistory.filter(run => run.schedule_id === schedule.id).length === 0 ? (
                                        <p className="text-[10px] text-slate-500 text-center py-2">No runs recorded yet</p>
                                      ) : (
                                        <div className="space-y-1">
                                          {runHistory
                                            .filter(run => run.schedule_id === schedule.id)
                                            .slice(0, 5)
                                            .map((run) => (
                                              <div key={run.run_id} className="border-b border-slate-800 last:border-0">
                                                <button
                                                  onClick={() => setExpandedScheduledRunId(expandedScheduledRunId === run.run_id ? null : run.run_id)}
                                                  className="w-full flex items-center justify-between gap-2 py-1.5 hover:bg-slate-800/50 rounded px-1 cursor-pointer transition-colors"
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
                                                    {expandedScheduledRunId === run.run_id ? (
                                                      <ChevronDown className="h-3 w-3 text-slate-500" />
                                                    ) : (
                                                      <ChevronRight className="h-3 w-3 text-slate-500" />
                                                    )}
                                                  </div>
                                                </button>
                                                
                                                {/* Expanded details */}
                                                {expandedScheduledRunId === run.run_id && (
                                                  <div className="px-2 pb-2 pt-1 space-y-2 bg-slate-800/30 rounded-b">
                                                    {/* Timing */}
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
                                                    
                                                    {/* Error */}
                                                    {run.error && (
                                                      <div>
                                                        <p className="text-[9px] text-red-400 mb-0.5">Error</p>
                                                        <div className="bg-red-500/10 border border-red-500/20 rounded p-1.5 max-h-20 overflow-y-auto">
                                                          <p className="text-[9px] text-red-300 font-mono whitespace-pre-wrap break-words">{run.error}</p>
                                                        </div>
                                                      </div>
                                                    )}
                                                    
                                                    {/* Result */}
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
                                            ))}
                                          {runHistory.filter(run => run.schedule_id === schedule.id).length > 5 && (
                                            <p className="text-[9px] text-slate-500 italic text-center pt-1">
                                              +{runHistory.filter(run => run.schedule_id === schedule.id).length - 5} more runs
                                            </p>
                                          )}
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                        
                        {/* Schedule Dialog */}
                        <ScheduleWorkflowDialog 
                          open={isScheduleDialogOpen} 
                          onOpenChange={setIsScheduleDialogOpen}
                          workflowId={workflowName || undefined}
                          workflowName={workflowName || undefined}
                          workflowGoal={workflowGoal || undefined}
                          onScheduleChange={fetchScheduledWorkflows}
                        />
              </CardContent>
            </Card>
          </div>

        <div className="flex-1 overflow-y-auto">
          <div className="flex flex-col gap-2 p-2">
            {/* Current Session User Section */}
            <Collapsible open={isConnectedUsersOpen} onOpenChange={setIsConnectedUsersOpen}>
                <div className="mb-4">
                  <CollapsibleTrigger asChild>
                    <Button 
                      variant="ghost" 
                      className="flex items-center gap-2 mb-2 px-1 hover:bg-transparent"
                    >
                      <Users className="h-4 w-4 text-muted-foreground" />
                      <span className="text-sm font-medium text-muted-foreground">Current Session</span>
                      {isConnectedUsersOpen ? (
                        <ChevronDown className="h-4 w-4 text-muted-foreground" />
                      ) : (
                        <ChevronRight className="h-4 w-4 text-muted-foreground" />
                      )}
                    </Button>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <ConnectedUsers />
                  </CollapsibleContent>
                </div>
              </Collapsible>
            
            {/* Agent Mode Toggle - Removed standalone card, now part of Host Agent */}
            
            {/* Remote Agents Section */}
            <Collapsible open={isRemoteAgentsOpen} onOpenChange={setIsRemoteAgentsOpen}>
                <div className="mb-2">
                  <div className="flex items-center justify-between mb-2 px-1">
                    <CollapsibleTrigger asChild>
                      <Button 
                        variant="ghost" 
                        className="flex items-center gap-2 p-0 hover:bg-transparent"
                      >
                        <Bot className="h-4 w-4 text-muted-foreground" />
                        <span className="text-sm font-medium text-muted-foreground">Remote Agents</span>
                        {isRemoteAgentsOpen ? (
                          <ChevronDown className="h-4 w-4 text-muted-foreground" />
                        ) : (
                          <ChevronRight className="h-4 w-4 text-muted-foreground" />
                        )}
                      </Button>
                    </CollapsibleTrigger>
                  </div>
                </div>
                
                <CollapsibleContent>
            {/* The list of agents is rendered with rich detail from the registry. */}
            <div className="space-y-2 pt-2">
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
                          // Convert hex to rgba for background (10% opacity like user cards)
                          const hex = agentDisplayInfo.hex.replace('#', '')
                          const r = parseInt(hex.substr(0, 2), 16)
                          const g = parseInt(hex.substr(2, 2), 16)
                          const b = parseInt(hex.substr(4, 2), 16)
                          const bgColor = `rgba(${r}, ${g}, ${b}, 0.1)`
                          
                          return (
                            <div 
                              className="p-2 rounded-lg flex items-center justify-center"
                              style={{ backgroundColor: bgColor }}
                            >
                              <AgentIcon className="h-4 w-4" style={{ color: agentDisplayInfo.hex }} />
                            </div>
                          )
                        })()}
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
                              // Convert hex to rgba for background (10% opacity like user cards)
                              const hex = agentDisplayInfo.hex.replace('#', '')
                              const r = parseInt(hex.substr(0, 2), 16)
                              const g = parseInt(hex.substr(2, 2), 16)
                              const b = parseInt(hex.substr(4, 2), 16)
                              const bgColor = `rgba(${r}, ${g}, ${b}, 0.1)`
                              
                              return (
                                <div 
                                  className="p-2 rounded-lg flex items-center justify-center"
                                  style={{ backgroundColor: bgColor }}
                                >
                                  <AgentIcon className="h-4 w-4" style={{ color: agentDisplayInfo.hex }} />
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
                              <CardTitle className="text-sm font-semibold">{agentName}</CardTitle>
                              {/* Status dot and label like user card */}
                              {(() => {
                                const statusIndicator = getStatusIndicator(agentName)
                                const status = agentStatuses.get(agentName)
                                const showStatusText = status?.currentTask && status.currentTask.state !== "completed"
                                
                                // Determine dot color based on status
                                let dotColor = "bg-green-500" // Default online
                                if (!status) {
                                  dotColor = "bg-gray-400" // Unknown
                                } else if (status.connectionStatus === "offline" && !status.currentTask) {
                                  dotColor = "bg-gray-400" // Offline
                                } else if (status.currentTask) {
                                  switch (status.currentTask.state) {
                                    case "working":
                                      dotColor = "bg-yellow-500"
                                      break
                                    case "completed":
                                      dotColor = "bg-green-500"
                                      break
                                    case "failed":
                                    case "rejected":
                                      dotColor = "bg-red-500"
                                      break
                                    case "submitted":
                                      dotColor = "bg-blue-500"
                                      break
                                    case "canceled":
                                      dotColor = "bg-gray-500"
                                      break
                                    case "input-required":
                                    case "auth-required":
                                      dotColor = "bg-orange-500"
                                      break
                                    default:
                                      dotColor = "bg-gray-400"
                                  }
                                }
                                
                                return (
                                  <>
                                    <div className={cn("w-2 h-2 rounded-full flex-shrink-0", dotColor)} title={statusIndicator.label}></div>
                                    {showStatusText && (
                                      <span className="text-xs text-muted-foreground">{statusIndicator.label}</span>
                                    )}
                                  </>
                                )
                              })()}
                            </div>
                            {agent.description && (
                              <div className="text-xs text-muted-foreground mt-1 line-clamp-2">
                                {agent.description}
                              </div>
                            )}
                          </div>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 p-0 hover:bg-destructive/10 hover:text-destructive flex-shrink-0"
                            onClick={(e) => {
                              e.stopPropagation()
                              handleRemoveAgent(agentName)
                            }}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
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
                                        {status.currentTask.state === "submitted" 
                                          ? "Processing request" 
                                          : status.currentTask.state === "working" 
                                          ? "Analyzing" 
                                          : status.currentTask.state === "completed" 
                                          ? "Task complete" 
                                          : status.currentTask.state === "failed" 
                                          ? "Task failed" 
                                          : status.currentTask.state}
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
                          
                          {(agent.url || agent.endpoint) && (
                            <div className="flex items-center gap-2 text-xs">
                              <Globe className="h-3 w-3 text-muted-foreground" />
                              <span className="text-muted-foreground">Endpoint:</span>
                              <code className="text-xs bg-muted px-1 py-0.5 rounded truncate max-w-[200px] block">
                                {agent.url || agent.endpoint}
                              </code>
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
                </CollapsibleContent>
              </Collapsible>
          </div>
        </div>
        
        {/* Agent Registration Buttons - Always at bottom */}
        <div className="p-2">
          <SimulateAgentRegistration />
        </div>
          </>
        )}
      </div>
      
      {/* Session Invitation Notifications - fixed position overlay */}
      <SessionInvitationNotification />
    </TooltipProvider>
  )
}
