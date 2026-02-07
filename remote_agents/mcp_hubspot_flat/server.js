#!/usr/bin/env node

/**
 * HubSpot MCP Server - HTTP Mode
 * Wraps the flattened HubSpot MCP server to work like QuickBooks/Stripe MCP servers
 * Supports direct POST to /sse for Azure AI Foundry compatibility
 */

import { spawn } from 'child_process';
import http from 'http';
import { randomUUID } from 'crypto';

const PORT = parseInt(process.env.PORT || '8000');
const HUBSPOT_ACCESS_TOKEN = process.env.PRIVATE_APP_ACCESS_TOKEN;

if (!HUBSPOT_ACCESS_TOKEN) {
  console.error('ERROR: PRIVATE_APP_ACCESS_TOKEN environment variable is required');
  process.exit(1);
}

console.error('Starting HubSpot MCP Server in HTTP mode...');
console.error(`  Port: ${PORT}`);
console.error(`  Token: ${HUBSPOT_ACCESS_TOKEN.substring(0, 20)}...`);

// Start the MCP server as a child process in stdio mode
const mcpServer = spawn('node', ['index.js'], {
  stdio: ['pipe', 'pipe', 'inherit'], // stdin, stdout, stderr
  env: { ...process.env, PRIVATE_APP_ACCESS_TOKEN: HUBSPOT_ACCESS_TOKEN }
});

mcpServer.on('error', (err) => {
  console.error('Failed to start HubSpot MCP:', err);
  process.exit(1);
});

mcpServer.on('exit', (code) => {
  console.error(`HubSpot MCP process exited with code ${code}`);
  process.exit(code || 0);
});

// Track pending requests waiting for responses
const pendingRequests = new Map();

// Read responses from MCP stdout
let buffer = '';
mcpServer.stdout.on('data', (data) => {
  buffer += data.toString();
  
  // Process complete JSON-RPC messages (one per line)
  let newlineIndex;
  while ((newlineIndex = buffer.indexOf('\n')) !== -1) {
    const line = buffer.substring(0, newlineIndex).trim();
    buffer = buffer.substring(newlineIndex + 1);
    
    if (!line) continue;
    
    try {
      const response = JSON.parse(line);
      console.error('Received from HubSpot MCP:', JSON.stringify(response).substring(0, 200));
      
      // Find the pending request with this ID
      if (response.id !== undefined && pendingRequests.has(response.id)) {
        const { resolve } = pendingRequests.get(response.id);
        pendingRequests.delete(response.id);
        resolve(response);
      }
    } catch (err) {
      console.error('Failed to parse HubSpot MCP response:', line.substring(0, 200), err);
    }
  }
});

// Function to send a JSON-RPC request to MCP and get the response
async function callMcp(request) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      pendingRequests.delete(request.id);
      reject(new Error('Request timeout'));
    }, 30000); // 30 second timeout
    
    pendingRequests.set(request.id, {
      resolve: (response) => {
        clearTimeout(timeout);
        resolve(response);
      },
      reject
    });
    
    const requestLine = JSON.stringify(request) + '\n';
    console.error('Sending to HubSpot MCP:', requestLine.trim().substring(0, 200));
    mcpServer.stdin.write(requestLine);
  });
}

// HTTP server
const server = http.createServer(async (req, res) => {
  console.error(`Received ${req.method} request to: ${req.url}`);

  // Enable CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Accept, Authorization');

  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    res.end();
    return;
  }

  // Root endpoint
  if (req.url === '/' && req.method === 'GET') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      name: 'HubSpot MCP Server',
      version: '1.0.0',
      protocol: 'MCP',
      endpoints: {
        sse: '/sse',
        health: '/health'
      }
    }));
    return;
  }

  // Health check
  if (req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'healthy', server: 'HubSpot MCP' }));
    return;
  }

  // Handle POST to /sse - Direct JSON-RPC handling (like QuickBooks/Stripe)
  if (req.url?.startsWith('/sse') && req.method === 'POST') {
    console.error('Received POST to /sse - direct JSON-RPC handling');
    
    // Check if client wants SSE format
    const acceptHeader = req.headers.accept || '';
    const wantsSSE = acceptHeader.includes('text/event-stream');
    console.error(`Accept header: ${acceptHeader}, wants SSE: ${wantsSSE}`);
    
    // Read request body
    let body = '';
    req.on('data', (chunk) => {
      body += chunk.toString();
    });
    
    req.on('end', async () => {
      try {
        const jsonRpcRequest = JSON.parse(body);
        console.error('JSON-RPC request:', JSON.stringify(jsonRpcRequest, null, 2));
        
        // Check if this is a notification (no id = no response expected)
        const isNotification = jsonRpcRequest.id === undefined || jsonRpcRequest.method?.startsWith('notifications/');
        
        if (isNotification) {
          // For notifications, just forward and don't wait for response
          const requestLine = JSON.stringify(jsonRpcRequest) + '\n';
          console.error('Sending notification to MCP:', requestLine.trim().substring(0, 200));
          mcpServer.stdin.write(requestLine);
          
          // Send empty success response
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ jsonrpc: '2.0', result: {} }));
          return;
        }
        
        // Forward to MCP server and wait for response
        const response = await callMcp(jsonRpcRequest);
        console.error('JSON-RPC response:', JSON.stringify(response).substring(0, 200));
        
        // Send response in correct format
        const jsonStr = JSON.stringify(response);
        if (wantsSSE) {
          res.writeHead(200, {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive'
          });
          res.write(`event: message\ndata: ${jsonStr}\n\n`);
          res.end();
        } else {
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(jsonStr);
        }
        
      } catch (err) {
        console.error('Error handling request:', err);
        const errorResponse = {
          jsonrpc: '2.0',
          id: null,
          error: {
            code: -32603,
            message: err.message || 'Internal error'
          }
        };
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(errorResponse));
      }
    });
    return;
  }

  // Unknown endpoint
  res.writeHead(404, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ error: 'Not found' }));
});

server.listen(PORT, () => {
  console.error(`HubSpot MCP Server listening on port ${PORT}`);
  console.error(`POST messages: http://localhost:${PORT}/sse`);
});

// Graceful shutdown
process.on('SIGTERM', () => {
  console.error('Received SIGTERM, shutting down...');
  mcpServer.kill();
  server.close(() => {
    process.exit(0);
  });
});

process.on('SIGINT', () => {
  console.error('Received SIGINT, shutting down...');
  mcpServer.kill();
  server.close(() => {
    process.exit(0);
  });
});
