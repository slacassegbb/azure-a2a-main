"use client"

import { useState, useEffect, useCallback } from "react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { User, UserPlus, Check, X, Loader2 } from "lucide-react"
import { useEventHub } from "@/hooks/use-event-hub"
import { useToast } from "@/hooks/use-toast"

type OnlineUser = {
  user_id: string
  username: string
  email: string
}

type SessionInvitation = {
  invitation_id: string
  from_user_id: string
  from_username: string
  session_id: string
  timestamp: string
}

export function SessionInviteButton() {
  const [isOpen, setIsOpen] = useState(false)
  const [onlineUsers, setOnlineUsers] = useState<OnlineUser[]>([])
  const [loading, setLoading] = useState(false)
  const [invitingUserId, setInvitingUserId] = useState<string | null>(null)
  const { sendMessage, subscribe, unsubscribe } = useEventHub()
  const { toast } = useToast()

  // Handle receiving online users list
  const handleOnlineUsers = useCallback((eventData: any) => {
    console.log("[SessionInvite] Received online users:", eventData)
    if (eventData.users) {
      setOnlineUsers(eventData.users)
    }
    setLoading(false)
  }, [])

  // Handle invitation sent confirmation
  const handleInviteSent = useCallback((eventData: any) => {
    console.log("[SessionInvite] Invitation sent:", eventData)
    setInvitingUserId(null)
    toast({
      title: "Invitation Sent",
      description: "Waiting for the user to accept...",
    })
  }, [toast])

  // Handle invitation error
  const handleInviteError = useCallback((eventData: any) => {
    console.log("[SessionInvite] Invitation error:", eventData)
    setInvitingUserId(null)
    toast({
      title: "Error",
      description: eventData.error || "Failed to send invitation",
      variant: "destructive",
    })
  }, [toast])

  // Handle invitation response
  const handleInviteResponse = useCallback((eventData: any) => {
    console.log("[SessionInvite] Invitation response:", eventData)
    if (eventData.accepted) {
      toast({
        title: "Invitation Accepted!",
        description: `${eventData.from_username} has joined your session`,
      })
    } else {
      toast({
        title: "Invitation Declined",
        description: `${eventData.from_username} declined your invitation`,
      })
    }
  }, [toast])

  useEffect(() => {
    subscribe("online_users", handleOnlineUsers)
    subscribe("session_invite_sent", handleInviteSent)
    subscribe("session_invite_error", handleInviteError)
    subscribe("session_invite_response_received", handleInviteResponse)

    return () => {
      unsubscribe("online_users", handleOnlineUsers)
      unsubscribe("session_invite_sent", handleInviteSent)
      unsubscribe("session_invite_error", handleInviteError)
      unsubscribe("session_invite_response_received", handleInviteResponse)
    }
  }, [subscribe, unsubscribe, handleOnlineUsers, handleInviteSent, handleInviteError, handleInviteResponse])

  const fetchOnlineUsers = () => {
    setLoading(true)
    sendMessage({
      type: "get_online_users"
    })
  }

  const sendInvitation = (user: OnlineUser) => {
    // Get session ID from sessionStorage or localStorage
    const sessionId = sessionStorage.getItem('session_id') || localStorage.getItem('anonymous_session_id') || ''
    
    if (!sessionId) {
      toast({
        title: "Error",
        description: "No active session found",
        variant: "destructive",
      })
      return
    }

    setInvitingUserId(user.user_id)
    sendMessage({
      type: "session_invite",
      target_user_id: user.user_id,
      target_username: user.username,
      session_id: sessionId
    })
  }

  const handleOpenChange = (open: boolean) => {
    setIsOpen(open)
    if (open) {
      fetchOnlineUsers()
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 w-8 p-0"
          title="Invite user to session"
        >
          <UserPlus className="h-4 w-4" />
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Invite User to Session</DialogTitle>
          <DialogDescription>
            Select an online user to invite to your collaborative session
          </DialogDescription>
        </DialogHeader>
        <div className="py-4">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : onlineUsers.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <User className="h-12 w-12 mx-auto mb-2 opacity-50" />
              <p>No other users online</p>
            </div>
          ) : (
            <div className="space-y-2">
              {onlineUsers.map((user) => (
                <div
                  key={user.user_id}
                  className="flex items-center justify-between p-3 rounded-lg border hover:bg-muted/50 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-primary/10">
                      <User className="h-4 w-4 text-primary" />
                    </div>
                    <div>
                      <div className="font-medium text-sm">{user.username}</div>
                      <div className="text-xs text-muted-foreground">{user.email}</div>
                    </div>
                  </div>
                  <Button
                    size="sm"
                    onClick={() => sendInvitation(user)}
                    disabled={invitingUserId === user.user_id}
                  >
                    {invitingUserId === user.user_id ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      "Invite"
                    )}
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function SessionInvitationNotification() {
  const [pendingInvitations, setPendingInvitations] = useState<SessionInvitation[]>([])
  const { sendMessage, subscribe, unsubscribe } = useEventHub()
  const { toast } = useToast()

  // Handle receiving an invitation
  const handleInviteReceived = useCallback((eventData: any) => {
    console.log("[SessionInvite] Received invitation:", eventData)
    setPendingInvitations(prev => [...prev, {
      invitation_id: eventData.invitation_id,
      from_user_id: eventData.from_user_id,
      from_username: eventData.from_username,
      session_id: eventData.session_id,
      timestamp: eventData.timestamp
    }])
    
    toast({
      title: "Session Invitation",
      description: `${eventData.from_username} invited you to collaborate`,
    })
  }, [toast])

  // Handle response error
  const handleResponseError = useCallback((eventData: any) => {
    toast({
      title: "Error",
      description: eventData.error || "Failed to respond to invitation",
      variant: "destructive",
    })
  }, [toast])

  // Handle session members updated
  const handleMembersUpdated = useCallback((eventData: any) => {
    console.log("[SessionInvite] Session members updated:", eventData)
    // Could update UI to show current session members
  }, [])

  useEffect(() => {
    subscribe("session_invite_received", handleInviteReceived)
    subscribe("session_invite_response_error", handleResponseError)
    subscribe("session_members_updated", handleMembersUpdated)

    return () => {
      unsubscribe("session_invite_received", handleInviteReceived)
      unsubscribe("session_invite_response_error", handleResponseError)
      unsubscribe("session_members_updated", handleMembersUpdated)
    }
  }, [subscribe, unsubscribe, handleInviteReceived, handleResponseError, handleMembersUpdated])

  const respondToInvitation = (invitation: SessionInvitation, accepted: boolean) => {
    sendMessage({
      type: "session_invite_response",
      invitation_id: invitation.invitation_id,
      accepted
    })
    
    // Remove from pending
    setPendingInvitations(prev => 
      prev.filter(inv => inv.invitation_id !== invitation.invitation_id)
    )

    if (accepted) {
      toast({
        title: "Joined Session",
        description: `You've joined ${invitation.from_username}'s session`,
      })
    }
  }

  if (pendingInvitations.length === 0) {
    return null
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 space-y-2">
      {pendingInvitations.map((invitation) => (
        <div
          key={invitation.invitation_id}
          className="bg-background border rounded-lg shadow-lg p-4 w-80 animate-in slide-in-from-right"
        >
          <div className="flex items-start gap-3">
            <div className="p-2 rounded-lg bg-primary/10">
              <UserPlus className="h-5 w-5 text-primary" />
            </div>
            <div className="flex-1">
              <h4 className="font-medium text-sm">Session Invitation</h4>
              <p className="text-xs text-muted-foreground mt-1">
                <span className="font-medium">{invitation.from_username}</span> wants to collaborate with you
              </p>
              <div className="flex gap-2 mt-3">
                <Button
                  size="sm"
                  onClick={() => respondToInvitation(invitation, true)}
                  className="flex-1"
                >
                  <Check className="h-4 w-4 mr-1" />
                  Accept
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => respondToInvitation(invitation, false)}
                  className="flex-1"
                >
                  <X className="h-4 w-4 mr-1" />
                  Decline
                </Button>
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
