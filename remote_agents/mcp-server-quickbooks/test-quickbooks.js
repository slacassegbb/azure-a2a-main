import http from 'http';

const SERVER_URL = 'http://localhost:3001';

async function testQuickBooks() {
  console.log('Connecting to QuickBooks MCP SSE endpoint...');
  
  const sseReq = http.get(`${SERVER_URL}/sse`, (sseRes) => {
    console.log('Connected to SSE stream');
    let sessionId = null;
    
    sseRes.on('data', (chunk) => {
      const data = chunk.toString();
      console.log('Received SSE data:', data);
      
      const lines = data.split('\n');
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const eventData = line.substring(6);
          
          if (eventData.includes('/message') && !sessionId) {
            const match = eventData.match(/sessionId=([^&\s]+)/);
            if (match) {
              sessionId = match[1];
              console.log('Session ID:', sessionId);
              
              // Test listing customers
              setTimeout(() => {
                sendToolCall(sessionId, 'list_customers', {});
              }, 500);
            }
          }
          
          // Check for tool response
          if (eventData.startsWith('{')) {
            try {
              const response = JSON.parse(eventData);
              console.log('\n=== TOOL RESPONSE ===');
              console.log(JSON.stringify(response, null, 2));
              console.log('=====================\n');
              process.exit(0);
            } catch (e) {
              // Not JSON, ignore
            }
          }
        }
      }
    });
    
    sseRes.on('end', () => {
      console.log('SSE connection closed');
    });
  });
  
  sseReq.on('error', (err) => {
    console.error('SSE connection error:', err);
  });
  
  // Keep connection open for response
  setTimeout(() => {
    console.log('Timeout - no response received');
    process.exit(1);
  }, 30000);
}

function sendToolCall(sessionId, toolName, args) {
  console.log(`\nCalling tool: ${toolName}...`);
  
  const request = {
    jsonrpc: '2.0',
    id: 1,
    method: 'tools/call',
    params: {
      name: toolName,
      arguments: args
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
    }
  };
  
  const req = http.request(options, (res) => {
    console.log('Response status:', res.statusCode);
    
    let responseData = '';
    res.on('data', (chunk) => {
      responseData += chunk;
    });
    
    res.on('end', () => {
      console.log('Response:', responseData);
      try {
        const parsed = JSON.parse(responseData);
        console.log('\nParsed result:', JSON.stringify(parsed, null, 2));
      } catch (e) {
        // Not JSON
      }
      process.exit(0);
    });
  });
  
  req.on('error', (err) => {
    console.error('Request error:', err);
  });
  
  req.write(postData);
  req.end();
}

testQuickBooks();
