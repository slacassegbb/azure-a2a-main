"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import { AgentNetwork } from "@/components/agent-network"
import { ChatPanel } from "@/components/chat-panel"
import { FileHistory } from "@/components/file-history"
import { useEventHub } from "@/hooks/use-event-hub"
import { ChatHistorySidebar } from "./chat-history-sidebar"
import { Panel, PanelGroup, PanelResizeHandle, ImperativePanelHandle } from "react-resizable-panels"
import { getOrCreateSessionId } from "@/lib/session"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Button } from "@/components/ui/button"
import { ChevronDown, ChevronRight, FileText } from "lucide-react"
import { useToast } from "@/hooks/use-toast"

const initialDagNodes = [
  { id: "User", group: "user" },
  { id: "Host Agent", group: "host" },
]

const initialDagLinks = [
  { source: "User", target: "Host Agent" },
]

export function ChatLayout() {
  const DEBUG = process.env.NEXT_PUBLIC_DEBUG_LOGS === 'true'
  const { toast } = useToast()
  
  // Use the Event Hub hook early for proper client-side initialization
  const { subscribe, unsubscribe, emit } = useEventHub()
  
  const [isLeftSidebarCollapsed, setLeftSidebarCollapsed] = useState(false)
  const [isRightSidebarCollapsed, setRightSidebarCollapsed] = useState(false)
  const [isFileHistoryOpen, setFileHistoryOpen] = useState(false) // Closed by default
  const [enableInterAgentMemory, setEnableInterAgentMemory] = useState(true)
  const [activeNode, setActiveNode] = useState<string | null>(null)
  
  // Panel refs for programmatic collapse/expand
  const leftPanelRef = useRef<ImperativePanelHandle>(null)
  const rightPanelRef = useRef<ImperativePanelHandle>(null)
  
  const [workflow, setWorkflow] = useState(() => {
    // Only persist workflow text (not agent mode toggle)
    if (typeof window !== 'undefined') {
      return localStorage.getItem('agent-mode-workflow') || ""
    }
    return ""
  })
  
  const [workflowName, setWorkflowName] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('agent-mode-workflow-name') || ""
    }
    return ""
  })
  
  const [workflowGoal, setWorkflowGoal] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('agent-mode-workflow-goal') || ""
    }
    return ""
  })

  // Only save workflow to localStorage (not agent mode toggle)
  useEffect(() => {
    if (typeof window !== 'undefined') {
      if (workflow) {
        localStorage.setItem('agent-mode-workflow', workflow)
      } else {
        localStorage.removeItem('agent-mode-workflow')
      }
      if (workflowName) {
        localStorage.setItem('agent-mode-workflow-name', workflowName)
      } else {
        localStorage.removeItem('agent-mode-workflow-name')
      }
      if (workflowGoal) {
        localStorage.setItem('agent-mode-workflow-goal', workflowGoal)
      } else {
        localStorage.removeItem('agent-mode-workflow-goal')
      }
    }
  }, [workflow, workflowName, workflowGoal])
  
  // Workflow action handlers (to be implemented)
  const handleRunWorkflow = useCallback(() => {
    if (!workflow) {
      toast({
        title: "No workflow defined",
        description: "Please create a workflow first",
        variant: "destructive"
      })
      return
    }
    
    // Parse the workflow text to get all step descriptions
    const lines = workflow.split('\n').filter(l => l.trim())
    if (lines.length === 0) {
      toast({
        title: "Empty workflow",
        description: "The workflow has no steps defined",
        variant: "destructive"
      })
      return
    }
    
    const workflowDisplayName = workflowName || 'Untitled Workflow'
    
    // Simple goal message - the workflow details are in the system prompt
    const initialMessage = `Execute the "${workflowDisplayName}" workflow.`
    
    console.log('[ChatLayout] Running workflow:', workflowDisplayName)
    console.log('[ChatLayout] Initial message:', initialMessage)
    console.log('[ChatLayout] Workflow goal:', workflowGoal || '(none - will use trigger message)')
    
    // Emit event for ChatPanel to handle - include workflowGoal for orchestrator
    emit('run_workflow', {
      workflowName: workflowDisplayName,
      workflow: workflow,
      initialMessage: initialMessage,
      workflowGoal: workflowGoal  // Pass the goal from workflow designer
    })
    
    toast({
      title: "Workflow Started",
      description: `Running: ${workflowDisplayName}`,
    })
  }, [workflow, workflowName, emit, toast])
  
  const handleScheduleWorkflow = useCallback(() => {
    console.log('[ChatLayout] Schedule workflow clicked:', workflowName || 'Untitled')
    // TODO: Implement workflow scheduling
    toast({
      title: "Coming Soon",
      description: "Workflow scheduling will be available in a future update",
    })
  }, [workflowName, toast])

  // Callback when file history loads files - auto-open if there are files
  const handleFilesLoaded = useCallback((count: number) => {
    if (count > 0) {
      setFileHistoryOpen(true)
    }
  }, [])

  // This state represents the Host Agent's knowledge of registered agents.
  // It starts empty and gets populated by the WebSocket agent registry sync.
  const [registeredAgents, setRegisteredAgents] = useState<any[]>([])
  const [connectedUsers, setConnectedUsers] = useState<any[]>([])
  
  // Track current session ID - when it changes (e.g., joining collaborative session), reload agents
  const [currentSessionId, setCurrentSessionId] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      return getOrCreateSessionId()
    }
    return ''
  })
  
  // Toggle handlers for sidebar collapse
  const handleLeftSidebarToggle = () => {
    if (leftPanelRef.current) {
      if (isLeftSidebarCollapsed) {
        leftPanelRef.current.expand()
      } else {
        leftPanelRef.current.collapse()
      }
    }
  }
  
  const handleRightSidebarToggle = () => {
    if (rightPanelRef.current) {
      if (isRightSidebarCollapsed) {
        rightPanelRef.current.expand()
      } else {
        rightPanelRef.current.collapse()
      }
    }
  }
  const [dagNodes, setDagNodes] = useState(() => [
    ...initialDagNodes,
  ])
  const [dagLinks, setDagLinks] = useState(() => [
    ...initialDagLinks,
  ])

  // Helper to update DAG from agents list
  const updateDagFromAgents = (agents: any[]) => {
    setDagNodes(prev => {
      const coreNodes = prev.filter(node => node.group === "user" || node.group === "host")
      const newAgentNodes = agents.map((agent: any) => ({ 
        id: agent.name, 
        group: "agent" 
      }))
      return [...coreNodes, ...newAgentNodes]
    })
    
    setDagLinks(prev => {
      const coreLinks = prev.filter(link => 
        (link.source === "User" && link.target === "Host Agent") ||
        (link.source === "Host Agent" && link.target === "User")
      )
      const agentLinks = agents.map((agent: any) => ({
        source: "Host Agent",
        target: agent.name
      }))
      return [...coreLinks, ...agentLinks]
    })
  }

  // Fetch session agents from backend
  const fetchSessionAgents = async () => {
    try {
      const sessionId = getOrCreateSessionId()
      const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
      const response = await fetch(`${baseUrl}/agents/session?session_id=${sessionId}`)
      
      if (response.ok) {
        const data = await response.json()
        const agents = (data.agents || []).map((agent: any) => ({
          id: agent.name.toLowerCase().replace(/\s+/g, '-'),
          name: agent.name,
          description: agent.description,
          status: "online",
          version: agent.version,
          endpoint: agent.url,
          organization: "Registry Agent",
          capabilities: agent.capabilities,
          skills: agent.skills,
          defaultInputModes: agent.defaultInputModes,
          defaultOutputModes: agent.defaultOutputModes,
          avatar: '/placeholder.svg?height=32&width=32'
        }))
        
        setRegisteredAgents(agents)
        updateDagFromAgents(agents)
        if (DEBUG) console.log("[ChatLayout] Loaded", agents.length, "session agents")
      }
    } catch (err) {
      console.error('[ChatLayout] Error fetching session agents:', err)
    }
  }

  // This useEffect hook represents the "Host Agent" listening to the Event Hub.
  useEffect(() => {
    // Load session agents on mount
    fetchSessionAgents()

    // Handle connected users list updates
    const handleUserListUpdate = (eventData: any) => {
      if (DEBUG) console.log("[ChatLayout] Received user list update")
      if (eventData.data?.active_users) {
        setConnectedUsers(eventData.data.active_users)
      }
    }

    // Handle agent enabled in catalog
    const handleAgentEnabled = (data: any) => {
      console.log("[ChatLayout] 🎯 Agent enabled event received:", data)
      if (data.agent) {
        const newAgent = {
          id: data.agent.name.toLowerCase().replace(/\s+/g, '-'),
          name: data.agent.name,
          description: data.agent.description,
          status: "online",
          version: data.agent.version,
          endpoint: data.agent.url,
          organization: "Registry Agent",
          capabilities: data.agent.capabilities,
          skills: data.agent.skills,
          defaultInputModes: data.agent.defaultInputModes,
          defaultOutputModes: data.agent.defaultOutputModes,
          avatar: '/placeholder.svg?height=32&width=32'
        }
        
        setRegisteredAgents(prev => {
          // Avoid duplicates
          if (prev.some(a => a.endpoint === newAgent.endpoint)) return prev
          const updated = [...prev, newAgent]
          updateDagFromAgents(updated)
          return updated
        })
      }
    }

    // Handle agent disabled in catalog
    const handleAgentDisabled = (data: any) => {
      if (DEBUG) console.log("[ChatLayout] Agent disabled:", data.agent_url)
      if (data.agent_url) {
        setRegisteredAgents(prev => {
          const updated = prev.filter(a => a.endpoint !== data.agent_url)
          updateDagFromAgents(updated)
          return updated
        })
      }
    }

    // Handle other Event Hub events for logging/debugging
    const handleMessage = (data: any) => {
      if (DEBUG) console.log("[ChatLayout] Message event")
      // ChatPanel already handles message events and emits final_response
      // This avoids duplicate or malformed final_response events here.
    }

    const handleConversationCreated = (data: any) => {
      if (DEBUG) console.log("[ChatLayout] Conversation created")
      // Forward to chat panel to start inference tracking (use different event name to avoid loop)
      emit("conversation_started", data)
    }

    const handleTaskUpdated = (data: any) => {
      if (DEBUG) console.log("[ChatLayout] Task updated")
      
      // NOTE: ChatLayout no longer emits status_update for workflow display
      // ChatPanel handles that with proper filtering to avoid duplicates
      // This handler is kept for potential future ChatLayout-specific logic
    }

    const handleFileUploaded = (data: any) => {
      console.log("[ChatLayout] 📁 File uploaded event received:", data)
      
      // Add file to File History (deduplication is handled in FileHistory component)
      if (data?.fileInfo && (window as any).addFileToHistory) {
        console.log("[ChatLayout] 📁 Adding to file history:", data.fileInfo.filename, data.fileInfo.uri?.substring(0, 80))
        ;(window as any).addFileToHistory(data.fileInfo)
        
        // Auto-expand file history when a file is added
        setFileHistoryOpen(true)
      } else {
        console.log("[ChatLayout] 📁 NOT adding to history - fileInfo:", !!data?.fileInfo, "addFileToHistory:", !!(window as any).addFileToHistory)
      }
    }

    const handleFormSubmitted = (data: any) => {
      if (DEBUG) console.log("[ChatLayout] Form submitted")
    }

    // Handle session cleared event (triggered on WebSocket reconnect after backend restart)
    const handleSessionCleared = (data: any) => {
      console.log("[ChatLayout] Session cleared due to:", data?.reason)
      // Clear the collaborative session but don't reload
      // The user will continue with their current state but on their own session
      const hadSession = sessionStorage.getItem('a2a_collaborative_session')
      if (hadSession) {
        sessionStorage.removeItem('a2a_collaborative_session')
        console.log("[ChatLayout] Cleared collaborative session, continuing on own session")
      }
    }

    // Handle session invalid event (collaborative session no longer exists on backend)
    const handleSessionInvalid = (data: any) => {
      console.log("[ChatLayout] Collaborative session invalid:", data?.reason)
      toast({
        title: "Collaborative Session Ended",
        description: "The session you were collaborating on is no longer available. You're now working in your own session.",
        variant: "default",
        duration: 6000,
      })
    }

    // Handle session members updated - this fires when we join a collaborative session
    // We need to reload agents since we're now in a different session
    const handleSessionMembersUpdated = (data: any) => {
      console.log("[ChatLayout] Session members updated:", data)
      // Check if our session ID changed
      const newSessionId = getOrCreateSessionId()
      if (newSessionId !== currentSessionId) {
        console.log("[ChatLayout] Session ID changed from", currentSessionId, "to", newSessionId, "- reloading agents")
        setCurrentSessionId(newSessionId)
        // Reload agents for the new session
        fetchSessionAgents()
      }
    }

    // Subscribe to Event Hub events
    console.log("[ChatLayout] 📡 Subscribing to session_agent_enabled/disabled events")
    subscribe("session_agent_enabled", handleAgentEnabled)
    subscribe("session_agent_disabled", handleAgentDisabled)
    subscribe("message", handleMessage)
    subscribe("conversation_created", handleConversationCreated)
    subscribe("task_updated", handleTaskUpdated)
    subscribe("file_uploaded", handleFileUploaded)
    subscribe("form_submitted", handleFormSubmitted)
    subscribe("user_list_update", handleUserListUpdate)
    subscribe("session_cleared", handleSessionCleared)
    subscribe("session_invalid", handleSessionInvalid)
    subscribe("session_members_updated", handleSessionMembersUpdated)

    if (DEBUG) console.log("[ChatLayout] Subscribed to Event Hub events")

    // Component initialization complete
    if (DEBUG) console.log("[ChatLayout] Event Hub subscriptions ready")

    // Clean up the subscriptions when the component unmounts.
    return () => {
      unsubscribe("session_agent_enabled", handleAgentEnabled)
      unsubscribe("session_agent_disabled", handleAgentDisabled)
      unsubscribe("message", handleMessage)
      unsubscribe("conversation_created", handleConversationCreated)
      unsubscribe("task_updated", handleTaskUpdated)
      unsubscribe("file_uploaded", handleFileUploaded)
      unsubscribe("form_submitted", handleFormSubmitted)
      unsubscribe("user_list_update", handleUserListUpdate)
      unsubscribe("session_cleared", handleSessionCleared)
      unsubscribe("session_invalid", handleSessionInvalid)
      unsubscribe("session_members_updated", handleSessionMembersUpdated)
      if (DEBUG) console.log("[ChatLayout] Unsubscribed from Event Hub events")
    }
  }, [subscribe, unsubscribe, emit, toast, currentSessionId])

  return (
    <div className="h-full w-full bg-background">
      <PanelGroup direction="horizontal">
        {/* Left Sidebar */}
        <Panel 
          ref={leftPanelRef}
          defaultSize={20} 
          minSize={2}
          maxSize={30}
          collapsible={true}
          collapsedSize={2}
          onCollapse={() => setLeftSidebarCollapsed(true)}
          onExpand={() => setLeftSidebarCollapsed(false)}
        >
          <div className="flex flex-col h-full bg-muted/20">
            <ChatHistorySidebar
              isCollapsed={isLeftSidebarCollapsed}
              onToggle={handleLeftSidebarToggle}
            />
            {!isLeftSidebarCollapsed && (
              <div className="mt-2">
                <Collapsible open={isFileHistoryOpen} onOpenChange={setFileHistoryOpen}>
                  <CollapsibleTrigger asChild>
                    <Button 
                      variant="ghost" 
                      className="w-full justify-between px-4 py-3 h-auto font-medium text-sm"
                    >
                      <div className="flex items-center gap-2">
                        <FileText className="h-4 w-4" />
                        <span>Shared Files</span>
                      </div>
                      {isFileHistoryOpen ? (
                        <ChevronDown className="h-4 w-4" />
                      ) : (
                        <ChevronRight className="h-4 w-4" />
                      )}
                    </Button>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <div className="p-2">
                      <FileHistory onFilesLoaded={handleFilesLoaded} />
                    </div>
                  </CollapsibleContent>
                </Collapsible>
                {/* Hidden FileHistory to check file count on mount when collapsed */}
                {!isFileHistoryOpen && (
                  <div className="hidden">
                    <FileHistory onFilesLoaded={handleFilesLoaded} />
                  </div>
                )}
              </div>
            )}
          </div>
        </Panel>
        
        <PanelResizeHandle className="w-px bg-border/30 hover:bg-accent/50 transition-colors" />
        
        {/* Main Chat Area */}
        <Panel defaultSize={60} minSize={40}>
          <div className="flex flex-col min-w-0 h-full">
            <ChatPanel 
              dagNodes={dagNodes} 
              dagLinks={dagLinks} 
              enableInterAgentMemory={enableInterAgentMemory}
              workflow={workflow}
              workflowGoal={workflowGoal}
              registeredAgents={registeredAgents}
              connectedUsers={connectedUsers}
              activeNode={activeNode}
              setActiveNode={setActiveNode}
            />
          </div>
        </Panel>
        
        <PanelResizeHandle className="w-px bg-border/30 hover:bg-accent/50 transition-colors" />
        
        {/* Right Sidebar - Agent Network */}
        <Panel 
          ref={rightPanelRef}
          defaultSize={20} 
          minSize={2}
          maxSize={35}
          collapsible={true}
          collapsedSize={2}
          onCollapse={() => setRightSidebarCollapsed(true)}
          onExpand={() => setRightSidebarCollapsed(false)}
        >
          <div className="h-full bg-muted/20">
          <AgentNetwork
            registeredAgents={registeredAgents}
            isCollapsed={isRightSidebarCollapsed}
            onToggle={handleRightSidebarToggle}
            enableInterAgentMemory={enableInterAgentMemory}
            onInterAgentMemoryChange={setEnableInterAgentMemory}
            workflow={workflow}
            workflowName={workflowName}
            workflowGoal={workflowGoal}
            onWorkflowChange={setWorkflow}
            onWorkflowNameChange={setWorkflowName}
            onWorkflowGoalChange={setWorkflowGoal}
            onRunWorkflow={handleRunWorkflow}
            onScheduleWorkflow={handleScheduleWorkflow}
            dagNodes={dagNodes}
            dagLinks={dagLinks}
            activeNode={activeNode}
          />
          </div>
        </Panel>
      </PanelGroup>
    </div>
  )
}
