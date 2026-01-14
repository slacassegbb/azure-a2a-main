"use client"

import { useState, useEffect } from "react"
import { AgentNetwork } from "@/components/agent-network"
import { ChatPanel } from "@/components/chat-panel"
import { FileHistory } from "@/components/file-history"
import { useEventHub } from "@/hooks/use-event-hub"
import { ChatHistorySidebar } from "./chat-history-sidebar"
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels"
import { getOrCreateSessionId } from "@/lib/session"

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
  const [agentMode, setAgentMode] = useState(false)  // Always starts OFF
  const [enableInterAgentMemory, setEnableInterAgentMemory] = useState(true)
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
  // It starts empty and gets populated by session agents fetch.
  const [registeredAgents, setRegisteredAgents] = useState<any[]>([])
  const [connectedUsers, setConnectedUsers] = useState<any[]>([])
  const [dagNodes, setDagNodes] = useState(() => [
    ...initialDagNodes,
  ])
  const [dagLinks, setDagLinks] = useState(() => [
    ...initialDagLinks,
  ])

  // Get session ID for multi-tenancy
  const sessionId = getOrCreateSessionId()

  // Use the Event Hub hook for proper client-side initialization
  const { subscribe, unsubscribe, emit } = useEventHub()

  // Fetch session agents on initial load
  useEffect(() => {
    const fetchSessionAgents = async () => {
      try {
        const response = await fetch(`/api/agents/session/registered?sessionId=${encodeURIComponent(sessionId)}`)
        if (response.ok) {
          const data = await response.json()
          if (data.agents && Array.isArray(data.agents)) {
            const transformedAgents = data.agents.map((agent: any) => ({
              id: agent.name.toLowerCase().replace(/\s+/g, '-'),
              name: agent.name,
              description: agent.description,
              status: agent.status || "online",
              version: agent.version,
              endpoint: agent.url,
              organization: "Registry Agent",
              capabilities: agent.capabilities,
              skills: agent.skills,
              defaultInputModes: agent.defaultInputModes,
              defaultOutputModes: agent.defaultOutputModes,
              avatar: '/placeholder.svg?height=32&width=32'
            }))
            setRegisteredAgents(transformedAgents)
            if (DEBUG) console.log("[ChatLayout] Loaded", transformedAgents.length, "session agents")
          }
        }
      } catch (error) {
        console.error("[ChatLayout] Error fetching session agents:", error)
      }
    }
    
    fetchSessionAgents()
  }, [sessionId, DEBUG])

  // This useEffect hook represents the "Host Agent" listening to the Event Hub.
  useEffect(() => {
    // Handle connected users list updates
    const handleUserListUpdate = (eventData: any) => {
      if (DEBUG) console.log("[ChatLayout] Received user list update")
      if (eventData.data?.active_users) {
        setConnectedUsers(eventData.data.active_users)
      }
    }

    // Handle registry sync events from WebSocket - this is for the CATALOG, not the sidebar
    // The sidebar now shows only session-enabled agents, not all agents from registry sync
    const handleAgentRegistrySync = (data: any) => {
      if (DEBUG) console.log("[ChatLayout] Received agent registry sync (catalog update, not sidebar)")
      // This event is now used to update the catalog, not the sidebar
      // The sidebar is populated from session agents only
    }    // Handle other Event Hub events for logging/debugging
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

    // Handle agent session updates (enable/disable from catalog)
    const handleAgentSessionUpdated = (data: any) => {
      console.log("[ChatLayout] Agent session updated:", data)
      const { agentUrl, enabled, agent } = data
      
      if (enabled && agent) {
        // Add agent directly from the event data
        const newAgent = {
          id: agent.name.toLowerCase().replace(/\s+/g, '-'),
          name: agent.name,
          description: agent.description,
          status: agent.status || "online",
          version: agent.version,
          endpoint: agent.url,
          organization: "Registry Agent",
          capabilities: agent.capabilities,
          skills: agent.skills,
          avatar: '/placeholder.svg?height=32&width=32'
        }
        
        setRegisteredAgents(prev => {
          // Check if already exists
          const exists = prev.some(a => a.endpoint?.replace(/\/$/, '') === agent.url?.replace(/\/$/, ''))
          if (exists) {
            console.log("[ChatLayout] Agent already in sidebar:", agent.name)
            return prev
          }
          console.log("[ChatLayout] Adding agent to sidebar:", agent.name)
          return [...prev, newAgent]
        })
      } else if (!enabled) {
        // Remove agent from sidebar by URL
        setRegisteredAgents(prev => {
          const filtered = prev.filter(a => 
            a.endpoint?.replace(/\/$/, '') !== agentUrl?.replace(/\/$/, '')
          )
          console.log("[ChatLayout] Removed agent from sidebar, remaining:", filtered.length)
          return filtered
        })
      }
    }

    // Subscribe to Event Hub events
    subscribe("agent_registry_sync", handleAgentRegistrySync)
    subscribe("message", handleMessage)
    subscribe("conversation_created", handleConversationCreated)
    subscribe("task_updated", handleTaskUpdated)
    subscribe("file_uploaded", handleFileUploaded)
    subscribe("form_submitted", handleFormSubmitted)
    subscribe("user_list_update", handleUserListUpdate)
    subscribe("agentSessionUpdated", handleAgentSessionUpdated)

    if (DEBUG) console.log("[ChatLayout] Subscribed to Event Hub events")

    // Component initialization complete
    if (DEBUG) console.log("[ChatLayout] Event Hub subscriptions ready")

    // Clean up the subscriptions when the component unmounts.
    return () => {
      unsubscribe("agent_registry_sync", handleAgentRegistrySync)
      unsubscribe("message", handleMessage)
      unsubscribe("conversation_created", handleConversationCreated)
      unsubscribe("task_updated", handleTaskUpdated)
      unsubscribe("file_uploaded", handleFileUploaded)
      unsubscribe("form_submitted", handleFormSubmitted)
      unsubscribe("user_list_update", handleUserListUpdate)
      unsubscribe("agentSessionUpdated", handleAgentSessionUpdated)
      if (DEBUG) console.log("[ChatLayout] Unsubscribed from Event Hub events")
    }
  }, [subscribe, unsubscribe, emit, DEBUG])

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
              <div className="p-2 space-y-2">
                <FileHistory />
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
          />
        </Panel>
      </PanelGroup>
    </div>
  )
}
