"use client"

import { useState, useRef, useCallback } from 'react'

export interface VoiceRecordingState {
  isRecording: boolean
  isProcessing: boolean
  audioBlob: Blob | null
  duration: number
  error: string | null
}

export function useVoiceRecording() {
  const [state, setState] = useState<VoiceRecordingState>({
    isRecording: false,
    isProcessing: false,
    audioBlob: null,
    duration: 0,
    error: null
  })

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const startTimeRef = useRef<number>(0)
  const durationIntervalRef = useRef<NodeJS.Timeout | null>(null)

  const startRecording = useCallback(async () => {
    try {
      // Clear any previous error
      setState(prev => ({ ...prev, error: null }))

      // Request microphone access
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          sampleRate: 44100
        } 
      })

      console.log('Microphone stream obtained:', stream)
      console.log('Audio tracks:', stream.getAudioTracks())

      // Check if we have audio tracks
      const audioTracks = stream.getAudioTracks()
      if (audioTracks.length === 0) {
        throw new Error('No audio tracks found')
      }

      console.log('Audio track settings:', audioTracks[0].getSettings())

      // Try different MIME types in order of preference
      let mimeType = 'audio/webm;codecs=opus'
      if (!MediaRecorder.isTypeSupported(mimeType)) {
        mimeType = 'audio/webm'
        if (!MediaRecorder.isTypeSupported(mimeType)) {
          mimeType = 'audio/mp4'
          if (!MediaRecorder.isTypeSupported(mimeType)) {
            mimeType = '' // Use default
          }
        }
      }

      console.log('Using MIME type:', mimeType)

      // Create MediaRecorder instance
      const mediaRecorder = new MediaRecorder(stream, 
        mimeType ? { mimeType } : undefined
      )

      mediaRecorderRef.current = mediaRecorder
      audioChunksRef.current = []

      // Set up event handlers
      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data)
        }
      }

      mediaRecorder.onstop = () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm;codecs=opus' })
        setState(prev => ({ 
          ...prev, 
          isRecording: false, 
          audioBlob,
          duration: 0 
        }))

        // Stop all tracks
        stream.getTracks().forEach(track => track.stop())

        // Clear duration interval
        if (durationIntervalRef.current) {
          clearInterval(durationIntervalRef.current)
          durationIntervalRef.current = null
        }
      }

      // Start recording
      mediaRecorder.start(100) // Collect data every 100ms
      startTimeRef.current = Date.now()

      // Update state
      setState(prev => ({ 
        ...prev, 
        isRecording: true, 
        audioBlob: null,
        duration: 0 
      }))

      // Start duration timer
      durationIntervalRef.current = setInterval(() => {
        const elapsed = Math.floor((Date.now() - startTimeRef.current) / 1000)
        setState(prev => ({ ...prev, duration: elapsed }))
      }, 1000)

    } catch (error) {
      console.error('Error starting recording:', error)
      setState(prev => ({ 
        ...prev, 
        error: error instanceof Error ? error.message : 'Failed to start recording' 
      }))
    }
  }, [])

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && state.isRecording) {
      mediaRecorderRef.current.stop()
    }
  }, [state.isRecording])

  const convertToWav = useCallback(async (webmBlob: Blob): Promise<Blob> => {
    return new Promise((resolve, reject) => {
      const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)()
      const fileReader = new FileReader()

      fileReader.onload = async () => {
        try {
          const arrayBuffer = fileReader.result as ArrayBuffer
          const audioBuffer = await audioContext.decodeAudioData(arrayBuffer)
          
          // Convert to WAV
          const wavBlob = bufferToWave(audioBuffer, audioBuffer.length)
          resolve(wavBlob)
        } catch (error) {
          reject(error)
        }
      }

      fileReader.onerror = () => reject(new Error('Failed to read audio file'))
      fileReader.readAsArrayBuffer(webmBlob)
    })
  }, [])

  const uploadAndTranscribe = useCallback(async (audioBlob: Blob) => {
    setState(prev => ({ ...prev, isProcessing: true, error: null }))

    try {
      // Convert WebM to WAV
      const wavBlob = await convertToWav(audioBlob)
      
      // Create form data
      const formData = new FormData()
      const filename = `voice_recording_${Date.now()}.wav`
      formData.append('file', wavBlob, filename)

      // Upload to backend
      const response = await fetch('/api/upload-voice', {
        method: 'POST',
        body: formData
      })

      if (!response.ok) {
        throw new Error(`Upload failed: ${response.statusText}`)
      }

      const result = await response.json()
      
      if (!result.success) {
        throw new Error(result.error || 'Upload failed')
      }

      setState(prev => ({ ...prev, isProcessing: false }))
      return result

    } catch (error) {
      console.error('Error uploading and transcribing:', error)
      setState(prev => ({ 
        ...prev, 
        isProcessing: false,
        error: error instanceof Error ? error.message : 'Failed to process recording'
      }))
      throw error
    }
  }, [convertToWav])

  const reset = useCallback(() => {
    setState({
      isRecording: false,
      isProcessing: false,
      audioBlob: null,
      duration: 0,
      error: null
    })
    
    if (durationIntervalRef.current) {
      clearInterval(durationIntervalRef.current)
      durationIntervalRef.current = null
    }
  }, [])

  return {
    ...state,
    startRecording,
    stopRecording,
    uploadAndTranscribe,
    reset
  }
}

// Helper function to convert AudioBuffer to WAV format
function bufferToWave(abuffer: AudioBuffer, len: number): Blob {
  const numOfChan = abuffer.numberOfChannels
  const length = len * numOfChan * 2 + 44
  const buffer = new ArrayBuffer(length)
  const view = new DataView(buffer)
  const channels = []
  let sample
  let offset = 0
  let pos = 0

  // write WAVE header
  setUint32(0x46464952) // "RIFF"
  setUint32(length - 8) // file length - 8
  setUint32(0x45564157) // "WAVE"

  setUint32(0x20746d66) // "fmt " chunk
  setUint32(16) // length = 16
  setUint16(1) // PCM (uncompressed)
  setUint16(numOfChan)
  setUint32(abuffer.sampleRate)
  setUint32(abuffer.sampleRate * 2 * numOfChan) // avg. bytes/sec
  setUint16(numOfChan * 2) // block-align
  setUint16(16) // 16-bit (hardcoded in this demo)

  setUint32(0x61746164) // "data" - chunk
  setUint32(length - pos - 4) // chunk length

  // write interleaved data
  for (let i = 0; i < abuffer.numberOfChannels; i++)
    channels.push(abuffer.getChannelData(i))

  while (pos < length) {
    for (let i = 0; i < numOfChan; i++) {
      // interleave channels
      sample = Math.max(-1, Math.min(1, channels[i][offset])) // clamp
      sample = (0.5 + sample < 0 ? sample * 32768 : sample * 32767) | 0 // scale to 16-bit signed int
      view.setInt16(pos, sample, true) // write 16-bit sample
      pos += 2
    }
    offset++ // next source sample
  }

  // create Blob
  return new Blob([buffer], { type: 'audio/wav' })

  function setUint16(data: number) {
    view.setUint16(pos, data, true)
    pos += 2
  }

  function setUint32(data: number) {
    view.setUint32(pos, data, true)
    pos += 4
  }
}
