// MCP SSE Client Test - waits for full response
import http from 'http';

const SERVER_URL = 'http://localhost:3001';

console.log('='.repeat(50));
console.log('QuickBooks MCP Server Test');
console.log('='.repeat(50));
console.log('');

// Step 1: Connect to SSE
console.log('Step 1: Connecting to SSE endpoint...');

const sseReq = http.get(`${SERVER_URL}/sse`, { timeout: 60000 }, (sseRes) => {
  console.log('✓ Connected to SSE stream');
  
  let sessionId = null;
  let buffer = '';
  
  sseRes.on('data', (chunk) => {
    buffer += chunk.toString();
    
    // Process complete events
    const events = buffer.split('\n\n');
    buffer = events.pop() || ''; // Keep incomplete event in buffer
    
    for (const event of events) {
      if (!event.trim()) continue;
      
      const lines = event.split('\n');
      let eventType = 'message';
      let eventData = '';
      
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.substring(7);
        } else if (line.startsWith('data: ')) {
          eventData = line.substring(6);
        }
      }
      
      // Handle endpoint event (get session ID)
      if (eventType === 'endpoint' && eventData.includes('/message')) {
        const match = eventData.match(/sessionId=([^&\s]+)/);
        if (match && !sessionId) {
          sessionId = match[1];
          console.log(`✓ Got session ID: ${sessionId}`);
          console.log('');
          
          // Step 2: Send tool call
          console.log('Step 2: Calling list_customers tool...');
          sendToolCall(sessionId);
        }
      }
      
      // Handle message event (tool response)
      if (eventType === 'message' && eventData) {
        try {
          const response = JSON.parse(eventData);
          if (response.result || response.error) {
            console.log('');
            console.log('='.repeat(50));
            console.log('Step 3: Response received!');
            console.log('='.repeat(50));
            console.log(JSON.stringify(response, null, 2));
            console.log('');
            console.log('✓ MCP Server working correctly!');
            process.exit(0);
          }
        } catch (e) {
          // Not JSON, might be partial
        }
      }
    }
  });
  
  sseRes.on('end', () => {
    console.log('SSE connection closed');
  });
  
  sseRes.on('error', (err) => {
    console.error('SSE error:', err.message);
  });
});

sseReq.on('error', (err) => {
  console.error('Connection error:', err.message);
  process.exit(1);
});

function sendToolCall(sessionId) {
  const request = {
    jsonrpc: '2.0',
    id: 1,
    method: 'tools/call',
    params: {
      name: 'qbo_search_customers',
      arguments: {}
    }
  };
  
  const postData = JSON.stringify(request);
  
  const options = {
    hostname: 'localhost',
    port: 3001,
    path: `/message?sessionId=${sessionId}`,
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(postData)
    },
    timeout: 30000
  };
  
  const req = http.request(options, (res) => {
    console.log(`✓ Request sent (status: ${res.statusCode})`);
    console.log('Waiting for response via SSE...');
  });
  
  req.on('error', (err) => {
    console.error('Request error:', err.message);
  });
  
  req.write(postData);
  req.end();
}

// Timeout after 30 seconds
setTimeout(() => {
  console.log('');
  console.log('✗ Timeout - no response after 30 seconds');
  process.exit(1);
}, 30000);
