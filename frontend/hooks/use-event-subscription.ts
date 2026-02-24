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
 * unsubscribes on unmount or when the factory function changes.
 *
 * The `factory` callback returns a map of event name → handler.
 * It is called inside a useEffect so handlers may safely reference
 * the latest component state via refs.
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

  useEffect(() => {
    const subscriptions = factory()
    const entries = Object.entries(subscriptions)

    for (const [eventName, handler] of entries) {
      subscribe(eventName, handler)
    }

    return () => {
      for (const [eventName, handler] of entries) {
        unsubscribe(eventName, handler)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
}
