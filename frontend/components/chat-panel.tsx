"use client"

import { useState, useEffect, useRef, useCallback, useMemo } from "react"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { Paperclip, Mic, MicOff, Send, Bot, User, Paintbrush, Copy, ThumbsUp, ThumbsDown, Loader2, Phone, PhoneOff, Plus } from "lucide-react"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useEventHub } from "@/hooks/use-event-hub"
import { useVoiceRecording } from "@/hooks/use-voice-recording"
import { useVoiceLive } from "@/hooks/use-voice-live"
import { getScenarioById } from "@/lib/voice-scenarios"
import { InferenceSteps } from "./inference-steps"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeHighlight from "rehype-highlight"
import { useSearchParams, useRouter } from "next/navigation"
import { getConversation, updateConversationTitle, createConversation, notifyConversationCreated, type Message as APIMessage } from "@/lib/conversation-api"
import { createContextId, getOrCreateSessionId } from "@/lib/session"

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

type Message = {
  id: string
  role: "user" | "assistant" | "system"
  content?: string
  agent?: string
  type?: "inference_summary"
  steps?: { agent: string; status: string; imageUrl?: string; imageName?: string }[]
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
  }[]
  // Images from DataPart artifacts (loaded from conversation history)
  images?: {
    uri: string
    fileName?: string
  }[]
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
      console.log(`✏️ Drawing on canvas: mode=${mode}, brush=${brushSize}px, point=(${Math.round(point.x)},${Math.round(point.y)})`)
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
      console.warn("Pointer capture failed", err)
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
    
    console.log(`🎨 Mask creation: ${drawnPixelCount} drawn pixels found (canvas size: ${overlay.width}x${overlay.height})`)
    if (drawnPixelCount === 0) {
      console.warn('⚠️ No drawn pixels found! Mask will be completely white.')
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
  registeredAgents?: any[]
  connectedUsers?: any[]
  activeNode?: string | null
  setActiveNode?: (node: string | null) => void
}

export function ChatPanel({ dagNodes, dagLinks, enableInterAgentMemory, workflow, registeredAgents = [], connectedUsers = [], activeNode: externalActiveNode, setActiveNode: externalSetActiveNode }: ChatPanelProps) {
  const DEBUG = process.env.NEXT_PUBLIC_DEBUG_LOGS === 'true'
  // Use the shared Event Hub hook so we subscribe to the same client as the rest of the app
  const { subscribe, unsubscribe, emit, sendMessage, isConnected } = useEventHub()
  
  // Get conversation ID from URL parameters (needed for hooks)
  const searchParams = useSearchParams()
  const router = useRouter()
  const conversationId = searchParams.get('conversationId') || 'frontend-chat-context'
  
  // Create tenant-aware contextId for A2A protocol
  // Format: sessionId::conversationId - enables multi-tenant isolation
  const contextId = useMemo(() => createContextId(conversationId), [conversationId])
  
  // Voice recording hook
  const voiceRecording = useVoiceRecording()
  
  // Track Voice Live call IDs for response injection
  const voiceLiveCallMapRef = useRef<Map<string, string>>(new Map()) // messageId -> call_id
  
  // Use refs to always get the latest values (avoid stale closure)
  const workflowRef = useRef(workflow)
  const enableInterAgentMemoryRef = useRef(enableInterAgentMemory)
  
  useEffect(() => {
    workflowRef.current = workflow
  }, [workflow])
  
  useEffect(() => {
    enableInterAgentMemoryRef.current = enableInterAgentMemory
  }, [enableInterAgentMemory])
  
  // Voice Live hook for realtime voice conversations
  const voiceLive = useVoiceLive({
    foundryProjectUrl: process.env.NEXT_PUBLIC_AZURE_AI_FOUNDRY_PROJECT_ENDPOINT || '',
    model: process.env.NEXT_PUBLIC_VOICE_MODEL || 'gpt-realtime',
    scenario: getScenarioById('host-agent-chat'),
    onSendToA2A: async (message: string, metadata?: any) => {
      // Send message through the host agent via HTTP POST (same as handleSend)
      try {
        console.log('[Voice Live] Sending message to A2A network:', message)
        console.log('[Voice Live] Metadata:', metadata)
        
        // Get current values from refs (not stale closure values!)
        const currentWorkflow = workflowRef.current
        const currentEnableMemory = enableInterAgentMemoryRef.current
        
        console.log('[Voice Live] Current settings:', {
          workflow: currentWorkflow?.substring(0, 50),
          enableMemory: currentEnableMemory
        })
        
        const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
        const messageId = `voice_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
        
        // Store the mapping of messageId to Voice Live call_id
        if (metadata?.tool_call_id) {
          voiceLiveCallMapRef.current.set(messageId, metadata.tool_call_id)
          console.log('[Voice Live] Stored call mapping:', messageId, '->', metadata.tool_call_id)
        }
        
        const response = await fetch(`${baseUrl}/message/send`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            params: {
              messageId,
              contextId: contextId,  // Use tenant-aware contextId
              role: 'user',
              parts: [{ root: { kind: 'text', text: message } }],
              enableInterAgentMemory: currentEnableMemory,
              workflow: currentWorkflow ? currentWorkflow.trim() : undefined  // Backend auto-detects mode from workflow presence
            }
          })
        })

        if (!response.ok) {
          console.error('[Voice Live] Failed to send message to backend:', response.statusText)
          throw new Error(`Failed to send message: ${response.statusText}`)
        }

        console.log('[Voice Live] Message sent to backend successfully')
        return contextId  // Return tenant-aware contextId
      } catch (error) {
        console.error('[Voice Live] Error sending to A2A:', error)
        throw error
      }
    }
  })
  
  const [messages, setMessages] = useState<Message[]>([])
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null)  // Track which message is currently streaming
  const [isLoadingMessages, setIsLoadingMessages] = useState(true) // Add loading state
  const [input, setInput] = useState("")
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const [isInferencing, setIsInferencing] = useState(false)
  const [inferenceSteps, setInferenceSteps] = useState<{ agent: string; status: string; imageUrl?: string; imageName?: string }[]>([])
  const [localActiveNode, setLocalActiveNode] = useState<string | null>(null)
  // Use external activeNode if provided, otherwise use local state
  const activeNode = externalActiveNode !== undefined ? externalActiveNode : localActiveNode
  const setActiveNode = externalSetActiveNode || setLocalActiveNode
  const [processedMessageIds, setProcessedMessageIds] = useState<Set<string>>(new Set())
  const [uploadedFiles, setUploadedFiles] = useState<any[]>([])
  const [refineTarget, setRefineTarget] = useState<any | null>(null)
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

  // Clear uploaded files when connection is lost (backend restart)
  useEffect(() => {
    if (!isConnected && uploadedFiles.length > 0) {
      if (DEBUG) console.log('[ChatPanel] WebSocket disconnected, clearing uploaded files')
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

  // Also clear uploaded files on component mount (page refresh)
  useEffect(() => {
    if (DEBUG) console.log('[ChatPanel] Component mounted, clearing any stale uploaded files')
    setUploadedFiles([])
  }, []) // Empty dependency array = only run on mount

  // Track if we're in the process of creating a conversation to avoid race conditions
  const [isCreatingConversation, setIsCreatingConversation] = useState(false)

  // Reset messages when conversation ID changes (new chat)
  useEffect(() => {
    const loadConversationMessages = async () => {
    setIsLoadingMessages(true) // Start loading
    if (DEBUG) console.log('[ChatPanel] Conversation ID changed to:', conversationId)
    if (DEBUG) console.log('[ChatPanel] URL search params:', searchParams.toString())
      
      // Load messages for existing conversations (no auth required for message loading)
      if (conversationId && conversationId !== 'frontend-chat-context') {
        try {
          if (DEBUG) console.log("[ChatPanel] Loading conversation:", conversationId)
          const conversation = await getConversation(conversationId)
          
          if (conversation && conversation.messages) {
            const apiMessages = conversation.messages
            if (DEBUG) console.log("[ChatPanel] Retrieved", apiMessages.length, "messages for conversation", conversationId)
            
            if (apiMessages.length > 0) {
              if (DEBUG) console.log("[ChatPanel] First message sample:", apiMessages[0])
            }
            
            // Convert API messages to our format
            // A2A serializes Part objects flat: { kind: 'text', text: '...' } not { root: { kind: 'text', text: '...' } }
            if (DEBUG) console.log('[ChatPanel] Converting', apiMessages.length, 'API messages')
            const convertedMessages: Message[] = apiMessages.map((msg, index) => {
              // Extract text content from parts - handle A2A format
              let content = ''
              let images: { uri: string; fileName?: string }[] = []
              
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
                  // Handle DataPart with image artifacts
                  else if (part.kind === 'data' && part.data) {
                    const artifactUri = part.data['artifact-uri']
                    const fileName = part.data['file-name']
                    if (artifactUri) {
                      images.push({ uri: artifactUri, fileName })
                    }
                  }
                  // Nested DataPart format
                  else if (part.root?.kind === 'data' && part.root?.data) {
                    const artifactUri = part.root.data['artifact-uri']
                    const fileName = part.root.data['file-name']
                    if (artifactUri) {
                      images.push({ uri: artifactUri, fileName })
                    }
                  }
                }
              }
              
              return {
                id: msg.messageId || `api_msg_${index}`,
                role: (msg.role === 'user' || msg.role === 'assistant' || msg.role === 'agent') ? 
                      (msg.role === 'agent' ? 'assistant' : msg.role) : 'assistant',
                content: content,
                images: images.length > 0 ? images : undefined,
                agent: (msg.role === 'assistant' || msg.role === 'agent') ? 'Assistant' : undefined
              }
            })
            
            // Load stored workflows from localStorage and inject them
            try {
              const storageKey = `workflow_${conversationId}`
              const storedData = localStorage.getItem(storageKey)
              if (storedData) {
                const workflows = JSON.parse(storedData)
                // Insert workflows at appropriate positions (before assistant messages)
                const messagesWithWorkflows: Message[] = []
                let workflowIndex = 0
                
                for (let i = 0; i < convertedMessages.length; i++) {
                  const msg = convertedMessages[i]
                  
                  // Insert workflow before assistant responses
                  if (msg.role === 'assistant' && workflowIndex < workflows.length) {
                    const workflow = workflows[workflowIndex]
                    messagesWithWorkflows.push({
                      id: workflow.id,
                      role: 'system',
                      type: 'inference_summary',
                      steps: workflow.steps
                    })
                    workflowIndex++
                  }
                  messagesWithWorkflows.push(msg)
                }
                
                setMessages(messagesWithWorkflows.filter(m => m.content || m.images?.length || m.type === 'inference_summary'))
              } else {
                setMessages(convertedMessages.filter(m => m.content || m.images?.length))
              }
            } catch (err) {
              console.error('[ChatPanel] Failed to load workflows from localStorage:', err)
              setMessages(convertedMessages.filter(m => m.content || m.images?.length))
            }
            
            if (DEBUG) console.log("[ChatPanel] Converted messages:", convertedMessages.length)
            
            if (convertedMessages.length === 0) {
              // If no messages found, show empty chat (ChatGPT-like)
              if (DEBUG) console.log("[ChatPanel] No messages found, showing empty chat")
              setMessages([])
            }
          } else {
            if (DEBUG) console.log("[ChatPanel] No conversation found or no messages")
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
        if (DEBUG) console.log("[ChatPanel] Using default conversation - showing empty chat")
        setMessages([])
      }
      
      // Only reset inference state if we're not actively inferencing
      // This prevents clearing live workflow updates when conversation reloads
      if (!isInferencing) {
        setIsInferencing(false)
        setInferenceSteps([])
        setProcessedMessageIds(new Set())
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
      console.log("[ChatPanel] Task update received (for agent registration only):", data)
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
      console.log("[ChatPanel] System event received:", data)
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
      console.log("[ChatPanel] Task created:", data)
      if (data.taskId) {
        emit("status_update", {
          inferenceId: data.taskId,
          agent: data.agentName || "System",
          status: "starting new task"
        })
      }
    }

    // Handle agent registration events
    const handleAgentRegistered = (data: any) => {
      console.log("[ChatPanel] Agent registered:", data)
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
      console.log("[ChatPanel] Message sent:", data)
      
      // If this is a user message (from workflow designer reply), add it to messages
      if (data.role === "user" && data.content) {
        console.log("[ChatPanel] Adding user message from workflow:", data.content?.substring(0, 50))
        const newMessage: Message = {
          id: data.messageId || `user_${Date.now()}`,
          role: "user",
          content: data.content
        }
        setMessages(prev => {
          // Avoid duplicates
          if (prev.some(m => m.content === data.content && m.role === "user")) {
            console.log("[ChatPanel] Skipping duplicate user message")
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
      console.log("[ChatPanel] Message received from thread:", data)
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
      console.log("[ChatPanel] Message received:", data)
      console.log("[ChatPanel] Current messages count:", messages.length)
      
      // A2A MessageEventData has: messageId, conversationId, role, content[], direction
      if (data.messageId && data.content && data.content.length > 0) {
        // Only process assistant messages to avoid duplicating user messages
        if (data.role === "assistant" || data.role === "system") {
          const textContent = data.content.find((c: any) => c.type === "text")?.content || ""
          const imageContents = data.content.filter((c: any) => c.type === "image")
          console.log("[ChatPanel] Image parts count:", imageContents.length)
          // Disable markdown URL extraction - images should come from file_uploaded events with proper SAS tokens
          // Extracting URLs from text can result in URLs without access tokens
          const derivedImageAttachments = [] as any[]
          // const markdownUrlRegex = /\[[^\]]*\]\((https?:\/\/[^)]+)\)|(https?:\/\/[^\s]+\.(?:png|jpe?g|gif|webp)(?:\?[^\s)]+)?)/gi
          // let match: RegExpExecArray | null
          // while ((match = markdownUrlRegex.exec(textContent)) !== null) {
          //   const url = (match[1] || match[2] || "").trim()
          //   if (!url) continue
          //   const extension = url.split('?')[0].toLowerCase().split('.').pop()
          //   if (!extension || !["png", "jpg", "jpeg", "gif", "webp"].includes(extension)) {
          //     continue
          //   }
          //   const uriWithToken = url
          //   derivedImageAttachments.push({
          //     uri: uriWithToken,
          //     mediaType: `image/${extension === "jpg" ? "jpeg" : extension}`,
          //     fileName: url.split("/").pop() || `image.${extension}`,
          //   })
          // }
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
          const allImageAttachments = [...imageContents, ...filteredDerived]
          if (allImageAttachments.length > 0) {
            const attachmentId = `${data.messageId}_attachments`
            if (!processedMessageIds.has(attachmentId)) {
              setProcessedMessageIds(prev => new Set([...prev, attachmentId]))
              const attachmentMessage: Message = {
                id: attachmentId,
                role: "assistant",
                agent: agentName,
                attachments: allImageAttachments.map((img: any) => ({
                  uri: img.uri,
                  fileName: img.fileName,
                  fileSize: img.fileSize,
                  storageType: img.storageType,
                  mediaType: img.mediaType || "image/png",
                })),
              }
              console.log("[ChatPanel] Adding attachment message:", attachmentMessage)
              setMessages(prev => [...prev, attachmentMessage])
              
              // Broadcast attachment message to other users so they can see images
              sendMessage({
                type: "shared_message",
                message: attachmentMessage
              })
            } else {
              console.log("[ChatPanel] Attachment message already processed, skipping:", attachmentId)
            }
          }
          
          console.log("[ChatPanel] Processing assistant message:", {
            messageId: data.messageId,
            content: textContent.slice(0, 50) + "...",
            role: data.role,
            agentName: agentName
          })
          
          // Remove streaming message when complete message arrives
          const streamingId = `streaming_${data.contextId || data.conversationId}`
          setMessages(prev => prev.filter(msg => msg.id !== streamingId))
          setStreamingMessageId(null)
          
          // Emit final_response for internal processing - this is converted from message event
          emit("final_response", {
            inferenceId: data.conversationId || data.messageId,
            conversationId: data.conversationId || data.contextId,
            messageId: data.messageId, // Pass through the backend's unique messageId
            message: {
              role: data.role === "user" ? "user" : "assistant",
              content: textContent,
              agent: agentName,
              attachments: [],
            },
          })
        } else {
          console.log("[ChatPanel] Skipping user message echo from backend:", data)
        }
      }
    }

    // Handle streaming message chunks (Responses API real-time streaming)
    const handleMessageChunk = (data: any) => {
      console.log("[ChatPanel] 📡 Message chunk received:", data)
      
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
      console.log("[ChatPanel] Shared message received:", data)
      
      if (data.message) {
        const newMessage: Message = {
          id: data.message.id,
          role: data.message.role,
          content: data.message.content,
          username: data.message.username,
          userColor: data.message.userColor,
          agent: data.message.agent,
          attachments: data.message.attachments // Include attachments (images, files)
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
      console.log("[ChatPanel] Shared inference started:", data)
      setIsInferencing(true)
      setInferenceSteps([])
      setActiveNode("User Input")
    }

    const handleSharedInferenceEnded = (data: any) => {
      console.log("[ChatPanel] Shared inference ended:", data)
      setIsInferencing(false)
      setInferenceSteps([])
      setActiveNode(null)
    }

    // Handle conversation events
    const handleConversationCreated = (data: any) => {
      console.log("[ChatPanel] Conversation created:", data)
      // A2A ConversationCreatedEventData has: conversationId, conversationName, isActive, messageCount
      if (data.conversationId) {
        // Start inference tracking for new conversations
        setIsInferencing(true)
        setInferenceSteps([])
        emit("status_update", {
          inferenceId: data.conversationId,
          agent: "System",
          status: "new conversation created"
        })
      }
    }

    // Handle outgoing agent message (Host Agent -> Remote Agent)
    const handleOutgoingAgentMessage = (data: any) => {
      console.log("[ChatPanel] 📤 Outgoing agent message received:", data)
      console.log("[ChatPanel] 📤 Message content:", data.message)
      console.log("[ChatPanel] 📤 Voice Live connected?", voiceLive.isConnected)
      console.log("[ChatPanel] 📤 Pending calls in map:", voiceLiveCallMapRef.current.size)
      
      // If Voice Live is connected and has a pending call, inject the outgoing message
      if (!voiceLive.isConnected) {
        console.log('[Voice Live] ⚠️ Not connected, skipping outgoing message injection')
        return
      }
      
      if (!data.message) {
        console.log('[Voice Live] ⚠️ No message in event data, skipping injection')
        return
      }
      
      if (voiceLiveCallMapRef.current.size === 0) {
        console.log('[Voice Live] ⚠️ No pending calls in map, skipping injection')
        return
      }
      
      // Get the most recent call_id (FIFO - first in, first out)
      const voiceCallIds = Array.from(voiceLiveCallMapRef.current.entries())
      console.log('[Voice Live] 📤 Injecting outgoing message for call:', voiceCallIds[0])
      
      if (voiceCallIds.length > 0) {
        const [messageId, callId] = voiceCallIds[0]
        
        console.log('[Voice Live] 📤 Injecting to call_id:', callId)
        console.log('[Voice Live] 📤 Message to inject:', data.message)
        
        // Inject the outgoing message so Voice Live speaks it
        voiceLive.injectNetworkResponse({
          call_id: callId,
          message: data.message,
          status: 'in_progress'  // Mark as in_progress, not completed yet
        })
        
        console.log('[Voice Live] ✅ Outgoing message injected successfully')
      }
    }

    // Subscribe to real Event Hub events from A2A backend
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
    subscribe("file_uploaded", handleFileUploaded)
    subscribe("outgoing_agent_message", handleOutgoingAgentMessage)

    return () => {
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
      unsubscribe("file_uploaded", handleFileUploaded)
      unsubscribe("outgoing_agent_message", handleOutgoingAgentMessage)
    }
  }, [subscribe, unsubscribe, emit, sendMessage, processedMessageIds, voiceLive])

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

  // Handle inference step events (tool calls, remote agent activities)
    const handleInferenceStep = (data: any) => {
      console.log("[ChatPanel] Inference step received:", data)
      if (data.agent && data.status) {
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
        
        // Also emit as status update for compatibility
        // eventHub.emit("status_update", {
        //   inferenceId: data.conversationId || `inf_${Date.now()}`,
        //   agent: data.agent,
        //   status: data.status
        // })
      }
    }

    // Handle tool call events
    const handleToolCall = (data: any) => {
      console.log("[ChatPanel] Tool call received:", data)
      if (data.toolName && data.agentName) {
        const status = `🛠️ Calling ${data.toolName}`
        setInferenceSteps(prev => [...prev, { 
          agent: data.agentName, 
          status: status 
        }])
      }
    }

    // Handle tool response events
    // DISABLED: task_updated is the single source of truth, this was causing duplicate status messages
    const handleToolResponse = (data: any) => {
      console.log("[ChatPanel] Tool response received (ignored - using task_updated instead):", data)
      // Commenting out to avoid duplicate messages with task_updated
      // if (data.toolName && data.agentName) {
      //   const status = data.status === "success" 
      //     ? `✅ ${data.toolName} completed`
      //     : `❌ ${data.toolName} failed`
      //   setInferenceSteps(prev => [...prev, { 
      //     agent: data.agentName, 
      //     status: status 
      //   }])
      // }
    }

    // Handle remote agent activity events
    // THIS is the single source for workflow display messages
    const handleRemoteAgentActivity = (data: any) => {
      console.log("[ChatPanel] Remote agent activity received:", data)
      if (data.agentName && data.content) {
        const content = data.content
        
        // Filter out noisy intermediate updates that shouldn't show in workflow
        // These are streaming progress indicators, not meaningful status updates
        // KEEP: status transitions (submitted, working, completed) - these are important
        // FILTER: repeated "Generating response..." progress updates
        const isNoisyUpdate = content === "task started" ||
                             content === "processing" ||
                             content === "processing request" ||
                             content === "generating artifact" ||
                             // Filter repetitive progress indicators with char counts
                             (content.includes("🤖 Generating response...") && content.includes("chars")) ||
                             (content.includes("🧠 Processing request..."))
        
        // Skip updates from host agent that are just tool management noise
        // These are internal implementation details, not meaningful user-facing updates
        const isHostToolNoise = data.agentName === "foundry-host-agent" && (
          content.includes("executing tools") ||
          content.includes("tool execution completed") ||
          content.includes("AI processing completed") ||
          content.includes("creating AI response") ||
          content.includes("AI response created") ||
          content.includes("finalizing response") ||
          content.startsWith("🛠️ Calling tool:") ||
          content.startsWith("✅ Tool ")
        )
        
        if (isNoisyUpdate || isHostToolNoise) {
          console.log("[ChatPanel] Skipping noisy remote activity:", content.substring(0, 50))
          return
        }
        
        // Deduplicate: check if we already have this exact message from this agent
        setInferenceSteps(prev => {
          // Check last 5 entries for duplicates
          const recentEntries = prev.slice(-5)
          const isDuplicate = recentEntries.some(
            entry => entry.agent === data.agentName && entry.status === content
          )
          
          if (isDuplicate) {
            console.log("[ChatPanel] Skipping duplicate remote activity:", content.substring(0, 50))
            return prev
          }
          
          return [...prev, { 
            agent: data.agentName, 
            status: content 
          }]
        })
      }
    }

    // Handle file uploaded events from agents
    const handleFileUploaded = (data: any) => {
      console.log("[ChatPanel] File uploaded from agent:", data)
      if (data?.fileInfo && data.fileInfo.source_agent) {
        const isImage = data.fileInfo.content_type?.startsWith('image/') || 
          ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'].includes(
            (data.fileInfo.filename || '').toLowerCase().split('.').pop() || ''
          )
        
        // Add to inference steps (with thumbnail for images, text for other files)
        setInferenceSteps(prev => [...prev, { 
          agent: data.fileInfo.source_agent, 
          status: `📎 Generated ${data.fileInfo.filename}`,
          imageUrl: isImage && data.fileInfo.uri ? data.fileInfo.uri : undefined,
          imageName: data.fileInfo.filename
        }])
      }
    }

  useEffect(() => {
    const handleStatusUpdate = (data: { inferenceId: string; agent: string; status: string }) => {
      console.log("[ChatPanel] Status update:", data)
      setInferenceSteps((prev) => [...prev, { agent: data.agent, status: data.status }])
      setActiveNode(data.agent)
    }

    const handleFinalResponse = (data: { inferenceId: string; message: Omit<Message, "id">; conversationId?: string; messageId?: string }) => {
      console.log("[ChatPanel] Final response received:", data)
      
      // Use messageId from backend if available, otherwise generate unique ID based on timestamp
      // Don't use content in the key since same content can be sent multiple times
      const responseId = data.messageId || `response_${data.inferenceId}_${Date.now()}`
      
      console.log("[ChatPanel] Response ID:", responseId)
      console.log("[ChatPanel] Already processed?", processedMessageIds.has(responseId))
      console.log("[ChatPanel] Current processed IDs:", Array.from(processedMessageIds))
      
      // Check if we've already processed this exact message
      if (processedMessageIds.has(responseId)) {
        console.log("[ChatPanel] Duplicate response detected, skipping:", responseId)
        return
      }
      
      // Mark this message as processed
      setProcessedMessageIds(prev => new Set([...prev, responseId]))
      
      // Only add messages if they have content
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
      console.log('[ChatPanel] Workflow save check:', {
        stepsCount: inferenceSteps.length,
        isHostAgent,
        agentName: data.message.agent,
        summaryId,
        inferenceId: data.inferenceId,
        effectiveConversationId
      })
      if (inferenceSteps.length > 0) {
        // Show workflow for ANY agent response when we have steps
        setProcessedMessageIds(prev => new Set([...prev, summaryId]))
        const stepsCopy = [...inferenceSteps] // Copy steps before they get cleared
        const summaryMessage: Message = {
          id: summaryId,
          role: "system",
          type: "inference_summary",
          steps: stepsCopy,
        }
        messagesToAdd.push(summaryMessage)
        
        // Persist workflow to localStorage so it survives page refresh
        // Store keyed by conversationId with the inference steps and associated message position
        try {
          const storageKey = `workflow_${effectiveConversationId}`
          const existingData = localStorage.getItem(storageKey)
          const workflows = existingData ? JSON.parse(existingData) : []
          workflows.push({
            id: summaryId,
            steps: stepsCopy,
            timestamp: Date.now()
          })
          localStorage.setItem(storageKey, JSON.stringify(workflows))
          console.log('[ChatPanel] Workflow persisted to:', storageKey)
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
      }

      // Check if this is a Voice Live response that needs to be injected back
      if (voiceLive.isConnected && isHostAgent && data.message.content) {
        // Check if any pending Voice Live calls exist
        const voiceCallIds = Array.from(voiceLiveCallMapRef.current.entries())
        console.log('[Voice Live] Checking for pending calls:', voiceCallIds)
        
        if (voiceCallIds.length > 0) {
          // Get the most recent call_id (FIFO - first in, first out)
          const [messageId, callId] = voiceCallIds[0]
          console.log('[Voice Live] Injecting response for call_id:', callId)
          
          voiceLive.injectNetworkResponse({
            call_id: callId,
            message: data.message.content,
            status: 'completed'
          })
          
          // Remove from map
          voiceLiveCallMapRef.current.delete(messageId)
          console.log('[Voice Live] Response injected successfully')
        }
      }

      // Add messages only if we have any
      if (messagesToAdd.length > 0) {
        setMessages((prev) => [...prev, ...messagesToAdd])
        
        // Broadcast messages to other users (but not inference summaries)
        messagesToAdd.forEach(msg => {
          if (msg.type !== 'inference_summary' && msg.role === 'assistant') {
            sendMessage({
              type: "shared_message",
              message: msg
            })
          }
        })
      }
      
      // Clear inference steps after final response (for any agent)
      // This ensures the workflow is captured before clearing
      if (messagesToAdd.length > 0) {
        setIsInferencing(false)
        setInferenceSteps([])
        setActiveNode(null)
      }

      // Broadcast inference ended to all other clients
      sendMessage({
        type: "shared_inference_ended",
        data: {
          conversationId: data.inferenceId,
          timestamp: new Date().toISOString()
        }
      })
    }

    subscribe("status_update", handleStatusUpdate)
    subscribe("final_response", handleFinalResponse)

    return () => {
      unsubscribe("status_update", handleStatusUpdate)
      unsubscribe("final_response", handleFinalResponse)
    }
  }, [inferenceSteps, processedMessageIds, subscribe, unsubscribe]) // Include subscribe/unsubscribe so we rewire after client init

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
          
          // Add to file history
          if ((window as any).addFileToHistory) {
            (window as any).addFileToHistory(result)
          }
          
          console.log('File uploaded successfully:', result.filename)
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

  const handleSend = async () => {
    if (isInferencing) return
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
        console.log('[ChatPanel] Waiting for conversation creation to complete...')
        // Wait up to 2 seconds for the conversation to be created
        for (let i = 0; i < 20; i++) {
          await new Promise(resolve => setTimeout(resolve, 100))
          if (!isCreatingConversation && conversationId !== 'frontend-chat-context') {
            actualConversationId = conversationId
            console.log('[ChatPanel] Conversation created, proceeding with:', actualConversationId)
            break
          }
        }
      }
      
      // If still no conversation after waiting, create one now
      if (actualConversationId === 'frontend-chat-context') {
        try {
          console.log('[ChatPanel] Creating conversation before sending message...')
          const newConversation = await createConversation()
          if (newConversation) {
            actualConversationId = newConversation.conversation_id
            console.log('[ChatPanel] Created conversation:', actualConversationId)
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
      message: userMessage
    })
    
    setIsInferencing(true)
    setInferenceSteps([]) // Reset for new inference
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
            workflow: workflow ? workflow.trim() : undefined  // Backend auto-detects mode from workflow presence
          }
        })
      })

      if (!response.ok) {
        console.error('[ChatPanel] Failed to send message to backend:', response.statusText)
        setIsInferencing(false)
      } else {
        console.log('[ChatPanel] Message sent to backend successfully')
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
                // Only render if there are actual steps
                if (!message.steps || message.steps.length === 0) {
                  return null
                }
                return <InferenceSteps key={`${message.id}-${index}`} steps={message.steps} isInferencing={false} />
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
                  className={`flex gap-3 ${message.role === "user" ? "justify-end" : "items-start"}`}
                >
                  {message.role === "assistant" && (
                    <div className="h-8 w-8 flex-shrink-0 bg-blue-100 rounded-full flex items-center justify-center">
                      <Bot size={18} className="text-blue-600" />
                    </div>
                  )}
                  <div className={`flex flex-col ${message.role === "user" ? "items-start" : "items-start"}`}>
                    {message.role === "user" && message.username && (
                      <p className="text-xs text-muted-foreground mb-1">{message.username}</p>
                    )}
                    <div className="flex gap-3">
                      <div
                        className={`rounded-lg p-3 max-w-md ${message.role === "user" ? "bg-slate-700 text-white" : "bg-muted"
                          }`}
                      >
                      {message.attachments && message.attachments.length > 0 && (
                        <div className="flex flex-col gap-3 mb-3">
                          {message.attachments.map((attachment, attachmentIndex) => {
                            const isImage = (attachment.mediaType || "").startsWith("image/")
                            const isVideo = (attachment.mediaType || "").startsWith("video/")
                            
                            if (isImage) {
                              return (
                                <div key={`${message.id}-attachment-${attachmentIndex}`} className="flex flex-col gap-2">
                                  <a
                                    href={attachment.uri}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="block rounded-lg border border-border"
                                  >
                                    <img
                                      src={attachment.uri}
                                      alt={attachment.fileName || "Image attachment"}
                                      className="w-full h-auto block rounded-t-lg"
                                      style={{ maxHeight: '500px', objectFit: 'contain', backgroundColor: '#f5f5f5' }}
                                    />
                                    <div className="px-3 py-2 text-xs text-muted-foreground border-t border-border bg-muted/50">
                                      {attachment.fileName || "Image attachment"}
                                    </div>
                                  </a>
                                  {message.role === "assistant" && (
                                    <div className="flex flex-wrap gap-2">
                                      <Button
                                        variant={refineTarget?.imageUrl === attachment.uri ? "default" : "secondary"}
                                        size="sm"
                                        className="self-start"
                                        onClick={() => {
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
                                        {refineTarget?.imageUrl === attachment.uri ? "Cancel refine" : "Refine this image"}
                                      </Button>
                                      {refineTarget?.imageUrl === attachment.uri && (
                                        <Button
                                          variant="outline"
                                          size="sm"
                                          disabled={maskUploadInFlight}
                                          onClick={() => {
                                            setMaskEditorSource({ uri: attachment.uri, meta: attachment })
                                            setMaskEditorOpen(true)
                                          }}
                                        >
                                          {maskUploadInFlight ? "Saving mask…" : maskAttachment ? "Edit mask" : "Paint mask"}
                                        </Button>
                                      )}
                                    </div>
                                  )}
                                </div>
                              )
                            }
                            
                            if (isVideo) {
                              return (
                                <div key={`${message.id}-attachment-${attachmentIndex}`} className="flex flex-col gap-2">
                                  <div className="overflow-hidden rounded-lg border border-border bg-background">
                                    <video
                                      src={attachment.uri}
                                      controls
                                      className="w-full h-auto"
                                    >
                                      Your browser does not support the video tag.
                                    </video>
                                    <div className="px-3 py-2 text-xs text-muted-foreground border-t border-border bg-muted/50">
                                      {attachment.fileName || "Video attachment"}
                                    </div>
                                  </div>
                                </div>
                              )
                            }

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
                      {/* Render images loaded from conversation history (DataPart artifacts) */}
                      {message.images && message.images.length > 0 && (
                        <div className="flex flex-col gap-3 mb-3">
                          {message.images.map((image, imageIndex) => (
                            <div key={`${message.id}-image-${imageIndex}`} className="flex flex-col gap-2">
                              <a
                                href={image.uri}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="block rounded-lg border border-border"
                              >
                                <img
                                  src={image.uri}
                                  alt={image.fileName || "Generated image"}
                                  className="w-full h-auto block rounded-t-lg"
                                  style={{ maxHeight: '500px', objectFit: 'contain', backgroundColor: '#f5f5f5' }}
                                />
                                <div className="px-3 py-2 text-xs text-muted-foreground border-t border-border bg-muted/50">
                                  {image.fileName || "Generated image"}
                                </div>
                              </a>
                            </div>
                          ))}
                        </div>
                      )}
                      {message.content && message.content.trim().length > 0 && (
                        <div className="text-sm prose prose-sm max-w-none dark:prose-invert">
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            rehypePlugins={[rehypeHighlight]}
                            components={{
                              p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                              code: ({ node, inline, className, children, ...props }: any) => 
                                inline ? (
                                  <code className="bg-black/10 dark:bg-white/10 px-1 py-0.5 rounded text-xs" {...props}>
                                    {children}
                                  </code>
                                ) : (
                                  <code className="block bg-black/10 dark:bg-white/10 p-2 rounded text-xs overflow-x-auto" {...props}>
                                    {children}
                                  </code>
                                ),
                              pre: ({ children }) => <div className="my-2">{children}</div>,
                              ul: ({ children }) => <ul className="mb-2 last:mb-0 pl-4">{children}</ul>,
                              ol: ({ children }) => <ol className="mb-2 last:mb-0 pl-4">{children}</ol>,
                              li: ({ children }) => <li className="mb-1">{children}</li>,
                              h1: ({ children }) => <h1 className="text-base font-bold mb-2">{children}</h1>,
                              h2: ({ children }) => <h2 className="text-sm font-bold mb-2">{children}</h2>,
                              h3: ({ children }) => <h3 className="text-sm font-semibold mb-1">{children}</h3>,
                              blockquote: ({ children }) => (
                                <blockquote className="border-l-2 border-gray-300 dark:border-gray-600 pl-2 my-2 italic">
                                  {children}
                                </blockquote>
                              ),
                            }}
                          >
                            {message.content || ""}
                          </ReactMarkdown>
                        </div>
                      )}
                    </div>
                    {message.role === "user" && (() => {
                      const { bgColor, iconColor } = getAvatarStyles(message.userColor)
                      return (
                        <div 
                          className="h-8 w-8 flex-shrink-0 rounded-full flex items-center justify-center"
                          style={{ backgroundColor: bgColor }}
                        >
                          <User size={18} style={{ color: iconColor }} />
                        </div>
                      )
                    })()}
                  </div>
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
            {isInferencing && <InferenceSteps steps={inferenceSteps} isInferencing={true} />}
            
            {/* Render streaming message separately AFTER workflow but treat it as a message */}
            {streamingMessageId && messages.find(m => m.id === streamingMessageId) && (() => {
              const streamingMsg = messages.find(m => m.id === streamingMessageId)!
              return (
                <div className="flex gap-3 items-start">
                  <div className="h-8 w-8 flex-shrink-0 bg-blue-100 rounded-full flex items-center justify-center">
                    <Bot size={18} className="text-blue-600" />
                  </div>
                  <div className="flex flex-col items-start">
                    <div className="rounded-lg p-3 max-w-md bg-muted">
                      <div className="text-sm prose prose-sm max-w-none dark:prose-invert">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          rehypePlugins={[rehypeHighlight]}
                          components={{
                            p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                            code: ({ node, inline, className, children, ...props }: any) => 
                              inline ? (
                                <code className="bg-black/10 dark:bg-white/10 px-1 py-0.5 rounded text-xs" {...props}>
                                  {children}
                                </code>
                              ) : (
                                <code className="block bg-black/10 dark:bg-white/10 p-2 rounded text-xs overflow-x-auto" {...props}>
                                  {children}
                                </code>
                              ),
                            pre: ({ children }) => <div className="my-2">{children}</div>,
                            ul: ({ children }) => <ul className="mb-2 last:mb-0 pl-4">{children}</ul>,
                            ol: ({ children }) => <ol className="mb-2 last:mb-0 pl-4">{children}</ol>,
                            li: ({ children }) => <li className="mb-1">{children}</li>,
                            h1: ({ children }) => <h1 className="text-base font-bold mb-2">{children}</h1>,
                            h2: ({ children }) => <h2 className="text-sm font-bold mb-2">{children}</h2>,
                            h3: ({ children }) => <h3 className="text-sm font-semibold mb-1">{children}</h3>,
                            blockquote: ({ children }) => (
                              <blockquote className="border-l-2 border-gray-300 dark:border-gray-600 pl-2 my-2 italic">
                                {children}
                              </blockquote>
                            ),
                          }}
                        >
                          {streamingMsg.content || ""}
                        </ReactMarkdown>
                        <span className="inline-block w-2 h-4 bg-blue-600 animate-pulse ml-1" />
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
      
      {/* Layout for empty state - centered welcome message and input */}
      {!isLoadingMessages && messages.length === 0 && !isInferencing && (
        <div className="flex-1 flex flex-col items-center justify-center px-4">
          <div className="w-full max-w-4xl space-y-8">
            <TypingWelcomeMessage text="What can I help you with today?" />
            {/* Input rendered in shared section below will appear here visually */}
          </div>
        </div>
      )}
      
      {/* Chat input area - positioned differently based on state */}
      <div className={`${!isLoadingMessages && messages.length === 0 && !isInferencing ? 'absolute top-1/2 left-0 right-0 flex items-center justify-center mt-8' : 'flex-shrink-0'}`}>
        <div className={`px-4 pb-4 pt-2 ${!isLoadingMessages && messages.length === 0 && !isInferencing ? 'w-full max-w-4xl' : 'w-full'}`}>
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
                
                return (
                  <div key={index} className="flex items-center gap-2 bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800 rounded-lg px-3 py-2 text-sm max-w-xs">
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
          
          <div className="relative max-w-4xl mx-auto">
            <div className="relative bg-muted/30 rounded-3xl transition-all duration-200">
            <Textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => {
                const newValue = e.target.value
                setInput(newValue)
                
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
              placeholder="Type your message... (Use @ to mention users or agents)"
              className="pl-14 pr-32 min-h-12 max-h-32 resize-none overflow-y-auto border-none focus-visible:ring-0 focus-visible:ring-offset-0 bg-transparent rounded-3xl py-3"
              disabled={isInferencing}
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
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button 
                    variant="ghost" 
                    size="icon"
                    className={`h-9 w-9 rounded-full ${
                      voiceLive.isConnected 
                        ? 'bg-green-100 text-green-600 hover:bg-green-200' 
                        : voiceLive.error 
                        ? 'bg-red-100 text-red-600' 
                        : 'hover:bg-primary/20'
                    }`}
                    disabled={isInferencing}
                    onClick={voiceLive.isConnected ? voiceLive.stopVoiceConversation : voiceLive.startVoiceConversation}
                  >
                    {voiceLive.isConnected ? <PhoneOff size={20} className="text-muted-foreground" /> : <Phone size={20} className="text-muted-foreground" />}
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="top">
                  {voiceLive.isConnected 
                    ? 'End voice conversation' 
                    : voiceLive.error 
                    ? `Error: ${voiceLive.error}` 
                    : 'Start voice conversation'
                  }
                </TooltipContent>
              </Tooltip>
              <Button 
                onClick={handleSend} 
                disabled={isInferencing || (!input.trim() && !refineTarget)}
                className="h-9 w-9 rounded-full bg-primary hover:bg-primary/90 disabled:bg-muted disabled:text-muted-foreground"
                size="icon"
              >
                <Send size={18} className="text-primary-foreground" />
              </Button>
            </div>
            </div>
          </div>
          
          {/* Helper text below input */}
          <div className="text-center mt-2">
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
                if ((window as any).addFileToHistory) {
                  (window as any).addFileToHistory(uploadedMask)
                }
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
