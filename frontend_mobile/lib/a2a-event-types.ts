export interface A2AEventEnvelope {
  eventType: string
  timestamp: string
  eventId: string
  source: "a2a-system"
  data: any
}
