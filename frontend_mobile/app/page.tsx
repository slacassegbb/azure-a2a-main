"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import { getAuthToken, getUserInfo } from "@/lib/auth"
import { clearSession } from "@/lib/session"
import { fetchAndEnableAllAgents } from "@/lib/agent-registry"
import { updateConversationTitle } from "@/lib/conversation-api"
import { LoginScreen } from "@/components/login-screen"
import { ConversationsList } from "@/components/conversations-list"
import { ConversationDetail } from "@/components/conversation-detail"
import { SchedulesTab } from "@/components/schedules-tab"
import { MobileVoiceButton } from "@/components/mobile-voice-button"
import { InferenceSteps, type StepEvent } from "@/components/inference-steps"
import { MessageSquare, Calendar, LogOut, Wifi, WifiOff } from "lucide-react"
import { useEventHub } from "@/contexts/event-hub-context"

type Tab = "conversations" | "schedules"

export default function MobilePage() {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [isCheckingAuth, setIsCheckingAuth] = useState(true)
  const [activeTab, setActiveTab] = useState<Tab>("conversations")
  const [selectedConversation, setSelectedConversation] = useState<string | null>(null)
  const [agentsLoaded, setAgentsLoaded] = useState(false)
  const [liveInferenceEvents, setLiveInferenceEvents] = useState<StepEvent[]>([])
  const [isVoiceActive, setIsVoiceActive] = useState(false)
  const { isConnected, subscribe, unsubscribe } = useEventHub()
  const conversationsListRef = useRef<{ refresh: () => void } | null>(null)

  // Check auth on mount
  useEffect(() => {
    const token = getAuthToken()
    setIsAuthenticated(!!token)
    setIsCheckingAuth(false)
  }, [])

  // Auto-load and enable all agents on login
  useEffect(() => {
    if (isAuthenticated && !agentsLoaded) {
      fetchAndEnableAllAgents().then((agents) => {
        console.log(`[Mobile] ${agents.length} agents loaded and enabled`)
        setAgentsLoaded(true)
      })
    }
  }, [isAuthenticated, agentsLoaded])

  // Subscribe to inference events at the page level so we never miss them
  // Subscribe to inference events and file artifacts at the page level
  useEffect(() => {
    if (!isAuthenticated) return

    const handleActivity = (data: any) => {
      setLiveInferenceEvents((prev) => [...prev, data])
    }

    // Convert file_uploaded events into inference step events with imageUrl
    // so images/videos render inline in the agent activity timeline
    const handleFileUploaded = (data: any) => {
      if (!data?.fileInfo) return
      const filename = data.fileInfo.filename || ""
      const uri = data.fileInfo.uri || ""
      const agent = data.fileInfo.source_agent || "Agent"
      const ext = filename.toLowerCase().split(".").pop() || ""
      const imageExts = ["jpg", "jpeg", "png", "gif", "webp", "svg", "bmp"]
      const videoExts = ["mp4", "webm", "mov", "avi", "mkv"]
      const isMedia = imageExts.includes(ext) || videoExts.includes(ext)
      const verb = isMedia ? "Generated" : "Extracted"

      setLiveInferenceEvents((prev) => [...prev, {
        agentName: agent,
        content: `📎 ${verb} ${filename}`,
        activityType: "file",
        imageUrl: uri,
        imageName: filename,
        mediaType: isMedia ? (imageExts.includes(ext) ? `image/${ext === "jpg" ? "jpeg" : ext}` : `video/${ext}`) : undefined,
      }])
    }

    subscribe("remote_agent_activity", handleActivity)
    subscribe("file_uploaded", handleFileUploaded)
    return () => {
      unsubscribe("remote_agent_activity", handleActivity)
      unsubscribe("file_uploaded", handleFileUploaded)
    }
  }, [isAuthenticated, subscribe, unsubscribe, selectedConversation])

  const handleLoginSuccess = useCallback(() => {
    setIsAuthenticated(true)
    window.location.reload()
  }, [])

  const handleLogout = useCallback(() => {
    clearSession()
    setIsAuthenticated(false)
    setSelectedConversation(null)
    setAgentsLoaded(false)
    window.location.reload()
  }, [])

  const handleNewConversation = useCallback(() => {
    setSelectedConversation(null)
  }, [])

  const handleConversationCreated = useCallback((id: string) => {
    // Auto-navigate to the new conversation and switch to conversations tab
    setActiveTab("conversations")
    setSelectedConversation(id)
    // Clear any old inference events for the new conversation
    setLiveInferenceEvents([])
  }, [])

  const handleFirstMessage = useCallback((conversationId: string, transcript: string) => {
    const title = transcript.length > 50 ? transcript.slice(0, 50) + "..." : transcript
    updateConversationTitle(conversationId, title)
  }, [])

  const handleVoiceStateChange = useCallback((active: boolean) => {
    setIsVoiceActive(active)
    if (active) {
      // Clear inference events when starting a new voice query
      setLiveInferenceEvents([])
    }
  }, [])

  // Show loading while checking auth
  if (isCheckingAuth) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-pulse text-muted-foreground">Loading...</div>
      </div>
    )
  }

  if (!isAuthenticated) {
    return <LoginScreen onSuccess={handleLoginSuccess} />
  }

  const user = getUserInfo()

  return (
    <div className="flex flex-col h-[100dvh] safe-top safe-bottom">
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-2 border-b bg-card/80 backdrop-blur-sm">
        <div className="flex items-center gap-2">
          {isConnected ? (
            <Wifi className="h-3.5 w-3.5 text-green-500" />
          ) : (
            <WifiOff className="h-3.5 w-3.5 text-red-500" />
          )}
          <span className="text-xs text-muted-foreground">
            {user?.name || user?.email || "User"}
          </span>
        </div>
        <button
          onClick={handleLogout}
          className="p-1.5 text-muted-foreground hover:text-foreground transition-colors"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>

      {/* Main content area */}
      <div className="flex-1 overflow-hidden">
        {activeTab === "conversations" ? (
          selectedConversation ? (
            <ConversationDetail
              conversationId={selectedConversation}
              onBack={() => setSelectedConversation(null)}
              externalInferenceEvents={liveInferenceEvents}
            />
          ) : (
            <ConversationsList
              onSelect={setSelectedConversation}
              onNew={handleNewConversation}
              selectedId={selectedConversation}
            />
          )
        ) : (
          <SchedulesTab />
        )}
      </div>

      {/* Voice button area - always visible */}
      <div className="border-t bg-card/80 backdrop-blur-sm py-4 px-4">
        <MobileVoiceButton
          conversationId={selectedConversation}
          onConversationCreated={handleConversationCreated}
          onFirstMessage={handleFirstMessage}
          onVoiceStateChange={handleVoiceStateChange}
        />
      </div>

      {/* Bottom tab bar */}
      <div className="flex border-t bg-card safe-bottom">
        <button
          onClick={() => { setActiveTab("conversations"); setSelectedConversation(null) }}
          className={`flex-1 flex flex-col items-center gap-0.5 py-2.5 transition-colors ${
            activeTab === "conversations" ? "text-primary" : "text-muted-foreground"
          }`}
        >
          <MessageSquare className="h-5 w-5" />
          <span className="text-[10px] font-medium">Chats</span>
        </button>
        <button
          onClick={() => setActiveTab("schedules")}
          className={`flex-1 flex flex-col items-center gap-0.5 py-2.5 transition-colors ${
            activeTab === "schedules" ? "text-primary" : "text-muted-foreground"
          }`}
        >
          <Calendar className="h-5 w-5" />
          <span className="text-[10px] font-medium">Schedules</span>
        </button>
      </div>
    </div>
  )
}
