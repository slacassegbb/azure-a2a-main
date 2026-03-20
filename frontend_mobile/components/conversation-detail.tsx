"use client"

import { useEffect, useState, useRef, useCallback } from "react"
import { listMessages, type Message } from "@/lib/conversation-api"
import { useEventHub } from "@/contexts/event-hub-context"
import { InferenceSteps, type StepEvent } from "./inference-steps"
import { ArrowLeft, Bot, User, FileText, Download, ChevronDown, ChevronUp } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

interface ConversationDetailProps {
  conversationId: string
  onBack: () => void
  externalInferenceEvents?: StepEvent[]
}

function getMediaType(uri: string, mimeType?: string): "image" | "video" | "audio" | "document" | "unknown" {
  const mime = (mimeType || "").toLowerCase()
  if (mime.startsWith("image/")) return "image"
  if (mime.startsWith("video/")) return "video"
  if (mime.startsWith("audio/")) return "audio"
  const cleanUri = uri.split("?")[0].toLowerCase()
  if (/\.(png|jpe?g|gif|webp|svg|bmp|ico)$/.test(cleanUri)) return "image"
  if (/\.(mp4|webm|mov|avi|mkv)$/.test(cleanUri)) return "video"
  if (/\.(mp3|wav|aac|ogg|flac|m4a)$/.test(cleanUri)) return "audio"
  if (/\.(pdf|docx?|pptx?|xlsx?|csv|tsv|txt)$/.test(cleanUri)) return "document"
  return "unknown"
}

function getAttachments(msg: Message): Array<{ uri: string; name: string; mimeType: string; mediaType: string }> {
  if (!msg.parts || !Array.isArray(msg.parts)) return []
  const attachments: Array<{ uri: string; name: string; mimeType: string; mediaType: string }> = []
  for (const part of msg.parts) {
    if ((part.kind === "file" || part.type === "file") && part.file?.uri) {
      const uri = part.file.uri
      const name = part.file.name || part.file.fileName || uri.split("/").pop()?.split("?")[0] || "file"
      const mime = part.file.mimeType || ""
      attachments.push({ uri, name, mimeType: mime, mediaType: getMediaType(uri, mime) })
    }
    if ((part.kind === "data" || part.type === "data") && part.data?.["artifact-uri"]) {
      const uri = part.data["artifact-uri"]
      const name = part.data["file-name"] || uri.split("/").pop()?.split("?")[0] || "file"
      attachments.push({ uri, name, mimeType: "", mediaType: getMediaType(uri) })
    }
  }
  return attachments
}

function AttachmentRenderer({ att }: { att: { uri: string; name: string; mimeType: string; mediaType: string } }) {
  switch (att.mediaType) {
    case "image":
      return (
        <a href={att.uri} target="_blank" rel="noopener noreferrer" className="block">
          <img src={att.uri} alt={att.name} className="rounded-lg max-w-full max-h-[300px] object-contain" loading="lazy" />
        </a>
      )
    case "video":
      return (
        <video src={att.uri} controls playsInline className="rounded-lg max-w-full max-h-[300px]" preload="metadata">
          <source src={att.uri} type={att.mimeType || undefined} />
        </video>
      )
    case "audio":
      return (
        <div className="space-y-1">
          <audio src={att.uri} controls className="w-full" preload="metadata">
            <source src={att.uri} type={att.mimeType || undefined} />
          </audio>
          <p className="text-xs text-muted-foreground truncate">{att.name}</p>
        </div>
      )
    default:
      return (
        <a href={att.uri} target="_blank" rel="noopener noreferrer"
          className="flex items-center gap-2 px-3 py-2 rounded-lg border border-dashed border-border hover:bg-accent/50 transition-colors">
          <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
          <span className="text-sm truncate flex-1">{att.name}</span>
          <Download className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        </a>
      )
  }
}

export function ConversationDetail({ conversationId, onBack, externalInferenceEvents }: ConversationDetailProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [inferenceEvents, setInferenceEvents] = useState<StepEvent[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [activityCollapsed, setActivityCollapsed] = useState(false)
  const messageCountBeforeInferenceRef = useRef(0)
  const scrollRef = useRef<HTMLDivElement>(null)
  const { subscribe, unsubscribe } = useEventHub()

  const scrollToBottom = useCallback(() => {
    setTimeout(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
    }, 100)
  }, [])

  // Load messages on mount / conversation change
  useEffect(() => {
    setIsLoading(true)
    setInferenceEvents([])
    setActivityCollapsed(false)
    messageCountBeforeInferenceRef.current = 0
    listMessages(conversationId).then((msgs) => {
      setMessages(msgs)
      setIsLoading(false)
      scrollToBottom()
    })
  }, [conversationId, scrollToBottom])

  // Subscribe to live events
  useEffect(() => {
    const handleMessage = (data: any) => {
      const msgConvId = data.conversationId || ""
      if (msgConvId === conversationId || msgConvId.includes(conversationId)) {
        listMessages(conversationId).then((msgs) => {
          // If we had inference events and new messages arrived, the final response is here
          // Auto-collapse the activity panel
          if (inferenceEvents.length > 0 && msgs.length > messageCountBeforeInferenceRef.current) {
            setActivityCollapsed(true)
          }
          setMessages(msgs)
          scrollToBottom()
        })
      }
    }

    const handleActivity = (data: any) => {
      // On first inference event, fetch messages to capture the user query
      // and record the count so we can split before/after
      if (inferenceEvents.length === 0) {
        listMessages(conversationId).then((msgs) => {
          setMessages(msgs)
          messageCountBeforeInferenceRef.current = msgs.length
          scrollToBottom()
        })
      }
      setInferenceEvents((prev) => [...prev, data])
      scrollToBottom()
    }

    subscribe("message", handleMessage)
    subscribe("remote_agent_activity", handleActivity)
    return () => {
      unsubscribe("message", handleMessage)
      unsubscribe("remote_agent_activity", handleActivity)
    }
  }, [conversationId, subscribe, unsubscribe, scrollToBottom, inferenceEvents.length, messages.length])

  const getMessageText = (msg: Message): string => {
    if (!msg.parts || !Array.isArray(msg.parts)) return ""
    let content = ""
    for (const part of msg.parts) {
      if (part.kind === "text" && part.text) content += (content ? "\n" : "") + part.text
      else if (part.root?.text) content += (content ? "\n" : "") + part.root.text
      else if (part.text) content += (content ? "\n" : "") + part.text
      else if (part.type === "text" && part.content) content += (content ? "\n" : "") + part.content
    }
    return content
  }

  // Combine local + external inference events
  const allLiveEvents = [...inferenceEvents, ...(externalInferenceEvents || [])]

  // Extract workflow plan steps from a message
  const getPlanSteps = (msg: Message): StepEvent[] => {
    const workflowPlan = (msg as any).metadata?.workflow_plan
    if (!workflowPlan?.tasks?.length) return []
    return workflowPlan.tasks.map((task: any) => ({
      agentName: task.recommended_agent || "Unknown Agent",
      content: task.state === "completed"
        ? (task.output?.result || task.task_description)
        : task.task_description,
      activityType: task.state === "completed" ? "agent_complete"
        : task.state === "failed" ? "agent_error" : "agent_start",
      imageUrl: task.output?.imageUrl,
      imageName: task.output?.imageName,
      mediaType: task.output?.mediaType,
    }))
  }

  const renderMessage = (msg: Message, i: number, skipPlan = false) => {
    const text = getMessageText(msg)
    const attachments = getAttachments(msg)
    const hasContent = text.trim() || attachments.length > 0
    const isUser = msg.role === "user"

    return (
      <div key={msg.messageId || `msg-${i}`}>
        {hasContent && (
          <div className={`flex gap-2 ${isUser ? "justify-end" : "justify-start"}`}>
            {!isUser && (
              <div className="h-7 w-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-1">
                <Bot className="h-4 w-4 text-primary" />
              </div>
            )}
            <div className="max-w-[85%] space-y-2">
              {text.trim() && (
                <div className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                  isUser ? "bg-primary text-primary-foreground rounded-br-sm" : "bg-muted rounded-bl-sm"
                }`}>
                  {isUser ? <p>{text}</p> : (
                    <div className="prose prose-sm dark:prose-invert max-w-none [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
                    </div>
                  )}
                </div>
              )}
              {attachments.length > 0 && (
                <div className="space-y-2">
                  {attachments.map((att, j) => <AttachmentRenderer key={`${att.uri}-${j}`} att={att} />)}
                </div>
              )}
            </div>
            {isUser && (
              <div className="h-7 w-7 rounded-full bg-secondary flex items-center justify-center shrink-0 mt-1">
                <User className="h-4 w-4" />
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-3 border-b bg-card/50 backdrop-blur-sm sticky top-0 z-10">
        <button onClick={onBack} className="p-1.5 -ml-1 text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-5 w-5" />
        </button>
        <h2 className="text-sm font-medium truncate flex-1">Conversation</h2>
      </div>

      {/* Scrollable content */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-4 scroll-smooth">
        {isLoading && (
          <div className="flex items-center justify-center h-20">
            <div className="animate-pulse text-sm text-muted-foreground">Loading...</div>
          </div>
        )}

        {(() => {
          const hasLiveActivity = allLiveEvents.length > 0

          // Split messages: messages that existed before inference vs new ones (final response)
          const splitAt = messageCountBeforeInferenceRef.current
          const beforeMessages = hasLiveActivity && splitAt > 0 ? messages.slice(0, splitAt) : messages
          const afterMessages = hasLiveActivity && splitAt > 0 ? messages.slice(splitAt) : []

          return (
            <>
              {/* Render messages, inserting workflow plans between user query and response */}
              {beforeMessages.map((msg, i) => {
                const planSteps = getPlanSteps(msg)
                if (planSteps.length > 0 && msg.role !== "user") {
                  // Plan on assistant message: render plan first, then response
                  return (
                    <div key={msg.messageId || `msg-${i}`}>
                      <div className="mb-3">
                        <p className="text-xs text-muted-foreground mb-2 font-medium uppercase tracking-wider">
                          Workflow Steps
                        </p>
                        <InferenceSteps events={planSteps} />
                      </div>
                      {renderMessage(msg, i, true)}
                    </div>
                  )
                }
                return renderMessage(msg, i)
              })}

              {/* Live agent activity — between user query and final response */}
              {hasLiveActivity && (
                <div className="pt-2 pb-2">
                  <button
                    onClick={() => setActivityCollapsed(!activityCollapsed)}
                    className="flex items-center gap-1.5 mb-2 w-full"
                  >
                    <p className="text-xs text-muted-foreground font-medium uppercase tracking-wider">
                      Agent Activity
                    </p>
                    <span className="text-xs text-muted-foreground">({allLiveEvents.length})</span>
                    {activityCollapsed ? (
                      <ChevronDown className="h-3.5 w-3.5 text-muted-foreground ml-auto" />
                    ) : (
                      <ChevronUp className="h-3.5 w-3.5 text-muted-foreground ml-auto" />
                    )}
                  </button>
                  {!activityCollapsed && <InferenceSteps events={allLiveEvents} />}
                </div>
              )}

              {/* Messages after inference (final response) */}
              {afterMessages.map((msg, i) => renderMessage(msg, splitAt + i))}
            </>
          )
        })()}
      </div>
    </div>
  )
}
