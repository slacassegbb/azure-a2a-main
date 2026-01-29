"use client"

import { useState, useEffect, useCallback } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { User, Clock, Phone, MessageCircle, UserPlus } from "lucide-react"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { useEventHub } from "@/hooks/use-event-hub"
import { useToast } from "@/hooks/use-toast"
import { SessionInviteButton } from "@/components/session-invite"
import { leaveCollaborativeSession, isInCollaborativeSession } from "@/lib/session"

type ConnectedUser = {
  user_id: string
  name: string
  email: string
  role: string
  description: string
  skills: string[]
  color: string
  last_seen: string
  status: string
}

export function ConnectedUsers() {
  const [users, setUsers] = useState<ConnectedUser[]>([])
  const [expandedUsers, setExpandedUsers] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(false)
  const { subscribe, unsubscribe, sendMessage, isConnected } = useEventHub()
  const { toast } = useToast()

  const fetchActiveUsers = useCallback(async () => {
    try {
      const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || "http://localhost:12000"
      const token = sessionStorage.getItem('auth_token')
      
      // If no token, user is not logged in - show empty
      if (!token) {
        setUsers([])
        return
      }
      
      const response = await fetch(`${baseUrl}/api/auth/active-users`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      })
      
      if (response.status === 401) {
        // Token invalid/expired - user not logged in
        setUsers([])
        return
      }
      
      const data = await response.json()
      
      if (data.success) {
        setUsers(data.users)
      }
    } catch (error) {
      console.error("Failed to fetch active users:", error)
    } finally {
      setLoading(false)
    }
  }, [])

  // Handle real-time user list updates from WebSocket
  const handleUserListUpdate = useCallback((eventData: any) => {
    console.log("[ConnectedUsers] Real-time user list update:", eventData)
    console.log("[ConnectedUsers] Active users data:", eventData.data?.active_users)
    console.log("[ConnectedUsers] Total active:", eventData.data?.total_active)
    if (eventData.data?.active_users) {
      setUsers(eventData.data.active_users)
      console.log("[ConnectedUsers] Updated users state with", eventData.data.active_users.length, "users")
    } else {
      console.warn("[ConnectedUsers] Received user_list_update but no active_users data!")
    }
  }, [])

  // Handle session ended (owner left/logged out)
  const handleSessionEnded = useCallback((eventData: any) => {
    console.log("[ConnectedUsers] Session ended event:", eventData)
    const message = eventData.data?.message || "Session has ended"
    
    // Only handle if we're in a collaborative session (we're a member, not owner)
    if (isInCollaborativeSession()) {
      console.log("[ConnectedUsers] We're in a collaborative session that just ended, returning to own session")
      
      // Show toast notification
      toast({
        title: "Session Ended",
        description: message,
        variant: "default",
      })
      
      // Wait a moment for toast to show, then return to own session
      setTimeout(() => {
        leaveCollaborativeSession(true) // Clear local storage and reload
      }, 1500)
    }
  }, [toast])

  useEffect(() => {
    // Subscribe to real-time user list updates (source of truth)
    subscribe("user_list_update", handleUserListUpdate)
    
    // Subscribe to session ended events (owner left/logged out)
    subscribe("session_ended", handleSessionEnded)
    
    // Request the user list after subscribing
    // This solves the race condition where the backend sends user_list_update
    // before the component has subscribed
    if (isConnected) {
      console.log("[ConnectedUsers] Requesting session users...")
      sendMessage({ type: "get_session_users" })
    }
    
    return () => {
      unsubscribe("user_list_update", handleUserListUpdate)
      unsubscribe("session_ended", handleSessionEnded)
    }
  }, []) // Only subscribe once on mount, unsubscribe on unmount - don't re-subscribe!

  const toggleUser = (userId: string) => {
    const newExpanded = new Set(expandedUsers)
    if (newExpanded.has(userId)) {
      newExpanded.delete(userId)
    } else {
      newExpanded.add(userId)
    }
    setExpandedUsers(newExpanded)
  }

  const getAvatarStyles = (hexColor: string) => {
    // Convert hex to RGB
    const hex = hexColor.replace('#', '')
    const r = parseInt(hex.substr(0, 2), 16)
    const g = parseInt(hex.substr(2, 2), 16)
    const b = parseInt(hex.substr(4, 2), 16)
    
    // Create light background version (add transparency)
    const bgColor = `rgba(${r}, ${g}, ${b}, 0.1)`
    const iconColor = hexColor
    
    return { bgColor, iconColor }
  }

  const formatLastSeen = (lastSeen: string) => {
    const date = new Date(lastSeen)
    const now = new Date()
    const diffMinutes = Math.floor((now.getTime() - date.getTime()) / (1000 * 60))
    
    if (diffMinutes < 1) return "Just now"
    if (diffMinutes < 60) return `${diffMinutes}m ago`
    if (diffMinutes < 1440) return `${Math.floor(diffMinutes / 60)}h ago`
    return `${Math.floor(diffMinutes / 1440)}d ago`
  }

  if (loading) {
    return (
      <div className="p-3">
        <div className="text-sm text-muted-foreground">Loading session...</div>
      </div>
    )
  }

  if (users.length === 0) {
    // Check if user is logged in (has token)
    const token = typeof window !== 'undefined' ? sessionStorage.getItem('auth_token') : null
    return (
      <div className="p-3">
        <div className="text-sm text-muted-foreground">
          {token ? "Session loading..." : "Not logged in"}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {/* Header with invite button */}
      <div className="flex items-center justify-between px-1 mb-2">
        <span className="text-xs text-muted-foreground">Session Users</span>
        <SessionInviteButton />
      </div>
      
      {users.map((user) => {
        const { bgColor, iconColor } = getAvatarStyles(user.color)
        const isExpanded = expandedUsers.has(user.user_id)
        
        return (
          <Card key={user.user_id} className="transition-all duration-200 hover:shadow-md">
            <Collapsible open={isExpanded} onOpenChange={() => toggleUser(user.user_id)}>
              <CollapsibleTrigger asChild>
                <CardHeader className="cursor-pointer p-3 hover:bg-muted/50 transition-colors">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div 
                        className="p-2 rounded-lg flex items-center justify-center"
                        style={{ backgroundColor: bgColor }}
                      >
                        <User className="h-4 w-4" style={{ color: iconColor }} />
                      </div>
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <CardTitle className="text-sm font-semibold">{user.name}</CardTitle>
                          <div className="w-2 h-2 rounded-full bg-green-500" title="Online"></div>
                        </div>
                        <div className="text-xs text-muted-foreground">{user.role}</div>
                      </div>
                    </div>
                    <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 w-8 p-0"
                        onClick={() => {
                          // TODO: Implement call functionality
                          console.log('Call user:', user.name)
                        }}
                        title="Call"
                      >
                        <Phone className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 w-8 p-0"
                        onClick={() => {
                          // TODO: Implement message functionality
                          console.log('Message user:', user.name)
                        }}
                        title="Message"
                      >
                        <MessageCircle className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </CardHeader>
              </CollapsibleTrigger>
              
              <CollapsibleContent>
                <CardContent className="pt-0 space-y-3">
                  {/* Description */}
                  {user.description && (
                    <div>
                      <div className="text-xs font-medium text-muted-foreground mb-1">About</div>
                      <div className="text-xs text-foreground">{user.description}</div>
                    </div>
                  )}
                  
                  {/* Skills */}
                  {user.skills && user.skills.length > 0 && (
                    <div>
                      <div className="text-xs font-medium text-muted-foreground mb-2">Skills</div>
                      <div className="flex flex-wrap gap-1">
                        {user.skills.map((skill, index) => (
                          <Badge 
                            key={index} 
                            variant="secondary" 
                            className="text-xs px-2 py-1"
                          >
                            {skill}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}
                  
                  {/* Contact Info */}
                  <div>
                    <div className="text-xs font-medium text-muted-foreground mb-1">Contact</div>
                    <div className="text-xs text-foreground">{user.email}</div>
                  </div>
                </CardContent>
              </CollapsibleContent>
            </Collapsible>
          </Card>
        )
      })}
    </div>
  )
}
