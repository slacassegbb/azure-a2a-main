"use client"

import { useState, useEffect, useMemo } from "react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { useToast } from "@/hooks/use-toast"
import { useEventHub } from "@/hooks/use-event-hub"
import { getOrCreateSessionId } from "@/lib/session"
import {
  Bot,
  Zap,
  ExternalLink,
  Globe,
  Search,
  FileText,
  Shield,
  Database,
  RefreshCw,
  Power,
  Plus,
  Minus,
  Mail,
  BarChart3,
  Code,
  MessageSquare,
  Phone,
  CreditCard,
  Receipt,
  Image,
  Palette,
  MapPin,
  FileSpreadsheet,
  FileType,
  Presentation,
  ClipboardCheck,
  AlertTriangle,
  Clock,
  UserSearch,
  Handshake,
  BrainCircuit,
} from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

import { getAgentTextClass, getAgentBgClass } from "@/lib/agent-colors"
import { deriveCategory, getAllCategories, CATEGORY_ICONS } from "@/lib/agent-categories"
import { warnDebug } from '@/lib/debug'
import { fetchRegistryAgents, checkAgentHealth, checkAgentHealthWithFallback } from '@/lib/agent-registry'
import { API_BASE_URL } from '@/lib/api-config'

export function AgentCatalog() {
  const { toast } = useToast()
  const { emit } = useEventHub()
  const [selectedAgent, setSelectedAgent] = useState<any>(null)
  const [startingAgent, setStartingAgent] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState("")
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [catalogAgents, setCatalogAgents] = useState<any[]>([])
  const [enabledAgentUrls, setEnabledAgentUrls] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Derived categories from agents
  const categories = useMemo(() => getAllCategories(catalogAgents), [catalogAgents])

  // Filtered agents based on search and category
  const filteredAgents = useMemo(() => {
    return catalogAgents.filter(agent => {
      // Category filter
      if (selectedCategory && deriveCategory(agent) !== selectedCategory) return false

      // Text search across name, description, skills
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase()
        const nameMatch = agent.name.toLowerCase().includes(q)
        const descMatch = agent.description?.toLowerCase().includes(q)
        const categoryMatch = deriveCategory(agent).toLowerCase().includes(q)
        const skillMatch = agent.skills?.some((s: any) =>
          s.name?.toLowerCase().includes(q) ||
          s.description?.toLowerCase().includes(q) ||
          s.tags?.some((t: string) => t.toLowerCase().includes(q))
        )
        if (!nameMatch && !descMatch && !categoryMatch && !skillMatch) return false
      }

      return true
    })
  }, [catalogAgents, searchQuery, selectedCategory])

  // Helper function to check if an endpoint is localhost
  const isLocalhostEndpoint = (endpoint: string): boolean => {
    const lower = endpoint.toLowerCase()
    return lower.includes('localhost') || lower.includes('127.0.0.1')
  }

  // Check health status for all agents using shared utility
  // Tries local URL first, falls back to production URL if local is offline
  const checkAllAgentsHealth = async (agents: any[]) => {
    const healthChecks = agents.map(async (agent) => {
      const result = await checkAgentHealthWithFallback(agent)
      if (result) {
        return { ...result, status: "Online" }
      }
      return { ...agent, status: "Offline" }
    })
    return Promise.all(healthChecks)
  }

  // Helper function to get icon based on agent name, then category fallback
  const getIconForAgent = (name: string, agent?: any) => {
    const n = name.toLowerCase()
    // Specific keyword matches
    if (n.includes('email')) return Mail
    if (n.includes('teams') || n.includes('chat') || n.includes('messaging')) return MessageSquare
    if (n.includes('twilio') || n.includes('sms') || n.includes('phone')) return Phone
    if (n.includes('stock') || n.includes('market') || n.includes('trading')) return BarChart3
    if (n.includes('quickbooks') || n.includes('invoice')) return Receipt
    if (n.includes('stripe') || n.includes('payment') || n.includes('billing')) return CreditCard
    if (n.includes('github') || n.includes('code') || n.includes('developer')) return Code
    if (n.includes('search') || n.includes('knowledge') || n.includes('deep search')) return Search
    if (n.includes('legal') || n.includes('compliance')) return FileText
    if (n.includes('classification') || n.includes('triage')) return Shield
    if (n.includes('claims') || n.includes('insurance')) return ClipboardCheck
    if (n.includes('fraud') || n.includes('risk')) return AlertTriangle
    if (n.includes('assessment') || n.includes('estimation')) return ClipboardCheck
    if (n.includes('branding') || n.includes('creative') || n.includes('content')) return Palette
    if (n.includes('image') || n.includes('vision') || n.includes('photo')) return Image
    if (n.includes('google') || n.includes('maps') || n.includes('location')) return MapPin
    if (n.includes('excel') || n.includes('spreadsheet')) return FileSpreadsheet
    if (n.includes('word') || n.includes('document')) return FileType
    if (n.includes('powerpoint') || n.includes('presentation') || n.includes('slide')) return Presentation
    if (n.includes('servicenow') || n.includes('ticket')) return Database
    if (n.includes('interview') || n.includes('recruit') || n.includes('hr')) return UserSearch
    if (n.includes('human') || n.includes('approval')) return Handshake
    if (n.includes('time') || n.includes('forecast') || n.includes('series')) return Clock
    if (n.includes('sentiment') || n.includes('analytic') || n.includes('intelligence')) return BrainCircuit
    if (n.includes('reporter') || n.includes('report')) return FileText
    // Category-based fallback
    if (agent) {
      const cat = deriveCategory(agent)
      const catIcon = CATEGORY_ICONS[cat]
      if (catIcon) return catIcon
    }
    return Bot
  }

  // Function to fetch agents from registry (uses shared utility)
  const fetchAgents = async () => {
    try {
      setLoading(true)
      setError(null)

      const baseAgents = await fetchRegistryAgents()

      // Extend with catalog-specific display fields
      const transformedAgents = baseAgents.map((agent) => ({
        ...agent,
        status: "Checking...",
        version: agent._raw.version,
        organization: "Registry Agent",
        icon: getIconForAgent(agent.name, agent._raw),
        rawColor: agent.color,
        color: getAgentTextClass(agent.name, agent.color),
        bgColor: getAgentBgClass(agent.name, agent.color),
        capabilities: agent._raw.capabilities,
        defaultInputModes: agent._raw.defaultInputModes,
        defaultOutputModes: agent._raw.defaultOutputModes,
      }))

      setCatalogAgents(transformedAgents)
      setLoading(false)

      checkAllAgentsHealth(transformedAgents).then(agentsWithHealthStatus => {
        setCatalogAgents(agentsWithHealthStatus)
      }).catch(err => {
        warnDebug('Background health check failed:', err)
      })
    } catch (err) {
      console.error('Error fetching agents:', err)
      setError(err instanceof Error ? err.message : 'Failed to load agents')
      toast({
        title: "Error",
        description: "Failed to load agents from registry",
        variant: "destructive"
      })
      setLoading(false)
    }
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
      const baseUrl = API_BASE_URL
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
      const baseUrl = API_BASE_URL

      const agentData = {
        name: agent.name,
        description: agent.description,
        version: agent.version,
        url: agent.endpoint,
        color: agent.rawColor,
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
      const baseUrl = API_BASE_URL

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

  // Function to refresh agents
  const refreshAgents = () => {
    fetchAgents()
    fetchEnabledAgents()
    toast({
      title: "Refreshing",
      description: "Loading latest agents from registry..."
    })
  }

  const handleStartAgent = async (agent: any) => {
    setStartingAgent(agent.id)

    try {
      toast({
        title: "Waking Up Agent...",
        description: `Triggering ${agent.name} (may take 10-15 seconds if cold start)`,
      })

      const maxRetries = 3
      let isOnline = false

      for (let i = 0; i < maxRetries; i++) {
        isOnline = await checkAgentHealth(agent.endpoint)

        if (isOnline) break

        if (i < maxRetries - 1) {
          await new Promise(resolve => setTimeout(resolve, 10000))
        }
      }

      if (isOnline) {
        toast({
          title: "Agent Awake!",
          description: `${agent.name} is now running and ready`,
        })
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

  // Loading state
  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center space-y-3">
          <RefreshCw className="h-6 w-6 animate-spin mx-auto text-slate-400" />
          <p className="text-sm text-slate-400">Loading agents from registry...</p>
        </div>
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center space-y-3">
          <p className="text-sm text-red-400">Error: {error}</p>
          <Button variant="outline" size="sm" onClick={refreshAgents}>
            <RefreshCw className="h-4 w-4 mr-2" />
            Retry
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Header: search + filters */}
      <div className="space-y-3 pb-4 border-b border-slate-700/50 flex-shrink-0">
        {/* Search bar row */}
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-slate-400" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search agents by name, description, or skills..."
              className="pl-10 h-9 text-sm bg-slate-800 border-slate-700 text-slate-200 placeholder:text-slate-500"
            />
          </div>
          <Button variant="outline" size="sm" onClick={refreshAgents} className="h-9 px-3 border-slate-700 text-slate-400 hover:text-slate-200">
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>

        {/* Category filter pills */}
        <div className="flex flex-wrap gap-1.5">
          <Button
            variant={selectedCategory === null ? "default" : "outline"}
            size="sm"
            onClick={() => setSelectedCategory(null)}
            className="h-7 text-xs rounded-full px-3"
          >
            All ({catalogAgents.length})
          </Button>
          {categories.map(cat => {
            const CatIcon = CATEGORY_ICONS[cat]
            const count = catalogAgents.filter(a => deriveCategory(a) === cat).length
            return (
              <Button
                key={cat}
                variant={selectedCategory === cat ? "default" : "outline"}
                size="sm"
                onClick={() => setSelectedCategory(cat === selectedCategory ? null : cat)}
                className="h-7 text-xs rounded-full px-3"
              >
                {CatIcon && <CatIcon className="h-3 w-3 mr-1" />}
                {cat} ({count})
              </Button>
            )
          })}
        </div>
      </div>

      {/* Agent grid */}
      <ScrollArea className="flex-1 min-h-0 pt-4">
        {filteredAgents.length === 0 ? (
          <div className="text-center py-16 text-slate-400">
            <Search className="h-8 w-8 mx-auto mb-3 opacity-50" />
            <p className="text-sm">No agents found{searchQuery ? ` matching "${searchQuery}"` : ""}</p>
            {selectedCategory && (
              <Button
                variant="link"
                size="sm"
                className="mt-2 text-xs text-slate-500"
                onClick={() => { setSelectedCategory(null); setSearchQuery("") }}
              >
                Clear filters
              </Button>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 pb-4">
            {filteredAgents.map((agent) => {
              const isStarting = startingAgent === agent.id
              const AgentIcon = agent.icon
              const isEnabled = enabledAgentUrls.has(agent.endpoint)
              const category = deriveCategory(agent)
              const skillNames = (agent.skills || []).map((s: any) => s.name)

              return (
                <Card
                  key={agent.id}
                  className={`bg-slate-800/80 border transition-all duration-200 hover:shadow-lg hover:shadow-indigo-500/5 flex flex-col ${
                    isEnabled
                      ? "border-green-500/40 hover:border-green-400/60"
                      : "border-slate-700/60 hover:border-indigo-500/60"
                  }`}
                >
                  {/* Header: icon + name + status on one line */}
                  <div className="flex items-center gap-2.5 px-3 pt-3">
                    <div className={`p-2 rounded-lg ${agent.bgColor} flex-shrink-0`}>
                      <AgentIcon className={`h-4 w-4 ${agent.color}`} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <h3 className="text-[13px] font-semibold text-slate-100 truncate">
                          {agent.name}
                        </h3>
                        <div
                          className={`w-2 h-2 rounded-full flex-shrink-0 ${
                            agent.status === "Online" ? "bg-green-500" :
                            agent.status === "Offline" ? "bg-red-500" :
                            "bg-yellow-500 animate-pulse"
                          }`}
                          title={agent.status}
                        />
                      </div>
                    </div>
                    {isEnabled && (
                      <Badge className="text-[9px] px-1.5 py-0 h-4 bg-green-500/15 text-green-400 border-green-500/30 hover:bg-green-500/15 flex-shrink-0">
                        In Team
                      </Badge>
                    )}
                  </div>

                  {/* Category */}
                  <span className="text-[10px] text-slate-500 uppercase tracking-wider font-medium px-3 mt-1">{category}</span>

                  {/* Description — fill the card */}
                  <p className="text-[11px] text-slate-400 line-clamp-3 leading-relaxed px-3 mt-1.5 flex-1">
                    {agent.description}
                  </p>

                  {/* Skills as bubbles — pinned to bottom */}
                  {skillNames.length > 0 && (
                    <div className="flex flex-wrap gap-1 px-3 mt-1.5">
                      {skillNames.map((name: string, i: number) => (
                        <span
                          key={i}
                          className="text-[10px] px-2 py-[1px] rounded-full bg-slate-700/50 text-slate-400 border border-slate-600/30"
                        >
                          {name}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Footer: action buttons */}
                  <div className="flex items-center justify-end gap-1 px-3 py-2">
                    <TooltipProvider delayDuration={300}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 text-slate-500 hover:text-indigo-400 hover:bg-indigo-400/10"
                            onClick={() => setSelectedAgent(agent)}
                          >
                            <ExternalLink className="h-3.5 w-3.5" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent side="bottom"><p>View details</p></TooltipContent>
                      </Tooltip>

                      {agent.status === "Online" && (
                        isEnabled ? (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                onClick={() => handleDisableAgent(agent)}
                                size="icon"
                                className="h-7 w-7 rounded-full bg-red-500/90 hover:bg-red-500 text-white"
                              >
                                <Minus className="h-3.5 w-3.5" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent side="bottom"><p>Remove from team</p></TooltipContent>
                          </Tooltip>
                        ) : (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                onClick={() => handleEnableAgent(agent)}
                                size="icon"
                                className="h-7 w-7 rounded-full bg-green-500/90 hover:bg-green-500 text-white"
                              >
                                <Plus className="h-3.5 w-3.5" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent side="bottom"><p>Add to team</p></TooltipContent>
                          </Tooltip>
                        )
                      )}
                      {agent.status === "Offline" && !isLocalhostEndpoint(agent.endpoint) && (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              onClick={() => handleStartAgent(agent)}
                              disabled={isStarting}
                              size="icon"
                              className="h-7 w-7 rounded-full bg-sky-500/90 hover:bg-sky-500 text-white disabled:opacity-50"
                            >
                              <Power className="h-3.5 w-3.5" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent side="bottom"><p>Wake up agent</p></TooltipContent>
                        </Tooltip>
                      )}
                    </TooltipProvider>
                  </div>
                </Card>
              )
            })}
          </div>
        )}
      </ScrollArea>

      {/* Shared detail dialog */}
      <Dialog open={!!selectedAgent} onOpenChange={(open) => { if (!open) setSelectedAgent(null) }}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          {selectedAgent && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  {(() => { const Icon = selectedAgent.icon; return <Icon className={`h-5 w-5 ${selectedAgent.color}`} /> })()}
                  {selectedAgent.name}
                </DialogTitle>
                <DialogDescription>
                  Agent details and capabilities
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-4">
                <div>
                  <h4 className="font-medium mb-2 text-sm">Description</h4>
                  <p className="text-sm text-muted-foreground">{selectedAgent.description}</p>
                </div>

                {/* Version and Endpoint */}
                <div className="space-y-1 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="text-muted-foreground">Version:</span>
                    <span className="font-mono">{selectedAgent.version}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Globe className="h-3 w-3 text-muted-foreground" />
                    <span className="text-muted-foreground">Endpoint:</span>
                    <span className="font-mono text-xs truncate">{selectedAgent.endpoint}</span>
                  </div>
                </div>

                {/* Capabilities */}
                {selectedAgent.capabilities && Object.keys(selectedAgent.capabilities).length > 0 && (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <Zap className="h-3 w-3 text-muted-foreground" />
                      <span className="text-xs font-medium text-muted-foreground">Capabilities</span>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(selectedAgent.capabilities).map(([key, value]) =>
                        value ? (
                          <Badge key={key} variant="secondary" className="text-xs">
                            {key.replace(/([A-Z])/g, ' $1').trim()}
                          </Badge>
                        ) : null
                      )}
                    </div>
                  </div>
                )}

                {/* All Skills */}
                <div>
                  <h4 className="font-medium mb-2 text-sm">All Skills ({selectedAgent.skills?.length || 0})</h4>
                  <div className="space-y-2">
                    {(selectedAgent.skills || []).map((skill: any, idx: number) => (
                      <div key={idx} className="bg-muted/50 rounded p-3">
                        <div className="font-medium text-sm">{skill.name}</div>
                        <div className="text-sm text-muted-foreground mt-1">
                          {skill.description}
                        </div>
                        {skill.tags && skill.tags.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-2">
                            {skill.tags.map((tag: string, tagIdx: number) => (
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
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
