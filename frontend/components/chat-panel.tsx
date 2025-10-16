"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Paperclip, Mic, MicOff, Send, Bot, User, Network } from "lucide-react"
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
  steps?: { agent: string; status: string }[]
  // Just username for showing who sent the message
  username?: string
  // User color for the avatar
  userColor?: string
}

const initialMessages: Message[] = [
  {
    id: "1",
    role: "assistant",
    content: "Hello! How can I help you today?",
    agent: "Greeting Bot",
  },
]

type ChatPanelProps = {
  dagNodes: any[]
  dagLinks: any[]
}

export function ChatPanel({ dagNodes, dagLinks }: ChatPanelProps) {
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
  const [inferenceSteps, setInferenceSteps] = useState<{ agent: string; status: string }[]>([])
  const [activeNode, setActiveNode] = useState<string | null>(null)
  const [processedMessageIds, setProcessedMessageIds] = useState<Set<string>>(new Set())
  const [uploadedFiles, setUploadedFiles] = useState<any[]>([])
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

  // Also clear uploaded files on component mount (page refresh)
  useEffect(() => {
    if (DEBUG) console.log('[ChatPanel] Component mounted, clearing any stale uploaded files')
    setUploadedFiles([])
  }, []) // Empty dependency array = only run on mount

  // Auto-create conversation if using default ID
  useEffect(() => {
    if (DEBUG) console.log('[ChatPanel] Auto-creation useEffect triggered with conversationId:', conversationId)
    
    const autoCreateConversation = async () => {
      // Only auto-create if we're using the default context and don't have a proper conversation ID
      if (conversationId === 'frontend-chat-context') {
        try {
          if (DEBUG) console.log('[ChatPanel] Auto-creating initial conversation after delay...')
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
        }
      } else {
        if (DEBUG) console.log('[ChatPanel] Not auto-creating conversation because conversationId is not default:', conversationId)
      }
    }
    
    // Add a delay to ensure the sidebar has loaded and set up event listeners first
    const timeoutId = setTimeout(autoCreateConversation, 800)
    
    return () => clearTimeout(timeoutId)
  }, [conversationId, router])

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
          let agentName = data.agentName || "System"
          
          // If this is a new agent we haven't seen before, register it
          if (data.agentName && data.agentName !== "Host Agent" && data.agentName !== "System" && data.agentName !== "User") {
            emit("agent_registered", {
              name: data.agentName,
              status: "online",
              avatar: "/placeholder.svg?height=32&width=32"
            })
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

  useEffect(() => {
    const handleStatusUpdate = (data: { inferenceId: string; agent: string; status: string }) => {
      console.log("[ChatPanel] Status update:", data)
      setInferenceSteps((prev) => [...prev, { agent: data.agent, status: data.status }])
      setActiveNode(data.agent)
    }

    const handleFinalResponse = (data: { inferenceId: string; message: Omit<Message, "id"> }) => {
      console.log("[ChatPanel] Final response received:", data)
      
      // Use the inference ID + content hash for more robust duplicate detection
      const contentHash = data.message.content ? data.message.content.slice(0, 50) : ""
      const responseId = `response_${data.inferenceId}_${contentHash}`
      
      // Check if we've already processed this exact message
      if (processedMessageIds.has(responseId)) {
        console.log("[ChatPanel] Duplicate response detected, skipping:", responseId)
        return
      }
      
      // Mark this message as processed
      setProcessedMessageIds(prev => new Set([...prev, responseId]))
      
      const summaryMessage: Message = {
        id: `summary_${data.inferenceId}`,
        role: "system",
        type: "inference_summary",
        steps: inferenceSteps,
      }
      const finalMessage: Message = {
        id: responseId,
        ...data.message,
      }

      setMessages((prev) => [...prev, summaryMessage, finalMessage])
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
    if (!input.trim() || isInferencing) return

    // If we're still using the default conversation ID, create a real conversation first
    let actualConversationId = conversationId
    if (conversationId === 'frontend-chat-context') {
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
              mime_type: file.content_type
            }
          }
        })
      })

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
            parts: parts
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
                return <InferenceSteps key={`${message.id}-${index}`} steps={message.steps || []} isInferencing={false} />
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
                      <div className="text-sm prose prose-sm max-w-none dark:prose-invert">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          rehypePlugins={[rehypeHighlight]}
                          components={{
                            // Customize rendering for better chat bubble styling
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
                      {message.role === "assistant" && message.agent && (
                        <p className="text-xs text-muted-foreground mt-1">{message.agent}</p>
                      )}
                    </div>
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
              <Button onClick={handleSend} disabled={isInferencing || !input.trim()}>
                <Send size={18} />
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
