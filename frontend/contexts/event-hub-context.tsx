"use client";

/**
 * EventHub Context - Provides a single WebSocket connection shared across the app
 * 
 * This Context ensures only one WebSocket connection is created and shared
 * across all components that need real-time event communication.
 */

import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from 'react';
import type { EventCallback } from '@/lib/websocket-client';
import { logDebug, warnDebug } from '@/lib/debug';

// Import types only to avoid client/server issues
interface WebSocketConfig {
  url: string;
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
}

// Generic WebSocket client interface
interface WebSocketClientInterface {
  subscribe: (eventName: string, callback: EventCallback) => void;
  unsubscribe: (eventName: string, callback: EventCallback) => void;
  emit?: (eventName: string, data: any) => void;
  getConnectionStatus: () => boolean;
  initialize?: () => Promise<boolean>;
  close?: () => Promise<void>;
}

interface EventHubContextType {
  client: WebSocketClientInterface | null;
  isConnected: boolean;
  isConnecting: boolean;
  error: string | null;
  subscribe: (eventName: string, callback: EventCallback) => void;
  unsubscribe: (eventName: string, callback: EventCallback) => void;
  emit: (eventName: string, data: any) => void;
  sendMessage: (message: any) => boolean;
  reconnect: () => Promise<void>;
}

const EventHubContext = createContext<EventHubContextType | null>(null);

export function EventHubProvider({ children }: { children: React.ReactNode }) {
  const [client, setClient] = useState<WebSocketClientInterface | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const initializationRef = useRef(false);
  // Use a ref for client in callbacks to avoid re-creating callbacks when client changes
  const clientRef = useRef<WebSocketClientInterface | null>(null);
  
  // Queue for subscriptions made before client is ready
  const pendingSubscriptionsRef = useRef<Map<string, Set<EventCallback>>>(new Map());
  
  // Keep clientRef in sync with client state
  useEffect(() => {
    clientRef.current = client;
    
    // Apply pending subscriptions when client becomes available
    if (client && pendingSubscriptionsRef.current.size > 0) {
      logDebug(`[EventHubProvider] Applying ${pendingSubscriptionsRef.current.size} pending subscription types`);
      pendingSubscriptionsRef.current.forEach((callbacks, eventName) => {
        callbacks.forEach(callback => {
          client.subscribe(eventName, callback);
        });
      });
      pendingSubscriptionsRef.current.clear();
    }
  }, [client]);

  const createClient = useCallback(async (): Promise<WebSocketClientInterface> => {
    // Get configuration from environment variables
    const websocketUrl = process.env.NEXT_PUBLIC_WEBSOCKET_URL || 'ws://localhost:8080/events';
    
    logDebug("[EventHubProvider] Creating WebSocket client...");

    // Dynamic import to ensure client-side only
    const { WebSocketClient } = await import('@/lib/websocket-client');

    const config: WebSocketConfig = {
      url: websocketUrl,
      reconnectInterval: 3000,
      maxReconnectAttempts: 10
    };

    logDebug("[EventHubProvider] Creating WebSocket client with config:", config);
    return new WebSocketClient(config);
  }, []);

  const initializeClient = useCallback(async () => {
    if (initializationRef.current) {
      logDebug("[EventHubProvider] Initialization already in progress, skipping");
      return; // Already initializing or initialized
    }

    initializationRef.current = true;
    setIsConnecting(true);
    setError(null);

    try {
      const newClient = await createClient();
      setClient(newClient);

      // If it's a real WebSocket client, initialize it
      if (newClient && 'initialize' in newClient && typeof newClient.initialize === 'function') {
        const success = await newClient.initialize();
        if (success) {
          setIsConnected(true);
          logDebug("[EventHubProvider] Successfully connected to WebSocket server");
        } else {
          throw new Error("Failed to initialize WebSocket client");
        }
      } else {
        // Mock client - consider it "connected" for UI purposes
        setIsConnected(false); // Keep false to show it's a mock
        logDebug("[EventHubProvider] Using mock WebSocket client");
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error';
      console.error("[EventHubProvider] Failed to initialize WebSocket client:", err);
      setError(errorMessage);
      
      // Fall back to mock client
      try {
        const { MockWebSocketClient } = await import('@/lib/websocket-client');
        const mockClient = new MockWebSocketClient();
        await mockClient.initialize();
        setClient(mockClient);
        setIsConnected(false);
        logDebug("[EventHubProvider] Fallback to mock client successful");
      } catch (mockErr) {
        console.error("[EventHubProvider] Even mock client failed:", mockErr);
      }
    } finally {
      setIsConnecting(false);
      initializationRef.current = false; // Allow retry after delay
    }
  }, [createClient]);

  const reconnect = useCallback(async () => {
    logDebug("[EventHubProvider] Reconnect requested");

    // Prevent multiple concurrent reconnects
    if (isConnecting) {
      logDebug("[EventHubProvider] Reconnect already in progress, skipping");
      return;
    }
    
    if (client && 'close' in client && typeof client.close === 'function') {
      await client.close();
    }
    setClient(null);
    setIsConnected(false);
    initializationRef.current = false;
    
    // Add a small delay before reconnecting to avoid rapid retry loops
    setTimeout(() => {
      if (!initializationRef.current) { // Double-check before initializing
        initializeClient();
      }
    }, 1000);
  }, [client, initializeClient, isConnecting]);

  const subscribe = useCallback((eventName: string, callback: EventCallback) => {
    if (clientRef.current) {
      clientRef.current.subscribe(eventName, callback);
    } else {
      // Queue subscription for when client becomes available
      logDebug(`[EventHubProvider] Queuing subscription for ${eventName} (client not ready)`);
      if (!pendingSubscriptionsRef.current.has(eventName)) {
        pendingSubscriptionsRef.current.set(eventName, new Set());
      }
      pendingSubscriptionsRef.current.get(eventName)!.add(callback);
    }
  }, []);

  const unsubscribe = useCallback((eventName: string, callback: EventCallback) => {
    if (clientRef.current) {
      clientRef.current.unsubscribe(eventName, callback);
    }
    // Also remove from pending if queued
    if (pendingSubscriptionsRef.current.has(eventName)) {
      pendingSubscriptionsRef.current.get(eventName)!.delete(callback);
      if (pendingSubscriptionsRef.current.get(eventName)!.size === 0) {
        pendingSubscriptionsRef.current.delete(eventName);
      }
    }
  }, []);

  const emit = useCallback((eventName: string, data: any) => {
    if (clientRef.current && 'emit' in clientRef.current && typeof clientRef.current.emit === 'function') {
      clientRef.current.emit(eventName, data);
    }
  }, []);

  const sendMessage = useCallback((message: any) => {
    if (clientRef.current && 'sendMessage' in clientRef.current && typeof clientRef.current.sendMessage === 'function') {
      return clientRef.current.sendMessage(message);
    }
    warnDebug('[EventHubProvider] Cannot send message - client does not support sending');
    return false;
  }, []);

  // Initialize client on mount (client-side only)
  useEffect(() => {
    // Only initialize if not already initialized or initializing
    if (!client && !initializationRef.current) {
      logDebug("[EventHubProvider] Starting WebSocket initialization...");
      initializeClient();
    }

    // Cleanup on unmount
    return () => {
      logDebug("[EventHubProvider] Cleaning up WebSocket connection...");
      if (client && 'close' in client && typeof client.close === 'function') {
        client.close();
      }
      initializationRef.current = false;
    };
  }, []); // Empty dependency array to run only once on mount

  // Monitor connection status
  useEffect(() => {
    if (!client) return;

    const interval = setInterval(() => {
      const currentStatus = client.getConnectionStatus();
      if (currentStatus !== isConnected) {
        setIsConnected(currentStatus);
      }
    }, 5000); // Check every 5 seconds

    return () => clearInterval(interval);
  }, [client, isConnected]);

  const value: EventHubContextType = {
    client,
    isConnected,
    isConnecting,
    error,
    subscribe,
    unsubscribe,
    emit,
    sendMessage,
    reconnect
  };

  return (
    <EventHubContext.Provider value={value}>
      {children}
    </EventHubContext.Provider>
  );
}

export function useEventHub(): EventHubContextType {
  const context = useContext(EventHubContext);
  if (!context) {
    throw new Error('useEventHub must be used within an EventHubProvider');
  }
  return context;
}
