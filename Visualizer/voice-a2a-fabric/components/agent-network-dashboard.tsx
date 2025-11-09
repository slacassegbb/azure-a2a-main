"use client"

import type React from "react"

import { useEffect, useRef, useState, useCallback } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Badge } from "@/components/ui/badge"
import { Activity, Cpu, Network, Plus, Pencil, Mic, MicOff, Phone } from "lucide-react"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useEventHub } from "@/hooks/use-event-hub"
import { useVoiceLive } from "@/hooks/use-voice-live"
import { VOICE_SCENARIOS, getScenarioById } from "@/lib/voice-scenarios"

type AgentType = "host" | "remote" | "human"

interface AgentSkill {
  id: string
  name: string
  description: string
  tags: string[]
  examples: string[]
  inputModes?: string[]
  outputModes?: string[]
}

interface Agent {
  id: string
  name: string
  type: AgentType
  status: "active" | "idle"
  x: number
  y: number
  isGlowing: boolean
  glowIntensity: number
  parentId?: string
  description: string
  skills: AgentSkill[]
  color: string
}

interface Message {
  id: string
  agentId: string
  agentName: string
  content: string
  timestamp: Date
  type: "event" | "input_required" | "response"
}

interface KPI {
  title: string
  value: string
  change: string
  icon: React.ReactNode
}

interface TerminalEvent {
  id: string
  agentId: string
  agentName: string
  action: string
  details: string
  timestamp: Date
  level: "info" | "success" | "warning" | "error"
}

interface ThoughtBubble {
  id: string
  agentId: string
  text: string
  y: number
  opacity: number
}

interface CatalogAgent {
  id: string
  name: string
  description: string
  skills: string[]
  category: string
  rating: number
  downloads: number
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

const shuffleArray = <T,>(array: T[]): T[] => {
  const shuffled = [...array]
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]]
  }
  return shuffled
}

const getUniqueColors = (count: number): string[] => {
  const shuffled = shuffleArray(AGENT_COLORS)
  return shuffled.slice(0, count)
}

const generateGlowGradient = (baseColor: string): [string, string] => {
  const colors = AGENT_COLORS.filter((c) => c !== baseColor)
  const secondColor = colors[Math.floor(Math.random() * colors.length)]
  return [baseColor, secondColor]
}

export function AgentNetworkDashboard() {
  const DEBUG = process.env.NEXT_PUBLIC_DEBUG_LOGS === 'true'
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const messageIdCounter = useRef(0) // Counter for unique message IDs
  const [isSimulating, setIsSimulating] = useState(false)
  const [thoughtBubbles, setThoughtBubbles] = useState<ThoughtBubble[]>([])
  const [hasInitialized, setHasInitialized] = useState(false)
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null)
  const [eventCount, setEventCount] = useState(0)
  const [avgResponseTime, setAvgResponseTime] = useState(0)
  const [processingAgents, setProcessingAgents] = useState<Set<string>>(new Set()) // Track which agents are processing
  const [finalResponse, setFinalResponse] = useState<string>("")
  const [showResponsePanel, setShowResponsePanel] = useState(false)
  const [isClearingMemory, setIsClearingMemory] = useState(false)
  const [requestMessage, setRequestMessage] = useState("Analyze the current network performance and provide optimization recommendations")
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false)
  const [editedMessage, setEditedMessage] = useState("")

  // Get WebSocket connection from EventHub
  const { subscribe, unsubscribe, sendMessage, isConnected } = useEventHub()

  // Voice scenario state - default to network outage scenario
  const [currentScenario, setCurrentScenario] = useState<any>(getScenarioById('network-outage'))
  const [pendingA2AResponse, setPendingA2AResponse] = useState<string | null>(null)
  const [pendingInjection, setPendingInjection] = useState<any>(null)
  const [pendingInjectionQueue, setPendingInjectionQueue] = useState<any[]>([])
  const pendingInjectionTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  
  // Map messageId -> callId to track which function call each response belongs to
  const pendingCallIdMapRef = useRef<Map<string, string>>(new Map())

  // Initialize Voice Live API with scenario support
  const voiceLive = useVoiceLive({
    foundryProjectUrl: process.env.NEXT_PUBLIC_AZURE_AI_FOUNDRY_PROJECT_ENDPOINT || '',
    model: process.env.NEXT_PUBLIC_VOICE_MODEL || 'gpt-4o-realtime',
    scenario: currentScenario,
    onToolCall: (toolName, args) => {
      console.log('[Dashboard] Tool called:', toolName, args)
      
      // Start pulsing the human operator (voice user) when they trigger a function call
      const humanId = 'human-1'
      setProcessingAgents((prev) => {
        const updated = new Set(prev)
        updated.add(humanId)
        if (DEBUG) console.log(`[Dashboard] Voice function call - started pulsing human operator: ${humanId}`)
        return updated
      })
    },
    onSendToA2A: async (message, claimData) => {
      console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
      console.log('[VOICE-A2A] 📤 STEP 1: onSendToA2A CALLED')
      console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
      console.log('[VOICE-A2A] Message:', message)
      console.log('[VOICE-A2A] Metadata:', claimData)
      
      // Generate IDs - unique messageId per call, shared conversationId for session
      const messageId = `voice-msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
      const conversationId = currentConversationId || `voice-${Date.now()}`
      const callId = claimData?.tool_call_id || claimData?.call_id || ''
      
      console.log('[VOICE-A2A] 🆔 Generated messageId:', messageId)
      console.log('[VOICE-A2A] 💬 ConversationId:', conversationId)
      console.log('[VOICE-A2A] 🔑 Extracted call_id:', callId)
      
      // Store conversationId for session, track THIS message for response matching
      setCurrentConversationId(conversationId)
      setPendingA2AResponse(messageId)
      
      // Map messageId -> callId so we can match responses to the right function call
      if (callId) {
        pendingCallIdMapRef.current.set(messageId, callId)
        console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
        console.log('[VOICE-A2A] 🔗 STEP 2: STORED messageId → call_id IN MAP')
        console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
        console.log('[VOICE-A2A] messageId:', messageId)
        console.log('[VOICE-A2A] call_id:', callId)
        console.log('[VOICE-A2A] Map size:', pendingCallIdMapRef.current.size)
      } else {
        console.warn('[VOICE-A2A] ⚠️ NO call_id in metadata!')
      }
      
      // Add user message to activity log
      addMessage('user', 'Voice User', message, 'event')
      
      // Start pulsing host agent
      const hostAgentId = 'contoso-concierge'
      setProcessingAgents((prev) => new Set(prev).add(hostAgentId))
      triggerGlow(hostAgentId)
      addMessage(hostAgentId, 'Contoso Concierge', 'Processing voice request and routing to agents...', 'event')
      
      // Send to backend using same endpoint and format as Send Request button
      try {
        const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
        const requestBody = {
          params: {
            messageId: messageId,
            contextId: conversationId,
            role: 'user',
            parts: [
              {
                root: {
                  kind: 'text',
                  text: message,
                }
              }
            ],
            agentMode: false,
            enableInterAgentMemory: false,
          }
        }
        
        console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
        console.log('[VOICE-A2A] 📤 STEP 3: SENDING HTTP REQUEST')
        console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
        console.log('[VOICE-A2A] URL:', `${baseUrl}/message/send`)
        
        const response = await fetch(`${baseUrl}/message/send`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(requestBody)
        })
        
        console.log('[VOICE-A2A] Response status:', response.status)
        
        if (!response.ok) {
          console.error('[Dashboard] ❌ Failed to send voice message:', response.statusText)
          // Stop host agent pulsing on error
          setProcessingAgents((prev) => {
            const next = new Set(prev)
            next.delete(hostAgentId)
            return next
          })
          return 'error'
        }
        
        console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
        console.log('[VOICE-A2A] ✅ STEP 4: HTTP REQUEST SUCCESSFUL')
        console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
        console.log('[VOICE-A2A] Now waiting for WebSocket assistant message...')
        
        return conversationId
      } catch (error) {
        console.error('[Dashboard] ❌ Error sending voice request to A2A:', error)
        // Stop pulsing on error
        setProcessingAgents((prev) => {
          const updated = new Set(prev)
          updated.delete(hostAgentId)
          updated.delete('human-1')
          return updated
        })
        return 'error'
      }
    }
  })

  const uniqueColors = getUniqueColors(3)

  // Start with just the Host Agent, populate remote agents from registry
  const [agents, setAgents] = useState<Agent[]>([
    {
      id: "contoso-concierge",
      name: "Contoso Concierge",
      type: "host",
      status: "active",
      x: 0,
      y: 0,
      isGlowing: false,
      glowIntensity: 0,
      description: "Central orchestrator managing all agent communication and workflow coordination",
      skills: [
        { id: "routing", name: "Request Routing", description: "Routes requests to agents", tags: [], examples: [] },
        { id: "balancing", name: "Load Balancing", description: "Balances load across agents", tags: [], examples: [] },
        { id: "registry", name: "Agent Registry", description: "Manages agent registry", tags: [], examples: [] },
        { id: "aggregation", name: "Response Aggregation", description: "Aggregates responses", tags: [], examples: [] },
      ],
      color: "#6366f1",
    },
  ])

  const [messages, setMessages] = useState<Message[]>([])
  const [terminalEvents, setTerminalEvents] = useState<TerminalEvent[]>([])
  const [kpis, setKpis] = useState<KPI[]>([
    {
      title: "Active Agents",
      value: "1",
      change: "+0%",
      icon: <Network className="h-4 w-4" />,
    },
    {
      title: "Events Processed",
      value: "0",
      change: "+0%",
      icon: <Activity className="h-4 w-4" />,
    },
    {
      title: "Response Time",
      value: "0ms",
      change: "-0%",
      icon: <Cpu className="h-4 w-4" />,
    },
  ])

  const [showCatalog, setShowCatalog] = useState(false)
  const [catalogAgents] = useState<CatalogAgent[]>([
    {
      id: "catalog-nlp",
      name: "NLP Agent",
      description: "Advanced natural language processing with sentiment analysis and entity extraction",
      skills: ["NER", "Sentiment Analysis", "Text Classification", "Language Detection"],
      category: "AI & ML",
      rating: 4.8,
      downloads: 1523,
    },
    {
      id: "catalog-vision",
      name: "Vision Agent",
      description: "Computer vision specialist for image recognition, object detection, and OCR",
      skills: ["Object Detection", "Image Classification", "OCR", "Face Recognition"],
      category: "AI & ML",
      rating: 4.9,
      downloads: 2104,
    },
    {
      id: "catalog-db",
      name: "Database Agent",
      description: "Multi-database connector supporting SQL and NoSQL with query optimization",
      skills: ["SQL", "MongoDB", "Redis", "Query Optimization"],
      category: "Data",
      rating: 4.7,
      downloads: 3421,
    },
    {
      id: "catalog-api",
      name: "API Gateway Agent",
      description: "RESTful API management with rate limiting, caching, and authentication",
      skills: ["REST API", "GraphQL", "Rate Limiting", "OAuth"],
      category: "Integration",
      rating: 4.6,
      downloads: 1876,
    },
    {
      id: "catalog-monitor",
      name: "Monitoring Agent",
      description: "Real-time system monitoring with alerting and performance analytics",
      skills: ["Metrics", "Alerting", "Logging", "Tracing"],
      category: "Operations",
      rating: 4.9,
      downloads: 2654,
    },
    {
      id: "catalog-security",
      name: "Security Agent",
      description: "Security scanning, threat detection, and compliance validation",
      skills: ["Threat Detection", "Vulnerability Scanning", "Compliance", "Encryption"],
      category: "Security",
      rating: 4.8,
      downloads: 1987,
    },
  ])

  const addThoughtBubble = (agentId: string, text: string) => {
    const id = `thought-${Date.now()}-${Math.random()}`
    
    let startY = 0
    
    // Use functional update to get latest state and calculate position
    setThoughtBubbles((prev) => {
      // Find existing bubbles for this agent to calculate starting position
      const agentBubbles = prev.filter(b => b.agentId === agentId)
      const maxY = agentBubbles.length > 0 
        ? Math.max(...agentBubbles.map(b => b.y)) 
        : 0
      startY = maxY + 50 // Start 50px above the highest existing bubble (increased spacing)
      
      return [...prev, { id, agentId, text, y: startY, opacity: 1 }]
    })

    const duration = 4320
    const startTime = Date.now()

    const animate = () => {
      const elapsed = Date.now() - startTime
      const progress = Math.min(elapsed / duration, 1)
      const easedProgress = easeOutCubic(progress)

      let opacity = 1
      if (progress > 0.6) {
        const fadeProgress = (progress - 0.6) / 0.4 // Map 0.6-1.0 to 0-1
        opacity = 1 - easeOutCubic(fadeProgress) // Smooth cubic easing for fade
      }

      setThoughtBubbles((prev) =>
        prev.map((bubble) =>
          bubble.id === id
            ? {
                ...bubble,
                y: startY + (easedProgress * 100), // Drift up 100 pixels from starting position
                opacity: opacity,
              }
            : bubble,
        ),
      )

      if (progress < 1) {
        requestAnimationFrame(animate)
      } else {
        setThoughtBubbles((prev) => prev.filter((bubble) => bubble.id !== id))
      }
    }

    requestAnimationFrame(animate)
  }

  const addTerminalEvent = (
    agentId: string,
    agentName: string,
    action: string,
    details: string,
    level: TerminalEvent["level"] = "info",
  ) => {
    setTerminalEvents((prev) => [
      {
        id: `term-${Date.now()}-${Math.random()}`,
        agentId,
        agentName,
        action,
        details,
        timestamp: new Date(),
        level,
      },
      ...prev.slice(0, 99),
    ])
  }

  const agentOutputs = {
    host: [
      "Request received from client, parsing payload and routing to appropriate agents for processing",
      "Validating authentication tokens and checking user permissions for requested operation security compliance",
      "Orchestrating multi-agent workflow, distributing tasks based on agent capabilities and current load",
      "Aggregating results from all remote agents and compiling comprehensive response for client delivery",
    ],
    remote: [
      "Analyzing incoming data stream using ML model v2.4, detecting patterns and anomalies in real time",
      "Executing database query optimization, reducing lookup time from 450ms to 78ms through index",
      "Processing 1,247 records through validation pipeline, maintaining 99.2% accuracy rate across all checks",
      "Running sentiment analysis on user feedback corpus, identifying key themes and customer satisfaction",
      "Generating synthetic data samples for model training, ensuring balanced distribution across all classes",
      "Transforming raw telemetry into structured format, normalizing timestamps and standardizing units of measurement",
    ],
    human: [
      "Reviewing generated analysis report for accuracy and compliance with regulatory standards and policies",
      "Approving deployment of model updates to production environment after validation of test metrics",
      "Evaluating edge cases flagged by automated systems, applying human judgment to ambiguous scenarios",
      "Providing feedback on agent performance and recommending parameter adjustments for optimization tasks",
    ],
  }

  const getAgentOutput = (agentType: AgentType): string => {
    const outputs =
      agentType === "host" ? agentOutputs.host : agentType === "human" ? agentOutputs.human : agentOutputs.remote
    const fullOutput = outputs[Math.floor(Math.random() * outputs.length)]
    return fullOutput.split(" ").slice(0, 10).join(" ") + "..."
  }

  useEffect(() => {
    setAgents((prev) => {
      return prev.map((agent, index) => {
        if (agent.type === "host") {
          return { ...agent, x: 0, y: 0 }
        }

        const remoteAgents = prev.filter((a) => a.type === "remote")
        const agentIndex = remoteAgents.findIndex((a) => a.id === agent.id)
        const totalRemote = remoteAgents.length
        const angle = (agentIndex / totalRemote) * 2 * Math.PI
        const radius = 200

        return {
          ...agent,
          x: Math.cos(angle) * radius,
          y: Math.sin(angle) * radius,
        }
      })
    })
  }, [])

  useEffect(() => {
    if (!hasInitialized) {
      agents.forEach((agent, index) => {
        setTimeout(() => {
          addMessage(agent.id, agent.name, `${agent.name} connected to network`, "event")
        }, index * 300)
      })
      setHasInitialized(true)
    }
  }, [hasInitialized, agents])

  const triggerGlow = (agentId: string) => {
    setAgents((prev) => prev.map((agent) => (agent.id === agentId ? { ...agent, isGlowing: true } : agent)))

    setTimeout(() => {
      setAgents((prev) => prev.map((agent) => (agent.id === agentId ? { ...agent, isGlowing: false } : agent)))
    }, 2000)
  }

  const addMessage = (agentId: string, agentName: string, content: string, type: Message["type"]) => {
    messageIdCounter.current += 1
    const uniqueId = `msg-${Date.now()}-${messageIdCounter.current}-${Math.random().toString(36).substring(2, 9)}`
    setMessages((prev) => [
      {
        id: uniqueId,
        agentId,
        agentName,
        content,
        timestamp: new Date(),
        type,
      },
      ...prev,
    ])
    setEventCount((prev) => prev + 1)
  }

  // WebSocket Event Handlers
  useEffect(() => {
    if (DEBUG) console.log("[AgentDashboard] Setting up WebSocket event handlers")

    // Handle agent registry sync - populate agents from backend
    const handleAgentRegistrySync = (data: any) => {
      if (DEBUG) console.log("[AgentDashboard] Agent registry sync received:", data)
      
      if (data.agents && Array.isArray(data.agents)) {
        const colors = getUniqueColors(data.agents.length)
        
        // Calculate circular positioning for remote agents
        const numAgents = data.agents.length
        const radius = 350 // Distance from center - increased for better spacing
        
        // Keep the host agent, add remote agents from registry
        const remoteAgents = data.agents.map((agent: any, index: number) => {
          const agentId = agent.name.toLowerCase().replace(/\s+/g, '-')
          
          // Calculate position in circle
          const angle = (index / numAgents) * 2 * Math.PI
          const x = Math.cos(angle) * radius
          const y = Math.sin(angle) * radius
          
          // Ensure skills are properly extracted (backend sends full skill objects)
          const skills = (agent.skills || []).map((skill: any) => ({
            id: skill.id || '',
            name: skill.name || '',
            description: skill.description || '',
            tags: skill.tags || [],
            examples: skill.examples || [],
            inputModes: skill.inputModes || [],
            outputModes: skill.outputModes || []
          }))

          if (DEBUG) console.log(`[AgentDashboard] Agent ${agent.name} has ${skills.length} skills:`, skills.map((s: any) => s.name))
          
          return {
            id: agentId,
            name: agent.name,
            type: 'remote' as AgentType,
            status: agent.status === 'online' ? 'active' as const : 'idle' as const,
            x: x,
            y: y,
            isGlowing: false,
            glowIntensity: 0,
            description: agent.description || 'Remote agent',
            skills: skills,
            color: colors[index % colors.length],
          }
        })

        // Create human operator nodes for agents with HITL skill
        const humanOperators: Agent[] = []
        remoteAgents.forEach((agent: Agent, index: number) => {
          const hasHITL = agent.skills.some((skill: AgentSkill) => 
            skill.name === "Human-in-the-Loop" || 
            skill.id === "hitl" || 
            skill.tags?.includes('human-in-loop') ||
            skill.tags?.includes('human-in-the-loop')
          )
          
          if (hasHITL) {
            // Calculate human operator position (further out from the agent)
            const angle = (index / numAgents) * 2 * Math.PI
            const humanRadius = radius + 150 // 150px further out
            const humanX = Math.cos(angle) * humanRadius
            const humanY = Math.sin(angle) * humanRadius
            
            humanOperators.push({
              id: `${agent.id}-human`,
              name: `Human Operator (${agent.name})`,
              type: 'human' as AgentType,
              status: 'idle' as const,
              x: humanX,
              y: humanY,
              isGlowing: false,
              glowIntensity: 0,
              parentId: agent.id,
              description: `Human operator for ${agent.name}`,
              skills: [],
              color: '#14b8a6', // Teal color for humans
            })
          }
        })

        setAgents((prev) => {
          const hostAgent = prev.find((a) => a.type === 'host')
          return hostAgent ? [hostAgent, ...remoteAgents, ...humanOperators] : [...remoteAgents, ...humanOperators]
        })

        // Update KPIs
        setKpis((prev) => [
          {
            ...prev[0],
            value: String(remoteAgents.length + 1), // +1 for host
          },
          prev[1],
          prev[2],
        ])

        if (DEBUG) console.log(`[AgentDashboard] Populated ${remoteAgents.length} remote agents`)
      }
    }

    // Handle task updates (agent processing)
    const handleTaskUpdated = (data: any) => {
      if (DEBUG) console.log("[AgentDashboard] Task updated:", data)
      
      // Extract agentName from the event data - if not provided, skip
      const agentName = data.agentName
      if (!agentName) {
        if (DEBUG) console.log("[AgentDashboard] No agentName in task update, skipping")
        return
      }
      
      const state = data.state || data.status || 'Processing'
      const agentId = agentName.toLowerCase().replace(/\s+/g, '-')

      if (DEBUG) console.log(`[AgentDashboard] Task update for agent: ${agentName} (${agentId}), state: ${state}`)

      // Only start pulsing for in_progress, queued, or requires_action states
      if (state === 'in_progress' || state === 'queued' || state === 'requires_action' || state === 'created') {
        // Mark agent as processing (will keep pulsing)
        setProcessingAgents((prev) => {
          const next = new Set(prev)
          next.add(agentId)
          if (DEBUG) console.log(`[AgentDashboard] Started pulsing for: ${agentId}`)
          
          // If requires_action, also pulse the human operator
          if (state === 'requires_action') {
            const humanId = `${agentId}-human`
            next.add(humanId)
            if (DEBUG) console.log(`[AgentDashboard] HITL required - started pulsing human operator: ${humanId}`)
          }
          
          return next
        })

        // Trigger glow for the agent
        triggerGlow(agentId)
        
        // If requires_action, trigger glow for human operator too
        if (state === 'requires_action') {
          const humanId = `${agentId}-human`
          triggerGlow(humanId)
          addMessage(humanId, 'Human Operator', `Awaiting human response for ${agentName}`, "event")
          setTimeout(() => {
            addThoughtBubble(humanId, 'Reviewing request...')
          }, Math.random() * 300)
        }
        
        // Add message to activity log
        addMessage(agentId, agentName, `${agentName}: ${state}`, "event")
        
        // Add thought bubble with delay to show over time
        setTimeout(() => {
          addThoughtBubble(agentId, state === 'requires_action' ? 'Requesting human input' : state)
        }, Math.random() * 300)

        // Update agent status to active
        setAgents((prev) =>
          prev.map((agent) =>
            agent.id === agentId || agent.name === agentName
              ? { ...agent, status: 'active' as const }
              : agent
          )
        )
      } else if (state === 'completed' || state === 'failed' || state === 'cancelled') {
        // Stop pulsing when task completes
        setProcessingAgents((prev) => {
          const next = new Set(prev)
          next.delete(agentId)
          // Also stop pulsing the human operator if exists
          const humanId = `${agentId}-human`
          next.delete(humanId)
          if (DEBUG) console.log(`[AgentDashboard] Stopped pulsing for: ${agentId} and ${humanId}`)
          return next
        })
      }
    }

    // Handle messages from agents
    const handleMessage = (data: any) => {
      console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
      console.log('[VOICE-A2A] 📬 WebSocket message event received')
      console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
      console.log('[VOICE-A2A] data.role:', data.role)
      console.log('[VOICE-A2A] data.messageId:', data.messageId)
      console.log('[VOICE-A2A] data.message_id:', data.message_id)
      console.log('[VOICE-A2A] data.contextId:', data.contextId)
      console.log('[VOICE-A2A] Full data:', JSON.stringify(data, null, 2))
      
      // Extract agentName from the event data - if not provided, use 'System' for system messages
      const agentName = data.agentName || 'System'
      const agentId = agentName.toLowerCase().replace(/\s+/g, '-')
      
      let messageText = ''
      if (data.content && Array.isArray(data.content)) {
        const textContent = data.content.find((c: any) => c.type === 'text')
        messageText = textContent?.content || ''
      } else if (data.message) {
        messageText = data.message
      }

      if (messageText) {
        // Stop processing pulse for this specific agent when they send a message
        setProcessingAgents((prev) => {
          const next = new Set(prev)
          next.delete(agentId)
          if (DEBUG) console.log(`[AgentDashboard] Agent ${agentId} sent message, stopped pulsing`)
          return next
        })

        // If this is the final assistant response (from host agent), stop host pulsing
        if (data.role === 'assistant') {
          setFinalResponse(messageText)
          setShowResponsePanel(true)
          
          // Check if this response is for a pending Voice Live call
          const responseConversationId = data.conversation_id || data.contextId || data.conversationId
          
          console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
          console.log('[VOICE-A2A] 📬 STEP 5: Checking for voice call match by contextId')
          console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
          console.log('[VOICE-A2A] responseConversationId:', responseConversationId)
          console.log('[VOICE-A2A] Map size:', pendingCallIdMapRef.current.size)
          console.log('[VOICE-A2A] Map keys:', Array.from(pendingCallIdMapRef.current.keys()))
          
          // Find the messageId that matches this contextId
          // Our messageId format: voice-msg-{timestamp}-{random}
          // Our contextId format: voice-{timestamp}
          let matchedCallId: string | null = null
          let matchedMessageId: string | null = null
          
          for (const [messageId, callId] of pendingCallIdMapRef.current.entries()) {
            if (messageId.startsWith('voice-msg-')) {
              const timestamp = messageId.split('-')[2]
              const expectedContextId = `voice-${timestamp}`
              console.log('[VOICE-A2A] Checking messageId:', messageId, '→ contextId:', expectedContextId)
              if (expectedContextId === responseConversationId) {
                matchedCallId = callId
                matchedMessageId = messageId
                console.log('[VOICE-A2A] ✅ MATCH FOUND!')
                break
              }
            }
          }
          
          console.log('[VOICE-A2A] Final matched call_id:', matchedCallId)
          
          if (matchedCallId && matchedMessageId) {
            console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
            console.log('[VOICE-A2A] ✅ STEP 6: This is a voice response!')
            console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
            console.log('[VOICE-A2A] Message preview:', messageText.substring(0, 150))
            console.log('[VOICE-A2A] call_id:', matchedCallId)
            
            const callId = matchedCallId
            
            if (callId) {
              // Add response to queue WITH call_id
              const newResponse = {
                call_id: callId,
                claim_id: responseConversationId,
                status: 'completed',
                message: messageText,
                next_steps: [],
                timestamp: Date.now()
              }
              
              console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
              console.log('[VOICE-A2A] 📦 STEP 6: ADDING TO INJECTION QUEUE')
              console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
              console.log('[VOICE-A2A] call_id:', callId)
              setPendingInjectionQueue(prev => [...prev, newResponse])
              console.log('[VOICE-A2A] ✅ Response added to queue')
              
              // Clear mappings
              pendingCallIdMapRef.current.delete(matchedMessageId!)
              console.log('[VOICE-A2A] 🗑️ Cleared messageId from map')
            } else {
              console.warn('[VOICE-A2A] ❌ NO call_id found in map!')
            }
          } else {
            console.log('[VOICE-A2A] ℹ️ No pending voice call match for this contextId')
          }
          
          // Stop host agent pulsing
          setProcessingAgents((prev) => {
            const next = new Set(prev)
            next.delete('host')
            next.delete('foundry-host')
            next.delete('contoso-concierge')
            if (DEBUG) console.log('[AgentDashboard] Final response received, stopped host pulsing')
            return next
          })
          
          setIsSimulating(false)
        }

        // Trigger glow
        triggerGlow(agentId)
        
        // Add to activity log
        const shortMessage = messageText.split(' ').slice(0, 15).join(' ') + (messageText.split(' ').length > 15 ? '...' : '')
        addMessage(agentId, agentName, shortMessage, data.role === 'user' ? 'event' : 'response')
        
        // Add thought bubble with delay
        setTimeout(() => {
          addThoughtBubble(agentId, shortMessage)
        }, Math.random() * 300)

        // Calculate and update average response time
        setAvgResponseTime((prev) => Math.floor((prev * 0.8 + Math.random() * 200 + 50)))
      }
    }

    // Handle shared inference started
    const handleSharedInferenceStarted = (data: any) => {
      if (DEBUG) console.log("[AgentDashboard] Shared inference started:", data)
      // Don't start pulsing here - it's already started in simulateRequest
      // This just sets the flag
      setIsSimulating(true)
    }

    // Handle shared inference ended
    const handleSharedInferenceEnded = (data: any) => {
      if (DEBUG) console.log("[AgentDashboard] Shared inference ended:", data)
      setProcessingAgents(new Set()) // Clear all processing agents
      setIsSimulating(false)
    }

    // Handle task created
    const handleTaskCreated = (data: any) => {
      if (DEBUG) console.log("[AgentDashboard] Task created:", data)
      
      // task_created events don't include agentName - they represent the initial task creation
      // Default to "Contoso Concierge" since tasks are created when user sends request to host
      const agentName = data.agentName || 'Contoso Concierge'
      const agentId = agentName.toLowerCase().replace(/\s+/g, '-')
      
      if (DEBUG) console.log(`[AgentDashboard] Task created for agent: ${agentName} (${agentId})`)
      
      // Mark agent as processing
      setProcessingAgents((prev) => {
        const next = new Set(prev)
        next.add(agentId)
        if (DEBUG) console.log(`[AgentDashboard] Started pulsing for: ${agentId}`)
        return next
      })
      
      // Trigger glow
      triggerGlow(agentId)
      addMessage(agentId, agentName, `Task created for ${agentName}`, 'event')
      
      // Add thought bubble with delay
      setTimeout(() => {
        addThoughtBubble(agentId, 'Starting task...')
      }, Math.random() * 300)
    }

    // Handle tool calls
    const handleToolCall = (data: any) => {
      if (DEBUG) console.log("[AgentDashboard] Tool call:", data)
      // Use agentName from payload (sent by backend for both host and remote agents)
      const agentName = data.agentName || 'System'
      const agentId = agentName.toLowerCase().replace(/\s+/g, '-')
      const toolName = data.toolName || data.tool_name || 'tool'
      
      // Skip send_message tool calls as they're internal communication
      if (toolName.toLowerCase().includes('send_message') || toolName.toLowerCase().includes('sendmessage')) {
        triggerGlow(agentId)
        return
      }
      
      // Trigger glow for tool call
      triggerGlow(agentId)
      addMessage(agentId, agentName, `Using ${toolName}`, 'event')
      
      // Add thought bubble with delay
      setTimeout(() => {
        addThoughtBubble(agentId, `Using ${toolName}`)
      }, Math.random() * 400)
    }

    // Handle tool responses
    const handleToolResponse = (data: any) => {
      if (DEBUG) console.log("[AgentDashboard] Tool response:", data)
      // Use agentName from payload (sent by backend for both host and remote agents)
      const agentName = data.agentName || 'System'
      const agentId = agentName.toLowerCase().replace(/\s+/g, '-')
      const toolName = data.toolName || data.tool_name || 'tool'
      
      // Trigger glow for tool response
      triggerGlow(agentId)
      addMessage(agentId, agentName, `Tool response from: ${toolName}`, 'event')
      
      // Add thought bubble with delay
      setTimeout(() => {
        addThoughtBubble(agentId, `${toolName} completed`)
      }, Math.random() * 400)
    }

    // Handle inference steps
    const handleInferenceStep = (data: any) => {
      if (DEBUG) console.log("[AgentDashboard] Inference step:", data)
      // Use agentName from payload (sent by backend for both host and remote agents)
      const agentName = data.agentName || data.agent || 'System'
      const agentId = agentName.toLowerCase().replace(/\s+/g, '-')
      const status = data.status || 'processing'
      
      // Trigger glow
      triggerGlow(agentId)
      addMessage(agentId, agentName, `${agentName}: ${status}`, 'event')
      
      // Add thought bubble with delay
      setTimeout(() => {
        addThoughtBubble(agentId, status)
      }, Math.random() * 400)
    }

    // Handle remote agent activity
    const handleRemoteAgentActivity = (data: any) => {
      if (DEBUG) console.log("[AgentDashboard] Remote agent activity:", data)
      // Use agentName from payload (sent by backend for both host and remote agents)
      const agentName = data.agentName || 'System'
      const agentId = agentName.toLowerCase().replace(/\s+/g, '-')
      const activity = data.activity || 'active'
      
      // Only trigger glow, don't add message/bubble since tool_call events handle that
      triggerGlow(agentId)
    }

    // Handle conversation created
    const handleConversationCreated = (data: any) => {
      if (DEBUG) console.log("[AgentDashboard] Conversation created:", data)
      setCurrentConversationId(data.conversationId)
      
      // Trigger host agent glow
      triggerGlow('contoso-concierge')
      addMessage('contoso-concierge', 'Contoso Concierge', 'New conversation initiated', 'event')
    }

    // Handle general events
    const handleEvent = (data: any) => {
      if (DEBUG) console.log("[AgentDashboard] General event:", data)
      // Can add additional event handling here
    }

    // Subscribe to WebSocket events
    subscribe('agent_registry_sync', handleAgentRegistrySync)
    subscribe('task_updated', handleTaskUpdated)
    subscribe('task_created', handleTaskCreated)
    subscribe('message', handleMessage)
    subscribe('conversation_created', handleConversationCreated)
    subscribe('event', handleEvent)
    subscribe('shared_inference_started', handleSharedInferenceStarted)
    subscribe('shared_inference_ended', handleSharedInferenceEnded)
    subscribe('tool_call', handleToolCall)
    subscribe('tool_response', handleToolResponse)
    subscribe('inference_step', handleInferenceStep)
    subscribe('remote_agent_activity', handleRemoteAgentActivity)

    if (DEBUG) console.log("[AgentDashboard] WebSocket event handlers subscribed")

    // Cleanup subscriptions
    return () => {
      unsubscribe('agent_registry_sync', handleAgentRegistrySync)
      unsubscribe('task_updated', handleTaskUpdated)
      unsubscribe('task_created', handleTaskCreated)
      unsubscribe('message', handleMessage)
      unsubscribe('conversation_created', handleConversationCreated)
      unsubscribe('event', handleEvent)
      unsubscribe('shared_inference_started', handleSharedInferenceStarted)
      unsubscribe('shared_inference_ended', handleSharedInferenceEnded)
      unsubscribe('tool_call', handleToolCall)
      unsubscribe('tool_response', handleToolResponse)
      unsubscribe('inference_step', handleInferenceStep)
      unsubscribe('remote_agent_activity', handleRemoteAgentActivity)
      if (DEBUG) console.log("[AgentDashboard] WebSocket event handlers unsubscribed")
    }
  }, [subscribe, unsubscribe, DEBUG])

  // Process injection queue - inject next response when ready
  useEffect(() => {
    console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
    console.log('[VOICE-A2A] 🔄 STEP 7: INJECTION USEEFFECT TRIGGERED')
    console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
    console.log('[VOICE-A2A] Queue size:', pendingInjectionQueue.length)
    console.log('[VOICE-A2A] isRecording:', voiceLive.isRecording)
    console.log('[VOICE-A2A] isSpeaking:', voiceLive.isSpeaking)
    
    // Clear any existing timeout when dependencies change
    if (pendingInjectionTimeoutRef.current) {
      console.log('[Dashboard] 🗑️ Clearing existing injection timeout')
      clearTimeout(pendingInjectionTimeoutRef.current)
      pendingInjectionTimeoutRef.current = null
    }

    // Get next response from queue
    const nextResponse = pendingInjectionQueue[0]
    if (nextResponse) {
      console.log('[VOICE-A2A] Next response in queue - call_id:', nextResponse.call_id)
      
      // AI is still speaking - do nothing, wait for it to finish
      if (voiceLive.isSpeaking) {
        console.log('[VOICE-A2A] ⏳ AI still speaking, waiting...')
      }
      // AI finished speaking - set 2s timeout to give user chance to respond
      else if (!pendingInjectionTimeoutRef.current) {
        console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
        console.log('[VOICE-A2A] ⏰ STEP 8: AI finished speaking, setting 2s timeout')
        console.log('[VOICE-A2A] ════════════════════════════════════════════════════════')
        console.log('[Dashboard] ═══════════════════════════════════════════════════════')
        console.log('[Dashboard] ⏰ Setting 2s timeout - AI finished, waiting')
        console.log('[Dashboard] ═══════════════════════════════════════════════════════')
        
        pendingInjectionTimeoutRef.current = setTimeout(() => {
          console.log('[Dashboard] ═══════════════════════════════════════════════════════')
          console.log('[Dashboard] ⏰ TIMEOUT FIRED - Injecting proactively')
          console.log('[Dashboard] ═══════════════════════════════════════════════════════')
          console.log('[Dashboard] call_id:', nextResponse.call_id)
          console.log('[Dashboard] Message:', nextResponse.message.substring(0, 100) + '...')
          
          voiceLive.injectNetworkResponse(nextResponse)
          setPendingInjectionQueue(prev => prev.slice(1)) // Remove processed item
          
          // Stop pulsing human-1 after injection
          setProcessingAgents((prev) => {
            const next = new Set(prev)
            next.delete('human-1')
            if (DEBUG) console.log('[Dashboard] Voice response auto-injected after timeout, stopped pulsing human-1')
            return next
          })
        }, 2000)
      }
      // Case 3: AI still speaking OR user currently speaking - wait for it to finish
      else {
        console.log('[Dashboard] ═══════════════════════════════════════════════════════')
        console.log('[Dashboard] ⏸️ WAITING - Cannot inject yet')
        console.log('[Dashboard] ═══════════════════════════════════════════════════════')
        if (voiceLive.isSpeaking) {
          console.log('[Dashboard] Reason: AI still speaking')
        } else if (voiceLive.isRecording) {
          console.log('[Dashboard] Reason: User currently speaking')
        }
        console.log('[Dashboard] Will retry when state changes')
      }
    } else {
      console.log('[Dashboard] ℹ️ No responses in queue to inject')
    }

    // Cleanup timeout on unmount
    return () => {
      if (pendingInjectionTimeoutRef.current) {
        clearTimeout(pendingInjectionTimeoutRef.current)
        pendingInjectionTimeoutRef.current = null
      }
    }
  }, [pendingInjectionQueue, voiceLive.isRecording, voiceLive.isSpeaking, DEBUG])

  // Handle voice live state - make human operators pulse when recording or AI is speaking
  useEffect(() => {
    const isVoiceActive = voiceLive.isRecording || voiceLive.isSpeaking
    
    setProcessingAgents((prev) => {
      const next = new Set(prev)
      let changed = false
      
      agents.forEach((agent) => {
        if (agent.type === 'human') {
          if (isVoiceActive && !prev.has(agent.id)) {
            next.add(agent.id)
            triggerGlow(agent.id)
            changed = true
          } else if (!isVoiceActive && prev.has(agent.id)) {
            next.delete(agent.id)
            changed = true
          }
        }
      })
      
      return changed ? next : prev
    })
  }, [voiceLive.isRecording, voiceLive.isSpeaking])

  // Update KPIs periodically
  useEffect(() => {
    const interval = setInterval(() => {
      setKpis((prev) => [
        prev[0], // Keep active agents count
        {
          ...prev[1],
          value: String(eventCount),
        },
        {
          ...prev[2],
          value: `${avgResponseTime}ms`,
        },
      ])
    }, 1000)

    return () => clearInterval(interval)
  }, [eventCount, avgResponseTime])

  const openEditDialog = () => {
    setEditedMessage(requestMessage)
    setIsEditDialogOpen(true)
  }

  const saveEditedMessage = () => {
    setRequestMessage(editedMessage)
    setIsEditDialogOpen(false)
  }

  const clearMemory = async () => {
    setIsClearingMemory(true)
    try {
      const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
      const response = await fetch(`${baseUrl}/clear-memory`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      })

      const data = await response.json()

      if (data.success) {
        alert('Memory index cleared successfully!')
      } else {
        alert('Failed to clear memory: ' + (data.message || 'Unknown error'))
      }
    } catch (error) {
      console.error('[AgentDashboard] Error clearing memory:', error)
      alert('Error clearing memory: ' + error)
    } finally {
      setIsClearingMemory(false)
    }
  }

  const simulateRequest = async () => {
    if (!isConnected) {
      console.warn('[AgentDashboard] Not connected to backend, cannot send request')
      return
    }

    setIsSimulating(true)

    try {
      // Send HTTP POST to /message/send (like frontend does)
      const message = requestMessage
      const messageId = `viz-msg-${Date.now()}`
      const conversationId = currentConversationId || `viz-${Date.now()}`

      // Add user message to activity log immediately
      addMessage('user', 'Visualizer', message, 'event')

      // Start host agent pulsing immediately
      const hostAgentId = 'contoso-concierge'
      setProcessingAgents((prev) => new Set(prev).add(hostAgentId))
      triggerGlow(hostAgentId)
      addMessage(hostAgentId, 'Contoso Concierge', 'Processing request and routing to agents...', 'event')

      const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
      const response = await fetch(`${baseUrl}/message/send`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          params: {
            messageId: messageId,
            contextId: conversationId,
            role: 'user',
            parts: [
              {
                root: {
                  kind: 'text',
                  text: message,
                }
              }
            ],
            agentMode: false,
            enableInterAgentMemory: false,
          }
        })
      })

      if (!response.ok) {
        console.error('[AgentDashboard] Failed to send message to backend:', response.statusText)
        // Stop host agent pulsing on error
        setProcessingAgents((prev) => {
          const next = new Set(prev)
          next.delete(hostAgentId)
          return next
        })
        setIsSimulating(false)
        return
      }

      if (DEBUG) console.log('[AgentDashboard] Message sent to backend successfully via HTTP')
      
      // Update current conversation ID
      if (!currentConversationId) {
        setCurrentConversationId(conversationId)
      }

      // The response will come through WebSocket events (task_updated, message, etc.)
      
    } catch (error) {
      console.error('[AgentDashboard] Error sending message to backend:', error)
      // Stop host agent pulsing on error
      setProcessingAgents((prev) => {
        const next = new Set(prev)
        next.delete('contoso-concierge')
        return next
      })
    }

    setIsSimulating(false)
  }

  // Legacy simulation function (fallback if not connected)
  const simulateRequestOld = async () => {
    setIsSimulating(true)

    const hostAgent = agents.find((a) => a.type === "host")
    if (hostAgent) {
      triggerGlow(hostAgent.id)
      const output = getAgentOutput("host")
      addMessage(hostAgent.id, hostAgent.name, output, "event")
      addThoughtBubble(hostAgent.id, output)
      await new Promise((resolve) => setTimeout(resolve, 1000))
    }

    const otherAgents = agents.filter((a) => a.type !== "host")
    for (const agent of otherAgents) {
      triggerGlow(agent.id)
      const output = getAgentOutput(agent.type)
      addMessage(agent.id, agent.name, output, "event")
      addThoughtBubble(agent.id, output)
      await new Promise((resolve) => setTimeout(resolve, 1200))
    }

    if (hostAgent) {
      triggerGlow(hostAgent.id)
      const output = "Request completed successfully, all agents processed their tasks and returned results"
      const shortOutput = output.split(" ").slice(0, 10).join(" ") + "..."
      addMessage(hostAgent.id, hostAgent.name, shortOutput, "response")
      addThoughtBubble(hostAgent.id, shortOutput)
    }

    setKpis([
      {
        title: "Active Agents",
        value: String(agents.length),
        change: "+0%",
        icon: <Network className="h-4 w-4" />,
      },
      {
        title: "Events Processed",
        value: String(messages.length),
        change: "+12%",
        icon: <Activity className="h-4 w-4" />,
      },
      {
        title: "Response Time",
        value: `${Math.floor(Math.random() * 100 + 50)}ms`,
        change: "-8%",
        icon: <Cpu className="h-4 w-4" />,
      },
    ])

    setIsSimulating(false)
  }

  const easeOutCubic = (t: number): number => {
    return 1 - Math.pow(1 - t, 3)
  }

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
        }),
      )
      animationFrameId = requestAnimationFrame(animateGlow)
    }

    animationFrameId = requestAnimationFrame(animateGlow)

    return () => cancelAnimationFrame(animationFrameId)
  }, [])

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

      const bgGradient = ctx.createLinearGradient(0, 0, 0, rect.height)
      bgGradient.addColorStop(0, "#0f172a")
      bgGradient.addColorStop(1, "#1e293b")
      ctx.fillStyle = bgGradient
      ctx.fillRect(0, 0, rect.width, rect.height)

      ctx.strokeStyle = "rgba(148, 163, 184, 0.1)"
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

      const hostAgent = agents.find((a) => a.type === "host")
      if (hostAgent) {
        agents.forEach((agent) => {
          if (agent.type === "remote") {
            const gradient = ctx.createLinearGradient(centerX, centerY, centerX + agent.x, centerY + agent.y)
            gradient.addColorStop(0, "rgba(99, 102, 241, 0.6)")
            gradient.addColorStop(1, "rgba(236, 72, 153, 0.6)")

            ctx.shadowColor = "rgba(99, 102, 241, 0.5)"
            ctx.shadowBlur = 10
            ctx.beginPath()
            ctx.moveTo(centerX, centerY)
            ctx.lineTo(centerX + agent.x, centerY + agent.y)
            ctx.strokeStyle = gradient
            ctx.lineWidth = 3
            ctx.stroke()
            ctx.shadowBlur = 0
          }
        })
      }

      // Draw connections from agents to their human operators
      agents.forEach((agent) => {
        if (agent.type === "human" && agent.parentId) {
          const parentAgent = agents.find(a => a.id === agent.parentId)
          if (parentAgent) {
            const agentX = centerX + parentAgent.x
            const agentY = centerY + parentAgent.y
            const humanX = centerX + agent.x
            const humanY = centerY + agent.y

            ctx.shadowColor = "rgba(20, 184, 166, 0.4)"
            ctx.shadowBlur = 8
            ctx.beginPath()
            ctx.moveTo(agentX, agentY)
            ctx.lineTo(humanX, humanY)
            ctx.strokeStyle = "rgba(20, 184, 166, 0.6)"
            ctx.lineWidth = 2
            ctx.setLineDash([5, 5])
            ctx.stroke()
            ctx.setLineDash([])
            ctx.shadowBlur = 0
          }
        }
      })

      agents.forEach((agent) => {
        const x = centerX + agent.x
        const y = centerY + agent.y

        // Check if agent is processing (should keep pulsing)
        const isProcessing = processingAgents.has(agent.id)

        if (agent.glowIntensity > 0 || isProcessing) {
          const rgb = agent.color.match(/\w\w/g)?.map((x) => Number.parseInt(x, 16)) || [99, 102, 241]

          const pulseScale = 1 + Math.sin(Date.now() / 300) * 0.12

          const maxRadius = 70 * pulseScale
          const gradient = ctx.createRadialGradient(x, y, 0, x, y, maxRadius)

          gradient.addColorStop(0, `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${agent.glowIntensity * 0.1})`)
          gradient.addColorStop(0.3, `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${agent.glowIntensity * 0.3})`)
          gradient.addColorStop(0.6, `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${agent.glowIntensity * 0.6})`)
          gradient.addColorStop(0.85, `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${agent.glowIntensity * 0.8})`)
          gradient.addColorStop(1, `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, 0)`)

          ctx.fillStyle = gradient
          ctx.fillRect(x - maxRadius, y - maxRadius, maxRadius * 2, maxRadius * 2)
        }

        ctx.save()
        ctx.translate(x, y)

        if (agent.type === "host") {
          drawHostIcon(ctx)
        } else if (agent.type === "human") {
          drawHumanIcon(ctx)
        } else {
          drawBotIcon(ctx, agent.color)
        }

        ctx.restore()

        ctx.shadowColor = "rgba(0, 0, 0, 0.8)"
        ctx.shadowBlur = 6
        ctx.fillStyle = "#f1f5f9"
        ctx.font = "600 13px system-ui"
        ctx.textAlign = "center"
        ctx.fillText(agent.name, x, y + 50)
        ctx.shadowBlur = 0

        const agentBubbles = thoughtBubbles.filter((bubble) => bubble.agentId === agent.id)
        agentBubbles.forEach((bubble) => {
          ctx.save()
          ctx.globalAlpha = bubble.opacity

          const bubbleX = x
          const bubbleY = y - 60 - bubble.y

          const textWidth = ctx.measureText(bubble.text).width
          const bubbleWidth = Math.max(textWidth + 24, 120)
          const bubbleHeight = 40

          const bubbleGradient = ctx.createLinearGradient(
            bubbleX - bubbleWidth / 2,
            bubbleY - bubbleHeight / 2,
            bubbleX + bubbleWidth / 2,
            bubbleY + bubbleHeight / 2,
          )
          bubbleGradient.addColorStop(0, "#334155")
          bubbleGradient.addColorStop(1, "#1e293b")

          ctx.shadowColor = "rgba(0, 0, 0, 0.5)"
          ctx.shadowBlur = 12
          ctx.fillStyle = bubbleGradient
          ctx.strokeStyle = "#475569"
          ctx.lineWidth = 2

          ctx.beginPath()
          ctx.roundRect(bubbleX - bubbleWidth / 2, bubbleY - bubbleHeight / 2, bubbleWidth, bubbleHeight, 18)
          ctx.fill()
          ctx.stroke()

          ctx.shadowBlur = 8
          ctx.beginPath()
          ctx.arc(bubbleX - 12, bubbleY + bubbleHeight / 2 + 6, 5, 0, Math.PI * 2)
          ctx.fill()
          ctx.stroke()

          ctx.beginPath()
          ctx.arc(bubbleX - 6, bubbleY + bubbleHeight / 2 + 14, 3, 0, Math.PI * 2)
          ctx.fill()
          ctx.stroke()

          ctx.shadowBlur = 0
          ctx.fillStyle = "#e2e8f0"
          ctx.font = "600 11px system-ui"
          ctx.textAlign = "center"

          const maxWidth = bubbleWidth - 16
          if (textWidth > maxWidth) {
            const words = bubble.text.split(" ")
            let line = ""
            let y = bubbleY - 8
            for (let i = 0; i < words.length; i++) {
              const testLine = line + words[i] + " "
              const testWidth = ctx.measureText(testLine).width
              if (testWidth > maxWidth && i > 0) {
                ctx.fillText(line, bubbleX, y)
                line = words[i] + " "
                y += 14
              } else {
                line = testLine
              }
            }
            ctx.fillText(line, bubbleX, y)
          } else {
            ctx.fillText(bubble.text, bubbleX, bubbleY)
          }

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

  const drawBotIcon = (ctx: CanvasRenderingContext2D, color: string) => {
    const size = 20

    // Outer hexagon frame
    ctx.strokeStyle = color
    ctx.lineWidth = 3
    ctx.shadowColor = color
    ctx.shadowBlur = 8
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

    // Inner solid hexagon (smaller)
    ctx.fillStyle = color
    ctx.beginPath()
    for (let i = 0; i < 6; i++) {
      const angle = (Math.PI / 3) * i - Math.PI / 2
      const x = Math.cos(angle) * (size * 0.7)
      const y = Math.sin(angle) * (size * 0.7)
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.closePath()
    ctx.fill()

    // Central core circle
    ctx.fillStyle = "#ffffff"
    ctx.beginPath()
    ctx.arc(0, 0, size * 0.35, 0, Math.PI * 2)
    ctx.fill()

    // Three connection points
    ctx.fillStyle = color
    ctx.beginPath()
    ctx.arc(0, -size * 0.4, 3, 0, Math.PI * 2)
    ctx.fill()

    ctx.beginPath()
    ctx.arc(-size * 0.35, size * 0.2, 3, 0, Math.PI * 2)
    ctx.fill()

    ctx.beginPath()
    ctx.arc(size * 0.35, size * 0.2, 3, 0, Math.PI * 2)
    ctx.fill()
  }

  const drawHostIcon = (ctx: CanvasRenderingContext2D) => {
    const size = 24

    // Outer diamond/square rotated 45 degrees
    ctx.save()
    ctx.rotate(Math.PI / 4)

    // Outer frame
    ctx.strokeStyle = "#6366f1"
    ctx.lineWidth = 3.5
    ctx.shadowColor = "#6366f1"
    ctx.shadowBlur = 12
    ctx.strokeRect(-size, -size, size * 2, size * 2)
    ctx.shadowBlur = 0

    // Inner filled square
    ctx.fillStyle = "#6366f1"
    ctx.fillRect(-size * 0.7, -size * 0.7, size * 1.4, size * 1.4)

    ctx.restore()

    // Central circle overlay
    ctx.fillStyle = "#ffffff"
    ctx.beginPath()
    ctx.arc(0, 0, size * 0.5, 0, Math.PI * 2)
    ctx.fill()

    // Inner core
    ctx.fillStyle = "#6366f1"
    ctx.beginPath()
    ctx.arc(0, 0, size * 0.3, 0, Math.PI * 2)
    ctx.fill()

    // Four directional markers
    const markerPositions = [
      [0, -size * 0.85],
      [size * 0.85, 0],
      [0, size * 0.85],
      [-size * 0.85, 0],
    ]

    ctx.fillStyle = "#6366f1"
    markerPositions.forEach(([x, y]) => {
      ctx.beginPath()
      ctx.arc(x, y, 3.5, 0, Math.PI * 2)
      ctx.fill()
    })
  }

  const drawHumanIcon = (ctx: CanvasRenderingContext2D) => {
    const size = 16

    // Head
    ctx.fillStyle = "#14b8a6"
    ctx.shadowColor = "#14b8a6"
    ctx.shadowBlur = 8
    ctx.beginPath()
    ctx.arc(0, -size * 0.7, size * 0.5, 0, Math.PI * 2)
    ctx.fill()
    ctx.shadowBlur = 0

    // Body - sleek trapezoid
    ctx.beginPath()
    ctx.moveTo(-size * 0.5, 0)
    ctx.lineTo(size * 0.5, 0)
    ctx.lineTo(size * 0.65, size)
    ctx.lineTo(-size * 0.65, size)
    ctx.closePath()
    ctx.fill()

    // Arms
    ctx.lineWidth = 4
    ctx.strokeStyle = "#14b8a6"
    ctx.lineCap = "round"

    ctx.beginPath()
    ctx.moveTo(-size * 0.5, size * 0.2)
    ctx.lineTo(-size * 0.9, size * 0.7)
    ctx.stroke()

    ctx.beginPath()
    ctx.moveTo(size * 0.5, size * 0.2)
    ctx.lineTo(size * 0.9, size * 0.7)
    ctx.stroke()

    // Face details
    ctx.fillStyle = "#ffffff"
    ctx.beginPath()
    ctx.arc(-size * 0.15, -size * 0.75, 2, 0, Math.PI * 2)
    ctx.arc(size * 0.15, -size * 0.75, 2, 0, Math.PI * 2)
    ctx.fill()
  }

  return (
    <div className="flex h-screen bg-slate-900">
      <div className="w-80 border-r border-slate-700 bg-slate-800 flex flex-col">
        <div className="p-4 border-b border-slate-700">
          <h2 className="font-semibold text-lg text-slate-100">Activity Log</h2>
          <p className="text-sm text-slate-400">Real-time agent events</p>
        </div>
        <ScrollArea className="flex-1">
          <div className="p-4 space-y-3">
            {messages.map((message) => (
              <div
                key={message.id}
                className="border border-slate-600 rounded-lg p-3 bg-gradient-to-br from-slate-700 to-slate-800 shadow-lg transition-all hover:shadow-xl hover:border-slate-500"
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="font-semibold text-sm text-slate-100">{message.agentName}</span>
                  <Badge variant={message.type === "input_required" ? "destructive" : "secondary"} className="text-xs">
                    {message.type === "input_required" ? "Action Required" : "Event"}
                  </Badge>
                </div>
                <p className="text-sm text-slate-300 leading-relaxed">{message.content}</p>
                <p className="text-xs text-slate-500 mt-1">{message.timestamp.toLocaleTimeString()}</p>
              </div>
            ))}
          </div>
        </ScrollArea>
        
        {/* Voice Scenario Selector - Bottom of Sidebar */}
        <div className="p-4 border-t border-slate-700 bg-slate-800">
          <label className="text-xs text-slate-400 mb-2 block font-semibold">Voice Conversation Scenario</label>
          <Select
            value={currentScenario?.id || ''}
            onValueChange={(value) => {
              const scenario = getScenarioById(value)
              setCurrentScenario(scenario || null)
              console.log('[Dashboard] Scenario selected:', scenario?.name)
            }}
          >
            <SelectTrigger className="w-full bg-slate-700 text-slate-100 border-slate-600">
              <SelectValue placeholder="Select a scenario..." />
            </SelectTrigger>
            <SelectContent className="bg-slate-800 border-slate-700">
              {VOICE_SCENARIOS.map((scenario: any) => (
                <SelectItem key={scenario.id} value={scenario.id} className="text-slate-100">
                  <div className="flex flex-col">
                    <span>{scenario.name}</span>
                    {scenario.enableA2A && <span className="text-xs text-emerald-400">(A2A)</span>}
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {currentScenario && (
            <p className="text-xs text-slate-400 mt-2 leading-relaxed">{currentScenario.description}</p>
          )}
        </div>
      </div>

      <div className="flex-1 flex flex-col">
        <div className="flex-1 relative bg-slate-900">
          <div className="absolute top-4 left-4 z-10">
            <h1 className="text-2xl font-bold text-slate-100 drop-shadow-lg">Agent Network</h1>
            <p className="text-sm text-slate-400">A2A Multi-Agent System</p>
            <div className="flex items-center gap-2 mt-2">
              <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} />
              <span className="text-xs text-slate-400">
                {isConnected ? 'Connected to Backend' : 'Disconnected'}
              </span>
            </div>
            {voiceLive.isRecording && (
              <div className="flex items-center gap-2 mt-1">
                <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                <span className="text-xs text-emerald-400">
                  {voiceLive.isSpeaking ? 'AI Speaking...' : 'Listening...'}
                </span>
              </div>
            )}
            {voiceLive.error && (
              <div className="mt-1 text-xs text-red-400 max-w-xs">
                {voiceLive.error}
              </div>
            )}
          </div>
          <div className="absolute top-4 right-4 z-10 flex flex-col gap-2 items-end">
            <div className="flex gap-2 items-center">
              <button
                onClick={openEditDialog}
                className="p-2 bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600 transition-all duration-300 shadow-lg hover:shadow-xl hover:scale-105 active:scale-95"
                title="Edit request message"
              >
                <Pencil size={16} />
              </button>
              <button
                onClick={voiceLive.isRecording ? voiceLive.stopVoiceConversation : voiceLive.startVoiceConversation}
                className={`p-2 rounded-lg transition-all duration-300 shadow-lg hover:shadow-xl hover:scale-105 active:scale-95 ${
                  voiceLive.isRecording 
                    ? 'bg-red-600 hover:bg-red-500 text-white animate-pulse' 
                    : 'bg-emerald-600 hover:bg-emerald-500 text-white'
                }`}
                title={voiceLive.isRecording ? 'Stop voice conversation' : 'Start voice conversation'}
              >
                {voiceLive.isRecording ? <Phone size={16} /> : <Mic size={16} />}
              </button>
              <button
                onClick={simulateRequest}
                disabled={isSimulating || !isConnected}
                className="px-5 py-2.5 bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-lg font-semibold hover:from-indigo-500 hover:to-purple-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-300 shadow-lg hover:shadow-xl hover:scale-105 active:scale-95"
                title={!isConnected ? 'Connect to backend to send requests' : 'Send request to agent network'}
              >
                {isSimulating ? "Processing..." : "Send Request"}
              </button>
            </div>
            <button
              onClick={clearMemory}
              disabled={isClearingMemory || !isConnected}
              className="px-5 py-2.5 bg-gradient-to-r from-rose-600 to-orange-600 text-white rounded-lg font-semibold hover:from-rose-500 hover:to-orange-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-300 shadow-lg hover:shadow-xl hover:scale-105 active:scale-95"
              title={!isConnected ? 'Connect to backend to clear memory' : 'Clear inter-agent memory index'}
            >
              {isClearingMemory ? "Clearing..." : "Clear Memory"}
            </button>
            {!isConnected && (
              <p className="text-xs text-amber-400">
                Waiting for backend connection...
              </p>
            )}
          </div>
          <canvas ref={canvasRef} className="w-full h-full" />
        </div>

        <div className="border-t border-slate-700 bg-slate-800 p-6">
          <div className="grid grid-cols-3 gap-6">
            {kpis.map((kpi, index) => (
              <Card key={index} className="bg-gradient-to-br from-slate-700 to-slate-800 border-slate-600 shadow-lg">
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium text-slate-300">{kpi.title}</CardTitle>
                  <div className="text-slate-400">{kpi.icon}</div>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold text-slate-100">{kpi.value}</div>
                  <p className="text-xs text-emerald-400 mt-1 font-medium">{kpi.change} from last period</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </div>

      <div className="w-96 border-l border-slate-700 bg-slate-800">
        <div className="p-4 border-b border-slate-700">
          <h2 className="font-semibold text-lg text-slate-100">Connected Agents</h2>
          <p className="text-sm text-slate-400">
            {agents.length} agent{agents.length !== 1 ? "s" : ""} registered
          </p>
        </div>
        <ScrollArea className="h-[calc(100vh-81px)]">
          <Accordion type="single" collapsible className="w-full px-4">
            {agents.map((agent) => (
              <AccordionItem key={agent.id} value={agent.id} className="border-slate-700">
                <AccordionTrigger className="hover:no-underline text-slate-100 hover:text-slate-50">
                  <div className="flex items-center gap-3 w-full">
                    <div
                      className={`w-3 h-3 rounded-full shadow-lg ${agent.status === "active" ? "bg-emerald-500 shadow-emerald-500/50" : "bg-slate-500"}`}
                    />
                    <div className="flex-1 text-left">
                      <div className="font-semibold text-slate-100">{agent.name}</div>
                      <div className="text-xs text-slate-500">{agent.id}</div>
                    </div>
                    <Badge
                      className={`text-xs font-semibold shadow-md ${
                        agent.type === "host"
                          ? "bg-gradient-to-r from-indigo-500 to-purple-500 text-white border-0"
                          : agent.type === "human"
                            ? "bg-gradient-to-r from-teal-500 to-cyan-500 text-white border-0"
                            : "bg-gradient-to-r from-pink-500 to-rose-500 text-white border-0"
                      }`}
                    >
                      {agent.type}
                    </Badge>
                  </div>
                </AccordionTrigger>
                <AccordionContent>
                  <div className="pt-3 pb-2 space-y-4">
                    <div>
                      <h4 className="font-semibold text-sm text-slate-200 mb-2">Description</h4>
                      <p className="text-sm text-slate-400 leading-relaxed">{agent.description}</p>
                    </div>
                    <div>
                      <h4 className="font-semibold text-sm text-slate-200 mb-2">Skills</h4>
                      <div className="flex flex-wrap gap-2">
                        {agent.skills.map((skill, index) => (
                          <Badge
                            key={index}
                            className="text-xs bg-gradient-to-r from-indigo-500 to-purple-500 text-white border-0 font-semibold shadow-md"
                          >
                            {skill.name}
                          </Badge>
                        ))}
                      </div>
                    </div>
                    <div className="pt-2 border-t border-slate-700">
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-slate-500">Status</span>
                        <span
                          className={`font-medium ${agent.status === "active" ? "text-emerald-400" : "text-slate-400"}`}
                        >
                          {agent.status.toUpperCase()}
                        </span>
                      </div>
                    </div>
                  </div>
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </ScrollArea>
      </div>

      <button
        onClick={() => setShowCatalog(true)}
        className="fixed bottom-6 right-6 p-4 bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-full shadow-2xl hover:from-indigo-500 hover:to-purple-500 transition-all duration-300 hover:scale-110 active:scale-95 z-50"
      >
        <Plus className="h-6 w-6" />
      </button>

      <Dialog open={showCatalog} onOpenChange={setShowCatalog}>
        <DialogContent className="max-w-4xl max-h-[80vh] bg-slate-800 border-slate-700 text-slate-100">
          <DialogHeader>
            <DialogTitle className="text-2xl font-bold text-slate-100">Agent Marketplace</DialogTitle>
            <p className="text-sm text-slate-400">Browse and connect A2A agents to your network</p>
          </DialogHeader>
          <ScrollArea className="h-[60vh] pr-4">
            <div className="grid grid-cols-2 gap-4">
              {catalogAgents.map((agent) => (
                <Card
                  key={agent.id}
                  className="bg-gradient-to-br from-slate-700 to-slate-800 border-slate-600 shadow-lg hover:shadow-xl transition-all duration-300 hover:border-indigo-500"
                >
                  <CardHeader className="pb-3">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <CardTitle className="text-lg text-slate-100">{agent.name}</CardTitle>
                        <Badge variant="outline" className="mt-2 text-xs border-slate-500 text-slate-300">
                          {agent.category}
                        </Badge>
                      </div>
                      <div className="text-right">
                        <div className="text-xs text-slate-400">⭐ {agent.rating}</div>
                        <div className="text-xs text-slate-500">{agent.downloads.toLocaleString()} installs</div>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm text-slate-400 leading-relaxed mb-4">{agent.description}</p>
                    <div className="flex flex-wrap gap-2 mb-4">
                      {agent.skills.map((skill, index) => (
                        <Badge
                          key={index}
                          className="text-xs bg-gradient-to-r from-indigo-500 to-purple-600 text-white border-0 font-semibold shadow-md"
                        >
                          {skill}
                        </Badge>
                      ))}
                    </div>
                    <button className="w-full py-2 bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-lg font-semibold hover:from-indigo-500 hover:to-purple-500 transition-all duration-300 shadow-md hover:shadow-lg hover:scale-105 active:scale-95">
                      Connect Agent
                    </button>
                  </CardContent>
                </Card>
              ))}
            </div>
          </ScrollArea>
        </DialogContent>
      </Dialog>

      {/* Response Panel - Bottom Right */}
      {showResponsePanel && (
        <div className="fixed bottom-4 right-4 w-96 bg-slate-800 border border-slate-600 rounded-lg shadow-2xl overflow-hidden z-50">
          <div className="bg-gradient-to-r from-indigo-600 to-purple-600 p-3 flex items-center justify-between">
            <h3 className="font-semibold text-white">Final Response</h3>
            <button
              onClick={() => setShowResponsePanel(false)}
              className="text-white hover:text-slate-200 transition-colors"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <ScrollArea className="max-h-96 p-4">
            <p className="text-sm text-slate-200 leading-relaxed whitespace-pre-wrap">{finalResponse}</p>
          </ScrollArea>
        </div>
      )}

      {/* Edit Request Dialog */}
      <Dialog open={isEditDialogOpen} onOpenChange={setIsEditDialogOpen}>
        <DialogContent className="bg-slate-800 text-slate-100 border-slate-700">
          <DialogHeader>
            <DialogTitle>Edit Request Message</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <Textarea
              value={editedMessage}
              onChange={(e) => setEditedMessage(e.target.value)}
              className="min-h-[200px] bg-slate-900 border-slate-700 text-slate-100 focus:border-indigo-500"
              placeholder="Enter your request message..."
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setIsEditDialogOpen(false)}
                className="px-4 py-2 bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600 transition-all"
              >
                Cancel
              </button>
              <button
                onClick={saveEditedMessage}
                className="px-4 py-2 bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-lg hover:from-indigo-500 hover:to-purple-500 transition-all"
              >
                Save
              </button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
