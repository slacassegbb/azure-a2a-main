"use client"

import { useState, useEffect, useCallback } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Badge } from "@/components/ui/badge"
import { Trash2, Download, Eye, ExternalLink } from "lucide-react"
import { useEventHub } from "@/hooks/use-event-hub"

interface FileRecord {
  id: string
  filename: string
  originalName: string
  size: number
  contentType: string
  uploadedAt: Date
  uri: string
}

interface FileHistoryProps {
  className?: string
  onFileSelect?: (file: FileRecord) => void
}

const SESSION_ID_KEY = 'backendSessionId'

export function FileHistory({ className, onFileSelect }: FileHistoryProps) {
  const [files, setFiles] = useState<FileRecord[]>([])
  const { subscribe, unsubscribe } = useEventHub()

  // Handle backend session changes - clear file history when backend restarts
  useEffect(() => {
    const handleSessionStarted = (data: any) => {
      const newSessionId = data?.sessionId
      if (!newSessionId) return
      
      const storedSessionId = localStorage.getItem(SESSION_ID_KEY)
      
      if (storedSessionId && storedSessionId !== newSessionId) {
        // Backend restarted - clear file history
        console.log('[FileHistory] Backend restarted (session changed), clearing file history')
        console.log('[FileHistory] Old session:', storedSessionId?.slice(0, 8), '-> New session:', newSessionId.slice(0, 8))
        setFiles([])
        localStorage.removeItem('uploadedFilesHistory')
      }
      
      // Store the new session ID
      localStorage.setItem(SESSION_ID_KEY, newSessionId)
      console.log('[FileHistory] Session ID stored:', newSessionId.slice(0, 8))
    }

    subscribe('session_started', handleSessionStarted)
    
    return () => {
      unsubscribe('session_started', handleSessionStarted)
    }
  }, [subscribe, unsubscribe])

  // Load files from localStorage on mount and validate they still exist
  useEffect(() => {
    const savedFiles = localStorage.getItem('uploadedFilesHistory')
    if (savedFiles) {
      try {
        const parsedFiles = JSON.parse(savedFiles).map((file: any) => ({
          ...file,
          uploadedAt: new Date(file.uploadedAt)
        }))
        
        // Deduplicate loaded files by filename only (keep most recent)
        const seenFiles = new Map<string, FileRecord>()
        const deduplicatedFiles: FileRecord[] = []
        
        for (const file of parsedFiles) {
          const key = file.filename
          
          // Only keep the most recent version of each filename
          if (!seenFiles.has(key)) {
            seenFiles.set(key, file)
            deduplicatedFiles.push(file)
          } else {
            // If we've seen this filename before, keep the newer one
            const existing = seenFiles.get(key)!
            if (file.uploadedAt > existing.uploadedAt) {
              // Replace with newer file
              const index = deduplicatedFiles.indexOf(existing)
              deduplicatedFiles[index] = file
              seenFiles.set(key, file)
              console.log('[FileHistory] Replaced older duplicate:', file.filename)
            } else {
              console.log('[FileHistory] Removed duplicate from localStorage:', file.filename)
            }
          }
        }
        
        setFiles(deduplicatedFiles)
        console.log('[FileHistory] Loaded', deduplicatedFiles.length, 'unique files from localStorage (removed', parsedFiles.length - deduplicatedFiles.length, 'duplicates)')
      } catch (error) {
        console.error('Error loading file history:', error)
        // Clear corrupted data
        localStorage.removeItem('uploadedFilesHistory')
      }
    }
  }, [])

  // Save files to localStorage whenever files change
  useEffect(() => {
    localStorage.setItem('uploadedFilesHistory', JSON.stringify(files))
  }, [files])

  // Function to add a new file to history (will be called from parent)
  // Use useCallback to prevent recreating the function on every render
  const addFileToHistory = useCallback((fileData: any) => {
    const fileRecord: FileRecord = {
      id: fileData.file_id || Date.now().toString(),
      filename: fileData.filename,
      originalName: fileData.filename,
      size: fileData.size || 0,
      contentType: fileData.content_type || '',
      uploadedAt: new Date(),
      uri: fileData.uri || ''
    }

    // Deduplicate by filename only - replace if same filename exists
    setFiles(prev => {
      // Check if file with same filename already exists
      const existingIndex = prev.findIndex(f => f.filename === fileRecord.filename)
      
      if (existingIndex !== -1) {
        // Replace existing file with new version (more recent upload)
        console.log('[FileHistory] Replacing existing file:', fileRecord.filename)
        const updated = [...prev]
        updated[existingIndex] = fileRecord
        // Move it to the front (most recent)
        updated.splice(existingIndex, 1)
        return [fileRecord, ...updated].slice(0, 50)
      }
      
      // Add new file and keep last 50
      console.log('[FileHistory] Adding new file:', fileRecord.filename)
      return [fileRecord, ...prev].slice(0, 50)
    })
  }, []) // Empty deps - setFiles is stable

  // Expose the function globally so chat-panel can call it
  useEffect(() => {
    (window as any).addFileToHistory = addFileToHistory
  }, [addFileToHistory])

  const removeFile = (fileId: string) => {
    setFiles(prev => prev.filter(file => file.id !== fileId))
  }

  const clearHistory = () => {
    setFiles([])
  }

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

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
  }

  const formatDate = (date: Date) => {
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    const days = Math.floor(diff / (1000 * 60 * 60 * 24))
    
    if (days === 0) {
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    } else if (days === 1) {
      return 'Yesterday'
    } else if (days < 7) {
      return `${days} days ago`
    } else {
      return date.toLocaleDateString()
    }
  }

  return (
    <Card className={className}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">File History</CardTitle>
          <Badge variant="secondary">{files.length}</Badge>
        </div>
        <CardDescription className="text-xs">
          Uploaded files across all conversations
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {files.length === 0 ? (
          <div className="text-center text-xs text-muted-foreground py-4">
            No files uploaded yet
          </div>
        ) : (
          <>
            <ScrollArea className="h-48">
              <div className="space-y-2">
                {files.map((file, index) => {
                  // Check if file is an image
                  const isImage = file.contentType.startsWith('image/') || 
                    ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'].includes(
                      file.filename.toLowerCase().split('.').pop() || ''
                    )
                  
                  return (
                    <div key={file.id}>
                      <div className="flex items-start gap-2 p-2 rounded-md hover:bg-gray-50 transition-colors">
                        {/* Show thumbnail for images, icon for other files */}
                        {isImage && file.uri ? (
                          <div className="flex-shrink-0 w-10 h-10 rounded overflow-hidden border border-gray-200 bg-gray-100">
                            <img 
                              src={file.uri} 
                              alt={file.originalName}
                              className="w-full h-full object-cover"
                              onError={(e) => {
                                // Fallback to emoji if image fails to load
                                e.currentTarget.style.display = 'none'
                                e.currentTarget.parentElement!.innerHTML = '<span class="flex items-center justify-center w-full h-full text-sm">🖼️</span>'
                              }}
                            />
                          </div>
                        ) : (
                          <span className="text-sm mt-0.5">{getFileIcon(file.filename, file.contentType)}</span>
                        )}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1">
                            {file.uri ? (
                              <a
                                href={file.uri}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs font-medium truncate hover:underline hover:text-blue-600 flex items-center gap-1 group"
                                title={`${file.originalName} - Click to open in new tab`}
                              >
                                <span className="truncate">{file.originalName}</span>
                                <ExternalLink size={10} className="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
                              </a>
                            ) : (
                              <span className="text-xs font-medium truncate" title={file.originalName}>
                                {file.originalName}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2 mt-1">
                            <span className="text-xs text-muted-foreground">
                              {formatFileSize(file.size)}
                            </span>
                            <span className="text-xs text-muted-foreground">
                              {formatDate(file.uploadedAt)}
                            </span>
                          </div>
                        </div>
                        <div className="flex gap-1">
                          {onFileSelect && (
                            <button
                              onClick={() => onFileSelect(file)}
                              className="p-1 hover:bg-gray-200 rounded text-muted-foreground hover:text-foreground"
                              title="View file"
                            >
                              <Eye size={12} />
                            </button>
                          )}
                          <button
                            onClick={() => removeFile(file.id)}
                            className="p-1 hover:bg-gray-200 rounded text-muted-foreground hover:text-destructive"
                            title="Remove from history"
                          >
                            <Trash2 size={12} />
                          </button>
                        </div>
                      </div>
                      {index < files.length - 1 && <Separator className="my-1" />}
                    </div>
                  )
                })}
              </div>
            </ScrollArea>
          </>
        )}
      </CardContent>
    </Card>
  )
}
