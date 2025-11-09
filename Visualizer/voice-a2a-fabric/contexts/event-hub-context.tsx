"use client";

/**
 * EventHub Context - Provides a single WebSocket connection shared across the app
 * 
 * This Context ensures only one WebSocket connection is created and shared
 * across all components that need real-time event communication.
 */

import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from 'react';
import type { EventCallback } from '@/lib/websocket-client';

interface WebSocketConfig {
  url: string;
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
}

interface WebSocketClientInterface {
  subscribe: (eventName: string, callback: EventCallback) => void;
  unsubscribe: (eventName: string, callback: EventCallback) => void;
  emit?: (eventName: string, data: any) => void;
  getConnectionStatus: () => boolean;
  initialize?: () => Promise<boolean>;
  close?: () => Promise<void>;
  sendMessage?: (message: any) => boolean;
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
  const DEBUG = process.env.NEXT_PUBLIC_DEBUG_LOGS === 'true'
  const [client, setClient] = useState<WebSocketClientInterface | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const initializationRef = useRef(false);

  const createClient = useCallback(async (): Promise<WebSocketClientInterface> => {
    const websocketUrl = process.env.NEXT_PUBLIC_WEBSOCKET_URL || 'ws://localhost:8080/events';
    
    if (DEBUG) console.log("[EventHubProvider] Creating WebSocket client...");
    
    const { WebSocketClient } = await import('@/lib/websocket-client');
    
    const config: WebSocketConfig = {
      url: websocketUrl,
      reconnectInterval: 3000,
      maxReconnectAttempts: 10
    };

    if (DEBUG) console.log("[EventHubProvider] Creating WebSocket client with config:", config);
    return new WebSocketClient(config);
  }, [DEBUG]);

  const initializeClient = useCallback(async () => {
    if (initializationRef.current) {
      if (DEBUG) console.log("[EventHubProvider] Initialization already in progress, skipping");
      return;
    }

    initializationRef.current = true;
    setIsConnecting(true);
    setError(null);

    try {
      const newClient = await createClient();
      setClient(newClient);

      if (newClient && 'initialize' in newClient && typeof newClient.initialize === 'function') {
        const success = await newClient.initialize();
        if (success) {
          setIsConnected(true);
          if (DEBUG) console.log("[EventHubProvider] Successfully connected to WebSocket server");
        } else {
          throw new Error("Failed to initialize WebSocket client");
        }
      } else {
        setIsConnected(false);
        if (DEBUG) console.log("[EventHubProvider] Using mock WebSocket client");
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error';
      console.error("[EventHubProvider] Failed to initialize WebSocket client:", err);
      setError(errorMessage);
      
      try {
        const { MockWebSocketClient } = await import('@/lib/websocket-client');
        const mockClient = new MockWebSocketClient();
        await mockClient.initialize();
        setClient(mockClient);
        setIsConnected(false);
        if (DEBUG) console.log("[EventHubProvider] Fallback to mock client successful");
      } catch (mockErr) {
        console.error("[EventHubProvider] Even mock client failed:", mockErr);
      }
    } finally {
      setIsConnecting(false);
      initializationRef.current = false;
    }
  }, [createClient, DEBUG]);

  const reconnect = useCallback(async () => {
    if (DEBUG) console.log("[EventHubProvider] Reconnect requested");
    
    if (isConnecting) {
      if (DEBUG) console.log("[EventHubProvider] Reconnect already in progress, skipping");
      return;
    }
    
    if (client && 'close' in client && typeof client.close === 'function') {
      await client.close();
    }
    setClient(null);
    setIsConnected(false);
    initializationRef.current = false;
    
    setTimeout(() => {
      if (!initializationRef.current) {
        initializeClient();
      }
    }, 1000);
  }, [client, initializeClient, isConnecting, DEBUG]);

  const subscribe = useCallback((eventName: string, callback: EventCallback) => {
    if (client) {
      client.subscribe(eventName, callback);
    } else {
      if (DEBUG) console.warn(`[EventHubProvider] Cannot subscribe to ${eventName} - no client available`);
    }
  }, [client, DEBUG]);

  const unsubscribe = useCallback((eventName: string, callback: EventCallback) => {
    if (client) {
      client.unsubscribe(eventName, callback);
    }
  }, [client]);

  const emit = useCallback((eventName: string, data: any) => {
    if (client && 'emit' in client && typeof client.emit === 'function') {
      client.emit(eventName, data);
    }
  }, [client]);

  const sendMessage = useCallback((message: any) => {
    if (client && 'sendMessage' in client && typeof client.sendMessage === 'function') {
      return client.sendMessage(message);
    }
    if (DEBUG) console.warn('[EventHubProvider] Cannot send message - client does not support sending');
    return false;
  }, [client, DEBUG]);

  useEffect(() => {
    if (!client && !initializationRef.current) {
      if (DEBUG) console.log("[EventHubProvider] Starting WebSocket initialization...");
      initializeClient();
    }

    return () => {
      if (DEBUG) console.log("[EventHubProvider] Cleaning up WebSocket connection...");
      if (client && 'close' in client && typeof client.close === 'function') {
        client.close();
      }
      initializationRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!client) return;

    const interval = setInterval(() => {
      const currentStatus = client.getConnectionStatus();
      if (currentStatus !== isConnected) {
        setIsConnected(currentStatus);
      }
    }, 5000);

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
