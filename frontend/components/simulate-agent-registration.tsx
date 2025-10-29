"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { useEventHub } from "@/hooks/use-event-hub"
import { Bot, Plus, ExternalLink, Store } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useToast } from "@/hooks/use-toast"
import { AgentCatalog } from "./agent-catalog"

/**
 * This component allows users to register remote agents by entering their address.
 * It uses the existing A2A protocol infrastructure to discover and register agents.
 */
export function SimulateAgentRegistration() {
  const { emit } = useEventHub()
  const { toast } = useToast()
  const [open, setOpen] = useState(false)
  const [catalogOpen, setCatalogOpen] = useState(false)
  const [agentAddress, setAgentAddress] = useState("")
  const [isRegistering, setIsRegistering] = useState(false)
  
  const handleRegister = async () => {
    if (!agentAddress.trim()) {
      toast({
        title: "Invalid Address",
        description: "Please enter a valid agent address",
        variant: "destructive",
      })
      return
    }

    // Basic URL validation
    try {
      new URL(agentAddress)
    } catch {
      toast({
        title: "Invalid URL",
        description: "Please enter a valid URL (e.g., https://agent.example.com)",
        variant: "destructive",
      })
      return
    }

    setIsRegistering(true)
    
    try {
      // Call backend to register the agent
      const response = await fetch('/api/register-agent', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ address: agentAddress.trim() }),
      })

      const result = await response.json()

      if (response.ok && result.success) {
        toast({
          title: "Agent Registered",
          description: `Successfully registered agent at ${agentAddress}`,
        })
        setAgentAddress("")
        setOpen(false)
        
        // The agent registry will update immediately via WebSocket real-time sync
        console.log('[Register New Agent] Agent registered - UI will update in real-time')
      } else {
        const errorMessage = result.error || "Failed to register agent"
        toast({
          title: "Registration Failed",
          description: errorMessage.includes("404") 
            ? `Agent at ${agentAddress} does not have a valid A2A agent card at /.well-known/agent-card.json`
            : errorMessage,
          variant: "destructive",
        })
      }
    } catch (error) {
      console.error("Error registering agent:", error)
      toast({
        title: "Registration Error",
        description: "An error occurred while registering the agent",
        variant: "destructive",
      })
    } finally {
      setIsRegistering(false)
    }
  }

  return (
    <div className="space-y-2">
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button className="w-full">
            <Plus className="mr-2 h-4 w-4" />
            Register New Agent
          </Button>
        </DialogTrigger>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Bot className="h-5 w-5" />
              Register Remote Agent
            </DialogTitle>
            <DialogDescription>
              Enter the address of a remote A2A agent to register it with this host.
              The agent must be running and accessible via HTTP/HTTPS.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="address" className="text-right">
                Address
              </Label>
              <Input
                id="address"
                placeholder="https://agent.example.com"
                value={agentAddress}
                onChange={(e) => setAgentAddress(e.target.value)}
                className="col-span-3"
                disabled={isRegistering}
              />
            </div>
            <div className="text-sm text-muted-foreground">
              <div className="flex items-center gap-1">
                <ExternalLink className="h-3 w-3" />
                <span>Examples: https://agent1.ngrok.app, http://localhost:8000</span>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button 
              type="submit" 
              onClick={handleRegister}
              disabled={isRegistering || !agentAddress.trim()}
            >
              {isRegistering ? "Registering..." : "Register Agent"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={catalogOpen} onOpenChange={setCatalogOpen}>
        <DialogTrigger asChild>
          <Button variant="outline" className="w-full">
            <Store className="mr-2 h-4 w-4" />
            Agent Catalog
          </Button>
        </DialogTrigger>
        <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Store className="h-5 w-5" />
              Agent Catalog
            </DialogTitle>
            <DialogDescription>
              Browse and start pre-configured agents for various tasks.
            </DialogDescription>
          </DialogHeader>
          <AgentCatalog />
        </DialogContent>
      </Dialog>
    </div>
  )
}
