#!/usr/bin/env node

/**
 * Quick test to verify Playwright MCP server is working
 * Run this with: node test-playwright-mcp.js
 */

const { spawn } = require('child_process');

console.log('🎭 Testing Playwright MCP Server...\n');

const mcp = spawn('npx', ['playwright', 'run-test-mcp-server']);

mcp.stdout.on('data', (data) => {
  console.log(`✅ MCP Server Output: ${data}`);
});

mcp.stderr.on('data', (data) => {
  console.log(`📋 MCP Server Info: ${data}`);
});

mcp.on('close', (code) => {
  console.log(`\n🏁 MCP Server exited with code ${code}`);
});

// Send a test request after 2 seconds
setTimeout(() => {
  console.log('\n📤 Sending test request to MCP server...');
  mcp.stdin.write(JSON.stringify({
    jsonrpc: '2.0',
    method: 'tools/list',
    id: 1
  }) + '\n');
}, 2000);

// Keep process alive for 5 seconds
setTimeout(() => {
  console.log('\n⏹️  Closing MCP server...');
  mcp.kill();
}, 5000);
