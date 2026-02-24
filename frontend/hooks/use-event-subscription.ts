/**
 * Hooks for subscribing to WebSocket events via the EventHub.
 *
 * Eliminates the repetitive subscribe/unsubscribe boilerplate that
 * appears across most components.
 */

import { useEffect, useRef } from 'react'
import { useEventHub } from '@/hooks/use-event-hub'
import type { EventCallback } from '@/lib/websocket-client'

/**
 * Subscribe to a single WebSocket event. Automatically unsubscribes on
 * unmount or when the handler reference changes.
 *
 * @example
 * const handler = useCallback((data: any) => { ... }, [])
 * useEventSubscription('agent_activity', handler)
 */
export function useEventSubscription(eventName: string, handler: EventCallback): void {
  const { subscribe, unsubscribe } = useEventHub()
  const handlerRef = useRef(handler)
  handlerRef.current = handler

  useEffect(() => {
    const cb: EventCallback = (data) => handlerRef.current(data)
    subscribe(eventName, cb)
    return () => { unsubscribe(eventName, cb) }
    // Re-subscribe only if the event name changes (rare)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventName])
}

/**
 * Subscribe to multiple WebSocket events at once. Automatically
 * unsubscribes on unmount or when deps change.
 *
 * The `factory` callback returns a map of event name → handler.
 * Handlers always see the latest component state because the factory
 * is called on every render and stored in a ref (same pattern as
 * useEventSubscription above).
 *
 * @example
 * useEventSubscriptions(() => ({
 *   status_update: (data) => setStatus(data.status),
 *   agent_message: handleAgentMessage,
 *   final_response: (data) => { ... },
 * }))
 */
export function useEventSubscriptions(
  factory: () => Record<string, EventCallback>,
  deps: React.DependencyList = []
): void {
  const { subscribe, unsubscribe } = useEventHub()
  const handlersRef = useRef<Record<string, EventCallback>>({})

  // Always keep the latest handlers in the ref (called every render)
  handlersRef.current = factory()

  useEffect(() => {
    const eventNames = Object.keys(handlersRef.current)

    // Create stable wrapper callbacks that delegate to the ref
    const wrappers: [string, EventCallback][] = eventNames.map(name => [
      name,
      (data: any) => handlersRef.current[name]?.(data)
    ])

    for (const [name, cb] of wrappers) {
      subscribe(name, cb)
    }

    return () => {
      for (const [name, cb] of wrappers) {
        unsubscribe(name, cb)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
}
