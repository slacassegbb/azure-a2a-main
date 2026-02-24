import { NextRequest, NextResponse } from 'next/server'
import { API_BASE_URL } from '@/lib/api-config'

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const { address } = body

    if (!address) {
      return NextResponse.json(
        { success: false, error: 'Agent address is required' },
        { status: 400 }
      )
    }

    // Forward the request to the backend server
    const backendUrl = API_BASE_URL
    const response = await fetch(`${backendUrl}/agent/register-by-address`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ address }),
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
    console.error('Error in register-agent API route:', error)
    return NextResponse.json(
      { success: false, error: 'Internal server error' },
      { status: 500 }
    )
  }
}
