"use client"

import { useState, useEffect } from "react"
import { AgentNetwork } from "@/components/agent-network"
import { ChatPanel } from "@/components/chat-panel"
import { FileHistory } from "@/components/file-history"
import { useEventHub } from "@/hooks/use-event-hub"
import { ChatHistorySidebar } from "./chat-history-sidebar"
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels"
import { getOrCreateSessionId } from "@/lib/session"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Button } from "@/components/ui/button"
import { ChevronDown, ChevronRight, FileText } from "lucide-react"

const initialDagNodes = [
  { id: "User", group: "user" },
  { id: "Host Agent", group: "host" },
]

const initialDagLinks = [
  { source: "User", target: "Host Agent" },
]

export function ChatLayout() {
  const DEBUG = process.env.NEXT_PUBLIC_DEBUG_LOGS === 'true'
  const [isLeftSidebarCollapsed, setLeftSidebarCollapsed] = useState(false)
  const [isRightSidebarCollapsed, setRightSidebarCollapsed] = useState(false)
  const [isFileHistoryOpen, setFileHistoryOpen] = useState(false) // Closed by default
  const [agentMode, setAgentMode] = useState(false)  // Always starts OFF
  const [enableInterAgentMemory, setEnableInterAgentMemory] = useState(true)
  const [activeNode, setActiveNode] = useState<string | null>(null)
  const [workflow, setWorkflow] = useState(() => {
    // Only persist workflow text (not agent mode toggle)
    if (typeof window !== 'undefined') {
      return localStorage.getItem('agent-mode-workflow') || ""
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
    }
  }, [workflow])

  // This state represents the Host Agent's knowledge of registered agents.
  // It starts empty and gets populated by the WebSocket agent registry sync.
  const [registeredAgents, setRegisteredAgents] = useState<any[]>([])
  const [connectedUsers, setConnectedUsers] = useState<any[]>([])
  const [dagNodes, setDagNodes] = useState(() => [
    ...initialDagNodes,
  ])
  const [dagLinks, setDagLinks] = useState(() => [
    ...initialDagLinks,
  ])

  // Use the Event Hub hook for proper client-side initialization
  const { subscribe, unsubscribe, emit } = useEventHub()

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
      if (DEBUG) console.log("[ChatLayout] Agent enabled:", data.agent?.name)
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
      // Forward task updates to chat panel for status display
      emit("status_update", {
        inferenceId: data.taskId || `task_${Date.now()}`,
        agent: data.agentName || "Unknown Agent",  // Use agentName to match backend events
        status: data.state || "Processing..."  // Use state instead of status
      })
    }

    const handleFileUploaded = (data: any) => {
      if (DEBUG) console.log("[ChatLayout] File uploaded:", data)
      
      // Add file to File History (deduplication is handled in FileHistory component)
      if (data?.fileInfo && (window as any).addFileToHistory) {
        (window as any).addFileToHistory(data.fileInfo)
        if (DEBUG) console.log("[ChatLayout] Sent file to history:", data.fileInfo.filename)
      }
    }

    const handleFormSubmitted = (data: any) => {
      if (DEBUG) console.log("[ChatLayout] Form submitted")
    }

    // Subscribe to Event Hub events
    subscribe("session_agent_enabled", handleAgentEnabled)
    subscribe("session_agent_disabled", handleAgentDisabled)
    subscribe("message", handleMessage)
    subscribe("conversation_created", handleConversationCreated)
    subscribe("task_updated", handleTaskUpdated)
    subscribe("file_uploaded", handleFileUploaded)
    subscribe("form_submitted", handleFormSubmitted)
    subscribe("user_list_update", handleUserListUpdate)

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
      if (DEBUG) console.log("[ChatLayout] Unsubscribed from Event Hub events")
    }
  }, [subscribe, unsubscribe, emit])

  return (
    <div className="h-full w-full">
      <PanelGroup direction="horizontal">
        {/* Left Sidebar */}
        <Panel defaultSize={20} minSize={15} maxSize={30}>
          <div className="flex flex-col h-full">
            <ChatHistorySidebar
              isCollapsed={isLeftSidebarCollapsed}
              onToggle={() => setLeftSidebarCollapsed(!isLeftSidebarCollapsed)}
            />
            {!isLeftSidebarCollapsed && (
              <div className="border-t">
                <Collapsible open={isFileHistoryOpen} onOpenChange={setFileHistoryOpen}>
                  <CollapsibleTrigger asChild>
                    <Button 
                      variant="ghost" 
                      className="w-full justify-between px-4 py-3 h-auto font-medium text-sm"
                    >
                      <div className="flex items-center gap-2">
                        <FileText className="h-4 w-4" />
                        <span>File History</span>
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
                      <FileHistory />
                    </div>
                  </CollapsibleContent>
                </Collapsible>
              </div>
            )}
          </div>
        </Panel>
        
        <PanelResizeHandle className="w-2 bg-border hover:bg-accent transition-colors" />
        
        {/* Main Chat Area */}
        <Panel defaultSize={60} minSize={40}>
          <div className="flex flex-col min-w-0 border-x h-full">
            <ChatPanel 
              dagNodes={dagNodes} 
              dagLinks={dagLinks} 
              agentMode={agentMode}
              enableInterAgentMemory={enableInterAgentMemory}
              workflow={workflow}
              registeredAgents={registeredAgents}
              connectedUsers={connectedUsers}
              activeNode={activeNode}
              setActiveNode={setActiveNode}
            />
          </div>
        </Panel>
        
        <PanelResizeHandle className="w-2 bg-border hover:bg-accent transition-colors" />
        
        {/* Right Sidebar - Agent Network */}
        <Panel defaultSize={20} minSize={15} maxSize={35}>
          <AgentNetwork
            registeredAgents={registeredAgents}
            isCollapsed={isRightSidebarCollapsed}
            onToggle={() => setRightSidebarCollapsed(!isRightSidebarCollapsed)}
            agentMode={agentMode}
            onAgentModeChange={setAgentMode}
            enableInterAgentMemory={enableInterAgentMemory}
            onInterAgentMemoryChange={setEnableInterAgentMemory}
            workflow={workflow}
            onWorkflowChange={setWorkflow}
            dagNodes={dagNodes}
            dagLinks={dagLinks}
            activeNode={activeNode}
          />
        </Panel>
      </PanelGroup>
    </div>
  )
}
