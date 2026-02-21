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
// Composite tool: build_spreadsheet
// ========================================

const BUILD_SPREADSHEET_TOOL = {
  name: 'build_spreadsheet',
  description:
    'Create a complete Excel workbook with multiple sheets, data, tables, and formatting in a single call. ' +
    'Use this instead of calling excel_write_to_sheet + excel_create_table + excel_format_range individually.',
  inputSchema: {
    type: 'object',
    properties: {
      filename: {
        type: 'string',
        description: 'Filename for the workbook (e.g. "report.xlsx"). Will be saved to /tmp/xlsx_downloads/.',
      },
      sheets: {
        type: 'array',
        description: 'Ordered list of sheets to create.',
        items: {
          type: 'object',
          properties: {
            name: { type: 'string', description: 'Sheet name' },
            data: {
              type: 'array',
              description: '2D array of cell values (first row is typically headers)',
              items: { type: 'array', items: { type: 'string' } },
            },
            table_name: {
              type: 'string',
              description: 'Optional: create an Excel Table object with this name',
            },
            header_style: {
              type: 'object',
              description:
                'Optional: style for the header row. Object with optional keys: font (object with bold, italic, size, color), fill (object with type, pattern, color array), border (array of border objects), numFmt (string)',
            },
            data_style: {
              type: 'object',
              description: 'Optional: style for data rows (same format as header_style)',
            },
          },
          required: ['name', 'data'],
        },
      },
    },
    required: ['filename', 'sheets'],
  },
};

/**
 * Convert a column number (0-based) to Excel column letter(s).
 * 0 -> A, 1 -> B, ..., 25 -> Z, 26 -> AA
 */
function colToLetter(col) {
  let letter = '';
  let c = col;
  while (c >= 0) {
    letter = String.fromCharCode((c % 26) + 65) + letter;
    c = Math.floor(c / 26) - 1;
  }
  return letter;
}

/**
 * Build a cell range string like "A1:D10" from row/col counts.
 */
function buildRange(rows, cols, startRow = 1) {
  const endCol = colToLetter(cols - 1);
  return `A${startRow}:${endCol}${startRow + rows - 1}`;
}

/**
 * Build a 2D style array where every cell gets the same style.
 */
function buildStyleGrid(rows, cols, style) {
  const grid = [];
  for (let r = 0; r < rows; r++) {
    const row = [];
    for (let c = 0; c < cols; c++) {
      row.push(style);
    }
    grid.push(row);
  }
  return grid;
}

let _buildCallId = 0;
function nextId() {
  return `__build_${++_buildCallId}`;
}

async function handleBuildSpreadsheet(args) {
  const filename = args.filename.endsWith('.xlsx') ? args.filename : `${args.filename}.xlsx`;
  const filePath = path.join(DOWNLOAD_DIR, filename);
  const sheets = args.sheets || [];
  const results = [];

  for (let i = 0; i < sheets.length; i++) {
    const sheet = sheets[i];
    const sheetName = sheet.name || `Sheet${i + 1}`;
    const data = sheet.data || [];
    const rows = data.length;
    const cols = rows > 0 ? Math.max(...data.map((r) => r.length)) : 0;

    if (rows === 0 || cols === 0) {
      results.push({ index: i, sheet: sheetName, ok: false, error: 'Empty data' });
      continue;
    }

    // Pad rows to uniform width
    const paddedData = data.map((row) => {
      const padded = [...row];
      while (padded.length < cols) padded.push('');
      return padded;
    });

    const range = buildRange(rows, cols);

    // 1. Write data
    try {
      const writeResp = await sendToMcp({
        jsonrpc: '2.0',
        id: nextId(),
        method: 'tools/call',
        params: {
          name: 'excel_write_to_sheet',
          arguments: {
            fileAbsolutePath: filePath,
            sheetName,
            newSheet: true,
            range,
            values: paddedData,
          },
        },
      });
      if (writeResp.error) {
        results.push({ index: i, sheet: sheetName, ok: false, error: writeResp.error.message || JSON.stringify(writeResp.error) });
        continue;
      }
    } catch (e) {
      results.push({ index: i, sheet: sheetName, ok: false, error: e.message });
      continue;
    }

    // 2. Create table (optional)
    if (sheet.table_name) {
      try {
        const tableResp = await sendToMcp({
          jsonrpc: '2.0',
          id: nextId(),
          method: 'tools/call',
          params: {
            name: 'excel_create_table',
            arguments: {
              fileAbsolutePath: filePath,
              sheetName,
              range,
              tableName: sheet.table_name,
            },
          },
        });
        if (tableResp.error) {
          console.error(`[build_spreadsheet] table creation warning for ${sheetName}: ${JSON.stringify(tableResp.error)}`);
        }
      } catch (e) {
        console.error(`[build_spreadsheet] table creation error for ${sheetName}: ${e.message}`);
      }
    }

    // 3. Format header row (optional)
    if (sheet.header_style && rows > 0) {
      try {
        const headerRange = buildRange(1, cols, 1);
        const headerGrid = buildStyleGrid(1, cols, sheet.header_style);
        const fmtResp = await sendToMcp({
          jsonrpc: '2.0',
          id: nextId(),
          method: 'tools/call',
          params: {
            name: 'excel_format_range',
            arguments: {
              fileAbsolutePath: filePath,
              sheetName,
              range: headerRange,
              styles: headerGrid,
            },
          },
        });
        if (fmtResp.error) {
          console.error(`[build_spreadsheet] header format warning for ${sheetName}: ${JSON.stringify(fmtResp.error)}`);
        }
      } catch (e) {
        console.error(`[build_spreadsheet] header format error for ${sheetName}: ${e.message}`);
      }
    }

    // 4. Format data rows (optional)
    if (sheet.data_style && rows > 1) {
      try {
        const dataRange = buildRange(rows - 1, cols, 2);
        const dataGrid = buildStyleGrid(rows - 1, cols, sheet.data_style);
        const fmtResp = await sendToMcp({
          jsonrpc: '2.0',
          id: nextId(),
          method: 'tools/call',
          params: {
            name: 'excel_format_range',
            arguments: {
              fileAbsolutePath: filePath,
              sheetName,
              range: dataRange,
              styles: dataGrid,
            },
          },
        });
        if (fmtResp.error) {
          console.error(`[build_spreadsheet] data format warning for ${sheetName}: ${JSON.stringify(fmtResp.error)}`);
        }
      } catch (e) {
        console.error(`[build_spreadsheet] data format error for ${sheetName}: ${e.message}`);
      }
    }

    results.push({ index: i, sheet: sheetName, ok: true });
  }

  const errors = results.filter((r) => !r.ok);
  const fileSize = fs.existsSync(filePath) ? fs.statSync(filePath).size : 0;

  return {
    message: 'Spreadsheet created and ready for download',
    filename,
    sheets_processed: results.length,
    errors: errors.length > 0 ? errors : null,
    size_bytes: fileSize,
    download_url: `/download/${filename}`,
  };
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

        // Handle tools/call for build_spreadsheet locally
        if (request.method === 'tools/call' && request.params?.name === 'build_spreadsheet') {
          console.error('[MCP] Handling build_spreadsheet composite tool');
          let toolResult;
          try {
            const args = request.params.arguments || {};
            toolResult = await handleBuildSpreadsheet(args);
          } catch (e) {
            toolResult = { error: `build_spreadsheet failed: ${e.message}` };
          }
          const mcpResponse = {
            jsonrpc: '2.0',
            id: request.id,
            result: {
              content: [{ type: 'text', text: JSON.stringify(toolResult) }],
            },
          };
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
        let mcpResponse = await sendToMcp(request);
        // Restore original id=0 in the response
        if (originalId === 0) {
          mcpResponse.id = 0;
        }

        // Inject build_spreadsheet into tools/list response
        if (request.method === 'tools/list' && mcpResponse.result?.tools) {
          mcpResponse.result.tools.push(BUILD_SPREADSHEET_TOOL);
          console.error(`[MCP] Injected build_spreadsheet into tools/list (total: ${mcpResponse.result.tools.length})`);
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
