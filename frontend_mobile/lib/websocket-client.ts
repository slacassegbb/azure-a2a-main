/**
 * WebSocket client — identical to main frontend's websocket-client.ts
 * Provides real-time event streaming from the A2A backend.
 */

import { logDebug, warnDebug, logInfo, DEBUG } from "./debug"

export type EventCallback = (data: any) => void
type Subscribers = { [key: string]: EventCallback[] }

interface WebSocketConfig {
  url: string
  reconnectInterval?: number
  maxReconnectAttempts?: number
}

export class WebSocketClient {
  private subscribers: Subscribers = {}
  private websocket: WebSocket | null = null
  private isConnected: boolean = false
  private isReconnecting: boolean = false
  private reconnectAttempts: number = 0
  private reconnectTimeout: NodeJS.Timeout | null = null
  private config: WebSocketConfig
  private isInitializing: boolean = false
  private pingInterval: NodeJS.Timeout | null = null
  private hasEverConnected: boolean = false

  constructor(config: WebSocketConfig) {
    this.config = {
      reconnectInterval: 2000,
      maxReconnectAttempts: 50,
      ...config,
    }
  }

  private startPingInterval() {
    this.stopPingInterval()
    this.pingInterval = setInterval(() => {
      if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
        try {
          this.websocket.send(JSON.stringify({ type: "ping" }))
        } catch {}
      }
    }, 30000)
  }

  private stopPingInterval() {
    if (this.pingInterval) {
      clearInterval(this.pingInterval)
      this.pingInterval = null
    }
  }

  async initialize(): Promise<boolean> {
    if (this.isInitializing) return false
    if (this.isConnected && this.websocket?.readyState === WebSocket.OPEN) return true
    this.isInitializing = true

    try {
      if (this.websocket) {
        this.websocket.close()
        this.websocket = null
      }

      const maxInitialAttempts = 3
      let attempts = 0

      while (attempts < maxInitialAttempts) {
        try {
          attempts++
          logDebug(`[WebSocket] Connection attempt ${attempts}/${maxInitialAttempts}`)

          let wsUrl = this.config.url
          if (typeof window !== "undefined") {
            const params: string[] = []
            const token = localStorage.getItem("auth_token")
            if (token) params.push(`token=${encodeURIComponent(token)}`)

            const { getOrCreateSessionId } = await import("./session")
            const tenantId = getOrCreateSessionId()
            if (tenantId) params.push(`tenantId=${encodeURIComponent(tenantId)}`)

            if (params.length > 0) {
              const sep = wsUrl.includes("?") ? "&" : "?"
              wsUrl = `${wsUrl}${sep}${params.join("&")}`
            }
          }

          this.websocket = new WebSocket(wsUrl)

          const connectionResult = await new Promise<boolean>((resolve) => {
            const timeout = setTimeout(() => resolve(false), 5000)

            this.websocket!.onopen = () => {
              clearTimeout(timeout)
              logInfo("[WebSocket] CONNECTED")
              this.isConnected = true
              this.isReconnecting = false
              this.reconnectAttempts = 0
              this.hasEverConnected = true
              this.startPingInterval()
              if (this.reconnectTimeout) {
                clearTimeout(this.reconnectTimeout)
                this.reconnectTimeout = null
              }
              resolve(true)
            }

            this.websocket!.onerror = () => {
              clearTimeout(timeout)
              this.isConnected = false
              resolve(false)
            }

            this.websocket!.onclose = () => {
              clearTimeout(timeout)
              this.isConnected = false
              resolve(false)
            }
          })

          if (connectionResult) {
            this.websocket.onmessage = (event) => {
              try {
                const data = JSON.parse(event.data)
                this.handleEvent(data)
              } catch {}
            }

            this.websocket.onclose = (event) => {
              logInfo(`[WebSocket] CLOSED: code=${event.code}`)
              this.isConnected = false
              this.stopPingInterval()
              if (event.code !== 1000 && this.reconnectAttempts < this.config.maxReconnectAttempts!) {
                this.scheduleReconnect()
              }
            }

            this.websocket.onerror = () => {
              this.isConnected = false
            }

            return true
          } else if (attempts < maxInitialAttempts) {
            await new Promise((r) => setTimeout(r, 1000))
          }
        } catch {
          if (attempts < maxInitialAttempts) {
            await new Promise((r) => setTimeout(r, 1000))
          }
        }
      }
      return false
    } finally {
      this.isInitializing = false
    }
  }

  private scheduleReconnect() {
    if (this.isReconnecting || this.reconnectTimeout) return
    this.isReconnecting = true
    this.reconnectAttempts++
    const delay = Math.min((this.config.reconnectInterval || 2000) * Math.min(Math.floor(this.reconnectAttempts / 3) + 1, 5), 10000)
    this.reconnectTimeout = setTimeout(async () => {
      this.reconnectTimeout = null
      try {
        await this.initialize()
      } catch {
        this.isReconnecting = false
        if (this.reconnectAttempts < this.config.maxReconnectAttempts!) {
          this.scheduleReconnect()
        }
      }
    }, delay)
  }

  private handleEvent(eventData: any) {
    const eventType = eventData.eventType || eventData.type || "unknown"

    switch (eventType) {
      case "message":
        this.emit("message", eventData)
        break
      case "remote_agent_activity":
        this.emit("remote_agent_activity", eventData)
        break
      case "file":
        this.emit("file_uploaded", eventData)
        break
      case "conversation":
        this.emit("conversation", eventData)
        if (eventData.action === "created") this.emit("conversation_created", eventData)
        if (eventData.action === "updated") this.emit("conversation_updated", eventData)
        break
      case "agent_registry_sync":
        this.emit("agent_registry_sync", eventData)
        break
      case "session_started":
        this.emit("session_started", eventData)
        break
      default:
        this.emit(eventType, eventData)
    }
    this.emit("raw_event", eventData)
  }

  subscribe(eventName: string, callback: EventCallback): void {
    if (!this.subscribers[eventName]) this.subscribers[eventName] = []
    this.subscribers[eventName].push(callback)
  }

  unsubscribe(eventName: string, callback: EventCallback): void {
    if (this.subscribers[eventName]) {
      this.subscribers[eventName] = this.subscribers[eventName].filter((cb) => cb !== callback)
    }
  }

  emit(eventName: string, data: any): void {
    this.subscribers[eventName]?.forEach((cb) => {
      try { cb(data) } catch {}
    })
  }

  sendMessage(message: any): boolean {
    if (this.websocket?.readyState === WebSocket.OPEN) {
      try {
        this.websocket.send(typeof message === "string" ? message : JSON.stringify(message))
        return true
      } catch {
        return false
      }
    }
    return false
  }

  getConnectionStatus(): boolean {
    return this.isConnected && this.websocket?.readyState === WebSocket.OPEN
  }

  async close(): Promise<void> {
    this.isInitializing = false
    this.stopPingInterval()
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout)
      this.reconnectTimeout = null
    }
    this.isReconnecting = false
    this.reconnectAttempts = this.config.maxReconnectAttempts!
    if (this.websocket) {
      this.websocket.close(1000, "Client closing")
      this.websocket = null
    }
    this.isConnected = false
  }
}
