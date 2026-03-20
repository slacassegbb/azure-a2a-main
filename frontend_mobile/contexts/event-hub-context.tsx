"use client"

import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from "react"
import type { EventCallback } from "@/lib/websocket-client"
import { logDebug, warnDebug } from "@/lib/debug"

interface WebSocketClientInterface {
  subscribe: (eventName: string, callback: EventCallback) => void
  unsubscribe: (eventName: string, callback: EventCallback) => void
  emit?: (eventName: string, data: any) => void
  getConnectionStatus: () => boolean
  initialize?: () => Promise<boolean>
  close?: () => Promise<void>
  sendMessage?: (message: any) => boolean
}

interface EventHubContextType {
  client: WebSocketClientInterface | null
  isConnected: boolean
  subscribe: (eventName: string, callback: EventCallback) => void
  unsubscribe: (eventName: string, callback: EventCallback) => void
  emit: (eventName: string, data: any) => void
  sendMessage: (message: any) => boolean
}

const EventHubContext = createContext<EventHubContextType | null>(null)

export function EventHubProvider({ children }: { children: React.ReactNode }) {
  const [client, setClient] = useState<WebSocketClientInterface | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const initRef = useRef(false)
  const clientRef = useRef<WebSocketClientInterface | null>(null)
  const pendingRef = useRef<Map<string, Set<EventCallback>>>(new Map())

  useEffect(() => {
    clientRef.current = client
    if (client && pendingRef.current.size > 0) {
      pendingRef.current.forEach((callbacks, eventName) => {
        callbacks.forEach((cb) => client.subscribe(eventName, cb))
      })
      pendingRef.current.clear()
    }
  }, [client])

  useEffect(() => {
    if (initRef.current) return
    initRef.current = true

    ;(async () => {
      try {
        const wsUrl = process.env.NEXT_PUBLIC_WEBSOCKET_URL || "ws://localhost:8080/events"
        const { WebSocketClient } = await import("@/lib/websocket-client")
        const ws = new WebSocketClient({ url: wsUrl, reconnectInterval: 3000, maxReconnectAttempts: 10 })
        setClient(ws)
        const ok = await ws.initialize()
        if (ok) setIsConnected(true)
      } catch (err) {
        console.error("[EventHub] Init failed:", err)
      }
    })()

    return () => {
      if (clientRef.current?.close) clientRef.current.close()
    }
  }, [])

  // Monitor connection status
  useEffect(() => {
    if (!client) return
    const interval = setInterval(() => {
      const status = client.getConnectionStatus()
      if (status !== isConnected) setIsConnected(status)
    }, 5000)
    return () => clearInterval(interval)
  }, [client, isConnected])

  const subscribe = useCallback((eventName: string, callback: EventCallback) => {
    if (clientRef.current) {
      clientRef.current.subscribe(eventName, callback)
    } else {
      if (!pendingRef.current.has(eventName)) pendingRef.current.set(eventName, new Set())
      pendingRef.current.get(eventName)!.add(callback)
    }
  }, [])

  const unsubscribe = useCallback((eventName: string, callback: EventCallback) => {
    clientRef.current?.unsubscribe(eventName, callback)
    if (pendingRef.current.has(eventName)) {
      pendingRef.current.get(eventName)!.delete(callback)
    }
  }, [])

  const emit = useCallback((eventName: string, data: any) => {
    if (clientRef.current?.emit) clientRef.current.emit(eventName, data)
  }, [])

  const sendMessage = useCallback((message: any) => {
    if (clientRef.current?.sendMessage) return clientRef.current.sendMessage(message)
    return false
  }, [])

  return (
    <EventHubContext.Provider value={{ client, isConnected, subscribe, unsubscribe, emit, sendMessage }}>
      {children}
    </EventHubContext.Provider>
  )
}

export function useEventHub(): EventHubContextType {
  const ctx = useContext(EventHubContext)
  if (!ctx) throw new Error("useEventHub must be used within EventHubProvider")
  return ctx
}
