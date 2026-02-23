"use client"

import { useState, useEffect, useRef, useCallback, useMemo } from "react"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { Paperclip, Mic, MicOff, Send, Bot, User, Paintbrush, Copy, ThumbsUp, ThumbsDown, Loader2, Plus, Pencil, X, Sparkles, Square, Zap } from "lucide-react"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useEventHub } from "@/hooks/use-event-hub"
import { useVoiceRecording } from "@/hooks/use-voice-recording"
import { VoiceButton } from "@/components/voice-button"
import { InferenceSteps } from "./inference-steps"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeHighlight from "rehype-highlight"
import { useSearchParams, useRouter } from "next/navigation"
import { getConversation, updateConversationTitle, createConversation, notifyConversationCreated, type Message as APIMessage } from "@/lib/conversation-api"
import { createContextId, getOrCreateSessionId } from "@/lib/session"
import { logDebug, warnDebug, errorDebug, logInfo, DEBUG } from '@/lib/debug'

// Helper function to generate conversation title from first message
const generateTitleFromMessage = (message: string): string => {
  // Clean up the message and truncate to reasonable length
  const cleaned = message.trim().replace(/\n/g, ' ').replace(/\s+/g, ' ')
  return cleaned.length > 50 ? cleaned.slice(0, 47) + '...' : cleaned
}

// Helper function to get avatar styles from hex color
const getAvatarStyles = (hexColor: string = "#6B7280") => {
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

// Typing animation component for welcome message
function TypingWelcomeMessage({ text }: { text: string }) {
  const [displayedText, setDisplayedText] = useState("")
  const [currentIndex, setCurrentIndex] = useState(0)

  useEffect(() => {
    // Reset when component mounts
    setDisplayedText("")
    setCurrentIndex(0)
  }, [])

  useEffect(() => {
    if (currentIndex < text.length) {
      const timeout = setTimeout(() => {
        setDisplayedText(prev => prev + text[currentIndex])
        setCurrentIndex(prev => prev + 1)
      }, 50) // Adjust speed here (50ms per character)

      return () => clearTimeout(timeout)
    }
  }, [currentIndex, text])

  return (
    <h1 className="text-4xl font-semibold text-center">
      {displayedText}
      {currentIndex < text.length && (
        <span className="animate-pulse">|</span>
      )}
    </h1>
  )
}

type MessageReaction = {
  emoji: string
  users: string[] // Array of user IDs who reacted
  usernames: string[] // Array of usernames for display
}

type Message = {
  id: string
  role: "user" | "assistant" | "system"
  content?: string
  agent?: string
  type?: "inference_summary"
  steps?: { agent: string; status: string; imageUrl?: string; imageName?: string }[]
  // User ID for looking up user info
  userId?: string
  // Just username for showing who sent the message
  username?: string
  // User color for the avatar
  userColor?: string
  attachments?: {
    uri: string
    fileName?: string
    fileSize?: number
    mediaType?: string
    storageType?: string
    // Video remix metadata (for Sora videos)
    videoId?: string
    generationId?: string
    originalVideoId?: string
  }[]
  // Images from DataPart artifacts (loaded from conversation history)
  images?: {
    uri: string
    fileName?: string
    mimeType?: string
    videoId?: string // For video remix functionality
  }[]
  // Reactions from users
  reactions?: MessageReaction[]
  // Message metadata (includes workflow_plan for workflow messages)
  metadata?: {
    type?: string
    workflow_plan?: any
    [key: string]: any
  }
}

const initialMessages: Message[] = []

type MaskEditorDialogProps = {
  open: boolean
  imageUrl: string
  onClose: () => void
  onSave: (blob: Blob) => Promise<void> | void
}

function MaskEditorDialog({ open, imageUrl, onClose, onSave }: MaskEditorDialogProps) {
  const imageRef = useRef<HTMLImageElement>(null)
  const overlayRef = useRef<HTMLCanvasElement>(null)
  const [imageLoaded, setImageLoaded] = useState(false)
  const [brushSize, setBrushSize] = useState(80)
  const [mode, setMode] = useState<"paint" | "erase">("paint")
  const isDrawingRef = useRef(false)
  const lastPointRef = useRef<{ x: number; y: number } | null>(null)
  const [maskDirty, setMaskDirty] = useState(false)
  const [isSaving, setIsSaving] = useState(false)

  const resetCanvas = useCallback(() => {
    const overlay = overlayRef.current
    if (overlay) {
      const ctx = overlay.getContext("2d")
      if (ctx) {
        ctx.clearRect(0, 0, overlay.width, overlay.height)
      }
    }
    setMaskDirty(false)
  }, [])

  const handleImageLoad = useCallback(() => {
    const imageEl = imageRef.current
    const overlay = overlayRef.current
    if (!imageEl || !overlay) {
      return
    }

    const width = imageEl.naturalWidth || imageEl.width
    const height = imageEl.naturalHeight || imageEl.height
    overlay.width = width
    overlay.height = height

    const ctx = overlay.getContext("2d")
    if (ctx) {
      ctx.clearRect(0, 0, width, height)
    }

    setMaskDirty(false)
    setImageLoaded(true)
  }, [])

  const handleImageError = useCallback(() => {
    setImageLoaded(false)
  }, [])

  useEffect(() => {
    if (!open) {
      setImageLoaded(false)
      setMaskDirty(false)
      const overlay = overlayRef.current
      const ctx = overlay?.getContext("2d")
      if (ctx && overlay) {
        ctx.clearRect(0, 0, overlay.width, overlay.height)
      }
    }
  }, [open])

  useEffect(() => {
    const overlay = overlayRef.current
    const ctx = overlay?.getContext("2d")
    if (ctx && overlay) {
      ctx.clearRect(0, 0, overlay.width, overlay.height)
    }
    setMaskDirty(false)
    setImageLoaded(false)
  }, [imageUrl])

  const getRelativePoint = useCallback((event: React.PointerEvent<HTMLCanvasElement>) => {
    const overlay = overlayRef.current
    if (!overlay) {
      return { x: 0, y: 0 }
    }
    const rect = overlay.getBoundingClientRect()
    const scaleX = overlay.width / rect.width
    const scaleY = overlay.height / rect.height
    const x = (event.clientX - rect.left) * scaleX
    const y = (event.clientY - rect.top) * scaleY
    return { x, y }
  }, [])

  const paintStroke = useCallback((event: React.PointerEvent<HTMLCanvasElement>) => {
    const overlay = overlayRef.current
    if (!overlay) {
      return
    }
    const ctx = overlay.getContext("2d")
    if (!ctx) {
      return
    }

    const point = getRelativePoint(event)
    const lastPoint = lastPointRef.current || point

    ctx.save()
    ctx.lineJoin = "round"
    ctx.lineCap = "round"
    ctx.lineWidth = brushSize

    if (mode === "paint") {
      ctx.globalCompositeOperation = "source-over"
      ctx.strokeStyle = "rgba(239, 68, 68, 0.65)"
    } else {
      ctx.globalCompositeOperation = "destination-out"
      ctx.strokeStyle = "rgba(0, 0, 0, 1)"
    }

    ctx.beginPath()
    ctx.moveTo(lastPoint.x, lastPoint.y)
    ctx.lineTo(point.x, point.y)
    ctx.stroke()

    if (mode === "paint") {
      ctx.globalCompositeOperation = "source-over"
      ctx.fillStyle = "rgba(239, 68, 68, 0.65)"
      ctx.beginPath()
      ctx.arc(point.x, point.y, brushSize / 2, 0, Math.PI * 2)
      ctx.fill()
    }

    ctx.restore()
    lastPointRef.current = point
    setMaskDirty(true)
    
    // Debug: Log that we're drawing
    if (!lastPointRef.current || Math.random() < 0.1) { // Log occasionally
      logDebug(`✏️ Drawing on canvas: mode=${mode}, brush=${brushSize}px, point=(${Math.round(point.x)},${Math.round(point.y)})`)
    }
  }, [brushSize, getRelativePoint, mode])

  const handlePointerDown = useCallback((event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!imageLoaded) {
      return
    }
    event.preventDefault()
    const overlay = overlayRef.current
    if (!overlay) {
      return
    }
    const point = getRelativePoint(event)
    lastPointRef.current = point
    isDrawingRef.current = true
    try {
      event.currentTarget.setPointerCapture(event.pointerId)
    } catch (err) {
      warnDebug("Pointer capture failed", err)
    }
    paintStroke(event)
  }, [getRelativePoint, imageLoaded, paintStroke])

  const handlePointerMove = useCallback((event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!isDrawingRef.current) {
      return
    }
    event.preventDefault()
    paintStroke(event)
  }, [paintStroke])

  const stopDrawing = useCallback((event?: React.PointerEvent<HTMLCanvasElement>) => {
    if (!isDrawingRef.current) {
      return
    }
    isDrawingRef.current = false
    lastPointRef.current = null
    if (event) {
      try {
        event.currentTarget.releasePointerCapture(event.pointerId)
      } catch (err) {
        // Ignore release errors
      }
    }
  }, [])

  const exportMask = useCallback(async () => {
    const overlay = overlayRef.current
    if (!overlay || !imageLoaded || isSaving) {
      return
    }

    setIsSaving(true)

    const exportCanvas = document.createElement("canvas")
    exportCanvas.width = overlay.width
    exportCanvas.height = overlay.height

    const exportCtx = exportCanvas.getContext("2d")
    const sourceCtx = overlay.getContext("2d")

    if (!exportCtx || !sourceCtx) {
      setIsSaving(false)
      return
    }

    const overlayData = sourceCtx.getImageData(0, 0, overlay.width, overlay.height)
    const exportData = exportCtx.createImageData(overlay.width, overlay.height)

    // Initialize to white
    for (let i = 0; i < exportData.data.length; i += 4) {
      exportData.data[i] = 255
      exportData.data[i + 1] = 255
      exportData.data[i + 2] = 255
      exportData.data[i + 3] = 255
    }

    // Convert drawn areas to transparent mask (OpenAI expects transparent = edit)
    let drawnPixelCount = 0
    for (let i = 0; i < overlayData.data.length; i += 4) {
      const alpha = overlayData.data[i + 3]
      if (alpha > 10) {
        exportData.data[i] = 0
        exportData.data[i + 1] = 0
        exportData.data[i + 2] = 0
        exportData.data[i + 3] = 0  // Transparent (alpha=0) for areas to edit
        drawnPixelCount++
      }
    }
    
    logDebug(`🎨 Mask creation: ${drawnPixelCount} drawn pixels found (canvas size: ${overlay.width}x${overlay.height})`)
    if (drawnPixelCount === 0) {
      warnDebug('⚠️ No drawn pixels found! Mask will be completely white.')
    }

    exportCtx.putImageData(exportData, 0, 0)

    exportCanvas.toBlob(async (blob) => {
      if (!blob) {
        setIsSaving(false)
        return
      }
      try {
        await onSave(blob)
        onClose()
      } catch (error) {
        console.error('Error saving mask:', error)
      } finally {
        setIsSaving(false)
      }
    }, "image/png", 1)
  }, [imageLoaded, isSaving, onClose, onSave])

  return (
    <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
      <DialogContent className="max-w-5xl w-full">
        <DialogHeader>
          <DialogTitle>Paint a mask for targeted refinement</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <div className="text-sm text-muted-foreground">
            Highlight the area you want the model to change. Painted regions become transparent in the mask so only that area is edited.
          </div>
          <div className="flex flex-col lg:flex-row gap-4">
            <div className="flex-1">
              <div className="relative w-full border rounded-lg overflow-hidden bg-black/10"
                   style={{ maxHeight: "70vh" }}>
                <img
                  ref={imageRef}
                  src={imageUrl}
                  alt="Image for mask refinement"
                  className="w-full h-auto pointer-events-none select-none"
                  onLoad={handleImageLoad}
                  onError={handleImageError}
                  draggable={false}
                />
                <canvas
                  ref={overlayRef}
                  className="absolute inset-0 w-full h-full cursor-crosshair"
                  onPointerDown={handlePointerDown}
                  onPointerMove={handlePointerMove}
                  onPointerUp={stopDrawing}
                  onPointerLeave={stopDrawing}
                  onContextMenu={(e) => e.preventDefault()}
                  style={{ display: imageLoaded ? "block" : "none" }}
                />
                {!imageLoaded && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-sm text-muted-foreground bg-background/90 backdrop-blur-sm">
                    <Loader2 className="h-8 w-8 animate-spin text-primary" />
                    <p>Loading image…</p>
                  </div>
                )}
              </div>
            </div>
            <div className="w-full lg:w-64 flex-shrink-0 space-y-4">
              <div>
                <p className="text-sm font-medium mb-2">Brush size</p>
                <input
                  type="range"
                  min={10}
                  max={200}
                  value={brushSize}
                  onChange={(event) => setBrushSize(Number(event.target.value))}
                  className="w-full"
                />
                <div className="text-xs text-muted-foreground mt-1">{brushSize}px</div>
              </div>
              <div className="flex gap-2">
                <Button
                  variant={mode === "paint" ? "default" : "secondary"}
                  size="sm"
                  onClick={() => setMode("paint")}
                >
                  <Paintbrush className="h-4 w-4 mr-2" />Paint
                </Button>
                <Button
                  variant={mode === "erase" ? "default" : "secondary"}
                  size="sm"
                  onClick={() => setMode("erase")}
                >
                  Erase
                </Button>
              </div>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="flex-1"
                  onClick={resetCanvas}
                  disabled={!maskDirty}
                >
                  Clear mask
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={onClose}
                >
                  Cancel
                </Button>
              </div>
              <Button
                onClick={exportMask}
                disabled={!imageLoaded || isSaving}
                className="w-full"
              >
                {isSaving ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Saving mask...
                  </>
                ) : (
                  'Save mask & continue'
                )}
              </Button>
              <p className="text-xs text-muted-foreground">
                Tip: Use paint to mark the area you want to transform. Switch to erase for quick adjustments.
              </p>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

type ChatPanelProps = {
  dagNodes: any[]
  dagLinks: any[]
  enableInterAgentMemory: boolean
  workflow?: string
  workflowGoal?: string
  activeWorkflows?: Array<{
    id: string
    workflow: string
    name: string
    description?: string
    goal: string
  }>
  registeredAgents?: any[]
  connectedUsers?: any[]
  activeNode?: string | null
  setActiveNode?: (node: string | null) => void
}

export function ChatPanel({ dagNodes, dagLinks, enableInterAgentMemory, workflow, workflowGoal, activeWorkflows = [], registeredAgents = [], connectedUsers = [], activeNode: externalActiveNode, setActiveNode: externalSetActiveNode }: ChatPanelProps) {
  // Use the shared Event Hub hook so we subscribe to the same client as the rest of the app
  const { subscribe, unsubscribe, emit, sendMessage, isConnected } = useEventHub()

  // Build agent name -> hex color map from registered agents for InferenceSteps
  const agentColors = useMemo(() => {
    const map: Record<string, string> = {}
    for (const agent of registeredAgents) {
      if (agent.name && agent.color) map[agent.name] = agent.color
    }
    return map
  }, [registeredAgents])
  
  // Helper function to check if workflow's required agents are available in the session
  const isWorkflowRunnable = (workflowText: string): boolean => {
    // Parse workflow text to extract agent names
    const lines = workflowText.split('\n').filter(l => l.trim())
    const requiredAgents: string[] = []
    for (const line of lines) {
      const match = line.match(/^\d+\.\s*\[([^\]]+)\]/) || line.match(/^\d+\.\s*(?:Use the\s+)?([^:]+?)(?:\s+agent)?:/i)
      if (match) {
        requiredAgents.push(match[1].trim())
      }
    }
    
    // Check if all required agents are registered (EVALUATE and QUERY are handled locally, not remote agents)
    return requiredAgents.every(agentName =>
      agentName.toUpperCase() === 'EVALUATE' ||
      agentName.toUpperCase() === 'QUERY' ||
      agentName.toUpperCase() === 'WEB_SEARCH' ||
      registeredAgents.some(registered =>
        registered.name?.toLowerCase().includes(agentName.toLowerCase()) ||
        agentName.toLowerCase().includes(registered.name?.toLowerCase() || '')
      )
    )
  }
  
  // Get conversation ID from URL parameters (needed for hooks)
  const searchParams = useSearchParams()
  const router = useRouter()
  const conversationId = searchParams.get('conversationId') || 'frontend-chat-context'
  
  // Track the current session ID - this changes when joining a collaborative session
  // We need this as state so React knows to re-render when it changes
  const [currentSessionId, setCurrentSessionId] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      return getOrCreateSessionId()
    }
    return ''
  })
  
  // Track if we're in a collaborative session - needed for strict conversation filtering
  // In collaborative sessions, we should NOT allow the 'frontend-chat-context' exception
  // because we receive events from all of the session owner's conversations
  const [isInCollaborativeSession, setIsInCollaborativeSession] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      return !!sessionStorage.getItem('a2a_collaborative_session')
    }
    return false
  })
  
  // Update collaborative session state and session ID when they change
  // This is critical for proper sync after joining a collaborative session
  useEffect(() => {
    const checkSessionState = () => {
      const collab = sessionStorage.getItem('a2a_collaborative_session')
      logDebug('[ChatPanel] checkSessionState - collab:', collab, 'current isInCollaborativeSession:', isInCollaborativeSession)
      if (!!collab !== isInCollaborativeSession) {
        logDebug('[ChatPanel] Updating isInCollaborativeSession to:', !!collab)
        setIsInCollaborativeSession(!!collab)
      }
      // Update session ID - this triggers contextId recalculation
      const newSessionId = getOrCreateSessionId()
      setCurrentSessionId(prev => {
        if (prev !== newSessionId) {
          logDebug('[ChatPanel] Session ID changed:', prev, '->', newSessionId)
          return newSessionId
        }
        return prev
      })
    }
    
    // Check on mount
    checkSessionState()
    
    // Also listen for storage events in case it changes in another tab
    window.addEventListener('storage', checkSessionState)
    
    // Check periodically in case sessionStorage was updated programmatically
    // (storage events don't fire for same-tab changes)
    const interval = setInterval(checkSessionState, 500)
    
    return () => {
      window.removeEventListener('storage', checkSessionState)
      clearInterval(interval)
    }
  }, [])
  
  // Track the conversation we just created from the home page
  // This prevents cross-pollination: only accept messages for THIS conversation, not any conversation
  const pendingConversationIdRef = useRef<string | null>(null)
  
  // Clear pending conversation when URL updates to a DIFFERENT real conversation
  // This handles navigating away from a conversation we just created
  // IMPORTANT: Don't clear if the new conversationId matches the pending one - 
  // we still need to accept events for it during the transition
  useEffect(() => {
    if (conversationId !== 'frontend-chat-context') {
      // Only clear if we're navigating to a DIFFERENT conversation
      // If conversationId matches our pending one, keep accepting events
      if (pendingConversationIdRef.current && pendingConversationIdRef.current !== conversationId) {
        logDebug('[ChatPanel] Navigated to different conversation, clearing pending:', pendingConversationIdRef.current, '->', conversationId)
        pendingConversationIdRef.current = null
      }
      // If they match, don't clear - we're just transitioning to the page we created
    }
  }, [conversationId])
  
  // Create tenant-aware contextId for A2A protocol
  // Format: sessionId::conversationId - enables multi-tenant isolation
  // IMPORTANT: Include currentSessionId in deps so it recalculates when joining collaborative session
  const contextId = useMemo(() => {
    const newContextId = createContextId(conversationId)
    logDebug('[ChatPanel] contextId recalculated:', newContextId, 'session:', currentSessionId)
    return newContextId
  }, [conversationId, currentSessionId])
  
  // Callback to ensure we have a real conversation (for voice button)
  // Returns the new conversation ID if created, or null if already on a real conversation
  const ensureConversation = useCallback(async (): Promise<string | null> => {
    if (conversationId !== 'frontend-chat-context') {
      // Already on a real conversation
      return null
    }
    
    try {
      const newConversation = await createConversation()
      if (newConversation) {
        const newConvId = newConversation.conversation_id
        // Track this as our pending conversation to accept messages for it
        pendingConversationIdRef.current = newConvId
        notifyConversationCreated(newConversation)
        router.replace(`/?conversationId=${newConvId}`)
        return newConvId
      }
    } catch (error) {
      console.error('[ChatPanel] Failed to create conversation for voice:', error)
    }
    return null
  }, [conversationId, router])
  
  // Helper function to check if we should filter by conversationId
  // Each event should only be shown in its corresponding conversation view
  // Returns true if the event should be FILTERED OUT (not shown)
  const shouldFilterByConversationId = useCallback((eventConvId: string): boolean => {
    // If no conversationId in the event, accept it (backward compatibility)
    if (!eventConvId) return false
    
    // PRIORITY CHECK: If we have a pending conversation (just created from home page),
    // accept events for it regardless of current URL state. This handles the race condition
    // where events arrive before the URL update from router.replace() takes effect.
    if (pendingConversationIdRef.current && eventConvId === pendingConversationIdRef.current) {
      return false // Accept - it's for our pending conversation
    }
    
    // If the event is for our current conversation, accept it
    if (eventConvId === conversationId) return false
    
    // In collaborative sessions on the home page, auto-navigate to the conversation
    // This keeps session members in sync - when User A sends a message, User B goes there too
    if (isInCollaborativeSession && conversationId === 'frontend-chat-context' && eventConvId) {
      logDebug("[ChatPanel] Collaborative session: auto-navigating from home to conversation:", eventConvId)
      router.push(`/?conversationId=${eventConvId}`)
      // Return true to filter THIS event - after navigation, future events will be accepted
      // The page will reload with the correct conversationId and load messages from API
      return true
    }
    
    // On the home page with no pending conversation, filter all events
    // This is a clean home page state - shouldn't receive messages
    if (conversationId === 'frontend-chat-context') {
      logDebug("[ChatPanel] Home page: filtering event - no pending conversation, received:", eventConvId)
      return true
    }
    
    // Otherwise, filter out events for other conversations
    return true
  }, [conversationId, isInCollaborativeSession, router])
  
  // Use ref for shouldFilterByConversationId to avoid re-running event subscription effect
  // when isInCollaborativeSession changes. This prevents workflow bar state from resetting.
  const shouldFilterByConversationIdRef = useRef(shouldFilterByConversationId)
  useEffect(() => {
    shouldFilterByConversationIdRef.current = shouldFilterByConversationId
  }, [shouldFilterByConversationId])
  
  // Voice recording hook
  const voiceRecording = useVoiceRecording()
  
  // Ref for deduplicating message events (avoids stale closure issues in event handlers)
  const processedMessageIdsRef = useRef<Set<string>>(new Set())
  
  // Use refs to always get the latest values (avoid stale closure)
  const workflowRef = useRef(workflow)
  const workflowGoalRef = useRef(workflowGoal)
  const enableInterAgentMemoryRef = useRef(enableInterAgentMemory)
  
  useEffect(() => {
    workflowRef.current = workflow
  }, [workflow])
  
  useEffect(() => {
    workflowGoalRef.current = workflowGoal
  }, [workflowGoal])
  
  useEffect(() => {
    enableInterAgentMemoryRef.current = enableInterAgentMemory
  }, [enableInterAgentMemory])
  
  const [messages, setMessages] = useState<Message[]>([])
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null)  // Track which message is currently streaming
  const [isLoadingMessages, setIsLoadingMessages] = useState(false) // Start false, only true when loading existing conversations
  const [input, setInput] = useState("")
  const [isInputFocused, setIsInputFocused] = useState(false) // Track input focus for Teams-like highlight
  const [isInputHovered, setIsInputHovered] = useState(false) // Track input hover for gradient bar
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const [isInferencing, setIsInferencing] = useState(false)
  const [inferenceSteps, setInferenceSteps] = useState<{ agent: string; status: string; imageUrl?: string; imageName?: string; mediaType?: string; eventType?: string; metadata?: Record<string, any>; taskId?: string }[]>([])
  // Workflow plan from backend - the source of truth for workflow state
  const [workflowPlan, setWorkflowPlan] = useState<{
    goal: string
    goal_status: string
    tasks: Array<{
      task_id: string
      task_description: string
      recommended_agent: string | null
      output: { result?: string } | null
      state: string
      error_message: string | null
    }>
    reasoning?: string
  } | null>(null)
  const [localActiveNode, setLocalActiveNode] = useState<string | null>(null)
  // Use external activeNode if provided, otherwise use local state
  const activeNode = externalActiveNode !== undefined ? externalActiveNode : localActiveNode
  const setActiveNode = externalSetActiveNode || setLocalActiveNode
  const [processedMessageIds, setProcessedMessageIds] = useState<Set<string>>(new Set())
  const [uploadedFiles, setUploadedFiles] = useState<any[]>([])
  const [refineTarget, setRefineTarget] = useState<any | null>(null)
  const [remixTarget, setRemixTarget] = useState<{ videoId: string; uri: string; fileName?: string } | null>(null)
  const [maskAttachment, setMaskAttachment] = useState<any | null>(null)
  const [maskUploadInFlight, setMaskUploadInFlight] = useState(false)
  const [maskEditorOpen, setMaskEditorOpen] = useState(false)
  const [maskEditorSource, setMaskEditorSource] = useState<{ uri: string; meta?: any } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [isDragOver, setIsDragOver] = useState(false)
  
  // Feedback state for messages (thumbs up/down)
  const [messageFeedback, setMessageFeedback] = useState<Record<string, 'up' | 'down' | null>>({})
  
  // Current user state for multi-user chat
  const [currentUser, setCurrentUser] = useState<any>(null)
  
  // Mention autocomplete state
  const [showMentionDropdown, setShowMentionDropdown] = useState(false)
  const [mentionSearch, setMentionSearch] = useState("")
  const [mentionCursorPosition, setMentionCursorPosition] = useState(0)
  const [selectedMentionIndex, setSelectedMentionIndex] = useState(0)
  const [mentionedUserNames, setMentionedUserNames] = useState<Set<string>>(new Set())

  // Typing indicator state
  const [typingUsers, setTypingUsers] = useState<Map<string, string>>(new Map()) // user_id -> username
  const typingTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const lastTypingSentRef = useRef<number>(0)
  const workflowCancelledRef = useRef(false) // Synchronous flag for cancel detection

  // Build mention suggestions (agents + users)
  const mentionSuggestions = [
    ...registeredAgents.map(agent => ({
      type: 'agent' as const,
      id: agent.name,
      name: agent.name,
      display: agent.name,
      description: agent.description || '',
      avatar: agent.avatar
    })),
    ...connectedUsers.map(user => ({
      type: 'user' as const,
      id: user.user_id,
      name: user.name,
      display: user.name,
      description: user.role || '',
      color: user.color
    }))
  ]

  // Filter mentions based on search
  const filteredMentions = mentionSearch
    ? mentionSuggestions.filter(item =>
        item.name.toLowerCase().includes(mentionSearch.toLowerCase())
      )
    : mentionSuggestions

  // Handle backend session changes - clear messages when backend restarts
  useEffect(() => {
    const BACKEND_SESSION_KEY = 'a2a_backend_session_id'
    
    const handleSessionStarted = (data: any) => {
      const newSessionId = data?.data?.sessionId || data?.sessionId
      if (!newSessionId) {
        logDebug('[ChatPanel] session_started event but no sessionId found')
        return
      }
      
      const storedSessionId = localStorage.getItem(BACKEND_SESSION_KEY)
      
      if (storedSessionId && storedSessionId !== newSessionId) {
        // Backend restarted - clear all local state
        logInfo('[ChatPanel] Backend restarted (session changed), clearing messages and state')
        logInfo('[ChatPanel] Old session:', storedSessionId?.slice(0, 8), '-> New session:', newSessionId.slice(0, 8))
        setMessages([])
        setUploadedFiles([])
        setInferenceSteps([])
        setIsInferencing(false)
        // Navigate away from any stale conversation
        if (conversationId && conversationId !== 'frontend-chat-context') {
          logDebug('[ChatPanel] Navigating away from stale conversation')
          router.push('/')
        }
      }
      
      // Store the new session ID
      localStorage.setItem(BACKEND_SESSION_KEY, newSessionId)
      logDebug('[ChatPanel] Backend session ID stored:', newSessionId.slice(0, 8))
    }

    // Handle session members updated - fires when we join a collaborative session
    // This triggers an immediate session ID check (faster than polling)
    const handleSessionMembersUpdated = (data: any) => {
      logDebug('[ChatPanel] Session members updated:', data)
      const newSessionId = getOrCreateSessionId()
      setCurrentSessionId(prev => {
        if (prev !== newSessionId) {
          logDebug('[ChatPanel] Session ID changed after members update:', prev, '->', newSessionId)
          return newSessionId
        }
        return prev
      })
      // Also update collaborative session state
      const collab = sessionStorage.getItem('a2a_collaborative_session')
      setIsInCollaborativeSession(!!collab)
    }

    subscribe('session_started', handleSessionStarted)
    subscribe('session_members_updated', handleSessionMembersUpdated)
    
    return () => {
      unsubscribe('session_started', handleSessionStarted)
      unsubscribe('session_members_updated', handleSessionMembersUpdated)
    }
  }, [subscribe, unsubscribe, conversationId, router])

  // Clear uploaded files when connection is lost (backend restart)
  useEffect(() => {
    if (!isConnected && uploadedFiles.length > 0) {
      logDebug('[ChatPanel] WebSocket disconnected, clearing uploaded files')
      setUploadedFiles([])
    }
  }, [isConnected, uploadedFiles.length])

  useEffect(() => {
    if (!refineTarget) {
      setMaskAttachment(null)
      setMaskEditorOpen(false)
      setMaskEditorSource(null)
    } else {
      setMaskAttachment(null)
    }
  }, [refineTarget])

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    if (messagesContainerRef.current) {
      messagesContainerRef.current.scrollTop = messagesContainerRef.current.scrollHeight
    }
  }, [messages])

  // Auto-scroll to bottom when inference steps change (so user sees thinking progress)
  useEffect(() => {
    if (isInferencing && inferenceSteps.length > 0 && messagesContainerRef.current) {
      messagesContainerRef.current.scrollTop = messagesContainerRef.current.scrollHeight
    }
  }, [inferenceSteps, isInferencing])

  // Also clear uploaded files on component mount (page refresh)
  useEffect(() => {
    logDebug('[ChatPanel] Component mounted, clearing any stale uploaded files')
    setUploadedFiles([])
  }, []) // Empty dependency array = only run on mount

  // Track if we're in the process of creating a conversation to avoid race conditions
  const [isCreatingConversation, setIsCreatingConversation] = useState(false)

  // Reset messages when conversation ID changes (new chat)
  useEffect(() => {
    const loadConversationMessages = async () => {
    // Only set loading state for existing conversations, not new chats
    const isExistingConversation = conversationId && conversationId !== 'frontend-chat-context'
    if (isExistingConversation) {
      setIsLoadingMessages(true) // Start loading only for existing conversations
    }
    logDebug('[ChatPanel] Conversation ID changed to:', conversationId)
    logDebug('[ChatPanel] URL search params:', searchParams.toString())
      
      // Load messages for existing conversations (no auth required for message loading)
      if (isExistingConversation) {
        try {
          logDebug("[ChatPanel] Loading conversation:", conversationId)
          const { conversation, messageUserMap } = await getConversation(conversationId)
          
          // Fetch all users for color lookup (connectedUsers may not have all users)
          let allUsers: any[] = []
          try {
            const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
            const usersResponse = await fetch(`${baseUrl}/api/auth/users`)
            const usersData = await usersResponse.json()
            allUsers = usersData.users || []
            logDebug('[ChatPanel] Fetched', allUsers.length, 'users for color lookup')
          } catch (e) {
            console.error('[ChatPanel] Failed to fetch users for color lookup:', e)
          }
          
          if (conversation && conversation.messages) {
            const apiMessages = conversation.messages
            logDebug("[ChatPanel] Retrieved", apiMessages.length, "messages for conversation", conversationId)
            logDebug("[ChatPanel] messageUserMap has", Object.keys(messageUserMap).length, "entries")
            
            if (apiMessages.length > 0) {
              logDebug("[ChatPanel] First message sample:", apiMessages[0])
            }
            
            // Convert API messages to our format
            // A2A serializes Part objects flat: { kind: 'text', text: '...' } not { root: { kind: 'text', text: '...' } }
            logDebug('[ChatPanel] Converting', apiMessages.length, 'API messages')
            const convertedMessages: Message[] = apiMessages.map((msg, index) => {
              // Extract text content from parts - handle A2A format
              let content = ''
              let images: { uri: string; fileName?: string; mimeType?: string; videoId?: string }[] = []
              
              // DEBUG: Log the raw message parts to trace image persistence issues
              logDebug(`[ChatPanel] Message ${index} parts:`, JSON.stringify(msg.parts, null, 2).substring(0, 500))
              
              // FIRST PASS: Collect video metadata from DataParts (video_id mappings)
              const videoMetadata: { [uri: string]: string } = {}
              if (msg.parts && Array.isArray(msg.parts)) {
                for (const part of msg.parts) {
                  // Extract video_metadata from DataParts
                  if (part.kind === 'data' && part.data?.type === 'video_metadata' && part.data?.video_id) {
                    const videoId = part.data.video_id
                    logDebug(`[ChatPanel] Found video_metadata DataPart with video_id: ${videoId}`)
                    // Store for association with video file (we'll match by filename or use as fallback)
                    videoMetadata['__latest__'] = videoId
                  }
                }
              }
              
              // SECOND PASS: Extract content and files, applying video metadata
              if (msg.parts && Array.isArray(msg.parts)) {
                for (const part of msg.parts) {
                  // A2A flattened format (most common): { kind: 'text', text: '...' }
                  if (part.kind === 'text' && part.text) {
                    content += (content ? '\n' : '') + part.text
                  }
                  // Nested format (if present): { root: { kind: 'text', text: '...' } }
                  else if (part.root?.text) {
                    content += (content ? '\n' : '') + part.root.text
                  }
                  else if (part.root?.kind === 'text' && part.root?.text) {
                    content += (content ? '\n' : '') + part.root.text
                  }
                  // Direct text property
                  else if (part.text) {
                    content += (content ? '\n' : '') + part.text
                  }
                  // Content property
                  else if (part.content) {
                    content += (content ? '\n' : '') + part.content
                  }
                  // PRIMARY: Handle FilePart with media artifacts (standard A2A format)
                  // This is the canonical format - all media files (images, videos) should come as FilePart with URI
                  else if (part.kind === 'file' && part.file?.uri) {
                    const uri = part.file.uri
                    const mimeType = part.file.mimeType || ''
                    const fileRole = (part as any).metadata?.role || part.file?.role || ''
                    const fileName = part.file.name || ''
                    // Skip mask images — they're editing artifacts, not displayable content
                    const isMask = fileRole === 'mask' || /[-_]mask\b/i.test(fileName)
                    // Only include media files with valid blob storage URIs (not local cache refs)
                    if (!isMask && (uri.startsWith('http://') || uri.startsWith('https://'))) {
                      // Accept images and videos (strip query params for extension check)
                      const uriPath = uri.split('?')[0]
                      const isImage = mimeType.startsWith('image/') || /\.(png|jpe?g|gif|webp)$/i.test(uriPath)
                      const isVideo = mimeType.startsWith('video/') || /\.(mp4|mov|avi|mkv|webm)$/i.test(uriPath)
                      if (isImage || isVideo) {
                        const mediaType = isVideo ? 'video' : 'image'
                        logDebug(`[ChatPanel] Found FilePart ${mediaType}: ${uri.substring(0, 80)}...`)
                        // Extract videoId - check part directly first, then use metadata from DataPart
                        let videoId = (part as any).videoId || videoMetadata['__latest__'] || undefined
                        if (videoId) {
                          logDebug(`[ChatPanel] Assigned videoId to video: ${videoId}`)
                        }
                        images.push({
                          uri: uri,
                          fileName: fileName || `Generated ${mediaType}`,
                          mimeType: mimeType,
                          videoId: videoId
                        })
                      }
                    }
                  }
                  // Nested FilePart format
                  else if (part.root?.kind === 'file' && part.root?.file?.uri) {
                    const uri = part.root.file.uri
                    const mimeType = part.root.file.mimeType || ''
                    const fileRole = part.root?.metadata?.role || part.root?.file?.role || ''
                    const fileName = part.root.file.name || ''
                    const isMask = fileRole === 'mask' || /[-_]mask\b/i.test(fileName)
                    if (!isMask && (uri.startsWith('http://') || uri.startsWith('https://'))) {
                      // Accept images and videos (strip query params for extension check)
                      const uriPath = uri.split('?')[0]
                      const isImage = mimeType.startsWith('image/') || /\.(png|jpe?g|gif|webp)$/i.test(uriPath)
                      const isVideo = mimeType.startsWith('video/') || /\.(mp4|mov|avi|mkv|webm)$/i.test(uriPath)
                      if (isImage || isVideo) {
                        const mediaType = isVideo ? 'video' : 'image'
                        logDebug(`[ChatPanel] Found nested FilePart ${mediaType}: ${uri.substring(0, 80)}...`)
                        // Extract videoId - check part directly first, then use metadata from DataPart
                        let videoId = (part.root as any).videoId || videoMetadata['__latest__'] || undefined
                        if (videoId) {
                          logDebug(`[ChatPanel] Assigned videoId to nested video: ${videoId}`)
                        }
                        images.push({
                          uri: uri,
                          fileName: fileName || `Generated ${mediaType}`,
                          mimeType: mimeType,
                          videoId: videoId
                        })
                      }
                    }
                  }
                  // LEGACY: Handle DataPart with artifact-uri (for backward compatibility)
                  // This should be phased out - new code should use FilePart
                  else if (part.kind === 'data' && part.data) {
                    const artifactUri = part.data['artifact-uri']
                    const fileName = part.data['file-name']
                    if (artifactUri && (artifactUri.startsWith('http://') || artifactUri.startsWith('https://'))) {
                      logDebug(`[ChatPanel] Found DataPart artifact-uri (legacy): ${artifactUri.substring(0, 80)}...`)
                      images.push({ uri: artifactUri, fileName })
                    }
                  }
                  // Nested DataPart format (legacy)
                  else if (part.root?.kind === 'data' && part.root?.data) {
                    const artifactUri = part.root.data['artifact-uri']
                    const fileName = part.root.data['file-name']
                    if (artifactUri && (artifactUri.startsWith('http://') || artifactUri.startsWith('https://'))) {
                      logDebug(`[ChatPanel] Found nested DataPart artifact-uri (legacy): ${artifactUri.substring(0, 80)}...`)
                      images.push({ uri: artifactUri, fileName })
                    }
                  }
                }
              }
              
              // Log final file count for debugging
              if (images.length > 0) {
                logDebug(`[ChatPanel] Message ${index} has ${images.length} files (images/videos)`)
              }
              
              // Look up userId from messageUserMap and get color from allUsers (fetched above)
              const messageId = msg.messageId || `api_msg_${index}`
              const senderUserId = messageUserMap[messageId]
              const senderUser = senderUserId ? allUsers.find(u => u.user_id === senderUserId) : null
              const senderColor = senderUser?.color
              
              // Debug: log the lookup
              if (msg.role === 'user') {
                logDebug(`[ChatPanel] Message ${messageId}: senderUserId=${senderUserId}, allUsers=${allUsers.length}, senderUser=${senderUser?.name}, color=${senderColor}`)
              }
              
              return {
                id: messageId,
                role: (msg.role === 'user' || msg.role === 'assistant' || msg.role === 'agent') ? 
                      (msg.role === 'agent' ? 'assistant' : msg.role) : 'assistant',
                content: content,
                // Include user info for user messages (for avatar colors)
                ...(msg.role === 'user' && senderUserId && {
                  userId: senderUserId,
                  userColor: senderColor,
                }),
                // NOTE: Don't set 'images' here - use 'attachments' only to avoid duplicate rendering
                // The JSX has two render paths: one for message.images and one for message.attachments
                // We only want to use attachments
                attachments: images.length > 0 ? images.map(img => {
                  // Use the actual mimeType from the file, or infer from extension
                  let mediaType = img.mimeType || 'image/png'
                  if (!img.mimeType) {
                    // Fallback: infer from file extension
                    const ext = img.fileName?.split('.').pop()?.toLowerCase()
                    if (ext === 'mp4' || ext === 'mov' || ext === 'avi' || ext === 'mkv' || ext === 'webm') {
                      mediaType = `video/${ext === 'mov' ? 'quicktime' : ext}`
                    } else if (ext === 'jpg' || ext === 'jpeg') {
                      mediaType = 'image/jpeg'
                    } else if (ext === 'png' || ext === 'gif' || ext === 'webp') {
                      mediaType = `image/${ext}`
                    }
                  }
                  return {
                    uri: img.uri,
                    fileName: img.fileName || "Generated file",
                    mediaType: mediaType,
                    videoId: img.videoId, // Preserve videoId for remix functionality
                  }
                }) : undefined,
                agent: (msg.role === 'assistant' || msg.role === 'agent')
                  ? (msg.metadata?.agentName || 'foundry-host-agent')
                  : undefined,
                // Preserve metadata including workflow_plan for rendering workflow history
                metadata: msg.metadata || undefined
              }
            })
            
            // Debug: Log all converted messages to understand duplication
            logDebug('[ChatPanel] Converted messages from API:', convertedMessages.map(m => ({
              id: m.id,
              role: m.role,
              hasContent: !!m.content,
              contentPreview: m.content?.substring(0, 50),
              attachmentCount: m.attachments?.length || 0,
              attachments: m.attachments?.map(a => a.fileName)
            })))
            
            // Merge consecutive assistant messages (fixes duplicate attachments on page reload)
            // When attachments are sent separately from text, they create separate messages
            // Merge them so attachments appear with their associated text
            const mergedMessages: Message[] = []
            for (let i = 0; i < convertedMessages.length; i++) {
              const msg = convertedMessages[i]
              const prevMsg = mergedMessages[mergedMessages.length - 1]
              
              logDebug(`[ChatPanel] Checking message ${i}:`, {
                role: msg.role,
                hasContent: !!msg.content,
                hasAttachments: !!msg.attachments?.length,
                attachmentCount: msg.attachments?.length,
                prevRole: prevMsg?.role,
                prevHasContent: !!prevMsg?.content
              })
              
              // If current message is assistant with only attachments and PREVIOUS was also assistant with text
              // Merge the attachments INTO the previous message
              if (msg.role === 'assistant' && msg.attachments?.length && !msg.content && 
                  prevMsg && prevMsg.role === 'assistant' && prevMsg.content) {
                // Merge attachments into previous message
                logDebug('[ChatPanel] ✓ MERGING attachment message into PREVIOUS text message')
                prevMsg.attachments = [...(prevMsg.attachments || []), ...(msg.attachments || [])]
                // Skip current message (it's merged into previous)
                continue
              }
              mergedMessages.push(msg)
            }
            
            logDebug('[ChatPanel] After merge:', mergedMessages.length, 'messages (was', convertedMessages.length, ')')
            
            // Extract workflow plans from message metadata (for historical workflow display)
            // Build a map of message index to its workflow plan
            const plansFromDatabase: Array<{ plan: any, messageIndex: number, messageId: string }> = []
            for (let i = 0; i < mergedMessages.length; i++) {
              const msg = mergedMessages[i]
              if (msg.metadata?.workflow_plan) {
                plansFromDatabase.push({ 
                  plan: msg.metadata.workflow_plan, 
                  messageIndex: i,
                  messageId: msg.id 
                })
                logDebug('[ChatPanel] Found workflow_plan in message metadata:', msg.metadata.workflow_plan.goal)
              }
            }
            
            // Set the most recent workflow plan for the workflowPlan state
            if (plansFromDatabase.length > 0) {
              const mostRecentPlan = plansFromDatabase[plansFromDatabase.length - 1].plan
              setWorkflowPlan(mostRecentPlan)
            }
            
            // Inject workflow summaries from DATABASE PLANS (preferred) or localStorage (fallback)
            const messagesWithWorkflows: Message[] = []
            
            // Use database plans if available
            if (plansFromDatabase.length > 0) {
              logDebug('[ChatPanel] Using', plansFromDatabase.length, 'workflow plan(s) from database')
              
              // Track which plans have been inserted
              let planIndex = 0
              
              for (let i = 0; i < mergedMessages.length; i++) {
                const msg = mergedMessages[i]
                
                // Check if this message has a plan and insert inference_summary before it
                if (planIndex < plansFromDatabase.length && 
                    plansFromDatabase[planIndex].messageIndex === i) {
                  const plan = plansFromDatabase[planIndex].plan
                  
                  // Convert plan to steps format for InferenceSteps compatibility
                  const steps = plan.tasks?.map((task: any) => ({
                    agent: task.recommended_agent || 'Unknown Agent',
                    status: task.state === 'completed' ? 
                      (task.output?.result || task.task_description) : 
                      task.task_description,
                    eventType: task.state === 'completed' ? 'agent_complete' : 
                               task.state === 'running' ? 'agent_start' : 'pending'
                  })) || []
                  
                  // Insert inference_summary message BEFORE the assistant response
                  messagesWithWorkflows.push({
                    id: `workflow_db_${plansFromDatabase[planIndex].messageId}`,
                    role: 'system',
                    type: 'inference_summary',
                    steps: steps,
                    metadata: { workflow_plan: plan }
                  })
                  
                  planIndex++
                }
                
                messagesWithWorkflows.push(msg)
              }
              
              setMessages(messagesWithWorkflows.filter(m => m.content || m.images?.length || m.attachments?.length || m.type === 'inference_summary'))
            } else {
              // Fallback to localStorage workflows (backward compatibility)
              try {
                // Strip session prefix from conversationId to match how workflows are saved
                let workflowConversationId = conversationId
                if (workflowConversationId && workflowConversationId.includes('::')) {
                  workflowConversationId = workflowConversationId.split('::')[1]
                }
                const storageKey = `workflow_${workflowConversationId}`
                const storedData = localStorage.getItem(storageKey)
                if (storedData) {
                  const workflows = JSON.parse(storedData)
                  // Insert workflows at appropriate positions (before assistant messages)
                  let workflowIndex = 0
                  
                  for (let i = 0; i < mergedMessages.length; i++) {
                    const msg = mergedMessages[i]
                    
                    // Insert workflow before assistant responses WITH CONTENT
                    // Don't insert workflow before attachment-only messages
                    if (msg.role === 'assistant' && msg.content && workflowIndex < workflows.length) {
                      const workflow = workflows[workflowIndex]
                      messagesWithWorkflows.push({
                        id: workflow.id,
                        role: 'system',
                        type: 'inference_summary',
                        steps: workflow.steps,
                        ...(workflow.metadata ? { metadata: workflow.metadata } : {})
                      })
                      workflowIndex++
                    }
                    messagesWithWorkflows.push(msg)
                  }
                  
                  setMessages(messagesWithWorkflows.filter(m => m.content || m.images?.length || m.attachments?.length || m.type === 'inference_summary'))
                } else {
                  setMessages(mergedMessages.filter(m => m.content || m.images?.length || m.attachments?.length))
                }
              } catch (err) {
                console.error('[ChatPanel] Failed to load workflows from localStorage:', err)
                setMessages(mergedMessages.filter(m => m.content || m.images?.length || m.attachments?.length))
              }
            }
            
            logDebug("[ChatPanel] Converted messages:", convertedMessages.length)
            
            if (convertedMessages.length === 0) {
              // If no messages found, show empty chat (ChatGPT-like)
              logDebug("[ChatPanel] No messages found, showing empty chat")
              setMessages([])
            }
          } else {
            logDebug("[ChatPanel] No conversation found or no messages")
            // Conversation doesn't exist (maybe backend restarted) - redirect to fresh state
            if (conversationId && conversationId !== 'frontend-chat-context') {
              // Clear the stale conversationId from URL (conversationId will recalculate on next render)
              window.history.replaceState({}, '', '/')
            }
            setMessages([])
          }
        } catch (error) {
          console.error("[ChatPanel] Failed to load conversation messages:", error)
          setMessages([])
        }
      } else {
        // New conversation or default - show empty chat (ChatGPT-like behavior)
        logDebug("[ChatPanel] Using default conversation - showing empty chat")
        setMessages([])
      }
      
      // Only reset inference state if we're not actively inferencing
      // This prevents clearing live workflow updates when conversation reloads
      if (!isInferencing) {
        setIsInferencing(false)
        setInferenceSteps([])
        setProcessedMessageIds(new Set())
        processedMessageIdsRef.current = new Set() // Also clear ref for deduplication
      }
      
      setIsLoadingMessages(false) // Done loading
    }
    
    loadConversationMessages()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]) // Only depend on conversationId - isInferencing checked inside

  // Real Event Hub listener for backend events - moved inside component
  useEffect(() => {
    // Handle real status updates from A2A backend
    // CONSOLIDATED: task_updated is now ONLY for sidebar status (agent-network.tsx)
    // Workflow display uses remote_agent_activity instead
    // This prevents duplicate messages in the workflow
    const handleTaskUpdate = (data: any) => {
      logDebug("[ChatPanel] Task update received (for agent registration only):", data)
      
      // Filter by conversationId - only process updates for the current conversation
      let taskConvId = data.conversationId || data.contextId || ""
      if (taskConvId.includes("::")) {
        taskConvId = taskConvId.split("::")[1]
      }
      if (shouldFilterByConversationIdRef.current(taskConvId)) {
        logDebug("[ChatPanel] Ignoring task update for different conversation:", taskConvId, "current:", conversationId)
        return
      }
      
      // A2A TaskEventData has: taskId, conversationId, contextId, state, artifactsCount, agentName, content
      if (data.taskId && data.state) {
        // Use the actual agent name if available, otherwise fall back to generic names
        let agentName = data.agentName || "Host Agent"
        
        // If this is a new agent we haven't seen before, register it
        if (data.agentName && data.agentName !== "Host Agent" && data.agentName !== "System") {
          emit("agent_registered", {
            name: data.agentName,
            status: "online",
            avatar: "/placeholder.svg?height=32&width=32"
          })
        }
        
        // DO NOT emit status_update here - that causes duplicates
        // The sidebar uses task_updated directly, workflow uses remote_agent_activity
      }
    }

    // Handle system events for more detailed trace
    // These are for system-level events, NOT for workflow display
    const handleSystemEvent = (data: any) => {
      logDebug("[ChatPanel] System event received:", data)
      
      // Filter by conversationId - only process events for the current conversation
      let eventConvId = data.conversationId || ""
      if (eventConvId.includes("::")) {
        eventConvId = eventConvId.split("::")[1]
      }
      if (shouldFilterByConversationIdRef.current(eventConvId)) {
        logDebug("[ChatPanel] Ignoring system event for different conversation:", eventConvId, "current:", conversationId)
        return
      }
      
      // A2A SystemEventData has: eventId, conversationId, actor, role, content
      if (data.eventId && data.content) {
        // If this is a new agent we haven't seen before, register it
        if (data.actor && data.actor !== "Host Agent" && data.actor !== "System" && data.actor !== "User") {
          emit("agent_registered", {
            name: data.actor,
            status: "online",
            avatar: "/placeholder.svg?height=32&width=32"
          })
        }
        
        // DO NOT emit status_update - workflow uses remote_agent_activity only
        // This prevents duplicate messages
      }
    }

    // Handle task creation events
    const handleTaskCreated = (data: any) => {
      logDebug("[ChatPanel] Task created:", data)
      
      // Filter by conversationId - only process events for the current conversation
      let taskConvId = data.conversationId || data.contextId || ""
      if (taskConvId.includes("::")) {
        taskConvId = taskConvId.split("::")[1]
      }
      if (shouldFilterByConversationIdRef.current(taskConvId)) {
        logDebug("[ChatPanel] Ignoring task created for different conversation:", taskConvId, "current:", conversationId)
        return
      }
      
      if (data.taskId) {
        emit("status_update", {
          inferenceId: data.taskId,
          agent: data.agentName || "System",
          status: "The host orchestrator is starting a new task..."
        })
      }
    }

    // Handle agent registration events
    const handleAgentRegistered = (data: any) => {
      logDebug("[ChatPanel] Agent registered:", data)
      if (data.agentName) {
        // Forward the agent registration to the chat layout for the agent network
        emit("agent_registered", {
          name: data.agentName,
          status: "online",
          avatar: "/placeholder.svg?height=32&width=32"
        })
        
        // Also emit a status update for the UI
        emit("status_update", {
          inferenceId: "agent_registration",
          agent: "System",
          status: `registered agent: ${data.agentName}`
        })
      }
    }

    // Handle message sent events (when user sends message from workflow designer)
    const handleMessageSent = (data: any) => {
      logDebug("[ChatPanel] Message sent:", data)
      
      // If this is a user message (from workflow designer reply), add it to messages
      if (data.role === "user" && data.content) {
        logDebug("[ChatPanel] Adding user message from workflow:", data.content?.substring(0, 50))
        const newMessage: Message = {
          id: data.messageId || `user_${Date.now()}`,
          role: "user",
          content: data.content
        }
        setMessages(prev => {
          // Avoid duplicates
          if (prev.some(m => m.content === data.content && m.role === "user")) {
            logDebug("[ChatPanel] Skipping duplicate user message")
            return prev
          }
          return [...prev, newMessage]
        })
      }
      
      if (data.messageId) {
        emit("status_update", {
          inferenceId: data.conversationId || data.messageId,
          agent: data.agentName || "System",
          status: "analyzing request"
        })
      }
    }

    // Handle message received events (when AI gets response from thread)
    const handleMessageReceived = (data: any) => {
      logDebug("[ChatPanel] Message received from thread:", data)
      if (data.messageId) {
        emit("status_update", {
          inferenceId: data.conversationId || data.messageId,
          agent: data.agentName || "System", 
          status: "generating response"
        })
      }
    }

    // Handle real messages from A2A backend
    const handleMessage = (data: any) => {
      logDebug("[ChatPanel] Message received:", data)
      logDebug("[ChatPanel] Current conversationId:", conversationId)
      
      // Guard against messages arriving during conversation switch to prevent race conditions
      if (isLoadingMessages) {
        logDebug("[ChatPanel] Ignoring message during conversation switch (loading in progress)")
        return
      }
      
      // Filter by conversationId - only process messages for the current conversation
      // The backend sends conversationId in format "sessionId::convId" - extract just the convId part
      let messageConvId = data.conversationId || data.contextId || ""
      let messageTenantId = ""
      if (messageConvId.includes("::")) {
        const parts = messageConvId.split("::")
        messageTenantId = parts[0]
        messageConvId = parts[1]
      }
      
      // In collaborative sessions, auto-navigate to the conversation if different
      if (shouldFilterByConversationIdRef.current(messageConvId)) {
        logDebug("[ChatPanel] Ignoring message for different conversation:", messageConvId, "current:", conversationId)
        return
      }
      
      // Filter by session/tenant - only process messages for the current session
      // In collaborative sessions, getOrCreateSessionId() returns the shared session ID
      // So both User A and User B will accept events from the shared session
      const mySessionId = getOrCreateSessionId()
      if (messageTenantId && mySessionId && messageTenantId !== mySessionId) {
        logDebug("[ChatPanel] Ignoring message from different session:", messageTenantId, "my session:", mySessionId)
        return
      }
      
      // Deduplicate message events using ref (avoids stale closure issues)
      // Backend may send same message twice (once to tenant, once to collaborator)
      if (data.messageId) {
        if (processedMessageIdsRef.current.has(data.messageId)) {
          logDebug("[ChatPanel] Skipping duplicate message:", data.messageId)
          return
        }
        // Mark as processed immediately (before any async operations)
        processedMessageIdsRef.current.add(data.messageId)
      }
      
      // A2A MessageEventData has: messageId, conversationId, role, content[], direction
      if (data.messageId && data.content && data.content.length > 0) {
        // Only process assistant messages to avoid duplicating user messages
        if (data.role === "assistant" || data.role === "system") {
          let textContent = data.content.find((c: any) => c.type === "text")?.content || ""
          // Get image parts
          const imageContents = data.content.filter((c: any) => c.type === "image")

          // Strip markdown image references from text when the same images exist as attachments
          // This prevents duplicate rendering: once via ReactMarkdown, once via attachment with Refine button
          if (imageContents.length > 0) {
            const imageUris = new Set(imageContents.map((c: any) => c.uri))
            // Remove ![alt](url) where url matches an attachment URI
            textContent = textContent.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_match: string, _alt: string, url: string) => {
              return imageUris.has(url) ? '' : _match
            })
            // Clean up leftover blank lines
            textContent = textContent.replace(/\n{3,}/g, '\n\n').trim()
          }
          // Get video parts - either type="video" OR type="file" with video/* mimeType
          const videoContents = data.content.filter((c: any) => 
            c.type === "video" || (c.type === "file" && c.mimeType?.startsWith("video/"))
          ).map((c: any) => ({
            uri: c.uri,
            fileName: c.name || c.fileName || "Generated video",
            mediaType: c.mimeType || "video/mp4",
            // Extract video metadata for remix functionality
            videoId: c.videoId,
            generationId: c.generationId,
            originalVideoId: c.originalVideoId,
          }))
          logDebug("[ChatPanel] Image parts count:", imageContents.length)
          logDebug("[ChatPanel] Video parts count:", videoContents.length)
          const derivedImageAttachments = [] as any[]
          let agentName = data.agentName || "System"
          
          // If this is a new agent we haven't seen before, register it
          if (data.agentName && data.agentName !== "Host Agent" && data.agentName !== "System" && data.agentName !== "User") {
            emit("agent_registered", {
              name: data.agentName,
              status: "online",
              avatar: "/placeholder.svg?height=32&width=32"
            })
          }
          
          const existingUris = new Set(imageContents.map((img: any) => img.uri))
          const filteredDerived = derivedImageAttachments.filter(att => !existingUris.has(att.uri))
          // Combine images and videos into all attachments
          const allImageAttachments = [...imageContents, ...filteredDerived, ...videoContents]
          
          // NOTE: We no longer add attachmentMessage immediately here.
          // Instead, we pass attachments through final_response so they appear
          // AFTER the workflow, not before it.
          
          // NOTE: File history is handled by file_uploaded events via ChatLayout.handleFileUploaded
          // Adding files here with artifact.uri as file_id causes duplicates because
          // the file_uploaded event uses the actual file_id from blob storage.
          
          logDebug("[ChatPanel] Processing assistant message:", {
            messageId: data.messageId,
            content: textContent.slice(0, 50) + "...",
            role: data.role,
            agentName: agentName
          })
          
          // Remove streaming message when complete message arrives
          const streamingId = `streaming_${data.contextId || data.conversationId}`
          setMessages(prev => prev.filter(msg => msg.id !== streamingId))
          setStreamingMessageId(null)
          
          // Backend-originated messages should NOT be re-broadcast as shared_message
          // The backend already sent this to all session members via smart_broadcast
          // Setting isFromMyTenant: false prevents handleFinalResponse from re-broadcasting
          const shouldBroadcast = false
          
          // Emit final_response for internal processing - this is converted from message event
          // Include attachments so they appear AFTER the workflow, not before
          emit("final_response", {
            inferenceId: data.conversationId || data.messageId,
            conversationId: data.conversationId || data.contextId,
            messageId: data.messageId, // Pass through the backend's unique messageId
            isFromMyTenant: shouldBroadcast, // false = don't re-broadcast backend messages
            message: {
              role: data.role === "user" ? "user" : "assistant",
              content: textContent,
              agent: agentName,
            },
            // Pass full attachment data for adding AFTER workflow
            attachments: allImageAttachments.map((img: any) => ({
              uri: img.uri,
              fileName: img.fileName,
              fileSize: img.fileSize,
              storageType: img.storageType,
              mediaType: img.mediaType || "image/png",
              videoId: img.videoId,
              generationId: img.generationId,
              originalVideoId: img.originalVideoId,
            })),
          })
        } else {
          logDebug("[ChatPanel] Skipping user message echo from backend:", data)
        }
      }
    }

    // Handle streaming message chunks (Responses API real-time streaming)
    const handleMessageChunk = (data: any) => {
      logDebug("[ChatPanel] Message chunk received:", data)
      
      // Only accumulate chunks for the current context
      if (data.contextId === contextId) {
        const streamingId = `streaming_${data.contextId}`
        
        setMessages(prev => {
          const existingIndex = prev.findIndex(msg => msg.id === streamingId)
          
          if (existingIndex >= 0) {
            // Update existing streaming message
            const updated = [...prev]
            updated[existingIndex] = {
              ...updated[existingIndex],
              content: (updated[existingIndex].content || '') + (data.chunk || '')
            }
            return updated
          } else {
            // Create new streaming message in the messages array
            const newMessage: Message = {
              id: streamingId,
              role: "assistant",
              content: data.chunk || '',
              agent: "foundry-host-agent"
            }
            return [...prev, newMessage]
          }
        })
        
        setStreamingMessageId(streamingId)
        
        // Auto-scroll to bottom as tokens stream in
        if (messagesContainerRef.current) {
          const container = messagesContainerRef.current
          const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 100
          if (isNearBottom) {
            setTimeout(() => {
              container.scrollTop = container.scrollHeight
            }, 10)
          }
        }
      }
    }

    // Handle shared user messages from other clients
    const handleSharedMessage = (data: any) => {
      logDebug("[ChatPanel] Shared message received:", data)
      
      // Guard against messages arriving during conversation switch to prevent race conditions
      if (isLoadingMessages) {
        logDebug("[ChatPanel] Ignoring shared message during conversation switch (loading in progress)")
        return
      }
      
      // Extract conversationId - backend sends it in format "sessionId::convId", strip the tenant prefix
      let messageConvId = data.conversationId || ""
      if (messageConvId.includes("::")) {
        const parts = messageConvId.split("::")
        messageConvId = parts[1]  // Take just the conv ID part
      }
      
      logDebug("[ChatPanel] Current conversationId:", conversationId, "Message conversationId:", messageConvId, "raw:", data.conversationId)
      
      // Filter by conversationId - only process messages for the current conversation
      // In collaborative sessions, auto-navigate to the conversation if different
      if (shouldFilterByConversationIdRef.current(messageConvId)) {
        logDebug("[ChatPanel] IGNORING message for different conversation:", messageConvId, "current:", conversationId)
        return
      }
      
      logDebug("[ChatPanel] ACCEPTING message for conversation:", messageConvId || "(no conversationId)")
      
      if (data.message) {
        const newMessage: Message = {
          id: data.message.id,
          role: data.message.role,
          content: data.message.content,
          username: data.message.username,
          userColor: data.message.userColor,
          agent: data.message.agent,
          attachments: data.message.attachments
        }
        
        // Add the message to our local state if we don't already have it
        setMessages((prev) => {
          const messageExists = prev.some(msg => msg.id === newMessage.id)
          if (!messageExists) {
            return [...prev, newMessage]
          }
          return prev
        })
      }
    }

    // Handle shared inference state changes from other clients
    const handleSharedInferenceStarted = (data: any) => {
      logDebug("[ChatPanel] Shared inference started:", data)
      
      // Filter by conversationId - only process inference events for the current conversation
      // conversationId is now at top level (from WebSocket client normalization)
      let eventConvId = data.conversationId || data.data?.conversationId || ""
      let eventTenantId = ""
      if (eventConvId.includes("::")) {
        const parts = eventConvId.split("::")
        eventTenantId = parts[0]
        eventConvId = parts[1]
      }
      
      // Filter by session - only process events for the current session
      // In collaborative sessions, getOrCreateSessionId() returns the shared session ID
      const mySessionId = getOrCreateSessionId()
      if (eventTenantId && mySessionId && eventTenantId !== mySessionId) {
        logDebug("[ChatPanel] Ignoring inference started from different session:", eventTenantId, "my session:", mySessionId)
        return
      }
      
      if (eventConvId && eventConvId !== conversationId) {
        logDebug("[ChatPanel] Ignoring inference started for different conversation:", eventConvId, "current:", conversationId)
        return
      }

      // Skip if workflow was cancelled by user
      if (workflowCancelledRef.current) {
        logDebug("[ChatPanel] Ignoring inference started - workflow was cancelled")
        return
      }

      setIsInferencing(true)
      setInferenceSteps([])
      setActiveNode("User Input")
    }

    const handleSharedInferenceEnded = (data: any) => {
      logDebug("[ChatPanel] Shared inference ended:", data)
      
      // Filter by conversationId - only process inference events for the current conversation
      // conversationId is now at top level (from WebSocket client normalization)
      let eventConvId = data.conversationId || data.data?.conversationId || ""
      let eventTenantId = ""
      if (eventConvId.includes("::")) {
        const parts = eventConvId.split("::")
        eventTenantId = parts[0]
        eventConvId = parts[1]
      }
      
      // Filter by session - only process events for the current session
      // In collaborative sessions, getOrCreateSessionId() returns the shared session ID
      const mySessionId = getOrCreateSessionId()
      if (eventTenantId && mySessionId && eventTenantId !== mySessionId) {
        logDebug("[ChatPanel] Ignoring inference ended from different session:", eventTenantId, "my session:", mySessionId)
        return
      }
      
      // In collaborative sessions, auto-navigate to the conversation if different
      if (shouldFilterByConversationIdRef.current(eventConvId)) {
        logDebug("[ChatPanel] Ignoring inference ended for different conversation:", eventConvId, "current:", conversationId)
        return
      }

      // Skip if workflow was cancelled by user - handleStop already saved the summary
      if (workflowCancelledRef.current) {
        logDebug("[ChatPanel] Ignoring shared inference ended - workflow was cancelled")
        return
      }

      // If workflow steps are included, create an inference_summary message
      const workflowSteps = data.workflowSteps || data.data?.workflowSteps
      const summaryId = data.summaryId || data.data?.summaryId || `summary_shared_${Date.now()}`
      
      // Check if we already processed a workflow for this conversation recently
      // This prevents duplicates when we receive both the direct message event AND shared_inference_ended
      // Use a workflow key based on conversation ID to track
      const workflowKey = `workflow_received_${eventConvId || conversationId}`
      
      if (workflowSteps && workflowSteps.length > 0) {
        logDebug("[ChatPanel] Received workflow steps from shared_inference_ended:", workflowSteps.length, "steps")
        
        // Check if we already have a recent workflow for this conversation (within last 5 seconds)
        // This handles the case where message event arrived before shared_inference_ended
        const recentWorkflow = processedMessageIds.has(workflowKey)
        if (recentWorkflow) {
          logDebug("[ChatPanel] Already have workflow for this conversation, skipping shared workflow")
        } else {
          // Add the workflow summary message so it appears in the chat
          const sharedPlan = data.workflowPlan || data.data?.workflowPlan
          const summaryMessage: Message = {
            id: summaryId,
            role: "system",
            type: "inference_summary",
            steps: workflowSteps,
            ...(sharedPlan ? { metadata: { workflow_plan: sharedPlan } } : {}),
          }
          
          // Add to messages if not already present (avoid duplicates)
          setMessages((prev) => {
            // Check if we already have any inference_summary for the most recent exchange
            // by looking for a summary that was added in the last few messages
            const recentSummaries = prev.slice(-5).filter(m => m.type === 'inference_summary')
            if (recentSummaries.length > 0) {
              logDebug("[ChatPanel] Recent workflow summary exists, skipping shared:", recentSummaries[0].id)
              return prev
            }
            
            const exists = prev.some(m => m.id === summaryId)
            if (exists) {
              logDebug("[ChatPanel] Workflow summary already exists, skipping:", summaryId)
              return prev
            }
            logDebug("[ChatPanel] Adding shared workflow summary:", summaryId)
            return [...prev, summaryMessage]
          })
          
          // Mark that we've received a workflow for this conversation
          setProcessedMessageIds(prev => new Set([...prev, workflowKey]))
          
          // Also persist to localStorage so it survives refresh
          try {
            let workflowConversationId = eventConvId || conversationId
            if (workflowConversationId.includes('::')) {
              workflowConversationId = workflowConversationId.split('::')[1]
            }
            const storageKey = `workflow_${workflowConversationId}`
            const existingData = localStorage.getItem(storageKey)
            const workflows = existingData ? JSON.parse(existingData) : []
            if (!workflows.some((w: any) => w.id === summaryId)) {
              workflows.push({
                id: summaryId,
                steps: workflowSteps,
                timestamp: Date.now()
              })
              localStorage.setItem(storageKey, JSON.stringify(workflows))
              logDebug("[ChatPanel] Persisted shared workflow to localStorage:", storageKey)
            }
          } catch (err) {
            console.error('[ChatPanel] Failed to persist shared workflow to localStorage:', err)
          }
        }
      }
      
      // Handle the response message if included
      const responseMessage = data.responseMessage || data.data?.responseMessage
      if (responseMessage) {
        logDebug("[ChatPanel] Received response message from shared_inference_ended:", responseMessage)
        
        // Check if we already received a response via the message event
        const responseReceivedKey = `response_received_${eventConvId || conversationId}`
        if (processedMessageIds.has(responseReceivedKey)) {
          logDebug("[ChatPanel] Response already received via message event, skipping shared response")
        } else {
          // Add the response message if we don't already have it
          // Check by content similarity since IDs may differ between message event and shared_inference_ended
          setMessages((prev) => {
            const exists = prev.some(m => m.id === responseMessage.id)
            if (exists) {
              logDebug("[ChatPanel] Response message already exists (by ID), skipping:", responseMessage.id)
              return prev
            }
            
            // Also check if we have a recent assistant message with the same content
            const recentAssistants = prev.slice(-3).filter(m => m.role === 'assistant')
            const hasSameContent = recentAssistants.some(m => 
              m.content === responseMessage.content && 
              m.agent === responseMessage.agent
            )
            if (hasSameContent) {
              logDebug("[ChatPanel] Response message already exists (by content), skipping")
              return prev
            }
            
            logDebug("[ChatPanel] Adding shared response message:", responseMessage.id)
            return [...prev, responseMessage]
          })
        }
      }
      
      setIsInferencing(false)
      setInferenceSteps([])
      setActiveNode(null)
    }

    // Handle shared file uploads from other collaborative session members
    const handleSharedFileUploaded = (data: any) => {
      logDebug("[ChatPanel] Shared file uploaded:", data)
      
      // Filter by session
      let eventTenantId = ""
      const convId = data.conversationId || ""
      if (convId.includes("::")) {
        eventTenantId = convId.split("::")[0]
      }
      const mySessionId = getOrCreateSessionId()
      if (eventTenantId && mySessionId && eventTenantId !== mySessionId) {
        logDebug("[ChatPanel] Ignoring shared file from different session:", eventTenantId, "my session:", mySessionId)
        return
      }
      
      // FileHistory component handles adding the file via its own 'shared_file_uploaded' subscription
    }

    // Handle conversation events
    const handleConversationCreated = (data: any) => {
      logInfo("[ChatPanel] Conversation created:", data)
      
      // Filter by session - only process events for the current session
      // In collaborative sessions, getOrCreateSessionId() returns the shared session ID
      let eventTenantId = ""
      const rawConvId = data.conversationId || ""
      if (rawConvId.includes("::")) {
        eventTenantId = rawConvId.split("::")[0]
      }
      const mySessionId = getOrCreateSessionId()
      if (eventTenantId && mySessionId && eventTenantId !== mySessionId) {
        logDebug("[ChatPanel] Ignoring conversation created from different session:", eventTenantId, "my session:", mySessionId)
        return
      }
      
      // A2A ConversationCreatedEventData has: conversationId, conversationName, isActive, messageCount
      if (data.conversationId) {
        // Strip tenant prefix from conversationId (format: "user_3::conv_id" -> "conv_id")
        const strippedConvId = rawConvId.includes("::") ? rawConvId.split("::")[1] : rawConvId
        
        // Only start inference tracking if we're on the home page or viewing this conversation
        // This prevents "Processing..." from showing when viewing a different conversation
        if (conversationId === 'frontend-chat-context' || conversationId === strippedConvId) {
          setIsInferencing(true)
          setInferenceSteps([])
          emit("status_update", {
            inferenceId: data.conversationId,
            agent: "System",
            status: "new conversation created"
          })
        }
        
        // Also fix the conversation name if it has the tenant prefix
        let convName = data.conversationName || `Chat ${strippedConvId.slice(0, 8)}...`
        if (convName.includes("::")) {
          convName = `Chat ${strippedConvId.slice(0, 8)}...`
        }
        
        // Notify the sidebar about the new conversation
        // Convert WebSocket event format to Conversation object format
        notifyConversationCreated({
          conversation_id: strippedConvId,
          name: convName,
          is_active: data.isActive !== false,
          task_ids: [],
          messages: []
        })
      }
    }

    // Handle inference step events (tool calls, remote agent activities)
    const handleInferenceStep = (data: any) => {
      logDebug("[ChatPanel] Inference step received:", data)
      
      // Filter by conversationId - only process steps for the current conversation
      let stepConvId = data.conversationId || data.contextId || ""
      if (stepConvId.includes("::")) {
        stepConvId = stepConvId.split("::")[1]
      }
      if (shouldFilterByConversationIdRef.current(stepConvId)) {
        logDebug("[ChatPanel] Ignoring inference step for different conversation:", stepConvId, "current:", conversationId)
        return
      }

      // Skip events after workflow was cancelled by user
      if (workflowCancelledRef.current) {
        logDebug("[ChatPanel] Ignoring inference step - workflow was cancelled")
        return
      }

      if (data.agent && data.status) {
        // If we receive inference steps, inference is happening - show the workflow panel
        // This helps collaborators who join mid-workflow see the progress
        setIsInferencing(true)
        
        setInferenceSteps(prev => {
          // Avoid duplicates - update existing or add new
          const existingIndex = prev.findIndex(step => 
            step.agent === data.agent && step.status === data.status
          )
          if (existingIndex >= 0) {
            return prev // Already exists, don't duplicate
          }
          return [...prev, { agent: data.agent, status: data.status }]
        })
      }
    }

    // Handle tool call events
    const handleToolCall = (data: any) => {
      logDebug("[ChatPanel] Tool call received:", data)
      
      // Filter by conversationId - only process tool calls for the current conversation
      let toolConvId = data.conversationId || data.contextId || ""
      if (toolConvId.includes("::")) {
        toolConvId = toolConvId.split("::")[1]
      }
      if (shouldFilterByConversationIdRef.current(toolConvId)) {
        logDebug("[ChatPanel] Ignoring tool call for different conversation:", toolConvId, "current:", conversationId)
        return
      }

      // Skip events after workflow was cancelled by user
      if (workflowCancelledRef.current) {
        logDebug("[ChatPanel] Ignoring tool call - workflow was cancelled")
        return
      }

      if (data.toolName && data.agentName) {
        const status = `🛠️ ${data.agentName} is using ${data.toolName}...`
        setInferenceSteps(prev => [...prev, { 
          agent: data.agentName, 
          status: status,
          eventType: "tool_call",
          metadata: { tool_name: data.toolName },
          taskId: data.taskId,
        }])
      }
    }

    // Handle tool response events
    const handleToolResponse = (data: any) => {
      logDebug("[ChatPanel] Tool response received (ignored - using task_updated instead):", data)
    }

    // Handle remote agent activity events
    const handleRemoteAgentActivity = (data: any) => {
      logDebug("[ChatPanel] Remote agent activity received:", data)
      
      // Filter by conversationId - only process activity for the current conversation
      // This prevents workflow steps from other conversations bleeding through
      let activityConvId = data.conversationId || data.contextId || ""
      if (activityConvId.includes("::")) {
        activityConvId = activityConvId.split("::")[1]
      }
      
      logDebug("[ChatPanel] Remote activity filter check:", {
        activityConvId, 
        currentConversationId: conversationId,
        pending: pendingConversationIdRef.current 
      })
      
      // In collaborative sessions, auto-navigate to the conversation if different
      if (shouldFilterByConversationIdRef.current(activityConvId)) {
        logDebug("[ChatPanel] Ignoring remote activity for different conversation:", activityConvId, "current:", conversationId)
        return
      }
      
      logDebug("[ChatPanel] Accepting remote activity for conversation:", activityConvId)

      // Skip events after workflow was cancelled by user
      if (workflowCancelledRef.current) {
        logDebug("[ChatPanel] Ignoring remote activity - workflow was cancelled")
        return
      }

      if (data.agentName && data.content) {
        const content = data.content
        // Backend now sends eventType on ALL events (no more untyped events)
        const activityType = data.activityType || data.eventType
        
        // Check if this is a completion message
        const isCompletionMessage = content.includes("completed the task") ||
                                    content.includes("completed successfully") ||
                                    content.includes("task complete") ||
                                    content === "completed"
        
        if (!isCompletionMessage) {
          setIsInferencing(true)
        }
        
        // All backend events now have eventType - no legacy filtering needed
        // Skip only truly empty content
        if (!content || content.trim().length < 2) {
          logDebug("[ChatPanel] Skipping empty status")
          return
        }
        
        setInferenceSteps(prev => {
          // Check last 8 entries for duplicates (wider window for busy workflows)
          const recentStartIdx = Math.max(0, prev.length - 8)
          const duplicateIdx = prev.findIndex(
            (entry, idx) => idx >= recentStartIdx && entry.agent === data.agentName && entry.status === content
          )
          
          // If a typed version arrives and an untyped duplicate exists, REPLACE the old one
          if (duplicateIdx >= 0 && activityType && !prev[duplicateIdx].eventType) {
            const updated = [...prev]
            updated[duplicateIdx] = {
              agent: data.agentName,
              status: content,
              eventType: activityType,
              metadata: data.metadata,
              taskId: data.taskId,
            }
            return updated
          }
          
          // Collapse consecutive "is working on" from same agent — but only if same parallel call
          if (prev.length > 0) {
            const lastEntry = prev[prev.length - 1]
            const lastCallId = lastEntry.metadata?.parallel_call_id
            const thisCallId = data.metadata?.parallel_call_id
            const sameParallelCall = lastCallId === thisCallId  // both undefined = same (sequential)
            if (lastEntry.agent === data.agentName &&
                sameParallelCall &&
                lastEntry.status.includes("is working on") &&
                content.includes("is working on")) {
              // Replace the last "working on" with the new one instead of adding
              return [...prev.slice(0, -1), {
                agent: data.agentName,
                status: content,
                eventType: activityType,
                metadata: data.metadata,
                taskId: data.taskId,
              }]
            }
          }
          
          if (duplicateIdx >= 0) {
            logDebug("[ChatPanel] Skipping duplicate remote activity:", content.substring(0, 50))
            return prev
          }
          
          return [...prev, { 
            agent: data.agentName, 
            status: content,
            eventType: activityType,
            metadata: data.metadata,
            taskId: data.taskId,
          }]
        })
      }
    }

    // Handle file uploaded events from agents
    const handleFileUploaded = (data: any) => {
      logDebug("[ChatPanel] File uploaded from agent:", data)
      
      // Filter by conversationId - only process files for the current conversation
      let fileConvId = data.conversationId || data.contextId || ""
      if (fileConvId.includes("::")) {
        fileConvId = fileConvId.split("::")[1]
      }
      if (shouldFilterByConversationIdRef.current(fileConvId)) {
        logDebug("[ChatPanel] Ignoring file upload for different conversation:", fileConvId, "current:", conversationId)
        return
      }

      // Skip events after workflow was cancelled by user
      if (workflowCancelledRef.current) {
        logDebug("[ChatPanel] Ignoring file upload - workflow was cancelled")
        return
      }

      if (data?.fileInfo && data.fileInfo.source_agent) {
        const isImage = data.fileInfo.content_type?.startsWith('image/') || 
          ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'].includes(
            (data.fileInfo.filename || '').toLowerCase().split('.').pop() || ''
          )
        const isVideo = data.fileInfo.content_type?.startsWith('video/') || 
          ['mp4', 'webm', 'mov', 'avi', 'mkv'].includes(
            (data.fileInfo.filename || '').toLowerCase().split('.').pop() || ''
          )
        const isMedia = isImage || isVideo
        
        // Determine correct media type - don't default to image/png for non-images
        let mediaType = data.fileInfo.content_type
        if (!mediaType) {
          const ext = (data.fileInfo.filename || '').toLowerCase().split('.').pop() || ''
          if (isImage) {
            mediaType = `image/${ext === 'jpg' ? 'jpeg' : ext}`
          } else if (isVideo) {
            mediaType = `video/${ext}`
          } else if (ext === 'pdf') {
            mediaType = 'application/pdf'
          } else {
            mediaType = 'application/octet-stream'
          }
        }
        
        // Add to inference steps (with thumbnail for images, text for other files)
        // This shows the image/video in the workflow panel during execution
        const fileVerb = isMedia ? "Generated" : "Extracted"
        setInferenceSteps(prev => [...prev, {
          agent: data.fileInfo.source_agent,
          status: `📎 ${fileVerb} ${data.fileInfo.filename}`,
          imageUrl: isMedia && data.fileInfo.uri ? data.fileInfo.uri : undefined,
          imageName: data.fileInfo.filename,
          mediaType: mediaType,
          metadata: data.fileInfo.parallel_call_id ? { parallel_call_id: data.fileInfo.parallel_call_id } : undefined,
        }])
        
        // NOTE: We do NOT add images as separate messages here anymore
        // The image will be included in the final_response message via attachments
        // This ensures the image appears AFTER the workflow, not before it
        
        // NOTE: File history is already handled by ChatLayout.handleFileUploaded
        // which also subscribes to file_uploaded events. Adding here would cause
        // duplicates with different IDs (uri vs file_id).
      }
    }

    // Handle plan_update events - the source of truth for workflow state
    const handlePlanUpdate = (data: any) => {
      logDebug("[ChatPanel] Plan update received:", data)
      
      // Filter by conversationId
      let planConvId = data.conversationId || data.contextId || ""
      if (planConvId.includes("::")) {
        planConvId = planConvId.split("::")[1]
      }
      if (shouldFilterByConversationIdRef.current(planConvId)) {
        logDebug("[ChatPanel] Ignoring plan update for different conversation:", planConvId)
        return
      }

      // Skip events after workflow was cancelled by user
      if (workflowCancelledRef.current) {
        logDebug("[ChatPanel] Ignoring plan update - workflow was cancelled")
        return
      }

      if (data.plan) {
        setWorkflowPlan({
          ...data.plan,
          reasoning: data.reasoning || data.plan.reasoning
        })
        setIsInferencing(data.plan.goal_status !== "completed")
      }
    }

    // Handle workflow_cancelled events - when user cancels a running workflow
    const handleWorkflowCancelled = (data: any) => {
      logDebug("[ChatPanel] Workflow cancelled event received:", data)
      
      // Filter by conversationId
      let cancelConvId = data.conversationId || data.contextId || ""
      if (cancelConvId.includes("::")) {
        cancelConvId = cancelConvId.split("::")[1]
      }
      if (shouldFilterByConversationIdRef.current(cancelConvId)) {
        logDebug("[ChatPanel] Ignoring workflow_cancelled for different conversation:", cancelConvId)
        return
      }

      // Skip if already handled locally by handleStop
      if (workflowCancelledRef.current) {
        logDebug("[ChatPanel] Ignoring workflow_cancelled event - already handled locally")
        return
      }

      // Stop inferencing immediately
      setIsInferencing(false)
      
      // Update workflow plan to show cancelled state
      if (data.plan) {
        setWorkflowPlan({
          ...data.plan,
          reasoning: data.reason || "Workflow cancelled by user"
        })
      } else {
        // Clear the workflow plan or mark it as cancelled
        setWorkflowPlan(prev => prev ? {
          ...prev,
          goal_status: "cancelled",
          reasoning: data.reason || "Workflow cancelled by user"
        } : null)
      }
      
      // Add a system message indicating cancellation
      if (data.message) {
        const cancelMessage: Message = {
          id: `cancel-${Date.now()}`,
          role: "system",
          content: data.message,
        }
        setMessages(prev => [...prev, cancelMessage])
      }
    }

    // Handle workflow_interrupted events - when user redirects a running workflow
    const handleWorkflowInterrupted = (data: any) => {
      logDebug("[ChatPanel] Workflow interrupted event received:", data)
      
      // Filter by conversationId
      let intConvId = data.conversationId || data.contextId || ""
      if (intConvId.includes("::")) {
        intConvId = intConvId.split("::")[1]
      }
      if (shouldFilterByConversationIdRef.current(intConvId)) {
        return
      }

      // Skip events after workflow was cancelled by user
      if (workflowCancelledRef.current) {
        logDebug("[ChatPanel] Ignoring workflow interrupted - workflow was cancelled")
        return
      }

      // Add an inference step to show the redirect in the workflow visualization
      const instruction = data.data?.instruction || "Redirected"
      setInferenceSteps(prev => [...prev, {
        agent: "foundry-host-agent",
        content: `⚡ Redirecting: ${instruction}`,
        status: "running" as const,
        timestamp: new Date()
      }])
    }

    // Handle typing indicator from other users
    const handleTypingIndicator = (eventData: any) => {
      const userId = eventData.data?.user_id
      const username = eventData.data?.username
      const isTyping = eventData.data?.is_typing
      
      if (!userId || !username) return
      
      setTypingUsers(prev => {
        const newMap = new Map(prev)
        if (isTyping) {
          newMap.set(userId, username)
        } else {
          newMap.delete(userId)
        }
        return newMap
      })
      
      // Auto-remove after 5 seconds (in case stop event is missed)
      if (isTyping) {
        setTimeout(() => {
          setTypingUsers(prev => {
            const newMap = new Map(prev)
            newMap.delete(userId)
            return newMap
          })
        }, 5000)
      }
    }

    // Handle message reactions
    const handleMessageReaction = (eventData: any) => {
      const messageId = eventData.data?.message_id
      const emoji = eventData.data?.emoji
      const userId = eventData.data?.user_id
      const username = eventData.data?.username
      const action = eventData.data?.action // 'add' or 'remove'
      
      logDebug('[MessageReaction] Received:', { messageId, emoji, userId, username, action })
      
      if (!messageId || !emoji || !userId || !username) {
        warnDebug('[MessageReaction] Missing required fields')
        return
      }
      
      // Force React to see a new array by creating entirely new message objects
      setMessages(prevMessages => {
        const newMessages = prevMessages.map(msg => {
          if (msg.id !== messageId) {
            return msg
          }
          
          // Found the message - create new reactions array
          const currentReactions = msg.reactions ? [...msg.reactions] : []
          const existingIdx = currentReactions.findIndex(r => r.emoji === emoji)
          
          if (action === 'add') {
            if (existingIdx >= 0) {
              // Update existing reaction with new arrays
              const existing = currentReactions[existingIdx]
              if (!existing.users.includes(userId)) {
                currentReactions[existingIdx] = {
                  emoji: existing.emoji,
                  users: [...existing.users, userId],
                  usernames: [...existing.usernames, username]
                }
              }
            } else {
              // Add new reaction
              currentReactions.push({
                emoji,
                users: [userId],
                usernames: [username]
              })
            }
          } else if (action === 'remove') {
            if (existingIdx >= 0) {
              const existing = currentReactions[existingIdx]
              const userIdx = existing.users.indexOf(userId)
              if (userIdx >= 0) {
                currentReactions[existingIdx] = {
                  emoji: existing.emoji,
                  users: existing.users.filter((_, i) => i !== userIdx),
                  usernames: existing.usernames.filter((_, i) => i !== userIdx)
                }
              }
            }
          }
          
          // Filter out empty reactions
          const finalReactions = currentReactions.filter(r => r.users.length > 0)
          
          logDebug('[MessageReaction] Updated reactions for message:', messageId, finalReactions)
          
          // Return a completely new message object
          return {
            ...msg,
            reactions: finalReactions.length > 0 ? finalReactions : undefined
          }
        })
        
        // Return a new array reference
        return [...newMessages]
      })
    }

    // Handle run_workflow event from Play button
    const handleRunWorkflow = async (eventData: any) => {
      const { workflowName, workflow: workflowText, initialMessage, workflowGoal } = eventData
      
      logDebug('[ChatPanel] Running workflow:', workflowName)
      logDebug('[ChatPanel] Initial message:', initialMessage)
      logDebug('[ChatPanel] Workflow goal:', workflowGoal || '(none)')
      
      if (!initialMessage || !workflowText) {
        console.error('[ChatPanel] Missing workflow data')
        return
      }
      
      // Don't run if already inferencing
      if (isInferencing) {
        warnDebug('[ChatPanel] Already inferencing, cannot start workflow')
        return
      }
      
      // Create a system message to indicate workflow is starting
      const systemMessage: Message = {
        id: `workflow_start_${Date.now()}`,
        role: "system",
        content: `▶️ Starting workflow: **${workflowName}**`
      }
      setMessages(prev => [...prev, systemMessage])
      
      // Create user message with the first step description
      const userMessage: Message = {
        id: `msg_${Date.now()}`,
        role: "user",
        content: initialMessage,
        ...(currentUser && {
          username: currentUser.name,
          userColor: currentUser.color
        })
      }
      setMessages(prev => [...prev, userMessage])
      
      setIsInferencing(true)
      setInferenceSteps([])
      setActiveNode("User Input")
      
      // Get or create conversation
      let actualConversationId = conversationId
      if (conversationId === 'frontend-chat-context') {
        try {
          const newConversation = await createConversation()
          if (newConversation) {
            actualConversationId = newConversation.conversation_id
            // Track this as our pending conversation to accept messages for it
            pendingConversationIdRef.current = actualConversationId
            notifyConversationCreated(newConversation)
            router.replace(`/?conversationId=${actualConversationId}`)
          }
        } catch (error) {
          console.error('[ChatPanel] Failed to create conversation:', error)
          setIsInferencing(false)
          return
        }
      }
      
      // Broadcast inference started
      sendMessage({
        type: "shared_inference_started",
        data: {
          conversationId: actualConversationId,
          timestamp: new Date().toISOString()
        }
      })
      
      // Send the workflow execution request to backend
      try {
        const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
        const response = await fetch(`${baseUrl}/message/send`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            params: {
              messageId: userMessage.id,
              contextId: createContextId(actualConversationId),
              role: 'user',
              parts: [{ root: { kind: 'text', text: initialMessage } }],
              enableInterAgentMemory: enableInterAgentMemory,
              workflow: workflowText.trim(),
              workflowGoal: workflowGoal || '',
              userId: currentUser?.user_id,
            }
          })
        })
        
        if (!response.ok) {
          console.error('[ChatPanel] Failed to execute workflow:', response.statusText)
          setIsInferencing(false)
        } else {
          logDebug('[ChatPanel] Workflow execution started successfully')
        }
      } catch (error) {
        console.error('[ChatPanel] Error executing workflow:', error)
        setIsInferencing(false)
      }
    }

    // Subscribe to real Event Hub events from A2A backend
    subscribe("run_workflow", handleRunWorkflow)
    subscribe("task_updated", handleTaskUpdate)
    subscribe("task_created", handleTaskCreated)
    subscribe("system_event", handleSystemEvent)
    subscribe("message_sent", handleMessageSent)
    subscribe("message_received", handleMessageReceived)
    subscribe("message", handleMessage)
    subscribe("message_chunk", handleMessageChunk)  // Real-time streaming
    subscribe("shared_message", handleSharedMessage)
    subscribe("shared_inference_started", handleSharedInferenceStarted)
    subscribe("shared_inference_ended", handleSharedInferenceEnded)
    subscribe("conversation_created", handleConversationCreated)
    subscribe("agent_registered", handleAgentRegistered)
    subscribe("inference_step", handleInferenceStep)
    subscribe("tool_call", handleToolCall)
    subscribe("tool_response", handleToolResponse)
    subscribe("remote_agent_activity", handleRemoteAgentActivity)
    subscribe("plan_update", handlePlanUpdate)
    subscribe("workflow_cancelled", handleWorkflowCancelled)
    subscribe("workflow_interrupted", handleWorkflowInterrupted)
    subscribe("file_uploaded", handleFileUploaded)
    subscribe("shared_file_uploaded", handleSharedFileUploaded)
    subscribe("typing_indicator", handleTypingIndicator)
    subscribe("message_reaction", handleMessageReaction)

    return () => {
      unsubscribe("run_workflow", handleRunWorkflow)
      unsubscribe("task_updated", handleTaskUpdate)
      unsubscribe("task_created", handleTaskCreated)
      unsubscribe("system_event", handleSystemEvent)
      unsubscribe("message_sent", handleMessageSent)
      unsubscribe("message_received", handleMessageReceived)
      unsubscribe("message", handleMessage)
      unsubscribe("message_chunk", handleMessageChunk)  // Real-time streaming
      unsubscribe("shared_message", handleSharedMessage)
      unsubscribe("shared_inference_started", handleSharedInferenceStarted)
      unsubscribe("shared_inference_ended", handleSharedInferenceEnded)
      unsubscribe("conversation_created", handleConversationCreated)
      unsubscribe("agent_registered", handleAgentRegistered)
      unsubscribe("inference_step", handleInferenceStep)
      unsubscribe("tool_call", handleToolCall)
      unsubscribe("tool_response", handleToolResponse)
      unsubscribe("remote_agent_activity", handleRemoteAgentActivity)
      unsubscribe("plan_update", handlePlanUpdate)
      unsubscribe("workflow_cancelled", handleWorkflowCancelled)
      unsubscribe("workflow_interrupted", handleWorkflowInterrupted)
      unsubscribe("file_uploaded", handleFileUploaded)
      unsubscribe("shared_file_uploaded", handleSharedFileUploaded)
      unsubscribe("typing_indicator", handleTypingIndicator)
      unsubscribe("message_reaction", handleMessageReaction)
    }
  }, [subscribe, unsubscribe, emit, sendMessage, conversationId, isLoadingMessages])
  // NOTE: Removed shouldFilterByConversationId from deps - using ref instead to prevent
  // effect re-runs when isInCollaborativeSession changes (which was resetting workflow bar state)
  // NOTE: Removed processedMessageIds from deps to prevent constant re-subscription

  // Check authentication status and show welcome message only when logged in
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const token = sessionStorage.getItem('auth_token')
      const userInfo = sessionStorage.getItem('user_info')
      if (token && userInfo) {
        try {
          const user = JSON.parse(userInfo)
          setCurrentUser(user)
          // User is authenticated - show welcome message if no conversation loaded
          setMessages((prevMessages) => {
            if (prevMessages.length === 0 && conversationId === 'frontend-chat-context') {
              return initialMessages
            }
            return prevMessages
          })
        } catch (e) {
          console.error('Failed to parse user info:', e)
          // Not authenticated - clear everything
          setCurrentUser(null)
          setMessages([])
        }
      } else {
        // Not authenticated - clear everything
        setCurrentUser(null)
        setMessages([])
      }
    }
  }, [conversationId])

  useEffect(() => {
    const handleStatusUpdate = (data: { inferenceId: string; agent: string; status: string }) => {
      logDebug("[ChatPanel] Status update:", data)
      
      // Filter by conversationId - only process status updates for the current conversation
      // inferenceId typically contains "sessionId::conversationId" format
      let statusConvId = data.inferenceId || ""
      if (statusConvId.includes("::")) {
        statusConvId = statusConvId.split("::")[1]
      }
      
      // In collaborative sessions, auto-navigate to the conversation if different
      if (shouldFilterByConversationIdRef.current(statusConvId)) {
        logDebug("[ChatPanel] Ignoring status update for different conversation:", statusConvId, "current:", conversationId)
        return
      }
      
      setInferenceSteps((prev) => [...prev, { agent: data.agent, status: data.status }])
      setActiveNode(data.agent)
    }

    const handleFinalResponse = (data: { inferenceId?: string; message?: Omit<Message, "id">; conversationId?: string; messageId?: string; attachments?: any[]; isFromMyTenant?: boolean; isComplete?: boolean; result?: string; contextId?: string }) => {
      logDebug("[ChatPanel] Final response received:", data)
      
      // Filter by conversationId - only process final responses for the current conversation
      let responseConvId = data.conversationId || data.inferenceId || data.contextId || ""
      if (responseConvId.includes("::")) {
        responseConvId = responseConvId.split("::")[1]
      }
      
      // In collaborative sessions, auto-navigate to the conversation if different
      if (shouldFilterByConversationIdRef.current(responseConvId)) {
        logDebug("[ChatPanel] Ignoring final response for different conversation:", responseConvId, "current:", conversationId)
        return
      }
      
      // If this is a simple "completion" event (from /api/query voice), just clear inference state
      // No message to add - the message was already handled via normal flow
      if (data.isComplete && !data.message) {
        logDebug("[ChatPanel] Voice/API query complete - clearing inference state")
        setIsInferencing(false)
        setInferenceSteps([])
        setActiveNode(null)
        return
      }
      
      // Use messageId from backend if available, otherwise generate unique ID based on timestamp
      // Don't use content in the key since same content can be sent multiple times
      const responseId = data.messageId || `response_${data.inferenceId}_${Date.now()}`
      
      logDebug("[ChatPanel] Response ID:", responseId)
      logDebug("[ChatPanel] Already processed?", processedMessageIds.has(responseId))
      logDebug("[ChatPanel] Current processed IDs:", Array.from(processedMessageIds))
      
      // Check if we've already processed this exact message
      if (processedMessageIds.has(responseId)) {
        logDebug("[ChatPanel] Duplicate response detected, skipping:", responseId)
        // Still clear inferencing state even for duplicates - the workflow is complete
        setIsInferencing(false)
        setInferenceSteps([])
        setActiveNode(null)
        return
      }
      
      // Mark this message as processed
      setProcessedMessageIds(prev => new Set([...prev, responseId]))
      
      // Only add messages if they have content and a message object exists
      if (!data.message) {
        logDebug("[ChatPanel] No message in final_response, just clearing inference state")
        setIsInferencing(false)
        setInferenceSteps([])
        setActiveNode(null)
        return
      }

      // If the workflow was cancelled by handleStop, skip the backend response entirely
      // (handleStop already saved the steps and added the cancel message)
      if (workflowCancelledRef.current) {
        logDebug("[ChatPanel] Skipping backend response - workflow was cancelled by user")
        workflowCancelledRef.current = false // Reset for next workflow
        setIsInferencing(false)
        setInferenceSteps([])
        setActiveNode(null)
        return
      }
      
      const messagesToAdd: Message[] = []
      
      const isHostAgent = data.message.agent === "foundry-host-agent" || 
                          data.message.agent === "Host Agent" ||
                          data.message.agent === "System"

      // Use conversationId from the event data if available, otherwise fall back to component state
      // This ensures workflows from the visual designer are saved to the correct key
      let effectiveConversationId = data.conversationId || data.inferenceId || conversationId
      
      // Extract just the conversationId part if it includes session prefix (sessionId::conversationId)
      // This ensures localStorage keys match between save and load
      if (effectiveConversationId && effectiveConversationId.includes('::')) {
        effectiveConversationId = effectiveConversationId.split('::')[1]
      }

      // Add inference summary FIRST (so workflow appears BEFORE response)
      // Show workflow whenever we have steps, regardless of which agent responds
      // Use timestamp to ensure uniqueness - each inference should get its own workflow display
      const summaryId = `summary_${data.inferenceId}_${Date.now()}`
      // Only create ONE workflow summary per message (using responseId which is unique per message)
      // Previously used inferenceId (conversationId) which caused second message workflow to be skipped
      const workflowKey = `workflow_${responseId}`
      // Also track by conversation ID so handleSharedInferenceEnded knows to skip
      const workflowReceivedKey = `workflow_received_${effectiveConversationId}`
      const alreadyCreatedWorkflow = processedMessageIds.has(workflowKey)
      
      // Copy steps EARLY - before any clearing happens - for sharing with other clients
      const stepsToShare = inferenceSteps.length > 0 ? [...inferenceSteps] : []
      
      if (inferenceSteps.length > 0 && !alreadyCreatedWorkflow) {
        // CRITICAL: Clear live workflow state IMMEDIATELY before creating the permanent workflow message
        // This prevents the brief moment where both the live workflow AND the permanent one are visible
        const stepsCopy = [...inferenceSteps] // Copy steps BEFORE clearing them
        setIsInferencing(false)
        setInferenceSteps([])
        setActiveNode(null)
        
        // Mark this inference as having a workflow created
        // Include workflowReceivedKey so handleSharedInferenceEnded will skip duplicate workflow
        setProcessedMessageIds(prev => new Set([...prev, summaryId, workflowKey, workflowReceivedKey]))
        const planCopy = workflowPlan ? { ...workflowPlan } : undefined
        const summaryMessage: Message = {
          id: summaryId,
          role: "system",
          type: "inference_summary",
          steps: stepsCopy,
          ...(planCopy ? { metadata: { workflow_plan: planCopy } } : {}),
        }
        messagesToAdd.push(summaryMessage)
        
        // Persist workflow to localStorage so it survives page refresh
        // Store keyed by conversationId with the inference steps and associated message position
        try {
          const storageKey = `workflow_${effectiveConversationId}`
          const existingData = localStorage.getItem(storageKey)
          const workflows = existingData ? JSON.parse(existingData) : []
          // Check if this workflow already exists (by id) to avoid duplicates
          if (!workflows.some((w: any) => w.id === summaryId)) {
            workflows.push({
              id: summaryId,
              steps: stepsCopy,
              ...(planCopy ? { metadata: { workflow_plan: planCopy } } : {}),
              timestamp: Date.now()
            })
            localStorage.setItem(storageKey, JSON.stringify(workflows))
          }
        } catch (err) {
          console.error('[ChatPanel] Failed to persist workflow to localStorage:', err)
        }
      }

      // Add final message AFTER the workflow summary
      if (data.message.content && data.message.content.trim().length > 0) {
        const finalMessage: Message = {
          id: responseId,
          role: data.message.role === "user" ? "user" : "assistant",
          content: data.message.content,
          agent: data.message.agent,
        }
        messagesToAdd.push(finalMessage)
        
        // Track that we've received a response for this conversation
        // This helps handleSharedInferenceEnded skip duplicate responses
        const responseReceivedKey = `response_received_${effectiveConversationId}`
        setProcessedMessageIds(prev => new Set([...prev, responseReceivedKey]))
      }

      // Add attachments AFTER the text message (so order is: workflow -> text -> video/images)
      if (data.attachments && data.attachments.length > 0) {
        const attachmentId = `${responseId}_attachments`
        const attachmentMessage: Message = {
          id: attachmentId,
          role: "assistant",
          agent: data.message.agent,
          attachments: data.attachments,
        }
        messagesToAdd.push(attachmentMessage)
        logDebug("[ChatPanel] Adding attachment message after text:", attachmentMessage)
        
        // Broadcast attachment message to other users
        // (done after adding to messagesToAdd so the order is preserved)
      }

      // NOTE: We no longer add media from inference steps as separate messages here.
      // Media (images/videos) are already added via handleMessage() -> attachmentMessage
      // when the WebSocket 'message' event arrives with video/image content.
      // Adding them here would create DUPLICATES.
      // The inference steps with imageUrl are only used for the workflow panel thumbnail preview.
      
      // NOTE: Inference state is cleared earlier (when creating the workflow summary)
      // to prevent brief moment where both live and permanent workflows are visible
      
      // Add messages only if we have any
      if (messagesToAdd.length > 0) {
        setMessages((prev) => [...prev, ...messagesToAdd])
        
        // Only broadcast to other users if this message originated from our session
        // This prevents re-broadcasting messages that were received from collaborative session members
        if (data.isFromMyTenant !== false) {
          // Broadcast messages to other users (but not inference summaries)
          messagesToAdd.forEach(msg => {
            if (msg.type !== 'inference_summary' && msg.role === 'assistant') {
              sendMessage({
                type: "shared_message",
                conversationId: effectiveConversationId,
                message: msg
              })
            }
          })
        } else {
          logDebug("[ChatPanel] Skipping shared_message broadcast - message from different tenant")
        }
      }

      // Only broadcast inference ended if this is from our session
      if (data.isFromMyTenant !== false) {
        // Find the assistant response message we just added (if any)
        const assistantMessage = messagesToAdd.find(msg => msg.role === 'assistant' && msg.type !== 'inference_summary')
        
        // Broadcast inference ended to all other clients WITH workflow steps AND response message
        sendMessage({
          type: "shared_inference_ended",
          data: {
            conversationId: data.inferenceId,
            timestamp: new Date().toISOString(),
            // Include workflow steps so other clients can display them
            workflowSteps: stepsToShare,
            // Include the workflow plan so other clients can render properly
            workflowPlan: workflowPlan || undefined,
            summaryId: `summary_${data.inferenceId}_${Date.now()}`,
            // Include the response message so other clients can display it
            responseMessage: assistantMessage || null
          }
        })
      }
      
      // Always clear inference state at the end of final_response processing
      // This handles cases where there are no inference steps (e.g., direct host agent responses)
      setIsInferencing(false)
      setInferenceSteps([])
      setActiveNode(null)
    }

    subscribe("status_update", handleStatusUpdate)
    subscribe("final_response", handleFinalResponse)

    return () => {
      unsubscribe("status_update", handleStatusUpdate)
      unsubscribe("final_response", handleFinalResponse)
    }
  }, [inferenceSteps, processedMessageIds, subscribe, unsubscribe, conversationId]) // Include conversationId for filtering
  // NOTE: Removed shouldFilterByConversationId - using ref instead

  const uploadFiles = async (files: FileList | File[]) => {
    if (!files || files.length === 0) return

    try {
      // Get session ID for tenant isolation
      const sessionId = getOrCreateSessionId()
      
      // Upload each file individually
      for (let i = 0; i < files.length; i++) {
        const file = files[i]
        const formData = new FormData()
        formData.append('file', file)

        const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
        const response = await fetch(`${baseUrl}/upload`, {
          method: 'POST',
          headers: {
            'X-Session-ID': sessionId
          },
          body: formData
        })

        const result = await response.json()
        if (result.success) {
          setUploadedFiles(prev => [...prev, result])

          // Broadcast file upload to collaborative session members
          // FileHistory component picks this up via 'shared_file_uploaded' subscription
          sendMessage({
            type: "shared_file_uploaded",
            conversationId: conversationId,
            fileInfo: {
              id: result.file_id || result.filename,
              filename: result.filename,
              originalName: result.filename,
              size: result.size || 0,
              contentType: result.content_type || 'application/octet-stream',
              uri: result.uri,
              uploadedAt: new Date().toISOString()
            }
          })
          
          logDebug('File uploaded successfully:', result.filename)
        } else {
          console.error('File upload failed:', result.error)
        }
      }
    } catch (error) {
      console.error('File upload error:', error)
    }
  }

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files
    if (!files || files.length === 0) return

    await uploadFiles(files)

    // Reset file input
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  // Drag and drop handlers
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    
    if (e.dataTransfer.types.includes('Files')) {
      setIsDragOver(true)
    }
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(false)
  }

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    
    setIsDragOver(false)

    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) {
      await uploadFiles(files)
    }
  }

  const handlePaperclipClick = () => {
    fileInputRef.current?.click()
  }

  // Voice recording handlers
  const handleMicClick = async () => {
    if (voiceRecording.isRecording) {
      // Stop recording
      voiceRecording.stopRecording()
    } else {
      // Start recording
      await voiceRecording.startRecording()
    }
  }

  // Voice recording transcription handler
  const handleVoiceTranscription = useCallback(async () => {
    if (!voiceRecording.audioBlob) return

    try {
      const result = await voiceRecording.uploadAndTranscribe(voiceRecording.audioBlob)
      
      if (result.success && result.transcript) {
        // Set the transcribed text as the input
        setInput(result.transcript)
        
        // Add a status message to show the transcription worked
        const statusMessage: Message = {
          id: `status_${Date.now()}`,
          role: "system",
          content: `🎤 Voice message transcribed: "${result.transcript.slice(0, 50)}${result.transcript.length > 50 ? '...' : ''}"`
        }
        setMessages((prev) => [...prev, statusMessage])
        
        // Auto-focus the input field so user can edit if needed
        setTimeout(() => {
          const inputElement = document.querySelector('input[placeholder="Type your message..."]') as HTMLInputElement
          inputElement?.focus()
        }, 100)
      } else {
        // Show error message
        const errorMessage: Message = {
          id: `error_${Date.now()}`,
          role: "system", 
          content: `❌ Voice transcription failed: ${result.error || 'Unknown error'}`
        }
        setMessages((prev) => [...prev, errorMessage])
      }
    } catch (error) {
      console.error('Voice transcription error:', error)
      const errorMessage: Message = {
        id: `error_${Date.now()}`,
        role: "system",
        content: `❌ Voice transcription failed: ${error instanceof Error ? error.message : 'Unknown error'}`
      }
      setMessages((prev) => [...prev, errorMessage])
    } finally {
      // Reset the voice recording state
      voiceRecording.reset()
    }
  }, [voiceRecording, setInput, setMessages])

  // Handle when recording is complete and blob is available
  useEffect(() => {
    if (voiceRecording.audioBlob && !voiceRecording.isRecording && !voiceRecording.isProcessing) {
      // Automatically upload and transcribe when recording stops
      handleVoiceTranscription()
    }
  }, [voiceRecording.audioBlob, voiceRecording.isRecording, voiceRecording.isProcessing, handleVoiceTranscription])

  // Handle message reactions
  const handleReaction = useCallback((messageId: string, emoji: string) => {
    logDebug('[handleReaction] Called:', { messageId, emoji, currentUser, isInCollaborativeSession })
    
    if (!currentUser || !isInCollaborativeSession) {
      logDebug('[handleReaction] Skipped: No currentUser or not in collaborative session')
      return
    }
    
    // Find the message and check if user already reacted with this emoji
    const message = messages.find(m => m.id === messageId)
    if (!message) return
    
    const existingReaction = message.reactions?.find(r => r.emoji === emoji)
    const hasReacted = existingReaction?.users.includes(currentUser.user_id)
    const action = hasReacted ? 'remove' : 'add'
    
    // Optimistically update local state
    setMessages(prev => prev.map(msg => {
      if (msg.id !== messageId) return msg
      
      const reactions = msg.reactions || []
      const reaction = reactions.find(r => r.emoji === emoji)
      
      if (action === 'add') {
        if (reaction) {
          if (!reaction.users.includes(currentUser.user_id)) {
            reaction.users.push(currentUser.user_id)
            reaction.usernames.push(currentUser.name)
          }
        } else {
          reactions.push({
            emoji,
            users: [currentUser.user_id],
            usernames: [currentUser.name]
          })
        }
      } else {
        if (reaction) {
          const userIndex = reaction.users.indexOf(currentUser.user_id)
          if (userIndex > -1) {
            reaction.users.splice(userIndex, 1)
            reaction.usernames.splice(userIndex, 1)
          }
        }
      }
      
      const filteredReactions = reactions.filter(r => r.users.length > 0)
      
      return {
        ...msg,
        reactions: filteredReactions.length > 0 ? filteredReactions : undefined
      }
    }))
    
    // Send to backend
    logDebug('[handleReaction] Sending to backend:', {
      type: "message_reaction",
      data: {
        message_id: messageId,
        emoji,
        action,
        user_id: currentUser.user_id,
        username: currentUser.name,
        session_id: currentSessionId
      }
    })
    sendMessage({
      type: "message_reaction",
      data: {
        message_id: messageId,
        emoji,
        action,
        user_id: currentUser.user_id,
        username: currentUser.name,
        session_id: currentSessionId
      }
    })
  }, [currentUser, isInCollaborativeSession, messages, sendMessage, currentSessionId])

  // Handle stop/cancel workflow
  const handleStop = useCallback(() => {
    if (!isInferencing) return

    logDebug("[ChatPanel] Stop button clicked - cancelling workflow")

    // Send cancel_workflow message to backend via WebSocket
    sendMessage({
      type: "cancel_workflow",
      conversationId: conversationId,
      sessionId: currentSessionId,
      contextId: contextId
    })

    // Save current inference steps as a cancelled workflow summary BEFORE clearing
    const stepsCopy = [...inferenceSteps]
    const planCopy = workflowPlan ? { ...workflowPlan, goal_status: "cancelled" } : undefined

    // Immediately clear live inference state
    setIsInferencing(false)
    setInferenceSteps([])
    setActiveNode(null)

    // Build messages to add: cancel message + cancelled workflow summary
    const messagesToAdd: Message[] = []

    // 1. Add cancelled workflow summary with inference steps (shows "Workflow cancelled" header)
    if (stepsCopy.length > 0) {
      messagesToAdd.push({
        id: `cancel_summary_${Date.now()}`,
        role: "system",
        type: "inference_summary",
        steps: stepsCopy,
        metadata: { workflow_plan: planCopy, cancelled: true },
      })
    }

    // 2. Add the cancel text message
    messagesToAdd.push({
      id: `cancel_${Date.now()}`,
      role: "assistant",
      content: "Workflow cancelled by user.",
    })

    // Persist cancelled workflow to localStorage so it survives page refresh
    if (stepsCopy.length > 0) {
      try {
        let workflowConversationId = conversationId
        if (workflowConversationId && workflowConversationId.includes('::')) {
          workflowConversationId = workflowConversationId.split('::')[1]
        }
        const storageKey = `workflow_${workflowConversationId}`
        const existingData = localStorage.getItem(storageKey)
        const workflows = existingData ? JSON.parse(existingData) : []
        workflows.push({
          id: messagesToAdd[0].id,
          steps: stepsCopy,
          metadata: { workflow_plan: planCopy, cancelled: true },
          timestamp: Date.now()
        })
        localStorage.setItem(storageKey, JSON.stringify(workflows))
      } catch (err) {
        console.error('[ChatPanel] Failed to persist cancelled workflow to localStorage:', err)
      }
    }

    // Mark cancel synchronously via ref so the backend response handler will skip it
    workflowCancelledRef.current = true

    setMessages(prev => [...prev, ...messagesToAdd])

  }, [isInferencing, sendMessage, conversationId, currentSessionId, contextId, inferenceSteps, workflowPlan])

  // Handle interrupt/redirect during inference
  const handleInterrupt = useCallback(() => {
    if (!isInferencing || !input.trim()) return
    
    const instruction = input.trim()
    logDebug("[ChatPanel] Interrupt - redirecting workflow:", instruction)
    
    // Send interrupt_workflow message to backend via WebSocket
    sendMessage({
      type: "interrupt_workflow",
      conversationId: conversationId,
      sessionId: currentSessionId,
      contextId: contextId,
      instruction: instruction
    })
    
    // Show the redirect instruction as a user message
    const redirectMessage: Message = {
      id: `interrupt_${Date.now()}`,
      role: "user",
      content: `⚡ ${instruction}`,
    }
    setMessages(prev => [...prev, redirectMessage])
    
    // Clear input
    setInput("")
    
  }, [isInferencing, input, sendMessage, conversationId, currentSessionId, contextId])

  const handleSend = async () => {
    // Reset cancel flag for new workflow
    workflowCancelledRef.current = false

    // During inference, redirect to interrupt handler
    if (isInferencing) {
      handleInterrupt()
      return
    }
    if (!input.trim() && !refineTarget) return

    // Check if message only mentions users (no agents) - if so, just broadcast to UI
    // We track user mentions when they're selected from the dropdown
    if (mentionedUserNames.size > 0) {
      const userMessage: Message = {
        id: `msg_${Date.now()}`,
        role: "user",
        content: input,
        ...(currentUser && {
          username: currentUser.name,
          userColor: currentUser.color
        }),
        // Include uploaded files as attachments so they display in chat
        ...(uploadedFiles.length > 0 && {
          attachments: uploadedFiles.map(file => ({
            uri: file.uri,
            fileName: file.filename,
            fileSize: file.size,
            mediaType: file.content_type
          }))
        })
      }
      
      // Add message locally
      setMessages((prev) => [...prev, userMessage])
      
      // Broadcast message to all other connected clients via WebSocket
      sendMessage({
        type: "shared_message",
        conversationId: conversationId,
        message: userMessage
      })
      
      // Clear input and reset UI
      setInput("")
      setUploadedFiles([])
      setRefineTarget(null)
      setMentionedUserNames(new Set()) // Clear tracked user mentions
      if (textareaRef.current) {
        textareaRef.current.style.height = '48px'
      }
      
      return // Don't send to host orchestrator
    }

    // If we're still using the default conversation ID, wait for or create a real conversation first
    let actualConversationId = conversationId
    if (conversationId === 'frontend-chat-context') {
      // Wait a moment if conversation is being created
      if (isCreatingConversation) {
        logDebug('[ChatPanel] Waiting for conversation creation to complete...')
        // Wait up to 2 seconds for the conversation to be created
        for (let i = 0; i < 20; i++) {
          await new Promise(resolve => setTimeout(resolve, 100))
          if (!isCreatingConversation && conversationId !== 'frontend-chat-context') {
            actualConversationId = conversationId
            logInfo('[ChatPanel] Conversation created, proceeding with:', actualConversationId)
            break
          }
        }
      }
      
      // If still no conversation after waiting, create one now
      if (actualConversationId === 'frontend-chat-context') {
        try {
          logDebug('[ChatPanel] Creating conversation before sending message...')
          const newConversation = await createConversation()
          if (newConversation) {
            actualConversationId = newConversation.conversation_id
            // Track this as our pending conversation to accept messages for it
            pendingConversationIdRef.current = actualConversationId
            logInfo('[ChatPanel] Created conversation:', actualConversationId)
            // Notify sidebar about the new conversation
            notifyConversationCreated(newConversation)
            // Update URL immediately
            const newUrl = `/?conversationId=${actualConversationId}`
            router.replace(newUrl)
          }
        } catch (error) {
          console.error('[ChatPanel] Failed to create conversation:', error)
          return // Don't send message if conversation creation failed
        }
      }
    }

    const userMessage: Message = {
      id: `msg_${Date.now()}`,
      role: "user",
      content: input,
      // Include user information if authenticated
      ...(currentUser && {
        username: currentUser.name,
        userColor: currentUser.color
      }),
      // Include uploaded files as attachments so they display in chat
      ...(uploadedFiles.length > 0 && {
        attachments: uploadedFiles.map(file => ({
          uri: file.uri,
          fileName: file.filename,
          fileSize: file.size,
          mediaType: file.content_type
        }))
      })
    }
    
    // Add message locally
    setMessages((prev) => [...prev, userMessage])
    
    // Broadcast message to all other connected clients via WebSocket
    sendMessage({
      type: "shared_message",
      conversationId: actualConversationId,
      message: userMessage
    })
    
    setIsInferencing(true)
    setInferenceSteps([]) // Reset for new inference
    setWorkflowPlan(null) // Reset plan for new inference
    setActiveNode("User Input")

    // Broadcast inference started to all other clients
    sendMessage({
      type: "shared_inference_started",
      data: {
        conversationId: actualConversationId,
        timestamp: new Date().toISOString()
      }
    })

    // If this is the first user message in the conversation, update the title
    const currentMessages = messages.filter(msg => msg.role === 'user')
    if (currentMessages.length === 0 && actualConversationId !== 'frontend-chat-context') {
      const newTitle = generateTitleFromMessage(input)
      updateConversationTitle(actualConversationId, newTitle)
      
      // Also broadcast title update to collaborative session members via WebSocket
      sendMessage({
        type: "conversation_title_update",
        conversationId: actualConversationId,
        title: newTitle
      })
    }

      // Send message to A2A backend via HTTP API using correct A2A Message format
      try {
      // Build message parts including any uploaded files
      const parts: any[] = [
        {
          root: {
            kind: 'text',
            text: input
          }
        }
      ]

      // Add file parts for uploaded files
      uploadedFiles.forEach(file => {
        parts.push({
          root: {
            kind: 'file',
            file: {
              name: file.filename,
              uri: file.uri,
              mime_type: file.content_type,
              role: 'overlay',
            }
          }
        })
      })

      const existingUris = new Set(parts.filter(p => p.root?.kind === 'file').map(p => p.root.file.uri))

      // Add remix context if remixTarget is set (for video remix functionality)
      logDebug('[VideoRemix] Checking remixTarget before send:', remixTarget)
      if (remixTarget?.videoId) {
        const remixData = {
          type: 'video_remix_request',
          video_id: remixTarget.videoId,
          source_uri: remixTarget.uri,
          file_name: remixTarget.fileName,
        }
        logDebug('[VideoRemix] Adding remix context to message parts:', remixData)
        parts.push({
          root: {
            kind: 'data',
            data: remixData
          }
        })
        logDebug('[VideoRemix] Parts after adding remix context:', parts.length, 'parts total')
      }

      if (refineTarget?.imageUrl && !existingUris.has(refineTarget.imageUrl)) {
        const baseOriginalName = refineTarget.imageMeta?.fileName || `refine-${Date.now()}.png`
        const baseStem = baseOriginalName.replace(/\.[^.]+$/, '')
        const baseTaggedName = `${baseStem}_base.png`

        parts.push({
          root: {
            kind: 'file',
            file: {
              name: baseTaggedName,
              uri: refineTarget.imageUrl,
              mime_type: refineTarget.imageMeta?.mediaType || 'image/png',
              role: 'base',
            },
          },
        })
        existingUris.add(refineTarget.imageUrl)
      }

      if (maskAttachment && !existingUris.has(maskAttachment.uri)) {
        const maskOriginalName = maskAttachment.filename || `mask-${Date.now()}.png`
        const maskStem = maskOriginalName.replace(/\.[^.]+$/, '')
        const maskTaggedName = maskStem.endsWith('_mask') ? `${maskStem}.png` : `${maskStem}_mask.png`

        parts.push({
          root: {
            kind: 'file',
            file: {
              name: maskTaggedName,
              uri: maskAttachment.uri,
              mime_type: maskAttachment.content_type || 'image/png',
              role: 'mask',
            }
          }
        })
        existingUris.add(maskAttachment.uri)
      }

      const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
      const response = await fetch(`${baseUrl}/message/send`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          params: {
            messageId: userMessage.id,
            contextId: createContextId(actualConversationId),  // Use tenant-aware contextId
            role: 'user',
            parts: parts,
            enableInterAgentMemory: enableInterAgentMemory,  // Include inter-agent memory flag
            workflow: workflow ? workflow.trim() : undefined,  // Backend auto-detects mode from workflow presence
            workflowGoal: workflowGoal ? workflowGoal.trim() : undefined,  // Goal from workflow designer for completion evaluation
            // Send only active workflows where all required agents are available (for intelligent routing)
            availableWorkflows: activeWorkflows.length > 0 ? activeWorkflows
              .filter(w => isWorkflowRunnable(w.workflow))
              .map(w => ({
                id: w.id,
                name: w.name,
                description: w.description || '',
                goal: w.goal,
                workflow: w.workflow
              })) : undefined,
            userId: currentUser?.user_id,  // Store userId for color lookup when loading messages
          }
        })
      })

      if (!response.ok) {
        console.error('[ChatPanel] Failed to send message to backend:', response.statusText)
        setIsInferencing(false)
      } else {
        logDebug('[ChatPanel] Message sent to backend successfully')
        // The response will come through Event Hub events
      }
    } catch (error) {
      console.error('[ChatPanel] Error sending message to backend:', error)
      setIsInferencing(false)
    }

    // Clear input and uploaded files after successful send
    setInput("")
    setUploadedFiles([])
    setRefineTarget(null)
    if (remixTarget) {
      logDebug('[VideoRemix] Clearing remixTarget after send:', remixTarget.videoId)
    }
    setRemixTarget(null)
    setMentionedUserNames(new Set()) // Clear tracked user mentions
    setMaskAttachment(null)
    
    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = '48px'
    }
  }

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex flex-col h-full overflow-hidden relative">
      {/* Layout for when there are messages - normal chat */}
      {(messages.length > 0 || isInferencing) && (
        <>
          <div className="flex-1 overflow-hidden relative">
            {/* Drag and drop overlay */}
            {isDragOver && (
              <div className="absolute inset-0 bg-blue-50/90 border-2 border-dashed border-blue-300 z-50 flex items-center justify-center pointer-events-none">
                <div className="text-center">
                  <div className="text-blue-600 text-xl mb-2">📁</div>
                  <div className="text-blue-700 font-medium">Drop files here to upload</div>
                  <div className="text-blue-600 text-sm">Files will be added to your message</div>
                </div>
              </div>
            )}
            <div 
              ref={messagesContainerRef}
              className={`h-full overflow-y-auto ${isDragOver ? '[&_*]:pointer-events-none' : ''}`}
              data-chat-drop-zone
              onDragOver={handleDragOver}
              onDragEnter={handleDragEnter}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              <div className="flex flex-col gap-4 p-4">
            {messages.map((message, index) => {
              // Skip streaming message - it will be rendered separately after workflow
              if (message.id === streamingMessageId) {
                return null
              }
              
              if (message.type === "inference_summary") {
                // Only render if there are actual steps OR a plan
                if ((!message.steps || message.steps.length === 0) && !message.metadata?.workflow_plan) {
                  return null
                }
                // If this summary has no plan, check if a LATER summary has a plan
                // (HITL workflows produce two summaries: pre-pause events + post-resume plan)
                // The plan contains full task history, so the earlier one is redundant
                if (!message.metadata?.workflow_plan) {
                  const hasLaterPlan = messages.slice(index + 1).some(
                    m => m.type === "inference_summary" && m.metadata?.workflow_plan
                  )
                  if (hasLaterPlan) {
                    return null  // Skip — the later plan-based summary covers everything
                  }
                }
                // Pass the plan from metadata for rich rendering
                return <InferenceSteps
                  key={`${message.id}-${index}`}
                  steps={message.steps || []}
                  isInferencing={false}
                  plan={message.metadata?.workflow_plan}
                  cancelled={!!message.metadata?.cancelled}
                  agentColors={agentColors}
                />
              }
              
              // Skip rendering messages with no content, no attachments, and no images
              const hasContent = message.content && message.content.trim().length > 0
              const hasAttachments = message.attachments && message.attachments.length > 0
              const hasImages = message.images && message.images.length > 0
              if (!hasContent && !hasAttachments && !hasImages) {
                return null
              }
              
              return (
                <div
                  key={`${message.id}-${index}`}
                  className={`flex gap-3 ${message.role === "user" ? "justify-end" : "items-start"} relative`}
                >
                  {message.role === "assistant" && (
                    <div className="h-8 w-8 flex-shrink-0 bg-blue-500/10 rounded-lg flex items-center justify-center">
                      <Bot size={16} className="text-blue-500" />
                    </div>
                  )}
                  <div className={`flex flex-col ${message.role === "user" ? "items-start" : "items-start"}`}>
                    <div className="group flex gap-3 relative">
                      {/* Reaction picker - shows on hover */}
                      {isInCollaborativeSession && (
                        <div className="absolute -top-8 left-0 hidden group-hover:flex items-center gap-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg p-1 z-10">
                          {['👍', '👎', '❤️', '😂', '😮', '😢', '🎉'].map((emoji) => (
                            <button
                              key={emoji}
                              onClick={() => handleReaction(message.id, emoji)}
                              className="text-lg hover:scale-125 transition-transform p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
                              title={`React with ${emoji}`}
                            >
                              {emoji}
                            </button>
                          ))}
                        </div>
                      )}
                      
                      <div
                        className={`rounded-lg p-3 ${message.role === "user" ? "bg-slate-700 text-white max-w-md" : "bg-muted flex-1"
                          }`}
                      >
                      {message.attachments && message.attachments.length > 0 && (
                        <div className="flex flex-col gap-3 mb-3">
                          {message.attachments.map((attachment, attachmentIndex) => {
                            // Check mediaType first, then fall back to URL extension detection
                            const urlWithoutParams = (attachment.uri || "").split('?')[0].toLowerCase()
                            const isVideoByExt = /\.(mp4|webm|mov|avi|mkv)$/.test(urlWithoutParams)
                            const isImageByExt = /\.(png|jpe?g|gif|webp|svg|bmp)$/.test(urlWithoutParams)
                            const isPdfByExt = /\.pdf$/.test(urlWithoutParams)
                            const isDocumentByExt = /\.(docx|pptx|xlsx|doc|ppt|xls|csv|tsv)$/.test(urlWithoutParams)

                            // Documents and PDFs should NEVER be treated as images, even if mediaType is wrong
                            const isImage = !isPdfByExt && !isDocumentByExt && ((attachment.mediaType || "").startsWith("image/") || (!attachment.mediaType && isImageByExt))
                            const isVideo = (attachment.mediaType || "").startsWith("video/") || (!attachment.mediaType && isVideoByExt) || isVideoByExt
                            
                            // Debug: Log full type detection for each attachment
                            logDebug('[VideoRemix] Type detection for attachment:', {
                              index: attachmentIndex,
                              fileName: attachment.fileName,
                              mediaType: attachment.mediaType,
                              uri: attachment.uri?.slice(-60),
                              urlWithoutParams: urlWithoutParams?.slice(-60),
                              isVideoByExt,
                              isImageByExt,
                              isPdfByExt,
                              isVideo,
                              isImage,
                              videoId: attachment.videoId,
                              willRenderAs: isVideo ? 'VIDEO' : isImage ? 'IMAGE' : 'LINK'
                            })
                            
                            // Check video FIRST (so .mp4 URLs don't get treated as images)
                            if (isVideo) {
                              logDebug('[VideoRemix] Rendering as VIDEO:', attachment.fileName)
                              return (
                                <div key={`${message.id}-attachment-${attachmentIndex}`} className="flex flex-col gap-2">
                                  <div className="relative overflow-hidden rounded-lg border border-border bg-background">
                                    <video
                                      src={attachment.uri}
                                      controls
                                      className="w-full h-auto"
                                    >
                                      Your browser does not support the video tag.
                                    </video>
                                    <div className="px-3 py-2 text-xs text-muted-foreground border-t border-border bg-muted/50 flex items-center justify-between">
                                      <span>{attachment.fileName || "Video attachment"}</span>
                                      {attachment.videoId && (
                                        <span className="text-xs opacity-60">ID: {attachment.videoId.slice(-8)}</span>
                                      )}
                                    </div>
                                    {/* Remix button overlay for videos with videoId */}
                                    {attachment.videoId && message.role === "assistant" && (
                                      <div className="absolute top-2 right-2">
                                        <Button
                                          variant={remixTarget?.videoId === attachment.videoId ? "destructive" : "default"}
                                          size="sm"
                                          className={`shadow-lg ${
                                            remixTarget?.videoId === attachment.videoId 
                                              ? '' 
                                              : 'bg-purple-500 hover:bg-purple-600 text-white'
                                          }`}
                                          title={remixTarget?.videoId === attachment.videoId ? "Cancel remix" : "Remix this video"}
                                          onClick={(e) => {
                                            e.preventDefault()
                                            e.stopPropagation()
                                            if (remixTarget?.videoId === attachment.videoId) {
                                              logDebug('[VideoRemix] Cancelled remix for video:', attachment.videoId)
                                              setRemixTarget(null)
                                            } else {
                                              const target = {
                                                videoId: attachment.videoId!,
                                                uri: attachment.uri,
                                                fileName: attachment.fileName,
                                              }
                                              logDebug('[VideoRemix] Selected video for remix:', target)
                                              setRemixTarget(target)
                                            }
                                          }}
                                        >
                                          {remixTarget?.videoId === attachment.videoId ? (
                                            <><X size={14} className="mr-1" /> Cancel</>
                                          ) : (
                                            <><Sparkles size={14} className="mr-1" /> Remix</>
                                          )}
                                        </Button>
                                      </div>
                                    )}
                                  </div>
                                </div>
                              )
                            }
                            
                            if (isImage) {
                              logDebug('[VideoRemix] Rendering as IMAGE:', attachment.fileName)
                              return (
                                <div key={`${message.id}-attachment-${attachmentIndex}`} className="relative flex flex-col gap-2">
                                  <a
                                    href={attachment.uri}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="block rounded-lg border border-border overflow-hidden"
                                  >
                                    <img
                                      src={attachment.uri}
                                      alt={attachment.fileName || "Image attachment"}
                                      className="w-full h-auto block rounded-lg"
                                      style={{ maxHeight: '500px', objectFit: 'contain', backgroundColor: '#f5f5f5' }}
                                    />
                                  </a>
                                  {/* Overlay buttons for refine and mask - top right corner */}
                                  {message.role === "assistant" && (
                                    <div className="absolute top-2 right-2 flex flex-col gap-1">
                                      {/* Refine button */}
                                      <Button
                                        variant={refineTarget?.imageUrl === attachment.uri ? "destructive" : "default"}
                                        size="sm"
                                        className={`shadow-lg ${
                                          refineTarget?.imageUrl === attachment.uri 
                                            ? '' 
                                            : 'bg-purple-500 hover:bg-purple-600 text-white'
                                        }`}
                                        title={refineTarget?.imageUrl === attachment.uri ? "Cancel refine" : "Refine this image"}
                                        onClick={(e) => {
                                          e.preventDefault()
                                          e.stopPropagation()
                                          if (refineTarget?.imageUrl === attachment.uri) {
                                            setRefineTarget(null)
                                            setMaskAttachment(null)
                                          } else {
                                            setRefineTarget({
                                              imageUrl: attachment.uri,
                                              imageMeta: attachment,
                                            })
                                            setMaskAttachment(null)
                                          }
                                        }}
                                      >
                                        {refineTarget?.imageUrl === attachment.uri ? (
                                          <><X size={14} className="mr-1" /> Cancel</>
                                        ) : (
                                          <><Sparkles size={14} className="mr-1" /> Refine</>
                                        )}
                                      </Button>
                                      {/* Paint mask button - only visible when refine is active */}
                                      {refineTarget?.imageUrl === attachment.uri && (
                                        <Button
                                          variant="default"
                                          size="icon"
                                          className="h-8 w-8 rounded-full shadow-lg bg-blue-500 hover:bg-blue-600 text-white"
                                          title={maskUploadInFlight ? "Saving mask…" : maskAttachment ? "Edit mask" : "Paint mask"}
                                          disabled={maskUploadInFlight}
                                          onClick={(e) => {
                                            e.preventDefault()
                                            e.stopPropagation()
                                            setMaskEditorSource({ uri: attachment.uri, meta: attachment })
                                            setMaskEditorOpen(true)
                                          }}
                                        >
                                          {maskUploadInFlight ? <Loader2 size={16} className="animate-spin" /> : <Paintbrush size={16} />}
                                        </Button>
                                      )}
                                    </div>
                                  )}
                                </div>
                              )
                            }

                            // Fallback: render as link (neither image nor video)
                            logDebug('[VideoRemix] Rendering as LINK (fallback):', {
                              fileName: attachment.fileName,
                              mediaType: attachment.mediaType,
                              uri: attachment.uri?.slice(-60)
                            })
                            return (
                              <a
                                key={`${message.id}-attachment-${attachmentIndex}`}
                                href={attachment.uri}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="block rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground hover:bg-muted/50 transition-colors"
                              >
                                {attachment.fileName || attachment.uri}
                              </a>
                            )
                          })}
                        </div>
                      )}
                      {/* Render images/videos loaded from conversation history (DataPart artifacts) */}
                      {message.images && message.images.length > 0 && (
                        <div className="flex flex-col gap-3 mb-3">
                          {message.images.filter((image) => {
                            // Skip document files — they should only appear as download links in text
                            const uriPath = (image.uri || "").split('?')[0].toLowerCase()
                            const isDocument = /\.(docx|pptx|xlsx|doc|ppt|xls|csv|tsv|pdf)$/.test(uriPath)
                            if (isDocument) {
                              logDebug('[VideoRemix] Skipping document in message.images:', image.fileName)
                            }
                            return !isDocument
                          }).map((image, imageIndex) => {
                            const isVideo = image.mimeType?.startsWith('video/') || image.uri.match(/\.(mp4|webm|mov)(\?|$)/i)
                            logDebug('[VideoRemix] Rendering message.images item:', {
                              index: imageIndex,
                              fileName: image.fileName,
                              mimeType: image.mimeType,
                              uri: image.uri?.slice(-60),
                              isVideo,
                              willRenderAs: isVideo ? 'VIDEO' : 'IMAGE'
                            })
                            return (
                              <div key={`${message.id}-image-${imageIndex}`} className="flex flex-col gap-2">
                                {isVideo ? (
                                  <video
                                    src={image.uri}
                                    controls
                                    className="w-full h-auto block rounded-lg border border-border"
                                    style={{ maxHeight: '500px', objectFit: 'contain', backgroundColor: '#000' }}
                                  >
                                    Your browser does not support the video tag.
                                  </video>
                                ) : (
                                  <a
                                    href={image.uri}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="block rounded-lg border border-border overflow-hidden"
                                  >
                                    <img
                                      src={image.uri}
                                      alt={image.fileName || "Generated image"}
                                      className="w-full h-auto block rounded-lg"
                                      style={{ maxHeight: '500px', objectFit: 'contain', backgroundColor: '#f5f5f5' }}
                                    />
                                  </a>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      )}
                      {message.content && message.content.trim().length > 0 && (
                        <div className="chat-message-content prose prose-sm max-w-none dark:prose-invert text-[13px]">
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            rehypePlugins={[rehypeHighlight]}
                            components={{
                              p: ({ children }) => <p className="mb-1.5 last:mb-0 leading-relaxed text-[13px]">{children}</p>,
                              strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
                              em: ({ children }) => <em className="italic">{children}</em>,
                              code: ({ node, inline, className, children, ...props }: any) => 
                                inline ? (
                                  <code className="bg-black/10 dark:bg-white/10 px-1.5 py-0.5 rounded text-[11px] font-mono" {...props}>
                                    {children}
                                  </code>
                                ) : (
                                  <code className="block bg-zinc-900 dark:bg-zinc-950 text-zinc-100 p-3 rounded-lg text-[11px] overflow-x-auto font-mono leading-relaxed" {...props}>
                                    {children}
                                  </code>
                                ),
                              pre: ({ children }) => <div className="my-2 rounded-lg overflow-hidden">{children}</div>,
                              ul: ({ children }) => <ul className="my-1.5 pl-4 space-y-0.5 list-disc marker:text-muted-foreground text-[13px]">{children}</ul>,
                              ol: ({ children }) => <ol className="my-1.5 pl-4 space-y-0.5 list-decimal marker:text-muted-foreground text-[13px]">{children}</ol>,
                              li: ({ children }) => <li className="leading-relaxed pl-0.5 text-[13px]">{children}</li>,
                              h1: ({ children }) => <h1 className="text-[15px] font-bold mt-3 mb-1.5 pb-1 border-b border-border text-foreground">{children}</h1>,
                              h2: ({ children }) => <h2 className="text-[14px] font-bold mt-3 mb-1.5 text-foreground">{children}</h2>,
                              h3: ({ children }) => <h3 className="text-[13px] font-semibold mt-2 mb-1 text-foreground">{children}</h3>,
                              h4: ({ children }) => <h4 className="text-[13px] font-medium mt-2 mb-1 text-muted-foreground">{children}</h4>,
                              blockquote: ({ children }) => (
                                <blockquote className="border-l-4 border-primary/30 bg-muted/30 pl-3 py-1.5 my-2 rounded-r italic text-[13px]">
                                  {children}
                                </blockquote>
                              ),
                              hr: () => <hr className="my-3 border-border" />,
                              table: ({ children }) => (
                                <div className="my-2 overflow-x-auto rounded-lg border border-border">
                                  <table className="w-full text-[13px]">{children}</table>
                                </div>
                              ),
                              thead: ({ children }) => <thead className="bg-muted/50">{children}</thead>,
                              tbody: ({ children }) => <tbody className="divide-y divide-border">{children}</tbody>,
                              tr: ({ children }) => <tr className="hover:bg-muted/30 transition-colors">{children}</tr>,
                              th: ({ children }) => <th className="px-2 py-1.5 text-left font-semibold text-foreground text-[13px]">{children}</th>,
                              td: ({ children }) => <td className="px-2 py-1.5 text-muted-foreground text-[13px]">{children}</td>,
                              a: ({ children, href }) => (
                                <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-2 hover:text-primary/80">
                                  {children}
                                </a>
                              ),
                            }}
                          >
                            {message.content || ""}
                          </ReactMarkdown>
                        </div>
                      )}
                    </div>
                    {message.role === "user" && (() => {
                      // Use message.userColor if available (from API), otherwise fall back to currentUser.color
                      const avatarColor = message.userColor || currentUser?.color
                      const { bgColor, iconColor } = getAvatarStyles(avatarColor)
                      return (
                        <div 
                          className="h-8 w-8 flex-shrink-0 rounded-lg flex items-center justify-center"
                          style={{ backgroundColor: bgColor }}
                        >
                          <User size={16} style={{ color: iconColor }} />
                        </div>
                      )
                    })()}
                  </div>
                  
                  {/* Message reactions - show existing reactions only in collaborative sessions */}
                  {isInCollaborativeSession && message.reactions && message.reactions.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1 items-center">
                      {message.reactions.map((reaction, idx) => {
                        const hasCurrentUserReacted = currentUser && reaction.users.includes(currentUser.user_id)
                        return (
                          <button
                            key={`${message.id}-reaction-${idx}`}
                            onClick={() => handleReaction(message.id, reaction.emoji)}
                            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-sm transition-all hover:scale-105 ${
                              hasCurrentUserReacted
                                ? 'bg-blue-100 dark:bg-blue-900 border border-blue-300 dark:border-blue-700'
                                : 'bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 hover:bg-gray-200 dark:hover:bg-gray-700'
                            }`}
                            title={reaction.usernames.join(', ')}
                          >
                            <span>{reaction.emoji}</span>
                            <span className="text-xs text-muted-foreground font-medium">{reaction.users.length}</span>
                          </button>
                        )
                      })}
                    </div>
                  )}
                  
                    {message.role === "assistant" && (
                      <div className="flex items-center justify-between mt-2 w-full">
                        <p className="text-xs text-muted-foreground">{message.agent || 'Assistant'}</p>
                        <div className="flex items-center gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 p-0"
                            onClick={() => {
                              // Copy message content or image URI to clipboard
                              if (message.attachments && message.attachments.length > 0) {
                                // For images, copy the first image URI
                                const imageAttachment = message.attachments.find(att => 
                                  (att.mediaType || "").startsWith("image/")
                                )
                                if (imageAttachment) {
                                  navigator.clipboard.writeText(imageAttachment.uri)
                                }
                              } else if (message.content) {
                                navigator.clipboard.writeText(message.content)
                              }
                            }}
                            title="Copy to clipboard"
                          >
                            <Copy size={14} />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className={`h-7 w-7 p-0 ${messageFeedback[message.id] === 'up' ? 'text-yellow-500 hover:text-yellow-600' : ''}`}
                            onClick={() => {
                              setMessageFeedback(prev => ({
                                ...prev,
                                [message.id]: prev[message.id] === 'up' ? null : 'up'
                              }))
                            }}
                            title="Good response"
                          >
                            <ThumbsUp size={14} />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className={`h-7 w-7 p-0 ${messageFeedback[message.id] === 'down' ? 'text-yellow-500 hover:text-yellow-600' : ''}`}
                            onClick={() => {
                              setMessageFeedback(prev => ({
                                ...prev,
                                [message.id]: prev[message.id] === 'down' ? null : 'down'
                              }))
                            }}
                            title="Bad response"
                          >
                            <ThumbsDown size={14} />
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
            
            {/* Workflow steps display - shows current agent activity - BEFORE streaming message */}
            {isInferencing && <InferenceSteps steps={inferenceSteps} isInferencing={true} plan={workflowPlan} agentColors={agentColors} />}
            
            {/* Render streaming message separately AFTER workflow but treat it as a message */}
            {streamingMessageId && messages.find(m => m.id === streamingMessageId) && (() => {
              const streamingMsg = messages.find(m => m.id === streamingMessageId)!
              return (
                <div className="flex gap-3 items-start">
                  <div className="h-8 w-8 flex-shrink-0 bg-blue-500/10 rounded-lg flex items-center justify-center">
                    <Bot size={16} className="text-blue-500" />
                  </div>
                  <div className="flex flex-col items-start flex-1">
                    <div className="rounded-lg p-3 bg-muted w-full">
                      <div className="chat-message-content prose prose-sm max-w-none dark:prose-invert text-[13px]">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          rehypePlugins={[rehypeHighlight]}
                          components={{
                            p: ({ children }) => <p className="mb-1.5 last:mb-0 leading-relaxed text-[13px]">{children}</p>,
                            strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
                            em: ({ children }) => <em className="italic">{children}</em>,
                            code: ({ node, inline, className, children, ...props }: any) => 
                              inline ? (
                                <code className="bg-black/10 dark:bg-white/10 px-1.5 py-0.5 rounded text-[11px] font-mono" {...props}>
                                  {children}
                                </code>
                              ) : (
                                <code className="block bg-zinc-900 dark:bg-zinc-950 text-zinc-100 p-3 rounded-lg text-[11px] overflow-x-auto font-mono leading-relaxed" {...props}>
                                  {children}
                                </code>
                              ),
                            pre: ({ children }) => <div className="my-2 rounded-lg overflow-hidden">{children}</div>,
                            ul: ({ children }) => <ul className="my-1.5 pl-4 space-y-0.5 list-disc marker:text-muted-foreground text-[13px]">{children}</ul>,
                            ol: ({ children }) => <ol className="my-1.5 pl-4 space-y-0.5 list-decimal marker:text-muted-foreground text-[13px]">{children}</ol>,
                            li: ({ children }) => <li className="leading-relaxed pl-0.5 text-[13px]">{children}</li>,
                            h1: ({ children }) => <h1 className="text-[15px] font-bold mt-3 mb-1.5 pb-1 border-b border-border text-foreground">{children}</h1>,
                            h2: ({ children }) => <h2 className="text-[14px] font-bold mt-3 mb-1.5 text-foreground">{children}</h2>,
                            h3: ({ children }) => <h3 className="text-[13px] font-semibold mt-2 mb-1 text-foreground">{children}</h3>,
                            h4: ({ children }) => <h4 className="text-[13px] font-medium mt-2 mb-1 text-muted-foreground">{children}</h4>,
                            blockquote: ({ children }) => (
                              <blockquote className="border-l-4 border-primary/30 bg-muted/30 pl-3 py-1.5 my-2 rounded-r italic text-[13px]">
                                {children}
                              </blockquote>
                            ),
                            hr: () => <hr className="my-3 border-border" />,
                            table: ({ children }) => (
                              <div className="my-2 overflow-x-auto rounded-lg border border-border">
                                <table className="w-full text-[13px]">{children}</table>
                              </div>
                            ),
                            thead: ({ children }) => <thead className="bg-muted/50">{children}</thead>,
                            tbody: ({ children }) => <tbody className="divide-y divide-border">{children}</tbody>,
                            tr: ({ children }) => <tr className="hover:bg-muted/30 transition-colors">{children}</tr>,
                            th: ({ children }) => <th className="px-2 py-1.5 text-left font-semibold text-foreground text-[13px]">{children}</th>,
                            td: ({ children }) => <td className="px-2 py-1.5 text-muted-foreground text-[13px]">{children}</td>,
                            a: ({ children, href }) => (
                              <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-2 hover:text-primary/80">
                                {children}
                              </a>
                            ),
                          }}
                        >
                          {streamingMsg.content || ""}
                        </ReactMarkdown>
                        <span className="inline-block w-1.5 h-3.5 bg-blue-600 animate-pulse ml-1" />
                      </div>
                    </div>
                  </div>
                </div>
              )
            })()}
          </div>
        </div>
      </div>
          <div className="flex-shrink-0">
            {/* Chat input area will be rendered below */}
          </div>
        </>
      )}
      
      {/* Loading state - take up space to keep input at bottom */}
      {isLoadingMessages && messages.length === 0 && !isInferencing && (
        <div className="flex-1" />
      )}
      
      {/* Layout for empty state - welcome message positioned above centered input */}
      {!isLoadingMessages && messages.length === 0 && !isInferencing && (
        <div className="flex-1 flex items-center justify-center">
          <div className="absolute top-[40%] left-0 right-0 text-center px-4">
            <TypingWelcomeMessage text="What can I help you with today?" />
          </div>
        </div>
      )}
      
      {/* Chat input area - positioned based on state */}
      <div className={`${!isLoadingMessages && messages.length === 0 && !isInferencing ? 'absolute top-[48%] left-0 right-0 flex justify-center px-4' : 'flex-shrink-0'}`}>
        <div className={`pb-4 pt-2 ${!isLoadingMessages && messages.length === 0 && !isInferencing ? 'w-full max-w-2xl' : 'w-full px-4'}`}>
          {/* File upload previews */}
          {uploadedFiles.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-2">
              {uploadedFiles.map((file, index) => {
                const getFileIcon = (filename: string, contentType: string = '') => {
                  const ext = filename.toLowerCase().split('.').pop() || ''
                  const type = contentType.toLowerCase()

                  if (type.startsWith('image/') || ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'].includes(ext)) {
                    return '🖼️'
                  } else if (type.startsWith('audio/') || ['mp3', 'wav', 'm4a', 'flac', 'aac'].includes(ext)) {
                    return '🎵'
                  } else if (type.startsWith('video/') || ['mp4', 'mov', 'avi', 'mkv', 'webm'].includes(ext)) {
                    return '🎥'
                  } else if (type === 'application/pdf' || ext === 'pdf') {
                    return '📄'
                  } else if (['doc', 'docx'].includes(ext)) {
                    return '📝'
                  } else if (['xls', 'xlsx'].includes(ext)) {
                    return '📊'
                  } else if (['ppt', 'pptx'].includes(ext)) {
                    return '📽️'
                  } else if (['txt', 'md'].includes(ext)) {
                    return '📋'
                  } else if (['zip', 'rar', '7z'].includes(ext)) {
                    return '📦'
                  } else {
                    return '📄'
                  }
                }

                const isImage = (file.content_type || '').startsWith('image/') ||
                  ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'].includes((file.filename || '').toLowerCase().split('.').pop() || '')

                return (
                  <div key={index} className={`relative group ${isImage ? 'w-20 h-20' : 'flex items-center gap-2 max-w-xs'} bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800 rounded-lg ${isImage ? 'p-1' : 'px-3 py-2'} text-sm`}>
                    {isImage ? (
                      <>
                        <img src={file.uri} alt={file.filename} className="w-full h-full object-cover rounded-md" />
                        <button
                          onClick={() => setUploadedFiles(prev => prev.filter((_, i) => i !== index))}
                          className="absolute -top-1.5 -right-1.5 bg-red-500 hover:bg-red-600 text-white rounded-full w-5 h-5 flex items-center justify-center text-xs opacity-0 group-hover:opacity-100 transition-opacity"
                          title="Remove image"
                        >
                          ×
                        </button>
                      </>
                    ) : (
                      <>
                        <div className="flex items-center gap-2 flex-1 min-w-0">
                          <span className="text-lg">{getFileIcon(file.filename, file.content_type)}</span>
                          <div className="flex flex-col min-w-0 flex-1">
                            <span className="truncate font-medium text-blue-900 dark:text-blue-100">{file.filename}</span>
                            <span className="text-xs text-blue-600 dark:text-blue-400">
                              {file.size ? `${(file.size / 1024).toFixed(1)} KB` : ''}
                            </span>
                          </div>
                        </div>
                        <button
                          onClick={() => setUploadedFiles(prev => prev.filter((_, i) => i !== index))}
                          className="text-blue-500 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 flex-shrink-0 w-5 h-5 flex items-center justify-center rounded-full hover:bg-blue-100 dark:hover:bg-blue-900/50"
                          title="Remove file"
                        >
                          ×
                        </button>
                      </>
                    )}
                  </div>
                )
              })}
            </div>
          )}
          {refineTarget && (
            <div className="mb-2 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              <span>Refining image: {refineTarget.imageMeta?.fileName || refineTarget.imageUrl}</span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setRefineTarget(null)}
              >
                Cancel
              </Button>
              {maskAttachment && (
                <Badge variant="outline" className="text-xs border-emerald-300 text-emerald-700 bg-emerald-100/70">
                  Mask attached: {maskAttachment.filename?.split("/").pop() || maskAttachment.filename}
                </Badge>
              )}
            </div>
          )}

          {/* Voice recording status */}
          {(voiceRecording.isRecording || voiceRecording.isProcessing) && (
            <div className="mb-2 flex items-center gap-2 bg-blue-50 border border-blue-200 rounded-lg px-3 py-2 text-sm">
              {voiceRecording.isRecording ? (
                <>
                  <div className="w-2 h-2 bg-red-500 rounded-full animate-pulse"></div>
                  <Mic size={14} className="text-red-600" />
                  <span className="text-blue-700">Recording... {voiceRecording.duration}s</span>
                  <span className="text-gray-500 text-xs ml-auto">Click mic to stop</span>
                </>
              ) : voiceRecording.isProcessing ? (
                <>
                  <div className="w-2 h-2 bg-blue-500 rounded-full animate-spin"></div>
                  <span className="text-blue-700">Processing voice message...</span>
                </>
              ) : null}
            </div>
          )}

          {/* Voice recording error */}
          {voiceRecording.error && (
            <div className="mb-2 flex items-center gap-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm">
              <span className="text-red-700">❌ {voiceRecording.error}</span>
              <button 
                onClick={voiceRecording.reset}
                className="text-red-500 hover:text-red-700 ml-auto"
              >
                ×
              </button>
            </div>
          )}
          
          {/* Typing indicator - show who's typing */}
          {typingUsers.size > 0 && (
            <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground animate-pulse">
              <span className="flex items-center gap-1">
                <span className="inline-flex gap-0.5">
                  <span className="w-1.5 h-1.5 bg-primary rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-1.5 h-1.5 bg-primary rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-1.5 h-1.5 bg-primary rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </span>
                <span className="ml-1">
                  {Array.from(typingUsers.values()).join(', ')} {typingUsers.size === 1 ? 'is' : 'are'} typing...
                </span>
              </span>
            </div>
          )}
          
          <div 
            className="relative max-w-4xl mx-auto"
            onMouseEnter={() => setIsInputHovered(true)}
            onMouseLeave={() => setIsInputHovered(false)}
          >
            {/* Container with Teams-like focus indicator at bottom */}
            <div className="relative bg-muted/30 rounded-3xl transition-all duration-200">
            <Textarea
              ref={textareaRef}
              value={input}
              onPaste={(e) => {
                const items = e.clipboardData?.items
                if (!items) return
                const imageFiles: File[] = []
                for (let i = 0; i < items.length; i++) {
                  if (items[i].type.startsWith('image/')) {
                    const file = items[i].getAsFile()
                    if (file) imageFiles.push(file)
                  }
                }
                if (imageFiles.length > 0) {
                  e.preventDefault()
                  uploadFiles(imageFiles)
                }
              }}
              onFocus={() => setIsInputFocused(true)}
              onBlur={() => {
                setIsInputFocused(false)
                // Send typing stopped when losing focus
                sendMessage({ type: "typing_indicator", is_typing: false })
              }}
              onChange={(e) => {
                const newValue = e.target.value
                setInput(newValue)
                
                // Send typing indicator (debounced - max once per second)
                const now = Date.now()
                if (newValue.length > 0 && now - lastTypingSentRef.current > 1000) {
                  sendMessage({ type: "typing_indicator", is_typing: true })
                  lastTypingSentRef.current = now
                }
                
                // Clear previous timeout and set new one to send "stopped typing"
                if (typingTimeoutRef.current) {
                  clearTimeout(typingTimeoutRef.current)
                }
                typingTimeoutRef.current = setTimeout(() => {
                  sendMessage({ type: "typing_indicator", is_typing: false })
                }, 2000)
                
                // Auto-resize textarea
                const target = e.target as HTMLTextAreaElement
                target.style.height = 'auto'
                target.style.height = `${Math.min(target.scrollHeight, 128)}px` // max 128px (max-h-32)
                
                // Detect @ mentions
                const cursorPos = target.selectionStart
                const textBeforeCursor = newValue.substring(0, cursorPos)
                const lastAtIndex = textBeforeCursor.lastIndexOf('@')
                
                if (lastAtIndex !== -1) {
                  const textAfterAt = textBeforeCursor.substring(lastAtIndex + 1)
                  // Show dropdown if @ is followed by word characters or empty
                  if (/^[\w\s]*$/.test(textAfterAt)) {
                    setMentionSearch(textAfterAt)
                    setMentionCursorPosition(lastAtIndex)
                    setShowMentionDropdown(true)
                    setSelectedMentionIndex(0)
                  } else {
                    setShowMentionDropdown(false)
                  }
                } else {
                  setShowMentionDropdown(false)
                }
              }}
              onKeyDown={(e) => {
                // Handle dropdown navigation
                if (showMentionDropdown && filteredMentions.length > 0) {
                  if (e.key === "ArrowDown") {
                    e.preventDefault()
                    setSelectedMentionIndex((prev) => 
                      prev < filteredMentions.length - 1 ? prev + 1 : prev
                    )
                  } else if (e.key === "ArrowUp") {
                    e.preventDefault()
                    setSelectedMentionIndex((prev) => (prev > 0 ? prev - 1 : 0))
                  } else if (e.key === "Tab" || (e.key === "Enter" && showMentionDropdown)) {
                    e.preventDefault()
                    const selected = filteredMentions[selectedMentionIndex]
                    if (selected) {
                      // Track if this is a user mention
                      if (selected.type === 'user') {
                        setMentionedUserNames(prev => new Set([...prev, selected.name]))
                      }
                      
                      // Insert mention
                      const beforeMention = input.substring(0, mentionCursorPosition)
                      const afterCursor = input.substring(textareaRef.current?.selectionStart || input.length)
                      const newText = `${beforeMention}@${selected.name} ${afterCursor}`
                      setInput(newText)
                      setShowMentionDropdown(false)
                      // Set cursor after mention
                      setTimeout(() => {
                        if (textareaRef.current) {
                          const newCursorPos = mentionCursorPosition + selected.name.length + 2
                          textareaRef.current.selectionStart = newCursorPos
                          textareaRef.current.selectionEnd = newCursorPos
                          textareaRef.current.focus()
                        }
                      }, 0)
                    }
                    return
                  } else if (e.key === "Escape") {
                    e.preventDefault()
                    setShowMentionDropdown(false)
                    return
                  }
                }
                
                // Normal enter to send
                if (e.key === "Enter" && !e.shiftKey && !showMentionDropdown) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              placeholder={isInferencing ? "Type to redirect workflow... (Enter to redirect)" : "Type your message... (Use @ to mention users or agents)"}
              className="pl-14 pr-32 min-h-12 max-h-32 resize-none overflow-y-auto border-none focus-visible:ring-0 focus-visible:ring-offset-0 bg-transparent rounded-3xl py-3"
              rows={1}
              style={{ height: '48px' }} // min-h-12 = 48px
            />
            
            {/* Mention Autocomplete Dropdown */}
            {showMentionDropdown && filteredMentions.length > 0 && (
              <div className="absolute bottom-full left-0 right-0 mb-2 bg-[#1a1a1a] border border-gray-700 rounded-lg shadow-lg max-h-60 overflow-y-auto z-50">
                {filteredMentions.map((item, index) => (
                  <div
                    key={item.id}
                    className="flex items-center gap-3 p-3 cursor-pointer hover:bg-gray-800 transition-colors"
                    onClick={() => {
                      // Track if this is a user mention
                      if (item.type === 'user') {
                        setMentionedUserNames(prev => new Set([...prev, item.name]))
                      }
                      
                      const beforeMention = input.substring(0, mentionCursorPosition)
                      const afterCursor = input.substring(textareaRef.current?.selectionStart || input.length)
                      const newText = `${beforeMention}@${item.name} ${afterCursor}`
                      setInput(newText)
                      setShowMentionDropdown(false)
                      setTimeout(() => {
                        textareaRef.current?.focus()
                      }, 0)
                    }}
                  >
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      {item.type === 'agent' ? (
                        <Bot size={18} className="flex-shrink-0 text-blue-500" />
                      ) : (
                        <div 
                          className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0"
                          style={{ backgroundColor: item.color + '33' }}
                        >
                          <User size={14} style={{ color: item.color }} />
                        </div>
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="font-medium text-sm truncate">{item.name}</div>
                        <div className="text-xs text-muted-foreground truncate">{item.description}</div>
                      </div>
                      <Badge variant={item.type === 'agent' ? 'default' : 'secondary'} className="text-xs">
                        {item.type}
                      </Badge>
                    </div>
                  </div>
                ))}
              </div>
            )}
            
            {/* Left side - Attachment button */}
            <div className="absolute top-1/2 left-3 -translate-y-1/2 flex items-center">
              <input
                ref={fileInputRef}
                type="file"
                onChange={handleFileUpload}
                className="hidden"
                accept="*/*"
                multiple
              />
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button 
                    variant="ghost" 
                    size="icon"
                    className="h-9 w-9 rounded-full bg-muted hover:bg-primary/20"
                    disabled={isInferencing}
                    onClick={handlePaperclipClick}
                  >
                    <Plus size={20} className="text-foreground" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="top">Attach files</TooltipContent>
              </Tooltip>
            </div>
            
            {/* Right side - Action buttons */}
            <div className="absolute top-1/2 right-2 -translate-y-1/2 flex items-center gap-1">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button 
                    variant="ghost" 
                    size="icon"
                    className={`h-9 w-9 rounded-full ${voiceRecording.isRecording ? 'bg-red-100 text-red-600 hover:bg-red-200' : 'hover:bg-primary/20'}`}
                    disabled={isInferencing || voiceRecording.isProcessing}
                    onClick={handleMicClick}
                  >
                    {voiceRecording.isRecording ? <MicOff size={20} className="text-muted-foreground" /> : <Mic size={20} className="text-muted-foreground" />}
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="top">
                  {voiceRecording.isRecording ? 
                    `Recording... ${voiceRecording.duration}s` : 
                    voiceRecording.isProcessing ? 'Processing...' : 'Record voice message'
                  }
                </TooltipContent>
              </Tooltip>
              <VoiceButton 
                sessionId={currentSessionId} 
                contextId={contextId} 
                conversationId={conversationId}
                onEnsureConversation={ensureConversation}
                onFirstMessage={(convId, transcript) => {
                  // Update title based on first voice message, same as text messages
                  const newTitle = generateTitleFromMessage(transcript);
                  updateConversationTitle(convId, newTitle);
                  // Broadcast title update to collaborative session members
                  sendMessage({
                    type: "conversation_title_update",
                    conversationId: convId,
                    title: newTitle
                  });
                }}
                disabled={isInferencing} 
              />
              {/* Three-state button: Redirect (⚡) / Stop (■) / Send (→) */}
              {isInferencing && input.trim() ? (
                <Button 
                  onClick={handleInterrupt}
                  className="h-9 w-9 rounded-full bg-amber-500 hover:bg-amber-600"
                  size="icon"
                  title="Redirect workflow"
                >
                  <Zap size={16} className="text-white fill-white" />
                </Button>
              ) : isInferencing ? (
                <Button 
                  onClick={handleStop}
                  className="h-9 w-9 rounded-full bg-red-500 hover:bg-red-600"
                  size="icon"
                  title="Stop workflow"
                >
                  <Square size={16} className="text-white fill-white" />
                </Button>
              ) : (
                <Button 
                  onClick={handleSend} 
                  disabled={!input.trim() && !refineTarget}
                  className="h-9 w-9 rounded-full bg-primary hover:bg-primary/90 disabled:bg-muted disabled:text-muted-foreground"
                  size="icon"
                >
                  <Send size={18} className="text-primary-foreground" />
                </Button>
              )}
            </div>
            </div>
            {/* Blue highlight bar at bottom - visible on hover, focus, or inferencing */}
            <div 
              className={`mx-4 h-[3px] rounded-full transition-all duration-300 pointer-events-none mt-0.5 ${
                (isInferencing && inferenceSteps.length > 0)
                  ? 'opacity-100 animate-gradient-flow' 
                  : (isInputFocused || isInputHovered)
                  ? 'opacity-100' 
                  : 'opacity-0'
              }`}
              style={{
                backgroundImage: (isInputFocused || isInputHovered || (isInferencing && inferenceSteps.length > 0))
                  ? 'linear-gradient(90deg, hsl(var(--primary)), hsl(270, 80%, 60%), hsl(var(--primary)))' 
                  : 'none',
                backgroundSize: (isInferencing && inferenceSteps.length > 0) ? '200% 100%' : '100% 100%',
                backgroundPosition: '0% 50%'
              }}
            />
          </div>
          
          {/* Helper text below input */}
          <div className="text-center mt-1">
            <p className="text-sm text-foreground">
              Use the Agent Catalog to add agents to your team
            </p>
          </div>
        </div>
      </div>
      {maskEditorSource && refineTarget && (
        <MaskEditorDialog
          open={maskEditorOpen}
          imageUrl={maskEditorSource.uri}
          onClose={() => setMaskEditorOpen(false)}
          onSave={async (blob) => {
            if (!blob) return
            setMaskUploadInFlight(true)
            try {
              // Get session ID for tenant isolation
              const sessionId = getOrCreateSessionId()
              
              const formData = new FormData()
              const filename = `${(refineTarget.imageMeta?.fileName || "mask")?.replace(/\.[^.]+$/, "")}-mask.png`
              const maskFile = new File([blob], filename, { type: "image/png" })
              formData.append('file', maskFile)

              const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
              const response = await fetch(`${baseUrl}/upload`, {
                method: 'POST',
                headers: {
                  'X-Session-ID': sessionId
                },
                body: formData
              })
              const result = await response.json()
              if (result.success) {
                const uploadedMask = {
                  ...result,
                  filename,
                  content_type: 'image/png',
                }
                setMaskAttachment(uploadedMask)
              } else {
                console.error('Mask upload failed:', result.error)
              }
            } catch (error) {
              console.error('Mask upload error:', error)
            } finally {
              setMaskUploadInFlight(false)
            }
          }}
        />
      )}
    </div>
    </TooltipProvider>
  )
}
