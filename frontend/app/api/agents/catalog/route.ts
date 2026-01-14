import { NextRequest, NextResponse } from 'next/server'

/**
 * GET /api/agents/catalog
 * Get all agents from the global catalog (discovery)
 */
export async function GET(request: NextRequest) {
  try {
    // Forward the request to the backend server
    const backendUrl = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
    const response = await fetch(`${backendUrl}/agents/catalog`)

    const result = await response.json()

    if (response.ok) {
      return NextResponse.json(result)
    } else {
      return NextResponse.json(
        { success: false, error: result.error || 'Failed to fetch agent catalog', agents: [] },
        { status: response.status }
      )
    }
  } catch (error) {
    console.error('Error in agent catalog API route:', error)
    return NextResponse.json(
      { success: false, error: 'Internal server error', agents: [] },
      { status: 500 }
    )
  }
}
