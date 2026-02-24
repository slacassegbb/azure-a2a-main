import { NextRequest, NextResponse } from 'next/server'
import { API_BASE_URL } from '@/lib/api-config'

export async function POST(request: NextRequest) {
  try {
    // Get the form data from the frontend
    const formData = await request.formData()
    
    // Get session ID from request header for tenant isolation
    const sessionId = request.headers.get('X-Session-ID')
    
    // Get the backend URL from environment or default
    const backendUrl = API_BASE_URL
    
    // Build headers to forward to backend
    const headers: Record<string, string> = {}
    if (sessionId) {
      headers['X-Session-ID'] = sessionId
    }
    
    // Forward the request to the Python backend
    const response = await fetch(`${backendUrl}/upload-voice`, {
      method: 'POST',
      headers,
      body: formData,
    })

    if (!response.ok) {
      throw new Error(`Backend request failed: ${response.status} ${response.statusText}`)
    }

    const result = await response.json()
    
    return NextResponse.json(result)
  } catch (error) {
    console.error('Voice upload proxy error:', error)
    return NextResponse.json(
      { 
        success: false, 
        error: error instanceof Error ? error.message : 'Voice upload failed' 
      },
      { status: 500 }
    )
  }
}
