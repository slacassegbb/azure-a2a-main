import { NextRequest, NextResponse } from 'next/server'

/**
 * GET /api/agents/session/registered?sessionId=xxx
 * Get all agents registered for the current session
 */
export async function GET(request: NextRequest) {
  try {
    const sessionId = request.nextUrl.searchParams.get('sessionId')

    if (!sessionId) {
      return NextResponse.json(
        { success: false, error: 'sessionId is required', agents: [] },
        { status: 400 }
      )
    }

    // Forward the request to the backend server
    const backendUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
    const response = await fetch(`${backendUrl}/agents/session/registered?sessionId=${encodeURIComponent(sessionId)}`)

    const result = await response.json()

    if (response.ok) {
      return NextResponse.json(result)
    } else {
      return NextResponse.json(
        { success: false, error: result.error || 'Failed to fetch session agents', agents: [] },
        { status: response.status }
      )
    }
  } catch (error) {
    console.error('Error in session registered API route:', error)
    return NextResponse.json(
      { success: false, error: 'Internal server error', agents: [] },
      { status: 500 }
    )
  }
}
