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
  X
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

export function AgentCatalog() {
  const { toast } = useToast()
  const { emit } = useEventHub()
  const [selectedAgent, setSelectedAgent] = useState<any>(null)
  const [startingAgent, setStartingAgent] = useState<string | null>(null)
  const [registeringAgent, setRegisteringAgent] = useState<string | null>(null)
  const [expandedAgents, setExpandedAgents] = useState<Set<string>>(new Set())
  const [catalogAgents, setCatalogAgents] = useState<any[]>([])
  const [sessionAgentUrls, setSessionAgentUrls] = useState<Set<string>>(new Set()) // Track session-enabled agents
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const sessionId = getOrCreateSessionId() // Get or create session ID

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
      
      // Fetch catalog agents and session agents in parallel using Next.js API routes
      const [catalogResponse, sessionResponse] = await Promise.all([
        fetch(`/api/agents/catalog`),
        fetch(`/api/agents/session/registered?sessionId=${encodeURIComponent(sessionId)}`)
      ])
      
      if (!catalogResponse.ok) {
        throw new Error(`Failed to fetch agents: ${catalogResponse.status}`)
      }
      
      const catalogData = await catalogResponse.json()
      const agents = catalogData.agents || []
      
      // Parse session agents to get enabled URLs
      let enabledUrls = new Set<string>()
      if (sessionResponse.ok) {
        const sessionData = await sessionResponse.json()
        const sessionAgents = sessionData.agents || []
        enabledUrls = new Set(sessionAgents.map((a: any) => a.url?.replace(/\/$/, '') || ''))
      }
      setSessionAgentUrls(enabledUrls)
      
      // Transform registry data to match UI expectations
      const transformedAgents = agents.map((agent: any, index: number) => ({
        id: agent.name.toLowerCase().replace(/\s+/g, '-'),
        name: agent.name,
        description: agent.description,
        status: agent.status === 'online' ? "Online" : agent.status === 'offline' ? "Offline" : "Checking...",
        version: agent.version,
        endpoint: agent.url,
        organization: "Registry Agent", // Default organization
        icon: getIconForAgent(agent.name), // Helper function to get icon
        color: getColorForAgent(index), // Helper function to get color
        bgColor: getBgColorForAgent(index), // Helper function to get bg color
        capabilities: agent.capabilities,
        skills: agent.skills,
        defaultInputModes: agent.defaultInputModes,
        defaultOutputModes: agent.defaultOutputModes,
        isEnabled: enabledUrls.has(agent.url?.replace(/\/$/, '') || '') // Track if enabled for session
      }))
      
      setCatalogAgents(transformedAgents)
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

  // Helper function to get color based on index
  const getColorForAgent = (index: number) => {
    const colors = [
      "text-cyan-700",
      "text-red-700", 
      "text-purple-700",
      "text-blue-700",
      "text-green-700",
      "text-orange-700"
    ]
    return colors[index % colors.length]
  }

  // Helper function to get background color based on index
  const getBgColorForAgent = (index: number) => {
    const bgColors = [
      "bg-cyan-100",
      "bg-red-100",
      "bg-purple-100", 
      "bg-blue-100",
      "bg-green-100",
      "bg-orange-100"
    ]
    return bgColors[index % bgColors.length]
  }

  // Load agents on component mount
  useEffect(() => {
    fetchAgents()
  }, [])

  // Function to refresh agents (for refresh button)
  const refreshAgents = () => {
    fetchAgents()
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
        title: "Starting Agent...",
        description: `Starting ${agent.name}`,
      })
      
      // For now, just simulate starting
      await new Promise(resolve => setTimeout(resolve, 2000))
      
      toast({
        title: "Agent Started",
        description: `${agent.name} is now running`,
      })
    } catch (error) {
      console.error('[Agent Catalog] Error starting agent:', error)
      toast({
        title: "Error",
        description: "Failed to start agent",
        variant: "destructive"
      })
    } finally {
      setStartingAgent(null)
    }
  }

  // Toggle agent enabled/disabled for this session
  const handleToggleSessionAgent = async (agent: any) => {
    const isCurrentlyEnabled = sessionAgentUrls.has(agent.endpoint?.replace(/\/$/, '') || '')
    const endpoint = isCurrentlyEnabled ? 'unregister' : 'register'
    const actionWord = isCurrentlyEnabled ? 'Disabling' : 'Enabling'
    const pastWord = isCurrentlyEnabled ? 'disabled' : 'enabled'
    
    try {
      setRegisteringAgent(agent.name)
      
      toast({
        title: `${actionWord} Agent...`,
        description: `${actionWord} ${agent.name} for your session`,
      })
      
      // Use Next.js API routes to proxy to backend
      const response = await fetch(`/api/agents/session/${endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ 
          sessionId, 
          agentUrl: agent.endpoint 
        }),
      })

      const result = await response.json()

      if (response.ok && result.success) {
        // Update local state
        const newUrls = new Set(sessionAgentUrls)
        const normalizedUrl = agent.endpoint?.replace(/\/$/, '') || ''
        
        if (isCurrentlyEnabled) {
          newUrls.delete(normalizedUrl)
        } else {
          newUrls.add(normalizedUrl)
        }
        setSessionAgentUrls(newUrls)
        
        // Update agent in list
        setCatalogAgents(prev => prev.map(a => 
          a.id === agent.id ? { ...a, isEnabled: !isCurrentlyEnabled } : a
        ))
        
        toast({
          title: `Agent ${pastWord}`,
          description: `${agent.name} is now ${pastWord} for your session`,
        })
        
        // Emit event for other components to update
        emit('agentSessionUpdated', { agentUrl: agent.endpoint, enabled: !isCurrentlyEnabled })
      } else {
        toast({
          title: "Error",
          description: result.error || `Failed to ${endpoint} agent`,
          variant: "destructive",
        })
      }
    } catch (error) {
      console.error(`[Agent Catalog] Error ${endpoint}ing agent:`, error)
      toast({
        title: "Error",
        description: `Failed to ${endpoint} agent`,
        variant: "destructive"
      })
    } finally {
      setRegisteringAgent(null)
    }
  }

  // Legacy: Register agent to global catalog (if not already in catalog)
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
                          </div>
                          <CardDescription className="text-xs mt-1 line-clamp-2">
                            {agent.description}
                          </CardDescription>
                        </div>
                      </div>
                      <div className="ml-2 flex gap-2" onClick={(e) => e.stopPropagation()}>
                        {/* Enable/Disable agent for this session */}
                        <Button
                          onClick={() => handleToggleSessionAgent(agent)}
                          disabled={registeringAgent === agent.name || agent.status === "Offline"}
                          size="sm"
                          variant={agent.isEnabled ? "default" : "outline"}
                          className={`h-7 px-2 text-xs ${agent.isEnabled ? 'bg-green-600 hover:bg-green-700' : ''}`}
                        >
                          {registeringAgent === agent.name ? (
                            <>
                              <RefreshCw className="h-3 w-3 mr-1 animate-spin" />
                              ...
                            </>
                          ) : agent.isEnabled ? (
                            <>
                              <Check className="h-3 w-3 mr-1" />
                              Enabled
                            </>
                          ) : (
                            <>
                              <UserPlus className="h-3 w-3 mr-1" />
                              Enable
                            </>
                          )}
                        </Button>
                        <Button
                          onClick={() => handleStartAgent(agent)}
                          disabled={isStarting || isOffline || !agent.isEnabled}
                          size="sm"
                          className="h-7 px-2 text-xs"
                          title={!agent.isEnabled ? "Enable this agent first" : ""}
                        >
                          <Play className="h-3 w-3 mr-1" />
                          {isStarting ? "Starting..." : "Start"}
                        </Button>
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
                        Skills ({agent.skills.length})
                      </span>
                      <div className="space-y-1">
                        <div className="bg-muted/50 rounded p-2">
                          <div className="font-medium text-xs">{agent.skills[0].name}</div>
                          <div className="text-xs text-muted-foreground mt-1 line-clamp-2">
                            {agent.skills[0].description}
                          </div>
                          <div className="flex flex-wrap gap-1 mt-2">
                            {agent.skills[0].tags.slice(0, 3).map((tag: string, idx: number) => (
                              <Badge key={idx} variant="outline" className="text-xs">
                                {tag}
                              </Badge>
                            ))}
                          </div>
                        </div>
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
