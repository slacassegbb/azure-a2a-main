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
}

interface ThoughtBubble {
  id: string
  agentId: string
  text: string
  y: number
  opacity: number
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
  const [agents, setAgents] = useState<Agent[]>([])
  const [thoughtBubbles, setThoughtBubbles] = useState<ThoughtBubble[]>([])
  const [hasInitialized, setHasInitialized] = useState(false)
  const colorMapRef = useRef<Map<string, string>>(new Map())
  const agentsRef = useRef<Agent[]>([])
  
  // WebSocket connection for real-time updates
  const { subscribe, unsubscribe } = useEventHub()

  // Keep agents ref in sync
  useEffect(() => {
    agentsRef.current = agents
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
            const radius = 200
            
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
        const radius = 200

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
    setThoughtBubbles((prev) => [...prev, { id, agentId, text, y: 0, opacity: 1 }])

    const duration = 3000
    const startTime = Date.now()

    const animate = () => {
      const elapsed = Date.now() - startTime
      const progress = Math.min(elapsed / duration, 1)
      const easedProgress = easeOutCubic(progress)

      let opacity = 1
      if (progress > 0.6) {
        const fadeProgress = (progress - 0.6) / 0.4
        opacity = 1 - easeOutCubic(fadeProgress)
      }

      setThoughtBubbles((prev) =>
        prev.map((bubble) =>
          bubble.id === id
            ? {
                ...bubble,
                y: easedProgress * 80,
                opacity: opacity,
              }
            : bubble
        )
      )

      if (progress < 1) {
        requestAnimationFrame(animate)
      } else {
        setThoughtBubbles((prev) => prev.filter((bubble) => bubble.id !== id))
      }
    }

    requestAnimationFrame(animate)
  }

  const easeOutCubic = (t: number): number => {
    return 1 - Math.pow(1 - t, 3)
  }

  // Animate glow intensity
  useEffect(() => {
    let animationFrameId: number

    const animateGlow = () => {
      setAgents((prev) =>
        prev.map((agent) => {
          if (!agent.isGlowing && agent.glowIntensity > 0) {
            return { ...agent, glowIntensity: Math.max(0, agent.glowIntensity - 0.05) }
          } else if (agent.isGlowing) {
            const newIntensity = agent.glowIntensity + 0.08
            if (newIntensity >= 1) {
              return { ...agent, glowIntensity: 1 }
            }
            return { ...agent, glowIntensity: newIntensity }
          }
          return agent
        })
      )
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

      // Background
      const bgGradient = ctx.createLinearGradient(0, 0, 0, rect.height)
      bgGradient.addColorStop(0, "hsl(222.2 47.4% 11.2%)")
      bgGradient.addColorStop(1, "hsl(220 17% 17%)")
      ctx.fillStyle = bgGradient
      ctx.fillRect(0, 0, rect.width, rect.height)

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
            ctx.shadowBlur = 8
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

        // Glow effect
        if (agent.glowIntensity > 0) {
          const rgb = agent.color.match(/\w\w/g)?.map((x) => Number.parseInt(x, 16)) || [99, 102, 241]
          const pulseScale = 1 + Math.sin(Date.now() / 300) * 0.1
          const maxRadius = 60 * pulseScale

          const gradient = ctx.createRadialGradient(x, y, 0, x, y, maxRadius)
          gradient.addColorStop(0, `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${agent.glowIntensity * 0.3})`)
          gradient.addColorStop(0.5, `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${agent.glowIntensity * 0.15})`)
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
        ctx.shadowColor = "rgba(0, 0, 0, 0.8)"
        ctx.shadowBlur = 4
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

        // Current response display (to the side)
        if (agent.currentResponse) {
          // Smart positioning: draw on left if agent is on right half, otherwise right
          const isRightSide = agent.x > 0
          const responseOffset = isRightSide ? -330 : 80
          const responseX = x + responseOffset
          const responseY = y

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
          const boxHeight = displayLines.length * lineHeight + padding * 2
          
          // Draw response box with agent color
          const boxGradient = ctx.createLinearGradient(
            responseX,
            responseY - boxHeight / 2,
            responseX + boxWidth,
            responseY + boxHeight / 2
          )
          boxGradient.addColorStop(0, "#1e293b")
          boxGradient.addColorStop(1, "#0f172a")
          
          ctx.shadowColor = "rgba(0, 0, 0, 0.5)"
          ctx.shadowBlur = 12
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
          
          // Draw text
          ctx.fillStyle = "#e2e8f0"
          ctx.font = "600 10px system-ui"
          ctx.textAlign = "left"
          
          displayLines.forEach((line, i) => {
            ctx.fillText(
              line,
              responseX + padding,
              responseY - boxHeight / 2 + padding + (i + 1) * lineHeight
            )
          })
          
          ctx.restore()
        }

        // Thought bubbles (keeping these for status updates)
        const agentBubbles = thoughtBubbles.filter((bubble) => bubble.agentId === agent.id)
        agentBubbles.forEach((bubble) => {
          ctx.save()
          ctx.globalAlpha = bubble.opacity

          const bubbleX = x
          const bubbleY = y - 50 - bubble.y

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

          ctx.shadowColor = "rgba(0, 0, 0, 0.5)"
          ctx.shadowBlur = 10
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
    }

    const animationFrame = requestAnimationFrame(function animate() {
      draw()
      requestAnimationFrame(animate)
    })

    return () => cancelAnimationFrame(animationFrame)
  }, [agents, thoughtBubbles])

  const drawAgentIcon = (ctx: CanvasRenderingContext2D, color: string, status: Agent["status"]) => {
    const size = 18

    // Outer hexagon
    ctx.strokeStyle = color
    ctx.lineWidth = status === "working" ? 3 : 2.5
    ctx.shadowColor = color
    ctx.shadowBlur = status === "working" ? 10 : 6
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
    ctx.shadowBlur = status === "working" ? 14 : 10
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
    ctx.shadowBlur = status === "working" ? 10 : 6
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
    <div className="w-full h-full flex items-center justify-center bg-slate-900">
      <canvas ref={canvasRef} className="w-full h-full" style={{ minHeight: "420px" }} />
    </div>
  )
}

// Memoize to prevent unnecessary re-renders
export const AgentNetworkDag = memo(AgentNetworkDagComponent)

