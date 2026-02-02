"use client"

import type React from "react"
import { useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { X, Plus, Trash2, Download, Upload, Library, X as CloseIcon, Send, Loader2, PlayCircle, StopCircle, Phone, PhoneOff, Mic, MicOff, ChevronLeft, ChevronRight, Save } from "lucide-react"
import { ScrollArea } from "@/components/ui/scroll-area"
import { WorkflowCatalog } from "./workflow-catalog"
import { Input } from "@/components/ui/input"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useEventHub } from "@/hooks/use-event-hub"
import { useVoiceLive } from "@/hooks/use-voice-live"
import { getScenarioById } from "@/lib/voice-scenarios"
import { useSearchParams } from "next/navigation"
import { createContextId } from "@/lib/session"

interface WorkflowStep {
  id: string
  agentId: string
  agentName: string
  agentColor: string
  description: string
  x: number
  y: number
  order: number
}

interface Connection {
  id: string
  fromStepId: string
  toStepId: string
}

interface Agent {
  id?: string
  name: string
  description?: string
  skills?: Array<{
    id: string
    name: string
    description: string
    tags?: string[]
    examples?: string[]
  }>
  color?: string
  [key: string]: any
}

interface VisualWorkflowDesignerProps {
  registeredAgents: Agent[]
  onWorkflowGenerated: (workflowText: string) => void
  onWorkflowNameChange?: (name: string) => void
  onWorkflowGoalChange?: (goal: string) => void
  initialWorkflow?: string
  initialWorkflowName?: string
  conversationId?: string // Optional: use existing conversation from chat panel
}

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

const HOST_COLOR = "#6366f1"

export function VisualWorkflowDesigner({ 
  registeredAgents, 
  onWorkflowGenerated,
  onWorkflowNameChange,
  onWorkflowGoalChange,
  initialWorkflow,
  initialWorkflowName,
  conversationId: externalConversationId
}: VisualWorkflowDesignerProps) {
  // Also read directly from URL as backup
  const searchParams = useSearchParams()
  const urlConversationId = searchParams.get('conversationId')
  
  // Use the conversation ID from URL (most reliable) or prop or generate new
  const activeConversationId = urlConversationId || externalConversationId
  
  console.log("[VisualWorkflowDesigner] Conversation IDs:", {
    fromUrl: urlConversationId,
    fromProp: externalConversationId,
    active: activeConversationId
  })
  
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [workflowSteps, setWorkflowSteps] = useState<WorkflowStep[]>([])
  const workflowStepsRef = useRef<WorkflowStep[]>([])
  const [connections, setConnections] = useState<Connection[]>([])
  const connectionsRef = useRef<Connection[]>([])
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null)
  const selectedStepIdRef = useRef<string | null>(null)
  const [draggedAgent, setDraggedAgent] = useState<Agent | null>(null)
  const [isDraggingOver, setIsDraggingOver] = useState(false)
  const [editingDescription, setEditingDescription] = useState<string>("")
  const [editingStepId, setEditingStepId] = useState<string | null>(null)
  const [cursorPosition, setCursorPosition] = useState<number>(0)
  const [showCursor, setShowCursor] = useState<boolean>(true)
  const [generatedWorkflowText, setGeneratedWorkflowText] = useState<string>("")
  const [workflowOrderMap, setWorkflowOrderMap] = useState<Map<string, number>>(new Map())
  const workflowOrderMapRef = useRef<Map<string, number>>(new Map())
  const hasInitializedRef = useRef(false)
  const [showCatalog, setShowCatalog] = useState(true)
  const [showSaveDialog, setShowSaveDialog] = useState(false)
  const [workflowName, setWorkflowName] = useState("")
  const [workflowDescription, setWorkflowDescription] = useState("")
  const [workflowCategory, setWorkflowCategory] = useState("Custom")
  const [workflowGoal, setWorkflowGoal] = useState("")
  const [catalogRefreshTrigger, setCatalogRefreshTrigger] = useState(0)
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null)
  
  // Component lifecycle logging (for debugging)
  // useEffect(() => {
  // }, [])
  
  // Connection creation state
  const [isCreatingConnection, setIsCreatingConnection] = useState(false)
  const isCreatingConnectionRef = useRef(false)
  const [connectionStart, setConnectionStart] = useState<{ stepId: string, x: number, y: number } | null>(null)
  const connectionStartRef = useRef<{ stepId: string, x: number, y: number } | null>(null)
  const [connectionPreview, setConnectionPreview] = useState<{ x: number, y: number } | null>(null)
  
  // Zoom and pan
  const zoomRef = useRef(1)
  const panOffsetRef = useRef({ x: 0, y: 0 })
  const [isPanning, setIsPanning] = useState(false)
  const panStartRef = useRef({ x: 0, y: 0 })
  
  // Testing state
  const [testInput, setTestInput] = useState("")
  const [isTesting, setIsTesting] = useState(false)
  const [workflowConversationId, setWorkflowConversationId] = useState<string | null>(null)
  const [testMessages, setTestMessages] = useState<Array<{ role: string, content: string, agent?: string }>>([])
  const [stepStatuses, setStepStatuses] = useState<Map<string, { 
    status: string, 
    messages: Array<{ text?: string, imageUrl?: string, fileName?: string, timestamp: number }>,
    completedAt?: number,
    startTime?: number,
    messagesCollapsed?: boolean,
    duration?: number,
    tokenUsage?: { prompt_tokens: number, completion_tokens: number, total_tokens: number }
  }>>(new Map())
  const stepStatusesRef = useRef<Map<string, { 
    status: string, 
    messages: Array<{ text?: string, imageUrl?: string, fileName?: string, timestamp: number }>,
    completedAt?: number,
    startTime?: number,
    messagesCollapsed?: boolean,
    duration?: number,
    tokenUsage?: { prompt_tokens: number, completion_tokens: number, total_tokens: number }
  }>>(new Map())
  const [waitingStepId, setWaitingStepId] = useState<string | null>(null)
  const waitingStepIdRef = useRef<string | null>(null)
  // Keep ref in sync with state
  useEffect(() => { waitingStepIdRef.current = waitingStepId }, [waitingStepId])
  const [waitingResponse, setWaitingResponse] = useState("")
  const [waitingMessage, setWaitingMessage] = useState<string | null>(null) // Captured agent message when waiting
  const workflowStepsMapRef = useRef<Map<string, WorkflowStep>>(new Map())
  const imageCache = useRef<Map<string, HTMLImageElement>>(new Map())
  const testTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  // Track which step ID is currently active for each agent name
  // When agent "X" has multiple steps, this tracks which step ID is currently receiving events
  const agentStepIndexRef = useRef<Map<string, string>>(new Map())
  const [hostMessages, setHostMessages] = useState<Array<{ message: string, target: string, timestamp: number, agentColor?: string, isHost?: boolean }>>([])
  const orchestrationSidebarRef = useRef<HTMLDivElement>(null)
  const [showOrchestrationSidebar, setShowOrchestrationSidebar] = useState(true)
  const [hostTokenUsage, setHostTokenUsage] = useState<{ prompt_tokens: number, completion_tokens: number, total_tokens: number } | null>(null)
  
  // Toggle message visibility for a step
  const toggleStepMessages = (stepId: string) => {
    const current = stepStatusesRef.current.get(stepId)
    if (!current) return
    
    const newEntry = {
      ...current,
      messagesCollapsed: !current.messagesCollapsed
    }
    stepStatusesRef.current.set(stepId, newEntry)
    setStepStatuses(prev => {
      const newMap = new Map(prev)
      newMap.set(stepId, newEntry)
      return newMap
    })
  }
  
  // Event Hub for live updates
  const { subscribe, unsubscribe, emit } = useEventHub()
  
  // Track Voice Live call IDs for response injection
  const voiceLiveCallMapRef = useRef<Map<string, string>>(new Map()) // messageId -> call_id
  
  // Helper function to generate workflow text from current refs (used by voiceLive hook)
  // NEW: Supports parallel branches with sub-lettered steps (2a, 2b, etc.)
  const generateWorkflowTextFromRefs = (): string => {
    const steps = workflowStepsRef.current
    const conns = connectionsRef.current
    
    if (steps.length === 0) return ""
    
    // If connections exist, use them to determine order and detect parallel branches
    if (conns.length > 0) {
      // Build adjacency maps
      const outgoing = new Map<string, string[]>()
      const incoming = new Map<string, string[]>()
      
      conns.forEach(conn => {
        if (!outgoing.has(conn.fromStepId)) outgoing.set(conn.fromStepId, [])
        outgoing.get(conn.fromStepId)!.push(conn.toStepId)
        
        if (!incoming.has(conn.toStepId)) incoming.set(conn.toStepId, [])
        incoming.get(conn.toStepId)!.push(conn.fromStepId)
      })
      
      const connectedStepIds = new Set<string>()
      conns.forEach(conn => {
        connectedStepIds.add(conn.fromStepId)
        connectedStepIds.add(conn.toStepId)
      })
      
      // Find root nodes
      const hasIncoming = new Set(conns.map(c => c.toStepId))
      const rootNodes = steps.filter(step => 
        connectedStepIds.has(step.id) && !hasIncoming.has(step.id)
      )
      
      // BFS with parallel detection
      interface WorkflowEntry {
        stepNumber: number
        subLetter?: string
        step: WorkflowStep
      }
      
      const entries: WorkflowEntry[] = []
      const visited = new Set<string>()
      let currentStepNumber = 0
      
      type QueueItem = { stepId: string, parentNumber: number, parallelSiblings: string[], siblingIndex: number }
      const queue: QueueItem[] = []
      
      if (rootNodes.length > 1) {
        rootNodes.forEach((node, idx) => {
          queue.push({ stepId: node.id, parentNumber: 0, parallelSiblings: rootNodes.map(n => n.id), siblingIndex: idx })
        })
      } else {
        rootNodes.forEach(node => {
          queue.push({ stepId: node.id, parentNumber: 0, parallelSiblings: [], siblingIndex: 0 })
        })
      }
      
      while (queue.length > 0) {
        const { stepId, parentNumber, parallelSiblings, siblingIndex } = queue.shift()!
        
        if (visited.has(stepId)) continue
        visited.add(stepId)
        
        const step = steps.find(s => s.id === stepId)
        if (!step) continue
        
        let stepNumber: number
        let subLetter: string | undefined
        
        if (parallelSiblings.length > 1) {
          stepNumber = parentNumber + 1
          subLetter = String.fromCharCode(97 + siblingIndex)
        } else {
          currentStepNumber++
          stepNumber = currentStepNumber
        }
        
        entries.push({ stepNumber, subLetter, step })
        
        const children = outgoing.get(stepId) || []
        if (children.length > 1) {
          children.forEach((childId, idx) => {
            queue.push({ stepId: childId, parentNumber: stepNumber, parallelSiblings: children, siblingIndex: idx })
          })
        } else if (children.length === 1) {
          queue.push({ stepId: children[0], parentNumber: stepNumber, parallelSiblings: [], siblingIndex: 0 })
        }
        
        if (parallelSiblings.length <= 1) {
          // Sequential
        } else if (siblingIndex === parallelSiblings.length - 1) {
          currentStepNumber = stepNumber
        }
      }
      
      entries.sort((a, b) => {
        if (a.stepNumber !== b.stepNumber) return a.stepNumber - b.stepNumber
        return (a.subLetter || '').localeCompare(b.subLetter || '')
      })
      
      return entries.map(entry => {
        const label = entry.subLetter ? `${entry.stepNumber}${entry.subLetter}` : `${entry.stepNumber}`
        const desc = entry.step.description || `Use the ${entry.step.agentName} agent`
        // Include agent name so orchestrator knows which agent to route to
        return `${label}. [${entry.step.agentName}] ${desc}`
      }).join('\n')
    } else {
      // No connections - use visual order
      const sortedSteps = [...steps].sort((a, b) => a.order - b.order)
      return sortedSteps.map((step, index) => 
        // Include agent name so orchestrator knows which agent to route to
        `${index + 1}. [${step.agentName}] ${step.description || `Use the ${step.agentName} agent`}`
      ).join('\n')
    }
  }
  
  // Voice Live hook for speaking agent messages
  const voiceLive = useVoiceLive({
    foundryProjectUrl: process.env.NEXT_PUBLIC_AZURE_AI_FOUNDRY_PROJECT_ENDPOINT || '',
    model: process.env.NEXT_PUBLIC_VOICE_MODEL || 'gpt-realtime',
    scenario: getScenarioById('host-agent-chat'),
    onSendToA2A: async (message: string, metadata?: any): Promise<string> => {
      // Send message through the test workflow
      try {
        console.log('[Voice Live] Sending message to workflow test:', message)
        console.log('[Voice Live] Metadata:', metadata)
        
        const messageId = `voice_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
        
        // Store the mapping of messageId to Voice Live call_id
        if (metadata?.tool_call_id) {
          voiceLiveCallMapRef.current.set(messageId, metadata.tool_call_id)
          console.log('[Voice Live] Stored call mapping:', messageId, '->', metadata.tool_call_id)
        }
        
        // Set the test input and trigger testing
        setTestInput(message)
        
        // Small delay to ensure state is updated
        await new Promise(resolve => setTimeout(resolve, 100))
        
        // Trigger the test
        const currentWorkflowText = generateWorkflowTextFromRefs()
        if (!currentWorkflowText) {
          console.error('[Voice Live] No workflow to test')
          return ''
        }
        
        // Read conversation ID from URL RIGHT NOW (not from cached state)
        const currentUrl = new URL(window.location.href)
        const freshConversationId = currentUrl.searchParams.get('conversationId')
        const newConversationId = freshConversationId || activeConversationId || `workflow-${Date.now()}`
        setWorkflowConversationId(newConversationId)
        console.log("[Voice Live] Using conversation ID:", newConversationId, freshConversationId ? "(from URL)" : activeConversationId ? "(from prop)" : "(new)")
        
        setIsTesting(true)
        setTestMessages([{ role: "user", content: message }])
        setStepStatuses(new Map())
        stepStatusesRef.current = new Map()
        agentStepIndexRef.current = new Map()  // Reset agent step counters
        setHostTokenUsage(null)  // Reset host tokens for new workflow
        
        const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
        
        const parts: any[] = [
          {
            root: {
              kind: 'text',
              text: message
            }
          }
        ]
        
        const response = await fetch(`${baseUrl}/message/send`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            params: {
              messageId,
              contextId: createContextId(newConversationId),  // Use tenant-aware contextId
              parts: parts,
              role: 'user',
              agentMode: true,
              enableInterAgentMemory: true,
              workflow: currentWorkflowText
            }
          })
        })
        
        if (!response.ok) {
          console.error('[Voice Live] Failed to send message:', response.statusText)
          throw new Error(`Failed to send message: ${response.statusText}`)
        }
        
        console.log('[Voice Live] Message sent successfully')
        
        // NOTE: URL update moved to when test completes to prevent chat panel from
        // reloading messages during the workflow test
        
        // Set timeout
        if (testTimeoutRef.current) {
          clearTimeout(testTimeoutRef.current)
        }
        testTimeoutRef.current = setTimeout(() => {
          console.log('[WorkflowTest] Test timeout reached (10 minutes), stopping...')
          setIsTesting(false)
        }, 600000)
        
        return newConversationId
      } catch (error) {
        console.error('[Voice Live] Error sending to A2A:', error)
        throw error
      }
    }
  })
  
  // Agent dragging
  const [draggingStepId, setDraggingStepId] = useState<string | null>(null)
  const draggingStepIdRef = useRef<string | null>(null)
  const dragOffsetRef = useRef({ x: 0, y: 0 })

  // Keep callback ref in sync
  const onWorkflowGeneratedRef = useRef(onWorkflowGenerated)
  useEffect(() => {
    onWorkflowGeneratedRef.current = onWorkflowGenerated
  }, [onWorkflowGenerated])

  // Keep refs in sync with state
  useEffect(() => {
    workflowStepsRef.current = workflowSteps
  }, [workflowSteps])
  
  useEffect(() => {
    connectionsRef.current = connections
  }, [connections])
  
  useEffect(() => {
    isCreatingConnectionRef.current = isCreatingConnection
  }, [isCreatingConnection])
  
  useEffect(() => {
    connectionStartRef.current = connectionStart
  }, [connectionStart])
  
  useEffect(() => {
    selectedStepIdRef.current = selectedStepId
  }, [selectedStepId])
  
  // Sync stepStatuses to ref for synchronous access in event handlers
  useEffect(() => {
    stepStatusesRef.current = stepStatuses
  }, [stepStatuses])
  
  // Auto-stop workflow when all steps are completed
  useEffect(() => {
    if (!isTesting || workflowSteps.length === 0) return
    
    // Check if all workflow steps are completed
    const allStepsCompleted = workflowSteps.every(step => {
      const status = stepStatuses.get(step.id)
      return status?.status === "completed"
    })
    
    if (allStepsCompleted) {
      console.log("[WorkflowTest] 🎉 All steps completed!")
      
      // NOTE: Don't update URL here - the chat panel is already showing everything live
      // URL updates cause the chat panel to reload, which creates a jarring "refresh" effect
      // The conversation is already saved on the backend and the chat panel has the live data
      
      // Mark workflow as no longer testing, but KEEP the visual data (statuses, messages, tokens, duration)
      // so the user can see the completed workflow results. Data is only cleared when starting a new test.
      const timeoutId = setTimeout(() => {
        console.log("[WorkflowTest] ✅ Workflow complete - keeping visual data for review")
        setIsTesting(false)
        // Don't clear stepStatuses, hostMessages, etc. - keep them visible!
        // They will be cleared when the user starts a new test
      }, 2000)
      
      return () => clearTimeout(timeoutId)
    }
  }, [stepStatuses, workflowSteps, isTesting])
  
  // Sync workflowOrderMap to ref for synchronous access in event handlers
  useEffect(() => {
    workflowOrderMapRef.current = workflowOrderMap
  }, [workflowOrderMap])
  
  // Keep workflow steps map in sync for fast lookup during testing
  useEffect(() => {
    const newMap = new Map<string, WorkflowStep>()
    workflowSteps.forEach(step => {
      newMap.set(step.agentName, step)
      newMap.set(step.agentId, step)
    })
    workflowStepsMapRef.current = newMap
  }, [workflowSteps])

  // Save positions and connections to localStorage (but not during initial load)
  useEffect(() => {
    // Don't save during initial load from localStorage
    if (!hasInitializedRef.current) {
      return
    }
    
    if (workflowSteps.length > 0) {
      const data = {
        positions: workflowSteps.map(step => ({
          id: step.id,
          agentId: step.agentId,
          agentName: step.agentName,
          agentColor: step.agentColor,
          x: step.x,
          y: step.y,
          order: step.order,
          description: step.description
        })),
        connections: connections.map(conn => ({
          id: conn.id,
          fromStepId: conn.fromStepId,
          toStepId: conn.toStepId
        }))
      }
      localStorage.setItem('workflow-visual-data', JSON.stringify(data))
    }
  }, [workflowSteps, connections])

  // Assign colors to agents
  const getAgentColor = (index: number): string => {
    return AGENT_COLORS[index % AGENT_COLORS.length]
  }

  // Load from localStorage ONCE on mount only
  useEffect(() => {
    if (hasInitializedRef.current) {
      return
    }
    
    hasInitializedRef.current = true
    
    // Only load from localStorage, never parse from text
    try {
      const saved = localStorage.getItem('workflow-visual-data')
      if (saved) {
        const data = JSON.parse(saved)
        const savedPositions = data.positions || []
        const savedConnections = data.connections || []
        
        if (savedPositions.length > 0) {
          // Restore with saved IDs to maintain connections
          const steps: WorkflowStep[] = savedPositions.map((pos: any) => {
            // Find the agent in registeredAgents to get the correct color
            // Always look up the color to ensure consistency, even if saved color exists
            const agentIndex = registeredAgents.findIndex(a => 
              (a.id || a.name.toLowerCase().replace(/\s+/g, '-')) === pos.agentId ||
              a.name === pos.agentName
            )
            
            return {
              id: pos.id,
              agentId: pos.agentId,
              agentName: pos.agentName,
              agentColor: agentIndex >= 0 ? getAgentColor(agentIndex) : (pos.agentColor || getAgentColor(pos.order)),
              description: pos.description,
              x: pos.x,
              y: pos.y,
              order: pos.order
            }
          })
          
          setWorkflowSteps(steps)
          
          // Restore connections with saved IDs
          if (savedConnections.length > 0) {
            const restoredConnections: Connection[] = savedConnections.map((conn: any) => ({
              id: conn.id,
              fromStepId: conn.fromStepId,
              toStepId: conn.toStepId
            }))
            
            setConnections(restoredConnections)
          }
          
          // Mark as initialized AFTER state updates
          setTimeout(() => {
            hasInitializedRef.current = true
          }, 0)
        } else {
          // No saved data - mark as initialized so new changes can be saved
          hasInitializedRef.current = true
        }
      } else {
        // No saved data - mark as initialized so new changes can be saved
        hasInitializedRef.current = true
      }
    } catch (e) {
      console.error('Failed to load saved data:', e)
      hasInitializedRef.current = true
    }
  }, [])

  // Update workflow text whenever steps or connections change
  // NEW: Detects parallel branches (fan-out) and generates sub-lettered steps (2a, 2b, etc.)
  useEffect(() => {
    if (workflowSteps.length === 0) {
      setGeneratedWorkflowText("")
      setWorkflowOrderMap(new Map())
      onWorkflowGeneratedRef.current("")
      return
    }
    
    // If connections exist, use them to determine order and detect parallel branches
    if (connections.length > 0) {
      // Build adjacency maps
      const outgoing = new Map<string, string[]>()
      const incoming = new Map<string, string[]>()
      
      connections.forEach(conn => {
        if (!outgoing.has(conn.fromStepId)) outgoing.set(conn.fromStepId, [])
        outgoing.get(conn.fromStepId)!.push(conn.toStepId)
        
        if (!incoming.has(conn.toStepId)) incoming.set(conn.toStepId, [])
        incoming.get(conn.toStepId)!.push(conn.fromStepId)
      })
      
      const connectedStepIds = new Set<string>()
      connections.forEach(conn => {
        connectedStepIds.add(conn.fromStepId)
        connectedStepIds.add(conn.toStepId)
      })
      
      // Find root nodes (no incoming connections)
      const hasIncoming = new Set(connections.map(c => c.toStepId))
      const rootNodes = workflowSteps.filter(step => 
        connectedStepIds.has(step.id) && !hasIncoming.has(step.id)
      )
      
      // BFS to generate workflow with parallel detection
      interface WorkflowEntry {
        stepNumber: number
        subLetter?: string  // 'a', 'b', 'c' for parallel steps
        step: WorkflowStep
      }
      
      const entries: WorkflowEntry[] = []
      const visited = new Set<string>()
      let currentStepNumber = 0
      
      // Queue for BFS: [stepId, parentStepNumber, isPartOfParallelGroup, subLetterIndex]
      type QueueItem = { stepId: string, parentNumber: number, parallelSiblings: string[], siblingIndex: number }
      const queue: QueueItem[] = []
      
      // Start with root nodes
      if (rootNodes.length > 1) {
        // Multiple roots = parallel from the start
        rootNodes.forEach((node, idx) => {
          queue.push({ stepId: node.id, parentNumber: 0, parallelSiblings: rootNodes.map(n => n.id), siblingIndex: idx })
        })
      } else {
        rootNodes.forEach(node => {
          queue.push({ stepId: node.id, parentNumber: 0, parallelSiblings: [], siblingIndex: 0 })
        })
      }
      
      while (queue.length > 0) {
        const { stepId, parentNumber, parallelSiblings, siblingIndex } = queue.shift()!
        
        if (visited.has(stepId)) continue
        visited.add(stepId)
        
        const step = workflowSteps.find(s => s.id === stepId)
        if (!step) continue
        
        // Determine step number and sub-letter
        let stepNumber: number
        let subLetter: string | undefined
        
        if (parallelSiblings.length > 1) {
          // This step is part of a parallel group - use parent's next number with sub-letter
          stepNumber = parentNumber + 1
          subLetter = String.fromCharCode(97 + siblingIndex) // 'a', 'b', 'c', ...
        } else {
          // Sequential step
          currentStepNumber++
          stepNumber = currentStepNumber
        }
        
        entries.push({ stepNumber, subLetter, step })
        
        // Add children to queue
        const children = outgoing.get(stepId) || []
        if (children.length > 1) {
          // Fan-out: parallel children
          children.forEach((childId, idx) => {
            queue.push({ stepId: childId, parentNumber: stepNumber, parallelSiblings: children, siblingIndex: idx })
          })
        } else if (children.length === 1) {
          // Sequential child
          queue.push({ stepId: children[0], parentNumber: stepNumber, parallelSiblings: [], siblingIndex: 0 })
        }
        
        // Update currentStepNumber for next sequential step
        if (parallelSiblings.length <= 1) {
          // Only increment if this wasn't a parallel step
        } else if (siblingIndex === parallelSiblings.length - 1) {
          // Last parallel sibling - increment for next sequential
          currentStepNumber = stepNumber
        }
      }
      
      // Sort entries and generate text
      entries.sort((a, b) => {
        if (a.stepNumber !== b.stepNumber) return a.stepNumber - b.stepNumber
        // Same number = parallel, sort by sub-letter
        return (a.subLetter || '').localeCompare(b.subLetter || '')
      })
      
      const workflowText = entries.map(entry => {
        const label = entry.subLetter ? `${entry.stepNumber}${entry.subLetter}` : `${entry.stepNumber}`
        const desc = entry.step.description || `Use the ${entry.step.agentName} agent`
        // Include agent name so orchestrator knows which agent to route to
        return `${label}. [${entry.step.agentName}] ${desc}`
      }).join('\n')
      
      const orderMap = new Map<string, number>()
      entries.forEach((entry, index) => {
        orderMap.set(entry.step.id, index + 1)
      })
      
      setWorkflowOrderMap(orderMap)
      setGeneratedWorkflowText(workflowText)
      onWorkflowGeneratedRef.current(workflowText)
    } else {
      // No connections - use visual order (all sequential)
      const sortedSteps = [...workflowSteps].sort((a, b) => a.order - b.order)
      const workflowText = sortedSteps.map((step, index) => 
        // Include agent name so orchestrator knows which agent to route to
        `${index + 1}. [${step.agentName}] ${step.description || `Use the ${step.agentName} agent`}`
      ).join('\n')
      
      const orderMap = new Map<string, number>()
      sortedSteps.forEach((step, index) => {
        orderMap.set(step.id, index + 1)
      })
      
      setWorkflowOrderMap(orderMap)
      setGeneratedWorkflowText(workflowText)
      onWorkflowGeneratedRef.current(workflowText)
    }
  }, [workflowSteps, connections])
  
  // Subscribe to event hub for live workflow testing
  // CLEAN IMPLEMENTATION: Simple, direct event handling
  useEffect(() => {
    
    // SIMPLE: Find the correct step for this agent
    // Track the CURRENT ACTIVE step per agent
    // Optional: pass isNewTaskStart=true when this is a "working"/"submitted" event to trigger advance
    const findStepForAgent = (agentName: string, isNewTaskStart: boolean = false): string | null => {
      if (!agentName) return null
      
      const steps = Array.from(workflowStepsRef.current).sort((a, b) => a.order - b.order)
      const matchingSteps = steps.filter(s => s.agentName === agentName || s.agentId === agentName)
      
      if (matchingSteps.length === 0) return null
      
      // Check if we have an active step for this agent
      const activeStepId = agentStepIndexRef.current.get(agentName)
      
      if (activeStepId) {
        const activeIndex = matchingSteps.findIndex(s => s.id === activeStepId)
        if (activeIndex >= 0) {
          const activeStatus = stepStatusesRef.current.get(activeStepId)
          
          // ONLY advance when a new task is starting (working/submitted status event)
          // AND the current step is completed.
          // This prevents late messages from step 1 being routed to step 4.
          // Messages always go to the current active step (even if completed).
          if (isNewTaskStart && activeStatus?.status === "completed" && activeIndex < matchingSteps.length - 1) {
            const nextStepId = matchingSteps[activeIndex + 1].id
            agentStepIndexRef.current.set(agentName, nextStepId)
            return nextStepId
          }
          
          // Otherwise return the current active step
          return activeStepId
        }
      }
      
      // No active step yet - set and return the first matching step
      const firstStepId = matchingSteps[0].id
      agentStepIndexRef.current.set(agentName, firstStepId)
      return firstStepId
    }

    // Helper to update step status and add a new message bubble
    const updateStep = (
      stepId: string, 
      status: string, 
      newMessage?: string, 
      imageUrl?: string, 
      fileName?: string,
      tokenUsage?: { prompt_tokens: number, completion_tokens: number, total_tokens: number }
    ) => {
      const current = stepStatusesRef.current.get(stepId)
      const messages = current?.messages || []
      
      // Add new message to the array if provided (with deduplication)
      if (newMessage || imageUrl) {
        // Check for duplicate: same message text within the last few messages (within 2 seconds)
        const messagePrefix = (newMessage || '').slice(0, 100)
        const isDuplicate = messages.slice(-5).some(m => 
          (m.text || '').slice(0, 100) === messagePrefix && 
          Date.now() - (m.timestamp || 0) < 2000
        )
        
        if (!isDuplicate) {
          messages.push({
            text: newMessage,
            imageUrl,
            fileName,
            timestamp: Date.now()
          })
        }
      }
      
      // Track start time when agent starts working
      const startTime = status === "working" && !current?.startTime 
        ? Date.now() 
        : current?.startTime
      
      // Calculate duration when agent completes
      const duration = status === "completed" && startTime
        ? (Date.now() - startTime) / 1000
        : current?.duration
      
      // Keep messages expanded initially when completing - will collapse after delay
      const isNewlyCompleted = status === "completed" && current?.status !== "completed"
      
      const newEntry = { 
        status, 
        messages,
        completedAt: status === "completed" ? Date.now() : current?.completedAt,
        startTime,
        messagesCollapsed: current?.messagesCollapsed || false, // Don't immediately collapse
        duration,
        tokenUsage: tokenUsage || current?.tokenUsage  // Preserve or update token usage
      }
      stepStatusesRef.current.set(stepId, newEntry)
      setStepStatuses(prev => {
        const newMap = new Map(prev)
        newMap.set(stepId, newEntry)
        return newMap
      })
      
      // Auto-collapse messages 2 seconds after agent completes (so user can see output)
      if (isNewlyCompleted && messages.length > 0) {
        setTimeout(() => {
          const currentEntry = stepStatusesRef.current.get(stepId)
          if (currentEntry) {
            const collapsedEntry = { ...currentEntry, messagesCollapsed: true }
            stepStatusesRef.current.set(stepId, collapsedEntry)
            setStepStatuses(prev => {
              const newMap = new Map(prev)
              newMap.set(stepId, collapsedEntry)
              return newMap
            })
          }
        }, 2000)
      }
    }
    
    // Handle status updates (agent: field instead of agentName)
    const handleStatusUpdate = (data: any) => {
      const agentName = data.agent || data.agentName
      const status = data.status
      if (!agentName || !status) return
      
      const stepId = findStepForAgent(agentName)
      if (!stepId) return
      
      // Only update message if it's meaningful content (not orchestration noise)
      if (status.length > 30 && !status.includes("Planning") && !status.includes("Initializing")) {
        const current = stepStatusesRef.current.get(stepId)
        updateStep(stepId, current?.status || "working", status)
        
        // Add to sidebar
        const agentStep = workflowStepsRef.current.find(s => s.id === stepId)
        const agentColor = agentStep?.agentColor || "#6366f1"
        setHostMessages(prev => [...prev, {
          message: status,
          target: agentName,
          timestamp: Date.now(),
          agentColor: agentColor,
          isHost: false
        }])
      }
    }
    
    // Main handler: task_updated events contain state changes
    const handleTaskUpdate = (data: any) => {
      const { state, agentName, content, message, tokenUsage } = data
      if (!agentName) return
      
      // Map state to status
      const newStatus = state === "completed" ? "completed" : 
                       state === "failed" ? "failed" : 
                       (state === "input_required" || state === "input-required") ? "waiting" :
                       "working"
      
      // When a new task starts (working/submitted), check if we should advance to next step
      const isNewTaskStart = (state === "working" || state === "submitted")
      const stepId = findStepForAgent(agentName, isNewTaskStart)
      if (!stepId) return
      
      // IMPORTANT: Don't let late "working" events revert a "completed" status
      const currentStatus = stepStatusesRef.current.get(stepId)?.status
      if (currentStatus === "completed" && newStatus === "working") {
        return
      }
      
      
      const messageContent = content || message
      if (messageContent) {
        updateStep(stepId, newStatus, messageContent, undefined, undefined, tokenUsage)
      } else {
        // Just update status if no message, but include tokenUsage if available
        updateStep(stepId, newStatus, undefined, undefined, undefined, tokenUsage)
      }
      
      // Handle waiting state
      if (newStatus === "waiting") {
        setWaitingStepId(stepId)
        if (messageContent) setWaitingMessage(messageContent)
      } else if (newStatus === "completed") {
        setWaitingStepId(prev => prev === stepId ? null : prev)
        // DON'T advance here - late messages still need to go to this step
        // The advance happens in findStepForAgent when the NEXT step starts
      }
    }
    
    // Agent messages
    const handleAgentMessage = (data: any) => {
      const { agentName, content } = data
      if (!agentName || !content) return
      
      const stepId = findStepForAgent(agentName)
      if (!stepId) return
      
      const current = stepStatusesRef.current.get(stepId)
      updateStep(stepId, current?.status || "working", content)
      
      // Add to sidebar
      const agentStep = workflowStepsRef.current.find(s => s.id === stepId)
      const agentColor = agentStep?.agentColor || "#6366f1"
      setHostMessages(prev => [...prev, {
        message: content,
        target: agentName,
        timestamp: Date.now(),
        agentColor: agentColor,
        isHost: false
      }])
      
      if (waitingStepIdRef.current === stepId) {
        setWaitingMessage(content)
      }
    }
    
    // Tool calls - show activity
    const handleToolCall = (data: any) => {
      const { agentName, toolName } = data
      if (!agentName || !toolName) return
      
      const stepId = findStepForAgent(agentName)
      if (!stepId) return
      
      const current = stepStatusesRef.current.get(stepId)
      if (current?.status !== "completed" && current?.status !== "waiting") {
        const toolMessage = `🛠️ ${toolName}`
        updateStep(stepId, "working", toolMessage)
        
        // Add to sidebar
        const agentStep = workflowStepsRef.current.find(s => s.id === stepId)
        const agentColor = agentStep?.agentColor || "#6366f1"
        setHostMessages(prev => [...prev, {
          message: toolMessage,
          target: agentName,
          timestamp: Date.now(),
          agentColor: agentColor,
          isHost: false
        }])
      }
    }
    
    const handleToolResponse = (data: any) => {
      const { agentName, toolName, status } = data
      if (!agentName || !toolName) return
      
      const stepId = findStepForAgent(agentName)
      if (!stepId) return
      
      const current = stepStatusesRef.current.get(stepId)
      if (current?.status !== "completed" && current?.status !== "waiting") {
        const msg = status === "success" ? `✅ ${toolName}` : `❌ ${toolName}`
        updateStep(stepId, "working", msg)
      }
    }
    
    // Agent activity - update message while preserving status
    const handleAgentActivity = (data: any) => {
      const { agentName, activity } = data
      if (!agentName || !activity) return
      
      const stepId = findStepForAgent(agentName)
      if (!stepId) return
      
      // Add to sidebar
      const agentStep = workflowStepsRef.current.find(s => s.id === stepId)
      const agentColor = agentStep?.agentColor || "#6366f1"
      setHostMessages(prev => [...prev, {
        message: activity,
        target: agentName,
        timestamp: Date.now(),
        agentColor: agentColor,
        isHost: false
      }])
      
      const current = stepStatusesRef.current.get(stepId)
      // IMPORTANT: Preserve completed/waiting/failed status - don't let late messages revert them
      const preservedStatus = (current?.status === "completed" || current?.status === "waiting" || current?.status === "failed") 
        ? current.status : "working"
      updateStep(stepId, preservedStatus, activity)
    }
    
    // Message events - extract content and update step (matches main chat behavior)
    const handleMessage = (data: any) => {
      const agentName = data.agentName || data.agent || data.from
      if (!agentName) return
      
      // Extract message text and images from content array
      let messageText = ""
      let hasImages = false
      
      if (data.content && Array.isArray(data.content)) {
        const textItem = data.content.find((c: any) => c.type === "text")
        messageText = textItem?.content || textItem?.text || ""
        
        // Extract images (will handle later if we have a stepId)
        const imageContents = data.content.filter((c: any) => c.type === "image")
        if (imageContents.length > 0) {
          hasImages = true
        }
      } else if (typeof data.message === "string") {
        messageText = data.message
      } else if (typeof data.content === "string") {
        messageText = data.content
      }
      
      console.log(`[VD handleMessage] agentName="${agentName}", messageText="${messageText?.substring(0, 50)}..."`)
      
      // Check if this is a foundry-host-agent orchestration message
      if (agentName.toLowerCase().includes('host') || agentName.toLowerCase().includes('foundry-host-agent')) {
        console.log(`[VD] 📤 HOST MESSAGE: "${messageText?.substring(0, 100)}"`)
        // Display in sidebar
        if (messageText) {
          setHostMessages(prev => {
            const newMessages = [...prev, {
              message: messageText,
              target: "Orchestrator",
              timestamp: Date.now(),
              agentColor: "#6366f1",
              isHost: true
            }]
            console.log(`[VD] Host messages count: ${newMessages.length}`)
            return newMessages
          })
        }
        return
      }
      
      // For remote agents, find the corresponding workflow step
      const stepId = findStepForAgent(agentName)
      if (!stepId) return
      
      const current = stepStatusesRef.current.get(stepId)
      const currentStatus = current?.status || "working"
      
      // Get agent color from workflow steps
      const agentStep = workflowStepsRef.current.find(s => s.id === stepId)
      const agentColor = agentStep?.agentColor || "#6366f1"
      
      // Handle images if we found a step
      if (hasImages && data.content && Array.isArray(data.content)) {
        const imageContents = data.content.filter((c: any) => c.type === "image")
        imageContents.forEach((img: any) => {
          updateStep(stepId, currentStatus, undefined, img.uri, img.fileName || "image")
        })
      }
      
      // Add text message as a separate bubble
      if (messageText) {
        updateStep(stepId, currentStatus, messageText)
        
        // Also add to orchestration sidebar
        setHostMessages(prev => [...prev, {
          message: messageText,
          target: agentName,
          timestamp: Date.now(),
          agentColor: agentColor,
          isHost: false
        }])
        
        if (waitingStepIdRef.current === stepId) {
          setWaitingMessage(messageText)
        }
        
        setTestMessages(prev => [...prev, { role: "assistant", content: messageText, agent: agentName }])
      }
    }
    
    // Remote agent activity - update step with content OR show host messages
    const handleRemoteAgentActivity = (data: any) => {
      const { agentName, content } = data
      if (!agentName || !content) return
      
      console.log(`[VD handleRemoteAgentActivity] agentName="${agentName}", content="${content?.substring(0, 50)}..."`)
      
      // Check if this is a foundry-host-agent orchestration message
      if (agentName.toLowerCase().includes('host') || agentName.toLowerCase().includes('foundry-host-agent')) {
        console.log(`[VD] 📤 HOST ACTIVITY: "${content?.substring(0, 100)}"`)
        // Display in sidebar
        setHostMessages(prev => {
          const newMessages = [...prev, {
            message: content,
            target: "Orchestrator",
            timestamp: Date.now(),
            agentColor: "#6366f1",
            isHost: true
          }]
          console.log(`[VD] Host messages count: ${newMessages.length}`)
          return newMessages
        })
        return
      }
      
      const stepId = findStepForAgent(agentName)
      if (!stepId) return
      
      const current = stepStatusesRef.current.get(stepId)
      // IMPORTANT: Preserve completed/waiting status - don't let late messages revert them
      const preservedStatus = (current?.status === "completed" || current?.status === "waiting" || current?.status === "failed") 
        ? current.status : "working"
      updateStep(stepId, preservedStatus, content)
      
      // Get agent color and add to sidebar
      const agentStep = workflowStepsRef.current.find(s => s.id === stepId)
      const agentColor = agentStep?.agentColor || "#6366f1"
      
      setHostMessages(prev => [...prev, {
        message: content,
        target: agentName,
        timestamp: Date.now(),
        agentColor: agentColor,
        isHost: false
      }])
      
      if (waitingStepIdRef.current === stepId) {
        setWaitingMessage(content)
      }
    }
    
    // Final response - mark step as completed with full content
    const handleFinalResponse = (data: any) => {
      if (!data.message?.agent || !data.message?.content) return
      
      const agentName = data.message.agent
      const content = data.message.content
      
      const stepId = findStepForAgent(agentName)
      if (!stepId) return
      
      const current = stepStatusesRef.current.get(stepId)
      
      // If waiting for input, just update message but keep waiting
      if (current?.status === "waiting") {
        updateStep(stepId, "waiting", content)
        setWaitingMessage(content)
        return
      }
      
      // Mark as completed
      updateStep(stepId, "completed", content)
      setTestMessages(prev => [...prev, { role: "assistant", content, agent: agentName }])
      
      // Check if this is the last step - auto-stop workflow
      const stepOrder = workflowOrderMapRef.current.get(stepId)
      const maxOrder = Math.max(...Array.from(workflowOrderMapRef.current.values()))
      if (stepOrder === maxOrder) {
        setTimeout(() => handleStopTest(), 2000)
      }
      
      // Voice Live integration
      if (voiceLive.isConnected && voiceLiveCallMapRef.current.size > 0) {
        const entries = Array.from(voiceLiveCallMapRef.current.entries())
        if (entries.length > 0) {
          const [messageId, callId] = entries[0]
          voiceLive.injectNetworkResponse({ call_id: callId, message: content, status: 'completed' })
          voiceLiveCallMapRef.current.delete(messageId)
        }
      }
    }
    
    // File uploaded - attach to step
    const handleFileUploaded = (data: any) => {
      if (!data.fileInfo?.source_agent || !data.fileInfo?.uri) return
      
      const agentName = data.fileInfo.source_agent
      const stepId = findStepForAgent(agentName)
      if (!stepId) return
      
      const isImage = data.fileInfo.content_type?.startsWith("image/")
      const current = stepStatusesRef.current.get(stepId)
      
      // Add image/file as a new message bubble
      if (isImage) {
        updateStep(stepId, current?.status || "working", undefined, data.fileInfo.uri, data.fileInfo.filename)
      }
    }
    
    // Inference step - update status message
    const handleInferenceStep = (data: any) => {
      if (!data.agent || !data.status) return
      
      const stepId = findStepForAgent(data.agent)
      if (!stepId) return
      
      const current = stepStatusesRef.current.get(stepId)
      if (current?.status !== "completed") {
        updateStep(stepId, "working", data.status)
      }
    }
    
    // Outgoing message - show host agent activity
    const handleOutgoingMessage = (data: any) => {
      if (data.targetAgent && data.message) {
        
        // Add to host messages stack
        setHostMessages(prev => [...prev, {
          message: data.message,
          target: data.targetAgent,
          timestamp: Date.now()
        }])
        
        // Voice Live integration
        if (voiceLive.isConnected && voiceLiveCallMapRef.current.size > 0) {
          const entries = Array.from(voiceLiveCallMapRef.current.entries())
          if (entries.length > 0) {
            const [, callId] = entries[0]
            voiceLive.injectNetworkResponse({ call_id: callId, message: data.message, status: 'in_progress' })
          }
        }
      }
    }
    
    // Host agent token usage
    const handleHostTokenUsage = (data: any) => {
      if (data.tokenUsage) {
        console.log("[VD] Host token usage received:", data.tokenUsage)
        setHostTokenUsage(data.tokenUsage)
      }
    }
    
    // Subscribe to events
    subscribe("status_update", handleStatusUpdate)
    subscribe("task_updated", handleTaskUpdate)
    subscribe("agent_message", handleAgentMessage)
    subscribe("message", handleMessage)
    subscribe("final_response", handleFinalResponse)
    subscribe("tool_call", handleToolCall)
    subscribe("tool_response", handleToolResponse)
    subscribe("agent_activity", handleAgentActivity)
    subscribe("remote_agent_activity", handleRemoteAgentActivity)
    subscribe("inference_step", handleInferenceStep)
    subscribe("file_uploaded", handleFileUploaded)
    subscribe("outgoing_agent_message", handleOutgoingMessage)
    subscribe("host_token_usage", handleHostTokenUsage)
    
    return () => {
      unsubscribe("status_update", handleStatusUpdate)
      unsubscribe("task_updated", handleTaskUpdate)
      unsubscribe("agent_message", handleAgentMessage)
      unsubscribe("message", handleMessage)
      unsubscribe("final_response", handleFinalResponse)
      unsubscribe("tool_call", handleToolCall)
      unsubscribe("tool_response", handleToolResponse)
      unsubscribe("agent_activity", handleAgentActivity)
      unsubscribe("remote_agent_activity", handleRemoteAgentActivity)
      unsubscribe("inference_step", handleInferenceStep)
      unsubscribe("file_uploaded", handleFileUploaded)
      unsubscribe("outgoing_agent_message", handleOutgoingMessage)
      unsubscribe("host_token_usage", handleHostTokenUsage)
    }
    // FIXED: Subscribe on mount, not when isTesting changes
    // This ensures we don't miss events due to race condition between setIsTesting and event arrival
    // Handlers check isTesting internally if needed
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Handle canvas drop
  const handleCanvasDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDraggingOver(false)
    
    if (!draggedAgent || !canvasRef.current) return
    
    const canvas = canvasRef.current
    const rect = canvas.getBoundingClientRect()
    
    // Calculate position accounting for zoom and pan
    const centerX = rect.width / 2
    const centerY = rect.height / 2
    const mouseX = e.clientX - rect.left
    const mouseY = e.clientY - rect.top
    
    // Convert screen coordinates to canvas coordinates
    const x = (mouseX - centerX - panOffsetRef.current.x) / zoomRef.current
    const y = (mouseY - centerY - panOffsetRef.current.y) / zoomRef.current
    const order = workflowSteps.length
    
    
    const agentId = draggedAgent.id || draggedAgent.name.toLowerCase().replace(/\s+/g, '-')
    const agentIndex = registeredAgents.findIndex(a => (a.id || a.name) === (draggedAgent.id || draggedAgent.name))
    
    const newStep: WorkflowStep = {
      id: `step-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      agentId: agentId,
      agentName: draggedAgent.name,
      agentColor: getAgentColor(agentIndex),
      description: `Use the ${draggedAgent.name} agent`,
      x,
      y,
      order
    }
    
    setWorkflowSteps(prev => [...prev, newStep])
    setSelectedStepId(newStep.id)
    setEditingDescription(newStep.description)
    setDraggedAgent(null)
  }

  // Delete selected step
  const deleteSelectedStep = () => {
    if (!selectedStepId) return
    setWorkflowSteps(prev => {
      const filtered = prev.filter(s => s.id !== selectedStepId)
      // Reorder remaining steps
      return filtered.map((step, index) => ({ ...step, order: index }))
    })
    setSelectedStepId(null)
  }

  // Update step description
  const updateStepDescription = (description: string, stepId?: string) => {
    const targetStepId = stepId || selectedStepId
    if (!targetStepId) return
    setWorkflowSteps(prev => 
      prev.map(step => 
        step.id === targetStepId ? { ...step, description } : step
      )
    )
    setEditingDescription(description)
  }

  // Reorder step
  const moveStepOrder = (stepId: string, direction: 'up' | 'down') => {
    setWorkflowSteps(prev => {
      const sorted = [...prev].sort((a, b) => a.order - b.order)
      const index = sorted.findIndex(s => s.id === stepId)
      
      if (index === -1) return prev
      if (direction === 'up' && index === 0) return prev
      if (direction === 'down' && index === sorted.length - 1) return prev
      
      const newIndex = direction === 'up' ? index - 1 : index + 1
      const temp = sorted[index]
      sorted[index] = sorted[newIndex]
      sorted[newIndex] = temp
      
      // Update order numbers
      return sorted.map((step, i) => ({ ...step, order: i }))
    })
  }

  // Clear all steps
  const clearWorkflow = () => {
    setWorkflowSteps([])
    setConnections([])
    setSelectedStepId(null)
    setSelectedWorkflowId(null) // Clear selected workflow highlight
    // Clear saved data from localStorage
    localStorage.removeItem('workflow-visual-data')
  }
  
  // Handle test workflow submission
  const handleTestSubmit = async () => {
    if (!testInput.trim()) return
    
    // Generate workflow text from current refs to ensure we have the latest
    const currentWorkflowText = generateWorkflowTextFromRefs()
    
    if (!currentWorkflowText) {
      alert("Please add agents to your workflow before testing")
      return
    }
    
    // Read conversation ID from URL RIGHT NOW (not from cached state)
    // This ensures we get the latest value the chat panel has set
    const currentUrl = new URL(window.location.href)
    const freshConversationId = currentUrl.searchParams.get('conversationId')
    const newConversationId = freshConversationId || activeConversationId || `conv-${Date.now()}`
    setWorkflowConversationId(newConversationId)
    console.log("[WorkflowTest] Using conversation ID:", newConversationId, freshConversationId ? "(from URL)" : activeConversationId ? "(from prop)" : "(new)")
    
    setIsTesting(true)
    setTestMessages([{ role: "user", content: testInput }])
    setStepStatuses(new Map())
    stepStatusesRef.current = new Map()
    agentStepIndexRef.current = new Map()  // Reset agent step counters
    setHostTokenUsage(null)  // Reset host tokens for new workflow
    
    console.log("[WorkflowTest] 🚀 Starting test with workflow:", currentWorkflowText)
    
    try {
      const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
      const messageId = `test_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
      
      // Build message parts in proper A2A format
      const parts: any[] = [
        {
          root: {
            kind: 'text',
            text: testInput
          }
        }
      ]
      
      console.log('[WorkflowTest] Sending message:', {
        messageId,
        contextId: createContextId(newConversationId),
        workflow: currentWorkflowText.substring(0, 100) + '...',
        partsCount: parts.length
      })
      
      const response = await fetch(`${baseUrl}/message/send`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          params: {
            messageId,
            contextId: createContextId(newConversationId),  // Use tenant-aware contextId
            parts: parts,
            role: 'user',
            agentMode: true,
            enableInterAgentMemory: true,
            workflow: currentWorkflowText
          }
        })
      })
      
      console.log('[WorkflowTest] Response status:', response.status)
      
      if (!response.ok) {
        const errorText = await response.text()
        console.error('[WorkflowTest] Failed to send message:', response.statusText, errorText)
        alert(`Failed to send message: ${response.statusText}\n${errorText}`)
        setIsTesting(false)
        return
      }
      
      // Successfully sent - response will come through WebSocket events
      console.log('[WorkflowTest] Message sent successfully, waiting for events...')
      
      // Emit message_sent event so chat panel can show the user message
      emit("message_sent", {
        role: "user",
        content: testInput,
        conversationId: newConversationId,
        contextId: createContextId(newConversationId),  // Use tenant-aware contextId
        timestamp: new Date().toISOString()
      })
      
      // NOTE: URL update moved to handleFinalResponse to prevent chat panel from
      // clearing messages during the workflow (the URL change triggers a reload)
      
      // Set a timeout to automatically stop testing after 60 seconds
      if (testTimeoutRef.current) {
        clearTimeout(testTimeoutRef.current)
      }
      testTimeoutRef.current = setTimeout(() => {
        console.log('[WorkflowTest] Test timeout reached (10 minutes), stopping...')
        setIsTesting(false)
      }, 600000) // 600 seconds (10 minutes) - allows for multi-step workflows with retries and fallbacks
      
    } catch (error) {
      console.error('[WorkflowTest] Error sending message:', error)
      alert(`Error sending message: ${error instanceof Error ? error.message : String(error)}`)
      setIsTesting(false)
    }
    
    setTestInput("")
  }
  
  // Stop testing
  const handleStopTest = () => {
    if (testTimeoutRef.current) {
      clearTimeout(testTimeoutRef.current)
      testTimeoutRef.current = null
    }
    setIsTesting(false)
    setTestMessages([])
    setStepStatuses(new Map())
    stepStatusesRef.current = new Map()
    agentStepIndexRef.current = new Map()  // Reset agent step counters
    setHostMessages([])
    setWaitingStepId(null)
    setWaitingResponse("")
    setWaitingMessage(null)
  }
  
  // Handle response submission when an agent is waiting for input
  const handleWaitingResponse = async () => {
    if (!waitingResponse.trim() || !waitingStepId || !workflowConversationId) {
      console.log("[WorkflowTest] ❌ Cannot send response - missing:", {
        hasResponse: !!waitingResponse.trim(),
        hasStepId: !!waitingStepId,
        hasConversationId: !!workflowConversationId
      })
      return
    }
    
    const waitingStep = workflowSteps.find(s => s.id === waitingStepId)
    console.log("[WorkflowTest] 📨 Sending response to waiting agent:", waitingStep?.agentName, "conversationId:", workflowConversationId)
    
    // Add user message to test messages
    setTestMessages(prev => [...prev, { role: "user", content: waitingResponse }])
    
    // Capture response and clear input immediately
    const responseToSend = waitingResponse
    const currentWaitingStepId = waitingStepId
    
    // Clear waiting UI immediately - user clicked Reply, box should disappear
    setWaitingResponse("")
    setWaitingStepId(null)
    setWaitingMessage(null)
    waitingStepIdRef.current = null
    
    // Set step to "working" while processing
    if (currentWaitingStepId) {
      setStepStatuses(prev => {
        const newMap = new Map(prev)
        const currentStatus = prev.get(currentWaitingStepId)
        newMap.set(currentWaitingStepId, { 
          status: "working",
          messages: currentStatus?.messages || [],
          completedAt: currentStatus?.completedAt
        })
        return newMap
      })
      stepStatusesRef.current.set(currentWaitingStepId, { 
        status: "working",
        messages: stepStatusesRef.current.get(currentWaitingStepId)?.messages || [],
        completedAt: stepStatusesRef.current.get(currentWaitingStepId)?.completedAt
      })
    }
    
    // If another input_required comes in, handleTaskUpdate will show the box again
    
    // Send the response via API (same format as handleTestSubmit)
    try {
      const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
      const messageId = `reply_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
      
      const parts: any[] = [
        { root: { kind: 'text', text: responseToSend } }
      ]
      
      console.log('[WorkflowTest] Sending reply:', {
        messageId,
        contextId: createContextId(workflowConversationId),
        workflow: generatedWorkflowText?.substring(0, 100) + '...'
      })
      
      const response = await fetch(`${baseUrl}/message/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          params: {
            messageId,
            contextId: createContextId(workflowConversationId),  // Use tenant-aware contextId
            parts: parts,
            role: 'user',
            agentMode: true,
            enableInterAgentMemory: true,
            workflow: generatedWorkflowText
          }
        })
      })
      
      if (!response.ok) {
        const errorText = await response.text()
        console.error("[WorkflowTest] ❌ API error:", response.status, response.statusText, errorText)
      } else {
        console.log("[WorkflowTest] ✅ Response sent successfully")
        
        // Emit message_sent event so chat panel can show the user message
        emit("message_sent", {
          role: "user",
          content: responseToSend,
          conversationId: workflowConversationId,
          contextId: createContextId(workflowConversationId),  // Use tenant-aware contextId
          timestamp: new Date().toISOString()
        })
      }
    } catch (err) {
      console.error("[WorkflowTest] ❌ Error sending response:", err)
    }
  }
  
  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (testTimeoutRef.current) {
        clearTimeout(testTimeoutRef.current)
      }
    }
  }, [])

  // Load workflow from template
  const loadWorkflow = (template: any) => {
    // Clear existing workflow first
    setWorkflowSteps([])
    setConnections([])
    setSelectedStepId(null)
    
    // Set the selected workflow ID to highlight it in the catalog
    setSelectedWorkflowId(template.id)
    
    // Load workflow metadata
    setWorkflowName(template.name || "")
    setWorkflowDescription(template.description || "")
    setWorkflowCategory(template.category || "Custom")
    setWorkflowGoal(template.goal || "")
    
    // Notify parent of the workflow name and goal
    // (now safe - parent won't auto-create workflows)
    if (onWorkflowNameChange && template.name) {
      onWorkflowNameChange(template.name)
    }
    if (onWorkflowGoalChange) {
      onWorkflowGoalChange(template.goal || "")
    }
    
    // Small delay to ensure state is cleared
    setTimeout(() => {
      // Guard against empty/undefined steps
      if (!template.steps || template.steps.length === 0) {
        console.log('[VisualWorkflowDesigner] No steps in template, keeping canvas empty')
        return
      }
      
      // Map template steps to workflow steps with colors
      const steps = template.steps.map((step: any) => {
        // Find the agent in registeredAgents to get the correct color
        const agentIndex = registeredAgents.findIndex(a => 
          (a.id || a.name.toLowerCase().replace(/\s+/g, '-')) === step.agentId ||
          a.name === step.agentName
        )
        
        return {
          id: step.id,
          agentId: step.agentId,
          agentName: step.agentName,
          agentColor: getAgentColor(agentIndex >= 0 ? agentIndex : step.order),
          description: step.description,
          x: step.x,
          y: step.y,
          order: step.order
        }
      })
      
      setWorkflowSteps(steps)
      setConnections(template.connections || [])
      
      // Update refs immediately to ensure test workflow uses latest data
      workflowStepsRef.current = steps
      connectionsRef.current = template.connections || []
      
      // Update workflow steps map ref for event handlers
      const newMap = new Map<string, WorkflowStep>()
      steps.forEach((step: WorkflowStep) => {
        newMap.set(step.agentName, step)
        newMap.set(step.agentId, step)
      })
      workflowStepsMapRef.current = newMap
      
      // Calculate and update workflow order map immediately
      if (template.connections && template.connections.length > 0) {
        const visited = new Set<string>()
        const result: WorkflowStep[] = []
        
        const connectedStepIds = new Set<string>()
        template.connections.forEach((conn: Connection) => {
          connectedStepIds.add(conn.fromStepId)
          connectedStepIds.add(conn.toStepId)
        })
        
        const hasIncoming = new Set(template.connections.map((c: Connection) => c.toStepId))
        const rootNodes = steps.filter((step: WorkflowStep) => 
          connectedStepIds.has(step.id) && !hasIncoming.has(step.id)
        )
        
        const dfs = (stepId: string) => {
          if (visited.has(stepId)) return
          visited.add(stepId)
          
          const step = steps.find((s: WorkflowStep) => s.id === stepId)
          if (step) {
            result.push(step)
            const outgoing = template.connections.filter((c: Connection) => c.fromStepId === stepId)
            outgoing.forEach((conn: Connection) => dfs(conn.toStepId))
          }
        }
        
        rootNodes.forEach((node: WorkflowStep) => dfs(node.id))
        
        const orderMap = new Map<string, number>()
        result.forEach((step, index) => {
          orderMap.set(step.id, index + 1)
        })
        
        setWorkflowOrderMap(orderMap)
        workflowOrderMapRef.current = orderMap
      }
      
      // Save to localStorage immediately
      const data = {
        positions: steps.map((step: any) => ({
          id: step.id,
          agentId: step.agentId,
          agentName: step.agentName,
          agentColor: step.agentColor,
          x: step.x,
          y: step.y,
          order: step.order,
          description: step.description
        })),
        connections: template.connections.map((conn: any) => ({
          id: conn.id,
          fromStepId: conn.fromStepId,
          toStepId: conn.toStepId
        }))
      }
      localStorage.setItem('workflow-visual-data', JSON.stringify(data))
    }, 100)
  }

  // Quick save - updates existing workflow without showing dialog
  const handleQuickSave = async () => {
    if (!workflowName.trim()) {
      // No name yet - show the dialog
      setShowSaveDialog(true)
      return
    }
    
    const workflowData = {
      name: workflowName,
      description: workflowDescription || "Custom workflow",
      category: workflowCategory,
      goal: workflowGoal || "",
      steps: workflowSteps.map(step => ({
        id: step.id,
        agentId: step.agentId,
        agentName: step.agentName,
        description: step.description,
        order: step.order,
        x: step.x,
        y: step.y
      })),
      connections: connections.map(conn => ({
        id: conn.id,
        fromStepId: conn.fromStepId,
        toStepId: conn.toStepId
      }))
    }
    
    console.log('[VisualWorkflowDesigner] Quick save - workflow data:', {
      name: workflowData.name,
      goal: workflowData.goal,
      selectedWorkflowId
    })
    
    try {
      const token = sessionStorage.getItem('auth_token') || localStorage.getItem('auth_token')
      
      if (token && selectedWorkflowId) {
        // Update existing workflow in backend
        const response = await fetch(`${process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'}/api/workflows/${selectedWorkflowId}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(workflowData)
        })
        
        if (response.ok) {
          console.log('[VisualWorkflowDesigner] Workflow updated successfully')
        } else {
          console.error('[VisualWorkflowDesigner] Failed to update workflow')
          alert("Failed to save workflow. Please try again.")
          return
        }
      } else if (token && !selectedWorkflowId) {
        // No selected workflow - create new one
        const newId = `workflow_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`
        const response = await fetch(`${process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'}/api/workflows`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({ id: newId, ...workflowData })
        })
        
        if (response.ok) {
          const data = await response.json()
          setSelectedWorkflowId(data.workflow?.id || newId)
          console.log('[VisualWorkflowDesigner] New workflow created:', data.workflow?.id || newId)
        } else {
          console.error('[VisualWorkflowDesigner] Failed to create workflow')
          alert("Failed to save workflow. Please try again.")
          return
        }
      } else {
        // Not authenticated - update in localStorage
        const customWorkflows = JSON.parse(localStorage.getItem('customWorkflows') || '[]')
        if (selectedWorkflowId) {
          const index = customWorkflows.findIndex((w: any) => w.id === selectedWorkflowId)
          if (index >= 0) {
            customWorkflows[index] = { id: selectedWorkflowId, ...workflowData, isCustom: true }
          } else {
            customWorkflows.push({ id: selectedWorkflowId, ...workflowData, isCustom: true })
          }
        } else {
          const newId = `workflow_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`
          customWorkflows.push({ id: newId, ...workflowData, isCustom: true })
          setSelectedWorkflowId(newId)
        }
        localStorage.setItem('customWorkflows', JSON.stringify(customWorkflows))
        console.log('[VisualWorkflowDesigner] Workflow saved to localStorage')
      }
      
      // Trigger catalog refresh
      setCatalogRefreshTrigger(prev => prev + 1)
      
    } catch (err) {
      console.error('[VisualWorkflowDesigner] Error saving workflow:', err)
      alert("Failed to save workflow. Please check your connection and try again.")
    }
  }

  // Save current workflow to catalog
  const handleSaveWorkflow = async () => {
    if (!workflowName.trim()) {
      alert("Please enter a workflow name")
      return
    }
    
    const customWorkflow = {
      id: `custom-${Date.now()}`,
      name: workflowName,
      description: workflowDescription || "Custom workflow",
      category: workflowCategory,
      goal: workflowGoal || "",
      steps: workflowSteps.map(step => ({
        id: step.id,
        agentId: step.agentId,
        agentName: step.agentName,
        description: step.description,
        order: step.order,
        x: step.x,
        y: step.y
      })),
      connections: connections.map(conn => ({
        id: conn.id,
        fromStepId: conn.fromStepId,
        toStepId: conn.toStepId
      })),
      isCustom: true
    }
    
    // Save to backend if authenticated, otherwise localStorage
    let savedToBackend = false
    try {
      const { createWorkflow, isAuthenticated } = await import('@/lib/workflow-api')
      
      if (isAuthenticated()) {
        const savedWorkflow = await createWorkflow({
          id: customWorkflow.id,
          name: customWorkflow.name,
          description: customWorkflow.description,
          category: customWorkflow.category,
          goal: customWorkflow.goal,
          steps: customWorkflow.steps,
          connections: customWorkflow.connections
        })
        
        if (savedWorkflow) {
          console.log('[VisualWorkflowDesigner] Workflow saved to backend:', savedWorkflow.id)
          savedToBackend = true
        } else {
          console.error('[VisualWorkflowDesigner] Backend save failed')
          alert("Failed to save workflow. Please try again.")
          return
        }
      } else {
        // Not authenticated - save to localStorage only
        console.log('[VisualWorkflowDesigner] User not authenticated, saving to localStorage')
        const saved = localStorage.getItem('custom-workflows')
        const existing = saved ? JSON.parse(saved) : []
        existing.push(customWorkflow)
        localStorage.setItem('custom-workflows', JSON.stringify(existing))
      }
    } catch (err) {
      console.error('[VisualWorkflowDesigner] Error saving workflow:', err)
      // If backend failed and user is authenticated, don't fall back to localStorage
      alert("Failed to save workflow. Please check your connection and try again.")
      return
    }
    
    // Update parent with the saved workflow name (so main UI shows it)
    if (onWorkflowNameChange) {
      onWorkflowNameChange(workflowName)
    }
    
    // Also update parent with the current workflow text (critical for Play button to work!)
    const currentWorkflowText = generateWorkflowTextFromRefs()
    if (currentWorkflowText) {
      onWorkflowGeneratedRef.current(currentWorkflowText)
      console.log('[VisualWorkflowDesigner] Updated parent with workflow text:', currentWorkflowText)
    }
    
    // Close dialog but keep the workflow name displayed
    setShowSaveDialog(false)
    
    // Trigger catalog refresh
    setCatalogRefreshTrigger(prev => prev + 1)
  }

  // Canvas rendering
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext("2d")
    if (!ctx) return

    const draw = () => {
      const rect = canvas.getBoundingClientRect()
      canvas.width = rect.width * window.devicePixelRatio
      canvas.height = rect.height * window.devicePixelRatio
      ctx.scale(window.devicePixelRatio, window.devicePixelRatio)

      const centerX = rect.width / 2
      const centerY = rect.height / 2

      // Background
      const bgGradient = ctx.createLinearGradient(0, 0, 0, rect.height)
      bgGradient.addColorStop(0, "hsl(222.2 47.4% 11.2%)")
      bgGradient.addColorStop(1, "hsl(220 17% 17%)")
      ctx.fillStyle = bgGradient
      ctx.fillRect(0, 0, rect.width, rect.height)

      // Apply transformations
      ctx.save()
      ctx.translate(centerX + panOffsetRef.current.x, centerY + panOffsetRef.current.y)
      ctx.scale(zoomRef.current, zoomRef.current)
      ctx.translate(-centerX, -centerY)

      // Grid
      ctx.strokeStyle = "rgba(148, 163, 184, 0.05)"
      ctx.lineWidth = 1
      const gridSize = 30
      for (let x = 0; x < rect.width; x += gridSize) {
        ctx.beginPath()
        ctx.moveTo(x, 0)
        ctx.lineTo(x, rect.height)
        ctx.stroke()
      }
      for (let y = 0; y < rect.height; y += gridSize) {
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.lineTo(rect.width, y)
        ctx.stroke()
      }

      // Draw connections based on connection state
      connections.forEach((connection) => {
        const from = workflowSteps.find(s => s.id === connection.fromStepId)
        const to = workflowSteps.find(s => s.id === connection.toStepId)
        
        if (!from || !to) return
        
        const fromCenterX = centerX + from.x
        const fromCenterY = centerY + from.y
        const toCenterX = centerX + to.x
        const toCenterY = centerY + to.y
        
        // Calculate angle between agents
        const angle = Math.atan2(to.y - from.y, to.x - from.x)
        
        // Hexagon boundary radius (approximate)
        const hexRadius = 40
        
        // Once connected, line starts from hexagon border (center)
        const fromX = fromCenterX + Math.cos(angle) * hexRadius
        const fromY = fromCenterY + Math.sin(angle) * hexRadius
        const toX = toCenterX - Math.cos(angle) * hexRadius
        const toY = toCenterY - Math.sin(angle) * hexRadius
        
        // Check if this connection involves the selected agent
        const isConnectionSelected = selectedStepId && (
          connection.fromStepId === selectedStepId || 
          connection.toStepId === selectedStepId
        )
        
        // Draw connection line
        ctx.strokeStyle = isConnectionSelected ? "rgba(99, 102, 241, 0.7)" : "rgba(99, 102, 241, 0.5)"
        ctx.lineWidth = isConnectionSelected ? 4 : 3
        ctx.shadowColor = "rgba(99, 102, 241, 0.3)"
        ctx.shadowBlur = isConnectionSelected ? 6 : 4
        
        ctx.beginPath()
        ctx.moveTo(fromX, fromY)
        ctx.lineTo(toX, toY)
        ctx.stroke()
        ctx.shadowBlur = 0
        
        // Draw arrow at target end
        const arrowLength = 12
        const arrowX = toX
        const arrowY = toY
        
        ctx.save()
        ctx.translate(arrowX, arrowY)
        ctx.rotate(angle)
        ctx.beginPath()
        ctx.moveTo(0, 0)
        ctx.lineTo(-arrowLength, -6)
        ctx.lineTo(-arrowLength, 6)
        ctx.closePath()
        ctx.fillStyle = isConnectionSelected ? "rgba(99, 102, 241, 0.9)" : "rgba(99, 102, 241, 0.7)"
        ctx.fill()
        ctx.restore()
        
        // Draw delete button on connection (middle point) - only for selected agent connections
        if (isConnectionSelected) {
          const midX = (fromX + toX) / 2
          const midY = (fromY + toY) / 2
          
          // Delete button circle
          ctx.fillStyle = "#ef4444"
          ctx.shadowColor = "rgba(239, 68, 68, 0.5)"
          ctx.shadowBlur = 8
          ctx.beginPath()
          ctx.arc(midX, midY, 10, 0, Math.PI * 2)
          ctx.fill()
          ctx.shadowBlur = 0
          
          // X mark
          ctx.strokeStyle = "#ffffff"
          ctx.lineWidth = 2
          ctx.beginPath()
          ctx.moveTo(midX - 4, midY - 4)
          ctx.lineTo(midX + 4, midY + 4)
          ctx.moveTo(midX + 4, midY - 4)
          ctx.lineTo(midX - 4, midY + 4)
          ctx.stroke()
        }
      })
      
      // Draw connection preview while dragging
      if (isCreatingConnection && connectionStart && connectionPreview) {
        const startStep = workflowSteps.find(s => s.id === connectionStart.stepId)
        if (startStep) {
          const fromCenterX = centerX + startStep.x
          const fromCenterY = centerY + startStep.y
          const toX = centerX + connectionPreview.x
          const toY = centerY + connectionPreview.y
          
          // Start from button position (x + 50)
          const buttonOffsetX = 50
          const fromX = fromCenterX + buttonOffsetX
          const fromY = fromCenterY
          
          ctx.strokeStyle = "rgba(99, 102, 241, 0.3)"
          ctx.lineWidth = 3
          ctx.setLineDash([10, 5])
          
          ctx.beginPath()
          ctx.moveTo(fromX, fromY)
          ctx.lineTo(toX, toY)
          ctx.stroke()
          
          ctx.setLineDash([])
        }
      }

      // Draw workflow steps
      workflowSteps.forEach((step) => {
        const x = centerX + step.x
        const y = centerY + step.y
        const isSelected = step.id === selectedStepId

        // Agent icon (hexagon)
        ctx.save()
        ctx.translate(x, y)
        
        const size = 30
        
        // Draw animated hexagon for selected state
        if (isSelected) {
          const pulse = Math.sin(Date.now() / 300) * 0.15 + 0.85 // Pulsing between 0.7 and 1.0
          
          // Outer animated hexagon with pulsing glow - WHITE
          ctx.strokeStyle = "#ffffff"
          ctx.lineWidth = 6
          ctx.shadowColor = "#ffffff"
          ctx.shadowBlur = 20 * pulse
          ctx.beginPath()
          for (let i = 0; i < 6; i++) {
            const angle = (Math.PI / 3) * i - Math.PI / 2
            const expandedSize = size + 6 * pulse // Pulsing expansion
            const px = Math.cos(angle) * expandedSize
            const py = Math.sin(angle) * expandedSize
            if (i === 0) ctx.moveTo(px, py)
            else ctx.lineTo(px, py)
          }
          ctx.closePath()
          ctx.stroke()
          
          // Animated dashed hexagon layer - WHITE with transparency
          const dashOffset = (Date.now() / 40) % 20
          ctx.setLineDash([10, 5])
          ctx.lineDashOffset = -dashOffset
          ctx.lineWidth = 3
          ctx.strokeStyle = "rgba(255, 255, 255, 0.8)"
          ctx.shadowBlur = 10
          ctx.beginPath()
          for (let i = 0; i < 6; i++) {
            const angle = (Math.PI / 3) * i - Math.PI / 2
            const dashedSize = size + 3
            const px = Math.cos(angle) * dashedSize
            const py = Math.sin(angle) * dashedSize
            if (i === 0) ctx.moveTo(px, py)
            else ctx.lineTo(px, py)
          }
          ctx.closePath()
          ctx.stroke()
          ctx.setLineDash([])
          ctx.shadowBlur = 0
        } else {
          // Normal hexagon outline
          ctx.strokeStyle = step.agentColor
          ctx.lineWidth = 3
          ctx.shadowColor = step.agentColor
          ctx.shadowBlur = 4
          ctx.beginPath()
          for (let i = 0; i < 6; i++) {
            const angle = (Math.PI / 3) * i - Math.PI / 2
            const px = Math.cos(angle) * size
            const py = Math.sin(angle) * size
            if (i === 0) ctx.moveTo(px, py)
            else ctx.lineTo(px, py)
          }
          ctx.closePath()
          ctx.stroke()
          ctx.shadowBlur = 0
        }

        // Inner fill (same for both selected and normal)
        ctx.fillStyle = step.agentColor
        ctx.beginPath()
        for (let i = 0; i < 6; i++) {
          const angle = (Math.PI / 3) * i - Math.PI / 2
          const px = Math.cos(angle) * (size * 0.7)
          const py = Math.sin(angle) * (size * 0.7)
          if (i === 0) ctx.moveTo(px, py)
          else ctx.lineTo(px, py)
        }
        ctx.closePath()
        ctx.fill()

        // Center circle (brighter when selected)
        ctx.fillStyle = isSelected ? "#ffffff" : "rgba(255, 255, 255, 0.9)"
        ctx.beginPath()
        ctx.arc(0, 0, size * 0.35, 0, Math.PI * 2)
        ctx.fill()
        
        ctx.restore()

        // Order badge - show workflow order in the center white circle
        const workflowOrder = workflowOrderMap.get(step.id)
        if (workflowOrder !== undefined) {
          // Draw number inside the center white circle
          ctx.fillStyle = step.agentColor
          ctx.font = "bold 16px system-ui"
          ctx.textAlign = "center"
          ctx.textBaseline = "middle"
          ctx.fillText(workflowOrder.toString(), x, y)
        } else {
          // Not in workflow - show grayed out dash in center
          ctx.fillStyle = "rgba(148, 163, 184, 0.4)"
          ctx.font = "bold 16px system-ui"
          ctx.textAlign = "center"
          ctx.textBaseline = "middle"
          ctx.fillText("-", x, y)
        }

        // Status indicator (working/completed/waiting) - show whenever we have status data
        const stepStatus = stepStatuses.get(step.id)
        if (stepStatus) {
            const statusX = x - 28
            const statusY = y - 28
            
            if (stepStatus.status === "working") {
              // Pulsing green dot
              const pulse = Math.sin(Date.now() / 300) * 0.3 + 0.7 // 0.4 to 1.0
              ctx.fillStyle = `rgba(34, 197, 94, ${pulse})`
              ctx.shadowColor = "rgba(34, 197, 94, 0.6)"
              ctx.shadowBlur = 8
              ctx.beginPath()
              ctx.arc(statusX, statusY, 5, 0, Math.PI * 2)
              ctx.fill()
              ctx.shadowBlur = 0
            } else if (stepStatus.status === "waiting") {
              // Pulsing orange dot with question mark - waiting for user input
              const pulse = Math.sin(Date.now() / 400) * 0.3 + 0.7
              ctx.fillStyle = `rgba(249, 115, 22, ${pulse})`
              ctx.shadowColor = "rgba(249, 115, 22, 0.7)"
              ctx.shadowBlur = 10
              ctx.beginPath()
              ctx.arc(statusX, statusY, 8, 0, Math.PI * 2)
              ctx.fill()
              ctx.shadowBlur = 0
              
              // White question mark
              ctx.fillStyle = "#ffffff"
              ctx.font = "bold 10px system-ui"
              ctx.textAlign = "center"
              ctx.textBaseline = "middle"
              ctx.fillText("?", statusX, statusY + 1)
            } else if (stepStatus.status === "completed") {
              // Green checkmark
              ctx.fillStyle = "#22c55e"
              ctx.shadowColor = "rgba(34, 197, 94, 0.6)"
              ctx.shadowBlur = 6
              ctx.beginPath()
              ctx.arc(statusX, statusY, 8, 0, Math.PI * 2)
              ctx.fill()
              ctx.shadowBlur = 0
              
              // White checkmark
              ctx.strokeStyle = "#ffffff"
              ctx.lineWidth = 2
              ctx.lineCap = "round"
              ctx.lineJoin = "round"
              ctx.beginPath()
              ctx.moveTo(statusX - 3, statusY)
              ctx.lineTo(statusX - 1, statusY + 2)
              ctx.lineTo(statusX + 3, statusY - 2)
              ctx.stroke()
            }
        }
        
        // Delete button (top center, floating above hexagon) - only show on selected agent
        if (isSelected) {
          const deleteX = x
          const deleteY = y - 55
          const deleteRadius = 9
          
          // Red gradient for delete button
          const deleteGradient = ctx.createRadialGradient(deleteX, deleteY, 0, deleteX, deleteY, deleteRadius)
          deleteGradient.addColorStop(0, "#ef4444")
          deleteGradient.addColorStop(1, "#dc2626")
          ctx.fillStyle = deleteGradient
          ctx.shadowColor = "rgba(239, 68, 68, 0.5)"
          ctx.shadowBlur = 10
          ctx.beginPath()
          ctx.arc(deleteX, deleteY, deleteRadius, 0, Math.PI * 2)
          ctx.fill()
          ctx.shadowBlur = 0
          
          // X icon (smaller)
          ctx.strokeStyle = "#ffffff"
          ctx.lineWidth = 1.8
          ctx.lineCap = "round"
          ctx.beginPath()
          ctx.moveTo(deleteX - 3, deleteY - 3)
          ctx.lineTo(deleteX + 3, deleteY + 3)
          ctx.moveTo(deleteX + 3, deleteY - 3)
          ctx.lineTo(deleteX - 3, deleteY + 3)
          ctx.stroke()
        }
        
        // Connection handle (arrow button on the right side) - show on selected agent for parallel workflow support
        if (isSelected) {
          // PARALLEL WORKFLOW SUPPORT:
          // Always show connection handle to allow multiple outgoing connections (fan-out)
          const handleX = x + 50
          const handleY = y
          const handleRadius = 10
            
            // Glow on/off animation
            const glow = Math.sin(Date.now() / 250) * 0.5 + 0.5 // Oscillates between 0 and 1
            
            // Gradient for handle
            const handleGradient = ctx.createRadialGradient(handleX, handleY, 0, handleX, handleY, handleRadius)
            handleGradient.addColorStop(0, "#818cf8")
            handleGradient.addColorStop(1, "#6366f1")
            ctx.fillStyle = handleGradient
            
            // Glowing shadow
            ctx.shadowColor = `rgba(99, 102, 241, ${0.3 + glow * 0.7})` // Opacity varies from 0.3 to 1.0
            ctx.shadowBlur = 8 + glow * 12 // Shadow blur varies from 8 to 20
            ctx.beginPath()
            ctx.arc(handleX, handleY, handleRadius, 0, Math.PI * 2)
            ctx.fill()
            ctx.shadowBlur = 0
            
          // Arrow icon (smaller)
          ctx.save()
          ctx.translate(handleX, handleY)
          ctx.fillStyle = "#ffffff"
          ctx.beginPath()
          ctx.moveTo(2.5, 0)
          ctx.lineTo(-2.5, -4)
          ctx.lineTo(-2.5, 4)
          ctx.closePath()
          ctx.fill()
          ctx.restore()
        }

        // Agent name - positioned below hexagon
        const nameYOffset = 50
        
        ctx.shadowColor = "rgba(0, 0, 0, 0.5)"
        ctx.shadowBlur = 2
        ctx.fillStyle = isSelected ? step.agentColor : "#f1f5f9"
        ctx.font = isSelected ? "bold 13px system-ui" : "600 12px system-ui"
        ctx.textAlign = "center"
        
        if (isSelected) {
          // Add background bar for selected agent name
          const textWidth = ctx.measureText(step.agentName).width
          ctx.fillStyle = "rgba(30, 41, 59, 0.9)"
          ctx.fillRect(x - textWidth / 2 - 8, y + nameYOffset - 8, textWidth + 16, 20)
          ctx.fillStyle = step.agentColor
        }
        
        ctx.fillText(step.agentName, x, y + nameYOffset)
        
        // Display duration beside agent name (right side) if completed
        {
          const stepStatusForDuration = stepStatuses.get(step.id)
          if (stepStatusForDuration && stepStatusForDuration.status === "completed") {
            const nameWidth = ctx.measureText(step.agentName).width
            let rightOffset = nameWidth / 2 + 8
            
            // Display duration if available
            if (stepStatusForDuration.startTime && stepStatusForDuration.completedAt) {
              const durationMs = stepStatusForDuration.completedAt - stepStatusForDuration.startTime
              const durationSec = (durationMs / 1000).toFixed(1)
              const durationText = `⏱️ ${durationSec}s`
              
              ctx.font = "10px system-ui"
              ctx.fillStyle = "#94a3b8"
              ctx.textAlign = "left"
              ctx.fillText(durationText, x + rightOffset, y + nameYOffset)
              
              rightOffset += ctx.measureText(durationText).width + 8
            }
            
            // Display token usage if available
            if (stepStatusForDuration.tokenUsage) {
              const tokens = stepStatusForDuration.tokenUsage.total_tokens
              const tokensText = `🎟️ ${tokens.toLocaleString()}`
              
              ctx.font = "10px system-ui"
              ctx.fillStyle = "#94a3b8"
              ctx.textAlign = "left"
              ctx.fillText(tokensText, x + rightOffset, y + nameYOffset)
            }
          }
        }
        
        ctx.shadowBlur = 0
        
        // Draw description below agent name (editable) - wrap text to multiple lines
        const descYOffset = nameYOffset + 25
        ctx.font = "11px system-ui"
        ctx.textAlign = "center"
        
        const maxWidth = 240 // Max width per line
        const isEditingThis = editingStepId === step.id
        const displayText = isEditingThis ? editingDescription : (step.description || "Click to add description")
        
        // Word wrap function
        const wrapText = (text: string, maxWidth: number) => {
          const words = text.split(' ')
          const lines: string[] = []
          let currentLine = ''
          
          for (const word of words) {
            const testLine = currentLine ? currentLine + ' ' + word : word
            const metrics = ctx.measureText(testLine)
            
            if (metrics.width > maxWidth && currentLine) {
              lines.push(currentLine)
              currentLine = word
            } else {
              currentLine = testLine
            }
          }
          if (currentLine) {
            lines.push(currentLine)
          }
          
          return lines
        }
        
        const lines = wrapText(displayText || " ", maxWidth)
        const lineHeight = 14
        const totalHeight = lines.length * lineHeight
        
        // Draw background for all lines
        const bgWidth = Math.max(...lines.map(line => ctx.measureText(line).width), 100) + 16
        ctx.fillStyle = isEditingThis ? "rgba(30, 41, 59, 0.95)" : "rgba(15, 23, 42, 0.8)"
        ctx.fillRect(x - bgWidth / 2 - 4, y + descYOffset - 10, bgWidth + 8, totalHeight + 8)
        
        // Draw border when editing
        if (isEditingThis) {
          ctx.strokeStyle = "rgba(129, 140, 248, 0.8)"
          ctx.lineWidth = 2
          ctx.strokeRect(x - bgWidth / 2 - 4, y + descYOffset - 10, bgWidth + 8, totalHeight + 8)
        }
        
        // Draw each line
        ctx.fillStyle = isEditingThis ? "rgba(129, 140, 248, 0.95)" : "rgba(148, 163, 184, 0.9)"
        lines.forEach((line, i) => {
          ctx.fillText(line, x, y + descYOffset + i * lineHeight)
        })
        
        // Draw blinking cursor when editing
        if (isEditingThis && showCursor) {
          // Calculate cursor position
          const textBeforeCursor = displayText.substring(0, cursorPosition)
          const linesBeforeCursor = wrapText(textBeforeCursor, maxWidth)
          const currentLineIndex = Math.max(0, linesBeforeCursor.length - 1)
          const currentLineText = linesBeforeCursor[currentLineIndex] || ""
          const cursorX = x + ctx.measureText(currentLineText).width / 2
          const cursorY = y + descYOffset + currentLineIndex * lineHeight
          
          ctx.fillStyle = "rgba(129, 140, 248, 1)"
          ctx.fillRect(cursorX, cursorY - 8, 2, 12)
        }
        
        // Add a subtle indicator that text is clickable (only when not editing)
        if (!isEditingThis) {
          ctx.font = "9px system-ui"
          ctx.fillStyle = "rgba(148, 163, 184, 0.4)"
          ctx.fillText("(click to edit)", x, y + descYOffset + totalHeight + 8)
        } else {
          ctx.font = "9px system-ui"
          ctx.fillStyle = "rgba(148, 163, 184, 0.6)"
          ctx.fillText("(press Enter to save, Esc to cancel)", x, y + descYOffset + totalHeight + 8)
        }
        
        // Display agent status and messages (above the agent)
        // Use step ID to get the correct status (handles duplicate agents)
        {
          const stepStatus = stepStatuses.get(step.id)
          if (stepStatus && stepStatus.messages && stepStatus.messages.length > 0) {
            const messageMaxWidth = 250
            
            // Check if messages are collapsed
          if (stepStatus.messagesCollapsed) {
            // Show a "+" button to expand messages
            const buttonSize = 32
            const buttonX = x - buttonSize / 2
            const buttonY = y - 80
              
              ctx.save()
              
              // Draw button background
              ctx.fillStyle = "rgba(30, 41, 59, 0.95)"
              ctx.strokeStyle = step.agentColor
              ctx.lineWidth = 2
              ctx.shadowColor = "rgba(0, 0, 0, 0.3)"
              ctx.shadowBlur = 4
              
              ctx.beginPath()
              ctx.roundRect(buttonX, buttonY, buttonSize, buttonSize, 6)
              ctx.fill()
              ctx.stroke()
              ctx.shadowBlur = 0
              
              // Draw "+" icon
              ctx.strokeStyle = step.agentColor
              ctx.lineWidth = 2
              ctx.lineCap = "round"
              
              const centerX = buttonX + buttonSize / 2
              const centerY = buttonY + buttonSize / 2
              const iconSize = 12
              
              ctx.beginPath()
              ctx.moveTo(centerX - iconSize / 2, centerY)
              ctx.lineTo(centerX + iconSize / 2, centerY)
              ctx.stroke()
              
              ctx.beginPath()
              ctx.moveTo(centerX, centerY - iconSize / 2)
              ctx.lineTo(centerX, centerY + iconSize / 2)
              ctx.stroke()
              
              // Message count badge
              ctx.fillStyle = step.agentColor
              ctx.font = "bold 10px system-ui"
              ctx.textAlign = "center"
              ctx.fillText(`${stepStatus.messages.length}`, centerX, buttonY - 8)
              
              ctx.restore()
            } else {
              // Show all messages stacked
              // Draw collapse button at same position as expand button
              const collapseButtonSize = 28
              const collapseButtonX = x - collapseButtonSize / 2
              const collapseButtonY = y - 80
              
              ctx.save()
              
              // Draw collapse button background
              ctx.fillStyle = "rgba(30, 41, 59, 0.95)"
              ctx.strokeStyle = step.agentColor
              ctx.lineWidth = 2
              ctx.shadowColor = "rgba(0, 0, 0, 0.3)"
              ctx.shadowBlur = 4
              
              ctx.beginPath()
              ctx.roundRect(collapseButtonX, collapseButtonY, collapseButtonSize, collapseButtonSize, 6)
              ctx.fill()
              ctx.stroke()
              ctx.shadowBlur = 0
              
              // Draw "-" icon
              ctx.strokeStyle = step.agentColor
              ctx.lineWidth = 2
              ctx.lineCap = "round"
              
              const centerX = collapseButtonX + collapseButtonSize / 2
              const centerY = collapseButtonY + collapseButtonSize / 2
              const iconSize = 12
              
              ctx.beginPath()
              ctx.moveTo(centerX - iconSize / 2, centerY)
              ctx.lineTo(centerX + iconSize / 2, centerY)
              ctx.stroke()
              
              ctx.restore()
              
              // Start messages above the collapse button
              let currentY = collapseButtonY - 10
              
              // Display each message as a separate bubble, stacking upward
              for (let msgIndex = stepStatus.messages.length - 1; msgIndex >= 0; msgIndex--) {
                const msg = stepStatus.messages[msgIndex]
                
                // Handle image messages
                if (msg.imageUrl) {
                  const imageUrl = msg.imageUrl
                  const imageSize = 120
                  const imageX = x - imageSize / 2
                  const imageY = currentY - imageSize - 10
                  
                  ctx.save()
                  
                  // Draw image background
                  ctx.shadowColor = "rgba(0, 0, 0, 0.3)"
                  ctx.shadowBlur = 4
                  ctx.fillStyle = "#1e293b"
                  ctx.strokeStyle = step.agentColor
                  ctx.lineWidth = 3
                  
                  ctx.beginPath()
                  ctx.roundRect(imageX - 4, imageY - 4, imageSize + 8, imageSize + 8, 8)
                  ctx.fill()
                  ctx.stroke()
                  ctx.shadowBlur = 0
                  
                  // Load and draw image
                  let img = imageCache.current.get(imageUrl)
                  if (!img) {
                    img = new Image()
                    const imgRef = img
                    imgRef.onload = () => {
                      imageCache.current.set(imageUrl, imgRef)
                    }
                    imgRef.onerror = () => {
                      imageCache.current.delete(imageUrl)
                    }
                    imgRef.src = imageUrl
                    imageCache.current.set(imageUrl, imgRef)
                  }
                  
                  if (img && img.complete && img.naturalWidth > 0) {
                    ctx.save()
                    ctx.beginPath()
                    ctx.roundRect(imageX, imageY, imageSize, imageSize, 4)
                    ctx.clip()
                    ctx.drawImage(img, imageX, imageY, imageSize, imageSize)
                    ctx.restore()
                  } else {
                    ctx.fillStyle = "#475569"
                    ctx.font = "12px system-ui"
                    ctx.textAlign = "center"
                    ctx.fillText("Loading...", x, imageY + imageSize / 2)
                  }
                  
                  // Draw filename
                  ctx.fillStyle = step.agentColor
                  ctx.font = "600 10px system-ui"
                  ctx.textAlign = "center"
                  ctx.fillText(`🖼️ ${msg.fileName || 'Image'}`, x, imageY - 10)
                  
                  ctx.restore()
                  
                  // Move up for next message
                  currentY = imageY - 20
                }
                
                // Handle text messages
                if (msg.text) {
                  ctx.save()
                  
                  ctx.font = "12px system-ui"
                  const words = msg.text.split(' ')
                  const lines: string[] = []
                  let currentLine = words[0]
              
              for (let i = 1; i < words.length; i++) {
                const testLine = currentLine + ' ' + words[i]
                const metrics = ctx.measureText(testLine)
                if (metrics.width > messageMaxWidth && currentLine.length > 0) {
                  lines.push(currentLine)
                  currentLine = words[i]
                } else {
                  currentLine = testLine
                }
              }
              lines.push(currentLine)
              
              const displayLines = lines.slice(0, 10)
              if (lines.length > 10) {
                displayLines[9] = displayLines[9].substring(0, 30) + '...'
              }
              
                  const lineHeight = 15
                  const padding = 10
                  const boxWidth = messageMaxWidth + padding * 2
                  const labelSpace = 20
                  const boxHeight = displayLines.length * lineHeight + padding * 2 + labelSpace
                  
                  // Position centered above current Y
                  const responseX = x - boxWidth / 2
                  const responseY = currentY - boxHeight / 2
              
              // Draw response box (matching DAG gradient style)
              const boxGradient = ctx.createLinearGradient(
                responseX,
                responseY - boxHeight / 2,
                responseX + boxWidth,
                responseY + boxHeight / 2
              )
              boxGradient.addColorStop(0, "#1e293b")
              boxGradient.addColorStop(1, "#0f172a")
              
              ctx.shadowColor = "rgba(0, 0, 0, 0.3)"
              ctx.shadowBlur = 4
              ctx.fillStyle = boxGradient
              ctx.strokeStyle = step.agentColor
              ctx.lineWidth = 2
              
              ctx.beginPath()
              ctx.roundRect(
                responseX,
                responseY - boxHeight / 2,
                boxWidth,
                boxHeight,
                8
              )
              ctx.fill()
              ctx.stroke()
              ctx.shadowBlur = 0
              
              // Add "From [Agent Name]" label
              ctx.fillStyle = step.agentColor
              ctx.font = "600 10px system-ui"
              ctx.textAlign = "left"
                  // Add "From [Agent Name]" label
                  ctx.fillStyle = step.agentColor
                  ctx.font = "600 10px system-ui"
                  ctx.textAlign = "left"
                  ctx.fillText(`📥 From ${step.agentName}`, responseX + padding, responseY - boxHeight / 2 + padding + 8)
                  
                  // Draw message text
                  ctx.fillStyle = "#e2e8f0"
                  ctx.font = "12px system-ui"
                  ctx.textAlign = "left"
                  
                  for (let i = 0; i < displayLines.length; i++) {
                    ctx.fillText(
                      displayLines[i],
                      responseX + padding,
                      responseY - boxHeight / 2 + padding + 28 + i * lineHeight
                    )
                  }
                  
                  ctx.restore()
                  
                  // Move up for next message
                  currentY = responseY - boxHeight / 2 - 20
                }
              }
            }
          }
        }
      })

      ctx.restore()

      // Instructions overlay (when empty)
      if (workflowSteps.length === 0 && !isDraggingOver) {
        ctx.fillStyle = "rgba(148, 163, 184, 0.3)"
        ctx.font = "16px system-ui"
        ctx.textAlign = "center"
        ctx.fillText("Drag agents from the left panel onto this canvas", centerX, centerY - 20)
        ctx.fillText("to build your workflow step by step", centerX, centerY + 10)
      }
      
      // Drag over indicator
      if (isDraggingOver) {
        ctx.strokeStyle = "rgba(99, 102, 241, 0.5)"
        ctx.lineWidth = 4
        ctx.setLineDash([20, 10])
        ctx.strokeRect(10, 10, rect.width - 20, rect.height - 20)
        ctx.setLineDash([])
      }
      
      // Orchestration sidebar will be rendered separately in JSX, not on canvas
    }

    let animationFrameId = requestAnimationFrame(function animate() {
      draw()
      animationFrameId = requestAnimationFrame(animate)
    })

    return () => cancelAnimationFrame(animationFrameId)
  }, [workflowSteps, selectedStepId, isDraggingOver, connections, isCreatingConnection, connectionStart, connectionPreview, workflowOrderMap, editingStepId, editingDescription, cursorPosition, showCursor, isTesting, stepStatuses, hostMessages])
  
  // Cursor blinking effect
  useEffect(() => {
    if (editingStepId) {
      const interval = setInterval(() => {
        setShowCursor(prev => !prev)
      }, 530) // Blink every 530ms
      return () => clearInterval(interval)
    } else {
      setShowCursor(true)
    }
  }, [editingStepId])

  // Auto-scroll orchestration sidebar to bottom when new messages arrive
  useEffect(() => {
    if (orchestrationSidebarRef.current) {
      orchestrationSidebarRef.current.scrollTop = orchestrationSidebarRef.current.scrollHeight
    }
  }, [hostMessages])

  // Mouse handlers for pan and agent dragging
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    
    let isPanningLocal = false
    let isDraggingAgentLocal = false

    const handleMouseDown = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect()
      const centerX = rect.width / 2
      const centerY = rect.height / 2
      const mouseX = e.clientX - rect.left
      const mouseY = e.clientY - rect.top
      
      // Convert to canvas coordinates
      const canvasX = (mouseX - centerX - panOffsetRef.current.x) / zoomRef.current
      const canvasY = (mouseY - centerY - panOffsetRef.current.y) / zoomRef.current
      
      // Check if clicking on message expand/collapse button (highest priority)
      for (const step of workflowStepsRef.current) {
        const stepStatus = stepStatusesRef.current.get(step.id)
        if (stepStatus && stepStatus.messages && stepStatus.messages.length > 0) {
          if (stepStatus.messagesCollapsed) {
            // Check for expand button click
            const buttonSize = 32
            const buttonX = step.x - buttonSize / 2
            const buttonY = step.y - 80
            
            if (canvasX >= buttonX && canvasX <= buttonX + buttonSize &&
                canvasY >= buttonY && canvasY <= buttonY + buttonSize) {
              // Clicked on the expand button
              toggleStepMessages(step.id)
              return
            }
          } else {
            // Check for collapse button click
            const buttonSize = 28
            const buttonX = step.x - buttonSize / 2
            const buttonY = step.y - 80
            
            if (canvasX >= buttonX && canvasX <= buttonX + buttonSize &&
                canvasY >= buttonY && canvasY <= buttonY + buttonSize) {
              // Clicked on the collapse button
              toggleStepMessages(step.id)
              return
            }
          }
        }
      }
      
      // First, check if clicking on an agent to determine what step is under cursor
      const clickedStep = workflowStepsRef.current.find(step => {
        const dx = canvasX - step.x
        const dy = canvasY - step.y
        const distance = Math.sqrt(dx * dx + dy * dy)
        return distance < 40 // 40px radius
      })
      
      // Check for clicks on description text area (highest priority)
      for (const step of workflowStepsRef.current) {
        const nameYOffset = 50
        const descYOffset = nameYOffset + 25
        
        // Estimate the description area bounds
        const descText = step.description || "Click to add description"
        const maxWidth = 240
        const lineHeight = 14
        
        // Rough calculation for multi-line text height
        const estimatedCharsPerLine = Math.floor(maxWidth / 6.5)
        const estimatedLines = Math.ceil(descText.length / estimatedCharsPerLine)
        const totalHeight = estimatedLines * lineHeight
        
        // Check if click is within description area
        const dx = Math.abs(canvasX - step.x)
        const dy = canvasY - (step.y + descYOffset)
        
        // Description area is centered horizontally and extends vertically
        if (dx < 130 && dy > -10 && dy < totalHeight + 10) {
          e.preventDefault()
          e.stopPropagation()
          setEditingStepId(step.id)
          const desc = step.description || ""
          setEditingDescription(desc)
          setCursorPosition(desc.length) // Put cursor at end
          setSelectedStepId(step.id)
          return
        }
      }
      
      // Check for delete button clicks on the selected step (check before other interactions)
      if (selectedStepIdRef.current) {
        const selectedStep = workflowStepsRef.current.find(s => s.id === selectedStepIdRef.current)
        
        if (selectedStep) {
          // Check if clicking on delete button (top center)
          const deleteX = selectedStep.x
          const deleteY = selectedStep.y - 55
          const deleteDx = canvasX - deleteX
          const deleteDy = canvasY - deleteY
          const deleteDistance = Math.sqrt(deleteDx * deleteDx + deleteDy * deleteDy)
          
          if (deleteDistance < 14) { // 14px radius for delete button (increased for easier clicking)
            e.preventDefault()
            e.stopPropagation()
            // Delete the agent and any connections involving it
            setWorkflowSteps(prev => prev.filter(s => s.id !== selectedStep.id))
            setConnections(prev => prev.filter(c => 
              c.fromStepId !== selectedStep.id && c.toStepId !== selectedStep.id
            ))
            setSelectedStepId(null)
            return
          }
          
          // Check if clicking on connection handle (arrow button)
          // PARALLEL WORKFLOW SUPPORT: Allow clicking handle even if connections exist
          const handleX = selectedStep.x + 50
          const handleY = selectedStep.y
          const handleDx = canvasX - handleX
          const handleDy = canvasY - handleY
          const handleDistance = Math.sqrt(handleDx * handleDx + handleDy * handleDy)
          
          if (handleDistance < 12) { // 12px radius for handle (slightly larger for easier clicking)
            // Start creating a connection
            e.preventDefault()
            e.stopPropagation()
            isCreatingConnectionRef.current = true
            setIsCreatingConnection(true)
            const startData = {
              stepId: selectedStep.id,
              x: selectedStep.x,
              y: selectedStep.y
            }
            connectionStartRef.current = startData
            setConnectionStart(startData)
            setConnectionPreview({ x: canvasX, y: canvasY })
            return
          }
          
          // Check if clicking on a connection delete button (only for selected agent's connections)
          for (const connection of connectionsRef.current) {
            // Only check if connection involves selected agent
            if (connection.fromStepId !== selectedStep.id && connection.toStepId !== selectedStep.id) {
              continue
            }
            
            const from = workflowStepsRef.current.find(s => s.id === connection.fromStepId)
            const to = workflowStepsRef.current.find(s => s.id === connection.toStepId)
            
            if (from && to) {
              const midX = (from.x + to.x) / 2
              const midY = (from.y + to.y) / 2
              const dx = canvasX - midX
              const dy = canvasY - midY
              const distance = Math.sqrt(dx * dx + dy * dy)
              
              if (distance < 10) { // 10px radius for delete button
                setConnections(prev => prev.filter(c => c.id !== connection.id))
                return
              }
            }
          }
        }
      }
      
      // Handle agent click/drag
      if (clickedStep) {
        // Start dragging agent
        isDraggingAgentLocal = true
        draggingStepIdRef.current = clickedStep.id
        setDraggingStepId(clickedStep.id)
        setSelectedStepId(clickedStep.id)
        setEditingDescription(clickedStep.description)
        
        // Store offset from agent center to mouse position
        dragOffsetRef.current = {
          x: canvasX - clickedStep.x,
          y: canvasY - clickedStep.y
        }
      } else {
        // Start panning canvas
        isPanningLocal = true
        setIsPanning(true)
        panStartRef.current = { 
          x: e.clientX - panOffsetRef.current.x, 
          y: e.clientY - panOffsetRef.current.y 
        }
      }
    }

    const handleMouseMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect()
      const centerX = rect.width / 2
      const centerY = rect.height / 2
      const mouseX = e.clientX - rect.left
      const mouseY = e.clientY - rect.top
      
      const canvasX = (mouseX - centerX - panOffsetRef.current.x) / zoomRef.current
      const canvasY = (mouseY - centerY - panOffsetRef.current.y) / zoomRef.current
      
      if (isCreatingConnectionRef.current) {
        // Update connection preview
        setConnectionPreview({ x: canvasX, y: canvasY })
      } else if (isDraggingAgentLocal && draggingStepIdRef.current) {
        // Update agent position
        setWorkflowSteps(prev => 
          prev.map(step => 
            step.id === draggingStepIdRef.current
              ? { 
                  ...step, 
                  x: canvasX - dragOffsetRef.current.x,
                  y: canvasY - dragOffsetRef.current.y
                }
              : step
          )
        )
      } else if (isPanningLocal) {
        // Pan canvas
        panOffsetRef.current = {
          x: e.clientX - panStartRef.current.x,
          y: e.clientY - panStartRef.current.y
        }
      }
    }

    const handleMouseUp = (e: MouseEvent) => {
      // Handle connection creation
      if (isCreatingConnectionRef.current && connectionStartRef.current) {
        const rect = canvas.getBoundingClientRect()
        const centerX = rect.width / 2
        const centerY = rect.height / 2
        const mouseX = e.clientX - rect.left
        const mouseY = e.clientY - rect.top
        
        const canvasX = (mouseX - centerX - panOffsetRef.current.x) / zoomRef.current
        const canvasY = (mouseY - centerY - panOffsetRef.current.y) / zoomRef.current
        
        // Check if releasing on an agent
        const targetStep = workflowStepsRef.current.find(step => {
          if (step.id === connectionStartRef.current!.stepId) return false // Can't connect to self
          const dx = canvasX - step.x
          const dy = canvasY - step.y
          const distance = Math.sqrt(dx * dx + dy * dy)
          return distance < 40 // 40px radius
        })
        
        if (targetStep) {
          // PARALLEL WORKFLOW SUPPORT:
          // Allow multiple outgoing connections from one step (fan-out for parallel execution)
          // Allow multiple incoming connections to one step (fan-in to merge parallel branches)
          // Only prevent duplicate connections (same from->to)
          
          // Create connection
          const newConnection: Connection = {
            id: `conn-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
            fromStepId: connectionStartRef.current.stepId,
            toStepId: targetStep.id
          }
          
          // Check if this exact connection already exists
          const exists = connectionsRef.current.some(c => 
            c.fromStepId === newConnection.fromStepId && c.toStepId === newConnection.toStepId
          )
          
          if (!exists) {
            setConnections(prev => [...prev, newConnection])
          }
        }
        
        // Reset connection creation state
        isCreatingConnectionRef.current = false
        connectionStartRef.current = null
        setIsCreatingConnection(false)
        setConnectionStart(null)
        setConnectionPreview(null)
      }
      
      isPanningLocal = false
      isDraggingAgentLocal = false
      setIsPanning(false)
      draggingStepIdRef.current = null
      setDraggingStepId(null)
    }

    canvas.addEventListener('mousedown', handleMouseDown)
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)

    return () => {
      canvas.removeEventListener('mousedown', handleMouseDown)
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
    // No dependencies - handlers use refs which don't trigger re-runs
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Mouse wheel zoom
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault()
      const zoomFactor = e.deltaY > 0 ? 0.95 : 1.05
      const newZoom = zoomRef.current * zoomFactor
      zoomRef.current = Math.max(0.3, Math.min(3, newZoom))
    }

    canvas.addEventListener('wheel', handleWheel, { passive: false })
    return () => canvas.removeEventListener('wheel', handleWheel)
  }, [])

  // Keyboard shortcuts and text input
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Handle editing mode
      if (editingStepId) {
        if (e.key === 'Enter' && !e.shiftKey) {
          // Save on Enter
          e.preventDefault()
          updateStepDescription(editingDescription, editingStepId)
          setEditingStepId(null)
          setCursorPosition(0)
        } else if (e.key === 'Escape') {
          // Cancel on Escape
          e.preventDefault()
          setEditingStepId(null)
          setCursorPosition(0)
        } else if (e.key === 'Backspace') {
          // Handle backspace
          e.preventDefault()
          if (cursorPosition > 0) {
            const newText = editingDescription.slice(0, cursorPosition - 1) + editingDescription.slice(cursorPosition)
            setEditingDescription(newText)
            setCursorPosition(cursorPosition - 1)
          }
        } else if (e.key === 'Delete') {
          // Handle delete
          e.preventDefault()
          if (cursorPosition < editingDescription.length) {
            const newText = editingDescription.slice(0, cursorPosition) + editingDescription.slice(cursorPosition + 1)
            setEditingDescription(newText)
          }
        } else if (e.key === 'ArrowLeft') {
          // Move cursor left
          e.preventDefault()
          setCursorPosition(Math.max(0, cursorPosition - 1))
        } else if (e.key === 'ArrowRight') {
          // Move cursor right
          e.preventDefault()
          setCursorPosition(Math.min(editingDescription.length, cursorPosition + 1))
        } else if (e.key === 'Home') {
          // Move to start
          e.preventDefault()
          setCursorPosition(0)
        } else if (e.key === 'End') {
          // Move to end
          e.preventDefault()
          setCursorPosition(editingDescription.length)
        } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
          // Regular character input
          e.preventDefault()
          const newText = editingDescription.slice(0, cursorPosition) + e.key + editingDescription.slice(cursorPosition)
          setEditingDescription(newText)
          setCursorPosition(cursorPosition + 1)
        }
        return
      }
      
      // Normal shortcuts (when not editing)
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selectedStepId && document.activeElement?.tagName !== 'TEXTAREA' && document.activeElement?.tagName !== 'INPUT') {
          e.preventDefault()
          deleteSelectedStep()
        }
      } else if (e.key === '0') {
        e.preventDefault()
        zoomRef.current = 1
        panOffsetRef.current = { x: 0, y: 0 }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedStepId, editingStepId, editingDescription, cursorPosition])

  const selectedStep = workflowSteps.find(s => s.id === selectedStepId)

  return (
    <div className="flex flex-col h-full gap-4">
      <div className="flex gap-4 h-full">
        {/* Agent Palette */}
        <div className="w-64 flex flex-col gap-2 bg-slate-900 rounded-lg p-4 border border-slate-800">
          <h3 className="text-sm font-semibold text-slate-200 mb-2">Available Agents</h3>
          <ScrollArea className="flex-1">
            <div className="space-y-2">
              {registeredAgents.length === 0 ? (
                <p className="text-xs text-slate-500">No agents registered</p>
              ) : (
                registeredAgents.map((agent, index) => (
                  <div
                    key={agent.id || agent.name}
                    draggable
                    onDragStart={() => setDraggedAgent(agent)}
                    onDragEnd={() => setDraggedAgent(null)}
                    className="p-3 bg-slate-800 rounded border border-slate-700 hover:border-slate-600 cursor-move transition-colors"
                    style={{
                      borderLeftColor: getAgentColor(index),
                      borderLeftWidth: '3px'
                    }}
                  >
                    <div className="text-sm font-medium text-slate-200">{agent.name}</div>
                    {agent.description && (
                      <div className="text-xs text-slate-400 mt-1 line-clamp-2">{agent.description}</div>
                    )}
                  </div>
                ))
              )}
            </div>
          </ScrollArea>
        </div>

        {/* Canvas */}
        <div className="flex-1 flex flex-col gap-2">
          {/* Workflow Metadata - Compact Editable */}
          {(workflowSteps.length > 0 || workflowName) && (
            <div className="px-3 py-2 bg-slate-800/50 rounded-lg border border-slate-700">
              <div className="flex items-end gap-3">
                <div className="flex-1 grid grid-cols-3 gap-3">
                  {/* Title */}
                  <div className="space-y-1">
                    <label className="text-[10px] text-slate-400 uppercase tracking-wide">Workflow Name</label>
                    <Input
                      value={workflowName}
                      onChange={(e) => {
                        setWorkflowName(e.target.value)
                        if (onWorkflowNameChange) {
                          onWorkflowNameChange(e.target.value)
                        }
                      }}
                      placeholder="Enter workflow name..."
                      className="h-8 text-sm font-medium bg-slate-900/50 border-slate-600 text-slate-200"
                    />
                  </div>
                  
                  {/* Description */}
                  <div className="space-y-1">
                    <label className="text-[10px] text-slate-400 uppercase tracking-wide">Description</label>
                    <Input
                      value={workflowDescription}
                      onChange={(e) => setWorkflowDescription(e.target.value)}
                      placeholder="Brief description..."
                      className="h-8 text-sm bg-slate-900/50 border-slate-600 text-slate-300"
                    />
                  </div>
                  
                  {/* Goal */}
                  <div className="space-y-1">
                    <label className="text-[10px] text-slate-400 uppercase tracking-wide">Goal</label>
                    <Input
                      value={workflowGoal}
                      onChange={(e) => {
                        setWorkflowGoal(e.target.value)
                        if (onWorkflowGoalChange) {
                          onWorkflowGoalChange(e.target.value)
                        }
                      }}
                      placeholder="What should this accomplish..."
                      className="h-8 text-sm bg-slate-900/50 border-slate-600 text-slate-300"
                    />
                  </div>
                </div>
                
                {/* Save Button - Always visible */}
                <Button
                  onClick={handleQuickSave}
                  size="sm"
                  className="h-8"
                >
                  <Save className="h-3 w-3 mr-1" />
                  Save
                </Button>
              </div>
            </div>
          )}
          
          <div 
            className="flex-1 relative bg-slate-900 rounded-lg border-2 border-dashed border-slate-800 overflow-hidden"
            onDragOver={(e) => {
              e.preventDefault()
              setIsDraggingOver(true)
            }}
            onDragLeave={() => setIsDraggingOver(false)}
            onDrop={handleCanvasDrop}
          >
            <canvas
              ref={canvasRef}
              className="w-full h-full"
              style={{ 
                minHeight: "400px",
                cursor: draggingStepId ? 'move' : isPanning ? 'grabbing' : 'grab'
              }}
            />
          </div>

          {/* Test Workflow Panel - Between canvas and analytics */}
          {workflowSteps.length > 0 && generatedWorkflowText && (
            <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
              <div className="flex items-center gap-2">
                <PlayCircle className="h-4 w-4 text-indigo-400" />
                <Input
                  value={testInput}
                  onChange={(e) => setTestInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      handleTestSubmit()
                    }
                  }}
                  placeholder="Test your workflow - enter a message and press Enter..."
                  disabled={isTesting}
                  className="flex-1 text-sm h-8"
                />
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={isTesting}
                  onClick={voiceLive.isConnected ? voiceLive.stopVoiceConversation : voiceLive.startVoiceConversation}
                  className={`h-8 ${
                    voiceLive.isConnected 
                      ? 'bg-green-100 text-green-600 hover:bg-green-200' 
                      : voiceLive.error 
                      ? 'bg-red-100 text-red-600' 
                      : ''
                  }`}
                  title={
                    voiceLive.isConnected 
                      ? 'End voice conversation' 
                      : voiceLive.error 
                      ? `Error: ${voiceLive.error}` 
                      : 'Start voice conversation'
                  }
                >
                  {voiceLive.isConnected ? <PhoneOff className="h-3 w-3" /> : <Phone className="h-3 w-3" />}
                </Button>
                {voiceLive.isConnected && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={voiceLive.toggleMute}
                    className={`h-8 ${
                      voiceLive.isMuted 
                        ? 'bg-primary/20 text-primary hover:bg-primary/30' 
                        : 'bg-primary/10 text-primary hover:bg-primary/20'
                    }`}
                    title={voiceLive.isMuted ? 'Unmute microphone' : 'Mute microphone'}
                  >
                    {voiceLive.isMuted ? <MicOff className="h-3 w-3" /> : <Mic className="h-3 w-3" />}
                  </Button>
                )}
                <Button
                  onClick={handleTestSubmit}
                  disabled={!testInput.trim() || isTesting}
                  size="sm"
                  className="h-8"
                >
                  {isTesting ? (
                    <>
                      <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                      Testing
                    </>
                  ) : (
                    <>
                      <Send className="h-3 w-3 mr-1" />
                      Test
                    </>
                  )}
                </Button>
                {isTesting && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleStopTest}
                    className="h-8"
                  >
                    <StopCircle className="h-3 w-3 mr-1" />
                    Stop
                  </Button>
                )}
              </div>
              
              {/* Waiting for Input Panel - shows when an agent is waiting for user response */}
              {waitingStepId && isTesting && (() => {
                const waitingStep = workflowSteps.find(s => s.id === waitingStepId)
                const waitingStatus = stepStatuses.get(waitingStepId)
                // Use captured waiting message or fall back to current status message
                const lastMessage = waitingStatus?.messages && waitingStatus.messages.length > 0 
                  ? waitingStatus.messages[waitingStatus.messages.length - 1].text 
                  : undefined
                const displayMessage = waitingMessage || lastMessage
                return (
                  <div className="mt-3 p-3 bg-orange-900/30 rounded-lg border border-orange-500/50">
                    <div className="flex items-start gap-3">
                      <div className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-white font-bold text-sm"
                           style={{ backgroundColor: waitingStep?.agentColor || '#f97316' }}>
                        ?
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="text-orange-400 font-medium text-sm">
                            {waitingStep?.agentName || "Agent"} is waiting for your response
                          </span>
                          <div className="h-2 w-2 bg-orange-500 rounded-full animate-pulse" />
                        </div>
                        
                        {/* Show the agent's question/message */}
                        {displayMessage && (
                          <div className="mb-3 p-2 bg-slate-800/50 rounded text-sm text-slate-300 whitespace-pre-wrap max-h-40 overflow-y-auto">
                            {displayMessage}
                          </div>
                        )}
                        
                        {/* Response input */}
                        <div className="flex items-center gap-2">
                          <Input
                            value={waitingResponse}
                            onChange={(e) => setWaitingResponse(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault()
                                handleWaitingResponse()
                              }
                            }}
                            placeholder="Type your response..."
                            className="flex-1 text-sm h-9 bg-slate-800/50 border-orange-500/30 focus:border-orange-500"
                            autoFocus
                          />
                          <Button
                            onClick={handleWaitingResponse}
                            disabled={!waitingResponse.trim()}
                            size="sm"
                            className="h-9 bg-orange-600 hover:bg-orange-700"
                          >
                            <Send className="h-3 w-3 mr-1" />
                            Reply
                          </Button>
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })()}
            </div>
          )}

          {/* Workflow Analytics */}
          {(() => {
            // Calculate totals from all step statuses
            let agentTokens = 0
            let agentPromptTokens = 0
            let agentCompletionTokens = 0
            let totalTime = 0
            let completedAgents = 0
            
            stepStatuses.forEach((status) => {
              if (status.tokenUsage?.total_tokens) {
                agentTokens += status.tokenUsage.total_tokens
                agentPromptTokens += status.tokenUsage.prompt_tokens || 0
                agentCompletionTokens += status.tokenUsage.completion_tokens || 0
              }
              if (status.duration) {
                totalTime += status.duration
              }
              if (status.status === "completed") {
                completedAgents++
              }
            })
            
            // Add host agent tokens
            const hostTokens = hostTokenUsage?.total_tokens || 0
            const hostPromptTokens = hostTokenUsage?.prompt_tokens || 0
            const hostCompletionTokens = hostTokenUsage?.completion_tokens || 0
            const totalTokens = agentTokens + hostTokens
            
            // Calculate cost - GPT-4o pricing (per 1M tokens)
            // Input: $2.50/1M, Output: $10/1M
            const INPUT_COST_PER_1M = 2.50
            const OUTPUT_COST_PER_1M = 10.00
            
            const totalPromptTokens = agentPromptTokens + hostPromptTokens
            const totalCompletionTokens = agentCompletionTokens + hostCompletionTokens
            
            const inputCost = (totalPromptTokens / 1000000) * INPUT_COST_PER_1M
            const outputCost = (totalCompletionTokens / 1000000) * OUTPUT_COST_PER_1M
            const totalCost = inputCost + outputCost
            
            const formatTokens = (tokens: number) => {
              if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`
              if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`
              return tokens.toString()
            }
            
            const formatCost = (cost: number) => {
              if (cost >= 1) return `$${cost.toFixed(2)}`
              if (cost >= 0.01) return `$${cost.toFixed(3)}`
              if (cost >= 0.001) return `$${cost.toFixed(4)}`
              return cost > 0 ? `$${cost.toFixed(5)}` : "$0"
            }
            
            const hasData = totalTokens > 0 || totalTime > 0
            
            return (
              <div className="flex items-center gap-6 px-4 py-2 bg-slate-800/50 rounded-lg border border-slate-700/50">
                {/* Total Time */}
                <div className="flex items-center gap-2">
                  <div className="flex items-center justify-center w-8 h-8 rounded-full bg-emerald-500/20 border border-emerald-500/30">
                    <span className="text-emerald-400">⏱️</span>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wide">Total Time</div>
                    <div className="text-lg font-bold text-emerald-400">
                      {hasData ? `${totalTime.toFixed(1)}s` : "—"}
                    </div>
                  </div>
                </div>
                
                {/* Divider */}
                <div className="w-px h-10 bg-slate-700"></div>
                
                {/* Agent Tokens */}
                <div className="flex items-center gap-2">
                  <div className="flex items-center justify-center w-8 h-8 rounded-full bg-amber-500/20 border border-amber-500/30">
                    <span className="text-amber-400">🤖</span>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wide">Agent Tokens</div>
                    <div className="text-lg font-bold text-amber-400">
                      {agentTokens > 0 ? formatTokens(agentTokens) : "—"}
                    </div>
                  </div>
                </div>
                
                {/* Divider */}
                <div className="w-px h-10 bg-slate-700"></div>
                
                {/* Host Tokens */}
                <div className="flex items-center gap-2">
                  <div className="flex items-center justify-center w-8 h-8 rounded-full bg-cyan-500/20 border border-cyan-500/30">
                    <span className="text-cyan-400">🧠</span>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wide">Host Tokens</div>
                    <div className="text-lg font-bold text-cyan-400">
                      {hostTokens > 0 ? formatTokens(hostTokens) : "—"}
                    </div>
                  </div>
                </div>
                
                {/* Divider */}
                <div className="w-px h-10 bg-slate-700"></div>
                
                {/* Total Tokens */}
                <div className="flex items-center gap-2">
                  <div className="flex items-center justify-center w-8 h-8 rounded-full bg-rose-500/20 border border-rose-500/30">
                    <span className="text-rose-400">Σ</span>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wide">Total</div>
                    <div className="text-lg font-bold text-rose-400">
                      {hasData ? formatTokens(totalTokens) : "—"}
                    </div>
                  </div>
                </div>
                
                {/* Divider */}
                <div className="w-px h-10 bg-slate-700"></div>
                
                {/* Cost */}
                <div className="flex items-center gap-2">
                  <div className="flex items-center justify-center w-8 h-8 rounded-full bg-green-500/20 border border-green-500/30">
                    <span className="text-green-400">💵</span>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wide">Est. Cost</div>
                    <div className="text-lg font-bold text-green-400">
                      {hasData ? formatCost(totalCost) : "—"}
                    </div>
                  </div>
                </div>
                
                {/* Divider */}
                <div className="w-px h-10 bg-slate-700"></div>
                
                {/* Agents Completed */}
                <div className="flex items-center gap-2">
                  <div className="flex items-center justify-center w-8 h-8 rounded-full bg-indigo-500/20 border border-indigo-500/30">
                    <span className="text-indigo-400">✓</span>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wide">Agents</div>
                    <div className="text-lg font-bold text-indigo-400">
                      {completedAgents > 0 ? `${completedAgents}/${workflowSteps.length}` : `0/${workflowSteps.length}`}
                    </div>
                  </div>
                </div>
                
                {/* Avg per Agent */}
                {completedAgents > 0 && (
                  <>
                    <div className="w-px h-10 bg-slate-700"></div>
                    <div className="flex items-center gap-2">
                      <div className="flex items-center justify-center w-8 h-8 rounded-full bg-purple-500/20 border border-purple-500/30">
                        <span className="text-purple-400">📊</span>
                      </div>
                      <div>
                        <div className="text-xs text-slate-500 uppercase tracking-wide">Avg/Agent</div>
                        <div className="text-lg font-bold text-purple-400">
                          {(totalTime / completedAgents).toFixed(1)}s
                        </div>
                      </div>
                    </div>
                  </>
                )}
              </div>
            )
          })()}
        </div>

        {/* Orchestration Sidebar - Collapsible */}
        {hostMessages.length > 0 && showOrchestrationSidebar && (
          <div className="w-80 flex flex-col bg-slate-900 rounded-lg border border-slate-700 overflow-hidden">
            <div className="p-3 border-b border-slate-700 bg-slate-800/50 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-indigo-400 flex items-center gap-2">
                  <div 
                    className="h-2 w-2 rounded-full animate-pulse"
                    style={{ backgroundColor: hostMessages.length > 0 ? (hostMessages[hostMessages.length - 1].agentColor || "#818cf8") : "#818cf8" }}
                  ></div>
                  Workflow Activity
                </h3>
                <p className="text-xs text-slate-400 mt-1">All agent messages & orchestration</p>
              </div>
              <button
                onClick={() => setShowOrchestrationSidebar(false)}
                className="text-slate-400 hover:text-slate-200 transition-colors"
                title="Hide orchestration sidebar"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
            
            <div 
              ref={orchestrationSidebarRef}
              className="flex-1 overflow-y-auto p-3 space-y-2 max-h-[600px] scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent"
            >
              {hostMessages.map((msg, idx) => {
                const messageColor = msg.agentColor || "#6366f1"
                const isHost = msg.isHost !== false // Default to true for backwards compatibility
                
                return (
                  <div 
                    key={idx} 
                    className="p-3 bg-slate-800/50 rounded-lg border border-slate-700/50 hover:border-opacity-100 transition-colors"
                    style={{ 
                      borderColor: `${messageColor}40`,
                      '--hover-border': messageColor 
                    } as any}
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <div 
                        className="h-1.5 w-1.5 rounded-full"
                        style={{ backgroundColor: messageColor }}
                      ></div>
                      <span 
                        className="text-xs font-semibold"
                        style={{ color: messageColor }}
                      >
                        {isHost ? "🎯 " : "🤖 "}{msg.target}
                      </span>
                      <span className="text-xs text-slate-500 ml-auto">
                        {new Date(msg.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                    <p className="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap">
                      {msg.message}
                    </p>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Workflow Catalog Sidebar */}
        {showCatalog && (
          <div className="w-80 flex flex-col">
            <div className="bg-slate-900 rounded-lg border border-slate-700 overflow-hidden h-full flex flex-col">
              <div className="p-3 border-b border-slate-700 bg-slate-800/50 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-200">Active Workflows</h3>
                <button
                  onClick={() => setShowCatalog(false)}
                  className="text-slate-400 hover:text-slate-200 transition-colors"
                  title="Hide workflow templates"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
              <div className="flex-1 overflow-hidden">
                <WorkflowCatalog
                  onLoadWorkflow={loadWorkflow}
                  onSaveWorkflow={handleQuickSave}
                  onNewWorkflow={async (name, description, category, goal) => {
                    // Clear the canvas
                    clearWorkflow()
                    // Set the workflow metadata (with fallback default for goal)
                    const defaultGoal = "Complete the workflow tasks efficiently and accurately"
                    setWorkflowName(name)
                    setWorkflowDescription(description)
                    setWorkflowCategory(category)
                    setWorkflowGoal(goal || defaultGoal)
                    
                    // Generate a unique ID for the new workflow
                    const newWorkflowId = `workflow_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`
                    
                    // Immediately save the blank workflow
                    try {
                      const token = sessionStorage.getItem('auth_token') || localStorage.getItem('auth_token')
                      const workflowData = {
                        id: newWorkflowId,
                        name: name,
                        description: description || '',
                        category: category || 'Custom',
                        steps: [], // Empty steps array
                        connections: [], // Empty connections array
                        goal: goal || 'Complete the workflow tasks efficiently and accurately'
                      }
                      
                      if (token) {
                        // Save to backend
                        const response = await fetch(`${process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'}/api/workflows`, {
                          method: 'POST',
                          headers: {
                            'Content-Type': 'application/json',
                            'Authorization': `Bearer ${token}`
                          },
                          body: JSON.stringify(workflowData)
                        })
                        
                        if (response.ok) {
                          const data = await response.json()
                          setSelectedWorkflowId(data.workflow?.id || newWorkflowId)
                        }
                      } else {
                        // Save to localStorage
                        const customWorkflows = JSON.parse(localStorage.getItem('customWorkflows') || '[]')
                        customWorkflows.push(workflowData)
                        localStorage.setItem('customWorkflows', JSON.stringify(customWorkflows))
                        setSelectedWorkflowId(newWorkflowId)
                      }
                      
                      // Trigger catalog refresh
                      setCatalogRefreshTrigger(prev => prev + 1)
                      
                    } catch (error) {
                      console.error('Failed to create workflow:', error)
                    }
                    
                    // Notify parent
                    if (onWorkflowNameChange) {
                      onWorkflowNameChange(name)
                    }
                    if (onWorkflowGoalChange) {
                      onWorkflowGoalChange(goal)
                    }
                  }}
                  currentWorkflowSteps={workflowSteps.length}
                  refreshTrigger={catalogRefreshTrigger}
                  selectedWorkflowId={selectedWorkflowId}
                />
              </div>
            </div>
          </div>
        )}

        {/* Floating toggle buttons for collapsed sidebars */}
        <div className="fixed right-4 top-20 flex flex-col gap-2 z-10">
          {!showCatalog && (
            <button
              onClick={() => setShowCatalog(true)}
              className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg border border-slate-600 shadow-lg transition-all hover:scale-105"
              title="Show workflow templates"
            >
              <div className="flex items-center gap-2">
                <ChevronLeft className="h-4 w-4" />
                <span className="text-xs font-medium">Templates</span>
              </div>
            </button>
          )}
          {hostMessages.length > 0 && !showOrchestrationSidebar && (
            <button
              onClick={() => setShowOrchestrationSidebar(true)}
              className="p-2 bg-indigo-900/80 hover:bg-indigo-800 text-indigo-200 rounded-lg border border-indigo-600 shadow-lg transition-all hover:scale-105"
              title="Show workflow activity"
            >
              <div className="flex items-center gap-2">
                <ChevronLeft className="h-4 w-4" />
                <span className="text-xs font-medium">Activity</span>
                <div 
                  className="h-2 w-2 rounded-full animate-pulse"
                  style={{ backgroundColor: hostMessages.length > 0 ? (hostMessages[hostMessages.length - 1].agentColor || "#818cf8") : "#818cf8" }}
                ></div>
              </div>
            </button>
          )}
        </div>
      </div>

      {/* Generated Workflow Preview - Collapsible */}
      {workflowSteps.length > 0 && generatedWorkflowText && (
        <details className="bg-slate-900 rounded-lg border border-slate-800">
          <summary className="cursor-pointer p-3 text-sm font-semibold text-slate-200 hover:bg-slate-800/50 rounded-lg">
            Generated Workflow Text (click to expand)
          </summary>
          <div className="p-4 pt-0">
            <pre className="text-xs font-mono text-slate-300 bg-slate-950 p-3 rounded whitespace-pre-wrap">
              {generatedWorkflowText}
            </pre>
          </div>
        </details>
      )}

      {/* Save Workflow Dialog */}
      <Dialog open={showSaveDialog} onOpenChange={setShowSaveDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Save Workflow Template</DialogTitle>
            <DialogDescription>
              Save your current workflow to the catalog for reuse
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium text-slate-200">Workflow Name *</label>
              <Input
                value={workflowName}
                onChange={(e) => {
                  setWorkflowName(e.target.value)
                  // Also update parent so main UI reflects the name
                  if (onWorkflowNameChange) {
                    onWorkflowNameChange(e.target.value)
                  }
                }}
                placeholder="e.g., My Custom Pipeline"
                className="mt-1"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-slate-200">Description</label>
              <Input
                value={workflowDescription}
                onChange={(e) => setWorkflowDescription(e.target.value)}
                placeholder="Brief description of this workflow"
                className="mt-1"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-slate-200">Category</label>
              <Input
                value={workflowCategory}
                onChange={(e) => setWorkflowCategory(e.target.value)}
                placeholder="e.g., Custom, Marketing, Quality Control"
                className="mt-1"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-slate-200">Workflow Goal</label>
              <Input
                value={workflowGoal}
                onChange={(e) => {
                  setWorkflowGoal(e.target.value)
                  onWorkflowGoalChange?.(e.target.value)
                }}
                placeholder="e.g., Analyze customer data and generate a report"
                className="mt-1"
              />
              <p className="text-xs text-slate-400 mt-1">
                Optional: Set a specific goal for this workflow. If empty, defaults to "Execute the [Workflow Name] workflow"
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowSaveDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleSaveWorkflow}>
              Save Workflow
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

