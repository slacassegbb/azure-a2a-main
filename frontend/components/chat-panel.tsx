"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Paperclip, Mic, MicOff, Send, Bot, User, Network, Paintbrush } from "lucide-react"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { D3Dag } from "./d3-dag"
import { RunLogsModal } from "./run-logs-modal"
import { useEventHub } from "@/hooks/use-event-hub"
import { useVoiceRecording } from "@/hooks/use-voice-recording"
import { InferenceSteps } from "./inference-steps"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeHighlight from "rehype-highlight"
import { useSearchParams, useRouter } from "next/navigation"
import { getConversation, updateConversationTitle, createConversation, notifyConversationCreated, type Message as APIMessage } from "@/lib/conversation-api"

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
}

const initialMessages: Message[] = [
  {
    id: "1",
    role: "assistant",
    content: "Hello! How can I help you today?",
    agent: "Greeting Bot",
  },
]

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

  const exportMask = useCallback(() => {
    const overlay = overlayRef.current
    if (!overlay || !imageLoaded) {
      return
    }

    const exportCanvas = document.createElement("canvas")
    exportCanvas.width = overlay.width
    exportCanvas.height = overlay.height

    const exportCtx = exportCanvas.getContext("2d")
    const sourceCtx = overlay.getContext("2d")

    if (!exportCtx || !sourceCtx) {
      return
    }

    const overlayData = sourceCtx.getImageData(0, 0, overlay.width, overlay.height)
    const exportData = exportCtx.createImageData(overlay.width, overlay.height)

    for (let i = 0; i < exportData.data.length; i += 4) {
      exportData.data[i] = 255
      exportData.data[i + 1] = 255
      exportData.data[i + 2] = 255
      exportData.data[i + 3] = 255
    }

    for (let i = 0; i < overlayData.data.length; i += 4) {
      const alpha = overlayData.data[i + 3]
      if (alpha > 10) {
        exportData.data[i] = 0
        exportData.data[i + 1] = 0
        exportData.data[i + 2] = 0
        exportData.data[i + 3] = 0
      }
    }

    exportCtx.putImageData(exportData, 0, 0)

    exportCanvas.toBlob(async (blob) => {
      if (!blob) {
        return
      }
      await onSave(blob)
      onClose()
    }, "image/png", 1)
  }, [onClose, onSave])

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
                  <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground bg-background/70">
                    Loading image…
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
                disabled={!imageLoaded}
                className="w-full"
              >
                Save mask &amp; continue
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
  agentMode: boolean
  enableInterAgentMemory: boolean
  workflow?: string
}

export function ChatPanel({ dagNodes, dagLinks, agentMode, enableInterAgentMemory, workflow }: ChatPanelProps) {
  const DEBUG = process.env.NEXT_PUBLIC_DEBUG_LOGS === 'true'
  // Use the shared Event Hub hook so we subscribe to the same client as the rest of the app
  const { subscribe, unsubscribe, emit, sendMessage, isConnected } = useEventHub()
  
  // Voice recording hook
  const voiceRecording = useVoiceRecording()
  
  // Get conversation ID from URL parameters
  const searchParams = useSearchParams()
  const router = useRouter()
  const conversationId = searchParams.get('conversationId') || 'frontend-chat-context'
  
  const [messages, setMessages] = useState<Message[]>(initialMessages)
  const [input, setInput] = useState("")
  const [isInferencing, setIsInferencing] = useState(false)
  const [inferenceSteps, setInferenceSteps] = useState<{ agent: string; status: string; imageUrl?: string; imageName?: string }[]>([])
  const [activeNode, setActiveNode] = useState<string | null>(null)
  const [processedMessageIds, setProcessedMessageIds] = useState<Set<string>>(new Set())
  const [uploadedFiles, setUploadedFiles] = useState<any[]>([])
  const [refineTarget, setRefineTarget] = useState<any | null>(null)
  const [maskAttachment, setMaskAttachment] = useState<any | null>(null)
  const [maskUploadInFlight, setMaskUploadInFlight] = useState(false)
  const [maskEditorOpen, setMaskEditorOpen] = useState(false)
  const [maskEditorSource, setMaskEditorSource] = useState<{ uri: string; meta?: any } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [isDragOver, setIsDragOver] = useState(false)
  
  // Current user state for multi-user chat
  const [currentUser, setCurrentUser] = useState<any>(null)

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

  // Also clear uploaded files on component mount (page refresh)
  useEffect(() => {
    if (DEBUG) console.log('[ChatPanel] Component mounted, clearing any stale uploaded files')
    setUploadedFiles([])
  }, []) // Empty dependency array = only run on mount

  // Track if we're in the process of creating a conversation to avoid race conditions
  const [isCreatingConversation, setIsCreatingConversation] = useState(false)

  // Auto-create conversation immediately on mount (removed delay to fix race condition)
  useEffect(() => {
    if (DEBUG) console.log('[ChatPanel] Auto-creation useEffect triggered with conversationId:', conversationId)
    
    const autoCreateConversation = async () => {
      // Only auto-create if we're using the default context and not already creating one
      if (conversationId === 'frontend-chat-context' && !isCreatingConversation) {
        try {
          setIsCreatingConversation(true)
          if (DEBUG) console.log('[ChatPanel] Auto-creating initial conversation...')
          const newConversation = await createConversation()
          if (newConversation) {
            if (DEBUG) console.log('[ChatPanel] Auto-created conversation:', newConversation.conversation_id)
            // Notify sidebar about the new conversation
            notifyConversationCreated(newConversation)
            // Redirect to the new conversation
            const newUrl = `/?conversationId=${newConversation.conversation_id}`
            router.replace(newUrl)
          }
        } catch (error) {
          console.error('[ChatPanel] Failed to auto-create conversation:', error)
        } finally {
          setIsCreatingConversation(false)
        }
      } else {
        if (DEBUG) console.log('[ChatPanel] Not auto-creating conversation. conversationId:', conversationId, 'isCreating:', isCreatingConversation)
      }
    }
    
    // Small delay to ensure sidebar is mounted, but much shorter to reduce race condition window
    const timeoutId = setTimeout(autoCreateConversation, 100)
    
    return () => clearTimeout(timeoutId)
  }, [conversationId, router, isCreatingConversation])

  // Reset messages when conversation ID changes (new chat)
  useEffect(() => {
    const loadConversationMessages = async () => {
    if (DEBUG) console.log('[ChatPanel] Conversation ID changed to:', conversationId)
    if (DEBUG) console.log('[ChatPanel] URL search params:', searchParams.toString())
      
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
            const convertedMessages: Message[] = apiMessages.map((msg, index) => ({
              id: msg.messageId || `api_msg_${index}`,
              role: (msg.role === 'user' || msg.role === 'assistant' || msg.role === 'agent') ? 
                    (msg.role === 'agent' ? 'assistant' : msg.role) : 'assistant',
              content: msg.parts?.map((part: any) => part.text || part.content).join('\n') || '',
              agent: (msg.role === 'assistant' || msg.role === 'agent') ? 'Assistant' : undefined
            }))
            
            if (DEBUG) console.log("[ChatPanel] Converted messages:", convertedMessages.length)
            
            if (convertedMessages.length > 0) {
              setMessages(convertedMessages)
            } else {
              // If no messages found, show initial message
              if (DEBUG) console.log("[ChatPanel] No messages found, showing initial messages")
              setMessages(initialMessages)
            }
          } else {
            if (DEBUG) console.log("[ChatPanel] No conversation found or no messages")
            setMessages(initialMessages)
          }
        } catch (error) {
          console.error("[ChatPanel] Failed to load conversation messages:", error)
          setMessages(initialMessages)
        }
      } else {
        // New conversation or default - reset to initial messages
        if (DEBUG) console.log("[ChatPanel] Using initial messages for new/default conversation")
        setMessages(initialMessages)
      }
      
      // Reset other state
      setIsInferencing(false)
      setInferenceSteps([])
      setProcessedMessageIds(new Set())
    }
    
    loadConversationMessages()
  }, [conversationId]) // Only depend on conversationId, not searchParams

  // Real Event Hub listener for backend events - moved inside component
  useEffect(() => {
    // Handle real status updates from A2A backend
    const handleTaskUpdate = (data: any) => {
      console.log("[ChatPanel] Task update received:", data)
      // A2A TaskEventData has: taskId, conversationId, contextId, state, artifactsCount
      if (data.taskId && data.state) {
        // Use the actual agent name if available, otherwise fall back to generic names
        let agentName = data.agentName || "Host Agent"
        let status = data.state
        
        // If this is a new agent we haven't seen before, register it
        if (data.agentName && data.agentName !== "Host Agent" && data.agentName !== "System") {
          emit("agent_registered", {
            name: data.agentName,
            status: "online",
            avatar: "/placeholder.svg?height=32&width=32"
          })
        }
        
        if (data.state === "created") {
          status = "initializing conversation"
        } else if (data.state === "completed") {
          status = "response complete"
        } else if (data.state === "in_progress") {
          status = "processing request"
        } else if (data.state === "queued") {
          status = "request queued"
        } else if (data.state === "requires_action") {
          status = "executing tools"
        }
        
  emit("status_update", {
          inferenceId: data.taskId,
          agent: agentName,
          status: status
        })
      }
    }

    // Handle system events for more detailed trace
    const handleSystemEvent = (data: any) => {
      console.log("[ChatPanel] System event received:", data)
      // A2A SystemEventData has: eventId, conversationId, actor, role, content
      if (data.eventId && data.content) {
        let agentName = data.actor || "System"
        
        // If this is a new agent we haven't seen before, register it
        if (data.actor && data.actor !== "Host Agent" && data.actor !== "System" && data.actor !== "User") {
          emit("agent_registered", {
            name: data.actor,
            status: "online",
            avatar: "/placeholder.svg?height=32&width=32"
          })
        }
        
        emit("status_update", {
          inferenceId: data.conversationId || data.eventId,
          agent: agentName,
          status: data.content
        })
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

    // Handle message sent events (when AI sends message to thread)
    const handleMessageSent = (data: any) => {
      console.log("[ChatPanel] Message sent to thread:", data)
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
          emit("final_response", {
            inferenceId: data.conversationId || data.messageId,
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

    // Handle shared user messages from other clients
    const handleSharedMessage = (data: any) => {
      console.log("[ChatPanel] Shared message received:", data)
      if (data.message) {
        const newMessage: Message = {
          id: data.message.id,
          role: data.message.role,
          content: data.message.content,
          username: data.message.username,
          userColor: data.message.userColor
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

    // Subscribe to real Event Hub events from A2A backend
    subscribe("task_updated", handleTaskUpdate)
    subscribe("task_created", handleTaskCreated)
    subscribe("system_event", handleSystemEvent)
    subscribe("message_sent", handleMessageSent)
    subscribe("message_received", handleMessageReceived)
    subscribe("message", handleMessage)
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

    return () => {
      unsubscribe("task_updated", handleTaskUpdate)
      unsubscribe("task_created", handleTaskCreated)
      unsubscribe("system_event", handleSystemEvent)
      unsubscribe("message_sent", handleMessageSent)
      unsubscribe("message_received", handleMessageReceived)
      unsubscribe("message", handleMessage)
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
    }
  }, [subscribe, unsubscribe, emit])

  // Check authentication status
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const token = localStorage.getItem('auth_token')
      const userInfo = localStorage.getItem('user_info')
      if (token && userInfo) {
        try {
          setCurrentUser(JSON.parse(userInfo))
        } catch (e) {
          console.error('Failed to parse user info:', e)
        }
      }
    }
  }, [])

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
    const handleToolResponse = (data: any) => {
      console.log("[ChatPanel] Tool response received:", data)
      if (data.toolName && data.agentName) {
        const status = data.status === "success" 
          ? `✅ ${data.toolName} completed`
          : `❌ ${data.toolName} failed`
        setInferenceSteps(prev => [...prev, { 
          agent: data.agentName, 
          status: status 
        }])
      }
    }

    // Handle remote agent activity events
    const handleRemoteAgentActivity = (data: any) => {
      console.log("[ChatPanel] Remote agent activity received:", data)
      if (data.agentName && data.content) {
        setInferenceSteps(prev => [...prev, { 
          agent: data.agentName, 
          status: data.content 
        }])
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

    const handleFinalResponse = (data: { inferenceId: string; message: Omit<Message, "id"> }) => {
      console.log("[ChatPanel] Final response received:", data)
      
      const contentKey = data.message.content ?? ""
      const agentKey = data.message.agent ?? "assistant"
      const responseId = `response_${data.inferenceId}_${agentKey}_${contentKey}`
      
      // Check if we've already processed this exact message
      if (processedMessageIds.has(responseId)) {
        console.log("[ChatPanel] Duplicate response detected, skipping:", responseId)
        return
      }
      
      // Mark this message as processed
      setProcessedMessageIds(prev => new Set([...prev, responseId]))
      
      // Only add messages if they have content
      const messagesToAdd: Message[] = []
      
      // Only add summary if there are actual steps
      if (inferenceSteps.length > 0) {
        const summaryMessage: Message = {
          id: `summary_${data.inferenceId}`,
          role: "system",
          type: "inference_summary",
          steps: inferenceSteps,
        }
        messagesToAdd.push(summaryMessage)
      }

      // Only add final message if it has content
      if (data.message.content && data.message.content.trim().length > 0) {
        const finalMessage: Message = {
          id: responseId,
          role: data.message.role === "user" ? "user" : "assistant",
          content: data.message.content,
          agent: data.message.agent,
        }
        messagesToAdd.push(finalMessage)
      }

      // Add messages only if we have any
      if (messagesToAdd.length > 0) {
        setMessages((prev) => [...prev, ...messagesToAdd])
      }
      setIsInferencing(false)
      setInferenceSteps([])
      setActiveNode(null)

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
      // Upload each file individually
      for (let i = 0; i < files.length; i++) {
        const file = files[i]
        const formData = new FormData()
        formData.append('file', file)

        const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
        const response = await fetch(`${baseUrl}/upload`, {
          method: 'POST',
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
      // Append workflow to the message if in Agent Mode and workflow is defined
      let messageText = input
      if (agentMode && workflow && workflow.trim()) {
        messageText = `${input}\n\n### WORKFLOW (ALWAYS FOLLOW THESE STEPS)\n${workflow}`
      }
      
      // Build message parts including any uploaded files
      const parts: any[] = [
        {
          root: {
            kind: 'text',
            text: messageText
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
            contextId: actualConversationId,
            role: 'user',
            parts: parts,
            agentMode: agentMode,  // Include agent mode in message params
            enableInterAgentMemory: enableInterAgentMemory  // Include inter-agent memory flag
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
    setMaskAttachment(null)
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <header className="p-4 border-b flex-shrink-0">
        <div className="flex items-center">
          <h2 className="text-xl font-bold">A2A Multi-Agent Host Orchestrator</h2>
          <div className="ml-auto flex items-center gap-2">
            <RunLogsModal />
            <Dialog>
              <DialogTrigger asChild>
                <Button variant="outline" size="icon" className="bg-transparent">
                  <Network size={20} />
                </Button>
              </DialogTrigger>
              <DialogContent className="max-w-2xl">
                <DialogHeader>
                  <DialogTitle>Agent Network DAG</DialogTitle>
                </DialogHeader>
                <D3Dag nodes={dagNodes} links={dagLinks} activeNodeId={activeNode} />
              </DialogContent>
            </Dialog>
          </div>
        </div>
      </header>
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
          className={`h-full overflow-y-auto ${isDragOver ? '[&_*]:pointer-events-none' : ''}`}
          data-chat-drop-zone
          onDragOver={handleDragOver}
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <div className="flex flex-col gap-4 p-4">
            {messages.map((message, index) => {
              if (message.type === "inference_summary") {
                // Only render if there are actual steps
                if (!message.steps || message.steps.length === 0) {
                  return null
                }
                return <InferenceSteps key={`${message.id}-${index}`} steps={message.steps} isInferencing={false} />
              }
              
              // Skip rendering messages with no content and no attachments
              const hasContent = message.content && message.content.trim().length > 0
              const hasAttachments = message.attachments && message.attachments.length > 0
              if (!hasContent && !hasAttachments) {
                return null
              }
              
              return (
                <div
                  key={`${message.id}-${index}`}
                  className={`flex gap-3 ${message.role === "user" ? "justify-end" : ""}`}
                >
                  {message.role === "assistant" && (
                    <div className="h-8 w-8 flex-shrink-0 bg-blue-100 rounded-full flex items-center justify-center mt-6">
                      <Bot size={18} className="text-blue-600" />
                    </div>
                  )}
                  <div className={`flex flex-col ${message.role === "user" ? "items-end" : "items-start"}`}>
                    {message.role === "user" && message.username && (
                      <p className="text-xs text-muted-foreground mb-1">{message.username}</p>
                    )}
                    <div
                      className={`rounded-lg p-3 max-w-md ${message.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted"
                        }`}
                    >
                      {message.attachments && message.attachments.length > 0 ? (
                        <div className="flex flex-col gap-3">
                          {message.attachments.map((attachment, attachmentIndex) => {
                            const isImage = (attachment.mediaType || "").startsWith("image/")
                            if (isImage) {
                              return (
                                <div key={`${message.id}-attachment-${attachmentIndex}`} className="flex flex-col gap-2">
                                  <a
                                    href={attachment.uri}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="block overflow-hidden rounded-lg border border-border bg-background"
                                  >
                                    <img
                                      src={attachment.uri}
                                      alt={attachment.fileName || "Image attachment"}
                                      className="w-full h-auto"
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
                      ) : (
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
                    {message.role === "assistant" && message.agent && (
                        <p className="text-xs text-muted-foreground mt-1">{message.agent}</p>
                      )}
                  </div>
                  {message.role === "user" && (() => {
                    const { bgColor, iconColor } = getAvatarStyles(message.userColor)
                    return (
                      <div 
                        className="h-8 w-8 flex-shrink-0 rounded-full flex items-center justify-center mt-6"
                        style={{ backgroundColor: bgColor }}
                      >
                        <User size={18} style={{ color: iconColor }} />
                      </div>
                    )
                  })()}
                </div>
              )
            })}
            {isInferencing && <InferenceSteps steps={inferenceSteps} isInferencing={true} />}
          </div>
        </div>
      </div>
      <div className="border-t flex-shrink-0">
        <div className="p-4">
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
                  <div key={index} className="flex items-center gap-2 bg-gray-100 rounded-lg px-3 py-2 text-sm max-w-xs">
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <span className="text-lg">{getFileIcon(file.filename, file.content_type)}</span>
                      <div className="flex flex-col min-w-0 flex-1">
                        <span className="truncate font-medium">{file.filename}</span>
                        <span className="text-xs text-gray-500">
                          {file.size ? `${(file.size / 1024).toFixed(1)} KB` : ''}
                        </span>
                      </div>
                    </div>
                    <button
                      onClick={() => setUploadedFiles(prev => prev.filter((_, i) => i !== index))}
                      className="text-gray-500 hover:text-gray-700 flex-shrink-0 w-5 h-5 flex items-center justify-center rounded-full hover:bg-gray-200"
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
          
          <div className="relative">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSend()}
              placeholder="Type your message..."
              className="pr-24 h-12"
              disabled={isInferencing}
            />
            <div className="absolute top-1/2 right-2 -translate-y-1/2 flex items-center gap-1">
              <input
                ref={fileInputRef}
                type="file"
                onChange={handleFileUpload}
                className="hidden"
                accept="*/*"
                multiple
              />
              <Button 
                variant="ghost" 
                size="icon" 
                disabled={isInferencing}
                onClick={handlePaperclipClick}
              >
                <Paperclip size={18} />
              </Button>
              <Button 
                variant="ghost" 
                size="icon" 
                disabled={isInferencing || voiceRecording.isProcessing}
                onClick={handleMicClick}
                className={`${voiceRecording.isRecording ? 'bg-red-100 text-red-600 hover:bg-red-200' : ''}`}
                title={voiceRecording.isRecording ? 
                  `Recording... ${voiceRecording.duration}s` : 
                  voiceRecording.isProcessing ? 'Processing...' : 'Record voice message'
                }
              >
                {voiceRecording.isRecording ? <MicOff size={18} /> : <Mic size={18} />}
              </Button>
              <Button onClick={handleSend} disabled={isInferencing || (!input.trim() && !refineTarget)}>
                <Send size={18} />
              </Button>
            </div>
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
              const formData = new FormData()
              const filename = `${(refineTarget.imageMeta?.fileName || "mask")?.replace(/\.[^.]+$/, "")}-mask.png`
              const maskFile = new File([blob], filename, { type: "image/png" })
              formData.append('file', maskFile)

              const baseUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
              const response = await fetch(`${baseUrl}/upload`, {
                method: 'POST',
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
  )
}
