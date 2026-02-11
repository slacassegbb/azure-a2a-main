import http from 'http';
import https from 'https';

const SERVER_URL = 'http://localhost:3010';

async function testSSEClient() {
  console.log('Connecting to SSE endpoint...');
  
  // Connect to SSE endpoint
  const sseReq = http.get(`${SERVER_URL}/sse`, (sseRes) => {
    console.log('Connected to SSE stream');
    
    let messageEndpoint = '';
    let sessionId = '';
    
    sseRes.on('data', (chunk) => {
      const data = chunk.toString();
      console.log('Received SSE data:', data);
      
      // Parse SSE events
      const lines = data.split('\n');
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const eventData = line.substring(6);
          console.log('Event data:', eventData);
          
          // Extract message endpoint
          if (eventData.includes('/message')) {
            messageEndpoint = eventData;
            const match = eventData.match(/sessionId=([^&\s]+)/);
            if (match) {
              sessionId = match[1];
              console.log('Session ID:', sessionId);
              
              // Now send a query request
              setTimeout(() => {
                sendQuery(sessionId);
              }, 500);
            }
          }
        } else if (line.startsWith('event: ')) {
          console.log('Event type:', line.substring(7));
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
}

function sendQuery(sessionId) {
  console.log('\nSending query request...');
  
  const request = {
    jsonrpc: '2.0',
    id: 1,
    method: 'tools/call',
    params: {
      name: 'salesforce_query_records',
      arguments: {
        objectName: 'Account',
        fields: ['Id', 'Name', 'Industry'],
        limit: 3
      }
    }
  };
  
  const postData = JSON.stringify(request);
  
  const options = {
    hostname: 'localhost',
    port: 3010,
    path: `/message?sessionId=${sessionId}`,
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(postData)
    }
  };
  
  const req = http.request(options, (res) => {
    console.log('POST response status:', res.statusCode);
    
    let responseData = '';
    res.on('data', (chunk) => {
      responseData += chunk;
    });
    
    res.on('end', () => {
      console.log('POST response:', responseData);
    });
  });
  
  req.on('error', (err) => {
    console.error('POST error:', err);
  });
  
  req.write(postData);
  req.end();
  
  console.log('Query sent:', postData);
}

// Run the test
testSSEClient();

// Keep the process alive
setTimeout(() => {
  console.log('\nTest complete, exiting...');
  process.exit(0);
}, 10000);
