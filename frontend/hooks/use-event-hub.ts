/**
 * React hook for accessing the shared WebSocket connection
 * 
 * This hook provides access to the singleton WebSocket connection
 * managed by the EventHubProvider context.
 */

import { useEventHub as useEventHubContext } from '@/contexts/event-hub-context';

export function useEventHub() {
  return useEventHubContext();
}

