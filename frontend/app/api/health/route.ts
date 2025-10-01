import { NextRequest, NextResponse } from 'next/server';

export async function GET(request: NextRequest) {
  try {
    // Basic health check
    const healthCheck = {
      status: 'healthy',
      timestamp: new Date().toISOString(),
      uptime: process.uptime(),
      environment: process.env.NODE_ENV,
      version: process.env.npm_package_version || '1.0.0',
      eventHub: {
        configured: !!(process.env.NEXT_PUBLIC_AZURE_EVENTHUB_NAME && 
                      (process.env.NEXT_PUBLIC_AZURE_EVENTHUB_CONNECTION_STRING || 
                       process.env.NEXT_PUBLIC_AZURE_EVENTHUB_NAMESPACE)),
        name: process.env.NEXT_PUBLIC_AZURE_EVENTHUB_NAME || 'not-configured',
        consumerGroup: process.env.NEXT_PUBLIC_AZURE_EVENTHUB_CONSUMER_GROUP || '$Default'
      }
    };

    return NextResponse.json(healthCheck, { status: 200 });
  } catch (error) {
    console.error('Health check failed:', error);
    
    return NextResponse.json(
      { 
        status: 'unhealthy', 
        timestamp: new Date().toISOString(),
        error: error instanceof Error ? error.message : 'Unknown error'
      }, 
      { status: 503 }
    );
  }
}
