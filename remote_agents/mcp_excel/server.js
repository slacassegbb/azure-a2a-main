#!/usr/bin/env node

/**
 * Excel MCP Server - HTTP Mode
 * Wraps @negokaz/excel-mcp-server (stdio Go binary) with an HTTP server
 * for Azure Container Apps deployment.
 *
 * Endpoints:
 *   POST /mcp          - MCP JSON-RPC (StreamableHTTP compatible)
 *   GET  /health       - Health check
 *   GET  /download/:fn - Download generated .xlsx files
 */

import { spawn } from 'child_process';
import http from 'http';
import { randomUUID } from 'crypto';
import fs from 'fs';
import path from 'path';

const PORT = parseInt(process.env.PORT || '8000');
const DOWNLOAD_DIR = '/tmp/xlsx_downloads';
const PAGING_LIMIT = process.env.EXCEL_MCP_PAGING_CELLS_LIMIT || '4000';

// Ensure download directory exists
fs.mkdirSync(DOWNLOAD_DIR, { recursive: true });

console.error('Starting Excel MCP Server in HTTP mode...');
console.error(`  Port: ${PORT}`);
console.error(`  Paging limit: ${PAGING_LIMIT}`);

// ========================================
// Stdio child process management
// ========================================

let mcpProcess = null;
let pendingRequests = new Map();
let inputBuffer = '';
let mcpInitialized = false;

function startMcpProcess() {
  mcpInitialized = false;
  // The npm-installed binary is available as 'excel-mcp-server' in PATH
  mcpProcess = spawn('excel-mcp-server', [], {
    stdio: ['pipe', 'pipe', 'pipe'],
    env: {
      ...process.env,
      EXCEL_MCP_PAGING_CELLS_LIMIT: PAGING_LIMIT,
    },
  });

  mcpProcess.stdout.on('data', (chunk) => {
    inputBuffer += chunk.toString();
    processBuffer();
  });

  mcpProcess.stderr.on('data', (chunk) => {
    console.error(`[excel-mcp-server] ${chunk.toString().trim()}`);
  });

  mcpProcess.on('exit', (code) => {
    console.error(`excel-mcp-server exited with code ${code}`);
    mcpInitialized = false;
    // Reject all pending requests
    for (const [id, { reject }] of pendingRequests) {
      reject(new Error(`MCP process exited with code ${code}`));
    }
    pendingRequests.clear();
    // Restart
    setTimeout(startMcpProcess, 1000);
  });

  console.error('excel-mcp-server stdio process started');

  // Initialize the Go binary so it's ready for tools/list, tools/call, etc.
  // Without this, the binary rejects requests because it hasn't been initialized.
  initializeMcpBinary();
}

async function initializeMcpBinary() {
  try {
    const initRequest = {
      jsonrpc: '2.0',
      id: '__init__',
      method: 'initialize',
      params: {
        protocolVersion: '2024-11-05',
        capabilities: {},
        clientInfo: { name: 'excel-http-wrapper', version: '1.0.0' },
      },
    };
    const initResp = await sendToMcp(initRequest);
    console.error('Go binary initialized:', JSON.stringify(initResp.result?.serverInfo || {}));

    // Send the required initialized notification (no id, no response expected)
    const notification = JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n';
    mcpProcess.stdin.write(notification);
    mcpInitialized = true;
    console.error('Go binary ready for requests');
  } catch (err) {
    console.error('Failed to initialize Go binary:', err.message);
  }
}

function processBuffer() {
  // MCP stdio uses JSON-RPC over newline-delimited JSON
  while (true) {
    const newlineIdx = inputBuffer.indexOf('\n');
    if (newlineIdx === -1) break;

    const line = inputBuffer.substring(0, newlineIdx).trim();
    inputBuffer = inputBuffer.substring(newlineIdx + 1);

    if (!line) continue;

    try {
      const msg = JSON.parse(line);
      if (msg.id !== undefined && pendingRequests.has(msg.id)) {
        const { resolve } = pendingRequests.get(msg.id);
        pendingRequests.delete(msg.id);
        resolve(msg);
      } else if (msg.method) {
        // Server-initiated notification/request — log it
        console.error(`[mcp notification] ${msg.method}`);
      }
    } catch (e) {
      console.error(`Failed to parse MCP response: ${line.substring(0, 200)}`);
    }
  }
}

function sendToMcp(request, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pendingRequests.delete(request.id);
      reject(new Error('MCP request timed out'));
    }, timeoutMs);

    pendingRequests.set(request.id, {
      resolve: (msg) => {
        clearTimeout(timer);
        resolve(msg);
      },
      reject: (err) => {
        clearTimeout(timer);
        reject(err);
      },
    });

    const data = JSON.stringify(request) + '\n';
    mcpProcess.stdin.write(data);
  });
}

// ========================================
// HTTP Server
// ========================================

const server = http.createServer(async (req, res) => {
  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Accept, mcp-session-id');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  // Health check
  if (req.url === '/health' && req.method === 'GET') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', server: 'excel-mcp-server' }));
    return;
  }

  // Download endpoint
  if (req.url.startsWith('/download/') && req.method === 'GET') {
    const filename = path.basename(decodeURIComponent(req.url.substring('/download/'.length)));
    const filePath = path.join(DOWNLOAD_DIR, filename);

    if (!fs.existsSync(filePath)) {
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: `File not found: ${filename}` }));
      return;
    }

    const stat = fs.statSync(filePath);
    res.writeHead(200, {
      'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'Content-Disposition': `attachment; filename="${filename}"`,
      'Content-Length': stat.size,
    });
    fs.createReadStream(filePath).pipe(res);
    return;
  }

  // MCP endpoint
  if (req.url === '/mcp' && req.method === 'POST') {
    let body = '';
    req.on('data', (chunk) => (body += chunk));
    req.on('end', async () => {
      try {
        const request = JSON.parse(body);
        console.error(`[MCP] method=${request.method} id=${request.id} accept=${req.headers['accept'] || 'none'} session=${req.headers['mcp-session-id'] || 'none'}`);

        // Handle initialize — respond with server capabilities
        // Also re-initialize the Go binary if it wasn't initialized yet
        if (request.method === 'initialize') {
          if (!mcpInitialized) {
            await initializeMcpBinary();
          }

          const response = {
            jsonrpc: '2.0',
            id: request.id,
            result: {
              protocolVersion: request.params?.protocolVersion || '2024-11-05',
              capabilities: {
                tools: { listChanged: false },
              },
              serverInfo: {
                name: 'excel-mcp-server',
                version: '0.12.0',
              },
            },
          };

          const sessionId = randomUUID().replace(/-/g, '');
          // Return as SSE if client accepts it
          const accept = req.headers['accept'] || '';
          if (accept.includes('text/event-stream')) {
            res.writeHead(200, {
              'Content-Type': 'text/event-stream',
              'Cache-Control': 'no-cache, no-transform',
              'Connection': 'keep-alive',
              'mcp-session-id': sessionId,
            });
            res.write(`event: message\ndata: ${JSON.stringify(response)}\n\n`);
            res.end();
          } else {
            res.writeHead(200, {
              'Content-Type': 'application/json',
              'mcp-session-id': sessionId,
            });
            res.end(JSON.stringify(response));
          }
          return;
        }

        // Handle notifications (like notifications/initialized) — no response needed.
        // Notifications have no "id" field at all (id=0 is a valid request id).
        if (request.method && request.id === undefined) {
          res.writeHead(204);
          res.end();
          return;
        }

        // Forward everything else to the stdio process.
        // WORKAROUND: The Go mcp-go library drops id=0 from responses,
        // so we remap 0 to a placeholder and restore it in the response.
        const originalId = request.id;
        const ID_ZERO_PLACEHOLDER = '__id_zero__';
        if (request.id === 0) {
          request.id = ID_ZERO_PLACEHOLDER;
        }
        console.error(`[MCP] Forwarding to Go binary: method=${request.method} id=${request.id}`);
        const mcpResponse = await sendToMcp(request);
        // Restore original id=0 in the response
        if (originalId === 0) {
          mcpResponse.id = 0;
        }
        if (mcpResponse.error) {
          console.error(`[MCP] Go binary error: ${JSON.stringify(mcpResponse.error)}`);
        } else {
          console.error(`[MCP] Go binary success: method=${request.method}`);
        }

        const accept = req.headers['accept'] || '';
        if (accept.includes('text/event-stream')) {
          res.writeHead(200, {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache, no-transform',
            'Connection': 'keep-alive',
          });
          res.write(`event: message\ndata: ${JSON.stringify(mcpResponse)}\n\n`);
          res.end();
        } else {
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify(mcpResponse));
        }
      } catch (err) {
        console.error('Error handling MCP request:', err.message);
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: err.message }));
      }
    });
    return;
  }

  // 404 for everything else
  res.writeHead(404, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ error: 'Not found' }));
});

// Start everything
startMcpProcess();

server.listen(PORT, '0.0.0.0', () => {
  console.error(`HTTP server listening on 0.0.0.0:${PORT}`);
  console.error(`  MCP endpoint: http://0.0.0.0:${PORT}/mcp`);
  console.error(`  Health check: http://0.0.0.0:${PORT}/health`);
  console.error(`  Downloads:    http://0.0.0.0:${PORT}/download/`);
});
