import { NextRequest, NextResponse } from 'next/server'

/**
 * POST /api/agents/session/register
 * Register an agent for the current session
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const { sessionId, agentUrl } = body

    if (!sessionId) {
      return NextResponse.json(
        { success: false, error: 'sessionId is required' },
        { status: 400 }
      )
    }

    if (!agentUrl) {
      return NextResponse.json(
        { success: false, error: 'agentUrl is required' },
        { status: 400 }
      )
    }

    // Forward the request to the backend server
    const backendUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
    const response = await fetch(`${backendUrl}/agents/session/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ sessionId, agentUrl }),
    })

    const result = await response.json()

    if (response.ok) {
      return NextResponse.json(result)
    } else {
      return NextResponse.json(
        { success: false, error: result.error || 'Registration failed' },
        { status: response.status }
      )
    }
  } catch (error) {
    console.error('Error in session register API route:', error)
    return NextResponse.json(
      { success: false, error: 'Internal server error' },
      { status: 500 }
    )
  }
}
