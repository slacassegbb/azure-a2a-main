"use client"

import type React from "react"
import { useEffect, useRef, useState, memo } from "react"
import { useEventHub } from "@/hooks/use-event-hub"

type AgentType = "host" | "remote" | "user"

interface Node {
  id: string
  group: string
}

interface Link {
  source: string | Node
  target: string | Node
}

interface Agent {
  id: string
  name: string
  type: AgentType
  status: "active" | "idle" | "working" | "completed" | "failed"
  x: number
  y: number
  isGlowing: boolean
  glowIntensity: number
  color: string
  taskState?: string
  currentResponse?: string // Latest response to display
  generatedImageUrl?: string // URL of generated image to display
  generatedImageFilename?: string // Filename of generated image
  generatedFileUrl?: string // URL of any generated file
  generatedFileType?: string // Content type of the file
  outgoingMessage?: string // Message being sent from this agent (Host) to remote agent
  outgoingMessageTarget?: string // Name of target agent receiving the message
}

interface ThoughtBubble {
  id: string
  agentId: string
  text: string
  y: number
  opacity: number
  startTime: number
}

interface AgentNetworkDagProps {
  nodes: Node[]
  links: Link[]
  activeNodeId: string | null
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

const HOST_COLOR = "#6366f1" // indigo
const USER_COLOR = "#22d3ee" // cyan

const shuffleArray = <T,>(array: T[]): T[] => {
  const shuffled = [...array]
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]]
  }
  return shuffled
}

const getColorForAgent = (nodeId: string, group: string, index: number): string => {
  if (group === "host") return HOST_COLOR
  if (group === "user") return USER_COLOR
  // For agents, use consistent color based on their position
  const shuffled = shuffleArray(AGENT_COLORS)
  return shuffled[index % shuffled.length]
}

const AgentNetworkDagComponent = ({ nodes, links, activeNodeId }: AgentNetworkDagProps) => {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [agents, setAgents] = useState<Agent[]>([])
  const [thoughtBubbles, setThoughtBubbles] = useState<ThoughtBubble[]>([])
  const [hasInitialized, setHasInitialized] = useState(false)
  const colorMapRef = useRef<Map<string, string>>(new Map())
  const agentsRef = useRef<Agent[]>([])
  const imageCache = useRef<Map<string, HTMLImageElement>>(new Map())
  
  // Zoom and pan state (using refs for performance - no re-renders on every change)
  const zoomRef = useRef(1)
  const panOffsetRef = useRef({ x: 0, y: 0 })
  const [isPanning, setIsPanning] = useState(false)
  const panStartRef = useRef({ x: 0, y: 0 })
  
  // Fullscreen state
  const [isFullscreen, setIsFullscreen] = useState(false)
  
  // WebSocket connection for real-time updates
  const { subscribe, unsubscribe } = useEventHub()

  // Keep agents ref in sync
  useEffect(() => {
    agentsRef.current = agents
  }, [agents])

  // Clean up image cache when images are removed
  useEffect(() => {
    const currentImageUrls = new Set(
      agents.map(a => a.generatedImageUrl).filter((url): url is string => !!url)
    )
    const currentFileUrls = new Set(
      agents.map(a => a.generatedFileUrl).filter((url): url is string => !!url)
    )
    
    // Remove cached images that are no longer in use
    for (const [url] of imageCache.current) {
      if (!currentImageUrls.has(url) && !currentFileUrls.has(url)) {
        imageCache.current.delete(url)
        console.log("[AgentNetworkDag] 🗑️ Removed cached file:", url)
      }
    }
  }, [agents])

  // Map backend agent names to frontend agent names
  const mapAgentName = (backendName: string): string => {
    const nameMap: Record<string, string> = {
      "foundry-host-agent": "Host Agent",
      "host": "Host Agent",
      "Host": "Host Agent",
    }
    return nameMap[backendName] || backendName
  }

  // Initialize agents from nodes prop
  useEffect(() => {
    if (!nodes || nodes.length === 0) return

    setAgents((prevAgents) => {
      // Only initialize new agents, preserve existing ones
      const existingIds = new Set(prevAgents.map(a => a.id))
      const newNodes = nodes.filter(node => !existingIds.has(node.id))
      
      if (newNodes.length === 0 && prevAgents.length === nodes.length) {
        // No new nodes, keep existing agents
        return prevAgents
      }

      const newAgents = nodes.map((node, index) => {
        // Check if agent already exists
        const existing = prevAgents.find(a => a.id === node.id)
        if (existing) {
          // Preserve existing agent data including position
          return existing
        }

        // Get or assign color consistently
        if (!colorMapRef.current.has(node.id)) {
          const color = getColorForAgent(node.id, node.group, index)
          colorMapRef.current.set(node.id, color)
        }

        const type: AgentType = 
          node.group === "host" ? "host" : 
          node.group === "user" ? "user" : 
          "remote"

        return {
          id: node.id,
          name: node.id,
          type,
          status: "idle" as const,
          x: 0,
          y: 0,
          isGlowing: false,
          glowIntensity: 0,
          color: colorMapRef.current.get(node.id) || HOST_COLOR,
        }
      })

      return newAgents
    })
  }, [nodes])

  // Position agents in a network layout
  useEffect(() => {
    if (agents.length === 0) return

    // Filter out user nodes - we don't want to display them
    const filteredAgents = agents.filter((a) => a.type !== "user")
    const remoteAgents = filteredAgents.filter((a) => a.type === "remote")
    const totalRemote = remoteAgents.length

    setAgents((prev) => {
      return prev.filter((a) => a.type !== "user").map((agent) => {
        // Don't reposition if already positioned (to avoid re-triggering)
        if (agent.x !== 0 || agent.y !== 0) {
          // Check if it's a remote agent that needs repositioning due to new agents
          if (agent.type === "remote") {
            const currentIndex = remoteAgents.findIndex((a) => a.id === agent.id)
            if (currentIndex === -1) return agent
            
            const angle = (currentIndex / totalRemote) * 2 * Math.PI - Math.PI / 2
            const radius = 300 // Increased radius for more space
            
            return {
              ...agent,
              x: Math.cos(angle) * radius,
              y: Math.sin(angle) * radius,
            }
          }
          return agent
        }

        // Initial positioning
        // Host in the center
        if (agent.type === "host") {
          return { ...agent, x: 0, y: 0 }
        }

        // Remote agents in a circle around the host
        const agentIndex = remoteAgents.findIndex((a) => a.id === agent.id)
        if (agentIndex === -1) return agent
        
        const angle = (agentIndex / totalRemote) * 2 * Math.PI - Math.PI / 2 // Start at top
        const radius = 300 // Increased radius for more space

        return {
          ...agent,
          x: Math.cos(angle) * radius,
          y: Math.sin(angle) * radius,
        }
      })
    })
  }, [agents.length])

  // WebSocket event listeners for task states
  useEffect(() => {
    // Log all events for debugging
    console.log("[AgentNetworkDag] Setting up WebSocket listeners")
    
    const handleStatusUpdate = (data: any) => {
      console.log("[AgentNetworkDag] ✅ Status update:", data)
      const { agent: agentName, status, inferenceId } = data

      if (!agentName) {
        console.log("[AgentNetworkDag] ⚠️ No agent name in status update")
        return
      }

      setAgents((prev) =>
        prev.map((agent) => {
          if (agent.name === agentName || agent.id === agentName) {
            let newStatus: Agent["status"] = "working"
            let shouldGlow = true
            let taskState = status

            // Map status strings to visual states
            if (status?.includes("completed") || status?.includes("response") || status?.includes("generated")) {
              newStatus = "completed"
              taskState = "completed"
            } else if (status?.includes("failed") || status?.includes("error")) {
              newStatus = "failed"
              taskState = "failed"
            } else if (status?.includes("input_required") || status?.includes("input-required")) {
              newStatus = "idle"
              taskState = "input-required"
              shouldGlow = true // Keep glowing to indicate waiting for input
            } else if (status?.includes("processing") || status?.includes("analyzing") || status?.includes("executing")) {
              newStatus = "working"
              taskState = "working"
            } else if (status?.includes("idle") || status?.includes("waiting")) {
              newStatus = "idle"
              shouldGlow = false
            } else {
              newStatus = "working"
            }

            // Add thought bubble for status updates
            if (status && shouldGlow) {
              const shortStatus = status.length > 60 ? status.substring(0, 57) + "..." : status
              addThoughtBubble(agent.id, shortStatus)
            }

            console.log("[AgentNetworkDag] ✨ Updated status for", agentName, "to", newStatus)

            // Preserve position when updating status
            return {
              ...agent,
              status: newStatus,
              isGlowing: shouldGlow,
              taskState,
              // Keep x and y unchanged
            }
          }
          return agent
        })
      )

      // Auto-clear completed/failed states after delay
      setTimeout(() => {
        setAgents((prev) =>
          prev.map((agent) => {
            if ((agent.name === agentName || agent.id === agentName) && 
                (agent.status === "completed" || agent.status === "failed")) {
              // Preserve position when clearing status
              return { 
                ...agent, 
                status: "idle" as const, 
                isGlowing: false, 
                glowIntensity: 0,
                // Keep x and y unchanged
              }
            }
            return agent
          })
        )
      }, 3000)
    }

    const handleTaskUpdate = (data: any) => {
      console.log("[AgentNetworkDag] 📋 Task update:", data)
      const { taskId, state, agentName } = data

      if (!agentName) return

      setAgents((prev) =>
        prev.map((agent) => {
          if (agent.name === agentName || agent.id === agentName) {
            let status: Agent["status"] = "working"
            
            if (state === "completed") status = "completed"
            else if (state === "failed") status = "failed"
            else if (state === "in_progress" || state === "requires_action") status = "working"
            else if (state === "queued") status = "idle"

            // Preserve position when updating task
            return { 
              ...agent, 
              status, 
              isGlowing: status === "working", 
              taskState: state,
              // Keep x and y unchanged
            }
          }
          return agent
        })
      )
    }

    const handleAgentMessage = (data: any) => {
      console.log("[AgentNetworkDag] 💬 Agent message:", data)
      const { agentName, content } = data
      
      if (agentName && content) {
        const shortContent = content.length > 60 ? content.substring(0, 57) + "..." : content
        const agent = agentsRef.current.find(a => a.name === agentName || a.id === agentName)
        if (agent) {
          console.log("[AgentNetworkDag] ✨ Adding thought bubble for", agentName, ":", shortContent)
          addThoughtBubble(agent.id, shortContent)
          triggerGlow(agent.id)
        } else {
          console.log("[AgentNetworkDag] ⚠️ Agent not found:", agentName, "Available:", agentsRef.current.map(a => a.name))
        }
      }
    }

    // Handle actual message events from A2A backend
    const handleMessage = (data: any) => {
      console.log("[AgentNetworkDag] 📨 Message event:", data)
      
      // Extract message content from the event
      let messageText = ""
      let rawAgentName = data.agentName || data.agent || data.from
      
      // Try different message formats
      if (data.content && Array.isArray(data.content)) {
        const textContent = data.content.find((c: any) => c.type === "text")?.content || ""
        messageText = textContent
      } else if (data.message && typeof data.message === "string") {
        messageText = data.message
      } else if (typeof data.content === "string") {
        messageText = data.content
      }
      
      // If we found message text but no explicit agent name, try to extract from message
      if (messageText && !rawAgentName) {
        // Look for patterns like "I consulted the **AgentName**"
        const match = messageText.match(/\*\*([^*]+Agent)\*\*/)
        if (match) {
          rawAgentName = match[1]
        }
      }
      
      if (messageText && rawAgentName) {
        // Map the agent name
        const agentName = mapAgentName(rawAgentName)
        // Show FULL message (no truncation)
        const fullContent = messageText
        const agent = agentsRef.current.find(a => a.name === agentName || a.id === agentName)
        if (agent) {
          console.log("[AgentNetworkDag] ✨ Setting response for", agentName, ":", fullContent.substring(0, 100) + "...")
          
          setAgents((prev) =>
            prev.map((a) =>
              a.id === agent.id
                ? { ...a, currentResponse: fullContent, isGlowing: true }
                : a
            )
          )
          
          // Clear after 15 seconds for full message display
          setTimeout(() => {
            setAgents((prev) =>
              prev.map((a) =>
                a.id === agent.id && a.currentResponse === fullContent
                  ? { ...a, currentResponse: undefined, isGlowing: false }
                  : a
              )
            )
          }, 15000)
        } else {
          console.log("[AgentNetworkDag] ⚠️ Agent not found:", agentName, "Available:", agentsRef.current.map(a => a.name))
          console.log("[AgentNetworkDag] Full event data:", JSON.stringify(data, null, 2))
        }
      } else {
        console.log("[AgentNetworkDag] ⚠️ Could not extract message or agent from event")
      }
    }

    // Handle final response events (processed messages)
    const handleFinalResponse = (data: any) => {
      console.log("[AgentNetworkDag] 🎯 Final response:", data)
      
      if (data.message?.agent && data.message?.content) {
        // Show FULL message (no truncation)
        const fullContent = data.message.content
        const agent = agentsRef.current.find(a => a.name === data.message.agent || a.id === data.message.agent)
        if (agent) {
          console.log("[AgentNetworkDag] ✨ Setting response for", data.message.agent, ":", fullContent.substring(0, 100) + "...")
          
          setAgents((prev) =>
            prev.map((a) =>
              a.id === agent.id
                ? { ...a, currentResponse: fullContent, isGlowing: true }
                : a
            )
          )
          
          // Clear after 15 seconds for full message display
          setTimeout(() => {
            setAgents((prev) =>
              prev.map((a) =>
                a.id === agent.id && a.currentResponse === fullContent
                  ? { ...a, currentResponse: undefined, isGlowing: false }
                  : a
              )
            )
          }, 15000)
        } else {
          console.log("[AgentNetworkDag] ⚠️ Agent not found:", data.message.agent, "Available:", agentsRef.current.map(a => a.name))
        }
      }
    }

    // Handle tool calls
    const handleToolCall = (data: any) => {
      console.log("[AgentNetworkDag] 🔧 Tool call:", data)
      
      if (data.agentName && data.toolName) {
        const message = `🛠️ Calling ${data.toolName}`
        const agent = agentsRef.current.find(a => a.name === data.agentName || a.id === data.agentName)
        if (agent) {
          console.log("[AgentNetworkDag] ✨ Setting response for", data.agentName, ":", message)
          
          setAgents((prev) =>
            prev.map((a) =>
              a.id === agent.id
                ? { ...a, currentResponse: message, isGlowing: true }
                : a
            )
          )
          
          setTimeout(() => {
            setAgents((prev) =>
              prev.map((a) =>
                a.id === agent.id && a.currentResponse === message
                  ? { ...a, currentResponse: undefined }
                  : a
              )
            )
          }, 5000)
        } else {
          console.log("[AgentNetworkDag] ⚠️ Agent not found:", data.agentName, "Available:", agentsRef.current.map(a => a.name))
        }
      }
    }

    // Handle tool responses
    const handleToolResponse = (data: any) => {
      console.log("[AgentNetworkDag] 🔧 Tool response:", data)
      
      if (data.agentName && data.toolName) {
        const message = data.status === "success" 
          ? `✅ ${data.toolName} completed`
          : `❌ ${data.toolName} failed`
        const agent = agentsRef.current.find(a => a.name === data.agentName || a.id === data.agentName)
        if (agent) {
          console.log("[AgentNetworkDag] ✨ Setting response for", data.agentName, ":", message)
          
          setAgents((prev) =>
            prev.map((a) =>
              a.id === agent.id
                ? { ...a, currentResponse: message, isGlowing: true }
                : a
            )
          )
          
          setTimeout(() => {
            setAgents((prev) =>
              prev.map((a) =>
                a.id === agent.id && a.currentResponse === message
                  ? { ...a, currentResponse: undefined }
                  : a
              )
            )
          }, 5000)
        } else {
          console.log("[AgentNetworkDag] ⚠️ Agent not found:", data.agentName, "Available:", agentsRef.current.map(a => a.name))
        }
      }
    }

    // Handle agent activity
    const handleAgentActivity = (data: any) => {
      console.log("[AgentNetworkDag] 🔄 Agent activity:", data)
      
      if (data.agentName && data.activity) {
        const shortActivity = data.activity.length > 100 
          ? data.activity.substring(0, 97) + "..." 
          : data.activity
        const agent = agentsRef.current.find(a => a.name === data.agentName || a.id === data.agentName)
        if (agent) {
          console.log("[AgentNetworkDag] ✨ Setting response for", data.agentName, ":", shortActivity)
          
          setAgents((prev) =>
            prev.map((a) =>
              a.id === agent.id
                ? { ...a, currentResponse: shortActivity, isGlowing: true }
                : a
            )
          )
          
          setTimeout(() => {
            setAgents((prev) =>
              prev.map((a) =>
                a.id === agent.id && a.currentResponse === shortActivity
                  ? { ...a, currentResponse: undefined, isGlowing: false }
                  : a
              )
            )
          }, 8000)
        } else {
          console.log("[AgentNetworkDag] ⚠️ Agent not found:", data.agentName, "Available:", agentsRef.current.map(a => a.name))
        }
      }
    }

    // Handle remote agent activity (THIS IS WHAT WE NEED!)
    const handleRemoteAgentActivity = (data: any) => {
      console.log("[AgentNetworkDag] 🤖 Remote agent activity:", data)
      
      if (data.agentName && data.content) {
        // Show FULL message (no truncation)
        const fullContent = data.content
        const agent = agentsRef.current.find(a => a.name === data.agentName || a.id === data.agentName)
        if (agent) {
          console.log("[AgentNetworkDag] ✨ Setting REMOTE AGENT response for", data.agentName, ":", fullContent.substring(0, 100) + "...")
          
          // Check if this is a short status message
          const isStatusMessage = fullContent.length < 100 && (
            fullContent.toLowerCase().includes("status:") ||
            fullContent.toLowerCase().includes("processing") ||
            fullContent.toLowerCase().includes("analyzing") ||
            fullContent.toLowerCase().includes("working") ||
            fullContent.toLowerCase().includes("submitted")
          )
          
          // Don't let short status messages overwrite substantial responses
          const currentResponse = agent.currentResponse || ""
          const shouldUpdate = !currentResponse || // No current response
                               !isStatusMessage || // New content is not a status message
                               currentResponse.length < 100 || // Current response is also short
                               fullContent.length > currentResponse.length + 50 // New content is significantly longer
          
          if (shouldUpdate) {
            console.log("[AgentNetworkDag] ✅ Updating response (isStatus:", isStatusMessage, "currentLen:", currentResponse.length, "newLen:", fullContent.length, ")")
            setAgents((prev) =>
              prev.map((a) =>
                a.id === agent.id
                  ? { ...a, currentResponse: fullContent, isGlowing: true }
                  : a
              )
            )
            
            setTimeout(() => {
              setAgents((prev) =>
                prev.map((a) =>
                  a.id === agent.id && a.currentResponse === fullContent
                    ? { ...a, currentResponse: undefined, isGlowing: false }
                    : a
                )
              )
            }, 15000)
          } else {
            console.log("[AgentNetworkDag] ⏭️ Skipping status message (preserving substantial response)")
          }
        } else {
          console.log("[AgentNetworkDag] ⚠️ Remote agent not found:", data.agentName, "Available:", agentsRef.current.map(a => a.name))
        }
      }
    }

    // Handle inference steps
    const handleInferenceStep = (data: any) => {
      console.log("[AgentNetworkDag] 🧠 Inference step:", data)
      
      if (data.agent && data.status) {
        const shortStatus = data.status.length > 80 
          ? data.status.substring(0, 77) + "..." 
          : data.status
        const agent = agentsRef.current.find(a => a.name === data.agent || a.id === data.agent)
        if (agent) {
          console.log("[AgentNetworkDag] ✨ Setting response for", data.agent, ":", shortStatus)
          
          // Update agent with current response
          setAgents((prev) =>
            prev.map((a) =>
              a.id === agent.id
                ? { ...a, currentResponse: shortStatus, isGlowing: true }
                : a
            )
          )
          
          // Clear response after 5 seconds
          setTimeout(() => {
            setAgents((prev) =>
              prev.map((a) =>
                a.id === agent.id && a.currentResponse === shortStatus
                  ? { ...a, currentResponse: undefined, isGlowing: false }
                  : a
              )
            )
          }, 5000)
        } else {
          console.log("[AgentNetworkDag] ⚠️ Agent not found:", data.agent, "Available:", agentsRef.current.map(a => a.name))
        }
      }
    }

    // Handle outgoing agent messages (Host Agent -> Remote Agent)
    const handleOutgoingMessage = (data: any) => {
      console.log("[AgentNetworkDag] 📤 Outgoing message:", data)
      
      if (data.targetAgent && data.message) {
        // Find the HOST agent (the one sending the message)
        const hostAgent = agentsRef.current.find(a => a.type === "host")
        if (hostAgent) {
          console.log("[AgentNetworkDag] 📨 Setting outgoing message on Host Agent to", data.targetAgent)
          
          setAgents((prev) =>
            prev.map((a) =>
              a.type === "host"
                ? { 
                    ...a, 
                    outgoingMessage: data.message,
                    outgoingMessageTarget: data.targetAgent
                  }
                : a
            )
          )
          
          // Clear outgoing message after 8 seconds
          setTimeout(() => {
            setAgents((prev) =>
              prev.map((a) =>
                a.type === "host" && a.outgoingMessage === data.message
                  ? { 
                      ...a, 
                      outgoingMessage: undefined,
                      outgoingMessageTarget: undefined
                    }
                  : a
              )
            )
          }, 8000)
        } else {
          console.log("[AgentNetworkDag] ⚠️ Host agent not found")
        }
      }
    }

    // Handle file uploaded (for all files in DAG)
    const handleFileUploaded = (data: any) => {
      console.log("[AgentNetworkDag] 📎 File uploaded:", data)
      
      if (data.fileInfo && data.fileInfo.source_agent && data.fileInfo.uri) {
        const sourceAgent = data.fileInfo.source_agent
        const fileUri = data.fileInfo.uri
        const fileName = data.fileInfo.filename || "unknown"
        const contentType = data.fileInfo.content_type || ""
        
        const agent = agentsRef.current.find(a => a.name === sourceAgent || a.id === sourceAgent)
        if (agent) {
          console.log("[AgentNetworkDag] 📄 File generated by", sourceAgent, ":", fileName, `(${contentType})`)
          
          // Store both image and file info
          const isImage = contentType.startsWith("image/")
          
          setAgents((prev) =>
            prev.map((a) =>
              a.id === agent.id
                ? { 
                    ...a, 
                    generatedImageUrl: isImage ? fileUri : undefined,
                    generatedImageFilename: fileName, // Store filename for all file types
                    generatedFileUrl: fileUri,
                    generatedFileType: contentType
                  }
                : a
            )
          )
          
          // Clear file after 10 seconds
          setTimeout(() => {
            setAgents((prev) =>
              prev.map((a) =>
                a.id === agent.id && a.generatedFileUrl === fileUri
                  ? { 
                      ...a, 
                      generatedImageUrl: undefined, 
                      generatedImageFilename: undefined,
                      generatedFileUrl: undefined,
                      generatedFileType: undefined
                    }
                  : a
              )
            )
          }, 10000)
        } else {
          console.log("[AgentNetworkDag] ⚠️ Agent not found for file:", sourceAgent, "Available:", agentsRef.current.map(a => a.name))
        }
      }
    }

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
    subscribe("file", handleFileUploaded)
    subscribe("outgoing_agent_message", handleOutgoingMessage)

    console.log("[AgentNetworkDag] ✅ All WebSocket listeners registered")

    return () => {
      console.log("[AgentNetworkDag] 🔌 Unsubscribing from WebSocket events")
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
      unsubscribe("file", handleFileUploaded)
      unsubscribe("outgoing_agent_message", handleOutgoingMessage)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subscribe, unsubscribe])

  // Highlight active node
  useEffect(() => {
    if (!activeNodeId) return

    setAgents((prev) =>
      prev.map((agent) => ({
        ...agent,
        isGlowing: agent.id === activeNodeId || agent.name === activeNodeId,
      }))
    )

    const timer = setTimeout(() => {
      setAgents((prev) =>
        prev.map((agent) => ({
          ...agent,
          isGlowing: false,
        }))
      )
    }, 2000)

    return () => clearTimeout(timer)
  }, [activeNodeId])

  const triggerGlow = (agentId: string) => {
    setAgents((prev) => prev.map((agent) => (agent.id === agentId ? { ...agent, isGlowing: true } : agent)))

    setTimeout(() => {
      setAgents((prev) => prev.map((agent) => (agent.id === agentId ? { ...agent, isGlowing: false } : agent)))
    }, 2000)
  }

  const addThoughtBubble = (agentId: string, text: string) => {
    const id = `thought-${Date.now()}-${Math.random()}`
    const startTime = Date.now()
    setThoughtBubbles((prev) => [
      ...prev,
      { id, agentId, text, y: 0, opacity: 1, startTime }
    ])

    // Auto-remove after 3 seconds
    setTimeout(() => {
      setThoughtBubbles((prev) => prev.filter((bubble) => bubble.id !== id))
    }, 3000)
  }

  const easeOutCubic = (t: number): number => {
    return 1 - Math.pow(1 - t, 3)
  }

  // Animate glow intensity (throttled to reduce overhead)
  useEffect(() => {
    let animationFrameId: number
    let lastTime = 0
    const throttleMs = 50 // Only update every 50ms instead of every frame

    const animateGlow = (currentTime: number) => {
      if (currentTime - lastTime >= throttleMs) {
        lastTime = currentTime
        
        setAgents((prev) => {
          let hasChanges = false
          const updated = prev.map((agent) => {
            if (!agent.isGlowing && agent.glowIntensity > 0) {
              hasChanges = true
              return { ...agent, glowIntensity: Math.max(0, agent.glowIntensity - 0.05) }
            } else if (agent.isGlowing && agent.glowIntensity < 1) {
              hasChanges = true
              const newIntensity = agent.glowIntensity + 0.08
              return { ...agent, glowIntensity: Math.min(1, newIntensity) }
            }
            return agent
          })
          return hasChanges ? updated : prev
        })
      }
      animationFrameId = requestAnimationFrame(animateGlow)
    }

    animationFrameId = requestAnimationFrame(animateGlow)

    return () => cancelAnimationFrame(animationFrameId)
  }, [])

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

      // Background (before transformations)
      const bgGradient = ctx.createLinearGradient(0, 0, 0, rect.height)
      bgGradient.addColorStop(0, "hsl(222.2 47.4% 11.2%)")
      bgGradient.addColorStop(1, "hsl(220 17% 17%)")
      ctx.fillStyle = bgGradient
      ctx.fillRect(0, 0, rect.width, rect.height)

      // Apply zoom and pan transformations
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

      // Draw connections
      const hostAgent = agents.find((a) => a.type === "host")
      if (hostAgent) {
        agents.forEach((agent) => {
          if (agent.type !== "host") {
            const gradient = ctx.createLinearGradient(
              centerX,
              centerY,
              centerX + agent.x,
              centerY + agent.y
            )
            gradient.addColorStop(0, `${hostAgent.color}80`)
            gradient.addColorStop(1, `${agent.color}80`)

            ctx.shadowColor = `${hostAgent.color}60`
            ctx.shadowBlur = 3
            ctx.beginPath()
            ctx.moveTo(centerX, centerY)
            ctx.lineTo(centerX + agent.x, centerY + agent.y)
            ctx.strokeStyle = gradient
            ctx.lineWidth = 2.5
            ctx.stroke()
            ctx.shadowBlur = 0
          }
        })
      }

      // Draw agents
      agents.forEach((agent) => {
        const x = centerX + agent.x
        const y = centerY + agent.y

        // Simplified glow effect (less expensive)
        if (agent.glowIntensity > 0.1) {
          const rgb = agent.color.match(/\w\w/g)?.map((x) => Number.parseInt(x, 16)) || [99, 102, 241]
          const maxRadius = 60

          const gradient = ctx.createRadialGradient(x, y, 0, x, y, maxRadius)
          gradient.addColorStop(0, `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${agent.glowIntensity * 0.2})`)
          gradient.addColorStop(1, `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, 0)`)

          ctx.fillStyle = gradient
          ctx.fillRect(x - maxRadius, y - maxRadius, maxRadius * 2, maxRadius * 2)
        }

        ctx.save()
        ctx.translate(x, y)

        // Draw icon based on type
        if (agent.type === "host") {
          drawHostIcon(ctx, agent.status)
        } else {
          drawAgentIcon(ctx, agent.color, agent.status)
        }

        ctx.restore()

        // Agent name with wrapping for long names
        // Reduced shadow for better performance
        ctx.shadowColor = "rgba(0, 0, 0, 0.5)"
        ctx.shadowBlur = 2
        ctx.fillStyle = "#f1f5f9"
        ctx.font = "600 11px system-ui"
        ctx.textAlign = "center"
        
        const maxWidth = 140
        const words = agent.name.split(' ')
        const lines: string[] = []
        let currentLine = words[0]
        
        for (let i = 1; i < words.length; i++) {
          const testLine = currentLine + ' ' + words[i]
          const metrics = ctx.measureText(testLine)
          if (metrics.width > maxWidth) {
            lines.push(currentLine)
            currentLine = words[i]
          } else {
            currentLine = testLine
          }
        }
        lines.push(currentLine)
        
        // Draw lines (max 2 lines)
        const startY = y + 45 - (Math.min(lines.length, 2) - 1) * 6
        for (let i = 0; i < Math.min(lines.length, 2); i++) {
          let line = lines[i]
          if (i === 1 && lines.length > 2) {
            line = line.substring(0, 15) + '...'
          }
          ctx.fillText(line, x, startY + i * 12)
        }
        
        ctx.shadowBlur = 0

        // Task state indicator
        if (agent.status !== "idle") {
          const statusText = agent.status === "working" ? "●" : agent.status === "completed" ? "✓" : "✗"
          const statusColor = 
            agent.status === "working" ? "#f59e0b" : 
            agent.status === "completed" ? "#10b981" : 
            "#ef4444"
          
          ctx.fillStyle = statusColor
          ctx.font = "bold 16px system-ui"
          ctx.fillText(statusText, x + 20, y - 20)
        }

        // Outgoing message display (Host Agent -> Remote Agent)
        if (agent.outgoingMessage && agent.outgoingMessageTarget) {
          // Use Host Agent's color (it's coming FROM the host)
          const messageColor = agent.color
          
          ctx.save()
          
          ctx.font = "12px system-ui"
          const maxWidth = 250
          const words = agent.outgoingMessage.split(' ')
          const lines: string[] = []
          let currentLine = words[0]
          
          for (let i = 1; i < words.length; i++) {
            const testLine = currentLine + ' ' + words[i]
            const metrics = ctx.measureText(testLine)
            if (metrics.width > maxWidth && currentLine.length > 0) {
              lines.push(currentLine)
              currentLine = words[i]
            } else {
              currentLine = testLine
            }
          }
          lines.push(currentLine)
          
          // Show more lines for full message (limit to 8 lines for outgoing messages)
          const displayLines = lines.slice(0, 8)
          if (lines.length > 8) {
            displayLines[7] = displayLines[7].substring(0, 30) + '...'
          }
          
          const lineHeight = 15
          const padding = 10
          const boxWidth = maxWidth + padding * 2
          const labelSpace = 20 // Extra space for label and gap
          const boxHeight = displayLines.length * lineHeight + padding * 2 + labelSpace
          
          // Position message above Host Agent (centered) or beside remote agents
          let messageX: number
          let messageY: number
          
          if (agent.type === "host") {
            // Host Agent: center message above it
            messageX = x - boxWidth / 2
            messageY = y - 150 // Position above agent with proper gap
          } else {
            // Remote agents: position beside the agent on the same side
            const isRightSide = agent.x > 0
            const messageDistance = 100
            messageX = isRightSide ? x + messageDistance : x - messageDistance - boxWidth
            messageY = y
          }
          
          // Draw outgoing message box with solid dark background (same as response)
          const boxGradient = ctx.createLinearGradient(
            messageX,
            messageY - boxHeight / 2,
            messageX + boxWidth,
            messageY + boxHeight / 2
          )
          boxGradient.addColorStop(0, "#1e293b")
          boxGradient.addColorStop(1, "#0f172a")
          
          ctx.shadowColor = "rgba(0, 0, 0, 0.3)"
          ctx.shadowBlur = 4
          
          ctx.fillStyle = boxGradient
          ctx.strokeStyle = messageColor
          ctx.lineWidth = 2
          
          ctx.beginPath()
          ctx.roundRect(
            messageX,
            messageY - boxHeight / 2,
            boxWidth,
            boxHeight,
            8
          )
          ctx.fill()
          ctx.stroke()
          ctx.shadowBlur = 0
          
          // Add "To [Agent Name]" label
          ctx.fillStyle = messageColor
          ctx.font = "600 10px system-ui"
          ctx.textAlign = "left"
          ctx.fillText(`📤 To ${agent.outgoingMessageTarget}`, messageX + padding, messageY - boxHeight / 2 + padding + 8)
          
          // Draw message lines (with more spacing after label)
          ctx.fillStyle = "#e2e8f0"
          ctx.font = "12px system-ui"
          ctx.textAlign = "left"
          
          for (let i = 0; i < displayLines.length; i++) {
            ctx.fillText(
              displayLines[i],
              messageX + padding,
              messageY - boxHeight / 2 + padding + 28 + i * lineHeight // Increased from 22 to 28
            )
          }
          
          ctx.restore()
        }

        // Current response display (beside the agent on the same side)
        if (agent.currentResponse) {
          ctx.save()
          
          ctx.font = "12px system-ui"
          const maxWidth = 250
          const words = agent.currentResponse.split(' ')
          const lines: string[] = []
          let currentLine = words[0]
          
          for (let i = 1; i < words.length; i++) {
            const testLine = currentLine + ' ' + words[i]
            const metrics = ctx.measureText(testLine)
            if (metrics.width > maxWidth && currentLine.length > 0) {
              lines.push(currentLine)
              currentLine = words[i]
            } else {
              currentLine = testLine
            }
          }
          lines.push(currentLine)
          
          // Show more lines for full message (limit to 10 lines for very long messages)
          const displayLines = lines.slice(0, 10)
          if (lines.length > 10) {
            displayLines[9] = displayLines[9].substring(0, 30) + '...'
          }
          
          const lineHeight = 15
          const padding = 10
          const boxWidth = maxWidth + padding * 2
          const labelSpace = 20 // Extra space for label and gap
          const boxHeight = displayLines.length * lineHeight + padding * 2 + labelSpace
          
          // Position message above Host Agent or beside remote agents
          let responseX: number
          let responseY: number
          
          if (agent.type === "host") {
            // Host Agent: center message above it (above outgoing message if it exists)
            const outgoingMessageOffset = agent.outgoingMessage ? 140 : 0 // Extra space if outgoing message exists
            responseX = x - boxWidth / 2
            responseY = y - 150 - outgoingMessageOffset // Position above agent with proper gap
          } else {
            // Remote agents: position beside the agent on the same side
            const isRightSide = agent.x > 0
            const messageDistance = 100
            responseX = isRightSide ? x + messageDistance : x - messageDistance - boxWidth
            // Vertical offset: if outgoing message exists, shift response down to avoid overlap
            const verticalOffset = agent.outgoingMessage ? 120 : 0
            responseY = y + verticalOffset
          }
          
          // Draw response box with agent color
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
          ctx.strokeStyle = agent.color
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
          ctx.fillStyle = agent.color
          ctx.font = "600 10px system-ui"
          ctx.textAlign = "left"
          ctx.fillText(`📥 From ${agent.name}`, responseX + padding, responseY - boxHeight / 2 + padding + 8)
          
          // Draw message text (with more spacing after label)
          ctx.fillStyle = "#e2e8f0"
          ctx.font = "12px system-ui"
          ctx.textAlign = "left"
          
          for (let i = 0; i < displayLines.length; i++) {
            ctx.fillText(
              displayLines[i],
              responseX + padding,
              responseY - boxHeight / 2 + padding + 28 + i * lineHeight // Increased from 22 to 28
            )
          }
          
          ctx.restore()
        }

        // Generated file/image display (below the text response)
        const hasImage = agent.generatedImageUrl
        const hasNonImageFile = agent.generatedFileUrl && !agent.generatedImageUrl
        const hasAnyFile = hasImage || hasNonImageFile
        
        // Calculate position below text response (if it exists) or below agent icon
        let fileDisplayY = y + 70 // Default: below agent icon
        let fileDisplayCenterX = x // Default: center under agent
        
        if (agent.currentResponse) {
          // Use EXACT same calculations as text rendering above
          const maxWidth = 250
          
          ctx.font = "12px system-ui"
          const words = agent.currentResponse.split(' ')
          const lines: string[] = []
          let currentLine = words[0]
          
          for (let i = 1; i < words.length; i++) {
            const testLine = currentLine + ' ' + words[i]
            const metrics = ctx.measureText(testLine)
            if (metrics.width > maxWidth && currentLine.length > 0) {
              lines.push(currentLine)
              currentLine = words[i]
            } else {
              currentLine = testLine
            }
          }
          lines.push(currentLine)
          
          const displayLines = lines.slice(0, 10)
          const lineHeight = 15
          const padding = 10
          const labelSpace = 20 // Extra space for label and gap
          const boxHeight = displayLines.length * lineHeight + padding * 2 + labelSpace
          const textBoxWidth = maxWidth + padding * 2
          
          let responseX: number
          let responseY: number
          
          if (agent.type === "host") {
            // Host Agent: files go below the response message which is above the agent
            const outgoingMessageOffset = agent.outgoingMessage ? 140 : 0
            responseX = x - textBoxWidth / 2
            responseY = y - 150 - outgoingMessageOffset
            
            // Position file below response message + 20px gap
            fileDisplayY = responseY + boxHeight / 2 + 20
            fileDisplayCenterX = x // Centered under host agent
          } else {
            // Remote agents: files go beside the agent and below response
            const isRightSide = agent.x > 0
            const messageDistance = 100
            const verticalOffset = agent.outgoingMessage ? 120 : 0
            responseY = y + verticalOffset
            responseX = isRightSide ? x + messageDistance : x - messageDistance - textBoxWidth
            
            // Position below the bottom of text box (responseY + boxHeight/2) + 20px gap
            fileDisplayY = responseY + boxHeight / 2 + 20
            fileDisplayCenterX = responseX + textBoxWidth / 2
          }
        }
        
        if (hasImage && agent.generatedImageUrl) {
          const imageUrl = agent.generatedImageUrl // Capture for type safety
          const imageSize = 120
          
          // Center image using the calculated fileDisplayCenterX
          const imageX = fileDisplayCenterX - imageSize / 2
          const imageY = fileDisplayY
          
          ctx.save()
          
          // Draw image background
          ctx.shadowColor = "rgba(0, 0, 0, 0.3)"
          ctx.shadowBlur = 4
          ctx.fillStyle = "#1e293b"
          ctx.strokeStyle = agent.color
          ctx.lineWidth = 3
          
          ctx.beginPath()
          ctx.roundRect(imageX - 4, imageY - 4, imageSize + 8, imageSize + 8, 8)
          ctx.fill()
          ctx.stroke()
          ctx.shadowBlur = 0
          
          // Load and draw image using cache
          let img = imageCache.current.get(imageUrl)
          if (!img) {
            // Create new image and add to cache
            img = new Image()
            const imgRef = img // Capture for closure
            // Note: Not setting crossOrigin since Azure Blob Storage SAS tokens work without CORS headers
            imgRef.onload = () => {
              console.log("[AgentNetworkDag] ✅ Image loaded successfully:", imageUrl)
              console.log("[AgentNetworkDag] Image dimensions:", imgRef.naturalWidth, "x", imgRef.naturalHeight)
              // Trigger re-render by updating agents state
              setAgents(prev => [...prev])
            }
            imgRef.onerror = (e) => {
              console.log("[AgentNetworkDag] ❌ Failed to load image:", imageUrl)
              console.log("[AgentNetworkDag] Error details:", e)
              // Remove from cache so it can be retried
              imageCache.current.delete(imageUrl)
            }
            console.log("[AgentNetworkDag] 📥 Starting image load:", imageUrl.substring(0, 100) + "...")
            imgRef.src = imageUrl
            imageCache.current.set(imageUrl, imgRef)
          }
          
          // Draw the image if it's loaded
          if (img && img.complete && img.naturalWidth > 0) {
            console.log("[AgentNetworkDag] Image status - complete:", img.complete, "naturalWidth:", img.naturalWidth)
            ctx.save()
            ctx.beginPath()
            ctx.roundRect(imageX, imageY, imageSize, imageSize, 4)
            ctx.clip()
            ctx.drawImage(img, imageX, imageY, imageSize, imageSize)
            ctx.restore()
          } else {
            // Show loading indicator
            ctx.fillStyle = "#475569"
            ctx.font = "12px system-ui"
            ctx.textAlign = "center"
            ctx.fillText("Loading...", x, imageY + imageSize / 2)
          }
          
          // Draw filename below the image (centered under the image)
          if (agent.generatedImageFilename) {
            ctx.fillStyle = "#94a3b8"
            ctx.font = "600 10px system-ui"
            ctx.textAlign = "center"
            const filenameY = imageY + imageSize + 18
            const filenameCenterX = imageX + imageSize / 2
            
            // Truncate long filenames
            let displayName = agent.generatedImageFilename
            if (displayName.length > 20) {
              displayName = displayName.substring(0, 17) + "..."
            }
            
            ctx.fillText(`📎 ${displayName}`, filenameCenterX, filenameY)
          }
          
          ctx.restore()
        }
        
        // Display non-image files (PDFs, docs, etc.)
        if (hasNonImageFile && agent.generatedFileUrl) {
          const fileY = fileDisplayY
          const boxWidth = 200
          const boxHeight = 60
          
          // Center file box using the calculated fileDisplayCenterX
          const boxX = fileDisplayCenterX - boxWidth / 2
          
          ctx.save()
          
          // Draw file box background
          ctx.shadowColor = "rgba(0, 0, 0, 0.3)"
          ctx.shadowBlur = 4
          ctx.fillStyle = "#1e293b"
          ctx.strokeStyle = agent.color
          ctx.lineWidth = 3
          
          ctx.beginPath()
          ctx.roundRect(boxX, fileY, boxWidth, boxHeight, 8)
          ctx.fill()
          ctx.stroke()
          ctx.shadowBlur = 0
          
          // Get file icon based on type
          let fileIcon = "📄"
          const contentType = agent.generatedFileType || ""
          if (contentType.includes("pdf")) fileIcon = "📕"
          else if (contentType.includes("word") || contentType.includes("document")) fileIcon = "📘"
          else if (contentType.includes("excel") || contentType.includes("spreadsheet")) fileIcon = "📗"
          else if (contentType.includes("powerpoint") || contentType.includes("presentation")) fileIcon = "📙"
          else if (contentType.includes("text")) fileIcon = "📝"
          else if (contentType.includes("json") || contentType.includes("xml")) fileIcon = "📋"
          
          // Draw file icon (center of the box)
          const boxCenterX = boxX + boxWidth / 2
          ctx.font = "32px system-ui"
          ctx.textAlign = "center"
          ctx.fillText(fileIcon, boxCenterX, fileY + 35)
          
          // Draw filename below icon
          if (agent.generatedImageFilename) {
            ctx.fillStyle = "#94a3b8"
            ctx.font = "600 10px system-ui"
            const filenameY = fileY + boxHeight + 12
            
            // Truncate long filenames
            let displayName = agent.generatedImageFilename
            if (displayName.length > 25) {
              displayName = displayName.substring(0, 22) + "..."
            }
            
            ctx.fillText(`📎 ${displayName}`, boxCenterX, filenameY)
          }
          
          ctx.restore()
        }

        // Thought bubbles (keeping these for status updates)
        const agentBubbles = thoughtBubbles.filter((bubble) => bubble.agentId === agent.id)
        const now = Date.now()
        agentBubbles.forEach((bubble) => {
          // Calculate animation progress based on time
          const elapsed = now - bubble.startTime
          const duration = 3000
          const progress = Math.min(elapsed / duration, 1)
          const easedProgress = easeOutCubic(progress)
          
          // Calculate y position and opacity
          const animY = easedProgress * 80
          let opacity = 1
          if (progress > 0.6) {
            const fadeProgress = (progress - 0.6) / 0.4
            opacity = 1 - easeOutCubic(fadeProgress)
          }
          
          ctx.save()
          ctx.globalAlpha = opacity

          const bubbleX = x
          const bubbleY = y - 50 - animY

          ctx.font = "11px system-ui"
          const textWidth = ctx.measureText(bubble.text).width
          const bubbleWidth = Math.min(Math.max(textWidth + 20, 100), 200)
          const bubbleHeight = 32

          const bubbleGradient = ctx.createLinearGradient(
            bubbleX - bubbleWidth / 2,
            bubbleY - bubbleHeight / 2,
            bubbleX + bubbleWidth / 2,
            bubbleY + bubbleHeight / 2
          )
          bubbleGradient.addColorStop(0, "#334155")
          bubbleGradient.addColorStop(1, "#1e293b")

          ctx.shadowColor = "rgba(0, 0, 0, 0.3)"
          ctx.shadowBlur = 4
          ctx.fillStyle = bubbleGradient
          ctx.strokeStyle = "#475569"
          ctx.lineWidth = 1.5

          ctx.beginPath()
          ctx.roundRect(
            bubbleX - bubbleWidth / 2,
            bubbleY - bubbleHeight / 2,
            bubbleWidth,
            bubbleHeight,
            12
          )
          ctx.fill()
          ctx.stroke()

          // Bubble tail
          ctx.beginPath()
          ctx.arc(bubbleX - 8, bubbleY + bubbleHeight / 2 + 4, 3, 0, Math.PI * 2)
          ctx.fill()
          ctx.stroke()

          ctx.shadowBlur = 0
          ctx.fillStyle = "#e2e8f0"
          ctx.font = "600 10px system-ui"
          ctx.textAlign = "center"
          ctx.fillText(bubble.text, bubbleX, bubbleY + 3, bubbleWidth - 16)

          ctx.restore()
        })
      })
      
      // Restore canvas state (undo zoom/pan transformations)
      ctx.restore()
    }

    let animationFrameId: number
    let isAnimating = true

    const animate = () => {
      if (!isAnimating) return
      draw()
      animationFrameId = requestAnimationFrame(animate)
    }

    animationFrameId = requestAnimationFrame(animate)

    return () => {
      isAnimating = false
      cancelAnimationFrame(animationFrameId)
    }
  }, [agents, thoughtBubbles])

  // Mouse wheel zoom
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault()
      
      // Zoom in/out with mouse wheel
      const zoomFactor = e.deltaY > 0 ? 0.95 : 1.05
      const newZoom = zoomRef.current * zoomFactor
      // Clamp zoom between 0.1x and 5x
      zoomRef.current = Math.max(0.1, Math.min(5, newZoom))
    }

    canvas.addEventListener('wheel', handleWheel, { passive: false })
    return () => canvas.removeEventListener('wheel', handleWheel)
  }, [])

  // Mouse drag to pan
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    
    let isPanningLocal = false

    const handleMouseDown = (e: MouseEvent) => {
      isPanningLocal = true
      setIsPanning(true)
      panStartRef.current = { 
        x: e.clientX - panOffsetRef.current.x, 
        y: e.clientY - panOffsetRef.current.y 
      }
    }

    const handleMouseMove = (e: MouseEvent) => {
      if (!isPanningLocal) return
      panOffsetRef.current = {
        x: e.clientX - panStartRef.current.x,
        y: e.clientY - panStartRef.current.y
      }
    }

    const handleMouseUp = () => {
      isPanningLocal = false
      setIsPanning(false)
    }

    canvas.addEventListener('mousedown', handleMouseDown)
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)

    return () => {
      canvas.removeEventListener('mousedown', handleMouseDown)
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [])

  // Reset zoom and pan (double-click)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const handleDoubleClick = () => {
      zoomRef.current = 1
      panOffsetRef.current = { x: 0, y: 0 }
    }

    canvas.addEventListener('dblclick', handleDoubleClick)
    return () => canvas.removeEventListener('dblclick', handleDoubleClick)
  }, [])

  // Keyboard shortcuts for zoom
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // + or = key to zoom in
      if (e.key === '+' || e.key === '=') {
        e.preventDefault()
        zoomRef.current = Math.min(5, zoomRef.current * 1.1)
      }
      // - or _ key to zoom out
      else if (e.key === '-' || e.key === '_') {
        e.preventDefault()
        zoomRef.current = Math.max(0.1, zoomRef.current * 0.9)
      }
      // 0 key to reset zoom and pan
      else if (e.key === '0') {
        e.preventDefault()
        zoomRef.current = 1
        panOffsetRef.current = { x: 0, y: 0 }
      }
      // F key to toggle fullscreen
      else if (e.key === 'f' || e.key === 'F') {
        e.preventDefault()
        toggleFullscreen()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  // Fullscreen functionality
  const toggleFullscreen = () => {
    if (!containerRef.current) return
    
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen().catch((err) => {
        console.error(`Error attempting to enable fullscreen: ${err.message}`)
      })
    } else {
      document.exitFullscreen()
    }
  }

  // Track fullscreen state changes
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement)
    }

    document.addEventListener('fullscreenchange', handleFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange)
  }, [])

  const drawAgentIcon = (ctx: CanvasRenderingContext2D, color: string, status: Agent["status"]) => {
    const size = 18

    // Outer hexagon
    ctx.strokeStyle = color
    ctx.lineWidth = status === "working" ? 3 : 2.5
    ctx.shadowColor = color
    ctx.shadowBlur = status === "working" ? 4 : 2
    ctx.beginPath()
    for (let i = 0; i < 6; i++) {
      const angle = (Math.PI / 3) * i - Math.PI / 2
      const x = Math.cos(angle) * size
      const y = Math.sin(angle) * size
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.closePath()
    ctx.stroke()
    ctx.shadowBlur = 0

    // Inner hexagon
    ctx.fillStyle = color
    ctx.beginPath()
    for (let i = 0; i < 6; i++) {
      const angle = (Math.PI / 3) * i - Math.PI / 2
      const x = Math.cos(angle) * (size * 0.65)
      const y = Math.sin(angle) * (size * 0.65)
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.closePath()
    ctx.fill()

    // Center circle
    ctx.fillStyle = "#ffffff"
    ctx.beginPath()
    ctx.arc(0, 0, size * 0.3, 0, Math.PI * 2)
    ctx.fill()
  }

  const drawHostIcon = (ctx: CanvasRenderingContext2D, status: Agent["status"]) => {
    const size = 22

    ctx.save()
    ctx.rotate(Math.PI / 4)

    ctx.strokeStyle = HOST_COLOR
    ctx.lineWidth = status === "working" ? 3.5 : 3
    ctx.shadowColor = HOST_COLOR
    ctx.shadowBlur = status === "working" ? 5 : 3
    ctx.strokeRect(-size, -size, size * 2, size * 2)
    ctx.shadowBlur = 0

    ctx.fillStyle = HOST_COLOR
    ctx.fillRect(-size * 0.65, -size * 0.65, size * 1.3, size * 1.3)

    ctx.restore()

    ctx.fillStyle = "#ffffff"
    ctx.beginPath()
    ctx.arc(0, 0, size * 0.45, 0, Math.PI * 2)
    ctx.fill()

    ctx.fillStyle = HOST_COLOR
    ctx.beginPath()
    ctx.arc(0, 0, size * 0.28, 0, Math.PI * 2)
    ctx.fill()
  }

  const drawUserIcon = (ctx: CanvasRenderingContext2D, status: Agent["status"]) => {
    const size = 16

    // Head
    ctx.fillStyle = USER_COLOR
    ctx.shadowColor = USER_COLOR
    ctx.shadowBlur = status === "working" ? 4 : 2
    ctx.beginPath()
    ctx.arc(0, -size * 0.6, size * 0.45, 0, Math.PI * 2)
    ctx.fill()
    ctx.shadowBlur = 0

    // Body
    ctx.beginPath()
    ctx.moveTo(-size * 0.45, 0)
    ctx.lineTo(size * 0.45, 0)
    ctx.lineTo(size * 0.6, size * 0.9)
    ctx.lineTo(-size * 0.6, size * 0.9)
    ctx.closePath()
    ctx.fill()

    // Face
    ctx.fillStyle = "#ffffff"
    ctx.beginPath()
    ctx.arc(-size * 0.15, -size * 0.65, 2, 0, Math.PI * 2)
    ctx.arc(size * 0.15, -size * 0.65, 2, 0, Math.PI * 2)
    ctx.fill()
  }

  return (
    <div ref={containerRef} className="w-full h-full flex items-center justify-center bg-slate-900 relative">
      <canvas 
        ref={canvasRef} 
        className="w-full h-full" 
        style={{ 
          minHeight: "420px",
          cursor: isPanning ? 'grabbing' : 'grab'
        }} 
      />
      
      {/* Fullscreen toggle button */}
      <button
        onClick={toggleFullscreen}
        className="absolute top-4 right-4 p-2 bg-slate-800/80 hover:bg-slate-700/80 text-slate-300 rounded-lg shadow-lg backdrop-blur-sm transition-all duration-200 border border-slate-700/50 hover:border-slate-600 z-10"
        title={isFullscreen ? "Exit fullscreen (F)" : "Enter fullscreen (F)"}
      >
        {isFullscreen ? (
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M8 3v3a2 2 0 0 1-2 2H3"/>
            <path d="M21 8h-3a2 2 0 0 1-2-2V3"/>
            <path d="M3 16h3a2 2 0 0 1 2 2v3"/>
            <path d="M16 21v-3a2 2 0 0 1 2-2h3"/>
          </svg>
        ) : (
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M8 3H5a2 2 0 0 0-2 2v3"/>
            <path d="M21 8V5a2 2 0 0 0-2-2h-3"/>
            <path d="M3 16v3a2 2 0 0 0 2 2h3"/>
            <path d="M16 21h3a2 2 0 0 0 2-2v-3"/>
          </svg>
        )}
      </button>
    </div>
  )
}

// Memoize to prevent unnecessary re-renders
export const AgentNetworkDag = memo(AgentNetworkDagComponent)

