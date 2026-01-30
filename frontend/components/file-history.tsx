"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import { Button } from "@/components/ui/button"
import { Trash2, Plus, Loader2, Database, AlertCircle, FileSearch } from "lucide-react"
import { useEventHub } from "@/hooks/use-event-hub"
import { getOrCreateSessionId } from "@/lib/session"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"

// Processing status for files
type FileStatus = 'uploading' | 'processing' | 'analyzed' | 'uploaded' | 'error' | undefined

interface FileRecord {
  id: string
  filename: string
  originalName: string
  size: number
  contentType: string
  uploadedAt: Date
  uri: string
  status?: FileStatus  // Processing status
  error?: string       // Error message if status is 'error'
}

interface FileHistoryProps {
  className?: string
  onFileSelect?: (file: FileRecord) => void
  onFilesLoaded?: (count: number) => void
  conversationId?: string  // For broadcasting to collaborative sessions
}

const SESSION_ID_KEY = 'backendSessionId'

export function FileHistory({ className, onFileSelect, onFilesLoaded, conversationId }: FileHistoryProps) {
  const [files, setFiles] = useState<FileRecord[]>([])
  const { subscribe, unsubscribe, sendMessage } = useEventHub()
  const fileInputRef = useRef<HTMLInputElement>(null)
  
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

  // Handle shared file uploads from collaborative session members
  useEffect(() => {
    const handleSharedFileUploaded = (data: any) => {
      console.log('[FileHistory] Shared file uploaded from session member:', data)
      const fileInfo = data?.fileInfo
      if (!fileInfo) return

      // Add to files list if not already present
      setFiles(prev => {
        const exists = prev.some(f => f.id === fileInfo.id)
        if (exists) {
          // Update existing file
          return prev.map(f => f.id === fileInfo.id ? {
            ...f,
            ...fileInfo,
            uploadedAt: fileInfo.uploadedAt ? new Date(fileInfo.uploadedAt) : f.uploadedAt,
            status: fileInfo.status || f.status
          } : f)
        }
        // Add new file
        const newFile: FileRecord = {
          id: fileInfo.id,
          filename: fileInfo.filename,
          originalName: fileInfo.originalName || fileInfo.filename,
          size: fileInfo.size || 0,
          contentType: fileInfo.contentType || 'application/octet-stream',
          uploadedAt: fileInfo.uploadedAt ? new Date(fileInfo.uploadedAt) : new Date(),
          uri: fileInfo.uri || '',
          status: (fileInfo.status as FileStatus) || 'uploaded'  // Use provided status or default to 'uploaded'
        }
        return [newFile, ...prev]
      })
    }

    const handleFileProcessingCompleted = (data: any) => {
      console.log('[FileHistory] File processing completed:', data)
      const { fileId, status } = data
      if (!fileId) return

      setFiles(prev => prev.map(f => 
        f.id === fileId ? { ...f, status: status as FileStatus } : f
      ))
    }

    subscribe('shared_file_uploaded', handleSharedFileUploaded)
    subscribe('file_processing_completed', handleFileProcessingCompleted)

    return () => {
      unsubscribe('shared_file_uploaded', handleSharedFileUploaded)
      unsubscribe('file_processing_completed', handleFileProcessingCompleted)
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
            uploadedAt: file.uploadedAt ? new Date(file.uploadedAt) : new Date(),
            status: (file.status as FileStatus) || 'uploaded'  // Use status from backend, default to 'uploaded'
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
      uri: fileData.uri || '',
      status: (fileData.status as FileStatus) || 'uploaded'  // Use provided status or default to 'uploaded'
    }

    // Deduplicate by filename only - replace if same filename exists
    setFiles(prev => {
      // Check if file with same filename already exists
      const existingIndex = prev.findIndex(f => f.filename === fileRecord.filename)
      
      if (existingIndex !== -1) {
        const existingFile = prev[existingIndex]
        
        // IMPORTANT: Preserve advanced status (processing, analyzed) - don't let late events overwrite
        // Status priority: analyzed > processing > error > uploading > uploaded
        const statusPriority: Record<string, number> = {
          'analyzed': 5,
          'processing': 4,
          'error': 3,
          'uploading': 2,
          'uploaded': 1
        }
        const existingPriority = statusPriority[existingFile.status || 'uploaded'] || 0
        const newPriority = statusPriority[fileRecord.status || 'uploaded'] || 0
        
        // Only update status if new status has higher priority
        const preservedStatus = newPriority >= existingPriority ? fileRecord.status : existingFile.status
        
        console.log('[FileHistory] Replacing existing file:', fileRecord.filename, 
          'existingStatus:', existingFile.status, 'newStatus:', fileRecord.status, 'preserved:', preservedStatus)
        
        const updated = [...prev]
        updated[existingIndex] = { ...fileRecord, status: preservedStatus }
        // Move it to the front (most recent)
        updated.splice(existingIndex, 1)
        return [{ ...fileRecord, status: preservedStatus }, ...updated].slice(0, 50)
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

  const removeFile = async (fileId: string) => {
    // Optimistically remove from UI
    setFiles(prev => prev.filter(file => file.id !== fileId))
    
    // Try to delete from backend (blob storage + local filesystem)
    try {
      const sessionId = getOrCreateSessionId()
      const backendUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
      
      const response = await fetch(`${backendUrl}/api/files/${fileId}`, {
        method: 'DELETE',
        headers: {
          'X-Session-ID': sessionId
        }
      })
      
      const data = await response.json()
      
      if (data.success) {
        console.log('[FileHistory] File deleted:', data.message)
      } else {
        console.warn('[FileHistory] File delete returned error (but UI already updated):', data.error)
      }
    } catch (error) {
      // Don't show error to user - file is already removed from UI
      // This is expected for expired/missing files
      console.log('[FileHistory] File delete request failed (this is OK for expired files):', error)
    }
  }

  // Process an existing file (analyze and add to memory)
  const processFile = async (file: FileRecord) => {
    const sessionId = getOrCreateSessionId()
    const backendUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
    
    // Update status to processing
    setFiles(prev => prev.map(f => 
      f.id === file.id ? { ...f, status: 'processing' as FileStatus } : f
    ))
    
    try {
      console.log('[FileHistory] Starting document processing for:', file.filename)
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 120000) // 2 minute timeout
      
      const processResponse = await fetch(`${backendUrl}/api/files/process`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Session-ID': sessionId
        },
        body: JSON.stringify({
          file_id: file.id,
          filename: file.filename,
          uri: file.uri,
          content_type: file.contentType,
          size: file.size
        }),
        signal: controller.signal
      })
      clearTimeout(timeoutId)
      
      console.log('[FileHistory] Processing response status:', processResponse.status)
      const processResult = await processResponse.json()
      console.log('[FileHistory] Processing result:', processResult)

      if (processResult.success) {
        // Update status to 'analyzed'
        setFiles(prev => prev.map(f => 
          f.id === file.id ? { ...f, status: 'analyzed' as FileStatus } : f
        ))
        console.log('[FileHistory] Document processing completed:', file.filename)

        // Broadcast status update
        if (sendMessage) {
          sendMessage({
            type: "file_processing_completed",
            conversationId: conversationId || sessionId,
            fileId: file.id,
            status: 'analyzed'
          })
        }
      } else {
        // Processing failed
        setFiles(prev => prev.map(f => 
          f.id === file.id ? { ...f, status: 'error' as FileStatus, error: processResult.error } : f
        ))
        console.warn('[FileHistory] Document processing failed:', processResult.error)
      }
    } catch (processError: any) {
      const isTimeout = processError?.name === 'AbortError'
      const errorMessage = isTimeout ? 'Processing timeout (>2min)' : 'Processing failed'
      console.error('[FileHistory] Document processing request failed:', processError?.message || processError)
      setFiles(prev => prev.map(f => 
        f.id === file.id ? { ...f, status: 'error' as FileStatus, error: errorMessage } : f
      ))
    }
  }

  const clearAllFiles = async () => {
    // Optimistically clear UI
    const filesToDelete = [...files]
    setFiles([])
    
    // Try to delete all files from backend
    try {
      const sessionId = getOrCreateSessionId()
      const backendUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
      
      // Delete all files in parallel
      const deletePromises = filesToDelete.map(file =>
        fetch(`${backendUrl}/api/files/${file.id}`, {
          method: 'DELETE',
          headers: {
            'X-Session-ID': sessionId
          }
        })
        .then(res => res.json())
        .catch(err => {
          console.log(`[FileHistory] Failed to delete ${file.filename}:`, err)
          return { success: true } // Treat as success
        })
      )
      
      const results = await Promise.all(deletePromises)
      const successCount = results.filter(r => r.success).length
      console.log(`[FileHistory] Cleared ${successCount}/${filesToDelete.length} files`)
      
    } catch (error) {
      console.log('[FileHistory] Clear all failed (but UI already updated):', error)
    }
  }

  // Upload files with document processing
  const uploadFiles = async (fileList: FileList | File[]) => {
    if (!fileList || fileList.length === 0) return

    const sessionId = getOrCreateSessionId()
    const backendUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'

    for (let i = 0; i < fileList.length; i++) {
      const file = fileList[i]
      const tempId = `temp_${Date.now()}_${i}`

      // Add file to UI immediately with 'uploading' status
      const tempRecord: FileRecord = {
        id: tempId,
        filename: file.name,
        originalName: file.name,
        size: file.size,
        contentType: file.type || 'application/octet-stream',
        uploadedAt: new Date(),
        uri: '',
        status: 'uploading'
      }
      setFiles(prev => [tempRecord, ...prev])

      try {
        // Upload to backend
        const formData = new FormData()
        formData.append('file', file)

        const uploadResponse = await fetch(`${backendUrl}/upload`, {
          method: 'POST',
          headers: {
            'X-Session-ID': sessionId
          },
          body: formData
        })

        const uploadResult = await uploadResponse.json()

        if (uploadResult.success) {
          // Update file record with real data and change status to 'processing'
          const realRecord: FileRecord = {
            id: uploadResult.file_id,
            filename: uploadResult.filename,
            originalName: uploadResult.filename,
            size: uploadResult.size || file.size,
            contentType: uploadResult.content_type || file.type,
            uploadedAt: new Date(),
            uri: uploadResult.uri,
            status: 'processing'
          }

          // Replace temp record with real record
          setFiles(prev => prev.map(f => f.id === tempId ? realRecord : f))

          // NOTE: Don't call addFileToHistory here - we already added via setFiles above
          // addFileToHistory would overwrite with status='uploaded' and break the processing flow

          // Broadcast to collaborative session members
          if (sendMessage) {
            sendMessage({
              type: "shared_file_uploaded",
              conversationId: conversationId || sessionId,
              fileInfo: {
                id: uploadResult.file_id,
                filename: uploadResult.filename,
                originalName: uploadResult.filename,
                size: uploadResult.size || file.size,
                contentType: uploadResult.content_type || file.type,
                uri: uploadResult.uri,
                uploadedAt: new Date().toISOString(),
                status: 'processing'
              }
            })
          }

          // Trigger document processing with timeout
          try {
            console.log('[FileHistory] Starting document processing for:', uploadResult.filename)
            const controller = new AbortController()
            const timeoutId = setTimeout(() => controller.abort(), 120000) // 2 minute timeout
            
            const processResponse = await fetch(`${backendUrl}/api/files/process`, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-Session-ID': sessionId
              },
              body: JSON.stringify({
                file_id: uploadResult.file_id,
                filename: uploadResult.filename,
                uri: uploadResult.uri,
                content_type: uploadResult.content_type || file.type,
                size: uploadResult.size || file.size
              }),
              signal: controller.signal
            })
            clearTimeout(timeoutId)
            
            console.log('[FileHistory] Processing response status:', processResponse.status)
            const processResult = await processResponse.json()
            console.log('[FileHistory] Processing result:', processResult)

            if (processResult.success) {
              // Update status to 'analyzed'
              setFiles(prev => prev.map(f => 
                f.id === uploadResult.file_id ? { ...f, status: 'analyzed' as FileStatus } : f
              ))
              console.log('[FileHistory] Document processing completed:', uploadResult.filename)

              // Broadcast status update
              if (sendMessage) {
                sendMessage({
                  type: "file_processing_completed",
                  conversationId: conversationId || sessionId,
                  fileId: uploadResult.file_id,
                  status: 'analyzed'
                })
              }
            } else {
              // Processing failed but file is uploaded
              setFiles(prev => prev.map(f => 
                f.id === uploadResult.file_id ? { ...f, status: 'error' as FileStatus, error: processResult.error } : f
              ))
              console.warn('[FileHistory] Document processing failed:', processResult.error)
            }
          } catch (processError: any) {
            // Processing request failed but file is uploaded
            const isTimeout = processError?.name === 'AbortError'
            const errorMessage = isTimeout ? 'Processing timeout (>2min)' : 'Processing failed'
            console.error('[FileHistory] Document processing request failed:', processError?.message || processError)
            setFiles(prev => prev.map(f => 
              f.id === uploadResult.file_id ? { ...f, status: 'error' as FileStatus, error: errorMessage } : f
            ))
          }

        } else {
          // Upload failed - update to error status
          setFiles(prev => prev.map(f => 
            f.id === tempId ? { ...f, status: 'error' as FileStatus, error: uploadResult.error } : f
          ))
          console.error('[FileHistory] File upload failed:', uploadResult.error)
        }
      } catch (error) {
        // Network error
        setFiles(prev => prev.map(f => 
          f.id === tempId ? { ...f, status: 'error' as FileStatus, error: 'Upload failed' } : f
        ))
        console.error('[FileHistory] File upload error:', error)
      }
    }
  }

  const handleFileInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files
    if (files && files.length > 0) {
      uploadFiles(files)
    }
    // Reset input so same file can be selected again
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
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

  // Helper to render status indicator
  const renderStatusIndicator = (file: FileRecord) => {
    switch (file.status) {
      case 'uploading':
        return (
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="absolute -top-1 -right-1 bg-background rounded-full p-0.5 cursor-help">
                <Loader2 className="w-3 h-3 text-blue-500 animate-spin" />
              </div>
            </TooltipTrigger>
            <TooltipContent side="top">
              <p>Uploading...</p>
            </TooltipContent>
          </Tooltip>
        )
      case 'processing':
        return (
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="absolute -top-1 -right-1 bg-background rounded-full p-0.5 cursor-help">
                <Loader2 className="w-3 h-3 text-amber-500 animate-spin" />
              </div>
            </TooltipTrigger>
            <TooltipContent side="top">
              <p>Processing document...</p>
            </TooltipContent>
          </Tooltip>
        )
      case 'error':
        return (
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="absolute -top-1 -right-1 bg-background rounded-full p-0.5 cursor-help">
                <AlertCircle className="w-3 h-3 text-destructive" />
              </div>
            </TooltipTrigger>
            <TooltipContent side="top">
              <p>Error processing file</p>
            </TooltipContent>
          </Tooltip>
        )
      case 'uploaded':
        // File is in storage but not yet processed - show analyze button as indicator
        return (
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  processFile(file)
                }}
                className="absolute -top-1.5 -right-1.5 bg-primary hover:bg-primary/80 rounded-full p-1 text-primary-foreground shadow-sm transition-colors cursor-pointer"
              >
                <FileSearch className="w-3.5 h-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top">
              <p>Click to analyze & add to memory</p>
            </TooltipContent>
          </Tooltip>
        )
      case 'analyzed':
        return (
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="absolute -top-1 -right-1 bg-background rounded-full p-0.5 cursor-help">
                <Database className="w-3 h-3 text-green-500" />
              </div>
            </TooltipTrigger>
            <TooltipContent side="top">
              <p>In Memory</p>
            </TooltipContent>
          </Tooltip>
        )
      default:
        // No indicator for undefined status
        return null
    }
  }

  return (
    <TooltipProvider delayDuration={0}>
    <div className={`${className}`}>
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        onChange={handleFileInputChange}
        className="hidden"
        accept="*/*"
      />
      
      <div className="pt-3 px-3 space-y-2">
        {/* Header with count, add button, and clear all */}
        <div className="flex items-center pb-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-muted-foreground">
              {files.length} {files.length === 1 ? 'file' : 'files'}
            </span>
            <button
              onClick={() => fileInputRef.current?.click()}
              className="p-1 rounded-full bg-primary/10 hover:bg-primary/20 text-primary transition-colors cursor-pointer"
              title="Upload files"
            >
              <Plus className="w-4 h-4" />
            </button>
          </div>
          {files.length > 0 && (
            <button
              onClick={clearAllFiles}
              className="text-xs font-medium text-muted-foreground hover:text-destructive transition-colors ml-auto"
              title="Clear all files"
            >
              Clear All
            </button>
          )}
        </div>
        
        {files.length === 0 ? (
          <div 
            className="text-center text-xs text-muted-foreground py-8 border-2 border-dashed border-muted-foreground/20 rounded-lg cursor-pointer hover:border-primary/50 hover:bg-muted/20 transition-colors"
            onClick={() => fileInputRef.current?.click()}
          >
            <Plus className="w-6 h-6 mx-auto mb-2 text-muted-foreground/50" />
            Click to upload files
          </div>
        ) : (
          <div className="h-56 overflow-y-auto pr-4">
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
                    <div className="flex items-center gap-2 p-2 pr-1 rounded-lg hover:bg-muted/50 transition-colors group cursor-pointer"
                         onClick={() => file.uri && window.open(file.uri, '_blank')}>
                      {/* Thumbnail - no overlay icons */}
                      <div className="flex-shrink-0">
                        {isImage && file.uri ? (
                          <div className="w-10 h-10 rounded-md overflow-hidden border border-border/50">
                            <img 
                              src={file.uri} 
                              alt={file.originalName}
                              className="w-full h-full object-cover"
                              onError={(e) => {
                                e.currentTarget.style.display = 'none'
                                e.currentTarget.parentElement!.innerHTML = '<div class="w-full h-full flex items-center justify-center bg-gradient-to-br from-blue-500/20 to-cyan-500/20"><span class="text-lg">🖼️</span></div>'
                              }}
                            />
                          </div>
                        ) : (
                          <div className={`w-10 h-10 rounded-md flex items-center justify-center bg-gradient-to-br ${fileStyle.gradient} border border-border/50`}>
                            <span className="text-lg">{fileStyle.icon}</span>
                          </div>
                        )}
                      </div>
                      
                      {/* File info - allow it to shrink more */}
                      <div className="flex-1 min-w-0 max-w-[140px]">
                        <div className="text-sm font-medium truncate text-foreground group-hover:text-primary transition-colors" title={file.originalName}>
                          {file.originalName}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {formatFileSize(file.size)} • {formatDate(file.uploadedAt)}
                        </div>
                      </div>
                      
                      {/* Action buttons - inline, always visible - MUST NOT SHRINK */}
                      <div className="flex items-center gap-1 flex-shrink-0 ml-auto">
                        {/* Analyze button for unprocessed files - prominent and clickable */}
                        {(file.status === 'uploaded' || file.status === 'error' || !file.status) && (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  processFile(file)
                                }}
                                className="px-2 py-1 text-xs font-medium bg-primary/10 hover:bg-primary/20 text-primary rounded border border-primary/30 hover:border-primary/50 transition-colors"
                              >
                                Analyze
                              </button>
                            </TooltipTrigger>
                            <TooltipContent side="top">
                              <p>Add to memory for AI context</p>
                            </TooltipContent>
                          </Tooltip>
                        )}
                        {/* In Memory indicator */}
                        {file.status === 'analyzed' && (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <div className="px-2 py-1 text-xs font-medium text-green-500">
                                In Memory
                              </div>
                            </TooltipTrigger>
                            <TooltipContent side="top">
                              <p>Document is loaded in AI context</p>
                            </TooltipContent>
                          </Tooltip>
                        )}
                        {/* Processing indicator */}
                        {file.status === 'processing' && (
                          <div className="p-1.5">
                            <Loader2 size={14} className="text-amber-500 animate-spin" />
                          </div>
                        )}
                        {/* Delete button */}
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                removeFile(file.id)
                              }}
                              className="p-1.5 hover:bg-destructive/10 rounded text-muted-foreground hover:text-destructive transition-colors"
                            >
                              <Trash2 size={14} />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent side="top">
                            <p>Delete</p>
                          </TooltipContent>
                        </Tooltip>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
    </TooltipProvider>
  )
}
