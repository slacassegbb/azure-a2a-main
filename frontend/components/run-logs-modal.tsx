"use client"

import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { FileText } from "lucide-react"
import { cn } from "@/lib/utils"

const logs = [
  { level: "INFO", timestamp: "2025-07-15 11:50:01", message: "User query received: 'Tell me about Citibank'" },
  { level: "INFO", timestamp: "2025-07-15 11:50:01", message: "Starting agent workflow..." },
  { level: "INFO", timestamp: "2025-07-15 11:50:02", message: "Activating node: Query Parser" },
  { level: "INFO", timestamp: "2025-07-15 11:50:03", message: "Activating node: Intent Classifier" },
  {
    level: "WARN",
    timestamp: "2025-07-15 11:50:03",
    message: "Ambiguous intent detected. Proceeding with 'Data Analyst' and 'Creative Writer'.",
  },
  { level: "INFO", timestamp: "2025-07-15 11:50:04", message: "Activating node: Data Analyst" },
  { level: "INFO", timestamp: "2025-07-15 11:50:05", message: "Data Analyst: Fetched 3 relevant documents." },
  { level: "INFO", timestamp: "2025-07-15 11:50:06", message: "Activating node: Creative Writer" },
  { level: "INFO", timestamp: "2025-07-15 11:50:07", message: "Creative Writer: Generating response draft." },
  { level: "INFO", timestamp: "2025-07-15 11:50:08", message: "Activating node: Response Synthesizer" },
  { level: "INFO", timestamp: "2025-07-15 11:50:09", message: "Synthesizing final response." },
  { level: "INFO", timestamp: "2025-07-15 11:50:10", message: "Activating node: Final Output" },
  { level: "INFO", timestamp: "2025-07-15 11:50:10", message: "Streaming response to user." },
  {
    level: "ERROR",
    timestamp: "2025-07-15 11:50:11",
    message: "Failed to load user profile image. Using fallback.",
    details: "404 Not Found",
  },
]

const getLogLevelClass = (level: string) => {
  switch (level) {
    case "ERROR":
      return "text-destructive"
    case "WARN":
      return "text-yellow-500"
    default:
      return "text-muted-foreground"
  }
}

export function RunLogsModal() {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" size="icon" className="bg-transparent">
          <FileText size={20} />
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-3xl h-[70vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Run Logs</DialogTitle>
        </DialogHeader>
        <ScrollArea className="flex-1 bg-muted/50 rounded-md p-2">
          <div className="p-2 font-mono text-xs">
            {logs.map((log, index) => (
              <div key={index} className="flex items-start gap-2 mb-1">
                <span className="text-muted-foreground">{log.timestamp}</span>
                <span className={cn("font-bold w-12 flex-shrink-0", getLogLevelClass(log.level))}>[{log.level}]</span>
                <p className="flex-1 whitespace-pre-wrap break-words">{log.message}</p>
              </div>
            ))}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  )
}
