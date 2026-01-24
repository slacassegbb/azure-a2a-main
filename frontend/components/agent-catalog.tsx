"use client"

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { useToast } from "@/hooks/use-toast"
import { useEventHub } from "@/hooks/use-event-hub"
import { getOrCreateSessionId } from "@/lib/session"
import { 
  Bot, 
  Play, 
  Zap, 
  ExternalLink, 
  Globe, 
  Search,
  FileText,
  Shield,
  Database,
  RefreshCw,
  UserPlus,
  Check,
  X,
  UserCheck,
  UserMinus,
  Power,
  Plus,
  Minus
} from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

export function AgentCatalog() {
  const { toast } = useToast()
  const { emit } = useEventHub()
  const [selectedAgent, setSelectedAgent] = useState<any>(null)
  const [startingAgent, setStartingAgent] = useState<string | null>(null)
  const [registeringAgent, setRegisteringAgent] = useState<string | null>(null)
  const [expandedAgents, setExpandedAgents] = useState<Set<string>>(new Set())
  const [catalogAgents, setCatalogAgents] = useState<any[]>([])
  const [enabledAgentUrls, setEnabledAgentUrls] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

    // Function to check agent health status via backend proxy
  const checkAgentHealth = async (url: string): Promise<boolean> => {
    try {
      // Extract just the localhost:port part from the URL
      const urlParts = url.replace('http://', '').replace('https://', '')
      const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
      const healthCheckUrl = `${baseUrl}/api/agents/health/${urlParts}`
      console.log(`Checking health for agent URL: ${url} -> ${healthCheckUrl}`)
      
      const response = await fetch(healthCheckUrl)
      
      if (!response.ok) {
        console.error(`Health check failed with status: ${response.status}`)
        return false
      }
      
      const data = await response.json()
      console.log(`Health check response for ${url}:`, JSON.stringify(data))
      
      // Check if the response has success and online fields
      if (data.success && typeof data.online === 'boolean') {
        console.log(`Agent online status: ${data.online}`)
        return data.online
      } else {
        console.error(`Invalid health response structure:`, data)
        return false
      }
    } catch (error) {
      console.warn(`Health check failed for ${url}:`, error)
      return false
    }
  }

  // Function to check health status for all agents
  const checkAllAgentsHealth = async (agents: any[]) => {
    console.log(`Starting health checks for ${agents.length} agents`)
    
    const healthChecks = agents.map(async (agent, index) => {
      console.log(`Health check ${index + 1}: Checking ${agent.name} at ${agent.endpoint}`)
      const isOnline = await checkAgentHealth(agent.endpoint)
      console.log(`Health check ${index + 1}: ${agent.name} is ${isOnline ? 'ONLINE' : 'OFFLINE'}`)
      
      return {
        ...agent,
        status: isOnline ? "Online" : "Offline"
      }
    })
    
    const results = await Promise.all(healthChecks)
    console.log(`Health checks complete. Results:`, results.map(r => `${r.name}: ${r.status}`))
    return results
  }

  // Function to fetch agents from registry
  const fetchAgents = async () => {
    try {
      setLoading(true)
      setError(null)
      const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
      const response = await fetch(`${baseUrl}/api/agents`)
      
      if (!response.ok) {
        throw new Error(`Failed to fetch agents: ${response.status}`)
      }
      
      const data = await response.json()
      const agents = data.agents || data // Handle both wrapped and unwrapped responses
      
      // Transform registry data to match UI expectations
      const transformedAgents = agents.map((agent: any, index: number) => ({
        id: agent.name.toLowerCase().replace(/\s+/g, '-'),
        name: agent.name,
        description: agent.description,
        status: "Checking...", // Initial status while checking health
        version: agent.version,
        endpoint: agent.url,
        organization: "Registry Agent", // Default organization
        icon: getIconForAgent(agent.name), // Helper function to get icon
        color: getColorForAgent(agent.name), // Deterministic color based on agent name
        bgColor: getBgColorForAgent(agent.name), // Deterministic bg color based on agent name
        capabilities: agent.capabilities,
        skills: agent.skills,
        defaultInputModes: agent.defaultInputModes,
        defaultOutputModes: agent.defaultOutputModes
      }))
      
      // Set initial agents with "Checking..." status
      setCatalogAgents(transformedAgents)
      
      // Check health status for all agents
      const agentsWithHealthStatus = await checkAllAgentsHealth(transformedAgents)
      setCatalogAgents(agentsWithHealthStatus)
    } catch (err) {
      console.error('Error fetching agents:', err)
      setError(err instanceof Error ? err.message : 'Failed to load agents')
      toast({
        title: "Error",
        description: "Failed to load agents from registry",
        variant: "destructive"
      })
    } finally {
      setLoading(false)
    }
  }

  // Helper function to get icon based on agent name
  const getIconForAgent = (name: string) => {
    if (name.toLowerCase().includes('sentiment')) return Bot
    if (name.toLowerCase().includes('classification') || name.toLowerCase().includes('triage')) return Shield
    if (name.toLowerCase().includes('legal') || name.toLowerCase().includes('compliance')) return FileText
    if (name.toLowerCase().includes('search') || name.toLowerCase().includes('knowledge')) return Search
    if (name.toLowerCase().includes('servicenow') || name.toLowerCase().includes('web')) return Database
    return Bot // Default icon
  }

  // Simple hash function to get consistent color for agent name
  const hashAgentName = (name: string): number => {
    let hash = 0
    for (let i = 0; i < name.length; i++) {
      hash = ((hash << 5) - hash) + name.charCodeAt(i)
      hash = hash & hash // Convert to 32bit integer
    }
    return Math.abs(hash)
  }

  // Helper function to get color based on agent name (deterministic, matches agent-network.tsx)
  const getColorForAgent = (agentName: string) => {
    const colors = [
      "text-pink-700",     // matches AGENT_COLORS[0]
      "text-purple-700",   // matches AGENT_COLORS[1]
      "text-cyan-700",     // matches AGENT_COLORS[2]
      "text-emerald-700",  // matches AGENT_COLORS[3]
      "text-amber-700",    // matches AGENT_COLORS[4]
      "text-red-700",      // matches AGENT_COLORS[5]
      "text-blue-700",     // matches AGENT_COLORS[6]
      "text-teal-700",     // matches AGENT_COLORS[7]
      "text-orange-700",   // matches AGENT_COLORS[8]
      "text-violet-700",   // matches AGENT_COLORS[9]
    ]
    return colors[hashAgentName(agentName) % colors.length]
  }

  // Helper function to get background color based on agent name (deterministic)
  const getBgColorForAgent = (agentName: string) => {
    const bgColors = [
      "bg-pink-100",     // matches AGENT_COLORS[0]
      "bg-purple-100",   // matches AGENT_COLORS[1]
      "bg-cyan-100",     // matches AGENT_COLORS[2]
      "bg-emerald-100",  // matches AGENT_COLORS[3]
      "bg-amber-100",    // matches AGENT_COLORS[4]
      "bg-red-100",      // matches AGENT_COLORS[5]
      "bg-blue-100",     // matches AGENT_COLORS[6]
      "bg-teal-100",     // matches AGENT_COLORS[7]
      "bg-orange-100",   // matches AGENT_COLORS[8]
      "bg-violet-100",   // matches AGENT_COLORS[9]
    ]
    return bgColors[hashAgentName(agentName) % bgColors.length]
  }

  // Load agents on component mount
  useEffect(() => {
    fetchAgents()
    fetchEnabledAgents()
  }, [])

  // Fetch which agents are enabled for this session
  const fetchEnabledAgents = async () => {
    try {
      const sessionId = getOrCreateSessionId()
      const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
      const response = await fetch(`${baseUrl}/agents/session?session_id=${sessionId}`)
      
      if (response.ok) {
        const data = await response.json()
        const urls = new Set<string>((data.agents || []).map((a: any) => a.url))
        setEnabledAgentUrls(urls)
      }
    } catch (err) {
      console.error('Error fetching enabled agents:', err)
    }
  }

  // Enable an agent for this session
  const handleEnableAgent = async (agent: any) => {
    try {
      const sessionId = getOrCreateSessionId()
      const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
      
      // Build the agent data to send (full agent card)
      const agentData = {
        name: agent.name,
        description: agent.description,
        version: agent.version,
        url: agent.endpoint,
        capabilities: agent.capabilities,
        skills: agent.skills,
        defaultInputModes: agent.defaultInputModes,
        defaultOutputModes: agent.defaultOutputModes
      }
      
      const response = await fetch(`${baseUrl}/agents/session/enable`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, agent: agentData })
      })
      
      if (response.ok) {
        setEnabledAgentUrls(prev => new Set([...prev, agent.endpoint]))
        emit('session_agent_enabled', { agent: agentData })
        toast({
          title: "Agent Enabled",
          description: `${agent.name} added to your team`
        })
      }
    } catch (err) {
      console.error('Error enabling agent:', err)
      toast({
        title: "Error",
        description: "Failed to enable agent",
        variant: "destructive"
      })
    }
  }

  // Disable an agent for this session
  const handleDisableAgent = async (agent: any) => {
    try {
      const sessionId = getOrCreateSessionId()
      const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
      
      const response = await fetch(`${baseUrl}/agents/session/disable`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, agent_url: agent.endpoint })
      })
      
      if (response.ok) {
        setEnabledAgentUrls(prev => {
          const next = new Set(prev)
          next.delete(agent.endpoint)
          return next
        })
        emit('session_agent_disabled', { agent_url: agent.endpoint })
        toast({
          title: "Agent Disabled",
          description: `${agent.name} removed from your team`
        })
      }
    } catch (err) {
      console.error('Error disabling agent:', err)
      toast({
        title: "Error",
        description: "Failed to disable agent",
        variant: "destructive"
      })
    }
  }

  // Function to refresh agents (for refresh button)
  const refreshAgents = () => {
    fetchAgents()
    fetchEnabledAgents()
    toast({
      title: "Refreshing",
      description: "Loading latest agents from registry..."
    })
  }

  const toggleAgent = (agentId: string, newState?: boolean) => {
    const newExpanded = new Set(expandedAgents)
    if (newState !== undefined) {
      // Use explicit state if provided
      if (newState) {
        newExpanded.add(agentId)
      } else {
        newExpanded.delete(agentId)
      }
    } else {
      // Toggle current state
      if (newExpanded.has(agentId)) {
        newExpanded.delete(agentId)
      } else {
        newExpanded.add(agentId)
      }
    }
    setExpandedAgents(newExpanded)
  }

  const handleStartAgent = async (agent: any) => {
    setStartingAgent(agent.id)
    
    try {
      toast({
        title: "Waking Up Agent...",
        description: `Triggering ${agent.name} (may take 10-15 seconds if cold start)`,
      })
      
      // Ping the agent's health endpoint multiple times to trigger Azure auto-scale
      // This will wake up the container if it's scaled to 0
      const maxRetries = 3
      let isOnline = false
      
      for (let i = 0; i < maxRetries; i++) {
        console.log(`[Agent Catalog] Wake-up attempt ${i + 1}/${maxRetries} for ${agent.name}`)
        
        // Check agent health (this will trigger auto-scale)
        isOnline = await checkAgentHealth(agent.endpoint)
        
        if (isOnline) {
          console.log(`[Agent Catalog] Agent ${agent.name} is now online!`)
          break
        }
        
        // Wait between retries (10 seconds for cold start)
        if (i < maxRetries - 1) {
          await new Promise(resolve => setTimeout(resolve, 10000))
        }
      }
      
      if (isOnline) {
        toast({
          title: "Agent Awake! ✅",
          description: `${agent.name} is now running and ready`,
        })
        
        // Refresh the agent's status in the UI
        setCatalogAgents(prev => prev.map(a => 
          a.id === agent.id ? { ...a, status: "Online" } : a
        ))
      } else {
        toast({
          title: "Wake Up Failed",
          description: `${agent.name} did not respond. It may need more time or manual intervention.`,
          variant: "destructive"
        })
      }
    } catch (error) {
      console.error('[Agent Catalog] Error waking up agent:', error)
      toast({
        title: "Error",
        description: "Failed to wake up agent",
        variant: "destructive"
      })
    } finally {
      setStartingAgent(null)
    }
  }

  const handleRegisterAgent = async (agent: any) => {
    try {
      // Set loading state for this specific agent
      setRegisteringAgent(agent.name)
      
      toast({
        title: "Registering Agent...",
        description: `Registering ${agent.name} to the platform`,
      })
      
      // Call backend to register the agent using its URL from the registry
      const response = await fetch('/api/register-agent', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ address: agent.endpoint.trim() }),
      })

      const result = await response.json()

      if (response.ok && result.success) {
        toast({
          title: "Agent Registered",
          description: `Successfully registered ${agent.name} at ${agent.endpoint}`,
        })
        
        // The agent registry will update immediately via WebSocket real-time sync
        console.log('[Agent Catalog] Agent registered - UI will update in real-time')
      } else {
        const errorMessage = result.error || "Failed to register agent"
        toast({
          title: "Registration Failed",
          description: errorMessage.includes("404") 
            ? `Agent at ${agent.endpoint} does not have a valid A2A agent card at /.well-known/agent-card.json`
            : errorMessage,
          variant: "destructive",
        })
      }
    } catch (error) {
      console.error('[Agent Catalog] Error registering agent:', error)
      toast({
        title: "Registration Failed",
        description: "Failed to register agent",
        variant: "destructive"
      })
    } finally {
      // Clear loading state after registration completes (success or failure)
      setRegisteringAgent(null)
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-end">
          <Button variant="outline" size="sm" disabled>
            <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
            Loading...
          </Button>
        </div>
        <div className="text-center py-8">Loading agents from registry...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-end">
          <Button variant="outline" size="sm" onClick={refreshAgents}>
            <RefreshCw className="h-4 w-4 mr-2" />
            Retry
          </Button>
        </div>
        <div className="text-center py-8 text-red-600">
          Error: {error}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end">
        <Button variant="outline" size="sm" onClick={refreshAgents}>
          <RefreshCw className="h-4 w-4 mr-2" />
          Refresh
        </Button>
      </div>
      
      <div className="grid gap-2">
        {catalogAgents.map((agent) => {
          const isStarting = startingAgent === agent.id
          const isOffline = agent.status === "Offline"
          const AgentIcon = agent.icon
          const isEnabled = enabledAgentUrls.has(agent.endpoint)
          
          return (
            <Card key={agent.id} className="transition-all duration-200 hover:shadow-md">
              <Collapsible 
                open={expandedAgents.has(agent.id)} 
                onOpenChange={(open) => toggleAgent(agent.id, open)}
              >
                <CollapsibleTrigger asChild>
                  <CardHeader className="cursor-pointer p-3 hover:bg-muted/50 transition-colors">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className={`p-2 rounded-lg ${agent.bgColor}`}>
                          <AgentIcon className={`h-4 w-4 ${agent.color}`} />
                        </div>
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <CardTitle className="text-sm font-semibold">{agent.name}</CardTitle>
                            <div className={`w-2 h-2 rounded-full ${
                              agent.status === "Online" ? "bg-green-500" : 
                              agent.status === "Offline" ? "bg-red-500" : 
                              "bg-yellow-500 animate-pulse"
                            }`} title={`Status: ${agent.status}`}></div>
                            {isEnabled && (
                              <Badge variant="secondary" className="text-xs">In Team</Badge>
                            )}
                          </div>
                          <CardDescription className="text-xs mt-1 line-clamp-2">
                            {agent.description}
                          </CardDescription>
                        </div>
                      </div>
                      <div className="ml-2 flex gap-2" onClick={(e) => e.stopPropagation()}>
                        <TooltipProvider>
                          {agent.status === "Online" && (
                            isEnabled ? (
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    onClick={() => handleDisableAgent(agent)}
                                    size="icon"
                                    className="h-9 w-9 rounded-full bg-red-500 hover:bg-red-600 text-white shadow-sm hover:shadow-md transition-all duration-200"
                                  >
                                    <Minus className="h-5 w-5" />
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent>
                                  <p>Remove agent from your team</p>
                                </TooltipContent>
                              </Tooltip>
                            ) : (
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    onClick={() => handleEnableAgent(agent)}
                                    size="icon"
                                    className="h-9 w-9 rounded-full bg-green-500 hover:bg-green-600 text-white shadow-sm hover:shadow-md transition-all duration-200"
                                  >
                                    <Plus className="h-5 w-5" />
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent>
                                  <p>Add agent to your team</p>
                                </TooltipContent>
                              </Tooltip>
                            )
                          )}
                          {agent.status === "Offline" && (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  onClick={() => handleStartAgent(agent)}
                                  disabled={isStarting}
                                  size="icon"
                                  className="h-9 w-9 rounded-full bg-sky-500 hover:bg-sky-600 text-white shadow-sm hover:shadow-md transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                  <Power className="h-4 w-4" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>
                                <p>Wake up the agent container</p>
                              </TooltipContent>
                            </Tooltip>
                          )}
                        </TooltipProvider>
                      </div>
                    </div>
                  </CardHeader>
                </CollapsibleTrigger>
                
                <CollapsibleContent>
                  <CardContent className="pt-0 space-y-3">
                    {/* Real-time Status */}
                    <div className="flex items-center justify-between text-xs">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="text-muted-foreground">Connection:</span>
                          <span className={
                            agent.status === "Online" ? "text-green-600" : 
                            agent.status === "Offline" ? "text-red-600" : 
                            "text-yellow-600"
                          }>
                            {agent.status.toLowerCase()}
                          </span>
                        </div>
                        {agent.status === "Online" && (
                          <div className="flex items-center gap-2">
                            <span className="text-muted-foreground">Last Seen:</span>
                            <span className="text-foreground">Now</span>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Version and Endpoint */}
                    <div className="space-y-1 text-xs">
                      <div className="flex items-center gap-2">
                        <span className="text-muted-foreground"># Version:</span>
                        <span className="font-mono">{agent.version}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Globe className="h-3 w-3 text-muted-foreground" />
                        <span className="text-muted-foreground">Endpoint:</span>
                        <span className="font-mono text-xs truncate">{agent.endpoint}</span>
                      </div>
                    </div>

                    {/* Capabilities */}
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <Zap className="h-3 w-3 text-muted-foreground" />
                        <span className="text-xs font-medium text-muted-foreground">Capabilities</span>
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {Object.entries(agent.capabilities || {}).map(([key, value]) => 
                          value ? (
                            <Badge key={key} variant="secondary" className="text-xs">
                              {key.replace(/([A-Z])/g, ' $1').trim()}
                            </Badge>
                          ) : null
                        )}
                      </div>
                    </div>

                    {/* Skills Summary */}
                    <div className="space-y-2">
                      <span className="text-xs font-medium text-muted-foreground">
                        Skills ({agent.skills?.length || 0})
                      </span>
                      <div className="space-y-1">
                        {agent.skills && agent.skills.length > 0 && (
                          <div className="bg-muted/50 rounded p-2">
                            <div className="font-medium text-xs">{agent.skills[0].name}</div>
                            <div className="text-xs text-muted-foreground mt-1 line-clamp-2">
                              {agent.skills[0].description}
                            </div>
                            <div className="flex flex-wrap gap-1 mt-2">
                              {agent.skills[0].tags?.slice(0, 3).map((tag: string, idx: number) => (
                                <Badge key={idx} variant="outline" className="text-xs">
                                  {tag}
                                </Badge>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Action Buttons */}
                    <div className="flex gap-2 pt-2">
                      <Dialog>
                        <DialogTrigger asChild>
                          <Button variant="outline" size="sm" onClick={() => setSelectedAgent(agent)} className="w-full">
                            <ExternalLink className="h-3 w-3 mr-2" />
                            View Details
                          </Button>
                        </DialogTrigger>
                        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
                          <DialogHeader>
                            <DialogTitle className="flex items-center gap-2">
                              <AgentIcon className={`h-5 w-5 ${agent.color}`} />
                              {agent.name}
                            </DialogTitle>
                            <DialogDescription>
                              Detailed information about this agent
                            </DialogDescription>
                          </DialogHeader>
                          
                          {selectedAgent && (
                            <div className="space-y-4">
                              <div>
                                <h4 className="font-medium mb-2">Description</h4>
                                <p className="text-sm text-muted-foreground">{selectedAgent.description}</p>
                              </div>
                              
                              <div>
                                <h4 className="font-medium mb-2">Organization</h4>
                                <p className="text-sm">{selectedAgent.organization}</p>
                              </div>
                              
                              <div>
                                <h4 className="font-medium mb-2">All Skills</h4>
                                <div className="space-y-2">
                                  {selectedAgent.skills.map((skill: any, idx: number) => (
                                    <div key={idx} className="bg-muted/50 rounded p-3">
                                      <div className="font-medium text-sm">{skill.name}</div>
                                      <div className="text-sm text-muted-foreground mt-1">
                                        {skill.description}
                                      </div>
                                      <div className="flex flex-wrap gap-1 mt-2">
                                        {skill.tags.map((tag: string, tagIdx: number) => (
                                          <Badge key={tagIdx} variant="outline" className="text-xs">
                                            {tag}
                                          </Badge>
                                        ))}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            </div>
                          )}
                        </DialogContent>
                      </Dialog>
                    </div>
                  </CardContent>
                </CollapsibleContent>
              </Collapsible>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
