import { NextRequest, NextResponse } from 'next/server'

export async function POST(request: NextRequest) {
  try {
    // Get the form data from the frontend
    const formData = await request.formData()
    
    // Get the backend URL from environment or default
    const backendUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
    
    // Forward the request to the Python backend
    const response = await fetch(`${backendUrl}/upload-voice`, {
      method: 'POST',
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
