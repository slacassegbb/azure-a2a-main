"use client"

import { useState, useEffect, useCallback } from "react"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Trash2 } from "lucide-react"
import { useEventHub } from "@/hooks/use-event-hub"
import { getOrCreateSessionId } from "@/lib/session"

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
  onFilesLoaded?: (count: number) => void
}

const SESSION_ID_KEY = 'backendSessionId'

export function FileHistory({ className, onFileSelect, onFilesLoaded }: FileHistoryProps) {
  const [files, setFiles] = useState<FileRecord[]>([])
  const { subscribe, unsubscribe } = useEventHub()
  
  // Track current session ID for collaborative session support
  const [currentSessionId, setCurrentSessionId] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      return getOrCreateSessionId()
    }
    return ''
  })

  // Handle backend session changes - clear file history when backend restarts
  useEffect(() => {
    const handleSessionStarted = (data: any) => {
      const newSessionId = data?.sessionId
      if (!newSessionId) return
      
      const storedSessionId = localStorage.getItem(SESSION_ID_KEY)
      
      if (storedSessionId && storedSessionId !== newSessionId) {
        // Backend restarted - clear file history for old session
        console.log('[FileHistory] Backend restarted (session changed), clearing file history')
        console.log('[FileHistory] Old session:', storedSessionId?.slice(0, 8), '-> New session:', newSessionId.slice(0, 8))
        setFiles([])
        // Note: We no longer clear localStorage here since each session has its own key
      }
      
      // Store the new session ID
      localStorage.setItem(SESSION_ID_KEY, newSessionId)
      console.log('[FileHistory] Session ID stored:', newSessionId.slice(0, 8))
    }

    // Handle session members updated - fires when we join a collaborative session
    const handleSessionMembersUpdated = (data: any) => {
      console.log('[FileHistory] Session members updated:', data)
      const newSessionId = getOrCreateSessionId()
      setCurrentSessionId(prev => {
        if (prev !== newSessionId) {
          console.log('[FileHistory] Session ID changed after members update:', prev, '->', newSessionId)
          return newSessionId
        }
        return prev
      })
    }

    subscribe('session_started', handleSessionStarted)
    subscribe('session_members_updated', handleSessionMembersUpdated)
    
    return () => {
      unsubscribe('session_started', handleSessionStarted)
      unsubscribe('session_members_updated', handleSessionMembersUpdated)
    }
  }, [subscribe, unsubscribe])

  // Load files from backend API on mount
  useEffect(() => {
    const loadFilesFromBackend = async () => {
      try {
        const sessionId = getOrCreateSessionId()
        const backendUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
        
        console.log('[FileHistory] Loading files from backend for session:', sessionId.slice(0, 8), 'URL:', backendUrl)
        
        const response = await fetch(`${backendUrl}/api/files`, {
          headers: {
            'X-Session-ID': sessionId
          }
        })
        
        if (!response.ok) {
          throw new Error(`Failed to load files: ${response.statusText}`)
        }
        
        const data = await response.json()
        
        if (data.success && data.files) {
          const loadedFiles = data.files.map((file: any) => ({
            ...file,
            uploadedAt: file.uploadedAt ? new Date(file.uploadedAt) : new Date()
          }))
          
          // Sort by upload date (most recent first)
          loadedFiles.sort((a: FileRecord, b: FileRecord) => 
            b.uploadedAt.getTime() - a.uploadedAt.getTime()
          )
          
          setFiles(loadedFiles)
          console.log('[FileHistory] Loaded', loadedFiles.length, 'files from backend')
          
          // Notify parent about loaded files count
          if (onFilesLoaded) {
            onFilesLoaded(loadedFiles.length)
          }
        } else {
          console.warn('[FileHistory] No files returned from backend:', data.error || 'Unknown error')
          if (onFilesLoaded) {
            onFilesLoaded(0)
          }
        }
      } catch (error) {
        console.error('[FileHistory] Error loading files from backend:', error)
        // Continue with empty files list
        if (onFilesLoaded) {
          onFilesLoaded(0)
        }
      }
    }
    
    loadFilesFromBackend()
  }, [onFilesLoaded, currentSessionId])  // Reload when session changes (joining collaborative session)

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
      return { icon: '🖼️', gradient: 'from-blue-500/20 to-cyan-500/20' }
    } else if (type.startsWith('audio/') || ['mp3', 'wav', 'm4a', 'flac', 'aac'].includes(ext)) {
      return { icon: '🎵', gradient: 'from-pink-500/20 to-rose-500/20' }
    } else if (type.startsWith('video/') || ['mp4', 'mov', 'avi', 'mkv', 'webm'].includes(ext)) {
      return { icon: '🎥', gradient: 'from-purple-500/20 to-blue-500/20' }
    } else if (type === 'application/pdf' || ext === 'pdf') {
      return { icon: '📄', gradient: 'from-red-500/20 to-orange-500/20' }
    } else if (['doc', 'docx'].includes(ext)) {
      return { icon: '📝', gradient: 'from-blue-500/20 to-indigo-500/20' }
    } else if (['xls', 'xlsx'].includes(ext)) {
      return { icon: '📊', gradient: 'from-green-500/20 to-emerald-500/20' }
    } else if (['ppt', 'pptx'].includes(ext)) {
      return { icon: '📽️', gradient: 'from-orange-500/20 to-amber-500/20' }
    } else if (['txt', 'md'].includes(ext)) {
      return { icon: '📋', gradient: 'from-slate-500/20 to-gray-500/20' }
    } else if (['zip', 'rar', '7z', 'tar', 'gz'].includes(ext)) {
      return { icon: '📦', gradient: 'from-amber-500/20 to-yellow-500/20' }
    } else if (['js', 'ts', 'py', 'java', 'c', 'cpp', 'cs', 'go', 'rs', 'rb'].includes(ext)) {
      return { icon: '💻', gradient: 'from-violet-500/20 to-purple-500/20' }
    } else if (['json', 'xml', 'yaml', 'yml', 'toml'].includes(ext)) {
      return { icon: '⚙️', gradient: 'from-teal-500/20 to-cyan-500/20' }
    } else if (['html', 'css', 'scss', 'sass'].includes(ext)) {
      return { icon: '🌐', gradient: 'from-sky-500/20 to-blue-500/20' }
    } else {
      return { icon: '📄', gradient: 'from-gray-500/20 to-slate-500/20' }
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
    <div className={`${className}`}>
      <div className="pt-3 px-2 space-y-2">
        {files.length === 0 ? (
          <div className="text-center text-xs text-muted-foreground py-4">
            No files uploaded yet
          </div>
        ) : (
          <ScrollArea className="h-56">
            <div className="space-y-1">
              {files.map((file) => {
                // Check if file is an image
                const isImage = file.contentType.startsWith('image/') || 
                  ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'].includes(
                    file.filename.toLowerCase().split('.').pop() || ''
                  )
                
                // Get file icon and gradient for non-image files
                const fileStyle = getFileIcon(file.filename, file.contentType)
                
                return (
                  <div key={file.id}>
                    <div className="flex items-center gap-3 p-2 rounded-lg hover:bg-muted/50 transition-colors group cursor-pointer"
                         onClick={() => file.uri && window.open(file.uri, '_blank')}>
                      {/* Show thumbnail for images, styled icon for other files */}
                      {isImage && file.uri ? (
                        <div className="flex-shrink-0 w-12 h-12 rounded-lg overflow-hidden border border-border/50">
                          <img 
                            src={file.uri} 
                            alt={file.originalName}
                            className="w-full h-full object-cover"
                            onError={(e) => {
                              // Fallback to gradient with emoji if image fails to load
                              e.currentTarget.style.display = 'none'
                              e.currentTarget.parentElement!.innerHTML = '<div class="w-full h-full flex items-center justify-center bg-gradient-to-br from-blue-500/20 to-cyan-500/20"><span class="text-xl">🖼️</span></div>'
                            }}
                          />
                        </div>
                      ) : (
                        <div className={`flex-shrink-0 w-12 h-12 rounded-lg flex items-center justify-center bg-gradient-to-br ${fileStyle.gradient} border border-border/50`}>
                          <span className="text-xl">{fileStyle.icon}</span>
                        </div>
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium truncate text-foreground group-hover:text-primary transition-colors" title={file.originalName}>
                          {file.originalName}
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="text-xs text-muted-foreground">
                            {formatFileSize(file.size)}
                          </span>
                          <span className="text-xs text-muted-foreground">•</span>
                          <span className="text-xs text-muted-foreground">
                            {formatDate(file.uploadedAt)}
                          </span>
                        </div>
                      </div>
                      <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            removeFile(file.id)
                          }}
                          className="p-1.5 hover:bg-destructive/10 rounded-md text-muted-foreground hover:text-destructive transition-colors"
                          title="Remove from history"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </ScrollArea>
        )}
      </div>
    </div>
  )
}
