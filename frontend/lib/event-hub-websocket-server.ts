// WebSocket server that connects to the Event Hub Relay
import { WebSocketServer, WebSocket } from 'ws';
import { createEventHubRelay, type WebClient } from './event-hub-relay';
import { randomUUID } from 'crypto';

interface EventHubWebSocketServerConfig {
  port: number;
  eventHubConfig: {
    fullyQualifiedNamespace: string;
    eventHubName: string;
    consumerGroup: string;
    connectionString?: string;
    useManagedIdentity?: boolean;
  };
}

export class EventHubWebSocketServer {
  private wss: WebSocketServer;
  private relay: any;
  private clients: Map<string, WebSocket> = new Map();

  constructor(private config: EventHubWebSocketServerConfig) {
    this.wss = new WebSocketServer({ port: config.port });
    this.relay = createEventHubRelay(config.eventHubConfig);
    this.setupWebSocketServer();
  }

  private setupWebSocketServer(): void {
    this.wss.on('connection', (ws: WebSocket) => {
      const clientId = randomUUID();
      console.log(`[WS] New client connected: ${clientId}`);
      
      this.clients.set(clientId, ws);

      // Create WebClient wrapper for the relay
      const webClient: WebClient = {
        id: clientId,
        send: (event) => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(event));
          }
        },
        isConnected: () => ws.readyState === WebSocket.OPEN
      };

      // Register with relay
      this.relay.addClient(clientId, webClient);

      // Handle client disconnect
      ws.on('close', () => {
        console.log(`[WS] Client disconnected: ${clientId}`);
        this.clients.delete(clientId);
        this.relay.removeClient(clientId);
      });

      // Handle client errors
      ws.on('error', (error) => {
        console.error(`[WS] Client ${clientId} error:`, error);
        this.clients.delete(clientId);
        this.relay.removeClient(clientId);
      });

      // Send connection status
      ws.send(JSON.stringify({
        type: 'connection',
        status: 'connected',
        clientId: clientId,
        eventHubStatus: this.relay.getConnectionStatus()
      }));
    });

    console.log(`[WS] WebSocket server listening on port ${this.config.port}`);
  }

  async start(): Promise<void> {
    console.log('[WS] Starting Event Hub Relay...');
    await this.relay.initialize();
    console.log('[WS] Event Hub WebSocket Server ready');
  }

  async stop(): Promise<void> {
    console.log('[WS] Stopping Event Hub WebSocket Server...');
    
    // Close all client connections
    this.clients.forEach((ws) => {
      ws.close();
    });
    this.clients.clear();

    // Close WebSocket server
    this.wss.close();

    // Close Event Hub relay
    await this.relay.close();
    
    console.log('[WS] Event Hub WebSocket Server stopped');
  }

  getStats(): { clientCount: number; eventHubConnected: boolean } {
    return {
      clientCount: this.clients.size,
      eventHubConnected: this.relay.getConnectionStatus()
    };
  }
}

// Usage example for standalone server
if (require.main === module) {
  const server = new EventHubWebSocketServer({
    port: 8080,
    eventHubConfig: {
      fullyQualifiedNamespace: process.env.EVENT_HUB_NAMESPACE || '',
      eventHubName: process.env.EVENT_HUB_NAME || '',
      consumerGroup: process.env.EVENT_HUB_CONSUMER_GROUP || '$Default',
      useManagedIdentity: true
    }
  });

  server.start().catch(console.error);

  // Graceful shutdown
  process.on('SIGINT', async () => {
    console.log('Received SIGINT, shutting down gracefully...');
    await server.stop();
    process.exit(0);
  });
}
