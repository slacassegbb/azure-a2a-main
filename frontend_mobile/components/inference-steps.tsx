"use client"

import { getAgentHexColor } from "@/lib/agent-colors"
import { CheckCircle2, Loader2, AlertCircle, Paperclip } from "lucide-react"
import { useState } from "react"

export interface StepEvent {
  agentName: string
  eventType?: string
  activityType?: string
  content?: string
  status?: string
  data?: any
  timestamp?: string
  imageUrl?: string
  imageName?: string
  mediaType?: string
}

interface InferenceStepsProps {
  events: StepEvent[]
}

interface FileAttachment {
  name: string
  url: string
  type?: string
}

interface TimelineEntry {
  agentName: string
  message: string
  status: "running" | "complete" | "error"
  stepNumber?: number
  color: string
  timestamp?: string
  files: FileAttachment[]
}

function getMediaCategory(fileName: string, mimeType?: string): "image" | "video" | "audio" | "other" {
  const mime = (mimeType || "").toLowerCase()
  if (mime.startsWith("image/")) return "image"
  if (mime.startsWith("video/")) return "video"
  if (mime.startsWith("audio/")) return "audio"

  const ext = fileName.toLowerCase().split(".").pop() || ""
  if (["jpg", "jpeg", "png", "gif", "webp", "svg", "bmp"].includes(ext)) return "image"
  if (["mp4", "webm", "mov", "avi", "mkv"].includes(ext)) return "video"
  if (["mp3", "wav", "aac", "ogg", "flac", "m4a"].includes(ext)) return "audio"
  return "other"
}

function parseEventsToTimeline(events: StepEvent[]): TimelineEntry[] {
  const timeline: TimelineEntry[] = []
  // Collect files per agent to attach to the nearest text entry
  const pendingFiles: Map<string, FileAttachment[]> = new Map()

  for (const evt of events) {
    const name = evt.agentName || ""
    if (name.toLowerCase().includes("foundry-host") || name.toLowerCase() === "host") continue

    const friendly = name
      .replace(/^azurefoundry_/i, "")
      .replace(/^AI Foundry /i, "")
      .replace(/_/g, " ")

    if (!friendly) continue

    // Check for file attachment in the event
    const imageUrl = evt.imageUrl || evt.data?.imageUrl
    const imageName = evt.imageName || evt.data?.imageName
    const mediaType = evt.mediaType || evt.data?.mediaType

    if (imageName && imageUrl) {
      if (!pendingFiles.has(friendly)) pendingFiles.set(friendly, [])
      const files = pendingFiles.get(friendly)!
      // Dedupe by URL
      if (!files.some((f) => f.url === imageUrl)) {
        files.push({ name: imageName, url: imageUrl, type: mediaType })
      }
    }

    const content = evt.content || evt.status || evt.data?.content || ""

    // File-only events (📎 prefix) — collect the file but also show in timeline
    if (content.startsWith("📎") || (imageName && !content)) {
      const fileName = imageName || content.replace(/^📎\s*(Extracted|Generated)\s*/i, "").trim()
      if (imageUrl && fileName) {
        if (!pendingFiles.has(friendly)) pendingFiles.set(friendly, [])
        const files = pendingFiles.get(friendly)!
        if (!files.some((f) => f.url === imageUrl)) {
          files.push({ name: fileName, url: imageUrl, type: mediaType })
        }
      }
      if (!content) continue
    }

    // Skip empty or JSON-only events
    if (!content || content.startsWith("{")) continue

    const stepMatch = content.match(/\[Step (\d+)\]/)
    const stepNumber = stepMatch ? parseInt(stepMatch[1]) : undefined

    const clean = content.replace(/\[Step \d+\]\s*/g, "").trim()
    if (!clean) continue

    const activity = evt.activityType || evt.data?.activityType || evt.eventType || ""
    let status: "running" | "complete" | "error" = "running"
    if (activity === "agent_complete" || activity === "complete") status = "complete"
    else if (activity === "agent_error" || activity === "error") status = "error"

    // When an agent completes/errors, update ALL previous entries for that agent
    if (status === "complete" || status === "error") {
      for (const entry of timeline) {
        if (entry.agentName === friendly && entry.status === "running") {
          entry.status = status
        }
      }
    }

    // Deduplicate
    const isDuplicate = timeline.some(
      (entry) => entry.agentName === friendly && entry.message === clean
    )
    if (isDuplicate) continue

    // Attach any pending files for this agent
    const files = pendingFiles.get(friendly) || []

    timeline.push({
      agentName: friendly,
      message: clean,
      status,
      stepNumber,
      color: getAgentHexColor(friendly),
      timestamp: evt.timestamp,
      files: [...files],
    })

    // Clear pending files once attached
    if (files.length > 0) pendingFiles.set(friendly, [])
  }

  // If there are leftover files not attached to any text entry, create entries for them
  pendingFiles.forEach((files, agentName) => {
    if (files.length === 0) return
    timeline.push({
      agentName,
      message: `${files.length} file${files.length > 1 ? "s" : ""} generated`,
      status: "complete",
      color: getAgentHexColor(agentName),
      files,
    })
  })

  return timeline
}

function FileRenderer({ file }: { file: FileAttachment }) {
  const [imgError, setImgError] = useState(false)
  const category = getMediaCategory(file.name, file.type)

  switch (category) {
    case "image":
      if (imgError) {
        return (
          <a href={file.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 text-xs text-primary hover:underline">
            <Paperclip className="h-3 w-3" />{file.name}
          </a>
        )
      }
      return (
        <a href={file.url} target="_blank" rel="noopener noreferrer" className="block mt-1.5">
          <img
            src={file.url}
            alt={file.name}
            className="rounded-md max-w-[200px] max-h-[150px] object-contain"
            loading="lazy"
            onError={() => setImgError(true)}
          />
        </a>
      )

    case "video":
      return (
        <video
          src={file.url}
          controls
          playsInline
          muted
          className="rounded-md max-w-[250px] max-h-[180px] mt-1.5"
          preload="metadata"
        />
      )

    case "audio":
      return (
        <div className="mt-1.5">
          <audio src={file.url} controls className="w-full max-w-[250px] h-8" preload="metadata" />
          <p className="text-[10px] text-muted-foreground mt-0.5">{file.name}</p>
        </div>
      )

    default:
      return (
        <a
          href={file.url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 text-xs text-primary hover:underline mt-1"
        >
          <Paperclip className="h-3 w-3" />
          {file.name}
        </a>
      )
  }
}

function TimelineCard({ entry, isLast }: { entry: TimelineEntry; isLast: boolean }) {
  return (
    <div className="flex gap-3">
      {/* Timeline line + dot */}
      <div className="flex flex-col items-center">
        <div
          className="h-7 w-7 rounded-full flex items-center justify-center text-[10px] font-bold text-white shrink-0"
          style={{ backgroundColor: entry.color }}
        >
          {entry.stepNumber || entry.agentName.charAt(0).toUpperCase()}
        </div>
        {!isLast && (
          <div className="w-0.5 flex-1 min-h-[12px] bg-border mt-1" />
        )}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 pb-3">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-medium">{entry.agentName}</span>
          {entry.status === "complete" && <CheckCircle2 className="h-3 w-3 text-green-500 shrink-0" />}
          {entry.status === "error" && <AlertCircle className="h-3 w-3 text-red-500 shrink-0" />}
        </div>
        <p className="text-xs text-muted-foreground leading-relaxed mt-0.5">
          {entry.message}
        </p>

        {/* File attachments (images, videos, audio, documents) */}
        {entry.files.length > 0 && (
          <div className="space-y-1.5 mt-1.5">
            {entry.files.map((file, i) => (
              <FileRenderer key={`${file.url}-${i}`} file={file} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export function InferenceSteps({ events }: InferenceStepsProps) {
  const timeline = parseEventsToTimeline(events)
  if (!timeline.length) return null

  return (
    <div>
      {timeline.map((entry, i) => (
        <TimelineCard
          key={`${entry.agentName}-${i}`}
          entry={entry}
          isLast={i === timeline.length - 1}
        />
      ))}
    </div>
  )
}
